"""diagnostics 聚合诊断端点专项测试。"""
import json
import sys
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_control.engine import WeChatControlEngine
from wechat_control.auth_gate import ALL_CAPABILITIES
from wechat_control.mcp_server import create_http_server


def _make_engine(data: Path) -> WeChatControlEngine:
    engine = WeChatControlEngine(
        audit_log_path=data / "audit.jsonl", auth_file_path=data / "auth.json",
        bindings_file_path=data / "bindings.json", models_config_path=data / "models.json",
        model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
        knowledge_db_path=data / "kb.sqlite", personas_file_path=data / "personas.json",
        snapshots_dir=data / "snap", reports_dir=data / "reports",
        allowed_groups=["VIP客户群"],
    )
    engine.auth_grant(ALL_CAPABILITIES, authorized_by="diag-test")
    return engine


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.engine = _make_engine(self.data)

    def test_shallow_diagnostics_aggregates_subsystems(self):
        rep = self.engine.diagnostics()
        self.assertTrue(rep["ok"])
        self.assertIn("generatedAt", rep)
        # 版本应与 plugin.manifest.json 动态一致（而非硬编码，避免每次 bump 挂测试）
        manifest_ver = json.loads(
            (Path(__file__).resolve().parent.parent / "plugin.manifest.json").read_text()
        ).get("version")
        self.assertEqual(rep["version"], manifest_ver)
        for key in ("auth", "hosting", "antiban", "knowledgeEntries", "monitorState", "recentEvents"):
            self.assertIn(key, rep, f"缺少 {key}")
            self.assertNotIn("error", rep[key] if isinstance(rep[key], dict) else {}, f"{key} 报错")
        self.assertIsInstance(rep["recentEvents"], list)
        # shallow 模式不包含慢探测项
        self.assertNotIn("permissions", rep)
        self.assertNotIn("llmGateway", rep)

    def test_deep_diagnostics_includes_probes(self):
        rep = self.engine.diagnostics(deep=True)
        self.assertIn("permissions", rep)
        self.assertIn("llmGateway", rep)

    def test_hosting_state_reflects_in_diagnostics(self):
        self.engine.bind_contact("诊断好友", role="friend", auto_reply_enabled=True)
        res = self.engine.start_hosting(["诊断好友"])
        self.assertTrue(res["ok"])
        rep = self.engine.diagnostics()
        self.assertTrue(rep["hosting"].get("enabled"))
        self.assertIn("诊断好友", rep["hosting"].get("targets") or [])

    def test_web_console_perm_wizard(self):
        from wechat_control.web_console import render_web_console_html
        html = render_web_console_html()
        for marker in ("renderPermWizard", "startWizardPolling", "stopWizardPolling", "去授权", "自动检测并进入下一步", "permWizard"):
            self.assertIn(marker, html, f"分步授权向导缺少标记: {marker}")

    def test_web_console_perm_modal_dismissable(self):
        from wechat_control.web_console import render_web_console_html
        html = render_web_console_html()
        for marker in ("PERM_MODAL_DISMISSED", "为什么之前授权过", "旧 WeChat Bot 条目"):
            self.assertIn(marker, html, f"权限弹窗缺少 dismissable/文案标记: {marker}")

    def test_web_console_has_diagnostics_ui(self):
        from wechat_control.web_console import render_web_console_html
        html = render_web_console_html()
        for marker in ("diagBtn", "diagOverlay", "loadDiagnostics", "健康诊断"):
            self.assertIn(marker, html, f"首页缺少诊断 UI 标记: {marker}")

    def test_diagnostics_http_endpoint(self):
        import threading
        import urllib.request
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/api/diagnostics", timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp.status, 200)
                self.assertTrue(body.get("ok"))
                self.assertIn("hosting", body)
            with urllib.request.urlopen(f"{base}/api/diagnostics?deep=1", timeout=10) as resp:
                body2 = json.loads(resp.read().decode("utf-8"))
                self.assertIn("permissions", body2)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_permissions_status_works_without_studio_auth(self):
        import threading
        import urllib.request

        fresh_dir = self.data / "fresh_unauth"
        fresh = WeChatControlEngine(
            audit_log_path=fresh_dir / "audit.jsonl",
            auth_file_path=fresh_dir / "auth.json",
            bindings_file_path=fresh_dir / "bindings.json",
            models_config_path=fresh_dir / "models.json",
            model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
            knowledge_db_path=fresh_dir / "kb.sqlite",
            personas_file_path=fresh_dir / "personas.json",
            snapshots_dir=fresh_dir / "snap",
            reports_dir=fresh_dir / "reports",
        )
        fresh._run_native = lambda args, timeout=15.0: {  # type: ignore[method-assign]
            "ok": True,
            "accessibilityTrusted": True,
            "postEventTrusted": True,
            "screenCaptureTrusted": True,
            "wechatRunning": True,
            "wechatPid": 999,
        }
        perms = fresh.permissions_status()
        self.assertTrue(perms["ok"])
        self.assertTrue(perms["allGranted"])
        self.assertEqual(len(perms["items"]), 3)

        rep = fresh.diagnostics(deep=True)
        self.assertTrue(rep["ok"])
        self.assertFalse((rep["auth"].get("authorization") or {}).get("authorized"))
        self.assertTrue(rep["permissions"]["allGranted"])

        srv = create_http_server(fresh, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/permissions", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertTrue(json.loads(resp.read().decode("utf-8"))["allGranted"])
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/diagnostics?deep=1", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertTrue(json.loads(resp.read().decode("utf-8"))["permissions"]["allGranted"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_diagnostics_knowledge_count_not_capped_at_one(self):
        rep = self.engine.diagnostics()
        self.assertIsInstance(rep["knowledgeEntries"], int)
        self.assertGreater(rep["knowledgeEntries"], 1)

    def test_legacy_runtime_migration_and_bundle_binary_resolution(self):
        from wechat_control.engine import _migrate_legacy_runtime_data, _resolve_default_binary_path

        bundle = self.data / "WeChat Bot.app" / "Contents" / "Resources"
        macos = bundle.parent / "MacOS"
        bundle.mkdir(parents=True)
        macos.mkdir(parents=True)
        bin_path = macos / "wechat-vision-ax"
        bin_path.write_text("#!/bin/sh\n", encoding="utf-8")
        self.assertEqual(_resolve_default_binary_path(bundle), bin_path)

        legacy = self.data / "legacy_repo"
        (legacy / "config").mkdir(parents=True)
        (legacy / "logs" / "contacts").mkdir(parents=True)
        (bundle / "repo_root.txt").write_text(str(legacy) + "\n", encoding="utf-8")

        (legacy / "config" / "studio_auth.json").write_text('{"authorized": true}\n', encoding="utf-8")
        (legacy / "config" / "bound_contacts.json").write_text('{"bindings": {"测试好友": {}}}\n', encoding="utf-8")
        (legacy / "config" / "personas.json").write_text('{"custom": true}\n', encoding="utf-8")
        (legacy / "logs" / "hosting_state.json").write_text('{"enabled": true}\n', encoding="utf-8")
        (legacy / "logs" / "contacts" / "测试_history.json").write_text('{"messages": []}\n', encoding="utf-8")

        target_root = self.data / "app_support"
        (target_root / "config").mkdir(parents=True)
        (target_root / "config" / "personas.json").write_text('{"custom": false}\n', encoding="utf-8")

        res = _migrate_legacy_runtime_data(bundle, target_root)
        self.assertTrue(res["migrated"])
        self.assertTrue((target_root / ".runtime_migrated_v1").is_file())
        self.assertTrue((target_root / "config" / "studio_auth.json").is_file())
        self.assertTrue((target_root / "config" / "bound_contacts.json").is_file())
        self.assertTrue((target_root / "logs" / "hosting_state.json").is_file())
        self.assertTrue((target_root / "logs" / "contacts" / "测试_history.json").is_file())
        self.assertEqual(json.loads((target_root / "config" / "personas.json").read_text()), {"custom": True})

        res2 = _migrate_legacy_runtime_data(bundle, target_root)
        self.assertFalse(res2["migrated"])
        self.assertEqual(res2["reason"], "already_migrated")

    def test_avatar_rel_coordinates_and_capture_auto_crop(self):
        import threading
        import urllib.request
        from wechat_control.live_inspector import WeChatLiveInspector

        elements = [
            {"text": "openbot", "bbox": {"x": 118, "y": 70, "width": 58, "height": 12}, "center": {"x": 147, "y": 76}},
            {"text": "测试预览", "bbox": {"x": 118, "y": 91, "width": 80, "height": 12}, "center": {"x": 158, "y": 97}},
            {"text": "安晓心", "bbox": {"x": 116, "y": 200, "width": 44, "height": 12}, "center": {"x": 138, "y": 206}},
            {"text": "请回复一句话", "bbox": {"x": 116, "y": 220, "width": 90, "height": 12}, "center": {"x": 161, "y": 226}},
        ]
        rows = WeChatLiveInspector._cluster_session_rows(elements, 310.0, 1320.0)
        self.assertEqual(len(rows), 2)
        self.assertGreaterEqual(rows[0]["avatarRel"]["x"], 64.0)
        self.assertEqual(rows[0]["avatarRel"]["x"], 70.0)
        self.assertEqual(rows[1]["avatarRel"]["x"], 68.0)

        snap = self.engine.inspector.snapshots_dir / "monitor_poll_cur.png"
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 300)

        recorded_crops = []

        def fake_native(args, timeout=15.0):
            if args and args[0] == "ocr" and "--crop" in args:
                crop_str = args[args.index("--crop") + 1]
                recorded_crops.append(crop_str)
                out_p = Path(args[args.index("--out") + 1])
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 300)
                return {"ok": True, "savedPath": str(out_p), "elements": []}
            if args and args[0] == "ocr":
                return {"ok": True, "imageWidth": 853, "imageHeight": 1320, "elements": elements}
            return {
                "ok": True,
                "accessibilityTrusted": True,
                "postEventTrusted": True,
                "screenCaptureTrusted": True,
                "wechatRunning": True,
                "wechatPid": 123,
                "windows": [],
            }

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        cap = self.engine.avatar_capture("安晓心")
        self.assertTrue(cap["ok"])
        self.assertEqual(cap["url"], "/avatars/安晓心.png")
        self.assertEqual(recorded_crops[-1], "68,196,40,40")

        ov = self.engine.get_web_overview()
        self.assertEqual((ov.get("avatars") or {}).get("安晓心"), "/avatars/安晓心.png")

        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/avatar",
                data=json.dumps({"target": "openbot"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                body = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(body["ok"])
                self.assertEqual(body["crop"]["x"], 70)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/avatars/openbot.png", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertGreater(len(resp.read()), 200)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
