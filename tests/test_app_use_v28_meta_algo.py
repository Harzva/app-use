"""v2.8.0 算法与并发引擎专项测试：5大元能力算法 + 全局 Meta Skill + 多窗口并发安全。"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_control.app_use_meta_algo import (
    AppUIStateGraph,
    SemanticElementGrounder,
    classify_step_failure,
    compute_lexical_similarity,
    compute_ui_state,
    detect_modal_blocker,
    diff_ui_states,
    infer_app_archetype,
    optimize_and_enrich_steps,
    score_workflow_readiness,
)
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
    engine.auth_grant(ALL_CAPABILITIES, authorized_by="v28-test")
    return engine


class AppUseV28MetaAlgoTests(unittest.TestCase):
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

    def test_01_semantic_grounder_bilingual_spatial_neighbor_and_bundle(self) -> None:
        self.assertGreaterEqual(compute_lexical_similarity("Submit", "发送"), 0.85)
        self.assertGreaterEqual(compute_lexical_similarity("发送消息", "发送"), 0.70)

        inspection = {
            "ok": True,
            "window": {"bounds": {"x": 0, "y": 0, "width": 1000, "height": 800}},
            "axControls": [
                {
                    "role": "AXButton",
                    "identifier": "ok_top",
                    "title": "确定",
                    "center": {"x": 200, "y": 160},
                    "relCenter": {"x": 0.2, "y": 0.2},
                    "bounds": {"x": 160, "y": 145, "width": 80, "height": 30},
                },
                {
                    "role": "AXStaticText",
                    "title": "金额",
                    "center": {"x": 700, "y": 600},
                    "relCenter": {"x": 0.70, "y": 0.75},
                    "bounds": {"x": 680, "y": 590, "width": 40, "height": 20},
                },
                {
                    "role": "AXStaticText",
                    "title": "备注",
                    "center": {"x": 820, "y": 600},
                    "relCenter": {"x": 0.82, "y": 0.75},
                    "bounds": {"x": 800, "y": 590, "width": 40, "height": 20},
                },
                {
                    "role": "AXButton",
                    "identifier": "ok_bottom",
                    "title": "发送",
                    "center": {"x": 760, "y": 650},
                    "relCenter": {"x": 0.76, "y": 0.8125},
                    "bounds": {"x": 720, "y": 635, "width": 80, "height": 30},
                },
            ],
            "ocrElements": [],
        }

        # Bilingual EN query + spatial prior + relational neighborTexts
        step = {
            "action": "click_element",
            "targetAxTitle": "Submit",
            "relX": 0.75,
            "relY": 0.80,
            "neighborTexts": ["金额", "备注"],
        }
        res = SemanticElementGrounder.resolve_best(step, inspection, min_score=0.38)
        self.assertTrue(res["ok"])
        self.assertEqual(res["point"], (760.0, 650.0))
        self.assertGreater(res["margin"], 0.05)
        bundle = res["anchorBundle"]
        self.assertEqual(bundle["targetAxId"], "ok_bottom")
        self.assertIn("金额", bundle["neighborTexts"])
        self.assertIn("备注", bundle["neighborTexts"])

        # Neighbor-only disambiguation even when duplicate buttons share exact title & no relX/relY
        dup_insp = {
            "ok": True,
            "window": {"bounds": {"x": 0, "y": 0, "width": 1000, "height": 800}},
            "axControls": [
                {"role": "AXButton", "identifier": "b1", "title": "确认", "center": {"x": 200, "y": 150}, "relCenter": {"x": 0.2, "y": 0.19}},
                {"role": "AXStaticText", "title": "发票总额", "center": {"x": 200, "y": 600}, "relCenter": {"x": 0.2, "y": 0.75}},
                {"role": "AXButton", "identifier": "b2", "title": "确认", "center": {"x": 200, "y": 640}, "relCenter": {"x": 0.2, "y": 0.80}},
            ],
        }
        res_dup = SemanticElementGrounder.resolve_best(
            {"action": "click_element", "targetAxTitle": "确认", "neighborTexts": ["发票总额"]},
            dup_insp,
            min_score=0.38,
        )
        self.assertTrue(res_dup["ok"])
        self.assertEqual(res_dup["point"], (200.0, 640.0))

    def test_02_modal_detection_ui_state_diff_and_all_6_archetypes(self) -> None:
        self.assertEqual(
            detect_modal_blocker({"ocrPreview": "请扫码登录账号或输入密码"})["kind"],
            "auth_or_risk_gate",
        )
        self.assertTrue(
            detect_modal_blocker({"ocrPreview": "Sign in to continue"})["requiresHuman"]
        )
        self.assertEqual(
            detect_modal_blocker({"ocrPreview": "发现新版本 3.0，是否更新？稍后提醒"})["kind"],
            "dismissible_modal",
        )
        # Ensure ordinary ChatGPT prompt wording ("输入提示词") does not false-trigger modal
        self.assertEqual(
            detect_modal_blocker({"ocrPreview": "请输入提示词以生成代码", "window": {"title": "ChatGPT"}})["kind"],
            "none",
        )

        s1 = compute_ui_state({"bundleID": "com.example.App", "window": {"title": "Home"}, "axTexts": ["Alpha", "Beta"]})
        s2 = compute_ui_state({"bundleID": "com.example.App", "window": {"title": "Result"}, "axTexts": ["Alpha", "Gamma"]})
        diff = diff_ui_states(s1, s2)
        self.assertTrue(diff["stateChanged"])
        self.assertTrue(diff["titleChanged"])
        self.assertIn("Gamma", diff["addedTexts"])
        self.assertIn("Beta", diff["removedTexts"])

        # All 6 topology-only archetypes (zero app-name hardcoding)
        self.assertEqual(
            infer_app_archetype({"axControlCount": 2, "ocrCount": 8, "inputElements": [], "axControls": []})["id"],
            "canvas_or_opaque",
        )
        self.assertEqual(
            infer_app_archetype({
                "window": {"bounds": {"width": 1000, "height": 800}},
                "inputElements": [{"role": "AXTextArea", "bounds": {"width": 900, "height": 600}, "relCenter": {"x": 0.5, "y": 0.5}}],
                "axControls": [{"role": "AXTextArea", "relCenter": {"x": 0.5, "y": 0.5}}],
            })["id"],
            "document_editor",
        )
        self.assertEqual(
            infer_app_archetype({
                "window": {"bounds": {"width": 1000, "height": 800}},
                "inputElements": [{"role": "AXTextArea", "bounds": {"width": 600, "height": 70}, "relCenter": {"x": 0.5, "y": 0.88}}],
                "axControls": [{"role": "AXScrollArea", "relCenter": {"x": 0.5, "y": 0.4}}],
            })["id"],
            "chat_agent_surface",
        )
        self.assertEqual(
            infer_app_archetype({
                "buttonElements": [{"role": "AXButton"} for _ in range(12)],
                "axTexts": ["0"],
                "inputElements": [],
                "axControls": [{"role": "AXButton"} for _ in range(12)],
            })["id"],
            "keypad_or_tool",
        )
        self.assertEqual(
            infer_app_archetype({
                "inputElements": [],
                "axControls": [
                    *[{"role": "AXCell", "relCenter": {"x": 0.15, "y": 0.2 + i * 0.1}} for i in range(4)],
                    *[{"role": "AXStaticText", "relCenter": {"x": 0.65, "y": 0.3 + i * 0.1}} for i in range(3)],
                ],
            })["id"],
            "list_detail_master",
        )
        self.assertEqual(
            infer_app_archetype({
                "inputElements": [
                    {"role": "AXSearchField", "bounds": {"width": 200, "height": 28}, "relCenter": {"x": 0.5, "y": 0.08}},
                    {"role": "AXTextField", "bounds": {"width": 200, "height": 28}, "relCenter": {"x": 0.5, "y": 0.25}},
                ],
                "axControls": [{"role": "AXSearchField", "relCenter": {"x": 0.5, "y": 0.08}}],
            })["id"],
            "form_workbench",
        )

    def test_03_state_graph_persistence_suggestions_and_http(self) -> None:
        gp = self.data / "graph.json"
        g = AppUIStateGraph(gp)
        s1 = {"stateHash": "h_home", "windowTitle": "Home", "modalStatus": {"kind": "none"}}
        s2 = {"stateHash": "h_detail", "windowTitle": "Detail", "modalStatus": {"kind": "none"}}
        g.record_transition("com.example.App", "Example", s1, "click_element:Search", s2, ok=True, latency_ms=140.0, archetype_id="form_workbench")

        g2 = AppUIStateGraph(gp)
        edges = g2.suggest_known_transitions("com.example.App", "h_home")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["toHash"], "h_detail")
        self.assertEqual(g2.summary()["totalEdges"], 1)

        # HTTP GET /api/app-use/state-graph via engine's state_graph
        self.engine.app_use.state_graph.record_transition("com.example.App", "Example", s1, "click_element:Go", s2, ok=True)
        base = self._start_http()
        with urllib.request.urlopen(f"{base}/api/app-use/state-graph?bundle_id=com.example.App", timeout=10) as r:
            self.assertEqual(r.status, 200)
            body = json.loads(r.read().decode("utf-8"))
        self.assertTrue(body["ok"])
        self.assertEqual(body["edgeCount"], 1)

    def test_04_trajectory_optimize_and_readiness_scoring(self) -> None:
        insp = {
            "ok": True,
            "window": {"bounds": {"x": 0, "y": 0, "width": 1000, "height": 800}},
            "axControls": [
                {"role": "AXStaticText", "title": "Query", "center": {"x": 180, "y": 100}, "relCenter": {"x": 0.18, "y": 0.125}},
                {"role": "AXSearchField", "identifier": "search_box", "title": "Search", "center": {"x": 300, "y": 100}, "relCenter": {"x": 0.30, "y": 0.125}},
            ],
        }
        raw_steps = [
            {"step": 1, "action": "activate_app", "title": "Activate 1"},
            {"step": 2, "action": "activate_app", "title": "Activate dup"},
            {"step": 3, "action": "click_element", "title": "Dead click"},
            {"step": 4, "action": "focus_and_type", "title": "Type query", "targetAxTitle": "Search", "text": "{{q}}"},
            {"step": 5, "action": "wait_and_read", "title": "Read result", "captureAs": "ans", "waitUntilChanged": True},
        ]
        opt = optimize_and_enrich_steps(
            raw_steps,
            inspection=insp,
            transition_logs=[{"stepIndex": 3, "stateChanged": False}],
        )
        self.assertEqual(len(opt), 3)
        self.assertEqual([s["action"] for s in opt], ["activate_app", "focus_and_type", "wait_and_read"])
        self.assertEqual(opt[1]["targetAxId"], "search_box")
        self.assertIn("Query", opt[1]["neighborTexts"])

        wf_good = {
            "steps": opt,
            "parameters": [{"name": "q"}],
            "safetyGates": ["HumanActivityGuard"],
            "uiProfileSnapshot": {"windowBounds": {"width": 1000}},
            "archetype": {"id": "form_workbench"},
        }
        wf_weak = {"steps": [{"step": 1, "action": "click_element", "x": 10, "y": 10}]}
        r_good = score_workflow_readiness(wf_good)
        r_weak = score_workflow_readiness(wf_weak)
        self.assertGreaterEqual(r_good["score"], 85.0)
        self.assertEqual(r_good["grade"], "A")
        self.assertLess(r_weak["score"], 50.0)

    def test_05_failure_taxonomy_self_healing_all_paths(self) -> None:
        # 1) Direct taxonomy unit checks
        c_front = classify_step_failure({"action": "focus_and_type"}, "Aborted: frontmost app is 'Finder', expected TextEdit", {})
        self.assertEqual(c_front["category"], "NOT_FRONTMOST")
        c_auth = classify_step_failure({"action": "click_element"}, "unresolved", {"ocrPreview": "请扫码登录以继续"})
        self.assertEqual(c_auth["category"], "AUTH_GATE")
        c_modal = classify_step_failure({"action": "click_element"}, "unresolved", {"ocrPreview": "软件更新可用，稍后提醒"})
        self.assertEqual(c_modal["category"], "MODAL_OCCLUSION")

        # 2) Live run integration: AUTH_GATE safely sets pausedForHuman=True
        self.engine._run_native = lambda args, timeout=15.0: {  # type: ignore[method-assign]
            "ok": True,
            "axControls": [],
            "ocrElements": [],
            "ocrPreview": "请扫码登录账号",
            "axTexts": ["请扫码登录"],
        }
        res_auth = self.engine.app_use_run_workflow(
            workflow={
                "id": "wf_auth_test",
                "targetApp": {"bundleID": "com.example.App", "name": "Example"},
                "steps": [{"step": 1, "action": "click_element", "targetAxTitle": "Send"}],
            },
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            self_heal=True,
        )
        self.assertTrue(res_auth["ok"])
        self.assertTrue(res_auth["pausedForHuman"])
        self.assertEqual(res_auth["healingEvents"][0]["failureCategory"], "AUTH_GATE")

        # 3) Live run integration: NOT_FRONTMOST triggers reactivate_and_retry and succeeds
        paste_calls = {"n": 0, "activated": 0}

        def fake_reactivate(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd == "app-use-activate":
                paste_calls["activated"] += 1
                return {"ok": True}
            if cmd == "app-use-inspect":
                return {"ok": True, "axControls": [{"role": "AXTextField", "identifier": "q", "title": "Search", "center": {"x": 200, "y": 80}}], "ocrElements": []}
            if cmd == "app-use-paste":
                paste_calls["n"] += 1
                if paste_calls["n"] == 1:
                    return {"ok": False, "error": "Aborted: frontmost app is 'ego lite', expected Dictionary."}
                return {"ok": True, "verified": True}
            return {"ok": True}

        self.engine._run_native = fake_reactivate  # type: ignore[method-assign]
        res_re = self.engine.app_use_run_workflow(
            workflow={
                "id": "wf_re_test",
                "targetApp": {"bundleID": "com.apple.Dictionary", "name": "Dictionary"},
                "steps": [{"step": 1, "action": "focus_and_type", "text": "hello", "targetAxTitle": "Search"}],
            },
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            self_heal=True,
        )
        self.assertTrue(res_re["ok"])
        self.assertEqual(paste_calls["n"], 2)
        self.assertGreaterEqual(paste_calls["activated"], 1)
        self.assertEqual(res_re["healingEvents"][0]["failureCategory"], "NOT_FRONTMOST")

        # 4) MODAL_OCCLUSION dismisses Escape modal then resolves drifted button
        modal_state = {"dismissed": False}

        def fake_modal(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd == "press-key" and "--combo" in args and "escape" in args:
                modal_state["dismissed"] = True
                return {"ok": True}
            if cmd == "app-use-inspect":
                if not modal_state["dismissed"]:
                    return {"ok": True, "axControls": [], "ocrElements": [], "ocrPreview": "发现新版本，稍后提醒"}
                return {
                    "ok": True,
                    "ocrPreview": "Compose",
                    "axControls": [{"role": "AXButton", "identifier": "btn_go", "title": "Send", "center": {"x": 450, "y": 500}}],
                }
            return {"ok": True}

        self.engine._run_native = fake_modal  # type: ignore[method-assign]
        res_modal = self.engine.app_use_run_workflow(
            workflow={
                "id": "wf_modal_test",
                "targetApp": {"bundleID": "com.example.App", "name": "App"},
                "steps": [{"step": 1, "action": "click_element", "targetAxTitle": "Send"}],
            },
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            self_heal=True,
        )
        self.assertTrue(res_modal["ok"])
        self.assertTrue(modal_state["dismissed"])

    def test_06_wait_until_changed_polling(self) -> None:
        inspect_calls = {"n": 0}

        def fake_chg(args, timeout=15.0):
            if args and args[0] == "app-use-inspect":
                inspect_calls["n"] += 1
                if inspect_calls["n"] <= 2:
                    return {"ok": True, "axTexts": ["\u200e256×4"], "ocrPreview": "256×4"}
                return {"ok": True, "axTexts": ["\u200e1,024"], "ocrPreview": "1,024"}
            return {"ok": True}

        self.engine._run_native = fake_chg  # type: ignore[method-assign]
        res = self.engine.app_use_run_workflow(
            workflow={
                "id": "wf_chg_test",
                "targetApp": {"bundleID": "com.apple.calculator", "name": "Calculator"},
                "steps": [
                    {"step": 1, "action": "inspect_ui", "title": "Pre-state"},
                    {
                        "step": 2,
                        "action": "wait_and_read",
                        "delaySec": 0.02,
                        "pollIntervalSec": 0.05,
                        "maxWaitSec": 2.0,
                        "waitUntilChanged": True,
                        "captureAs": "res",
                        "extractMode": "ax_last",
                    },
                ],
            },
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            self_heal=False,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["capturedVars"]["res"], "1,024")
        self.assertGreaterEqual(res["stepResults"][1]["polls"], 2)

    def test_07_explore_cycle_breaker(self) -> None:
        self.engine._run_native = lambda args, timeout=15.0: {  # type: ignore[method-assign]
            "ok": True,
            "bundleID": "com.example.Loop",
            "window": {"title": "Static", "bounds": {"x": 0, "y": 0, "width": 800, "height": 600}},
            "axControls": [{"role": "AXButton", "identifier": "b", "title": "LoopBtn", "center": {"x": 400, "y": 300}, "relCenter": {"x": 0.5, "y": 0.5}}],
            "axTexts": ["Static"],
            "ocrElements": [],
            "ocrPreview": "Static",
        }
        # Mock models to always propose the same stagnant click step
        self.engine.models.generate_chat_reply = lambda *a, **k: {  # type: ignore[method-assign]
            "ok": True,
            "replyText": json.dumps({"done": False, "reason": "repeat", "nextStep": {"action": "click_element", "targetAxTitle": "LoopBtn"}}),
        }
        res = self.engine.app_use_explore(
            goal="Loop test",
            bundle_id="com.example.Loop",
            app_name="Loop",
            agent_id="magpie:test-model",
            max_turns=6,
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            save=False,
        )
        self.assertTrue(res["ok"])
        self.assertLessEqual(res["turns"], 3)

    def test_08_generalize_new_app_and_http_ground_preview(self) -> None:
        unseen_inspect = {
            "ok": True,
            "bundleID": "com.example.UnseenERP",
            "name": "Unseen ERP",
            "appPath": "/Applications/UnseenERP.app",
            "window": {"title": "Order Search", "bounds": {"x": 100, "y": 100, "width": 900, "height": 700}},
            "axControlCount": 3,
            "ocrCount": 3,
            "axControls": [
                {"role": "AXSearchField", "identifier": "erp_search", "title": "Search Orders", "center": {"x": 350, "y": 160}, "relCenter": {"x": 0.278, "y": 0.086}},
                {"role": "AXButton", "identifier": "erp_go", "title": "查询", "center": {"x": 550, "y": 160}, "relCenter": {"x": 0.50, "y": 0.086}},
            ],
            "inputElements": [{"role": "AXSearchField", "identifier": "erp_search", "title": "Search Orders", "center": {"x": 350, "y": 160}, "relCenter": {"x": 0.278, "y": 0.086}}],
            "buttonElements": [{"role": "AXButton", "identifier": "erp_go", "title": "查询", "center": {"x": 550, "y": 160}, "relCenter": {"x": 0.50, "y": 0.086}}],
            "axTexts": ["Order #1029"],
            "ocrElements": [{"text": "Order #1029", "screenCenter": {"x": 350, "y": 300}, "relCenter": {"x": 0.278, "y": 0.286}}],
            "ocrPreview": "Order #1029",
        }
        self.engine._run_native = lambda args, timeout=15.0: unseen_inspect  # type: ignore[method-assign]
        base = self._start_http()

        req = urllib.request.Request(
            f"{base}/api/app-use/generalize",
            data=json.dumps({
                "goal": "搜索订单编号并读取详情",
                "bundle_id": "com.example.UnseenERP",
                "app_name": "Unseen ERP",
                "agent_id": "local:heuristic",
                "dry_run_verify": True,
                "export_skill": False,
                "save": True,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r1:
            gen = json.loads(r1.read().decode("utf-8"))
        self.assertTrue(gen["ok"])
        self.assertEqual(gen["archetype"]["id"], "form_workbench")
        self.assertGreaterEqual(gen["readiness"]["score"], 70.0)
        self.assertTrue(gen["dryRunVerification"]["ok"])
        self.assertGreaterEqual(len(gen["phases"]), 4)

        req_gp = urllib.request.Request(
            f"{base}/api/app-use/ground-preview",
            data=json.dumps({
                "bundle_id": "com.example.UnseenERP",
                "step": {"action": "click_element", "targetAxTitle": "Search"},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_gp, timeout=15) as r2:
            gp = json.loads(r2.read().decode("utf-8"))
        self.assertTrue(gp["ok"])
        self.assertEqual(gp["point"], [550.0, 160.0])

    def test_09_parallel_watch_and_parallel_run_with_hid_lease(self) -> None:
        # Part A: watch_windows_parallel achieves real concurrent speedup > 1.5x
        def fake_parallel_watch(args, timeout=15.0):
            if args and args[0] == "app-use-inspect":
                time.sleep(0.15)
                bid = args[args.index("--bundle-id") + 1] if "--bundle-id" in args else "com.example.App"
                return {
                    "ok": True,
                    "bundleID": bid,
                    "name": bid.split(".")[-1],
                    "window": {"windowID": 100, "title": f"Win {bid}"},
                    "axControls": [{"role": "AXTextArea", "relCenter": {"x": 0.5, "y": 0.8}}],
                    "inputElements": [{"role": "AXTextArea", "relCenter": {"x": 0.5, "y": 0.8}}],
                    "axControlCount": 1,
                    "axTexts": [f"Text from {bid}"],
                }
            return {"ok": True}

        self.engine._run_native = fake_parallel_watch  # type: ignore[method-assign]
        w_res = self.engine.app_use_watch_parallel(
            [
                {"bundle_id": "com.example.A"},
                {"bundle_id": "com.example.B"},
                {"bundle_id": "com.example.C"},
            ],
            include_ocr=False,
            max_workers=3,
        )
        self.assertTrue(w_res["ok"])
        self.assertEqual(w_res["succeededCount"], 3)
        self.assertGreater(w_res["speedupRatio"], 1.5)

        # Part B: run_workflows_parallel strictly serializes active HID steps via ForegroundHIDLease
        hid_guard = {"active": 0, "max_active": 0}
        guard_lock = threading.Lock()

        def fake_parallel_run(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd in ("app-use-activate", "app-use-paste", "press-key"):
                with guard_lock:
                    hid_guard["active"] += 1
                    if hid_guard["active"] > hid_guard["max_active"]:
                        hid_guard["max_active"] = hid_guard["active"]
                try:
                    time.sleep(0.06)
                finally:
                    with guard_lock:
                        hid_guard["active"] -= 1
                return {"ok": True, "verified": True}
            if cmd == "app-use-inspect":
                time.sleep(0.05)
                return {"ok": True, "axTexts": ["Done"], "ocrPreview": "Done", "axControls": []}
            return {"ok": True}

        self.engine._run_native = fake_parallel_run  # type: ignore[method-assign]
        r_res = self.engine.app_use_run_parallel(
            [
                {"workflow": {"id": "p1", "targetApp": {"bundleID": "com.a", "name": "A"}, "steps": [{"step": 1, "action": "activate_app"}, {"step": 2, "action": "focus_and_type", "text": "x"}, {"step": 3, "action": "wait_and_read", "delaySec": 0.02}]}},
                {"workflow": {"id": "p2", "targetApp": {"bundleID": "com.b", "name": "B"}, "steps": [{"step": 1, "action": "activate_app"}, {"step": 2, "action": "focus_and_type", "text": "y"}, {"step": 3, "action": "wait_and_read", "delaySec": 0.02}]}},
            ],
            dry_run=False,
            confirm_run=True,
            respect_human_guard=False,
            max_workers=2,
        )
        self.assertTrue(r_res["ok"])
        self.assertEqual(r_res["succeededCount"], 2)
        self.assertEqual(hid_guard["max_active"], 1, "ForegroundHIDLease must prevent concurrent HID overlap")
        self.assertGreaterEqual(r_res["hidLeaseStats"]["totalAcquisitions"], 4)

    def test_10_install_meta_skill_mcp_tools_and_web_console_v28(self) -> None:
        tmp_global = self.data / "global_skills"
        sym1 = self.data / "codex_skills"
        sym2 = self.data / "agy_skills"
        sym1.mkdir(parents=True)
        sym2.mkdir(parents=True)

        inst = self.engine.app_use_install_meta_skill(
            install_global=True,
            global_skills_root=tmp_global,
            symlink_roots=[sym1, sym2],
        )
        self.assertTrue(inst["ok"])
        self.assertTrue((tmp_global / "app-use-meta-builder" / "SKILL.md").is_file())
        self.assertTrue((sym1 / "app-use-meta-builder").is_symlink())
        self.assertTrue((sym2 / "app-use-meta-builder" / "SKILL.md").is_file())

        # Sealed .app/Contents/Resources non-pollution regression check
        import wechat_control.app_use_studio as app_use_studio_mod

        fake_app = self.data / "FakeWeChatBot.app"
        fake_py = fake_app / "Contents" / "Resources" / "wechat_control" / "app_use_studio.py"
        fake_py.parent.mkdir(parents=True, exist_ok=True)
        fake_py.write_text("# stub\n", encoding="utf-8")
        with mock.patch.object(app_use_studio_mod, "__file__", str(fake_py)):
            sealed_res = self.engine.app_use_install_meta_skill(install_global=False)
        self.assertTrue(sealed_res["ok"])
        self.assertNotIn(".app/Contents/Resources", sealed_res["repoSkillPath"])
        self.assertTrue(Path(sealed_res["repoSkillPath"]).is_file())
        self.assertFalse((fake_app / "Contents" / "Resources" / "skills").exists())

        tool_names = {t["name"] for t in MCP_TOOLS}
        for name in (
            "app_use_generalize_app",
            "app_use_state_graph",
            "app_use_install_meta_skill",
            "app_use_watch_parallel",
            "app_use_run_parallel",
        ):
            self.assertIn(name, tool_names)

        mcp = WeChatMCPServer(self.engine)
        sg = mcp._dispatch_tool("app_use_state_graph", {})
        self.assertTrue(sg["ok"])

        html = render_web_console_html()
        self.assertNotIn("window.confirm(", html)
        for marker in (
            "appuseGeneralizeNewApp",
            "appuseWatchRunningParallel",
            "appuseInstallMetaSkill",
            "appuseStateGraphBox",
            "appuseArchetypeBadge",
            "appuseReadinessBadge",
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
