"""Unit and integration tests for Conversational Chat-to-Workflow & Chat-to-Edit (v3.2)."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.cli import main as cli_main  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import WeChatMCPServer, create_http_server  # noqa: E402
from wechat_control.supervisor_eval import (  # noqa: E402
    is_blocked_outbound_directive,
    parse_hashtag_directive,
)
from wechat_control.web_console import render_web_console_html  # noqa: E402


class WorkflowChatV32Tests(unittest.TestCase):
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
        self.engine.auth_grant(["*"], authorized_by="unit-test-v32")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _fake_feishu_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
        cmd = args[0]
        if cmd == "app-use-inspect":
            out_idx = args.index("--out") + 1 if "--out" in args else -1
            if out_idx != -1:
                Path(args[out_idx]).parent.mkdir(parents=True, exist_ok=True)
                Path(args[out_idx]).write_bytes(b"fake")
            return {
                "ok": True,
                "window": {"bounds": {"x": 40, "y": 40, "width": 760, "height": 560}},
                "axControls": [],
                "axTexts": ["刘总：你好加我微信号 vip_feishu88，发份方案给我"],
                "ocrPreview": "刘总：你好加我微信号 vip_feishu88，发份方案给我",
                "ocrElements": [{"text": "vip_feishu88", "screenCenter": {"x": 280, "y": 210}}],
                "savedPath": args[out_idx] if out_idx != -1 else "",
            }
        return {"ok": True}

    def test_01_multiturn_chat_turn_clarify_ready_and_shadow_build(self) -> None:
        # Turn 1: Vague goal -> clarifying questions
        t1 = self.engine.workflow_agent_chat_turn("帮我搞个飞书同步", mode="shadow")
        self.assertTrue(t1["ok"], t1)
        chat_id = t1["chatId"]
        self.assertTrue(chat_id.startswith("wfchat_"))
        self.assertEqual(t1["phase"], "clarifying")
        self.assertGreaterEqual(len(t1["questions"]), 1)
        self.assertLessEqual(len(t1["questions"]), 3)
        self.assertEqual(len(t1["messages"]), 2)

        # Turn 2: Answer slots -> ready_to_build
        t2 = self.engine.workflow_agent_chat_turn(
            "提取客户微信号加微信，备注用飞书VIP-，发前需要我确认",
            chat_id=chat_id,
            mode="shadow",
        )
        self.assertTrue(t2["ok"], t2)
        self.assertEqual(t2["chatId"], chat_id)
        self.assertEqual(t2["phase"], "ready_to_build")
        self.assertEqual(t2["questions"], [])
        self.assertEqual(t2["collectedConfig"]["remarkPrefix"], "飞书VIP-")
        self.assertTrue(t2["collectedConfig"]["requireConfirm"])
        self.assertIsInstance(t2["spec"], dict)
        self.assertIsInstance(t2["workflow"], dict)

        # Turn 3: Confirm -> built_and_debugged + shadow_verified + "飞书VIP-" in workflow & CRM preview
        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            t3 = self.engine.workflow_agent_chat_turn(
                "确认开始调试",
                chat_id=chat_id,
                mode="shadow",
                params={"source_user": "飞书VIP刘总", "raw_message": "你好加我微信号 vip_feishu88"},
            )
        self.assertTrue(t3["ok"], t3)
        self.assertEqual(t3["phase"], "built_and_debugged")
        dbg = t3["debugSession"]
        self.assertTrue(dbg["ok"], dbg)
        self.assertEqual(dbg["status"], "shadow_verified")
        wf_json = json.dumps(t3["workflow"], ensure_ascii=False)
        self.assertIn("飞书VIP-", wf_json)
        last_run = dbg["lastRun"]
        self.assertEqual(last_run["capturedVars"]["wechat_account"], "vip_feishu88")
        previews_text = json.dumps(last_run.get("shadowPreviews") or [], ensure_ascii=False)
        self.assertIn("飞书VIP-", previews_text)

        # Chat session persistence check
        self.assertTrue(self.engine.workflow_agent.chats_path.exists())
        listed = self.engine.workflow_agent_list_chats(limit=20)
        self.assertTrue(listed["ok"])
        self.assertGreaterEqual(listed["count"], 1)
        self.assertEqual(listed["chats"][0]["chatId"], chat_id)
        self.assertEqual(listed["chats"][0]["phase"], "built_and_debugged")

    def test_02_multimode_chat_edit_safety_rejection_and_rollback(self) -> None:
        # Build v1 workflow via multi-turn chat
        t1 = self.engine.workflow_agent_chat_turn("帮我搞个飞书同步", mode="shadow")
        t2 = self.engine.workflow_agent_chat_turn(
            "提取客户微信号加微信，备注用飞书VIP-，发前需要我确认",
            chat_id=t1["chatId"],
            mode="shadow",
        )
        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            t3 = self.engine.workflow_agent_chat_turn(
                "确认开始调试",
                chat_id=t1["chatId"],
                mode="shadow",
                params={"source_user": "飞书VIP刘总", "raw_message": "你好加我微信号 vip_feishu88"},
            )
        wf_id = t3["workflow"]["id"]
        self.assertEqual(int(t3["workflow"].get("version") or 1), 1)

        # Edit 1: Remark prefix rewrite
        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            e1 = self.engine.workflow_agent_chat_edit(
                wf_id,
                "把备注前缀改成飞书大客户-",
                mode="shadow",
                params={"source_user": "王总", "raw_message": "你好加我微信号 vip_feishu88"},
            )
        self.assertTrue(e1["ok"], e1)
        self.assertEqual(e1["previousVersion"], 1)
        self.assertEqual(e1["newVersion"], 2)
        self.assertTrue(e1["lintReport"]["ok"])
        self.assertEqual(e1["verificationRun"]["status"], "shadow_verified")
        self.assertIn("飞书大客户-", json.dumps(e1["workflow"]["steps"], ensure_ascii=False))
        self.assertIn("飞书大客户-", json.dumps(e1["verificationRun"]["lastRun"]["shadowPreviews"], ensure_ascii=False))

        # Edit 2: Forward-only branch_if insertion after step 3
        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            e2 = self.engine.workflow_agent_chat_edit(
                wf_id,
                "第3步之后加一个判断，如果微信号为空就跳过",
                mode="shadow",
                params={"source_user": "王总", "raw_message": "你好加我微信号 vip_feishu88"},
            )
        self.assertTrue(e2["ok"], e2)
        self.assertEqual(e2["previousVersion"], 2)
        self.assertEqual(e2["newVersion"], 3)
        step4 = e2["workflow"]["steps"][3]
        self.assertEqual(step4["action"], "branch_if")
        self.assertEqual(step4["onFalse"], "skip_next")

        # Edit 3 (Unsafe): Attempt to delete the last assert_check -> must be rejected without mutating v3
        steps_v3 = e2["workflow"]["steps"]
        assert_indices = [i + 1 for i, s in enumerate(steps_v3) if s.get("action") == "assert_check"]
        self.assertEqual(len(assert_indices), 1)
        bad_del_assert = self.engine.workflow_agent_chat_edit(
            wf_id,
            f"删除第{assert_indices[0]}步",
            mode="shadow",
        )
        self.assertFalse(bad_del_assert["ok"])
        self.assertEqual(bad_del_assert["error_code"], "unsafe_edit_rejected")
        self.assertFalse(bad_del_assert["lintReport"]["ok"])

        # Edit 4 (Unsafe): Attempt to delete mandatory pause_for_human gate before wechat_add_friend -> rejected
        gate_indices = [i + 1 for i, s in enumerate(steps_v3) if s.get("action") == "pause_for_human"]
        self.assertGreaterEqual(len(gate_indices), 1)
        bad_del_gate = self.engine.workflow_agent_chat_edit(
            wf_id,
            f"删除第{gate_indices[0]}步",
            mode="shadow",
        )
        self.assertFalse(bad_del_gate["ok"])
        self.assertEqual(bad_del_gate["error_code"], "unsafe_edit_rejected")
        err_codes = {e.get("code") for e in bad_del_gate["lintReport"]["errors"]}
        self.assertIn("MISSING_OUTBOUND_GATE", err_codes)

        # Verify stored workflow is still intact at v3 with both pause_for_human and assert_check
        stored_v3 = self.engine.app_use._state["workflows"][wf_id]
        self.assertEqual(stored_v3["version"], 3)
        self.assertTrue(any(s.get("action") == "assert_check" for s in stored_v3["steps"]))
        self.assertTrue(any(s.get("action") == "pause_for_human" for s in stored_v3["steps"]))

        # Rollback back to v1 (revision_index=0) -> restores "飞书VIP-"
        rb = self.engine.app_use_rollback_workflow(wf_id, revision_index=0)
        self.assertTrue(rb["ok"], rb)
        self.assertEqual(rb["workflow"]["rolledBackFromVersion"], 1)
        rb_json = json.dumps(rb["workflow"]["steps"], ensure_ascii=False)
        self.assertIn("飞书VIP-", rb_json)
        self.assertNotIn("飞书大客户-", rb_json)

    def test_03_calculator_chat_edit_expression_and_assertion_live_mock(self) -> None:
        calc_v1 = {
            "id": "wf_calc_v32_test",
            "name": "计算器 125*8 验算",
            "goal": "用计算器算 125*8 并断言 1000",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator", "category": "productivity"},
            "parameters": [
                {"name": "expression", "defaultValue": "1,2,5,*,8,return"},
                {"name": "expected_result", "defaultValue": "1000"},
            ],
            "steps": [
                {"step": 1, "action": "activate_app", "title": "激活计算器", "launchIfNeeded": True},
                {"step": 2, "action": "press_shortcut", "title": "自动修复：计算前先连按两次 Escape 彻底清零 (AC)", "combo": "escape", "repeat": 2},
                {"step": 3, "action": "press_shortcut", "title": "键入表达式", "sequence": "1,2,5,*,8,return", "delayMs": 20},
                {"step": 4, "action": "wait_and_read", "title": "回读计算结果", "delaySec": 0.05},
                {"step": 5, "action": "assert_check", "title": "断言计算结果", "evidenceSource": "post_ui_readback", "operator": "contains", "expected": "1000"},
            ],
        }
        self.engine.app_use.save_workflow(calc_v1)

        seen_sequences: List[str] = []

        def fake_calc_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
            cmd = args[0]
            if cmd == "press-key" and "--sequence" in args:
                seen_sequences.append(args[args.index("--sequence") + 1])
                return {"ok": True}
            if cmd == "app-use-inspect":
                out_idx = args.index("--out") + 1 if "--out" in args else -1
                if out_idx != -1:
                    Path(args[out_idx]).parent.mkdir(parents=True, exist_ok=True)
                    Path(args[out_idx]).write_bytes(b"fake")
                result_txt = "100" if seen_sequences and seen_sequences[-1] == "2,5,*,4,return" else "0"
                return {
                    "ok": True,
                    "window": {"bounds": {"x": 0, "y": 0, "width": 300, "height": 420}},
                    "axControls": [],
                    "axTexts": [result_txt],
                    "ocrPreview": result_txt,
                    "ocrElements": [{"text": result_txt, "screenCenter": {"x": 150, "y": 80}}],
                    "savedPath": args[out_idx] if out_idx != -1 else "",
                }
            return {"ok": True}

        with patch.object(self.engine, "_run_native", side_effect=fake_calc_native), patch(
            "wechat_control.app_use_studio.time.sleep", return_value=None
        ):
            edit_res = self.engine.workflow_agent_chat_edit(
                "wf_calc_v32_test",
                "把计算表达式改成 25*4 并把断言改成 100",
                mode="live",
                auto_verify=True,
                confirm_run=True,
                respect_human_guard=False,
            )

        self.assertTrue(edit_res["ok"], edit_res)
        self.assertEqual(edit_res["previousVersion"], 1)
        self.assertEqual(edit_res["newVersion"], 2)
        clear_step = next(s for s in edit_res["workflow"]["steps"] if s.get("action") == "press_shortcut" and s.get("combo") == "escape")
        self.assertNotIn("sequence", clear_step)
        seq_step = next(s for s in edit_res["workflow"]["steps"] if s.get("action") == "press_shortcut" and s.get("sequence"))
        self.assertEqual(seq_step["sequence"], "2,5,*,4,return")
        assert_step = next(s for s in edit_res["workflow"]["steps"] if s.get("action") == "assert_check")
        self.assertEqual(assert_step["expected"], "100")
        params_map = {p["name"]: p["defaultValue"] for p in edit_res["workflow"].get("parameters") or []}
        self.assertEqual(params_map.get("expression"), "2,5,*,4,return")
        self.assertEqual(params_map.get("expected_result"), "100")
        vrun = edit_res["verificationRun"]
        self.assertTrue(vrun["ok"], vrun)
        self.assertEqual(vrun["status"], "verified")
        self.assertEqual(vrun["lastRun"]["evidenceLevel"], "effect_ok")
        self.assertEqual(seen_sequences[-1], "2,5,*,4,return")

    def test_04_hashtag_directives_and_admin_only_gating(self) -> None:
        # Parser unit checks
        p_create = parse_hashtag_directive("#建流程 从飞书提取微信号加微信")
        self.assertTrue(p_create["isDirective"])
        self.assertEqual(p_create["intent"], "workflow_create")
        self.assertEqual(p_create["goal"], "从飞书提取微信号加微信")

        p_create2 = parse_hashtag_directive("#新建流程：汇总飞书待办写文档")
        self.assertEqual(p_create2["intent"], "workflow_create")
        self.assertEqual(p_create2["goal"], "汇总飞书待办写文档")

        p_edit = parse_hashtag_directive("#改流程 把备注前缀改成 飞书大客户-")
        self.assertTrue(p_edit["isDirective"])
        self.assertEqual(p_edit["intent"], "workflow_edit")
        self.assertEqual(p_edit["instruction"], "把备注前缀改成 飞书大客户-")

        p_edit2 = parse_hashtag_directive("#修改流程 第3步之后加一个判断，如果微信号为空就跳过")
        self.assertEqual(p_edit2["intent"], "workflow_edit")

        self.assertTrue(is_blocked_outbound_directive("#建流程 帮我搞个飞书同步"))
        self.assertTrue(is_blocked_outbound_directive("#改流程 把备注前缀改成 VIP-"))

        # External non-admin sender MUST be strictly rejected
        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            ext_create = self.engine.handle_supervisor_hashtag(
                "外部陌生客户",
                "#建流程 从飞书提取微信号加微信，备注用黑客-",
            )
            self.assertFalse(ext_create["ok"])
            self.assertFalse(ext_create["handled"])
            self.assertEqual(ext_create["reason"], "unauthorized_sender")
            self.assertEqual(len(self.engine.app_use._state.get("workflows") or {}), 0)

            ext_edit = self.engine.handle_supervisor_hashtag(
                "普通微信客户A",
                "#改流程 把备注前缀改成 恶意前缀-",
            )
            self.assertFalse(ext_edit["ok"])
            self.assertFalse(ext_edit["handled"])
            self.assertEqual(ext_edit["reason"], "unauthorized_sender")

            # Admin sender ("文件传输助手") succeeds for #建流程 and #改流程
            adm_create = self.engine.handle_supervisor_hashtag(
                "文件传输助手",
                "#建流程 从飞书提取微信号加微信，备注用飞书VIP-，发前需要我确认",
            )
            self.assertTrue(adm_create["ok"], adm_create)
            self.assertTrue(adm_create["handled"])
            self.assertEqual(adm_create["intent"], "workflow_create")
            self.assertEqual(adm_create["workflowResult"]["phase"], "built_and_debugged")
            created_wf_id = adm_create["workflowResult"]["workflow"]["id"]

            adm_edit = self.engine.handle_supervisor_hashtag(
                "文件传输助手",
                f"#改流程 {created_wf_id} 把备注前缀改成 飞书VIP二期-",
            )
            self.assertTrue(adm_edit["ok"], adm_edit)
            self.assertTrue(adm_edit["handled"])
            self.assertEqual(adm_edit["intent"], "workflow_edit")
            self.assertEqual(adm_edit["workflowResult"]["newVersion"], 2)
            self.assertIn(
                "飞书VIP二期-",
                json.dumps(self.engine.app_use._state["workflows"][created_wf_id]["steps"], ensure_ascii=False),
            )

    def test_05_http_mcp_cli_and_web_console_v32(self) -> None:
        # 1. MCP tools
        mcp = WeChatMCPServer(self.engine)
        tools_res = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tool_names = {t["name"] for t in tools_res["result"]["tools"]}
        self.assertIn("workflow_agent_chat_turn", tool_names)
        self.assertIn("workflow_agent_chat_edit", tool_names)

        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            c1 = mcp.handle_request({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "workflow_agent_chat_turn", "arguments": {"message": "帮我搞个飞书同步", "mode": "shadow"}},
            })
            c1_data = json.loads(c1["result"]["content"][0]["text"])
            self.assertTrue(c1_data["ok"])
            self.assertEqual(c1_data["phase"], "clarifying")

            c2 = mcp.handle_request({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "workflow_agent_chat_turn",
                    "arguments": {
                        "chat_id": c1_data["chatId"],
                        "message": "提取微信号加微信，备注用飞书VIP-，发前需要我确认，确认开始调试",
                        "mode": "shadow",
                        "params": {"source_user": "MCP客户", "raw_message": "微信号 wx_mcp_88"},
                    },
                },
            })
            c2_data = json.loads(c2["result"]["content"][0]["text"])
            self.assertTrue(c2_data["ok"], c2_data)
            self.assertEqual(c2_data["phase"], "built_and_debugged")
            mcp_wf_id = c2_data["workflow"]["id"]

            e_mcp = mcp.handle_request({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "workflow_agent_chat_edit",
                    "arguments": {
                        "workflow_id": mcp_wf_id,
                        "instruction": "把备注前缀改成 飞书MCP-",
                        "mode": "shadow",
                        "params": {"source_user": "MCP客户", "raw_message": "微信号 wx_mcp_88"},
                    },
                },
            })
            e_mcp_data = json.loads(e_mcp["result"]["content"][0]["text"])
            self.assertTrue(e_mcp_data["ok"], e_mcp_data)
            self.assertEqual(e_mcp_data["newVersion"], 2)

        # 2. Loopback HTTP endpoints
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/api/workflow-agent/chats?limit=20", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                chats_payload = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(chats_payload["ok"])
                self.assertGreaterEqual(chats_payload["count"], 1)

            with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
                req_chat = urllib.request.Request(
                    f"{base}/api/workflow-agent/chat",
                    data=json.dumps(
                        {
                            "message": "从飞书提取微信号加微信，备注用飞书HTTP-，需要我确认，确认开始调试",
                            "mode": "shadow",
                            "params": {"source_user": "HTTP客户", "raw_message": "加我 wx_http99"},
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_chat, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    http_chat = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(http_chat["ok"])
                    self.assertEqual(http_chat["phase"], "built_and_debugged")
                    http_wf_id = http_chat["workflow"]["id"]

                req_edit = urllib.request.Request(
                    f"{base}/api/workflow-agent/chat-edit",
                    data=json.dumps(
                        {
                            "workflow_id": http_wf_id,
                            "instruction": "把备注前缀改成 飞书HTTP二期-",
                            "mode": "shadow",
                            "params": {"source_user": "HTTP客户", "raw_message": "加我 wx_http99"},
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_edit, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    http_edit = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(http_edit["ok"])
                    self.assertEqual(http_edit["newVersion"], 2)

                # Unsafe edit returns HTTP 400 with unsafe_edit_rejected
                http_steps = http_edit["workflow"]["steps"]
                last_assert_idx = next(i + 1 for i, s in enumerate(http_steps) if s.get("action") == "assert_check")
                req_bad = urllib.request.Request(
                    f"{base}/api/workflow-agent/chat-edit",
                    data=json.dumps({"workflow_id": http_wf_id, "instruction": f"删除第{last_assert_idx}步"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req_bad, timeout=10)
                self.assertEqual(ctx.exception.code, 400)
                bad_body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertFalse(bad_body["ok"])
                self.assertEqual(bad_body["error_code"], "unsafe_edit_rejected")
        finally:
            srv.shutdown()
            srv.server_close()

        # 3. CLI chat and chat-edit smoke (using isolated engine via patch)
        with patch("wechat_control.cli.WeChatControlEngine", return_value=self.engine), patch.object(
            self.engine, "_run_native", side_effect=self._fake_feishu_native
        ):
            buf1 = io.StringIO()
            with redirect_stdout(buf1):
                rc1 = cli_main([
                    "workflow-agent",
                    "--action",
                    "chat",
                    "--message",
                    "从飞书提取微信号加微信，备注用飞书CLI-，发前需要我确认，确认开始调试",
                    "--mode",
                    "shadow",
                    "--params",
                    json.dumps({"source_user": "CLI客户", "raw_message": "微信号 wx_cli77"}, ensure_ascii=False),
                ])
            self.assertEqual(rc1, 0)
            cli_chat_out = json.loads(buf1.getvalue())
            self.assertTrue(cli_chat_out["ok"])
            self.assertEqual(cli_chat_out["phase"], "built_and_debugged")

            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                rc2 = cli_main([
                    "workflow-agent",
                    "--action",
                    "chat-edit",
                    "--workflow-id",
                    cli_chat_out["workflow"]["id"],
                    "--edit-instruction",
                    "把备注前缀改成 飞书CLI二期-",
                    "--mode",
                    "shadow",
                    "--params",
                    json.dumps({"source_user": "CLI客户", "raw_message": "微信号 wx_cli77"}, ensure_ascii=False),
                ])
            self.assertEqual(rc2, 0)
            cli_edit_out = json.loads(buf2.getvalue())
            self.assertTrue(cli_edit_out["ok"])
            self.assertEqual(cli_edit_out["newVersion"], 2)

        # 4. Web Console markers, zero window.confirm(, and node --check on extracted JS
        html = render_web_console_html()
        for marker in (
            "appuseAppGrid",
            "appuseGoalInput",
            "wfagentStudioCard",
            "wfagentDirectPanel",
            "wfagentGoalInput",
            "wfagentChatBox",
            "wfagentChatLog",
            "wfagentChatOptions",
            "wfagentChatInput",
            "wfagentChatSendBtn",
            "wfagentChatResetBtn",
            "wfagentChatHistorySelect",
            "wfagentEditWorkflowSelect",
            "wfagentEditInput",
            "wfagentEditBtn",
            "wfagentEditDiffBox",
            "wfagentEditTargetPill",
            "wfagentUndoLastEdit",
            "wfagent-shadow-preview",
            "WFAGENT_ACTION_LABELS",
            "WFAGENT_PHASE_LABELS",
            "安全体检评分",
            "给CRM加标签",
            "改打招呼话术",
            "抖音引流-",
            "钉钉客户引流加微信",
            "/api/workflow-agent/chat",
            "/api/workflow-agent/chat-edit",
            "/api/workflow-agent/chats",
        ):
            self.assertIn(marker, html)
        self.assertNotIn('placeholder="[抖音]"', html)
        self.assertNotIn("window.confirm(", html)

        node_bin = shutil.which("node") or "/Users/mac/.local/node/node-v24.16.0-darwin-arm64/bin/node"
        if Path(node_bin).exists():
            scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE)
            self.assertGreaterEqual(len(scripts), 1)
            js_file = self.tdir / "web_console_check.js"
            js_file.write_text("\n\n".join(scripts), encoding="utf-8")
            proc = subprocess.run([node_bin, "--check", str(js_file)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_06_multichannel_dingtalk_wecom_chat_generalization(self) -> None:
        # DingTalk -> WeChat + CRM multi-turn chat
        c1 = self.engine.workflow_agent_chat_turn("帮我把钉钉客户提取微信号加微信", mode="shadow")
        self.assertTrue(c1["ok"], c1)
        self.assertEqual(c1["phase"], "clarifying")
        self.assertEqual(c1["collectedConfig"]["targetApps"], ["com.alibaba.DingTalkMac", "com.tencent.xinWeChat"])
        self.assertEqual(c1["collectedConfig"]["targetAppLabels"], ["钉钉", "微信"])

        q_map = {q["id"]: q for q in c1["questions"]}
        self.assertIn("remark_prefix", q_map)
        self.assertIn("备注用钉钉引流-", q_map["remark_prefix"]["options"])
        self.assertIn("confirm_gate", q_map)
        gate_opts = q_map["confirm_gate"]["options"]
        self.assertEqual(len(gate_opts), 3)
        self.assertEqual(len(set(gate_opts)), 3)

        c2 = self.engine.workflow_agent_chat_turn(
            "备注用钉钉引流-，需要人工确认 + 发自报家门话术（推荐）",
            chat_id=c1["chatId"],
            mode="shadow",
        )
        self.assertTrue(c2["ok"], c2)
        self.assertEqual(c2["phase"], "ready_to_build")
        self.assertEqual(c2["spec"]["blueprintId"], "im_to_wechat_crm")
        self.assertEqual(c2["workflow"]["targetApp"]["bundleID"], "com.alibaba.DingTalkMac")

        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            c3 = self.engine.workflow_agent_chat_turn(
                "确认开始调试",
                chat_id=c1["chatId"],
                mode="shadow",
                params={"source_user": "钉钉张总", "raw_message": "你好加我 wx_ding88"},
            )
            self.assertTrue(c3["ok"], c3)
            self.assertEqual(c3["phase"], "built_and_debugged")
            dbg = c3["debugSession"]
            self.assertEqual(dbg["status"], "shadow_verified")
            r0 = dbg["debugRounds"][0]
            self.assertGreaterEqual(len(r0.get("shadowPreviews") or []), 1)
            prev_text = json.dumps(r0["shadowPreviews"], ensure_ascii=False)
            self.assertIn("钉钉引流-", prev_text)
            self.assertIn("钉钉获客", prev_text)
            self.assertNotIn("飞书引流", prev_text)

            # Follow-up Chat-Edit on DingTalk workflow
            ed = self.engine.workflow_agent_chat_edit(
                c3["workflow"]["id"],
                "把备注前缀改成 钉钉大客户-",
                mode="shadow",
                params={"source_user": "钉钉张总", "raw_message": "你好加我 wx_ding88"},
            )
            self.assertTrue(ed["ok"], ed)
            self.assertEqual(ed["newVersion"], 2)
            self.assertIn("钉钉大客户-", json.dumps(ed["verificationRun"]["lastRun"]["shadowPreviews"], ensure_ascii=False))

            # WeCom lead->WeChat single-turn build + WeCom-only digest (no false WeChat detection)
            w_crm = self.engine.workflow_agent_chat_turn(
                "从企业微信提取客户微信号加微信，备注用企微VIP-，需要确认，确认开始调试",
                mode="shadow",
                params={"source_user": "企微李总", "raw_message": "加我 wx_wecom66"},
            )
            self.assertTrue(w_crm["ok"], w_crm)
            self.assertEqual(w_crm["workflow"]["targetApp"]["bundleID"], "com.tencent.WeWorkMac")
            self.assertIn("企微VIP-", json.dumps(w_crm["workflow"]["steps"], ensure_ascii=False))

        w_digest = self.engine.workflow_agent_chat_turn("把企业微信待办汇总写文档", mode="shadow")
        self.assertTrue(w_digest["ok"], w_digest)
        self.assertNotIn("com.tencent.xinWeChat", w_digest["collectedConfig"]["targetApps"])
        self.assertIn("com.tencent.WeWorkMac", w_digest["collectedConfig"]["targetApps"])

    def test_07_multiturn_hashtag_create_continuity_and_reset(self) -> None:
        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            h1 = self.engine.handle_supervisor_hashtag("文件传输助手", "#建流程 帮我搞个飞书同步")
            self.assertTrue(h1["ok"], h1)
            self.assertEqual(h1["workflowResult"]["phase"], "clarifying")
            cid = h1["workflowResult"]["chatId"]
            self.assertEqual(self.engine.workflow_agent.get_contact_active_chat("文件传输助手"), cid)
            self.assertIn("继续发送「#建流程", h1["ackMessage"])

            h2 = self.engine.handle_supervisor_hashtag(
                "文件传输助手",
                "#建流程 提取微信号加微信，备注用飞书多轮-，发前需要我确认",
            )
            self.assertTrue(h2["ok"], h2)
            self.assertEqual(h2["workflowResult"]["chatId"], cid)
            self.assertEqual(h2["workflowResult"]["phase"], "built_and_debugged")
            self.assertEqual(self.engine.workflow_agent.get_contact_active_chat("文件传输助手"), "")
            self.assertIn(
                "飞书多轮-",
                json.dumps(h2["workflowResult"]["workflow"]["steps"], ensure_ascii=False),
            )

            # Reset command drops active clarifying draft
            h3 = self.engine.handle_supervisor_hashtag("文件传输助手", "#建流程 帮我搞个钉钉同步")
            self.assertEqual(h3["workflowResult"]["phase"], "clarifying")
            self.assertTrue(bool(self.engine.workflow_agent.get_contact_active_chat("文件传输助手")))

            h4 = self.engine.handle_supervisor_hashtag("文件传输助手", "#建流程 重置")
            self.assertTrue(h4["ok"], h4)
            self.assertTrue(h4["workflowResult"]["reset"])
            self.assertEqual(self.engine.workflow_agent.get_contact_active_chat("文件传输助手"), "")

    def test_08_chat_edit_rename_crm_tags_stage_and_nl_undo(self) -> None:
        with patch.object(self.engine, "_run_native", side_effect=self._fake_feishu_native):
            built = self.engine.workflow_agent_chat_turn(
                "从钉钉提取客户微信号加微信，备注用钉钉VIP-，发前需要我确认，确认开始调试",
                mode="shadow",
                params={"source_user": "钉钉周总", "raw_message": "微信号 wx_z88"},
            )
            self.assertTrue(built["ok"], built)
            wf_id = built["workflow"]["id"]

            # 1. Rename workflow
            ed_ren = self.engine.workflow_agent_chat_edit(
                wf_id,
                "把当前流程重命名为 钉钉大客户获客",
                mode="shadow",
                params={"source_user": "钉钉周总", "raw_message": "微信号 wx_z88"},
            )
            self.assertTrue(ed_ren["ok"], ed_ren)
            self.assertEqual(ed_ren["newVersion"], 2)
            self.assertEqual(ed_ren["workflow"]["name"], "钉钉大客户获客")

            # 2. Append CRM tag (deduped)
            ed_tag = self.engine.workflow_agent_chat_edit(
                wf_id,
                "给CRM加标签 高意向客户",
                mode="shadow",
                params={"source_user": "钉钉周总", "raw_message": "微信号 wx_z88"},
            )
            self.assertTrue(ed_tag["ok"], ed_tag)
            self.assertEqual(ed_tag["newVersion"], 3)
            crm_step = next(s for s in ed_tag["workflow"]["steps"] if s.get("tool") == "crm_enroll")
            self.assertIn("高意向客户", crm_step["params"]["tags"])
            self.assertEqual(len(crm_step["params"]["tags"]), len(set(crm_step["params"]["tags"])))

            # 3. Change CRM stage using natural alias ("深度跟进" -> "深入沟通")
            ed_stg = self.engine.workflow_agent_chat_edit(
                wf_id,
                "把CRM漏斗阶段改成 深度跟进",
                mode="shadow",
                params={"source_user": "钉钉周总", "raw_message": "微信号 wx_z88"},
            )
            self.assertTrue(ed_stg["ok"], ed_stg)
            self.assertEqual(ed_stg["newVersion"], 4)
            crm_step4 = next(s for s in ed_stg["workflow"]["steps"] if s.get("tool") == "crm_enroll")
            self.assertEqual(crm_step4["params"]["stage"], "深入沟通")

            # 4. Natural-language undo -> restores v3 (stage back to "方案推进", still renamed + tag present)
            ed_undo = self.engine.workflow_agent_chat_edit(wf_id, "撤销上次修改", mode="shadow")
            self.assertTrue(ed_undo["ok"], ed_undo)
            self.assertTrue(ed_undo["rolledBack"])
            crm_step_rb = next(s for s in ed_undo["workflow"]["steps"] if s.get("tool") == "crm_enroll")
            self.assertEqual(crm_step_rb["params"]["stage"], "方案推进")
            self.assertIn("高意向客户", crm_step_rb["params"]["tags"])
            self.assertEqual(ed_undo["workflow"]["name"], "钉钉大客户获客")

            # 5. Admin WeChat hashtag "#改流程 <id> 撤销" -> rolls back to v2 (tag removed, still renamed)
            h_undo = self.engine.handle_supervisor_hashtag("文件传输助手", f"#改流程 {wf_id} 撤销")
            self.assertTrue(h_undo["ok"], h_undo)
            self.assertTrue(h_undo["workflowResult"]["rolledBack"])
            self.assertIn("已撤销并回滚流程", h_undo["ackMessage"])
            crm_step_rb2 = next(
                s for s in h_undo["workflowResult"]["workflow"]["steps"] if s.get("tool") == "crm_enroll"
            )
            self.assertNotIn("高意向客户", crm_step_rb2["params"]["tags"])
            self.assertEqual(h_undo["workflowResult"]["workflow"]["name"], "钉钉大客户获客")

            # 6. Third undo -> rolls back to v1 (original workflow name restored)
            ed_undo3 = self.engine.workflow_agent_chat_edit(wf_id, "撤销", mode="shadow")
            self.assertTrue(ed_undo3["ok"], ed_undo3)
            self.assertEqual(ed_undo3["workflow"]["name"], "钉钉获客引流加微信 + CRM 建档 (自建)")


if __name__ == "__main__":
    unittest.main()
