"""Unit and loopback integration tests for the v2.5.0 Multi-Channel App-Use RPA Hub."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import WeChatMCPServer, create_http_server  # noqa: E402
from wechat_control.omni_channels import (  # noqa: E402
    CHANNEL_ORDER,
    DingTalkOpenSourceBridge,
    FeishuOpenSourceBridge,
    normalize_channel_id,
    sanitize_public_channel_reply,
    score_lead_intent,
)
from wechat_control.web_console import render_web_console_html  # noqa: E402


class OmniChannelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tdir = Path(self._tmp.name)
        self.engine = WeChatControlEngine(
            auth_file_path=self.tdir / "studio_auth.json",
            bindings_file_path=self.tdir / "bound_contacts.json",
            knowledge_db_path=self.tdir / "kb.sqlite",
            audit_log_path=self.tdir / "audit.jsonl",
            personas_file_path=self.tdir / "personas.json",
            monitor_state_path=self.tdir / "mon.json",
            monitor_events_path=self.tdir / "mon.jsonl",
            snapshots_dir=self.tdir / "snaps",
            reports_dir=self.tdir / "reports",
        )
        self.engine.auth_grant(authorized_by="unit-test")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_channel_aliases_and_native_omni_scan(self) -> None:
        self.assertEqual(normalize_channel_id("lark"), "feishu")
        self.assertEqual(normalize_channel_id("飞书"), "feishu")
        self.assertEqual(normalize_channel_id("xhs"), "xiaohongshu")
        self.assertEqual(normalize_channel_id("抖音"), "douyin")
        self.assertEqual(CHANNEL_ORDER[:4], ("feishu", "dingtalk", "xiaohongshu", "douyin"))

        if self.engine.binary_path.is_file():
            res = self.engine._run_native(["list-app-windows", "--app", "omni"], timeout=10.0)
            self.assertTrue(res.get("ok"), res)
            app_ids = [a.get("appId") for a in res.get("apps") or []]
            for expected in ("wechat", "wecom", "feishu", "dingtalk", "xiaohongshu", "douyin"):
                self.assertIn(expected, app_ids)

    def test_anti_ban_sanitizer_and_lead_scoring(self) -> None:
        raw = "# 标题\n**一站式赋能**！加我微信 abc_123，或者拨打 13800138000 看 https://example.com"
        cleaned = sanitize_public_channel_reply("xiaohongshu", raw, soften=True)
        self.assertTrue(cleaned["modified"])
        self.assertNotIn("**", cleaned["sanitized"])
        self.assertNotIn("13800138000", cleaned["sanitized"])
        self.assertNotIn("https://example.com", cleaned["sanitized"])
        self.assertNotIn("加我微信", cleaned["sanitized"])
        self.assertIn("STRIPPED_MARKDOWN".lower(), cleaned["warnings"])
        self.assertTrue(cleaned["compliant"])

        # Enterprise IM like Feishu preserves rich text & links untouched
        feishu_keep = sanitize_public_channel_reply("feishu", "请看文档 https://example.com **方案报价**")
        self.assertFalse(feishu_keep["modified"])

        tier, score, signals = score_lead_intent("你好，请问私有化部署怎么报价？能发个试用吗？")
        self.assertEqual(tier, "hot")
        self.assertGreaterEqual(score, 70)
        self.assertIn("报价", signals)
        self.assertIn("私有化", signals)

    def test_feishu_and_dingtalk_signed_webhooks_loopback(self) -> None:
        received = []

        class _HookHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                received.append({"path": self.path, "body": body})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if "dingtalk" in self.path:
                    self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')
                else:
                    self.wfile.write(b'{"code":0,"msg":"success"}')

            def log_message(self, *args) -> None:
                return

        srv = HTTPServer(("127.0.0.1", 0), _HookHandler)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            feishu = FeishuOpenSourceBridge()
            f_dry = feishu.send_webhook_text(f"{base}/feishu", "Dry test", secret="sec-f", dry_run=True, timestamp=1700000000)
            self.assertTrue(f_dry["ok"])
            self.assertTrue(f_dry["dryRun"])
            self.assertEqual(received, [])

            f_live = feishu.send_webhook_text(f"{base}/feishu", "Live test", secret="sec-f", dry_run=False, timestamp=1700000000)
            self.assertTrue(f_live["ok"], f_live)
            exp_fsign = base64.b64encode(hmac.new(b"1700000000\nsec-f", b"", hashlib.sha256).digest()).decode()
            self.assertEqual(received[-1]["body"]["sign"], exp_fsign)

            ding = DingTalkOpenSourceBridge()
            d_live = ding.send_webhook_text(f"{base}/dingtalk", "Ding live", secret="sec-d", dry_run=False, timestamp_ms=1700000000123)
            self.assertTrue(d_live["ok"], d_live)
            parsed = urllib.parse.urlparse(received[-1]["path"])
            qs = urllib.parse.parse_qs(parsed.query)
            self.assertEqual(qs["timestamp"][0], "1700000000123")
            exp_dsign = base64.b64encode(hmac.new(b"sec-d", b"1700000000123\nsec-d", hashlib.sha256).digest()).decode()
            self.assertEqual(qs["sign"][0], exp_dsign)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_extract_leads_and_enroll_crm(self) -> None:
        leads_res = self.engine.omni_extract_leads(
            "douyin",
            messages=[
                {"sender": "张总-制造业", "direction": "incoming", "text": "你们这个私有化部署多少钱？我想了解合作报价"},
                {"sender": "路人甲", "direction": "incoming", "text": "路过打卡"},
                {"sender": "我", "direction": "outgoing", "text": "谢谢关注"},
            ],
            sync_crm=True,
        )
        self.assertTrue(leads_res["ok"])
        self.assertEqual(leads_res["hotOrWarmCount"], 1)
        self.assertEqual(leads_res["enrolledCount"], 1)
        self.assertIn("[抖音]张总-制造业", leads_res["enrolledTargets"])

        crm_overview = self.engine.crm_overview(auto_sync=False)
        people = [p["displayName"] for p in crm_overview.get("rankings") or []]
        self.assertIn("[抖音]张总-制造业", people)

    def test_mcp_http_and_web_console_omni_integration(self) -> None:
        # Config update with secret redaction
        cfg_res = self.engine.omni_update_config(
            {"feishu": {"webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/abcdef123456", "webhook_secret": "my-top-secret"}}
        )
        self.assertTrue(cfg_res["ok"])
        self.assertNotIn("my-top-secret", json.dumps(cfg_res))
        self.assertTrue(cfg_res["config"]["feishu"]["webhook_secret_configured"])

        mcp = WeChatMCPServer(self.engine)
        tools_res = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tool_names = {t["name"] for t in tools_res["result"]["tools"]}
        for tname in ("omni_channels_status", "omni_channel_inspect", "omni_channel_send", "omni_channel_leads"):
            self.assertIn(tname, tool_names)

        status_call = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "omni_channels_status", "arguments": {}}})
        payload = json.loads(status_call["result"]["content"][0]["text"])
        self.assertEqual([c["channelId"] for c in payload["channels"]], list(CHANNEL_ORDER))
        self.assertIn("systemAuth", payload)
        self.assertIn("readyCount", payload)
        self.assertIn("actionNeededCount", payload)
        for ch_item in payload["channels"]:
            guide = ch_item.get("authGuide") or {}
            self.assertIn(guide.get("status"), ("ready", "scan_qr", "need_launch", "need_install"))
            self.assertTrue(guide.get("badgeText"))
            self.assertTrue(guide.get("summary"))
            self.assertIsInstance(guide.get("actions"), list)

        ding_guide = self.engine.omni_hub._build_channel_auth_guide(
            "dingtalk",
            {"channelId": "dingtalk", "shortLabel": "钉钉", "installed": False, "desktopRunning": False, "desktopWindowCount": 0, "openProtocol": {}},
            {"webRetiredByVendor": True},
        )
        self.assertEqual(ding_guide["status"], "need_install")

        send_call = mcp.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "omni_channel_send",
                "arguments": {"channel": "feishu", "target": "", "text": "演练验证", "mode": "webhook", "dry_run": True},
            },
        })
        send_payload = json.loads(send_call["result"]["content"][0]["text"])
        self.assertTrue(send_payload["ok"])
        self.assertTrue(send_payload["dryRun"])

        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/api/omni/channels", timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp.status, 200)
                self.assertEqual(len(body["channels"]), 6)

            req = urllib.request.Request(
                f"{base}/api/omni/leads",
                data=json.dumps({
                    "channel": "xiaohongshu",
                    "messages": [{"sender": "小红书买家", "direction": "incoming", "text": "怎么买？求报价和试用"}],
                    "sync_crm": True,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                lbody = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(lbody["enrolledCount"], 1)

            for ch_name, act_type in (("feishu", "auto"), ("dingtalk", "download"), ("xiaohongshu", "ego_login"), ("douyin", "ego_login")):
                auth_req = urllib.request.Request(
                    f"{base}/api/omni/open-auth",
                    data=json.dumps({
                        "channel": ch_name,
                        "action_type": act_type,
                        "target_view": "creator" if ch_name == "douyin" else "home",
                        "dry_run": True,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(auth_req, timeout=10) as resp:
                    abody = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(abody["ok"], abody)
                    self.assertTrue(abody["dryRun"])
                    self.assertEqual(abody["channel"], ch_name)
        finally:
            srv.shutdown()
            srv.server_close()

        html = render_web_console_html()
        self.assertIn("id=\"tab-omni\"", html)
        self.assertIn("data-tab=\"omni\"", html)
        self.assertIn("/api/omni/channels", html)
        self.assertIn("/api/omni/open-auth", html)
        self.assertIn("omniSysAuthStrip", html)
        self.assertIn("omniRunAuthAction", html)
        self.assertNotIn("window.confirm(", html)

        # Auth gate must still fail-closed when revoked
        self.engine.auth_revoke(reason="revoke test")
        with self.assertRaises(Exception):
            self.engine.omni_update_config({"feishu": {"app_id": "cli_test"}})


if __name__ == "__main__":
    unittest.main()
