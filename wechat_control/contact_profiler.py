"""Bound contact policies, conversation history style profiling, and frequency/time analytics."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .live_inspector import _matches_target, _slugify_target
from .safety import normalize_chat_name

TIME_SLOTS = (
    "清晨 05:00-08:59",
    "上午 09:00-11:59",
    "下午 12:00-17:59",
    "晚间 18:00-21:59",
    "深夜 22:00-04:59",
)

_HM_RE = re.compile(r"(\d{1,2})\s*[:：]\s*(\d{2})")
_DATE_TOKEN_RE = re.compile(
    r"(昨天|今天|前天|星期[一二三四五六日天]|周[一二三四五六日天]|\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2})"
)

FOLDER_CHAT_TITLES = {"公众号", "服务号", "安心的...", "安心的 ai 工..."}

CARE_LEVELS = ("special_care", "vip", "normal")
CARE_LEVEL_LABELS = {
    "special_care": "特别关心",
    "vip": "重点关照",
    "normal": "普通会话",
}
CARE_MONITOR_PRIORITY = {
    "special_care": "P0-最高优",
    "vip": "P1-高优",
    "normal": "P2-常规",
}
CARE_LEVEL_ORDER = {
    "special_care": 0,
    "vip": 1,
    "normal": 2,
}
CARE_DEFAULT_FOLLOWUP_DAYS = {
    "special_care": 3,
    "vip": 7,
    "normal": 14,
}
TIME_WINDOW_MAP = {
    TIME_SLOTS[0]: "07:30-08:50 (清晨早安窗)",
    TIME_SLOTS[1]: "09:30-11:30 (上午工作窗)",
    TIME_SLOTS[2]: "14:00-17:30 (下午协作窗)",
    TIME_SLOTS[3]: "19:00-21:45 (晚间黄金窗)",
    TIME_SLOTS[4]: "22:00-23:15 (睡前低扰窗 · 谨慎打扰)",
}


def normalize_care_level(care_level: Optional[str] = None, special_care: Optional[bool] = None) -> str:
    """Normalize care level alias into one of special_care / vip / normal."""
    raw = unicodedata.normalize("NFKC", str(care_level or "")).strip().lower()
    if raw in ("special_care", "special-care", "special", "sc", "特别关心", "特关", "p0"):
        return "special_care"
    if raw in ("vip", "重点关照", "important", "star", "星标", "p1"):
        return "vip"
    if raw in ("normal", "default", "普通", "p2", ""):
        if special_care is True:
            return "special_care"
        return "normal"
    return "special_care" if special_care is True else "normal"


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_time_slot(text: str) -> Optional[str]:
    """Map an OCR timestamp string (containing HH:MM) to a Chinese time-of-day bucket."""
    norm = unicodedata.normalize("NFKC", text or "").strip()
    m = _HM_RE.search(norm)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if 5 <= hour <= 8:
        return TIME_SLOTS[0]
    if 9 <= hour <= 11:
        return TIME_SLOTS[1]
    if 12 <= hour <= 17:
        return TIME_SLOTS[2]
    if 18 <= hour <= 21:
        return TIME_SLOTS[3]
    return TIME_SLOTS[4]


def extract_time_markers(texts: Iterable[str]) -> Tuple[List[str], Dict[str, int]]:
    """Extract normalized date/time strings and count active time-of-day buckets."""
    markers: List[str] = []
    seen_markers: set[str] = set()
    slot_counts: Counter[str] = Counter()

    for raw in texts:
        norm = unicodedata.normalize("NFKC", raw or "").strip().strip("|｜ ")
        if not norm:
            continue
        slot = classify_time_slot(norm)
        if slot is not None:
            slot_counts[slot] += 1

        has_date = bool(_DATE_TOKEN_RE.search(norm))
        has_time = bool(_HM_RE.search(norm))
        if has_date or has_time:
            cleaned = re.sub(r"\s+", " ", norm)
            if len(cleaned) <= 36 and cleaned not in seen_markers:
                seen_markers.add(cleaned)
                markers.append(cleaned)
            elif len(cleaned) > 36:
                for dm in _DATE_TOKEN_RE.findall(cleaned):
                    if dm not in seen_markers:
                        seen_markers.add(dm)
                        markers.append(dm)

    ordered_slots = {slot: int(slot_counts.get(slot, 0)) for slot in TIME_SLOTS if slot_counts.get(slot, 0) > 0}
    return markers, ordered_slots


class ContactBindingStore:
    """Persists bound WeChat contacts/groups and their scheduled/AI interaction policies."""

    SCHEMA = "openbot.wechat-contact-bindings/1"

    def __init__(self, bindings_file: Path) -> None:
        self.bindings_file = Path(bindings_file)

    def _load_raw(self) -> Dict[str, Any]:
        if not self.bindings_file.exists():
            return {
                "schema": self.SCHEMA,
                "updatedAt": None,
                "bindings": {},
            }
        try:
            data = json.loads(self.bindings_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("bindings"), dict):
                return data
        except Exception:
            pass
        return {
            "schema": self.SCHEMA,
            "updatedAt": None,
            "bindings": {},
        }

    def _save_raw(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.bindings_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": self.SCHEMA,
            "updatedAt": _utc_iso_now(),
            "bindings": data.get("bindings", {}),
        }
        self.bindings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    @staticmethod
    def _key_for(target: str) -> str:
        return normalize_chat_name(target).casefold()

    def bind_contact(
        self,
        target: str,
        *,
        alias: str = "",
        role: str = "friend",
        ai_persona: str = "warm-companion",
        scheduled_enabled: bool = True,
        cron_hint: str = "0 9,21 * * *",
        auto_reply_enabled: bool = True,
        notes: str = "",
        special_care: Optional[bool] = None,
        care_level: Optional[str] = None,
        care_tags: Optional[Iterable[str]] = None,
        follow_up_days: Optional[int] = None,
        bound_agent_id: Optional[str] = None,
        bound_agent_name: Optional[str] = None,
        bound_agent_type: Optional[str] = None,
        vision_model_id: Optional[str] = None,
        auto_dispatch_instructions: Optional[bool] = None,
        auto_analyze_links_and_media: Optional[bool] = None,
    ) -> Dict[str, Any]:
        clean_target = (target or "").strip()
        if not clean_target:
            raise ValueError("Target contact or group name cannot be empty.")

        data = self._load_raw()
        bindings: Dict[str, Any] = dict(data.get("bindings") or {})
        key = self._key_for(clean_target)
        now = _utc_iso_now()
        prev = bindings.get(key) or {}

        if care_level is None and special_care is None:
            prev_level = str(prev.get("careLevel") or "").strip()
            resolved_level = normalize_care_level(prev_level, bool(prev.get("specialCare")))
        else:
            resolved_level = normalize_care_level(care_level, special_care)

        if special_care is False and care_level is None:
            resolved_level = "normal"

        resolved_special_care = resolved_level in ("special_care", "vip") or bool(special_care)
        if care_tags is not None:
            clean_tags: List[str] = []
            for t in care_tags:
                ts = str(t or "").strip()
                if ts and ts not in clean_tags:
                    clean_tags.append(ts)
        else:
            clean_tags = list(prev.get("careTags") or [])

        if resolved_level == "special_care" and not clean_tags:
            clean_tags = ["特别关心"]
        elif resolved_level == "vip" and not clean_tags:
            clean_tags = ["重点关照"]
        elif resolved_level == "normal" and care_tags is None and special_care is False:
            clean_tags = []

        if follow_up_days is not None:
            resolved_followup = max(1, int(follow_up_days))
        else:
            resolved_followup = int(prev.get("followUpDays") or CARE_DEFAULT_FOLLOWUP_DAYS.get(resolved_level, 7))

        resolved_agent_id = (
            str(bound_agent_id).strip()
            if bound_agent_id is not None
            else str(prev.get("boundAgentId") or "")
        )
        resolved_agent_type = (
            str(bound_agent_type).strip()
            if bound_agent_type is not None
            else str(prev.get("boundAgentType") or ("botstudio" if resolved_agent_id else ""))
        )
        resolved_agent_name = (
            str(bound_agent_name).strip()
            if bound_agent_name is not None
            else str(prev.get("boundAgentName") or resolved_agent_id)
        )
        resolved_vision_model = (
            str(vision_model_id).strip()
            if vision_model_id is not None and str(vision_model_id).strip()
            else str(prev.get("visionModelId") or "auto/deepseek-v4.1-flash")
        )
        resolved_auto_dispatch = (
            bool(auto_dispatch_instructions)
            if auto_dispatch_instructions is not None
            else bool(prev.get("autoDispatchInstructions", True))
        )
        resolved_auto_analyze = (
            bool(auto_analyze_links_and_media)
            if auto_analyze_links_and_media is not None
            else bool(prev.get("autoAnalyzeLinksAndMedia", True))
        )

        entry: Dict[str, Any] = {
            "target": clean_target,
            "normalizedTarget": normalize_chat_name(clean_target),
            "alias": alias.strip() or str(prev.get("alias") or ""),
            "role": (role or str(prev.get("role") or "friend")).strip(),
            "aiPersona": (ai_persona or str(prev.get("aiPersona") or "warm-companion")).strip(),
            "scheduledEnabled": bool(scheduled_enabled),
            "cronHint": (cron_hint or str(prev.get("cronHint") or "0 9,21 * * *")).strip(),
            "autoReplyEnabled": bool(auto_reply_enabled),
            "notes": notes.strip() if notes else str(prev.get("notes") or ""),
            "specialCare": resolved_special_care,
            "careLevel": resolved_level,
            "careTags": clean_tags,
            "followUpDays": resolved_followup,
            "boundAgentId": resolved_agent_id,
            "boundAgentName": resolved_agent_name,
            "boundAgentType": resolved_agent_type,
            "visionModelId": resolved_vision_model,
            "autoDispatchInstructions": resolved_auto_dispatch,
            "autoAnalyzeLinksAndMedia": resolved_auto_analyze,
            "createdAt": prev.get("createdAt") or now,
            "updatedAt": now,
        }
        bindings[key] = entry
        data["bindings"] = bindings
        saved = self._save_raw(data)
        return {
            "ok": True,
            "binding": entry,
            "totalBindings": len(saved["bindings"]),
            "bindingsFile": str(self.bindings_file),
        }

    def set_special_care(
        self,
        target: str,
        *,
        enabled: bool = True,
        care_level: Optional[str] = None,
        care_tags: Optional[Iterable[str]] = None,
        follow_up_days: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Promote or demote a contact/group between special_care, vip, and normal tiers."""
        clean_target = (target or "").strip()
        if not clean_target:
            raise ValueError("Target contact or group name cannot be empty.")

        prev = self.get_binding(clean_target) or {}
        resolved_target = str(prev.get("target") or clean_target)
        if not enabled:
            resolved_level = "normal"
            resolved_special = False
        else:
            resolved_level = normalize_care_level(care_level or "special_care", True)
            if resolved_level == "normal":
                resolved_level = "special_care"
            resolved_special = True

        default_role = str(prev.get("role") or ("group" if "bot" in resolved_target.lower() else "friend"))
        default_persona = str(prev.get("aiPersona") or "warm-friend")
        resolved_notes = notes.strip() if notes is not None else str(prev.get("notes") or "")
        return self.bind_contact(
            resolved_target,
            alias=str(prev.get("alias") or ""),
            role=default_role,
            ai_persona=default_persona,
            scheduled_enabled=bool(prev.get("scheduledEnabled", True)),
            cron_hint=str(prev.get("cronHint") or "0 9,21 * * *"),
            auto_reply_enabled=bool(prev.get("autoReplyEnabled", True)),
            notes=resolved_notes,
            special_care=resolved_special,
            care_level=resolved_level,
            care_tags=care_tags,
            follow_up_days=follow_up_days,
        )

    def unbind_contact(self, target: str) -> Dict[str, Any]:
        clean_target = (target or "").strip()
        data = self._load_raw()
        bindings: Dict[str, Any] = dict(data.get("bindings") or {})
        key = self._key_for(clean_target)
        removed = bindings.pop(key, None)
        if removed is None:
            for k in list(bindings.keys()):
                item = bindings[k]
                if _matches_target(clean_target, item.get("target", "")) or (
                    item.get("alias") and _matches_target(clean_target, item["alias"])
                ):
                    removed = bindings.pop(k)
                    break
        data["bindings"] = bindings
        self._save_raw(data)
        return {
            "ok": removed is not None,
            "removed": removed,
            "totalBindings": len(bindings),
            "bindingsFile": str(self.bindings_file),
        }

    def get_binding(self, target: str) -> Optional[Dict[str, Any]]:
        clean_target = (target or "").strip()
        if not clean_target:
            return None
        bindings = self._load_raw().get("bindings") or {}
        key = self._key_for(clean_target)
        if key in bindings:
            return bindings[key]
        for item in bindings.values():
            if _matches_target(clean_target, item.get("target", "")) or (
                item.get("alias") and _matches_target(clean_target, item["alias"])
            ):
                return item
        return None

    def list_bindings(self) -> List[Dict[str, Any]]:
        bindings = self._load_raw().get("bindings") or {}
        return sorted(bindings.values(), key=lambda x: x.get("updatedAt") or "", reverse=True)

    def bound_targets(self) -> List[str]:
        targets: List[str] = []
        for item in self.list_bindings():
            if item.get("target"):
                targets.append(str(item["target"]))
            if item.get("normalizedTarget"):
                targets.append(str(item["normalizedTarget"]))
            if item.get("alias"):
                targets.append(str(item["alias"]))
        return sorted(set(t for t in targets if t.strip()))


