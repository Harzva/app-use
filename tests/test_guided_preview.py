"""Use synthetic desktop captures for stop fences, adoption and delivery states."""
import http.client
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from wechat_control.guided_preview import create_guided
from wechat_control.mcp_server import create_http_server
from wechat_control.workbench import WorkbenchError


class GuidedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.engine, self.wb, self.state = create_guided(self.path)

    def select(self):
        return self.wb.select(self.wb.choices()[0]["id"])

    def live_sample(self):
        self.select()
        self.wb.set_monitor("start")
        return self.wb.ingest()

    def test_confirmation_does_not_monitor_and_disappearance_pauses(self):
        with self.assertRaisesRegex(WorkbenchError, "select_window"):
            self.wb.set_monitor("start")
        self.select()
        self.assertEqual(self.state["reads"], 0)
        with self.assertRaisesRegex(WorkbenchError, "monitor_paused"):
            self.wb.ingest()
        self.wb.set_monitor("start")
        self.state["available"] = False
        with self.assertRaisesRegex(WorkbenchError, "window_lost"):
            self.wb.ingest()
        self.assertFalse(self.wb.status()["watching"])
        self.assertIsNone(self.wb.status()["window"])
        self.assertEqual(self.state["reads"], 0)

    def test_pause_discards_capture_already_in_flight(self):
        self.select()
        self.wb.set_monitor("start")
        called, resume = threading.Event(), threading.Event()
        capture = self.wb.read_window
        def delayed(*args):
            called.set()
            if not resume.wait(3):
                raise RuntimeError("test did not release the capture")
            return capture(*args)
        self.wb.read_window = delayed
        with ThreadPoolExecutor(1) as executor:
            pending = executor.submit(self.wb.ingest)
            try:
                self.assertTrue(called.wait(2))
                self.wb.set_monitor("pause")
            finally:
                resume.set()
            self.assertIsNone(pending.result(timeout=4))
        self.assertEqual(self.wb.ledger.list(), [])

    def test_changed_conversation_pauses_and_does_not_read_other_window(self):
        self.select()
        self.wb.set_monitor("start")
        self.state["chat"] = "另一个会话"
        with self.assertRaisesRegex(WorkbenchError, "conversation_changed"):
            self.wb.ingest()
        self.assertEqual(self.wb.status()["monitorReason"], "conversation_changed")
        self.assertFalse(self.wb.status()["watching"])
        self.assertEqual(self.wb.ledger.list(), [])

    def test_requires_adoption_then_manual_confirm_and_only_sends_once(self):
        task = self.live_sample()
        self.assertEqual(len(task["basis"]["options"]), 3)
        with self.assertRaisesRegex(WorkbenchError, "draft_changed"):
            self.wb.confirm(task["id"], task["version"], "")
        adopted = self.wb.adopt(task["id"], task["version"], "2")
        self.assertEqual(self.state["calls"], 0)
        self.wb.set_monitor("pause")
        def confirm(_):
            return self.wb.confirm(adopted["id"], adopted["version"], adopted["draft"])["state"]
        with ThreadPoolExecutor(2) as executor:
            self.assertEqual(list(executor.map(confirm, range(2))), ["verified", "verified"])
        self.assertEqual(self.state["calls"], 1)
        _, reopened, _ = create_guided(self.path)
        self.assertFalse(reopened.status()["watching"])
        self.assertEqual(reopened.ledger.list()[0]["state"], "verified")

    def test_readback_unknown_never_resends(self):
        task = self.live_sample()
        adopted = self.wb.adopt(task["id"], task["version"], "2")
        self.state["deliver"] = False
        for _ in range(2):
            self.assertEqual(self.wb.confirm(adopted["id"], adopted["version"], adopted["draft"])["state"], "unknown")
        self.assertEqual(self.state["calls"], 1)

    def test_integrated_knowledge_is_used_for_drafting_and_legacy_routes_stay_closed(self):
        key = "1" * 64
        with create_http_server(self.engine, port=0, workbench=self.wb, preview_secret=key,
                                guided=True, integrated=True) as server:
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            origin = f"http://127.0.0.1:{server.server_port}"

            def request(path, body=None, *, token=key, request_origin=origin):
                client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                try:
                    headers = {"X-Workbench-Session": token, "Origin": request_origin}
                    if body is not None:
                        headers["Content-Type"] = "application/json"
                    client.request("GET" if body is None else "POST", path,
                                   None if body is None else json.dumps(body), headers)
                    response = client.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    client.close()

            knowledge = "/api/workbench/knowledge"
            item = {"title": "售后电话", "text": "售后电话为 12345。"}
            try:
                self.assertEqual(request(knowledge, item, request_origin="http://other.test")[0], 403)
                self.assertEqual(request(knowledge, item, token="")[0], 403)
                self.assertEqual(request(knowledge, item)[0], 200)
                saved = request(knowledge)[1]["entries"]
                self.assertEqual(sum(e["title"] == item["title"] for e in saved), 1)
                result = self.engine.knowledge.search_context(
                    "售后电话", space_id=self.wb.recommendation_space, limit=3
                )
                self.assertIn(item["text"], str(result))
                self.assertEqual(request("/console")[0], 404)
                for path in ("/send", "/api/takeover", "/api/watch-once", "/api/botstudio-bridge"):
                    self.assertEqual(request(path, {"target": "演练好友", "text": "不应发送"})[0], 404)
                self.assertEqual(self.state["calls"], 0)
            finally:
                server.shutdown()
                worker.join(timeout=3)
