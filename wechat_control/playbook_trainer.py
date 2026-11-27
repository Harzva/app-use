"""Zero-FDE self-training playbook synthesis, PII redaction, and draft gating engine."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .io_utils import atomic_write_json
from .knowledge_kf_engine import _SECRET_RE, WeChatKnowledgeStore, _guard_secrets

# ---------------------------------------------------------------------------
# PII & Secret Redaction
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])")
_CN_MOBILE_RE = re.compile(r"(?:\+?86[\s-]?)?(?<!\d)1[3-9]\d(?:[\s-]?\d{4}){2}(?!\d)")
_CN_ID18_RE = re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")
_CN_ID_GENERIC_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)(?:\d{4}[\s-]){3}\d{3,7}(?!\d)|(?<!\d)\d{16,19}(?!\d)")
_WXID_RE = re.compile(r"(?<![A-Za-z0-9_-])wxid_[A-Za-z0-9_-]{5,}(?![A-Za-z0-9_-])", re.IGNORECASE)
_WECHAT_ID_CTX_RE = re.compile(
    r"((?:微信号?|wx|vx|V信|加我微信)\s*[:：]?\s*)([A-Za-z][A-Za-z0-9_-]{4,19})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_ADDRESS_FULL_RE = re.compile(
    r"(?:[\u4e00-\u9fff]{2,6}(?:省|市|区|县|镇|乡)){1,3}"
    r"[\u4e00-\u9fff0-9A-Za-z\-]{1,18}"
    r"(?:路|街|大道|巷|弄|胡同|园区|大厦|广场|小区|花园|村)"
    r"[\u4e00-\u9fff0-9A-Za-z\-]{0,20}"
    r"(?:\d+号(?:楼|院|栋|幢|座)?|\d+栋|\d+单元|\d+室|\d+楼|\d+层|号楼)+"
    r"[\u4e00-\u9fff0-9A-Za-z\-]{0,12}"
)
_ADDRESS_LOCAL_RE = re.compile(
    r"[\u4e00-\u9fff0-9]{2,14}(?:路|街|大道|巷|弄|小区|花园|大厦|园区)"
    r"(?:\d+号(?:楼|院|栋|幢|座)?|\d+栋|\d+单元|\d+室|\d+楼|\d+层){1,4}"
)

# ---------------------------------------------------------------------------
# Segmentation, Noise & Scoring Constants
# ---------------------------------------------------------------------------

_SMALL_TALK_EXACT: frozenset[str] = frozenset({
    "在吗", "在不在", "在嘛", "你好", "您好", "嗨", "哈喽", "hello", "hi",
    "好的", "好滴", "好哒", "好嘞", "好", "行", "可以", "收到", "嗯", "嗯嗯",
    "哦", "哦哦", "了解", "知道了", "明白", "谢谢", "感谢", "多谢", "不客气",
    "ok", "okay", "1", "666", "哈哈", "哈哈哈", "呵呵", "再见", "拜拜",
})

_REJECTION_MARKERS: Tuple[str, ...] = (
    "不需要", "不用了", "算了", "不感兴趣", "没兴趣", "别发了", "别联系",
    "不考虑", "不买了", "不合作", "已找别家", "已经买了", "太贵了不考虑",
    "拉黑", "打扰了", "退钱", "投诉", "骗子", "滚", "烦不烦",
)

_UNHELPFUL_REPLY_EXACT: frozenset[str] = frozenset({
    "不知道", "不清楚", "自己看", "随便", "没空", "不晓得",
})

_SALES_PROGRESSION_SIGNALS: Tuple[str, ...] = (
    "询价", "报价", "价格", "多少钱", "预算", "方案", "合同", "试用",
    "演示", "案例", "下单", "付款", "开票", "发货", "交付", "售后",
    "优惠", "对比", "效果", "合作", "预约", "买", "标准版", "进阶版",
    "周期", "需求", "痛点", "场景", "团队", "配置", "维护", "服务",
)

_POSITIVE_FOLLOWUP_MARKERS: Tuple[str, ...] = (
    "可以", "行", "好的", "发我", "发来看看", "怎么买", "什么时候",
    "约个时间", "安排", "合同", "开票", "打款", "下单", "试试",
    "演示", "了解", "不错", "发资料", "试用", "细聊", "加你",
    "地址", "付款", "链接", "标准版", "进阶版", "太好了", "挺好",
)

_EMOJI_BRACKET_RE = re.compile(r"\[[\u4e00-\u9fffA-Za-z0-9_]{1,8}\]")
_PUNCT_ONLY_RE = re.compile(r"^[\W_]+$")

# ---------------------------------------------------------------------------
# Statistical Vocabulary Mining Constants
# ---------------------------------------------------------------------------

_VOCAB_STOPWORDS: frozenset[str] = frozenset({
    "我们", "你们", "他们", "自己", "大家", "什么", "怎么", "怎样", "如何",
    "为什么", "这个", "那个", "这些", "那些", "这样", "那样", "这里", "那里",
    "这边", "那边", "可以", "能否", "是不是", "是否", "没有", "不是", "不会",
    "不能", "就是", "还是", "或者", "以及", "因为", "所以", "但是", "不过",
    "如果", "虽然", "然后", "而且", "并且", "已经", "现在", "目前", "之前",
    "之后", "以后", "今天", "明天", "昨天", "一下", "看看", "请问", "麻烦",
    "需要", "想要", "觉得", "知道", "比较", "非常", "应该", "可能", "大概",
    "您好", "你好", "谢谢", "感谢", "好的", "收到", "嗯嗯", "明白", "了解",
    "有些", "有点", "一些", "很多", "多少", "几个", "一个", "一样", "一直",
    "的话", "时候", "东西", "问题", "地方", "方面", "情况", "意思",
})

_EDGE_FUNCTION_CHARS: frozenset[str] = frozenset(
    "的了着过吗呢吧啊呀哦嘛和与在把被给对向从是有不这那也都就才会能要去来很太更最"
)

_DOMAIN_CONTEXT_HINTS: Tuple[str, ...] = (
    "方案", "套餐", "型号", "系列", "版本", "礼盒", "服务", "系统", "产品",
    "定制", "报价", "支持", "包含", "交付", "部署", "体验", "试用", "企业",
)

_SKU_MODEL_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"[A-Za-z]{1,6}[-_]?\d{1,5}[A-Za-z0-9-]*"
    r"|[A-Za-z0-9]{1,10}(?:Pro|Max|Plus|Lite|Mini|Ultra|Air|SE)"
    r"|SKU[-_]?[A-Za-z0-9]+"
    r")(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Hard Risk Gating Patterns
# ---------------------------------------------------------------------------

_RISK_RULES: Tuple[Tuple[str, re.Pattern[str], str], ...] = (
    (
        "specific_price",
        re.compile(
            r"(?:¥|￥|\$)\s*\d+(?:\.\d+)?|"
            r"\d+(?:\.\d+)?\s*(?:元|块钱|块|万|千元|千|rmb|cny)|"
            r"(?:报价|单价|价格|收费|一共|仅需|到手价)\s*[:：]?\s*\d+",
            re.IGNORECASE,
        ),
        "包含具体金额或数字报价，需人工核价确认",
    ),
    (
        "discount",
        re.compile(r"打?\d+(?:\.\d+)?折|打折|折扣|优惠券?|立减|减免|特价|底价|降价|让利|返现|满减|代金券"),
        "包含折扣或让利条款，需人工审批",
    ),
    (
        "refund_return",
        re.compile(r"退款|退货|退费|退钱|赔付|赔偿|违约金|包退|无理由退|全额退"),
        "涉及退款、退货或赔付承诺，需人工把关",
    ),
    (
        "delivery_deadline",
        re.compile(
            r"\d+\s*(?:天|小时|周|个月|工作日).{0,6}(?:交付|上线|发货|到达|完成|搞定|送达)|"
            r"(?:保证|承诺).{0,6}(?:天|周|月|内).{0,4}(?:交付|发货|上线)|"
            r"当天发货|必达|最晚\d+"
        ),
        "包含具体交付时限承诺，需人工确认排期",
    ),
    (
        "freebie",
        re.compile(r"免费送|白送|赠送|免费试用|免费开通|附赠|买一送一|加赠|免单"),
        "包含免费赠送或白嫖权益，需人工审批",
    ),
    (
        "exaggerated_claim",
        re.compile(r"100%|百分之百|绝对|一定能|保证效果|包治|稳赚|零风险|全网最低|唯一|永久|包过|肯定能成|绝对有效"),
        "包含绝对化或夸大效果表述，需人工合规复核",
    ),
)

# ---------------------------------------------------------------------------
# Stage & Intent Mapping
# ---------------------------------------------------------------------------

_STAGE_RULES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("高风险转人工", "售后投诉与高风险处理", ("退款", "退货", "投诉", "纠纷", "赔付", "赔偿", "违约", "差评")),
    ("已报价", "报价异议与投入产出沟通", ("太贵", "优惠", "打折", "便宜", "报价", "多少钱", "预算", "价格", "费用", "收费")),
    ("方案推进", "方案推进与决策签约", ("合同", "签约", "开票", "付款", "打款", "下单", "老板", "合伙人", "审批", "确认单")),
    ("深入沟通", "试用案例与竞品细节澄清", ("试用", "演示", "案例", "竞品", "对比", "交付", "周期", "上线", "考虑一下", "效果")),
    ("已成交", "成交交接与售后复购", ("已付款", "收到货", "开通", "发货", "物流", "续费", "复购", "上手")),
    ("暂缓", "沉默暂缓客户激活", ("再说", "下个月", "过阵子", "忙完", "暂时不")),
    ("初步接触", "需求诊断与场景了解", ("需求", "场景", "怎么用", "支持什么", "适合", "规模", "人数", "定制")),
    ("沟通中", "方案介绍与价值匹配", ("方案", "功能", "特点", "优势", "怎么解决", "核心", "服务")),
    ("新线索", "首次破冰与开场沟通", ("加好友", "刚通过", "认识", "了解下", "咨询一下")),
)


def _parse_ts(raw: Any) -> Optional[float]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        iso = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$", text)
    if m:
        year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
        sec = int(m.group(6) or 0)
        return datetime(year, month, day, hour, minute, sec, tzinfo=timezone.utc).timestamp()
    return None


def _strip_noise_for_check(text: str) -> str:
    cleaned = unicodedata.normalize("NFKC", str(text or "")).strip()
    cleaned = _EMOJI_BRACKET_RE.sub("", cleaned)
    cleaned = re.sub(r"[\s,，。！!？?~～.、]+", "", cleaned)
    return cleaned.casefold()


def _is_pure_small_talk_or_noise(text: str) -> bool:
    raw = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not raw:
        return True
    without_emoji = _EMOJI_BRACKET_RE.sub("", raw).strip()
    if not without_emoji or _PUNCT_ONLY_RE.match(without_emoji):
        return True
    # Filter pure Unicode emoji characters without alphanumeric/Han content
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", without_emoji):
        return True
    compact = _strip_noise_for_check(raw)
    if not compact:
        return True
    if compact in _SMALL_TALK_EXACT:
        return True
    return len(compact) <= 1 and not compact.isdigit()


def _char_bigrams(text: str) -> set[str]:
    clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", unicodedata.normalize("NFKC", text or "").casefold())
    if len(clean) < 2:
        return {clean} if clean else set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / float(len(a | b))


def _classify_stage_and_intent(ask: str, reply: str) -> Tuple[str, str]:
    blob = f"{ask}\n{reply}"
    for stage, intent, keywords in _STAGE_RULES:
        if any(kw in blob for kw in keywords):
            return stage, intent
    return "沟通中", "常规业务咨询与价值沟通"


def _infer_owner_style(conversations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract lightweight owner speaking habits (sentence length, addressing, catchphrases)."""
    self_texts: List[str] = []
    for conv in conversations or ():
        for rec in conv.get("records") or ():
            if rec.get("direction") == "self":
                txt = str(rec.get("text") or "").strip()
                if txt:
                    self_texts.append(txt)

    if not self_texts:
        return {
            "avgSentenceLength": 24,
            "addressing": "您好",
            "catchphrases": [],
        }

    avg_len = round(sum(len(t) for t in self_texts) / len(self_texts), 1)
    blob = "\n".join(self_texts)
    addressing = "您好"
    for cand in ("老板", "哥", "姐", "老师", "朋友", "您好"):
        if cand in blob:
            addressing = cand
            break

    phrase_counts: Counter[str] = Counter()
    for txt in self_texts:
        for cand in ("没问题", "放心", "这边", "给您", "先看下", "安排", "欢迎"):
            if cand in txt:
                phrase_counts[cand] += 1
    catchphrases = [p for p, c in phrase_counts.most_common(3) if c >= 2]
    return {
        "avgSentenceLength": avg_len,
        "addressing": addressing,
        "catchphrases": catchphrases,
    }


