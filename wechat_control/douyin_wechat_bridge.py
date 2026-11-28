"""Douyin -> WeChat Lead Acquisition & Friend-Adding Funnel (v3.0.1).

Provides the complete closed loop for Douyin customer acquisition:
  1. Extracting WeChat IDs and Mainland mobile numbers from Douyin DMs/comments
     (including full-width NFKC normalization and context-aware bare IDs).
  2. Anti-ban compliant Douyin DM reply sanitization & generation to elicit the
     user's WeChat account without leaking self-promoted contact info.
  3. macOS WeChat 4.2.1 `add_friend` RPA state machine calibrated against the
     live `+` -> `添加朋友` window (`360x560`) with capability gates, daily
     quota, cooldown, dedup, and human-activity protection.
  4. Persistent `DouyinWeChatFunnel` orchestrating Douyin DM inspection, reply,
     WeChat extraction, SalesCRM enrollment, and WeChat friend requests.
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .io_utils import atomic_write_json

VERIFY_DIR_DEFAULT = (
    Path("/Volumes/SanDisk/Builds/WeChatBot/douyin-wechat-verify")
    if Path("/Volumes/SanDisk/Builds").exists()
    else Path(__file__).resolve().parent.parent / "logs" / "douyin-wechat-verify"
)

_AI_SLOP_WORDS: Tuple[str, ...] = (
    "赋能",
    "一站式",
    "颠覆",
    "全能",
    "闭环",
    "抓手",
    "解锁新体验",
    "效率神器",
    "宝子们",
)

# Patterns that leak our OWN off-platform ID/phone/URL (blocked on Douyin DM).
_SELF_PROMO_PATTERNS: Tuple[Tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"(?:加我?|添?加我)\s*(?:[Vv微微信vxVX]+)\s*[:：]?\s*[A-Za-z0-9_-]{3,}"),
        "self_promo_add_wechat",
        "方便发一下你的微信号，这边加你",
    ),
    (
        re.compile(r"(?:微信号?|wx|vx|v信)\s*[:：=]\s*[A-Za-z0-9_-]{4,}", re.IGNORECASE),
        "self_promo_wechat_id",
        "私信留一下你的联系方式",
    ),
    (
        re.compile(r"\+[VvXx]\s*[:：]?\s*[A-Za-z0-9_-]{4,}"),
        "self_promo_vx",
        "私信留一下你的联系方式",
    ),
    (re.compile(r"QQ\s*群?\s*[:：]?\s*\d{5,}", re.IGNORECASE), "self_promo_qq", "私信沟通"),
    (re.compile(r"https?://\S+", re.IGNORECASE), "external_url", "私信发你详细说明"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "self_promo_phone", "私信留个联系方式"),
)

# Rule 1: explicit prefix before WeChat ID or phone number.
_EXPLICIT_WECHAT_RE = re.compile(
    r"(?:微信号?|微信|wx号?|vx号?|v信|威信|威|➕\s*[vV微]|加\s*[vV微]|加我|w\s*x|v\s*x)"
    r"\s*[:：=是为叫，,\s]?\s*"
    r"(wxid_[A-Za-z0-9_-]{5,24}|[A-Za-z][A-Za-z0-9_-]{5,19}|1[3-9]\d(?:[\s\-]?\d{4}){2})"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)

# Rule 2: Mainland China 11-digit mobile numbers (allowing spaces or hyphens).
_MOBILE_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d(?:[\s\-]?\d{4}){2})(?!\d)")

# Rule 3: bare candidate token for contextual matching.
_BARE_WECHAT_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_@./-])([A-Za-z][A-Za-z0-9_-]{5,19})(?![A-Za-z0-9_@./-])")

_URL_OR_EMAIL_RE = re.compile(r"(?:https?://\S+|www\.\S+|\S+@\S+\.\S+)", re.IGNORECASE)

_ASK_WECHAT_CUES: Tuple[str, ...] = (
    "微信",
    "微信号",
    "联系方式",
    "加你",
    "留个",
    "发一下",
    "发我",
    "vx",
    "wx",
    "v信",
    "威信",
    "手机号",
)

_CONTEXT_SELF_CUES: Tuple[str, ...] = ("号", "加", "联系", "通过", "好友", "vx", "wx", "微")

_BARE_ID_STOPWORDS = frozenset({
    "douyin", "wechat", "tiktok", "hello", "thanks", "thankyou", "thank_you",
    "please", "iphone", "android", "macos", "windows", "github", "chatgpt",
    "gemini", "deepseek", "claude", "openbot", "feishu", "dingtalk",
    "xiaohongshu", "sorry", "nihao", "welcome", "friend", "message",
    "good_morning", "no_problem", "video", "comment", "system", "update",
    "chrome", "safari", "python", "server", "client", "docker", "online",
})

_WECHAT_ID_VALID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{5,19}$")
_WXID_VALID_RE = re.compile(r"^wxid_[A-Za-z0-9_-]{5,24}$", re.IGNORECASE)
_PHONE_VALID_RE = re.compile(r"^1[3-9]\d{9}$")

_LEAD_HOT_EXTRA_CUES: Tuple[str, ...] = ("报价", "多少钱", "怎么买", "购买", "合作", "私有化", "部署", "试用", "代理", "商务")
_LEAD_WARM_EXTRA_CUES: Tuple[str, ...] = ("怎么用", "发我", "看一下", "文档", "联系", "私信", "有兴趣", "想要", "了解")

_NOT_FOUND_OCR_CUES: Tuple[str, ...] = ("该用户不存在", "无法找到该用户", "用户不存在", "状态异常", "查无此人", "被搜账号状态异常")
_RATE_LIMIT_OCR_CUES: Tuple[str, ...] = ("操作过于频繁", "请稍后再试", "添加朋友过于频繁", "请求过于频繁")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def validate_wechat_account(account: str) -> Tuple[bool, str, str]:
    """Validate and normalize a WeChat ID (`wechat_id`) or Mainland phone (`phone`)."""
    raw = _normalize_nfkc(account)
    if not raw:
        return False, "", ""
    digits = re.sub(r"[\s\-]+", "", raw)
    if _PHONE_VALID_RE.match(digits):
        return True, digits, "phone"
    compact = raw.strip()
    if _WXID_VALID_RE.match(compact):
        return True, compact, "wechat_id"
    if _WECHAT_ID_VALID_RE.match(compact):
        return True, compact, "wechat_id"
    return False, compact, ""


def _is_plausible_bare_wechat_id(token: str) -> bool:
    low = token.casefold()
    if low in _BARE_ID_STOPWORDS:
        return False
    if low.startswith("wxid_"):
        return bool(_WXID_VALID_RE.match(token))
    if not _WECHAT_ID_VALID_RE.match(token):
        return False
    has_digit_or_sep = any(ch.isdigit() or ch in ("_", "-") for ch in token)
    return has_digit_or_sep


def extract_wechat_accounts_from_text(
    text: str,
    *,
    context_allows_bare: bool = False,
) -> List[Dict[str, Any]]:
    """Extract WeChat IDs and mobile numbers from a single incoming message."""
    norm = _normalize_nfkc(text)
    if not norm:
        return []

    found: Dict[str, Dict[str, Any]] = {}

    def _add(account: str, acc_type: str, confidence: str, rule: str, snippet: str) -> None:
        key = account.casefold()
        existing = found.get(key)
        if existing and existing["confidence"] == "high" and confidence != "high":
            return
        found[key] = {
            "account": account,
            "accountType": acc_type,
            "confidence": confidence,
            "matchedRule": rule,
            "rawSnippet": snippet[:80],
        }

    # Strip URLs and emails before scanning tokens/digits to prevent false positives.
    scrubbed = _URL_OR_EMAIL_RE.sub(" ", norm)

    # Rule 1: Explicit WeChat cue prefix.
    for match in _EXPLICIT_WECHAT_RE.finditer(scrubbed):
        candidate = match.group(1).strip()
        ok, normalized_acc, acc_type = validate_wechat_account(candidate)
        if not ok:
            continue
        if acc_type == "wechat_id" and normalized_acc.casefold() in _BARE_ID_STOPWORDS:
            continue
        _add(normalized_acc, acc_type, "high", "explicit_wechat_prefix", match.group(0))

    # Rule 2: Mainland mobile phone number.
    for match in _MOBILE_PHONE_RE.finditer(scrubbed):
        digits = re.sub(r"[\s\-]+", "", match.group(1))
        if _PHONE_VALID_RE.match(digits):
            _add(digits, "phone", "high", "mobile_phone", match.group(0))

    # Rule 3: Contextual bare WeChat ID in short messages.
    has_self_cue = any(cue in norm.casefold() for cue in _CONTEXT_SELF_CUES)
    if (context_allows_bare or has_self_cue) and len(norm) <= 60:
        for match in _BARE_WECHAT_TOKEN_RE.finditer(scrubbed):
            token = match.group(1).strip()
            if _is_plausible_bare_wechat_id(token):
                _add(token, "wechat_id", "medium", "contextual_bare_wechat_id", norm)

    results = list(found.values())
    rank = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda item: (rank.get(item["confidence"], 9), item["account"]))
    return results


def extract_wechat_accounts_from_messages(
    messages: Iterable[Dict[str, Any]],
    *,
    douyin_user: str = "",
) -> List[Dict[str, Any]]:
    """Scan a sequence of messages and harvest incoming customer WeChat accounts."""
    msg_list = [m for m in (messages or []) if isinstance(m, dict)]
    results_by_key: Dict[str, Dict[str, Any]] = {}
    prev_outgoing_asked = False

    for msg in msg_list:
        direction = str(msg.get("direction") or "incoming").strip().lower()
        txt = _normalize_nfkc(str(msg.get("text") or ""))
        if not txt:
            continue
        if direction == "outgoing":
            prev_outgoing_asked = any(cue in txt.casefold() for cue in _ASK_WECHAT_CUES)
            continue

        sender = str(msg.get("sender") or douyin_user or "").strip()
        extracted = extract_wechat_accounts_from_text(txt, context_allows_bare=prev_outgoing_asked)
        for item in extracted:
            key = item["account"].casefold()
            rec = dict(item)
            rec["douyinUser"] = sender or douyin_user
            existing = results_by_key.get(key)
            if existing and existing["confidence"] == "high" and rec["confidence"] != "high":
                continue
            results_by_key[key] = rec
        prev_outgoing_asked = False

    out = list(results_by_key.values())
    rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda item: (rank.get(item["confidence"], 9), item["account"]))
    return out


def sanitize_douyin_dm_reply(text: str, *, soften: bool = True) -> Dict[str, Any]:
    """Sanitize a Douyin DM reply: block self-promo IDs/URLs/phones/slop, allow soft asks."""
    original = str(text or "").strip()
    cleaned = original
    warnings: List[str] = []

    md_cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    md_cleaned = re.sub(r"`([^`]+)`", r"\1", md_cleaned)
    md_cleaned = re.sub(r"^#{1,6}\s+", "", md_cleaned, flags=re.MULTILINE)
    md_cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", md_cleaned)
    if md_cleaned != cleaned:
        warnings.append("stripped_markdown")
        cleaned = md_cleaned

    for bad in _AI_SLOP_WORDS:
        if bad in cleaned:
            warnings.append(f"ai_slop:{bad}")
            if soften:
                cleaned = cleaned.replace(bad, "")

    for pat, code, replacement in _SELF_PROMO_PATTERNS:
        if pat.search(cleaned):
            warnings.append(code)
            if soften:
                cleaned = pat.sub(replacement, cleaned)

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    if soften:
        cleaned = re.sub(r"^[，,。！!？?\s]+", "", cleaned).strip()

    post_violations = any(pat.search(cleaned) for pat, _, _ in _SELF_PROMO_PATTERNS)
    return {
        "channel": "douyin",
        "surface": "dm",
        "original": original,
        "sanitized": cleaned,
        "modified": cleaned != original,
        "warnings": warnings,
        "compliant": not post_violations,
    }


def compose_douyin_lead_reply(
    incoming_text: str,
    *,
    stage: str = "ask_wechat",
    kb_answer: str = "",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose a natural, anti-ban Douyin DM reply tailored to funnel stage."""
    cfg = config or {}
    norm_stage = str(stage or "ask_wechat").strip().lower()
    ask_tpl = str(
        cfg.get("replyTemplate")
        or "你好，方便发一下你的微信号吗？这边加你发详细资料和方案～"
    ).strip()
    followup_tpl = str(
        cfg.get("followupTemplate")
        or "这边在微信上发资料和演示更方便，直接发我一下你的微信号就行～"
    ).strip()
    ack_tpl = str(
        cfg.get("ackTemplate")
        or "收到啦，这边马上加你微信，注意通过一下好友申请～"
    ).strip()

    kb_snippet = str(kb_answer or "").strip()
    if norm_stage == "ack_wechat_captured":
        raw = ack_tpl
    elif norm_stage == "followup_ask_wechat":
        raw = f"{kb_snippet}\n{followup_tpl}" if kb_snippet else followup_tpl
    else:
        norm_stage = "ask_wechat"
        if kb_snippet:
            short_kb = kb_snippet[:140].rstrip("，,。 ")
            raw = f"{short_kb}。{ask_tpl}"
        else:
            raw = ask_tpl

    audit = sanitize_douyin_dm_reply(raw, soften=True)
    return {
        "text": audit["sanitized"],
        "stage": norm_stage,
        "incomingPreview": _normalize_nfkc(incoming_text)[:80],
        "compliance": audit,
    }


