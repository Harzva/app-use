"""Pre-call 1-click brief & human phone script advisor (`PreCallBriefEngine`).

Aggregates up to 5 real local data sources fault-tolerantly without fabricating
missing records:
1. Chat histories (`reports/contacts/*_history.json`) & realtime monitor events
2. Contact profiles (`engine.profile_contacts()`) & bindings (`engine.bindings`)
3. Soul & long-term memory (`engine.soul_profiler`)
4. WeChat Moments posts & mutual interactions (`engine.moments`)
5. SalesCRM opportunity metrics, stage, and timeline (`engine.sales_crm`)

Builds a deterministic zero-hallucination baseline brief first, and optionally
upgrades it via `engine.models.generate_chat_reply(...)` with strict JSON parsing
and smooth fallback on any model/timeout/format error.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .live_inspector import _matches_target, _slugify_target
from .moments_feed import normalize_key_text
from .safety import normalize_chat_name

GOAL_LABELS: Dict[str, str] = {
    "general": "综合沟通",
    "followup": "日常破冰与跟进",
    "quote": "推进方案与报价",
    "care": "客情维系关怀",
    "recovery": "异议拆解与情绪安抚",
    "custom": "自定义沟通目标",
}

_PRICE_HINTS = ("报价", "价格", "多少钱", "预算", "费用", "优惠", "折扣", "成本", "太贵")
_DELIVERY_HINTS = ("排期", "交付", "上线", "演示", "demo", "试用", "测试", "合同", "签约", "周", "月底", "截止")
_FRICTION_HINTS = ("不满意", "太慢", "卡住", "报错", "失败", "投诉", "担心", "顾虑", "延迟", "问题", "暂缓", "退")
_POSITIVE_HINTS = ("谢谢", "感谢", "太好了", "不错", "没问题", "期待", "哈哈", "辛苦", "赞", "满意", "顺利")
_COMMITMENT_HINTS = ("测试", "演示", "报价", "方案", "发您", "对齐", "确认", "下周", "周", "明天", "月底", "预约", "约定", "跟进")
_GENERIC_TOPIC_LABELS = {"日常沟通", "日常综合沟通"}

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_SECRET_TOKEN_RE = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{10,}|gh[pousr]_[A-Za-z0-9]{16,})")
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"'）)」』]+", re.IGNORECASE)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _speech_friendly_hook(text: Any, *, max_len: int = 28) -> str:
    """Convert raw chat/Moments text into a spoken-friendly snippet without raw URLs."""
    raw = _clean_text(text)
    if not raw:
        return ""
    had_url = bool(_URL_IN_TEXT_RE.search(raw))
    no_url = _URL_IN_TEXT_RE.sub("", raw)
    no_url = re.sub(r"\s+", " ", no_url).strip(" ：:，,、;；-")
    if had_url and len(no_url) < 2:
        return "之前发过来的链接"
    snippet = no_url if no_url else raw
    if len(snippet) > max_len:
        return snippet[:max_len] + "…"
    return snippet


def _redact_for_llm(text: Any) -> str:
    return _SECRET_TOKEN_RE.sub("[已脱敏凭据]", _clean_text(text))


def _format_time_marker(raw: Any) -> str:
    if raw is None or raw == "":
        return ""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            ts = float(raw)
            if ts > 1_000_000_000:
                return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
        except (OSError, OverflowError, ValueError):
            return ""
    text = _clean_text(raw)
    if re.fullmatch(r"\d{10}(?:\.\d+)?", text):
        try:
            return datetime.fromtimestamp(float(text)).strftime("%m-%d %H:%M")
        except (OSError, OverflowError, ValueError):
            return text
    if "T" in text and len(text) >= 16 and text[:4].isdigit():
        return text[:16].replace("T", " ")
    return text[:28]


def _names_match(target: str, candidate: str, aliases: Sequence[str] = ()) -> bool:
    cand = str(candidate or "").strip()
    if not cand:
        return False
    # Reject raw message snippet lines or unrelated multi-person group chats
    if (":" in cand or "：" in cand) and not any(":" in t or "：" in t for t in (target, *aliases) if t):
        return False
    candidates_to_check = [target, *[a for a in aliases if str(a or "").strip()]]
    for ref in candidates_to_check:
        ref_s = str(ref or "").strip()
        if not ref_s:
            continue
        if "、" in cand and "、" not in ref_s:
            continue
        if _matches_target(ref_s, cand):
            return True
        if normalize_chat_name(ref_s).casefold() == normalize_chat_name(cand).casefold():
            return True
        k_ref = normalize_key_text(ref_s)
        k_cand = normalize_key_text(cand)
        if len(k_ref) >= 2 and k_ref == k_cand:
            return True
    return False


def _dedupe_strings(items: Sequence[Any], *, limit: int = 8) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        s = _clean_text(item)
        if not s:
            continue
        key = unicodedata.normalize("NFKC", s).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    """Parse strict JSON from LLM output, stripping `<think>` blocks and ```json code fences."""
    cleaned = _THINK_TAG_RE.sub("", str(raw_text or "")).strip()
    if not cleaned:
        return None

    candidates: List[str] = []
    fence_match = _CODE_FENCE_RE.search(cleaned)
    if fence_match:
        candidates.append(fence_match.group(1).strip())
    candidates.append(cleaned)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # Fallback: extract balanced outermost `{ ... }` block
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for idx in range(start, len(cleaned)):
        ch = cleaned[idx]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                snippet = cleaned[start : idx + 1]
                try:
                    parsed = json.loads(snippet)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return None
    return None


class PreCallBriefEngine:
    """Aggregates 5 local WeChat sources into a pre-call brief & phone script card."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_brief(
        self,
        target: str,
        *,
        goal: str = "general",
        custom_goal: str = "",
        use_llm: bool = True,
        max_messages: int = 30,
        max_moments: int = 12,
    ) -> Dict[str, Any]:
        raw_target = str(target or "").strip()
        clean_target = normalize_chat_name(raw_target).strip()
        if not raw_target or not clean_target:
            return {
                "ok": False,
                "error_code": "target_required",
                "error": "请先选择或输入需要通话的联系人名称",
            }

        norm_goal, goal_label, clean_custom_goal = self._normalize_goal(goal, custom_goal)
        msg_limit = max(1, int(max_messages))
        moments_limit = max(1, int(max_moments))

        # 1) Binding & Analytics first (aliases help match chat/moments/soul cleanly)
        binding, contact_profile = self._collect_binding_and_profile(raw_target, clean_target)
        aliases: List[str] = []
        if binding and binding.get("alias"):
            aliases.append(str(binding["alias"]))
        if binding and binding.get("target"):
            aliases.append(str(binding["target"]))
        if contact_profile and contact_profile.get("matchedTitle"):
            aliases.append(str(contact_profile["matchedTitle"]))

        # 2) Chat history + Monitor recent events
        chat_data = self._collect_chat_history(clean_target, aliases=aliases, max_messages=msg_limit)
        # 3) Soul profile & long-term memory
        soul_data = self._collect_soul_memory(clean_target, aliases=aliases)
        # 4) Moments posts & mutual interactions
        moments_data = self._collect_moments(clean_target, aliases=aliases, max_moments=moments_limit)
        # 5) SalesCRM opportunity & timeline
        crm_data = self._collect_crm(clean_target, aliases=aliases)

        matched_title = self._resolve_matched_title(
            raw_target=raw_target,
            clean_target=clean_target,
            binding=binding,
            contact_profile=contact_profile,
            chat_data=chat_data,
            soul_data=soul_data,
            moments_data=moments_data,
            crm_data=crm_data,
        )

        data_coverage = {
            "chatMessages": int(chat_data["totalCount"]),
            "momentsPosts": int(moments_data["postsCount"]),
            "momentsMutualHits": int(moments_data["mutualHits"]),
            "soulMemories": int(soul_data["totalMemories"]),
            "hasCrmRecord": bool(crm_data["hasRecord"]),
            "crmStage": str(crm_data["stage"] or ""),
        }

        brief = self._build_baseline_brief(
            target=raw_target,
            matched_title=matched_title,
            goal=norm_goal,
            goal_label=goal_label,
            custom_goal=clean_custom_goal,
            data_coverage=data_coverage,
            binding=binding,
            contact_profile=contact_profile,
            chat_data=chat_data,
            soul_data=soul_data,
            moments_data=moments_data,
            crm_data=crm_data,
        )

        if use_llm:
            brief = self._enhance_with_llm(
                brief=brief,
                target=raw_target,
                matched_title=matched_title,
                goal=norm_goal,
                goal_label=goal_label,
                custom_goal=clean_custom_goal,
                binding=binding,
                contact_profile=contact_profile,
                chat_data=chat_data,
                soul_data=soul_data,
                moments_data=moments_data,
                crm_data=crm_data,
            )

        return brief

    # ------------------------------------------------------------------
    # Goal Normalization & Title Resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_goal(goal: str, custom_goal: str) -> Tuple[str, str, str]:
        norm_goal = str(goal or "general").strip().lower()
        clean_custom = _clean_text(custom_goal)
        if norm_goal not in GOAL_LABELS:
            norm_goal = "general"
        if norm_goal == "custom":
            label = clean_custom[:60] if clean_custom else GOAL_LABELS["custom"]
        else:
            label = GOAL_LABELS[norm_goal]
        return norm_goal, label, clean_custom

    @staticmethod
    def _resolve_matched_title(
        *,
        raw_target: str,
        clean_target: str,
        binding: Optional[Dict[str, Any]],
        contact_profile: Optional[Dict[str, Any]],
        chat_data: Dict[str, Any],
        soul_data: Dict[str, Any],
        moments_data: Dict[str, Any],
        crm_data: Dict[str, Any],
    ) -> str:
        candidates = [
            (binding or {}).get("target"),
            (contact_profile or {}).get("matchedTitle"),
            (soul_data.get("contactProfile") or {}).get("matchedTitle"),
            (crm_data.get("person") or {}).get("displayName"),
            chat_data.get("matchedTitle"),
            moments_data.get("matchedAuthor"),
            clean_target,
            raw_target,
        ]
        for c in candidates:
            cs = _clean_text(c)
            if cs:
                return cs
        return raw_target

    # ------------------------------------------------------------------
    # 5-Way Fault-Tolerant Local Data Collectors
    # ------------------------------------------------------------------

    def _collect_binding_and_profile(
        self,
        raw_target: str,
        clean_target: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        binding: Optional[Dict[str, Any]] = None
        bindings_store = getattr(self.engine, "bindings", None)
        if bindings_store is not None:
            try:
                get_b = getattr(bindings_store, "get_binding", None)
                if callable(get_b):
                    res = get_b(raw_target) or get_b(clean_target)
                    if isinstance(res, dict):
                        binding = dict(res)
            except Exception:
                binding = None
            if binding is None:
                try:
                    list_b = getattr(bindings_store, "list_bindings", None)
                    if callable(list_b):
                        for item in list_b() or []:
                            if isinstance(item, dict) and (
                                _names_match(clean_target, str(item.get("target") or ""))
                                or _names_match(clean_target, str(item.get("alias") or ""))
                            ):
                                binding = dict(item)
                                break
                except Exception:
                    pass

        aliases = [str(binding.get("alias"))] if binding and binding.get("alias") else []
        contact_profile: Optional[Dict[str, Any]] = None
        profiles_list: List[Dict[str, Any]] = []
        prof_fn = getattr(self.engine, "profile_contacts", None)
        if callable(prof_fn):
            try:
                analytics = prof_fn()
                if isinstance(analytics, dict) and isinstance(analytics.get("profiles"), list):
                    profiles_list = [p for p in analytics["profiles"] if isinstance(p, dict)]
            except Exception:
                profiles_list = []

        # Read-only fallback if profile_contacts() raised (e.g., auth gate missing `status`)
        if not profiles_list:
            try:
                inspector = getattr(self.engine, "inspector", None)
                reports_dir = getattr(inspector, "reports_dir", None)
                if reports_dir:
                    report_path = Path(reports_dir) / "contact_analytics_report.json"
                    if report_path.is_file():
                        cached = json.loads(report_path.read_text(encoding="utf-8"))
                        if isinstance(cached, dict) and isinstance(cached.get("profiles"), list):
                            profiles_list = [p for p in cached["profiles"] if isinstance(p, dict)]
            except Exception:
                profiles_list = []

        for prof in profiles_list:
            if _names_match(clean_target, str(prof.get("matchedTitle") or ""), aliases) or _names_match(
                clean_target, str(prof.get("target") or ""), aliases
            ):
                contact_profile = dict(prof)
                break

        return binding, contact_profile

    def _collect_chat_history(
        self,
        clean_target: str,
        *,
        aliases: Sequence[str],
        max_messages: int,
    ) -> Dict[str, Any]:
        raw_messages: List[Dict[str, str]] = []
        matched_title = ""
        taken_over = False
        takeover_reason = ""

        inspector = getattr(self.engine, "inspector", None)
        reports_dir_val = getattr(inspector, "reports_dir", None) if inspector is not None else None
        target_slug = _slugify_target(clean_target)

        # 1a) Read `<reports_dir>/contacts/*_history.json`
        if reports_dir_val:
            try:
                contacts_dir = Path(reports_dir_val) / "contacts"
                if contacts_dir.is_dir():
                    history_files = sorted(
                        contacts_dir.glob("*_history.json"),
                        key=lambda p: (p.stat().st_mtime, p.name),
                    )
                    for hp in history_files:
                        try:
                            doc = json.loads(hp.read_text(encoding="utf-8"))
                        except Exception:
                            continue
                        if not isinstance(doc, dict):
                            continue
                        doc_title = str(doc.get("matchedTitle") or doc.get("target") or doc.get("contact") or "").strip()
                        doc_slug = str(doc.get("slug") or "").strip()
                        stem_prefix = hp.stem[:-8] if hp.stem.endswith("_history") else hp.stem
                        is_match = (
                            (doc_title and _names_match(clean_target, doc_title, aliases))
                            or (doc_slug and doc_slug == target_slug)
                            or (not doc_title and _names_match(clean_target, stem_prefix, aliases))
                        )
                        if not is_match:
                            continue
                        if doc_title and len(doc_title) > len(matched_title):
                            matched_title = doc_title
                        entries = doc.get("records") if isinstance(doc.get("records"), list) else doc.get("messages")
                        for rec in entries or []:
                            if not isinstance(rec, dict):
                                continue
                            kind = str(rec.get("kind") or "message").strip().lower()
                            if kind == "timestamp":
                                continue
                            if kind not in ("message", "media_note", ""):
                                continue
                            txt = _clean_text(rec.get("text") or "")
                            if not txt:
                                continue
                            raw_dir = str(rec.get("direction") or "peer").strip().lower()
                            direction = "self" if raw_dir in ("self", "me", "owner", "out", "outgoing") else "peer"
                            time_marker = _format_time_marker(
                                rec.get("timeMarker") or rec.get("ts") or rec.get("timestamp")
                            )
                            raw_messages.append({
                                "direction": direction,
                                "text": txt,
                                "timeMarker": time_marker,
                                "source": "history_file",
                            })
            except Exception:
                pass

            # Secondary fallback from latest management report if no history file records were found
            if not raw_messages:
                try:
                    mgmt_path = Path(reports_dir_val) / "wechat_management_report.json"
                    if mgmt_path.is_file():
                        rep = json.loads(mgmt_path.read_text(encoding="utf-8"))
                        for sess in (rep.get("sessions") or []) if isinstance(rep, dict) else []:
                            if not isinstance(sess, dict) or sess.get("isFoldedFolder"):
                                continue
                            s_title = str(sess.get("fullTitle") or sess.get("listTitleSnippet") or "").strip()
                            if not _names_match(clean_target, s_title, aliases):
                                continue
                            if s_title and not matched_title:
                                matched_title = s_title
                            t_hint = _format_time_marker(sess.get("lastTimeHint"))
                            for vis in sess.get("visibleMessages") or []:
                                txt = _clean_text(vis)
                                if txt:
                                    raw_messages.append({
                                        "direction": "peer",
                                        "text": txt,
                                        "timeMarker": t_hint,
                                        "source": "live_report",
                                    })
                except Exception:
                    pass

        # 1b) Merge `engine.monitor` recent events & takeover state
        monitor = getattr(self.engine, "monitor", None)
        if monitor is not None:
            try:
                state_fn = getattr(monitor, "state_summary", None)
                if callable(state_fn):
                    st = state_fn()
                    contacts_map = (st.get("contacts") or {}) if isinstance(st, dict) else {}
                    for c_val in contacts_map.values():
                        if isinstance(c_val, dict) and _names_match(clean_target, str(c_val.get("target") or ""), aliases):
                            if c_val.get("takenOver"):
                                taken_over = True
                                takeover_reason = _clean_text(c_val.get("takeoverReason") or "")
                            break
            except Exception:
                pass

            events: List[Dict[str, Any]] = []
            try:
                rec_fn = getattr(monitor, "recent_events", None)
                if callable(rec_fn):
                    events = list(rec_fn(limit=80) or [])
                else:
                    status_fn = getattr(monitor, "get_status", None)
                    if callable(status_fn):
                        st = status_fn(event_limit=80)
                        if isinstance(st, dict):
                            events = list(st.get("recentEvents") or [])
            except Exception:
                events = []

            # `recent_events()` returns newest-first; iterate oldest-first for chronological merge
            for ev in reversed(events):
                if not isinstance(ev, dict):
                    continue
                ev_target = str(ev.get("target") or "").strip()
                if not _names_match(clean_target, ev_target, aliases):
                    continue
                if ev_target and not matched_title:
                    matched_title = ev_target
                ev_type = str(ev.get("event") or "").strip()
                if ev_type == "takeover" and ev.get("reason"):
                    taken_over = True
                    takeover_reason = _clean_text(ev.get("reason"))
                t_mark = _format_time_marker(ev.get("ts"))

                incoming = _clean_text(ev.get("incomingText") or (ev.get("draft") or {}).get("incoming") or "")
                reply = _clean_text(ev.get("replyText") or (ev.get("draft") or {}).get("reply") or "")
                if incoming:
                    raw_messages.append({
                        "direction": "peer",
                        "text": incoming,
                        "timeMarker": t_mark,
                        "source": f"monitor:{ev_type or 'event'}",
                    })
                if reply and ev_type in ("auto_reply_sent", "handoff_requested"):
                    raw_messages.append({
                        "direction": "self",
                        "text": reply,
                        "timeMarker": t_mark,
                        "source": f"monitor:{ev_type}",
                    })

        # Deduplicate preserving chronological order
        deduped: List[Dict[str, str]] = []
        seen_sigs: set[Tuple[str, str]] = set()
        for msg in raw_messages:
            norm_body = unicodedata.normalize("NFKC", _clean_text(msg["text"])).casefold()
            if not norm_body:
                continue
            sig = (msg["direction"], norm_body)
            if sig in seen_sigs:
                continue
            seen_sigs.add(sig)
            deduped.append(msg)

        return {
            "matchedTitle": matched_title,
            "totalCount": len(deduped),
            "messages": deduped[-max_messages:],
            "takenOver": taken_over,
            "takeoverReason": takeover_reason,
        }

    def _collect_soul_memory(
        self,
        clean_target: str,
        *,
        aliases: Sequence[str],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "ownerProfile": {},
            "contactProfile": None,
            "facts": [],
            "episodicEvents": [],
            "sharedContext": [],
            "rollingSummary": "",
            "totalMemories": 0,
        }
        profiler = getattr(self.engine, "soul_profiler", None)
        if profiler is None:
            return result

        contact_prof: Optional[Dict[str, Any]] = None
        try:
            get_prof = getattr(profiler, "get_profiles", None)
            if callable(get_prof):
                prof_res = get_prof(target=clean_target)
                if isinstance(prof_res, dict):
                    result["ownerProfile"] = dict(prof_res.get("ownerProfile") or {})
                    cps = list(prof_res.get("contactProfiles") or [])
                    if not cps and aliases:
                        for alias in aliases:
                            if alias:
                                alt = get_prof(target=alias)
                                if isinstance(alt, dict) and alt.get("contactProfiles"):
                                    cps = list(alt.get("contactProfiles") or [])
                                    break
                    for cp in cps:
                        if isinstance(cp, dict) and (
                            _names_match(clean_target, str(cp.get("matchedTitle") or ""), aliases)
                            or _names_match(clean_target, str(cp.get("target") or ""), aliases)
                        ):
                            contact_prof = dict(cp)
                            break
        except Exception:
            contact_prof = None

        mem_ctx: Dict[str, Any] = {}
        try:
            get_ctx = getattr(profiler, "get_contact_memory_context", None)
            if callable(get_ctx):
                ctx_res = get_ctx(clean_target)
                if isinstance(ctx_res, dict):
                    mem_ctx = ctx_res
                    if not result["ownerProfile"] and isinstance(ctx_res.get("ownerProfile"), dict):
                        result["ownerProfile"] = dict(ctx_res["ownerProfile"])
                    if contact_prof is None and isinstance(ctx_res.get("contactSoul"), dict):
                        contact_prof = dict(ctx_res["contactSoul"])
        except Exception:
            mem_ctx = {}

        if contact_prof is not None:
            result["contactProfile"] = contact_prof

        # Merge memories from both contactProfile and get_contact_memory_context (deduplicated)
        cp_mems = (contact_prof or {}).get("memories") or {}
        ctx_mems = mem_ctx.get("memories") or {}

        def _merge_mem_bucket(key: str, limit: int) -> List[Dict[str, Any]]:
            merged: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for bucket in (ctx_mems, cp_mems):
                for item in (bucket.get(key) or []) if isinstance(bucket, dict) else []:
                    if isinstance(item, dict):
                        content = _clean_text(item.get("content") or "")
                        entry = dict(item)
                    elif isinstance(item, str):
                        content = _clean_text(item)
                        entry = {"category": key, "content": content}
                    else:
                        continue
                    if not content or content.casefold() in seen:
                        continue
                    seen.add(content.casefold())
                    entry["content"] = content
                    merged.append(entry)
                    if len(merged) >= limit:
                        return merged
            return merged

        facts = _merge_mem_bucket("facts", 16)
        events = _merge_mem_bucket("episodicEvents", 20)
        shared = _merge_mem_bucket("sharedContext", 16)

        result["facts"] = facts
        result["episodicEvents"] = events
        result["sharedContext"] = shared
        result["rollingSummary"] = str(mem_ctx.get("rollingSummary") or "").strip()
        result["totalMemories"] = len(facts) + len(events) + len(shared)
        return result

    def _collect_moments(
        self,
        clean_target: str,
        *,
        aliases: Sequence[str],
        max_moments: int,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "authored": [],
            "interactedOnMine": [],
            "postsCount": 0,
            "mutualHits": 0,
            "matchedAuthor": "",
            "stats": {},
        }
        moments_hub = getattr(self.engine, "moments", None)
        if moments_hub is None:
            return result

        authored_raw: List[Dict[str, Any]] = []
        interacted_raw: List[Any] = []
        stats: Dict[str, Any] = {}

        get_for_contact = getattr(moments_hub, "get_posts_for_contact", None)
        use_list_fallback = not callable(get_for_contact)
        if callable(get_for_contact):
            try:
                res = get_for_contact(clean_target, limit=max_moments)
                if isinstance(res, dict) and res.get("ok") is not False:
                    authored_raw = [p for p in (res.get("authored") or []) if isinstance(p, dict)]
                    interacted_raw = list(res.get("interactedOnMine") or [])
                    if isinstance(res.get("stats"), dict):
                        stats = dict(res["stats"])
                if not authored_raw and not interacted_raw and aliases:
                    for alias in aliases:
                        if not alias:
                            continue
                        alt = get_for_contact(alias, limit=max_moments)
                        if isinstance(alt, dict) and alt.get("ok") is not False:
                            alt_auth = [p for p in (alt.get("authored") or []) if isinstance(p, dict)]
                            alt_int = list(alt.get("interactedOnMine") or [])
                            if alt_auth or alt_int:
                                authored_raw = alt_auth
                                interacted_raw = alt_int
                                if isinstance(alt.get("stats"), dict):
                                    stats = dict(alt["stats"])
                                break
            except NotImplementedError:
                use_list_fallback = True
            except Exception:
                authored_raw = []
                interacted_raw = []
        if use_list_fallback:
            list_posts = getattr(moments_hub, "list_posts", None)
            if callable(list_posts):
                try:
                    res = list_posts(author=clean_target, limit=max_moments)
                    if isinstance(res, dict) and res.get("ok") is not False:
                        authored_raw = [p for p in (res.get("posts") or []) if isinstance(p, dict)]
                    if not authored_raw and aliases:
                        for alias in aliases:
                            if not alias:
                                continue
                            alt = list_posts(author=alias, limit=max_moments)
                            if isinstance(alt, dict) and alt.get("posts"):
                                authored_raw = [p for p in alt["posts"] if isinstance(p, dict)]
                                break
                except Exception:
                    authored_raw = []

        # Exclude ads while preserving genuine authored posts
        authored = [p for p in authored_raw if not p.get("isAd")][:max_moments]
        matched_author = str(authored[0].get("author") or "").strip() if authored else ""

        # Count mutual hits (my likes/comments on their posts + their likes/comments on mine)
        hits_on_theirs = 0
        for p in authored:
            if p.get("likedByMe"):
                hits_on_theirs += 1
            if p.get("commentedByMe"):
                hits_on_theirs += 1

        hits_on_mine = 0
        for item in interacted_raw:
            if isinstance(item, dict):
                if "likedByContact" in item or "contactComments" in item:
                    if item.get("likedByContact"):
                        hits_on_mine += 1
                    hits_on_mine += len(item.get("contactComments") or [])
                elif "liked" in item or "likes" in item or "comments" in item:
                    matched_here = 1 if item.get("liked") else 0
                    for lk in item.get("likes") or []:
                        if _names_match(clean_target, str(lk), aliases):
                            matched_here += 1
                    for cm in item.get("comments") or []:
                        if isinstance(cm, dict) and (
                            not cm.get("author") or _names_match(clean_target, str(cm.get("author") or ""), aliases)
                        ):
                            matched_here += 1
                    hits_on_mine += max(1, matched_here)
                else:
                    hits_on_mine += 1
            elif item:
                hits_on_mine += 1

        # Reconcile with stats dict if provided by get_posts_for_contact or moments.stats()
        stats_hits = 0
        if stats:
            if isinstance(stats.get("mutualHits"), int) and int(stats["mutualHits"]) > 0:
                stats_hits = int(stats["mutualHits"])
            else:
                for k in ("likedByMe", "commentedByMe", "likedMyPosts", "commentedMyPosts", "interactionsTotal"):
                    val = stats.get(k)
                    if isinstance(val, int) and val > 0:
                        if k == "interactionsTotal":
                            stats_hits = max(stats_hits, val)
                        else:
                            stats_hits += val
        elif callable(getattr(moments_hub, "stats", None)):
            try:
                m_stats = moments_hub.stats(limit=60)
                for row in (m_stats.get("contacts") or []) if isinstance(m_stats, dict) else []:
                    if isinstance(row, dict) and _names_match(clean_target, str(row.get("author") or ""), aliases):
                        stats_hits = (
                            int(row.get("likedByMe") or 0)
                            + int(row.get("commentedByMe") or 0)
                            + int(row.get("likedMyPosts") or 0)
                            + int(row.get("commentedMyPosts") or 0)
                        )
                        break
            except Exception:
                pass

        mutual_hits = max(hits_on_theirs + hits_on_mine, stats_hits)

        result["authored"] = authored
        result["interactedOnMine"] = interacted_raw
        result["postsCount"] = len(authored)
        result["mutualHits"] = int(mutual_hits)
        result["matchedAuthor"] = matched_author
        result["stats"] = stats
        return result

    def _collect_crm(
        self,
        clean_target: str,
        *,
        aliases: Sequence[str],
    ) -> Dict[str, Any]:
        empty: Dict[str, Any] = {
            "hasRecord": False,
            "stage": "",
            "person": {},
            "metrics": {},
            "formulas": {},
            "timeline": [],
            "topDrafts": [],
        }
        sales_crm = getattr(self.engine, "sales_crm", None)
        if sales_crm is None:
            return empty
        analyze_fn = getattr(sales_crm, "analyze_contact", None)
        if not callable(analyze_fn):
            return empty

        candidates = [clean_target] + [str(a).strip() for a in aliases if str(a or "").strip()]
        for cand in candidates:
            try:
                res = analyze_fn(cand)
            except Exception:
                continue
            if isinstance(res, dict) and res.get("ok") is not False and isinstance(res.get("person"), dict):
                person = dict(res.get("person") or {})
                return {
                    "hasRecord": True,
                    "stage": str(person.get("stage") or ""),
                    "person": person,
                    "metrics": dict(res.get("metrics") or {}),
                    "formulas": dict(res.get("formulas") or {}),
                    "timeline": list(res.get("timeline") or []),
                    "topDrafts": list(res.get("topDrafts") or []),
                }
        return empty

    # ------------------------------------------------------------------
    # Deterministic Zero-Hallucination Baseline Brief Builder
    # ------------------------------------------------------------------

    def _build_baseline_brief(
        self,
        *,
        target: str,
        matched_title: str,
        goal: str,
        goal_label: str,
        custom_goal: str,
        data_coverage: Dict[str, Any],
        binding: Optional[Dict[str, Any]],
        contact_profile: Optional[Dict[str, Any]],
        chat_data: Dict[str, Any],
        soul_data: Dict[str, Any],
        moments_data: Dict[str, Any],
        crm_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        messages = list(chat_data.get("messages") or [])
        soul_cp = soul_data.get("contactProfile") or {}
        facts = list(soul_data.get("facts") or [])
        events = list(soul_data.get("episodicEvents") or [])
        shared = list(soul_data.get("sharedContext") or [])
        authored_posts = list(moments_data.get("authored") or [])
        interacted_mine = list(moments_data.get("interactedOnMine") or [])
        crm_person = crm_data.get("person") or {}
        crm_metrics = crm_data.get("metrics") or {}
        crm_formulas = crm_data.get("formulas") or {}
        crm_timeline = list(crm_data.get("timeline") or [])

        is_cold_start = (
            data_coverage["chatMessages"] == 0
            and data_coverage["momentsPosts"] == 0
            and data_coverage["momentsMutualHits"] == 0
            and data_coverage["soulMemories"] == 0
            and not data_coverage["hasCrmRecord"]
            and binding is None
            and contact_profile is None
        )

        # Signal scan over real text
        peer_texts = [m["text"] for m in messages if m.get("direction") == "peer"]
        all_msg_texts = [m["text"] for m in messages]
        combined_text = "\n".join(all_msg_texts + [str(f.get("content") or "") for f in facts])
        has_price_signal = any(k in combined_text for k in _PRICE_HINTS)
        has_delivery_signal = any(k in combined_text for k in _DELIVERY_HINTS)
        has_friction_signal = any(k in "\n".join(peer_texts[-6:]) for k in _FRICTION_HINTS)
        has_positive_signal = any(k in "\n".join(peer_texts[-6:]) for k in _POSITIVE_HINTS)

        # ---- 1. summaryCard ----
        one_liner = self._build_one_liner(
            matched_title=matched_title,
            goal=goal,
            goal_label=goal_label,
            is_cold_start=is_cold_start,
            binding=binding,
            contact_profile=contact_profile,
            soul_cp=soul_cp,
            crm_data=crm_data,
            data_coverage=data_coverage,
        )

        temperament = self._build_temperament_style(
            is_cold_start=is_cold_start,
            soul_cp=soul_cp,
            contact_profile=contact_profile,
        )

        emotional_tone = self._build_emotional_tone(
            is_cold_start=is_cold_start,
            soul_cp=soul_cp,
            contact_profile=contact_profile,
            has_friction_signal=has_friction_signal,
            has_positive_signal=has_positive_signal,
        )

        dos, donts = self._build_dos_and_donts(
            matched_title=matched_title,
            goal=goal,
            goal_label=goal_label,
            custom_goal=custom_goal,
            is_cold_start=is_cold_start,
            soul_cp=soul_cp,
            contact_profile=contact_profile,
            binding=binding,
            chat_data=chat_data,
            moments_data=moments_data,
            crm_data=crm_data,
        )

        # ---- 2. momentsInsights (strictly grounded) ----
        moments_insights = self._build_moments_insights(
            matched_title=matched_title,
            authored_posts=authored_posts,
            interacted_mine=interacted_mine,
            mutual_hits=data_coverage["momentsMutualHits"],
        )

        # ---- 3. needsAndFocus ----
        needs_and_focus = self._build_needs_and_focus(
            matched_title=matched_title,
            is_cold_start=is_cold_start,
            messages=messages,
            binding=binding,
            contact_profile=contact_profile,
            soul_cp=soul_cp,
            facts=facts,
            events=events,
            shared=shared,
            chat_data=chat_data,
            crm_data=crm_data,
            has_price_signal=has_price_signal,
            has_delivery_signal=has_delivery_signal,
            has_friction_signal=has_friction_signal,
        )

        # ---- 4. historyHighlights (max 8) ----
        history_highlights = self._build_history_highlights(
            messages=messages,
            events=events,
            rolling_summary=str(soul_data.get("rollingSummary") or ""),
            crm_timeline=crm_timeline,
        )

        # ---- 5. phoneScripts ----
        phone_scripts = self._build_phone_scripts(
            matched_title=matched_title,
            goal=goal,
            goal_label=goal_label,
            custom_goal=custom_goal,
            is_cold_start=is_cold_start,
            messages=messages,
            moments_insights=moments_insights,
            needs_and_focus=needs_and_focus,
            crm_data=crm_data,
            binding=binding,
            has_price_signal=has_price_signal,
            has_delivery_signal=has_delivery_signal,
            has_friction_signal=has_friction_signal,
        )

        return {
            "ok": True,
            "target": target,
            "matchedTitle": matched_title,
            "generatedAt": _utc_iso_now(),
            "goal": goal,
            "goalLabel": goal_label,
            "usedLlm": False,
            "modelId": "",
            "llmFallbackReason": "use_llm=false",
            "dataCoverage": data_coverage,
            "summaryCard": {
                "oneLiner": one_liner,
                "temperamentAndStyle": temperament,
                "emotionalTone": emotional_tone,
                "dos": dos,
                "donts": donts,
            },
            "momentsInsights": moments_insights,
            "needsAndFocus": needs_and_focus,
            "historyHighlights": history_highlights,
            "phoneScripts": phone_scripts,
        }

    @staticmethod
    def _build_one_liner(
        *,
        matched_title: str,
        goal: str,
        goal_label: str,
        is_cold_start: bool,
        binding: Optional[Dict[str, Any]],
        contact_profile: Optional[Dict[str, Any]],
        soul_cp: Dict[str, Any],
        crm_data: Dict[str, Any],
        data_coverage: Dict[str, Any],
    ) -> str:
        if is_cold_start:
            return (
                f"「{matched_title}」暂无本地聊天、朋友圈或 CRM 历史沉淀，本次按「{goal_label}」温和破冰建档即可。"
            )
        tags: List[str] = []
        care_label = str((soul_cp or {}).get("careLevelLabel") or (contact_profile or {}).get("careLevelLabel") or "")
        if care_label and care_label != "普通会话":
            tags.append(care_label)
        elif binding and binding.get("role"):
            tags.append(str(binding["role"]))
        if soul_cp.get("personalityTag"):
            tags.append(str(soul_cp["personalityTag"]))
        elif contact_profile and contact_profile.get("friendStyleTag"):
            tags.append(str(contact_profile["friendStyleTag"]))

        clauses: List[str] = [f"围绕「{goal_label}」展开通话"]
        if crm_data.get("hasRecord"):
            stage = crm_data.get("stage") or "跟进中"
            sig = (crm_data.get("metrics") or {}).get("signalLevel") or ""
            clauses.append(f"CRM 处于「{stage}」" + (f"（{sig}）" if sig else ""))
        elif data_coverage["chatMessages"] > 0:
            clauses.append(f"已汇集 {data_coverage['chatMessages']} 条历史往来")
        if data_coverage["momentsPosts"] > 0:
            clauses.append(f"有 {data_coverage['momentsPosts']} 条近期朋友圈可作切入点")

        prefix = f"{matched_title}（{' · '.join(tags[:2])}）" if tags else matched_title
        return f"{prefix}：{'，'.join(clauses)}。"

    @staticmethod
    def _build_temperament_style(
        *,
        is_cold_start: bool,
        soul_cp: Dict[str, Any],
        contact_profile: Optional[Dict[str, Any]],
    ) -> str:
        if is_cold_start:
            return "暂无历史语料画像；开场前 30 秒先顺着对方语速和寒暄程度匹配节奏，不急于长篇输出。"
        parts: List[str] = []
        if soul_cp.get("personalityTag"):
            parts.append(str(soul_cp["personalityTag"]))
        if soul_cp.get("mbtiEstimate"):
            parts.append(f"倾向 {soul_cp['mbtiEstimate']}")
        if soul_cp.get("communicationPreferences"):
            parts.append(str(soul_cp["communicationPreferences"]))
        elif contact_profile and contact_profile.get("styleSummary"):
            parts.append(str(contact_profile["styleSummary"]))
        if not parts:
            return "性格与沟通偏好样本较少，建议先短句确认对方当前时间是否方便再深入聊。"
        return "；".join(parts)

    @staticmethod
    def _build_emotional_tone(
        *,
        is_cold_start: bool,
        soul_cp: Dict[str, Any],
        contact_profile: Optional[Dict[str, Any]],
        has_friction_signal: bool,
        has_positive_signal: bool,
    ) -> str:
        if is_cold_start:
            return "中性友善 · 首次沟通待观察"
        base = str(soul_cp.get("emotionalBaseline") or "").strip()
        warmth = soul_cp.get("warmthScore") or (contact_profile or {}).get("warmthScore")
        rapport = soul_cp.get("rapportScore")
        suffix_parts: List[str] = []
        if has_friction_signal:
            suffix_parts.append("近期消息含顾虑/卡点情绪，宜先共情降温")
        elif has_positive_signal:
            suffix_parts.append("近期互动反馈偏积极")
        if warmth is not None:
            suffix_parts.append(f"热度 {warmth}/100")
        if rapport is not None:
            suffix_parts.append(f"默契度 {rapport}/100")
        if base and suffix_parts:
            return f"{base}（{'；'.join(suffix_parts)}）"
        if base:
            return base
        if suffix_parts:
            return "；".join(suffix_parts)
        return "平和友好"

    @staticmethod
    def _build_dos_and_donts(
        *,
        matched_title: str,
        goal: str,
        goal_label: str,
        custom_goal: str,
        is_cold_start: bool,
        soul_cp: Dict[str, Any],
        contact_profile: Optional[Dict[str, Any]],
        binding: Optional[Dict[str, Any]],
        chat_data: Dict[str, Any],
        moments_data: Dict[str, Any],
        crm_data: Dict[str, Any],
    ) -> Tuple[List[str], List[str]]:
        dos: List[str] = []
        donts: List[str] = []

        if is_cold_start:
            dos = [
                f"开场先报名字并说明来意（围绕「{goal_label}」），确认 {matched_title} 现在方便接电话",
                "多用开放式短问句了解近况与真实需求，自己少说多听",
                "挂断前口头确认一条轻量后续动作，并在通话后补充联系人备注",
            ]
            donts = [
                "切勿假装记得未发生过的聊天约定或朋友圈内容",
                "避免一上来念稿式推销，先建立轻松对话节奏",
            ]
            return dos, donts

        if soul_cp.get("communicationPreferences"):
            dos.append(str(soul_cp["communicationPreferences"]))
        if contact_profile and contact_profile.get("bestContactWindow"):
            dos.append(f"优先留意对方活跃窗口：{contact_profile['bestContactWindow']}")
        if moments_data.get("postsCount", 0) > 0:
            dos.append("可用近期真实朋友圈内容做 10 秒自然破冰，拉近熟人感")
        if chat_data.get("takenOver"):
            dos.append("该会话此前已由人工接管，通话时可直接承接并敲定最终结论")

        goal_dos = {
            "quote": "先复核对方最看重的交付节点与效果标准，再分档讲清报价与优惠边界",
            "recovery": "先完整倾听并复述对方的具体困扰，再给出可落地的补救时间表",
            "care": "以关心近况和分享有用小线索为主，保持松弛不压迫",
            "followup": "顺着上一次聊到的未闭环话题自然续聊，顺便确认下一步节奏",
            "custom": f"紧扣本次自定义目标推进：{custom_goal or goal_label}",
            "general": "先同步重点关切，控制在 2~3 个核心问题内高效对齐",
        }
        dos.append(goal_dos.get(goal, goal_dos["general"]))

        if binding and binding.get("notes"):
            dos.append(f"牢记绑定备注：{str(binding['notes'])[:80]}")

        if soul_cp.get("taboosAndBoundaries"):
            donts.append(str(soul_cp["taboosAndBoundaries"]))
        if crm_data.get("hasRecord") and (crm_data.get("person") or {}).get("isStagnant"):
            donts.append("当前商机处于停滞状态，切忌机械催单，需先问清真正卡点")
        goal_donts = {
            "quote": "需求与决策人未确认前，勿过早一次性交出全部底价",
            "recovery": "切忌急于解释辩白或把责任推给流程/系统",
            "care": "客情维系通话避免生硬转入报价或硬性转化",
            "followup": "勿连续追问多个问题给对方造成审讯感",
            "custom": "避免偏离本次设定的自定义通话主线",
            "general": "不要照本宣科念长句，保持口语停顿与回应感",
        }
        donts.append(goal_donts.get(goal, goal_donts["general"]))
        donts.append("严禁提及或编造未经核实的聊天/朋友圈细节")

        return _dedupe_strings(dos, limit=5), _dedupe_strings(donts, limit=4)

    @staticmethod
    def _build_moments_insights(
        *,
        matched_title: str,
        authored_posts: List[Dict[str, Any]],
        interacted_mine: List[Any],
        mutual_hits: int,
    ) -> Dict[str, Any]:
        recent_posts: List[Dict[str, Any]] = []
        for post in authored_posts[:12]:
            recent_posts.append({
                "key": str(post.get("key") or ""),
                "timeText": str(post.get("timeText") or ""),
                "publishedEstimate": post.get("publishedEstimate"),
                "text": str(post.get("text") or ""),
                "attachments": [str(a) for a in (post.get("attachments") or []) if str(a or "").strip()],
                "source": str(post.get("source") or ""),
                "likesCount": len(post.get("likes") or []),
                "commentsCount": len(post.get("comments") or []),
                "likedByMe": bool(post.get("likedByMe")),
                "commentedByMe": bool(post.get("commentedByMe")),
            })

        if not recent_posts and not interacted_mine:
            return {
                "summary": (
                    f"暂未读取到「{matched_title}」的朋友圈动态，本次不凭空编造动态内容；"
                    "如需用朋友圈破冰，可先前往「朋友圈」页刷新读取后再生成。"
                ),
                "icebreakers": [],
                "recentPosts": [],
            }

        icebreakers: List[str] = []
        for post in recent_posts[:3]:
            t_label = f"（{post['timeText']}）" if post["timeText"] else ""
            body = _clean_text(post["text"])
            atts = post["attachments"]
            if body:
                snippet = _speech_friendly_hook(body, max_len=28)
                icebreakers.append(f"刚想起你之前发的那条「{snippet}」{t_label}，最近这块进展怎么样？")
            elif atts:
                att_s = atts[0][:26] + ("…" if len(atts[0]) > 26 else "")
                icebreakers.append(f"前两天看你转发了「{att_s}」{t_label}，挺有意思的，你最近也在看这方面吗？")

        if interacted_mine and len(icebreakers) < 3:
            icebreakers.append(f"前阵子还看到你在我朋友圈互动过，一直没顾上细聊，正好今天电话打声招呼。")

        if recent_posts:
            latest = recent_posts[0]
            latest_t = latest["timeText"] or "近期"
            preview = _clean_text(latest["text"] or " / ".join(latest["attachments"]))[:36]
            summary = (
                f"已读取 {len(recent_posts)} 条近期动态（最近一条：{latest_t}"
                + (f"，「{preview}」" if preview else "")
                + f"），双方互赞/互评累计 {mutual_hits} 次。"
            )
        else:
            summary = (
                f"暂未读取到「{matched_title}」自己发布的新动态，但对方近期在你的朋友圈互动过 "
                f"{len(interacted_mine)} 次（互赞/互评合计 {mutual_hits} 次），整体关系热度在线。"
            )

        return {
            "summary": summary,
            "icebreakers": _dedupe_strings(icebreakers, limit=4),
            "recentPosts": recent_posts,
        }

    @staticmethod
    def _build_needs_and_focus(
        *,
        matched_title: str,
        is_cold_start: bool,
        messages: List[Dict[str, str]],
        binding: Optional[Dict[str, Any]],
        contact_profile: Optional[Dict[str, Any]],
        soul_cp: Dict[str, Any],
        facts: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        shared: List[Dict[str, Any]],
        chat_data: Dict[str, Any],
        crm_data: Dict[str, Any],
        has_price_signal: bool,
        has_delivery_signal: bool,
        has_friction_signal: bool,
    ) -> Dict[str, Any]:
        core_needs: List[str] = []
        focus_topics: List[str] = []
        open_loops: List[str] = []

        if has_price_signal:
            core_needs.append("关注方案价格区间、预算匹配度与优惠空间")
        if has_delivery_signal:
            core_needs.append("关注演示/试用排期与最终交付上线时间节点")
        if has_friction_signal:
            core_needs.append("存在待澄清的顾虑或体验卡点，需要明确答复与兜底安排")

        for f in facts[:5]:
            c = _clean_text(f.get("content") or "")
            if not c or "微信号账号标识" in c:
                continue
            core_needs.append(c)
        if binding and binding.get("notes"):
            core_needs.append(f"客户备注：{str(binding['notes'])[:80]}")

        if not core_needs:
            if is_cold_start:
                core_needs = [f"暂无历史需求记录，本次重点倾听「{matched_title}」当前的实际业务/个人诉求"]
            else:
                core_needs = ["保持信息同步，确认近期核心诉求与配合优先级"]

        # Focus topics
        raw_topics: List[str] = []
        for src_list in (
            soul_cp.get("coreTopics") or [],
            (contact_profile or {}).get("contentCategories") or [],
            (crm_data.get("person") or {}).get("tags") or [],
            (binding or {}).get("careTags") or [],
        ):
            for t in src_list:
                ts = _clean_text(t)
                if ts and ts not in _GENERIC_TOPIC_LABELS:
                    raw_topics.append(ts)
        for sh in shared[:4]:
            sc = _clean_text(sh.get("content") or "")
            if sc:
                raw_topics.append(sc[:42])
        if not raw_topics:
            raw_topics = ["近期近况破冰", "核心需求确认"] if is_cold_start else ["日常沟通主线"]
        focus_topics = _dedupe_strings(raw_topics, limit=6)

        # Open loops
        if chat_data.get("takenOver"):
            reason = chat_data.get("takeoverReason") or "待人工直接确认"
            open_loops.append(f"会话处于人工接管状态（{reason}），可在电话中直接拍板闭环")

        # Check last few messages for unanswered questions or commitments
        for m in reversed(messages[-8:]):
            txt = m["text"]
            if m["direction"] == "peer" and ("?" in txt or "？" in txt or "吗" in txt or any(h in txt for h in _COMMITMENT_HINTS)):
                open_loops.append(f"对方待回应/待确认：{txt[:64]}")
                if len(open_loops) >= 3:
                    break
            elif m["direction"] == "self" and any(h in txt for h in _COMMITMENT_HINTS):
                open_loops.append(f"我方曾约定/提及：{txt[:64]}")
                if len(open_loops) >= 3:
                    break

        for ev in events[:3]:
            ec = _clean_text(ev.get("content") or "")
            if ec and any(h in ec for h in _COMMITMENT_HINTS):
                open_loops.append(f"记忆事件({ev.get('timeMarker') or '近期'})：{ec[:64]}")

        if crm_data.get("hasRecord"):
            p = crm_data.get("person") or {}
            if p.get("followUpBeijing"):
                open_loops.append(f"CRM 预约跟进时间：{p['followUpBeijing']}")
            if p.get("isStagnant"):
                open_loops.append("CRM 标记商机有停滞风险，需确认阻塞原因")

        if not open_loops:
            if is_cold_start:
                open_loops = ["暂无历史未闭环事项（首次建档通话，挂断后建议记录后续跟进节点）"]
            else:
                open_loops = ["暂未发现明确逾期事项，通话中顺手确认下一步合作/联系节奏即可"]

        # CRM hint
        if crm_data.get("hasRecord"):
            p = crm_data.get("person") or {}
            m = crm_data.get("metrics") or {}
            f = crm_data.get("formulas") or {}
            action_obj = f.get("salesAction") or {}
            parts = [f"当前 CRM 阶段「{p.get('stage') or '跟进中'}」"]
            if m.get("signalLevel"):
                parts.append(f"意向信号：{m['signalLevel']}")
            if action_obj.get("action"):
                reason = str(action_obj.get("reason") or "").strip()
                parts.append(f"动作建议：{action_obj['action']}" + (f"（{reason}）" if reason else ""))
            if float(p.get("dealValue") or 0.0) > 0:
                parts.append(f"预计金额：{p['dealValue']:.0f}")
            if p.get("followUpBeijing"):
                parts.append(f"计划跟进：{p['followUpBeijing']}")
            crm_hint = "；".join(parts) + "。"
        else:
            crm_hint = "尚未纳入 SalesCRM 商机流水线；若本次沟通确认有明确合作/采购意向，可在「客户跟进」一键建档并设定回访提醒。"

        return {
            "coreNeeds": _dedupe_strings(core_needs, limit=5),
            "focusTopics": focus_topics,
            "openLoops": _dedupe_strings(open_loops, limit=5),
            "crmHint": crm_hint,
        }

    @staticmethod
    def _build_history_highlights(
        *,
        messages: List[Dict[str, str]],
        events: List[Dict[str, Any]],
        rolling_summary: str,
        crm_timeline: List[Dict[str, Any]],
    ) -> List[str]:
        items: List[str] = []
        for m in messages[-8:]:
            who = "我方" if m.get("direction") == "self" else "对方"
            t = m.get("timeMarker") or ""
            tag = f"{who} · {t}" if t else who
            items.append(f"[{tag}] {m['text'][:90]}")

        if len(items) < 8 and rolling_summary:
            for line in rolling_summary.splitlines():
                clean_ln = line.lstrip("- ").strip()
                if clean_ln:
                    items.append(clean_ln[:90])

        if len(items) < 8:
            for ev in events[:5]:
                ec = _clean_text(ev.get("content") or "")
                tm = _clean_text(ev.get("timeMarker") or "")
                if ec:
                    items.append(f"[{tm or '记忆'}] {ec[:88]}")

        if len(items) < 8:
            for tl in crm_timeline[:4]:
                if isinstance(tl, dict):
                    label = _clean_text(tl.get("title") or tl.get("label") or "CRM进展")
                    detail = _clean_text(tl.get("detail") or "")
                    if detail:
                        items.append(f"[CRM · {label}] {detail[:80]}")

        return _dedupe_strings(items, limit=8)

    @staticmethod
    def _build_phone_scripts(
        *,
        matched_title: str,
        goal: str,
        goal_label: str,
        custom_goal: str,
        is_cold_start: bool,
        messages: List[Dict[str, str]],
        moments_insights: Dict[str, Any],
        needs_and_focus: Dict[str, Any],
        crm_data: Dict[str, Any],
        binding: Optional[Dict[str, Any]],
        has_price_signal: bool,
        has_delivery_signal: bool,
        has_friction_signal: bool,
    ) -> Dict[str, Any]:
        icebreakers = list(moments_insights.get("icebreakers") or [])
        last_peer = next((m["text"] for m in reversed(messages) if m.get("direction") == "peer"), "")
        last_hook = _speech_friendly_hook(last_peer, max_len=28) if last_peer else ""
        moments_hook = icebreakers[0] if icebreakers else ""

        # Opening
        if goal == "quote":
            if last_hook:
                opening = (
                    f"喂 {matched_title}，你好呀，我是这边负责对接的。刚整理完咱们之前聊到的「{last_hook}」，"
                    "特意电话花两三分钟帮您对一下具体方案档位和交付时间，现在方便接听吗？"
                )
            else:
                opening = (
                    f"喂 {matched_title}，你好呀，现在方便聊两分钟吗？我把方案版本和报价明细理顺了，"
                    "想直接跟您电话核对下核心需求，免得微信里发大段文字看不过来。"
                )
        elif goal == "recovery":
            opening = (
                f"喂 {matched_title}，实在不好意思打扰您两分钟，我是专门来跟进您这边遇到的问题的。"
                "文字里怕没把您的真实顾虑听全，您现在方便的话，我想当面在电话里听您详细说说卡在哪儿。"
            )
        elif goal == "care":
            if moments_hook:
                opening = f"喂 {matched_title}，在忙吗？{moments_hook} 这几天忙得顺不顺呀，顺便打个电话问候一声。"
            else:
                opening = (
                    f"喂 {matched_title}，最近忙不忙呀？这阵子没怎么语音聊，今天正好想起您，打个电话问候下近况，顺便看看最近有没有能搭把手的。"
                )
        elif goal == "followup":
            if moments_hook:
                opening = f"喂 {matched_title}，方便聊两分钟吗？{moments_hook} 另外也顺便跟您对一下咱们上一轮聊到的事情最新进展。"
            elif last_hook:
                opening = f"喂 {matched_title}，你好呀～上次微信聊到「{last_hook}」，怕文字说不清楚，电话里花一分钟跟您确认下最新进度。"
            else:
                opening = f"喂 {matched_title}，你好呀，我是这边跟进项目的。今天打个电话主要跟您同步下近期进展，看您现在方便聊两分钟吗？"
        elif goal == "custom":
            goal_phrase = custom_goal or goal_label
            opening = (
                f"喂 {matched_title}，你好呀，现在方便聊两分钟吗？今天电话主要是想跟您专门沟通「{goal_phrase}」，"
                "先把重点节奏对清楚。"
            )
        else:  # general
            if is_cold_start:
                opening = (
                    f"喂 {matched_title}，你好呀，方便聊两分钟吗？这次主要是想先电话认识沟通一下，了解一下您目前最看重的事情和需求节奏。"
                )
            elif moments_hook:
                opening = f"喂 {matched_title}，方便聊两分钟吗？{moments_hook} 另外今天也正好电话跟您把最近要对接的事顺一下。"
            elif last_hook:
                opening = f"喂 {matched_title}，你好呀，顺着咱们前几天聊到的「{last_hook}」，电话里花两分钟快速帮您把后续安排对齐下。"
            else:
                opening = f"喂 {matched_title}，最近挺忙吧？今天打电话是想花两三分钟和您快速对齐一下近况和接下来的安排，现在方便吗？"

        # Discovery questions
        if goal == "quote":
            questions = [
                "如果按你们团队/业务的实际规模，这一期最核心必须先跑通的 1~2 个场景是什么？",
                "预算和审批流程上，老板或决策方最关心的是投入产出比、交付周期还是售后保障？",
                "假设这周内定下来，您理想中的上线或内部演示节点大概在什么时间？",
            ]
        elif goal == "recovery":
            questions = [
                "就目前已经出现的环节，最让您觉得别扭或耽误事的是哪一步？",
                "您心目中最理想的解决结果和最晚能接受的恢复时间是什么？",
                "除了当前这个卡点，前面还有没有其他让您不太放心的细节一并告诉我？",
            ]
        elif goal == "care":
            questions = [
                "最近工作和生活节奏怎么样，这一阶段主要重心放在哪一块？",
                "之前咱们聊过或用过的东西，现在日常还顺手吗，有没有需要微调的地方？",
                "接下来一两周如果我有相关的行业信息或小工具资料，您更喜欢我发摘要还是直接拉个短会？",
            ]
        elif goal == "followup":
            questions = [
                "上次咱们提到的那件事，您这边内部沟通完目前到哪一步了？",
                "接下来推进过程中，现在最需要我先补齐哪份材料或配合哪一块？",
                "这周大概什么时候方便再碰一次结论，我提前把时间空出来？",
            ]
        elif goal == "custom":
            goal_phrase = custom_goal or goal_label
            questions = [
                f"围绕「{goal_phrase}」这件事，您目前最关心、最想先拍板的核心指标是什么？",
                "现在推进这件事还缺哪些前提条件、资料或内部协调动作？",
                "咱们期望在什么时间点看到第一个阶段性结果？",
            ]
        else:
            questions = [
                "您近期这边最优先推进的事情是什么，有没有时间上比较赶的节点？",
                "目前方案或配合方式里，哪一块最符合您的预期，哪一块还希望调整？",
                "接下来一周如果您需要我这边配合，最先落实哪一件小事最有帮助？",
            ]

        if is_cold_start and goal == "general":
            questions = [
                "您这边目前最核心想解决的问题或近期重点目标大概是什么？",
                "平时跟进对接，您更习惯微信文字同步还是关键节点直接短电话沟通？",
                "这周方便的话，我可以先按您的需求整理一版简洁参考给您看看，您主要看重哪几项？",
            ]

        # Objection handlers
        handlers: List[Dict[str, str]] = []
        if has_price_signal or goal == "quote":
            handlers.append({
                "concern": "觉得价格偏高或超出当前一期预算",
                "response": "非常理解预算把控！咱们可以先不一步到位全上，我帮您拆成基础落地版和进阶扩展版两档，先用核心模块把本周演示和业务闭环跑出来，成本能压下来很多。",
            })
        if has_delivery_signal or goal in ("quote", "followup"):
            handlers.append({
                "concern": "担心交付周期来不及、怕耽误老板/团队演示",
                "response": "时间节点我帮您兜底：今天挂电话后我先把可立即演示的核心部分和排期表发您，明天先做一轮内部预演，保证不耽误下周正式汇报。",
            })
        if has_friction_signal or goal == "recovery":
            handlers.append({
                "concern": "对之前响应速度、细节稳定度有顾虑",
                "response": "这块确实是我们该盯紧的，不找借口。今天起由我这边直接单点兜底跟进，给您一个明确的修复确认时间点，没验证稳妥前不让您反复折腾。",
            })

        if goal == "care":
            handlers.extend([
                {
                    "concern": "客气说「最近一切都挺好，不用麻烦」",
                    "response": "那就太好了！您忙您的，我就打声招呼放心了，有需要随时微信喊我一声就行。",
                },
                {
                    "concern": "说最近特别忙、出差或家里事多顾不上",
                    "response": "理解理解，那我不占您时间了！您先忙手头正事，回头方便了咱们再约个轻松时间喝杯茶/聊几句。",
                },
            ])
        elif goal == "custom":
            goal_phrase = custom_goal or goal_label
            handlers.extend([
                {
                    "concern": f"暂时还没想好怎么推进「{goal_phrase}」",
                    "response": f"没关系，我先根据今天聊到的情况整理 2 个轻量备选方案发您微信，您挑一个看着顺眼的，咱们再细化。",
                },
                {
                    "concern": "担心现在推进太耗精力或需要内部对齐",
                    "response": "我尽量把准备工作都在我这边先做完，做成一页纸结论发您，您转发给相关同事确认一下就行，不额外增加您工作量。",
                },
            ])
        else:
            if len(handlers) < 2:
                handlers.extend([
                    {
                        "concern": "说「现在不太方便，先微信发我看看吧」",
                        "response": "好的没问题，不打扰您忙！我挂了电话就把今天要对齐的 3 条要点发您微信，您忙完抽空回我个数字就行。",
                    },
                    {
                        "concern": "表示还在内部评估或对比其他方案",
                        "response": "完全应该多对比几家才踏实！您可以重点看下部署成本和后期维护省不省心，我顺手整理一份对比清单发您供参考。",
                    },
                ])

        # Closing
        if goal == "quote":
            closing = (
                f"那咱们就这么定，{matched_title}：我挂了电话把分档报价和下周演示提纲发您微信，您看明天下午方便简单确认下选哪一档吗？不打扰您忙，先这样！"
            )
        elif goal == "recovery":
            closing = (
                f"感谢您跟我把话说透，{matched_title}。我马上按咱们刚对齐的方案处理，最晚今天下班前给您回一个明确结果，有进展第一时间微信同步您。"
            )
        elif goal == "care":
            closing = (
                f"好的 {matched_title}，听到您这边一切顺利就踏实了，您先忙，后面得空了咱们再随时联系！"
            )
        elif goal == "followup":
            closing = (
                f"行，那 {matched_title} 您先忙，我把今天聊的结论发一条短备忘到微信里，咱们按约定时间再对齐下一步，拜拜！"
            )
        elif goal == "custom":
            goal_phrase = custom_goal or goal_label
            closing = (
                f"好勒 {matched_title}，围绕「{goal_phrase}」的下一步我就按刚聊的先动起来，整理完马上微信发您确认，先不打扰您！"
            )
        else:
            closing = (
                f"好的 {matched_title}，今天非常清楚了！我把刚才对齐的要点发您微信备忘，有变化随时喊我，祝您今天工作顺利！"
            )

        return {
            "opening": opening,
            "discoveryQuestions": _dedupe_strings(questions, limit=5),
            "objectionHandlers": handlers[:4],
            "closing": closing,
        }

    # ------------------------------------------------------------------
    # Optional LLM Synthesis & Strict Safe Merge
    # ------------------------------------------------------------------

    def _enhance_with_llm(
        self,
        *,
        brief: Dict[str, Any],
        target: str,
        matched_title: str,
        goal: str,
        goal_label: str,
        custom_goal: str,
        binding: Optional[Dict[str, Any]],
        contact_profile: Optional[Dict[str, Any]],
        chat_data: Dict[str, Any],
        soul_data: Dict[str, Any],
        moments_data: Dict[str, Any],
        crm_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        models = getattr(self.engine, "models", None)
        if models is None:
            brief["usedLlm"] = False
            brief["modelId"] = ""
            brief["llmFallbackReason"] = "models_unavailable"
            return brief

        try:
            enabled = bool(models.is_llm_enabled())
        except Exception as exc:
            brief["usedLlm"] = False
            brief["modelId"] = ""
            brief["llmFallbackReason"] = f"models_check_failed: {exc}"
            return brief

        if not enabled:
            brief["usedLlm"] = False
            brief["modelId"] = ""
            brief["llmFallbackReason"] = "llm_disabled"
            return brief

        # Build sanitized, compact 5-way context (no secrets, no local file paths)
        soul_cp = soul_data.get("contactProfile") or {}
        compact_context = {
            "target": target,
            "matchedTitle": matched_title,
            "goal": goal,
            "goalLabel": goal_label,
            "customGoal": custom_goal,
            "dataCoverage": brief["dataCoverage"],
            "binding": {
                "role": (binding or {}).get("role") or "",
                "alias": (binding or {}).get("alias") or "",
                "careLevel": (binding or {}).get("careLevel") or "",
                "careTags": list((binding or {}).get("careTags") or []),
                "notes": _redact_for_llm((binding or {}).get("notes") or "")[:160],
            } if binding else None,
            "contactAnalytics": {
                "friendStyleTag": (contact_profile or {}).get("friendStyleTag") or "",
                "warmthScore": (contact_profile or {}).get("warmthScore"),
                "bestContactWindow": (contact_profile or {}).get("bestContactWindow") or "",
                "contentCategories": list((contact_profile or {}).get("contentCategories") or []),
            } if contact_profile else None,
            "soulProfile": {
                "personalityTag": soul_cp.get("personalityTag") or "",
                "mbtiEstimate": soul_cp.get("mbtiEstimate") or "",
                "psychologicalSummary": _redact_for_llm(soul_cp.get("psychologicalSummary") or "")[:200],
                "communicationPreferences": _redact_for_llm(soul_cp.get("communicationPreferences") or "")[:160],
                "emotionalBaseline": soul_cp.get("emotionalBaseline") or "",
                "taboosAndBoundaries": _redact_for_llm(soul_cp.get("taboosAndBoundaries") or "")[:160],
                "coreTopics": list(soul_cp.get("coreTopics") or [])[:6],
            } if soul_cp else None,
            "memories": {
                "facts": [_redact_for_llm(m.get("content") or "")[:100] for m in (soul_data.get("facts") or [])[:6]],
                "episodicEvents": [_redact_for_llm(m.get("content") or "")[:100] for m in (soul_data.get("episodicEvents") or [])[:6]],
                "sharedContext": [_redact_for_llm(m.get("content") or "")[:100] for m in (soul_data.get("sharedContext") or [])[:5]],
                "rollingSummary": _redact_for_llm(soul_data.get("rollingSummary") or "")[:260],
            },
            "recentChat": [
                {
                    "who": "我方" if m.get("direction") == "self" else "对方",
                    "time": m.get("timeMarker") or "",
                    "text": _redact_for_llm(m.get("text") or "")[:140],
                }
                for m in (chat_data.get("messages") or [])[-16:]
            ],
            "moments": [
                {
                    "timeText": p.get("timeText") or "",
                    "text": _redact_for_llm(p.get("text") or "")[:140],
                    "attachments": [_redact_for_llm(a)[:60] for a in (p.get("attachments") or [])[:2]],
                    "likedByMe": bool(p.get("likedByMe")),
                    "commentedByMe": bool(p.get("commentedByMe")),
                }
                for p in (moments_data.get("authored") or [])[:8]
            ],
            "momentsMutualHits": int(moments_data.get("mutualHits") or 0),
            "crm": {
                "stage": crm_data.get("stage") or "",
                "signalLevel": (crm_data.get("metrics") or {}).get("signalLevel") or "",
                "dealValue": (crm_data.get("person") or {}).get("dealValue") or 0,
                "followUpBeijing": (crm_data.get("person") or {}).get("followUpBeijing") or "",
                "isStagnant": bool((crm_data.get("person") or {}).get("isStagnant")),
                "salesAction": ((crm_data.get("formulas") or {}).get("salesAction") or {}).get("action") or "",
                "note": _redact_for_llm((crm_data.get("person") or {}).get("note") or "")[:140],
                "timeline": [
                    f"{tl.get('title') or ''}: {_redact_for_llm(tl.get('detail') or '')[:80]}"
                    for tl in (crm_data.get("timeline") or [])[:4]
                    if isinstance(tl, dict)
                ],
            } if crm_data.get("hasRecord") else None,
        }

        system_prompt = (
            "你是一位资深人脉与销售通话参谋。请严格基于提供的真实上下文，为号主生成【人工打电话前速览与口语话术提词卡】。\n"
            "【铁律】\n"
            "1. 绝对不得编造输入中没有的聊天记录、朋友圈动态、价格数字或约定；输入为空的维度要如实保留保守/破冰建议。\n"
            "2. 电话话术必须像真人打电话一样自然口语、简短有温度，绝不直接念出 http/https 网址，严禁出现 AI 腔或长篇书面体。\n"
            "3. 请简短思考并直接输出精简合法 JSON 对象（不要额外解释，每个列表 2~4 条、每条简明扼要），包含以下键：\n"
            '{"summaryCard":{"oneLiner":"...","temperamentAndStyle":"...","emotionalTone":"...","dos":["..."],"donts":["..."]},'
            '"momentsInsights":{"summary":"...","icebreakers":["..."]},'
            '"needsAndFocus":{"coreNeeds":["..."],"focusTopics":["..."],"openLoops":["..."],"crmHint":"..."},'
            '"historyHighlights":["..."],'
            '"phoneScripts":{"opening":"...","discoveryQuestions":["..."],"objectionHandlers":[{"concern":"...","response":"..."}],"closing":"..."}}'
        )
        user_prompt = (
            f"请为联系人「{matched_title}」生成通话目标为「{goal_label}」的电话前速览 JSON。\n"
            "注意：当 moments 数组为空且 momentsMutualHits 为 0 时，momentsInsights.icebreakers 必须为空数组 []；"
            "当 recentChat 与 memories 均为空时，historyHighlights 必须为空数组 []。\n"
            f"真实上下文数据：\n{json.dumps(compact_context, ensure_ascii=False)}"
        )

        try:
            res = models.generate_chat_reply(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                contact_name=target,
                temperature=0.35,
                max_tokens=4096,
                timeout=35.0,
            )
        except Exception as exc:
            brief["usedLlm"] = False
            brief["modelId"] = ""
            brief["llmFallbackReason"] = f"llm_exception: {exc}"
            return brief

        if not isinstance(res, dict) or not res.get("ok"):
            err = str((res or {}).get("error") or "llm_reply_failed") if isinstance(res, dict) else "invalid_llm_response"
            brief["usedLlm"] = False
            brief["modelId"] = str((res or {}).get("modelId") or "") if isinstance(res, dict) else ""
            brief["llmFallbackReason"] = f"llm_failed: {err}"
            return brief

        model_id = str(res.get("modelId") or "").strip()
        raw_reply = str(res.get("replyText") or "")
        parsed = _extract_json_object(raw_reply)
        if not isinstance(parsed, dict):
            brief["usedLlm"] = False
            brief["modelId"] = model_id
            brief["llmFallbackReason"] = "invalid_llm_json"
            return brief

        applied = self._merge_llm_fields(brief, parsed)
        if applied == 0:
            brief["usedLlm"] = False
            brief["modelId"] = model_id
            brief["llmFallbackReason"] = "empty_llm_payload"
            return brief

        brief["usedLlm"] = True
        brief["modelId"] = model_id
        brief["llmFallbackReason"] = ""
        return brief

    @staticmethod
    def _merge_llm_fields(brief: Dict[str, Any], parsed: Dict[str, Any]) -> int:
        """Safely validate & merge LLM JSON sections onto baseline; returns count of fields updated."""
        updated = 0
        cov = brief["dataCoverage"]
        has_moments = (cov["momentsPosts"] > 0) or (cov["momentsMutualHits"] > 0)
        has_history = (cov["chatMessages"] > 0) or (cov["soulMemories"] > 0) or bool(cov["hasCrmRecord"])

        # summaryCard
        sc_in = parsed.get("summaryCard")
        if isinstance(sc_in, dict):
            sc_out = brief["summaryCard"]
            for key in ("oneLiner", "temperamentAndStyle", "emotionalTone"):
                val = sc_in.get(key)
                if isinstance(val, str) and val.strip():
                    sc_out[key] = _clean_text(val)
                    updated += 1
            for list_key, cap in (("dos", 5), ("donts", 4)):
                raw_list = sc_in.get(list_key)
                if isinstance(raw_list, list):
                    cleaned = _dedupe_strings([x for x in raw_list if isinstance(x, str)], limit=cap)
                    if cleaned:
                        sc_out[list_key] = cleaned
                        updated += 1

        # momentsInsights (never overwrite real `recentPosts`; never invent icebreakers if 0 moments)
        mi_in = parsed.get("momentsInsights")
        if isinstance(mi_in, dict):
            mi_out = brief["momentsInsights"]
            if has_moments:
                if isinstance(mi_in.get("summary"), str) and mi_in["summary"].strip():
                    mi_out["summary"] = _clean_text(mi_in["summary"])
                    updated += 1
                if isinstance(mi_in.get("icebreakers"), list):
                    cleaned_ice = _dedupe_strings(
                        [x for x in mi_in["icebreakers"] if isinstance(x, str)],
                        limit=4,
                    )
                    if cleaned_ice:
                        mi_out["icebreakers"] = cleaned_ice
                        updated += 1

        # needsAndFocus
        nf_in = parsed.get("needsAndFocus")
        if isinstance(nf_in, dict):
            nf_out = brief["needsAndFocus"]
            for list_key, cap in (("coreNeeds", 5), ("focusTopics", 6), ("openLoops", 5)):
                raw_list = nf_in.get(list_key)
                if isinstance(raw_list, list):
                    cleaned = _dedupe_strings([x for x in raw_list if isinstance(x, str)], limit=cap)
                    if cleaned:
                        nf_out[list_key] = cleaned
                        updated += 1
            if isinstance(nf_in.get("crmHint"), str) and nf_in["crmHint"].strip():
                nf_out["crmHint"] = _clean_text(nf_in["crmHint"])
                updated += 1

        # historyHighlights (only when local records exist; max 8)
        hh_in = parsed.get("historyHighlights")
        if has_history and isinstance(hh_in, list):
            normalized_hh: List[str] = []
            for item in hh_in:
                if isinstance(item, str) and item.strip():
                    normalized_hh.append(item)
                elif isinstance(item, dict):
                    summary = _clean_text(item.get("summary") or item.get("text") or item.get("content") or "")
                    tm = _clean_text(item.get("time") or item.get("timeMarker") or "")
                    if summary:
                        normalized_hh.append(f"[{tm}] {summary}" if tm else summary)
            cleaned_hh = _dedupe_strings(normalized_hh, limit=8)
            if cleaned_hh:
                brief["historyHighlights"] = cleaned_hh
                updated += 1

        # phoneScripts
        ps_in = parsed.get("phoneScripts")
        if isinstance(ps_in, dict):
            ps_out = brief["phoneScripts"]
            for key in ("opening", "closing"):
                val = ps_in.get(key)
                if isinstance(val, str) and val.strip():
                    cleaned_script = _URL_IN_TEXT_RE.sub("之前发过来的链接", _clean_text(val))
                    ps_out[key] = _clean_text(cleaned_script)
                    updated += 1
            if isinstance(ps_in.get("discoveryQuestions"), list):
                cleaned_q = _dedupe_strings(
                    [x for x in ps_in["discoveryQuestions"] if isinstance(x, str)],
                    limit=5,
                )
                if cleaned_q:
                    ps_out["discoveryQuestions"] = cleaned_q
                    updated += 1
            if isinstance(ps_in.get("objectionHandlers"), list):
                valid_handlers: List[Dict[str, str]] = []
                for h in ps_in["objectionHandlers"]:
                    if not isinstance(h, dict):
                        continue
                    concern = _clean_text(h.get("concern") or "")
                    response = _clean_text(h.get("response") or "")
                    if concern and response:
                        valid_handlers.append({"concern": concern, "response": response})
                if valid_handlers:
                    ps_out["objectionHandlers"] = valid_handlers[:4]
                    updated += 1

        return updated
