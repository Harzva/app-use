"""WeChat Customer Service Knowledge Base, Domain Terminology, and Persona Switching Engine.

Aligns with OpenBot's dual-layer SQLite FTS5 knowledge architecture (`bot-knowledge.js`),
customer-service takeover/basis governance (`feishu-customer-pilot.js`), and manual
personality system (`openbot-personality.js`).
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_OPENBOT_KNOWLEDGE_DB = Path("/Users/mac/Library/Application Support/openbot/bot-knowledge/knowledge.sqlite")

LIBRARIES = ("shared", "bot")
KINDS = ("terminology", "knowledge", "script", "faq")
STATUSES = ("draft", "published")
MBTI_TYPES = (
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
)
INTERACTION_STYLES = ("challenger", "builder", "neutral", "supporter")

STYLE_LABELS: Dict[str, str] = {
    "challenger": "反驳型",
    "builder": "建设型",
    "neutral": "中立型",
    "supporter": "捧场型",
}

STYLE_DIRECTIVES: Dict[str, str] = {
    "challenger": "直率核验前提与潜在风险，不被习惯表述带偏。",
    "builder": "结论先行并给出可执行方案与前置条件。",
    "neutral": "客观陈述事实、依据与边界，不偏不倚。",
    "supporter": "积极回应并肯定对方互动细节，自然延展交流。",
}

_TERM_SPLIT_RE = re.compile(r"[\s,，。、;；:：!！?？\"'“”‘’()（）\[\]{}<>《》~@#$%^&*+=|\\/\-_]+")
_SECRET_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|sk-[A-Za-z0-9]{20,}")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_entries (
  space_id TEXT NOT NULL,
  owner_bot_id TEXT NOT NULL,
  id TEXT NOT NULL,
  library TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  keywords TEXT NOT NULL DEFAULT '[]',
  synonyms TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL DEFAULT '',
  external INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'published',
  withdrawn INTEGER NOT NULL DEFAULT 0,
  revision INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (space_id, owner_bot_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS knowledge_entries_space_id ON knowledge_entries(space_id, id);
CREATE INDEX IF NOT EXISTS knowledge_entries_scope
  ON knowledge_entries(space_id, owner_bot_id, library, withdrawn, status);
CREATE TABLE IF NOT EXISTS knowledge_styles (
  space_id TEXT NOT NULL,
  bot_id TEXT NOT NULL,
  value TEXT NOT NULL,
  revision INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (space_id, bot_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
  USING fts5(entry_rowid UNINDEXED, title, body, keywords, synonyms, tokenize = 'trigram');
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _guard_secrets(*values: str) -> None:
    for val in values:
        if val and _SECRET_RE.search(val):
            raise ValueError("Secret/private-key material is rejected from knowledge store.")


def split_search_terms(query: str, max_terms: int = 16) -> List[str]:
    """Extract phrase, tokenized terms, and 2-char Han bigrams matching OpenBot knowledgeForText."""
    norm = unicodedata.normalize("NFKC", query or "").strip()
    if not norm:
        return []

    terms: List[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        clean = tok.strip()
        if not clean:
            return
        cf = clean.casefold()
        if cf in seen:
            return
        seen.add(cf)
        terms.append(clean[:40])

    for raw in _TERM_SPLIT_RE.split(norm):
        if len(raw) >= 2:
            _add(raw)

    # Extract sliding 2-char Chinese bigrams and meaningful English/alnum tokens
    han_runs = re.findall(r"[\u4e00-\u9fff]+", norm)
    for run in han_runs:
        if len(run) <= 6 and len(run) >= 2:
            _add(run)
        for i in range(len(run) - 1):
            _add(run[i : i + 2])
            if len(terms) >= max_terms:
                break
        if len(terms) >= max_terms:
            break

    return terms[:max_terms]


DEFAULT_SEED_ENTRIES: List[Dict[str, Any]] = [
    {
        "id": "seed-term-wechat-rpa",
        "library": "shared",
        "kind": "terminology",
        "title": "WeChat RPA (微信桌面自动化)",
        "body": "基于 macOS CGWindowListCreateImage 窗口截图、VNRecognizeTextRequest 视觉 OCR 与 CGEvent 坐标合成的零注入安全操控方案，不 hook 微信内存、不修改微信客户端二进制。",
        "keywords": ["WeChat RPA", "视觉OCR", "CGEvent", "零注入", "微信自动化", "桌面控制"],
        "synonyms": ["微信RPA", "微信桌面操控", "非侵入式自动化", "Vision OCR"],
        "source": "openbot://terminology/wechat-rpa",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-term-realtime-monitor",
        "library": "shared",
        "kind": "terminology",
        "title": "RealtimeMessageMonitor (后台实时消息监控器)",
        "body": "通过非侵入式窗口快照周期轮询左侧会话未读角标、最新摘要变化与右侧聊天区底部气泡增量，自动识别已绑定好友或客户的新消息并结合知识库与性格配置触发回复的后台守护程序。",
        "keywords": ["实时监控", "后台监控", "自动回复", "消息监测", "未读角标", "轮询", "RealtimeMessageMonitor"],
        "synonyms": ["实时监测", "后台监听", "自动应答", "消息监控"],
        "source": "openbot://terminology/realtime-monitor",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-term-circuit-breaker",
        "library": "shared",
        "kind": "terminology",
        "title": "3x Dirty-Input Circuit Breaker (3倍脏输入熔断器)",
        "body": "粘贴消息到微信输入框后立即执行 Cmd+A / Cmd+C 剪贴板回读与输入框 Vision OCR 校验；若输入框残留历史草稿导致长度超过预期 3 倍或正文不匹配，则自动清空熔断，严防错发或拼接误发。",
        "keywords": ["熔断器", "脏输入", "回读校验", "防误发", "去重锁"],
        "synonyms": ["3倍熔断", "回读保护", "防错发机制"],
        "source": "openbot://terminology/circuit-breaker",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-term-studio-gate",
        "library": "shared",
        "kind": "terminology",
        "title": "Bot Studio Fail-Closed Gate (Studio 授权门控)",
        "body": "微信插件遵循 Fail-Closed（默认关闭）原则，必须持有 Bot Studio 签发的 studio_auth.json 授权凭据及细分能力白名单（只读巡检、演练校验、实时发送），撤销授权即刻阻断全部调用。",
        "keywords": ["Bot Studio", "授权门控", "Fail-Closed", "能力白名单", "独立插件"],
        "synonyms": ["插件授权", "默认关闭", "权限开关"],
        "source": "openbot://terminology/studio-gate",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-term-wecom-kf-bridge",
        "library": "shared",
        "kind": "terminology",
        "title": "WeChat Customer Service Bridge (微信企业客服知识接入)",
        "body": "复用 OpenBot 本地双层知识库（shared 共享规则与 bot 专属 SOP）、SQLite FTS5 trigram + 中文短词检索、对外发布白名单（external=1）、标准客服话术（script）与人工接管（takeover）状态机，确保性格切换只调语气，不改批准口径。",
        "keywords": ["微信客服", "企业客服", "知识库", "性格切换", "话术", "人工接管", "takeover", "专业术语"],
        "synonyms": ["微信企业客服", "客服知识库", "人设切换", "智能客服"],
        "source": "openbot://terminology/wecom-kf-bridge",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-term-wechat-bridge",
        "library": "shared",
        "kind": "terminology",
        "title": "WeChatBridge 归档导入",
        "body": "支持将微信合并转发 .zip 归档与 聊天记录.txt 离线导入为 Obsidian Markdown 与 JSONL 结构化语料，内置 Zip Slip 路径穿越防护。",
        "keywords": ["WeChatBridge", "聊天记录导入", "zip", "Obsidian", "归档"],
        "synonyms": ["微信桥接", "聊天记录解析", "离线归档"],
        "source": "openbot://terminology/wechat-bridge",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-script-live-reply-ack",
        "library": "shared",
        "kind": "script",
        "title": "实时监控与自动回复确认话术",
        "body": "标准回复要点：1. 明确告知已通过后台实时消息监控捕获本条提问；2. 说明已接入本地微信客服知识库、专业术语词典与动态性格切换引擎；3. 邀请对方继续发送测试问题或业务咨询。",
        "keywords": ["回复消息", "能回复", "在吗", "测试", "你好", "收到", "实时监控", "自动回复"],
        "synonyms": ["可以回复", "看到消息", "智能回复确认"],
        "source": "openbot://scripts/live-reply-ack",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-kb-rpa-vs-crawler",
        "library": "shared",
        "kind": "knowledge",
        "title": "RPA 与爬虫、按键精灵区别解答",
        "body": "标准技术口径：爬虫仅抓取网页接口或 HTML；按键精灵依赖易失效的固定屏幕绝对坐标；而 OpenBot WeChat RPA 结合窗口相对坐标、macOS Vision OCR 语义识别、输入框 3x 回读熔断与知识库推理，可稳定理解会话上下文并安全交互。",
        "keywords": ["RPA", "爬虫", "按键精灵", "影刀", "区别", "StaffDeck"],
        "synonyms": ["视觉RPA", "桌面机器人"],
        "source": "openbot://kb/rpa-vs-crawler",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-script-kf-takeover",
        "library": "shared",
        "kind": "script",
        "title": "企业客服标准接待与人工接管说明",
        "body": "标准客服口径：仅依据已发布且允许对外（external=1）的知识条目与专业术语作答；如遇未收录政策、订单争议或复杂售后，不编造承诺，立即标记人工接管（takeover）交由专员核对。",
        "keywords": ["客服", "退货", "政策", "数字婚礼", "转人工", "人工接管", "咨询", "报价"],
        "synonyms": ["售后", "工单", "企业微信客服"],
        "source": "openbot://scripts/kf-takeover",
        "external": True,
        "status": "published",
    },
]

DEFAULT_PERSONAS: Dict[str, Dict[str, Any]] = {
    "warm-friend": {
        "id": "warm-friend",
        "name": "轻松幽默好友",
        "mbti": "ENFP",
        "interactionStyle": "supporter",
        "tone": "轻松自然、懂得接梗、带温度与适度表情符号",
        "prefixHint": "哈哈收到啦！",
        "guidelines": "像熟悉的老友一样自然回话，同时清晰传递知识库要点；避免生硬客服官腔。",
        "maxChars": 150,
    },
    "wecom-kf-pro": {
        "id": "wecom-kf-pro",
        "name": "微信企业客服专员",
        "mbti": "ISTJ",
        "interactionStyle": "builder",
        "tone": "礼貌规范、结构清晰、严格遵循已发布话术与专业术语口径",
        "prefixHint": "您好，",
        "guidelines": "以“您好”开头，分点给出准确答案与依据，不对未授权政策作承诺。",
        "maxChars": 160,
    },
    "rpa-tech-expert": {
        "id": "rpa-tech-expert",
        "name": "OpenBot 技术架构师",
        "mbti": "INTJ",
        "interactionStyle": "builder",
        "tone": "硬核干练、善用专业术语（Vision OCR / FTS5 / 3x 熔断 / Takeover）",
        "prefixHint": "【技术应答】",
        "guidelines": "直接阐明底层机制、数据链路与安全边界，精准使用术语名称。",
        "maxChars": 160,
    },
    "concise-assistant": {
        "id": "concise-assistant",
        "name": "干练高效助理",
        "mbti": "ESTJ",
        "interactionStyle": "neutral",
        "tone": "简洁明了、直击结论、不拖泥带水",
        "prefixHint": "收到：",
        "guidelines": "一句结论 + 关键事实，控制字数在 80 字以内。",
        "maxChars": 95,
    },
    "owner-digital-twin": {
        "id": "owner-digital-twin",
        "name": "🎭 号主本人数字分身 · 原生性格与记忆",
        "mbti": "ENTJ",
        "interactionStyle": "builder",
        "tone": "真实还原微信号主本我性格与说话习惯：对熟人轻松幽默短句接梗，对技术与工作群务实直给结论，结合过往共同记忆自然接话。",
        "prefixHint": "",
        "guidelines": "先调用号主本我画像与双方历史记忆，绝不说生硬AI或客服套话；像号主真人微信秒回一样简练自然。",
        "maxChars": 140,
    },
}


class WeChatKnowledgeStore:
    """SQLite + FTS5 trigram dual-layer knowledge, terminology, and customer-service script store."""

    def __init__(
        self,
        db_path: Path,
        *,
        openbot_db_path: Optional[Path] = DEFAULT_OPENBOT_KNOWLEDGE_DB,
        auto_seed: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.openbot_db_path = Path(openbot_db_path) if openbot_db_path else None
        self._init_schema()
        if auto_seed:
            self.seed_default_knowledge()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    @staticmethod
    def _entry_view(row: sqlite3.Row) -> Dict[str, Any]:
        def _parse_list(raw: Any) -> List[str]:
            if isinstance(raw, list):
                return [str(x) for x in raw]
            try:
                val = json.loads(raw or "[]")
                return [str(x) for x in val] if isinstance(val, list) else []
            except Exception:
                return []

        return {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "ownerBotId": str(row["owner_bot_id"]),
            "library": str(row["library"]),
            "kind": str(row["kind"]),
            "title": str(row["title"]),
            "body": str(row["body"]),
            "keywords": _parse_list(row["keywords"]),
            "synonyms": _parse_list(row["synonyms"]),
            "source": str(row["source"]),
            "external": bool(row["external"]),
            "status": str(row["status"]),
            "withdrawn": bool(row["withdrawn"]),
            "revision": int(row["revision"]),
            "updatedAt": int(row["updated_at"]),
        }

    @staticmethod
    def _sync_fts(conn: sqlite3.Connection, rowid: int, title: str, body: str, keywords: str, synonyms: str) -> None:
        conn.execute("DELETE FROM knowledge_fts WHERE entry_rowid = ?", (rowid,))
        conn.execute(
            "INSERT INTO knowledge_fts(entry_rowid, title, body, keywords, synonyms) VALUES(?, ?, ?, ?, ?)",
            (rowid, title, body, keywords, synonyms),
        )

    def seed_default_knowledge(self, *, space_id: str = "personal") -> Dict[str, Any]:
        inserted = 0
        now = _now_ms()
        with self._connect() as conn:
            for item in DEFAULT_SEED_ENTRIES:
                exists = conn.execute(
                    "SELECT 1 FROM knowledge_entries WHERE space_id = ? AND id = ?",
                    (space_id, item["id"]),
                ).fetchone()
                if exists:
                    continue
                kw_json = json.dumps(item.get("keywords") or [], ensure_ascii=False)
                syn_json = json.dumps(item.get("synonyms") or [], ensure_ascii=False)
                cur = conn.execute(
                    """
                    INSERT INTO knowledge_entries(
                      space_id, owner_bot_id, id, library, kind, title, body, keywords, synonyms,
                      source, external, status, withdrawn, revision, created_at, updated_at
                    ) VALUES(?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
                    """,
                    (
                        space_id,
                        item["id"],
                        item["library"],
                        item["kind"],
                        item["title"],
                        item["body"],
                        kw_json,
                        syn_json,
                        item.get("source", ""),
                        1 if item.get("external", True) else 0,
                        item.get("status", "published"),
                        now,
                        now,
                    ),
                )
                self._sync_fts(conn, int(cur.lastrowid), item["title"], item["body"], kw_json, syn_json)
                inserted += 1
        return {"ok": True, "inserted": inserted}

    def save_entry(
        self,
        *,
        title: str,
        body: str,
        kind: str = "knowledge",
        library: str = "shared",
        keywords: Optional[Iterable[str]] = None,
        synonyms: Optional[Iterable[str]] = None,
        source: str = "wechat-plugin",
        external: bool = True,
        status: str = "published",
        space_id: str = "personal",
        bot_id: str = "default",
        entry_id: Optional[str] = None,
        expected_revision: int = 0,
    ) -> Dict[str, Any]:
        if library not in LIBRARIES:
            raise ValueError(f"Unsupported library: {library!r}")
        if kind not in KINDS:
            raise ValueError(f"Unsupported kind: {kind!r}")
        if status not in STATUSES:
            raise ValueError(f"Unsupported status: {status!r}")
        clean_title = (title or "").strip()
        clean_body = (body or "").strip()
        if not clean_title or not clean_body:
            raise ValueError("Knowledge title and body cannot be empty.")
        _guard_secrets(clean_title, clean_body, source)

        kw_list = [str(k).strip() for k in (keywords or []) if str(k).strip()]
        syn_list = [str(s).strip() for s in (synonyms or []) if str(s).strip()]
        kw_json = json.dumps(kw_list, ensure_ascii=False)
        syn_json = json.dumps(syn_list, ensure_ascii=False)
        owner_bot_id = "" if library == "shared" else bot_id
        now = _now_ms()

        with self._connect() as conn:
            if entry_id:
                existing = conn.execute(
                    """
                    SELECT rowid, * FROM knowledge_entries
                    WHERE space_id = ? AND id = ? AND withdrawn = 0
                      AND (library = 'shared' OR (library = 'bot' AND owner_bot_id = ?))
                    """,
                    (space_id, entry_id, bot_id),
                ).fetchone()
                if not existing:
                    raise KeyError(f"Knowledge entry not found: {entry_id}")
                if int(existing["revision"]) != int(expected_revision):
                    raise ValueError(
                        f"REVISION_CONFLICT: expected {expected_revision}, got {existing['revision']}"
                    )
                next_rev = int(existing["revision"]) + 1
                conn.execute(
                    """
                    UPDATE knowledge_entries
                    SET kind = ?, title = ?, body = ?, keywords = ?, synonyms = ?, source = ?,
                        external = ?, status = ?, revision = ?, updated_at = ?
                    WHERE rowid = ?
                    """,
                    (
                        kind,
                        clean_title,
                        clean_body,
                        kw_json,
                        syn_json,
                        source,
                        1 if external else 0,
                        status,
                        next_rev,
                        now,
                        int(existing["rowid"]),
                    ),
                )
                self._sync_fts(conn, int(existing["rowid"]), clean_title, clean_body, kw_json, syn_json)
                saved_id = entry_id
            else:
                if int(expected_revision) != 0:
                    raise ValueError("REVISION_CONFLICT: expectedRevision must be 0 for new entry.")
                saved_id = f"kb_{uuid.uuid4().hex[:12]}"
                cur = conn.execute(
                    """
                    INSERT INTO knowledge_entries(
                      space_id, owner_bot_id, id, library, kind, title, body, keywords, synonyms,
                      source, external, status, withdrawn, revision, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
                    """,
                    (
                        space_id,
                        owner_bot_id,
                        saved_id,
                        library,
                        kind,
                        clean_title,
                        clean_body,
                        kw_json,
                        syn_json,
                        source,
                        1 if external else 0,
                        status,
                        now,
                        now,
                    ),
                )
                self._sync_fts(conn, int(cur.lastrowid), clean_title, clean_body, kw_json, syn_json)

            row = conn.execute(
                "SELECT * FROM knowledge_entries WHERE space_id = ? AND id = ?",
                (space_id, saved_id),
            ).fetchone()
            return {"ok": True, "entry": self._entry_view(row)}

    def withdraw_entry(
        self,
        entry_id: str,
        *,
        expected_revision: int,
        space_id: str = "personal",
        bot_id: str = "default",
    ) -> Dict[str, Any]:
        now = _now_ms()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT rowid, * FROM knowledge_entries
                WHERE space_id = ? AND id = ? AND withdrawn = 0
                  AND (library = 'shared' OR (library = 'bot' AND owner_bot_id = ?))
                """,
                (space_id, entry_id, bot_id),
            ).fetchone()
            if not row:
                raise KeyError(f"Knowledge entry not found: {entry_id}")
            if int(row["revision"]) != int(expected_revision):
                raise ValueError(f"REVISION_CONFLICT: expected {expected_revision}, got {row['revision']}")
            next_rev = int(row["revision"]) + 1
            conn.execute(
                "UPDATE knowledge_entries SET withdrawn = 1, status = 'draft', revision = ?, updated_at = ? WHERE rowid = ?",
                (next_rev, now, int(row["rowid"])),
            )
            updated = conn.execute(
                "SELECT * FROM knowledge_entries WHERE rowid = ?",
                (int(row["rowid"]),),
            ).fetchone()
            return {"ok": True, "entry": self._entry_view(updated)}

    def list_entries(
        self,
        *,
        space_id: str = "personal",
        bot_id: str = "default",
        library: Optional[str] = None,
        kind: Optional[str] = None,
        include_drafts: bool = True,
        external_only: bool = False,
        limit: int = 200,
    ) -> Dict[str, Any]:
        where = ["space_id = ?", "withdrawn = 0"]
        params: List[Any] = [space_id]
        if library == "shared":
            where.append("library = 'shared'")
        elif library == "bot":
            where.append("library = 'bot' AND owner_bot_id = ?")
            params.append(bot_id)
        else:
            where.append("(library = 'shared' OR (library = 'bot' AND owner_bot_id = ?))")
            params.append(bot_id)

        if not include_drafts:
            where.append("status = 'published'")
        if external_only:
            where.append("external = 1")
        if kind:
            where.append("kind = ?")
            params.append(kind)

        sql = (
            f"SELECT * FROM knowledge_entries WHERE {' AND '.join(where)} "
            "ORDER BY CASE kind WHEN 'terminology' THEN 0 WHEN 'script' THEN 1 WHEN 'faq' THEN 2 ELSE 3 END, updated_at DESC LIMIT ?"
        )
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            style_row = conn.execute(
                "SELECT value, revision FROM knowledge_styles WHERE space_id = ? AND bot_id = ?",
                (space_id, bot_id),
            ).fetchone()
        return {
            "ok": True,
            "count": len(rows),
            "dbPath": str(self.db_path),
            "entries": [self._entry_view(r) for r in rows],
            "style": (
                {"value": str(style_row["value"]), "revision": int(style_row["revision"])}
                if style_row
                else {"value": "", "revision": 0}
            ),
        }

    def search_context(
        self,
        query: str,
        *,
        space_id: str = "personal",
        bot_id: str = "default",
        library: Optional[str] = None,
        kind: Optional[str] = None,
        external_only: bool = True,
        limit: int = 6,
    ) -> Dict[str, Any]:
        terms = split_search_terms(query)
        where = ["e.space_id = ?", "e.withdrawn = 0", "e.status = 'published'"]
        params: List[Any] = [space_id]
        if library == "shared":
            where.append("e.library = 'shared'")
        elif library == "bot":
            where.append("e.library = 'bot' AND e.owner_bot_id = ?")
            params.append(bot_id)
        else:
            where.append("(e.library = 'shared' OR (e.library = 'bot' AND e.owner_bot_id = ?))")
            params.append(bot_id)
        if external_only:
            where.append("e.external = 1")
        if kind:
            where.append("e.kind = ?")
            params.append(kind)

        with self._connect() as conn:
            # Candidate retrieval via FTS5 trigram for >=3-char terms plus full-scope scan for short tokens/synonyms
            candidates: Dict[str, sqlite3.Row] = {}
            long_terms = [t for t in terms if len(t) >= 3]
            if long_terms:
                fts_or = " OR ".join('"' + t.replace('"', '""') + '"' for t in long_terms[:8])
                fts_rows = conn.execute(
                    f"""
                    SELECT e.* FROM knowledge_fts f
                    JOIN knowledge_entries e ON e.rowid = f.entry_rowid
                    WHERE knowledge_fts MATCH ? AND {' AND '.join(where)}
                    LIMIT 200
                    """,
                    [fts_or] + params,
                ).fetchall()
                for r in fts_rows:
                    candidates[str(r["id"])] = r

            # Bounded scope scan handles 2-char Chinese tokens & synonyms accurately
            all_scope_rows = conn.execute(
                f"SELECT e.* FROM knowledge_entries e WHERE {' AND '.join(where)} ORDER BY e.updated_at DESC LIMIT 400",
                params,
            ).fetchall()
            for r in all_scope_rows:
                candidates.setdefault(str(r["id"]), r)

        if not terms:
            ordered = [self._entry_view(r) for r in list(candidates.values())[:limit]]
            return {"ok": True, "query": query, "terms": [], "count": len(ordered), "entries": ordered}

        scored: List[Tuple[float, Dict[str, Any]]] = []
        norm_query = unicodedata.normalize("NFKC", query or "").casefold()
        for row in candidates.values():
            view = self._entry_view(row)
            title_cf = view["title"].casefold()
            body_cf = view["body"].casefold()
            kw_cf = " ".join(view["keywords"]).casefold()
            syn_cf = " ".join(view["synonyms"]).casefold()

            score = 0.0
            matched_terms: List[str] = []
            for term in terms:
                t_cf = term.casefold()
                hit = False
                if t_cf in title_cf:
                    score += 4.5 + min(len(t_cf), 10) * 0.25
                    hit = True
                if t_cf in kw_cf:
                    score += 4.0
                    hit = True
                if t_cf in syn_cf:
                    score += 3.5
                    hit = True
                if t_cf in body_cf:
                    score += 1.5
                    hit = True
                if hit:
                    matched_terms.append(term)

            # Exact multi-char substring boost
            for kw in view["keywords"] + view["synonyms"]:
                if len(kw) >= 2 and kw.casefold() in norm_query:
                    score += 5.0
                    if kw not in matched_terms:
                        matched_terms.append(kw)

            if score <= 0:
                continue
            if view["kind"] == "terminology":
                score += 1.5
            elif view["kind"] == "script":
                score += 1.25

            view["score"] = round(score, 2)
            view["matchedTerms"] = matched_terms
            scored.append((score, view))

        scored.sort(key=lambda item: (-item[0], -item[1]["updatedAt"], item[1]["id"]))
        top_entries = [item[1] for item in scored[:limit]]
        return {
            "ok": True,
            "query": query,
            "terms": terms,
            "count": len(top_entries),
            "matchedCount": len(top_entries),
            "entries": top_entries,
        }

    def sync_from_openbot_knowledge(self, source_db_path: Optional[Path] = None) -> Dict[str, Any]:
        """Import published external-safe entries and styles from OpenBot's native knowledge.sqlite."""
        src = Path(source_db_path) if source_db_path else self.openbot_db_path
        if src is None or not src.exists():
            return {
                "ok": True,
                "sourceExists": False,
                "sourcePath": str(src) if src else None,
                "importedEntries": 0,
                "importedStyles": 0,
                "note": "OpenBot native knowledge.sqlite not found; using built-in WeChat KF knowledge store.",
            }

        imported_entries = 0
        imported_styles = 0
        try:
            src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=3.0)
            src_conn.row_factory = sqlite3.Row
        except Exception as exc:
            return {
                "ok": False,
                "sourceExists": True,
                "sourcePath": str(src),
                "error": f"Failed to open OpenBot knowledge DB read-only: {exc}",
            }

        try:
            rows = src_conn.execute(
                "SELECT * FROM knowledge_entries WHERE withdrawn = 0 AND status = 'published'"
            ).fetchall()
            styles = src_conn.execute("SELECT * FROM knowledge_styles").fetchall()
        except Exception as exc:
            src_conn.close()
            return {"ok": False, "sourcePath": str(src), "error": str(exc)}

        with self._connect() as dst:
            for r in rows:
                orig_id = f"openbot:{r['id']}"
                kind = str(r["kind"]) if str(r["kind"]) in KINDS else "knowledge"
                existing = dst.execute(
                    "SELECT rowid, revision FROM knowledge_entries WHERE space_id = ? AND id = ?",
                    (str(r["space_id"]), orig_id),
                ).fetchone()
                if existing:
                    dst.execute(
                        """
                        UPDATE knowledge_entries
                        SET kind = ?, title = ?, body = ?, source = ?, external = ?, status = ?,
                            revision = ?, updated_at = ?
                        WHERE rowid = ?
                        """,
                        (
                            kind,
                            str(r["title"]),
                            str(r["body"]),
                            f"openbot:{r['source']}",
                            int(r["external"]),
                            str(r["status"]),
                            int(r["revision"]),
                            int(r["updated_at"]),
                            int(existing["rowid"]),
                        ),
                    )
                    self._sync_fts(conn=dst, rowid=int(existing["rowid"]), title=str(r["title"]), body=str(r["body"]), keywords="[]", synonyms="[]")
                else:
                    cur = dst.execute(
                        """
                        INSERT INTO knowledge_entries(
                          space_id, owner_bot_id, id, library, kind, title, body, keywords, synonyms,
                          source, external, status, withdrawn, revision, created_at, updated_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, '[]', '[]', ?, ?, ?, 0, ?, ?, ?)
                        """,
                        (
                            str(r["space_id"]),
                            str(r["owner_bot_id"]),
                            orig_id,
                            str(r["library"]),
                            kind,
                            str(r["title"]),
                            str(r["body"]),
                            f"openbot:{r['source']}",
                            int(r["external"]),
                            str(r["status"]),
                            int(r["revision"]),
                            int(r["created_at"]),
                            int(r["updated_at"]),
                        ),
                    )
                    self._sync_fts(conn=dst, rowid=int(cur.lastrowid), title=str(r["title"]), body=str(r["body"]), keywords="[]", synonyms="[]")
                imported_entries += 1

            for st in styles:
                dst.execute(
                    """
                    INSERT INTO knowledge_styles(space_id, bot_id, value, revision, updated_at)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(space_id, bot_id) DO UPDATE SET
                      value = excluded.value, revision = excluded.revision, updated_at = excluded.updated_at
                    """,
                    (str(st["space_id"]), str(st["bot_id"]), str(st["value"]), int(st["revision"]), int(st["updated_at"])),
                )
                imported_styles += 1

        src_conn.close()
        total_now = self.list_entries(include_drafts=False)["count"]
        return {
            "ok": True,
            "sourceExists": True,
            "sourcePath": str(src),
            "importedEntries": imported_entries,
            "importedStyles": imported_styles,
            "totalPublishedEntries": total_now,
        }