DOUYIN_TO_WECHAT_SOP_WORKFLOW: Dict[str, Any] = {
    "id": "sop-douyin-to-wechat-funnel",
    "name": "抖音获客 → 引流到微信标准化 SOP 工作流",
    "version": "1.0.0",
    "steps": [
        {
            "step": 1,
            "code": "douyin_dm_guide",
            "title": "抖音私信自然引导留微信号",
            "action": "回复客户产品/服务疑问并用口语自然索要微信号或手机号，严禁发送我方微信号/手机号/外链以防限流。",
        },
        {
            "step": 2,
            "code": "extract_and_score",
            "title": "自动提取微信号与意向分级",
            "action": "从抖音私信/评论中识别微信号或11位手机号，结合询价/合作信号词完成 hot/warm/cold 意向评级。",
        },
        {
            "step": 3,
            "code": "wechat_add_with_self_intro",
            "title": "微信发起好友申请（自报家门 + 统一备注）",
            "action": "验证语必须自报家门（品牌主体 + 称呼 + 来源抖音 + 沟通目的），微信备注统一设为「抖音引流-对方昵称」或「抖音引流」。",
        },
        {
            "step": 4,
            "code": "crm_and_memory_profile",
            "title": "后端 CRM 与记忆库建档标注「抖音获客」",
            "action": "自动在销售 CRM 与长期记忆库建立客户档案，写入标签「抖音获客」「抖音引流」「渠道:抖音」及原始私信上下文。",
        },
        {
            "step": 5,
            "code": "wechat_承接转化",
            "title": "通过好友后无缝承接推进",
            "action": "对方通过申请后，基于已建档的抖音来意直接发送匹配资料或提问推进，不再重复盘问基础背景。",
        },
    ],
}


def compose_friend_greeting(
    template: str = "",
    *,
    business_name: str = "",
    owner_name: str = "",
    douyin_user: str = "",
    source_channel: str = "douyin",
) -> str:
    """Compose a concise, natural self-introducing WeChat friend verification greeting."""
    biz = re.sub(r"\s+", " ", str(business_name or "")).strip()
    owner = re.sub(r"\s+", " ", str(owner_name or "")).strip()
    user = re.sub(r"\s+", " ", str(douyin_user or "")).strip()
    tpl = str(template or "").strip()

    if tpl and ("{businessName}" in tpl or "{ownerName}" in tpl or "{douyinUser}" in tpl):
        if biz and owner:
            intro = f"{biz}的{owner}"
        elif biz:
            intro = f"{biz}这边"
        elif owner:
            intro = owner
        else:
            intro = "这边的顾问"
        out = tpl
        if "{businessName}的{ownerName}" in out:
            out = out.replace("{businessName}的{ownerName}", intro)
        elif "{businessName}{ownerName}" in out:
            out = out.replace("{businessName}{ownerName}", intro)
        out = out.replace("{businessName}", biz or "我们团队")
        out = out.replace("{ownerName}", owner or "顾问")
        out = out.replace("{douyinUser}", user)
        out = re.sub(r"\s+", " ", out).strip(" ，,")
        return out[:50]

    if tpl:
        if biz and biz not in tpl:
            return f"你好，我是{biz}{('的' + owner) if owner else ''}，{tpl}"[:50]
        return tpl[:50]

    channel_label = "抖音" if str(source_channel or "douyin").strip().lower() == "douyin" else str(source_channel or "线上").strip()
    if biz and owner:
        who = f"我是{biz}的{owner}"
    elif biz:
        who = f"我是{biz}这边"
    elif owner:
        who = f"我是{owner}"
    else:
        who = "这边是顾问团队"
    return f"你好呀，{who}，刚在{channel_label}看到你发来的消息，这边加你微信详聊～"[:50]


