"""Supervisor evaluation, test-contact sandbox, `#` hashtag loop, and dual-track scoring."""

from __future__ import annotations

import inspect
import json
import re
import sqlite3
import threading
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .coevolution_engine import evaluate_turn_human_likeness
from .knowledge_kf_engine import split_search_terms
from .safety import normalize_chat_name

DEFAULT_SUPERVISOR_DB_PATH = Path("config/supervisor_eval.sqlite")
SUPERVISOR_EVAL_SCHEMA_VERSION = "openbot.supervisor-eval/1"

AUTHORIZED_NON_WECHAT_CHANNELS = frozenset({"workbench", "mobile", "sparring_sim"})
BUILTIN_ADMIN_CONTACTS: Tuple[str, ...] = ("文件传输助手",)

MIN_ENTRY_WEIGHT = 0.35
MAX_ENTRY_WEIGHT = 1.45
DEFAULT_ENTRY_WEIGHT = 1.0

_SCORE_WEIGHTS: Dict[str, float] = {
    "kbGrounding": 0.22,
    "terminologyAlignment": 0.16,
    "salesProgression": 0.22,
    "complianceSafety": 0.22,
    "humanLikeness": 0.18,
}

_HASHTAG_PREFIX_RE = re.compile(r"^\s*[#＃]")
_LEAKED_DIRECTIVE_LINE_RE = re.compile(
    r"(?:^|\n)\s*[#＃]\s*(?:评分|打分|话术|记住|词汇|术语|接管|停|停止|暂停|恢复|继续|[1-5]\s*[分星]|\s+\S)"
)

_RATE_KEYWORD_RE = re.compile(r"^(?:评分|打分)\s*[:：]?\s*([1-5]|\d+)\s*[分星]?\s*(.*)$")
_RATE_COMPACT_RE = re.compile(r"^([1-5])\s*[分星]\s*(.*)$")
_SCRIPT_RE = re.compile(r"^(?:话术|记住)\s*[:：]?\s*(.+)$", re.DOTALL)
_TERM_RE = re.compile(r"^(?:词汇|术语)\s*[:：]?\s*(.+)$", re.DOTALL)
_TAKEOVER_RE = re.compile(r"^(接管|人工接管|人工|停|停止|暂停|恢复托管|恢复|继续)(?:\s+(.*))?$")
_ARROW_SPLIT_RE = re.compile(r"\s*(?:=>|＝＞|->|→)\s*")

_FORBIDDEN_CLAUSE_RE = re.compile(
    r"(?:别|不要|不能|切勿|严禁|禁止|少说|避免)([^，。；,!！\n]{2,20})"
)
_FORBIDDEN_FILLER_TOKENS = frozenset({
    "这样", "这么", "那样", "直接", "上来", "一上来", "随便", "乱说", "乱回", "开口",
})

