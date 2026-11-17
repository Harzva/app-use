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
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .contact_profiler import CARE_LEVEL_ORDER, normalize_care_level
from .live_inspector import _matches_target, _slugify_target
from .safety import normalize_chat_name

if TYPE_CHECKING:
    from .engine import WeChatControlEngine

_TODAY_HHMM_RE = re.compile(r"(?:^|\|\s*)\d{1,2}:\d{2}(?:\s*\||$)")
_PREFIX_TS_RE = re.compile(
    r"^(?:昨天|今天|前天|星期[一二三四五六日天]|周[一二三四五六日天]|\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2})\s*\|?\s*"
)


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
    ) -> Dict[str, Any]:
        """Inspect a single contact's chat pane, minimizing unnecessary UI clicks."""
        if _matches_target(target, active_header):
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
        return {
            "checked": True,
            "source": trigger_reason or "selected_session",
            "matchedTitle": structured.get("headerTitle") or nav.get("matchedTitle") or target,
            "structured": structured,
            "snapshotPath": str(snap_path),
            "rowPreview": row_preview,
        }

    def _agent_dispatch_notes(
        self,
        binding: Dict[str, Any],
        target: str,
        bubbles: List[Dict[str, Any]],
        incoming_text: str,
        inspected: Dict[str, Any],
    ) -> Tuple[List[str], Optional[Dict[str, Any]]]:
        """Agent 分发与链接/图片/视频深读：产出注入回复上下文的识别备注（并持久化 media_note）。

        返回 (extra_notes, dispatched_receipt)；深读失败静默降级，不影响回复主流程。
        """
        extra_notes: List[str] = []
        dispatched_receipt: Optional[Dict[str, Any]] = None
        if not (hasattr(self.engine, "agent_dispatcher") and (
            binding.get("boundAgentId") or binding.get("autoAnalyzeLinksAndMedia", True)
        )):
            return extra_notes, dispatched_receipt
        try:
            parsed_tasks = self.engine.agent_dispatcher.parse_messages_for_instructions(
                target,
                bubbles[-6:],
                snapshot_path=Path(inspected["snapshotPath"]) if inspected.get("snapshotPath") else None,
            )
            interesting = [
                t
                for t in parsed_tasks
                if t.get("kind") in ("link_deep_read", "agent_instruction", "video_analysis", "image_card_analysis")
            ]
            if interesting and (
                any(t.get("kind") == "link_deep_read" for t in interesting)
                or binding.get("autoDispatchInstructions", True)
            ):
                vision_model = str(binding.get("visionModelId") or "auto/deepseek-v4.1-flash")
                for it in interesting[:2]:
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
                        # 图片/图文卡片深读：对巡检快照做 2x Vision OCR + 视觉模型识别，
                        # 让机器人"看懂"客户发来的图片而不仅看到 [图片] 占位符。
                        # analyze_image_or_card 要求 crop_region（source_snapshot 只作底图），全图裁剪=整窗识别
                        snap_path = Path(inspected["snapshotPath"]) if inspected.get("snapshotPath") else None
                        crop_region = self._png_size(snap_path) if snap_path else None
                        if crop_region:
                            ires = self.engine.media_analyzer.analyze_image_or_card(
                                source_snapshot=snap_path,
                                crop_region=crop_region,
                                from_viewer_window=False,
                                contact=target,
                                context_text=it.get("rawText") or incoming_text,
                                model_id=vision_model,
                            )
                            if ires.get("summary"):
                                extra_notes.append(f"[图片识别:{ires.get('title','') or '图片'}] {ires.get('summary')}")
                    elif it.get("kind") == "video_analysis" and hasattr(self.engine, "media_analyzer"):
                        # 视频消息：若客户点开过（微信媒体查看窗存在）则抓帧 OCR；
                        # 查看窗不在时 analyze_video 自行降级，摘要失败不影响回复主流程
                        vres = self.engine.media_analyzer.analyze_video(
                            from_viewer_window=True,
                            window_title="图片和视频",
                            contact=target,
                            context_text=it.get("rawText") or incoming_text,
                            model_id=vision_model,
                        )
                        if vres.get("summary"):
                            extra_notes.append(f"[视频识别:{vres.get('title','') or '视频'}] {vres.get('summary')}")
                    else:
                        extra_notes.append(f"[识别指令:{it.get('category')}] {it.get('rawText','')}")
                if extra_notes:
                    # 深读结果持久化：客户下次再提同一链接/图片时机器人仍记得内容
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
            dispatched_receipt = None
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
        if not ignore_human_guard and hasattr(self.engine, "human_guard"):
            guard_state = self.engine.human_guard.check_can_operate()
            if not guard_state.get("canOperate", True):
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
            if state["daemon"].get("pausedByHumanGuard"):
                state["daemon"]["pausedByHumanGuard"] = False
                state["daemon"]["humanGuard"] = guard_state
                self._append_event(
                    "human_idle_resumed",
                    {
                        "anyInputIdleSeconds": guard_state.get("anyInputIdleSeconds"),
                        "idleResumeSeconds": guard_state.get("idleResumeSeconds"),
                    },
                )
        cap = self._capture_live_window()
        if not cap.get("ok"):
            state["daemon"]["lastPollAt"] = _utc_iso_now()
            state["daemon"]["lastError"] = str(cap.get("error") or cap.get("error_code"))
            self._save_state(state)
            self._append_event("poll_error", cap)
            return cap

        bounds = cap["bounds"]
        win_w = float(bounds["width"])
        win_h = float(bounds["height"])
        elements = cap["ocrPayload"].get("elements") or []
        split_x = float(cap["ocrPayload"].get("splitX") or self.engine.inspector._infer_split_x(elements, win_w))

        rows = self.engine.inspector._cluster_session_rows(
            elements, split_x, win_h, image_path=cap["snapshotPath"],
        )
        active_structured = self.engine.inspector.extract_structured_bubbles(
            cap["ocrPayload"],
            snapshot_path=cap["snapshotPath"],
            bounds=bounds,
        )
        active_header = str(active_structured.get("headerTitle") or "")

        all_bindings = self.engine.bindings.list_bindings()
        # 托管范围过滤：首页「一键托管」勾选的好友列表（hosting targets）是唯一的自动回复范围——
        # 「只关注这些好友」。未勾选的好友即使 autoReplyEnabled=True 也不扫不回。
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

        # Priority scanning: Special Care (P0) -> VIP (P1) -> Normal (P2)
        targets.sort(
            key=lambda b: (
                CARE_LEVEL_ORDER.get(normalize_care_level(b.get("careLevel"), b.get("specialCare")), 2),
                str(b.get("target") or ""),
            )
        )

        actions: List[Dict[str, Any]] = []
        replies_this_cycle = 0

        for binding in targets:
            if not ignore_human_guard and hasattr(self.engine, "human_guard"):
                mid_guard = self.engine.human_guard.check_can_operate()
                if not mid_guard.get("canOperate", True):
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
            target = str(binding["target"])
            care_level = normalize_care_level(binding.get("careLevel"), binding.get("specialCare"))
            is_special_care = care_level in ("special_care", "vip") or bool(binding.get("specialCare"))
            c_state = self._contact_entry(state, target)
            matched_row = next((r for r in rows if _matches_target(target, r.get("titleSnippet", ""))), None)
            if matched_row and not c_state.get("lastSeenPreview"):
                # Keep preview handy after inspection completes
                pass

            inspected = self._inspect_target_bubbles(
                target,
                active_header=active_header,
                active_structured=active_structured,
                in_row=matched_row,
                contact_state=c_state,
                force_open=bool(target_filter),
            )
            if not inspected.get("checked"):
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": inspected.get("skipReason", "skipped"),
                    "error": inspected.get("error"),
                })
                continue

            new_row_preview = str(matched_row["previewSnippet"]) if (matched_row and matched_row.get("previewSnippet")) else ""

            structured = inspected["structured"]
            bubbles: List[Dict[str, Any]] = list(structured.get("bubbles") or [])
            if not bubbles:
                actions.append({"target": target, "status": "no_visible_bubbles"})
                continue

            last_bubble = bubbles[-1]
            # Update active cache when navigation switched screens so next loop iteration has fresh active_header
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
                })
                continue

            preceding_self = ""
            for b in reversed(bubbles[:-1]):
                if b.get("direction") == "self":
                    preceding_self = str(b.get("text") or "")
                    break

            incoming_text = str(last_bubble.get("text") or "").strip()
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
                })
                continue

            recent_out = list(c_state.get("recentOutboundTexts") or [])

            # 转人工意图：客户明确要真人时，自动切换到「人工接管」状态（机器人停答，
            # 后续消息只出草稿供人工审阅；人工处理完在控制台恢复）。此前转人工会被
            # persona 引擎当普通消息循环回复——客服正确性缺口。
            if _is_human_handoff_request(incoming_text):
                # 直接在主流程 state 上置接管（勿调 takeover_contact——其独立 load/save
                # 会被本循环尾部的 _save_state(state) 用旧副本覆盖回去，竞态丢状态）
                c_state["takenOver"] = True
                c_state["takeoverReason"] = "customer_requested_human"
                c_state["takeoverAt"] = _utc_iso_now()
                handoff_line = "好的，已为您转接人工客服，请稍候；人工不在时您可以留言，看到会第一时间回复您。"
                self._append_event("takeover", {"target": target, "reason": c_state["takeoverReason"]})
                self._append_event(
                    "handoff_requested",
                    {"target": target, "incomingText": incoming_text, "replyText": handoff_line,
                     "careLevel": care_level, "specialCare": is_special_care},
                )
                takeover_res = {"ok": True, "contactState": dict(c_state)}
                try:
                    send_res = self.engine.send_text(
                        target, handoff_line,
                        dry_run=not auto_reply or not confirm_send,
                        silent_mode=not (auto_reply and confirm_send),
                        confirm_send=bool(auto_reply and confirm_send),
                        skip_navigation=True,
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
                })
                continue
            if c_state.get("lastOutboundText"):
                recent_out.append(str(c_state["lastOutboundText"]))
            if any(normalize_chat_name(incoming_text) == normalize_chat_name(o) for o in recent_out if o):
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
                actions.append({
                    "target": target,
                    "status": "skipped_matches_outbound",
                    "incomingText": incoming_text,
                })
                continue

            recent_peer_msgs = [str(b.get("text", "")) for b in bubbles[-6:] if b.get("text")]
            sender_name = str(last_bubble.get("sender") or "").strip()
            query_incoming = incoming_text
            if sender_name and incoming_text.startswith(f"{sender_name}: "):
                query_incoming = incoming_text[len(sender_name) + 2 :].strip() or incoming_text
            extra_notes, dispatched_receipt = self._agent_dispatch_notes(
                binding, target, bubbles, query_incoming, inspected,
            )
            if extra_notes:
                recent_peer_msgs = recent_peer_msgs + extra_notes
            mem_ctx = self._memory_context_with_history(target)
            if sender_name:
                mem_ctx = dict(mem_ctx or {})
                mem_ctx["groupSpeaker"] = sender_name
            smart = self.engine.personas.generate_smart_reply(
                target,
                query_incoming,
                knowledge_store=self.engine.knowledge,
                binding=binding,
                recent_messages=recent_peer_msgs,
                memory_context=mem_ctx,
            )
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
            }

            if c_state.get("takenOver"):
                c_state["pendingDraft"] = draft_record
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                self._append_event(
                    "takeover_draft_only",
                    {"target": target, "careLevel": care_level, "specialCare": is_special_care, "draft": draft_record},
                )
                # 同步进待办审阅台：人工接管期间客户发的新消息，人工要真的看得到、能一键发送
                try:
                    self.engine.push_pending_draft_to_workbench(
                        target,
                        msgid=str(last_bubble.get("msgid") or msg_sig),
                        incoming=incoming_text,
                        draft=reply_text,
                    )
                except Exception:
                    pass  # 待办同步失败不影响接管主流程
                actions.append({
                    "target": target,
                    "careLevel": care_level,
                    "specialCare": is_special_care,
                    "status": "skipped_taken_over",
                    "pendingDraft": draft_record,
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
                })
                continue

            # AntiBan 频控闸门：真发送前四道检查（联系人/小时、回复间隔、全局小时/日）。
            # contact_gap 属于短暂冷却（默认 90s）：只延后重检、不吞消息签名；
            # 小时/日硬配额超限时记录签名避免重复扫描——宁可不回，不可轰炸。
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
                    {"target": target, "reason": limit_reason},
                )
                actions.append({
                    "target": target,
                    "status": "rate_limited",
                    "reason": limit_reason,
                    "incomingText": incoming_text,
                })
                continue

            send_res = self.engine.send_text(
                target,
                reply_text,
                dry_run=False,
                silent_mode=False,
                confirm_send=True,
                skip_navigation=True,
            )
            if send_res.get("ok") and send_res.get("status") == "sent":
                self.engine.antiban.record_sent(target)
                c_state["lastProcessedPeerSig"] = msg_sig
                c_state["lastProcessedPeerText"] = incoming_text
                c_state["lastOutboundText"] = reply_text
                if new_row_preview:
                    c_state["lastSeenPreview"] = new_row_preview
                c_state.pop("pendingGapRetry", None)
                c_state.pop("lastRateLimitReason", None)
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
                })

        daemon = state["daemon"]
        daemon["cyclesCompleted"] = int(daemon.get("cyclesCompleted") or 0) + 1
        daemon["repliesDispatched"] = int(daemon.get("repliesDispatched") or 0) + replies_this_cycle
        daemon["lastPollAt"] = _utc_iso_now()
        daemon["lastHeartbeatAt"] = daemon["lastPollAt"]
        daemon["lastError"] = ""
        self._save_state(state)

        return {
            "ok": True,
            "confirmSend": bool(confirm_send),
            "autoReply": bool(auto_reply),
            "activeHeader": active_header,
            "boundTargetsScanned": len(targets),
            "repliesDispatched": replies_this_cycle,
            "actions": actions,
            "stateFile": str(self.state_path),
        }

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
