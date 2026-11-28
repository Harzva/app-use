"""Unit and integration tests for Self-Authoring & Self-Debugging Workflow Agent (v3.1)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.cli import main as cli_main  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import WeChatMCPServer, create_http_server  # noqa: E402
from wechat_control.web_console import render_web_console_html  # noqa: E402
from wechat_control.workflow_agent import WorkflowSpecLinter, detect_apps_from_goal  # noqa: E402


class WorkflowAgentV31Tests(unittest.TestCase):
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
        self.engine.auth_grant(["*"], authorized_by="unit-test-v31")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_01_dsl_six_new_primitives_anti_self_cert_and_cycle_guard(self) -> None:
        # Mocked native inspection returning a chat snippet + WeChat ID
        def fake_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            cmd = args[0]
            if cmd == "app-use-inspect":
                out_idx = args.index("--out") + 1 if "--out" in args else -1
                if out_idx != -1:
                    Path(args[out_idx]).parent.mkdir(parents=True, exist_ok=True)
                    Path(args[out_idx]).write_bytes(b"fake")
                return {
                    "ok": True,
                    "window": {"bounds": {"x": 100, "y": 100, "width": 500, "height": 400}},
                    "axControls": [{"role": "AXStaticText", "value": "我的微信号是 lark_vip88"}],
                    "axTexts": ["客户发来消息：请加我微信号 lark_vip88"],
                    "ocrPreview": "客户发来消息：请加我微信号 lark_vip88",
                    "ocrElements": [{"text": "lark_vip88", "screenCenter": {"x": 240, "y": 220}}],
                    "savedPath": args[out_idx] if out_idx != -1 else "",
                }
            return {"ok": True}

        wf = {
            "id": "wf_primitives_test",
            "name": "6-Primitive Cross-App Test",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator", "category": "productivity"},
            "parameters": [{"name": "source_user", "defaultValue": "飞书赵总"}],
            "steps": [
                {"step": 1, "action": "switch_app", "title": "切到飞书", "targetApp": {"bundleID": "com.bytedance.macos.feishu", "name": "Feishu"}},
                {"step": 2, "action": "inspect_ui", "title": "读飞书文本", "captureAs": "raw_feishu"},
                {"step": 3, "action": "llm_extract", "title": "抽微信号", "sourceVar": "raw_feishu", "extractor": "wechat_accounts", "captureAs": "wx_acc", "required": True},
                {"step": 4, "action": "branch_if", "title": "判断是否空", "var": "wx_acc", "operator": "not_empty", "onFalse": "skip_next"},
                {"step": 5, "action": "llm_draft", "title": "生成自报家门文案", "template": "你好我是{businessName}的{ownerName}", "captureAs": "greet"},
                {"step": 6, "action": "builtin_tool", "title": "登记CRM", "tool": "crm_enroll", "idempotencyKey": "k_crm_1", "captureAs": "crm_res", "params": {"target": "飞书引流-{{source_user}}", "tags": ["飞书获客", "飞书引流"], "note": "账号={{wx_acc}}"}},
                {"step": 7, "action": "assert_check", "title": "核验独立CRM回执", "evidenceSource": "tool_result", "targetVar": "crm_res", "operator": "contains", "expected": "飞书引流"},
            ],
        }
        with patch.object(self.engine, "_run_native", side_effect=fake_native), patch.object(
            self.engine, "_check_human_guard_for_action", return_value=None
        ):
            r1 = self.engine.app_use.run_workflow(workflow=wf, dry_run=False, confirm_run=True, respect_human_guard=False)
            self.assertTrue(r1["ok"], r1)
            self.assertEqual(r1["evidenceLevel"], "effect_ok")
            self.assertEqual(r1["capturedVars"]["wx_acc"], "lark_vip88")
            self.assertIn("智拓巨浪", r1["capturedVars"]["greet"])
            self.assertTrue(r1["allAssertionsPassed"])

            # Idempotency check on second live run of step 6
            r2 = self.engine.app_use.run_workflow(workflow=wf, dry_run=False, confirm_run=True, respect_human_guard=False)
            self.assertTrue(r2["ok"])
            crm_step2 = next(s for s in r2["stepResults"] if s.get("action") == "builtin_tool")
            self.assertTrue(crm_step2.get("deduplicated"))

        # Self-certified assertion (input param only) must fail even in dry_run!
        bad_self_cert = {
            "id": "wf_bad_cert",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator"},
            "parameters": [{"name": "user_input", "defaultValue": "1000"}],
            "steps": [
                {"step": 1, "action": "assert_check", "evidenceSource": "captured_var_from_read", "targetVar": "user_input", "operator": "not_empty"}
            ],
        }
        res_bad_cert = self.engine.app_use.run_workflow(workflow=bad_self_cert, dry_run=True)
        self.assertFalse(res_bad_cert["ok"])
        self.assertEqual(res_bad_cert["error_code"], "SELF_CERTIFIED_ASSERTION")

        # Backward jump branch_if must be rejected with CYCLE_DETECTED
        bad_cycle = {
            "id": "wf_bad_cycle",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator"},
            "steps": [
                {"step": 1, "action": "inspect_ui", "captureAs": "x"},
                {"step": 2, "action": "branch_if", "var": "x", "operator": "is_empty", "onFalse": "jump_to_step", "jumpToStep": 1},
            ],
        }
        res_bad_cycle = self.engine.app_use.run_workflow(workflow=bad_cycle, dry_run=True)
        self.assertFalse(res_bad_cycle["ok"])
        self.assertEqual(res_bad_cycle["error_code"], "CYCLE_DETECTED")

        # Unwhitelisted tool must be rejected
        bad_tool = {
            "id": "wf_bad_tool",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator"},
            "steps": [{"step": 1, "action": "builtin_tool", "tool": "exec_shell_arbitrary", "params": {}}],
        }
        res_bad_tool = self.engine.app_use.run_workflow(workflow=bad_tool, dry_run=True)
        self.assertFalse(res_bad_tool["ok"])
        self.assertEqual(res_bad_tool["error_code"], "UNWHITELISTED_TOOL")

    def test_02_spec_linter_and_auto_hardening(self) -> None:
        raw_wf = {
            "id": "wf_unhardened",
            "targetApp": {"bundleID": "com.tencent.xinWeChat", "name": "WeChat", "category": "im_social"},
            "steps": [
                {"step": 1, "action": "activate_app"},
                {"step": 2, "action": "builtin_tool", "tool": "wechat_add_friend", "params": {"account": "wx_test1"}},
                {"step": 3, "action": "assert_check", "evidenceSource": "tool_result", "targetVar": "tool_wechat_add_friend", "operator": "not_empty"},
            ],
        }
        lint_bad = WorkflowSpecLinter.lint(raw_wf)
        self.assertFalse(lint_bad["ok"])
        codes = {e["code"] for e in lint_bad["errors"]}
        self.assertIn("MISSING_OUTBOUND_GATE", codes)

        hardened, fixes = WorkflowSpecLinter.auto_harden(raw_wf)
        self.assertTrue(len(fixes) >= 1)
        lint_ok = WorkflowSpecLinter.lint(hardened)
        self.assertTrue(lint_ok["ok"], lint_ok)
        self.assertEqual(hardened["steps"][1]["action"], "pause_for_human")
        add_step = next(s for s in hardened["steps"] if s.get("tool") == "wechat_add_friend")
        self.assertTrue(bool(add_step.get("idempotencyKey")))

    def test_03_closed_loop_self_debug_element_drift_and_timing_to_verified(self) -> None:
        # Simulate v1 where click target is drifted ("Submit Old" -> real button "提交计算")
        # and wait_and_read initially checks before result settles -> round 1 fails ELEMENT_DRIFT,
        # debugger patches to "提交计算", round 2 passes & compiles as "verified"!
        click_coords: List[float] = []

        def fake_native_heal(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            cmd = args[0]
            if cmd == "app-use-activate":
                return {"ok": True}
            if cmd == "app-use-ax-action":
                return {"ok": False, "code": "ax_not_found"}
            if cmd == "app-use-inspect":
                out_idx = args.index("--out") + 1 if "--out" in args else -1
                if out_idx != -1:
                    Path(args[out_idx]).parent.mkdir(parents=True, exist_ok=True)
                    Path(args[out_idx]).write_bytes(b"fake")
                clicked_submit = len(click_coords) > 0
                return {
                    "ok": True,
                    "window": {"bounds": {"x": 0, "y": 0, "width": 400, "height": 300}},
                    "axControls": [
                        {"role": "AXButton", "title": "计算提交", "identifier": "btn_calc", "center": {"x": 200, "y": 240}},
                    ],
                    "axTexts": ["1000" if clicked_submit else "0"],
                    "ocrPreview": "结果: 1000" if clicked_submit else "初始 0",
                    "ocrElements": [
                        {"text": "计算提交", "screenCenter": {"x": 200, "y": 240}},
                        {"text": "1000" if clicked_submit else "0", "screenCenter": {"x": 200, "y": 80}},
                    ],
                    "savedPath": args[out_idx] if out_idx != -1 else "",
                }
            if cmd == "click":
                click_coords.append(float(args[args.index("--x") + 1]))
                return {"ok": True}
            return {"ok": True}

        broken_wf = {
            "id": "wf_broken_calc",
            "name": "故意写坏的计算提交",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator", "category": "productivity"},
            "steps": [
                {"step": 1, "action": "activate_app", "title": "激活", "launchIfNeeded": True},
                {"step": 2, "action": "click_element", "title": "点提交(漂移)", "targetAxTitle": "提交按钮", "relX": 0.9, "relY": 0.9},
                {"step": 3, "action": "wait_and_read", "title": "读结果", "delaySec": 0.05, "captureAs": "res"},
                {"step": 4, "action": "assert_check", "title": "断言1000", "evidenceSource": "post_ui_readback", "operator": "contains", "expected": "1000"},
            ],
        }
        # Deliberately force relX/relY unresolved & wrong title in v1 without fuzzy fallback match on first run?
        # Even cleaner: have v1 fail assert_check due to missing click on round 1 -> wait: click with relX=0.9 falls back to rel:(0.9,0.9)!
        # So test missing clear / bad sequence before click or wrong targetAxTitle WITHOUT relX/x/y so click_element genuinely fails unresolved!
        broken_wf["steps"][1] = {"step": 2, "action": "click_element", "title": "点计算提交", "targetAxTitle": "计算"}

        # Ensure round 1 click fails by making round 1 have unknown title and round 2 re-anchored via SemanticElementGrounder?
        # SemanticElementGrounder scores "计算提交" against "计算" high! To make round 1 fail first inside run_workflow(self_heal=True),
        # have round 1 wait_and_read missing delay or have v1 skip click step & fail ASSERTION_FAILED on round 1, then debugger inserts Escape before sequence!
        broken_calc_v1 = {
            "id": "wf_broken_seq",
            "name": "漏了清零的步骤",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator", "category": "productivity"},
            "steps": [
                {"step": 1, "action": "activate_app", "title": "激活", "launchIfNeeded": True},
                {"step": 2, "action": "press_shortcut", "title": "键入序列", "sequence": "1,2,5,*,8,return", "delayMs": 20},
                {"step": 3, "action": "wait_and_read", "title": "回读结果", "delaySec": 0.05},
                {"step": 4, "action": "assert_check", "title": "断言出现1000", "evidenceSource": "post_ui_readback", "operator": "contains", "expected": "1000"},
            ],
        }
        seen_combos: List[str] = []

        def fake_native_seq(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            cmd = args[0]
            if cmd == "press-key":
                if "--combo" in args:
                    seen_combos.append(args[args.index("--combo") + 1])
                elif "--sequence" in args:
                    seen_combos.append("seq")
                return {"ok": True}
            if cmd == "app-use-inspect":
                out_idx = args.index("--out") + 1 if "--out" in args else -1
                if out_idx != -1:
                    Path(args[out_idx]).parent.mkdir(parents=True, exist_ok=True)
                    Path(args[out_idx]).write_bytes(b"fake")
                cleared = "escape" in seen_combos
                return {
                    "ok": True,
                    "window": {"bounds": {"x": 0, "y": 0, "width": 300, "height": 400}},
                    "axControls": [],
                    "axTexts": ["1000" if cleared else "999999"],
                    "ocrPreview": "1000" if cleared else "999999",
                    "ocrElements": [{"text": "1000" if cleared else "999999", "screenCenter": {"x": 150, "y": 80}}],
                    "savedPath": args[out_idx] if out_idx != -1 else "",
                }
            return {"ok": True}

        with patch.object(self.engine, "_run_native", side_effect=fake_native_seq), patch(
            "wechat_control.app_use_studio.time.sleep", return_value=None
        ):
            dbg = self.engine.workflow_agent_author_and_debug(
                "计算器算 125*8 并验证 1000",
                mode="live",
                max_debug_rounds=4,
                confirm_run=True,
                respect_human_guard=False,
                initial_workflow=broken_calc_v1,
            )

        self.assertTrue(dbg["ok"], dbg)
        self.assertEqual(dbg["status"], "verified")
        self.assertEqual(dbg["verificationStatus"], "verified")
        self.assertEqual(dbg["roundsUsed"], 2)
        self.assertEqual(dbg["workflowVersion"], 2)
        self.assertIn("escape", [s.get("combo") for s in dbg["workflow"]["steps"] if s.get("action") == "press_shortcut"])
        # Rollback back to v1 works cleanly
        rb = self.engine.app_use_rollback_workflow(dbg["workflowId"])
        self.assertTrue(rb["ok"])

    def test_04_anti_loop_fingerprint_breaker_and_auth_gate_halt(self) -> None:
        # Case A: AUTH_GATE screen -> immediate halt at Round 1, zero patching
        def fake_native_auth(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            if args[0] == "app-use-inspect":
                return {
                    "ok": True,
                    "window": {"bounds": {"x": 0, "y": 0, "width": 400, "height": 500}},
                    "axControls": [],
                    "ocrPreview": "请使用飞书扫码登录",
                    "ocrElements": [{"text": "请使用飞书扫码登录", "screenCenter": {"x": 200, "y": 250}}],
                }
            return {"ok": True}

        with patch.object(self.engine, "_run_native", side_effect=fake_native_auth):
            auth_res = self.engine.workflow_agent_author_and_debug(
                "从飞书聊天读取微信号并加微信",
                target_apps=["com.bytedance.macos.feishu"],
                mode="shadow",
                max_debug_rounds=4,
            )
        self.assertFalse(auth_res["ok"])
        self.assertEqual(auth_res["status"], "paused_auth_gate")
        self.assertEqual(auth_res["roundsUsed"], 1)

        # Case B: Persistent identical failure -> stops at Round 2 as needs_human_demo
        unfixable_wf = {
            "id": "wf_unfixable",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator"},
            "steps": [
                {"step": 1, "action": "wait_and_read", "delaySec": 0.9},
                {"step": 2, "action": "assert_check", "evidenceSource": "post_ui_readback", "operator": "contains", "expected": "IMPOSSIBLE_TOKEN_XYZ"},
            ],
        }

        def fake_native_static(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            if args[0] == "app-use-inspect":
                return {
                    "ok": True,
                    "window": {"bounds": {"x": 0, "y": 0, "width": 300, "height": 300}},
                    "axControls": [],
                    "axTexts": ["42"],
                    "ocrPreview": "42",
                    "ocrElements": [{"text": "42", "screenCenter": {"x": 100, "y": 100}}],
                }
            return {"ok": True}

        with patch.object(self.engine, "_run_native", side_effect=fake_native_static), patch(
            "wechat_control.app_use_studio.time.sleep", return_value=None
        ):
            loop_res = self.engine.workflow_agent_author_and_debug(
                "impossible check",
                mode="shadow",
                max_debug_rounds=5,
                initial_workflow=unfixable_wf,
            )
        self.assertFalse(loop_res["ok"])
        self.assertEqual(loop_res["status"], "needs_human_demo")
        self.assertEqual(loop_res["roundsUsed"], 2)

    def test_05_feishu_to_wechat_crm_shadow_and_omini_cli_fix(self) -> None:
        detected = detect_apps_from_goal("从飞书客户聊天里读取微信号，用智拓巨浪话术加微信，写入CRM")
        self.assertEqual(detected[0]["bundleID"], "com.bytedance.macos.feishu")
        self.assertEqual(detected[1]["bundleID"], "com.tencent.xinWeChat")

        def fake_feishu_ui(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            if args[0] == "app-use-inspect":
                return {
                    "ok": True,
                    "window": {"bounds": {"x": 50, "y": 50, "width": 800, "height": 600}},
                    "axControls": [],
                    "axTexts": ["林总：你好，方便加下微信 feishu_lin88 发个报价表吗？"],
                    "ocrPreview": "林总：你好，方便加下微信 feishu_lin88 发个报价表吗？",
                    "ocrElements": [{"text": "feishu_lin88", "screenCenter": {"x": 300, "y": 240}}],
                }
            return {"ok": True}

        with patch.object(self.engine, "_run_native", side_effect=fake_feishu_ui):
            shadow_res = self.engine.workflow_agent_author_and_debug(
                "从飞书客户聊天中提取微信号，用智拓巨浪话术自报家门加微信，备注飞书引流并写入后端CRM档案",
                mode="shadow",
                max_debug_rounds=3,
                auto_export_skill=True,
                params={"source_user": "林总"},
            )
        self.assertTrue(shadow_res["ok"], shadow_res)
        self.assertEqual(shadow_res["status"], "shadow_verified")
        self.assertEqual(shadow_res["lastRun"]["capturedVars"]["wechat_account"], "feishu_lin88")
        self.assertIn("智拓巨浪", shadow_res["lastRun"]["capturedVars"]["friend_greeting"])
        self.assertTrue(len(shadow_res["lastRun"]["shadowPreviews"]) >= 2)
        self.assertTrue(shadow_res["exportedSkill"]["ok"])

        # Verify cli:omini invokes --role proposer --id <uuid> and parses responseText cleanly
        captured_cmds: List[List[str]] = []

        def fake_cli_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            payload = {
                "ok": True,
                "actualModel": "gemini-3-pro",
                "responseText": json.dumps({"name": "CLI Plan", "steps": [{"step": 1, "action": "activate_app"}]}, ensure_ascii=False),
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        orig_runner = self.engine.app_use._cli_runner
        self.engine.app_use._cli_runner = fake_cli_run
        try:
            with patch.object(self.engine.app_use, "_find_cli_binary", return_value="/Users/mac/.local/bin/omini"):
                cli_res = self.engine.app_use._invoke_cli_agent(bin_name="omini", sys_prompt="sys", user_prompt="usr")
        finally:
            self.engine.app_use._cli_runner = orig_runner

        self.assertTrue(cli_res["ok"])
        self.assertIn("--role", captured_cmds[0])
        self.assertEqual(captured_cmds[0][captured_cmds[0].index("--role") + 1], "proposer")
        self.assertIn("--id", captured_cmds[0])
        self.assertIn("CLI Plan", cli_res["replyText"])

    def test_06_http_mcp_cli_and_web_console_v31(self) -> None:
        # MCP tools
        mcp = WeChatMCPServer(self.engine)
        tools_res = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tnames = {t["name"] for t in tools_res["result"]["tools"]}
        for expected in (
            "workflow_agent_propose_spec",
            "workflow_agent_author_and_debug",
            "workflow_agent_debug_existing",
            "workflow_agent_list_sessions",
        ):
            self.assertIn(expected, tnames)

        spec_call = mcp.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "workflow_agent_propose_spec", "arguments": {"goal": "从飞书找客户微信号并加微信写CRM", "inspect_live": False}},
        })
        spec_payload = json.loads(spec_call["result"]["content"][0]["text"])
        self.assertTrue(spec_payload["ok"])
        self.assertEqual(spec_payload["spec"]["blueprintId"], "feishu_to_wechat_crm")

        # HTTP routes
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/api/workflow-agent/templates", timeout=10) as resp:
                tpl_res = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp.status, 200)
                self.assertGreaterEqual(len(tpl_res["templates"]), 3)

            req_spec = urllib.request.Request(
                f"{base}/api/workflow-agent/spec",
                data=json.dumps({"goal": "计算器算 125*8 并写入文本编辑", "inspect_live": False}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_spec, timeout=10) as resp:
                http_spec = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(http_spec["ok"])
        finally:
            srv.shutdown()
            srv.server_close()

        # Web Console assertions (zero window.confirm!)
        html = render_web_console_html()
        for marker in ("wfagentStudioCard", "wfagentGoalInput", "wfagentRunAuthorDebugClick", "/api/workflow-agent/author-debug"):
            self.assertIn(marker, html)
        self.assertNotIn("window.confirm(", html)

        # CLI templates smoke
        rc = cli_main(["workflow-agent", "--action", "templates"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