def classify_wechat_add_lookup_ocr(
    ocr_texts: Iterable[str],
    ocr_elements: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Classify macOS WeChat `添加朋友` search results from OCR text & elements."""
    texts = [str(t or "").strip() for t in (ocr_texts or []) if str(t or "").strip()]
    if not texts and ocr_elements:
        texts = [str(el.get("text") or "").strip() for el in ocr_elements if str(el.get("text") or "").strip()]
    joined = " ".join(texts)

    for cue in _RATE_LIMIT_OCR_CUES:
        if cue in joined:
            return {
                "status": "rate_limited",
                "matchedCue": cue,
                "actionPoint": None,
                "texts": texts[:20],
            }

    for cue in _NOT_FOUND_OCR_CUES:
        if cue in joined:
            return {
                "status": "not_found",
                "matchedCue": cue,
                "actionPoint": None,
                "texts": texts[:20],
            }

    add_btn_point: Optional[Dict[str, float]] = None
    has_add_btn = "添加到通讯录" in joined
    if ocr_elements:
        for el in ocr_elements:
            txt = str(el.get("text") or "").strip()
            if "添加到通讯录" in txt:
                has_add_btn = True
                c = el.get("center") or {}
                if "x" in c and "y" in c:
                    add_btn_point = {"x": float(c["x"]), "y": float(c["y"])}
                break

    if has_add_btn:
        return {
            "status": "candidate_found",
            "matchedCue": "添加到通讯录",
            "actionPoint": add_btn_point,
            "texts": texts[:20],
        }

    if "发消息" in joined or "音视频通话" in joined:
        return {
            "status": "already_friend",
            "matchedCue": "发消息" if "发消息" in joined else "音视频通话",
            "actionPoint": None,
            "texts": texts[:20],
        }

    return {
        "status": "unknown",
        "matchedCue": "",
        "actionPoint": None,
        "texts": texts[:20],
    }


def _find_ocr_element(
    elements: Iterable[Dict[str, Any]],
    keywords: Iterable[str],
    *,
    min_y: float = 0.0,
) -> Optional[Dict[str, Any]]:
    keys = [k.replace(" ", "") for k in keywords if k]
    for el in elements or []:
        txt = str(el.get("text") or "").replace(" ", "")
        c = el.get("center") or {}
        if float(c.get("y") or 0.0) < min_y:
            continue
        if any(k in txt for k in keys):
            return el
    return None


def _human_pause(min_s: float = 0.35, max_s: float = 0.85) -> None:
    time.sleep(random.uniform(min_s, max_s))


class WeChatFriendAdder:
    """Safe macOS WeChat `add_friend` RPA state machine calibrated for WeChat 4.2.1."""

    def __init__(
        self,
        engine: Any,
        *,
        funnel: Optional["DouyinWeChatFunnel"] = None,
        verify_dir: Optional[Path] = None,
        rng: Optional[Callable[[float, float], float]] = None,
    ) -> None:
        self.engine = engine
        self.funnel = funnel
        self.verify_dir = Path(verify_dir) if verify_dir else VERIFY_DIR_DEFAULT
        self._uniform = rng or random.uniform

    def _sleep_paced(self, low: float = 0.35, high: float = 0.90) -> None:
        time.sleep(max(0.05, float(self._uniform(low, high))))

    @staticmethod
    def _ocr_scale(ocr_res: Dict[str, Any], win_w: float, win_h: float) -> Tuple[float, float]:
        wb = ocr_res.get("windowBounds") or {}
        eff_w = float(wb.get("width") or win_w or 1.0)
        eff_h = float(wb.get("height") or win_h or 1.0)
        img_w = float(ocr_res.get("imageWidth") or eff_w or 1.0)
        img_h = float(ocr_res.get("imageHeight") or eff_h or 1.0)
        return img_w / max(eff_w, 1.0), img_h / max(eff_h, 1.0)

    @staticmethod
    def _scaled_center(el: Dict[str, Any], sx: float, sy: float) -> Tuple[float, float]:
        c = el.get("center") or {}
        return float(c.get("x") or 0.0) / max(sx, 1e-6), float(c.get("y") or 0.0) / max(sy, 1e-6)

    def _dismiss_wechat_modal(self) -> None:
        try:
            self.engine._run_native(
                ["press-key", "--bundle-id", "com.tencent.xinWeChat", "--combo", "escape", "--skip-human-check"],
                timeout=6.0,
            )
            for _ in range(2):
                st = self.engine._run_native(["status", "--app", "wechat"], timeout=6.0)
                add_win = next((w for w in (st.get("windows") or []) if "添加朋友" in str(w.get("title") or "")), None)
                if not add_win:
                    break
                wb = add_win.get("bounds") or {}
                close_x = float(wb.get("x") or 0.0) + 18.0
                close_y = float(wb.get("y") or 0.0) + 21.0
                self.engine._run_native(
                    ["click", "--x", f"{close_x:.1f}", "--y", f"{close_y:.1f}", "--skip-human-check"],
                    timeout=6.0,
                )
                time.sleep(0.25)
        except Exception:
            pass

    def _locate_plus_button(self, main_win: Dict[str, Any], ocr_res: Dict[str, Any]) -> Tuple[float, float]:
        wb = main_win.get("bounds") or {}
        win_x = float(wb.get("x") or 0.0)
        win_y = float(wb.get("y") or 0.0)
        win_w = float(wb.get("width") or 1200.0)
        elements = ocr_res.get("elements") or []
        img_w = float(ocr_res.get("imageWidth") or win_w or 1.0)
        img_h = float(ocr_res.get("imageHeight") or wb.get("height") or 1.0)
        sx = img_w / max(win_w, 1.0)
        sy = img_h / max(float(wb.get("height") or 800.0), 1.0)

        # In WeChat 4.2.1 Chats view, the `+` button sits immediately left of the
        # chat header title at y ≈ 28..30 inside the main window.
        header_candidates: List[Tuple[float, float]] = []
        for el in elements:
            bbox = el.get("bbox") or {}
            cx = float((el.get("center") or {}).get("x") or 0.0) / sx
            cy = float((el.get("center") or {}).get("y") or 0.0) / sy
            bx = float(bbox.get("x") or 0.0) / sx
            txt = str(el.get("text") or "").strip()
            if 12.0 <= cy <= 50.0 and bx >= 240.0 and txt and "搜索" not in txt:
                header_candidates.append((bx, cy))
        if header_candidates:
            header_candidates.sort(key=lambda item: item[0])
            rel_x = max(180.0, header_candidates[0][0] - 40.0)
            rel_y = header_candidates[0][1]
        else:
            rel_x = min(win_w * 0.30, 464.0)
            rel_y = 28.0
        return win_x + rel_x, win_y + rel_y

    def _ensure_chats_tab(self, main_win: Dict[str, Any]) -> None:
        wb = main_win.get("bounds") or {}
        win_x = float(wb.get("x") or 0.0)
        win_y = float(wb.get("y") or 0.0)
        # Left rail `聊天` icon is consistently at (27, 118) window-relative.
        self.engine._run_native(
            ["click", "--x", f"{win_x + 27.0:.1f}", "--y", f"{win_y + 118.0:.1f}", "--skip-human-check"],
            timeout=8.0,
        )
        time.sleep(0.35)

    def _open_add_friend_window(self) -> Dict[str, Any]:
        status = self.engine._run_native(["status", "--app", "wechat"], timeout=10.0)
        wins = status.get("windows") or []
        if any("申请添加朋友" in str(w.get("title") or "") for w in wins):
            self._dismiss_wechat_modal()
            status = self.engine._run_native(["status", "--app", "wechat"], timeout=10.0)
            wins = status.get("windows") or []
        existing = next((w for w in wins if str(w.get("title") or "").strip() == "添加朋友"), None)
        if existing:
            return {"ok": True, "window": existing, "alreadyOpen": True}

        self.engine._run_native(["activate", "--app", "wechat", "--skip-human-check"], timeout=12.0)
        time.sleep(0.3)
        status = self.engine._run_native(["status", "--app", "wechat"], timeout=10.0)
        wins = status.get("windows") or []
        main_win = next((w for w in wins if w.get("isMainWindow")), wins[0] if wins else None)
        if not main_win:
            return {"ok": False, "error_code": "wechat_window_not_found", "error": "未找到微信主窗口"}

        self.verify_dir.mkdir(parents=True, exist_ok=True)
        ocr_main = self.engine._run_native(
            ["capture-ocr", "--app", "wechat", "--out", str(self.verify_dir / "wechat_main_probe.png")],
            timeout=14.0,
        )
        plus_x, plus_y = self._locate_plus_button(main_win, ocr_main)
        # Ensure we are on Chats tab if `通讯录管理` is visible (Contacts tab hides `+`).
        joined_top = " ".join(str(el.get("text") or "") for el in (ocr_main.get("elements") or [])[:12])
        if "通讯录管理" in joined_top:
            self._ensure_chats_tab(main_win)
            ocr_main = self.engine._run_native(
                ["capture-ocr", "--app", "wechat", "--out", str(self.verify_dir / "wechat_main_probe.png")],
                timeout=14.0,
            )
            plus_x, plus_y = self._locate_plus_button(main_win, ocr_main)

        self.engine._run_native(
            ["click", "--x", f"{plus_x:.1f}", "--y", f"{plus_y:.1f}", "--skip-human-check"],
            timeout=8.0,
        )
        self._sleep_paced(0.45, 0.75)

        reg_x = max(0, int(round(plus_x - 105)))
        reg_y = max(0, int(round(plus_y - 10)))
        popup_ocr = self.engine._run_native(
            [
                "capture-region",
                "--x",
                str(reg_x),
                "--y",
                str(reg_y),
                "--width",
                "260",
                "--height",
                "240",
                "--out",
                str(self.verify_dir / "wechat_plus_popup.png"),
            ],
            timeout=10.0,
        )
        add_item = _find_ocr_element(popup_ocr.get("elements") or [], ["添加朋友"])
        if not add_item:
            self._dismiss_wechat_modal()
            return {
                "ok": False,
                "error_code": "add_friend_menu_not_found",
                "error": "未在微信 + 菜单中识别到「添加朋友」按钮",
                "popupOcr": [el.get("text") for el in (popup_ocr.get("elements") or [])],
            }

        sc = add_item.get("screenCenter") or {}
        click_x = float(sc.get("x") or (reg_x + float((add_item.get("center") or {}).get("x") or 95.0)))
        click_y = float(sc.get("y") or (reg_y + float((add_item.get("center") or {}).get("y") or 85.0)))
        self.engine._run_native(
            ["click", "--x", f"{click_x:.1f}", "--y", f"{click_y:.1f}", "--skip-human-check"],
            timeout=8.0,
        )
        time.sleep(0.85)

        st_after = self.engine._run_native(["status", "--app", "wechat"], timeout=10.0)
        add_win = next(
            (w for w in (st_after.get("windows") or []) if str(w.get("title") or "").strip() == "添加朋友"),
            None,
        )
        if not add_win:
            return {
                "ok": False,
                "error_code": "add_friend_window_not_opened",
                "error": "已点击「添加朋友」，但未检测到独立的「添加朋友」窗口",
            }
        return {"ok": True, "window": add_win}

    def add_friend(
        self,
        account: str,
        *,
        greeting: str = "",
        remark: str = "",
        source_channel: str = "douyin",
        source_user: str = "",
        dry_run: bool = True,
        probe_ui: bool = False,
        confirm_send: bool = False,
        force: bool = False,
        ignore_human_guard: bool = False,
        _from_funnel: bool = False,
    ) -> Dict[str, Any]:
        """Search and optionally send a WeChat friend request with full anti-ban guards."""
        will_live = bool((not dry_run) and confirm_send)
        self.engine._require("send_text_live" if will_live else "send_text_dry_run")

        valid, norm, acc_type = validate_wechat_account(account)
        if not valid:
            return {
                "ok": False,
                "error_code": "invalid_wechat_account",
                "error": f"无效的微信号或手机号格式: {account!r}（需为 6–20 位字母开头微信号或 11 位手机号）",
                "account": str(account or ""),
            }

        quota_info = {"dailyLimit": 15, "usedToday": 0, "remaining": 15, "cooldownRemainingSeconds": 0}
        if self.funnel is not None:
            guard = self.funnel.check_add_guard(norm, force=force)
            quota_info = guard.get("quota") or quota_info
            if not guard.get("allowed"):
                return {
                    "ok": False,
                    "dryRun": bool(dry_run),
                    "sent": False,
                    "status": guard.get("reason", "blocked"),
                    "error_code": guard.get("reason", "add_friend_guarded"),
                    "error": guard.get("error", "触发加好友防封保护限制"),
                    "account": norm,
                    "accountType": acc_type,
                    "quota": quota_info,
                }

        if dry_run and not probe_ui:
            return {
                "ok": True,
                "dryRun": True,
                "probeUi": False,
                "sent": False,
                "status": "dry_run_ready",
                "account": norm,
                "accountType": acc_type,
                "greeting": str(greeting or "").strip(),
                "remark": str(remark or "").strip(),
                "sourceChannel": source_channel,
                "sourceUser": source_user,
                "quota": quota_info,
            }

        blocked = self.engine._check_human_guard_for_action(
            manual_trigger=bool(probe_ui or will_live),
            ignore_human_guard=ignore_human_guard,
        )
        if blocked is not None:
            return {
                "ok": False,
                "dryRun": bool(dry_run),
                "sent": False,
                "error_code": "human_input_active",
                "error": "检测到用户正在操作键鼠，已安全让路，未执行微信加好友。",
                "humanGuard": blocked,
                "account": norm,
            }

        opened = self._open_add_friend_window()
        if not opened.get("ok"):
            return {
                "ok": False,
                "dryRun": bool(dry_run),
                "sent": False,
                "account": norm,
                **opened,
            }

        add_win = opened["window"]
        wb = add_win.get("bounds") or {}
        win_x = float(wb.get("x") or 0.0)
        win_y = float(wb.get("y") or 0.0)
        win_w = float(wb.get("width") or 360.0)
        win_h = float(wb.get("height") or 560.0)

        self.verify_dir.mkdir(parents=True, exist_ok=True)
        win_ocr = self.engine._run_native(
            [
                "capture-ocr",
                "--app",
                "wechat",
                "--window-title",
                "添加朋友",
                "--out",
                str(self.verify_dir / "wechat_add_friend_open.png"),
            ],
            timeout=12.0,
        )
        wsx, wsy = self._ocr_scale(win_ocr, win_w, win_h)
        search_box_el = _find_ocr_element(win_ocr.get("elements") or [], ["搜索微信号", "微信号或者手机号", "手机号"])
        if search_box_el:
            rx, ry = self._scaled_center(search_box_el, wsx, wsy)
            input_x = win_x + (rx or 117.0)
            input_y = win_y + (ry or 69.0)
        else:
            input_x = win_x + min(win_w * 0.35, 117.0)
            input_y = win_y + 69.0

        paste_args = [
            "app-use-paste",
            "--bundle-id",
            "com.tencent.xinWeChat",
            "--window-title",
            "添加朋友",
            "--x",
            f"{input_x:.1f}",
            "--y",
            f"{input_y:.1f}",
            "--clear",
            "--text",
            norm,
            "--submit",
            "--skip-human-check",
        ]
        # Focus the Add Friend input explicitly before pasting so newly opened windows accept input reliably.
        self.engine._run_native(
            ["click", "--x", f"{input_x:.1f}", "--y", f"{input_y:.1f}", "--skip-human-check"],
            timeout=8.0,
        )
        time.sleep(0.2)
        paste_res = self.engine._run_native(paste_args, timeout=15.0)
        if not paste_res.get("ok"):
            self._dismiss_wechat_modal()
            return {
                "ok": False,
                "dryRun": bool(dry_run),
                "sent": False,
                "error_code": "add_friend_paste_failed",
                "error": paste_res.get("error") or "向「添加朋友」搜索框粘贴账号失败",
                "native": paste_res,
                "account": norm,
            }

        time.sleep(1.1)
        # Check if WeChat requires clicking the green `搜索` button or `搜索：<norm>` row.
        slug = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]
        lookup_shot = self.verify_dir / f"wechat_add_{slug}.png"
        lookup_ocr = self.engine._run_native(
            [
                "capture-ocr",
                "--app",
                "wechat",
                "--window-title",
                "添加朋友",
                "--out",
                str(lookup_shot),
            ],
            timeout=12.0,
        )
        lsx, lsy = self._ocr_scale(lookup_ocr, win_w, win_h)
        lookup_elems = lookup_ocr.get("elements") or []
        lookup_texts = [str(el.get("text") or "").strip() for el in lookup_elems]
        classified = classify_wechat_add_lookup_ocr(lookup_texts, lookup_elems)

        if classified["status"] == "unknown":
            # Try clicking explicit `搜索` button if still on initial query form.
            search_btn = _find_ocr_element(lookup_elems, ["搜索"])
            if search_btn:
                sbx, sby = self._scaled_center(search_btn, lsx, lsy)
                if sbx > win_w * 0.65:
                    self.engine._run_native(
                        [
                            "click",
                            "--x",
                            f"{win_x + sbx:.1f}",
                            "--y",
                            f"{win_y + sby:.1f}",
                            "--skip-human-check",
                        ],
                        timeout=8.0,
                    )
                    time.sleep(1.2)
                    lookup_ocr = self.engine._run_native(
                        [
                            "capture-ocr",
                            "--app",
                            "wechat",
                            "--window-title",
                            "添加朋友",
                            "--out",
                            str(lookup_shot),
                        ],
                        timeout=12.0,
                    )
                    lsx, lsy = self._ocr_scale(lookup_ocr, win_w, win_h)
                    lookup_elems = lookup_ocr.get("elements") or []
                    lookup_texts = [str(el.get("text") or "").strip() for el in lookup_elems]
                    classified = classify_wechat_add_lookup_ocr(lookup_texts, lookup_elems)

        lookup_status = classified["status"]
        clean_remark = str(remark or "").strip()
        if not clean_remark and str(source_channel or "").strip().lower() == "douyin":
            clean_remark = f"抖音引流-{source_user.strip()}" if str(source_user or "").strip() else "抖音引流"

        if lookup_status == "already_friend" and (not probe_ui) and (not dry_run) and confirm_send:
            remark_updated = False
            final_shot = lookup_shot
            if clean_remark:
                rem_trigger = _find_ocr_element(lookup_elems, ["添加备注名"])
                if rem_trigger:
                    rrx, rry = self._scaled_center(rem_trigger, lsx, lsy)
                    rx_pt = win_x + (rrx or 140.0)
                    ry_pt = win_y + (rry or 190.0)
                else:
                    rem_lbl = _find_ocr_element(lookup_elems, ["备注"])
                    if rem_lbl:
                        rrx, rry = self._scaled_center(rem_lbl, lsx, lsy)
                        rx_pt = win_x + (rrx or 60.0) + 100.0
                        ry_pt = win_y + (rry or 190.0)
                    else:
                        rx_pt = None
                        ry_pt = None
                if rx_pt is not None and ry_pt is not None:
                    self.engine._run_native(["activate", "--app", "wechat", "--skip-human-check"], timeout=8.0)
                    self._sleep_paced(0.25, 0.45)
                    self.engine._run_native(
                        ["click", "--x", f"{rx_pt:.1f}", "--y", f"{ry_pt:.1f}", "--skip-human-check"],
                        timeout=8.0,
                    )
                    time.sleep(0.3)
                    self.engine._run_native(
                        [
                            "app-use-paste",
                            "--bundle-id",
                            "com.tencent.xinWeChat",
                            "--window-title",
                            "添加朋友",
                            "--x",
                            f"{rx_pt:.1f}",
                            "--y",
                            f"{ry_pt:.1f}",
                            "--clear",
                            "--text",
                            clean_remark,
                            "--submit",
                            "--skip-human-check",
                        ],
                        timeout=12.0,
                    )
                    time.sleep(0.6)
                    remark_shot = self.verify_dir / f"wechat_add_{slug}_remark_set.png"
                    rem_ocr = self.engine._run_native(
                        [
                            "capture-ocr",
                            "--app",
                            "wechat",
                            "--window-title",
                            "添加朋友",
                            "--out",
                            str(remark_shot),
                        ],
                        timeout=12.0,
                    )
                    rem_texts = [str(el.get("text") or "").strip() for el in (rem_ocr.get("elements") or [])]
                    if rem_texts:
                        lookup_texts = rem_texts
                    if remark_shot.is_file():
                        final_shot = remark_shot
                    remark_updated = any((clean_remark in t) or ("抖音引流" in t) for t in rem_texts)

            self._dismiss_wechat_modal()
            clean_greeting = str(greeting or "").strip()
            if self.funnel is not None and not _from_funnel:
                try:
                    self.funnel.record_direct_wechat_add(
                        norm,
                        remark=clean_remark,
                        greeting=clean_greeting,
                        source_channel=source_channel,
                        source_user=source_user,
                        status="wechat_already_friend",
                    )
                except Exception:
                    pass
            return {
                "ok": True,
                "dryRun": False,
                "probeUi": False,
                "sent": False,
                "status": "already_friend",
                "lookupStatus": lookup_status,
                "matchedCue": classified.get("matchedCue") or "",
                "account": norm,
                "accountType": acc_type,
                "greeting": clean_greeting,
                "remark": clean_remark,
                "remarkUpdated": remark_updated,
                "sourceChannel": source_channel,
                "sourceUser": source_user,
                "screenshotPath": str(final_shot) if final_shot.is_file() else "",
                "ocrSample": lookup_texts[:20],
                "quota": quota_info,
            }

        if probe_ui or dry_run or (not confirm_send) or lookup_status != "candidate_found":
            self._dismiss_wechat_modal()
            ok_flag = True if (probe_ui or dry_run or lookup_status in ("already_friend", "candidate_found")) else False
            if lookup_status in ("not_found", "rate_limited"):
                ok_flag = False
            return {
                "ok": ok_flag,
                "dryRun": bool(dry_run or probe_ui or not confirm_send),
                "probeUi": bool(probe_ui),
                "sent": False,
                "status": f"probe_{lookup_status}" if (probe_ui or dry_run) else lookup_status,
                "lookupStatus": lookup_status,
                "matchedCue": classified.get("matchedCue") or "",
                "account": norm,
                "accountType": acc_type,
                "screenshotPath": str(lookup_shot) if lookup_shot.is_file() else "",
                "ocrSample": lookup_texts[:20],
                "quota": quota_info,
            }

        # Live path: click `添加到通讯录`
        act_pt = classified.get("actionPoint")
        act_rx = (float(act_pt["x"]) / max(lsx, 1e-6)) if act_pt else (win_w * 0.5)
        act_ry = (float(act_pt["y"]) / max(lsy, 1e-6)) if act_pt else (win_h * 0.55)
        self._sleep_paced(0.35, 0.75)
        self.engine._run_native(
            [
                "click",
                "--x",
                f"{win_x + act_rx:.1f}",
                "--y",
                f"{win_y + act_ry:.1f}",
                "--skip-human-check",
            ],
            timeout=8.0,
        )
        time.sleep(0.95)

        st_modal = self.engine._run_native(["status", "--app", "wechat"], timeout=8.0)
        modal_win = next(
            (w for w in (st_modal.get("windows") or []) if "申请添加朋友" in str(w.get("title") or "")),
            None,
        ) or add_win
        modal_title = str(modal_win.get("title") or "添加朋友").strip()
        mb = modal_win.get("bounds") or wb
        mx = float(mb.get("x") or win_x)
        my = float(mb.get("y") or win_y)
        mw = float(mb.get("width") or win_w)
        mh = float(mb.get("height") or win_h)

        self.engine._run_native(["activate", "--app", "wechat", "--skip-human-check"], timeout=8.0)
        time.sleep(0.25)

        modal_shot = self.verify_dir / f"wechat_add_{slug}_modal.png"
        modal_ocr = self.engine._run_native(
            [
                "capture-ocr",
                "--app",
                "wechat",
                "--window-title",
                modal_title,
                "--out",
                str(modal_shot),
            ],
            timeout=12.0,
        )
        msx, msy = self._ocr_scale(modal_ocr, mw, mh)
        modal_elems = modal_ocr.get("elements") or []
        modal_texts = [str(el.get("text") or "").strip() for el in modal_elems]

        clean_greeting = str(greeting or "").strip()
        if not clean_greeting:
            prof = {}
            if hasattr(self.engine, "tenant") and self.engine.tenant is not None:
                try:
                    prof = self.engine.tenant.get_profile() or {}
                except Exception:
                    prof = {}
            clean_greeting = compose_friend_greeting(
                "",
                business_name=str(prof.get("businessName") or ""),
                owner_name=str(prof.get("ownerName") or ""),
                douyin_user=source_user,
                source_channel=source_channel,
            )

        if clean_greeting:
            greet_lbl = _find_ocr_element(modal_elems, ["发送添加朋友申请", "验证信息", "打招呼"])
            if greet_lbl:
                grx, gry = self._scaled_center(greet_lbl, msx, msy)
                gx = mx + (grx or 140.0)
                gy = my + (gry or 74.0) + 41.0
                self._sleep_paced(0.35, 0.70)
                self.engine._run_native(
                    ["click", "--x", f"{gx:.1f}", "--y", f"{gy:.1f}", "--skip-human-check"],
                    timeout=8.0,
                )
                time.sleep(0.15)
                self.engine._run_native(
                    [
                        "app-use-paste",
                        "--bundle-id",
                        "com.tencent.xinWeChat",
                        "--window-title",
                        modal_title,
                        "--x",
                        f"{gx:.1f}",
                        "--y",
                        f"{gy:.1f}",
                        "--clear",
                        "--text",
                        clean_greeting,
                        "--skip-human-check",
                    ],
                    timeout=12.0,
                )

        if clean_remark:
            # Re-capture OCR after greeting input because WeChat inserts `设为常用申请语` and shifts `备注` down.
            if clean_greeting and modal_title == "申请添加朋友":
                time.sleep(0.3)
                modal_ocr = self.engine._run_native(
                    [
                        "capture-ocr",
                        "--app",
                        "wechat",
                        "--window-title",
                        modal_title,
                        "--out",
                        str(modal_shot),
                    ],
                    timeout=12.0,
                )
                msx, msy = self._ocr_scale(modal_ocr, mw, mh)
                modal_elems = modal_ocr.get("elements") or []
                modal_texts = [str(el.get("text") or "").strip() for el in modal_elems]

            rem_lbl = _find_ocr_element(modal_elems, ["设置备注", "备注名", "备注"])
            if rem_lbl:
                rrx, rry = self._scaled_center(rem_lbl, msx, msy)
                rx_pt = mx + (rrx or 140.0)
                ry_pt = my + (rry or 228.0) + 40.0
                self._sleep_paced(0.35, 0.70)
                self.engine._run_native(
                    ["click", "--x", f"{rx_pt:.1f}", "--y", f"{ry_pt:.1f}", "--skip-human-check"],
                    timeout=8.0,
                )
                time.sleep(0.15)
                self.engine._run_native(
                    [
                        "app-use-paste",
                        "--bundle-id",
                        "com.tencent.xinWeChat",
                        "--window-title",
                        modal_title,
                        "--x",
                        f"{rx_pt:.1f}",
                        "--y",
                        f"{ry_pt:.1f}",
                        "--clear",
                        "--text",
                        clean_remark,
                        "--skip-human-check",
                    ],
                    timeout=12.0,
                )

        before_submit_shot = self.verify_dir / f"wechat_add_{slug}_before_submit.png"
        if modal_title == "申请添加朋友":
            time.sleep(0.25)
            modal_ocr = self.engine._run_native(
                [
                    "capture-ocr",
                    "--app",
                    "wechat",
                    "--window-title",
                    modal_title,
                    "--out",
                    str(before_submit_shot),
                ],
                timeout=12.0,
            )
            msx, msy = self._ocr_scale(modal_ocr, mw, mh)
            modal_elems = modal_ocr.get("elements") or []
            modal_texts = [str(el.get("text") or "").strip() for el in modal_elems]

        confirm_btn = _find_ocr_element(modal_elems, ["确定", "发送"], min_y=mh * 0.65 * msy)
        if not confirm_btn:
            self._dismiss_wechat_modal()
            return {
                "ok": False,
                "dryRun": False,
                "sent": False,
                "error_code": "confirm_button_not_found",
                "error": "未在好友申请弹窗中找到「确定/发送」按钮",
                "account": norm,
                "ocrSample": modal_texts[:20],
            }

        crx, cry = self._scaled_center(confirm_btn, msx, msy)
        self._sleep_paced(0.4, 0.85)
        self.engine._run_native(["activate", "--app", "wechat", "--skip-human-check"], timeout=8.0)
        time.sleep(0.15)
        self.engine._run_native(
            [
                "click",
                "--x",
                f"{mx + (crx or mw * 0.7):.1f}",
                "--y",
                f"{my + (cry or mh * 0.94):.1f}",
                "--skip-human-check",
            ],
            timeout=8.0,
        )
        time.sleep(1.2)

        # Verify post-submit status.
        after_status = self.engine._run_native(["status", "--app", "wechat"], timeout=8.0)
        still_open = any(modal_title in str(w.get("title") or "") for w in (after_status.get("windows") or []))
        post_texts: List[str] = []
        if still_open and modal_title == "申请添加朋友":
            post_ocr = self.engine._run_native(
                ["capture-ocr", "--app", "wechat", "--window-title", modal_title, "--out", str(modal_shot)],
                timeout=10.0,
            )
            post_texts = [str(el.get("text") or "").strip() for el in (post_ocr.get("elements") or [])]
            post_class = classify_wechat_add_lookup_ocr(post_texts, post_ocr.get("elements") or [])
            if post_class["status"] == "rate_limited":
                self._dismiss_wechat_modal()
                return {
                    "ok": False,
                    "dryRun": False,
                    "sent": False,
                    "status": "wechat_rate_limited",
                    "error_code": "wechat_rate_limited",
                    "error": "微信提示操作过于频繁，请稍后再试。",
                    "account": norm,
                    "ocrSample": post_texts[:20],
                }
            # Retry clicking refreshed `确定` once if the separate apply window stayed open.
            retry_psx, retry_psy = self._ocr_scale(post_ocr, mw, mh)
            retry_confirm = _find_ocr_element(post_ocr.get("elements") or [], ["确定", "发送"], min_y=mh * 0.65 * retry_psy)
            if retry_confirm:
                rcrx, rcry = self._scaled_center(retry_confirm, retry_psx, retry_psy)
                self.engine._run_native(["activate", "--app", "wechat", "--skip-human-check"], timeout=8.0)
                time.sleep(0.15)
                self.engine._run_native(
                    [
                        "click",
                        "--x",
                        f"{mx + rcrx:.1f}",
                        "--y",
                        f"{my + rcry:.1f}",
                        "--skip-human-check",
                    ],
                    timeout=8.0,
                )
                time.sleep(1.2)
                after_retry = self.engine._run_native(["status", "--app", "wechat"], timeout=8.0)
                still_open = any(modal_title in str(w.get("title") or "") for w in (after_retry.get("windows") or []))
            if still_open:
                self._dismiss_wechat_modal()
                return {
                    "ok": False,
                    "dryRun": False,
                    "sent": False,
                    "status": "submit_not_confirmed",
                    "error_code": "submit_not_confirmed",
                    "error": "已填入验证语与备注并点击「确定」，但「申请添加朋友」窗口未关闭，请核实截图。",
                    "account": norm,
                    "screenshotPath": str(before_submit_shot) if before_submit_shot.is_file() else str(modal_shot),
                    "ocrSample": post_texts[:20],
                }
        elif still_open:
            post_ocr = self.engine._run_native(
                ["capture-ocr", "--app", "wechat", "--window-title", modal_title, "--out", str(modal_shot)],
                timeout=10.0,
            )
            post_texts = [str(el.get("text") or "").strip() for el in (post_ocr.get("elements") or [])]
            post_class = classify_wechat_add_lookup_ocr(post_texts, post_ocr.get("elements") or [])
            if post_class["status"] == "rate_limited":
                self._dismiss_wechat_modal()
                return {
                    "ok": False,
                    "dryRun": False,
                    "sent": False,
                    "status": "wechat_rate_limited",
                    "error_code": "wechat_rate_limited",
                    "error": "微信提示操作过于频繁，请稍后再试。",
                    "account": norm,
                    "ocrSample": post_texts[:20],
                }
        self._dismiss_wechat_modal()

        if self.funnel is not None and not _from_funnel:
            try:
                self.funnel.record_direct_wechat_add(
                    norm,
                    remark=clean_remark,
                    greeting=clean_greeting,
                    source_channel=source_channel,
                    source_user=source_user,
                    status="wechat_friend_requested",
                )
            except Exception:
                pass

        return {
            "ok": True,
            "dryRun": False,
            "sent": True,
            "status": "wechat_friend_requested",
            "lookupStatus": lookup_status,
            "account": norm,
            "accountType": acc_type,
            "greeting": clean_greeting,
            "remark": clean_remark,
            "sourceChannel": source_channel,
            "sourceUser": source_user,
            "screenshotPath": str(before_submit_shot) if before_submit_shot.is_file() else (str(modal_shot) if modal_shot.is_file() else ""),
            "postOcrSample": post_texts[:15],
        }


class DouyinWeChatFunnel:
    """Persistent state store & orchestrator for Douyin DM -> WeChat Friend Acquisition."""

    def __init__(self, engine: Any, *, state_path: Path) -> None:
        self.engine = engine
        self.state_path = Path(state_path)
        self.adder = WeChatFriendAdder(engine, funnel=self)
        self._state = self._load_state()

    def _default_config(self) -> Dict[str, Any]:
        return {
            "replyTemplate": "你好，方便发一下你的微信号吗？这边加你发详细资料和方案～",
            "followupTemplate": "这边在微信上发资料和演示更方便，直接发我一下你的微信号就行～",
            "ackTemplate": "收到啦，这边马上加你微信，注意通过一下好友申请～",
            "wechatGreetingTemplate": "你好呀，我是{businessName}的{ownerName}，刚在抖音看到你发来的消息，这边加你微信详聊～",
            "wechatRemarkPrefix": "抖音引流-",
            "dailyAddLimit": 15,
            "addCooldownSeconds": 90,
            "useKnowledgeBaseReply": True,
        }

    @staticmethod
    def get_sop_workflow() -> Dict[str, Any]:
        """Return the standardized Douyin acquisition -> WeChat diversion SOP workflow."""
        return dict(DOUYIN_TO_WECHAT_SOP_WORKFLOW)

    def _default_state(self) -> Dict[str, Any]:
        return {
            "schema": "openbot.douyin-wechat-funnel/1",
            "updatedAt": _utc_iso_now(),
            "config": self._default_config(),
            "dailyStats": {},
            "lastWechatAddAt": 0.0,
            "leads": {},
            "events": [],
        }

    def _load_state(self) -> Dict[str, Any]:
        base = self._default_state()
        if not self.state_path.is_file():
            return base
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                cfg = dict(self._default_config())
                if isinstance(parsed.get("config"), dict):
                    cfg.update(parsed["config"])
                # Auto-migrate legacy v1/v2 defaults so existing host installs receive the Douyin remark prefix & self-intro template.
                defaults = self._default_config()
                if str(cfg.get("wechatRemarkPrefix") or "").strip() == "[抖音]":
                    cfg["wechatRemarkPrefix"] = defaults["wechatRemarkPrefix"]
                if str(cfg.get("wechatGreetingTemplate") or "").strip() == "你好，刚在抖音看到你咨询，加个微信发你详细资料":
                    cfg["wechatGreetingTemplate"] = defaults["wechatGreetingTemplate"]
                base.update(parsed)
                base["config"] = cfg
                base.setdefault("dailyStats", {})
                base.setdefault("leads", {})
                base.setdefault("events", [])
                return base
        except Exception:
            pass
        return base

    def _save_state(self) -> None:
        self._state["updatedAt"] = _utc_iso_now()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_path, self._state)

    def _record_event(self, kind: str, detail: Dict[str, Any]) -> None:
        events = list(self._state.get("events") or [])
        events.append({"at": _utc_iso_now(), "kind": kind, **detail})
        if len(events) > 200:
            events = events[-200:]
        self._state["events"] = events

    def _today_stats(self) -> Dict[str, int]:
        day = _today_key()
        all_days = self._state.setdefault("dailyStats", {})
        day_doc = all_days.setdefault(day, {"douyinReplies": 0, "wechatAdds": 0, "wechatCaptured": 0})
        return day_doc

    def check_add_guard(self, account: str, *, force: bool = False) -> Dict[str, Any]:
        cfg = self._state["config"]
        daily_limit = max(1, int(cfg.get("dailyAddLimit") or 15))
        cooldown = max(0, int(cfg.get("addCooldownSeconds") or 90))
        stats = self._today_stats()
        used = int(stats.get("wechatAdds") or 0)
        remaining = max(0, daily_limit - used)
        now_ts = time.time()
        last_ts = float(self._state.get("lastWechatAddAt") or 0.0)
        cd_rem = max(0, int(round(cooldown - (now_ts - last_ts)))) if last_ts > 0 else 0

        quota = {
            "dailyLimit": daily_limit,
            "usedToday": used,
            "remaining": remaining,
            "cooldownSeconds": cooldown,
            "cooldownRemainingSeconds": cd_rem,
        }

        if not force:
            for lead in (self._state.get("leads") or {}).values():
                if str(lead.get("wechatAccount") or "").casefold() == account.casefold():
                    if lead.get("status") in ("wechat_friend_requested", "wechat_already_friend", "wechat_connected"):
                        return {
                            "allowed": False,
                            "reason": "already_requested_or_friend",
                            "error": f"微信号 {account} 已处理过（状态：{lead.get('status')}），传 force=true 可强制重试。",
                            "quota": quota,
                        }
            if remaining <= 0:
                return {
                    "allowed": False,
                    "reason": "daily_limit_reached",
                    "error": f"今日微信加好友已达防封上限 {used}/{daily_limit}，请明日再试或调整 dailyAddLimit。",
                    "quota": quota,
                }
            if cd_rem > 0:
                return {
                    "allowed": False,
                    "reason": "cooldown_active",
                    "error": f"加好友冷却中，请等待 {cd_rem} 秒后再试。",
                    "quota": quota,
                }

        return {"allowed": True, "quota": quota}

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(updates, dict):
            return {"ok": False, "error": "updates 必须为 JSON 对象"}
        cfg = self._state["config"]
        for key in (
            "replyTemplate",
            "followupTemplate",
            "ackTemplate",
            "wechatGreetingTemplate",
            "wechatRemarkPrefix",
            "dailyAddLimit",
            "addCooldownSeconds",
            "useKnowledgeBaseReply",
        ):
            if key in updates and updates[key] is not None:
                if key in ("dailyAddLimit", "addCooldownSeconds"):
                    cfg[key] = max(0, int(updates[key]))
                elif key == "useKnowledgeBaseReply":
                    cfg[key] = bool(updates[key])
                else:
                    cfg[key] = str(updates[key]).strip()
        self._save_state()
        return {"ok": True, "config": dict(cfg)}

    def _find_lead(self, key_or_user: str) -> Optional[Dict[str, Any]]:
        clean = str(key_or_user or "").strip()
        if not clean:
            return None
        leads = self._state.get("leads") or {}
        if clean in leads:
            return leads[clean]
        for lead in leads.values():
            if clean in (str(lead.get("douyinUser") or ""), str(lead.get("wechatAccount") or "")):
                return lead
        return None

    def _upsert_lead(self, douyin_user: str) -> Dict[str, Any]:
        clean_user = str(douyin_user or "").strip() or "抖音访客"
        lead_id = "dy_" + hashlib.sha1(clean_user.encode("utf-8")).hexdigest()[:12]
        leads = self._state.setdefault("leads", {})
        if lead_id not in leads:
            leads[lead_id] = {
                "leadId": lead_id,
                "douyinUser": clean_user,
                "status": "new_message",
                "intentTier": "cold",
                "intentScore": 0,
                "lastIncoming": "",
                "lastOutgoing": "",
                "wechatAccount": "",
                "wechatAccountType": "",
                "wechatConfidence": "",
                "extractedAccounts": [],
                "replyCount": 0,
                "wechatAddAttempts": 0,
                "lastError": "",
                "crmTarget": "",
                "createdAt": _utc_iso_now(),
                "updatedAt": _utc_iso_now(),
            }
        return leads[lead_id]

    def _sync_lead_crm(self, lead: Dict[str, Any], *, note_extra: str = "") -> None:
        user = str(lead.get("douyinUser") or "抖音访客").strip()
        wx = str(lead.get("wechatAccount") or "").strip()
        remark_prefix = str((self._state.get("config") or {}).get("wechatRemarkPrefix") or "抖音引流-").strip()
        if user:
            crm_name = f"{remark_prefix}{user}" if remark_prefix.endswith("-") else f"{remark_prefix}-{user}"
        else:
            crm_name = remark_prefix.rstrip("-") or "抖音引流"

        tags = ["抖音获客", "抖音引流", "渠道:抖音", f"意向:{lead.get('intentTier', 'warm')}"]
        if wx:
            tags.append("已留微信号")
        stage = "沟通中"
        if lead.get("status") in ("wechat_friend_requested", "wechat_already_friend", "wechat_connected"):
            stage = "已加微信" if "已加微信" in getattr(self.engine.sales_crm, "stages", ()) else "方案推进"
        note_parts = [
            f"来源渠道：抖音获客（抖音引流） | 状态：{lead.get('status')}",
            f"抖音昵称：{user or '抖音访客'}",
        ]
        if wx:
            note_parts.append(f"微信号/手机号：{wx}")
        if lead.get("lastIncoming"):
            note_parts.append(f"原私信：{str(lead['lastIncoming'])[:120]}")
        if note_extra:
            note_parts.append(note_extra[:120])

        if hasattr(self.engine, "sales_crm"):
            try:
                self.engine.sales_crm.enroll_contact(
                    crm_name,
                    stage=stage,
                    note=" | ".join(note_parts)[:500],
                    alias=user or wx,
                    tags=tags,
                )
                lead["crmTarget"] = crm_name
            except Exception:
                pass

        if hasattr(self.engine, "soul_profiler") and (wx or lead.get("status") in ("wechat_friend_requested", "wechat_already_friend", "wechat_connected")):
            try:
                mem_text = f"客户来源：抖音获客（抖音引流），抖音昵称 {user or '抖音访客'}，通过账号 {wx or '待补充'} 引流至微信"
                self.engine.soul_profiler.add_memory_note(
                    crm_name,
                    mem_text,
                    category="fact",
                    source="douyin_funnel",
                )
            except Exception:
                pass

    def record_direct_wechat_add(
        self,
        account: str,
        *,
        remark: str = "",
        greeting: str = "",
        source_channel: str = "douyin",
        source_user: str = "",
        status: str = "wechat_friend_requested",
    ) -> Dict[str, Any]:
        """Persist lead, CRM profile, and memory note after a direct WeChat friend request."""
        clean_acc = str(account or "").strip()
        clean_user = str(source_user or "").strip()
        if not clean_user and remark:
            clean_user = re.sub(r"^(?:抖音引流[-_:]?|\[抖音\])", "", str(remark).strip()).strip()
        lead = self._upsert_lead(clean_user or clean_acc or "抖音访客")
        lead["wechatAccount"] = clean_acc
        lead["wechatAccountType"] = "phone" if _PHONE_VALID_RE.match(clean_acc) else "wechat_id"
        lead["wechatConfidence"] = "high"
        lead["intentTier"] = "hot"
        lead["intentScore"] = max(int(lead.get("intentScore") or 0), 92)
        lead["status"] = status
        lead["wechatAddAttempts"] = int(lead.get("wechatAddAttempts") or 0) + 1
        lead["lastOutgoing"] = str(greeting or lead.get("lastOutgoing") or "")[:300]
        lead["updatedAt"] = _utc_iso_now()
        self._sync_lead_crm(
            lead,
            note_extra=f"微信备注:{remark or '抖音引流'} | 验证语:{str(greeting or '')[:60]}",
        )
        stats = self._today_stats()
        stats["wechatAdds"] = int(stats.get("wechatAdds") or 0) + 1
        self._state["lastWechatAddAt"] = time.time()
        self._record_event(
            "wechat_add_sent",
            {"account": clean_acc, "douyinUser": clean_user, "remark": remark, "sourceChannel": source_channel},
        )
        self._save_state()
        return dict(lead)

    @staticmethod
    def _score_intent(text: str) -> Tuple[str, int]:
        low = _normalize_nfkc(text).casefold()
        score = 0
        for kw in _LEAD_HOT_EXTRA_CUES:
            if kw in low:
                score += 35
        for kw in _LEAD_WARM_EXTRA_CUES:
            if kw in low:
                score += 18
        if "?" in text or "？" in text:
            score += 10
        score = min(100, score)
        tier = "hot" if score >= 50 else ("warm" if score >= 20 else "cold")
        return tier, score

    def ingest_messages(
        self,
        messages: Iterable[Dict[str, Any]],
        *,
        douyin_user: str = "",
        source: str = "manual",
        sync_crm: bool = True,
    ) -> Dict[str, Any]:
        """Ingest Douyin DM/comment messages, extract WeChat accounts, and update funnel/CRM."""
        msg_list = [m for m in (messages or []) if isinstance(m, dict)]
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        generic_senders = {"我", "对方", "抖音用户", "用户"}
        last_user = douyin_user.strip()
        for msg in msg_list:
            direction = str(msg.get("direction") or "incoming").strip().lower()
            sender = str(msg.get("sender") or "").strip()
            if direction == "outgoing":
                key_user = douyin_user.strip() or last_user or "抖音访客"
            else:
                if sender and sender not in generic_senders:
                    key_user = sender
                else:
                    key_user = douyin_user.strip() or "抖音访客"
                last_user = key_user
            grouped.setdefault(key_user, []).append(msg)

        updated_leads: List[Dict[str, Any]] = []
        captured_accounts: List[Dict[str, Any]] = []
        stats = self._today_stats()

        for user_name, thread in grouped.items():
            lead = self._upsert_lead(user_name)
            incoming_texts = [
                _normalize_nfkc(str(m.get("text") or ""))
                for m in thread
                if str(m.get("direction") or "incoming").lower() != "outgoing" and str(m.get("text") or "").strip()
            ]
            outgoing_texts = [
                _normalize_nfkc(str(m.get("text") or ""))
                for m in thread
                if str(m.get("direction") or "").lower() == "outgoing" and str(m.get("text") or "").strip()
            ]
            if incoming_texts:
                lead["lastIncoming"] = incoming_texts[-1][:300]
                tier, score = self._score_intent(" ".join(incoming_texts))
                if score >= int(lead.get("intentScore") or 0):
                    lead["intentTier"] = tier
                    lead["intentScore"] = score
            if outgoing_texts:
                lead["lastOutgoing"] = outgoing_texts[-1][:300]

            extracted = extract_wechat_accounts_from_messages(thread, douyin_user=user_name)
            if extracted:
                lead["extractedAccounts"] = extracted
                top = extracted[0]
                was_empty = not bool(lead.get("wechatAccount"))
                lead["wechatAccount"] = top["account"]
                lead["wechatAccountType"] = top["accountType"]
                lead["wechatConfidence"] = top["confidence"]
                lead["intentTier"] = "hot"
                lead["intentScore"] = max(int(lead.get("intentScore") or 0), 92)
                if lead.get("status") in ("new_message", "replied_asking_wechat"):
                    lead["status"] = "wechat_captured"
                if was_empty:
                    stats["wechatCaptured"] = int(stats.get("wechatCaptured") or 0) + 1
                captured_accounts.extend(extracted)
            lead["updatedAt"] = _utc_iso_now()
            if sync_crm and (lead.get("wechatAccount") or lead.get("intentTier") in ("hot", "warm")):
                self._sync_lead_crm(lead, note_extra=f"source={source}")
            updated_leads.append(dict(lead))

        self._record_event("ingest", {"source": source, "leadCount": len(updated_leads), "capturedCount": len(captured_accounts)})
        self._save_state()
        return {
            "ok": True,
            "source": source,
            "processedLeads": len(updated_leads),
            "capturedCount": len(captured_accounts),
            "extractedWechatAccounts": captured_accounts,
            "leads": updated_leads,
        }

    def suggest_reply(
        self,
        douyin_user: str,
        *,
        incoming_text: str = "",
        surface: str = "dm",
    ) -> Dict[str, Any]:
        lead = self._find_lead(douyin_user)
        text_in = str(incoming_text or (lead.get("lastIncoming") if lead else "") or "").strip()
        cfg = self._state["config"]

        stage = "ask_wechat"
        if lead:
            if lead.get("wechatAccount"):
                stage = "ack_wechat_captured"
            elif int(lead.get("replyCount") or 0) >= 1:
                stage = "followup_ask_wechat"

        kb_answer = ""
        if cfg.get("useKnowledgeBaseReply", True) and text_in and stage != "ack_wechat_captured":
            try:
                if hasattr(self.engine, "kb_search"):
                    hits = (self.engine.kb_search(text_in, limit=1) or {}).get("results") or []
                    if hits:
                        kb_answer = str(hits[0].get("answer") or hits[0].get("content") or "").strip()
            except Exception:
                pass

        composed = compose_douyin_lead_reply(text_in, stage=stage, kb_answer=kb_answer, config=cfg)
        return {
            "ok": True,
            "douyinUser": douyin_user,
            "surface": surface,
            "leadId": lead["leadId"] if lead else "",
            **composed,
        }

    def reply_lead(
        self,
        douyin_user: str,
        *,
        text: str = "",
        surface: str = "dm",
        mode: str = "auto",
        dry_run: bool = True,
        confirm_send: bool = False,
    ) -> Dict[str, Any]:
        lead = self._upsert_lead(douyin_user)
        reply_text = str(text or "").strip()
        stage = "custom"
        if not reply_text:
            sug = self.suggest_reply(douyin_user, incoming_text=lead.get("lastIncoming") or "", surface=surface)
            reply_text = sug["text"]
            stage = sug["stage"]

        send_res = self.engine.omni_send(
            "douyin",
            douyin_user,
            reply_text,
            mode=mode,
            dry_run=dry_run,
            confirm_send=confirm_send,
            surface=surface,
        )
        if send_res.get("ok") and send_res.get("sent"):
            lead["replyCount"] = int(lead.get("replyCount") or 0) + 1
            lead["lastOutgoing"] = reply_text[:300]
            if not lead.get("wechatAccount"):
                lead["status"] = "replied_asking_wechat"
            lead["updatedAt"] = _utc_iso_now()
            stats = self._today_stats()
            stats["douyinReplies"] = int(stats.get("douyinReplies") or 0) + 1
            self._record_event("douyin_reply", {"douyinUser": douyin_user, "stage": stage, "sent": True})
            self._save_state()

        return {
            **send_res,
            "leadId": lead["leadId"],
            "douyinUser": lead["douyinUser"],
            "stage": stage,
            "leadStatus": lead["status"],
        }

    def add_lead_to_wechat(
        self,
        lead_key_or_account: str,
        *,
        greeting: str = "",
        remark: str = "",
        dry_run: bool = True,
        probe_ui: bool = False,
        confirm_send: bool = False,
        force: bool = False,
        ignore_human_guard: bool = False,
    ) -> Dict[str, Any]:
        lead = self._find_lead(lead_key_or_account)
        account = ""
        douyin_user = ""
        if lead:
            account = str(lead.get("wechatAccount") or "").strip()
            douyin_user = str(lead.get("douyinUser") or "").strip()
            if not account:
                ok_raw, norm_raw, _ = validate_wechat_account(lead_key_or_account)
                if ok_raw:
                    account = norm_raw
        else:
            account = str(lead_key_or_account or "").strip()

        if not account:
            return {
                "ok": False,
                "error_code": "missing_wechat_account",
                "error": f"线索 {lead_key_or_account!r} 尚未提取到微信号，请先在抖音私信引导对方发送微信号。",
            }

        cfg = self._state["config"]
        prof = {}
        if hasattr(self.engine, "tenant") and self.engine.tenant is not None:
            try:
                prof = self.engine.tenant.get_profile() or {}
            except Exception:
                prof = {}
        final_greeting = str(greeting or "").strip() or compose_friend_greeting(
            str(cfg.get("wechatGreetingTemplate") or ""),
            business_name=str(prof.get("businessName") or ""),
            owner_name=str(prof.get("ownerName") or ""),
            douyin_user=douyin_user,
            source_channel="douyin",
        )
        prefix = str(cfg.get("wechatRemarkPrefix") or "抖音引流-").strip()
        if str(remark or "").strip():
            final_remark = str(remark).strip()
        elif douyin_user:
            final_remark = f"{prefix}{douyin_user}" if prefix.endswith("-") else f"{prefix}-{douyin_user}"
        else:
            final_remark = prefix.rstrip("-") or "抖音引流"

        res = self.adder.add_friend(
            account,
            greeting=final_greeting,
            remark=final_remark,
            source_channel="douyin",
            source_user=douyin_user,
            dry_run=dry_run,
            probe_ui=probe_ui,
            confirm_send=confirm_send,
            force=force,
            ignore_human_guard=ignore_human_guard,
            _from_funnel=True,
        )

        if lead:
            lead["wechatAddAttempts"] = int(lead.get("wechatAddAttempts") or 0) + (0 if (dry_run and not probe_ui) else 1)
            lookup_st = res.get("lookupStatus") or ""
            if res.get("sent"):
                lead["status"] = "wechat_friend_requested"
                lead["lastError"] = ""
            elif lookup_st == "already_friend":
                lead["status"] = "wechat_already_friend"
            elif lookup_st == "not_found":
                lead["status"] = "wechat_not_found"
                lead["lastError"] = "该微信号不存在或账号状态异常"
            elif lookup_st == "rate_limited" or res.get("error_code") == "wechat_rate_limited":
                lead["status"] = "wechat_rate_limited"
                lead["lastError"] = res.get("error") or "操作过于频繁"
            lead["updatedAt"] = _utc_iso_now()
            self._sync_lead_crm(lead, note_extra=f"add_status={lead['status']}")

        if res.get("sent"):
            stats = self._today_stats()
            stats["wechatAdds"] = int(stats.get("wechatAdds") or 0) + 1
            self._state["lastWechatAddAt"] = time.time()
            self._record_event("wechat_add_sent", {"account": account, "douyinUser": douyin_user})

        self._save_state()
        return {
            **res,
            "leadId": lead["leadId"] if lead else "",
            "douyinUser": douyin_user,
        }

    def run_cycle(
        self,
        *,
        target: str = "",
        limit: int = 20,
        auto_reply: bool = False,
        auto_add_wechat: bool = False,
        dry_run: bool = True,
        probe_ui: bool = False,
        confirm_send: bool = False,
        launch_if_needed: bool = False,
    ) -> Dict[str, Any]:
        """Run one end-to-end Douyin DM read -> extract WeChat -> reply -> WeChat add cycle."""
        read_res = self.engine.omni_read_messages(
            "douyin",
            target=target,
            limit=limit,
            launch_if_needed=launch_if_needed,
        )
        if not read_res.get("ok"):
            return {
                "ok": False,
                "stage": "read_douyin",
                "error_code": read_res.get("error_code") or "douyin_read_failed",
                "error": read_res.get("error") or "读取抖音私信失败",
                "readResult": read_res,
            }
        if read_res.get("loginRequired"):
            return {
                "ok": False,
                "stage": "douyin_login_required",
                "loginRequired": True,
                "error_code": "douyin_login_required",
                "error": "抖音尚未登录，请先在抖音窗口扫码登录后重试。",
                "readResult": read_res,
            }

        cur_user = str(target or read_res.get("currentChatTitle") or "").strip()
        messages = list(read_res.get("messages") or [])
        sessions = list(read_res.get("sessions") or [])

        # If drawer showed session list previews without active conversation, ingest previews too.
        ingest_items = list(messages)
        if not ingest_items and sessions:
            for s in sessions:
                preview = str(s.get("preview") or "").strip()
                title = str(s.get("title") or "").strip()
                if title and preview:
                    ingest_items.append({"sender": title, "direction": "incoming", "text": preview})

        ingest_res = self.ingest_messages(
            ingest_items,
            douyin_user=cur_user if (messages and read_res.get("source") == "desktop_rpa") else "",
            source=read_res.get("source") or "douyin_live",
            sync_crm=True,
        )

        reply_actions: List[Dict[str, Any]] = []
        add_actions: List[Dict[str, Any]] = []

        for lead_doc in ingest_res.get("leads") or []:
            user = str(lead_doc.get("douyinUser") or "")
            if auto_reply and not lead_doc.get("wechatAccount"):
                reply_actions.append(
                    self.reply_lead(
                        user,
                        surface="dm",
                        dry_run=dry_run,
                        confirm_send=confirm_send,
                    )
                )
            if auto_add_wechat and lead_doc.get("wechatAccount") and lead_doc.get("status") == "wechat_captured":
                add_actions.append(
                    self.add_lead_to_wechat(
                        lead_doc["leadId"],
                        dry_run=dry_run,
                        probe_ui=probe_ui,
                        confirm_send=confirm_send,
                    )
                )

        return {
            "ok": True,
            "dryRun": bool(dry_run),
            "source": read_res.get("source") or "",
            "currentChatTitle": cur_user,
            "sessionCount": len(sessions),
            "messageCount": len(messages),
            "ingest": ingest_res,
            "replyActions": reply_actions,
            "addActions": add_actions,
            "overview": self.overview(),
        }

    def overview(self) -> Dict[str, Any]:
        leads = list((self._state.get("leads") or {}).values())
        leads.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        cfg = self._state["config"]
        stats = self._today_stats()
        daily_limit = max(1, int(cfg.get("dailyAddLimit") or 15))
        used_today = int(stats.get("wechatAdds") or 0)

        counts = {
            "total": len(leads),
            "awaitingWechat": sum(1 for l in leads if l.get("status") in ("new_message", "replied_asking_wechat")),
            "wechatCaptured": sum(1 for l in leads if bool(l.get("wechatAccount"))),
            "friendRequested": sum(1 for l in leads if l.get("status") == "wechat_friend_requested"),
            "alreadyFriendOrConnected": sum(1 for l in leads if l.get("status") in ("wechat_already_friend", "wechat_connected")),
        }

        return {
            "ok": True,
            "config": dict(cfg),
            "today": _today_key(),
            "dailyStats": dict(stats),
            "quota": {
                "dailyLimit": daily_limit,
                "usedToday": used_today,
                "remaining": max(0, daily_limit - used_today),
                "cooldownSeconds": int(cfg.get("addCooldownSeconds") or 90),
            },
            "counts": counts,
            "leads": leads[:80],
            "recentEvents": list(self._state.get("events") or [])[-20:],
            "sopWorkflow": self.get_sop_workflow(),
        }
