"""WeChat Customer Service Knowledge Base, Domain Terminology, and Persona Switching Engine.

Aligns with OpenBot's dual-layer SQLite FTS5 knowledge architecture (`bot-knowledge.js`),
customer-service takeover/basis governance (`feishu-customer-pilot.js`), and manual
personality system (`openbot-personality.js`).
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from .io_utils import atomic_write_json

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
    "challenger": "直率核验前提与潜在风险，不迎合错误假设，给出关键反例或核查点。",
    "builder": "结论先行，条理清晰地给出核心依据与可执行建议，专业干练、不堆砌套话。",
    "neutral": "客观陈述事实、依据与边界，分点清晰、不偏不倚。",
    "supporter": "积极回应并肯定对方观点与互动细节，在此基础上补充有价值的专业延伸。",
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


_SEARCH_STOPWORDS = frozenset({
    "什么", "怎么", "怎样", "如何", "为何", "为什么",
    "可以", "能否", "能不能", "是不是", "是否",
    "这个", "那个", "这些", "那些", "这样", "那样", "这里", "那里", "这边", "那边",
    "目前", "现在", "已经", "还是", "或者", "以及", "因为", "所以", "但是", "不过", "如果", "虽然",
    "需要", "想要", "知道", "觉得", "没有", "不是", "不会", "不能",
    "我们", "你们", "他们", "大家", "自己", "一下", "看看", "请问", "帮忙",
})


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
        if cf in _SEARCH_STOPWORDS or cf in seen:
            return
        seen.add(cf)
        terms.append(clean[:40])

    # Extract ASCII/alnum words cleanly even when adjacent to Chinese characters (e.g. "为什么Agent需要")
    for ascii_tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,}", norm):
        _add(ascii_tok)

    for raw in _TERM_SPLIT_RE.split(norm):
        if len(raw) >= 2 and not re.search(r"[\u4e00-\u9fff][A-Za-z0-9]|[A-Za-z0-9][\u4e00-\u9fff]", raw):
            _add(raw)

    # Extract sliding 2-char Chinese bigrams and meaningful short Han phrases
    han_runs = re.findall(r"[\u4e00-\u9fff]+", norm)
    for run in han_runs:
        if 2 <= len(run) <= 6:
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
        "body": "标准回复要点：1. 明确告知已收到本条提问；2. 说明常见问题可即时解答，复杂问题可转人工；3. 邀请对方继续发送问题或业务咨询。",
        "customerScript": "您好，我在的～常见问题我可以即时为您解答，复杂问题也可以帮您转人工，请问有什么可以帮您？",
        "keywords": ["在吗", "在线吗", "能回复", "回复消息", "收到", "你好", "实时监控"],
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
        "id": "seed-faq-product-intro",
        "library": "shared",
        "kind": "faq",
        "title": "WaveBot 产品介绍",
        "body": "WaveBot 是一款运行在 macOS 上的微信智能客服助手：自动监听微信会话、按知识库即时回复好友咨询，支持一键托管多位好友、聊天记录导入、图片识别与语音转文字；发来的链接、文章与视频消息也能自动打开识别内容后回复，回复风格可按需切换（专业客服 / 轻松好友 / 简洁助手）。",
        "keywords": ["WaveBot", "产品", "什么产品", "功能", "能做什么", "怎么用", "机器人", "是干什么的", "链接", "网页", "文章", "视频", "看懂", "打开看"],
        "synonyms": ["智能客服", "微信助手", "自动客服"],
        "source": "openbot://faq/product-intro",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-faq-pricing",
        "library": "shared",
        "kind": "faq",
        "title": "价格与获取方式",
        "body": "WaveBot 目前在 GitHub 开源（github.com/Harzva/wechat-bot），可免费下载使用；暂无付费套餐与续费计费，如后续推出企业增值服务会在官网与公众号同步公告。",
        "keywords": ["多少钱", "收费", "价格", "免费", "费用", "优惠", "试用", "退款", "计费", "折扣", "会员", "开发票", "购买", "续费", "太贵", "便宜"],
        "synonyms": ["报价", "怎么收费", "免费版", "年付", "付款"],
        "source": "openbot://faq/pricing",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-faq-hosting-usage",
        "library": "shared",
        "kind": "faq",
        "title": "自动回复与一键托管使用方法",
        "body": "在首页「好友托管」面板勾选需要托管的好友，点「一键托管」即可：机器人只回复被托管好友的咨询，并内置防封频控保护（按小时/每日发送限额与最小回复间隔自动节流），重启后自动恢复托管状态；随时可停止托管或对单个好友转人工。",
        "keywords": ["自动回复", "托管", "一键托管", "选择好友", "监管", "开启", "怎么开", "自动恢复", "重启", "同时管", "几个好友", "停止", "防封", "封号"],
        "synonyms": ["批量托管", "托管好友", "自动回复设置"],
        "source": "openbot://faq/hosting-usage",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-faq-privacy-security",
        "library": "shared",
        "kind": "faq",
        "title": "数据安全、备份与导出说明",
        "body": "所有消息识别、知识库检索与回复生成都在本机完成，聊天记录与日志保存在本地设备不上传云端，支持按需备份与导出文章/视频内容；对外分享的代码与配置均已脱敏处理，可放心用于私域客服场景。",
        "keywords": ["数据", "安全", "隐私", "泄露", "聊天记录", "存储", "本地", "脱敏", "上传", "保密", "导出", "备份"],
        "synonyms": ["数据存在哪里", "信息安全", "数据保存"],
        "source": "openbot://faq/privacy-security",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-faq-voice-to-text",
        "library": "shared",
        "kind": "faq",
        "title": "语音消息转文字说明",
        "body": "支持语音消息转文字：收到语音后可调用微信自带「转文字」能力识别内容并据此回复；识别结果会以系统备注形式记录在聊天流中，识别不清时会请对方重发或转人工跟进。",
        "keywords": ["语音", "转文字", "语音消息", "听写", "语音识别", "转写"],
        "synonyms": ["语音转文字", "听语音"],
        "source": "openbot://faq/voice-to-text",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-faq-avatar-display",
        "library": "shared",
        "kind": "faq",
        "title": "好友头像显示说明",
        "body": "控制台对话流支持显示好友头像：从微信窗口识别好友位置后自动截取头像区域，在网页工作台的气泡对话中展示；未识别到时会显示默认占位头像，不影响回复功能。",
        "keywords": ["头像", "显示头像", "加载头像", "头像更新", "占位头像"],
        "synonyms": ["头像能显示吗", "头像不显示"],
        "source": "openbot://faq/avatar-display",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-faq-platform-requirements",
        "library": "shared",
        "kind": "faq",
        "title": "系统要求与安装更新",
        "body": "WaveBot 目前支持 macOS（建议 Apple Silicon 芯片），需授予辅助功能与屏幕录制权限；断网时基于本地知识库的回复仍可正常工作，联网大模型增强功能暂不可用；本地控制台提供 HTTP API（127.0.0.1:18788）可供其他系统对接；新版本可在 GitHub Releases 下载，覆盖安装即可完成更新，卸载时删除应用与本地日志目录即可。",
        "keywords": ["mac", "系统要求", "安装", "更新", "版本", "卸载", "下载", "windows", "苹果", "intel", "权限", "多开", "断网", "离线", "联网", "api", "对接", "接口", "集成"],
        "synonyms": ["支持mac吗", "怎么更新版本", "怎么卸载干净"],
        "source": "openbot://faq/platform-requirements",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-faq-human-service-hours",
        "library": "shared",
        "kind": "faq",
        "title": "人工客服与响应时间",
        "body": "机器人全天候在线即时回复；发送「转人工」即可转入人工队列，人工客服会在工作时间内尽快跟进复杂问题，紧急问题建议留下联系方式与问题描述以便优先处理。",
        "keywords": ["人工多久", "工作时间", "在线时间", "回复时间", "服务时间", "响应时间", "人工在线", "多久回复", "联系", "遇到问题", "找谁", "找什么人", "问题找谁"],
        "synonyms": ["什么时候回复", "客服在线吗"],
        "source": "openbot://faq/human-service-hours",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-faq-community-support",
        "library": "shared",
        "kind": "faq",
        "title": "教程文档与社区支持",
        "body": "使用教程与完整文档在 GitHub 仓库 README（github.com/Harzva/wechat-bot），历史版本与更新说明见 Releases 页面；使用问题也可以直接在本对话咨询机器人，复杂问题可随时转人工。",
        "keywords": ["有群", "群聊", "交流群", "教程", "文档", "说明书", "指南", "帮助文档", "wiki", "社区", "文档在哪", "怎么学"],
        "synonyms": ["有教程吗", "哪里有文档", "用户群"],
        "source": "openbot://faq/community-support",
        "external": True,
        "status": "published",
    },
    {
        "id": "seed-script-kf-takeover",
        "library": "shared",
        "kind": "script",
        "title": "企业客服标准接待与人工接管说明",
        "body": "标准客服口径：仅依据已发布且允许对外（external=1）的知识条目与专业术语作答；如遇未收录政策、订单争议或复杂售后，不编造承诺，立即标记人工接管（takeover）交由专员核对。",
        "customerScript": "您好，您咨询的问题我已记录，会转交人工客服为您核对确认，请稍候～",
        "keywords": ["客服", "退货", "政策", "数字婚礼", "转人工", "人工接管", "咨询", "报价"],
        "synonyms": ["售后", "工单", "企业微信客服"],
        "source": "openbot://scripts/kf-takeover",
        "external": True,
        "status": "published",
    },
]

# script 条目的 body 是给机器人看的话术要点（内部口径）；客户人设直接输出这里的话术本身
SCRIPT_CUSTOMER_TEXT: Dict[str, str] = {
    "seed-script-live-reply-ack": "您好，我在的～常见问题我可以即时为您解答，复杂问题也可以帮您转人工，请问有什么可以帮您？",
    "seed-script-kf-takeover": "您好，您咨询的问题我已记录，会转交人工客服为您核对确认，请稍候～",
}

DEFAULT_PERSONAS: Dict[str, Dict[str, Any]] = {
    "warm-friend": {
        "id": "warm-friend",
        "name": "轻松幽默好友",
        "mbti": "ENFP",
        "interactionStyle": "supporter",
        "tone": "专业可靠又不失亲和力，表达自然流畅、直击重点",
        "prefixHint": "哈哈收到啦！",
        "guidelines": "像懂技术的专业好友一样自然回话：有观点、有依据、简练清晰，不背诵生硬客服官腔。",
        "maxChars": 150,
    },
    "wecom-kf-pro": {
        "id": "wecom-kf-pro",
        "name": "微信企业客服专员",
        "mbti": "ISTJ",
        "interactionStyle": "builder",
        "tone": "礼貌专业、结构清晰、结论明确，严守事实依据与服务边界",
        "prefixHint": "您好，",
        "guidelines": "以「您好」开头，先给明确结论再分点给出准确依据或可行建议；对外部话题或技术咨询就事论事专业解答，不泄露内部实现细节。",
        "maxChars": 160,
    },
    "rpa-tech-expert": {
        "id": "rpa-tech-expert",
        "name": "OpenBot 技术架构师",
        "mbti": "INTJ",
        "interactionStyle": "builder",
        "tone": "资深技术顾问视角：结论清晰、直击技术原理与架构权衡，语言简洁干练",
        "prefixHint": "",
        "guidelines": "直接拆解核心机理、适用场景、潜在风险与安全边界，就事论事回答，避免内部调试术语或固定前缀套话。",
        "maxChars": 160,
    },
    "concise-assistant": {
        "id": "concise-assistant",
        "name": "干练高效助理",
        "mbti": "ESTJ",
        "interactionStyle": "neutral",
        "tone": "简洁明了、直击结论、不拖泥带水",
        "prefixHint": "收到：",
        "guidelines": "一句核心结论 + 1-2 个关键事实，控制在 80 字以内。",
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

            if score < 2.0:
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
            atomic_write_json(self.personas_file, payload)

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
        atomic_write_json(self.personas_file, payload)

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
                elif any(k in hint for k in ("技术", "架构", "研发", "Agent", "StaffDeck")):
                    selected = dict(personas["rpa-tech-expert"])
                elif any(k in hint for k in ("简洁", "助理", "concise")):
                    selected = dict(personas["concise-assistant"])
                elif role == "group":
                    selected = dict(personas["wecom-kf-pro"])
                elif any(k in cf for k in ("warm", "friend", "companion", "友好", "轻松")):
                    selected = dict(personas["warm-friend"])
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
        cut = collapsed[:max_len]
        for sep in ("。", "；", "！", "？"):
            idx = cut.rfind(sep)
            if idx >= max(24, int(max_len * 0.55)):
                return cut[: idx + 1]
        idx = cut.rfind("，")
        if idx >= max(24, int(max_len * 0.65)):
            return cut[:idx].rstrip("，、；： ") + "…"
        return collapsed[: max_len - 1].rstrip("，、；： ") + "…"

    @staticmethod
    def _sentence_excerpt(text: str, max_len: int = 95) -> str:
        """句界截断：优先在句末/分句标点处截断，避免半句话与 URL 被切断。"""
        t = str(text or "").strip()
        # 剥掉内部文档式元前缀（客户回复不需要"标准技术口径："这类引导语）
        t = re.sub(r"^(标准技术口径|标准回复要点|标准客服口径|技术口径|标准口径)[：:]", "", t).strip()
        if len(t) <= max_len:
            return t
        cut = t[:max_len]
        for sep in ("。", "；", "！", "？"):
            idx = cut.rfind(sep)
            if idx >= 20:
                return cut[: idx + 1]
        idx = cut.rfind("，")
        if idx >= 20:
            return cut[:idx].rstrip("，、； ") + "…"
        return cut.rstrip("，、；：： ") + "…"

    # 人性化结尾轮换池：同一客户重问时回复不同，避免内容级防重发（120s）拦截导致客户收不到答复
    _REPLY_SUFFIX_POOL: Dict[str, List[str]] = {
        "wecom-kf-pro": ["祝您生活愉快！", "期待您的下次咨询～", "祝一切顺利！"],
        "warm-friend": ["跟你聊超开心！", "随时来找我玩呀～", "比心 ❤️"],
        "concise-assistant": ["完毕。", "待命中。"],
    }

    def _vary_reply(self, text: str, pid: str, max_chars: int = 160) -> str:
        """为模板回复追加轮换结尾（已在原文出现则跳过），保证重问时内容有变化。"""
        pool = self._REPLY_SUFFIX_POOL.get(pid)
        if not pool or not text:
            return text
        suffix = random.choice(pool)
        base = text.rstrip("。！？～… ")
        if not base or suffix in text or base.endswith(suffix[:6]):
            return text
        budget = max(20, int(max_chars) - len(suffix) - 2)
        if len(base) > budget:
            base = self._clean_single_line(base, budget)
        return f"{base}。{suffix}" if base[-1] not in "。！？～…" else f"{base}{suffix}"

    # 内部术语（客户看不懂）：LLM 模仿知识库技术条目时可能外泄，出口统一温和改写为面向用户的自然表述
    _INTERNAL_JARGON_RE = re.compile(
        r"(FTS5|AXUIElement|熔断|读回|Takeover|3x\b|prompt|system prompt|RealtimeMessageMonitor|RealtimeMonitor|preview_reply|脏输入|CGWindow|VNRecognize|CGEvent|零注入)",
        re.IGNORECASE,
    )
    _JARGON_REPLACEMENTS: Tuple[Tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"RealtimeMessageMonitor|RealtimeMonitor", re.I), "实时巡检"),
        (re.compile(r"VNRecognize\w*|Vision\s*OCR", re.I), "图文识别"),
        (re.compile(r"CGWindow\w*", re.I), "窗口截图"),
        (re.compile(r"CGEvent\w*", re.I), "界面操作"),
        (re.compile(r"AXUIElement", re.I), "界面组件"),
        (re.compile(r"preview_reply", re.I), "回复预览"),
        (re.compile(r"FTS5", re.I), "知识库"),
        (re.compile(r"\bsystem\s+prompt\b|\bprompt\b", re.I), "提示词"),
        (re.compile(r"\btakeover\b", re.I), "人工接管"),
        (re.compile(r"3\s*x\s*(?:读回|校验|熔断)|\b3x\b", re.I), "多重校验"),
        (re.compile(r"脏输入", re.I), "异常输入"),
        (re.compile(r"零注入", re.I), "非侵入式安全"),
        (re.compile(r"读回", re.I), "校验"),
        (re.compile(r"熔断", re.I), "安全拦截"),
    )

    def sanitize_for_customer(self, text: str, max_len: int = 160) -> str:
        """客户出口净化：内部术语 → 自然易懂的专业表述；去除机械调试前缀。"""
        cleaned = str(text or "").strip()
        if not cleaned:
            return cleaned
        rewritten = re.sub(
            r"已捕获关键词[^\u4e00-\u9fa5]*[，,；]?\s*",
            "",
            cleaned,
        )
        rewritten = re.sub(r"但我只能暂判为[^。；]+[。；]?", "", rewritten)
        rewritten = rewritten.replace("OCR 噪声偏大", "内容识别不太清晰")
        for pat, repl in self._JARGON_REPLACEMENTS:
            rewritten = pat.sub(repl, rewritten)
        rewritten = re.sub(r"(知识库|校验|多重校验|实时巡检|提示词)\s*\1+", r"\1", rewritten)
        rewritten = re.sub(r"(?:前置条件|信源标识)[：:]?\s*", "", rewritten)
        rewritten = re.sub(r"(?:未触发可执行任务|无法定位可执行任务|仅名称无法定位具体条目)[，,；;。]?", "", rewritten)
        rewritten = re.sub(r"已捕获关键词[^。；]+[。；]?", "", rewritten)
        rewritten = re.sub(r"无法可靠[^一-龥，。]*[。；]?", "这条我需要更多信息才能帮到你。", rewritten)
        rewritten = re.sub(r"\s*([，,。；;！!？?])", r"\1", rewritten)
        rewritten = re.sub(r"^[，,；;。:\s]+", "", rewritten)
        # 最终兜底：仅当仍有未替换的内部术语时才触发通用回复
        if self._INTERNAL_JARGON_RE.search(rewritten):
            rewritten = "这条消息我还在学习中，已转交人工客服为您详细解答～"
        return self._clean_single_line(rewritten, max_len)

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

        norm_in = unicodedata.normalize("NFKC", incoming_text or "").strip()
        in_cf = norm_in.casefold()
        kb_res = knowledge_store.search_context(incoming_text, external_only=True, limit=5)
        raw_entries = kb_res.get("entries") or []
        has_url = bool(re.search(r"(?:https?://|github\.com/)", in_cf))
        mentions_self_product = any(
            k in in_cf for k in ("wavebot", "harzva/wechat-bot", "yobot", "微信客服", "自动回复", "托管")
        )
        is_external_link = has_url and not mentions_self_product
        ai_media_insight = next(
            (str(m).strip() for m in reversed(recent_messages or []) if str(m or "").strip().startswith(("[元宝深读:", "[小微深读:"))),
            "",
        )
        has_explicit_media_ref = any(
            phrase in in_cf
            for phrase in ("这条视频", "这个视频", "刚才发的", "上面发的", "发的文章", "发的视频", "发的链接", "这篇文章", "那篇文章")
        )
        is_media_followup = (
            (
                (
                    bool(ai_media_insight)
                    and any(kw in in_cf for kw in ("视频", "文章", "链接", "卡片", "讲了", "总结", "要点", "分享", "内容"))
                )
                or has_explicit_media_ref
            )
            and not any(kw in in_cf for kw in ("wavebot", "openbot", "定价", "多少钱", "退款", "部署", "安装", "托管", "微信客服"))
        )
        entries = (
            [
                e
                for e in raw_entries
                if not str(e.get("id") or "").startswith("seed-") and float(e.get("score") or 0.0) >= 8.0
            ]
            if (is_external_link or is_media_followup)
            else raw_entries
        )
        terms_hit = [e for e in entries if e["kind"] == "terminology"]
        scripts_hit = [e for e in entries if e["kind"] == "script"]
        knowledge_hit = [e for e in entries if e["kind"] in ("knowledge", "faq")]
        # 空/纯标点消息早退：不走 KB 检索，避免误命中内部术语条目
        _substantive = re.sub(r"[\s。，．,．.！!？?～~、…·•\-_=]+", "", norm_in)
        if not _substantive:
            if pid == "concise-assistant":
                reply = "您的消息好像没发完整，请再发一次。"
            elif pid == "warm-friend":
                reply = "咦，这条好像只有表情或标点～麻烦把想问的再发一次哈 🙂"
            elif pid == "rpa-tech-expert":
                reply = "EmptyInput: 未检测到有效内容，请重新发送测试文本。"
            else:
                reply = "您好，您的消息好像没发完整～麻烦再发一次，我看到后会立即为您解答。"
            template_text = self._clean_single_line(reply, max_len=int(persona.get("maxChars") or 160))
            return {
                "ok": True,
                "target": target,
                "incomingText": norm_in,
                "persona": persona,
                "matchedCount": 0,
                "matchedEntries": [],
                "memoryCount": 0,
                "memoryRefs": [],
                "templateFallbackReply": template_text,
                "replyText": template_text,
                "generationMode": "empty_input_guard",
                "modelUsed": None,
                "providerUsed": None,
                "latencyMs": None,
                "llmError": None,
                "basis": {"personaId": persona["id"], "personaName": persona["name"],
                          "generationMode": "empty_input_guard"},
            }
        is_reply_check = any(
            kw in in_cf
            for kw in ("回复我", "回复消息", "能回复", "在吗", "在线吗", "收到吗", "看到吗", "你好你好")
        )
        is_rpa_question = any(kw in in_cf for kw in ("rpa", "爬虫", "按键精灵", "ocr", "原理", "熔断"))
        is_kf_or_handoff = any(
            kw in in_cf for kw in ("客服", "退货", "政策", "人工", "接管", "知识库", "术语", "性格", "数字婚礼")
        )
        # 显式转人工意图：无论 KB 是否命中，优先给出转接话术（与 realtime_monitor 手动接管检测对齐）
        _handoff_kw = ("转人工", "转接人工", "人工客服", "找人工", "人工服务", "找真人", "真人客服", "真人",
                       "人工接管", "人工在线", "找主管", "你们主管", "找经理", "找负责人", "要投诉",
                       "transfer to human", "human agent", "real person")
        is_explicit_handoff = any(kw in in_cf for kw in _handoff_kw)

        card_m = re.match(r"^(?:[CVWXYMcvwxym]\s+(\S.*)|([◎•·∞♡〇])\s*(\S.*))$", norm_in)
        is_card_source_only = bool(card_m) and len(norm_in) <= 24 and "?" not in norm_in and "？" not in norm_in

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
                top = entries[0]  # 按检索分数取最高，避免 script 条目硬优先导致答非所问
                fact_excerpt = self._sentence_excerpt(top["body"], 82).rstrip("。；， ")
                clue_note = f"；结合咱们之前的「{shared_clue}」" if shared_clue else ""
                reply = f"这事按咱们这边经验：{fact_excerpt}{clue_note}，你要测的话我随时帮你跑一下～（本我语态：{owner_tone}）"
            else:
                clue_note = f"刚看咱们记忆库里的「{shared_clue}」，" if shared_clue else ""
                reply = f"收到「{norm_in[:24]}」啦，{clue_note}这边都记着呢，晚点直接推进！"
        elif is_reply_check and not is_rpa_question and not is_kf_or_handoff:
            if pid == "wecom-kf-pro":
                reply = (
                    "您好，我是微信客服智能助手，您的消息我已收到～"
                    "产品使用、活动规则、常见问题我都可以即时为您解答；"
                    "如遇复杂问题，也可以随时让我为您转接人工客服。请问有什么可以帮您？"
                )
            elif pid == "rpa-tech-expert":
                reply = (
                    "收到，消息已确认。我可以协助解答自动化工具对比、使用场景与技术方案类问题，"
                    "欢迎直接描述你的需求或继续发送测试指令。"
                )
            elif pid == "concise-assistant":
                reply = "收到，我在线。有问题请直接说。"
            else:
                # warm-friend
                reply = (
                    "哈哈收到收到！👋 你的消息我秒回啦～常见问题我都能答，"
                    "解决不了也会帮你转人工，别客气尽管问！✨"
                )
        elif is_rpa_question and (knowledge_hit or terms_hit):
            top = (knowledge_hit or terms_hit)[0]
            core_fact = re.sub(r"^(标准技术口径|标准回复要点|标准客服口径|技术口径|标准口径)[：:]", "", str(top["body"])).strip()
            if pid == "wecom-kf-pro":
                reply = f"您好，关于「{top['title']}」，为您说明：{core_fact} 如有需要可进一步提供技术文档参考。"
            elif pid == "rpa-tech-expert":
                term_names = "、".join(t["title"].split(" (")[0] for t in terms_hit[:3]) or "Vision OCR / CGEvent"
                reply = f"结合专业术语（{term_names}）：{core_fact}"
            elif pid == "concise-assistant":
                reply = f"结论：{core_fact}"
            else:
                reply = f"嘿～简单来说区别在这：{core_fact} 是不是比纯靠死坐标靠谱多啦 😄"
        elif is_card_source_only:
            card_name = (card_m.group(1) or card_m.group(3) or norm_in).strip()
            ai_insight = next(
                (str(m).strip() for m in reversed(recent_messages or []) if str(m or "").strip().startswith(("[元宝深读:", "[小微深读:"))),
                "",
            )
            if ai_insight:
                ai_body = ai_insight.split("]", 1)[-1].strip()
                reply = f"您好，关于「{card_name}」的内容卡片，已结合助手解析为您梳理要点：{ai_body[:105]}"
            else:
                reply = f"您好，看到您分享了「{card_name}」的内容卡片；目前仅能看到来源标题，方便贴一下具体链接或想交流的问题，我帮您进一步梳理分析。"
        elif is_explicit_handoff:
            # 显式转人工意图优先于 KB 命中（包括英文 transfer to human）
            if pid == "wecom-kf-pro":
                reply = "好的，已为您标记转接人工客服，专员会尽快跟进您的问题，请稍候～"
            elif pid == "rpa-tech-expert":
                reply = "已收到转人工请求，已转交人工团队为您跟进处理，请稍候。"
            elif pid == "concise-assistant":
                reply = "已转人工，请稍候。"
            else:
                reply = "收到！马上帮你转人工，专员看到消息就会回复你哒～稍等一下哈 🙂"
        elif entries:
            top = entries[0]  # 按检索分数取最高，避免 script 条目硬优先导致答非所问
            # script 条目的 body 是话术要点（给机器人看的口径），客户人设直接输出话术本身
            cs = SCRIPT_CUSTOMER_TEXT.get(str(top.get("id") or "")) or top.get("customerScript")
            if str(top.get("kind")) == "script" and cs and pid != "rpa-tech-expert":
                cs = str(cs)
                reply = cs if pid == "concise-assistant" else (cs + " 有啥尽管问哈～" if pid == "warm-friend" else cs)
            else:
                fact_excerpt = self._sentence_excerpt(top["body"], 95)
                matched_term_titles = [t["title"].split(" (")[0] for t in terms_hit[:2]]
                term_badge = f"（参考术语：{'、'.join(matched_term_titles)}）" if matched_term_titles else ""
                if pid == "wecom-kf-pro":
                    if fact_excerpt.endswith("…"):
                        # 摘要以省略号收尾（长条目压缩）时不再硬接尾巴
                        reply = f"您好，针对您咨询的「{norm_in[:22]}」，为您说明：{fact_excerpt}更多细节欢迎随时问我～"
                    else:
                        reply = f"您好，针对您咨询的「{norm_in[:22]}」，为您说明：{fact_excerpt}如仍需人工核对，我可以为您转接人工客服。"
                elif pid == "rpa-tech-expert":
                    reply = f"命中知识库《{top['title']}》{term_badge}：{fact_excerpt}" + ("" if fact_excerpt.endswith(("。", "！", "？", "…")) else "。")
                elif pid == "concise-assistant":
                    reply = f"收到（匹配《{top['title']}》）：{fact_excerpt}" + ("" if fact_excerpt.endswith(("。", "！", "？", "…")) else "。")
                else:
                    reply = f"收到你说的啦！我刚查了下「{top['title']}」：{fact_excerpt}{term_badge}有需要随时继续聊呀 ✨"
        else:
            clean_in = norm_in[:28]
            recent_hint = f"（结合最近聊到的「{recent_messages[-1][:18]}」）" if recent_messages else ""
            if is_explicit_handoff:
                if pid == "wecom-kf-pro":
                    reply = "好的，已为您标记转接人工客服，专员会尽快跟进您的问题，请稍候～"
                elif pid == "rpa-tech-expert":
                    reply = f"已收到「{clean_in}」的转人工请求{recent_hint}，已转交人工团队处理。"
                elif pid == "concise-assistant":
                    reply = "已转人工，请稍候。"
                else:
                    reply = "收到！马上帮你转人工，专员看到消息就会回复你哒～稍等一下哈 🙂"
            elif pid == "wecom-kf-pro":
                ai_insight = next(
                    (str(m).strip() for m in reversed(recent_messages or []) if str(m or "").strip().startswith(("[元宝深读:", "[小微深读:"))),
                    "",
                )
                if ai_insight and any(kw in norm_in for kw in ("视频", "文章", "链接", "卡片", "讲了", "什么", "总结", "要点", "分享")):
                    ai_body = ai_insight.split("]", 1)[-1].strip()
                    reply = f"结合已解析的内容要点，为您说明：{ai_body[:120]}"
                elif is_media_followup:
                    reply = f"您好，已收到您的消息「{clean_in}」；当前尚未读取到该文章或视频的完整正文，方便贴一下原文链接或点击「@元宝 解析 / 转发小微」，我立即为您梳理核心要点。"
                else:
                    reply = f"您好，我已实时收到您的消息「{clean_in}」。当前知识库暂未收录该细分条款，我已为您记录并可转人工客服核对确认。"
            elif pid == "rpa-tech-expert":
                reply = f"关于「{clean_in}」{recent_hint}，我已记录要点；如有具体文档、链接或报错细节可继续发我，也可以为您转交人工跟进。"
            elif pid == "concise-assistant":
                reply = f"已收到「{clean_in}」，知识库暂无直接条目，已记录。"
            else:
                reply = f"收到「{clean_in}」啦！{recent_hint}有什么想继续探讨的细节、文档或问题随时发我就行～"

        # 人性化变化：同一客户重问时回复不同，防止 120s 内容级防重发把第二次答复拦掉
        if pid != "rpa-tech-expert" and not is_explicit_handoff:
            reply = self._vary_reply(str(reply), pid, max_chars=int(persona.get("maxChars") or 160))
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
            ) or "（本次来信未命中特定企业知识库条目，按专业常识与当前对话语境直接作答）"
            chat_lines: List[str] = []
            media_notes: List[str] = []
            for m in (recent_messages or []):
                s_m = str(m or "").strip()
                if not s_m:
                    continue
                if s_m.startswith(("[元宝深读:", "[小微深读:", "[链接深读:", "[图片识别:", "[视频识别:", "[识别指令:")):
                    media_notes.append(f"- {s_m[:420]}")
                else:
                    chat_lines.append(f"- {s_m[:160]}")
            recent_ctx = "\n".join(chat_lines[-5:]) or "（暂无历史消息）"
            media_block = ("\n深读解析上下文（已提取的链接/图文/视频事实）：\n" + "\n".join(media_notes[:3]) + "\n") if media_notes else ""
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
            target_chars = max(60, max_chars - 12)
            speaker = str((memory_context or {}).get("groupSpeaker") or "").strip()
            speaker_hint = f"群内发言人：{speaker}\n" if speaker else ""
            card_hint = "\n提示：对方仅发来了公众号/视频号来源卡片标题，请礼貌说明目前仅能看到标题，并邀请对方补充原文链接或想讨论的具体问题。\n" if is_card_source_only else ""
            sys_prompt = (
                f"你正在代表号主通过微信与「{target}」专业沟通。\n"
                f"当前性格角色：{persona['name']}（MBTI: {persona['mbti']}，互动风格: {persona.get('interactionStyleLabel', '')}）。\n"
                f"角色定位与要求：{persona.get('tone', '')} {persona.get('guidelines', '')}\n"
                f"表达原则：{persona.get('styleDirective', '')}\n"
                f"企业知识库与术语参考（仅在对方确实咨询我们的产品、定价、功能、权限或服务政策时引用；若对方询问通用技术原理、行业问题或分享第三方 GitHub/文章/视频，请直接就事论事给出专业解答或点评，切勿生硬推销或强行附加无关产品链接）：\n{kb_snippets}"
                f"{media_block}{soul_block}{card_hint}\n"
                "高质量专业回复标准：\n"
                "1) 结论清晰、信息密度高：先给出明确判断或核心结论，再补充 1-2 条关键依据、机制拆解或可执行建议。\n"
                "2) 若「深读解析上下文」已有识别结论，优先紧扣其中的具体项目/观点作答。\n"
                "3) 面向真实客户/好友输出自然流畅、不亢不卑的中文单行文本，严禁出现内部模块或调试词汇（如 FTS5、AXUIElement、RealtimeMessageMonitor、127.0.0.1:18788、信源标识、未触发可执行任务、前置条件），不要 Markdown 标题或多余引号。\n"
                f"4) 必须完整收尾，总字数严格控制在 {target_chars} 字以内（上限 {max_chars} 字），避免半句话被截断。"
            )
            user_prompt = (
                f"{speaker_hint}最近聊天参考：\n{recent_ctx}\n\n"
                f"对方发来新消息：{norm_in}\n请直接给出一条专业、自然、直击要点的微信回复："
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
        # 对所有客户向人设与 LLM 实发回复统一执行客户出口术语净化与句界规整
        if generation_mode == "llm_magpie" or str(persona.get("id") or "") != "rpa-tech-expert":
            final_text = self.sanitize_for_customer(final_text, max_len=int(persona.get("maxChars") or 160))
        return {
            "ok": True,
            "target": target,
            "incomingText": norm_in,
            "persona": persona,
            "matchedCount": len(entries),
            "matchedEntries": entries,
            "memoryCount": len(memory_refs),
            "memoryRefs": memory_refs[:6],
            "templateFallbackReply": template_text,
            "replyText": final_text,
            "generationMode": generation_mode,
            "modelUsed": model_used,
            "providerUsed": provider_used,
            "latencyMs": latency_ms,
            "llmError": llm_error,
            "basis": basis,
        }
