"""Local manual drafts, kept apart from the reviewed-send ledger."""

import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


_FIELDS = {"id", "version", "target", "incoming", "draft"}
_STATES = {"pending", "completed"}
_ID = re.compile(r"[0-9a-f]{32}")


class SavedDraftError(Exception):
    def __init__(self, code, status):
        super().__init__(code)
        self.code, self.status = code, status


def _validate_id(identifier):
    if not isinstance(identifier, str) or _ID.fullmatch(identifier) is None:
        raise SavedDraftError("invalid_saved_draft", 400)


def _validate_body(body):
    if not isinstance(body, dict) or body.keys() != _FIELDS:
        raise SavedDraftError("invalid_saved_draft", 400)
    _validate_id(body["id"])
    if type(body["version"]) is not int or not 0 <= body["version"] < 2**63 - 1:
        raise SavedDraftError("invalid_saved_draft", 400)
    for field, limit in (("target", 256), ("incoming", 3000), ("draft", 3000)):
        value = body[field]
        if not isinstance(value, str) or len(value) > limit or "\0" in value:
            raise SavedDraftError("invalid_saved_draft", 400)
        if field != "incoming" and not value.strip():
            raise SavedDraftError("invalid_saved_draft", 400)
        if field == "target" and value != value.strip():
            raise SavedDraftError("invalid_saved_draft", 400)
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise SavedDraftError("invalid_saved_draft", 400) from None


class SavedDraftStore:
    def __init__(self, path):
        self.path = Path(path)

    def _check_path(self):
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise SavedDraftError("workbench_error", 500)

    def _read_db(self):
        self._check_path()
        if not self.path.is_file():
            return None
        db = sqlite3.connect(self.path.absolute().as_uri() + "?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        # Keep the schema probe and row query in the same snapshot: the first
        # completion can create its side table while a legacy read is in flight.
        db.execute("BEGIN")
        return db

    @staticmethod
    def _has_table(db):
        return db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='saved_draft'"
        ).fetchone() is not None

    @staticmethod
    def _state_sql(db):
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='saved_draft_status'"
        ).fetchone() is None:
            return "'pending'"
        return """CASE WHEN EXISTS (
            SELECT 1 FROM saved_draft_status WHERE draft_id=saved_draft.id
        ) THEN 'completed' ELSE 'pending' END"""

    def _row(self, db, identifier):
        state = self._state_sql(db)
        return db.execute(
            f"SELECT saved_draft.*, {state} AS state FROM saved_draft WHERE id=?", (identifier,)
        ).fetchone()

    def list(self):
        db = self._read_db()
        if db is None:
            return []
        with closing(db):
            if not self._has_table(db):
                return []
            state = self._state_sql(db)
            return [dict(row) for row in db.execute(f"""
                SELECT id, target, updated, version, {state} AS state,
                       CASE WHEN length(draft) > 120 THEN substr(draft, 1, 120) || '…' ELSE draft END AS preview
                FROM saved_draft ORDER BY updated DESC, id ASC""")]

    def get(self, identifier):
        _validate_id(identifier)
        db = self._read_db()
        if db is not None:
            with closing(db):
                if self._has_table(db):
                    row = self._row(db, identifier)
                    if row is not None:
                        return dict(row)
        raise SavedDraftError("saved_draft_not_found", 404)

    def save(self, body):
        _validate_body(body)
        self._check_path()
        if body["version"] and not self.path.is_file():
            raise SavedDraftError("saved_draft_not_found", 404)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)

        identifier, version = body["id"], body["version"]
        target, incoming, draft = body["target"], body["incoming"], body["draft"]
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS saved_draft (
                id TEXT PRIMARY KEY, target TEXT NOT NULL, incoming TEXT NOT NULL,
                draft TEXT NOT NULL, updated TEXT NOT NULL, version INTEGER NOT NULL)""")
            row = self._row(db, identifier)
            if row is None and version != 0:
                raise SavedDraftError("saved_draft_not_found", 404)
            if row is not None:
                if row["state"] == "completed":
                    raise SavedDraftError("saved_draft_completed", 409)
                if (version in {row["version"], row["version"] - 1}
                        and (target, incoming, draft) == (row["target"], row["incoming"], row["draft"])):
                    # Either unchanged or the previous save succeeded but its response was lost.
                    return dict(row)
                if target != row["target"] or version != row["version"]:
                    raise SavedDraftError("saved_draft_changed", 409)
            updated = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            if row is None:
                db.execute(
                    "INSERT INTO saved_draft(id,target,incoming,draft,updated,version) VALUES(?,?,?,?,?,?)",
                    (identifier, target, incoming, draft, updated, 1))
            else:
                db.execute(
                    "UPDATE saved_draft SET incoming=?,draft=?,updated=?,version=? WHERE id=?",
                    (incoming, draft, updated, version + 1, identifier))
            return dict(self._row(db, identifier))

    def set_state(self, identifier, body):
        _validate_id(identifier)
        if not isinstance(body, dict) or body.keys() != {"version", "state"}:
            raise SavedDraftError("invalid_saved_draft_state", 400)
        version, state = body["version"], body["state"]
        if (type(version) is not int or not 1 <= version < 2**63 - 1
                or not isinstance(state, str) or state not in _STATES):
            raise SavedDraftError("invalid_saved_draft_state", 400)
        self._check_path()
        if not self.path.is_file():
            raise SavedDraftError("saved_draft_not_found", 404)

        with closing(sqlite3.connect(self.path.absolute().as_uri() + "?mode=rw", uri=True, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, identifier) if self._has_table(db) else None
            if row is None:
                raise SavedDraftError("saved_draft_not_found", 404)
            if row["state"] == state and version in {row["version"], row["version"] - 1}:
                # Retrying a successful request must not add another revision.
                return dict(row)
            if version != row["version"]:
                raise SavedDraftError("saved_draft_changed", 409)

            if state == "completed":
                db.execute("""CREATE TABLE IF NOT EXISTS saved_draft_status (
                    draft_id TEXT PRIMARY KEY NOT NULL REFERENCES saved_draft(id) ON DELETE CASCADE)""")
                db.execute("INSERT INTO saved_draft_status(draft_id) VALUES(?)", (identifier,))
            else:
                db.execute("DELETE FROM saved_draft_status WHERE draft_id=?", (identifier,))
            db.execute("UPDATE saved_draft SET updated=?,version=? WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(timespec="microseconds"), version + 1, identifier))
            return dict(self._row(db, identifier))
