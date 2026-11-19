"""v2.9.0 Headless Background AX + Three-Tier Anti-Ban Risk Guardrails + Concurrency Swimlane Tests."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_control.app_use_meta_algo import AntiRiskPacer, classify_app_risk_tier
from wechat_control.auth_gate import ALL_CAPABILITIES
from wechat_control.engine import WeChatControlEngine
from wechat_control.mcp_server import MCP_TOOLS, WeChatMCPServer, create_http_server
from wechat_control.web_console import render_web_console_html


def _make_engine(data: Path) -> WeChatControlEngine:
    engine = WeChatControlEngine(
        audit_log_path=data / "audit.jsonl",
        auth_file_path=data / "auth.json",
        bindings_file_path=data / "bindings.json",
        models_config_path=data / "models.json",
        model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
        knowledge_db_path=data / "kb.sqlite",
        personas_file_path=data / "personas.json",
        snapshots_dir=data / "snap",
        reports_dir=data / "reports",
        allowed_groups=["VIP客户群"],
    )
    engine.auth_grant(ALL_CAPABILITIES, authorized_by="v29-test")
    return engine


class AppUseV29HeadlessAxAndRiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.engine = _make_engine(self.data)

    def _start_http(self):
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        return f"http://127.0.0.1:{port}"

    def test_01_risk_tier_classification_three_tiers(self) -> None:
        for bid, name in (
            ("com.tencent.xinWeChat", "微信"),
            ("com.alibaba.DingTalkMac", "DingTalk"),
            ("com.bytedance.macos.feishu", "Feishu"),
            ("com.xingin.xhs", "小红书"),
        ):
            rp = classify_app_risk_tier(bid, name)
            self.assertEqual(rp["tier"], "high_risk_social", f"{bid} should be high_risk_social")
            self.assertFalse(rp["allowHeadlessAxWrite"])
            self.assertEqual(rp["defaultDispatchMode"], "foreground_human_paced")

        for bid, name in (
            ("com.openai.chat", "ChatGPT"),
            ("com.google.Chrome", "Chrome"),
        ):
            rp = classify_app_risk_tier(bid, name)
            self.assertEqual(rp["tier"], "moderate_agent_or_web")
            self.assertTrue(rp["allowHeadlessAxWrite"])

        for bid, name in (
            ("com.apple.calculator", "Calculator"),
            ("com.apple.TextEdit", "TextEdit"),
            ("com.apple.Dictionary", "Dictionary"),
        ):
            rp = classify_app_risk_tier(bid, name)
            self.assertEqual(rp["tier"], "safe_native")
            self.assertTrue(rp["allowHeadlessAxWrite"])
            self.assertEqual(rp["jitterRangeMs"], [0, 0])

    def test_02_anti_risk_pacer_enforces_gap_and_jitter(self) -> None:
        pacer = AntiRiskPacer()
        slept_log = []
        clock = {"t": 100.0}

        def fake_sleep(sec: float) -> None:
            slept_log.append(sec)
            clock["t"] += sec

        rp_safe = classify_app_risk_tier("com.apple.TextEdit", "TextEdit")
        p0 = pacer.pace_before_mutation("com.apple.TextEdit", rp_safe, sleep_fn=fake_sleep, mono_fn=lambda: clock["t"])
        self.assertEqual(p0["sleptMs"], 0.0)
        self.assertEqual(slept_log, [])

        rp_high = classify_app_risk_tier("com.tencent.xinWeChat", "微信")
        p1 = pacer.pace_before_mutation("com.tencent.xinWeChat", rp_high, sleep_fn=fake_sleep, mono_fn=lambda: clock["t"])
        self.assertGreaterEqual(p1["sleptMs"], 260.0)
        self.assertLessEqual(p1["sleptMs"], 780.0)

        # Second immediate call with no elapsed real time must also pay minActionGapMs (350) + jitter
        p2 = pacer.pace_before_mutation("com.tencent.xinWeChat", rp_high, sleep_fn=fake_sleep, mono_fn=lambda: clock["t"])
        self.assertGreaterEqual(p2["sleptMs"], 260.0)
        self.assertEqual(pacer.stats()["totalPacedOps"], 3)

    def test_03_safe_native_headless_ax_zero_hid_lease(self) -> None:
        seen_cmds = []

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            seen_cmds.append(cmd)
            if cmd == "app-use-ax-action":
                return {
                    "ok": True,
                    "channel": "headless_ax",
                    "action": "AXPress",
                    "axError": 0,
                    "stoleFocus": False,
                    "touchedClipboard": False,
                    "matchedElement": {"role": "AXButton", "identifier": "btn_ok"},
                }
            if cmd == "app-use-ax-set-value":
                txt = args[args.index("--text") + 1]
                return {
                    "ok": True,
                    "verified": True,
                    "channel": "headless_ax",
                    "axError": 0,
                    "stoleFocus": False,
                    "touchedClipboard": False,
                    "readbackSource": "ax_headless",
                    "readbackPreview": txt,
                    "matchedElement": {"role": "AXTextArea"},
                }
            raise AssertionError(f"Unexpected HID command: {args}")

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        res = self.engine.app_use_run_workflow(
            workflow={
                "id": "wf_v29_headless",
                "targetApp": {"bundleID": "com.apple.TextEdit", "name": "TextEdit"},
                "steps": [
                    {"step": 1, "action": "activate_app", "headlessOptional": True},
                    {"step": 2, "action": "click_element", "targetAxIdentifier": "btn_ok"},
                    {"step": 3, "action": "focus_and_type", "targetRole": "AXTextArea", "text": "Headless Hello"},
                ],
            },
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["dispatchSummary"]["headlessAxSteps"], 2)
        self.assertEqual(res["dispatchSummary"]["foregroundHidSteps"], 0)
        self.assertEqual(self.engine.app_use._hid_lease.stats()["totalAcquisitions"], 0)
        self.assertEqual(res["stepResults"][0]["dispatchChannel"], "headless_ax_skipped")
        self.assertEqual(res["stepResults"][1]["dispatchChannel"], "headless_ax")
        self.assertEqual(res["stepResults"][2]["dispatchChannel"], "headless_ax")
        self.assertEqual(seen_cmds, ["app-use-ax-action", "app-use-ax-set-value"])

    def test_04_headless_ax_failure_falls_back_to_hid_lease(self) -> None:
        seen_cmds = []

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            seen_cmds.append(cmd)
            if cmd == "app-use-ax-set-value":
                return {"ok": False, "code": "ax_value_not_settable", "channel": "headless_ax"}
            if cmd == "app-use-inspect":
                return {"ok": True, "axControls": [], "axTexts": []}
            if cmd == "app-use-paste":
                txt = args[args.index("--text") + 1]
                return {"ok": True, "verified": True, "readbackSource": "ax", "readbackPreview": txt}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        res = self.engine.app_use_run_workflow(
            workflow={
                "id": "wf_v29_fb",
                "targetApp": {"bundleID": "com.apple.TextEdit", "name": "TextEdit"},
                "steps": [
                    {"step": 1, "action": "focus_and_type", "targetRole": "AXTextArea", "text": "Fallback OK"},
                ],
            },
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            dispatch_mode="headless_ax_first",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["dispatchSummary"]["fallbackSteps"], 1)
        self.assertEqual(res["dispatchSummary"]["foregroundHidSteps"], 1)
        self.assertEqual(res["stepResults"][0]["dispatchChannel"], "foreground_hid_fallback")
        self.assertEqual(res["stepResults"][0]["headlessFallbackReason"], "ax_value_not_settable")
        self.assertGreaterEqual(self.engine.app_use._hid_lease.stats()["totalAcquisitions"], 1)
        self.assertIn("app-use-paste", seen_cmds)

    def test_05_high_risk_social_hard_blocks_headless_ax_write(self) -> None:
        seen_cmds = []

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            seen_cmds.append(cmd)
            if cmd == "app-use-inspect":
                return {
                    "ok": True,
                    "window": {"bounds": {"x": 0, "y": 0, "width": 1000, "height": 800}},
                    "axControls": [],
                    "axTexts": [],
                }
            if cmd == "app-use-paste":
                return {"ok": True, "verified": True, "readbackPreview": "hi"}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        res = self.engine.app_use_run_workflow(
            workflow={
                "id": "wf_v29_wechat_guard",
                "targetApp": {"bundleID": "com.tencent.xinWeChat", "name": "微信"},
                "steps": [
                    {"step": 1, "action": "click_element", "relX": 0.5, "relY": 0.5},
                    {"step": 2, "action": "focus_and_type", "text": "hi"},
                ],
            },
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            dispatch_mode="headless_ax_first",
        )
        self.assertTrue(res["ok"])
        self.assertNotIn("app-use-ax-action", seen_cmds)
        self.assertNotIn("app-use-ax-set-value", seen_cmds)
        self.assertTrue(res["dispatchSummary"]["riskGuardEnforced"])
        self.assertFalse(res["dispatchSummary"]["effectiveHeadlessAllowed"])
        self.assertEqual(res["dispatchSummary"]["headlessAxSteps"], 0)
        self.assertGreater(res["dispatchSummary"]["totalJitterMs"], 0.0)
        self.assertEqual(res["stepResults"][0]["dispatchChannel"], "foreground_hid")
        self.assertEqual(res["stepResults"][1]["dispatchChannel"], "foreground_hid")

    def test_06_parallel_headless_ax_true_overlap_and_swimlanes(self) -> None:
        overlap = {"active": 0, "max_active": 0}
        guard = threading.Lock()

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd in ("app-use-ax-action", "app-use-ax-set-value"):
                with guard:
                    overlap["active"] += 1
                    if overlap["active"] > overlap["max_active"]:
                        overlap["max_active"] = overlap["active"]
                try:
                    time.sleep(0.10)
                finally:
                    with guard:
                        overlap["active"] -= 1
                if cmd == "app-use-ax-action":
                    return {"ok": True, "channel": "headless_ax", "action": "AXPress", "axError": 0, "matchedElement": {"role": "AXButton"}}
                return {"ok": True, "verified": True, "channel": "headless_ax", "axError": 0, "readbackSource": "ax_headless", "readbackPreview": "parallel", "matchedElement": {"role": "AXTextArea"}}
            raise AssertionError(f"Should stay headless: {args}")

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        r_res = self.engine.app_use_run_parallel(
            [
                {
                    "workflow": {
                        "id": "wf_p_calc",
                        "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator"},
                        "steps": [{"step": 1, "action": "click_element", "targetAxTitle": "9", "targetRole": "AXButton"}],
                    }
                },
                {
                    "workflow": {
                        "id": "wf_p_text",
                        "targetApp": {"bundleID": "com.apple.TextEdit", "name": "TextEdit"},
                        "steps": [{"step": 1, "action": "focus_and_type", "targetRole": "AXTextArea", "text": "parallel"}],
                    }
                },
            ],
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            max_workers=2,
            dispatch_mode="headless_ax_first",
        )
        self.assertTrue(r_res["ok"])
        self.assertEqual(overlap["max_active"], 2, "Headless AX jobs should truly execute in parallel without blocking on HID lock")
        self.assertEqual(r_res["hidLeaseStats"]["totalAcquisitions"], 0)
        conc = self.engine.app_use_concurrency_status()
        self.assertTrue(conc["ok"])
        self.assertGreaterEqual(conc["metrics"]["totalHeadlessAxOps"], 2)
        self.assertGreaterEqual(len(conc["recentLanes"]), 2)

    def test_07_http_mcp_and_web_console_v29(self) -> None:
        tool_names = {t["name"] for t in MCP_TOOLS}
        self.assertIn("app_use_concurrency_status", tool_names)
        self.assertIn("app_use_risk_profile", tool_names)

        mcp = WeChatMCPServer(self.engine)
        cs = mcp._dispatch_tool("app_use_concurrency_status", {})
        self.assertTrue(cs["ok"])
        rp = mcp._dispatch_tool("app_use_risk_profile", {"bundle_id": "com.tencent.xinWeChat", "app_name": "微信"})
        self.assertEqual(rp["riskProfile"]["tier"], "high_risk_social")

        base = self._start_http()
        with urllib.request.urlopen(f"{base}/api/app-use/concurrency-status", timeout=10) as r:
            body_c = json.loads(r.read().decode("utf-8"))
        self.assertTrue(body_c["ok"])
        with urllib.request.urlopen(f"{base}/api/app-use/risk-profile?bundle_id=com.tencent.xinWeChat", timeout=10) as r:
            body_r = json.loads(r.read().decode("utf-8"))
        self.assertEqual(body_r["riskProfile"]["tier"], "high_risk_social")

        html = render_web_console_html()
        self.assertNotIn("window.confirm(", html)
        for marker in ("appuseConcurrencyBox", "appuseRiskBadge", "appuseDispatchModeSelect"):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
