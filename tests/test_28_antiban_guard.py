"""AntiBanGuard 防封频控：四道闸门 + monitor 限流路径 + 首页弹窗/配额标记。"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.auth_gate import ALL_CAPABILITIES  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import create_http_server  # noqa: E402
from wechat_control.safety import AntiBanGuard  # noqa: E402
from wechat_control.web_console import render_web_console_html  # noqa: E402


def _offline_model_requester(method, url, **kwargs):
    raise ConnectionRefusedError("offline in default unit test setup")


class AntiBanGuardUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _guard(self, **kwargs) -> AntiBanGuard:
        defaults = dict(
            state_path=self.tmp_path / "antiban_state.json",
            per_contact_hourly=2,
            global_hourly=3,
            global_daily=4,
            min_reply_gap_seconds=0,
        )
        defaults.update(kwargs)
        return AntiBanGuard(**defaults)

    def test_contact_hourly_gate(self) -> None:
        guard = self._guard()
        self.assertTrue(guard.check_can_send("心安")[0])
        guard.record_sent("心安")
        self.assertTrue(guard.check_can_send("心安")[0])
        guard.record_sent("心安")
        ok, reason = guard.check_can_send("心安")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("contact_hourly_limit"))

    def test_contact_gap_gate(self) -> None:
        clock = {"t": 1000.0}
        guard = self._guard(min_reply_gap_seconds=90, now_fn=lambda: clock["t"])
        guard.record_sent("心安")
        clock["t"] += 30  # 30 秒后：在 90s 冷却内
        ok, reason = guard.check_can_send("心安")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("contact_gap"))
        clock["t"] += 70  # 100 秒后：冷却已过
        ok, _ = guard.check_can_send("心安")
        self.assertTrue(ok)

    def test_global_hourly_and_daily_gates(self) -> None:
        guard = self._guard(per_contact_hourly=10, min_reply_gap_seconds=0)
        for name in ("甲", "乙", "丙"):
            guard.record_sent(name)
        ok, reason = guard.check_can_send("丁")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("hourly_limit"))

        clock = {"t": 2000.0}
        guard2 = self._guard(global_daily=2, now_fn=lambda: clock["t"])
        guard2.record_sent("甲")
        guard2.record_sent("乙")
        ok, reason = guard2.check_can_send("丙")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("daily_limit"))

    def test_state_persists_across_instances(self) -> None:
        path = self.tmp_path / "antiban_state.json"
        guard = self._guard(state_path=path, per_contact_hourly=1)
        guard.record_sent("心安")
        # 新实例（模拟重启）计数延续
        guard2 = self._guard(state_path=path, per_contact_hourly=1, min_reply_gap_seconds=0)
        ok, reason = guard2.check_can_send("心安")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("contact_hourly_limit"))

    def test_status_shape(self) -> None:
        guard = self._guard()
        st = guard.status()
        for key in ("dailySent", "dailyLimit", "hourlySent", "hourlyLimit", "perContactHourlyLimit", "minReplyGapSeconds"):
            self.assertIn(key, st)


class AntiBanIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.engine = WeChatControlEngine(
            audit_log_path=self.tmp_path / "audit.jsonl",
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
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="unit-test-antiban")

    def tearDown(self) -> None:
        try:
            self.engine.hosting_manager.stop()
        except Exception:
            pass
        self.tmpdir.cleanup()

    def test_engine_assembles_antiban_and_overview_exposes_it(self) -> None:
        self.assertIn("dailyLimit", self.engine.antiban.status())
        # 限流阈值可由环境变量覆盖（防封参数可调）
        self.assertGreater(self.engine.antiban.global_daily, 0)

    def test_llm_gateway_status_probe(self) -> None:
        res = self.engine.llm_gateway_status()
        self.assertTrue(res["ok"])
        for key in ("llmEnabled", "gatewayUrl", "reachable", "note"):
            self.assertIn(key, res)
        # 离线测试环境里网关大概率不可达，但探活必须安全返回布尔而非抛错
        self.assertIsInstance(res["reachable"], bool)
        # overview 暴露 llmGateway
        ov = self.engine.get_web_overview()
        self.assertIn("llmGateway", ov)
        self.assertIn("gatewayUrl", ov["llmGateway"])

    def test_llm_gateway_relaunch_safety(self) -> None:
        res = self.engine.relaunch_llm_gateway()
        self.assertTrue(res["ok"])
        # 网关可达时幂等：alreadyUp，不执行拉起
        if res.get("alreadyUp"):
            self.assertNotIn("relaunched", res)
        # 首页含一键自愈按钮与端点标记
        html = render_web_console_html()
        self.assertIn("llmFixBtn", html)
        self.assertIn("启动 Magpie", html)
        self.assertIn("/api/llm-gateway/relaunch", html)
        self.assertIn("relaunchLlmGateway", html)

    def test_manual_send_event_distinguishes_actor(self) -> None:
        """人工手动发送写 manual_send 事件→回写 source=manual_human；托管回复 source=hosting。"""
        from wechat_control.safety import normalize_chat_name
        self.engine.bind_contact("心安", auto_reply_enabled=True)
        # 托管自动回复事件
        self.engine.monitor._append_event("auto_reply_sent", {
            "target": "心安", "incomingText": "在吗", "replyText": "在的", "careLevel": "normal", "specialCare": False,
        })
        # 人工手动发送事件
        self.engine.monitor._append_event("manual_send", {
            "target": "心安", "replyText": "我本人回复的", "actor": "human",
        })
        res = self.engine.sync_hosting_histories()
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["appended"], 3)
        import glob as _glob
        f = sorted(_glob.glob(str(self.engine.inspector.reports_dir / "contacts" / "心安_*_history.json")),
                   key=lambda p: __import__("os").path.getmtime(p))[-1]
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        sources = {(r["direction"], r["text"], r.get("source")) for r in doc["records"]}
        self.assertIn(("self", "在的", "hosting"), sources)
        self.assertIn(("self", "我本人回复的", "manual_human"), sources)

    def test_homepage_perm_modal_and_antiban_markers(self) -> None:
        html = render_web_console_html()
        # 启动授权弹窗（影刀式）
        self.assertIn("permOverlay", html)
        self.assertIn("需要授权以下权限才能正常使用 WeChat Bot", html)
        self.assertIn("showPermModal", html)
        self.assertIn("x-apple.systempreferences", html)
        # 防封配额展示
        self.assertIn("超限自动暂停", html)
        self.assertIn("防封频控", html)
        # 草稿生成只针对最新来信（上下文框是给人看的）
        self.assertIn("extractLatestPeerMessage", html)

    def test_http_permissions_endpoint(self) -> None:
        self.engine._run_native = lambda args, timeout=15.0: {  # type: ignore[method-assign]
            "ok": True,
            "accessibilityTrusted": True,
            "postEventTrusted": True,
            "screenCaptureTrusted": True,
            "wechatRunning": True,
            "wechatPid": 777,
            "windowCount": 1,
            "windows": [],
        }
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/permissions", timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["ok"])
            self.assertTrue(data["allGranted"])
            self.assertEqual({i["id"] for i in data["items"]}, {"accessibility", "post_event", "screen_capture"})
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