class ContactStyleProfiler:
    """Computes communication style, topic preferences, frequency & active hours per WeChat contact."""

    @staticmethod
    def _detect_categories(title: str, texts: List[str]) -> List[str]:
        blob = unicodedata.normalize("NFKC", f"{title} " + " ".join(texts)).casefold()
        categories: List[str] = []
        rules = [
            ("视频号/趣味生活", ("呆猫", "视频", "久病", "围观群众", "yobot", "小葵子", "哈哈")),
            ("AI/GitHub开源工程", ("github", "openbmb", "staffdeck", "openbot", "grok", "agent", "元宝", "sop", "开源")),
            ("学术论文/顶会", ("iclr", "acm", "tgrs", "ccf", "resworld", "遥感", "论文", "学术")),
            ("大模型社群讨论", ("model agent", "权重", "挂梯子", "turbo", "pluto", "嗯哼", "物芳", "没绷住")),
            ("企业办公通知", ("企业微信", "安心的", "郝泽华", "邀请", "管理员", "微信开放社区", "微信号", "微信团队")),
            ("个人收藏/备忘录", ("文件传输", "工具箱", "笔记", "指南", "日记")),
            ("公众号/服务号资讯", ("公众号", "服务号", "村西边老王", "看一看", "百度网", "微信小店", "腾讯云")),
        ]
        for label, keywords in rules:
            if any(kw in blob for kw in keywords):
                categories.append(label)
        return categories or ["日常综合沟通"]

    @staticmethod
    def _estimate_frequency(msg_count: int, markers: List[str]) -> str:
        joined = " ".join(markers)
        has_recent_hour = any(_HM_RE.search(m) for m in markers) or ("昨天" in joined) or ("今天" in joined)
        distinct_days = len(set(_DATE_TOKEN_RE.findall(joined)))
        if msg_count >= 12 or (has_recent_hour and distinct_days >= 2):
            return "高频/近期活跃"
        if has_recent_hour or distinct_days >= 1 or msg_count >= 5:
            return "中频/周内阶段互动"
        return "低频/专题触达"

    @staticmethod
    def _synthesize_style(
        title: str,
        *,
        categories: List[str],
        self_count: int,
        peer_count: int,
        avg_length: float,
        peak_slot: str,
        is_folder: bool,
    ) -> Tuple[str, str, str]:
        norm_title = normalize_chat_name(title).casefold()
        if is_folder:
            return (
                "订阅资讯/组织聚合文件夹",
                "聚合类入口（包含多条推送或二级子会话），非单一自然人对话。",
                "定期只读摘要抓取即可，无需直接发送聊天消息。",
            )
        if "心安" in norm_title:
            return (
                "轻松趣味视频号与新鲜工具分享型好友",
                f"偏好视频号短视频与实用工具链接互动，平均片段约 {avg_length:.1f} 字；近期活跃于「{peak_slot}」。",
                "适合轻松幽默、带生活梗与工具反馈的定时问候及 AI 闲聊。",
            )
        if "openbot" in norm_title:
            return (
                "AI 开源工程与 Agent 总结型核心测试群",
                f"聚焦 GitHub/Agent 项目总结、SOP 与工具地址沉淀（如 StaffDeck），消息偏长干货（均值 {avg_length:.1f} 字），近期活跃于「{peak_slot}」。",
                "适合直接同步测试进展、技术摘要与自动化回归状态。",
            )
        if "model agent" in norm_title:
            return (
                "高活跃极客大模型社群",
                f"群友口语节奏快、短句即时吐槽多（如权重下载、模型评测对比），活跃集中于「{peak_slot}」。",
                "默认免打扰旁观读取重点结论，如需发言应简短直给技术细节。",
            )
        if "苏文璐" in norm_title:
            return (
                "学术前沿与顶会论文精准分享型好友",
                f"沟通克制低噪，内容高度聚焦顶会论文/科研动向（ICLR/世界模型），常见于「{peak_slot}」。",
                "适合分享高信噪比学术论文或科研进展，避免高频寒暄打扰。",
            )
        if "企业微信" in norm_title or "服务通知" in norm_title:
            return (
                "组织协同与商务建联对象",
                "以企业微信邀请与简洁礼貌破冰（如「你好」）为主，属于低频商务/工作触发节点。",
                "保持专业礼貌回复，重要通知建议同步提醒用户人工确认。",
            )
        if "文件传输" in norm_title:
            return (
                "个人知识收藏与链接中转站",
                "用于个人沉淀 AI 工具箱与技术指南文章链接，属于自我工作流归档节点。",
                "可用于定时投递每日日报或测试回执归档，不会打扰外部好友。",
            )
        if "微信团队" in norm_title:
            return (
                "官方安全告警与端内调试反馈通道",
                "承载登录安全提醒（开发者社区等）及早期置顶/功能联调记录。",
                "仅只读监控安全登录提示，勿向官方通道自动群发。",
            )
        ratio_hint = "主动分享居多" if self_count >= peer_count else "对方推送/发言较多"
        return (
            f"{categories[0]}沟通风格",
            f"共识别 {self_count + peer_count} 条文本片段（{ratio_hint}），平均 {avg_length:.1f} 字，峰值时段为「{peak_slot}」。",
            "可根据最近聊天主题配置低频精准跟进或只读观察。",
        )

    def profile_single(
        self,
        title: str,
        *,
        list_snippets: Optional[List[str]] = None,
        observed_history: Optional[Dict[str, Any]] = None,
        fallback_texts: Optional[List[str]] = None,
        binding: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        snippets = [s for s in (list_snippets or []) if s]
        records = list((observed_history or {}).get("records") or [])
        is_folder = normalize_chat_name(title).casefold() in FOLDER_CHAT_TITLES

        msg_records = [r for r in records if r.get("kind") == "message"]
        ts_records = [r for r in records if r.get("kind") == "timestamp"]

        if msg_records:
            texts = [str(r.get("text", "")).strip() for r in msg_records if str(r.get("text", "")).strip()]
            self_count = sum(1 for r in msg_records if r.get("direction") == "self")
            peer_count = sum(1 for r in msg_records if r.get("direction") == "peer")
        else:
            texts = [str(t).strip() for t in (fallback_texts or []) if str(t).strip()]
            self_count = 0
            peer_count = len(texts)

        all_time_sources = (
            snippets
            + [str(r.get("text", "")) for r in ts_records]
            + [str(r.get("timeMarker", "")) for r in msg_records if r.get("timeMarker")]
            + texts
        )
        markers, slot_dist = extract_time_markers(all_time_sources)
        peak_slot = max(slot_dist.items(), key=lambda kv: kv[1])[0] if slot_dist else "时段样本不足（待继续滚动采集）"

        avg_len = round(sum(len(t) for t in texts) / len(texts), 1) if texts else 0.0
        categories = self._detect_categories(title, texts + snippets)
        freq_label = self._estimate_frequency(len(texts), markers)
        style_tag, style_summary, strategy = self._synthesize_style(
            title,
            categories=categories,
            self_count=self_count,
            peer_count=peer_count,
            avg_length=avg_len,
            peak_slot=peak_slot,
            is_folder=is_folder,
        )

        care_level = normalize_care_level(
            (binding or {}).get("careLevel"),
            (binding or {}).get("specialCare"),
        )
        special_care = care_level in ("special_care", "vip") or bool((binding or {}).get("specialCare"))
        care_tags = list((binding or {}).get("careTags") or [])
        if care_level == "special_care" and not care_tags:
            care_tags = ["特别关心"]
        elif care_level == "vip" and not care_tags:
            care_tags = ["重点关照"]
        follow_up_days = int((binding or {}).get("followUpDays") or CARE_DEFAULT_FOLLOWUP_DAYS.get(care_level, 14))

        total_dir = self_count + peer_count
        self_ratio = round(self_count / max(1, total_dir), 3)
        peer_ratio = round(peer_count / max(1, total_dir), 3) if total_dir > 0 else 0.0
        if is_folder or total_dir == 0:
            balance_label = "只读聚合/待观测" if is_folder else "待补充对话样本"
        elif self_count > 0 and peer_count > 0:
            if 0.3 <= self_ratio <= 0.7:
                balance_label = "双向均衡互动"
            elif self_ratio > 0.7:
                balance_label = "我方主动居多（留意对方反馈）"
            else:
                balance_label = "对方主动偏高（建议及时回应）"
        elif self_count > 0:
            balance_label = "我方单向发起（待对方回复）"
        else:
            balance_label = "对方发送为主"

        warmth = self._compute_warmth_score(
            message_count=len(texts),
            self_count=self_count,
            peer_count=peer_count,
            markers=markers,
            care_level=care_level,
            is_folder=is_folder,
        )
        best_window = self._best_contact_window(peak_slot)
        proactive_draft = self._build_proactive_care_draft(
            title,
            care_level=care_level,
            categories=categories,
            best_window=best_window,
            is_folder=is_folder,
        )

        return {
            "target": (binding or {}).get("target") or normalize_chat_name(title),
            "matchedTitle": title,
            "slug": _slugify_target(title),
            "bound": binding is not None,
            "role": (binding or {}).get("role") or ("folder" if is_folder else "observed"),
            "isFolderContainer": is_folder,
            "aiPersona": (binding or {}).get("aiPersona", ""),
            "cronHint": (binding or {}).get("cronHint", ""),
            "autoReplyEnabled": bool((binding or {}).get("autoReplyEnabled", True)) if binding else False,
            "scheduledEnabled": bool((binding or {}).get("scheduledEnabled", True)) if binding else False,
            "notes": str((binding or {}).get("notes") or ""),
            "specialCare": special_care,
            "careLevel": care_level,
            "careLevelLabel": CARE_LEVEL_LABELS.get(care_level, "普通会话"),
            "monitorPriority": CARE_MONITOR_PRIORITY.get(care_level, "P2-常规"),
            "careTags": care_tags,
            "followUpDays": follow_up_days,
            "messageCount": len(texts),
            "selfCount": self_count,
            "peerCount": peer_count,
            "selfRatio": self_ratio,
            "peerRatio": peer_ratio,
            "interactionBalance": balance_label,
            "warmthScore": warmth,
            "bestContactWindow": best_window,
            "proactiveCareDraft": proactive_draft,
            "avgLength": avg_len,
            "activeTimeMarkers": markers,
            "timeSlotDistribution": slot_dist,
            "peakTimeSlot": peak_slot,
            "frequencyLabel": freq_label,
            "contentCategories": categories,
            "friendStyleTag": style_tag,
            "styleSummary": style_summary,
            "recommendedStrategy": strategy,
            "sampleExcerpts": texts[:8],
        }

    @staticmethod
    def _compute_warmth_score(
        *,
        message_count: int,
        self_count: int,
        peer_count: int,
        markers: List[str],
        care_level: str,
        is_folder: bool,
    ) -> int:
        if is_folder:
            return min(35, 10 + message_count * 2)
        base = 20 if (self_count + peer_count) > 0 else 10
        volume_pts = min(35, message_count * 2)
        total = self_count + peer_count
        if total > 0 and self_count > 0 and peer_count > 0:
            balance_ratio = min(self_count, peer_count) / max(self_count, peer_count)
            balance_pts = int(round(20 * balance_ratio))
        elif total > 0:
            balance_pts = 8
        else:
            balance_pts = 0
        recency_pts = min(15, len(markers) * 3)
        care_bonus = 12 if care_level == "special_care" else (6 if care_level == "vip" else 0)
        return max(5, min(100, base + volume_pts + balance_pts + recency_pts + care_bonus))

    @staticmethod
    def _best_contact_window(peak_slot: str) -> str:
        if peak_slot in TIME_WINDOW_MAP:
            return TIME_WINDOW_MAP[peak_slot]
        return "18:00-21:30 (默认晚间黄金触达窗)"

    @staticmethod
    def _build_proactive_care_draft(
        title: str,
        *,
        care_level: str,
        categories: List[str],
        best_window: str,
        is_folder: bool,
    ) -> str:
        if is_folder:
            return "订阅/聚合容器建议只做定期摘要读取，不主动发送私聊。"
        clean_name = normalize_chat_name(title)
        topic = categories[0] if categories else "最近动态"
        if care_level == "special_care":
            return f"嗨 {clean_name}～最近看你常关注{topic}，趁「{best_window.split(' ')[0]}」方便时问候下，有需要我或 OpenBot 随时配合！"
        if care_level == "vip":
            return f"【重点跟进】{clean_name}，近期围绕「{topic}」互动较多，可在「{best_window.split(' ')[0]}」发送一次轻量进展同步。"
        return f"按「{best_window.split(' ')[0]}」时段保持常规温和互动即可。"

    def generate_analytics_report(
        self,
        *,
        inspection_report: Optional[Dict[str, Any]],
        histories_dir: Path,
        bindings: List[Dict[str, Any]],
        reports_dir: Path,
        focus_target: Optional[str] = None,
    ) -> Dict[str, Any]:
        reports_dir = Path(reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        histories_dir = Path(histories_dir)

        # Load all observed contact history JSON files keyed by normalized target
        history_by_key: Dict[str, Dict[str, Any]] = {}
        if histories_dir.exists():
            for hp in sorted(histories_dir.glob("*_history.json")):
                try:
                    data = json.loads(hp.read_text(encoding="utf-8"))
                    title = str(data.get("matchedTitle") or data.get("target") or "")
                    if title:
                        history_by_key[normalize_chat_name(title).casefold()] = data
                except Exception:
                    continue

        # Aggregate deduplicated sessions from latest inspection report
        session_buckets: Dict[str, Dict[str, Any]] = {}
        for sess in (inspection_report or {}).get("sessions") or []:
            raw_title = str(sess.get("fullTitle") or sess.get("listTitleSnippet") or "").strip()
            if not raw_title or re.match(r"^\d{1,2}/\d{1,2}$", raw_title):
                continue
            key = normalize_chat_name(raw_title).casefold()
            bucket = session_buckets.setdefault(
                key,
                {"title": raw_title, "snippets": [], "texts": []},
            )
            if len(raw_title) > len(bucket["title"]):
                bucket["title"] = raw_title
            for snip_key in ("listTitleSnippet", "listPreviewSnippet"):
                val = str(sess.get(snip_key) or "").strip()
                if val and val not in bucket["snippets"]:
                    bucket["snippets"].append(val)
            for msg in sess.get("visibleMessages") or []:
                msg_s = str(msg).strip()
                if msg_s and msg_s not in bucket["texts"]:
                    bucket["texts"].append(msg_s)

        # Ensure every deep-observed history or bound contact is also included
        for key, hdata in history_by_key.items():
            if key not in session_buckets:
                session_buckets[key] = {
                    "title": str(hdata.get("matchedTitle") or hdata.get("target") or key),
                    "snippets": [],
                    "texts": [],
                }
        for b in bindings:
            b_target = str(b.get("target") or "").strip()
            if not b_target:
                continue
            matched_existing = any(_matches_target(b_target, v["title"]) for v in session_buckets.values())
            if not matched_existing:
                key = normalize_chat_name(b_target).casefold()
                session_buckets[key] = {"title": b_target, "snippets": [], "texts": []}

        def _find_binding(title: str) -> Optional[Dict[str, Any]]:
            for b in bindings:
                if _matches_target(str(b.get("target", "")), title) or (
                    b.get("alias") and _matches_target(str(b["alias"]), title)
                ):
                    return b
            return None

        def _find_history(title: str) -> Optional[Dict[str, Any]]:
            key = normalize_chat_name(title).casefold()
            if key in history_by_key:
                return history_by_key[key]
            for hdata in history_by_key.values():
                if _matches_target(str(hdata.get("target", "")), title) or _matches_target(
                    title, str(hdata.get("matchedTitle", ""))
                ):
                    return hdata
            return None

        profiles: List[Dict[str, Any]] = []
        for bucket in session_buckets.values():
            title = bucket["title"]
            if focus_target and not _matches_target(focus_target, title):
                continue
            prof = self.profile_single(
                title,
                list_snippets=bucket["snippets"],
                observed_history=_find_history(title),
                fallback_texts=bucket["texts"],
                binding=_find_binding(title),
            )
            profiles.append(prof)

        # Special Care -> VIP -> Bound -> Active non-folders -> Folders
        profiles.sort(
            key=lambda p: (
                CARE_LEVEL_ORDER.get(p.get("careLevel", "normal"), 2),
                not p["bound"],
                p["isFolderContainer"],
                -int(p.get("warmthScore") or 0),
                -p["messageCount"],
                p["matchedTitle"],
            )
        )

        global_slots: Counter[str] = Counter()
        for p in profiles:
            for slot, cnt in p["timeSlotDistribution"].items():
                global_slots[slot] += cnt

        special_care_profiles = [p for p in profiles if p.get("careLevel") == "special_care"]
        vip_profiles = [p for p in profiles if p.get("careLevel") == "vip"]
        non_folder = [p for p in profiles if not p.get("isFolderContainer")]
        avg_warmth = round(sum(int(p.get("warmthScore") or 0) for p in non_folder) / len(non_folder), 1) if non_folder else 0.0

        analytics: Dict[str, Any] = {
            "ok": True,
            "generatedAt": _utc_iso_now(),
            "focusTarget": focus_target,
            "profileCount": len(profiles),
            "boundProfileCount": sum(1 for p in profiles if p["bound"]),
            "specialCareSummary": {
                "specialCareCount": len(special_care_profiles),
                "vipCount": len(vip_profiles),
                "totalMessagesAnalyzed": sum(int(p.get("messageCount") or 0) for p in profiles),
                "averageWarmthScore": avg_warmth,
                "priorityTargets": [
                    {
                        "target": p["target"],
                        "matchedTitle": p["matchedTitle"],
                        "careLevel": p["careLevel"],
                        "careLevelLabel": p["careLevelLabel"],
                        "warmthScore": p["warmthScore"],
                        "messageCount": p["messageCount"],
                        "bestContactWindow": p["bestContactWindow"],
                    }
                    for p in (special_care_profiles + vip_profiles)
                ],
            },
            "overallTimeSlotDistribution": {slot: int(global_slots.get(slot, 0)) for slot in TIME_SLOTS if global_slots.get(slot, 0) > 0},
            "profiles": profiles,
        }

        json_path = reports_dir / "contact_analytics_report.json"
        md_path = reports_dir / "contact_analytics_report.md"
        json_path.write_text(json.dumps(analytics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(self._format_markdown_report(analytics), encoding="utf-8")
        analytics["reportJsonPath"] = str(json_path)
        analytics["reportMarkdownPath"] = str(md_path)
        return analytics

    @staticmethod
    def _format_markdown_report(analytics: Dict[str, Any]) -> str:
        lines: List[str] = [
            "# 微信好友沟通风格、聊天频率与活跃时段统计报告",
            "",
            f"- 生成时间: `{analytics.get('generatedAt', '')}`",
            f"- 纳管分析对象数: **{analytics.get('profileCount', 0)}**（已绑定重点追踪对象: **{analytics.get('boundProfileCount', 0)}**）",
            "",
            "## 一、全局聊天活跃时段分布",
            "",
        ]
        overall_slots = analytics.get("overallTimeSlotDistribution") or {}
        if overall_slots:
            for slot, cnt in overall_slots.items():
                lines.append(f"- `{slot}`: **{cnt}** 次时间节点记录")
        else:
            lines.append("- 暂无可解析的时间戳节点，可运行 `observe-contact` 深入采集更多历史页。")

        profiles = analytics.get("profiles") or []
        bound_profiles = [p for p in profiles if p.get("bound")]
        other_profiles = [p for p in profiles if not p.get("bound") and not p.get("isFolderContainer")]
        folder_profiles = [p for p in profiles if p.get("isFolderContainer")]

        if bound_profiles:
            lines.extend(["", "## 二、特别关心 / 重点关照与已绑定好友深度画像", ""])
            for p in bound_profiles:
                care_badge = f" · {p.get('careLevelLabel', '普通会话')}({p.get('monitorPriority', 'P2')})" if p.get("specialCare") else ""
                lines.append(f"### {p['matchedTitle']} (`{p['role']}` · 已绑定{care_badge})")
                lines.append(f"- **互动温度**: **{p.get('warmthScore', 0)} / 100** | **互动平衡**: {p.get('interactionBalance', '')} | **最佳触达窗**: {p.get('bestContactWindow', '')}")
                lines.append(f"- **好友/群风格**: {p['friendStyleTag']} —— {p['styleSummary']}")
                lines.append(f"- **AI 人设绑定**: {p['aiPersona'] or '默认'} | 定时策略: `{p['cronHint']}`")
                lines.append(
                    f"- **互动统计**: 文本片段 **{p['messageCount']}** 条（我方 {p['selfCount']} / 对方 {p['peerCount']}，均值 {p['avgLength']} 字）"
                )
                lines.append(f"- **频率评估**: {p['frequencyLabel']} | **高频时段**: {p['peakTimeSlot']}")
                lines.append(f"- **活跃时间记录**: {', '.join(p['activeTimeMarkers']) if p['activeTimeMarkers'] else '无'}")
                lines.append(f"- **核心话题**: {', '.join(p['contentCategories'])}")
                lines.append(f"- **主动关怀草稿**: {p.get('proactiveCareDraft', '')}")
                lines.append(f"- **互动建议**: {p['recommendedStrategy']}")
                lines.append("")

        lines.extend(["## 三、其余会话对象沟通风格与频率总览", ""])
        for p in other_profiles:
            lines.append(f"### {p['matchedTitle']}")
            lines.append(f"- **风格标签**: {p['friendStyleTag']} —— {p['styleSummary']}")
            lines.append(
                f"- **频率 / 时段**: {p['frequencyLabel']} | 峰值时段: {p['peakTimeSlot']} | 时间点: {', '.join(p['activeTimeMarkers']) if p['activeTimeMarkers'] else '待采集'}"
            )
            lines.append(f"- **话题分类**: {', '.join(p['contentCategories'])} | **建议策略**: {p['recommendedStrategy']}")
            lines.append("")

        if folder_profiles:
            lines.extend(["## 四、订阅/组织聚合文件夹", ""])
            for p in folder_profiles:
                lines.append(f"- **{p['matchedTitle']}**: {p['friendStyleTag']}（最近节点: {', '.join(p['activeTimeMarkers']) or '无'}）")
            lines.append("")

        return "\n".join(lines)


class ContextualAIChatGenerator:
    """Generates natural scheduled test check-ins or contextual AI chat messages for bound contacts."""

    @staticmethod
    def build_message(
        target: str,
        *,
        mode: str = "scheduled",
        custom_text: Optional[str] = None,
        binding: Optional[Dict[str, Any]] = None,
        recent_messages: Optional[List[str]] = None,
    ) -> str:
        if custom_text and custom_text.strip():
            return custom_text.strip()

        clean_target = normalize_chat_name(target) or target
        persona = (binding or {}).get("aiPersona") or "友好自然的智能助手"
        recent = [m.strip() for m in (recent_messages or []) if m and len(m.strip()) >= 2]
        snippet = " / ".join(recent[:2])[:48]

        norm_mode = (mode or "scheduled").strip().lower()
        if norm_mode in ("scheduled", "cron", "timer"):
            return f"【定时测试】嗨 {clean_target}～我是 OpenBot 微信插件定时问候测试消息 ⏰✨（风格设定：{persona[:24]}）"
        if snippet:
            return f"🤖 [AI 随便聊聊] 刚看了咱们最近的记录（{snippet}），已经完成绑定和对话统计测试，随时可以一起聊～"
        return f"🤖 [AI 随便聊聊] 嗨 {clean_target}，我现在按「{persona[:28]}」人设和你上线测试 AI 聊天啦～"