def _evaluate_risk_flags(texts: Iterable[str]) -> List[str]:
    blob = "\n".join(str(t or "") for t in texts if t)
    flags: List[str] = []
    for flag_name, pattern, _reason in _RISK_RULES:
        if pattern.search(blob):
            flags.append(flag_name)
    return flags


def _apply_owner_style(
    script_text: str,
    owner_style: Optional[Dict[str, Any]],
) -> str:
    style = owner_style or {}
    clean = str(script_text or "").strip()
    if not clean:
        return ""
    addressing = str(style.get("addressing") or "").strip()
    catchphrases = [str(c).strip() for c in (style.get("catchphrases") or []) if str(c).strip()]

    result = clean
    if addressing and addressing not in result[:8]:
        if result.startswith("您好"):
            if addressing != "您好":
                result = f"{addressing}{result}"
        else:
            result = f"{addressing}，{result}"

    if catchphrases:
        cp = catchphrases[0]
        if cp not in result and len(result) < 120:
            result = f"{result.rstrip('。！!')}，{cp}。"

    avg_len = style.get("avgSentenceLength")
    try:
        if avg_len is not None and float(avg_len) <= 22 and len(result) > 95:
            sentences = [s.strip() for s in re.split(r"[。！？!?]+", result) if s.strip()]
            if len(sentences) >= 2:
                result = "。".join(sentences[:2]) + "。"
    except (TypeError, ValueError):
        pass
    return result


