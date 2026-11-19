"""v2.7.0 升级专项测试：侧栏停止态与批量头像刷新 + 通用 App-Use 2.7 全栈能力。"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_control.auth_gate import ALL_CAPABILITIES
from wechat_control.engine import WeChatControlEngine
from wechat_control.mcp_server import MCP_TOOLS, WeChatMCPServer, create_http_server
from wechat_control.web_console import render_web_console_html


PNG_STUB = b"\x89PNG\r\n\x1a\n" + b"\x00" * 320


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
    engine.auth_grant(ALL_CAPABILITIES, authorized_by="v27-test")
    return engine


class AppUseV27UpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.engine = _make_engine(self.data)

    def tearDown(self) -> None:
        try:
            studio = getattr(self.engine, "app_use", None)
            if studio is not None and studio._rec_thread is not None and studio._rec_thread.is_alive():
                studio._rec_stop_event.set()
                studio._rec_thread.join(timeout=2.0)
        except Exception:
            pass

    def _start_http(self):
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        return f"127.0.0.1", port, f"http://127.0.0.1:{port}"

    def test_01_refresh_avatars_overview_and_http_nocache(self) -> None:
        self.engine.bind_contact("安晓心", role="friend", auto_reply_enabled=True)
        self.engine.bind_contact("微信ClawBot", role="friend", auto_reply_enabled=True)

        ocr_elements = [
            {"text": "安晓心", "bbox": {"x": 116, "y": 200, "width": 44, "height": 12}, "center": {"x": 138, "y": 206}},
            {"text": "你好", "bbox": {"x": 116, "y": 220, "width": 60, "height": 12}, "center": {"x": 146, "y": 226}},
            {"text": "微信ClawBot", "bbox": {"x": 118, "y": 300, "width": 78, "height": 12}, "center": {"x": 157, "y": 306}},
            {"text": "在的", "bbox": {"x": 118, "y": 320, "width": 50, "height": 12}, "center": {"x": 143, "y": 326}},
            {"text": "聊天气泡", "bbox": {"x": 500, "y": 250, "width": 72, "height": 14}, "center": {"x": 536, "y": 257}},
        ]

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd == "capture-ocr":
                out_p = Path(args[args.index("--out") + 1])
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_p.write_bytes(PNG_STUB)
                return {
                    "ok": True,
                    "windowTitle": "微信",
                    "imageWidth": 853,
                    "imageHeight": 1320,
                    "elements": ocr_elements,
                }
            if cmd == "ocr" and "--crop" in args:
                out_p = Path(args[args.index("--out") + 1])
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_p.write_bytes(PNG_STUB)
                return {"ok": True, "savedPath": str(out_p), "elements": []}
            if cmd == "ocr":
                return {"ok": True, "imageWidth": 853, "imageHeight": 1320, "elements": ocr_elements}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        res = self.engine.refresh_avatars(capture_fresh=True)
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["updatedCount"], 2)
        self.assertIn("安晓心", res["avatars"])
        self.assertIn("微信ClawBot", res["avatars"])
        self.assertEqual(res["avatars"]["安晓心"], "/avatars/安晓心.png")
        self.assertGreater(res["avatarVersions"]["安晓心"], 0)

        ov = self.engine.get_web_overview()
        self.assertEqual(ov["avatars"]["安晓心"], "/avatars/安晓心.png")
        self.assertIn("avatarVersions", ov)
        self.assertGreater(ov["avatarVersions"]["安晓心"], 0)

        _, _, base = self._start_http()
        req = urllib.request.Request(
            f"{base}/api/avatars/refresh",
            data=json.dumps({"capture_fresh": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r1:
            self.assertEqual(r1.status, 200)
            body = json.loads(r1.read().decode("utf-8"))
            self.assertTrue(body["ok"])
            self.assertGreaterEqual(body["updatedCount"], 2)

        with urllib.request.urlopen(f"{base}/avatars/%E5%AE%89%E6%99%93%E5%BF%83.png", timeout=10) as r2:
            self.assertEqual(r2.status, 200)
            cc = str(r2.headers.get("Cache-Control") or "")
            self.assertIn("no-store", cc)
            self.assertGreater(len(r2.read()), 200)

    def test_02_web_console_v27_markers_and_no_window_confirm(self) -> None:
        html = render_web_console_html()
        self.assertNotIn("window.confirm(", html)
        required = (
            "isHostingActive",
            "⏸ 已停止",
            "watch-chip.is-paused",
            "refreshAvatarsBtn",
            "refreshSidebarAvatars",
            "AVATAR_CACHE_BUST",
            "appuseSelfHealChk",
            "appuseAutoPatchChk",
            "appuseExportSkill",
            "appuseRollbackCurrent",
            "appuseExplore",
            "appuseStartRecording",
            "appuseStopRecording",
            "appuseRunPipeline",
            "appuseLoadCalcTextEditPreset",
            "/api/app-use/artifact/",
        )
        for marker in required:
            self.assertIn(marker, html, f"Web 控制台缺少 v2.7.0 标记: {marker}")

    def test_03_capture_variables_and_bidi_cleanup(self) -> None:
        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd == "app-use-activate":
                return {"ok": True}
            if cmd == "app-use-inspect":
                if "--out" in args:
                    out_p = Path(args[args.index("--out") + 1])
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_bytes(PNG_STUB)
                is_first = "--skip-ocr" in args
                if is_first:
                    return {
                        "ok": True,
                        "ocrPreview": "Title\nHeader",
                        "axTexts": [],
                        "axControls": [],
                        "savedPath": "",
                    }
                return {
                    "ok": True,
                    "ocrPreview": "Title\nHeader\nNewDiffLine\nTotal: 42",
                    "axTexts": ["\u200e1,024"],
                    "axControls": [],
                    "savedPath": str(self.data / "snap" / "cap_test.png"),
                }
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        wf = {
            "id": "wf_cap_test",
            "name": "Capture Var Test",
            "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator"},
            "steps": [
                {"step": 1, "action": "wait_and_read", "delaySec": 0.05, "captureAs": "v_ax", "extractMode": "ax_last"},
                {"step": 2, "action": "wait_and_read", "delaySec": 0.05, "captureAs": "v_rx", "extractMode": "regex", "extractPattern": r"Total:\s*(\d+)"},
                {"step": 3, "action": "wait_and_read", "delaySec": 0.05, "captureAs": "v_auto", "extractMode": "auto"},
            ],
        }
        res = self.engine.app_use_run_workflow(
            workflow=wf,
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            self_heal=False,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["capturedVars"]["v_ax"], "1,024")
        self.assertEqual(res["capturedVars"]["v_rx"], "42")
        self.assertEqual(res["capturedVars"]["v_auto"], "1,024")

    def test_04_runtime_self_heal_patch_and_rollback(self) -> None:
        clicks = []

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd == "app-use-activate":
                return {"ok": True}
            if cmd == "app-use-inspect":
                return {
                    "ok": True,
                    "axTexts": ["Ready"],
                    "ocrPreview": "Submit Form",
                    "axControls": [
                        {
                            "role": "AXButton",
                            "identifier": "submit_btn",
                            "title": "Submit Form",
                            "description": "Confirm submit",
                            "center": {"x": 320, "y": 410},
                        }
                    ],
                }
            if cmd == "click":
                clicks.append((args[args.index("--x") + 1], args[args.index("--y") + 1]))
                return {"ok": True}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        saved = self.engine.app_use_save_workflow(
            {
                "id": "wf_heal_test",
                "name": "Self Heal Click Workflow",
                "targetApp": {"bundleID": "com.apple.TextEdit", "name": "TextEdit"},
                "steps": [
                    {
                        "step": 1,
                        "action": "click_element",
                        "title": "Click submit button",
                        "targetAxTitle": "Submit Legacy Button",
                    }
                ],
            }
        )
        self.assertTrue(saved["ok"])

        res = self.engine.app_use_run_workflow(
            workflow_id="wf_heal_test",
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            self_heal=True,
            auto_patch_workflow=True,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["workflowPatched"])
        self.assertEqual(len(res["healingEvents"]), 1)
        self.assertEqual(clicks[-1], ("320.0", "410.0"))

        wfs = {w["id"]: w for w in self.engine.app_use_list_workflows()["workflows"]}
        patched_wf = wfs["wf_heal_test"]
        self.assertEqual(patched_wf["version"], 2)
        self.assertEqual(len(patched_wf["revisionHistory"]), 1)
        self.assertEqual(patched_wf["steps"][0]["x"], 320.0)

        rb = self.engine.app_use_rollback_workflow("wf_heal_test", revision_index=-1)
        self.assertTrue(rb["ok"])
        self.assertEqual(rb["workflow"]["version"], 3)
        self.assertNotIn("x", rb["workflow"]["steps"][0])
        self.assertEqual(rb["workflow"]["steps"][0]["targetAxTitle"], "Submit Legacy Button")

    def test_05_explore_and_confirmation_guard(self) -> None:
        self.engine._run_native = lambda args, timeout=15.0: {"ok": True, "axControls": [], "axTexts": []}  # type: ignore[method-assign]
        blocked = self.engine.app_use_explore(
            goal="测试未确认保护",
            bundle_id="com.apple.calculator",
            app_name="Calculator",
            dry_run=False,
            confirm_run=False,
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error_code"], "confirmation_required")

        ok_dry = self.engine.app_use_explore(
            goal="输入 256*4 并读取结果",
            bundle_id="com.apple.calculator",
            app_name="Calculator",
            agent_id="local:heuristic",
            max_turns=3,
            dry_run=True,
            save=True,
        )
        self.assertTrue(ok_dry["ok"])
        self.assertEqual(ok_dry["workflow"]["mode"], "autonomous_explore")
        self.assertGreaterEqual(ok_dry["turns"], 1)

    def test_06_cross_app_pipeline_and_http(self) -> None:
        pasted = []

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd == "app-use-inspect":
                if "--out" in args:
                    p = Path(args[args.index("--out") + 1])
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(PNG_STUB)
                if "com.apple.calculator" in args:
                    return {"ok": True, "axTexts": ["\u200e1,024"], "ocrPreview": "1,024", "savedPath": str(self.data / "snap" / "c.png")}
                return {"ok": True, "axTexts": pasted[:], "ocrPreview": "\n".join(pasted), "savedPath": str(self.data / "snap" / "t.png")}
            if cmd == "app-use-paste":
                txt = args[args.index("--text") + 1]
                pasted.append(txt)
                return {"ok": True, "verified": True, "readbackPreview": txt}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        pipeline_def = {
            "id": "pipe_calc_text_test",
            "name": "Calculator -> TextEdit",
            "stages": [
                {
                    "name": "Calc Stage",
                    "workflow": {
                        "id": "wf_p_calc",
                        "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator"},
                        "steps": [
                            {"step": 1, "action": "activate_app"},
                            {"step": 2, "action": "wait_and_read", "delaySec": 0.05, "captureAs": "calc_result", "extractMode": "ax_last"},
                        ],
                    },
                },
                {
                    "name": "Text Stage",
                    "workflow": {
                        "id": "wf_p_text",
                        "targetApp": {"bundleID": "com.apple.TextEdit", "name": "TextEdit"},
                        "steps": [
                            {"step": 1, "action": "activate_app"},
                            {"step": 2, "action": "focus_and_type", "text": "Result={{calc_result}}"},
                            {"step": 3, "action": "wait_and_read", "delaySec": 0.05, "expectText": "{{calc_result}}"},
                        ],
                    },
                },
            ],
        }

        host, port, base = self._start_http()
        save_res = self.engine.app_use_save_pipeline(pipeline_def)
        self.assertTrue(save_res["ok"])
        self.assertEqual(len(self.engine.app_use_list_pipelines()["pipelines"]), 1)

        req = urllib.request.Request(
            f"{base}/api/app-use/pipelines/run",
            data=json.dumps({"pipeline_id": "pipe_calc_text_test", "dry_run": False, "confirm_run": True, "respect_human_guard": False}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            run_res = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(run_res["ok"])
        self.assertEqual(run_res["stagesExecuted"], 2)
        self.assertEqual(run_res["contextVars"]["calc_result"], "1,024")
        self.assertIn("Result=1,024", pasted[-1])

        del_res = self.engine.app_use_delete_pipeline("pipe_calc_text_test")
        self.assertTrue(del_res["deleted"])

    def test_07_demo_recorder_compile_and_clean_join(self) -> None:
        calls = {"n": 0}

        def fake_native(args, timeout=15.0):
            if args and args[0] == "app-use-focus-snapshot":
                calls["n"] += 1
                if calls["n"] == 1:
                    return {
                        "ok": True,
                        "tsMs": 1000,
                        "bundleID": "com.apple.TextEdit",
                        "name": "TextEdit",
                        "window": {"title": "Untitled"},
                        "hid": {"mouseClickIdleSeconds": 0.1},
                        "elementUnderCursor": {"role": "AXTextArea", "title": "Editor", "identifier": "ed1", "relCenter": {"x": 200, "y": 240}},
                        "focusedElement": {"role": "AXTextArea", "identifier": "ed1", "value": "", "relCenter": {"x": 200, "y": 240}},
                    }
                return {
                    "ok": True,
                    "tsMs": 1300,
                    "bundleID": "com.apple.TextEdit",
                    "name": "TextEdit",
                    "window": {"title": "Untitled"},
                    "hid": {"mouseClickIdleSeconds": 5.0},
                    "elementUnderCursor": {},
                    "focusedElement": {"role": "AXTextArea", "identifier": "ed1", "value": "Recorded Hello", "relCenter": {"x": 200, "y": 240}},
                }
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        st_start = self.engine.app_use_recording_start(max_duration_sec=10.0, poll_interval_sec=0.2)
        self.assertTrue(st_start["ok"])
        self.assertTrue(st_start["active"])
        time.sleep(0.38)
        st_mid = self.engine.app_use_recording_status()
        self.assertGreaterEqual(st_mid["eventCount"], 2)

        compiled = self.engine.app_use_recording_stop_and_compile(goal_hint="文本录入示范", agent_id="local:heuristic", save=True)
        self.assertTrue(compiled["ok"])
        self.assertEqual(compiled["workflow"]["mode"], "recorded_demo")
        self.assertGreaterEqual(compiled["eventCount"], 2)
        self.assertFalse(self.engine.app_use._rec_thread.is_alive())

    def test_08_export_skill_runs_log_and_artifact_security(self) -> None:
        self.engine.app_use_save_workflow(
            {
                "id": "wf_export_demo",
                "name": "Exportable SOP",
                "goal": "Test portable export",
                "targetApp": {"bundleID": "com.apple.Notes", "name": "Notes"},
                "parameters": [{"name": "note_body", "label": "正文", "defaultValue": "Hello", "required": True}],
                "steps": [{"step": 1, "action": "activate_app"}],
            }
        )
        skill_out = self.data / "exported_skill"
        exp = self.engine.app_use_export_skill("wf_export_demo", out_dir=str(skill_out))
        self.assertTrue(exp["ok"])
        skill_md = Path(exp["skillMdPath"])
        wf_json = Path(exp["workflowJsonPath"])
        self.assertTrue(skill_md.is_file())
        self.assertTrue(wf_json.is_file())
        self.assertIn("app_use_run_workflow", skill_md.read_text(encoding="utf-8"))

        # Append a run record and verify list_runs
        self.engine.app_use._append_run_log({"kind": "workflow", "runId": "r1", "workflowName": "Exportable SOP", "ok": True, "dryRun": True})
        runs = self.engine.app_use_list_runs(limit=10)
        self.assertTrue(runs["ok"])
        self.assertGreaterEqual(runs["count"], 1)

        # Place PNG in snapshots_dir/app-use-runs and test /api/app-use/artifact/
        art_dir = self.engine.inspector.snapshots_dir / "app-use-runs"
        art_dir.mkdir(parents=True, exist_ok=True)
        art_name = "v27_unit_artifact_proof.png"
        (art_dir / art_name).write_bytes(PNG_STUB)

        host, port, _ = self._start_http()
        conn = HTTPConnection(host, port, timeout=10)
        self.addCleanup(conn.close)

        conn.request("GET", f"/api/app-use/artifact/{art_name}")
        r_ok = conn.getresponse()
        body_ok = r_ok.read()
        self.assertEqual(r_ok.status, 200)
        self.assertGreater(len(body_ok), 200)

        for bad_path in ("/api/app-use/artifact/..%2Fevil.png", "/api/app-use/artifact/../evil.png", "/api/app-use/artifact/foo.txt"):
            conn.request("GET", bad_path)
            r_bad = conn.getresponse()
            r_bad.read()
            self.assertEqual(r_bad.status, 400, f"应拒绝非法产物路径: {bad_path}")

    def test_09_mcp_tools_v27_registered_and_dispatchable(self) -> None:
        names = {t["name"] for t in MCP_TOOLS}
        for req_name in (
            "app_use_run_workflow",
            "app_use_explore_and_build",
            "app_use_run_pipeline",
            "app_use_record_demo",
            "app_use_export_skill",
        ):
            self.assertIn(req_name, names)

        self.engine._run_native = lambda args, timeout=15.0: {"ok": True, "axControls": [], "axTexts": []}  # type: ignore[method-assign]
        mcp = WeChatMCPServer(self.engine)
        res_rec = mcp._dispatch_tool("app_use_record_demo", {"action": "status"})
        self.assertTrue(res_rec["ok"])

        res_exp = mcp._dispatch_tool(
            "app_use_explore_and_build",
            {"goal": "Test", "bundle_id": "com.apple.calculator", "agent_id": "local:heuristic", "dry_run": True},
        )
        self.assertTrue(res_exp["ok"])


if __name__ == "__main__":
    unittest.main()
