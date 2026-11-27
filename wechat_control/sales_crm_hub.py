"""Open-source Aurora-73/SalesCRM hub integrated cleanly into OpenBot WeChatBot.

Bridges upstream MIT-licensed ``Aurora-73/SalesCRM`` modules vendored under
``vendor/salescrm/`` ("代码负责数据，Agent 负责推理") with WeChatBot's real
contact bindings, chat histories, SoulMemoryProfiler, FTS5 knowledge base,
DSH/Bot Studio plugin bridge, and Beijing-time follow-up inbox.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from vendor.salescrm.engine.analyzers.events import detect_events, detect_milestones
from vendor.salescrm.engine.analyzers.metrics import (
    SIGNAL_LEVELS,
    SIGNAL_THRESHOLDS,
    classify_sales_interaction_pattern,
    compute_metrics_for_contact,
    compute_signal_level,
)
from vendor.salescrm.engine.analyzers.stage_recognizer import recognize_stage
from vendor.salescrm.engine.config import Config as SalesCRMConfig
from vendor.salescrm.engine.formulas import (
    formula_action,
    formula_ews,
    formula_ivi,
    formula_spe,
    sales_action,
    sales_bq,
    sales_bsp,
    sales_bws,
    sales_pv,
)
from vendor.salescrm.engine.identity.directory import IdentityAccount, IdentityPerson

from .live_inspector import _matches_target, normalize_chat_name


BEIJING_TZ = timezone(timedelta(hours=8))
OWNER_WXID = "owner_self"

STAGES: Tuple[str, ...] = (
    "新线索",
    "初步接触",
    "沟通中",
    "深入沟通",
    "已报价",
    "方案推进",
    "已成交",
    "暂缓",
    "退出/失败",
)

LEGACY_STAGE_MAP: Dict[str, str] = {
    "未识别": "新线索",
    "线索": "新线索",
    "已会面": "沟通中",
    "持续跟进": "深入沟通",
    "签约确认": "已成交",
}

PATTERN_LABELS: Dict[str, str] = {
    "buyer": "买方 (Buyer)",
    "evaluator": "评估者 (Evaluator)",
    "free_consulting": "白嫖咨询 (Free Consulting)",
    "silent": "沉默 (Silent)",
    "neutral": "常态互动 (Neutral)",
}

SIGNAL_FLAG_KEYWORDS = (
    "报价", "价格", "多少钱", "预算", "费用", "采购", "购买", "下单",
    "试用", "需求", "合同", "签约", "老板", "负责人", "审批", "部署",
)

METRIC_15D_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("fback", "回复字数比", "客户相对我方的表达投入度"),
    ("rlatency", "回复速度比", "双向消息响应速度平衡"),
    ("fback_quality", "回复质量深度", "正向互动与追问质量"),
    ("qscore_personal", "个性化提问频次", "围绕具体场景的深度提问"),
    ("escore", "正向情绪表达", "情绪词与正向反馈占比"),
    ("escore_volatility", "情绪波动度", "情绪起伏与张力变化"),
    ("recent", "距最后互动新鲜度", "近期活跃衰减得分"),
    ("active_days", "30 天活跃天数", "窗口期有效互动天数"),
    ("msg_count", "有效消息总量", "累计沉淀消息密度"),
    ("moments", "朋友圈互动", "好友与我在朋友圈的点赞、评论往来（读取朋友圈后才有数据）"),
    ("trend", "周综合变化趋势", "相对前周期的分数变化"),
    ("msg_volume_trend", "消息量变化趋势", "近期对话量环比变化"),
    ("latency_trend", "响应速度趋势", "近期回复响应提速变化"),
    ("neediness_penalty", "防过度追问惩罚", "我方消息占比过高时的降权系数"),
    ("signal_flags_score", "购买/询价信号分", "报价/预算/决策人/试用关键信号"),
)


class SalesCRMValidationError(ValueError):
    """Raised when CRM stage, note, follow-up timestamp, or target is invalid."""


def _utc_iso(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc)
    return dt.isoformat(timespec="seconds")


def _stable_person_id(name: str) -> str:
    norm = normalize_chat_name(name).casefold()
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]
    return f"person_{digest}"


def _stable_wxid(name: str) -> str:
    norm = normalize_chat_name(name).casefold()
    digest = hashlib.sha1(f"wxid:{norm}".encode("utf-8")).hexdigest()[:12]
    return f"wxid_{digest}"


def parse_follow_up_beijing(value: Optional[str]) -> Tuple[Optional[int], str]:
    """Validate Beijing time ``YYYY-MM-DDTHH:MM`` (or space separator) and convert to UTC epoch."""
    if value is None:
        return None, ""
    if not isinstance(value, str):
        raise SalesCRMValidationError("跟进时间必须为字符串格式 YYYY-MM-DDTHH:MM。")
    cleaned = value.strip()
    if not cleaned:
        return None, ""
    if " " in cleaned and "T" not in cleaned and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", cleaned):
        cleaned = cleaned.replace(" ", "T", 1)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", cleaned):
        raise SalesCRMValidationError("请输入有效的北京时间 (YYYY-MM-DDTHH:MM)，精确到分钟。")
    try:
        dt = datetime.strptime(cleaned, "%Y-%m-%dT%H:%M")
    except ValueError as exc:
        raise SalesCRMValidationError("请输入有效的北京时间日期与时间。") from exc
    if dt.year < 2000:
        raise SalesCRMValidationError("跟进时间年份须在 2000 年或之后。")
    utc_ts = int(dt.replace(tzinfo=BEIJING_TZ).timestamp())
    return utc_ts, cleaned


def format_utc_as_beijing(utc_ts: Optional[int]) -> str:
    """Render UTC epoch seconds in Asia/Shanghai (UTC+8) minute precision."""
    if utc_ts is None:
        return ""
    return datetime.fromtimestamp(int(utc_ts), tz=BEIJING_TZ).strftime("%Y-%m-%dT%H:%M")


def _parse_wechat_marker_to_epoch(marker: str, *, base_ts: int, offset_idx: int) -> int:
    """Convert WeChat time markers (e.g. '昨天 19:09', '星期二 08:42', ISO date) into monotonic timestamps."""
    base_dt = datetime.fromtimestamp(base_ts, tz=BEIJING_TZ)
    raw = (marker or "").strip()
    if not raw:
        return base_ts - max(60, offset_idx * 180)

    iso_m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", raw)
    if iso_m:
        y, mo, d = int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3))
        hh = int(iso_m.group(4) or 12)
        mm = int(iso_m.group(5) or 0)
        try:
            return int(datetime(y, mo, d, hh, mm, tzinfo=BEIJING_TZ).timestamp())
        except ValueError:
            pass

    hm_m = re.search(r"(\d{1,2}):(\d{2})", raw)
    hh = int(hm_m.group(1)) if hm_m else 12
    mm = int(hm_m.group(2)) if hm_m else 0
    hh = min(23, max(0, hh))
    mm = min(59, max(0, mm))

    day_shift = 0
    if "昨天" in raw:
        day_shift = 1
    elif "前天" in raw:
        day_shift = 2
    else:
        weekdays = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        wk_m = re.search(r"(?:星期|周)([一二三四五六日天])", raw)
        if wk_m:
            target_wd = weekdays[wk_m.group(1)]
            diff = (base_dt.weekday() - target_wd) % 7
            day_shift = diff if diff > 0 else 7

    candidate = (base_dt - timedelta(days=day_shift)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate > base_dt:
        candidate -= timedelta(days=1)
    return int(candidate.timestamp())


def _build_sales_config() -> SalesCRMConfig:
    return SalesCRMConfig({
        "my_name": "号主本人",
        "my_wxid": OWNER_WXID,
        "metrics": {
            "msg_count_cap": 100,
            "active_days_window": 30,
            "recency_decay": 90,
            "session_gap_hours": 4,
            "min_messages": 1,
        },
        "ranking": {"exclude": {"name_keywords": []}},
    })


class WeChatSalesCRMHub:
    """Aurora-73/SalesCRM powered marketing CRM & follow-up workbench hub."""

    UPSTREAM_INFO = {
        "name": "Aurora-73/SalesCRM",
        "repoUrl": "https://github.com/Aurora-73/SalesCRM",
        "commit": "6bdf30046acaa21d7ba1af04a06c10e99e32f197",
        "license": "MIT",
        "philosophy": "代码负责数据，Agent 负责推理",
        "vendorDir": "vendor/salescrm",
    }

    def __init__(
        self,
        engine: Any,
        *,
        db_path: Optional[Path] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.engine = engine
        default_dir = Path(getattr(engine.knowledge, "db_path", Path(engine.plugin_root) / "config" / "wechat_knowledge.sqlite")).parent
        self.db_path = Path(db_path) if db_path else (default_dir / "sales_crm.sqlite")
        self.clock = clock
        self._sales_cfg = _build_sales_config()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        new_file = not self.db_path.exists()
        conn = sqlite3.connect(self.db_path, timeout=8.0)
        conn.row_factory = sqlite3.Row
        if new_file:
            try:
                self.db_path.chmod(0o600)
            except OSError:
                pass
        return conn

    def _is_test_contact(self, name: str) -> bool:
        se = getattr(self.engine, "supervisor_eval", None)
        if se is None or not hasattr(se, "is_test_contact"):
            return False
        try:
            return bool(se.is_test_contact(str(name or "")))
        except Exception:
            return False

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS crm_people (
                    person_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    real_name TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT '新线索',
                    manual_stage_override INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    follow_up_utc INTEGER,
                    follow_up_beijing TEXT NOT NULL DEFAULT '',
                    deal_value REAL NOT NULL DEFAULT 0.0,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crm_accounts (
                    account_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    wxid TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    remark TEXT NOT NULL DEFAULT '',
                    nickname TEXT NOT NULL DEFAULT '',
                    channel_type TEXT NOT NULL DEFAULT 'wechat'
                );
                CREATE TABLE IF NOT EXISTS crm_aliases (
                    alias TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual'
                );
                CREATE TABLE IF NOT EXISTS crm_timeline_events (
                    event_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    event_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS crm_followup_drafts (
                    draft_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    rank_index INTEGER NOT NULL,
                    style_tag TEXT NOT NULL,
                    content TEXT NOT NULL,
                    basis_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                -- Upstream Aurora-73/SalesCRM mirror schema for direct analyzer execution
                CREATE TABLE IF NOT EXISTS people (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    real_name TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    created_at INTEGER DEFAULT 0,
                    updated_at INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS contact_accounts (
                    id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    wxid TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    display_name TEXT DEFAULT '',
                    remark TEXT DEFAULT '',
                    nickname TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    updated_at INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS contact_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id TEXT NOT NULL,
                    alias_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    value_norm TEXT NOT NULL,
                    source TEXT DEFAULT 'manual',
                    confidence REAL DEFAULT 1.0,
                    created_at INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS contacts (
                    id TEXT PRIMARY KEY,
                    display_name TEXT DEFAULT '',
                    remark TEXT DEFAULT '',
                    nickname TEXT DEFAULT '',
                    alias TEXT DEFAULT '',
                    type TEXT DEFAULT 'friend',
                    labels TEXT DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    type TEXT DEFAULT 'private',
                    display_name TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    type INTEGER NOT NULL DEFAULT 1,
                    content TEXT,
                    raw_content TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS moment_interactions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    kind TEXT DEFAULT 'media_analysis'
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_wxid TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    notes TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS failure_archives (
                    contact_wxid TEXT PRIMARY KEY,
                    reason TEXT DEFAULT ''
                );
                """
            )

    def _add_alias_conn(self, conn: sqlite3.Connection, person_id: str, alias: str, *, source: str = "sync") -> None:
        clean = (alias or "").strip()
        if not clean:
            return
        conn.execute(
            "INSERT OR IGNORE INTO crm_aliases (alias, person_id, source) VALUES (?, ?, ?)",
            (clean, person_id, source),
        )
        norm = normalize_chat_name(clean).casefold()
        existing = conn.execute(
            "SELECT 1 FROM contact_aliases WHERE person_id = ? AND value_norm = ?",
            (person_id, norm),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO contact_aliases (person_id, alias_type, value, value_norm, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (person_id, source, clean, norm, source, int(self.clock())),
            )

    def _ensure_person_conn(
        self,
        conn: sqlite3.Connection,
        target: str,
        *,
        alias: str = "",
        remark: str = "",
        stage: str = "新线索",
        manual_override: bool = False,
        note: str = "",
        deal_value: float = 0.0,
        tags: Optional[List[str]] = None,
        channel_type: str = "wechat",
        wxid_override: Optional[str] = None,
    ) -> str:
        resolved = self._resolve_person_id_conn(conn, target)
        now_iso = _utc_iso(self.clock())
        now_epoch = int(self.clock())
        clean_name = target.strip()
        if resolved:
            person_id = resolved
        else:
            person_id = _stable_person_id(clean_name)
            wxid = (wxid_override or _stable_wxid(clean_name)).strip()
            tags_str = json.dumps(list(tags or []), ensure_ascii=False)
            conn.execute(
                "INSERT INTO crm_people "
                "(person_id, display_name, real_name, stage, manual_stage_override, note, follow_up_utc, "
                "follow_up_beijing, deal_value, tags_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, '', ?, ?, ?, ?)",
                (
                    person_id,
                    clean_name,
                    clean_name,
                    stage if stage in STAGES else "新线索",
                    1 if manual_override else 0,
                    note,
                    float(deal_value or 0.0),
                    tags_str,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO people (id, display_name, real_name, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (person_id, clean_name, clean_name, note, now_epoch, now_epoch),
            )
            acc_id = f"acc_{hashlib.sha1(f'{person_id}:{wxid}'.encode('utf-8')).hexdigest()[:10]}"
            conn.execute(
                "INSERT OR IGNORE INTO crm_accounts "
                "(account_id, person_id, wxid, conversation_id, display_name, remark, nickname, channel_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (acc_id, person_id, wxid, wxid, clean_name, remark, clean_name, channel_type),
            )
            conn.execute(
                "INSERT OR IGNORE INTO contact_accounts "
                "(id, person_id, wxid, conversation_id, display_name, remark, nickname, active, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (acc_id, person_id, wxid, wxid, clean_name, remark, clean_name, now_epoch),
            )
            conn.execute(
                "INSERT OR IGNORE INTO conversations (id, type, display_name) VALUES (?, 'private', ?)",
                (wxid, clean_name),
            )
            conn.execute(
                "INSERT OR IGNORE INTO contacts (id, display_name, remark, nickname, alias, type, labels) "
                "VALUES (?, ?, ?, ?, ?, 'friend', ?)",
                (wxid, clean_name, remark, clean_name, alias or "", json.dumps(list(tags or []), ensure_ascii=False)),
            )

        self._add_alias_conn(conn, person_id, clean_name, source="display_name")
        if alias:
            self._add_alias_conn(conn, person_id, alias, source="manual_alias")
        if remark:
            self._add_alias_conn(conn, person_id, remark, source="remark")
        return person_id

    def _resolve_person_id_conn(self, conn: sqlite3.Connection, query: str) -> Optional[str]:
        q = (query or "").strip()
        if not q:
            return None
        row = conn.execute("SELECT person_id FROM crm_people WHERE person_id = ?", (q,)).fetchone()
        if row:
            return str(row["person_id"])

        row = conn.execute(
            "SELECT person_id FROM crm_accounts WHERE wxid = ? OR conversation_id = ?",
            (q, q),
        ).fetchone()
        if row:
            return str(row["person_id"])

        row = conn.execute("SELECT person_id FROM crm_aliases WHERE alias = ?", (q,)).fetchone()
        if row:
            return str(row["person_id"])

        people_rows = conn.execute("SELECT person_id, display_name, real_name FROM crm_people").fetchall()
        for pr in people_rows:
            if _matches_target(q, str(pr["display_name"] or "")) or (
                pr["real_name"] and _matches_target(q, str(pr["real_name"]))
            ):
                return str(pr["person_id"])

        alias_rows = conn.execute("SELECT person_id, alias FROM crm_aliases").fetchall()
        q_norm = normalize_chat_name(q).casefold()
        for ar in alias_rows:
            a_val = str(ar["alias"] or "")
            if normalize_chat_name(a_val).casefold() == q_norm or _matches_target(q, a_val):
                return str(ar["person_id"])
        for ar in alias_rows:
            if q_norm and q_norm in normalize_chat_name(str(ar["alias"] or "")).casefold():
                return str(ar["person_id"])
        return None

    def _get_identity_person_conn(self, conn: sqlite3.Connection, person_id: str) -> Optional[IdentityPerson]:
        pr = conn.execute(
            "SELECT person_id, display_name, real_name, note FROM crm_people WHERE person_id = ?",
            (person_id,),
        ).fetchone()
        if not pr:
            return None
        acc_rows = conn.execute(
            "SELECT account_id, person_id, wxid, conversation_id, display_name, remark, nickname "
            "FROM crm_accounts WHERE person_id = ?",
            (person_id,),
        ).fetchall()
        accounts = [
            IdentityAccount(
                id=str(r["account_id"]),
                person_id=str(r["person_id"]),
                wxid=str(r["wxid"]),
                conversation_id=str(r["conversation_id"]),
                display_name=str(r["display_name"]),
                remark=str(r["remark"]),
                nickname=str(r["nickname"]),
                active=True,
            )
            for r in acc_rows
        ]
        alias_rows = conn.execute(
            "SELECT alias, source FROM crm_aliases WHERE person_id = ?",
            (person_id,),
        ).fetchall()
        aliases = [{"alias": str(r["alias"]), "source": str(r["source"])} for r in alias_rows]
        return IdentityPerson(
            id=str(pr["person_id"]),
            display_name=str(pr["display_name"]),
            real_name=str(pr["real_name"] or ""),
            note=str(pr["note"] or ""),
            accounts=accounts,
            aliases=aliases,
        )

    def resolve_person(self, query: str) -> Dict[str, Any]:
        """Resolve a contact query via Person -> Account -> Alias identity directory."""
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "查询词不能为空。", "candidates": []}
        with closing(self._connect()) as conn:
            pid = self._resolve_person_id_conn(conn, q)
            if pid:
                ident = self._get_identity_person_conn(conn, pid)
                return {
                    "ok": True,
                    "personId": pid,
                    "displayName": ident.display_name if ident else "",
                    "accounts": [
                        {
                            "wxid": a.wxid,
                            "conversationId": a.conversation_id,
                            "displayName": a.display_name,
                            "remark": a.remark,
                        }
                        for a in (ident.accounts if ident else [])
                    ],
                    "aliases": ident.aliases if ident else [],
                }
        return {"ok": False, "query": q, "error": f"未匹配到客户档案: {q}", "candidates": []}

    def merge_accounts(
        self,
        primary_target: str,
        secondary_target: str,
        *,
        alias: str = "",
    ) -> Dict[str, Any]:
        """Merge a secondary contact account into a primary Person identity."""
        with closing(self._connect()) as conn, conn:
            p_id = self._ensure_person_conn(conn, primary_target)
            s_id = self._resolve_person_id_conn(conn, secondary_target)
            if not s_id:
                s_id = self._ensure_person_conn(conn, secondary_target)
            if p_id == s_id:
                if alias:
                    self._add_alias_conn(conn, p_id, alias, source="merged_alias")
                return {"ok": True, "personId": p_id, "merged": False, "reason": "same_person"}

            sec_row = conn.execute("SELECT display_name FROM crm_people WHERE person_id = ?", (s_id,)).fetchone()
            sec_name = str(sec_row["display_name"]) if sec_row else secondary_target

            conn.execute("UPDATE crm_accounts SET person_id = ? WHERE person_id = ?", (p_id, s_id))
            conn.execute("UPDATE contact_accounts SET person_id = ? WHERE person_id = ?", (p_id, s_id))
            sec_aliases = conn.execute("SELECT alias, source FROM crm_aliases WHERE person_id = ?", (s_id,)).fetchall()
            for ar in sec_aliases:
                conn.execute(
                    "INSERT OR REPLACE INTO crm_aliases (alias, person_id, source) VALUES (?, ?, ?)",
                    (str(ar["alias"]), p_id, str(ar["source"])),
                )
            conn.execute("UPDATE contact_aliases SET person_id = ? WHERE person_id = ?", (p_id, s_id))
            conn.execute("UPDATE crm_timeline_events SET person_id = ? WHERE person_id = ?", (p_id, s_id))
            conn.execute("DELETE FROM crm_people WHERE person_id = ?", (s_id,))
            conn.execute("DELETE FROM people WHERE id = ?", (s_id,))
            self._add_alias_conn(conn, p_id, sec_name, source="merged_account")
            if alias:
                self._add_alias_conn(conn, p_id, alias, source="merged_alias")
            self._record_timeline_event_conn(
                conn,
                p_id,
                event_type="INFO_UPDATE",
                category="信息更新",
                title="多账号身份合并",
                detail=f"已将账号/别名「{sec_name}」并入统一 Person 档案",
            )
            return {"ok": True, "personId": p_id, "merged": True, "mergedName": sec_name}

    def _record_timeline_event_conn(
        self,
        conn: sqlite3.Connection,
        person_id: str,
        *,
        event_type: str,
        category: str,
        title: str,
        detail: str,
        event_at: Optional[str] = None,
    ) -> str:
        at = event_at or _utc_iso(self.clock())
        raw_key = f"{person_id}:{event_type}:{title}:{detail}:{at}"
        event_id = f"ev_{hashlib.sha1(raw_key.encode('utf-8')).hexdigest()[:14]}"
        conn.execute(
            "INSERT OR IGNORE INTO crm_timeline_events "
            "(event_id, person_id, event_type, category, title, detail, event_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, person_id, event_type, category, title, detail, at),
        )
        return event_id

    def _ingest_messages_for_person(
        self,
        conn: sqlite3.Connection,
        wxid: str,
        records: List[Dict[str, Any]],
        *,
        source_tag: str,
    ) -> int:
        inserted = 0
        base_ts = int(self.clock())
        prev_ts = 0
        total = len(records)
        for idx, rec in enumerate(records):
            text = str(rec.get("text") or rec.get("content") or "").strip()
            if not text:
                continue
            kind = str(rec.get("kind") or "message")
            direction = str(rec.get("direction") or "").lower()
            if kind == "timestamp" or direction == "system":
                continue
            sender = OWNER_WXID if direction in ("self", "owner", "me") else wxid
            raw_ts = rec.get("timestamp")
            if isinstance(raw_ts, (int, float)) and raw_ts > 0:
                msg_ts = int(raw_ts)
            else:
                msg_ts = _parse_wechat_marker_to_epoch(
                    str(rec.get("timeMarker") or ""),
                    base_ts=base_ts,
                    offset_idx=max(1, total - idx),
                )
            if msg_ts <= prev_ts:
                msg_ts = prev_ts + 45
            prev_ts = msg_ts
            msg_digest = hashlib.sha1(f"{wxid}:{source_tag}:{idx}:{sender}:{text}".encode("utf-8")).hexdigest()[:16]
            msg_id = f"msg_{msg_digest}"
            cur = conn.execute(
                "INSERT OR IGNORE INTO messages (id, conversation_id, sender_id, timestamp, type, content, raw_content) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (msg_id, wxid, sender, msg_ts, text, ""),
            )
            inserted += int(cur.rowcount or 0)
        return inserted

    def sync_from_wechat(self) -> Dict[str, Any]:
        """Incrementally sync contacts, bindings, histories, Moments interactions, and Soul memories."""
        synced_people = 0
        ingested_messages = 0
        moments_events = 0
        excluded_test_contacts: List[str] = []
        excluded_test_seen: set[str] = set()

        def _skip_if_test(name: str) -> bool:
            clean = str(name or "").strip()
            if not clean:
                return False
            if self._is_test_contact(clean):
                key = clean.casefold()
                if key not in excluded_test_seen:
                    excluded_test_seen.add(key)
                    excluded_test_contacts.append(clean)
                return True
            return False

        reports_dir = Path(self.engine.inspector.reports_dir)
        contacts_dir = reports_dir / "contacts"
        mgmt_path = reports_dir / "wechat_management_report.json"

        with closing(self._connect()) as conn, conn:
            # 1. Sync bound contacts
            for b in self.engine.bindings.list_bindings():
                target = str(b.get("target") or "").strip()
                if not target or _skip_if_test(target):
                    continue
                tags = list(b.get("careTags") or [])
                if b.get("specialCare") and "特别关心" not in tags:
                    tags.append("特别关心")
                pid = self._ensure_person_conn(
                    conn,
                    target,
                    alias=str(b.get("alias") or ""),
                    note=str(b.get("notes") or ""),
                    tags=tags,
                )
                if b.get("notes"):
                    conn.execute(
                        "UPDATE crm_people SET note = CASE WHEN note = '' THEN ? ELSE note END, "
                        "tags_json = ? WHERE person_id = ?",
                        (str(b.get("notes")), json.dumps(tags, ensure_ascii=False), pid),
                    )
                synced_people += 1

            # 2. Sync SoulMemoryProfiler friend profiles (get_profiles returns list of contact dicts)
            soul = self.engine.soul_profiler.get_profiles()
            raw_cp = soul.get("contactProfiles") or []
            cp_list = list(raw_cp.values()) if isinstance(raw_cp, dict) else list(raw_cp)
            for idx_cp, prof in enumerate(cp_list):
                if not isinstance(prof, dict):
                    continue
                cname = str(prof.get("matchedTitle") or prof.get("target") or prof.get("displayName") or "").strip()
                if not cname and isinstance(raw_cp, dict):
                    cname = str(list(raw_cp.keys())[idx_cp]).strip()
                if not cname or _skip_if_test(cname):
                    continue
                pid = self._ensure_person_conn(conn, cname)
                ident = self._get_identity_person_conn(conn, pid)
                wxid = ident.accounts[0].wxid if ident and ident.accounts else _stable_wxid(cname)
                synth_records: List[Dict[str, Any]] = []
                raw_mems = prof.get("memories") or {}
                mem_items: List[Any] = []
                if isinstance(raw_mems, dict):
                    for bucket in ("facts", "episodicEvents", "sharedContext"):
                        bucket_val = raw_mems.get(bucket)
                        if isinstance(bucket_val, list):
                            mem_items.extend(bucket_val)
                elif isinstance(raw_mems, list):
                    mem_items.extend(raw_mems)
                for mem in mem_items:
                    if isinstance(mem, str):
                        content, marker = mem.strip(), ""
                    elif isinstance(mem, dict):
                        content = str(mem.get("content") or "").strip()
                        marker = str(mem.get("timeMarker") or "")
                    else:
                        continue
                    if content:
                        synth_records.append({
                            "text": content,
                            "kind": "message",
                            "direction": "peer",
                            "timeMarker": marker,
                        })
                if synth_records:
                    ingested_messages += self._ingest_messages_for_person(
                        conn, wxid, synth_records, source_tag="soul_mem"
                    )
                synced_people += 1

            # 3. Sync observed contact chat histories
            if contacts_dir.is_dir():
                for hp in sorted(contacts_dir.glob("*_history.json")):
                    try:
                        doc = json.loads(hp.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    target = str(doc.get("matchedTitle") or doc.get("target") or doc.get("contact") or "").strip()
                    if not target or _skip_if_test(target):
                        continue
                    pid = self._ensure_person_conn(conn, target)
                    ident = self._get_identity_person_conn(conn, pid)
                    wxid = ident.accounts[0].wxid if ident and ident.accounts else _stable_wxid(target)
                    records = list(doc.get("records") or doc.get("messages") or [])
                    ingested_messages += self._ingest_messages_for_person(
                        conn, wxid, records, source_tag=hp.stem
                    )
                    synced_people += 1

            # 4. Sync sessions visible in live management report
            if mgmt_path.is_file():
                try:
                    rep = json.loads(mgmt_path.read_text(encoding="utf-8"))
                except Exception:
                    rep = {}
                for sess in rep.get("sessions") or []:
                    if not isinstance(sess, dict):
                        continue
                    title = str(sess.get("fullTitle") or sess.get("listTitleSnippet") or "").strip()
                    if not title or sess.get("isFoldedFolder") or _skip_if_test(title):
                        continue
                    pid = self._ensure_person_conn(conn, title)
                    ident = self._get_identity_person_conn(conn, pid)
                    wxid = ident.accounts[0].wxid if ident and ident.accounts else _stable_wxid(title)
                    vis = [
                        {"text": str(m), "kind": "message", "direction": "peer", "timeMarker": str(sess.get("lastTimeHint") or "")}
                        for m in (sess.get("visibleMessages") or [])
                        if str(m).strip()
                    ]
                    if vis:
                        ingested_messages += self._ingest_messages_for_person(
                            conn, wxid, vis, source_tag="live_report"
                        )
                    synced_people += 1
                for c_item in rep.get("contacts") or []:
                    if isinstance(c_item, str):
                        cname, snippet = c_item.strip(), ""
                    elif isinstance(c_item, dict):
                        cname = str(c_item.get("name") or c_item.get("target") or "").strip()
                        snippet = str(c_item.get("latestSnippet") or "").strip()
                    else:
                        continue
                    if not cname or _skip_if_test(cname):
                        continue
                    pid = self._ensure_person_conn(conn, cname)
                    ident = self._get_identity_person_conn(conn, pid)
                    wxid = ident.accounts[0].wxid if ident and ident.accounts else _stable_wxid(cname)
                    if snippet:
                        ingested_messages += self._ingest_messages_for_person(
                            conn, wxid, [{"text": snippet, "kind": "message", "direction": "peer"}], source_tag="mgmt_contact"
                        )
                    synced_people += 1

            # 5. 真实的朋友圈互动 → 上游 moment_interactions 表：
            #    好友点赞/评论了我的帖子、我点赞/评论了好友的帖子，一条帖子 × 一个人记一行。
            #    旧版本把聊天里的链接/图片分析写进这张表冒充朋友圈互动；读到真实数据后把这些替身清掉。
            moments_rows: List[Dict[str, Any]] = []
            moments_hub = getattr(self.engine, "moments", None)
            if moments_hub is not None:
                try:
                    moments_rows = list(moments_hub.crm_interactions() or [])
                except Exception:
                    moments_rows = []
            for item in moments_rows:
                person = str(item.get("person") or "").strip()
                if not person or _skip_if_test(person):
                    continue
                pid = self._ensure_person_conn(conn, person)
                ident = self._get_identity_person_conn(conn, pid)
                wxid = ident.accounts[0].wxid if ident and ident.accounts else _stable_wxid(person)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO moment_interactions (id, user_id, timestamp, kind) VALUES (?, ?, ?, ?)",
                    (str(item["id"]), wxid, int(item["timestamp"]), str(item.get("kind") or "")),
                )
                moments_events += int(cur.rowcount or 0)
            legacy_removed = 0
            if moments_rows:
                legacy_removed = int(conn.execute(
                    "DELETE FROM moment_interactions WHERE id LIKE 'mi\\_%' ESCAPE '\\'"
                ).rowcount or 0)

        return {
            "ok": True,
            "syncedAt": _utc_iso(self.clock()),
            "syncedContacts": synced_people,
            "syncedSources": synced_people,
            "ingestedMessages": ingested_messages,
            "momentsInteractions": moments_events,
            "legacyMediaInteractionsRemoved": legacy_removed,
            "excludedTestContacts": excluded_test_contacts,
            "excludedTestContactsCount": len(excluded_test_contacts),
            "dbPath": str(self.db_path),
        }

    def enroll_contact(
        self,
        target: str,
        *,
        stage: str = "新线索",
        note: str = "",
        follow_up: Optional[str] = None,
        deal_value: float = 0.0,
        alias: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Manually enroll a WeChat contact or lead into SalesCRM."""
        clean_target = (target or "").strip()
        if not clean_target:
            raise SalesCRMValidationError("联系人名称不能为空。")
        clean_stage = LEGACY_STAGE_MAP.get(stage.strip(), stage.strip())
        if clean_stage not in STAGES:
            raise SalesCRMValidationError(f"无效阶段 '{stage}'，可选：{', '.join(STAGES)}")
        if not isinstance(note, str) or len(note) > 2000:
            raise SalesCRMValidationError("备注必须为不超过 2000 字的文本。")
        follow_utc, follow_bj = parse_follow_up_beijing(follow_up)

        with closing(self._connect()) as conn, conn:
            pid = self._ensure_person_conn(
                conn,
                clean_target,
                alias=alias,
                stage=clean_stage,
                manual_override=True,
                note=note,
                deal_value=float(deal_value or 0.0),
                tags=tags,
            )
            conn.execute(
                "UPDATE crm_people SET stage = ?, manual_stage_override = 1, note = ?, "
                "follow_up_utc = ?, follow_up_beijing = ?, deal_value = ?, updated_at = ? "
                "WHERE person_id = ?",
                (
                    clean_stage,
                    note,
                    follow_utc,
                    follow_bj,
                    float(deal_value or 0.0),
                    _utc_iso(self.clock()),
                    pid,
                ),
            )
            self._record_timeline_event_conn(
                conn,
                pid,
                event_type="INFO_UPDATE",
                category="信息更新",
                title=f"纳入 CRM 阶段：{clean_stage}",
                detail=note or f"已将「{clean_target}」纳入 SalesCRM 漏斗",
            )
        return self.analyze_contact(pid)

    def update_record(
        self,
        target: str,
        *,
        stage: str,
        note: str,
        follow_up: Optional[str] = None,
        deal_value: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Update stage, note, Beijing follow-up time, and deal value atomically."""
        clean_stage = LEGACY_STAGE_MAP.get(stage.strip(), stage.strip())
        if clean_stage not in STAGES:
            raise SalesCRMValidationError(f"无效阶段 '{stage}'，可选：{', '.join(STAGES)}")
        if not isinstance(note, str) or len(note) > 2000:
            raise SalesCRMValidationError("备注必须为不超过 2000 字的文本。")
        follow_utc, follow_bj = parse_follow_up_beijing(follow_up)

        with closing(self._connect()) as conn, conn:
            pid = self._resolve_person_id_conn(conn, target)
            if not pid:
                raise SalesCRMValidationError(f"未找到联系人档案：{target}")
            now_iso = _utc_iso(self.clock())
            if deal_value is not None:
                conn.execute(
                    "UPDATE crm_people SET stage = ?, manual_stage_override = 1, note = ?, "
                    "follow_up_utc = ?, follow_up_beijing = ?, deal_value = ?, updated_at = ? "
                    "WHERE person_id = ?",
                    (clean_stage, note, follow_utc, follow_bj, float(deal_value), now_iso, pid),
                )
            else:
                conn.execute(
                    "UPDATE crm_people SET stage = ?, manual_stage_override = 1, note = ?, "
                    "follow_up_utc = ?, follow_up_beijing = ?, updated_at = ? WHERE person_id = ?",
                    (clean_stage, note, follow_utc, follow_bj, now_iso, pid),
                )

            if clean_stage in ("已报价", "方案推进"):
                ev_type, cat = "PROPOSAL_SENT", "销售进展"
            elif clean_stage == "已成交":
                ev_type, cat = "DEAL_CLOSE", "里程碑"
            else:
                ev_type, cat = "INFO_UPDATE", "信息更新"
            self._record_timeline_event_conn(
                conn,
                pid,
                event_type=ev_type,
                category=cat,
                title=f"跟进更新 -> {clean_stage}",
                detail=f"{note[:120]} {'[排期 ' + follow_bj + ' CST]' if follow_bj else ''}".strip(),
            )
            if clean_stage == "退出/失败":
                ident = self._get_identity_person_conn(conn, pid)
                if ident and ident.accounts:
                    conn.execute(
                        "INSERT OR REPLACE INTO failure_archives (contact_wxid, reason) VALUES (?, ?)",
                        (ident.accounts[0].wxid, note or "手动标记退出/失败"),
                    )
        return self.analyze_contact(pid)

    def complete_reminder(self, target: str) -> Dict[str, Any]:
        """Complete a contact follow-up reminder by clearing its scheduled follow_up timestamp."""
        with closing(self._connect()) as conn, conn:
            pid = self._resolve_person_id_conn(conn, target)
            if not pid:
                raise SalesCRMValidationError(f"未找到联系人档案：{target}")
            conn.execute(
                "UPDATE crm_people SET follow_up_utc = NULL, follow_up_beijing = '', updated_at = ? "
                "WHERE person_id = ?",
                (_utc_iso(self.clock()), pid),
            )
            self._record_timeline_event_conn(
                conn,
                pid,
                event_type="MILESTONE",
                category="里程碑",
                title="跟进提醒已完成",
                detail="运营已在工作台完成本轮跟进并清空到期排期",
            )
        return {"ok": True, "personId": pid, "status": "completed", "reminders": self.list_reminders()}

    def reschedule_reminder(self, target: str, follow_up: str) -> Dict[str, Any]:
        """Reschedule a contact's follow-up reminder using Beijing time YYYY-MM-DDTHH:MM."""
        follow_utc, follow_bj = parse_follow_up_beijing(follow_up)
        if follow_utc is None:
            raise SalesCRMValidationError("改期必须提供有效的北京时间 YYYY-MM-DDTHH:MM。")
        with closing(self._connect()) as conn, conn:
            pid = self._resolve_person_id_conn(conn, target)
            if not pid:
                raise SalesCRMValidationError(f"未找到联系人档案：{target}")
            conn.execute(
                "UPDATE crm_people SET follow_up_utc = ?, follow_up_beijing = ?, updated_at = ? "
                "WHERE person_id = ?",
                (follow_utc, follow_bj, _utc_iso(self.clock()), pid),
            )
            self._record_timeline_event_conn(
                conn,
                pid,
                event_type="INFO_UPDATE",
                category="信息更新",
                title=f"跟进改期至 {follow_bj} (北京时间)",
                detail=f"UTC={follow_utc}",
            )
        return {
            "ok": True,
            "personId": pid,
            "followUpBeijing": follow_bj,
            "followUpUtc": follow_utc,
            "reminders": self.list_reminders(),
        }

    def list_reminders(self, *, now_ts: Optional[int] = None) -> Dict[str, Any]:
        """Return due (overdue/active) and upcoming Beijing-time follow-up reminders."""
        now_sec = int(now_ts if now_ts is not None else self.clock())
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT person_id, display_name, stage, note, follow_up_utc, follow_up_beijing, deal_value "
                "FROM crm_people WHERE follow_up_utc IS NOT NULL ORDER BY follow_up_utc ASC, display_name ASC"
            ).fetchall()

        due: List[Dict[str, Any]] = []
        upcoming: List[Dict[str, Any]] = []
        for r in rows:
            utc_ts = int(r["follow_up_utc"])
            is_due = utc_ts <= now_sec
            item = {
                "personId": str(r["person_id"]),
                "displayName": str(r["display_name"]),
                "stage": str(r["stage"]),
                "note": str(r["note"] or ""),
                "followUpUtc": utc_ts,
                "followUpBeijing": str(r["follow_up_beijing"] or format_utc_as_beijing(utc_ts)),
                "dealValue": float(r["deal_value"] or 0.0),
                "isDue": is_due,
                "overdueMinutes": max(0, (now_sec - utc_ts) // 60) if is_due else 0,
            }
            if is_due:
                due.append(item)
            else:
                upcoming.append(item)
        return {
            "ok": True,
            "checkedAtUtc": now_sec,
            "checkedAtBeijing": format_utc_as_beijing(now_sec),
            "dueCount": len(due),
            "upcomingCount": len(upcoming),
            "due": due,
            "upcoming": upcoming,
        }

    def _compute_metrics_conn(self, conn: sqlite3.Connection, person_id: str) -> Dict[str, Any]:
        ident = self._get_identity_person_conn(conn, person_id)
        if not ident:
            raise SalesCRMValidationError(f"未找到联系人档案：{person_id}")
        wxids = [a.wxid for a in ident.accounts] or [_stable_wxid(ident.display_name)]
        primary_wxid = wxids[0]
        binding = self.engine.bindings.get_binding(ident.display_name) or {}
        top_target = bool(binding.get("specialCare"))
        ref_dt = datetime.fromtimestamp(self.clock())

        metrics_obj = compute_metrics_for_contact(
            conn,
            self._sales_cfg,
            primary_wxid,
            contact_name=ident.display_name,
            top_target=top_target,
            ref_date=ref_dt,
            to_ts=int(self.clock()),
        )
        msg_rows = conn.execute(
            f"SELECT content, sender_id FROM messages WHERE conversation_id IN ({','.join('?' for _ in wxids)}) AND type = 1",
            tuple(wxids),
        ).fetchall()
        msg_texts = [str(r["content"] or "") for r in msg_rows]
        keyword_hits = sum(1 for txt in msg_texts if any(kw in txt for kw in SIGNAL_FLAG_KEYWORDS))
        signal_flag_norm = min(
            1.0,
            round(
                0.25 * float(metrics_obj.budget_known)
                + 0.25 * float(metrics_obj.decision_chain)
                + 0.25 * float(metrics_obj.urgency)
                + min(0.35, keyword_hits * 0.1),
                4,
            ),
        )
        pattern_code = classify_sales_interaction_pattern(metrics_obj)
        signal_level = compute_signal_level(metrics_obj.composite)

        dimensions: List[Dict[str, Any]] = []
        all_mv = metrics_obj.all_metrics()
        for key, label, desc in METRIC_15D_SPECS:
            if key == "neediness_penalty":
                val = round(float(metrics_obj.neediness_penalty), 4)
                dimensions.append({
                    "key": key,
                    "label": label,
                    "description": desc,
                    "raw": val,
                    "normalized": val,
                    "confidence": 0.8 if len(msg_rows) >= 4 else (0.4 if msg_rows else 0.1),
                    "sampleSize": len(msg_rows),
                })
            elif key == "signal_flags_score":
                dimensions.append({
                    "key": key,
                    "label": label,
                    "description": desc,
                    "raw": keyword_hits,
                    "normalized": signal_flag_norm,
                    "confidence": 0.9 if keyword_hits > 0 else 0.3,
                    "sampleSize": len(msg_rows),
                })
            else:
                mv = all_mv[key]
                dimensions.append({
                    "key": key,
                    "label": label,
                    "description": desc,
                    "raw": round(float(mv.raw), 4),
                    "normalized": round(float(mv.normalized), 4),
                    "confidence": round(float(mv.confidence), 2),
                    "sampleSize": int(mv.sample_size),
                })

        return {
            "personId": person_id,
            "displayName": ident.display_name,
            "wxid": primary_wxid,
            "messageCount": len(msg_rows),
            "baseScore": round(float(metrics_obj.base_score), 4),
            "compositeScore": round(float(metrics_obj.composite), 4),
            "signalLevel": signal_level,
            "interactionPattern": pattern_code,
            "interactionPatternLabel": PATTERN_LABELS.get(pattern_code, pattern_code),
            "needinessPenalty": round(float(metrics_obj.neediness_penalty), 4),
            "volumeRatio": round(float(metrics_obj.volume_ratio), 4),
            "initiationRatio": round(float(metrics_obj.initiation_ratio), 4),
            "topTargetBonus": bool(top_target),
            "dimensions15": dimensions,
            "salesSignals": {
                "meetingCount": int(metrics_obj.meeting_count),
                "dealStageCode": int(metrics_obj.deal_stage),
                "budgetKnown": bool(metrics_obj.budget_known),
                "decisionChain": float(metrics_obj.decision_chain),
                "competition": float(metrics_obj.competition),
                "urgency": float(metrics_obj.urgency),
                "keywordHits": keyword_hits,
            },
            "_metricsObj": metrics_obj,
        }

    def compute_15d_metrics(self, target: str) -> Dict[str, Any]:
        """Compute full 15-dimensional quantitative SalesCRM metrics for a contact."""
        with closing(self._connect()) as conn:
            pid = self._resolve_person_id_conn(conn, target)
            if not pid:
                raise SalesCRMValidationError(f"未找到联系人档案：{target}")
            res = self._compute_metrics_conn(conn, pid)
            res.pop("_metricsObj", None)
            res["ok"] = True
            return res

    def _evaluate_formulas_from_metrics(
        self,
        metrics_data: Dict[str, Any],
        *,
        deal_value: float = 0.0,
        overrides: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        dim_map = {d["key"]: float(d["normalized"]) for d in metrics_data["dimensions15"]}
        sales_sig = metrics_data["salesSignals"]
        ov = overrides or {}

        sp = float(ov.get("sp", min(1.0, 0.35 + dim_map["qscore_personal"] * 0.4 + (0.25 if sales_sig["budgetKnown"] else 0.0))))
        fback = float(ov.get("fback", max(0.15, dim_map["fback"])))
        user_investment = float(ov.get("user_investment", min(1.0, max(0.1, 1.0 - float(metrics_data["needinessPenalty"]) * 0.5))))
        pface = float(ov.get("pface", max(0.05, round(1.0 - dim_map["fback_quality"] * 0.7 - dim_map["signal_flags_score"] * 0.3, 3))))

        user_ddepth = float(ov.get("user_ddepth", round(0.45 + dim_map["fback_quality"] * 0.4, 3)))
        target_ddepth = float(ov.get("target_ddepth", round(0.40 + dim_map["qscore_personal"] * 0.45, 3)))
        target_latency = float(ov.get("target_latency", round(0.8 + (1.0 - dim_map["rlatency"]) * 0.6, 3)))
        user_latency = float(ov.get("user_latency", round(0.75 + dim_map["rlatency"] * 0.3, 3)))

        gap_effect = float(ov.get("gap_effect", round(0.35 + dim_map["escore_volatility"] * 0.5, 3)))
        cp_index = float(ov.get("cp_index", round(0.45 + dim_map["recent"] * 0.4, 3)))
        eev = float(ov.get("eev", round(0.25 + dim_map["signal_flags_score"] * 0.65, 3)))
        scarcity_loss = float(ov.get("scarcity_loss", round(max(0.0, (1.0 - float(metrics_data["needinessPenalty"])) * 0.5), 3)))

        p_succ = float(ov.get("p_succ", min(0.95, max(0.15, round(0.25 + float(metrics_data["compositeScore"]) * 0.6 + dim_map["signal_flags_score"] * 0.15, 3)))))
        escalation_bonus = float(ov.get("escalation_bonus", round(0.8 + sales_sig["urgency"] * 0.4, 3)))
        p_fail = float(ov.get("p_fail", round(max(0.05, 1.0 - p_succ), 3)))
        loss_risk = float(ov.get("loss_risk", round(0.2 + float(sales_sig["competition"]) * 0.4, 3)))
        bs = float(ov.get("bs", round(float(sales_sig["competition"]), 3)))

        bq = sales_bq(sp=sp, fback=fback, user_investment=user_investment, pface=pface)
        bsp = sales_bsp(user_ddepth=user_ddepth, target_ddepth=target_ddepth, target_latency=target_latency, user_latency=user_latency)
        bws = sales_bws(gap_effect=gap_effect, cp_index=cp_index, eev=eev, scarcity_loss=scarcity_loss)
        pv = sales_pv(p_succ=p_succ, escalation_bonus=escalation_bonus, p_fail=p_fail, loss_risk=loss_risk)
        action = sales_action(bq=bq["bq"], bsp=bsp["bsp"], bws=bws["bws"], bs=bs, pv=pv["pv"])

        ivi = formula_ivi(sp=sp, fback=fback, user_investment=user_investment, pface=pface)
        spe = formula_spe(user_ddepth=user_ddepth, target_ddepth=target_ddepth, target_latency=target_latency, user_latency=user_latency)
        ews = formula_ews(gap_effect=gap_effect, cp_index=cp_index, eev=eev, scarcity_loss=scarcity_loss)
        rapport_action = formula_action(ivi=ivi["ivi"], spe=spe["spe"], ews=ews["ews"], cs=bs, ev=pv["pv"])

        return {
            "ok": True,
            "bq": bq,
            "bsp": bsp,
            "bws": bws,
            "pv": pv,
            "salesAction": action,
            "expectedDealValue": round(float(deal_value or 0.0) * p_succ, 2),
            "loveCompatFormulas": {
                "ivi": ivi,
                "spe": spe,
                "ews": ews,
                "action": rapport_action,
            },
            "inputs": {
                "sp": round(sp, 3),
                "fback": round(fback, 3),
                "user_investment": round(user_investment, 3),
                "pface": round(pface, 3),
                "user_ddepth": round(user_ddepth, 3),
                "target_ddepth": round(target_ddepth, 3),
                "target_latency": round(target_latency, 3),
                "user_latency": round(user_latency, 3),
                "gap_effect": round(gap_effect, 3),
                "cp_index": round(cp_index, 3),
                "eev": round(eev, 3),
                "scarcity_loss": round(scarcity_loss, 3),
                "p_succ": round(p_succ, 3),
                "escalation_bonus": round(escalation_bonus, 3),
                "p_fail": round(p_fail, 3),
                "loss_risk": round(loss_risk, 3),
                "bs": round(bs, 3),
            },
        }

    def evaluate_formulas(self, target: str, *, overrides: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Run upstream SalesCRM BQ / BSP / BWS / PV / sales_action formulas for a contact."""
        with closing(self._connect()) as conn:
            pid = self._resolve_person_id_conn(conn, target)
        if not pid:
            self.sync_from_wechat()
        with closing(self._connect()) as conn:
            pid = self._resolve_person_id_conn(conn, target)
            if not pid:
                raise SalesCRMValidationError(f"未找到联系人档案：{target}")
            prow = conn.execute("SELECT display_name, deal_value FROM crm_people WHERE person_id = ?", (pid,)).fetchone()
            metrics_data = self._compute_metrics_conn(conn, pid)
            res = self._evaluate_formulas_from_metrics(
                metrics_data,
                deal_value=float(prow["deal_value"] or 0.0) if prow else 0.0,
                overrides=overrides,
            )
            res["personId"] = pid
            res["displayName"] = str(prow["display_name"]) if prow else target
            return res

    def build_activity_timeline(self, target: str) -> List[Dict[str, Any]]:
        """Combine upstream message event/milestone detection with stored CRM timeline entries."""
        with closing(self._connect()) as conn:
            pid = self._resolve_person_id_conn(conn, target)
            if not pid:
                raise SalesCRMValidationError(f"未找到联系人档案：{target}")
            return self._build_timeline_conn(conn, pid)

    def _build_timeline_conn(self, conn: sqlite3.Connection, person_id: str) -> List[Dict[str, Any]]:
        ident = self._get_identity_person_conn(conn, person_id)
        items: List[Dict[str, Any]] = []
        if ident and ident.accounts:
            detected = detect_events(conn, ident) + detect_milestones(conn, ident)
            for ev in detected:
                items.append({
                    "eventType": ev.event_type.name,
                    "label": ev.event_type.value,
                    "category": ev.category.value,
                    "title": f"{ev.event_type.value}",
                    "detail": ev.detail,
                    "at": ev.date,
                    "confidence": round(float(ev.confidence), 2),
                    "source": "salescrm_detector",
                })
        stored_rows = conn.execute(
            "SELECT event_type, category, title, detail, event_at FROM crm_timeline_events "
            "WHERE person_id = ? ORDER BY event_at DESC LIMIT 40",
            (person_id,),
        ).fetchall()
        for r in stored_rows:
            items.append({
                "eventType": str(r["event_type"]),
                "label": str(r["event_type"]),
                "category": str(r["category"]),
                "title": str(r["title"]),
                "detail": str(r["detail"]),
                "at": str(r["event_at"]),
                "confidence": 1.0,
                "source": "crm_ledger",
            })
        items.sort(key=lambda x: str(x.get("at") or ""), reverse=True)
        return items[:50]

    def _generate_drafts_conn(
        self,
        conn: sqlite3.Connection,
        person_id: str,
        *,
        display_name: str,
        stage: str,
        metrics_data: Dict[str, Any],
        formulas_data: Dict[str, Any],
        incoming_text: str = "",
    ) -> List[Dict[str, Any]]:
        kb_query = incoming_text or f"{display_name} {stage} 报价 试用 方案"
        kb_hits = (
            self.engine.knowledge.search_context(kb_query, external_only=True, limit=3).get("entries") or []
            if getattr(self.engine, "knowledge", None)
            else []
        )
        kb_hint = ""
        if kb_hits:
            kb_hint = str(kb_hits[0].get("title") or "").strip()
        soul = self.engine.soul_profiler.get_profiles(target=display_name)
        raw_cp = soul.get("contactProfiles") or []
        friend_prof: Dict[str, Any] = {}
        if isinstance(raw_cp, dict):
            friend_prof = raw_cp.get(display_name) or {}
        elif isinstance(raw_cp, list) and raw_cp:
            friend_prof = raw_cp[0] if isinstance(raw_cp[0], dict) else {}
        mem_snippet = ""
        raw_mems = friend_prof.get("memories") or {}
        flat_mems: List[Any] = []
        if isinstance(raw_mems, dict):
            for b in ("sharedContext", "episodicEvents", "facts"):
                if isinstance(raw_mems.get(b), list):
                    flat_mems.extend(raw_mems[b])
        elif isinstance(raw_mems, list):
            flat_mems.extend(raw_mems)
        if flat_mems:
            last_m = flat_mems[-1]
            mem_snippet = str(last_m.get("content") if isinstance(last_m, dict) else last_m)[:36]

        action_obj = formulas_data.get("salesAction") or {}
        action_code = str(action_obj.get("action") or "maintain")
        reason = str(action_obj.get("reason") or "综合当前互动节奏推进")
        signal_level = metrics_data["signalLevel"]

        if action_code == "bargain":
            t1 = f"结合咱们前面沟通的进度{('（' + mem_snippet + '）') if mem_snippet else ''}，我已把完整方案和报价整理好，方便的话今天帮您对齐最终交付节点？"
        elif action_code == "push":
            t1 = f"最近看您对这块的关注度很高{('，尤其是' + kb_hint) if kb_hint else ''}，我给您准备了一份精简落地对照表，方便约 15 分钟快速过一下吗？"
        elif action_code == "reset":
            t1 = "最近忙吧～前几天整理的行业实战清单刚好更新了新版，先发您放着参考，有空再随时聊。"
        else:
            t1 = f"跟您同步下最新进展{('（围绕「' + kb_hint + '」）') if kb_hint else ''}，您看目前卡在哪一步最需要我先配合？"

        drafts_spec = [
            (
                1,
                "主推 · 精准推进",
                t1,
                {"action": action_code, "signalLevel": signal_level, "kbRef": kb_hint, "reason": reason, "autoSelected": True},
            ),
            (
                2,
                "备选 · 价值案例培育",
                f"分享一个同场景客户的近期实测复盘{('（关联记忆：' + mem_snippet + '）') if mem_snippet else ''}，他们按这个节奏一周内就把核心流程跑通了，需要的话我发您看下详情。",
                {"action": "nurture", "signalLevel": signal_level, "kbRef": kb_hint, "reason": "用案例与知识库证据降低客户决策阻力"},
            ),
            (
                3,
                "备选 · 轻量低压力触达",
                "不打扰您忙，先把资料要点留在这儿，您方便时看一眼就行，有任何问题随时微信喊我。",
                {"action": "maintain", "signalLevel": signal_level, "reason": f"控制发送占比，维持 BSP={formulas_data['bsp']['bsp']} 健康势能"},
            ),
        ]

        now_iso = _utc_iso(self.clock())
        conn.execute("DELETE FROM crm_followup_drafts WHERE person_id = ?", (person_id,))
        results: List[Dict[str, Any]] = []
        for rank_idx, style_tag, content, basis in drafts_spec:
            did = f"dr_{person_id}_{rank_idx}"
            status = "selected" if rank_idx == 1 else "candidate"
            conn.execute(
                "INSERT INTO crm_followup_drafts "
                "(draft_id, person_id, rank_index, style_tag, content, basis_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    did,
                    person_id,
                    rank_idx,
                    style_tag,
                    content,
                    json.dumps(basis, ensure_ascii=False),
                    status,
                    now_iso,
                    now_iso,
                ),
            )
            results.append({
                "draftId": did,
                "rank": rank_idx,
                "styleTag": style_tag,
                "content": content,
                "basis": basis,
                "status": status,
                "selected": rank_idx == 1,
            })
        return results

    def adopt_draft(
        self,
        target: str,
        *,
        rank_index: int = 1,
        send_mode: str = "adopt_only",
    ) -> Dict[str, Any]:
        """Adopt a Top 1-3 follow-up draft; optionally run dry_run or silent_verify via engine.send_text."""
        if rank_index not in (1, 2, 3):
            raise SalesCRMValidationError("rank_index 仅支持 1、2 或 3。")
        with closing(self._connect()) as conn, conn:
            pid = self._resolve_person_id_conn(conn, target)
            if not pid:
                raise SalesCRMValidationError(f"未找到联系人档案：{target}")
            prow = conn.execute("SELECT display_name FROM crm_people WHERE person_id = ?", (pid,)).fetchone()
            display_name = str(prow["display_name"]) if prow else target
            drow = conn.execute(
                "SELECT draft_id, style_tag, content FROM crm_followup_drafts WHERE person_id = ? AND rank_index = ?",
                (pid, int(rank_index)),
            ).fetchone()
            if not drow:
                raise SalesCRMValidationError("请先分析客户以生成 Top 1-3 跟进草稿。")
            draft_content = str(drow["content"])
            now_iso = _utc_iso(self.clock())
            conn.execute(
                "UPDATE crm_followup_drafts SET status = CASE WHEN rank_index = ? THEN 'adopted' ELSE 'archived' END, "
                "updated_at = ? WHERE person_id = ?",
                (int(rank_index), now_iso, pid),
            )
            self._record_timeline_event_conn(
                conn,
                pid,
                event_type="INFO_UPDATE",
                category="销售进展",
                title=f"采纳 Top {rank_index} 跟进草稿 ({drow['style_tag']})",
                detail=draft_content,
            )

        send_receipt: Optional[Dict[str, Any]] = None
        if send_mode in ("dry_run", "silent_verify"):
            send_receipt = self.engine.send_text(
                target=display_name,
                text=draft_content,
                dry_run=(send_mode == "dry_run"),
                silent_mode=True,
                confirm_send=False,
            )
        return {
            "ok": True,
            "personId": pid,
            "displayName": display_name,
            "rank": int(rank_index),
            "adoptedContent": draft_content,
            "sendMode": send_mode,
            "sendReceipt": send_receipt,
        }

    def analyze_contact(
        self,
        target: str,
        *,
        incoming_text: str = "",
        formula_overrides: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Run full SalesCRM 15D metrics, formulas, stage, timeline, and Top 1-3 follow-up drafts."""
        with closing(self._connect()) as conn:
            pid = self._resolve_person_id_conn(conn, target)
        if not pid:
            self.sync_from_wechat()
        with closing(self._connect()) as conn, conn:
            pid = self._resolve_person_id_conn(conn, target)
            if not pid:
                raise SalesCRMValidationError(f"未找到联系人档案：{target}")
            prow = conn.execute("SELECT * FROM crm_people WHERE person_id = ?", (pid,)).fetchone()
            assert prow is not None
            metrics_data = self._compute_metrics_conn(conn, pid)
            metrics_obj = metrics_data.pop("_metricsObj")
            stage_eval = recognize_stage(conn, metrics_obj, metrics_data["wxid"], metrics_data["displayName"])
            inferred_stage = LEGACY_STAGE_MAP.get(stage_eval.stage_state.current_stage, stage_eval.stage_state.current_stage)
            if not prow["manual_stage_override"] and inferred_stage in STAGES:
                conn.execute(
                    "UPDATE crm_people SET stage = ?, updated_at = ? WHERE person_id = ?",
                    (inferred_stage, _utc_iso(self.clock()), pid),
                )
                active_stage = inferred_stage
            else:
                active_stage = str(prow["stage"])

            formulas_data = self._evaluate_formulas_from_metrics(
                metrics_data,
                deal_value=float(prow["deal_value"] or 0.0),
                overrides=formula_overrides,
            )
            timeline = self._build_timeline_conn(conn, pid)
            drafts = self._generate_drafts_conn(
                conn,
                pid,
                display_name=str(prow["display_name"]),
                stage=active_stage,
                metrics_data=metrics_data,
                formulas_data=formulas_data,
                incoming_text=incoming_text,
            )
            ident = self._get_identity_person_conn(conn, pid)

            return {
                "ok": True,
                "upstream": self.UPSTREAM_INFO,
                "person": {
                    "personId": pid,
                    "displayName": str(prow["display_name"]),
                    "realName": str(prow["real_name"] or ""),
                    "stage": active_stage,
                    "inferredStage": inferred_stage,
                    "manualStageOverride": bool(prow["manual_stage_override"]),
                    "nextStage": stage_eval.stage_state.next_stage,
                    "isStagnant": bool(stage_eval.stage_state.is_stagnant),
                    "note": str(prow["note"] or ""),
                    "followUpUtc": prow["follow_up_utc"],
                    "followUpBeijing": str(prow["follow_up_beijing"] or ""),
                    "dealValue": float(prow["deal_value"] or 0.0),
                    "tags": json.loads(prow["tags_json"] or "[]"),
                    "accounts": [a.__dict__ for a in (ident.accounts if ident else [])],
                    "aliases": ident.aliases if ident else [],
                },
                "metrics": metrics_data,
                "formulas": formulas_data,
                "timeline": timeline,
                "topDrafts": drafts,
            }

    def get_overview(self, *, auto_sync: bool = True) -> Dict[str, Any]:
        """Return SalesCRM pipeline summary, ranked customers, due follow-ups, and formulas overview."""
        sync_info: Optional[Dict[str, Any]] = None
        if auto_sync:
            sync_info = self.sync_from_wechat()
        reminders = self.list_reminders()

        ranked_people: List[Dict[str, Any]] = []
        total_pipeline_pv = 0.0
        strong_count = 0
        medium_count = 0
        excluded_test_names: set[str] = {
            str(n).strip().casefold()
            for n in ((sync_info or {}).get("excludedTestContacts") or [])
            if str(n).strip()
        }

        with closing(self._connect()) as conn:
            people_rows = conn.execute("SELECT * FROM crm_people ORDER BY updated_at DESC").fetchall()
            for prow in people_rows:
                display_name = str(prow["display_name"] or "")
                if self._is_test_contact(display_name):
                    excluded_test_names.add(display_name.strip().casefold())
                    continue
                pid = str(prow["person_id"])
                metrics_data = self._compute_metrics_conn(conn, pid)
                metrics_data.pop("_metricsObj", None)
                formulas_data = self._evaluate_formulas_from_metrics(
                    metrics_data,
                    deal_value=float(prow["deal_value"] or 0.0),
                )
                expected_val = float(formulas_data["expectedDealValue"])
                total_pipeline_pv += expected_val
                sig_level = metrics_data["signalLevel"]
                if sig_level == "强意向":
                    strong_count += 1
                elif sig_level == "中意向":
                    medium_count += 1

                binding = self.engine.bindings.get_binding(str(prow["display_name"])) or {}
                priority_boost = 0.1 if binding.get("specialCare") else 0.0
                urgency_score = round(min(1.0, float(metrics_data["compositeScore"]) + priority_boost), 4)
                ranked_people.append({
                    "personId": pid,
                    "displayName": str(prow["display_name"]),
                    "stage": str(prow["stage"]),
                    "note": str(prow["note"] or ""),
                    "followUpUtc": prow["follow_up_utc"],
                    "followUpBeijing": str(prow["follow_up_beijing"] or ""),
                    "dealValue": float(prow["deal_value"] or 0.0),
                    "expectedDealValue": expected_val,
                    "compositeScore": metrics_data["compositeScore"],
                    "baseScore": metrics_data["baseScore"],
                    "urgencyScore": urgency_score,
                    "signalLevel": sig_level,
                    "interactionPattern": metrics_data["interactionPattern"],
                    "interactionPatternLabel": metrics_data["interactionPatternLabel"],
                    "messageCount": metrics_data["messageCount"],
                    "specialCare": bool(binding.get("specialCare")),
                    "tags": json.loads(prow["tags_json"] or "[]"),
                    "bq": formulas_data["bq"]["bq"],
                    "bsp": formulas_data["bsp"]["bsp"],
                    "bws": formulas_data["bws"]["bws"],
                    "pv": formulas_data["pv"]["pv"],
                    "salesAction": formulas_data["salesAction"]["action"],
                    "salesActionReason": formulas_data["salesAction"]["reason"],
                })

        ranked_people.sort(key=lambda x: (x["urgencyScore"], x["compositeScore"], x["messageCount"]), reverse=True)
        for idx, item in enumerate(ranked_people, start=1):
            item["rank"] = idx

        stage_counts: Dict[str, int] = {st: 0 for st in STAGES}
        for item in ranked_people:
            st = item["stage"] if item["stage"] in stage_counts else "新线索"
            stage_counts[st] += 1

        focus_analysis: Optional[Dict[str, Any]] = None
        if ranked_people:
            focus_analysis = self.analyze_contact(ranked_people[0]["personId"])

        return {
            "ok": True,
            "upstream": self.UPSTREAM_INFO,
            "dbPath": str(self.db_path),
            "stages": list(STAGES),
            "metric15Specs": [{"key": k, "label": lbl, "desc": dsc} for k, lbl, dsc in METRIC_15D_SPECS],
            "sync": sync_info,
            "summary": {
                "totalPeople": len(ranked_people),
                "strongIntentCount": strong_count,
                "mediumIntentCount": medium_count,
                "dueRemindersCount": reminders["dueCount"],
                "upcomingRemindersCount": reminders["upcomingCount"],
                "totalPipelineExpectedValue": round(total_pipeline_pv, 2),
                "excludedTestContactsCount": len(excluded_test_names),
                "stageCounts": stage_counts,
            },
            "reminders": reminders,
            "rankings": ranked_people,
            "focusAnalysis": focus_analysis,
        }
