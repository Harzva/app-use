"""Zero-FDE corpus discovery, owner inference, and batch archive import engine."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .bridge_importer import TranscriptBundle, WeChatBridgeImporter, validate_zip_member_name
from .safety import normalize_chat_name

# System, official, folder, and non-customer WeChat session titles to filter out.
SYSTEM_ACCOUNT_EXACT: frozenset[str] = frozenset({
    "公众号",
    "服务号",
    "订阅号",
    "微信团队",
    "腾讯新闻",
    "微信支付",
    "微信运动",
    "文件传输助手",
    "折叠的群聊",
    "折叠置顶聊天",
    "折叠的聊天",
    "折叠",
    "qq邮箱提醒",
    "微信游戏",
    "微信安全中心",
    "腾讯客服",
    "企业微信通知",
    "朋友推荐消息",
    "群收款",
    "语音记事本",
    "视频号",
    "朋友圈",
    "漂流瓶",
    "摇一摇",
})

SYSTEM_ACCOUNT_SUBSTRINGS: Tuple[str, ...] = (
    "公众号",
    "服务号",
    "订阅号",
    "微信团队",
    "腾讯新闻",
    "微信支付",
    "微信运动",
    "折叠置顶",
    "折叠的群",
    "折叠的聊天",
    "文件传输助手",
    "微信安全中心",
    "腾讯客服",
    "qq邮箱提醒",
)

SALES_SIGNAL_KEYWORDS: Tuple[str, ...] = (
    "询价",
    "报价",
    "多少钱",
    "预算",
    "方案",
    "合同",
    "试用",
    "下单",
    "发货",
    "交付",
    "售后",
    "优惠",
    "对比",
    "效果",
    "合作",
    "预约",
    "买",
)

DEFAULT_SEARCH_DIRS: Tuple[Path, ...] = (
    Path.home() / "Downloads",
    Path.home() / "Desktop",
)

_GROUP_SUFFIX_RE = re.compile(r"\s*[\(（]\d+[\)）]\s*$")
_CHAT_LOG_NAME_RE = re.compile(r"聊天记录", re.IGNORECASE)


def _norm_contact_key(name: Any) -> str:
    """Normalize a WeChat contact or session name for deduplication and matching."""
    raw = str(name or "").strip()
    if not raw:
        return ""
    stripped = _GROUP_SUFFIX_RE.sub("", raw).strip()
    return normalize_chat_name(stripped).casefold()


def _display_contact_name(name: Any) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    stripped = _GROUP_SUFFIX_RE.sub("", raw).strip()
    return normalize_chat_name(stripped) or stripped


def _is_system_or_service_account(title: str, session_meta: Optional[Dict[str, Any]] = None) -> bool:
    """Return True if the session represents a WeChat system, official, or folder entry."""
    if session_meta and bool(session_meta.get("enteredFolder")):
        return True
    norm = _norm_contact_key(title)
    if not norm:
        return True
    if norm in SYSTEM_ACCOUNT_EXACT:
        return True
    for marker in SYSTEM_ACCOUNT_SUBSTRINGS:
        if marker in norm:
            return True
    return False


def _parse_iso_ts(raw: Any) -> Optional[float]:
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
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$", text)
    if m:
        year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
        sec = int(m.group(6) or 0)
        return datetime(year, month, day, hour, minute, sec, tzinfo=timezone.utc).timestamp()
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_session_items(inspector_sessions: Any) -> List[Dict[str, Any]]:
    if not inspector_sessions:
        return []
    if isinstance(inspector_sessions, dict):
        items = inspector_sessions.get("sessions") or []
    elif isinstance(inspector_sessions, Iterable) and not isinstance(inspector_sessions, (str, bytes)):
        items = list(inspector_sessions)
    else:
        return []

    out: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            out.append({"fullTitle": item})
        elif isinstance(item, dict):
            out.append(item)
    return out


def _collect_local_histories(histories_dir: Optional[Path | str]) -> Dict[str, Dict[str, Any]]:
    """Load *_history.json summaries keyed by normalized contact key."""
    if not histories_dir:
        return {}
    root = Path(histories_dir)
    if not root.is_dir():
        return {}

    by_key: Dict[str, Dict[str, Any]] = {}
    for hp in sorted(root.glob("*_history.json")):
        try:
            doc = json.loads(hp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        raw_target = str(doc.get("matchedTitle") or doc.get("target") or "").strip()
        if not raw_target:
            continue
        key = _norm_contact_key(raw_target)
        if not key:
            continue

        records = [r for r in (doc.get("records") or []) if isinstance(r, dict) and r.get("kind") != "timestamp"]
        texts = [str(r.get("text") or "").strip() for r in records if str(r.get("text") or "").strip()]
        directions = {str(r.get("direction") or "") for r in records if str(r.get("text") or "").strip()}
        obs_ts = _parse_iso_ts(doc.get("observedAt"))
        for r in reversed(records):
            rec_ts = _parse_iso_ts(r.get("ts") or r.get("timestamp"))
            if rec_ts is not None:
                obs_ts = max(obs_ts or 0.0, rec_ts)
                break
        if obs_ts is None:
            try:
                obs_ts = hp.stat().st_mtime
            except OSError:
                obs_ts = 0.0

        existing = by_key.get(key)
        if existing is None:
            by_key[key] = {
                "target": _display_contact_name(raw_target),
                "messageCount": max(int(doc.get("recordCount") or 0), len(records)),
                "texts": texts,
                "directions": directions,
                "lastTs": obs_ts,
                "observedAt": str(doc.get("observedAt") or ""),
                "historyPaths": [str(hp)],
            }
        else:
            existing["messageCount"] += len(records)
            existing["texts"].extend(texts)
            existing["directions"].update(directions)
            existing["lastTs"] = max(existing["lastTs"], obs_ts)
            if doc.get("observedAt") and str(doc.get("observedAt")) > existing["observedAt"]:
                existing["observedAt"] = str(doc.get("observedAt"))
            existing["historyPaths"].append(str(hp))
    return by_key


def _extract_bundle_participants_and_records(bundle: Any) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """Normalize a TranscriptBundle or dict into (source_path, participants, records)."""
    if isinstance(bundle, TranscriptBundle):
        recs = [
            {
                "sender": str(r.sender or "").strip(),
                "text": str(r.content or "").strip(),
                "timestamp": str(r.timestamp or "").strip(),
                "msg_type": str(r.msg_type or "text"),
            }
            for r in bundle.records
        ]
        parts = [str(p).strip() for p in bundle.participants if str(p).strip()]
        return bundle.source_path, parts, recs

    if isinstance(bundle, dict):
        raw_recs = bundle.get("records") or []
        recs = []
        for r in raw_recs:
            if not isinstance(r, dict):
                continue
            recs.append({
                "sender": str(r.get("sender") or "").strip(),
                "text": str(r.get("content") if r.get("content") is not None else r.get("text") or "").strip(),
                "timestamp": str(r.get("timestamp") or r.get("ts") or r.get("timeMarker") or "").strip(),
                "msg_type": str(r.get("msg_type") or "text"),
            })
        parts = [str(p).strip() for p in (bundle.get("participants") or []) if str(p).strip()]
        if not parts:
            parts = sorted({r["sender"] for r in recs if r["sender"] and r["sender"] != "unknown"})
        return str(bundle.get("source_path") or bundle.get("sourcePath") or ""), parts, recs

    raise TypeError(f"Unsupported bundle object: {type(bundle)!r}")


class CorpusDiscoveryEngine:
    """Discovers high-value WeChat sales conversations, local archives, and owner identity."""

    def __init__(self, importer: Optional[WeChatBridgeImporter] = None) -> None:
        self.importer = importer or WeChatBridgeImporter()

    def discover_wechat_sessions(
        self,
        inspector_sessions: Any,
        histories_dir: Optional[Path | str] = None,
        *,
        test_contacts: Iterable[str] = (),
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Filter, score, and rank WeChat sessions by sales value and local history readiness."""
        test_keys = {_norm_contact_key(name) for name in test_contacts if _norm_contact_key(name)}
        local_histories = _collect_local_histories(histories_dir)
        session_items = _extract_session_items(inspector_sessions)

        merged: Dict[str, Dict[str, Any]] = {}

        for idx, sess in enumerate(session_items):
            raw_title = str(
                sess.get("fullTitle")
                or sess.get("target")
                or sess.get("listTitleSnippet")
                or sess.get("titleSnippet")
                or ""
            ).strip()
            if not raw_title or _is_system_or_service_account(raw_title, sess):
                continue
            key = _norm_contact_key(raw_title)
            if not key or key in test_keys:
                continue

            display_name = _display_contact_name(raw_title)
            preview = str(sess.get("listPreviewSnippet") or sess.get("previewSnippet") or "").strip()
            vis_msgs = [str(m).strip() for m in (sess.get("visibleMessages") or []) if str(m).strip()]
            vis_count = int(sess.get("visibleMessageCount") or len(vis_msgs) or 0)
            sess_ts = _parse_iso_ts(sess.get("lastActiveAt") or sess.get("observedAt") or sess.get("updatedAt"))

            entry = merged.setdefault(key, {
                "target": display_name,
                "visibleCount": 0,
                "texts": [],
                "previewSnippet": "",
                "sessionOrder": idx,
                "lastTs": 0.0,
            })
            entry["visibleCount"] = max(entry["visibleCount"], vis_count)
            if preview and not entry["previewSnippet"]:
                entry["previewSnippet"] = preview
                entry["texts"].append(preview)
            entry["texts"].extend(vis_msgs)
            if sess_ts is not None:
                entry["lastTs"] = max(entry["lastTs"], sess_ts)

        for key, hist in local_histories.items():
            if key in test_keys or _is_system_or_service_account(hist["target"]):
                continue
            entry = merged.setdefault(key, {
                "target": hist["target"],
                "visibleCount": 0,
                "texts": [],
                "previewSnippet": "",
                "sessionOrder": 999,
                "lastTs": 0.0,
            })
            entry["hasLocalHistory"] = True
            entry["historyMessageCount"] = hist["messageCount"]
            entry["directions"] = hist["directions"]
            entry["historyPaths"] = hist["historyPaths"]
            entry["observedAt"] = hist["observedAt"]
            entry["lastTs"] = max(entry["lastTs"], float(hist["lastTs"] or 0.0))
            entry["texts"].extend(hist["texts"])
            if not entry["previewSnippet"] and hist["texts"]:
                entry["previewSnippet"] = hist["texts"][-1][:80]

        now_ts = datetime.now(timezone.utc).timestamp()
        max_hist_ts = max((float(v.get("lastTs") or 0.0) for v in merged.values()), default=0.0)
        ref_ts = max(now_ts, max_hist_ts) if max_hist_ts > 0 else now_ts

        ranked: List[Dict[str, Any]] = []
        for key, info in merged.items():
            has_local = bool(info.get("hasLocalHistory"))
            msg_count = int(info.get("historyMessageCount") or 0)
            if msg_count == 0:
                msg_count = int(info.get("visibleCount") or 0)

            corpus_blob = "\n".join(info.get("texts") or [])
            matched_signals: List[str] = []
            for kw in SALES_SIGNAL_KEYWORDS:
                if kw in corpus_blob and kw not in matched_signals:
                    matched_signals.append(kw)

            # Scoring: message volume (0-35), sales signals (0-40), recency (0-20), bidirectional/local bonus (0-15)
            volume_score = min(35.0, msg_count * 1.4)
            signal_score = min(40.0, len(matched_signals) * 8.0)

            last_ts = float(info.get("lastTs") or 0.0)
            if last_ts > 0:
                age_days = max(0.0, (ref_ts - last_ts) / 86400.0)
                recency_score = max(0.0, 20.0 - age_days * 1.5)
            else:
                # Top-of-list sessions in inspector get mild recency credit
                recency_score = max(2.0, 12.0 - min(10.0, float(info.get("sessionOrder", 10)) * 0.8))

            directions = info.get("directions") or set()
            bidirectional = "self" in directions and "peer" in directions
            bonus_score = (8.0 if has_local else 0.0) + (7.0 if bidirectional else 0.0)

            total_score = round(volume_score + signal_score + recency_score + bonus_score, 2)

            reason_tags: List[str] = []
            if matched_signals:
                reason_tags.append(f"商机关键词({','.join(matched_signals[:3])})")
            if msg_count >= 10:
                reason_tags.append(f"高频对话({msg_count}条)")
            elif msg_count > 0:
                reason_tags.append(f"已有记录({msg_count}条)")
            if has_local:
                reason_tags.append("本地历史已就绪")
            if bidirectional:
                reason_tags.append("双向互动完整")
            if recency_score >= 14.0:
                reason_tags.append("近期活跃")

            ranked.append({
                "target": info["target"],
                "score": total_score,
                "reasonTags": reason_tags,
                "messageCount": msg_count,
                "hasLocalHistory": has_local,
                "matchedSignals": matched_signals,
                "previewSnippet": info.get("previewSnippet") or "",
                "observedAt": info.get("observedAt") or "",
                "historyPaths": list(info.get("historyPaths") or []),
            })

        ranked.sort(key=lambda item: (-item["score"], -item["messageCount"], item["target"]))
        if limit is not None and limit >= 0:
            return ranked[: int(limit)]
        return ranked

    def scan_archive_directories(
        self,
        search_dirs: Optional[Iterable[Path | str]] = None,
    ) -> List[Dict[str, Any]]:
        """Scan directories read-only for WeChat exported .zip and *聊天记录*.txt candidates."""
        dirs = [Path(d).expanduser() for d in (search_dirs if search_dirs is not None else DEFAULT_SEARCH_DIRS)]
        candidates: List[Dict[str, Any]] = []
        seen_paths: set[Path] = set()
        seen_sha256: set[str] = set()

        raw_files: List[Path] = []
        for root in dirs:
            if not root.exists() or not root.is_dir():
                continue
            for item in sorted(root.rglob("*")):
                if not item.is_file():
                    continue
                suffix = item.suffix.lower()
                if suffix == ".zip" or (suffix == ".txt" and _CHAT_LOG_NAME_RE.search(item.name)):
                    raw_files.append(item)

        # Prefer newest files first if duplicates exist across directories
        raw_files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)

        for path in raw_files:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            try:
                stat = resolved.stat()
            except OSError:
                continue

            suffix = resolved.suffix.lower()
            transcript_entry = resolved.name if suffix == ".txt" else ""
            entry_count = 1 if suffix == ".txt" else 0

            if suffix == ".zip":
                has_txt = False
                seen_canon: Dict[str, str] = {}
                try:
                    with zipfile.ZipFile(resolved, "r") as zf:
                        infos = zf.infolist()
                        for info in infos:
                            validate_zip_member_name(info.filename, seen_canon)
                        entry_count = len(infos)
                        txt_names = [inf.filename for inf in infos if not inf.is_dir() and inf.filename.lower().endswith(".txt")]
                        if txt_names:
                            has_txt = True
                            native = next((n for n in txt_names if Path(n).name == "聊天记录.txt"), None)
                            transcript_entry = native or txt_names[0]
                except Exception:
                    continue
                if not has_txt and not _CHAT_LOG_NAME_RE.search(resolved.name):
                    continue

            try:
                digest = _sha256_file(resolved)
            except OSError:
                continue
            if digest in seen_sha256:
                continue
            seen_sha256.add(digest)

            candidates.append({
                "path": str(resolved),
                "name": resolved.name,
                "kind": "zip" if suffix == ".zip" else "txt",
                "sizeBytes": int(stat.st_size),
                "modifiedAt": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
                "sha256": digest,
                "entryCount": entry_count,
                "transcriptEntry": transcript_entry,
            })

        return candidates

    def infer_owner_from_bundles(
        self,
        bundles: Sequence[Any],
        *,
        known_aliases: Iterable[str] = (),
    ) -> Dict[str, Any]:
        """Infer the WeChat owner from cross-session sender intersection or single-bundle heuristics."""
        alias_display = [str(a).strip() for a in known_aliases if str(a).strip()]
        alias_keys = {unicodedata.normalize("NFKC", a).strip().casefold() for a in alias_display}

        session_counts: Counter[str] = Counter()
        msg_counts: Counter[str] = Counter()
        reply_counts: Counter[str] = Counter()
        sales_hits: Counter[str] = Counter()
        display_names: Dict[str, str] = {}
        valid_bundle_count = 0

        for bundle in bundles or ():
            _, parts, recs = _extract_bundle_participants_and_records(bundle)
            bundle_senders: set[str] = set()
            for p in parts:
                if p and p != "unknown":
                    k = unicodedata.normalize("NFKC", p).strip().casefold()
                    bundle_senders.add(k)
                    display_names.setdefault(k, p)

            prev_sender_key: Optional[str] = None
            for rec in recs:
                sender = str(rec.get("sender") or "").strip()
                if not sender or sender == "unknown":
                    continue
                sk = unicodedata.normalize("NFKC", sender).strip().casefold()
                display_names.setdefault(sk, sender)
                bundle_senders.add(sk)
                msg_counts[sk] += 1
                if prev_sender_key is not None and prev_sender_key != sk:
                    reply_counts[sk] += 1
                prev_sender_key = sk
                txt = str(rec.get("text") or "")
                if any(marker in txt for marker in ("您好", "发您", "这边", "报价", "方案", "安排", "感谢")):
                    sales_hits[sk] += 1

            if bundle_senders:
                valid_bundle_count += 1
                for sk in bundle_senders:
                    session_counts[sk] += 1

        if not display_names:
            if alias_display:
                return {
                    "ownerName": alias_display[0],
                    "confidence": 0.3,
                    "method": "known_alias_fallback",
                    "candidates": [],
                }
            return {
                "ownerName": "",
                "confidence": 0.0,
                "method": "none",
                "candidates": [],
            }

        candidates: List[Dict[str, Any]] = []
        for sk, disp in display_names.items():
            sc = int(session_counts[sk])
            mc = int(msg_counts[sk])
            rc = int(reply_counts[sk])
            alias_match = sk in alias_keys
            score = sc * 100.0 + rc * 2.5 + mc * 0.5 + sales_hits[sk] * 1.5 + (40.0 if alias_match else 0.0)
            candidates.append({
                "name": disp,
                "sessionCount": sc,
                "messageCount": mc,
                "replyCount": rc,
                "aliasMatched": alias_match,
                "score": round(score, 2),
            })

        candidates.sort(key=lambda c: (-c["sessionCount"], -c["score"], -c["replyCount"], -c["messageCount"], c["name"]))
        top = candidates[0]

        if valid_bundle_count >= 2 and top["sessionCount"] >= 2:
            coverage = top["sessionCount"] / max(1, valid_bundle_count)
            conf = round(min(0.99, 0.72 + 0.18 * coverage + (0.06 if top["aliasMatched"] else 0.0)), 2)
            method = "cross_session_intersection+known_alias" if top["aliasMatched"] else "cross_session_intersection"
            return {
                "ownerName": top["name"],
                "confidence": conf,
                "method": method,
                "candidates": candidates,
            }

        alias_candidates = [c for c in candidates if c["aliasMatched"]]
        if alias_candidates:
            chosen = alias_candidates[0]
            return {
                "ownerName": chosen["name"],
                "confidence": 0.9,
                "method": "known_alias",
                "candidates": candidates,
            }

        # Single-bundle reply-frequency heuristic
        heuristic_sorted = sorted(
            candidates,
            key=lambda c: (-(c["replyCount"] * 2.5 + sales_hits[unicodedata.normalize("NFKC", c["name"]).strip().casefold()] * 1.5 + c["messageCount"] * 0.5), c["name"]),
        )
        chosen = heuristic_sorted[0]
        runner_up_score = heuristic_sorted[1]["score"] if len(heuristic_sorted) > 1 else 0.0
        margin = max(0.0, chosen["score"] - runner_up_score)
        conf = round(min(0.78, 0.52 + min(0.24, margin * 0.02)), 2)
        return {
            "ownerName": chosen["name"],
            "confidence": conf,
            "method": "reply_frequency_heuristic",
            "candidates": heuristic_sorted,
        }

    def batch_import_archives(
        self,
        paths: Iterable[Path | str],
        *,
        owner_name: Optional[str] = None,
        known_aliases: Iterable[str] = (),
    ) -> List[Dict[str, Any]]:
        """Import multiple WeChat archives into standardized per-contact bidirectional conversations."""
        bundles: List[TranscriptBundle] = []
        for p in paths or ():
            bundles.append(self.importer.load(Path(p)))

        if not bundles:
            return []

        resolved_owner = str(owner_name or "").strip()
        aliases = [str(a).strip() for a in known_aliases if str(a).strip()]
        if not resolved_owner:
            inferred = self.infer_owner_from_bundles(bundles, known_aliases=aliases)
            resolved_owner = str(inferred.get("ownerName") or "").strip()

        owner_keys = {
            unicodedata.normalize("NFKC", name).strip().casefold()
            for name in ([resolved_owner] + aliases)
            if name
        }

        conversations_by_contact: Dict[str, Dict[str, Any]] = {}
        seen_sigs: Dict[str, set[Tuple[str, str, str]]] = {}

        for bundle in bundles:
            sender_counts: Counter[str] = Counter()
            for rec in bundle.records:
                sender = str(rec.sender or "").strip()
                if not sender or sender == "unknown":
                    continue
                sk = unicodedata.normalize("NFKC", sender).strip().casefold()
                if sk not in owner_keys:
                    sender_counts[sender] += 1

            if sender_counts:
                contact = sender_counts.most_common(1)[0][0]
            else:
                other_parts = [
                    p for p in bundle.participants
                    if unicodedata.normalize("NFKC", p).strip().casefold() not in owner_keys
                ]
                contact = other_parts[0] if other_parts else Path(bundle.source_path).stem

            contact_display = _display_contact_name(contact) or contact
            contact_key = _norm_contact_key(contact_display) or contact_display.casefold()

            conv = conversations_by_contact.setdefault(contact_key, {
                "contact": contact_display,
                "owner": resolved_owner,
                "sourcePaths": [],
                "records": [],
            })
            if bundle.source_path not in conv["sourcePaths"]:
                conv["sourcePaths"].append(bundle.source_path)
            sig_set = seen_sigs.setdefault(contact_key, set())

            for rec in bundle.records:
                sender = str(rec.sender or "").strip()
                sk = unicodedata.normalize("NFKC", sender).strip().casefold()
                direction = "self" if sk and sk in owner_keys else "peer"
                text = str(rec.content or "").strip()
                ts = str(rec.timestamp or "").strip()
                if not text:
                    continue
                sig = (direction, ts, text)
                if sig in sig_set:
                    continue
                sig_set.add(sig)
                conv["records"].append({
                    "direction": direction,
                    "sender": sender,
                    "text": text,
                    "timestamp": ts,
                })

        return list(conversations_by_contact.values())
