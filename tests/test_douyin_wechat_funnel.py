"""Unit and integration tests for the Douyin -> WeChat lead acquisition & add-friend loop."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.douyin_wechat_bridge import (  # noqa: E402
    classify_wechat_add_lookup_ocr,
    compose_douyin_lead_reply,
    extract_wechat_accounts_from_messages,
    extract_wechat_accounts_from_text,
    sanitize_douyin_dm_reply,
    validate_wechat_account,
)
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import WeChatMCPServer, create_http_server  # noqa: E402
from wechat_control.omni_channels import sanitize_public_channel_reply  # noqa: E402
from wechat_control.web_console import render_web_console_html  # noqa: E402


class DouyinWeChatFunnelTests(unittest.TestCase):
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

    def test_extract_wechat_accounts_variants_and_rejections(self) -> None:
        positive_cases = [
            ("微信号: zhangsan_88", "zhangsan_88", "wechat_id"),
            ("vx：li_si2026", "li_si2026", "wechat_id"),
            ("v信是 wxid_abc12345", "wxid_abc12345", "wechat_id"),
            ("➕v wangwu_99", "wangwu_99", "wechat_id"),
            ("威信：chen_007", "chen_007", "wechat_id"),
            ("w x: zhao_2025", "zhao_2025", "wechat_id"),
            ("ＶＸ：ａｂｃ＿１２３", "abc_123", "wechat_id"),
            ("加微：lin_vip99", "lin_vip99", "wechat_id"),
            ("我的手机号 138 1234 5678", "13812345678", "phone"),
            ("电话：139-8765-4321", "13987654321", "phone"),
            ("１３６１１１１２２２２", "13611112222", "phone"),
            ("加我微信 13700009999", "13700009999", "phone"),
        ]
        for text, expected_acc, expected_type in positive_cases:
            res = extract_wechat_accounts_from_text(text)
            self.assertTrue(res, f"Failed to extract from: {text!r}")
            self.assertEqual(res[0]["account"], expected_acc, text)
            self.assertEqual(res[0]["accountType"], expected_type, text)
            self.assertEqual(res[0]["confidence"], "high", text)

        # Bare contextual ID after outgoing ask-wechat message
        thread = [
            {"sender": "我", "direction": "outgoing", "text": "方便留个微信号吗，这边加你发报价单"},
            {"sender": "张总", "direction": "incoming", "text": "vip_client99"},
        ]
        res_thread = extract_wechat_accounts_from_messages(thread, douyin_user="张总")
        self.assertEqual(len(res_thread), 1)
        self.assertEqual(res_thread[0]["account"], "vip_client99")
        self.assertEqual(res_thread[0]["confidence"], "medium")
        self.assertEqual(res_thread[0]["douyinUser"], "张总")

        # False positives must be rejected, and outgoing messages ignored
        negatives = [
            "hello thanks for sharing",
            "visit https://github.com/openbot_123 or user123@example.com",
            "订单号 1234567890123456 已发货",
            "2026-11-28 iphone android douyin wechat",
        ]
        for bad in negatives:
            self.assertEqual(extract_wechat_accounts_from_text(bad, context_allows_bare=True), [], bad)

        outgoing_only = [
            {"sender": "我", "direction": "outgoing", "text": "加我微信 my_own_wx888"},
            {"sender": "访客", "direction": "incoming", "text": "好的"},
        ]
        self.assertEqual(extract_wechat_accounts_from_messages(outgoing_only), [])

    def test_douyin_dm_vs_comment_sanitizer_and_composer(self) -> None:
        # DM allows soft ask for customer's WeChat while blocking self-promo & URLs
        dm_soft = sanitize_public_channel_reply(
            "douyin",
            "你好，方便发一下你的微信号吗？这边加你发资料",
            surface="dm",
        )
        self.assertTrue(dm_soft["compliant"])
        self.assertIn("微信号", dm_soft["sanitized"])

        dm_dirty = sanitize_douyin_dm_reply(
            "**一站式赋能**！加我微信 my_wx_123 或拨打 13800138000 看 https://example.com"
        )
        self.assertTrue(dm_dirty["modified"])
        self.assertNotIn("my_wx_123", dm_dirty["sanitized"])
        self.assertNotIn("13800138000", dm_dirty["sanitized"])
        self.assertNotIn("https://example.com", dm_dirty["sanitized"])
        self.assertNotIn("**", dm_dirty["sanitized"])
        self.assertTrue(dm_dirty["compliant"])

        # Public comment mode stays strict as before
        comment_strict = sanitize_public_channel_reply("douyin", "加我微信 abc_123")
        self.assertNotIn("abc_123", comment_strict["sanitized"])

        composed = compose_douyin_lead_reply("请问怎么报价？", stage="ask_wechat")
        self.assertTrue(composed["compliance"]["compliant"])
        self.assertIn("微信", composed["text"])

    def test_classify_wechat_add_lookup_ocr_states(self) -> None:
        c1 = classify_wechat_add_lookup_ocr(
            ["微信号：test_wx99", "添加到通讯录"],
            [{"text": "添加到通讯录", "center": {"x": 180, "y": 320}}],
        )
        self.assertEqual(c1["status"], "candidate_found")
        self.assertEqual(c1["actionPoint"], {"x": 180.0, "y": 320.0})

        c2 = classify_wechat_add_lookup_ocr(["微信号：friend_1", "发消息", "音视频通话"])
        self.assertEqual(c2["status"], "already_friend")

        c3 = classify_wechat_add_lookup_ocr(["该用户不存在"])
        self.assertEqual(c3["status"], "not_found")

        c4 = classify_wechat_add_lookup_ocr(["操作过于频繁，请稍后再试"])
        self.assertEqual(c4["status"], "rate_limited")

        c5 = classify_wechat_add_lookup_ocr(["搜索"])
        self.assertEqual(c5["status"], "unknown")

    def test_wechat_friend_adder_guards_and_mocked_native_flow(self) -> None:
        ok, norm, t = validate_wechat_account("138 0013 8000")
        self.assertTrue(ok)
        self.assertEqual((norm, t), ("13800138000", "phone"))

        bad = self.engine.wechat_add_friend("12", dry_run=True)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error_code"], "invalid_wechat_account")

        dry = self.engine.wechat_add_friend("wxid_demo1234", greeting="你好", remark="[抖音]测试", dry_run=True)
        self.assertTrue(dry["ok"])
        self.assertTrue(dry["dryRun"])
        self.assertFalse(dry["sent"])
        self.assertEqual(dry["status"], "dry_run_ready")

        # Mocked live add-friend UI sequence
        seen_cmds: List[List[str]] = []

        def fake_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            seen_cmds.append(list(args))
            cmd = args[0]
            if cmd == "status":
                has_add = any(c[0] == "click" and float(c[2]) == 1443.0 for c in seen_cmds)
                wins: List[Dict[str, Any]] = [
                    {"title": "微信", "isMainWindow": True, "bounds": {"x": 980, "y": 31, "width": 1579, "height": 1320}}
                ]
                if has_add and not any(c[0] == "press-key" for c in seen_cmds):
                    wins.append({"title": "添加朋友", "isMainWindow": False, "bounds": {"x": 1099, "y": 411, "width": 360, "height": 560}})
                return {"ok": True, "windows": wins}
            if cmd == "activate":
                return {"ok": True}
            if cmd == "capture-ocr":
                if "--window-title" in args:
                    paste_done = any(c[0] == "app-use-paste" and "--submit" in c for c in seen_cmds)
                    add_clicked = any(c[0] == "click" and float(c[4]) == 731.0 for c in seen_cmds)
                    if add_clicked:
                        return {
                            "ok": True,
                            "elements": [
                                {"text": "发送添加朋友申请", "center": {"x": 100, "y": 90}},
                                {"text": "设置备注", "center": {"x": 100, "y": 210}},
                                {"text": "确定", "center": {"x": 250, "y": 500}},
                            ],
                        }
                    if paste_done:
                        return {
                            "ok": True,
                            "elements": [
                                {"text": "微信号：mock_wx88", "center": {"x": 160, "y": 190}},
                                {"text": "添加到通讯录", "center": {"x": 180, "y": 320}},
                            ],
                        }
                    return {
                        "ok": True,
                        "elements": [{"text": "Q 搜索微信号或者手机号", "center": {"x": 117, "y": 69}}],
                    }
                return {
                    "ok": True,
                    "imageWidth": 1579,
                    "imageHeight": 1320,
                    "elements": [{"text": "openbot", "bbox": {"x": 503, "y": 20}, "center": {"x": 545, "y": 28}}],
                }
            if cmd == "capture-region":
                return {
                    "ok": True,
                    "elements": [{"text": "2 添加朋友", "screenCenter": {"x": 1443, "y": 135}, "center": {"x": 93, "y": 85}}],
                }
            if cmd in ("click", "app-use-paste", "press-key"):
                return {"ok": True}
            return {"ok": True}

        from wechat_control.douyin_wechat_bridge import compose_friend_greeting

        g1 = compose_friend_greeting(
            "你好呀，我是{businessName}的{ownerName}，刚在抖音看到你发来的消息，这边加你微信详聊～",
            business_name="智拓巨浪",
            owner_name="安晓心",
        )
        self.assertIn("智拓巨浪", g1)
        self.assertIn("安晓心", g1)
        self.assertNotIn("{", g1)

        g2 = compose_friend_greeting("", business_name="智拓巨浪")
        self.assertIn("智拓巨浪", g2)

        with (
            patch.object(self.engine, "_run_native", side_effect=fake_native),
            patch.object(self.engine, "_check_human_guard_for_action", return_value=None),
            patch.object(self.engine.douyin_funnel.adder, "_sleep_paced", return_value=None),
            patch("wechat_control.douyin_wechat_bridge.time.sleep", return_value=None),
        ):
            ingest = self.engine.douyin_funnel_ingest(
                [{"sender": "刘总", "direction": "incoming", "text": "我的微信是 mock_wx88"}],
                douyin_user="刘总",
            )
            self.assertEqual(ingest["capturedCount"], 1)
            # Default safe grant without send_text_live must reject live friend request
            with self.assertRaises(Exception):
                self.engine.douyin_funnel_add_wechat("刘总", dry_run=False, confirm_send=True, ignore_human_guard=True)

            self.engine.auth_grant(["*"], authorized_by="unit-test-live")
            live_res = self.engine.douyin_funnel_add_wechat(
                "刘总",
                dry_run=False,
                confirm_send=True,
                ignore_human_guard=True,
            )
            self.assertTrue(live_res["ok"], live_res)
            self.assertTrue(live_res["sent"])
            self.assertEqual(live_res["status"], "wechat_friend_requested")
            self.assertEqual(live_res["remark"], "抖音引流-刘总")

            # Direct add_friend call also builds CRM & memory profile
            seen_cmds.clear()
            direct_res = self.engine.wechat_add_friend(
                "13900008888",
                greeting="你好呀，我是智拓巨浪的安晓心，这边加你微信详聊～",
                remark="抖音引流-测试直加",
                source_user="测试直加",
                dry_run=False,
                confirm_send=True,
                force=True,
                ignore_human_guard=True,
            )
            self.assertTrue(direct_res["ok"], direct_res)
            self.assertTrue(direct_res["sent"])
            crm_after_direct = self.engine.crm_overview(auto_sync=False)
            direct_names = [p["displayName"] for p in crm_after_direct.get("rankings") or []]
            self.assertIn("抖音引流-测试直加", direct_names)
            direct_rec = next(p for p in crm_after_direct["rankings"] if p["displayName"] == "抖音引流-测试直加")
            self.assertIn("抖音获客", direct_rec.get("tags") or [])

        # Dedup guard blocks duplicate add without force=True
        dup_blocked = self.engine.douyin_funnel_add_wechat("刘总", dry_run=True)
        self.assertFalse(dup_blocked["ok"])
        self.assertEqual(dup_blocked["error_code"], "already_requested_or_friend")

        # Cooldown guard blocks immediate second account
        self.engine.douyin_funnel._state["lastWechatAddAt"] = time.time()
        cd_blocked = self.engine.wechat_add_friend("another_wx99", dry_run=True)
        self.assertFalse(cd_blocked["ok"])
        self.assertEqual(cd_blocked["error_code"], "cooldown_active")

        # Daily limit guard blocks when quota exhausted
        self.engine.douyin_funnel_update_config({"dailyAddLimit": 1, "addCooldownSeconds": 0})
        limit_blocked = self.engine.wechat_add_friend("another_wx99", dry_run=True)
        self.assertFalse(limit_blocked["ok"])
        self.assertEqual(limit_blocked["error_code"], "daily_limit_reached")

    def test_funnel_cycle_crm_mcp_http_and_console(self) -> None:
        mocked_read = {
            "ok": True,
            "channel": "douyin",
            "source": "desktop_rpa",
            "loginRequired": False,
            "currentChatTitle": "陈先生",
            "sessions": [{"title": "陈先生", "preview": "我微信号是 chen_boss88"}],
            "messages": [
                {"sender": "陈先生", "direction": "incoming", "text": "你好，私有化部署怎么报价？我微信号是 chen_boss88"},
                {"sender": "王小姐", "direction": "incoming", "text": "想了解一下产品功能"},
            ],
        }
        with patch.object(self.engine, "omni_read_messages", return_value=mocked_read):
            cyc = self.engine.douyin_funnel_run_cycle(
                auto_reply=True,
                auto_add_wechat=True,
                dry_run=True,
            )
        self.assertTrue(cyc["ok"])
        self.assertEqual(cyc["ingest"]["capturedCount"], 1)
        self.assertTrue(len(cyc["replyActions"]) >= 1)
        self.assertEqual(cyc["addActions"][0]["account"], "chen_boss88")
        self.assertEqual(cyc["addActions"][0]["remark"], "抖音引流-陈先生")

        # Verify SalesCRM enrolled the lead with Douyin source tags & WeChat account note
        crm = self.engine.crm_overview(auto_sync=False)
        rankings = crm.get("rankings") or []
        names = [p["displayName"] for p in rankings]
        self.assertIn("抖音引流-陈先生", names)
        chen = next(p for p in rankings if p["displayName"] == "抖音引流-陈先生")
        self.assertIn("抖音获客", chen.get("tags") or [])
        self.assertIn("抖音引流", chen.get("tags") or [])
        ov_direct = self.engine.douyin_funnel_overview()
        self.assertEqual(len((ov_direct.get("sopWorkflow") or {}).get("steps") or []), 5)

        # MCP tools
        mcp = WeChatMCPServer(self.engine)
        tools_res = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tool_names = {t["name"] for t in tools_res["result"]["tools"]}
        for tname in ("wechat_add_friend", "douyin_wechat_funnel_status", "douyin_wechat_funnel_run", "douyin_wechat_add_lead"):
            self.assertIn(tname, tool_names)

        st_call = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "douyin_wechat_funnel_status", "arguments": {}}})
        st_payload = json.loads(st_call["result"]["content"][0]["text"])
        self.assertTrue(st_payload["ok"])
        self.assertGreaterEqual(st_payload["counts"]["wechatCaptured"], 1)

        add_call = mcp.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "wechat_add_friend", "arguments": {"account": "mcp_test88", "dry_run": True}},
        })
        add_payload = json.loads(add_call["result"]["content"][0]["text"])
        self.assertTrue(add_payload["ok"])
        self.assertTrue(add_payload["dryRun"])

        # HTTP loopback checks
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/api/douyin-funnel/overview", timeout=10) as resp:
                ov = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp.status, 200)
                self.assertTrue(ov["ok"])

            req_add = urllib.request.Request(
                f"{base}/api/wechat/add-friend",
                data=json.dumps({"account": "http_wx99", "dry_run": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_add, timeout=10) as resp:
                add_http = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(add_http["ok"])
                self.assertTrue(add_http["dryRun"])
        finally:
            srv.shutdown()
            srv.server_close()

        # Web Console assertions (must remain free of window.confirm)
        html = render_web_console_html()
        self.assertIn("douyinFunnelRunCycle", html)
        self.assertIn("wechatQuickAddFriend", html)
        self.assertIn("/api/douyin-funnel/overview", html)
        self.assertIn("/api/wechat/add-friend", html)
        self.assertNotIn("window.confirm(", html)

        # Auth gate must fail closed when revoked
        self.engine.auth_revoke(reason="revoke test")
        with self.assertRaises(Exception):
            self.engine.wechat_add_friend("revoked_wx99", dry_run=True)

    def test_legacy_config_migration_and_already_friend_remark(self) -> None:
        from wechat_control.douyin_wechat_bridge import DouyinWeChatFunnel

        state_path = self.tdir / "legacy_funnel.json"
        state_path.write_text(
            json.dumps(
                {
                    "schema": "openbot.douyin-wechat-funnel/1",
                    "config": {
                        "wechatRemarkPrefix": "[抖音]",
                        "wechatGreetingTemplate": "你好，刚在抖音看到你咨询，加个微信发你详细资料",
                    },
                    "leads": {},
                    "events": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        funnel = DouyinWeChatFunnel(self.engine, state_path=state_path)
        cfg = funnel._state["config"]
        self.assertEqual(cfg["wechatRemarkPrefix"], "抖音引流-")
        self.assertIn("{businessName}", cfg["wechatGreetingTemplate"])

        # Mocked native flow for already_friend setting remark & CRM record
        remark_pasted: List[str] = []
        seen_cmds_already: List[List[str]] = []

        def fake_native_already(args: List[str], timeout: float = 10.0) -> Dict[str, Any]:
            seen_cmds_already.append(list(args))
            cmd = args[0]
            if cmd == "status":
                has_add = any(c[0] == "click" and float(c[2]) == 1443.0 for c in seen_cmds_already)
                wins: List[Dict[str, Any]] = [
                    {"title": "微信", "isMainWindow": True, "bounds": {"x": 980, "y": 31, "width": 1579, "height": 1320}}
                ]
                if has_add and not any(c[0] == "press-key" for c in seen_cmds_already):
                    wins.append(
                        {"title": "添加朋友", "isMainWindow": False, "bounds": {"x": 100, "y": 100, "width": 360, "height": 560}}
                    )
                return {"ok": True, "windows": wins}
            if cmd == "capture-region":
                return {
                    "ok": True,
                    "elements": [{"text": "2 添加朋友", "screenCenter": {"x": 1443, "y": 135}, "center": {"x": 93, "y": 85}}],
                }
            if cmd == "capture-ocr":
                if "--window-title" not in args:
                    return {
                        "ok": True,
                        "imageWidth": 1579,
                        "imageHeight": 1320,
                        "elements": [{"text": "openbot", "bbox": {"x": 503, "y": 20}, "center": {"x": 545, "y": 28}}],
                    }
                out_path = args[args.index("--out") + 1] if "--out" in args else ""
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                Path(out_path).write_bytes(b"fake-png")
                paste_done = any(c[0] == "app-use-paste" and "--submit" in c for c in seen_cmds_already)
                if "remark_set" in out_path:
                    return {
                        "ok": True,
                        "imageWidth": 360,
                        "imageHeight": 560,
                        "elements": [
                            {"text": "心安", "center": {"x": 150, "y": 110}},
                            {"text": "备注", "center": {"x": 60, "y": 190}},
                            {"text": "抖音引流-wavewave", "center": {"x": 180, "y": 190}},
                            {"text": "发消息", "center": {"x": 180, "y": 300}},
                        ],
                    }
                if paste_done:
                    return {
                        "ok": True,
                        "imageWidth": 360,
                        "imageHeight": 560,
                        "elements": [
                            {"text": "心安", "center": {"x": 150, "y": 110}},
                            {"text": "添加备注名", "center": {"x": 180, "y": 190}},
                            {"text": "发消息", "center": {"x": 180, "y": 300}},
                        ],
                    }
                return {
                    "ok": True,
                    "imageWidth": 360,
                    "imageHeight": 560,
                    "elements": [{"text": "Q 搜索微信号或者手机号", "center": {"x": 117, "y": 69}}],
                }
            if cmd == "app-use-paste":
                txt = args[args.index("--text") + 1] if "--text" in args else ""
                remark_pasted.append(txt)
                return {"ok": True}
            return {"ok": True}

        self.engine.auth_grant(["*"], authorized_by="unit-test-live")
        self.engine.douyin_funnel.adder.verify_dir = self.tdir / "verify"
        with (
            patch.object(self.engine, "_run_native", side_effect=fake_native_already),
            patch.object(self.engine, "_check_human_guard_for_action", return_value=None),
            patch.object(self.engine.douyin_funnel.adder, "_sleep_paced", return_value=None),
            patch("wechat_control.douyin_wechat_bridge.time.sleep", return_value=None),
        ):
            res = self.engine.wechat_add_friend(
                "18733111944",
                greeting="你好呀，我是智拓巨浪的安晓心，刚在抖音看到你发来的消息，这边加你微信详聊～",
                remark="抖音引流-wavewave",
                source_channel="douyin",
                source_user="wavewave",
                dry_run=False,
                confirm_send=True,
                force=True,
            )

        self.assertTrue(res["ok"], res)
        self.assertEqual(res["status"], "already_friend")
        self.assertTrue(res["remarkUpdated"])
        self.assertEqual(res["remark"], "抖音引流-wavewave")
        self.assertIn("抖音引流-wavewave", remark_pasted)

        crm = self.engine.crm_overview(auto_sync=False)
        rankings = crm.get("rankings") or []
        wave = next((p for p in rankings if p["displayName"] == "抖音引流-wavewave"), None)
        self.assertIsNotNone(wave)
        self.assertIn("抖音获客", wave.get("tags") or [])
        self.assertIn("抖音引流", wave.get("tags") or [])


if __name__ == "__main__":
    unittest.main()
