"""Synthetic end-to-end checks; never call native WeChat or a model provider."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from pathlib import Path

from wechat_control.auth_gate import READ_ONLY_CAPABILITIES, StudioPluginUnauthorizedError
from wechat_control.engine import WeChatControlEngine
from wechat_control.mcp_server import create_http_server
from wechat_control.workbench import ReviewLedger, Workbench, WorkbenchError

TARGET = "演练客户"
INCOMING = "请问试用期限是什么？"


def fixture(root):
    def offline(*args, **kwargs):
        raise AssertionError("no external network allowed in this fixture")

    engine = WeChatControlEngine(
        auth_file_path=root / "auth.json", bindings_file_path=root / "bindings.json",
        audit_log_path=root / "audit.jsonl", knowledge_db_path=root / "knowledge.sqlite",
        models_config_path=root / "models.json", personas_file_path=root / "personas.json",
        monitor_state_path=root / "monitor.json", monitor_events_path=root / "events.jsonl",
        snapshots_dir=root / "snapshots", reports_dir=root / "reports",
        model_http_requester=offline,
    )
    engine.auth_grant(authorized_by="synthetic-workbench", capabilities=["status", "read_messages", "send_text_live"])
    engine.bind_contact(TARGET, role="test", ai_persona="wecom-kf-pro",
                        scheduled_enabled=False, auto_reply_enabled=False)
    engine.knowledge.save_entry(title="试用期限", body="试用期为七天，试用结束后可联系人工续期。",
                                keywords=["试用期限"], kind="faq")
    engine.models.state["llmReplyEnabled"] = False
    view = {"title": TARGET, "peer": INCOMING, "responses": [], "send_calls": 0,
            "deliver": True, "guard": True, "protocol": 1, "pid": 32}
    bounds = {"width": 900, "height": 750, "x": 0, "y": 0}
    def bubble(text, x, y):
        return {"text": text, "confidence": 0.97, "center": {"x": x, "y": y},
                "bbox": {"x": x-60, "y": y-7, "width": 120, "height": 14}}

    def native(args, timeout=20):
        if args == ["status"]:
            return {"ok": True, "reviewedSendProtocol": view["protocol"], "wechatRunning": True,
                    "windowCount": 1, "wechatPID": view["pid"], "accessibilityTrusted": True, "postEventTrusted": True, "screenCaptureTrusted": True,
                    "windows": [{"windowID": 17, "bounds": bounds}]}
        if args[0] == "capture-ocr":
            assert "--no-activate" in args and args[args.index("--window-id")+1] == "17", args
            messages = [bubble(view["title"], 425, 26),
                        bubble("10:40", 570, 65), bubble(view["peer"], 410, 110)]
            messages += [bubble(text, 795, 170 + index*65) for index, text in enumerate(view["responses"])]
            return {"ok": True, "windowID": 17, "windowBounds": bounds, "elements": messages}
        if args[0] == "paste-and-verify":
            assert args[-1] == "--send" and args[args.index("--review-window")+1] == "17", args
            assert args[args.index("--review-title")+1] == view["title"]
            view["send_calls"] += 1
            if view["deliver"]:
                view["responses"].append(args[args.index("--text")+1])
            return {"ok": True, "sent": True}
        raise AssertionError(f"unexpected native command {args[0]}")

    engine._run_native = native
    engine.human_guard.check_can_operate = lambda: {"canOperate": view["guard"]}
    return engine, Workbench(engine, ReviewLedger(root / "workbench" / "ledger.sqlite"), idle_wait=0), view


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.engine, self.wb, self.view = fixture(Path(tmp.name))

    def draft(self):
        task = self.wb.ingest()
        self.assertIsNotNone(task)
        return self.wb.draft(task["id"])

    def test_inbound_kb_confirm_verified_and_restart(self):
        row = self.draft()
        self.assertEqual(row["state"], "ready")
        self.assertIn("七天", row["draft"])
        self.assertEqual(row["basis"]["documentRefs"][0]["title"], "试用期限")
        self.assertEqual(self.wb.ingest()["id"], row["id"])
        self.assertEqual(len(self.wb.ledger.list()), 1)
        self.assertEqual(self.view["send_calls"], 0)
        with ThreadPoolExecutor(2) as pool:
            action = lambda _: self.wb.confirm(row["id"], row["version"], row["draft"])["state"]
            self.assertEqual(list(pool.map(action, range(2))), ["verified", "verified"])
        self.assertEqual(self.view["send_calls"], 1)
        reopened = Workbench(self.engine, ReviewLedger(self.wb.ledger.path), idle_wait=0)
        saved = reopened.confirm(row["id"], row["version"], row["draft"])
        self.assertEqual(saved["reason"], "new_outbound_bubble")
        self.assertEqual([event["stage"] for event in saved["events"]], ["verified", "sending", "ready", "drafting", "new"])
        self.assertNotIn(INCOMING, json.dumps(saved["events"], ensure_ascii=False))
        self.assertEqual(self.view["send_calls"], 1)

    def test_unknown_result_not_repeated_and_recover_interrupted_claim(self):
        row = self.draft()
        self.view["deliver"] = False
        self.assertEqual(self.wb.confirm(row["id"], row["version"], row["draft"])["state"], "unknown")
        self.assertEqual(self.view["send_calls"], 1)
        with sqlite3.connect(self.wb.ledger.path) as db:
            db.execute("UPDATE review SET state='sending' WHERE id=?", (row["id"],))
        reopened = Workbench(self.engine, ReviewLedger(self.wb.ledger.path), idle_wait=0)
        self.assertEqual(reopened.confirm(row["id"], row["version"], row["draft"])["reason"], "interrupted")
        self.assertEqual(self.view["send_calls"], 1)

    def test_unmatched_knowledge_routes_to_manual(self):
        self.view["peer"] = "🧪 unrelated_identifier_xyz"
        row = self.draft()
        self.assertEqual((row["state"], row["reason"]), ("manual", "no_knowledge"))
        with self.assertRaisesRegex(WorkbenchError, "draft_changed"):
            self.wb.confirm(row["id"], row["version"], "")
        self.assertEqual(self.view["send_calls"], 0)

    def test_stale_confirmation_and_wrong_conversation_are_blocked(self):
        row = self.draft()
        self.wb.draft(row["id"])
        with self.assertRaisesRegex(WorkbenchError, "draft_changed"):
            self.wb.confirm(row["id"], row["version"], row["draft"])
        current = self.wb.ledger.list()[0]
        self.view["pid"] += 1
        with self.assertRaisesRegex(WorkbenchError, "conversation_changed"):
            self.wb.confirm(row["id"], current["version"], current["draft"])
        self.view["pid"] -= 1
        self.view["peer"] = "我又发来一个不同的问题"
        with self.assertRaisesRegex(WorkbenchError, "conversation_changed"):
            self.wb.confirm(row["id"], current["version"], current["draft"])
        self.assertEqual(self.view["send_calls"], 0)

    def test_revoked_permissions_human_pause_and_old_binary_do_not_write(self):
        row = self.draft()
        self.view["guard"] = False
        with self.assertRaisesRegex(WorkbenchError, "human_pause"):
            self.wb.confirm(row["id"], row["version"], row["draft"])
        self.view["protocol"] = 0
        with self.assertRaisesRegex(WorkbenchError, "driver_unavailable"):
            self.wb.ingest()
        driver_result = self.engine.send_text(TARGET, row["draft"], dry_run=False, silent_mode=False,
                                              confirm_send=True, skip_navigation=True, expected_window_id=17)
        self.assertEqual(driver_result["status"], "unsupported_review_driver")
        self.engine.auth_grant(capabilities=READ_ONLY_CAPABILITIES)
        with self.assertRaises(StudioPluginUnauthorizedError):
            self.wb.confirm(row["id"], row["version"], row["draft"])
        self.assertEqual(self.view["send_calls"], 0)

    def test_local_http_workflow_rejects_foreign_origin(self):
        srv = create_http_server(self.engine, "127.0.0.1", 0, workbench=self.wb)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        origin = f"http://127.0.0.1:{srv.server_port}"
        def request(method, path, payload=None, site=origin):
            conn = HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
            try:
                headers = {"Content-Type": "application/json", "Origin": site}
                conn.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=headers)
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()
        code, body = request("GET", "/workbench")
        self.assertEqual(code, 200)
        self.assertIn(b"id=\"confirm\"", body)
        self.assertEqual(request("POST", "/api/workbench/capture", {}, "https://outside.example")[0], 403)
        code, body = request("POST", "/api/workbench/capture", {})
        self.assertEqual(code, 200)
        id_ = json.loads(body)["task"]["id"]
        code, body = request("POST", "/api/workbench/draft", {"id": id_})
        self.assertEqual(code, 200)
        draft = json.loads(body)["task"]
        self.assertEqual(self.view["send_calls"], 0)
        code, body = request("POST", "/api/workbench/confirm",
                             {"id": id_, "version": draft["version"], "text": draft["draft"]})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["task"]["state"], "verified")
        self.assertEqual(self.view["send_calls"], 1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serve-fixture":
        with tempfile.TemporaryDirectory() as path:
            engine, workbench, _ = fixture(Path(path))
            with create_http_server(engine, "127.0.0.1", int(sys.argv[2]), workbench=workbench) as server:
                print(f"http://127.0.0.1:{server.server_port}/workbench", flush=True)
                server.serve_forever()
    else:
        unittest.main()
