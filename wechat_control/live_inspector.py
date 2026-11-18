"""Read-only live WeChat inspector for sessions, visible chat messages, and contacts.

Strictly enforces non-destructive exploration:
- Only clicks left-rail navigation icons (profile avatar, Chats, Contacts) and
  left/middle list items; NEVER clicks bottom message input box or dispatches Return/Paste.
- Captures screenshots via CGWindowListCreateImage and runs macOS Vision OCR.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .safety import normalize_chat_name
from .io_utils import atomic_write_json

_TIMESTAMP_DIVIDER_RE = re.compile(
    r"^(?:"
    r"(?:昨天|今天|前天|星期[一二三四五六日天]|周[一二三四五六日天])(?:\s*\d{1,2}[:：-]\d{2})?"
    r"|\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?(?:\s*\d{1,2}[:：-]\d{2})?"
    r"|\d{1,2}月\d{1,2}日(?:\s*\d{1,2}[:：-]\d{2})?"
    r"|\d{1,2}/\d{1,2}(?:\s*\d{1,2}[:：-]\d{2})?"
    r"|(?:[01]?\d|2[0-3])[:：-][0-5]\d"
    r")$"
)


_BADGE_RE = re.compile(r"^\d{1,3}\+?$")
_CARD_SOURCE_RE = re.compile(r"^(?:[CVWXYMcvwxym]\s+\S+|[◎•·∞♡〇]\s*\S+)")
_CHANNELS_SOURCE_RE = re.compile(r"^(?:[WVwv∞🦋]\s+\S+|视频号\s*[:：·]?\s*\S*)")
_ARTICLE_SOURCE_RE = re.compile(r"^(?:[MCXYmcxy]\s+\S+|[◎•·♡〇]\s*\S+|(?:公众号|服务号)\s*[:：·]?\s*\S*)")


def _slugify_target(target: str) -> str:
    norm = normalize_chat_name(target)
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", norm).strip("_")
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:6]
    if not safe:
        return f"contact_{digest}"
    return f"{safe[:32]}_{digest}"


def _clean_title_for_match(text: str) -> str:
    if not text:
        return ""
    nfkc = unicodedata.normalize("NFKC", text).strip()
    # Strip leading decorative OCR noise (dots/bullets/unread badges)
    nfkc = re.sub(r"^(?:[•·〇口]\s*|\d{1,3}\+?\s+)+", "", nfkc)
    # Strip trailing group count `(123)` and any trailing icon OCR noise after it
    nfkc = re.sub(r"\s*\(\d+\).*$", "", nfkc)
    # Strip trailing time/date snippets commonly appended on the same OCR line
    nfkc = re.sub(
        r"\s*(?:昨天|今天|前天|星期[一二三四五六日天]|周[一二三四五六日天]|\d{1,2}:\d{2}|\d{1,2}/\d{1,2}).*$",
        "",
        nfkc,
    )
    # Strip trailing WeChat native "AI" badge suffix (e.g. "微信 ClawBot AI")
    nfkc = re.sub(r"\s+AI$", "", nfkc, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", nfkc).strip()


def _matches_target(target: str, candidate: str) -> bool:
    t_norm = normalize_chat_name(_clean_title_for_match(target)).casefold()
    if not t_norm or not candidate:
        return False
    c_clean = normalize_chat_name(_clean_title_for_match(candidate)).casefold()
    if not c_clean:
        return False
    # Reject message preview lines like "联系人A: [链接]..."
    if ":" in c_clean or "：" in c_clean:
        return False
    # Prevent 1-on-1 friend name from matching multi-person group chat title containing "、"
    if "、" in c_clean and "、" not in t_norm:
        return False
    t_compact = re.sub(r"\s+", "", t_norm)
    c_compact = re.sub(r"\s+", "", c_clean)
    if t_norm == c_clean or (t_compact and t_compact == c_compact):
        return True
    for marker in ("...", "⋯", "…", ".."):
        if marker in c_clean:
            prefix = c_clean.split(marker, 1)[0].strip()
            if len(prefix) >= 2 and (t_norm.startswith(prefix) or t_compact.startswith(re.sub(r"\s+", "", prefix))):
                return True
    if len(t_compact) >= 4 and len(c_compact) >= 4 and (t_compact in c_compact or c_compact in t_compact):
        return True
    return False


def _is_timestamp_line(text: str) -> bool:
    cleaned = unicodedata.normalize("NFKC", text or "").strip().rstrip("|｜ ")
    if not cleaned or len(cleaned) > 28:
        return False
    return bool(_TIMESTAMP_DIVIDER_RE.match(cleaned))


def _is_wechat_green_rgb(rgb: Optional[Tuple[int, int, int]]) -> bool:
    """Detect WeChat outgoing green bubble pixels across light/dark themes."""
    if not rgb:
        return False
    r, g, b = rgb
    return (g - r) >= 22 and (g - b) >= 18 and g >= 95


def _is_wechat_badge_red_rgb(rgb: Optional[Tuple[int, int, int]]) -> bool:
    """Detect WeChat unread red badge dot/pill pixels."""
    if not rgb:
        return False
    r, g, b = rgb
    return r >= 205 and g <= 105 and b <= 105 and (r - max(g, b)) >= 110


def _load_bmp_pixel_sampler(image_path: Optional[Path]) -> Optional[Callable[[float, float], Optional[Tuple[int, int, int]]]]:
    """Decode PNG via macOS `sips` to BMP (~30ms) and return an `(x, y) -> (r, g, b)` sampler."""
    if not image_path:
        return None
    src = Path(image_path)
    if not src.exists():
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".bmp") as tf:
            subprocess.run(
                ["/usr/bin/sips", "-s", "format", "bmp", str(src), "--out", tf.name],
                capture_output=True,
                check=True,
                timeout=4.0,
            )
            buf = Path(tf.name).read_bytes()
        if len(buf) < 54 or buf[:2] != b"BM":
            return None
        offset = struct.unpack_from("<I", buf, 10)[0]
        w, h = struct.unpack_from("<ii", buf, 18)
        bpp = struct.unpack_from("<H", buf, 28)[0] // 8
        if w <= 0 or h == 0 or bpp not in (3, 4):
            return None
        top_down = h < 0
        h_abs = abs(h)
        row_bytes = ((w * bpp + 3) // 4) * 4

        def _sample(x: float, y: float) -> Optional[Tuple[int, int, int]]:
            xi = max(0, min(w - 1, int(round(x))))
            yi = max(0, min(h_abs - 1, int(round(y))))
            ry = yi if top_down else (h_abs - 1 - yi)
            idx = offset + ry * row_bytes + xi * bpp
            if idx + 2 >= len(buf):
                return None
            return (buf[idx + 2], buf[idx + 1], buf[idx])

        return _sample
    except Exception:
        return None


class WeChatLiveInspector:
    """Walks the visible WeChat desktop UI (Chats + Contacts) using native Vision OCR."""

    def __init__(
        self,
        run_native: Callable[[List[str], float], Dict[str, Any]],
        snapshots_dir: Path,
        reports_dir: Path,
    ) -> None:
        self._run_native = run_native
        self.snapshots_dir = Path(snapshots_dir)
        self.reports_dir = Path(reports_dir)

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _capture_wechat_ocr(self, out_path: Path, *, timeout: float = 30.0,
                            window_title: str = "微信") -> Dict[str, Any]:
        """只截微信窗口做 OCR（--window-title 定位），避免截到覆盖在上面的无关窗口。

        窗口不存在时退回不带 title 的调用（保留自动拉起能力）。
        """
        res = self._run_native(
            ["capture-ocr", "--window-title", window_title, "--out", str(out_path)], timeout)
        if res.get("ok"):
            return res
        if res.get("error_code") in ("window_not_found", "no_window"):
            fallback = self._run_native(["capture-ocr", "--out", str(out_path)], timeout)
            fallback["fallbackUsed"] = True
            fallback["fallbackReason"] = res.get("error_code")
            return fallback
        return res

    def _activate_and_get_status(self) -> Dict[str, Any]:
        status = self._run_native(["status"], 10.0)
        windows = status.get("windows") or []
        if not status.get("wechatRunning") or not windows:
            self._run_native(["activate"], 12.0)
            self._sleep(0.35)
            status = self._run_native(["status"], 10.0)
            windows = status.get("windows") or []
        if not status.get("ok") or not status.get("wechatRunning"):
            raise RuntimeError(f"WeChat is not running: {status}")
        if not windows:
            raise RuntimeError("No visible WeChat window found (please keep WeChat main window open).")
        self._run_native(["activate"], 10.0)
        self._sleep(0.3)
        return status

    @staticmethod
    def _split_x(win_w: float) -> float:
        # WeChat compact left rail (~60px) + session column (~160px..250px)
        return max(218.0, min(310.0, win_w * 0.38))

    @staticmethod
    def _infer_split_x(elements: List[Dict[str, Any]], win_w: float) -> float:
        """动态推断左栏会话列表与右栏聊天区的分界 X 坐标（兼容窄窗与宽屏窗口）。"""
        base = WeChatLiveInspector._split_x(win_w)
        header_candidates: List[Tuple[float, Dict[str, Any]]] = []
        for el in elements or []:
            center = el.get("center") or {}
            cx = float(center.get("x", 0.0) or 0.0)
            cy = float(center.get("y", 0.0) or 0.0)
            txt = str(el.get("text") or "").strip()
            if not txt or (len(txt) <= 1 and txt in "Q口〇•·+-×÷|"):
                continue
            if "搜索" in txt:
                continue
            if 6.0 <= cy <= 46.0 and cx > base:
                bbox = el.get("bbox") or {}
                bx = float(bbox.get("x", cx) or cx)
                header_candidates.append((bx, el))
        if header_candidates:
            header_candidates.sort(key=lambda pair: pair[0])
            leftmost_bx = header_candidates[0][0]
            if (base + 24.0) < leftmost_bx < (win_w * 0.72):
                return round(leftmost_bx - 16.0, 1)
        return base

    @staticmethod
    def _is_popout_window(ocr_payload: Dict[str, Any], elements: List[Dict[str, Any]]) -> bool:
        """Detect standalone pop-out chat windows (no left sidebar / session column)."""
        if not isinstance(ocr_payload, dict):
            return False
        if ocr_payload.get("isMainWindow") is False:
            return True
        if "splitX" in ocr_payload and ocr_payload.get("splitX") is not None:
            try:
                if float(ocr_payload["splitX"]) <= 0.0:
                    return True
            except (TypeError, ValueError):
                pass
        win_title = str(ocr_payload.get("windowTitle") or "").strip()
        if win_title and win_title not in ("微信", "WeChat", "企业微信", "WeCom"):
            has_search_box = any(
                "搜索" in str(el.get("text") or "")
                and float((el.get("center") or {}).get("x", 9999.0) or 9999.0) <= 260.0
                and float((el.get("center") or {}).get("y", 9999.0) or 9999.0) <= 80.0
                for el in (elements or [])
            )
            if not has_search_box:
                return True
        return False

    @staticmethod
    def _cluster_session_rows(
        elements: List[Dict[str, Any]],
        split_x: float,
        win_h: float,
        image_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Group OCR fragments in the middle session column (64 <= x <= split_x) into chat rows."""
        sampler = _load_bmp_pixel_sampler(image_path) if image_path else None
        mid_els: List[Dict[str, Any]] = []
        badge_els: List[Dict[str, Any]] = []
        for el in elements:
            cx = el["center"]["x"]
            cy = el["center"]["y"]
            if not (46.0 <= cx <= split_x and 50.0 <= cy <= (win_h - 8.0)):
                continue
            txt = el.get("text", "").strip()
            if not txt:
                continue
            if _BADGE_RE.match(txt):
                badge_els.append(el)
                continue
            if cx < 64.0:
                continue
            if len(txt) == 1 and txt in "口〇•·":
                continue
            mid_els.append(el)

        mid_els.sort(key=lambda e: (e["center"]["y"], e["center"]["x"]))

        rows: List[List[Dict[str, Any]]] = []
        for el in mid_els:
            cy = el["center"]["y"]
            if rows and (cy - rows[-1][0]["center"]["y"]) <= 36.0:
                rows[-1].append(el)
            else:
                rows.append([el])

        summarized: List[Dict[str, Any]] = []
        for idx, group in enumerate(rows):
            group_sorted = sorted(group, key=lambda e: (e["center"]["y"], e["center"]["x"]))
            non_ts = [g for g in group_sorted if not _is_timestamp_line(g.get("text", ""))]
            top_pool = non_ts if non_ts else group_sorted
            top_y = min(g["center"]["y"] for g in top_pool)

            title_candidates = []
            for g in non_ts:
                raw_txt = g.get("text", "").strip()
                cleaned_no_ts = _clean_title_for_match(raw_txt)
                if (
                    abs(g["center"]["y"] - top_y) <= 10.0
                    and not _is_timestamp_line(raw_txt)
                    and ":" not in cleaned_no_ts
                    and "：" not in cleaned_no_ts
                ):
                    title_candidates.append(g)

            if title_candidates:
                title_candidates.sort(key=lambda e: e["center"]["x"])
                title_el = title_candidates[0]
            else:
                title_el = top_pool[0]

            title_line = title_el["text"].strip()
            preview_lines = [g["text"].strip() for g in group_sorted if g is not title_el]
            ys = [g["center"]["y"] for g in top_pool]
            avg_y = sum(ys) / len(ys)

            title_x = float((title_el.get("bbox") or {}).get("x") or 118.0)
            avatar_x = round(max(64.0, min(80.0, title_x - 48.0)), 1)
            avatar_y = round(avg_y - 20.0, 1)

            matching_badges = [
                b for b in badge_els
                if abs(b["center"]["y"] - avg_y) <= 24.0
            ]
            matching_badges.sort(
                key=lambda b: (b["center"]["x"] > 95.0, abs(b["center"]["y"] - avg_y))
            )
            unread_badge = matching_badges[0]["text"].strip() if matching_badges else ""
            if not unread_badge and sampler is not None:
                red_hits = 0
                for dx in (30, 34, 38):
                    for dy in (2, 5, 8):
                        if _is_wechat_badge_red_rgb(sampler(avatar_x + dx, avatar_y + dy)):
                            red_hits += 1
                if red_hits >= 2:
                    unread_badge = "dot"

            summarized.append({
                "rowIndex": idx,
                "centerY": round(avg_y, 1),
                "clickRelX": round(min(split_x - 28.0, 145.0), 1),
                "clickRelY": round(avg_y, 1),
                "titleSnippet": title_line,
                "previewSnippet": " | ".join(preview_lines),
                "unreadBadge": unread_badge,
                "rawTexts": [g["text"] for g in group_sorted],
                # 头像裁剪区：会话列标题左侧 48px（跳过 60px 左导航栏）、文本行中心 ±20px 的 40×40 正方形
                "avatarRel": {
                    "x": avatar_x,
                    "y": avatar_y,
                    "width": 40.0,
                    "height": 40.0,
                },
            })
        return summarized

    @staticmethod
    def _parse_right_pane(
        elements: List[Dict[str, Any]],
        split_x: float,
        win_h: float,
        *,
        window_title: str = "",
    ) -> Dict[str, Any]:
        """Extract untruncated header title and chat message lines from the right pane (or full pop-out window)."""
        if split_x <= 0.0:
            raw_headers = [
                el for el in elements
                if 8.0 <= el["center"]["x"] <= 460.0
                and 6.0 <= el["center"]["y"] <= 64.0
                and str(el.get("text") or "").strip()
            ]
            non_chrome = [
                el for el in raw_headers
                if not (
                    len(str(el.get("text") or "").strip()) == 1
                    and str(el.get("text") or "").strip().lower() in "x×+-÷|□〇•·…—"
                )
            ]
            pool = non_chrome if non_chrome else raw_headers
            chosen_headers: List[Dict[str, Any]] = []
            if pool:
                pool_sorted = sorted(pool, key=lambda e: (e["center"]["x"], e["center"]["y"]))
                first = pool_sorted[0]
                chosen_headers.append(first)
                first_cy = float(first["center"]["y"])
                first_bbox = first.get("bbox") or {}
                prev_right = float(first_bbox.get("x", first["center"]["x"])) + float(first_bbox.get("width", 0.0))
                for cand in pool_sorted[1:]:
                    cand_cy = float(cand["center"]["y"])
                    cand_bbox = cand.get("bbox") or {}
                    cand_left = float(cand_bbox.get("x", cand["center"]["x"]))
                    if abs(cand_cy - first_cy) <= 12.0 and (cand_left - prev_right) <= 45.0:
                        chosen_headers.append(cand)
                        prev_right = max(prev_right, cand_left + float(cand_bbox.get("width", 0.0)))
            header_els = sorted(chosen_headers, key=lambda e: (e["center"]["y"], e["center"]["x"]))
            header_ids = {id(el) for el in header_els}
            max_header_cy = max((float(el["center"]["y"]) for el in header_els), default=48.0)
            min_msg_y = max(56.0, min(72.0, max_header_cy + 10.0))
            msg_els = sorted(
                [
                    el for el in elements
                    if id(el) not in header_ids
                    and el["center"]["x"] >= 8.0
                    and min_msg_y < el["center"]["y"] <= (win_h - 140.0)
                    and not (
                        float(el["center"]["y"]) <= 68.0
                        and float(el["center"]["x"]) >= 460.0
                    )
                ],
                key=lambda e: (e["center"]["y"], e["center"]["x"]),
            )
            header_text = " ".join(str(el["text"]).strip() for el in header_els).strip()
            if window_title and (not header_text or len(re.sub(r"[、，。….\s]+", "", header_text)) <= 1):
                header_text = str(window_title).strip()
            elif not header_text and window_title:
                header_text = str(window_title).strip()
        else:
            header_els = sorted(
                [
                    el for el in elements
                    if el["center"]["x"] > split_x + 4.0 and 6.0 <= el["center"]["y"] <= 46.0
                ],
                key=lambda e: (e["center"]["y"], e["center"]["x"]),
            )
            msg_els = sorted(
                [
                    el for el in elements
                    if el["center"]["x"] > split_x + 4.0 and 48.0 < el["center"]["y"] <= (win_h - 140.0)
                ],
                key=lambda e: (e["center"]["y"], e["center"]["x"]),
            )
            header_text = " ".join(el["text"] for el in header_els).strip()
        # Filter noise such as single tiny glyphs in empty state
        messages: List[Dict[str, Any]] = []
        for el in msg_els:
            txt = el["text"].strip()
            if not txt:
                continue
            messages.append({
                "text": txt,
                "y": el["center"]["y"],
                "x": el["center"]["x"],
                "bbox": el.get("bbox", {}),
                "confidence": round(float(el.get("confidence", 0.0)), 3),
            })
        return {
            "headerTitle": header_text,
            "messageCountVisible": len(messages),
            "messages": messages,
        }

    @staticmethod
    def classify_line_direction(
        msg: Dict[str, Any],
        split_x: float,
        win_w: float,
        sampler: Optional[Callable[[float, float], Optional[Tuple[int, int, int]]]] = None,
    ) -> str:
        """Classify a chat line as 'system' (timestamp divider), 'self' (green bubble), or 'peer'."""
        txt = msg.get("text", "")
        if _is_timestamp_line(txt):
            return "system"

        bbox = msg.get("bbox") or {}
        cx = float(msg.get("x", 0.0))
        cy = float(msg.get("y", 0.0))
        bx = float(bbox.get("x", cx))
        bw = float(bbox.get("width", 0.0))
        bh = float(bbox.get("height", 0.0))
        by = float(bbox.get("y", cy - bh * 0.5))

        if sampler is not None:
            right_px = (bx + bw) if bw > 0 else cx
            bottom_px = (by + bh) if bh > 0 else (cy + 8.0)
            left_floor = (split_x + 12.0) if split_x > 0.0 else 8.0
            sample_points = (
                (max(left_floor, bx - 4.0), cy),
                (cx if bw <= 0 else (bx + bw * 0.5), max(49.0, by - 3.0)),
                (min(win_w - 18.0, right_px + 8.0), cy),
                (cx if bw <= 0 else (bx + bw * 0.5), bottom_px + 3.0),
            )
            green_hits = sum(1 for px, py in sample_points if _is_wechat_green_rgb(sampler(px, py)))
            return "self" if green_hits >= 1 else "peer"

        mid_x = bx + bw / 2.0 if bw > 0 else cx
        right_edge = bx + bw if bw > 0 else cx
        if split_x <= 0.0:
            if bw > 0 and bx < win_w * 0.25 and mid_x <= win_w * 0.58:
                return "peer"
            is_self = (mid_x > win_w * 0.45 and (bw <= 0 or bx >= win_w * 0.25)) or (right_edge > win_w * 0.78)
            return "self" if is_self else "peer"
        pane_w = max(1.0, win_w - split_x)
        is_self = (mid_x > split_x + pane_w * 0.56) or (right_edge > split_x + pane_w * 0.78)
        return "self" if is_self else "peer"

    @staticmethod
    def _join_bubble_lines(lines: List[str]) -> str:
        out = ""
        for part in lines:
            seg = (part or "").strip()
            if not seg:
                continue
            if not out:
                out = seg
                continue
            if out[-1].isascii() and out[-1].isalnum() and seg[0].isascii() and seg[0].isalnum():
                out += " " + seg
            else:
                out += seg
        return out

    @staticmethod
    def _is_card_footer_line(line: str) -> bool:
        clean = str(line or "").strip()
        if not clean or len(clean) > 28:
            return False
        return bool(
            _CARD_SOURCE_RE.match(clean)
            or _CHANNELS_SOURCE_RE.match(clean)
            or _ARTICLE_SOURCE_RE.match(clean)
            or "公众号" in clean
            or "视频号" in clean
            or "服务号" in clean
        )

    @staticmethod
    def classify_bubble_media_type(bubble: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Classify a chat bubble into text/image/video/channels_video/wechat_article/external_link and extract card metadata."""
        raw_lines = [str(x).strip() for x in (bubble.get("lines") or []) if str(x).strip()]
        text = str(bubble.get("text") or "").strip()
        lower = text.lower()
        height = max(0.0, float(bubble.get("yBottom", 0.0) or 0.0) - float(bubble.get("yTop", 0.0) or 0.0))

        # Strip optional group `sender: ` prefix on the first line for metadata inspection
        lines = list(raw_lines)
        sender = str(bubble.get("sender") or "").strip()
        if sender and lines and lines[0] == sender:
            lines = lines[1:]

        source_name = ""
        card_kind = ""
        source_idx = -1
        for i, ln in enumerate(lines):
            if _CHANNELS_SOURCE_RE.match(ln):
                card_kind = "channels_video"
                source_name = re.sub(r"^(?:[WVwv∞🦋]|视频号)\s*[:：·]?\s*", "", ln).strip()
                source_idx = i
            elif _ARTICLE_SOURCE_RE.match(ln):
                card_kind = "wechat_article"
                source_name = re.sub(r"^(?:[MCXYmcxy◎•·♡〇]|公众号|服务号)\s*[:：·]?\s*", "", ln).strip()
                source_idx = i
            elif _CARD_SOURCE_RE.match(ln):
                card_kind = "wechat_article"
                source_name = re.sub(r"^[CVWXYMcvwxym◎•·∞♡〇]\s*", "", ln).strip()
                source_idx = i

        content_lines = [ln for idx, ln in enumerate(lines) if idx != source_idx] if source_idx >= 0 else list(lines)

        if card_kind:
            # Tall card with W/V/视频号 is channels_video; multi-line card with digest + M/公众号 is wechat_article
            if card_kind == "channels_video" or "视频号" in text or height >= 165.0:
                media_type = "channels_video"
            else:
                media_type = "wechat_article"
            title_lines = content_lines[:2] if len(content_lines) >= 2 else content_lines
            digest_lines = content_lines[2:] if len(content_lines) > 2 else []
            return media_type, {
                "cardKind": media_type,
                "cardSource": source_name,
                "cardTitle": WeChatLiveInspector._join_bubble_lines(title_lines)[:120],
                "cardDigest": WeChatLiveInspector._join_bubble_lines(digest_lines)[:180],
            }

        if re.search(r"mp\.weixin\.qq\.com", lower):
            return "wechat_article", {
                "cardKind": "wechat_article",
                "cardSource": "微信公众号",
                "cardTitle": text[:120],
                "cardDigest": "",
            }

        if re.search(r"(?:https?://|github\.com/|yobot\.yokoagi\.com)", lower):
            return "external_link", {
                "cardKind": "external_link",
                "cardSource": "",
                "cardTitle": text[:120],
                "cardDigest": "",
            }

        if any(tok in lower for tok in ("[视频]", "[video]", "视频消息")) or (
            height >= 42.0 and re.fullmatch(r"\d{1,2}:[0-5]\d(?::[0-5]\d)?", text)
        ):
            return "video", {
                "cardKind": "video",
                "cardSource": "微信视频",
                "cardTitle": text[:120] or "微信视频",
                "cardDigest": "",
            }

        if any(tok in lower for tok in ("[图片]", "[image]", "[photo]", "[动画表情]", "图片消息")):
            return "image", {
                "cardKind": "image",
                "cardSource": "微信图片",
                "cardTitle": text[:120] or "微信图片",
                "cardDigest": "",
            }

        if len(content_lines) >= 3 and height >= 85.0 and any(tok in text for tok in ("..", "…", "|", "｜")):
            return "wechat_article", {
                "cardKind": "wechat_article",
                "cardSource": "",
                "cardTitle": WeChatLiveInspector._join_bubble_lines(content_lines[:2])[:120],
                "cardDigest": WeChatLiveInspector._join_bubble_lines(content_lines[2:])[:180],
            }

        return "text", {}

    @staticmethod
    def cluster_message_bubbles(
        messages: List[Dict[str, Any]],
        split_x: float,
        win_w: float,
        image_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Group wrapped same-sender OCR lines (same timestamp section, dy <= 34px) into chat bubbles."""
        sampler = _load_bmp_pixel_sampler(image_path) if image_path else None
        ordered = sorted(messages, key=lambda m: (float(m.get("y", 0.0)), float(m.get("x", 0.0))))

        bubbles: List[Dict[str, Any]] = []
        active_time_marker = ""
        current: Optional[Dict[str, Any]] = None

        for m in ordered:
            txt = (m.get("text") or "").strip()
            if not txt:
                continue
            direction = WeChatLiveInspector.classify_line_direction(m, split_x, win_w, sampler=sampler)
            if direction == "system":
                active_time_marker = unicodedata.normalize("NFKC", txt).strip().rstrip("|｜ ")
                current = None
                continue

            bbox = m.get("bbox") or {}
            y_center = float(m.get("y", 0.0))
            x_center = float(m.get("x", 0.0))
            bw = float(bbox.get("width", 0.0) or 0.0)
            bh = float(bbox.get("height", 16.0) or 16.0)
            bx = float(bbox.get("x", max(0.0, x_center - (bw * 0.5 if bw > 0 else 20.0))))
            by = float(bbox.get("y", y_center - bh * 0.5))
            x_left = bx
            x_right = bx + (bw if bw > 0 else 40.0)
            y_top = by
            y_bottom = by + bh

            dy = y_center - float(current["_lastCenterY"]) if current is not None else 0.0
            prev_ended_with_footer = bool(
                current is not None
                and current.get("lines")
                and WeChatLiveInspector._is_card_footer_line(current["lines"][-1])
            )
            same_group_head = (
                current is not None
                and not prev_ended_with_footer
                and current["direction"] == "peer"
                and direction == "peer"
                and current["timeMarker"] == active_time_marker
                and len(current["lines"]) == 1
                and len(current["lines"][0].strip()) <= 12
                and -4.0 <= dy <= 125.0
            )
            card_footer_follow = (
                current is not None
                and not prev_ended_with_footer
                and current["direction"] == "peer"
                and direction == "peer"
                and current["timeMarker"] == active_time_marker
                and len(txt) <= 28
                and WeChatLiveInspector._is_card_footer_line(txt)
                and -4.0 <= dy <= 210.0
            )
            if (
                current is not None
                and not prev_ended_with_footer
                and current["direction"] == direction
                and current["timeMarker"] == active_time_marker
                and (-4.0 <= dy <= 34.0 or same_group_head or card_footer_follow)
            ):
                if same_group_head and dy >= 24.0 and not current.get("sender"):
                    current["sender"] = current["lines"][0].strip()
                current["lines"].append(txt)
                if current.get("sender") and len(current["lines"]) >= 2:
                    body_text = WeChatLiveInspector._join_bubble_lines(current["lines"][1:])
                    current["text"] = f"{current['sender']}: {body_text}"
                else:
                    current["text"] = WeChatLiveInspector._join_bubble_lines(current["lines"])
                current["yTop"] = round(min(float(current["yTop"]), y_top), 1)
                current["yBottom"] = round(max(float(current["yBottom"]), y_bottom), 1)
                current["_xLeft"] = round(min(float(current["_xLeft"]), x_left), 1)
                current["_xRight"] = round(max(float(current["_xRight"]), x_right), 1)
                current["_lastCenterY"] = max(float(current["_lastCenterY"]), y_center)
            else:
                current = {
                    "direction": direction,
                    "text": txt,
                    "lines": [txt],
                    "timeMarker": active_time_marker,
                    "yTop": round(y_top, 1),
                    "yBottom": round(y_bottom, 1),
                    "_xLeft": round(x_left, 1),
                    "_xRight": round(x_right, 1),
                    "_lastCenterY": y_center,
                }
                bubbles.append(current)

        for b in bubbles:
            b.pop("_lastCenterY", None)
            xl = float(b.pop("_xLeft", 0.0))
            xr = float(b.pop("_xRight", xl + 40.0))
            yt = float(b.get("yTop", 0.0))
            yb = float(b.get("yBottom", yt + 20.0))
            if xr > xl:
                b["clickRelX"] = round((xl + xr) * 0.5, 1)
                b["clickRelY"] = round((yt + yb) * 0.5, 1)
                crop_x = max(0, int(round(xl - 16)))
                crop_y = max(0, int(round(yt - 12)))
                crop_w = max(80, int(round((xr - xl) + 32)))
                crop_h = max(48, int(round((yb - yt) + 24)))
                b["cropRegion"] = {"x": crop_x, "y": crop_y, "width": crop_w, "height": crop_h}
            media_type, card_meta = WeChatLiveInspector.classify_bubble_media_type(b)
            b["mediaType"] = media_type
            if card_meta:
                b["cardMeta"] = card_meta
        return bubbles

    def extract_structured_bubbles(
        self,
        ocr_payload: Dict[str, Any],
        *,
        snapshot_path: Optional[Path] = None,
        bounds: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extract right-pane header + clustered message bubbles from a capture-ocr payload."""
        resolved_bounds = (
            bounds
            or ocr_payload.get("windowBounds")
            or ocr_payload.get("window")
            or ocr_payload.get("bounds")
            or (
                {"width": ocr_payload["imageWidth"], "height": ocr_payload["imageHeight"]}
                if ocr_payload.get("imageWidth") and ocr_payload.get("imageHeight")
                else {}
            )
        )
        win_w = float(resolved_bounds.get("width", 585.0) or 585.0)
        win_h = float(resolved_bounds.get("height", 640.0) or 640.0)
        elements = ocr_payload.get("elements") or []
        if self._is_popout_window(ocr_payload, elements):
            split_x = 0.0
        elif ocr_payload.get("splitX") is not None:
            split_x = float(ocr_payload["splitX"])
        else:
            split_x = self._infer_split_x(elements, win_w)
        win_title = str(ocr_payload.get("windowTitle") or "")
        right_info = self._parse_right_pane(elements, split_x, win_h, window_title=win_title)
        resolved_image = snapshot_path or ocr_payload.get("imagePath") or ocr_payload.get("snapshotPath")
        img_path = Path(resolved_image) if resolved_image else None
        bubbles = self.cluster_message_bubbles(
            right_info["messages"],
            split_x,
            win_w,
            image_path=img_path,
        )
        return {
            "headerTitle": right_info["headerTitle"],
            "bubbles": bubbles,
            "lastBubble": bubbles[-1] if bubbles else None,
        }

    @staticmethod
    def _parse_contacts_pane(elements: List[Dict[str, Any]], split_x: float, win_h: float) -> Dict[str, Any]:
        """Extract visible contact rows & categories from the Contacts tab."""
        mid_els = sorted(
            [
                el for el in elements
                if 64.0 <= el["center"]["x"] <= split_x and 55.0 <= el["center"]["y"] <= (win_h - 8.0)
            ],
            key=lambda e: (e["center"]["y"], e["center"]["x"]),
        )
        right_els = sorted(
            [
                el for el in elements
                if el["center"]["x"] > split_x + 4.0 and 10.0 <= el["center"]["y"] <= (win_h - 20.0)
            ],
            key=lambda e: (e["center"]["y"], e["center"]["x"]),
        )
        return {
            "listItems": [el["text"].strip() for el in mid_els if el["text"].strip()],
            "detailItems": [el["text"].strip() for el in right_els if el["text"].strip()],
        }

    def _click_rel(
        self,
        bounds: Dict[str, Any],
        rel_x: float,
        rel_y: float,
        *,
        double: bool = False,
    ) -> None:
        abs_x = float(bounds["x"]) + rel_x
        abs_y = float(bounds["y"]) + rel_y
        cmd = ["click", "--x", f"{abs_x:.1f}", "--y", f"{abs_y:.1f}"]
        if double:
            cmd.append("--double")
        self._run_native(cmd, 5.0)

    def _scroll_rel(self, bounds: Dict[str, Any], rel_x: float, rel_y: float, dy: int) -> None:
        abs_x = float(bounds["x"]) + rel_x
        abs_y = float(bounds["y"]) + rel_y
        self._run_native(["scroll", "--x", f"{abs_x:.1f}", "--y", f"{abs_y:.1f}", "--dy", str(dy)], 5.0)

    @staticmethod
    def _is_folder_view(rows: List[Dict[str, Any]]) -> bool:
        """Detect if clicking a row (like 服务号/公众号) replaced the main session list with a sub-view."""
        if not rows:
            return False
        joined = " ".join(r["titleSnippet"] for r in rows[:3])
        return "返回" in joined or ("服务号" in rows[0]["titleSnippet"] and len(rows) <= 4 and "文件传输" not in joined)

    def _persist_contact_history(
        self,
        target: str,
        matched_title: str,
        bubbles: List[Dict[str, Any]],
        snapshot_path: Optional[str] = None,
    ) -> Optional[Path]:
        """Merge pop-out or live observed bubbles into `<reports>/contacts/<slug>_history.json`."""
        clean_target = str(target or "").strip()
        if not clean_target:
            return None
        contacts_dir = self.reports_dir / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify_target(clean_target)
        history_path = contacts_dir / f"{slug}_history.json"
        prior_records: List[Dict[str, Any]] = []
        if history_path.exists():
            try:
                old = json.loads(history_path.read_text(encoding="utf-8"))
                prior_records = list(old.get("records") or [])
            except Exception:
                prior_records = []
        observed_items: List[Dict[str, Any]] = []
        norm_title_cf = re.sub(r"\s+", "", _clean_title_for_match(str(matched_title or clean_target))).casefold()
        norm_target_cf = re.sub(r"\s+", "", _clean_title_for_match(clean_target)).casefold()
        for idx, b in enumerate(bubbles):
            txt = str(b.get("text") or "").strip()
            if not txt:
                continue
            txt_cf = re.sub(r"\s+", "", _clean_title_for_match(txt)).casefold()
            if txt_cf and txt_cf in {norm_title_cf, norm_target_cf} and idx == 0 and float(b.get("yTop", 999.0)) <= 76.0:
                continue
            item: Dict[str, Any] = {
                "page": 0,
                "index": idx,
                "kind": "message",
                "direction": str(b.get("direction") or "peer"),
                "text": txt,
                "sender": str(b.get("sender") or ""),
                "timeMarker": str(b.get("timeMarker") or ""),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            if b.get("mediaType") and b.get("mediaType") != "text":
                item["mediaType"] = str(b["mediaType"])
            if isinstance(b.get("cardMeta"), dict) and b["cardMeta"]:
                item["cardMeta"] = dict(b["cardMeta"])
            observed_items.append(item)
        merged: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        for rec in prior_records + observed_items:
            dedup_key = f"{rec.get('kind')}||{rec.get('direction')}||{rec.get('text')}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            merged.append(rec)
        if len(merged) > 500:
            merged = merged[-500:]
        payload: Dict[str, Any] = {
            "ok": True,
            "target": clean_target,
            "matchedTitle": str(matched_title or clean_target),
            "slug": slug,
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "pagesCaptured": 1,
            "pages": [{"page": 0, "snapshotPath": str(snapshot_path or "")}],
            "recordCount": len(merged),
            "records": merged,
            "historyPath": str(history_path),
        }
        atomic_write_json(history_path, payload)
        return history_path

    def _inspect_live_popouts_only(
        self,
        *,
        status: Dict[str, Any],
        win: Dict[str, Any],
        ax_trusted: bool,
        post_event_trusted: bool,
    ) -> Dict[str, Any]:
        """Inspect only standalone pop-out windows when main WeChat window is closed."""
        popouts = self.list_popout_windows(app="all")
        if not popouts:
            popouts = [w for w in (status.get("windows") or []) if w.get("isMainWindow") is False]
        sessions_summary: List[Dict[str, Any]] = []
        seen_titles: set[str] = set()
        for pw in popouts:
            pw_title = _clean_title_for_match(str(pw.get("title") or "").strip())
            if not pw_title:
                continue
            norm_key = normalize_chat_name(pw_title).casefold()
            if norm_key in seen_titles:
                continue
            seen_titles.add(norm_key)
            insp = self.inspect_popout_window(pw, target=pw_title, snapshot_prefix="inspect_popout")
            structured = insp.get("structured") or {}
            bubbles = list(structured.get("bubbles") or [])
            snap_path = insp.get("snapshotPath") or ""
            raw_header = _clean_title_for_match(str(structured.get("headerTitle") or pw_title)) or pw_title
            header_title = (
                pw_title
                if re.sub(r"\s+", "", raw_header).casefold() == re.sub(r"\s+", "", pw_title).casefold()
                else raw_header
            )
            self._persist_contact_history(pw_title, header_title, bubbles, snap_path)
            sessions_summary.append({
                "index": len(sessions_summary) + 1,
                "page": 0,
                "listTitleSnippet": pw_title,
                "listPreviewSnippet": str((bubbles[-1].get("text") if bubbles else "") or "")[:80],
                "fullTitle": header_title,
                "enteredFolder": False,
                "visibleMessageCount": len(bubbles),
                "visibleMessages": [str(b.get("text") or "") for b in bubbles],
                "snapshotPath": str(snap_path),
                "windowID": pw.get("windowID"),
                "popoutWindow": True,
            })

        report: Dict[str, Any] = {
            "ok": True,
            "inspectedAt": datetime.now(timezone.utc).isoformat(),
            "window": win,
            "popoutOnlyMode": True,
            "permissions": {
                "accessibilityTrusted": ax_trusted,
                "postEventTrusted": post_event_trusted,
                "screenCaptureTrusted": bool(status.get("screenCaptureTrusted")),
            },
            "interactiveNavigationGranted": post_event_trusted,
            "accountProfileOCR": [],
            "sessionCount": len(sessions_summary),
            "sessions": sessions_summary,
            "contactItemCount": len(sessions_summary),
            "contacts": [s["listTitleSnippet"] for s in sessions_summary],
            "contactPages": [],
        }
        json_path = self.reports_dir / "wechat_management_report.json"
        md_path = self.reports_dir / "wechat_management_report.md"
        atomic_write_json(json_path, report)
        md_path.write_text(self._format_markdown_report(report), encoding="utf-8")
        report["reportJsonPath"] = str(json_path)
        report["reportMarkdownPath"] = str(md_path)
        return report

    def inspect_live(self, *, max_session_pages: int = 2, max_contact_pages: int = 4) -> Dict[str, Any]:
        """Run a full read-only walkthrough of the currently open WeChat window."""
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        status = self._activate_and_get_status()
        all_windows = list(status.get("windows") or [])
        main_win = next((w for w in all_windows if w.get("isMainWindow") is True), None)
        win = main_win or all_windows[0]
        bounds = win["bounds"]
        win_w = float(bounds["width"])
        win_h = float(bounds["height"])
        split_x = self._split_x(win_w)
        post_event_trusted = bool(status.get("postEventTrusted"))
        ax_trusted = bool(status.get("accessibilityTrusted"))

        if win.get("isMainWindow") is False or (main_win is None and self._is_popout_window(win, [])):
            return self._inspect_live_popouts_only(
                status=status,
                win=win,
                ax_trusted=ax_trusted,
                post_event_trusted=post_event_trusted,
            )

        if not post_event_trusted:
            overview_path = self.snapshots_dir / "sessions_overview_p0.png"
            overview_ocr = self._capture_wechat_ocr(overview_path)
            elements = overview_ocr.get("elements") or []
            split_x = self._infer_split_x(elements, win_w)
            rows = self._cluster_session_rows(elements, split_x, win_h, image_path=overview_path)
            right_info = self._parse_right_pane(elements, split_x, win_h)

            sessions_summary = [
                {
                    "index": i + 1,
                    "page": 0,
                    "listTitleSnippet": r["titleSnippet"],
                    "listPreviewSnippet": r["previewSnippet"],
                    "fullTitle": (right_info["headerTitle"] if right_info["messageCountVisible"] > 0 and i == 0 else r["titleSnippet"]),
                    "visibleMessageCount": 0,
                    "visibleMessages": [],
                    "snapshotPath": str(overview_path),
                    "avatarRel": r.get("avatarRel"),
                }
                for i, r in enumerate(rows)
            ]
            blocked_reason = (
                "macOS 辅助功能 / PostEvent 权限未授予 (accessibilityTrusted=false, postEventTrusted=false)，"
                "系统会静默丢弃模拟点击与滚轮事件，因此无法自动点击进入各个群/好友详情页或切换至通讯录列表。"
                "本次已通过 Screen Recording + Vision OCR 无损采集当前可见窗口的全部首屏会话摘要。"
            )
            report: Dict[str, Any] = {
                "ok": True,
                "inspectedAt": datetime.now(timezone.utc).isoformat(),
                "window": win,
                "permissions": {
                    "accessibilityTrusted": ax_trusted,
                    "postEventTrusted": post_event_trusted,
                    "screenCaptureTrusted": bool(status.get("screenCaptureTrusted")),
                },
                "interactiveNavigationGranted": False,
                "blockedReason": blocked_reason,
                "accountProfileOCR": [],
                "sessionCount": len(sessions_summary),
                "sessions": sessions_summary,
                "activeRightPane": right_info,
                "contactItemCount": 0,
                "contacts": [],
                "contactPages": [],
            }
            json_path = self.reports_dir / "wechat_management_report.json"
            md_path = self.reports_dir / "wechat_management_report.md"
            atomic_write_json(json_path, report)
            md_path.write_text(self._format_markdown_report(report), encoding="utf-8")
            report["reportJsonPath"] = str(json_path)
            report["reportMarkdownPath"] = str(md_path)
            return report

        # Rail coordinates relative to compact/standard WeChat window
        rail_x = 30.0
        avatar_y = 72.0
        chat_tab_y = 122.0
        contacts_tab_y = 170.0
        safe_session_x = min(split_x - 30.0, 145.0)

        # 1. Capture self profile card briefly (click avatar -> OCR -> dismiss)
        self._click_rel(bounds, rail_x, avatar_y)
        self._sleep(0.45)
        profile_shot = self.snapshots_dir / "account_profile.png"
        profile_ocr = self._capture_wechat_ocr(profile_shot)
        # Dismiss profile popup by clicking empty top bar area
        self._click_rel(bounds, win_w * 0.65, 24.0)
        self._sleep(0.25)

        account_texts = [
            el["text"] for el in (profile_ocr.get("elements") or [])
            if el["center"]["x"] >= 50 and el["center"]["y"] <= 260
        ]

        # Ensure Chat tab is active
        self._click_rel(bounds, rail_x, chat_tab_y)
        self._sleep(0.35)

        # 2. Walk Chat Sessions across pages
        inspected_sessions: List[Dict[str, Any]] = []
        seen_signatures: set[str] = set()
        session_counter = 0

        for page in range(max_session_pages):
            overview_path = self.snapshots_dir / f"sessions_overview_p{page}.png"
            overview_ocr = self._capture_wechat_ocr(overview_path)
            if not overview_ocr.get("ok"):
                break
            overview_els = overview_ocr.get("elements") or []
            split_x = self._infer_split_x(overview_els, win_w)
            rows = self._cluster_session_rows(overview_els, split_x, win_h, image_path=overview_path)
            if not rows:
                break

            new_on_page = 0
            for row in rows:
                row_sig = f"{row['titleSnippet']}||{row['previewSnippet']}"
                if row_sig in seen_signatures:
                    continue
                seen_signatures.add(row_sig)
                new_on_page += 1
                session_counter += 1

                # Click session row
                self._click_rel(bounds, row["clickRelX"], row["clickRelY"])
                self._sleep(0.42)

                snap_path = self.snapshots_dir / f"session_{session_counter:02d}.png"
                cap = self._capture_wechat_ocr(snap_path)
                elements = cap.get("elements") or []
                cap_split_x = self._infer_split_x(elements, win_w)
                right_info = self._parse_right_pane(elements, cap_split_x, win_h)

                # If clicking entered a folder (like 服务号/公众号), return back to Chats list
                mid_after = self._cluster_session_rows(elements, cap_split_x, win_h)
                entered_folder = False
                if len(mid_after) != len(rows) and (
                    not mid_after or mid_after[0]["titleSnippet"] != rows[0]["titleSnippet"]
                ):
                    entered_folder = True
                    # Back button inside header of middle column or click Chats tab
                    self._click_rel(bounds, 78.0, 28.0)
                    self._sleep(0.30)
                    self._click_rel(bounds, rail_x, chat_tab_y)
                    self._sleep(0.30)

                inspected_sessions.append({
                    "index": session_counter,
                    "page": page,
                    "listTitleSnippet": row["titleSnippet"],
                    "listPreviewSnippet": row["previewSnippet"],
                    "fullTitle": right_info["headerTitle"] or row["titleSnippet"],
                    "enteredFolder": entered_folder,
                    "visibleMessageCount": right_info["messageCountVisible"],
                    "visibleMessages": [m["text"] for m in right_info["messages"]],
                    "snapshotPath": str(snap_path),
                    "avatarRel": row.get("avatarRel"),
                })

            if page + 1 < max_session_pages:
                if new_on_page == 0:
                    break
                # Scroll down inside middle session list
                self._scroll_rel(bounds, safe_session_x, min(win_h - 80.0, 320.0), dy=-8)
                self._sleep(0.45)

        # 3. Walk Contacts tab
        # Scroll back up slightly and switch to Contacts tab
        self._click_rel(bounds, rail_x, contacts_tab_y)
        self._sleep(0.50)

        contact_pages: List[Dict[str, Any]] = []
        all_contacts: List[str] = []
        seen_contact_items: set[str] = set()
        prev_page_digest = ""

        for page in range(max_contact_pages):
            c_snap = self.snapshots_dir / f"contacts_p{page}.png"
            c_ocr = self._capture_wechat_ocr(c_snap)
            parsed = self._parse_contacts_pane(c_ocr.get("elements") or [], split_x, win_h)
            digest = "|".join(parsed["listItems"])
            if digest == prev_page_digest and page > 0:
                break
            prev_page_digest = digest

            for item in parsed["listItems"]:
                if item not in seen_contact_items:
                    seen_contact_items.add(item)
                    all_contacts.append(item)

            contact_pages.append({
                "page": page,
                "listItems": parsed["listItems"],
                "detailItems": parsed["detailItems"],
                "snapshotPath": str(c_snap),
            })

            if page + 1 < max_contact_pages:
                self._scroll_rel(bounds, safe_session_x, min(win_h - 80.0, 320.0), dy=-8)
                self._sleep(0.45)

        # Restore WeChat back to Chat tab
        self._click_rel(bounds, rail_x, chat_tab_y)
        self._sleep(0.30)

        report: Dict[str, Any] = {
            "ok": True,
            "inspectedAt": datetime.now(timezone.utc).isoformat(),
            "window": win,
            "permissions": {
                "accessibilityTrusted": ax_trusted,
                "postEventTrusted": post_event_trusted,
                "screenCaptureTrusted": bool(status.get("screenCaptureTrusted")),
            },
            "interactiveNavigationGranted": True,
            "accountProfileOCR": account_texts,
            "profileSnapshot": str(profile_shot),
            "sessionCount": len(inspected_sessions),
            "sessions": inspected_sessions,
            "contactItemCount": len(all_contacts),
            "contacts": all_contacts,
            "contactPages": contact_pages,
        }

        json_path = self.reports_dir / "wechat_management_report.json"
        md_path = self.reports_dir / "wechat_management_report.md"
        atomic_write_json(json_path, report)
        md_path.write_text(self._format_markdown_report(report), encoding="utf-8")

        report["reportJsonPath"] = str(json_path)
        report["reportMarkdownPath"] = str(md_path)
        return report

    @staticmethod
    def _format_markdown_report(report: Dict[str, Any]) -> str:
        lines: List[str] = [
            "# 微信实机盘点报告（好友 / 会话 / 可见聊天记录）",
            "",
            f"- 巡检时间: `{report.get('inspectedAt', '')}`",
            f"- 窗口坐标: `{json.dumps(report.get('window', {}), ensure_ascii=False)}`",
            f"- 交互导航权限 (Accessibility/PostEvent): `{report.get('interactiveNavigationGranted', False)}`",
            f"- 已识别会话数: **{report.get('sessionCount', 0)}**",
            f"- 通讯录可见条目数: **{report.get('contactItemCount', 0)}**",
            "",
        ]
        if report.get("blockedReason"):
            lines.append(f"> [!NOTE] 受限说明: {report['blockedReason']}")
            lines.append("")
        lines.extend([
            "## 一、个人名片 / 账号卡片识别",
            "",
        ])
        for txt in report.get("accountProfileOCR") or []:
            lines.append(f"- {txt}")

        lines.extend(["", "## 二、会话列表与右侧聊天记录", ""])
        for sess in report.get("sessions") or []:
            lines.append(f"### {sess['index']}. {sess['fullTitle']}")
            lines.append(f"- 列表摘要: `{sess['listTitleSnippet']}` | `{sess['listPreviewSnippet']}`")
            lines.append(f"- 截图快照: `{sess['snapshotPath']}`")
            msgs = sess.get("visibleMessages") or []
            if msgs:
                lines.append(f"- 右侧可见内容 ({len(msgs)} 条文本块):")
                for m in msgs[:40]:
                    lines.append(f"  - {m}")
            else:
                lines.append("- 右侧可见内容: （文件夹列表 / 空白 / 非标准文本气泡）")
            lines.append("")

        lines.extend(["## 三、通讯录可见好友 / 群组条目", ""])
        for item in report.get("contacts") or []:
            lines.append(f"- {item}")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Target Session Navigation & Bound Contact History Observation
    # ------------------------------------------------------------------

    def _return_from_folder_if_needed(
        self,
        bounds: Dict[str, Any],
        before_rows: List[Dict[str, Any]],
        after_elements: List[Dict[str, Any]],
        split_x: float,
        win_h: float,
    ) -> bool:
        mid_after = self._cluster_session_rows(after_elements, split_x, win_h)
        if len(mid_after) != len(before_rows) and (
            not mid_after or not before_rows or mid_after[0]["titleSnippet"] != before_rows[0]["titleSnippet"]
        ):
            self._click_rel(bounds, 78.0, 28.0)
            self._sleep(0.30)
            self._click_rel(bounds, 30.0, 122.0)
            self._sleep(0.30)
            return True
        return False

    def select_session(self, target: str, *, max_pages: int = 5) -> Dict[str, Any]:
        """Navigate to `target` in WeChat and verify the right-pane header matches."""
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        status = self._activate_and_get_status()
        if not status.get("postEventTrusted"):
            return {
                "ok": False,
                "error_code": "post_event_permission_denied",
                "target": target,
                "error": "macOS Accessibility/PostEvent permission is not granted; cannot click session.",
            }

        win = status["windows"][0]
        bounds = win["bounds"]
        win_w = float(bounds["width"])
        win_h = float(bounds["height"])
        split_x = self._split_x(win_w)
        rail_x = 30.0
        chat_tab_y = 122.0
        safe_session_x = min(split_x - 30.0, 145.0)
        slug = _slugify_target(target)

        # Ensure Chats tab is active
        self._click_rel(bounds, rail_x, chat_tab_y)
        self._sleep(0.35)

        cur_snap = self.snapshots_dir / f"nav_{slug}_cur.png"
        cur_ocr = self._capture_wechat_ocr(cur_snap)
        elements = cur_ocr.get("elements") or []
        split_x = self._infer_split_x(elements, win_w)
        right_info = self._parse_right_pane(elements, split_x, win_h)
        if right_info["headerTitle"] and _matches_target(target, right_info["headerTitle"]):
            return {
                "ok": True,
                "target": target,
                "matchedTitle": right_info["headerTitle"],
                "alreadyOpen": True,
                "bounds": bounds,
                "splitX": split_x,
                "snapshotPath": str(cur_snap),
                "ocrPayload": cur_ocr,
            }

        # Check current viewport rows before scrolling
        rows = self._cluster_session_rows(elements, split_x, win_h, image_path=cur_snap)
        for row in rows:
            if _matches_target(target, row["titleSnippet"]):
                self._click_rel(bounds, row["clickRelX"], row["clickRelY"])
                self._sleep(0.45)
                click_snap = self.snapshots_dir / f"nav_{slug}_matched.png"
                cap = self._capture_wechat_ocr(click_snap)
                cap_els = cap.get("elements") or []
                cap_split_x = self._infer_split_x(cap_els, win_w)
                after_right = self._parse_right_pane(cap_els, cap_split_x, win_h)
                if after_right["headerTitle"] and _matches_target(target, after_right["headerTitle"]):
                    return {
                        "ok": True,
                        "target": target,
                        "matchedTitle": after_right["headerTitle"],
                        "alreadyOpen": False,
                        "bounds": bounds,
                        "splitX": cap_split_x,
                        "snapshotPath": str(click_snap),
                        "ocrPayload": cap,
                    }
                self._return_from_folder_if_needed(bounds, rows, cap_els, cap_split_x, win_h)

        # Scroll back to top of the middle session list and scan downward
        for _ in range(8):
            self._scroll_rel(bounds, safe_session_x, 220.0, dy=25)
            self._sleep(0.18)
        self._sleep(0.45)

        seen_pages: set[str] = set()
        for page in range(max_pages):
            page_snap = self.snapshots_dir / f"nav_{slug}_p{page}.png"
            cap = self._capture_wechat_ocr(page_snap)
            page_els = cap.get("elements") or []
            page_split_x = self._infer_split_x(page_els, win_w)
            page_rows = self._cluster_session_rows(page_els, page_split_x, win_h, image_path=page_snap)
            digest = "|".join(f"{r['titleSnippet']}::{r['previewSnippet']}" for r in page_rows)
            if page > 0 and digest in seen_pages:
                break
            seen_pages.add(digest)

            for row in page_rows:
                if _matches_target(target, row["titleSnippet"]):
                    self._click_rel(bounds, row["clickRelX"], row["clickRelY"])
                    self._sleep(0.45)
                    matched_snap = self.snapshots_dir / f"nav_{slug}_matched.png"
                    m_cap = self._capture_wechat_ocr(matched_snap)
                    m_els = m_cap.get("elements") or []
                    m_split_x = self._infer_split_x(m_els, win_w)
                    m_right = self._parse_right_pane(m_els, m_split_x, win_h)
                    if m_right["headerTitle"] and _matches_target(target, m_right["headerTitle"]):
                        return {
                            "ok": True,
                            "target": target,
                            "matchedTitle": m_right["headerTitle"],
                            "alreadyOpen": False,
                            "bounds": bounds,
                            "splitX": m_split_x,
                            "snapshotPath": str(matched_snap),
                            "ocrPayload": m_cap,
                        }
                    self._return_from_folder_if_needed(bounds, page_rows, m_els, m_split_x, win_h)

            if page + 1 < max_pages:
                self._scroll_rel(bounds, safe_session_x, min(win_h - 80.0, 320.0), dy=-8)
                self._sleep(0.45)

        return {
            "ok": False,
            "error_code": "target_not_found",
            "target": target,
            "error": f"Could not navigate to or verify right-pane header matching target {target!r} within {max_pages} session pages.",
        }

    def open_popout_window(self, target: str, *, max_pages: int = 3) -> Dict[str, Any]:
        """Ensure an independent pop-out chat window is open for `target` (double-click main session row)."""
        clean_target = str(target or "").strip()
        if not clean_target:
            return {"ok": False, "error_code": "missing_target", "error": "Target contact name is required."}

        existing = self.find_popout_window(clean_target, app="all")
        if existing:
            return {
                "ok": True,
                "target": clean_target,
                "matchedTitle": str(existing.get("title") or clean_target),
                "alreadyPopout": True,
                "opened": False,
                "windowID": existing.get("windowID"),
                "window": existing,
            }

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        status = self._activate_and_get_status()
        if not status.get("postEventTrusted"):
            return {
                "ok": False,
                "error_code": "post_event_permission_denied",
                "target": clean_target,
                "error": "macOS Accessibility/PostEvent permission is not granted; cannot double-click session.",
            }
        all_windows = list(status.get("windows") or [])
        main_win = next((w for w in all_windows if w.get("isMainWindow", True)), None)
        if not main_win or main_win.get("isMainWindow") is False:
            return {
                "ok": False,
                "error_code": "no_main_window",
                "target": clean_target,
                "error": "WeChat main window is not open; double-click cannot open pop-out window.",
            }

        bounds = main_win["bounds"]
        win_w = float(bounds["width"])
        win_h = float(bounds["height"])
        split_x = self._split_x(win_w)
        rail_x = 30.0
        chat_tab_y = 122.0
        safe_session_x = min(split_x - 30.0, 145.0)
        slug = _slugify_target(clean_target)

        self._click_rel(bounds, rail_x, chat_tab_y)
        self._sleep(0.30)

        seen_pages: set[str] = set()
        for page in range(max_pages):
            page_snap = self.snapshots_dir / f"popout_nav_{slug}_p{page}.png"
            cap = self._capture_wechat_ocr(page_snap)
            page_els = cap.get("elements") or []
            if self._is_popout_window(main_win, page_els):
                break
            page_split_x = self._infer_split_x(page_els, win_w)
            page_rows = self._cluster_session_rows(page_els, page_split_x, win_h, image_path=page_snap)
            digest = "|".join(f"{r['titleSnippet']}::{r['previewSnippet']}" for r in page_rows)
            if page > 0 and digest in seen_pages:
                break
            seen_pages.add(digest)

            for row in page_rows:
                if _matches_target(clean_target, row["titleSnippet"]):
                    self._click_rel(bounds, row["clickRelX"], row["clickRelY"], double=True)
                    self._sleep(0.45)
                    popped = self.find_popout_window(clean_target, app="all")
                    return {
                        "ok": True,
                        "target": clean_target,
                        "matchedTitle": row["titleSnippet"],
                        "alreadyPopout": False,
                        "opened": bool(popped),
                        "windowID": popped.get("windowID") if popped else None,
                        "window": popped,
                    }

            if page + 1 < max_pages:
                self._scroll_rel(bounds, safe_session_x, min(win_h - 80.0, 320.0), dy=-8)
                self._sleep(0.40)

        return {
            "ok": False,
            "error_code": "target_not_found",
            "target": clean_target,
            "error": f"Session {clean_target!r} not found in visible list.",
        }

    def observe_contact_history(self, target: str, *, scroll_pages: int = 4) -> Dict[str, Any]:
        """Navigate to `target`, scroll upward through chat history, and persist structured OCR records."""
        nav = self.select_session(target)
        if not nav.get("ok"):
            return nav

        bounds = nav["bounds"]
        win_w = float(bounds["width"])
        win_h = float(bounds["height"])
        split_x = float(nav["splitX"])
        slug = _slugify_target(target)
        contacts_dir = self.reports_dir / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        history_path = contacts_dir / f"{slug}_history.json"

        right_mid_x = split_x + (win_w - split_x) * 0.50
        right_mid_y = win_h * 0.45
        pane_w = max(1.0, win_w - split_x)
        self_threshold_x = split_x + pane_w * 0.56

        pages_data: List[Dict[str, Any]] = []
        observed_items: List[Dict[str, Any]] = []
        active_time_marker = ""
        prev_digest = ""

        for page in range(max(1, scroll_pages)):
            snap_path = self.snapshots_dir / f"observe_{slug}_p{page}.png"
            cap = self._capture_wechat_ocr(snap_path)
            elements = cap.get("elements") or []
            right_info = self._parse_right_pane(elements, split_x, win_h)
            digest = "|".join(m["text"] for m in right_info["messages"])
            if page > 0 and digest == prev_digest:
                break
            prev_digest = digest

            sampler = _load_bmp_pixel_sampler(snap_path)
            page_records: List[Dict[str, Any]] = []
            for m in right_info["messages"]:
                txt = m["text"]
                bbox = m.get("bbox") or {}
                bx = float(bbox.get("x", m["x"]))
                bw = float(bbox.get("width", 0.0))
                mid_x = bx + bw / 2.0 if bw > 0 else float(m["x"])
                direction = self.classify_line_direction(m, split_x, win_w, sampler=sampler)
                if direction == "system":
                    active_time_marker = unicodedata.normalize("NFKC", txt).strip().rstrip("|｜ ")
                    kind = "timestamp"
                else:
                    kind = "message"

                rec = {
                    "text": txt,
                    "kind": kind,
                    "direction": direction,
                    "timeMarker": active_time_marker,
                    "page": page,
                    "y": m["y"],
                    "x": round(mid_x, 1),
                    "confidence": m["confidence"],
                }
                page_records.append(rec)
                observed_items.append(rec)

            pages_data.append({
                "page": page,
                "snapshotPath": str(snap_path),
                "headerTitle": right_info["headerTitle"],
                "recordCount": len(page_records),
            })

            if page + 1 < scroll_pages:
                self._scroll_rel(bounds, right_mid_x, right_mid_y, dy=10)
                self._sleep(0.45)

        # Scroll back down to bottom of conversation so UI stays at latest messages
        for _ in range(max(1, len(pages_data) - 1)):
            self._scroll_rel(bounds, right_mid_x, right_mid_y, dy=-15)
            self._sleep(0.20)

        # Load prior persisted history if present and merge deduplicated records
        prior_records: List[Dict[str, Any]] = []
        if history_path.exists():
            try:
                old = json.loads(history_path.read_text(encoding="utf-8"))
                prior_records = list(old.get("records") or [])
            except Exception:
                prior_records = []

        merged: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        # Preserve older scrolled pages first (highest page number = oldest visible top page)
        ordered_new: List[Dict[str, Any]] = []
        for p in sorted({r["page"] for r in observed_items}, reverse=True):
            ordered_new.extend([r for r in observed_items if r["page"] == p])

        for rec in prior_records + ordered_new:
            dedup_key = f"{rec.get('kind')}||{rec.get('direction')}||{rec.get('text')}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            merged.append(rec)

        payload: Dict[str, Any] = {
            "ok": True,
            "target": target,
            "matchedTitle": nav["matchedTitle"],
            "slug": slug,
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "pagesCaptured": len(pages_data),
            "pages": pages_data,
            "recordCount": len(merged),
            "records": merged,
            "historyPath": str(history_path),
        }
        atomic_write_json(history_path, payload)
        return payload

    # ------------------------------------------------------------------
    # Standalone Pop-Out Chat Window Discovery & Zero-Switch Inspection
    # ------------------------------------------------------------------

    def list_popout_windows(self, app: str = "all") -> List[Dict[str, Any]]:
        """List visible standalone pop-out chat windows (`isMainWindow` is False)."""
        try:
            res = self._run_native(["list-app-windows", "--app", str(app or "all")], 8.0)
        except Exception:
            return []
        if not isinstance(res, dict) or not res.get("ok"):
            return []
        windows = res.get("windows") or []
        return [
            w for w in windows
            if isinstance(w, dict) and w.get("windowID") and not w.get("isMainWindow")
        ]

    @staticmethod
    def _match_popout_window(target: str, popouts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        clean_target = str(target or "").strip()
        if not clean_target or not popouts:
            return None
        norm_target = normalize_chat_name(_clean_title_for_match(clean_target)).casefold()
        for w in popouts:
            title = str(w.get("title") or "").strip()
            if not title:
                continue
            if normalize_chat_name(_clean_title_for_match(title)).casefold() == norm_target:
                return w
        for w in popouts:
            title = str(w.get("title") or "").strip()
            if title and _matches_target(clean_target, title):
                return w
        return None

    def find_popout_window(self, target: str, app: str = "all") -> Optional[Dict[str, Any]]:
        """Find a standalone pop-out chat window whose title matches `target`."""
        if not target or not str(target).strip():
            return None
        return self._match_popout_window(target, self.list_popout_windows(app=app))

    def inspect_popout_window(
        self,
        popout_window: Dict[str, Any],
        *,
        target: Optional[str] = None,
        snapshot_prefix: str = "popout",
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Directly capture and parse bubbles from a pop-out window without switching main chat list."""
        wid = int(popout_window["windowID"])
        win_title = str(popout_window.get("title") or target or "").strip()
        slug = _slugify_target(target or win_title or str(wid))
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        snap_path = self.snapshots_dir / f"{snapshot_prefix}_{slug}_{wid}.png"
        ocr_payload = self._run_native(
            ["capture-ocr", "--window-id", str(wid), "--no-activate", "--out", str(snap_path)],
            timeout,
        )
        if not isinstance(ocr_payload, dict) or not ocr_payload.get("ok"):
            return {
                "ok": False,
                "error_code": (ocr_payload or {}).get("error_code", "capture_failed") if isinstance(ocr_payload, dict) else "capture_failed",
                "error": (ocr_payload or {}).get("error", f"Failed to capture pop-out window #{wid}.") if isinstance(ocr_payload, dict) else f"Failed to capture pop-out window #{wid}.",
                "popoutWindow": True,
                "windowID": wid,
                "popoutWindowID": wid,
                "zeroSwitch": True,
            }
        enriched_ocr = dict(ocr_payload)
        if not enriched_ocr.get("windowTitle") and win_title:
            enriched_ocr["windowTitle"] = win_title
        enriched_ocr["isMainWindow"] = False
        enriched_ocr["splitX"] = 0.0
        bounds = (
            enriched_ocr.get("windowBounds")
            or enriched_ocr.get("bounds")
            or popout_window.get("bounds")
            or {}
        )
        structured = self.extract_structured_bubbles(
            enriched_ocr,
            snapshot_path=snap_path,
            bounds=bounds,
        )
        bubbles = list(structured.get("bubbles") or [])
        header = str(structured.get("headerTitle") or win_title)
        return {
            "ok": True,
            "target": target or header,
            "matchedTitle": header,
            "headerTitle": header,
            "popoutWindow": True,
            "windowID": wid,
            "popoutWindowID": wid,
            "appId": str(popout_window.get("appId") or enriched_ocr.get("appId") or "wechat"),
            "zeroSwitch": True,
            "bounds": bounds,
            "snapshotPath": str(snap_path),
            "bubbles": bubbles,
            "lastBubble": structured.get("lastBubble"),
            "messageCount": len(bubbles),
            "ocrPayload": enriched_ocr,
            "structured": structured,
        }

    def inspect_messages(
        self,
        target: Optional[str] = None,
        *,
        app: str = "all",
        window_id: Optional[int] = None,
        max_pages: int = 5,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Inspect visible chat messages for `target` (direct pop-out capture if open, else main pane)."""
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        popout: Optional[Dict[str, Any]] = None
        if window_id is not None:
            for pw in self.list_popout_windows(app=app):
                if int(pw.get("windowID") or 0) == int(window_id):
                    popout = pw
                    break
        elif target:
            popout = self.find_popout_window(target, app=app)

        if popout is not None and popout.get("windowID"):
            return self.inspect_popout_window(popout, target=target, timeout=timeout)

        if target:
            nav = self.select_session(target, max_pages=max_pages)
            if not nav.get("ok"):
                return nav
            snap_path = Path(nav["snapshotPath"]) if nav.get("snapshotPath") else (
                self.snapshots_dir / f"inspect_{_slugify_target(target)}.png"
            )
            ocr_payload = nav.get("ocrPayload")
            if not isinstance(ocr_payload, dict) or not ocr_payload.get("elements"):
                ocr_payload = self._capture_wechat_ocr(snap_path, timeout=timeout)
            structured = self.extract_structured_bubbles(
                ocr_payload,
                snapshot_path=snap_path,
                bounds=nav.get("bounds"),
            )
            bubbles = list(structured.get("bubbles") or [])
            header = str(structured.get("headerTitle") or nav.get("matchedTitle") or target)
            return {
                "ok": True,
                "target": target,
                "matchedTitle": header,
                "headerTitle": header,
                "popoutWindow": False,
                "zeroSwitch": False,
                "bounds": nav.get("bounds") or {},
                "snapshotPath": str(snap_path),
                "bubbles": bubbles,
                "lastBubble": structured.get("lastBubble"),
                "messageCount": len(bubbles),
                "ocrPayload": ocr_payload,
                "structured": structured,
            }

        snap_path = self.snapshots_dir / "inspect_active_pane.png"
        ocr_payload = self._capture_wechat_ocr(snap_path, timeout=timeout)
        if not isinstance(ocr_payload, dict) or not ocr_payload.get("ok"):
            return {
                "ok": False,
                "error_code": (ocr_payload or {}).get("error_code", "capture_failed") if isinstance(ocr_payload, dict) else "capture_failed",
                "error": (ocr_payload or {}).get("error", "Failed to capture active window.") if isinstance(ocr_payload, dict) else "Failed to capture active window.",
                "popoutWindow": False,
                "zeroSwitch": False,
            }
        structured = self.extract_structured_bubbles(ocr_payload, snapshot_path=snap_path)
        bubbles = list(structured.get("bubbles") or [])
        header = str(structured.get("headerTitle") or ocr_payload.get("windowTitle") or "")
        return {
            "ok": True,
            "target": header,
            "matchedTitle": header,
            "headerTitle": header,
            "popoutWindow": self._is_popout_window(ocr_payload, ocr_payload.get("elements") or []),
            "windowID": ocr_payload.get("windowID"),
            "zeroSwitch": False,
            "bounds": ocr_payload.get("windowBounds") or ocr_payload.get("bounds") or {},
            "snapshotPath": str(snap_path),
            "bubbles": bubbles,
            "lastBubble": structured.get("lastBubble"),
            "messageCount": len(bubbles),
            "ocrPayload": ocr_payload,
            "structured": structured,
        }
