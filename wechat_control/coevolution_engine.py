"""Dual-Product Co-Evolution Engine (Bot Studio VLSE Bot <-> WeChatBot RPA).

Makes peer-to-peer bot sparring (`微信ClawBot` / `openbot`) and human conversations a
continuous mutual-growth loop across both product layers:

1. Cognitive Layer (`Bot Studio / VLSE Bot`):
   - Evaluates every outbound reply on 5 concrete human-likeness checks (`0-100`).
   - Detects peer feedback on tone/roboticness ("你是AI", "一二三点", "截断", "看不到")
     and adapts `@god-core/persona-sdk` 16-partition trait weights per contact.
   - Distills multimodal takeaways (`[链接深读:]`, `[图片识别:]`, `[视频识别:]`,
     `[视频号深读:]`, `[公众号文章深读:]`) into FTS5 (`source="coevolution-sparring"`).

2. Execution Layer (`WeChatBot RPA`):
   - Collects per-contact RPA telemetry (zero-switch popout rate, card click-to-open
     success, multimodal coverage across links/images/videos/cards, send verification rate).
   - Auto-tunes per-contact perception settings (`dhashThreshold`, `preferClickToOpen`)
     when media cards or rapid bursts are observed.
   - Appends structured training tuples to `logs/coevolution_corpus.jsonl` and syncs a
     shared cross-product artifact (`botstudio_coevolution_sync.json`) so both WeChatBot
     RPA and Bot Studio (VLSE Bot) co-evolve together.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .humanizer_affect import OFFICIAL_WECHAT_EMOJIS
from .io_utils import atomic_write_json
from .safety import normalize_chat_name


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_MODAL_SLOP_RE = re.compile(
    r"(?:哈哈+收到|收到你说的啦|总的来说|简单来说|结合已解析的内容要点|为您(?:说明|确认|梳理|总结)|哒[～~!！]?)"
)
_ENUM_SLOP_RE = re.compile(
    r"(?:(?:第[一二三四五六七八九十]+[点步条个]?|首先|其次|再次|最后|一方面|另一方面)[，、:：\s]|(?:^|[\s，。；])[1-9]\d?\s*[\.、\)）]\s+)"
)
_WECHAT_EMOTE_RE = re.compile(r"\[[\u4e00-\u9fffA-Za-z0-9]{1,6}\]")

_NOTE_PREFIX_KIND_MAP: Tuple[Tuple[str, str], ...] = (
    ("[链接深读:", "link"),
    ("[图片识别:", "image"),
    ("[视频识别:", "video"),
    ("[视频号深读:", "channels_video"),
    ("[公众号文章深读:", "wechat_article"),
    ("[元宝深读:", "wechat_ai"),
    ("[小微深读:", "wechat_ai"),
)


def evaluate_turn_human_likeness(reply_text: str, incoming_text: str = "") -> Dict[str, Any]:
    """Score a generated WeChat reply (0..100) across five de-AI human-likeness criteria."""
    text = str(reply_text or "").strip()
    incoming = str(incoming_text or "").strip()
    issues: List[str] = []

    no_enum = not bool(_ENUM_SLOP_RE.search(text))
    if not no_enum:
        issues.append("contains_list_enumeration")

    no_slop = not bool(_MODAL_SLOP_RE.search(text))
    if not no_slop:
        issues.append("contains_ai_modal_slop")

    stiff_punct = bool(
        text.endswith("。")
        or any(ch in text for ch in ("「", "」", "『", "』", "《", "》", "；"))
    )
    natural_punct = not stiff_punct
    if not natural_punct:
        issues.append("stiff_punctuation_or_trailing_period")

    char_len = len(text)
    conversational_len = 6 <= char_len <= 145
    if not conversational_len:
        issues.append("reply_too_short_or_too_long")

    has_emote = any(
        tag in OFFICIAL_WECHAT_EMOJIS
        for tag in re.findall(r"\[([^\[\]\s:：]{1,6})\]", text)
    )
    shared_tokens = {
        tok
        for tok in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2}", incoming)
        if tok in text
    }
    grounded = bool(has_emote or len(shared_tokens) >= 1 or char_len >= 16)
    if not grounded:
        issues.append("low_context_grounding")

    score = (
        (25 if no_enum else 0)
        + (25 if no_slop else 0)
        + (20 if natural_punct else 0)
        + (15 if conversational_len else 0)
        + (15 if grounded else 0)
    )
    grade = "S" if score >= 95 else ("A" if score >= 80 else ("B" if score >= 60 else "C"))
    return {
        "humanLikenessScore": score,
        "grade": grade,
        "issues": issues,
        "metrics": {
            "noEnumeration": no_enum,
            "noModalSlop": no_slop,
            "naturalPunctuation": natural_punct,
            "conversationalLength": conversational_len,
            "contextualGrounding": grounded,
            "hasWeChatEmote": has_emote,
        },
    }


def _classify_media_notes(media_notes: List[str]) -> List[Dict[str, str]]:
    parsed: List[Dict[str, str]] = []
    for raw in media_notes or []:
        s = str(raw or "").strip()
        if not s:
            continue
        modality = "other"
        for prefix, mtype in _NOTE_PREFIX_KIND_MAP:
            if s.startswith(prefix):
                modality = mtype
                break
        head, _, body = s.partition("]")
        title = head.split(":", 1)[-1].strip() if ":" in head else head.lstrip("[").strip()
        summary = body.strip() or s
        if modality != "other":
            parsed.append({
                "modality": modality,
                "title": title[:64] or modality,
                "summary": summary[:320],
                "rawNote": s[:420],
            })
    return parsed


def extract_peer_coevolution_signals(
    target: str,
    incoming_text: str,
    reply_text: str,
    *,
    media_notes: Optional[List[str]] = None,
    send_receipt: Optional[Dict[str, Any]] = None,
    popout_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Derive style adaptations, multimodal knowledge items, and RPA tuning deltas from one turn."""
    norm_in = str(incoming_text or "").strip()
    cf_in = norm_in.casefold()
    notes_list = [str(n or "").strip() for n in (media_notes or []) if str(n or "").strip()]
    multimodal_items = _classify_media_notes(notes_list)

    partition_deltas: Dict[str, Dict[str, float]] = {}
    style_rules: List[str] = []
    critique_flags: List[str] = []

    if any(k in cf_in for k in ("你是ai", "机器人", "套路", "模板", "一二三", "官腔", "客服")):
        critique_flags.append("peer_called_out_ai_tone")
        partition_deltas["语言组织"] = {"自然口语": 0.72, "简洁直接": 0.28}
        partition_deltas["表现欲"] = {"自嘲解围": 0.65, "不事修饰": 0.35}
        partition_deltas["幽默手法"] = {"冷面幽默": 0.60, "轻快俏皮": 0.40}
        style_rules.append("被调侃AI或套路时直接口语接梗或轻微自嘲，严禁分点解释")

    if any(k in cf_in for k in ("截断", "缺半截", "太长", "看不完")):
        critique_flags.append("peer_reported_truncation")
        partition_deltas["语言组织"] = {"简洁直接": 0.70, "自然口语": 0.30}
        style_rules.append("控制单条回复紧凑可读，代码或长方案给出完整可运行短版")

    media_blind_spot = any(k in cf_in for k in ("看不到", "没读到", "403", "点进去", "没打开"))
    if media_blind_spot:
        critique_flags.append("peer_probed_media_access")
        style_rules.append("遇到文章/视频卡片先点开阅读再答要点，受限时坦诚说明抓取边界不硬编")

    rpa_info = send_receipt if isinstance(send_receipt, dict) else {}
    p_meta = popout_meta if isinstance(popout_meta, dict) else {}
    used_zero_switch = bool(p_meta.get("zeroSwitch") or p_meta.get("popoutWindowID"))
    send_ok = bool(rpa_info.get("ok") and rpa_info.get("status") in ("sent", "preview", "dry_run"))
    send_verified = bool(rpa_info.get("ok") and rpa_info.get("status") == "sent")

    rpa_tuning: Dict[str, Any] = {}
    if multimodal_items or media_blind_spot:
        rpa_tuning["preferClickToOpen"] = True
        rpa_tuning["dhashThreshold"] = 2
    if used_zero_switch:
        rpa_tuning["preferPopoutWindow"] = True

    return {
        "target": str(target or "").strip(),
        "critiqueFlags": critique_flags,
        "partitionDeltas": partition_deltas,
        "styleRules": style_rules,
        "multimodalItems": multimodal_items,
        "mediaBlindSpot": media_blind_spot,
        "rpaTelemetry": {
            "zeroSwitch": used_zero_switch,
            "sendOk": send_ok,
            "sendVerified": send_verified,
            "modalitiesRead": [item["modality"] for item in multimodal_items],
        },
        "rpaTuning": rpa_tuning,
    }


