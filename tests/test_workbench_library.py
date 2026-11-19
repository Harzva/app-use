import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from wechat_control.guided_preview import create_guided
from wechat_control.mcp_server import create_http_server


class CandidateLibraryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "candidate"
        self.engine, self.wb, self.state = create_guided(self.data)
        self.engine.models.sync_models = self.unexpected
        self.engine.soul_profiler.build_profiles = self.unexpected
        self.port = self.serve(integrated=True)

    def unexpected(self, *args, **kwargs):
        self.fail("read-only request attempted to refresh/rebuild")

    def serve(self, integrated):
        server = create_http_server(
            self.engine, port=0, workbench=self.wb, preview_secret="opaque-test-session",
            guided=True, integrated=integrated,
        )
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.addCleanup(close)
        return server.server_port

    def req(self, path, *, port=None, method="GET", key=True, origin=None, host=None):
        port = port or self.port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        headers = {"X-Workbench-Session": "opaque-test-session"} if key else {}
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        body = "{}" if method == "POST" else None
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=body, headers=headers)
            res = conn.getresponse()
            return res.status, json.loads(res.read())
        finally:
            conn.close()

    def write_json(self, p, value):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value), encoding="utf-8")

    def fingerprints(self):
        return {
            p.relative_to(self.data).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.data.rglob("*") if p.is_file()
        }

    def test_metadata_covers_existing_archive_accounts_channels_and_contacts(self):
        contact = "Archive fixture contact"
        self.engine.bind_contact(contact, alias="Local alias", role="friend", notes="not for listing",
                                 auto_reply_enabled=True, scheduled_enabled=True)
        p = self.engine.article_exporter.export_root
        self.write_json(p / "fixture-article" / "metadata.json",
                        {"title": "Safety FAQ", "account": "Docs", "exported_at": "2026-11-15",
                         "downloaded_image_count": 2, "markdown_path": "not for listing"})
        self.write_json(p / "accounts" / "fixture-account" / "account_catalog.json",
                        {"accountName": "Archived service account", "exportedAt": "2026-11-15",
                         "exportedCount": 3, "articles": ["not for listing"], "albumUrl": "not for listing"})
        self.write_json(p / "channels" / "fixture-channel" / "channels_catalog.json",
                        {"authorName": "Archived Channels creator", "exportedAt": "2026-11-15",
                         "exportedCount": 1, "videosDir": "not for listing", "videos": ["not for listing"]})
        before = self.fingerprints()
        status, archived = self.req("/api/workbench/archive")
        self.assertEqual(status, 200)
        self.assertEqual(archived["articles"][0]["title"], "Safety FAQ")
        self.assertEqual(archived["accounts"][0]["accountName"], "Archived service account")
        self.assertEqual(archived["channels"][0]["authorName"], "Archived Channels creator")
        self.assertNotIn("not for listing", json.dumps(archived))
        status, contacts = self.req("/api/workbench/contacts")
        self.assertEqual(status, 200)
        row = next(item for item in contacts["contacts"] if item["target"] == contact)
        self.assertEqual(row["alias"], "Local alias")
        self.assertNotIn("autoReplyEnabled", row)
        self.assertNotIn("scheduledEnabled", row)
        self.assertNotIn("notes", row)
        self.assertEqual(self.fingerprints(), before)

    def test_soul_read_never_regenerates_and_models_never_sync_or_disclose_secrets(self):
        self.assertFalse(self.engine.soul_profiler.store_path.exists())
        status, blank = self.req("/api/workbench/soul?rebuild=1")
        self.assertEqual(status, 200)
        self.assertEqual(blank["contactProfiles"], [])
        self.assertFalse(self.engine.soul_profiler.store_path.exists())
        self.write_json(self.engine.soul_profiler.store_path,
                        {"ownerProfile": {"archetypeTag": "Owner style", "ownerId": "private-owner"},
                         "contactProfiles": {"fixture": {"target": "Fixture", "personalityTag": "Practical",
                                                        "memories": ["private-memory"]}}})
        self.engine.models.state["contactModelBindings"] = {"private-contact": "model"}
        self.engine.models.state["profiles"] = {"private-profile": {"endpoint": "private-url"}}
        self.engine.models.state["providers"]["magpie-gateway"]["apiKey"] = "private-api-key"
        before = self.fingerprints()
        status, soul = self.req("/api/workbench/soul")
        self.assertEqual(status, 200)
        self.assertEqual(soul["ownerProfile"], {"archetypeTag": "Owner style"})
        self.assertEqual(soul["contactProfiles"][0]["personalityTag"], "Practical")
        status, models = self.req("/api/workbench/models?refresh=1")
        self.assertEqual(status, 200)
        self.assertFalse(models["networkChecked"])
        self.assertIn("magpie-gateway", {p["id"] for p in models["providers"]})
        self.assertNotIn("private-", json.dumps([soul, models]))
        self.assertNotIn("baseUrl", json.dumps(models))
        self.assertEqual(self.fingerprints(), before)

    def test_no_symlink_backdoor_to_other_local_profiles(self):
        other = self.root / "external"
        self.write_json(other / "metadata.json", {"title": "different user data"})
        self.write_json(other / "soul.json", {"ownerProfile": {"archetypeTag": "different user data"}})
        self.engine.article_exporter.export_root.mkdir(parents=True)
        (self.engine.article_exporter.export_root / "symlink").symlink_to(other, target_is_directory=True)
        self.engine.soul_profiler.store_path.symlink_to(other / "soul.json")
        self.assertEqual(self.req("/api/workbench/archive")[1]["articles"], [])
        self.assertEqual(self.req("/api/workbench/soul")[1]["ownerProfile"], {})

    def test_allowlist_requires_session_local_origin_and_integrated_mode(self):
        for suffix in ("archive", "contacts", "models", "soul"):
            path = "/api/workbench/" + suffix
            self.assertEqual(self.req(path, key=False)[0], 403)
            self.assertEqual(self.req(path, origin="https://nonlocal.invalid")[0], 403)
            self.assertEqual(self.req(path, host="alias.invalid")[0], 403)
            self.assertEqual(self.req(path, method="POST", origin=f"http://127.0.0.1:{self.port}")[0], 404)
        port = self.serve(integrated=False)
        self.assertEqual(self.req("/api/workbench/models", port=port)[0], 404)
        for path in ("/api/models", "/api/channels-exports", "/api/send", "/api/special-care",
                     "/api/activate", "/api/watch", "/api/request-permissions"):
            self.assertEqual(self.req(path)[0], 404)
            self.assertEqual(self.req(path, method="POST", origin=f"http://127.0.0.1:{self.port}")[0], 404)
        self.assertEqual(self.state["calls"], 0)
        self.assertEqual(self.state["reads"], 0)
