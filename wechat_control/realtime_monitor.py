"""Real-time macOS WeChat message monitor & intelligent auto-responder.

Runs incremental OCR / pixel-verified bubble monitoring over bound contacts,
guards against double-replies and self-message loops, supports human takeover
(`takeover` / `resume`), and generates replies via the local FTS5 WeChat
customer-service knowledge base, domain terminology, and switchable personas.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import struct
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .contact_profiler import CARE_LEVEL_ORDER, normalize_care_level
from .live_inspector import _matches_target, _slugify_target
from .media_link_analyzer import (
    extract_assistant_insights_from_bubbles,
    is_explicit_wechat_ai_mention,
    is_wechat_ai_assistant_name,
)
from .multi_window_scheduler import UnreadDeltaTracker
from .safety import normalize_chat_name

if TYPE_CHECKING:
    from .engine import WeChatControlEngine

_TODAY_HHMM_RE = re.compile(r"(?:^|\|\s*)\d{1,2}:\d{2}(?:\s*\||$)")
_PREFIX_TS_RE = re.compile(
    r"^(?:昨天|今天|前天|星期[一二三四五六日天]|周[一二三四五六日天]|\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2})\s*\|?\s*"
)


def _is_ai_bot_sandbox_target(target: str) -> bool:
    """Return True for explicit AI test-bot contacts (e.g. ClawBot / 微信ClawBot) allowed rapid sandbox dialogue."""
    return "clawbot" in normalize_chat_name(str(target or "")).casefold()


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_row_timestamp(preview_snippet: str) -> str:
    text = unicodedata.normalize("NFKC", preview_snippet or "").strip()
    parts = [p.strip() for p in text.split("|") if p.strip()]
    kept: List[str] = []
    for part in parts:
        if _TODAY_HHMM_RE.match(part) or _PREFIX_TS_RE.fullmatch(part):
            continue
        cleaned = _PREFIX_TS_RE.sub("", part).strip()
        if cleaned:
            kept.append(cleaned)
    return " ".join(kept).strip()


def _preview_matches_outbound(preview_snippet: str, recent_outbound: List[str]) -> bool:
    if not recent_outbound:
        return False
    stripped = _strip_row_timestamp(preview_snippet)
    if not stripped:
        return False
    clean_stripped = stripped.rstrip("….").strip()
    if len(clean_stripped) < 4:
        return False
    for out_text in recent_outbound:
        norm_out = unicodedata.normalize("NFKC", out_text or "").strip()
        if not norm_out:
            continue
        if norm_out.startswith(clean_stripped) or clean_stripped in norm_out:
            return True
    return False


_HUMAN_HANDOFF_KEYWORDS = (
    "转人工", "转接人工", "人工客服", "找人工", "人工服务", "找真人", "真人客服", "人工接管",
)


_TIMESTAMP_TEXT_RE = re.compile(
    r"^(?:昨天|前天|今天|星期[一二三四五六日天]|周[一二三四五六日天]|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)?\s*"
    r"\d{1,2}:\d{2}(?::\d{2})?\s*(?:上午|下午|am|pm)?$",
    re.IGNORECASE,
)


def _looks_like_timestamp(text: str) -> bool:
    """OCR 把时间戳行误分类为 message 的防御：纯时间标记不是对话内容。"""
    norm = unicodedata.normalize("NFKC", str(text or "")).strip()
    return bool(norm) and bool(_TIMESTAMP_TEXT_RE.match(norm))


def _is_human_handoff_request(text: str) -> bool:
    """客户明确要求真人接管（转人工）。短语匹配，NFKC 归一后判断。"""
    norm = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    if not norm:
        return False
    return any(kw in norm for kw in _HUMAN_HANDOFF_KEYWORDS)


def _bubble_signature(
    target: str,
    last_bubble: Dict[str, Any],
    preceding_self_text: str,
) -> str:
    norm_t = normalize_chat_name(target)
    payload = "|".join([
        norm_t,
        str(last_bubble.get("timeMarker") or ""),
        str(last_bubble.get("text") or "").strip(),
        str(preceding_self_text or "").strip(),
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


class WeChatRealtimeMonitor:
    """Polls live WeChat panes/rows and dispatches guarded KB + persona auto-replies."""

    def __init__(
        self,
        engine: "WeChatControlEngine",
        *,
        state_path: Path,
        events_path: Path,
    ) -> None:
        self.engine = engine
        self.state_path = Path(state_path)
        self.events_path = Path(events_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)

    def _default_state(self) -> Dict[str, Any]:
        return {
            "schema": "openbot.wechat-monitor-state/1",
            "updatedAt": _utc_iso_now(),
            "daemon": {
                "running": False,
                "pid": None,
                "startedAt": None,
                "lastHeartbeatAt": None,
                "lastPollAt": None,
                "cyclesCompleted": 0,
                "repliesDispatched": 0,
                "lastError": "",
            },
            "contacts": {},
        }

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("daemon", self._default_state()["daemon"])
                raw.setdefault("contacts", {})
                return raw
        except Exception:
            pass
        return self._default_state()

    def state_summary(self) -> Dict[str, Any]:
        """公开状态摘要（供诊断/首页聚合使用），替代外部直接调私有 _load_state。"""
        return self._load_state()

    def _save_state(self, state: Dict[str, Any]) -> None:
        state["updatedAt"] = _utc_iso_now()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def _append_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        now_ts = _utc_iso_now()
        if event_type in ("poll_error", "human_active_paused") and self.events_path.exists():
            try:
                lines = [ln for ln in self.events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if lines:
                    last = json.loads(lines[-1])
                    if (
                        isinstance(last, dict)
                        and last.get("event") == event_type
                        and (event_type != "poll_error" or last.get("error") == payload.get("error"))
                    ):
                        last.update(payload)
                        last["ts"] = now_ts
                        last["repeatCount"] = int(last.get("repeatCount") or 1) + 1
                        lines[-1] = json.dumps(last, ensure_ascii=False)
                        self.events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                        return
            except Exception:
                pass
        record = {
            "ts": now_ts,
            "event": event_type,
            **payload,
        }
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _contact_entry(self, state: Dict[str, Any], target: str) -> Dict[str, Any]:
        key = normalize_chat_name(target)
        contacts = state.setdefault("contacts", {})
        if key not in contacts or not isinstance(contacts[key], dict):
            contacts[key] = {
                "target": target,
                "normalizedTarget": key,
                "lastProcessedPeerSig": "",
                "lastProcessedPeerText": "",
                "lastPreviewedPeerSig": "",
                "lastSeenPreview": "",
                "lastOutboundText": "",
                "recentOutboundTexts": [],
                "takenOver": False,
                "takeoverReason": "",
                "takeoverAt": None,
                "pendingDraft": None,
                "lastRepliedAt": None,
                "lastPostSendSnapshot": None,
            }
        elif not contacts[key].get("target"):
            contacts[key]["target"] = target
        return contacts[key]

    def recent_events(self, limit: int = 30) -> List[Dict[str, Any]]:
        if not self.events_path.exists():
            return []
        try:
            lines = [ln.strip() for ln in self.events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            parsed: List[Dict[str, Any]] = []
            for ln in lines[-max(1, int(limit)) :]:
                try:
                    item = json.loads(ln)
                    if isinstance(item, dict):
                        parsed.append(item)
                except Exception:
                    continue
            parsed.reverse()
            return parsed
        except Exception:
            return []

    def get_status(self, *, event_limit: int = 25) -> Dict[str, Any]:
        state = self._load_state()
        events = self.recent_events(limit=event_limit)
        return {
            "ok": True,
            "stateFile": str(self.state_path),
            "eventsFile": str(self.events_path),
            "daemon": state.get("daemon", {}),
            "contacts": state.get("contacts", {}),
            "contactCount": len(state.get("contacts", {})),
            "recentEvents": events,
            "eventCount": len(events),
        }

    def takeover_contact(self, target: str, reason: str = "") -> Dict[str, Any]:
        state = self._load_state()
        entry = self._contact_entry(state, target)
        entry["takenOver"] = True
        entry["takeoverReason"] = (reason or "manual_human_takeover").strip()
        entry["takeoverAt"] = _utc_iso_now()
        self._save_state(state)
        self._append_event("takeover", {"target": target, "reason": entry["takeoverReason"]})
        return {"ok": True, "target": target, "contactState": entry}

    def resume_contact(self, target: str) -> Dict[str, Any]:
        state = self._load_state()
        entry = self._contact_entry(state, target)
        entry["takenOver"] = False
        entry["takeoverReason"] = ""
        entry["takeoverAt"] = None
        self._save_state(state)
        self._append_event("resume_contact", {"target": target})
        return {"ok": True, "target": target, "contactState": entry}

    @staticmethod
    def _png_size(path) -> Optional[Dict[str, int]]:
        """读 PNG 尺寸（IHDR），供图片消息全图裁剪识别。"""
        try:
            with open(path, "rb") as fh:
                head = fh.read(24)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return {"x": 0, "y": 0, "width": int(w), "height": int(h)}
        except Exception:
            pass
        return None

    def _capture_live_window(self) -> Dict[str, Any]:
        status = self.engine._run_native(["status"], 10.0)
        windows = status.get("windows") or []
        if not status.get("wechatRunning") or not windows:
            act = self.engine._run_native(["activate"], 12.0)
            time.sleep(0.35)
            status = self.engine._run_native(["status"], 10.0)
            windows = status.get("windows") or []
            if windows and act.get("recoveryMethod"):
                self._append_event(
                    "window_auto_restored",
                    {
                        "recoveryMethod": act.get("recoveryMethod"),
                        "wechatPID": status.get("wechatPID"),
                    },
                )
        if not status.get("ok") or not status.get("wechatRunning"):
            return {"ok": False, "error_code": "wechat_not_running", "error": f"WeChat is not running: {status}"}
        if not windows:
            return {"ok": False, "error_code": "no_window", "error": "No visible WeChat main window."}

        win = windows[0]
        bounds = win["bounds"]
        self.engine.inspector.snapshots_dir.mkdir(parents=True, exist_ok=True)
        snap_path = self.engine.inspector.snapshots_dir / "monitor_poll_cur.png"
        # 统一走 capture_wechat_ocr 封装：窗口定向 + 遮挡重试（裸调用曾占 poll_error 的 71%）
        ocr_payload = self.engine.capture_wechat_ocr(snap_path, timeout=30.0)
        if not ocr_payload.get("ok"):
            return {
                "ok": False,
                "error_code": ocr_payload.get("error_code", "ocr_failed"),
                "error": ocr_payload.get("error", "capture-ocr failed during monitor poll."),
            }
        return {
            "ok": True,
            "bounds": bounds,
            "snapshotPath": snap_path,
            "ocrPayload": ocr_payload,
        }

    def _inspect_target_bubbles(
        self,
        target: str,
        *,
        active_header: str,
        active_structured: Dict[str, Any],
        in_row: Optional[Dict[str, Any]],
        contact_state: Dict[str, Any],
        force_open: bool,
        popout_windows: Optional[List[Dict[str, Any]]] = None,
        prefetched_popout: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Inspect a single contact's chat pane, preferring direct pop-out capture (zero-switch)."""
        popout_win = (
            self.engine.inspector._match_popout_window(target, popout_windows)
            if popout_windows is not None
            else self.engine.inspector.find_popout_window(target)
        )
        if popout_win is not None and popout_win.get("windowID"):
            popout_res = prefetched_popout or self.engine.inspector.inspect_popout_window(
                popout_win,
                target=target,
                snapshot_prefix="monitor_popout",
            )
            wid = int(popout_win["windowID"])
            if not popout_res.get("ok"):
                return {
                    "checked": False,
                    "error": popout_res.get("error", f"Failed to capture pop-out window #{wid}"),
                    "skipReason": popout_res.get("error_code") or "popout_capture_failed",
                    "popoutWindow": True,
                    "popoutWindowID": wid,
                    "zeroSwitch": True,
                }
            matched_title = str(popout_res.get("matchedTitle") or target)
            bubbles = list((popout_res.get("structured") or {}).get("bubbles") or [])
            if bubbles and hasattr(self.engine.inspector, "_persist_contact_history"):
                try:
                    self.engine.inspector._persist_contact_history(
                        target,
                        matched_title,
                        bubbles,
                        popout_res.get("snapshotPath"),
                    )
                except Exception:
                    pass
            return {
                "checked": True,
                "source": "popout_window",
                "matchedTitle": matched_title,
                "structured": popout_res["structured"],
                "snapshotPath": popout_res.get("snapshotPath"),
                "bounds": popout_res.get("bounds") or popout_win.get("bounds"),
                "rowPreview": str((in_row or {}).get("previewSnippet") or ""),
                "popoutWindow": True,
                "popoutWindowID": wid,
                "windowID": wid,
                "zeroSwitch": True,
            }

        if _matches_target(target, active_header):
            bubbles = list((active_structured or {}).get("bubbles") or [])
            if bubbles and hasattr(self.engine.inspector, "_persist_contact_history"):
                try:
                    self.engine.inspector._persist_contact_history(
                        target,
                        active_header,
                        bubbles,
                        None,
                    )
                except Exception:
                    pass
            return {
                "checked": True,
                "source": "active_pane",
                "matchedTitle": active_header,
                "structured": active_structured,
            }

        row_preview = str((in_row or {}).get("previewSnippet") or "")
        unread_badge = str((in_row or {}).get("unreadBadge") or "")
        prev_preview = str(contact_state.get("lastSeenPreview") or "")
        recent_outbound = list(contact_state.get("recentOutboundTexts") or [])
        if contact_state.get("lastOutboundText"):
            recent_outbound.append(str(contact_state["lastOutboundText"]))

        should_open = force_open or bool(unread_badge) or bool(contact_state.get("pendingGapRetry"))
        trigger_reason = (
            "unread_badge" if unread_badge else ("gap_retry" if contact_state.get("pendingGapRetry") else ("target_filter" if force_open else ""))
        )

        if not should_open and in_row is not None and row_preview:
            if _preview_matches_outbound(row_preview, recent_outbound):
                contact_state["lastSeenPreview"] = row_preview
                return {"checked": False, "skipReason": "row_matches_last_outbound", "rowPreview": row_preview}
            if not prev_preview:
                if _TODAY_HHMM_RE.search(row_preview):
                    should_open = True
                    trigger_reason = "today_activity_preview"
                else:
                    # Baseline non-today historical rows without clicking away from active screen
                    contact_state["lastSeenPreview"] = row_preview
                    return {"checked": False, "skipReason": "baseline_historical_row", "rowPreview": row_preview}
            elif row_preview != prev_preview:
                should_open = True
                trigger_reason = "preview_changed"

        if not should_open:
            return {"checked": False, "skipReason": "no_change", "rowPreview": row_preview}

        nav = self.engine.inspector.select_session(target)
        if not nav.get("ok"):
            return {
                "checked": False,
                "error": nav.get("error", f"Failed to select session {target!r}"),
                "skipReason": "navigation_failed",
            }
        snap_path = Path(nav["snapshotPath"]) if nav.get("snapshotPath") else (
            self.engine.inspector.snapshots_dir / f"monitor_{_slugify_target(target)}.png"
        )
        ocr_payload = nav.get("ocrPayload")
        if not isinstance(ocr_payload, dict) or not ocr_payload.get("elements"):
            # 同上：统一封装（窗口定向 + 遮挡重试），避免 OCR 出空后误判为噪声输入
            ocr_payload = self.engine.capture_wechat_ocr(snap_path, timeout=30.0)
        structured = self.engine.inspector.extract_structured_bubbles(
            ocr_payload,
            snapshot_path=snap_path,
            bounds=nav.get("bounds"),
        )
        matched_title = str(structured.get("headerTitle") or nav.get("matchedTitle") or target)
        bubbles = list(structured.get("bubbles") or [])
        if bubbles and hasattr(self.engine.inspector, "_persist_contact_history"):
            try:
                self.engine.inspector._persist_contact_history(
                    target,
                    matched_title,
                    bubbles,
                    str(snap_path),
                )
            except Exception:
                pass
        return {
            "checked": True,
            "source": trigger_reason or "selected_session",
            "matchedTitle": matched_title,
            "structured": structured,
            "snapshotPath": str(snap_path),
            "bounds": nav.get("bounds"),
            "rowPreview": row_preview,
        }

    def _agent_dispatch_notes(
        self,
        binding: Dict[str, Any],
        target: str,
        bubbles: List[Dict[str, Any]],
        incoming_text: str,
        inspected: Dict[str, Any],
        *,
        active_cards: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[str], Optional[Dict[str, Any]]]:
        """Agent 分发与链接/图片/视频/视频号/公众号卡片深读：产出注入回复上下文的识别备注（并持久化 media_note）。

        返回 (extra_notes, dispatched_receipt)；深读失败静默降级，不影响回复主流程。
        """
        extra_notes: List[str] = []
        dispatched_receipt: Optional[Dict[str, Any]] = None
        card_targets: List[Dict[str, Any]] = []
        deep_read_card_texts: set[str] = set()
        vision_model = str(binding.get("visionModelId") or "auto/deepseek-v4.1-flash")

        # 1) 优先识别当前屏幕可见的视频号/公众号文章/图片/视频卡片（并按需主动点击深读），防止旧历史笔记抢占焦点
        try:
            detected_cards = (
                list(active_cards)
                if active_cards is not None
                else list(UnreadDeltaTracker.extract_unread_delta(bubbles).get("activeMediaCards") or [])
            )
            card_targets = [
                c for c in detected_cards
                if str(c.get("mediaType") or "") in ("channels_video", "wechat_article", "video", "image")
            ]
        except Exception:
            card_targets = []

        if card_targets and hasattr(self.engine, "media_analyzer"):
            snap_path = Path(inspected["snapshotPath"]) if inspected.get("snapshotPath") else None
            win_bounds = inspected.get("bounds") if isinstance(inspected.get("bounds"), dict) else None
            win_id = inspected.get("windowID") or inspected.get("popoutWindowID")
            for card in card_targets[-3:]:
                card_txt = str(card.get("text") or "").strip()
                if card_txt:
                    deep_read_card_texts.add(card_txt[:120])
                if hasattr(self.engine.media_analyzer, "click_and_deep_read_bubble"):
                    try:
                        cres = self.engine.media_analyzer.click_and_deep_read_bubble(
                            card,
                            window_bounds=win_bounds,
                            window_id=int(win_id) if win_id else None,
                            snapshot_path=snap_path,
                            contact=target,
                            context_text=incoming_text,
                            click_to_open=bool(win_bounds),
                            model_id=vision_model,
                        )
                        if cres.get("ok") and cres.get("note"):
                            note_str = str(cres["note"]).strip()
                            if note_str not in extra_notes:
                                extra_notes.append(note_str)
                                try:
                                    self.engine.append_media_note(target, note_str)
                                except Exception:
                                    pass
                            continue
                    except Exception:
                        pass
                # 降级：直接把结构化卡片信息写入置顶上下文
                cm = dict(card.get("cardMeta") or {})
                mtype = str(card.get("mediaType") or "card")
                tag = "当前画面视频号卡片" if mtype == "channels_video" else ("当前画面公众号文章卡片" if mtype == "wechat_article" else "当前画面媒体卡片")
                fallback_note = f"[{tag}:{cm.get('cardSource') or mtype}] {cm.get('cardTitle') or card_txt[:120]}" + (
                    f" — {cm.get('cardDigest')}" if cm.get("cardDigest") else ""
                )
                if fallback_note not in extra_notes:
                    extra_notes.append(fallback_note)

        # 2) 收割微信原生助手（元宝 / 小微）总结；仅在当前屏幕无明确媒体卡片时再回溯历史 media_note，避免旧链接张冠李戴
        try:
            for ai_note in extract_assistant_insights_from_bubbles(bubbles[-8:]):
                if ai_note not in extra_notes:
                    extra_notes.append(ai_note)
                    try:
                        self.engine.append_media_note(target, ai_note)
                    except Exception:
                        pass
            if not card_targets and hasattr(self.engine, "recent_media_notes"):
                for persisted_note in self.engine.recent_media_notes(target, limit=2):
                    if persisted_note not in extra_notes:
                        extra_notes.append(persisted_note)
        except Exception:
            pass

        if not (hasattr(self.engine, "agent_dispatcher") and (
            binding.get("boundAgentId") or binding.get("autoAnalyzeLinksAndMedia", True)
        )):
            if card_targets and extra_notes:
                dispatched_receipt = {
                    "boundAgentId": binding.get("boundAgentId") or "bot_wechat_ecosystem",
                    "tasks": [{"kind": "card_deep_read", "category": c.get("mediaType"), "rawText": str(c.get("text") or "")[:120]} for c in card_targets[:4]],
                    "notes": extra_notes,
                }
            return extra_notes, dispatched_receipt
        try:
            parsed_tasks = self.engine.agent_dispatcher.parse_messages_for_instructions(
                target,
                bubbles[-8:],
                snapshot_path=Path(inspected["snapshotPath"]) if inspected.get("snapshotPath") else None,
            )
            interesting = [
                t
                for t in parsed_tasks
                if t.get("kind") in ("link_deep_read", "agent_instruction", "video_analysis", "image_card_analysis")
            ]
            _kind_prio = {
                "link_deep_read": 0,
                "video_analysis": 1,
                "image_card_analysis": 2,
                "agent_instruction": 3,
            }
            interesting.sort(
                key=lambda t: (
                    0 if (t.get("isLatest") or (incoming_text and incoming_text[:24] in str(t.get("rawText") or ""))) else 1,
                    _kind_prio.get(str(t.get("kind") or ""), 9),
                )
            )
            if interesting and (
                any(t.get("kind") == "link_deep_read" for t in interesting)
                or binding.get("autoDispatchInstructions", True)
            ):
                has_ai_insight = any(n.startswith(("[元宝深读:", "[小微深读:")) for n in extra_notes)
                for it in interesting[:3]:
                    raw_it_txt = str(it.get("rawText") or "").strip()
                    if it.get("kind") in ("video_analysis", "image_card_analysis") and raw_it_txt[:120] in deep_read_card_texts:
                        continue
                    if it.get("kind") == "link_deep_read" and it.get("url") and hasattr(self.engine, "media_analyzer"):
                        lres = self.engine.media_analyzer.analyze_link(
                            str(it["url"]),
                            contact=target,
                            context_text=incoming_text,
                            model_id=vision_model,
                        )
                        if lres.get("summary"):
                            extra_notes.append(f"[链接深读:{lres.get('title','')}] {lres.get('summary')}")
                    elif it.get("kind") == "image_card_analysis" and hasattr(self.engine, "media_analyzer"):
                        # 图片/图文卡片深读：对巡检快照做 2x Vision OCR + 视觉模型识别
                        snap_path = Path(inspected["snapshotPath"]) if inspected.get("snapshotPath") else None
                        crop_region = self._png_size(snap_path) if snap_path else None
                        if crop_region and not extra_notes:
                            ires = self.engine.media_analyzer.analyze_image_or_card(
                                source_snapshot=snap_path,
                                crop_region=crop_region,
                                from_viewer_window=False,
                                contact=target,
                                context_text=raw_it_txt or incoming_text,
                                model_id=vision_model,
                            )
                            if ires.get("summary"):
                                extra_notes.append(f"[图片识别:{ires.get('title','') or '图片'}] {ires.get('summary')}")
                    elif it.get("kind") == "video_analysis" and hasattr(self.engine, "media_analyzer"):
                        if not card_targets:
                            vres = self.engine.media_analyzer.analyze_video(
                                from_viewer_window=True,
                                window_title="图片和视频",
                                contact=target,
                                context_text=raw_it_txt or incoming_text,
                                model_id=vision_model,
                            )
                            if vres.get("summary"):
                                extra_notes.append(f"[视频识别:{vres.get('title','') or '视频'}] {vres.get('summary')}")
                            elif not has_ai_insight and binding.get("autoConsultWeChatAi", False):
                                ares = self.engine.media_analyzer.consult_wechat_assistant(
                                    target,
                                    incoming_text,
                                    bubbles=bubbles,
                                    dry_run=False,
                                    model_id=vision_model,
                                )
                                if ares.get("note"):
                                    extra_notes.append(str(ares["note"]))
                                    has_ai_insight = True
                    else:
                        extra_notes.append(f"[识别指令:{it.get('category')}] {raw_it_txt}")
                if extra_notes:
                    for note in extra_notes:
                        try:
                            self.engine.append_media_note(target, note)
                        except Exception:
                            pass
                    dispatched_receipt = {
                        "boundAgentId": binding.get("boundAgentId") or "bot_wechat_ecosystem",
                        "tasks": interesting[:4],
                        "notes": extra_notes,
                    }
        except Exception:
            if card_targets and extra_notes:
                dispatched_receipt = {
                    "boundAgentId": binding.get("boundAgentId") or "bot_wechat_ecosystem",
                    "tasks": [{"kind": "card_deep_read", "category": c.get("mediaType")} for c in card_targets[:4]],
                    "notes": extra_notes,
                }
        return extra_notes, dispatched_receipt

    def _memory_context_with_history(self, target: str) -> Optional[Dict[str, Any]]:
        """联系人记忆画像 + 聊天历史往来摘要（历史缺失不阻塞回复生成）。"""
        mem_ctx = (
            self.engine.soul_profiler.get_contact_memory_context(target)
            if hasattr(self.engine, "soul_profiler")
            else None
        )
        try:
            history_snippet = self.engine.recent_history_thread(target, limit=6)
            if history_snippet:
                mem_ctx = dict(mem_ctx or {})
                mem_ctx["historyThreadSnippet"] = history_snippet
        except Exception:
            pass  # 历史上下文缺失不阻塞回复生成
        return mem_ctx

    def poll_once(
        self,
        *,
        target_filter: Optional[str] = None,
        auto_reply: bool = True,
        confirm_send: bool = False,
        ignore_human_guard: bool = False,
    ) -> Dict[str, Any]:
        """Run one incremental scan & optional guarded auto-reply cycle across bound contacts."""
        state = self._load_state()
        popout_windows: List[Dict[str, Any]] = []
        if hasattr(self.engine, "inspector") and hasattr(self.engine.inspector, "list_popout_windows"):
            popout_windows = self.engine.inspector.list_popout_windows()

        all_bindings = self.engine.bindings.list_bindings()
        hosting_targets = None
        try:
            hosting_status = self.engine.hosting_manager.status()
            if hosting_status.get("running") or hosting_status.get("enabled"):
                ht = hosting_status.get("targets") or []
                hosting_targets = {normalize_chat_name(str(t)).casefold() for t in ht if str(t).strip()}
        except Exception:
            hosting_targets = None

        targets: List[Dict[str, Any]] = []
        for b in all_bindings:
            if not b.get("autoReplyEnabled", True) and not target_filter:
                continue
            if target_filter and not _matches_target(target_filter, b["target"]):
                continue
            if hosting_targets is not None and normalize_chat_name(str(b.get("target") or "")).casefold() not in hosting_targets:
                continue
            targets.append(b)

        has_sandbox_bot = any(_is_ai_bot_sandbox_target(str(b.get("target") or "")) for b in targets)
        guard_can_operate = True
        guard_kb_idle: Optional[float] = None
        guard_state: Dict[str, Any] = {}
        if not ignore_human_guard and hasattr(self.engine, "human_guard"):
            guard_state = self.engine.human_guard.check_can_operate()
            guard_can_operate = bool(guard_state.get("canOperate", True))
            if guard_state.get("keyboardIdleSeconds") is not None:
                try:
                    guard_kb_idle = float(guard_state.get("keyboardIdleSeconds"))
                except (TypeError, ValueError):
                    guard_kb_idle = None
            if not guard_can_operate:
                kb_busy = guard_kb_idle is not None and guard_kb_idle < 1.2
                is_security_agent = str(guard_state.get("status") or "") == "security_agent_paused"
                if (not has_sandbox_bot) or is_security_agent or kb_busy:
                    state["daemon"]["pausedByHumanGuard"] = True
                    state["daemon"]["lastPollAt"] = _utc_iso_now()
                    state["daemon"]["humanGuard"] = guard_state
                    self._save_state(state)
                    self._append_event(
                        "human_active_paused",
                        {
                            "status": guard_state.get("status"),
                            "remainingCooldownSeconds": guard_state.get("remainingCooldownSeconds", 0.0),
                            "anyInputIdleSeconds": guard_state.get("anyInputIdleSeconds"),
                            "triggerReason": guard_state.get("triggerReason", ""),
                        },
                    )
                    return {
                        "ok": True,
                        "pausedByHumanGuard": True,
                        "humanGuard": guard_state,
                        "repliesDispatched": 0,
                        "cyclesCompleted": state["daemon"].get("cyclesCompleted", 0),
                    }
            if guard_can_operate and state["daemon"].get("pausedByHumanGuard"):
                state["daemon"]["pausedByHumanGuard"] = False
                state["daemon"]["humanGuard"] = guard_state
                self._append_event(
                    "human_idle_resumed",
                    {
                        "anyInputIdleSeconds": guard_state.get("anyInputIdleSeconds"),
                        "idleResumeSeconds": guard_state.get("idleResumeSeconds"),
                    },
                )

        # Priority scanning: Special Care (P0) -> VIP (P1) -> Normal (P2)
        targets.sort(
            key=lambda b: (
                CARE_LEVEL_ORDER.get(normalize_care_level(b.get("careLevel"), b.get("specialCare")), 2),
                str(b.get("target") or ""),
            )
        )

        # Match open standalone pop-out windows and skip main-window OCR when all targets already live in pop-outs
        popout_by_target: Dict[str, Dict[str, Any]] = {}
        if popout_windows and hasattr(self.engine, "inspector"):
            for b in targets:
                t_name = str(b.get("target") or "")
                pw = self.engine.inspector._match_popout_window(t_name, popout_windows)
                if pw is not None and pw.get("windowID"):
                    popout_by_target[t_name] = pw

        all_covered_by_popouts = bool(targets) and len(popout_by_target) == len(targets)
        prefetched_popouts: Dict[str, Dict[str, Any]] = {}
        if len(popout_by_target) >= 2:
            def _fetch_pop(item: Tuple[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
                t_name, pw_dict = item
                return t_name, self.engine.inspector.inspect_popout_window(
                    pw_dict, target=t_name, snapshot_prefix="monitor_popout"
                )
            with ThreadPoolExecutor(max_workers=min(5, len(popout_by_target))) as cap_pool:
                for t_name, pres in cap_pool.map(_fetch_pop, list(popout_by_target.items())):
                    prefetched_popouts[t_name] = pres

        if all_covered_by_popouts:
            bounds = {}
            elements = []
            rows = []
            active_structured = {"headerTitle": "", "bubbles": [], "lastBubble": None}
            active_header = ""
        else:
            cap = self._capture_live_window()
            if not cap.get("ok"):
                if popout_windows:
                    bounds = {}
                    elements = []
                    rows = []
                    active_structured = {"headerTitle": "", "bubbles": [], "lastBubble": None}
                    active_header = ""
                else:
                    state["daemon"]["lastPollAt"] = _utc_iso_now()
                    state["daemon"]["lastError"] = str(cap.get("error") or cap.get("error_code"))
                    self._save_state(state)
                    self._append_event("poll_error", cap)
                    return cap
            else:
                bounds = cap["bounds"]
                win_w = float(bounds.get("width", 585.0) or 585.0)
                win_h = float(bounds.get("height", 640.0) or 640.0)
                elements = cap["ocrPayload"].get("elements") or []
                if self.engine.inspector._is_popout_window(cap["ocrPayload"], elements):
                    split_x = 0.0
                elif cap["ocrPayload"].get("splitX") is not None:
                    split_x = float(cap["ocrPayload"]["splitX"])
                else:
                    split_x = self.engine.inspector._infer_split_x(elements, win_w)

                rows = (
                    []
                    if split_x <= 0.0
                    else self.engine.inspector._cluster_session_rows(
                        elements, split_x, win_h, image_path=cap["snapshotPath"],
                    )
                )
                active_structured = self.engine.inspector.extract_structured_bubbles(
                    cap["ocrPayload"],
                    snapshot_path=cap["snapshotPath"],
                    bounds=bounds,
                )
                active_header = str(active_structured.get("headerTitle") or "")

        actions: List[Dict[str, Any]] = []
        replies_this_cycle = 0
        ready_jobs: List[Dict[str, Any]] = []

        for binding in targets:
            target = str(binding["target"])
            is_sandbox_bot = _is_ai_bot_sandbox_target(target)
            if not ignore_human_guard and hasattr(self.engine, "human_guard") and not is_sandbox_bot:
                mid_guard = self.engine.human_guard.check_can_operate()
                if not mid_guard.get("canOperate", True):
                    if not has_sandbox_bot:
                        state["daemon"]["pausedByHumanGuard"] = True
                        state["daemon"]["humanGuard"] = mid_guard
                        self._append_event(
                            "human_active_paused",
                            {
                                "status": mid_guard.get("status"),
                                "remainingCooldownSeconds": mid_guard.get("remainingCooldownSeconds", 0.0),
                                "anyInputIdleSeconds": mid_guard.get("anyInputIdleSeconds"),
                                "triggerReason": mid_guard.get("triggerReason", ""),
                            },
                        )
                        break
                    actions.append({"target": target, "status": "paused_by_human_guard"})
                    continue
            care_level = normalize_care_level(binding.get("careLevel"), binding.get("specialCare"))
            is_special_care = care_level in ("special_care", "vip") or bool(binding.get("specialCare"))
            c_state = self._contact_entry(state, target)
            if is_sandbox_bot and c_state.get("takenOver"):
                c_state["takenOver"] = False
                c_state["takeoverReason"] = ""
                c_state["takeoverAt"] = None
            matched_row = next((r for r in rows if _matches_target(target, r.get("titleSnippet", ""))), None)

            inspected = self._inspect_target_bubbles(
                target,
                active_header=active_header,
                active_structured=active_structured,
                in_row=matched_row,
                contact_state=c_state,
                force_open=bool(target_filter),
                popout_windows=popout_windows,
                prefetched_popout=prefetched_popouts.get(target),
            )
            popout_meta: Dict[str, Any] = (
                {"popoutWindowID": int(inspected["popoutWindowID"]), "zeroSwitch": True}
                if inspected.get("popoutWindow") and inspected.get("popoutWindowID")
                else {}
            )
            if not inspected.get("checked"):
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": inspected.get("skipReason", "skipped"),
                    "error": inspected.get("error"),
                    **popout_meta,
                })
                continue

            new_row_preview = str(matched_row["previewSnippet"]) if (matched_row and matched_row.get("previewSnippet")) else ""

            structured = inspected["structured"]
            bubbles: List[Dict[str, Any]] = list(structured.get("bubbles") or [])
            if not bubbles:
                actions.append({"target": target, "status": "no_visible_bubbles", **popout_meta})
                continue

            last_bubble = bubbles[-1]
            # Only update main-pane active cache when navigation actually switched the main window
            if not inspected.get("popoutWindow"):
                active_header = str(inspected.get("matchedTitle") or active_header)
                active_structured = structured

            if last_bubble.get("direction") != "peer":
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
                actions.append({
                    "target": target,
                    "status": "skipped_last_is_self",
                    "lastBubbleText": last_bubble.get("text", ""),
                    **popout_meta,
                })
                continue

            recent_out = list(c_state.get("recentOutboundTexts") or [])
            if c_state.get("lastOutboundText"):
                recent_out.append(str(c_state["lastOutboundText"]))

            delta = UnreadDeltaTracker.extract_unread_delta(
                bubbles,
                last_processed_text=str(c_state.get("lastProcessedPeerText") or ""),
                last_outbound_text=str(c_state.get("lastOutboundText") or ""),
                recent_outbound=recent_out,
            )
            preceding_self = ""
            for b in reversed(bubbles[:-1]):
                if b.get("direction") == "self":
                    preceding_self = str(b.get("text") or "")
                    break

            raw_last_text = str(last_bubble.get("text") or "").strip()
            coalesced_text = str(delta.get("coalescedText") or "").strip()
            incoming_text = coalesced_text if len(delta.get("unreadPeerBubbles") or []) >= 2 and coalesced_text else raw_last_text
            msg_sig = _bubble_signature(target, last_bubble, preceding_self)

            if msg_sig == c_state.get("lastProcessedPeerSig"):
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
                actions.append({
                    "target": target,
                    "status": "skipped_already_replied",
                    "signature": msg_sig,
                    "incomingText": incoming_text,
                    **popout_meta,
                })
                continue

            # 转人工意图：客户明确要真人时，自动切换到「人工接管」状态（机器人停答）
            if (not is_sandbox_bot) and _is_human_handoff_request(incoming_text):
                c_state["takenOver"] = True
                c_state["takeoverReason"] = "customer_requested_human"
                c_state["takeoverAt"] = _utc_iso_now()
                handoff_line = "好的，已为您转接人工客服，请稍候；人工不在时您可以留言，看到会第一时间回复您。"
                self._append_event("takeover", {"target": target, "reason": c_state["takeoverReason"], **popout_meta})
                self._append_event(
                    "handoff_requested",
                    {"target": target, "incomingText": incoming_text, "replyText": handoff_line,
                     "careLevel": care_level, "specialCare": is_special_care, **popout_meta},
                )
                takeover_res = {"ok": True, "contactState": dict(c_state)}
                try:
                    if hasattr(self.engine, "human_guard"):
                        self.engine.human_guard.record_rpa_action(action="paste-and-verify")
                    send_res = self.engine.send_text(
                        target, handoff_line,
                        dry_run=not auto_reply or not confirm_send,
                        silent_mode=not (auto_reply and confirm_send),
                        confirm_send=bool(auto_reply and confirm_send),
                        skip_navigation=True,
                        target_window_id=popout_meta.get("popoutWindowID"),
                    )
                except Exception:
                    send_res = {"ok": False}
                c_state["lastProcessedPeerSig"] = msg_sig
                c_state["pendingDraft"] = None
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
                actions.append({
                    "target": target,
                    "status": "handoff_taken_over",
                    "incomingText": incoming_text,
                    "send": send_res,
                    "takeover": takeover_res,
                    **popout_meta,
                })
                continue

            if any(normalize_chat_name(incoming_text) == normalize_chat_name(o) for o in recent_out if o):
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
                actions.append({
                    "target": target,
                    "status": "skipped_matches_outbound",
                    "incomingText": incoming_text,
                    **popout_meta,
                })
                continue

            recent_peer_msgs = [str(b.get("text", "")) for b in bubbles[-8:] if b.get("text")]
            sender_name = str(last_bubble.get("sender") or "").strip()
            query_incoming = incoming_text
            if sender_name and incoming_text.startswith(f"{sender_name}: "):
                query_incoming = incoming_text[len(sender_name) + 2 :].strip() or incoming_text

            # 微信原生 AI 助手（元宝 / 腾讯元宝 / 小微）气泡自动收割并防机器人互回死循环
            harvested_ai_notes = extract_assistant_insights_from_bubbles(bubbles[-8:])
            for ai_note in harvested_ai_notes:
                try:
                    self.engine.append_media_note(target, ai_note)
                except Exception:
                    pass
            inline_speaker = (
                re.split(r"[:：]", incoming_text, maxsplit=1)[0].strip()
                if (":" in incoming_text or "：" in incoming_text)
                else ""
            )
            if is_wechat_ai_assistant_name(sender_name) or is_wechat_ai_assistant_name(inline_speaker):
                c_state["lastProcessedPeerSig"] = msg_sig
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
                self._append_event(
                    "ai_assistant_insight_harvested",
                    {
                        "target": target,
                        "sender": sender_name or inline_speaker,
                        "incomingText": incoming_text[:240],
                        "harvestedNotes": harvested_ai_notes,
                        **popout_meta,
                    },
                )
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": "skipped_ai_assistant_bubble",
                    "incomingText": incoming_text,
                    "harvestedNotes": harvested_ai_notes,
                    **popout_meta,
                })
                continue

            if is_explicit_wechat_ai_mention(query_incoming):
                c_state["lastProcessedPeerSig"] = msg_sig
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
                self._append_event(
                    "deferred_for_wechat_ai_assistant",
                    {"target": target, "incomingText": incoming_text[:240], **popout_meta},
                )
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": "deferred_for_wechat_ai_assistant",
                    "incomingText": incoming_text,
                    **popout_meta,
                })
                continue

            ready_jobs.append({
                "binding": binding,
                "target": target,
                "is_sandbox_bot": is_sandbox_bot,
                "care_level": care_level,
                "is_special_care": is_special_care,
                "c_state": c_state,
                "inspected": inspected,
                "popout_meta": popout_meta,
                "new_row_preview": new_row_preview,
                "bubbles": bubbles,
                "last_bubble": last_bubble,
                "incoming_text": incoming_text,
                "query_incoming": query_incoming,
                "msg_sig": msg_sig,
                "recent_out": recent_out,
                "recent_peer_msgs": recent_peer_msgs,
                "sender_name": sender_name,
                "active_cards": list(delta.get("activeMediaCards") or []),
            })

        def _think_job(job: Dict[str, Any]) -> Dict[str, Any]:
            t_name = job["target"]
            extra_notes, dispatched_receipt = self._agent_dispatch_notes(
                job["binding"],
                t_name,
                job["bubbles"],
                job["query_incoming"],
                job["inspected"],
                active_cards=job["active_cards"],
            )
            recent_msgs = list(job["recent_peer_msgs"])
            if extra_notes:
                recent_msgs = recent_msgs + extra_notes
            mem_ctx = self._memory_context_with_history(t_name)
            if job["sender_name"]:
                mem_ctx = dict(mem_ctx or {})
                mem_ctx["groupSpeaker"] = job["sender_name"]
            smart = self.engine.personas.generate_smart_reply(
                t_name,
                job["query_incoming"],
                knowledge_store=self.engine.knowledge,
                binding=job["binding"],
                recent_messages=recent_msgs,
                memory_context=mem_ctx,
            )
            return {
                "job": job,
                "smart": smart,
                "dispatched_receipt": dispatched_receipt,
            }

        thought_results: List[Dict[str, Any]] = []
        if len(ready_jobs) >= 2:
            with ThreadPoolExecutor(max_workers=min(4, len(ready_jobs))) as think_pool:
                thought_results = list(think_pool.map(_think_job, ready_jobs))
        elif ready_jobs:
            thought_results = [_think_job(ready_jobs[0])]

        for item in thought_results:
            job = item["job"]
            smart = item["smart"]
            dispatched_receipt = item["dispatched_receipt"]
            target = job["target"]
            is_sandbox_bot = job["is_sandbox_bot"]
            care_level = job["care_level"]
            is_special_care = job["is_special_care"]
            c_state = job["c_state"]
            popout_meta = job["popout_meta"]
            new_row_preview = job["new_row_preview"]
            last_bubble = job["last_bubble"]
            incoming_text = job["incoming_text"]
            query_incoming = job["query_incoming"]
            msg_sig = job["msg_sig"]
            recent_out = job["recent_out"]
            reply_text = str(smart.get("replyText") or "").strip()

            draft_record = {
                "signature": msg_sig,
                "incomingText": incoming_text,
                "timeMarker": last_bubble.get("timeMarker", ""),
                "replyText": reply_text,
                "personaId": smart["persona"]["id"],
                "basis": smart["basis"],
                "dispatchedAgentTask": dispatched_receipt,
                "draftedAt": _utc_iso_now(),
                **popout_meta,
            }

            if c_state.get("takenOver"):
                c_state["pendingDraft"] = draft_record
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                self._append_event(
                    "takeover_draft_only",
                    {"target": target, "careLevel": care_level, "specialCare": is_special_care, "draft": draft_record, **popout_meta},
                )
                try:
                    self.engine.push_pending_draft_to_workbench(
                        target,
                        msgid=str(last_bubble.get("msgid") or msg_sig),
                        incoming=incoming_text,
                        draft=reply_text,
                    )
                except Exception:
                    pass
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": "skipped_taken_over",
                    "pendingDraft": draft_record,
                    **popout_meta,
                })
                continue

            if not auto_reply or not confirm_send:
                c_state["lastPreviewedPeerSig"] = msg_sig
                c_state["pendingDraft"] = draft_record
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                send_res = self.engine.send_text(
                    target,
                    reply_text,
                    dry_run=True,
                    silent_mode=True,
                    confirm_send=False,
                    skip_navigation=True,
                )
                self._append_event(
                    "preview_reply",
                    {
                        "target": target,
                        "careLevel": care_level,
                        "specialCare": is_special_care,
                        "incomingText": incoming_text,
                        "replyText": reply_text,
                        "personaId": smart["persona"]["id"],
                        "send": send_res,
                        **popout_meta,
                    },
                )
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": "preview_ready",
                    "incomingText": incoming_text,
                    "replyText": reply_text,
                    "persona": smart["persona"],
                    "basis": smart["basis"],
                    "send": send_res,
                    **popout_meta,
                })
                continue

            is_correction_followup = bool(
                job["active_cards"]
                and any(k in query_incoming for k in ("看不到", "没读到", "最新的", "微信文章", "视频号"))
            )
            if is_sandbox_bot:
                can_send, limit_reason = True, "sandbox_bot_exempt"
            elif is_correction_followup and not c_state.get("correctionBypassUsed"):
                can_send, limit_reason = self.engine.antiban.check_can_send(target)
                if not can_send and str(limit_reason).startswith("contact_gap"):
                    can_send, limit_reason = True, "media_followup_gap_bypass"
                    c_state["correctionBypassUsed"] = True
            else:
                can_send, limit_reason = self.engine.antiban.check_can_send(target)

            if not can_send:
                c_state["lastRateLimitReason"] = limit_reason
                if str(limit_reason).startswith("contact_gap"):
                    c_state["pendingGapRetry"] = True
                else:
                    c_state["lastProcessedPeerSig"] = msg_sig
                    if new_row_preview:
                        c_state["lastSeenPreview"] = new_row_preview
                    c_state.pop("pendingGapRetry", None)
                self._append_event(
                    "auto_reply_rate_limited",
                    {"target": target, "reason": limit_reason, **popout_meta},
                )
                actions.append({
                    "target": target,
                    "status": "rate_limited",
                    "reason": limit_reason,
                    "incomingText": incoming_text,
                    **popout_meta,
                })
                continue

            if hasattr(self.engine, "human_guard"):
                self.engine.human_guard.record_rpa_action(action="paste-and-verify")
            send_res = self.engine.send_text(
                target,
                reply_text,
                dry_run=False,
                silent_mode=False,
                confirm_send=True,
                skip_navigation=True,
                target_window_id=popout_meta.get("popoutWindowID"),
            )
            if send_res.get("ok") and send_res.get("status") == "sent":
                if hasattr(self.engine, "human_guard"):
                    self.engine.human_guard.record_rpa_action(action="paste-and-verify")
                if not is_sandbox_bot:
                    self.engine.antiban.record_sent(target)
                c_state["lastProcessedPeerSig"] = msg_sig
                c_state["lastProcessedPeerText"] = raw_last_text
                c_state["lastOutboundText"] = reply_text
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
                c_state.pop("correctionBypassUsed", None)
                updated_recent = [t for t in recent_out if t and t != reply_text]
                updated_recent.append(reply_text)
                c_state["recentOutboundTexts"] = updated_recent[-10:]
                c_state["pendingDraft"] = None
                c_state["lastRepliedAt"] = _utc_iso_now()
                c_state["lastPostSendSnapshot"] = send_res.get("postSendSnapshot")
                replies_this_cycle += 1
                self._append_event(
                    "auto_reply_sent",
                    {
                        "target": target,
                        "careLevel": care_level,
                        "specialCare": is_special_care,
                        "incomingText": incoming_text,
                        "replyText": reply_text,
                        "personaId": smart["persona"]["id"],
                        "postSendSnapshot": send_res.get("postSendSnapshot"),
                        **popout_meta,
                    },
                )
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": "replied",
                    "incomingText": incoming_text,
                    "replyText": reply_text,
                    "persona": smart["persona"],
                    "basis": smart["basis"],
                    "send": send_res,
                    **popout_meta,
                })
            else:
                c_state["pendingDraft"] = draft_record
                self._append_event(
                    "auto_reply_failed",
                    {
                        "target": target,
                        "careLevel": care_level,
                        "specialCare": is_special_care,
                        "incomingText": incoming_text,
                        "replyText": reply_text,
                        "send": send_res,
                        **popout_meta,
                    },
                )
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": send_res.get("status", "send_failed"),
                    "incomingText": incoming_text,
                    "replyText": reply_text,
                    "send": send_res,
                    **popout_meta,
                })

        daemon = state["daemon"]
        daemon["cyclesCompleted"] = int(daemon.get("cyclesCompleted") or 0) + 1
        daemon["repliesDispatched"] = int(daemon.get("repliesDispatched") or 0) + replies_this_cycle
        daemon["lastPollAt"] = _utc_iso_now()
        daemon["lastHeartbeatAt"] = daemon["lastPollAt"]
        daemon["lastError"] = ""
        self._save_state(state)

        popout_ids_used = [int(a["popoutWindowID"]) for a in actions if a.get("popoutWindowID")]
        poll_resp: Dict[str, Any] = {
            "ok": True,
            "confirmSend": bool(confirm_send),
            "autoReply": bool(auto_reply),
            "activeHeader": active_header,
            "boundTargetsScanned": len(targets),
            "repliesDispatched": replies_this_cycle,
            "actions": actions,
            "stateFile": str(self.state_path),
        }
        if popout_ids_used:
            poll_resp["zeroSwitch"] = True
            poll_resp["popoutWindowIDs"] = popout_ids_used
            if len(popout_ids_used) == 1:
                poll_resp["popoutWindowID"] = popout_ids_used[0]
        return poll_resp

    def run_loop(
        self,
        *,
        interval_seconds: float = 2.5,
        max_cycles: Optional[int] = None,
        target_filter: Optional[str] = None,
        auto_reply: bool = True,
        confirm_send: bool = False,
    ) -> Dict[str, Any]:
        """Run continuous background monitoring until stopped or `max_cycles` is reached."""
        interval = max(0.2, float(interval_seconds))
        stop_requested = False

        def _handle_sig(_signum: int, _frame: Any) -> None:
            nonlocal stop_requested
            stop_requested = True

        prev_int = signal.getsignal(signal.SIGINT)
        prev_term = signal.getsignal(signal.SIGTERM)
        try:
            signal.signal(signal.SIGINT, _handle_sig)
            signal.signal(signal.SIGTERM, _handle_sig)
        except ValueError:
            pass

        state = self._load_state()
        daemon = state["daemon"]
        daemon["running"] = True
        daemon["pid"] = os.getpid()
        daemon["startedAt"] = _utc_iso_now()
        daemon["lastHeartbeatAt"] = daemon["startedAt"]
        daemon["lastError"] = ""
        self._save_state(state)
        self._append_event(
            "daemon_started",
            {"pid": os.getpid(), "intervalSeconds": interval, "confirmSend": bool(confirm_send)},
        )

        cycles_run = 0
        last_result: Optional[Dict[str, Any]] = None
        try:
            while not stop_requested:
                try:
                    last_result = self.poll_once(
                        target_filter=target_filter,
                        auto_reply=auto_reply,
                        confirm_send=confirm_send,
                    )
                except Exception as exc:
                    err_state = self._load_state()
                    err_state["daemon"]["lastHeartbeatAt"] = _utc_iso_now()
                    err_state["daemon"]["lastError"] = str(exc)
                    self._save_state(err_state)
                    self._append_event("daemon_cycle_exception", {"error": str(exc)})
                cycles_run += 1
                if max_cycles is not None and cycles_run >= max_cycles:
                    break
                # Sleep in small slices so SIGTERM wakes quickly
                deadline = time.monotonic() + interval
                while not stop_requested and time.monotonic() < deadline:
                    time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        finally:
            fin_state = self._load_state()
            fin_state["daemon"]["running"] = False
            fin_state["daemon"]["pid"] = None
            fin_state["daemon"]["lastHeartbeatAt"] = _utc_iso_now()
            self._save_state(fin_state)
            self._append_event("daemon_stopped", {"cyclesRun": cycles_run})
            try:
                signal.signal(signal.SIGINT, prev_int)
                signal.signal(signal.SIGTERM, prev_term)
            except Exception:
                pass

        return {
            "ok": True,
            "cyclesRun": cycles_run,
            "lastCycle": last_result,
            "stateFile": str(self.state_path),
        }