def _extract_json_block(raw_text: str) -> Any:
    text = str(raw_text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


class SelfTrainingPlaybookEngine:
    """Offline-capable pipeline to turn WeChat sales conversations into governed playbooks."""

    def redact_pii(
        self,
        text: str,
        *,
        customer_names: Iterable[str] = (),
    ) -> str:
        """Mask phone numbers, IDs, bank cards, emails, WeChat IDs, addresses, and customer names."""
        out = str(text or "")
        if not out:
            return ""

        # Mask any private keys or API secrets first so knowledge_store._guard_secrets never trips.
        out = _SECRET_RE.sub("{密钥}", out)
        out = _EMAIL_RE.sub("{邮箱}", out)
        out = _WXID_RE.sub("{微信号}", out)
        out = _WECHAT_ID_CTX_RE.sub(r"\1{微信号}", out)
        out = _CN_ID18_RE.sub("{身份证号}", out)
        out = _CN_ID_GENERIC_RE.sub("{身份证号}", out)
        out = _CN_MOBILE_RE.sub("{手机号}", out)
        out = _BANK_CARD_RE.sub("{银行卡号}", out)
        out = _ADDRESS_FULL_RE.sub("{地址}", out)
        out = _ADDRESS_LOCAL_RE.sub("{地址}", out)

        cleaned_names = sorted(
            {str(n).strip() for n in customer_names if str(n).strip() and len(str(n).strip()) >= 2},
            key=len,
            reverse=True,
        )
        for name in cleaned_names:
            out = out.replace(name, "{客户}")

        _guard_secrets(out)
        return out

    def segment_qa_turns(
        self,
        records: Sequence[Dict[str, Any]],
        *,
        gap_minutes: float = 30.0,
        contact: str = "",
    ) -> List[Dict[str, Any]]:
        """Merge consecutive peer/self bubbles into customer-ask -> sales-reply Q&A turns."""
        blocks: List[Dict[str, Any]] = []
        gap_seconds = max(0.0, float(gap_minutes)) * 60.0

        for rec in records or ():
            if not isinstance(rec, dict):
                continue
            if rec.get("kind") == "timestamp":
                continue
            direction = str(rec.get("direction") or "").strip().lower()
            if direction not in ("peer", "self"):
                continue
            text = str(rec.get("text") if rec.get("text") is not None else rec.get("content") or "").strip()
            if not text:
                continue
            raw_ts = rec.get("timestamp") or rec.get("ts") or rec.get("timeMarker") or ""
            parsed_ts = _parse_ts(raw_ts)

            should_merge = False
            if blocks and blocks[-1]["direction"] == direction:
                prev_ts = blocks[-1]["endTs"]
                if prev_ts is None or parsed_ts is None:
                    should_merge = True
                elif (parsed_ts - prev_ts) <= gap_seconds:
                    should_merge = True

            if should_merge:
                blocks[-1]["texts"].append(text)
                blocks[-1]["endRawTs"] = str(raw_ts)
                if parsed_ts is not None:
                    blocks[-1]["endTs"] = parsed_ts
            else:
                blocks.append({
                    "direction": direction,
                    "texts": [text],
                    "startRawTs": str(raw_ts),
                    "endRawTs": str(raw_ts),
                    "startTs": parsed_ts,
                    "endTs": parsed_ts,
                })

        turns: List[Dict[str, Any]] = []
        i = 0
        while i < len(blocks):
            blk = blocks[i]
            if blk["direction"] == "peer" and i + 1 < len(blocks) and blocks[i + 1]["direction"] == "self":
                reply_blk = blocks[i + 1]
                next_peer_reply = ""
                if i + 2 < len(blocks) and blocks[i + 2]["direction"] == "peer":
                    next_peer_reply = "\n".join(blocks[i + 2]["texts"])

                ask_text = "\n".join(blk["texts"])
                reply_text = "\n".join(reply_blk["texts"])
                turns.append({
                    "turnIndex": len(turns) + 1,
                    "contact": contact,
                    "askText": ask_text,
                    "replyText": reply_text,
                    "next_peer_reply": next_peer_reply,
                    "askTimestamp": blk["startRawTs"],
                    "replyTimestamp": reply_blk["startRawTs"],
                    "askBubbleCount": len(blk["texts"]),
                    "replyBubbleCount": len(reply_blk["texts"]),
                })
                i += 2
            else:
                i += 1

        return turns

    def select_high_value_turns(
        self,
        turns: Sequence[Dict[str, Any]],
        *,
        similarity_threshold: float = 0.45,
    ) -> List[Dict[str, Any]]:
        """Drop small talk/rejections, score remaining turns, and cluster similar intents."""
        filtered: List[Dict[str, Any]] = []
        # Track 4-char reply shingles -> distinct contacts for cross-customer repetition bonus
        shingle_contacts: Dict[str, set[str]] = defaultdict(set)

        for idx, turn in enumerate(turns or ()):
            ask = str(turn.get("askText") or turn.get("ask") or "").strip()
            reply = str(turn.get("replyText") or turn.get("reply") or "").strip()
            next_peer = str(turn.get("next_peer_reply") or turn.get("nextPeerReply") or "").strip()
            contact = str(turn.get("contact") or f"unknown_{idx}").strip()

            if _is_pure_small_talk_or_noise(ask) or _is_pure_small_talk_or_noise(reply):
                continue
            if _strip_noise_for_check(reply) in _UNHELPFUL_REPLY_EXACT:
                continue
            if any(marker in next_peer for marker in _REJECTION_MARKERS):
                continue

            compact_reply = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", reply)
            if len(compact_reply) >= 4:
                for pos in range(0, len(compact_reply) - 3):
                    shingle_contacts[compact_reply[pos : pos + 4]].add(contact)

            filtered.append({
                **turn,
                "contact": contact,
                "askText": ask,
                "replyText": reply,
                "next_peer_reply": next_peer,
            })

        scored: List[Dict[str, Any]] = []
        for item in filtered:
            ask = item["askText"]
            reply = item["replyText"]
            next_peer = item["next_peer_reply"]
            contact = item["contact"]
            combined = f"{ask}\n{reply}\n{next_peer}"

            sales_hits = [kw for kw in _SALES_PROGRESSION_SIGNALS if kw in combined]
            sales_score = min(40.0, len(sales_hits) * 8.0)

            pos_hits = [mk for mk in _POSITIVE_FOLLOWUP_MARKERS if mk in next_peer]
            followup_score = min(25.0, len(pos_hits) * 9.0)
            if not pos_hits and next_peer and ("?" in next_peer or "？" in next_peer or len(next_peer) >= 6):
                followup_score = 8.0

            compact_reply = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", reply)
            repeated_shingles = 0
            if len(compact_reply) >= 4:
                seen_shingles: set[str] = set()
                for pos in range(0, len(compact_reply) - 3):
                    sh = compact_reply[pos : pos + 4]
                    if sh not in seen_shingles and len(shingle_contacts.get(sh, set())) >= 2:
                        seen_shingles.add(sh)
                        repeated_shingles += 1
            cross_score = min(20.0, repeated_shingles * 4.0)

            reply_len = len(reply)
            if reply_len >= 30:
                completeness_score = 15.0
            elif reply_len >= 15:
                completeness_score = 10.0
            elif reply_len >= 8:
                completeness_score = 5.0
            else:
                completeness_score = 2.0

            total_score = round(sales_score + followup_score + cross_score + completeness_score, 2)
            if total_score < 12.0:
                continue

            stage, intent = _classify_stage_and_intent(ask, reply)
            scored.append({
                **item,
                "score": total_score,
                "stage": stage,
                "intent": intent,
                "matchedSignals": sales_hits,
                "scoreBreakdown": {
                    "salesSignals": round(sales_score, 2),
                    "positiveFollowup": round(followup_score, 2),
                    "crossCustomerPhrase": round(cross_score, 2),
                    "completeness": round(completeness_score, 2),
                },
            })

        scored.sort(key=lambda t: (-t["score"], -len(t["replyText"]), t["askText"]))

        clusters: List[Dict[str, Any]] = []
        for turn in scored:
            sig = _char_bigrams(f"{turn['askText']} {turn['replyText']}")
            matched_cluster: Optional[Dict[str, Any]] = None
            for cl in clusters:
                if cl["stage"] == turn["stage"] and _jaccard(cl["_sig"], sig) >= similarity_threshold:
                    matched_cluster = cl
                    break
            if matched_cluster is not None:
                matched_cluster["clusterSize"] += 1
                snippet = f"客户：{turn['askText']} -> 回复：{turn['replyText']}"
                if snippet not in matched_cluster["evidenceSnippets"] and len(matched_cluster["evidenceSnippets"]) < 4:
                    matched_cluster["evidenceSnippets"].append(snippet)
            else:
                clusters.append({
                    **turn,
                    "clusterSize": 1,
                    "evidenceSnippets": [f"客户：{turn['askText']} -> 回复：{turn['replyText']}"],
                    "_sig": sig,
                })

        for cl in clusters:
            cl.pop("_sig", None)
        return clusters

    def mine_vocabulary(
        self,
        conversations: Sequence[Dict[str, Any]],
        *,
        model_hub: Any = None,
        use_llm: bool = True,
        max_terms: int = 20,
    ) -> List[Dict[str, Any]]:
        """Mine domain terminology and SKU/model codes using n-gram PMI + optional LLM enrichment."""
        utterances: List[Tuple[str, str, str]] = []  # (contact, direction, redacted_text)
        for idx, conv in enumerate(conversations or ()):
            contact = str(conv.get("contact") or f"contact_{idx}").strip()
            names = [contact] if contact else []
            for rec in conv.get("records") or ():
                raw = str(rec.get("text") if rec.get("text") is not None else rec.get("content") or "").strip()
                if not raw:
                    continue
                redacted = self.redact_pii(raw, customer_names=names)
                utterances.append((contact, str(rec.get("direction") or "peer"), redacted))

        if not utterances:
            return []

        # 1. Statistical Chinese n-gram (2..6 chars) + min-split PMI
        unigram_counts: Counter[str] = Counter()
        ngram_counts: Counter[str] = Counter()
        ngram_contacts: Dict[str, set[str]] = defaultdict(set)
        ngram_utterances: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        total_chars = 0

        for contact, direction, text in utterances:
            for run in re.findall(r"[\u4e00-\u9fff]+", text):
                for ch in run:
                    unigram_counts[ch] += 1
                    total_chars += 1
                run_len = len(run)
                seen_in_utt: set[str] = set()
                for n in range(2, min(7, run_len + 1)):
                    for i in range(run_len - n + 1):
                        gram = run[i : i + n]
                        ngram_counts[gram] += 1
                        ngram_contacts[gram].add(contact)
                        if gram not in seen_in_utt:
                            seen_in_utt.add(gram)
                            ngram_utterances[gram].append((direction, text))

        total_chars = max(1, total_chars)
        total_grams_by_len: Dict[int, int] = defaultdict(int)
        for g, cnt in ngram_counts.items():
            total_grams_by_len[len(g)] += cnt

        def _prob(token: str) -> float:
            if len(token) == 1:
                return unigram_counts[token] / float(total_chars)
            denom = max(1, total_grams_by_len[len(token)])
            return ngram_counts[token] / float(denom)

        scored_grams: List[Tuple[float, str, float, int]] = []
        for gram, freq in ngram_counts.items():
            if freq < 2:
                continue
            if gram in _VOCAB_STOPWORDS:
                continue
            if gram[0] in _EDGE_FUNCTION_CHARS or gram[-1] in _EDGE_FUNCTION_CHARS:
                continue
            if any(sw in gram for sw in ("什么", "怎么", "这个", "那个", "可以", "没有", "不是")):
                continue
            if len(set(gram)) == 1:
                continue

            p_g = _prob(gram)
            min_pmi = float("inf")
            for split_idx in range(1, len(gram)):
                left = gram[:split_idx]
                right = gram[split_idx:]
                denom = _prob(left) * _prob(right)
                if denom > 0 and p_g > 0:
                    pmi = math.log2(p_g / denom)
                    if pmi < min_pmi:
                        min_pmi = pmi
            if min_pmi == float("inf") or min_pmi < 0.8:
                continue

            contact_spread = len(ngram_contacts[gram])
            domain_bonus = 0.0
            contexts = ngram_utterances[gram]
            if any(any(h in txt for h in _DOMAIN_CONTEXT_HINTS) for _, txt in contexts):
                domain_bonus += 2.0
            if contact_spread >= 2:
                domain_bonus += 2.5

            score = freq * 1.6 + min(8.0, min_pmi) + len(gram) * 0.6 + domain_bonus
            scored_grams.append((score, gram, round(min_pmi, 2), freq))

        scored_grams.sort(key=lambda item: (-item[0], -len(item[1]), -item[3], item[1]))

        # Suppress redundant sub-grams covered by a stronger super-gram of similar frequency
        kept_chinese: List[Tuple[float, str, float, int]] = []
        for item in scored_grams:
            _, gram, _, freq = item
            subsumed = False
            for _, longer, _, longer_freq in kept_chinese:
                if len(longer) > len(gram) and gram in longer and freq <= longer_freq + 1:
                    subsumed = True
                    break
            if not subsumed:
                kept_chinese.append(item)

        # 2. Alphanumeric model / SKU regex mining
        sku_counts: Counter[str] = Counter()
        sku_canonical: Dict[str, str] = {}
        sku_contacts: Dict[str, set[str]] = defaultdict(set)
        sku_utterances: Dict[str, List[Tuple[str, str]]] = defaultdict(list)

        for contact, direction, text in utterances:
            for match in _SKU_MODEL_RE.finditer(text):
                raw_sku = match.group(0).strip()
                if len(raw_sku) < 2 or raw_sku.isdigit():
                    continue
                if raw_sku.lower() in {"ok", "http", "https", "v1", "v2"}:
                    continue
                key = raw_sku.casefold()
                sku_canonical.setdefault(key, raw_sku)
                sku_counts[key] += 1
                sku_contacts[key].add(contact)
                sku_utterances[key].append((direction, text))

        results: List[Dict[str, Any]] = []
        seen_terms: set[str] = set()

        for key, freq in sku_counts.most_common():
            if freq < 1:
                continue
            term = sku_canonical[key]
            seen_terms.add(term.casefold())
            contexts = sku_utterances[key]
            results.append(
                self._build_vocab_item(
                    term=term,
                    kind="sku",
                    frequency=freq,
                    pmi=0.0,
                    contact_count=len(sku_contacts[key]),
                    contexts=contexts,
                )
            )

        for score, gram, pmi, freq in kept_chinese:
            if gram.casefold() in seen_terms:
                continue
            seen_terms.add(gram.casefold())
            results.append(
                self._build_vocab_item(
                    term=gram,
                    kind="domain_term",
                    frequency=freq,
                    pmi=pmi,
                    contact_count=len(ngram_contacts[gram]),
                    contexts=ngram_utterances[gram],
                )
            )
            if len(results) >= max_terms:
                break

        results = results[:max_terms]

        if use_llm and model_hub is not None and results and self._is_model_hub_enabled(model_hub):
            results = self._enrich_vocabulary_with_llm(results, model_hub)

        return results

    @staticmethod
    def _build_vocab_item(
        *,
        term: str,
        kind: str,
        frequency: int,
        pmi: float,
        contact_count: int,
        contexts: List[Tuple[str, str]],
    ) -> Dict[str, Any]:
        snippets: List[str] = []
        self_snippets: List[str] = []
        for direction, txt in contexts:
            clean = txt.replace("\n", " ").strip()[:120]
            if clean not in snippets and len(snippets) < 3:
                snippets.append(clean)
            if direction == "self" and clean not in self_snippets:
                self_snippets.append(clean)

        aliases: List[str] = []
        if kind == "sku" and term.lower() != term:
            aliases.append(term.lower())

        sample_ctx = snippets[0] if snippets else term
        definition = (
            f"业务高频{'型号/SKU' if kind == 'sku' else '专有词'}（语料出现 {frequency} 次，涉及 {contact_count} 位客户），"
            f"常见语境如：「{sample_ctx}」。"
        )
        do_say = (
            f"沿用客户与我方常用表达「{self_snippets[0]}」"
            if self_snippets
            else f"结合客户当前场景准确使用「{term}」，讲清对应适用条件与价值。"
        )
        dont_say = f"避免脱离客户诉求生硬堆砌「{term}」，或未经核实擅自承诺价格与交付期限。"
        return {
            "term": term,
            "kind": kind,
            "aliases": aliases,
            "definition": definition,
            "doSay": do_say,
            "dontSay": dont_say,
            "evidence": snippets,
            "frequency": frequency,
            "pmi": pmi,
        }

    @staticmethod
    def _is_model_hub_enabled(model_hub: Any) -> bool:
        if model_hub is None or not callable(getattr(model_hub, "generate_chat_reply", None)):
            return False
        state = getattr(model_hub, "state", None)
        if isinstance(state, dict) and state.get("enabled") is False:
            return False
        return True

    @staticmethod
    def _enrich_vocabulary_with_llm(items: List[Dict[str, Any]], model_hub: Any) -> List[Dict[str, Any]]:
        compact_input = [
            {"term": it["term"], "evidence": it["evidence"][:2]}
            for it in items[:12]
        ]
        prompt = (
            "请根据以下微信销售聊天上下文片段，为每个业务术语补充简洁的中文定义(definition)、"
            "同义词/别名(aliases数组)、推荐说法(doSay)和禁用踩坑说法(dontSay)。"
            "只输出 JSON 数组，元素字段为 term, aliases, definition, doSay, dontSay。\n"
            f"{json.dumps(compact_input, ensure_ascii=False)}"
        )
        try:
            resp = model_hub.generate_chat_reply(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1024,
                timeout=8.0,
            )
            if not isinstance(resp, dict) or not resp.get("ok"):
                return items
            parsed = _extract_json_block(str(resp.get("replyText") or ""))
            if not isinstance(parsed, list):
                return items
            by_term = {str(p.get("term") or "").strip(): p for p in parsed if isinstance(p, dict)}
            for it in items:
                patch = by_term.get(it["term"])
                if not patch:
                    continue
                if isinstance(patch.get("definition"), str) and patch["definition"].strip():
                    it["definition"] = patch["definition"].strip()
                if isinstance(patch.get("doSay"), str) and patch["doSay"].strip():
                    it["doSay"] = patch["doSay"].strip()
                if isinstance(patch.get("dontSay"), str) and patch["dontSay"].strip():
                    it["dontSay"] = patch["dontSay"].strip()
                if isinstance(patch.get("aliases"), list):
                    it["aliases"] = [str(a).strip() for a in patch["aliases"] if str(a).strip()]
        except Exception:
            return items
        return items

    def synthesize_playbooks(
        self,
        selected_turns: Sequence[Dict[str, Any]],
        vocabulary: Sequence[Dict[str, Any]],
        sales_pack: Dict[str, Any],
        owner_style: Optional[Dict[str, Any]] = None,
        *,
        model_hub: Any = None,
        use_llm: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fuse L1 sales pack skeletons + mined turns + vocabulary + owner style with hard risk gating."""
        stages_by_name: Dict[str, Dict[str, Any]] = {}
        for st in sales_pack.get("stages") or ():
            if isinstance(st, dict) and st.get("stage"):
                stages_by_name[str(st["stage"])] = st

        pack_entries_by_stage: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for pe in sales_pack.get("entries") or ():
            if isinstance(pe, dict) and pe.get("stage"):
                pack_entries_by_stage[str(pe["stage"])].append(pe)

        entries: List[Dict[str, Any]] = []
        vocab_terms = [str(v.get("term") or "").strip() for v in (vocabulary or ()) if str(v.get("term") or "").strip()]

        # 1. Synthesize script / faq entries from selected high-value turns fused with L1 stage skeletons
        for idx, turn in enumerate(selected_turns or ()):
            ask = self.redact_pii(str(turn.get("askText") or "").strip())
            reply = self.redact_pii(str(turn.get("replyText") or "").strip())
            stage = str(turn.get("stage") or "沟通中").strip()
            intent = str(turn.get("intent") or "客户咨询应对").strip()
            stage_meta = stages_by_name.get(stage) or stages_by_name.get("沟通中") or {}
            stage_strategy = str(stage_meta.get("strategy") or "").strip()

            is_faq = any(q in ask for q in ("?", "？", "怎么", "多少", "什么", "能不能", "是否", "为什么", "对比"))
            kind = "faq" if is_faq else "script"

            matched_pack_entry = (pack_entries_by_stage.get(stage) or [None])[0]
            base_keywords = list(turn.get("matchedSignals") or [])
            for vt in vocab_terms:
                if vt in ask or vt in reply:
                    base_keywords.append(vt)
            if matched_pack_entry:
                for kw in matched_pack_entry.get("keywords") or ():
                    if kw not in base_keywords:
                        base_keywords.append(str(kw))
            base_keywords = list(dict.fromkeys(k for k in base_keywords if k))[:8]

            short_ask = ask.replace("\n", " ")[:24]
            title = f"{stage}·{intent}（{short_ask}）" if short_ask else f"{stage}·{intent}"

            personalized = _apply_owner_style(reply, owner_style)
            if use_llm and model_hub is not None and self._is_model_hub_enabled(model_hub):
                personalized = self._polish_script_with_llm(
                    ask=ask,
                    reply=personalized,
                    strategy=stage_strategy,
                    owner_style=owner_style,
                    model_hub=model_hub,
                )

            body_parts = [f"【客户常见提问】{ask}", f"【实战回复话术】{personalized}"]
            if stage_strategy:
                body_parts.append(f"【阶段策略要点】{stage_strategy}")
            body = self.redact_pii("\n".join(body_parts))

            evidence = [self.redact_pii(str(s)) for s in (turn.get("evidenceSnippets") or [f"客户：{ask} -> 回复：{reply}"])]
            synonyms = [ask.replace("\n", " ")[:40]]
            if matched_pack_entry:
                for syn in (matched_pack_entry.get("synonyms") or ())[:3]:
                    if syn not in synonyms:
                        synonyms.append(str(syn))

            raw_score = float(turn.get("score") or 50.0)
            confidence = round(min(0.98, max(0.45, raw_score / 100.0)), 2)

            risk_flags = _evaluate_risk_flags([title, body, personalized, *evidence])
            needs_approval = len(risk_flags) > 0
            rec_status = "draft" if needs_approval else "published"

            entries.append({
                "id": f"st_{kind}_{idx + 1}",
                "kind": kind,
                "stage": stage,
                "triggerIntents": [intent],
                "title": title,
                "body": body,
                "personalizedScript": personalized,
                "keywords": base_keywords or [stage, intent],
                "synonyms": synonyms,
                "evidenceSnippets": evidence,
                "confidence": confidence,
                "riskFlags": risk_flags,
                "recommendedStatus": rec_status,
                "needsApproval": needs_approval,
            })

        # 2. Synthesize terminology entries from mined vocabulary
        for v_idx, vocab in enumerate(vocabulary or ()):
            term = self.redact_pii(str(vocab.get("term") or "").strip())
            if not term:
                continue
            definition = self.redact_pii(str(vocab.get("definition") or "").strip())
            do_say = self.redact_pii(str(vocab.get("doSay") or "").strip())
            dont_say = self.redact_pii(str(vocab.get("dontSay") or "").strip())
            evidence = [self.redact_pii(str(s)) for s in (vocab.get("evidence") or ())]
            aliases = [self.redact_pii(str(a)) for a in (vocab.get("aliases") or ()) if str(a).strip()]

            body = "\n".join(
                part for part in (
                    definition,
                    f"推荐说法：{do_say}" if do_say else "",
                    f"注意事项：{dont_say}" if dont_say else "",
                ) if part
            )
            title = f"行业术语：{term}"
            risk_flags = _evaluate_risk_flags([title, body, *evidence])
            needs_approval = len(risk_flags) > 0
            rec_status = "draft" if needs_approval else "published"
            freq = int(vocab.get("frequency") or 1)
            conf = round(min(0.95, 0.55 + freq * 0.06), 2)

            entries.append({
                "id": f"st_term_{v_idx + 1}",
                "kind": "terminology",
                "stage": "沟通中",
                "triggerIntents": ["术语理解与专业表达"],
                "title": title,
                "body": body,
                "personalizedScript": do_say or definition,
                "keywords": [term] + aliases[:4],
                "synonyms": aliases,
                "evidenceSnippets": evidence,
                "confidence": conf,
                "riskFlags": risk_flags,
                "recommendedStatus": rec_status,
                "needsApproval": needs_approval,
            })

        return entries

    @staticmethod
    def _polish_script_with_llm(
        *,
        ask: str,
        reply: str,
        strategy: str,
        owner_style: Optional[Dict[str, Any]],
        model_hub: Any,
    ) -> str:
        prompt = (
            "请在不改变原有业务事实、数字、价格或承诺的前提下，结合销售阶段策略和号主说话习惯，"
            "润色下面这条微信回复，使其更像真人自然口语，只返回润色后的回复正文。\n"
            f"客户提问：{ask}\n"
            f"原回复：{reply}\n"
            f"阶段策略：{strategy}\n"
            f"风格参考：{json.dumps(owner_style or {}, ensure_ascii=False)}"
        )
        try:
            resp = model_hub.generate_chat_reply(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=512,
                timeout=8.0,
            )
            if isinstance(resp, dict) and resp.get("ok"):
                polished = str(resp.get("replyText") or "").strip()
                if polished:
                    return polished
        except Exception:
            pass
        return reply

    def train_from_corpora(
        self,
        conversations: Sequence[Dict[str, Any]],
        *,
        sales_pack: Dict[str, Any],
        knowledge_store: WeChatKnowledgeStore,
        model_hub: Any = None,
        use_llm: bool = True,
        auto_publish_safe: bool = True,
        report_path: Optional[Path | str] = None,
        owner_style: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute end-to-end self-training from corpora and persist governed playbooks."""
        redacted_conversations: List[Dict[str, Any]] = []
        all_turns: List[Dict[str, Any]] = []
        raw_message_count = 0

        for idx, conv in enumerate(conversations or ()):
            contact = str(conv.get("contact") or f"客户_{idx + 1}").strip()
            customer_names = [contact] if contact else []
            redacted_records: List[Dict[str, Any]] = []
            for rec in conv.get("records") or ():
                raw_text = str(rec.get("text") if rec.get("text") is not None else rec.get("content") or "").strip()
                if not raw_text:
                    continue
                raw_message_count += 1
                redacted_records.append({
                    **rec,
                    "text": self.redact_pii(raw_text, customer_names=customer_names),
                })
            redacted_conv = {**conv, "contact": contact, "records": redacted_records}
            redacted_conversations.append(redacted_conv)
            all_turns.extend(self.segment_qa_turns(redacted_records, contact=contact))

        selected_turns = self.select_high_value_turns(all_turns)
        vocabulary = self.mine_vocabulary(
            redacted_conversations,
            model_hub=model_hub,
            use_llm=use_llm,
        )
        resolved_style = owner_style if owner_style is not None else _infer_owner_style(redacted_conversations)
        synthesized = self.synthesize_playbooks(
            selected_turns,
            vocabulary,
            sales_pack,
            resolved_style,
            model_hub=model_hub,
            use_llm=use_llm,
        )

        saved_entries: List[Dict[str, Any]] = []
        published_ids: List[str] = []
        draft_ids: List[str] = []

        for item in synthesized:
            should_publish = (item["recommendedStatus"] == "published") and bool(auto_publish_safe)
            target_status = "published" if should_publish else "draft"
            saved = knowledge_store.save_entry(
                title=item["title"],
                body=item["body"],
                kind=item["kind"],
                library="shared",
                keywords=item["keywords"],
                synonyms=item["synonyms"],
                source="self-train",
                external=True,
                status=target_status,
            )
            stored_entry = dict(saved["entry"])
            stored_entry["stage"] = item["stage"]
            stored_entry["riskFlags"] = list(item["riskFlags"])
            stored_entry["needsApproval"] = bool(item["needsApproval"])
            stored_entry["confidence"] = item["confidence"]
            stored_entry["personalizedScript"] = item["personalizedScript"]
            saved_entries.append(stored_entry)
            if target_status == "published":
                published_ids.append(stored_entry["id"])
            else:
                draft_ids.append(stored_entry["id"])

        report: Dict[str, Any] = {
            "ok": True,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "packId": str(sales_pack.get("packId") or ""),
            "stats": {
                "conversationCount": len(redacted_conversations),
                "messageCount": raw_message_count,
                "segmentedTurnCount": len(all_turns),
                "selectedTurnCount": len(selected_turns),
                "vocabularyCount": len(vocabulary),
                "synthesizedCount": len(saved_entries),
                "publishedCount": len(published_ids),
                "draftCount": len(draft_ids),
            },
            "ownerStyle": resolved_style,
            "vocabulary": vocabulary,
            "selectedTurns": selected_turns,
            "entries": saved_entries,
            "publishedIds": published_ids,
            "draftIds": draft_ids,
            "reportPath": str(report_path) if report_path else None,
        }

        if report_path is not None:
            atomic_write_json(Path(report_path), report)

        return report

    def approve_drafts(
        self,
        knowledge_store: WeChatKnowledgeStore,
        entry_ids: Iterable[str],
        *,
        edits: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Publish selected draft entries in knowledge_store with optional title/body edits."""
        wanted = [str(eid).strip() for eid in (entry_ids or ()) if str(eid).strip()]
        listing = knowledge_store.list_entries(include_drafts=True, limit=1000)
        by_id = {str(e["id"]): e for e in listing.get("entries") or ()}

        edits_map = edits if isinstance(edits, dict) else {}
        approved: List[Dict[str, Any]] = []
        published_ids: List[str] = []
        missing_ids: List[str] = []

        for eid in wanted:
            existing = by_id.get(eid)
            if not existing:
                missing_ids.append(eid)
                continue

            patch: Dict[str, Any] = {}
            if eid in edits_map and isinstance(edits_map[eid], dict):
                patch = edits_map[eid]
            elif len(wanted) == 1 and any(k in edits_map for k in ("title", "body", "keywords", "synonyms")):
                patch = edits_map

            new_title = self.redact_pii(str(patch.get("title") or existing["title"]).strip())
            new_body = self.redact_pii(str(patch.get("body") or existing["body"]).strip())
            new_keywords = patch.get("keywords") if "keywords" in patch else existing.get("keywords", [])
            new_synonyms = patch.get("synonyms") if "synonyms" in patch else existing.get("synonyms", [])

            res = knowledge_store.save_entry(
                title=new_title,
                body=new_body,
                kind=existing["kind"],
                library=existing["library"],
                keywords=new_keywords,
                synonyms=new_synonyms,
                source=existing.get("source") or "self-train",
                external=bool(existing.get("external", True)),
                status="published",
                space_id=existing.get("spaceId") or "personal",
                bot_id=existing.get("ownerBotId") or "default",
                entry_id=eid,
                expected_revision=int(existing["revision"]),
            )
            approved_entry = res["entry"]
            approved.append(approved_entry)
            published_ids.append(eid)

        return {
            "ok": True,
            "approved": approved,
            "publishedIds": published_ids,
            "missingIds": missing_ids,
        }
