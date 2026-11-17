"""Durable human-reviewed replies, using only the current visible chat."""
import hashlib
import json
import re
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .auth_gate import StudioPluginUnauthorizedError
from .realtime_monitor import _bubble_signature


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkbenchError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


class ReviewLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS review (
                id TEXT PRIMARY KEY, target TEXT NOT NULL, incoming TEXT NOT NULL,
                state TEXT NOT NULL, updated TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                draft TEXT NOT NULL DEFAULT '', basis TEXT NOT NULL DEFAULT '{}',
                reason TEXT NOT NULL DEFAULT '', window_token TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS review_event (
                seq INTEGER PRIMARY KEY, task TEXT NOT NULL, at TEXT NOT NULL,
                stage TEXT NOT NULL, code TEXT NOT NULL)""")
            for row in db.execute("SELECT id FROM review WHERE state='sending'").fetchall():
                self.update(db, row["id"], "unknown", "interrupted")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        finally:
            db.close()

    def event(self, db, task, stage, code=""):
        db.execute("INSERT INTO review_event(task,at,stage,code) VALUES(?,?,?,?)", (task, now(), stage, code))

    def update(self, db, task, state, reason="", **values):
        if not set(values) <= {"draft", "basis", "version"}:
            raise ValueError("invalid ledger field")
        changes = {"state": state, "updated": now(), "reason": reason, **values}
        db.execute("UPDATE review SET " + ",".join(f"{k}=?" for k in changes) + " WHERE id=?",
                   (*changes.values(), task))
        self.event(db, task, state, reason)

    def get(self, db, task, *, events=True):
        row = db.execute("SELECT * FROM review WHERE id=?", (task,)).fetchone()
        if row is None:
            raise WorkbenchError("task_not_found", 404)
        result = dict(row)
        result["basis"] = json.loads(result["basis"])
        if events:
            result["events"] = [dict(e) for e in db.execute(
                "SELECT at,stage,code FROM review_event WHERE task=? ORDER BY seq DESC LIMIT 30", (task,))]
        return result

    def list(self):
        with self.transaction() as db:
            rows = db.execute("SELECT id FROM review ORDER BY rowid DESC LIMIT 100").fetchall()
            return [self.get(db, r["id"], events=False) for r in rows]

    def add(self, task, target, incoming, token):
        with self.transaction() as db:
            changed = db.execute(
                "INSERT OR IGNORE INTO review(id,target,incoming,state,updated,window_token) VALUES(?,?,?,'new',?,?)",
                (task, target, incoming, now(), token)).rowcount
            if changed:
                self.event(db, task, "new", "incoming_observed")
            return self.get(db, task)


def latest_peer(view):
    bubbles = view.get("bubbles") or []
    if not bubbles or bubbles[-1].get("direction") != "peer":
        return None
    last = bubbles[-1]
    text = str(last.get("text") or "").strip()
    if not text or len(text) > 4000:
        return None
    prior = next((b.get("text", "") for b in reversed(bubbles[:-1]) if b.get("direction") == "self"), "")
    signature = _bubble_signature(view["headerTitle"], last, prior)
    task = hashlib.sha256((view["headerTitle"] + "\0" + signature).encode()).hexdigest()[:32]
    return task, text


class Workbench:
    def __init__(self, engine, ledger, *, idle_wait=90):
        self.engine, self.ledger = engine, ledger
        self.input_lock = threading.Lock()
        self.draft_lock = threading.Lock()
        self.idle_wait = idle_wait

    def status(self):
        auth = self.engine.auth_gate.get_state()
        capabilities = (auth.get("capabilities") or []) if auth.get("authorized") is True else []
        allowed = lambda cap: cap in capabilities or "*" in capabilities
        native = self.engine._run_native(["status"], timeout=4)
        if not native.get("ok") or native.get("reviewedSendProtocol") != 1:
            code = "driver_unavailable"
        elif not native.get("wechatRunning"):
            code = "wechat_closed"
        elif not native.get("windowCount"):
            code = "window_missing"
        elif not native.get("screenCaptureTrusted"):
            code = "screen_permission"
        elif not allowed("read_messages"):
            code = "read_permission"
        else:
            code = "ready"
        return {"connection": code, "canRead": code == "ready", "canSend": code == "ready"
                and bool(native.get("accessibilityTrusted")) and bool(native.get("postEventTrusted"))
                and allowed("send_text_live")}

    def bound(self, title):
        return next((b for b in self.engine.bindings.list_bindings() if b.get("target") == title), None)

    def capture(self):
        status = self.status()
        if not status["canRead"]:
            raise WorkbenchError(status["connection"])
        n = self.engine._run_native(["status"], timeout=4)
        windows = n.get("windows") or []
        if n.get("reviewedSendProtocol") != 1 or len(windows) != 1 or not isinstance(windows[0].get("windowID"), int):
            raise WorkbenchError("window_ambiguous")
        return self.read_window(n, windows[0]["windowID"])

    def read_window(self, n, window):
        candidates = {item.get("windowID"): item for item in n.get("windows") or []}
        if n.get("reviewedSendProtocol") != 1 or window not in candidates:
            raise WorkbenchError("window_lost")
        pid = n.get("wechatPID")
        if not isinstance(pid, int) or pid < 1:
            raise WorkbenchError("window_ambiguous")
        token = f"{pid}:{window}"
        # Never launch WeChat and never retain a screenshot in the task ledger.
        with tempfile.TemporaryDirectory(dir=self.ledger.path.parent) as d:
            image = Path(d) / "pane.png"
            ocr = self.engine._run_native(
                ["capture-ocr", "--no-activate", "--window-id", str(window), "--out", str(image)], timeout=15)
            if not ocr.get("ok") or ocr.get("windowID") != window:
                raise WorkbenchError("capture_failed")
            view = self.engine.inspector.extract_structured_bubbles(
                ocr, snapshot_path=image, bounds=ocr.get("windowBounds") or candidates[window]["bounds"])
        title = str(view.get("headerTitle") or "")
        if not self.bound(title):
            raise WorkbenchError("conversation_unbound")
        return {**view, "window": window, "token": token}

    def ingest(self):
        self.engine._require("read_messages")
        with self.input_lock:
            return self.ingest_view(self.capture())

    def ingest_view(self, view):
        peer = latest_peer(view)
        if not peer:
            return None
        task, incoming = peer
        return self.ledger.add(task, view["headerTitle"], incoming, view["token"])

    def draft(self, task):
        self.engine._require("read_messages")
        if not self.draft_lock.acquire(blocking=False):
            raise WorkbenchError("draft_busy")
        try:
            return self._draft(task)
        finally:
            self.draft_lock.release()

    def _draft(self, task):
        with self.ledger.transaction() as db:
            row = self.ledger.get(db, task)
            if row["state"] not in {"new", "manual", "ready"}:
                raise WorkbenchError("not_draftable")
            self.ledger.event(db, task, "drafting")
        binding = self.bound(row["target"])
        if not binding:
            raise WorkbenchError("conversation_unbound")
        try:
            # Do not call a remote model for a message that has no KB match.
            if not self.engine.knowledge.search_context(row["incoming"], limit=6).get("entries"):
                draft, basis, reason = "", {}, "no_knowledge"
            else:
                result = self.engine.personas.generate_smart_reply(
                    row["target"], row["incoming"], knowledge_store=self.engine.knowledge, binding=binding)
                raw = result.get("basis") or {}
                refs = raw.get("documentRefs") or []
                basis = {k: raw.get(k) for k in ("generationMode", "modelUsed", "providerUsed")}
                basis["documentRefs"] = refs
                draft = str(result.get("replyText") or "").strip() if result.get("ok") and refs else ""
                reason = "" if draft else "no_grounded_draft"
        except Exception:
            draft, basis, reason = "", {}, "draft_failed"
        self.engine._require("read_messages")
        with self.ledger.transaction() as db:
            current = self.ledger.get(db, task)
            if current["state"] not in {"new", "manual", "ready"} or current["version"] != row["version"]:
                raise WorkbenchError("draft_changed")
            self.ledger.update(db, task, "ready" if draft else "manual", reason,
                               draft=draft, basis=json.dumps(basis, ensure_ascii=False), version=row["version"] + 1)
            return self.ledger.get(db, task)

    recommendation_space = "personal"

    def recommend(self, task):
        """Rank deterministic drafts against published knowledge; never authorize a send."""
        self.engine._require("read_messages")
        with self.ledger.transaction() as db:
            row = self.ledger.get(db, task)
            if row["state"] not in {"new", "manual", "ready"}:
                raise WorkbenchError("not_draftable")
            if row["basis"].get("adopted"):
                return row
            entries = self.engine.knowledge.search_context(
                row["incoming"], space_id=self.recommendation_space, limit=3
            ).get("entries") or []
            fact = str(entries[0].get("body", "")).strip() if entries else ""
            # Never truncate a fact: incomplete passages are sent for review instead.
            fact = fact if 0 < len(fact) <= 260 else ""
            basis = {"generationMode": "kb_recommendations", "documentRefs": [], "options": []}
            if fact:
                doc = entries[0]
                basis["documentRefs"] = [{k: doc[k] for k in ("id", "title", "revision")}]
                first = re.split(r"(?<=[。！？])", fact, maxsplit=1)[0]
                variants = [
                    ("直答", "您好，" + fact),
                    ("简答", first),
                    ("便于跟进", fact + " 如果您还有具体情况，可以告诉我。"),
                ]
                seen = set()
                for label, reply in variants:
                    key = re.sub(r"\s+", "", reply)
                    if key not in seen:
                        seen.add(key)
                        basis["options"].append({"id": str(len(basis["options"]) + 1),
                                                 "label": label, "text": reply})
            self.ledger.update(db, task, "ready" if fact else "manual", "" if fact else "no_knowledge",
                               draft="", basis=json.dumps(basis, ensure_ascii=False), version=row["version"]+1)
            return self.ledger.get(db, task)

    def adopt(self, task, version, choice):
        self.engine._require("read_messages")
        with self.ledger.transaction() as db:
            row = self.ledger.get(db, task)
            basis = row["basis"]
            if (type(version) is not int or version != row["version"] or row["state"] not in {"ready", "manual"}
                    or basis.get("generationMode") != "kb_recommendations" or basis.get("adopted")):
                raise WorkbenchError("draft_changed")
            option = next((o for o in basis["options"] if o["id"] == choice), None)
            if choice != "defer" and option is None:
                raise WorkbenchError("invalid_choice", 400)
            basis["adopted"] = choice
            state, reason = ("deferred", "deferred_by_user") if option is None else ("adopted", "draft_adopted")
            self.ledger.update(db, task, state, reason, draft=option["text"] if option else "",
                               basis=json.dumps(basis, ensure_ascii=False), version=version+1)
            return self.ledger.get(db, task)

    confirmation_state = "ready"

    def confirm(self, task, version, text):
        self.engine._require("read_messages")
        # Reject retries without ever repeating the external action.
        with self.input_lock:
            with self.ledger.transaction() as db:
                row = self.ledger.get(db, task)
                if row["state"] in {"sending", "verified", "unknown", "failed"}:
                    return row
                if row["state"] != self.confirmation_state or type(version) is not int or version != row["version"] or text != row["draft"]:
                    raise WorkbenchError("draft_changed")
            try:
                self.engine._require("send_text_live")
                if not self.status()["canSend"]:
                    raise WorkbenchError("send_permission")
                deadline = time.monotonic() + self.idle_wait
                while not self.engine.human_guard.check_can_operate().get("canOperate"):
                    if time.monotonic() >= deadline:
                        raise WorkbenchError("human_pause")
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
                before = self.capture()
                if not self.engine.human_guard.check_can_operate().get("canOperate"):
                    raise WorkbenchError("human_pause")
                if (before["headerTitle"] != row["target"] or before["token"] != row["window_token"]
                        or (latest_peer(before) or (None,))[0] != task):
                    raise WorkbenchError("conversation_changed")
            except (WorkbenchError, StudioPluginUnauthorizedError) as exc:
                with self.ledger.transaction() as db:
                    self.ledger.event(db, task, "blocked", getattr(exc, "code", "unauthorized"))
                raise
            with self.ledger.transaction() as db:
                current = self.ledger.get(db, task)
                if current["state"] != self.confirmation_state or current["version"] != version:
                    raise WorkbenchError("draft_changed")
                self.ledger.update(db, task, "sending", "confirmed")
            state, reason = self._send(row, before)
            with self.ledger.transaction() as db:
                self.ledger.update(db, task, state, reason)
                return self.ledger.get(db, task)

    def _send(self, row, before):
        text = row["draft"]
        try:
            result = self.engine.send_text(
                row["target"], text, dry_run=False, silent_mode=False, confirm_send=True,
                skip_navigation=True, expected_window_id=before["window"])
            code = result.get("status")
            if code in {"blocked_whitelist", "blocked_duplicate", "review_target_changed",
                        "review_input_busy", "review_no_input", "review_ax_denied", "unsupported_review_driver"}:
                return "failed", code
            if code == "sent":
                after = self.capture()
                if after["headerTitle"] == row["target"] and after["token"] == before["token"]:
                    def matches(v):
                        # OCR can wrap lines; do not drop punctuation or change characters.
                        key = "".join(text.split())
                        return [b for b in v["bubbles"] if b.get("direction") == "self"
                                and "".join(str(b.get("text") or "").split()) == key]
                    latest = (after["bubbles"] or [None])[-1]
                    if latest and latest in matches(after) and len(matches(after)) > len(matches(before)):
                        return "verified", "new_outbound_bubble"
        except Exception:
            pass
        return "unknown", "no_delivery_evidence"
