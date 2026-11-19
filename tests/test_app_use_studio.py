"""Unit and loopback integration tests for the v2.6.0 Universal App-Use & Any-Agent SOP Studio."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.app_use_studio import classify_mac_app  # noqa: E402
from wechat_control.auth_gate import ALL_CAPABILITIES  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import WeChatMCPServer, create_http_server  # noqa: E402
from wechat_control.web_console import render_web_console_html  # noqa: E402


class AppUseStudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tdir = Path(self._tmp.name)
        self.http_calls: List[Dict[str, Any]] = []

        def _fake_http(method: str, url: str, *, headers=None, payload=None, timeout=12.0):
            self.http_calls.append({"method": method, "url": url, "payload": payload})
            if url.endswith("/models"):
                return 200, {
                    "data": [
                        {"id": "auto/deepseek-v4.1-flash", "display_name": "DeepSeek V4.1 Flash", "owned_by": "qwen-vip"},
                        {"id": "group/smart-split", "display_name": "Smart Split", "owned_by": "deepseek"},
                    ]
                }
            if url.endswith("/chat/completions"):
                model_used = (payload or {}).get("model", "")
                if model_used == "force-error-model":
                    return 502, {"error": "upstream unavailable"}
                plan = {
                    "name": "计算器自动乘除校验 SOP",
                    "summary": "使用计算器执行 {{expression}} 并回读显示值。",
                    "parameters": [
                        {"name": "expression", "label": "计算序列", "defaultValue": "1,2,5,*,8,return", "required": True, "description": "按键"}
                    ],
                    "preconditions": ["已打开 macOS 计算器"],
                    "safetyGates": ["先 Dry-Run 验证窗口"],
                    "steps": [
                        {"step": 1, "action": "activate_app", "title": "唤醒计算器", "description": "激活", "launchIfNeeded": True},
                        {"step": 2, "action": "press_shortcut", "title": "输入表达式", "description": "按键", "sequence": "{{expression}}", "delayMs": 60},
                        {"step": 3, "action": "wait_and_read", "title": "回读结果", "description": "OCR", "delaySec": 0.1, "expectText": "1000"},
                    ],
                    "verification": "读取 1000",
                    "sopMarkdown": "# SOP：计算器自动乘除校验\n\n1. 唤醒计算器\n2. 输入 `{{expression}}`\n3. 回读校验 `1000`",
                }
                return 200, {
                    "choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}],
                    "usage": {"total_tokens": 180},
                }
            return 404, {"error": "not found"}

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
            model_http_requester=_fake_http,
        )
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="unit-test")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_app_classification_and_native_list_mac_apps(self) -> None:
        self.assertEqual(classify_mac_app("com.openai.codex", "ChatGPT")["category"], "agent_app")
        self.assertTrue(classify_mac_app("com.bytedance.doubao", "Doubao")["isAgentApp"])
        self.assertTrue(classify_mac_app("app.openbot.desktop", "Bot Studio")["selfOrHost"])
        self.assertEqual(classify_mac_app("com.apple.calculator", "Calculator")["category"], "productivity")
        self.assertEqual(classify_mac_app("com.alibaba.DingTalkMac", "DingTalk")["category"], "im_social")

        if self.engine.binary_path.is_file():
            res = self.engine.app_use_list_apps(include_installed=True)
            self.assertTrue(res["ok"], res)
            self.assertGreaterEqual(res["totalCount"], 5)
            bids = {str(a.get("bundleID") or "") for a in res["apps"]}
            self.assertTrue(any(b in bids for b in ("com.apple.TextEdit", "com.apple.calculator", "com.apple.finder")))

    def test_list_builder_agents_and_build_sop_with_magpie_and_fallback(self) -> None:
        agents_res = self.engine.app_use_list_agents(refresh_models=True)
        self.assertTrue(agents_res["ok"])
        agent_ids = {a["id"] for a in agents_res["agents"]}
        self.assertIn("magpie:auto/deepseek-v4.1-flash", agent_ids)
        self.assertIn("local:heuristic", agent_ids)

        # Build with Magpie LLM Agent (no live activation during offline unit test)
        res = self.engine.app_use_build_sop(
            "计算 125 乘以 8 并校验结果",
            bundle_id="com.apple.calculator",
            app_name="Calculator",
            agent_id="magpie:auto/deepseek-v4.1-flash",
            inspect_live=False,
            save=True,
        )
        self.assertTrue(res["ok"], res)
        wf = res["workflow"]
        self.assertFalse(wf["builderAgent"]["usedFallback"])
        self.assertEqual(wf["targetApp"]["bundleID"], "com.apple.calculator")
        self.assertEqual(len(wf["steps"]), 3)
        self.assertIn("计算器", res["sopMarkdown"])

        # Fallback when chosen LLM errors out
        fb = self.engine.app_use_build_sop(
            "向豆包提问总结日报并等待输出稳定",
            bundle_id="com.bytedance.doubao",
            app_name="Doubao",
            agent_id="magpie:force-error-model",
            inspect_live=False,
            save=True,
        )
        self.assertTrue(fb["ok"], fb)
        self.assertTrue(fb["workflow"]["builderAgent"]["usedFallback"])
        self.assertIn("unavailable", fb["workflow"]["builderAgent"]["fallbackReason"])
        self.assertTrue(fb["workflow"]["targetApp"]["isAgentApp"])
        actions = [s["action"] for s in fb["workflow"]["steps"]]
        self.assertIn("focus_and_type", actions)
        self.assertIn("wait_and_read", actions)
        wait_step = next(s for s in fb["workflow"]["steps"] if s["action"] == "wait_and_read")
        self.assertTrue(wait_step.get("waitUntilStable"))

        # Knowledge base export & search (internal SOP stored with external=False)
        kb_res = self.engine.app_use_export_sop_to_kb(wf["id"])
        self.assertTrue(kb_res["ok"])
        search = self.engine.kb_search("计算器", library="shared", external_only=False)
        self.assertGreaterEqual(search["count"], 1)

    def test_cli_agent_adapter_and_heuristic_textedit_plan(self) -> None:
        cli_plan = {
            "name": "TextEdit 纪要归档 SOP",
            "summary": "打开 TextEdit 并写入会议纪要",
            "parameters": [{"name": "content", "label": "纪要", "defaultValue": "测试纪要", "required": True}],
            "steps": [
                {"step": 1, "action": "activate_app", "title": "唤醒 TextEdit", "launchIfNeeded": True},
                {"step": 2, "action": "press_shortcut", "title": "新建文档", "combo": "cmd+n"},
                {"step": 3, "action": "focus_and_type", "title": "贴入纪要", "text": "{{content}}"},
            ],
            "sopMarkdown": "# SOP: TextEdit\n\n1. 新建文档\n2. 写入 `{{content}}`",
        }
        self.engine.app_use._cli_runner = lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(cli_plan, ensure_ascii=False), stderr=""
        )
        orig_which = self.engine.app_use._find_cli_binary
        self.engine.app_use._find_cli_binary = lambda name: "/Users/mac/.local/bin/gemini-api" if name == "gemini-api" else orig_which(name)

        res = self.engine.app_use_build_sop(
            "写会议纪要",
            bundle_id="com.apple.TextEdit",
            app_name="TextEdit",
            agent_id="cli:gemini-api",
            inspect_live=False,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["workflow"]["builderAgent"]["kind"], "cli_agent")
        self.assertFalse(res["workflow"]["builderAgent"]["usedFallback"])
        self.assertEqual(res["workflow"]["steps"][1]["combo"], "cmd+n")

    def test_run_workflow_dry_run_live_execution_and_safety_gates(self) -> None:
        native_calls: List[List[str]] = []
        poll_counter = {"n": 0}

        def _fake_native(args: List[str], timeout: float = 15.0) -> Dict[str, Any]:
            native_calls.append(list(args))
            cmd = args[0] if args else ""
            if cmd == "app-use-inspect":
                poll_counter["n"] += 1
                ocr_txt = "正在生成..." if poll_counter["n"] == 1 else "最终答案：私有化部署三步走完成"
                return {
                    "ok": True,
                    "bundleID": "com.bytedance.doubao",
                    "name": "Doubao",
                    "window": {"windowID": 99, "title": "Doubao", "bounds": {"x": 100.0, "y": 100.0, "width": 800.0, "height": 600.0}},
                    "axControlCount": 2,
                    "axControls": [
                        {"role": "AXButton", "identifier": "new_chat_btn", "title": "新对话", "center": {"x": 160.0, "y": 160.0}},
                        {"role": "AXTextArea", "identifier": "prompt_box", "title": "输入框", "center": {"x": 500.0, "y": 620.0}},
                    ],
                    "ocrCount": 1,
                    "ocrElements": [{"text": ocr_txt, "screenCenter": {"x": 450.0, "y": 350.0}}],
                    "axTexts": [ocr_txt],
                    "ocrPreview": ocr_txt,
                    "savedPath": "/Volumes/SanDisk/Builds/WeChatBot/app-use-verify/mock.png",
                }
            if cmd == "app-use-activate":
                return {"ok": True, "bundleID": "com.bytedance.doubao", "isFrontmost": True}
            if cmd == "click":
                return {"ok": True, "x": 160.0, "y": 160.0}
            if cmd == "app-use-paste":
                return {"ok": True, "verified": True, "submitted": True, "readbackSource": "ax", "readbackPreview": "测试问题"}
            if cmd == "press-key":
                return {"ok": True, "posted": ["cmd+k"]}
            if cmd == "hid-idle":
                return {"ok": True, "hidIdle": {"anyInputIdleSeconds": 999.0, "mouseIdleSeconds": 999.0, "keyboardIdleSeconds": 999.0}}
            return {"ok": True}

        self.engine._run_native = _fake_native  # type: ignore[method-assign]

        wf = {
            "id": "wf_doubao_test",
            "name": "Doubao 自动问答测试",
            "targetApp": {"bundleID": "com.bytedance.doubao", "name": "Doubao", "isAgentApp": True},
            "parameters": [{"name": "prompt", "label": "问题", "defaultValue": "默认问题"}],
            "steps": [
                {"step": 1, "action": "activate_app", "title": "激活", "launchIfNeeded": True},
                {"step": 2, "action": "click_element", "title": "点新对话", "targetAxId": "new_chat_btn"},
                {"step": 3, "action": "focus_and_type", "title": "输入问题", "targetAxId": "prompt_box", "text": "{{prompt}}", "submitAfter": True},
                {"step": 4, "action": "wait_and_read", "title": "等回复稳定", "delaySec": 0.05, "waitUntilStable": True, "pollIntervalSec": 0.5, "maxWaitSec": 3.0, "expectText": "私有化部署"},
                {"step": 5, "action": "pause_for_human", "title": "人工确认", "message": "请复核回答"},
            ],
        }

        # Live without confirm_run must fail-closed
        blocked = self.engine.app_use_run_workflow(workflow=wf, dry_run=False, confirm_run=False)
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error_code"], "confirmation_required")

        # Dry-run resolves dynamic AX coordinates without clicking
        dry = self.engine.app_use_run_workflow(workflow=wf, params={"prompt": "真实测试问题"}, dry_run=True)
        self.assertTrue(dry["ok"], dry)
        self.assertTrue(dry["dryRun"])
        self.assertEqual(dry["stepResults"][1]["resolvedPoint"], {"x": 160.0, "y": 160.0})
        self.assertEqual(dry["stepResults"][1]["resolutionSource"], "ax_id:new_chat_btn")
        self.assertFalse(any(c[0] in ("click", "app-use-paste", "press-key") for c in native_calls))

        # Live run executes steps, polls wait_and_read until OCR stabilizes, pauses cleanly at pause_for_human
        live = self.engine.app_use_run_workflow(
            workflow=wf,
            params={"prompt": "测试问题"},
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
        )
        self.assertTrue(live["ok"], live)
        self.assertTrue(live["pausedForHuman"])
        self.assertEqual(live["stepsExecuted"], 5)
        self.assertIn("最终答案", live["finalReadback"]["ocrPreview"])
        self.assertTrue(live["stepResults"][3]["matchedExpectation"])
        self.assertGreaterEqual(live["stepResults"][3]["polls"], 2)

        # HumanActivityGuard blocks live run when human was just active
        self.engine.human_guard._state["cooldown_until"] = 9999999999.0
        self.engine.human_guard._state["enabled"] = True
        guarded = self.engine.app_use_run_workflow(
            workflow=wf,
            dry_run=False,
            confirm_run=True,
            respect_human_guard=True,
        )
        self.assertFalse(guarded["ok"])
        self.assertEqual(guarded["error_code"], "human_activity_guard_paused")

    def test_mcp_http_and_web_console_app_use_integration(self) -> None:
        mcp = WeChatMCPServer(self.engine)
        tools_res = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tool_names = {t["name"] for t in tools_res["result"]["tools"]}
        for tname in (
            "app_use_list_apps",
            "app_use_list_agents",
            "app_use_inspect",
            "app_use_build_sop",
            "app_use_run_workflow",
        ):
            self.assertIn(tname, tool_names)

        build_call = mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "app_use_build_sop",
                    "arguments": {
                        "goal": "打开 TextEdit 写入日报",
                        "bundle_id": "com.apple.TextEdit",
                        "app_name": "TextEdit",
                        "agent_id": "local:heuristic",
                        "inspect_live": False,
                    },
                },
            }
        )
        b_payload = json.loads(build_call["result"]["content"][0]["text"])
        self.assertTrue(b_payload["ok"])
        wf_id = b_payload["workflow"]["id"]

        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            base = f"http://127.0.0.1:{port}"
            for ep in ("/api/app-use/agents", "/api/app-use/workflows"):
                with urllib.request.urlopen(f"{base}{ep}", timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(data["ok"])

            req = urllib.request.Request(
                f"{base}/api/app-use/run",
                data=json.dumps({"workflow_id": wf_id, "dry_run": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                rbody = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(rbody["ok"])
                self.assertTrue(rbody["dryRun"])
        finally:
            srv.shutdown()
            srv.server_close()

        html = render_web_console_html()
        self.assertIn('id="tab-appuse"', html)
        self.assertIn('data-tab="appuse"', html)
        self.assertIn("/api/app-use/build-sop", html)
        self.assertIn("/api/app-use/run", html)
        self.assertNotIn("window.confirm(", html)


if __name__ == "__main__":
    unittest.main()
