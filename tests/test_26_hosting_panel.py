"""首页「一键托管好友」：批量托管端点 + HostingManager 生命周期 + 首页面板标记。"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.auth_gate import (  # noqa: E402
    ALL_CAPABILITIES,
    READ_ONLY_CAPABILITIES,
    StudioPluginUnauthorizedError,
)
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import create_http_server  # noqa: E402
from wechat_control.web_console import render_web_console_html  # noqa: E402


def _offline_model_requester(method, url, **kwargs):
    raise ConnectionRefusedError("offline in default unit test setup")


class HostingPanelTestSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.audit_log = self.tmp_path / "audit.jsonl"
        self.engine = WeChatControlEngine(
            audit_log_path=self.audit_log,
            auth_file_path=self.tmp_path / "studio_auth.json",
            bindings_file_path=self.tmp_path / "bound_contacts.json",
            models_config_path=self.tmp_path / "model_providers.json",
            model_http_requester=_offline_model_requester,
            knowledge_db_path=self.tmp_path / "kb.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.tmp_path / "reports",
            dedup_window_seconds=120.0,
            allowed_groups=["VIP客户群", "测试私域运营群"],
        )
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="unit-test-hosting")
        self.engine._run_native = lambda args, timeout=15.0: {  # type: ignore[method-assign]
            "ok": True,
            "accessibilityTrusted": True,
            "postEventTrusted": True,
            "screenCaptureTrusted": True,
            "wechatRunning": True,
            "wechatPid": 12345,
            "windowCount": 1,
            "windows": [{"windowID": 1, "bounds": {"x": 0, "y": 0, "width": 585, "height": 640}}],
            "activeChat": {"title": "测试好友甲"},
        }

    def tearDown(self) -> None:
        try:
            self.engine.hosting_manager.stop()
        except Exception:
            pass
        self.tmpdir.cleanup()

    # 1. 一键托管：为勾选好友确保绑定 + autoReplyEnabled，并启动托管循环
    def test_hosting_enable_creates_bindings_and_starts_loop(self) -> None:
        res = self.engine.start_hosting(["测试好友甲", "测试好友乙"])
        self.assertTrue(res["ok"])
        self.assertEqual(sorted(res["applied"]), ["测试好友乙", "测试好友甲"])
        status = res
        self.assertTrue(status.get("running") or status.get("enabled"))
        self.assertEqual(status.get("sendMode"), "confirm_send")

        for target in ("测试好友甲", "测试好友乙"):
            binding = self.engine.bindings.get_binding(target)
            self.assertIsNotNone(binding)
            self.assertTrue(binding["autoReplyEnabled"])

        self.assertTrue(self.engine.hosting_manager.status()["running"])
        stop_res = self.engine.stop_hosting()
        self.assertTrue(stop_res["ok"])
        self.assertFalse(self.engine.hosting_manager.status()["running"])
        # 默认 stop 不改编录：绑定仍在、自动回复仍开启
        binding = self.engine.bindings.get_binding("测试好友甲")
        self.assertTrue(binding["autoReplyEnabled"])

    # 2. 停止托管可顺带关闭所选好友的自动回复
    def test_hosting_disable_disables_replies(self) -> None:
        self.engine.start_hosting(["测试好友甲"])
        res = self.engine.stop_hosting(targets=["测试好友甲"], disable_replies=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["disabledReplies"], ["测试好友甲"])
        binding = self.engine.bindings.get_binding("测试好友甲")
        self.assertIsNotNone(binding)
        self.assertFalse(binding["autoReplyEnabled"])
        self.assertFalse(self.engine.hosting_manager.status()["running"])

    # 3. 边界：空目标拒绝；未授权 send_text_live 时 fail-closed
    def test_hosting_requires_targets_and_live_capability(self) -> None:
        res = self.engine.start_hosting([])
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "HOSTING_TARGETS_REQUIRED")

        readonly = WeChatControlEngine(
            audit_log_path=self.tmp_path / "ro_audit.jsonl",
            auth_file_path=self.tmp_path / "ro_studio_auth.json",
            bindings_file_path=self.tmp_path / "ro_bound_contacts.json",
            models_config_path=self.tmp_path / "ro_model_providers.json",
            model_http_requester=_offline_model_requester,
            knowledge_db_path=self.tmp_path / "ro_kb.sqlite",
            personas_file_path=self.tmp_path / "ro_personas.json",
            snapshots_dir=self.tmp_path / "ro_snapshots",
            reports_dir=self.tmp_path / "ro_reports",
        )
        readonly.auth_grant(READ_ONLY_CAPABILITIES, authorized_by="unit-test-readonly")
        with self.assertRaises(StudioPluginUnauthorizedError):
            readonly.start_hosting(["测试好友甲"])

    # 4. merge 语义：重复托管保留旧字段（alias/careLevel 不被冲掉）
    def test_hosting_merge_preserves_existing_fields(self) -> None:
        self.engine.bind_contact("测试好友甲", alias="老王", care_level="vip")
        self.engine.start_hosting(["测试好友甲"])
        binding = self.engine.bindings.get_binding("测试好友甲")
        self.assertEqual(binding["alias"], "老王")
        self.assertEqual(binding["careLevel"], "vip")
        self.assertTrue(binding["autoReplyEnabled"])

    # 5. 好友清单：含已绑定无画像样本的联系人 + takenOver 状态
    def test_hosting_friends_lists_bindings_and_takeover(self) -> None:
        self.engine.bind_contact("测试好友甲", alias="老王", auto_reply_enabled=True)
        res = self.engine.hosting_friends()
        self.assertTrue(res["ok"])
        by_target = {f["target"]: f for f in res["friends"]}
        self.assertIn("测试好友甲", by_target)
        friend = by_target["测试好友甲"]
        self.assertTrue(friend["bound"])
        self.assertTrue(friend["autoReplyEnabled"])
        self.assertEqual(friend["matchedTitle"], "老王")

        self.engine.monitor.takeover_contact("测试好友甲", reason="unit-test")
        res2 = self.engine.hosting_friends()
        friend2 = {f["target"]: f for f in res2["friends"]}["测试好友甲"]
        self.assertTrue(friend2["takenOver"])

    # 6. HTTP 端点：GET /api/hosting + POST enable/disable + 首页含托管面板
    def test_hosting_http_endpoints_and_homepage_markers(self) -> None:
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"

        def _req(path: str, payload: dict | None = None):
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Content-Type": "application/json"} if data is not None else {}
            req = urllib.request.Request(base + path, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as err:
                return err.code, err.read()

        try:
            st, raw = _req("/")
            self.assertEqual(st, 200)
            html = raw.decode("utf-8")
            self.assertIn("一键托管", html)
            self.assertIn("hosting-panel", html)
            self.assertIn("/api/hosting", html)
            self.assertIn("applyHosting", html)

            st, raw = _req("/api/hosting")
            self.assertEqual(st, 200)
            doc = json.loads(raw.decode("utf-8"))
            self.assertTrue(doc["ok"])
            self.assertIn("hosting", doc)
            self.assertIn("friends", doc)

            st, raw = _req("/api/hosting", {"action": "enable", "targets": ["测试好友甲"]})
            self.assertEqual(st, 200)
            doc = json.loads(raw.decode("utf-8"))
            self.assertTrue(doc["ok"])
            self.assertEqual(doc["applied"], ["测试好友甲"])
            self.assertTrue(self.engine.bindings.get_binding("测试好友甲")["autoReplyEnabled"])

            st, raw = _req("/api/hosting", {"action": "disable", "targets": ["测试好友甲"], "disable_replies": True})
            self.assertEqual(st, 200)
            self.assertFalse(self.engine.bindings.get_binding("测试好友甲")["autoReplyEnabled"])

            st, raw = _req("/api/hosting", {"action": "nope", "targets": []})
            self.assertEqual(st, 400)
            self.assertFalse(json.loads(raw.decode("utf-8"))["ok"])
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
