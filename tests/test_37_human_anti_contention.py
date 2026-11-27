"""Comprehensive tests for 5-layer human-priority anti-contention (mouse/keyboard/focus yield)."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Any, Dict, List

from wechat_control import ALL_CAPABILITIES
from wechat_control.engine import WeChatControlEngine
from wechat_control.human_activity_guard import HumanActivityGuard


def _write_solid_png(path: Path, width: int = 720, height: int = 860) -> None:
    raw = b"".join(b"\x00" + (b"\xf5\xf5\xf5" * width) for _ in range(height))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


class TestHumanAntiContention(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wx_anticontend_"))
        self.clock = {"now": 10000.0}
        self.hid_state: Dict[str, Any] = {
            "anyInputIdleSeconds": 90.0,
            "mouseIdleSeconds": 90.0,
            "hardwareMouseIdleSeconds": 90.0,
            "keyboardIdleSeconds": 90.0,
            "hardwareKeyboardIdleSeconds": 90.0,
            "scrollIdleSeconds": 90.0,
            "keyboardActive": False,
            "cursorPosition": {"x": 500.0, "y": 500.0},
        }
        self.engine = WeChatControlEngine(
            audit_log_path=self.tmp / "audit.jsonl",
            auth_file_path=self.tmp / "auth.json",
            bindings_file_path=self.tmp / "bindings.json",
            models_config_path=self.tmp / "models.json",
            model_http_requester=lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError),
            knowledge_db_path=self.tmp / "kb.sqlite",
            personas_file_path=self.tmp / "personas.json",
            snapshots_dir=self.tmp / "snapshots",
            reports_dir=self.tmp / "reports",
        )
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="test-anticontention")
        self.engine.human_guard = HumanActivityGuard(
            state_path=self.tmp / "human_guard_state.json",
            hid_query_fn=lambda: dict(self.hid_state),
            clock_fn=lambda: self.clock["now"],
            default_idle_resume_seconds=20.0,
            default_cooldown_seconds=25.0,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1_sandbox_target_no_longer_bypasses_human_guard(self) -> None:
        """微信ClawBot 等沙盒目标在用户动鼠标/键盘时也必须立刻暂停让路，禁止 2026-11-19 类越过守卫强发。"""
        self.engine.bind_contact("微信ClawBot", role="ai_bot", auto_reply_enabled=True)
        native_calls: List[List[str]] = []

        def fake_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            native_calls.append(list(args))
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        # User moves mouse -> mouseIdle=0.2s, keyboard still idle=90s (this exact case bypassed before!)
        self.hid_state.update({
            "anyInputIdleSeconds": 0.2,
            "mouseIdleSeconds": 0.2,
            "hardwareMouseIdleSeconds": 0.2,
            "keyboardIdleSeconds": 90.0,
            "hardwareKeyboardIdleSeconds": 90.0,
            "cursorPosition": {"x": 850.0, "y": 500.0},
        })
        poll_res = self.engine.monitor.poll_once(target_filter="微信ClawBot", auto_reply=True, confirm_send=True)
        self.assertTrue(poll_res.get("pausedByHumanGuard"))
        self.assertEqual(poll_res.get("repliesDispatched"), 0)
        self.assertEqual(native_calls, [])

    def test_2_mid_think_human_interruption_blocks_post_llm_send(self) -> None:
        """LLM 思考期间用户突然动鼠标或按键：思考返回后发送前复检必须立刻拦截、保存 interruptedSend 并中止。"""
        self.engine.bind_contact("微信ClawBot", role="ai_bot", auto_reply_enabled=True)
        self.engine.bind_contact("第二位好友", role="friend", auto_reply_enabled=True)
        native_cmds: List[str] = []

        def fake_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            cmd = args[0] if args else ""
            native_cmds.append(cmd)
            if cmd == "list-app-windows":
                return {
                    "ok": True,
                    "windows": [
                        {"windowID": 3001, "title": "微信ClawBot", "isMainWindow": False, "bounds": {"x": 100, "y": 100, "width": 700, "height": 800}},
                        {"windowID": 3002, "title": "第二位好友", "isMainWindow": False, "bounds": {"x": 820, "y": 100, "width": 700, "height": 800}},
                    ],
                }
            if cmd == "capture-ocr":
                out_path = Path(args[args.index("--out") + 1])
                _write_solid_png(out_path, 700, 800)
                return {
                    "ok": True,
                    "isMainWindow": False,
                    "splitX": 0.0,
                    "windowTitle": "微信ClawBot",
                    "windowBounds": {"x": 100, "y": 100, "width": 700, "height": 800},
                    "elements": [
                        {"text": "微信ClawBot", "bbox": {"x": 20, "y": 30, "width": 100, "height": 18}, "center": {"x": 70, "y": 39}},
                        {"text": "06:50", "bbox": {"x": 320, "y": 160, "width": 45, "height": 12}, "center": {"x": 342, "y": 166}},
                        {"text": "请帮我查下今天日程", "bbox": {"x": 50, "y": 230, "width": 220, "height": 22}, "center": {"x": 160, "y": 241}},
                    ],
                }
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]

        def fake_think(target: str, incoming_text: str, **kwargs: Any) -> Dict[str, Any]:
            # Simulate human moving the cursor during LLM think time!
            self.clock["now"] += 2.0
            self.hid_state.update({
                "anyInputIdleSeconds": 0.1,
                "mouseIdleSeconds": 0.1,
                "hardwareMouseIdleSeconds": 0.1,
                "cursorPosition": {"x": 1200.0, "y": 700.0},
            })
            return {
                "ok": True,
                "replyText": "这是思考完成后的回复",
                "persona": {"id": "warm-companion", "name": "Warm"},
                "basis": "test",
            }

        self.engine.personas.generate_smart_reply = fake_think  # type: ignore[method-assign]
        res = self.engine.monitor.poll_once(auto_reply=True, confirm_send=True)
        self.assertTrue(res.get("pausedByHumanGuard"))
        self.assertEqual(res.get("repliesDispatched"), 0)
        self.assertNotIn("paste-and-verify", native_cmds)
        mon_state = json.loads(self.engine.monitor.state_path.read_text(encoding="utf-8"))
        c_state = mon_state["contacts"].get("微信clawbot") or mon_state["contacts"].get("微信ClawBot")
        self.assertIsNotNone(c_state)
        self.assertIsInstance(c_state.get("interruptedSend"), dict)
        self.assertEqual(c_state["interruptedSend"]["replyText"], "这是思考完成后的回复")

    def test_3_capture_wechat_ocr_uses_no_activate_and_refuses_stealing_focus(self) -> None:
        """capture_wechat_ocr 首轮必须传 --no-activate；遮挡且用户活跃时禁止调 activate 抢前台窗口。"""
        calls: List[List[str]] = []

        def fake_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            calls.append(list(args))
            if args[0] == "capture-ocr":
                return {"ok": False, "error_code": "window_occluded", "error": "occluded"}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        self.hid_state.update({"anyInputIdleSeconds": 0.4, "mouseIdleSeconds": 0.4, "hardwareMouseIdleSeconds": 0.4})
        out = self.engine.capture_wechat_ocr(self.tmp / "ocr.png")
        self.assertFalse(out.get("ok"))
        self.assertTrue(out.get("occluded"))
        self.assertTrue(out.get("pausedByHumanGuard"))
        self.assertIn("--no-activate", calls[0])
        self.assertTrue(all(c[0] != "activate" for c in calls))

    def test_4_guard_self_rpa_requires_cursor_coords_and_blocks_scroll(self) -> None:
        """record_rpa_action 不带坐标时绝不豁免鼠标活动；1.2s 内滚轮或原生中断触发冷却。"""
        self.engine.human_guard.record_rpa_action(action="paste-and-verify")
        self.clock["now"] += 0.3
        res_no_coords = self.engine.human_guard.check_can_operate({
            "anyInputIdleSeconds": 0.3,
            "mouseIdleSeconds": 0.3,
            "keyboardIdleSeconds": 50.0,
            "cursorPosition": {"x": 500.0, "y": 500.0},
        })
        self.assertFalse(res_no_coords["canOperate"])

        # Reset clock past cooldown + idle thresholds
        self.clock["now"] += 60.0
        self.engine.human_guard.record_rpa_action(action="click", cursor_x=400.0, cursor_y=300.0)
        self.clock["now"] += 0.2
        res_scroll = self.engine.human_guard.check_can_operate({
            "anyInputIdleSeconds": 0.2,
            "mouseIdleSeconds": 0.2,
            "scrollIdleSeconds": 0.2,
            "keyboardIdleSeconds": 50.0,
            "cursorPosition": {"x": 401.0, "y": 300.0},
        })
        self.assertFalse(res_scroll["canOperate"])

        trig = self.engine.human_guard.trigger_human_cooldown(
            reason="human_mouse_contended_during_move",
            cursor_pos={"x": 612.3, "y": 418.9},
        )
        self.assertFalse(trig["canOperate"])
        self.assertEqual(trig["status"], "human_active_cooldown")
        self.assertEqual(trig["triggerReason"], "human_mouse_contended_during_move")

    def test_5_run_native_enforces_guard_injects_flag_and_triggers_cooldown(self) -> None:
        """enforce_human_guard 下 _run_native 拦截活跃期交互、注入 --guard-idle 1.5、并在原生中止后进冷却。"""
        fake_bin = self.tmp / "fake_native.py"
        fake_bin.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "args = sys.argv[1:]\n"
            "print(json.dumps({'ok': False, 'error_code': 'human_input_active', 'reason': 'human_mouse_active', 'args': args}))\n",
            encoding="utf-8",
        )
        fake_bin.chmod(0o755)
        self.engine.binary_path = fake_bin

        # When idle and enforced: injects --guard-idle 1.5, gets native abort, and enters cooldown!
        with self.engine.enforce_human_guard(True):
            res = self.engine._run_native(["click", "--x", "10", "--y", "20"], timeout=5.0)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "human_input_active")
        self.assertIn("--guard-idle", res.get("args", []))
        self.assertFalse(self.engine.human_guard.check_can_operate()["canOperate"])

        # Subsequent call inside enforce_human_guard must be blocked before even spawning binary
        fake_bin.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(99)\n", encoding="utf-8")
        fake_bin.chmod(0o755)
        with self.engine.enforce_human_guard(True):
            blocked = self.engine._run_native(["click", "--x", "10", "--y", "20"], timeout=5.0)
        self.assertTrue(blocked.get("blockedByHumanGuard"))
        self.assertEqual(blocked.get("error_code"), "human_input_active")

    def test_6_send_text_manual_vs_auto_guard_and_dedup_rollback(self) -> None:
        """自动 send_text 在人工冷却期内让路并回滚防重锁；manual_trigger=True 显式人工点击可立即发送。"""
        self.engine.allowlist = type(self.engine.allowlist)(["测试好友Z"])
        self.hid_state.update({
            "anyInputIdleSeconds": 0.3,
            "mouseIdleSeconds": 0.3,
            "hardwareMouseIdleSeconds": 0.3,
            "cursorPosition": {"x": 920.0, "y": 500.0},
        })

        seen_args: List[List[str]] = []

        def fake_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            seen_args.append(list(args))
            return {"ok": True, "sent": True, "verified": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        auto_res = self.engine.send_text(
            "测试好友Z",
            "你好呀",
            dry_run=False,
            silent_mode=False,
            confirm_send=True,
            skip_navigation=True,
            target_window_id=101,
            manual_trigger=False,
        )
        self.assertFalse(auto_res.get("ok"))
        self.assertTrue(auto_res.get("blockedByHumanGuard"))
        self.assertEqual(auto_res.get("status"), "paused_human_active")
        self.assertEqual(seen_args, [])

        # Because dedup rolled back, manual trigger with exact same text succeeds!
        manual_res = self.engine.send_text(
            "测试好友Z",
            "你好呀",
            dry_run=False,
            silent_mode=False,
            confirm_send=True,
            skip_navigation=True,
            target_window_id=101,
            manual_trigger=True,
        )
        self.assertTrue(manual_res.get("ok"))
        self.assertEqual(manual_res.get("status"), "sent")

    def test_7_media_analyzer_skips_click_when_human_active(self) -> None:
        """人工活跃期间 media_link_analyzer 禁止点击卡片或滚动正文窗口。"""
        self.engine.allowlist = type(self.engine.allowlist)(["测试好友Z"])
        self.hid_state.update({"anyInputIdleSeconds": 0.2, "mouseIdleSeconds": 0.2, "hardwareMouseIdleSeconds": 0.2})
        called_cmds: List[str] = []

        def fake_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            called_cmds.append(args[0] if args else "")
            return {"ok": True, "windows": []}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        snap = self.tmp / "card.png"
        _write_solid_png(snap, 700, 800)
        res = self.engine.media_analyzer.click_and_deep_read_bubble(
            bubble={
                "senderRole": "peer",
                "mediaType": "wechat_article",
                "text": "一篇深度文章",
                "clickRelX": 240.0,
                "clickRelY": 320.0,
            },
            snapshot_path=snap,
            window_bounds={"x": 100, "y": 100, "width": 700, "height": 800},
            click_to_open=True,
            contact="测试好友Z",
        )
        self.assertIsInstance(res, dict)
        self.assertNotIn("click", called_cmds)
        self.assertNotIn("scroll", called_cmds)

    def test_8_compiled_swift_binary_live_zero_intrusion_guard(self) -> None:
        """实测编译后的 bin/wechat-vision-ax：hid-idle 与 --guard-idle 99999 零激活、零移动立即返回 human_input_active。"""
        bin_path = Path(__file__).resolve().parent.parent / "bin" / "wechat-vision-ax"
        self.assertTrue(bin_path.is_file(), f"Missing native binary at {bin_path}")

        hid_proc = subprocess.run([str(bin_path), "hid-idle"], capture_output=True, text=True, timeout=8)
        self.assertEqual(hid_proc.returncode, 0, msg=hid_proc.stderr)
        hid_json = json.loads(hid_proc.stdout)
        self.assertTrue(hid_json.get("ok"))
        hid = hid_json.get("hidIdle") or {}
        self.assertIn("hardwareMouseIdleSeconds", hid)
        self.assertIn("hardwareKeyboardIdleSeconds", hid)
        self.assertIn("cursorPosition", hid)

        if float(hid.get("anyInputIdleSeconds") or 0.0) < 99999.0:
            paste_proc = subprocess.run(
                [str(bin_path), "paste-and-verify", "--text", "guard-smoke", "--silent", "--guard-idle", "99999"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            self.assertNotEqual(paste_proc.returncode, 0)
            paste_json = json.loads(paste_proc.stdout)
            self.assertFalse(paste_json.get("ok"))
            self.assertEqual(paste_json.get("error_code"), "human_input_active")

            act_proc = subprocess.run(
                [str(bin_path), "activate", "--guard-idle", "99999"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            self.assertNotEqual(act_proc.returncode, 0)
            act_json = json.loads(act_proc.stdout)
            self.assertFalse(act_json.get("ok"))
            self.assertEqual(act_json.get("error_code"), "human_input_active")


if __name__ == "__main__":
    unittest.main()