class PersonaSwitchEngine:
    """Manages switchable personalities (`openbot-personality.js` compatible) and KB-backed replies."""

    def __init__(self, personas_file: Path, model_hub: Optional[Any] = None) -> None:
        self.personas_file = Path(personas_file)
        self.model_hub = model_hub
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        if not self.personas_file.exists():
            self.personas_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": "openbot.wechat-personas/1",
                "updatedAt": _utc_iso_now(),
                "personas": DEFAULT_PERSONAS,
            }
            self.personas_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load(self) -> Dict[str, Any]:
        self._ensure_seeded()
        try:
            data = json.loads(self.personas_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("personas"), dict):
                merged = dict(DEFAULT_PERSONAS)
                merged.update(data["personas"])
                return merged
        except Exception:
            pass
        return dict(DEFAULT_PERSONAS)

    def _save(self, personas: Dict[str, Any]) -> None:
        self.personas_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "openbot.wechat-personas/1",
            "updatedAt": _utc_iso_now(),
            "personas": personas,
        }
        self.personas_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def list_personas(self) -> Dict[str, Any]:
        personas = self._load()
        return {
            "ok": True,
            "count": len(personas),
            "personasFile": str(self.personas_file),
            "personas": list(personas.values()),
            "mbtiTypes": list(MBTI_TYPES),
            "interactionStyles": list(INTERACTION_STYLES),
        }

    def resolve_persona(
        self,
        persona_hint: Optional[str] = None,
        *,
        role: str = "friend",
        mbti: Optional[str] = None,
        interaction_style: Optional[str] = None,
    ) -> Dict[str, Any]:
        personas = self._load()
        hint = (persona_hint or "").strip()
        selected: Optional[Dict[str, Any]] = None

        if hint in personas:
            selected = dict(personas[hint])
        else:
            cf = hint.casefold()
            for p in personas.values():
                if cf and (cf == str(p.get("name", "")).casefold() or p["id"].casefold() in cf):
                    selected = dict(p)
                    break
            if selected is None:
                if any(k in hint or k in cf for k in ("数字分身", "本我", "号主", "twin", "owner")):
                    selected = dict(personas["owner-digital-twin"])
                elif "客服" in hint or "kf" in cf or role == "customer":
                    selected = dict(personas["wecom-kf-pro"])
                elif any(k in hint for k in ("技术", "架构", "研发", "Agent", "StaffDeck")) or role == "group":
                    selected = dict(personas["rpa-tech-expert"])
                elif any(k in hint for k in ("简洁", "助理", "concise")):
                    selected = dict(personas["concise-assistant"])
                else:
                    selected = dict(personas["warm-friend"])

        if mbti and mbti.strip().upper() in MBTI_TYPES:
            selected["mbti"] = mbti.strip().upper()
        if interaction_style and interaction_style.strip().lower() in INTERACTION_STYLES:
            selected["interactionStyle"] = interaction_style.strip().lower()
        selected["interactionStyleLabel"] = STYLE_LABELS.get(selected.get("interactionStyle", "supporter"), "捧场型")
        selected["styleDirective"] = STYLE_DIRECTIVES.get(selected.get("interactionStyle", "supporter"), "")
        return selected

    def upsert_persona(self, persona_data: Dict[str, Any]) -> Dict[str, Any]:
        """Persist or refresh a dynamic persona (such as synthesized owner-digital-twin)."""
        pid = str(persona_data.get("id") or "").strip()
        if not pid:
            raise ValueError("Persona id cannot be empty.")
        personas = self._load()
        base = dict(personas.get(pid) or DEFAULT_PERSONAS.get(pid) or {})
        base.update(persona_data)
        base["id"] = pid
        personas[pid] = base
        self._save(personas)
        return base

    def switch_contact_persona(
        self,
        binding_store: Any,
        target: str,
        persona_id: str,
        *,
        mbti: Optional[str] = None,
        interaction_style: Optional[str] = None,
        custom_note: str = "",
    ) -> Dict[str, Any]:
        resolved = self.resolve_persona(persona_id, mbti=mbti, interaction_style=interaction_style)
        binding = binding_store.get_binding(target)
        role = (binding or {}).get("role", "friend")
        updated = binding_store.bind_contact(
            target=binding.get("target") if binding else target,
            alias=(binding or {}).get("alias", ""),
            role=role,
            ai_persona=resolved["id"],
            scheduled_enabled=(binding or {}).get("scheduledEnabled", True),
            cron_hint=(binding or {}).get("cronHint", "0 9,21 * * *"),
            auto_reply_enabled=(binding or {}).get("autoReplyEnabled", True),
            notes=(custom_note.strip() or (binding or {}).get("notes", "")),
        )
        # Annotate MBTI / interactionStyle metadata in binding if needed
        return {
            "ok": True,
            "target": target,
            "persona": resolved,
            "binding": updated.get("binding"),
        }

    @staticmethod
    def _clean_single_line(text: str, max_len: int = 160) -> str:
        collapsed = re.sub(r"\s+", " ", (text or "").replace("\r", " ").replace("\n", " ")).strip()
        if len(collapsed) <= max_len:
            return collapsed
        return collapsed[: max_len - 1].rstrip("，、；： ") + "…"

    def generate_smart_reply(
        self,
        target: str,
        incoming_text: str,
        *,
        knowledge_store: WeChatKnowledgeStore,
        binding: Optional[Dict[str, Any]] = None,
        persona_override: Optional[str] = None,
        recent_messages: Optional[List[str]] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        model_hub: Optional[Any] = None,
        model_id: Optional[str] = None,
        use_llm: Optional[bool] = None,
    ) -> Dict[str, Any]:
        role = str((binding or {}).get("role") or "friend")
        persona_hint = persona_override or (binding or {}).get("aiPersona") or ""
        persona = self.resolve_persona(persona_hint, role=role)
        pid = persona["id"]
        owner_twin_active = pid == "owner-digital-twin"

        mem_ctx = memory_context or {}
        owner_prof = mem_ctx.get("ownerProfile") or {}
        contact_soul = mem_ctx.get("contactSoul") or {}
        memory_snippet = str(mem_ctx.get("memoryPromptSnippet") or "").strip()
        memory_refs = list(mem_ctx.get("memoryRefs") or [])

        kb_res = knowledge_store.search_context(incoming_text, external_only=True, limit=5)
        entries = kb_res.get("entries") or []
        terms_hit = [e for e in entries if e["kind"] == "terminology"]
        scripts_hit = [e for e in entries if e["kind"] == "script"]
        knowledge_hit = [e for e in entries if e["kind"] in ("knowledge", "faq")]

        norm_in = unicodedata.normalize("NFKC", incoming_text or "").strip()
        in_cf = norm_in.casefold()
        is_reply_check = any(
            kw in in_cf
            for kw in ("回复我", "回复消息", "能回复", "在吗", "在线吗", "收到吗", "看到吗", "你好你好")
        )
        is_rpa_question = any(kw in in_cf for kw in ("rpa", "爬虫", "按键精灵", "ocr", "原理", "熔断"))
        is_kf_or_handoff = any(
            kw in in_cf for kw in ("客服", "退货", "政策", "人工", "接管", "知识库", "术语", "性格", "数字婚礼")
        )

        # Build fact-grounded answer tailored strictly in tone/structure by persona
        shared_mems = (mem_ctx.get("memories") or {}).get("sharedContext") or []
        event_mems = (mem_ctx.get("memories") or {}).get("episodicEvents") or []
        shared_clue = ""
        if shared_mems:
            shared_clue = str(shared_mems[0].get("content") or "")[:36]
        elif event_mems:
            shared_clue = str(event_mems[0].get("content") or "")[:36]

        if owner_twin_active:
            owner_tone = str((owner_prof.get("speakingStyle") or {}).get("toneTag") or "简练自然")
            if is_reply_check and not is_rpa_question:
                clue_note = f"（顺带记得咱们聊过的「{shared_clue}」）" if shared_clue else ""
                reply = f"在的在的，刚看到消息～我这边实时监测一直开着呢{clue_note}，有啥直接发我就行！"
            elif entries:
                top = (scripts_hit or knowledge_hit or terms_hit)[0]
                fact_excerpt = top["body"][:82].rstrip("。；， ")
                clue_note = f"；结合咱们之前的「{shared_clue}」" if shared_clue else ""
                reply = f"这事按咱们这边经验：{fact_excerpt}{clue_note}，你要测的话我随时帮你跑一下～（本我语态：{owner_tone}）"
            else:
                clue_note = f"刚看咱们记忆库里的「{shared_clue}」，" if shared_clue else ""
                reply = f"收到「{norm_in[:24]}」啦，{clue_note}这边都记着呢，晚点直接推进！"
        elif is_reply_check and not is_rpa_question and not is_kf_or_handoff:
            if pid == "wecom-kf-pro":
                reply = (
                    "您好，我是 OpenBot 微信客服智能专员。您的消息已由后台 RealtimeMessageMonitor 实时监测捕获："
                    "1）支持自动读取会话增量与未读提醒；2）已接入本地企业知识库、专业术语词典与性格切换引擎，确保回复口径规范；"
                    "3）如涉及复杂问题可随时切换人工接管（takeover）。请随时发送您的咨询。"
                )
            elif pid == "rpa-tech-expert":
                reply = (
                    "已实时捕获并响应！当前由 OpenBot RealtimeMessageMonitor 后台守护驱动："
                    "macOS Vision OCR 增量监测 + FTS5 知识库/专业术语检索 + 多性格切换 + 3x 脏输入熔断校验，"
                    "欢迎继续发送任意技术或测试指令。"
                )
            elif pid == "concise-assistant":
                reply = "收到，后台实时监控已正常捕获你的消息，知识库、术语校验与自动回复链路全部在线，可随时继续测试。"
            else:
                # warm-friend
                reply = (
                    "哈哈收到收到！👋 我的后台实时消息监控已经秒速捕获你的消息啦～"
                    "现在还接上了微信客服知识库、专业术语库，而且支持随时切换好友/客服/技术性格呢，"
                    "不信你再问我个问题试试！✨"
                )
        elif is_rpa_question and (knowledge_hit or terms_hit):
            top = (knowledge_hit or terms_hit)[0]
            core_fact = top["body"]
            if pid == "wecom-kf-pro":
                reply = f"您好，关于「{top['title']}」，标准口径说明如下：{core_fact} 如有需要可进一步提供技术文档参考。"
            elif pid == "rpa-tech-expert":
                term_names = "、".join(t["title"].split(" (")[0] for t in terms_hit[:3]) or "Vision OCR / CGEvent"
                reply = f"结合专业术语（{term_names}）：{core_fact}"
            elif pid == "concise-assistant":
                reply = f"结论：{core_fact}"
            else:
                reply = f"嘿～简单来说区别在这：{core_fact} 是不是比纯靠死坐标靠谱多啦 😄"
        elif entries:
            top = (scripts_hit or knowledge_hit or terms_hit)[0]
            fact_excerpt = top["body"][:95].rstrip("。；， ")
            matched_term_titles = [t["title"].split(" (")[0] for t in terms_hit[:2]]
            term_badge = f"（参考术语：{'、'.join(matched_term_titles)}）" if matched_term_titles else ""
            if pid == "wecom-kf-pro":
                reply = f"您好，针对您咨询的「{norm_in[:22]}」，依据《{top['title']}》为您说明：{fact_excerpt}。{term_badge}如仍需人工核对，我可以为您标记专员接管。"
            elif pid == "rpa-tech-expert":
                reply = f"命中知识库《{top['title']}》{term_badge}：{fact_excerpt}。"
            elif pid == "concise-assistant":
                reply = f"收到（匹配《{top['title']}》）：{fact_excerpt}。"
            else:
                reply = f"收到你说的啦！我刚查了下「{top['title']}」：{fact_excerpt}～{term_badge}有需要随时继续聊呀 ✨"
        else:
            clean_in = norm_in[:28]
            recent_hint = f"（结合最近聊到的「{recent_messages[-1][:18]}」）" if recent_messages else ""
            if pid == "wecom-kf-pro":
                reply = f"您好，我已实时收到您的消息「{clean_in}」。当前知识库暂未收录该细分条款，我已为您记录并可转人工客服核对确认。"
            elif pid == "rpa-tech-expert":
                reply = f"RealtimeMonitor 已捕获来信「{clean_in}」{recent_hint}；当前 KB 未命中精确术语条目，已进入标准人工待核队列。"
            elif pid == "concise-assistant":
                reply = f"已收到「{clean_in}」，知识库暂无直接条目，已记录。"
            else:
                reply = f"收到「{clean_in}」啦！{recent_hint}我的实时监控正稳稳盯着窗口呢，你想测什么话术、术语或切换哪种性格随时告诉我～🤖"

        template_text = self._clean_single_line(reply, max_len=int(persona.get("maxChars") or 160))
        final_text = template_text
        generation_mode = "kb_template_fallback"
        model_used = None
        provider_used = None
        latency_ms = None
        llm_error = None

        hub = model_hub if model_hub is not None else self.model_hub
        should_use_llm = bool(hub is not None and (use_llm if use_llm is not None else hub.is_llm_enabled()))
        if should_use_llm:
            kb_snippets = "\n".join(
                f"- [{e['kind']}] {e['title']}: {e['body'][:180]}"
                for e in entries[:4]
            ) or "（本次来信未命中特定企业知识库条目，按角色与对话语境自然作答）"
            recent_ctx = "\n".join(f"- {m[:120]}" for m in (recent_messages or [])[-4:]) or "（暂无历史消息）"
            # 聊天历史往来（导入的旧记录 + 托管实时沉淀）注入参考，机器人"记得"之前聊过什么
            history_snippet = str((memory_context or {}).get("historyThreadSnippet") or "").strip()
            if history_snippet:
                recent_ctx = f"{recent_ctx}\n— 更早的往来（来自聊天记录）—\n{history_snippet}"
            soul_block = ""
            if owner_twin_active or memory_snippet:
                owner_style = str(owner_prof.get("digitalTwinSystemPrompt") or owner_prof.get("archetypeTag") or "")
                friend_tag = str(contact_soul.get("personalityTag") or "")
                friend_pref = str(contact_soul.get("communicationPreferences") or "")
                soul_block = (
                    f"\n号主本我画像与说话习惯：{owner_style[:260]}\n"
                    f"好友心智画像：{friend_tag} | 偏好：{friend_pref[:160]}\n"
                    f"双方长期共同记忆（facts/events/shared）：\n{memory_snippet or '（暂无）'}\n"
                )
            max_chars = int(persona.get("maxChars") or 160)
            sys_prompt = (
                f"你正在代表主人回复微信好友「{target}」的消息。\n"
                f"当前性格角色：{persona['name']}（MBTI: {persona['mbti']}，互动风格: {persona.get('interactionStyleLabel', '')}）。\n"
                f"性格设定：{persona.get('tone', '')} {persona.get('guidelines', '')}\n"
                f"互动指令：{persona.get('styleDirective', '')}\n"
                f"企业知识库与术语参考：\n{kb_snippets}{soul_block}\n"
                f"硬性要求：1) 必须符合上述人设、长期记忆与知识库事实；2) 输出单行自然口语微信回复，不要 Markdown 标题或引号；3) 字数控制在 {max_chars} 字以内。"
            )
            user_prompt = (
                f"最近聊天参考：\n{recent_ctx}\n\n"
                f"好友发来新消息：{norm_in}\n请直接给出一条微信回复："
            )
            llm_res = hub.generate_chat_reply(
                [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                model_id=model_id,
                contact_name=target,
            )
            latency_ms = llm_res.get("latencyMs")
            model_used = llm_res.get("modelId")
            provider_used = llm_res.get("providerId")
            if llm_res.get("ok") and llm_res.get("replyText"):
                final_text = self._clean_single_line(llm_res["replyText"], max_len=max_chars)
                generation_mode = "llm_magpie"
            else:
                llm_error = llm_res.get("error")

        basis = {
            "personaId": persona["id"],
            "personaName": persona["name"],
            "mbti": persona["mbti"],
            "interactionStyle": persona["interactionStyle"],
            "ownerTwinActive": owner_twin_active,
            "generationMode": generation_mode,
            "modelUsed": model_used,
            "providerUsed": provider_used,
            "latencyMs": latency_ms,
            "documentRefs": [
                {"id": e["id"], "kind": e["kind"], "title": e["title"], "revision": e["revision"]}
                for e in entries
            ],
            "memoryRefs": memory_refs[:6],
            "matchedTerms": [
                term for e in entries for term in (e.get("matchedTerms") or [])
            ][:8],
        }
        return {
            "ok": True,
            "target": target,
            "incomingText": norm_in,
            "persona": persona,
            "matchedCount": len(entries),
            "matchedEntries": entries,
            "memoryCount": len(memory_refs),
            "memoryRefs": memory_refs[:6],
            "replyText": final_text,
            "templateFallbackReply": template_text,
            "generationMode": generation_mode,
            "modelUsed": model_used,
            "providerUsed": provider_used,
            "latencyMs": latency_ms,
            "llmError": llm_error,
            "basis": basis,
        }
