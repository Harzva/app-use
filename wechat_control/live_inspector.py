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
    r"(?:昨天|今天|前天|星期[一二三四五六日天]|周[一二三四五六日天])(?:\s*\d{1,2}:\d{2})?"
    r"|\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?(?:\s*\d{1,2}:\d{2})?"
    r"|\d{1,2}月\d{1,2}日(?:\s*\d{1,2}:\d{2})?"
    r"|\d{1,2}/\d{1,2}(?:\s*\d{1,2}:\d{2})?"
    r"|\d{1,2}:\d{2}"
    r")$"
)


_BADGE_RE = re.compile(r"^\d{1,3}\+?$")


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
    return re.sub(r"\s+", " ", nfkc).strip()


def _matches_target(target: str, candidate: str) -> bool:
    t_norm = normalize_chat_name(_clean_title_for_match(target)).casefold()
    if not t_norm or not candidate:
        return False
    c_clean = normalize_chat_name(_clean_title_for_match(candidate)).casefold()
    if not c_clean:
        return False
    # Reject message preview lines like "心安: [链接]..."
    if ":" in c_clean or "：" in c_clean:
        return False
    # Prevent 1-on-1 friend name from matching multi-person group chat title containing "、"
    if "、" in c_clean and "、" not in t_norm:
        return False
    if t_norm == c_clean:
        return True
    for marker in ("...", "⋯", "…", ".."):
        if marker in c_clean:
            prefix = c_clean.split(marker, 1)[0].strip()
            if len(prefix) >= 2 and t_norm.startswith(prefix):
                return True
    if len(t_norm) >= 4 and len(c_clean) >= 4 and (t_norm in c_clean or c_clean in t_norm):
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
    def _cluster_session_rows(elements: List[Dict[str, Any]], split_x: float, win_h: float) -> List[Dict[str, Any]]:
        """Group OCR fragments in the middle session column (64 <= x <= split_x) into chat rows."""
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
                if abs(g["center"]["y"] - top_y) <= 10.0 and ":" not in cleaned_no_ts and "：" not in cleaned_no_ts:
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

            matching_badges = [
                b for b in badge_els
                if abs(b["center"]["y"] - avg_y) <= 24.0
            ]
            matching_badges.sort(
                key=lambda b: (b["center"]["x"] > 95.0, abs(b["center"]["y"] - avg_y))
            )
            unread_badge = matching_badges[0]["text"].strip() if matching_badges else ""

            title_x = float((title_el.get("bbox") or {}).get("x") or 118.0)
            avatar_x = round(max(64.0, min(80.0, title_x - 48.0)), 1)

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
                    "y": round(avg_y - 20.0, 1),
                    "width": 40.0,
                    "height": 40.0,
                },
            })
        return summarized

    @staticmethod
    def _parse_right_pane(elements: List[Dict[str, Any]], split_x: float, win_h: float) -> Dict[str, Any]:
        """Extract untruncated header title and chat message lines from the right pane."""
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
            sample_points = (
                (max(split_x + 12.0, bx - 4.0), cy),
                (cx if bw <= 0 else (bx + bw * 0.5), max(49.0, by - 3.0)),
                (min(win_w - 18.0, right_px + 8.0), cy),
                (cx if bw <= 0 else (bx + bw * 0.5), bottom_px + 3.0),
            )
            green_hits = sum(1 for px, py in sample_points if _is_wechat_green_rgb(sampler(px, py)))
            return "self" if green_hits >= 1 else "peer"

        pane_w = max(1.0, win_w - split_x)
        mid_x = bx + bw / 2.0 if bw > 0 else cx
        right_edge = bx + bw if bw > 0 else cx
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
            bh = float(bbox.get("height", 16.0) or 16.0)
            by = float(bbox.get("y", y_center - bh * 0.5))
            y_top = by
            y_bottom = by + bh

            if (
                current is not None
                and current["direction"] == direction
                and current["timeMarker"] == active_time_marker
                and -4.0 <= (y_center - float(current["_lastCenterY"])) <= 34.0
            ):
                current["lines"].append(txt)
                current["text"] = WeChatLiveInspector._join_bubble_lines(current["lines"])
                current["yBottom"] = round(max(float(current["yBottom"]), y_bottom), 1)
                current["_lastCenterY"] = max(float(current["_lastCenterY"]), y_center)
            else:
                current = {
                    "direction": direction,
                    "text": txt,
                    "lines": [txt],
                    "timeMarker": active_time_marker,
                    "yTop": round(y_top, 1),
                    "yBottom": round(y_bottom, 1),
                    "_lastCenterY": y_center,
                }
                bubbles.append(current)

        for b in bubbles:
            b.pop("_lastCenterY", None)
        return bubbles

    def extract_structured_bubbles(
        self,
        ocr_payload: Dict[str, Any],
        *,
        snapshot_path: Optional[Path] = None,
        bounds: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extract right-pane header + clustered message bubbles from a capture-ocr payload."""
        resolved_bounds = bounds or ocr_payload.get("window") or ocr_payload.get("bounds") or {}
        win_w = float(resolved_bounds.get("width", 585.0) or 585.0)
        win_h = float(resolved_bounds.get("height", 640.0) or 640.0)
        split_x = float(ocr_payload.get("splitX") or self._split_x(win_w))
        elements = ocr_payload.get("elements") or []
        right_info = self._parse_right_pane(elements, split_x, win_h)
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

    def _click_rel(self, bounds: Dict[str, Any], rel_x: float, rel_y: float) -> None:
        abs_x = float(bounds["x"]) + rel_x
        abs_y = float(bounds["y"]) + rel_y
        self._run_native(["click", "--x", f"{abs_x:.1f}", "--y", f"{abs_y:.1f}"], 5.0)

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

    def inspect_live(self, *, max_session_pages: int = 2, max_contact_pages: int = 4) -> Dict[str, Any]:
        """Run a full read-only walkthrough of the currently open WeChat window."""
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        status = self._activate_and_get_status()
        win = status["windows"][0]
        bounds = win["bounds"]
        win_w = float(bounds["width"])
        win_h = float(bounds["height"])
        split_x = self._split_x(win_w)
        post_event_trusted = bool(status.get("postEventTrusted"))
        ax_trusted = bool(status.get("accessibilityTrusted"))

        if not post_event_trusted:
            overview_path = self.snapshots_dir / "sessions_overview_p0.png"
            overview_ocr = self._capture_wechat_ocr(overview_path)
            elements = overview_ocr.get("elements") or []
            rows = self._cluster_session_rows(elements, split_x, win_h)
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
            rows = self._cluster_session_rows(overview_ocr.get("elements") or [], split_x, win_h)
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
                right_info = self._parse_right_pane(elements, split_x, win_h)

                # If clicking entered a folder (like 服务号/公众号), return back to Chats list
                mid_after = self._cluster_session_rows(elements, split_x, win_h)
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
        rows = self._cluster_session_rows(elements, split_x, win_h)
        for row in rows:
            if _matches_target(target, row["titleSnippet"]):
                self._click_rel(bounds, row["clickRelX"], row["clickRelY"])
                self._sleep(0.45)
                click_snap = self.snapshots_dir / f"nav_{slug}_matched.png"
                cap = self._capture_wechat_ocr(click_snap)
                cap_els = cap.get("elements") or []
                after_right = self._parse_right_pane(cap_els, split_x, win_h)
                if after_right["headerTitle"] and _matches_target(target, after_right["headerTitle"]):
                    return {
                        "ok": True,
                        "target": target,
                        "matchedTitle": after_right["headerTitle"],
                        "alreadyOpen": False,
                        "bounds": bounds,
                        "splitX": split_x,
                        "snapshotPath": str(click_snap),
                        "ocrPayload": cap,
                    }
                self._return_from_folder_if_needed(bounds, rows, cap_els, split_x, win_h)

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
            page_rows = self._cluster_session_rows(page_els, split_x, win_h)
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
                    m_right = self._parse_right_pane(m_els, split_x, win_h)
                    if m_right["headerTitle"] and _matches_target(target, m_right["headerTitle"]):
                        return {
                            "ok": True,
                            "target": target,
                            "matchedTitle": m_right["headerTitle"],
                            "alreadyOpen": False,
                            "bounds": bounds,
                            "splitX": split_x,
                            "snapshotPath": str(matched_snap),
                            "ocrPayload": m_cap,
                        }
                    self._return_from_folder_if_needed(bounds, page_rows, m_els, split_x, win_h)

            if page + 1 < max_pages:
                self._scroll_rel(bounds, safe_session_x, min(win_h - 80.0, 320.0), dy=-8)
                self._sleep(0.45)

        return {
            "ok": False,
            "error_code": "target_not_found",
            "target": target,
            "error": f"Could not navigate to or verify right-pane header matching target {target!r} within {max_pages} session pages.",
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
