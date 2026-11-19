"""Recommendation preview regressions use a private SQLite store and no WeChat process."""
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from wechat_control.mcp_server import create_http_server
from wechat_control.recommendation_preview import progress, start_preview
from wechat_control.workbench import WorkbenchError


class PreviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        self.engine, self.wb = start_preview(self.data)

    def test_grounded_ranked_adoption_and_restart(self):
        good, missing = self.wb.ledger.list()
        self.assertEqual([o["id"] for o in good["basis"]["options"]], ["1", "2", "3"])
        self.assertEqual(good["basis"]["documentRefs"][0]["title"], "试用期限")
        self.assertEqual((missing["state"], missing["basis"]["options"]), ("manual", []))
        adopted = self.wb.adopt(good["id"], good["version"], "2")
        self.assertEqual((adopted["state"], adopted["draft"]), ("adopted", "试用期是七天。"))
        with self.assertRaisesRegex(WorkbenchError, "draft_changed"):
            self.wb.adopt(good["id"], good["version"], "1")
        self.wb.adopt(missing["id"], missing["version"], "defer")
        _, reopened = start_preview(self.data)
        self.assertEqual(reopened.ledger.list()[0]["draft"], adopted["draft"])
        self.assertEqual(progress(self.data)["tasksByStatus"], {"adopted": 1, "deferred": 1})

    def test_http_preview_with_no_send_or_other_production_apis(self):
        key = "1" * 64
        srv = create_http_server(self.engine, port=0, workbench=self.wb, preview_secret=key)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        def request(method, route, token=key, origin=None):
            conn = HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
            try:
                conn.request(method, route, "{}" if method == "POST" else None,
                             {"Origin": origin or f"http://127.0.0.1:{srv.server_port}",
                              "Content-Type": "application/json", "X-Workbench-Session": token})
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()
        self.assertEqual(request("GET", "/api/workbench/tasks", "")[0], 403)
        self.assertEqual(request("GET", "/workbench")[0], 200)
        self.assertEqual(request("POST", "/api/workbench/capture")[0], 200)
        self.assertEqual(request("POST", "/api/workbench/adopt", origin="https://elsewhere.example")[0], 403)
        self.assertEqual(request("POST", "/api/workbench/confirm")[0], 403)
        for route in ("/send", "/api/auth-toggle", "/api/monitor/poll"):
            self.assertEqual(request("POST", route)[0], 404)

    def test_mcp_read_only_no_chat_data_and_no_state_change(self):
        row = self.wb.ledger.list()[0]
        self.wb.adopt(row["id"], row["version"], "1")
        db = self.data / "inbox.sqlite"
        before = hashlib.sha256(db.read_bytes()).digest()
        messages = [
            {"id": 1, "method": "initialize"},
            {"id": 2, "method": "tools/list"},
            {"id": 3, "method": "tools/call", "params": {"name": "wechat_workbench_progress"}},
            {"id": 4, "method": "tools/call", "params": {"name": "wechat_send"}},
        ]
        result = subprocess.run([sys.executable, "-B", "-m", "wechat_control.recommendation_preview",
                                 "progress-mcp", str(self.data)],
                                input="\n".join(map(json.dumps, messages)), capture_output=True,
                                text=True, timeout=5, check=True)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([t["name"] for t in replies[1]["result"]["tools"]], ["wechat_workbench_progress"])
        data = json.loads(replies[2]["result"]["content"][0]["text"])
        self.assertEqual(data["draftsAdopted"], 1)
        self.assertFalse(data["sendEnabled"])
        self.assertEqual(replies[3]["error"]["code"], -32601)
        self.assertNotIn("演练好友", result.stdout)
        self.assertNotIn("七天", result.stdout)
        self.assertEqual(before, hashlib.sha256(db.read_bytes()).digest())
