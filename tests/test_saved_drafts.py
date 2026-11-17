"""Manual draft route tests, with storage and HTTP confined to a synthetic profile."""

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace

from wechat_control.auth_gate import StudioPluginUnauthorizedError
from wechat_control.mcp_server import create_http_server


ROUTE = "/api/workbench/saved-drafts"
DRAFT_ID = "1a" * 16
STATE_ROUTE = f"{ROUTE}/{DRAFT_ID}/state"
ORIGINAL = {
    "id": DRAFT_ID, "version": 0, "target": "北岸样品店 · CAFÉ",
    "incoming": "  样品几点寄？\n", "draft": "  明天下午寄出。🚚\n",
}


class SyntheticEngine:
    def __init__(self, root):
        self.auth_gate = SimpleNamespace(auth_file=root / "config" / "auth.json")
        self.authorized = True
        self.operations = []

    def _require(self, capability):
        self.operations.append(capability)
        if capability != "read_messages":
            raise AssertionError("saved drafts must not request capture or send capabilities")
        if not self.authorized:
            raise StudioPluginUnauthorizedError("synthetic revoked", capability)

    def __getattr__(self, name):
        self.operations.append(name)
        raise AssertionError(f"unexpected engine command: {name}")


class SavedDraftHTTPTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.engine = SyntheticEngine(Path(tmp.name))
        self.db = self.engine.auth_gate.auth_file.parent / "workbench" / "saved-drafts.sqlite"

    @contextmanager
    def server(self, **options):
        with create_http_server(self.engine, "127.0.0.1", 0, **options) as server:
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(server.serve_forever, poll_interval=0.02)
                try:
                    yield server.server_port
                finally:
                    server.shutdown()
                    future.result(timeout=2)

    def request(self, port, method, path=ROUTE, body=None, *, origin=True, headers=None):
        request_headers = {}
        if origin is True:
            request_headers["Origin"] = f"http://127.0.0.1:{port}"
        elif origin:
            request_headers["Origin"] = origin
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
            conn.request(method, path, body=payload, headers=request_headers)
            res = conn.getresponse()
            return res.status, json.loads(res.read()), res.headers
        finally:
            conn.close()

    def test_manual_draft_persists_and_legacy_routes_cannot_send_it(self):
        with self.server() as port:
            status, data, headers = self.request(port, "GET")
            self.assertEqual((status, data), (200, {"ok": True, "drafts": []}))
            self.assertEqual(headers.get("Cache-Control"), "no-store")
            self.assertFalse(self.db.exists())
            status, data, _ = self.request(port, "POST", body=ORIGINAL)
            self.assertEqual(status, 200)
            draft = data["draft"]
            self.assertEqual(draft, {**ORIGINAL, "version": 1, "updated": draft["updated"], "state": "pending"})
            self.assertEqual(self.request(port, "POST", body=ORIGINAL)[:2], (200, data))
            self.assertTrue(self.db.is_file())
            self.assertFalse(self.db.with_name("inbox.sqlite").exists())
            self.assertEqual(len(self.request(port, "GET")[1]["drafts"]), 1)
            summary = self.request(port, "GET")[1]["drafts"][0]
            self.assertEqual(summary, {k: draft[k] for k in ("id", "target", "updated", "version", "state")}
                             | {"preview": ORIGINAL["draft"]})
            update = {**ORIGINAL, "draft": "周四前寄出。", "version": draft["version"]}
            status, data, _ = self.request(port, "POST", body=update)
            self.assertEqual(status, 200)
            self.assertEqual(self.request(port, "POST", body=update)[:2], (200, data))
            self.assertEqual(data["draft"]["version"], 2)
        with self.server() as port:
            self.assertEqual(self.request(port, "GET", f"{ROUTE}/{DRAFT_ID}")[:2], (200, data))
            tasks = self.request(port, "GET", "/api/workbench/tasks")[1]["tasks"]
            self.assertEqual(tasks, [])
            for action in ("draft", "confirm"):
                code, response, _ = self.request(port, "POST", f"/api/workbench/{action}",
                                                 {"id": DRAFT_ID, "version": 2, "text": update["draft"]})
                self.assertEqual((code, response["error_code"]), (404, "task_not_found"))
        self.assertEqual(set(self.engine.operations), {"read_messages"})

    def test_conflicting_edits_do_not_overwrite_target_or_latest_draft(self):
        with self.server() as port:
            self.assertEqual(self.request(port, "POST", body=ORIGINAL)[0], 200)
            wrong_target = {**ORIGINAL, "version": 1, "target": "另一个合成会话"}
            for payload in (wrong_target, {**ORIGINAL, "draft": "相同 ID 的另一份草稿"}):
                code, response, _ = self.request(port, "POST", body=payload)
                self.assertEqual((code, response["error_code"]), (409, "saved_draft_changed"))
            barrier = threading.Barrier(2)
            def save(text):
                barrier.wait(timeout=3)
                return self.request(port, "POST", body={**ORIGINAL, "version": 1, "draft": text})
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(save, ("合成编辑一", "合成编辑二")))
            self.assertEqual(sorted(result[0] for result in results), [200, 409])
            winner = next(result[1] for result in results if result[0] == 200)
            self.assertEqual(self.request(port, "GET", f"{ROUTE}/{DRAFT_ID}")[:2], (200, winner))
            self.assertEqual(winner["draft"]["target"], ORIGINAL["target"])
            self.assertEqual(winner["draft"]["version"], 2)

    def test_invalid_payloads_and_unicode_size_limit(self):
        with self.server() as port:
            cases = (
                {"id": DRAFT_ID.upper()}, {"version": True}, {"version": -1},
                {"version": 2 ** 64}, {"target": " "}, {"target": "  有填充的目标"},
                {"target": "甲" * 257}, {"incoming": "甲" * 3001},
                {"draft": " \n "}, {"draft": "甲" * 3001}, {"draft": "\0"}, {"send": True},
            )
            for fields in cases:
                with self.subTest(fields=tuple(fields)):
                    code, data, _ = self.request(port, "POST", body={**ORIGINAL, **fields})
                    self.assertEqual((code, data["error_code"]), (400, "invalid_saved_draft"))
            self.assertEqual(self.request(port, "GET", ROUTE + "/wrong-id")[0], 400)
            self.assertEqual(self.request(port, "GET", ROUTE + "/" + DRAFT_ID)[0], 404)
            self.assertEqual(self.request(port, "POST", body={**ORIGINAL, "version": 1})[0], 404)
            self.assertFalse(self.db.exists())
            valid = {**ORIGINAL, "incoming": "🧪" * 3000, "draft": "🚚" * 3000}
            code, data, _ = self.request(port, "POST", body=valid)
            self.assertEqual(code, 200)
            self.assertEqual(data["draft"]["draft"], valid["draft"])
            self.assertEqual(self.request(port, "GET")[1]["drafts"][0]["preview"], "🚚" * 120 + "…")

    def test_legacy_draft_stays_untouched_until_completed_and_can_be_reopened(self):
        self.db.parent.mkdir(parents=True)
        updated = "2026-05-27T06:00:00.000000+00:00"
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""CREATE TABLE saved_draft (
                id TEXT PRIMARY KEY, target TEXT NOT NULL, incoming TEXT NOT NULL,
                draft TEXT NOT NULL, updated TEXT NOT NULL, version INTEGER NOT NULL)""")
            db.execute("INSERT INTO saved_draft VALUES (?,?,?,?,?,?)", (
                DRAFT_ID, ORIGINAL["target"], ORIGINAL["incoming"], ORIGINAL["draft"], updated, 7))
        legacy_bytes = self.db.read_bytes()
        with self.server() as port:
            row = self.request(port, "GET", f"{ROUTE}/{DRAFT_ID}")[1]["draft"]
            self.assertEqual(row, {**ORIGINAL, "updated": updated, "version": 7, "state": "pending"})
            self.assertEqual(self.request(port, "GET")[1]["drafts"][0]["state"], "pending")
            self.assertEqual(self.db.read_bytes(), legacy_bytes)
            payload = {"version": 7, "state": "completed"}
            code, result, headers = self.request(port, "POST", STATE_ROUTE, payload)
            self.assertEqual(code, 200)
            self.assertEqual(headers.get("Cache-Control"), "no-store")
            closed = result["draft"]
            self.assertNotEqual(closed["updated"], updated)
            self.assertEqual(closed, {**row, "updated": closed["updated"], "state": "completed", "version": 8})
            self.assertEqual(self.request(port, "POST", STATE_ROUTE, payload)[:2], (200, result))
            self.assertEqual(self.request(port, "POST", STATE_ROUTE, {**payload, "version": 8})[:2], (200, result))
            code, data, _ = self.request(port, "POST", STATE_ROUTE, {"version": 7, "state": "pending"})
            self.assertEqual((code, data["error_code"]), (409, "saved_draft_changed"))
            code, data, _ = self.request(port, "POST", body={**ORIGINAL, "version": 8, "draft": "不应覆盖"})
            self.assertEqual((code, data["error_code"]), (409, "saved_draft_completed"))
            self.assertFalse(self.db.with_name("inbox.sqlite").exists())
        with self.server() as port:
            self.assertEqual(self.request(port, "GET", f"{ROUTE}/{DRAFT_ID}")[1]["draft"], closed)
            self.assertEqual(self.request(port, "GET")[1]["drafts"][0]["state"], "completed")
            payload = {"version": 8, "state": "pending"}
            code, result, _ = self.request(port, "POST", STATE_ROUTE, payload)
            self.assertEqual(code, 200)
            opened = result["draft"]
            self.assertEqual(opened, {**closed, "state": "pending", "version": 9, "updated": opened["updated"]})
            self.assertEqual(self.request(port, "POST", STATE_ROUTE, payload)[:2], (200, result))
            code, data, _ = self.request(port, "POST", STATE_ROUTE, {"version": 8, "state": "completed"})
            self.assertEqual((code, data["error_code"]), (409, "saved_draft_changed"))
            code, data, _ = self.request(port, "POST", body={**ORIGINAL, "version": 9, "draft": "已重新编辑"})
            self.assertEqual((code, data["draft"]["state"], data["draft"]["version"]), (200, "pending", 10))
        self.assertEqual(set(self.engine.operations), {"read_messages"})

    def test_parallel_completion_and_text_edit_use_one_revision(self):
        with self.server() as port:
            self.assertEqual(self.request(port, "POST", body=ORIGINAL)[0], 200)
            barrier = threading.Barrier(2)

            def change(path_and_body):
                barrier.wait(timeout=3)
                return self.request(port, "POST", *path_and_body)

            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(change, (
                    (STATE_ROUTE, {"version": 1, "state": "completed"}),
                    (ROUTE, {**ORIGINAL, "version": 1, "draft": "另一个页面的编辑"}),
                )))
            self.assertEqual(sorted(result[0] for result in results), [200, 409])
            winner = next(result[1] for result in results if result[0] == 200)
            self.assertEqual(self.request(port, "GET", f"{ROUTE}/{DRAFT_ID}")[:2], (200, winner))
            self.assertEqual(winner["draft"]["version"], 2)
            if results[0][0] == 200:
                self.assertEqual(winner["draft"]["draft"], ORIGINAL["draft"])
            else:
                self.assertEqual(winner["draft"]["state"], "pending")
        self.assertEqual(set(self.engine.operations), {"read_messages"})

    def test_invalid_or_missing_state_change_does_not_create_database(self):
        with self.server() as port:
            for payload in ({}, {"version": 0, "state": "completed"}, {"version": True, "state": "pending"},
                            {"version": 2**63 - 1, "state": "pending"}, {"version": 1, "state": []},
                            {"version": 1, "state": "sent"}, {"version": 1, "state": "completed", "send": True},
                            {"version": 1, "state": "文" * 600}):
                code, data, _ = self.request(port, "POST", STATE_ROUTE, payload)
                self.assertEqual((code, data["error_code"]), (400, "invalid_saved_draft_state"))
            code, data, _ = self.request(port, "POST", STATE_ROUTE, {"version": 1, "state": "completed"})
            self.assertEqual((code, data["error_code"]), (404, "saved_draft_not_found"))
            self.assertFalse(self.db.exists())

    def test_scope_auth_revocation_and_preview_isolation(self):
        with self.server() as port:
            self.assertEqual(self.request(port, "POST", body=ORIGINAL, origin=False)[0], 403)
            self.assertEqual(self.request(port, "POST", body=ORIGINAL, origin="https://example.invalid")[0], 403)
            self.assertEqual(self.request(port, "GET", headers={"Host": "example.invalid"}, origin=False)[0], 403)
            self.assertEqual(self.request(port, "GET", headers={"Sec-Fetch-Site": "same-site"})[0], 403)
            self.assertEqual(self.request(
                port, "POST", body=ORIGINAL, headers={"Content-Type": "text/plain"})[0], 415)
            self.engine.authorized = False
            self.assertEqual(self.request(port, "POST", body=ORIGINAL)[0], 403)
            self.assertEqual(self.request(port, "GET")[0], 403)
            self.assertFalse(self.db.exists())
            self.engine.authorized = True
            self.assertEqual(self.request(port, "POST", body={**ORIGINAL, "incoming": ""})[0], 200)
            state = {"version": 1, "state": "completed"}
            self.assertEqual(self.request(port, "POST", STATE_ROUTE, state, origin=False)[0], 403)
            self.assertEqual(self.request(port, "POST", STATE_ROUTE, state, origin="https://example.invalid")[0], 403)
            self.assertEqual(self.request(port, "POST", STATE_ROUTE, state, headers={"Content-Type": "text/plain"})[0], 415)
            self.engine.authorized = False
            self.assertEqual(self.request(port, "GET", ROUTE + "/" + DRAFT_ID)[0], 403)
            self.assertEqual(self.request(port, "POST", STATE_ROUTE, state)[0], 403)
        self.engine.authorized = True
        for options in ({}, {"guided": True, "integrated": True}):
            with self.server(preview_secret="synthetic-session", workbench=object(), **options) as port:
                header = {"X-Workbench-Session": "synthetic-session"}
                self.assertEqual(self.request(port, "GET", headers=header)[0], 404)
                self.assertEqual(self.request(port, "POST", body=ORIGINAL, headers=header)[0], 404)
                self.assertEqual(self.request(port, "POST", STATE_ROUTE, state, headers=header)[0], 404)