_SALES_QUESTION_RE = re.compile(r"[?？]|(?:吗|呢|几套|多少|什么|哪|方便|大概|预算|需求|场景)\s*$")
_SALES_CTA_RE = re.compile(
    r"(?:几套|多少|预算|需求|场景|行业|对比|方案|报价|区间|样品|演示|发您|发你|看看|聊聊|安排|沟通|周期|交付|试用|优惠)"
)
_OVERPROMISE_RE = re.compile(
    r"(?:100%|百分百|绝对保证|稳赚不赔|包过|无条件全额退款|永久免费)"
)
_INTERNAL_JARGON_RE = re.compile(
    r"(?:FTS5|SQLite|AXUIElement|CGEvent|Magpie|WaveBot|OpenBot)",
    re.IGNORECASE,
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_iso_days_ago(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
    return dt.isoformat(timespec="seconds")


def _norm_contact(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    return normalize_chat_name(raw) or raw


def _contact_key(name: str) -> str:
    return _norm_contact(name).casefold()


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _json_loads_list(raw: Any) -> List[Any]:
    if isinstance(raw, list):
        return list(raw)
    try:
        parsed = json.loads(raw or "[]")
        return list(parsed) if isinstance(parsed, list) else []
    except Exception:
        return []


def _json_loads_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw or "{}")
        return dict(parsed) if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _extract_keywords(text: str, extra: Iterable[str] = (), limit: int = 16) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []

    def _push(item: str) -> None:
        clean = unicodedata.normalize("NFKC", str(item or "")).strip()
        if len(clean) < 2:
            return
        cf = clean.casefold()
        if cf in seen:
            return
        seen.add(cf)
        result.append(clean[:40])

    for item in extra:
        _push(item)
    for tok in split_search_terms(text, max_terms=limit):
        _push(tok)
    return result[:limit]


def _char_bigrams(text: str) -> set[str]:
    clean = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")).casefold())
    if len(clean) < 2:
        return {clean} if clean else set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def _extract_reply_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("revisedReply", "reply", "text", "content", "message"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return str(raw).strip()


def _invoke_reply_generator(
    reply_generator: Callable[..., Any],
    contact: str,
    trigger_text: str,
    *,
    directive: str = "",
    negative_constraints: Sequence[Dict[str, Any]] = (),
) -> str:
    candidate_kwargs: Dict[str, Any] = {
        "directive": directive,
        "negative_constraints": list(negative_constraints),
    }
    try:
        sig = inspect.signature(reply_generator)
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if accepts_var_kw:
            kwargs = candidate_kwargs
        else:
            kwargs = {k: v for k, v in candidate_kwargs.items() if k in sig.parameters}
    except (TypeError, ValueError):
        kwargs = candidate_kwargs

    raw = reply_generator(contact, trigger_text, **kwargs)
    return _extract_reply_text(raw)


def _invoke_takeover_cb(
    takeover_cb: Callable[..., Any],
    contact: str,
    action: str,
) -> Any:
    try:
        sig = inspect.signature(takeover_cb)
        pos_params = [
            p
            for p in sig.parameters.values()
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
        if has_var_pos or len(pos_params) >= 2:
            return takeover_cb(contact, action)
        if len(pos_params) == 1:
            return takeover_cb(contact)
        return takeover_cb()
    except (TypeError, ValueError):
        return takeover_cb(contact, action)


def is_hashtag_directive(text: str) -> bool:
    """Return True when incoming text begins with `#` or fullwidth `＃` and carries content."""
    raw = str(text or "")
    stripped = raw.strip()
    if not _HASHTAG_PREFIX_RE.match(stripped):
        return False
    return bool(stripped[1:].strip())


def is_blocked_outbound_directive(text: str) -> bool:
    """Block raw `#...` directives from ever being sent to normal WeChat customers."""
    raw = str(text or "")
    if is_hashtag_directive(raw):
        return True
    return bool(_LEAKED_DIRECTIVE_LINE_RE.search(raw))


def parse_hashtag_directive(text: str) -> Dict[str, Any]:
    """Parse `#` / `＃` supervisor commands into 5 structured intents."""
    raw = str(text or "")
    if not is_hashtag_directive(raw):
        return {
            "ok": False,
            "isDirective": False,
            "intent": "none",
            "rawText": raw,
        }

    body = unicodedata.normalize("NFKC", raw.strip()[1:]).strip()

    # 1. Takeover control: #接管, #停, #恢复
    takeover_match = _TAKEOVER_RE.match(body)
    if takeover_match:
        cmd = takeover_match.group(1)
        note = (takeover_match.group(2) or "").strip()
        if cmd in ("恢复", "恢复托管", "继续"):
            action = "resume"
            paused = False
        elif cmd == "接管" or cmd in ("人工接管", "人工"):
            action = "takeover"
            paused = True
        else:
            action = "pause"
            paused = True
        return {
            "ok": True,
            "isDirective": True,
            "intent": "takeover_control",
            "action": action,
            "paused": paused,
            "command": cmd,
            "note": note,
            "rawText": raw,
        }

    # 2. Rating: #评分 2 语气太硬 / #2分 没说交付周期 / #5星 很好
    rate_match = _RATE_KEYWORD_RE.match(body) or _RATE_COMPACT_RE.match(body)
    if rate_match:
        raw_stars = int(rate_match.group(1))
        stars = int(_clamp(raw_stars, 1, 5))
        comment = (rate_match.group(2) or "").strip(" ：:，,")
        return {
            "ok": True,
            "isDirective": True,
            "intent": "rate",
            "stars": stars,
            "comment": comment,
            "tags": [],
            "rawText": raw,
        }

    # 3. Save script: #话术 问价格 => 先了解需求数量再给区间 / #记住 老客户统一9折
    script_match = _SCRIPT_RE.match(body)
    if script_match:
        payload = script_match.group(1).strip()
        parts = _ARROW_SPLIT_RE.split(payload, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            trigger = parts[0].strip()
            script_body = parts[1].strip()
            title = trigger[:40]
        else:
            trigger = ""
            script_body = payload
            title = payload[:28]
        return {
            "ok": True,
            "isDirective": True,
            "intent": "save_script",
            "title": title,
            "trigger": trigger,
            "body": script_body,
            "ruleText": script_body,
            "rawText": raw,
        }

    # 4. Save terminology: #词汇 定制版 => 指支持按logo和尺寸定制的方案
    term_match = _TERM_RE.match(body)
    if term_match:
        payload = term_match.group(1).strip()
        parts = _ARROW_SPLIT_RE.split(payload, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            term = parts[0].strip()
            definition = parts[1].strip()
        else:
            colon_parts = re.split(r"\s*[:：]\s*|\s+", payload, maxsplit=1)
            term = colon_parts[0].strip()
            definition = colon_parts[1].strip() if len(colon_parts) > 1 and colon_parts[1].strip() else payload
        return {
            "ok": True,
            "isDirective": True,
            "intent": "save_term",
            "term": term,
            "definition": definition,
            "rawText": raw,
        }

    # 5. Default fallback: critique_rewrite
    return {
        "ok": True,
        "isDirective": True,
        "intent": "critique_rewrite",
        "ruleText": body,
        "directive": body,
        "rawText": raw,
    }


def _violates_negative_constraint(reply_text: str, constraint: Dict[str, Any]) -> Optional[str]:
    """Return a concise violation reason if reply_text repeats a constrained bad behavior."""
    reply_norm = unicodedata.normalize("NFKC", str(reply_text or "")).strip()
    if not reply_norm:
        return None
    reply_cf = reply_norm.casefold()

    bad_reply = unicodedata.normalize("NFKC", str(constraint.get("badReply") or constraint.get("bad_reply") or "")).strip()
    if bad_reply:
        bad_cf = bad_reply.casefold()
        if bad_cf == reply_cf:
            return "repeats_rejected_reply"
        if len(bad_cf) >= 8 and bad_cf in reply_cf:
            return "contains_rejected_reply_segment"
        bad_bg = _char_bigrams(bad_cf)
        rep_bg = _char_bigrams(reply_cf)
        if bad_bg and rep_bg:
            jaccard = len(bad_bg & rep_bg) / max(1, len(bad_bg | rep_bg))
            if jaccard >= 0.62:
                return "high_similarity_to_rejected_reply"

    rule_text = unicodedata.normalize(
        "NFKC",
        str(constraint.get("ruleText") or constraint.get("rule_text") or ""),
    ).strip()
    if not rule_text:
        return None

    for clause_match in _FORBIDDEN_CLAUSE_RE.finditer(rule_text):
        clause = clause_match.group(1).strip()
        if not clause:
            continue
        if ("底价" in clause or "报价" in clause or "报低价" in clause) and (
            "底价" in reply_cf
            or bool(re.search(r"(?:¥|￥)\s*\d+|\d+\s*(?:元|块|万)/?(?:套|个|件)?", reply_cf))
        ):
            return f"violates_rule:{clause}"

        tokens = [
            tok
            for tok in split_search_terms(clause, max_terms=6)
            if tok not in _FORBIDDEN_FILLER_TOKENS and len(tok) >= 2
        ]
        matched_forbidden = [tok for tok in tokens if tok.casefold() in reply_cf]
        if matched_forbidden:
            return f"violates_rule:{matched_forbidden[0]}"

    return None


class SupervisorEvalEngine:
    """Persists sparring turns, test contacts, hashtag corrections, and dual-track evals."""

    def __init__(self, db_path: Path | str = DEFAULT_SUPERVISOR_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_schema(self) -> None:
        schema_sql = """
        CREATE TABLE IF NOT EXISTS test_contacts (
            contact_key TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sparring_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_name TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'wechat',
            incoming_text TEXT NOT NULL,
            ai_reply TEXT NOT NULL,
            matched_entry_ids_json TEXT NOT NULL DEFAULT '[]',
            auto_score_json TEXT NOT NULL DEFAULT '{}',
            supervisor_rating INTEGER,
            supervisor_tags_json TEXT NOT NULL DEFAULT '[]',
            supervisor_comment TEXT NOT NULL DEFAULT '',
            hashtag_directive TEXT NOT NULL DEFAULT '',
            revised_reply TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sparring_turns_contact_id
            ON sparring_turns(contact_name, id DESC);
        CREATE INDEX IF NOT EXISTS idx_sparring_turns_created
            ON sparring_turns(created_at DESC);
        CREATE TABLE IF NOT EXISTS negative_constraints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_text TEXT NOT NULL DEFAULT '',
            bad_reply TEXT NOT NULL DEFAULT '',
            rule_text TEXT NOT NULL,
            corrected_reply TEXT NOT NULL DEFAULT '',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            source_contact TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entry_quality_stats (
            entry_id TEXT PRIMARY KEY,
            rating_sum INTEGER NOT NULL DEFAULT 0,
            rating_count INTEGER NOT NULL DEFAULT 0,
            low_count INTEGER NOT NULL DEFAULT 0,
            high_count INTEGER NOT NULL DEFAULT 0,
            weight REAL NOT NULL DEFAULT 1.0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS golden_exemplars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_text TEXT NOT NULL DEFAULT '',
            reply_text TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT '',
            rating INTEGER NOT NULL DEFAULT 5,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            source_contact TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
        with self._lock, self._connect() as conn:
            conn.executescript(schema_sql)

    @staticmethod
    def _turn_view(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "turnId": int(row["id"]),
            "contactName": str(row["contact_name"]),
            "channel": str(row["channel"]),
            "incomingText": str(row["incoming_text"]),
            "aiReply": str(row["ai_reply"]),
            "matchedEntryIds": [str(x) for x in _json_loads_list(row["matched_entry_ids_json"])],
            "autoScore": _json_loads_dict(row["auto_score_json"]),
            "supervisorRating": (
                int(row["supervisor_rating"]) if row["supervisor_rating"] is not None else None
            ),
            "supervisorTags": [str(x) for x in _json_loads_list(row["supervisor_tags_json"])],
            "supervisorComment": str(row["supervisor_comment"] or ""),
            "hashtagDirective": str(row["hashtag_directive"] or ""),
            "revisedReply": str(row["revised_reply"] or ""),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    @staticmethod
    def _constraint_view(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "triggerText": str(row["trigger_text"]),
            "badReply": str(row["bad_reply"]),
            "ruleText": str(row["rule_text"]),
            "correctedReply": str(row["corrected_reply"]),
            "keywords": [str(x) for x in _json_loads_list(row["keywords_json"])],
            "sourceContact": str(row["source_contact"]),
            "active": bool(row["active"]),
            "createdAt": str(row["created_at"]),
        }

    @staticmethod
    def _exemplar_view(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "triggerText": str(row["trigger_text"]),
            "replyText": str(row["reply_text"]),
            "stage": str(row["stage"]),
            "rating": int(row["rating"]),
            "keywords": [str(x) for x in _json_loads_list(row["keywords_json"])],
            "sourceContact": str(row["source_contact"]),
            "createdAt": str(row["created_at"]),
        }

    # ------------------------------------------------------------------
    # Test contact sandbox & authorization
    # ------------------------------------------------------------------
    def mark_test_contact(self, name: str, note: str = "") -> Dict[str, Any]:
        display = _norm_contact(name)
        if not display:
            raise ValueError("Test contact name cannot be empty.")
        key = display.casefold()
        now = _utc_iso_now()
        clean_note = str(note or "").strip()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO test_contacts(contact_key, display_name, note, created_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(contact_key) DO UPDATE SET
                    display_name = excluded.display_name,
                    note = excluded.note
                """,
                (key, display, clean_note, now),
            )
            row = conn.execute(
                "SELECT * FROM test_contacts WHERE contact_key = ?",
                (key,),
            ).fetchone()
        return {
            "ok": True,
            "contactKey": str(row["contact_key"]),
            "displayName": str(row["display_name"]),
            "note": str(row["note"]),
            "createdAt": str(row["created_at"]),
        }

    def unmark_test_contact(self, name: str) -> Dict[str, Any]:
        key = _contact_key(name)
        if not key:
            return {"ok": True, "removed": False, "contactKey": ""}
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM test_contacts WHERE contact_key = ?", (key,))
        return {"ok": True, "removed": cur.rowcount > 0, "contactKey": key}

    def is_test_contact(self, name: str) -> bool:
        key = _contact_key(name)
        if not key:
            return False
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM test_contacts WHERE contact_key = ?",
                (key,),
            ).fetchone()
        return row is not None

    def list_test_contacts(self) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM test_contacts ORDER BY created_at DESC, contact_key ASC"
            ).fetchall()
        return [
            {
                "contactKey": str(row["contact_key"]),
                "displayName": str(row["display_name"]),
                "note": str(row["note"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    def is_authorized_supervisor(
        self,
        sender: str,
        *,
        channel: str = "wechat",
        admin_contacts: Iterable[str] = (),
    ) -> bool:
        """Return True ONLY for internal channels, test contacts, or admin contacts."""
        channel_cf = str(channel or "").strip().casefold()
        if channel_cf in AUTHORIZED_NON_WECHAT_CHANNELS:
            return True

        sender_key = _contact_key(sender)
        if not sender_key:
            return False

        builtin_keys = {_contact_key(c) for c in BUILTIN_ADMIN_CONTACTS}
        if sender_key in builtin_keys:
            return True

        if isinstance(admin_contacts, str):
            admin_iter: Iterable[str] = [admin_contacts]
        else:
            admin_iter = admin_contacts or ()
        admin_keys = {_contact_key(c) for c in admin_iter if _contact_key(c)}
        if sender_key in admin_keys:
            return True

        return self.is_test_contact(sender)

    # ------------------------------------------------------------------
    # Static wrappers for convenience
    # ------------------------------------------------------------------
    @staticmethod
    def is_hashtag_directive(text: str) -> bool:
        return is_hashtag_directive(text)

    @staticmethod
    def is_blocked_outbound_directive(text: str) -> bool:
        return is_blocked_outbound_directive(text)

    @staticmethod
    def parse_hashtag_directive(text: str) -> Dict[str, Any]:
        return parse_hashtag_directive(text)

    # ------------------------------------------------------------------
    # Turn recording & scoring
    # ------------------------------------------------------------------
    def auto_score_reply(
        self,
        incoming_text: str,
        reply_text: str,
        *,
        matched_entries: Sequence[Dict[str, Any]] = (),
        terminology_terms: Sequence[Any] = (),
        negative_constraints: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Compute 5-dimension quality score (0..100), stars (1..5), and issues."""
        incoming = str(incoming_text or "").strip()
        reply = str(reply_text or "").strip()
        reply_cf = reply.casefold()
        issues: List[str] = []

        # 1) humanLikeness via coevolution_engine
        hl = evaluate_turn_human_likeness(reply, incoming)
        human_likeness = int(hl.get("humanLikenessScore") or 0)
        for hl_issue in hl.get("issues") or []:
            if hl_issue not in issues:
                issues.append(str(hl_issue))

        # 2) kbGrounding
        entries_list = [e for e in (matched_entries or ()) if isinstance(e, dict)]
        if entries_list:
            entry_terms: set[str] = set()
            for entry in entries_list:
                entry_terms.update(
                    split_search_terms(
                        f"{entry.get('title', '')} {entry.get('body', '')}",
                        max_terms=10,
                    )
                )
                for kw in list(entry.get("keywords") or []) + list(entry.get("synonyms") or []):
                    clean_kw = str(kw or "").strip()
                    if len(clean_kw) >= 2:
                        entry_terms.add(clean_kw)
            hit_count = sum(1 for tok in entry_terms if tok.casefold() in reply_cf)
            if hit_count >= 2:
                kb_grounding = min(100, 75 + min(25, hit_count * 6))
            elif hit_count == 1:
                kb_grounding = 72
            else:
                kb_grounding = 42
                issues.append("low_kb_grounding")
        else:
            in_terms = split_search_terms(incoming, max_terms=8)
            overlap = sum(1 for tok in in_terms if tok.casefold() in reply_cf)
            if len(reply) < 8:
                kb_grounding = 40
                issues.append("ungrounded_short_reply")
            elif in_terms and overlap == 0 and len(reply) < 20:
                kb_grounding = 52
                issues.append("low_context_grounding")
            else:
                kb_grounding = min(90, 72 + overlap * 6)

        # 3) terminologyAlignment
        term_specs: List[Dict[str, Any]] = []
        for item in terminology_terms or ():
            if isinstance(item, str) and item.strip():
                term_specs.append({"term": item.strip(), "aliases": [], "dontSay": []})
            elif isinstance(item, dict):
                t_name = str(item.get("term") or item.get("title") or "").strip()
                if t_name:
                    term_specs.append({
                        "term": t_name,
                        "aliases": list(item.get("aliases") or item.get("synonyms") or []),
                        "dontSay": list(item.get("dontSay") or []),
                    })
        for entry in entries_list:
            if entry.get("kind") == "terminology" and entry.get("title"):
                term_specs.append({
                    "term": str(entry["title"]).strip(),
                    "aliases": list(entry.get("synonyms") or []),
                    "dontSay": [],
                })

        if not term_specs:
            term_alignment = 85
        else:
            relevant_hits = 0
            canonical_hits = 0
            dont_say_hits = 0
            for spec in term_specs:
                t_cf = spec["term"].casefold()
                aliases = [str(a).strip() for a in spec["aliases"] if str(a).strip()]
                dont_says = [str(d).strip() for d in spec["dontSay"] if str(d).strip()]
                used_canonical = t_cf in reply_cf
                used_alias = any(a.casefold() in reply_cf for a in aliases)
                used_dont = any(d.casefold() in reply_cf for d in dont_says)
                mentioned_in_context = (
                    t_cf in incoming.casefold()
                    or any(a.casefold() in incoming.casefold() for a in aliases)
                    or used_canonical
                    or used_alias
                    or used_dont
                )
                if mentioned_in_context:
                    relevant_hits += 1
                    if used_canonical:
                        canonical_hits += 1
                    if used_dont:
                        dont_say_hits += 1
            if dont_say_hits > 0:
                term_alignment = max(25, 65 - dont_say_hits * 20)
                issues.append("terminology_dont_say_used")
            elif relevant_hits == 0:
                term_alignment = 85
            elif canonical_hits == relevant_hits:
                term_alignment = 96
            elif canonical_hits > 0:
                term_alignment = 82
            else:
                term_alignment = 55
                issues.append("terminology_mismatch")

        # 4) salesProgression
        if len(reply) <= 8:
            sales_progression = 35
            issues.append("no_sales_progression")
        else:
            sp_score = 45
            if _SALES_QUESTION_RE.search(reply):
                sp_score += 28
            if _SALES_CTA_RE.search(reply):
                sp_score += 22
            if len(reply) >= 18:
                sp_score += 5
            sales_progression = int(_clamp(sp_score, 0, 100))
            if sales_progression < 65:
                issues.append("weak_sales_progression")

        # 5) complianceSafety
        compliance_safety = 100
        if is_blocked_outbound_directive(reply):
            compliance_safety -= 65
            issues.append("leaked_hashtag_directive")
        if _INTERNAL_JARGON_RE.search(reply):
            compliance_safety -= 40
            issues.append("internal_jargon_leak")
        if _OVERPROMISE_RE.search(reply):
            compliance_safety -= 25
            issues.append("overpromise_risk")

        active_constraints = (
            list(negative_constraints)
            if negative_constraints is not None
            else self.match_negative_constraints(incoming, limit=5)
        )
        violated_constraints: List[str] = []
        for nc in active_constraints:
            reason = _violates_negative_constraint(reply, nc)
            if reason:
                violated_constraints.append(reason)
        if violated_constraints:
            compliance_safety -= 40 * len(violated_constraints)
            issues.append("violates_negative_constraint")
        compliance_safety = int(_clamp(compliance_safety, 0, 100))

        weighted = (
            kb_grounding * _SCORE_WEIGHTS["kbGrounding"]
            + term_alignment * _SCORE_WEIGHTS["terminologyAlignment"]
            + sales_progression * _SCORE_WEIGHTS["salesProgression"]
            + compliance_safety * _SCORE_WEIGHTS["complianceSafety"]
            + human_likeness * _SCORE_WEIGHTS["humanLikeness"]
        )
        overall_score = int(round(weighted))
        if compliance_safety < 65:
            overall_score = min(overall_score, 62)
        overall_score = int(_clamp(overall_score, 0, 100))

        if overall_score >= 90:
            stars = 5
        elif overall_score >= 78:
            stars = 4
        elif overall_score >= 65:
            stars = 3
        elif overall_score >= 50:
            stars = 2
        else:
            stars = 1

        dimensions = {
            "kbGrounding": int(kb_grounding),
            "terminologyAlignment": int(term_alignment),
            "salesProgression": int(sales_progression),
            "complianceSafety": int(compliance_safety),
            "humanLikeness": int(human_likeness),
        }
        return {
            **dimensions,
            "dimensions": dimensions,
            "overallScore": overall_score,
            "stars": stars,
            "needsReview": overall_score < 70,
            "issues": issues,
            "violatedConstraints": violated_constraints,
        }

    def record_turn(
        self,
        contact_name: str,
        incoming_text: str,
        ai_reply: str,
        *,
        channel: str = "wechat",
        matched_entry_ids: Iterable[str] = (),
        auto_score: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record a customer/sparring turn and return turn_id plus stored turn dict."""
        norm_contact = _norm_contact(contact_name) or "unknown"
        entry_ids = [str(eid).strip() for eid in (matched_entry_ids or ()) if str(eid).strip()]
        computed_score = (
            dict(auto_score)
            if isinstance(auto_score, dict)
            else self.auto_score_reply(incoming_text, ai_reply)
        )
        now = _utc_iso_now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO sparring_turns(
                    contact_name, channel, incoming_text, ai_reply,
                    matched_entry_ids_json, auto_score_json,
                    supervisor_rating, supervisor_tags_json, supervisor_comment,
                    hashtag_directive, revised_reply, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, NULL, '[]', '', '', '', ?, ?)
                """,
                (
                    norm_contact,
                    str(channel or "wechat").strip() or "wechat",
                    str(incoming_text or ""),
                    str(ai_reply or ""),
                    json.dumps(entry_ids, ensure_ascii=False),
                    json.dumps(computed_score, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            turn_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM sparring_turns WHERE id = ?",
                (turn_id,),
            ).fetchone()
        turn = self._turn_view(row)
        return {
            "ok": True,
            "turnId": turn_id,
            "turn": turn,
            **turn,
        }

    def _get_latest_turn_for_contact(self, conn: sqlite3.Connection, contact_name: str) -> Optional[sqlite3.Row]:
        norm = _norm_contact(contact_name)
        if not norm:
            return None
        row = conn.execute(
            "SELECT * FROM sparring_turns WHERE contact_name = ? ORDER BY id DESC LIMIT 1",
            (norm,),
        ).fetchone()
        if row is not None:
            return row
        rows = conn.execute(
            "SELECT * FROM sparring_turns ORDER BY id DESC LIMIT 100"
        ).fetchall()
        norm_cf = norm.casefold()
        for cand in rows:
            if _contact_key(str(cand["contact_name"])) == norm_cf:
                return cand
        return None

    def _adjust_entry_weights_unlocked(
        self,
        conn: sqlite3.Connection,
        entry_ids: Iterable[str],
        *,
        rating: int,
        now: str,
    ) -> Dict[str, float]:
        updated: Dict[str, float] = {}
        delta = 0.0
        low_inc = 0
        high_inc = 0
        if rating <= 1:
            delta = -0.18
            low_inc = 1
        elif rating == 2:
            delta = -0.12
            low_inc = 1
        elif rating == 4:
            delta = 0.08
            high_inc = 1
        elif rating >= 5:
            delta = 0.12
            high_inc = 1

        for raw_id in entry_ids:
            entry_id = str(raw_id or "").strip()
            if not entry_id:
                continue
            existing = conn.execute(
                "SELECT * FROM entry_quality_stats WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if existing:
                new_sum = int(existing["rating_sum"]) + int(rating)
                new_cnt = int(existing["rating_count"]) + 1
                new_low = int(existing["low_count"]) + low_inc
                new_high = int(existing["high_count"]) + high_inc
                new_weight = round(
                    _clamp(float(existing["weight"]) + delta, MIN_ENTRY_WEIGHT, MAX_ENTRY_WEIGHT),
                    4,
                )
                conn.execute(
                    """
                    UPDATE entry_quality_stats
                    SET rating_sum = ?, rating_count = ?, low_count = ?, high_count = ?,
                        weight = ?, updated_at = ?
                    WHERE entry_id = ?
                    """,
                    (new_sum, new_cnt, new_low, new_high, new_weight, now, entry_id),
                )
            else:
                new_weight = round(
                    _clamp(DEFAULT_ENTRY_WEIGHT + delta, MIN_ENTRY_WEIGHT, MAX_ENTRY_WEIGHT),
                    4,
                )
                conn.execute(
                    """
                    INSERT INTO entry_quality_stats(
                        entry_id, rating_sum, rating_count, low_count, high_count, weight, updated_at
                    ) VALUES(?, ?, 1, ?, ?, ?, ?)
                    """,
                    (entry_id, int(rating), low_inc, high_inc, new_weight, now),
                )
            updated[entry_id] = new_weight
        return updated

    def _insert_negative_constraint_unlocked(
        self,
        conn: sqlite3.Connection,
        *,
        trigger_text: str,
        bad_reply: str,
        rule_text: str,
        corrected_reply: str,
        source_contact: str,
        now: str,
    ) -> int:
        keywords = _extract_keywords(f"{trigger_text} {rule_text}")
        cur = conn.execute(
            """
            INSERT INTO negative_constraints(
                trigger_text, bad_reply, rule_text, corrected_reply,
                keywords_json, source_contact, active, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                str(trigger_text or ""),
                str(bad_reply or ""),
                str(rule_text or "").strip(),
                str(corrected_reply or "").strip(),
                json.dumps(keywords, ensure_ascii=False),
                _norm_contact(source_contact),
                now,
            ),
        )
        return int(cur.lastrowid)

    def _insert_golden_exemplar_unlocked(
        self,
        conn: sqlite3.Connection,
        *,
        trigger_text: str,
        reply_text: str,
        rating: int,
        source_contact: str,
        stage: str,
        now: str,
    ) -> int:
        clean_trigger = str(trigger_text or "").strip()
        clean_reply = str(reply_text or "").strip()
        existing = conn.execute(
            """
            SELECT id, rating FROM golden_exemplars
            WHERE trigger_text = ? AND reply_text = ?
            LIMIT 1
            """,
            (clean_trigger, clean_reply),
        ).fetchone()
        if existing:
            if int(rating) > int(existing["rating"]):
                conn.execute(
                    "UPDATE golden_exemplars SET rating = ? WHERE id = ?",
                    (int(rating), int(existing["id"])),
                )
            return int(existing["id"])
        keywords = _extract_keywords(f"{clean_trigger} {clean_reply}")
        cur = conn.execute(
            """
            INSERT INTO golden_exemplars(
                trigger_text, reply_text, stage, rating, keywords_json, source_contact, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_trigger,
                clean_reply,
                str(stage or "").strip(),
                int(rating),
                json.dumps(keywords, ensure_ascii=False),
                _norm_contact(source_contact),
                now,
            ),
        )
        return int(cur.lastrowid)

    def _save_sop_to_knowledge_store(
        self,
        knowledge_store: Any,
        *,
        title: str,
        body: str,
        kind: str = "script",
        source: str = "supervisor-hashtag",
        keywords: Sequence[str] = (),
    ) -> Optional[str]:
        if knowledge_store is None:
            return None
        clean_title = str(title or "").strip()[:64] or "主管纠偏话术"
        clean_body = str(body or "").strip()
        if not clean_body:
            return None
        res = knowledge_store.save_entry(
            title=clean_title,
            body=clean_body,
            kind=kind,
            keywords=list(keywords),
            source=source,
            external=True,
            status="published",
        )
        if isinstance(res, dict):
            entry = res.get("entry")
            if isinstance(entry, dict) and entry.get("id"):
                return str(entry["id"])
        return None

    # ------------------------------------------------------------------
    # Hashtag directive closed-loop handler
    # ------------------------------------------------------------------
    def handle_hashtag_directive(
        self,
        contact: str,
        raw_text: str,
        *,
        channel: str = "wechat",
        admin_contacts: Iterable[str] = (),
        knowledge_store: Optional[Any] = None,
        reply_generator: Optional[Callable[..., Any]] = None,
        takeover_cb: Optional[Callable[..., Any]] = None,
    ) -> Dict[str, Any]:
        """Authorize sender, execute `#` directive, update constraints/KB/weights, and return reply."""
        norm_contact = _norm_contact(contact)
        if not self.is_authorized_supervisor(
            contact,
            channel=channel,
            admin_contacts=admin_contacts,
        ):
            return {
                "ok": False,
                "handled": False,
                "reason": "unauthorized_sender",
                "contact": norm_contact,
            }

        parsed = parse_hashtag_directive(raw_text)
        if not parsed.get("isDirective"):
            return {
                "ok": False,
                "handled": False,
                "reason": "not_a_directive",
                "contact": norm_contact,
            }

        intent = parsed["intent"]
        now = _utc_iso_now()

        if intent == "takeover_control":
            cb_result = None
            if takeover_cb is not None:
                cb_result = _invoke_takeover_cb(takeover_cb, norm_contact, parsed["action"])
            action_label = "恢复 AI 托管" if not parsed["paused"] else "切换为人工接管/暂停自动回复"
            return {
                "ok": True,
                "handled": True,
                "intent": intent,
                "contact": norm_contact,
                "action": parsed["action"],
                "paused": bool(parsed["paused"]),
                "takeoverResult": cb_result,
                "ackMessage": f"已为「{norm_contact or '当前会话'}」{action_label}",
                "parsed": parsed,
            }

        if intent == "save_script":
            title = parsed["title"]
            body = parsed["body"]
            keywords = _extract_keywords(f"{parsed.get('trigger', '')} {body}")
            saved_id = self._save_sop_to_knowledge_store(
                knowledge_store,
                title=title,
                body=body,
                kind="script",
                source="supervisor-hashtag",
                keywords=keywords,
            )
            return {
                "ok": True,
                "handled": True,
                "intent": intent,
                "contact": norm_contact,
                "title": title,
                "body": body,
                "savedEntryId": saved_id,
                "ackMessage": f"已沉淀话术《{title}》到专属话术库",
                "parsed": parsed,
            }

        if intent == "save_term":
            term = parsed["term"]
            definition = parsed["definition"]
            keywords = _extract_keywords(definition, extra=[term])
            saved_id = self._save_sop_to_knowledge_store(
                knowledge_store,
                title=term,
                body=definition,
                kind="terminology",
                source="supervisor-hashtag",
                keywords=keywords,
            )
            return {
                "ok": True,
                "handled": True,
                "intent": intent,
                "contact": norm_contact,
                "term": term,
                "definition": definition,
                "savedEntryId": saved_id,
                "ackMessage": f"已保存专有词汇「{term}」到词汇表",
                "parsed": parsed,
            }

        with self._lock, self._connect() as conn:
            latest_row = self._get_latest_turn_for_contact(conn, norm_contact)

        if intent == "rate":
            stars = int(parsed["stars"])
            comment = str(parsed.get("comment") or "").strip()
            if latest_row is None:
                return {
                    "ok": True,
                    "handled": True,
                    "intent": intent,
                    "contact": norm_contact,
                    "turnId": None,
                    "stars": stars,
                    "comment": comment,
                    "ackMessage": f"已记录 {stars} 星反馈（当前会话暂无历史轮次）",
                    "parsed": parsed,
                }
            turn_id = int(latest_row["id"])
            rating_res = self.submit_rating(
                turn_id,
                stars=stars,
                comment=comment,
                knowledge_store=knowledge_store,
            )
            with self._lock, self._connect() as conn:
                conn.execute(
                    "UPDATE sparring_turns SET hashtag_directive = ?, updated_at = ? WHERE id = ?",
                    (str(raw_text), _utc_iso_now(), turn_id),
                )
            ack = f"已记录本轮评分 {stars} 星" + (f"（{comment}）" if comment else "")
            return {
                "ok": True,
                "handled": True,
                "intent": intent,
                "contact": norm_contact,
                "turnId": turn_id,
                "stars": stars,
                "comment": comment,
                "ratingResult": rating_res,
                "ackMessage": ack,
                "parsed": parsed,
            }

        # intent == "critique_rewrite"
        rule_text = parsed["ruleText"]
        turn_id = int(latest_row["id"]) if latest_row is not None else None
        trigger_text = str(latest_row["incoming_text"]) if latest_row is not None else ""
        bad_reply = str(latest_row["ai_reply"]) if latest_row is not None else ""
        matched_ids = (
            [str(x) for x in _json_loads_list(latest_row["matched_entry_ids_json"])]
            if latest_row is not None
            else []
        )

        # Gather existing + incoming negative constraint context for reply_generator
        preview_constraint = {
            "triggerText": trigger_text,
            "badReply": bad_reply,
            "ruleText": rule_text,
            "correctedReply": "",
            "keywords": _extract_keywords(f"{trigger_text} {rule_text}"),
        }
        prior_negatives = self.match_negative_constraints(trigger_text or rule_text, limit=4)
        negatives_for_gen = [preview_constraint] + prior_negatives

        revised_reply = ""
        if reply_generator is not None:
            revised_reply = _invoke_reply_generator(
                reply_generator,
                norm_contact,
                trigger_text,
                directive=rule_text,
                negative_constraints=negatives_for_gen,
            )

        with self._lock, self._connect() as conn:
            constraint_id = self._insert_negative_constraint_unlocked(
                conn,
                trigger_text=trigger_text,
                bad_reply=bad_reply,
                rule_text=rule_text,
                corrected_reply=revised_reply,
                source_contact=norm_contact,
                now=now,
            )
            decayed_weights = self._adjust_entry_weights_unlocked(
                conn,
                matched_ids,
                rating=1,
                now=now,
            )
            if turn_id is not None:
                conn.execute(
                    """
                    UPDATE sparring_turns
                    SET hashtag_directive = ?,
                        revised_reply = ?,
                        supervisor_comment = ?,
                        supervisor_rating = COALESCE(supervisor_rating, 2),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (str(raw_text), revised_reply, rule_text, now, turn_id),
                )

        sop_title = f"纠偏话术：{trigger_text[:20]}" if trigger_text else f"纠偏话术：{rule_text[:20]}"
        sop_body = rule_text if not revised_reply else f"要求：{rule_text}\n参考回复：{revised_reply}"
        saved_entry_id = self._save_sop_to_knowledge_store(
            knowledge_store,
            title=sop_title,
            body=sop_body,
            kind="script",
            source="supervisor-hashtag",
            keywords=_extract_keywords(f"{trigger_text} {rule_text} {revised_reply}"),
        )

        ack_message = f"已记住你的纠偏要求（{rule_text[:32]}），并同步更新约束与话术库。"
        if revised_reply:
            ack_message = f"{ack_message}\n按新口径重回：{revised_reply}"

        return {
            "ok": True,
            "handled": True,
            "intent": "critique_rewrite",
            "contact": norm_contact,
            "turnId": turn_id,
            "constraintId": constraint_id,
            "savedEntryId": saved_entry_id,
            "decayedWeights": decayed_weights,
            "revisedReply": revised_reply,
            "ackMessage": ack_message,
            "parsed": parsed,
        }

    # ------------------------------------------------------------------
    # Manual rating & optimization loop
    # ------------------------------------------------------------------
    def submit_rating(
        self,
        turn_id: int,
        *,
        stars: int,
        tags: Iterable[str] = (),
        comment: str = "",
        rewritten_reply: str = "",
        knowledge_store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if isinstance(stars, bool) or not isinstance(stars, int) or stars < 1 or stars > 5:
            raise ValueError(f"stars must be an integer between 1 and 5, got {stars!r}")

        clean_tags = [str(t).strip() for t in (tags or ()) if str(t).strip()]
        clean_comment = str(comment or "").strip()
        clean_rewrite = str(rewritten_reply or "").strip()
        now = _utc_iso_now()

        constraint_id: Optional[int] = None
        exemplar_id: Optional[int] = None
        saved_entry_id: Optional[str] = None

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sparring_turns WHERE id = ?",
                (int(turn_id),),
            ).fetchone()
            if row is None:
                raise KeyError(f"Sparring turn not found: {turn_id}")

            matched_ids = [str(x) for x in _json_loads_list(row["matched_entry_ids_json"])]
            final_rewrite = clean_rewrite or str(row["revised_reply"] or "")

            conn.execute(
                """
                UPDATE sparring_turns
                SET supervisor_rating = ?,
                    supervisor_tags_json = ?,
                    supervisor_comment = ?,
                    revised_reply = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    stars,
                    json.dumps(clean_tags, ensure_ascii=False),
                    clean_comment,
                    final_rewrite,
                    now,
                    int(turn_id),
                ),
            )

            updated_weights = self._adjust_entry_weights_unlocked(
                conn,
                matched_ids,
                rating=stars,
                now=now,
            )

            incoming_text = str(row["incoming_text"])
            ai_reply = str(row["ai_reply"])
            contact_name = str(row["contact_name"])

            if stars <= 2 and (clean_rewrite or clean_comment):
                rule_text = clean_comment or f"低分改进（{','.join(clean_tags) or '需优化'}）"
                constraint_id = self._insert_negative_constraint_unlocked(
                    conn,
                    trigger_text=incoming_text,
                    bad_reply=ai_reply,
                    rule_text=rule_text,
                    corrected_reply=clean_rewrite,
                    source_contact=contact_name,
                    now=now,
                )

            if stars >= 4:
                exemplar_id = self._insert_golden_exemplar_unlocked(
                    conn,
                    trigger_text=incoming_text,
                    reply_text=clean_rewrite or ai_reply,
                    rating=stars,
                    source_contact=contact_name,
                    stage="",
                    now=now,
                )

        if stars <= 2 and (clean_rewrite or clean_comment) and knowledge_store is not None:
            sop_title = f"低分纠偏：{incoming_text[:20]}" if incoming_text else "低分纠偏话术"
            parts = []
            if clean_comment:
                parts.append(f"纠偏要求：{clean_comment}")
            if clean_rewrite:
                parts.append(f"推荐回复：{clean_rewrite}")
            saved_entry_id = self._save_sop_to_knowledge_store(
                knowledge_store,
                title=sop_title,
                body="\n".join(parts),
                kind="script",
                source="supervisor-rating",
                keywords=_extract_keywords(f"{incoming_text} {clean_comment} {clean_rewrite}"),
            )

        return {
            "ok": True,
            "turnId": int(turn_id),
            "stars": stars,
            "tags": clean_tags,
            "updatedWeights": updated_weights,
            "constraintId": constraint_id,
            "exemplarId": exemplar_id,
            "savedEntryId": saved_entry_id,
        }

    def get_entry_weights(self) -> Dict[str, float]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT entry_id, weight FROM entry_quality_stats").fetchall()
        return {str(row["entry_id"]): float(row["weight"]) for row in rows}

    def match_negative_constraints(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        limit_n = max(1, int(limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM negative_constraints WHERE active = 1 ORDER BY id DESC LIMIT 300"
            ).fetchall()
        views = [self._constraint_view(r) for r in rows]
        norm_q = unicodedata.normalize("NFKC", str(query or "")).strip()
        if not norm_q:
            return views[:limit_n]

        q_cf = norm_q.casefold()
        q_terms = split_search_terms(norm_q, max_terms=12)
        scored: List[Tuple[float, int, Dict[str, Any]]] = []
        for item in views:
            hay_trigger = item["triggerText"].casefold()
            hay_rule = item["ruleText"].casefold()
            kw_list = [k.casefold() for k in item["keywords"]]
            score = 0.0
            for tok in q_terms:
                t_cf = tok.casefold()
                if any(t_cf in k or k in t_cf for k in kw_list):
                    score += 3.0
                if t_cf in hay_trigger:
                    score += 2.5
                if t_cf in hay_rule:
                    score += 1.5
            if item["triggerText"] and (
                item["triggerText"].casefold() in q_cf or q_cf in item["triggerText"].casefold()
            ):
                score += 5.0
            if score > 0:
                scored.append((score, item["id"], item))

        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [x[2] for x in scored[:limit_n]]

    def match_golden_exemplars(self, query: str, limit: int = 2) -> List[Dict[str, Any]]:
        limit_n = max(1, int(limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM golden_exemplars ORDER BY rating DESC, id DESC LIMIT 300"
            ).fetchall()
        views = [self._exemplar_view(r) for r in rows]
        norm_q = unicodedata.normalize("NFKC", str(query or "")).strip()
        if not norm_q:
            return views[:limit_n]

        q_cf = norm_q.casefold()
        q_terms = split_search_terms(norm_q, max_terms=12)
        scored: List[Tuple[float, int, int, Dict[str, Any]]] = []
        for item in views:
            hay_trigger = item["triggerText"].casefold()
            hay_reply = item["replyText"].casefold()
            kw_list = [k.casefold() for k in item["keywords"]]
            score = 0.0
            for tok in q_terms:
                t_cf = tok.casefold()
                if any(t_cf in k or k in t_cf for k in kw_list):
                    score += 3.0
                if t_cf in hay_trigger:
                    score += 2.5
                if t_cf in hay_reply:
                    score += 1.0
            if item["triggerText"] and (
                item["triggerText"].casefold() in q_cf or q_cf in item["triggerText"].casefold()
            ):
                score += 5.0
            if score > 0:
                scored.append((score, item["rating"], item["id"], item))

        scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
        return [x[3] for x in scored[:limit_n]]

    # ------------------------------------------------------------------
    # Quality dashboard & regression suite
    # ------------------------------------------------------------------
    def get_quality_dashboard(self, days: int = 7) -> Dict[str, Any]:
        cutoff = _utc_iso_days_ago(days) if days and int(days) > 0 else ""
        with self._lock, self._connect() as conn:
            if cutoff:
                turn_rows = conn.execute(
                    "SELECT * FROM sparring_turns WHERE created_at >= ? ORDER BY id DESC",
                    (cutoff,),
                ).fetchall()
            else:
                turn_rows = conn.execute(
                    "SELECT * FROM sparring_turns ORDER BY id DESC"
                ).fetchall()

            neg_count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM negative_constraints WHERE active = 1"
            ).fetchone()
            exemplar_rows = conn.execute(
                "SELECT * FROM golden_exemplars ORDER BY rating DESC, id DESC LIMIT 20"
            ).fetchall()
            stats_rows = conn.execute(
                "SELECT * FROM entry_quality_stats ORDER BY weight DESC, rating_count DESC"
            ).fetchall()
            test_contacts_cnt_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM test_contacts"
            ).fetchone()

        turns = [self._turn_view(r) for r in turn_rows]
        total_turns = len(turns)
        rated_turns = [t for t in turns if t["supervisorRating"] is not None]
        hashtag_turns = [t for t in turns if t["hashtagDirective"]]

        auto_scores = [
            float(t["autoScore"].get("overallScore"))
            for t in turns
            if isinstance(t.get("autoScore"), dict) and t["autoScore"].get("overallScore") is not None
        ]
        avg_auto = round(sum(auto_scores) / len(auto_scores), 1) if auto_scores else 0.0
        avg_stars = (
            round(sum(int(t["supervisorRating"]) for t in rated_turns) / len(rated_turns), 2)
            if rated_turns
            else 0.0
        )
        needs_review_turns = [
            t
            for t in turns
            if bool((t.get("autoScore") or {}).get("needsReview"))
            or (t["supervisorRating"] is not None and int(t["supervisorRating"]) <= 2)
            or bool(t["hashtagDirective"])
        ]
        pass_turns = sum(1 for s in auto_scores if s >= 70.0)
        pass_rate = round((pass_turns / len(auto_scores)) * 100.0, 1) if auto_scores else 0.0

        rating_dist: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        tag_counter: Counter[str] = Counter()
        for t in turns:
            if t["supervisorRating"] is not None:
                star_val = int(_clamp(int(t["supervisorRating"]), 1, 5))
                rating_dist[star_val] += 1
            for tag in t.get("supervisorTags") or []:
                tag_counter[tag] += 1
            for issue in (t.get("autoScore") or {}).get("issues") or []:
                tag_counter[str(issue)] += 1

        top_issue_tags = [
            {"tag": tag, "count": cnt}
            for tag, cnt in tag_counter.most_common(12)
        ]

        entry_ranking = []
        for r in stats_rows:
            cnt = int(r["rating_count"])
            r_sum = int(r["rating_sum"])
            entry_ranking.append({
                "entryId": str(r["entry_id"]),
                "weight": float(r["weight"]),
                "ratingCount": cnt,
                "avgRating": round(r_sum / cnt, 2) if cnt > 0 else 0.0,
                "lowCount": int(r["low_count"]),
                "highCount": int(r["high_count"]),
                "updatedAt": str(r["updated_at"]),
            })

        return {
            "ok": True,
            "days": int(days),
            "summary": {
                "totalTurns": total_turns,
                "ratedTurns": len(rated_turns),
                "hashtagTurns": len(hashtag_turns),
                "avgAutoScore": avg_auto,
                "avgSupervisorStars": avg_stars,
                "needsReviewCount": len(needs_review_turns),
                "passRate": pass_rate,
                "activeNegativeConstraints": int(neg_count_row["cnt"]) if neg_count_row else 0,
                "goldenExemplarsCount": len(exemplar_rows),
                "testContactsCount": int(test_contacts_cnt_row["cnt"]) if test_contacts_cnt_row else 0,
            },
            "ratingDistribution": rating_dist,
            "topIssueTags": top_issue_tags,
            "lowScoreTurns": needs_review_turns[:20],
            "goldenExemplars": [self._exemplar_view(r) for r in exemplar_rows],
            "entryQualityRanking": entry_ranking,
        }

    def run_regression_suite(
        self,
        reply_generator: Callable[..., Any],
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Re-run `#`-critiqued and `<=2`-star turns through reply_generator + auto_score_reply."""
        limit_n = max(1, int(limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sparring_turns
                WHERE hashtag_directive != ''
                   OR (supervisor_rating IS NOT NULL AND supervisor_rating <= 2)
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit_n,),
            ).fetchall()

        results: List[Dict[str, Any]] = []
        passed = 0
        for row in rows:
            turn = self._turn_view(row)
            negatives = self.match_negative_constraints(turn["incomingText"], limit=5)
            generated_reply = _invoke_reply_generator(
                reply_generator,
                turn["contactName"],
                turn["incomingText"],
                directive=turn["hashtagDirective"] or turn["supervisorComment"],
                negative_constraints=negatives,
            )
            score = self.auto_score_reply(
                turn["incomingText"],
                generated_reply,
                negative_constraints=negatives,
            )
            violated = bool(score.get("violatedConstraints"))
            case_passed = bool(generated_reply) and not violated and int(score["overallScore"]) >= 70
            if case_passed:
                passed += 1
            results.append({
                "turnId": turn["id"],
                "contactName": turn["contactName"],
                "incomingText": turn["incomingText"],
                "previousBadReply": turn["aiReply"],
                "generatedReply": generated_reply,
                "overallScore": score["overallScore"],
                "complianceSafety": score["complianceSafety"],
                "violatedConstraints": score["violatedConstraints"],
                "issues": score["issues"],
                "passed": case_passed,
            })

        total = len(results)
        return {
            "ok": True,
            "totalCases": total,
            "passedCases": passed,
            "failedCases": total - passed,
            "passRate": round((passed / total) * 100.0, 1) if total > 0 else 100.0,
            "results": results,
        }


__all__ = [
    "AUTHORIZED_NON_WECHAT_CHANNELS",
    "BUILTIN_ADMIN_CONTACTS",
    "DEFAULT_ENTRY_WEIGHT",
    "DEFAULT_SUPERVISOR_DB_PATH",
    "MAX_ENTRY_WEIGHT",
    "MIN_ENTRY_WEIGHT",
    "SUPERVISOR_EVAL_SCHEMA_VERSION",
    "SupervisorEvalEngine",
    "is_blocked_outbound_directive",
    "is_hashtag_directive",
    "parse_hashtag_directive",
]
