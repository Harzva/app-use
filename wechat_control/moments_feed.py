"""Pure parsing helpers for the WeChat Moments (朋友圈) feed captured by Vision OCR.

WeChat 4.2.0 for macOS exposes no accessibility children for the Moments view (`ax-tree`
returns the bare AXWindow), so the feed is read from `capture-ocr` output. Verified layout
(zh-CN, 1x window, 1579 wide):

    发现列表 │ 朋友圈内容区
    朋友圈   │ [封面，右下角是号主昵称]                 （滚动后变成吸顶标题「朋友圈」）
    视频号   │   头像  作者                     ⌄
    搜一搜   │         正文行 … 「全文」
    …        │         链接卡片标题（缩进）
             │         时间 来源                        ··      ← 页脚
             │         ♡ 点赞人, 点赞人                          ┐ 点赞与评论
             │         评论人：内容 / 评论人 回复 某人：内容       ┘ 同在一个浅灰框

本模块不做任何界面操作：输入是一帧 OCR 结果，输出是结构化的帖子列表，便于单测。
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

POSTS_SCHEMA = "openbot.wechat-moments-posts/1"

# 发现列表 = 左侧导航栏(58) + 列表栏(430)，它右侧才是朋友圈内容区
DISCOVER_PANE_LEFT = 470.0
# 滚动后出现的吸顶标题栏高度，其下才是可见信息流
STICKY_HEADER_BOTTOM = 50.0
# 首屏封面底部（读不到号主昵称时的兜底）
COVER_BOTTOM_FALLBACK = 318.0
# 默认正文列左边缘（实测 1579 宽窗口）；实际以页脚时间戳的左边缘为准
DEFAULT_COL_LEFT = 827.0
# 页脚行右侧「··」按钮相对正文列右边缘的内缩量
MORE_BUTTON_INSET = 9.0

DISCOVER_MARKERS = ("朋友圈", "视频号", "搜一搜", "游戏", "小程序")

_TIME_TOKEN_RE = re.compile(
    r"^(刚刚|\d+\s*(?:秒钟?|分钟|小时|天|周|个月|年)前|昨天|前天"
    r"|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*月\s*\d{1,2}\s*日)"
)
_REL_DELTA_RE = re.compile(r"^(\d+)(秒钟?|分钟|小时|天|周|个月|年)前$")
_REL_UNITS = {
    "秒": 1, "秒钟": 1, "分钟": 60, "小时": 3600, "天": 86400,
    "周": 7 * 86400, "个月": 30 * 86400, "年": 365 * 86400,
}
# 页脚右侧的「··」：Vision 常读成两个圆点
_MORE_DOTS_RE = re.compile(r"^[•·．。.‧∘]{2,4}$")
_EXPAND_RE = re.compile(r"^(全文|收起|展开)$")
_FOLDED_RE = re.compile(r"^余下\s*\d+\s*条\s*[>›》]?$")
_AD_LABELS = ("广告", "推广", "Sponsored")
_SOURCE_HINTS = ("公众号", "视频号", "·", "•", "|", "｜", "音乐", "位置", "来自")
# 评论输入框打开时出现在页脚下方的两行，不是点赞
_COMMENT_INPUT_TEXT = "评论"
_COMMENT_SEND_SUFFIX = "发送"
# 心形图标：Vision 常把 ♡ 读成 V / v / d / ⑦。符号类直接剥掉；字母只有后面紧跟空格或汉字时才当成图标，
# 避免把 Victor 这类昵称砍掉首字母。
_HEART_SYMBOL_CATEGORIES = ("So", "Sm", "No", "Sk", "Cf", "Mn")
_HEART_LETTERS = "vVdDuUwW"
_COMMENT_RE = re.compile(
    r"^(?P<who>[^：:]{1,40}?)\s*(?:[（(]?(?:作者|朋友)[)）])?\s*"
    r"(?:(?:回复|回答)\s*(?P<to>[^：:]{1,40}?))?\s*[：:]\s*(?P<text>.+)$"
)
# 「··」按钮离正文列左边缘约 440px；正文行里被单独读出来的「。。」不算页脚
_MORE_BUTTON_MIN_OFFSET = 380.0


def _is_cjk(ch: str) -> bool:
    return "\u3400" <= ch <= "\u9fff"


def normalize_key_text(text: str) -> str:
    """去掉空白、标点和表情，只留字母数字汉字，用于比对与生成帖子指纹。"""
    compact = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s\W_]+", "", compact, flags=re.UNICODE).upper()


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0


def normalize_ocr_elements(cap: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """把 capture-ocr 的像素坐标换算成窗口内的点坐标（Retina 下截图是 2 倍像素）。"""
    bounds = cap.get("windowBounds") or {}
    win_w = float(bounds.get("width") or 0.0) or float(cap.get("imageWidth") or 1.0)
    win_h = float(bounds.get("height") or 0.0) or float(cap.get("imageHeight") or 1.0)
    sx = float(cap.get("imageWidth") or win_w) / max(win_w, 1.0)
    sy = float(cap.get("imageHeight") or win_h) / max(win_h, 1.0)
    out: List[Dict[str, Any]] = []
    for el in cap.get("elements") or []:
        text = str(el.get("text") or "").strip()
        if not text:
            continue
        box = el.get("bbox") or {}
        center = el.get("center") or {}
        out.append({
            "text": text,
            "x": float(box.get("x", 0.0) or 0.0) / sx,
            "y": float(center.get("y", 0.0) or 0.0) / sy,
            "w": float(box.get("width", 0.0) or 0.0) / sx,
            "h": float(box.get("height", 0.0) or 0.0) / sy,
            "confidence": float(el.get("confidence") or 0.0),
        })
    return out, {"width": win_w, "height": win_h, "scaleX": sx, "scaleY": sy}


def group_rows(elements: List[Dict[str, Any]], tol: float = 9.0) -> List[Dict[str, Any]]:
    """把同一行上的若干 OCR 片段合并成一行（时间戳与「··」在同一行）。"""
    rows: List[Dict[str, Any]] = []
    for el in sorted(elements, key=lambda e: (e["y"], e["x"])):
        if rows and abs(el["y"] - rows[-1]["y"]) <= tol:
            row = rows[-1]
            row["els"].append(el)
            row["y"] = sum(e["y"] for e in row["els"]) / len(row["els"])
        else:
            rows.append({"els": [el], "y": el["y"]})
    for row in rows:
        row["els"].sort(key=lambda e: e["x"])
        row["xmin"] = min(e["x"] for e in row["els"])
        row["xmax"] = max(e["x"] + e["w"] for e in row["els"])
        row["text"] = " ".join(e["text"] for e in row["els"])
    return rows


def parse_relative_seconds(token: str) -> Optional[float]:
    """「20小时前」「3天前」→ 距今秒数；认不出返回 None。"""
    compact = re.sub(r"\s+", "", token or "")
    if compact == "刚刚":
        return 0.0
    if compact == "昨天":
        return 86400.0
    if compact == "前天":
        return 2 * 86400.0
    match = _REL_DELTA_RE.match(compact)
    if match:
        return float(int(match.group(1)) * _REL_UNITS[match.group(2)])
    return None


def estimate_published_ts(token: str, now_ts: float) -> Optional[float]:
    """把相对时间或月日换算成大致的发布时间戳（精度取决于刻度：小时级 ±1 小时，天级 ±1 天）。"""
    delta = parse_relative_seconds(token)
    if delta is not None:
        return float(now_ts) - delta
    compact = re.sub(r"\s+", "", token or "")
    full = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", compact)
    if full:
        try:
            return datetime(int(full.group(1)), int(full.group(2)), int(full.group(3))).timestamp()
        except ValueError:
            return None
    short = re.match(r"^(\d{1,2})月(\d{1,2})日$", compact)
    if short:
        now = datetime.fromtimestamp(now_ts)
        for year in (now.year, now.year - 1):
            try:
                candidate = datetime(year, int(short.group(1)), int(short.group(2))).timestamp()
            except ValueError:
                continue
            if candidate <= now_ts + 86400.0:
                return candidate
    return None


def parse_likes_line(text: str) -> List[str]:
    """「V 心安, 苏文璐」「⑦ 心安，苏文璐」「• 心安」→ ["心安", "苏文璐"]。

    行首是点赞的心形图标，Vision 把它读成什么没有规律（V / ⑦ / • / C …），所以不枚举，
    用结构判断：第一个字符不是汉字、后面紧跟空格，就当图标剥掉；符号类字符不管后面是什么都剥掉。"""
    cleaned = (text or "").strip()
    while cleaned:
        head = cleaned[0]
        symbol = unicodedata.category(head) in _HEART_SYMBOL_CATEGORIES or head in "•·.。‧∘●○◦"
        lone_token = len(cleaned) >= 2 and head not in ",，、" and cleaned[1] in " \t"
        letter_before_cjk = head in _HEART_LETTERS and len(cleaned) >= 2 and _is_cjk(cleaned[1])
        if _is_cjk(head) or not (symbol or lone_token or letter_before_cjk):
            break
        cleaned = cleaned[1:].lstrip()
    cleaned = cleaned.strip(" ,，、;；")
    if not cleaned:
        return []
    return [name.strip() for name in re.split(r"[,，、]", cleaned) if name.strip()]


def parse_comment_line(text: str) -> Optional[Dict[str, str]]:
    """「苏文璐：好的」「心安 回复 苏文璐：哈哈」→ {author, replyTo, text}；不是评论行返回 None。"""
    match = _COMMENT_RE.match((text or "").strip())
    if not match:
        return None
    return {
        "author": match.group("who").strip(),
        "replyTo": (match.group("to") or "").strip(),
        "text": match.group("text").strip(),
    }


def _day_bucket(ts: Optional[float], token: str) -> str:
    if ts is not None:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    return normalize_key_text(token)


def post_key(author: str, text: str, time_text: str = "", published_ts: Optional[float] = None) -> str:
    """帖子指纹。朋友圈不暴露帖子 ID，只能用「作者 + 正文开头」做跨次读取的稳定标识；
    纯图或极短正文的帖子再加上发布日，避免同一个人同一天发几条时混在一起。"""
    head = normalize_key_text(text)[:24]
    base = normalize_key_text(author)
    if len(head) >= 6:
        material = f"{base}|{head}"
    else:
        material = f"{base}|{head}|{_day_bucket(published_ts, time_text)}"
    return "mom_" + hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _text_alike(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _authors_compatible(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if not (a.get("authorConfident", True) and b.get("authorConfident", True)):
        return True
    aa = normalize_key_text(a.get("author") or "")
    ab = normalize_key_text(b.get("author") or "")
    return aa == ab or _text_alike(aa, ab) >= 0.8


def _times_compatible(a: Dict[str, Any], b: Dict[str, Any], *, strict: bool, max_drift_days: float = 0.0) -> bool:
    """两条观测的发布时间是否对得上。

    同一次读取里的几帧是几秒内连续拍的，同一条帖子的时间刻度不会变——所以默认要求刻度相同，
    同一个人同一天发的两条不同帖子（都是「762天前」）也靠各自独立的页脚区分，不会被时间误并。
    `max_drift_days` 用在隔了几天之后的再次读取：「17天前」隔天会变成「18天前」。"""
    est_a = a.get("publishedEstimate")
    est_b = b.get("publishedEstimate")
    if est_a and est_b:
        if a.get("timeText") and a.get("timeText") == b.get("timeText"):
            return True
        gap = abs(datetime.fromisoformat(est_a) - datetime.fromisoformat(est_b)).total_seconds()
        # 2 小时余量吸收「20小时前」与「21小时前」这种刻度跳动
        return gap <= max(7200.0, max_drift_days * 86400.0)
    if strict:
        # 任一方缺时间：正文要几乎逐字相同才算同一条
        return _text_alike(normalize_key_text(a.get("text") or "")[:80],
                           normalize_key_text(b.get("text") or "")[:80]) >= 0.92
    return True


def _content_lines(post: Dict[str, Any]) -> List[str]:
    """帖子里可以用来和另一帧对齐的内容行：正文、缩进的链接标题、评论内容。"""
    parts: List[str] = []
    if not post.get("authorConfident", True) and post.get("author"):
        parts.append(str(post["author"]))
    parts.extend((post.get("text") or "").splitlines())
    parts.extend(post.get("attachments") or [])
    parts.extend(str(c.get("text") or "") for c in post.get("comments") or [])
    return [line for line in (normalize_key_text(part) for part in parts) if len(line) >= 10]


def same_post(a: Dict[str, Any], b: Dict[str, Any], *, max_drift_days: float = 0.0) -> bool:
    """判断两条观测是不是同一条帖子。

    朋友圈不暴露帖子 ID。指纹相同直接算同一条；否则依次看：正文开头是否基本一致、
    两帧在滚动重叠区是否有共同的内容行（一帧只见上半、另一帧只见下半）、以及没有内容可比的
    纯图帖是否同作者同发布时间。"""
    if a.get("key") and a.get("key") == b.get("key"):
        return True
    if not _authors_compatible(a, b):
        return False
    ta = normalize_key_text(a.get("text") or "")
    tb = normalize_key_text(b.get("text") or "")
    if min(len(ta), len(tb)) >= 16 and _text_alike(ta[:80], tb[:80]) >= 0.8:
        return _times_compatible(a, b, strict=True, max_drift_days=max_drift_days)
    lines_b = _content_lines(b)
    if any(len(line) >= 10 and line in lines_b for line in _content_lines(a)):
        return _times_compatible(a, b, strict=False, max_drift_days=max_drift_days)
    if a.get("key") and b.get("key") and a["key"] != b["key"]:
        return False
    return (
        not ta and not tb
        and bool(a.get("authorConfident")) and bool(b.get("authorConfident"))
        and bool(a.get("timeText")) and a.get("timeText") == b.get("timeText")
    )


def _footer_time(row: Dict[str, Any]) -> Tuple[str, str]:
    """判断这一行是不是页脚，是则返回 (时间, 时间后面的文字)。

    数字型相对时间（「774天前」「20小时前」）几乎不可能出现在正文行首，所以时间后面跟几个
    杂字也算页脚——可见范围、删除这些图标常被读成「2面」之类。而「昨天」「3月5日」可能正好是
    正文的开头，只有后面的文字像来源（「公众号 · xxx」）或短到不可能是句子时才算页脚。"""
    first = row["els"][0]["text"]
    match = _TIME_TOKEN_RE.match(first)
    if not match:
        return "", ""
    token = match.group(1)
    rest = first[match.end():].strip()
    if _REL_DELTA_RE.match(re.sub(r"\s+", "", token)):
        if len(rest) <= 6 and not any(ch in "，。！？；…" for ch in rest):
            return token, rest
        return (token, rest) if _looks_like_source(rest) else ("", "")
    return (token, rest) if _looks_like_source(rest) else ("", "")


def _looks_like_source(rest: str) -> bool:
    """页脚里时间后面的来源（「公众号 · xxx」「视频号 · xxx」）。正文以「昨天…」开头的行
    后面跟的是一长串文字，不像来源，借此把两者区分开。"""
    if not rest:
        return True
    if any(hint in rest for hint in _SOURCE_HINTS):
        return True
    return len(rest) <= 3 and not any(_is_cjk(ch) for ch in rest)


def _new_post() -> Dict[str, Any]:
    return {
        "key": "", "author": "", "authorConfident": True, "text": "", "collapsed": False,
        "attachments": [], "timeText": "", "source": "", "publishedEstimate": None,
        "likes": [], "comments": [], "isAd": False, "isOwn": False,
        "likedByMe": False, "commentedByMe": False,
        "topCut": False, "bottomCut": False, "footer": None,
        "_text": [],
    }


def _absorb_social_row(post: Dict[str, Any], row: Dict[str, Any], state: Dict[str, bool]) -> None:
    text = row["text"].strip()
    comment = parse_comment_line(text)
    if comment:
        post["comments"].append(comment)
        state["seen_comment"] = True
        return
    if text == _COMMENT_INPUT_TEXT or text.endswith(_COMMENT_SEND_SUFFIX):
        # 评论输入框正开着：占位符「评论」和「发送」按钮落在点赞/评论框的位置上
        post["commentInputOpen"] = True
        return
    if state["seen_comment"]:
        # 评论折行：续行没有「昵称：」前缀
        if post["comments"]:
            post["comments"][-1]["text"] = (post["comments"][-1]["text"] + text).strip()
        return
    for name in parse_likes_line(text):
        if name and name not in post["likes"]:
            post["likes"].append(name)


def _finalize(post: Dict[str, Any], owner_name: str) -> None:
    post["text"] = "\n".join(post.pop("_text")).strip()
    owner = normalize_key_text(owner_name)
    post["isOwn"] = bool(owner) and normalize_key_text(post["author"]) == owner
    post["likedByMe"] = bool(owner) and any(normalize_key_text(n) == owner for n in post["likes"])
    post["commentedByMe"] = bool(owner) and any(
        normalize_key_text(c.get("author") or "") == owner for c in post["comments"]
    )
    published_ts = post.pop("_publishedTs", None)
    post["key"] = post_key(post["author"], post["text"], post["timeText"], published_ts)


def parse_feed_page(
    cap: Dict[str, Any],
    *,
    owner_name: str = "",
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """解析一帧朋友圈 OCR：返回可见帖子（含页脚按钮坐标）以及这一帧的摘要。"""
    elements, win = normalize_ocr_elements(cap)
    win_w = win["width"]
    now = time.time() if now_ts is None else float(now_ts)

    left_text = " ".join(e["text"] for e in elements if e["x"] + e["w"] / 2.0 < DISCOVER_PANE_LEFT)
    discover_hits = sum(1 for marker in DISCOVER_MARKERS if marker in left_text)
    is_discover = discover_hits >= 3
    sticky = any(
        "朋友圈" in e["text"] and e["y"] < STICKY_HEADER_BOTTOM and e["x"] >= DISCOVER_PANE_LEFT
        for e in elements
    )

    # 首屏封面右下角是号主昵称：用来判断哪些帖子是本人发的、本人是否已点过赞
    cover_owner = ""
    cover_bottom = COVER_BOTTOM_FALLBACK
    if not sticky:
        for el in elements:
            if 200.0 <= el["y"] <= 340.0 and el["x"] + el["w"] >= win_w - 110.0 and 1 <= len(el["text"]) <= 40:
                cover_owner = el["text"]
                cover_bottom = el["y"] + 26.0
                break
    if cover_owner:
        owner_name = cover_owner
    feed_top = STICKY_HEADER_BOTTOM if sticky else cover_bottom

    rows = group_rows([
        e for e in elements
        if e["x"] + e["w"] / 2.0 >= DISCOVER_PANE_LEFT and e["y"] >= feed_top
    ])

    time_rows = [row for row in rows if _footer_time(row)[0]]
    col_left = _median([row["xmin"] for row in time_rows]) if time_rows else DEFAULT_COL_LEFT

    def _more_buttons(row: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            e for e in row["els"]
            if _MORE_DOTS_RE.match(e["text"]) and e["x"] >= col_left + _MORE_BUTTON_MIN_OFFSET
        ]

    dots_x = [e["x"] + e["w"] / 2.0 for row in rows for e in _more_buttons(row)]
    col_right = max([row["xmax"] for row in rows] or [col_left + 453.0])
    fallback_button_x = (_median(dots_x) if dots_x else col_right - MORE_BUTTON_INSET)

    posts: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    social: Optional[Dict[str, Any]] = None
    state = {"seen_comment": False}
    started = False

    for row in rows:
        if row["xmin"] < col_left - 12.0:
            # 头像里的文字被读出来了，不是正文，也不打断正在收点赞/评论的那条帖子
            continue

        time_text, rest = _footer_time(row)
        dots = _more_buttons(row)
        # _footer_time 只在整行确实像页脚时才返回时间；这里再确认它落在正文列的左边缘上
        is_footer = bool(dots) or (bool(time_text) and abs(row["xmin"] - col_left) <= 12.0)
        if is_footer:
            if current is None:
                # 先读到页脚、之前却没有作者行：作者被吸顶标题裁掉了
                current = _new_post()
                current["topCut"] = True
                current["authorConfident"] = False
            started = True
            published_ts = estimate_published_ts(time_text, now)
            current["timeText"] = time_text
            current["source"] = rest
            current["_publishedTs"] = published_ts
            current["publishedEstimate"] = _iso(published_ts)
            current["footer"] = {"x": dots[0]["x"] + dots[0]["w"] / 2.0 if dots else fallback_button_x, "y": row["y"]}
            current["bottomCut"] = False
            posts.append(current)
            social = current
            current = None
            state["seen_comment"] = False
            continue

        if social is not None:
            if row["xmin"] >= col_left + 5.0:
                _absorb_social_row(social, row, state)
                continue
            if _FOLDED_RE.match(unicodedata.normalize("NFKC", row["text"]).replace(" ", "")):
                social["foldedAfter"] = True
                social = None
                continue
            social = None

        if current is None:
            current = _new_post()
            # 滚动后的帧，最上面那条帖子的作者多半被吸顶标题裁掉了：这一行可能只是正文的一行，
            # 不能当成作者。它的作者由上一帧（滚动重叠区）补全。
            current["topCut"] = sticky and not started
            current["authorConfident"] = not current["topCut"]
            started = True
            if current["topCut"] and row["xmin"] > col_left + 12.0:
                # 最上面一行是缩进的链接卡片标题：作者在上面，压根没读到
                current["attachments"].append(row["text"])
                continue
            is_ad = any(label in e["text"] for label in _AD_LABELS for e in row["els"])
            author_els = [
                e for e in row["els"]
                if not any(label in e["text"] for label in _AD_LABELS)
            ]
            current["author"] = " ".join(e["text"] for e in author_els).strip() or row["text"]
            current["isAd"] = is_ad
            continue
        if _EXPAND_RE.match(row["text"]) and row["xmin"] <= col_left + 12.0:
            if "全文" in row["text"]:
                current["collapsed"] = True
            continue
        if row["xmin"] <= col_left + 12.0:
            current["_text"].append(row["text"])
        else:
            current["attachments"].append(row["text"])

    if current is not None:
        current["bottomCut"] = True
        posts.append(current)

    for post in posts:
        _finalize(post, owner_name)

    return {
        "ok": True,
        "isDiscoverList": is_discover,
        "isMomentsView": is_discover and (sticky or bool(cover_owner) or bool(posts)),
        "topPage": not sticky,
        "stickyHeader": sticky,
        "ownerName": owner_name,
        "feedTop": feed_top,
        "colLeft": col_left,
        "colRight": col_right,
        "window": win,
        "elements": elements,
        "posts": posts,
        "digest": "|".join(
            f"{p['timeText']}@{int(p['footer']['y']) if p.get('footer') else 'x'}" for p in posts
        ) + f"#{len(rows)}",
    }


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _merge_text(base_text: str, other_text: str) -> str:
    """把同一条帖子两次读到的正文拼起来：一次是上半（开头几行），一次是下半（后面几行）。

    以两边都出现过的那一行为接缝：另一份在接缝之前的行补到前面，接缝之后没见过的行追加到后面。"""
    base = [line for line in (base_text or "").splitlines() if line.strip()]
    other = [line for line in (other_text or "").splitlines() if line.strip()]
    if not base:
        return "\n".join(other)
    if not other:
        return "\n".join(base)
    base_keys = [normalize_key_text(line) for line in base]
    other_keys = [normalize_key_text(line) for line in other]
    shared = [index for index, line in enumerate(other_keys) if line and line in base_keys]
    if not shared:
        return base_text if len(base_text) >= len(other_text) else other_text
    merged = other[:shared[0]] + base
    seam = base_keys.index(other_keys[shared[-1]])
    seen = set(base_keys[:seam + 1]) | set(other_keys[:shared[-1] + 1])
    for line, key in zip(other[shared[-1] + 1:], other_keys[shared[-1] + 1:]):
        if key not in seen:
            merged.append(line)
            seen.add(key)
    return "\n".join(merged)


def _merge_into(target: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    if incoming.get("authorConfident") and not target.get("authorConfident"):
        target["author"] = incoming.get("author") or target.get("author") or ""
    target["authorConfident"] = bool(target.get("authorConfident")) or bool(incoming.get("authorConfident"))
    incoming_text = incoming.get("text") or ""
    if (
        target.get("authorConfident")
        and not incoming.get("authorConfident")
        and incoming.get("author")
        and not _authors_compatible(
            {"author": target.get("author") or "", "authorConfident": True},
            {"author": incoming.get("author") or "", "authorConfident": True},
        )
    ):
        cand_line = normalize_key_text(incoming["author"])
        target_lines = [normalize_key_text(ln) for ln in (target.get("text") or "").splitlines()]
        if cand_line and cand_line in target_lines:
            incoming_text = f"{incoming['author']}\n{incoming_text}".strip()
    target["text"] = _merge_text(target.get("text") or "", incoming_text)
    for field in ("timeText", "source", "publishedEstimate"):
        if not target.get(field) and incoming.get(field):
            target[field] = incoming[field]
    for field in ("collapsed", "isAd", "isOwn", "likedByMe", "commentedByMe"):
        target[field] = bool(target.get(field)) or bool(incoming.get(field))
    # 只有两头都读到过，这条帖子才算完整
    target["topCut"] = bool(target.get("topCut")) and bool(incoming.get("topCut"))
    target["bottomCut"] = bool(target.get("bottomCut")) and bool(incoming.get("bottomCut"))
    if incoming.get("footer"):
        target["footer"] = incoming["footer"]
    for field in ("attachments", "likes"):
        bucket = target.setdefault(field, [])
        for item in incoming.get(field) or []:
            if item not in bucket:
                bucket.append(item)
    comments = target.setdefault("comments", [])
    for comment in incoming.get("comments") or []:
        if not any(c.get("author") == comment.get("author") and c.get("text") == comment.get("text") for c in comments):
            comments.append(dict(comment))
    published_ts = None
    if target.get("publishedEstimate"):
        published_ts = datetime.fromisoformat(str(target["publishedEstimate"])).timestamp()
    target["key"] = post_key(target.get("author") or "", target.get("text") or "", target.get("timeText") or "", published_ts)


def _mark_partial(posts: List[Dict[str, Any]]) -> None:
    for post in posts:
        post["partial"] = bool(
            post.get("topCut") or post.get("bottomCut") or not post.get("authorConfident")
        )


class FeedMerger:
    """把一次读取中连续滚动得到的若干帧逐帧并入同一份帖子列表（新 → 旧）。

    只要每帧滚动的距离不超过可视高度的 30%，高度不超过可视区 70% 的帖子必然在某一帧里完整出现
    （作者和页脚同框）。每条帖子以它完整出现的那一帧为准；只露半截的观测能按内容或发布时间对上就
    并入，对不上的保留下来并标记 `partial`，由调用方决定是否计入统计。纯图帖没有内容可比对，
    它的半截观测对不上就作废——完整的那一帧已经把它记下来了。"""

    def __init__(self) -> None:
        self.posts: List[Dict[str, Any]] = []
        self.frames = 0

    def add_page(self, page: Dict[str, Any]) -> int:
        """并入一帧，返回这一帧里此前没见过的帖子数。"""
        self.frames += 1
        fresh = 0
        # 同一帧里出现的两条帖子不可能是同一条：先对上的记录不再给这一帧后面的帖子用。
        # 没有这一条，同一个人同一天发的两条纯图帖（没有正文可比）会被并成一条。
        taken = set()
        for post in page.get("posts") or []:
            target = next(
                (candidate for candidate in reversed(self.posts[-40:])
                 if id(candidate) not in taken and same_post(candidate, post)),
                None,
            )
            if target is None:
                self.posts.append(copy.deepcopy(post))
                fresh += 1
            else:
                _merge_into(target, post)
                taken.add(id(target))
        _mark_partial(self.posts)
        return fresh


def merge_feed_pages(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merger = FeedMerger()
    for page in pages:
        merger.add_page(page)
    return merger.posts


def public_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """对外输出用的帖子：去掉只在本帧有效的坐标等内部字段。"""
    keep = (
        "key", "author", "text", "collapsed", "attachments", "timeText", "source", "publishedEstimate",
        "likes", "comments", "isAd", "isOwn", "likedByMe", "commentedByMe", "firstSeenAt", "lastSeenAt",
        "seenCount", "partial",
    )
    return {field: post[field] for field in keep if field in post}