class DualProductCoevolutionEngine:
    """Persists continuous co-evolution state for Bot Studio (VLSE Bot) and WeChatBot RPA."""

    def __init__(
        self,
        *,
        state_path: Path,
        corpus_path: Optional[Path] = None,
        knowledge_store: Optional[Any] = None,
        sync_path: Optional[Path] = None,
        botstudio_work_dir: Optional[Path] = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.corpus_path = Path(corpus_path) if corpus_path else (self.state_path.parent / "coevolution_corpus.jsonl")
        self.sync_path = Path(sync_path) if sync_path else (self.state_path.parent / "botstudio_coevolution_sync.json")
        default_work = Path.home() / "Library" / "Application Support" / "CodexWorkbench" / "spaces" / "bot_wechat_ecosystem" / "work"
        self.botstudio_work_dir = Path(botstudio_work_dir) if botstudio_work_dir else default_work
        self.knowledge_store = knowledge_store
        self._lock = threading.RLock()
        self._state = self._load_state()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "schema": "openbot.dual-coevolution/1",
            "updatedAt": _utc_iso_now(),
            "vlseBotLayer": {
                "totalTurns": 0,
                "scoreSum": 0,
                "avgHumanLikenessScore": 0.0,
                "distilledKnowledgeCount": 0,
                "distilledDigests": [],
                "evolvedRulesCount": 0,
            },
            "wechatRpaLayer": {
                "totalTurns": 0,
                "zeroSwitchTurns": 0,
                "zeroSwitchRate": 0.0,
                "sendVerifiedTurns": 0,
                "sendVerifyRate": 0.0,
                "multimodalDeepReadTotal": 0,
                "multimodalByKind": {
                    "link": 0,
                    "image": 0,
                    "video": 0,
                    "channels_video": 0,
                    "wechat_article": 0,
                    "wechat_ai": 0,
                },
                "cardClickOpens": 0,
            },
            "contacts": {},
            "recentTurns": [],
        }

    def _load_state(self) -> Dict[str, Any]:
        if self.state_path.is_file():
            try:
                raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("schema") == "openbot.dual-coevolution/1":
                    base = self._default_state()
                    for k in ("vlseBotLayer", "wechatRpaLayer"):
                        if isinstance(raw.get(k), dict):
                            base[k].update(raw[k])
                    if isinstance(raw.get("contacts"), dict):
                        base["contacts"] = raw["contacts"]
                    if isinstance(raw.get("recentTurns"), list):
                        base["recentTurns"] = raw["recentTurns"][-30:]
                    base["updatedAt"] = raw.get("updatedAt") or base["updatedAt"]
                    return base
            except Exception:
                pass
        return self._default_state()

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state["updatedAt"] = _utc_iso_now()
        atomic_write_json(self.state_path, self._state, newline=False)

    def _append_corpus(self, row: Dict[str, Any]) -> None:
        self.corpus_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.corpus_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _distill_multimodal_knowledge(
        self,
        target: str,
        items: List[Dict[str, str]],
        incoming_text: str,
    ) -> int:
        if not self.knowledge_store or not items:
            return 0
        added = 0
        seen = list(self._state["vlseBotLayer"].get("distilledDigests") or [])
        seen_set = set(seen)
        for item in items:
            modality = item["modality"]
            if modality == "wechat_ai":
                continue
            title = f"对聊深读({target}) · {item['title'][:34]}"
            body = f"[{modality}] {item['summary']}"
            if incoming_text:
                body = f"来源提问: {incoming_text[:80]}\n{body}"
            digest = hashlib.sha1(f"{target}|{modality}|{item['title']}|{item['summary'][:80]}".encode("utf-8")).hexdigest()[:16]
            if digest in seen_set:
                continue
            try:
                self.knowledge_store.save_entry(
                    title=title,
                    body=body[:500],
                    kind="knowledge",
                    library="shared",
                    keywords=[target, modality, item["title"][:20]],
                    source="coevolution-sparring",
                    external=True,
                    status="published",
                )
                seen.append(digest)
                seen_set.add(digest)
                added += 1
            except Exception:
                continue
        self._state["vlseBotLayer"]["distilledDigests"] = seen[-200:]
        self._state["vlseBotLayer"]["distilledKnowledgeCount"] = int(
            self._state["vlseBotLayer"].get("distilledKnowledgeCount") or 0
        ) + added
        return added

    def record_sparring_turn(
        self,
        *,
        target: str,
        incoming_text: str,
        reply_text: str,
        persona_id: str = "warm-friend",
        generation_mode: str = "",
        model_used: str = "",
        media_notes: Optional[List[str]] = None,
        dispatched_receipt: Optional[Dict[str, Any]] = None,
        send_receipt: Optional[Dict[str, Any]] = None,
        popout_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record one live or preview sparring turn and update both VLSE Bot and WeChatBot RPA."""
        clean_target = str(target or "").strip() or "unknown"
        norm_key = normalize_chat_name(clean_target).casefold() or clean_target.casefold()
        quality = evaluate_turn_human_likeness(reply_text, incoming_text)
        signals = extract_peer_coevolution_signals(
            clean_target,
            incoming_text,
            reply_text,
            media_notes=media_notes,
            send_receipt=send_receipt,
            popout_meta=popout_meta,
        )

        with self._lock:
            vlse = self._state["vlseBotLayer"]
            rpa = self._state["wechatRpaLayer"]
            contacts = self._state["contacts"]
            c_rec = contacts.get(norm_key)
            if not isinstance(c_rec, dict):
                c_rec = {
                    "target": clean_target,
                    "turns": 0,
                    "avgHumanLikenessScore": 0.0,
                    "scoreSum": 0,
                    "partitionOverrides": {},
                    "styleRules": [],
                    "multimodalCounts": {},
                    "rpaTuning": {"preferPopoutWindow": False, "preferClickToOpen": True, "dhashThreshold": 4},
                    "lastModelUsed": "",
                    "lastUpdatedAt": "",
                }
                contacts[norm_key] = c_rec

            # 1) Update VLSE Bot layer metrics
            vlse["totalTurns"] = int(vlse.get("totalTurns") or 0) + 1
            vlse["scoreSum"] = int(vlse.get("scoreSum") or 0) + int(quality["humanLikenessScore"])
            vlse["avgHumanLikenessScore"] = round(vlse["scoreSum"] / max(1, vlse["totalTurns"]), 1)

            c_rec["turns"] = int(c_rec.get("turns") or 0) + 1
            c_rec["scoreSum"] = int(c_rec.get("scoreSum") or 0) + int(quality["humanLikenessScore"])
            c_rec["avgHumanLikenessScore"] = round(c_rec["scoreSum"] / max(1, c_rec["turns"]), 1)
            c_rec["lastModelUsed"] = str(model_used or c_rec.get("lastModelUsed") or "")
            c_rec["lastUpdatedAt"] = _utc_iso_now()

            if signals["partitionDeltas"]:
                po = dict(c_rec.get("partitionOverrides") or {})
                for part_name, trait_map in signals["partitionDeltas"].items():
                    po[part_name] = dict(trait_map)
                c_rec["partitionOverrides"] = po

            if signals["styleRules"]:
                existing_rules = list(c_rec.get("styleRules") or [])
                for rule in signals["styleRules"]:
                    if rule not in existing_rules:
                        existing_rules.append(rule)
                c_rec["styleRules"] = existing_rules[-8:]

            vlse["evolvedRulesCount"] = sum(
                len((v or {}).get("styleRules") or []) for v in contacts.values() if isinstance(v, dict)
            )

            distilled_added = self._distill_multimodal_knowledge(
                clean_target,
                signals["multimodalItems"],
                incoming_text,
            )

            # 2) Update WeChatBot RPA training telemetry
            rpa_tel = signals["rpaTelemetry"]
            rpa["totalTurns"] = int(rpa.get("totalTurns") or 0) + 1
            if rpa_tel["zeroSwitch"]:
                rpa["zeroSwitchTurns"] = int(rpa.get("zeroSwitchTurns") or 0) + 1
            rpa["zeroSwitchRate"] = round(100.0 * rpa["zeroSwitchTurns"] / max(1, rpa["totalTurns"]), 1)
            if rpa_tel["sendVerified"]:
                rpa["sendVerifiedTurns"] = int(rpa.get("sendVerifiedTurns") or 0) + 1
            rpa["sendVerifyRate"] = round(100.0 * rpa["sendVerifiedTurns"] / max(1, rpa["totalTurns"]), 1)

            by_kind = dict(rpa.get("multimodalByKind") or {})
            c_mm = dict(c_rec.get("multimodalCounts") or {})
            for item in signals["multimodalItems"]:
                mod = item["modality"]
                by_kind[mod] = int(by_kind.get(mod) or 0) + 1
                c_mm[mod] = int(c_mm.get(mod) or 0) + 1
                rpa["multimodalDeepReadTotal"] = int(rpa.get("multimodalDeepReadTotal") or 0) + 1
            rpa["multimodalByKind"] = by_kind
            c_rec["multimodalCounts"] = c_mm

            if isinstance(dispatched_receipt, dict):
                tasks = dispatched_receipt.get("tasks") or []
                if any(isinstance(t, dict) and t.get("clickedToOpen") for t in tasks):
                    rpa["cardClickOpens"] = int(rpa.get("cardClickOpens") or 0) + 1

            if signals["rpaTuning"]:
                tuning = dict(c_rec.get("rpaTuning") or {})
                tuning.update(signals["rpaTuning"])
                c_rec["rpaTuning"] = tuning

            turn_record = {
                "ts": _utc_iso_now(),
                "target": clean_target,
                "personaId": persona_id,
                "generationMode": generation_mode,
                "modelUsed": model_used,
                "incomingPreview": str(incoming_text or "")[:120],
                "replyPreview": str(reply_text or "")[:140],
                "humanLikenessScore": quality["humanLikenessScore"],
                "grade": quality["grade"],
                "issues": quality["issues"],
                "critiqueFlags": signals["critiqueFlags"],
                "modalitiesRead": rpa_tel["modalitiesRead"],
                "distilledKnowledgeAdded": distilled_added,
                "zeroSwitch": rpa_tel["zeroSwitch"],
                "sendVerified": rpa_tel["sendVerified"],
            }
            recent = list(self._state.get("recentTurns") or [])
            recent.append(turn_record)
            self._state["recentTurns"] = recent[-25:]
            self._save_state()

            try:
                self._append_corpus({
                    **turn_record,
                    "incomingText": str(incoming_text or ""),
                    "replyText": str(reply_text or ""),
                    "mediaNotes": list(media_notes or [])[:6],
                    "partitionOverrides": c_rec.get("partitionOverrides") or {},
                    "rpaTuning": c_rec.get("rpaTuning") or {},
                })
            except Exception:
                pass

            self._write_cross_product_sync_locked()

        return {
            "ok": True,
            "turn": turn_record,
            "quality": quality,
            "signals": signals,
            "summary": self.get_summary(),
        }

    def _write_cross_product_sync_locked(self) -> Dict[str, Any]:
        payload = {
            "schema": "openbot.dual-coevolution-sync/1",
            "syncedAt": _utc_iso_now(),
            "vlseBotLayer": dict(self._state["vlseBotLayer"]),
            "wechatRpaLayer": dict(self._state["wechatRpaLayer"]),
            "contacts": {
                k: {
                    "target": v.get("target"),
                    "turns": v.get("turns"),
                    "avgHumanLikenessScore": v.get("avgHumanLikenessScore"),
                    "styleRules": v.get("styleRules") or [],
                    "partitionOverrides": v.get("partitionOverrides") or {},
                    "multimodalCounts": v.get("multimodalCounts") or {},
                    "rpaTuning": v.get("rpaTuning") or {},
                }
                for k, v in (self._state.get("contacts") or {}).items()
                if isinstance(v, dict)
            },
            "recentTurns": list(self._state.get("recentTurns") or [])[-8:],
        }
        try:
            self.sync_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.sync_path, payload, newline=False)
        except Exception:
            pass
        mirrored = False
        if self.botstudio_work_dir.is_dir():
            try:
                atomic_write_json(self.botstudio_work_dir / "coevolution_sync.json", payload, newline=False)
                mirrored = True
            except Exception:
                pass
        return {
            "ok": True,
            "syncPath": str(self.sync_path),
            "botStudioMirrored": mirrored,
            "botStudioWorkDir": str(self.botstudio_work_dir),
            "syncedAt": payload["syncedAt"],
        }

    def sync_to_botstudio(self) -> Dict[str, Any]:
        """Explicitly flush cross-product co-evolution state for Bot Studio (VLSE Bot) & WeChatBot RPA."""
        with self._lock:
            self._save_state()
            return self._write_cross_product_sync_locked()

    def get_contact_partition_overrides(self, target: str) -> Optional[Dict[str, Any]]:
        """Return learned `@god-core/persona-sdk` partition overrides for a contact, if any."""
        norm_key = normalize_chat_name(target or "").casefold()
        with self._lock:
            rec = (self._state.get("contacts") or {}).get(norm_key)
            if isinstance(rec, dict) and isinstance(rec.get("partitionOverrides"), dict) and rec["partitionOverrides"]:
                return {"partitions": dict(rec["partitionOverrides"])}
        return None

    def get_contact_style_rules(self, target: str) -> List[str]:
        """Return learned humanization style rules derived from peer critiques for a contact."""
        norm_key = normalize_chat_name(target or "").casefold()
        with self._lock:
            rec = (self._state.get("contacts") or {}).get(norm_key)
            if isinstance(rec, dict) and isinstance(rec.get("styleRules"), list):
                return [str(r) for r in rec["styleRules"] if str(r).strip()]
        return []

    def get_contact_rpa_tuning(self, target: str) -> Dict[str, Any]:
        """Return adaptive RPA tuning flags learned from peer conversations for a contact."""
        norm_key = normalize_chat_name(target or "").casefold()
        with self._lock:
            rec = (self._state.get("contacts") or {}).get(norm_key)
            if isinstance(rec, dict) and isinstance(rec.get("rpaTuning"), dict):
                return dict(rec["rpaTuning"])
        return {"preferPopoutWindow": False, "preferClickToOpen": True, "dhashThreshold": 4}

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            vlse = dict(self._state["vlseBotLayer"])
            vlse.pop("distilledDigests", None)
            rpa = dict(self._state["wechatRpaLayer"])
            contacts_out = {}
            for k, v in (self._state.get("contacts") or {}).items():
                if not isinstance(v, dict):
                    continue
                contacts_out[k] = {
                    "target": v.get("target"),
                    "turns": v.get("turns", 0),
                    "avgHumanLikenessScore": v.get("avgHumanLikenessScore", 0.0),
                    "styleRulesCount": len(v.get("styleRules") or []),
                    "styleRules": list(v.get("styleRules") or []),
                    "partitionOverridesCount": len(v.get("partitionOverrides") or {}),
                    "multimodalCounts": dict(v.get("multimodalCounts") or {}),
                    "rpaTuning": dict(v.get("rpaTuning") or {}),
                    "lastModelUsed": v.get("lastModelUsed") or "",
                    "lastUpdatedAt": v.get("lastUpdatedAt") or "",
                }
            return {
                "ok": True,
                "schema": self._state.get("schema"),
                "updatedAt": self._state.get("updatedAt"),
                "statePath": str(self.state_path),
                "corpusPath": str(self.corpus_path),
                "syncPath": str(self.sync_path),
                "vlseBotLayer": vlse,
                "wechatRpaLayer": rpa,
                "contacts": contacts_out,
                "recentTurns": list(self._state.get("recentTurns") or [])[-12:],
            }
