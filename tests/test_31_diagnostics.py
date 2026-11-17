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
        self.assertEqual(rep["version"], "2.4.49")
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


if __name__ == "__main__":
    unittest.main()
