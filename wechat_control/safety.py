"""Safety, anti-ban, circuit-breaker, deduplication, and audit logging guards.

Adapted from the core safety designs of:
- a6996660/wx4py-macos (OutgoingMessageRegistry dedup, allowlist, jitter, JSONL audit)
- wq19901103wq/wechat-mac-rpa (3x dirty-input readback circuit breaker)
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple
from .io_utils import atomic_write_json


class SafetyViolationError(RuntimeError):
    """Base error raised when an outbound WeChat action violates safety guards."""


class DirtyInputCircuitBreakerError(SafetyViolationError):
    """Raised when readback length exceeds 3x the intended message length."""


class ReadbackMismatchError(SafetyViolationError):
    """Raised when pasted input box content does not match expected message text."""


class DuplicateSendBlockedError(SafetyViolationError):
    """Raised when the same (target, text) is retried inside the dedup window."""


class GroupNotAllowedError(SafetyViolationError):
    """Raised when sending to a target not present in the configured allowlist."""


def normalize_chat_name(name: str) -> str:
    """Normalize WeChat session/group titles by stripping trailing member count ` (N)`."""
    if not name:
        return ""
    cleaned = re.sub(r"\s*\(\d+\)\s*$", "", name).strip()
    nfkc = unicodedata.normalize("NFKC", cleaned)
    return re.sub(r"\s+", " ", nfkc).strip()


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReadbackVerifier:
    """Validates pasted text against expected text with 3x dirty-input circuit breaker."""

    MAX_EXPANSION_RATIO = 3

    @classmethod
    def verify(cls, expected_text: str, actual_readback: str) -> None:
        expected = expected_text.strip()
        actual = actual_readback or ""
        if not expected:
            raise ReadbackMismatchError("Expected outgoing message text cannot be empty.")
        if len(actual) > len(expected_text) * cls.MAX_EXPANSION_RATIO:
            raise DirtyInputCircuitBreakerError(
                f"Dirty input circuit breaker: readback length ({len(actual)}) "
                f"> {cls.MAX_EXPANSION_RATIO}x expected ({len(expected_text)})."
            )
        if expected not in actual:
            raise ReadbackMismatchError(
                f"Readback mismatch: expected substring of length {len(expected)} not found in input."
            )


class OutgoingMessageRegistry:
    """Thread-safe deduplication registry to block duplicate sends within a time window."""

    def __init__(self, dedup_window_seconds: float = 120.0) -> None:
        self.dedup_window_seconds = float(dedup_window_seconds)
        self._lock = threading.Lock()
        self._records: Dict[str, float] = {}

    @staticmethod
    def fingerprint(target: str, text: str) -> str:
        norm_target = normalize_chat_name(target)
        norm_text = unicodedata.normalize("NFKC", text).strip()
        payload = f"{norm_target}\x1f{norm_text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def check_and_record(
        self,
        target: str,
        text: str,
        *,
        record_now: bool = True,
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, str, float]:
        """Return (allowed, fingerprint, seconds_since_previous_or_0)."""
        ts = time.monotonic() if now_ts is None else now_ts
        fp = self.fingerprint(target, text)
        with self._lock:
            expired = [
                k for k, prev in self._records.items()
                if ts - prev >= self.dedup_window_seconds
            ]
            for k in expired:
                del self._records[k]

            prev_ts = self._records.get(fp)
            if prev_ts is not None and (ts - prev_ts) < self.dedup_window_seconds:
                return False, fp, round(ts - prev_ts, 3)

            if record_now:
                self._records[fp] = ts
            return True, fp, 0.0

    def mark_sent(self, target: str, text: str, now_ts: Optional[float] = None) -> str:
        ts = time.monotonic() if now_ts is None else now_ts
        fp = self.fingerprint(target, text)
        with self._lock:
            self._records[fp] = ts
        return fp


class GroupAllowlistGuard:
    """Optional allowlist restricting live/batch messaging to approved chats/groups."""

    def __init__(self, allowed_targets: Optional[Iterable[str]] = None) -> None:
        raw = list(allowed_targets) if allowed_targets is not None else []
        self._normalized: Set[str] = {
            normalize_chat_name(item) for item in raw if str(item).strip()
        }

    @property
    def enabled(self) -> bool:
        return bool(self._normalized)

    def is_allowed(self, target: str) -> bool:
        if not self._normalized:
            return True
        if not target or not target.strip():
            return False
        norm_target = normalize_chat_name(target)
        return norm_target in self._normalized

    def list_allowed(self) -> list[str]:
        return sorted(self._normalized)


@dataclass
class HumanJitter:
    """Configurable human-like randomized delay calculator."""

    min_delay_ms: int = 350
    max_delay_ms: int = 1200

    def next_delay_seconds(self) -> float:
        low = max(0, self.min_delay_ms)
        high = max(low, self.max_delay_ms)
        return random.randint(low, high) / 1000.0

    def sleep_before_action(self) -> float:
        sec = self.next_delay_seconds()
        time.sleep(sec)
        return sec


@dataclass
class AuditLogger:
    """Append-only structured JSONL audit log for every RPA/OCR/Bridge event."""

    log_path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def log(self, action: str, status: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry: Dict[str, Any] = {
            "timestamp": _utc_iso_now(),
            "action": action,
            "status": status,
            "details": details or {},
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return entry


@dataclass
class AntiBanGuard:
    """自动回复频控守卫：约束机器人发送节奏，降低账号被风控/限制的风险。

    四道闸门（超额即拒绝自动发送，只记录事件、绝不静默丢弃审计）：
    1. 每联系人每小时上限（default 8）——避免对同一好友高频轰炸
    2. 同一联系人最短回复间隔（default 90s）——连续消息强制冷却
    3. 全局每小时上限（default 15）
    4. 全局每日总量上限（default 60）
    状态原子落盘（tmp+replace），进程重启后计数延续（按日/小时键自然滚动）。
    只约束自动回复路径；用户在控制台手动发送不受此限（那是本人真实操作）。
    """

    state_path: Path
    per_contact_hourly: int = 8
    global_hourly: int = 15
    global_daily: int = 60
    min_reply_gap_seconds: int = 90
    now_fn: Any = None  # callable() -> float，测试注入

    def __post_init__(self) -> None:
        import threading as _threading

        self._lock = _threading.Lock()
        self._now = self.now_fn or time.time
        self._state: Dict[str, Any] = {}

    # ---------- 内部 ----------
    def _load(self) -> Dict[str, Any]:
        try:
            doc = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
        except Exception:
            pass
        return {"dailyKey": "", "daily": 0, "hourly": {}, "contacts": {}}

    def _save(self, doc: Dict[str, Any]) -> None:
        try:
            atomic_write_json(self.state_path, doc)
        except OSError:
            pass

    @staticmethod
    def _hour_key(ts: float) -> str:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H")

    @staticmethod
    def _day_key(ts: float) -> str:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _contact_key(target: str) -> str:
        return normalize_chat_name(str(target or "")).casefold()

    def _prune(self, doc: Dict[str, Any], ts: float) -> None:
        # 只保留最近 48 个小时桶与当日计数，防止无限增长
        keys = sorted(doc.get("hourly", {}).keys())
        for k in keys[:-48]:
            doc["hourly"].pop(k, None)

    # ---------- 对外 ----------
    def check_can_send(self, target: str) -> Tuple[bool, str]:
        ts = self._now()
        with self._lock:
            doc = self._load()
            day = self._day_key(ts)
            if doc.get("dailyKey") != day:
                doc["dailyKey"] = day
                doc["daily"] = 0
            self._prune(doc, ts)
            hour = self._hour_key(ts)
            ckey = self._contact_key(target)
            contact = doc.setdefault("contacts", {}).setdefault(ckey, {})
            if contact.get("hourKey") != hour:
                contact["hourKey"] = hour
                contact["hourCount"] = 0
            if doc.get("daily", 0) >= self.global_daily:
                return False, f"daily_limit:{doc.get('daily')}/{self.global_daily}"
            if doc.get("hourly", {}).get(hour, 0) >= self.global_hourly:
                return False, f"hourly_limit:{doc.get('hourly', {}).get(hour)}/{self.global_hourly}"
            if contact.get("hourCount", 0) >= self.per_contact_hourly:
                return False, f"contact_hourly_limit:{contact.get('hourCount')}/{self.per_contact_hourly}"
            last = float(contact.get("lastTs") or 0)
            gap = ts - last
            if last and gap < self.min_reply_gap_seconds:
                return False, f"contact_gap:{int(gap)}s<{self.min_reply_gap_seconds}s"
            return True, "ok"

    def record_sent(self, target: str) -> None:
        ts = self._now()
        with self._lock:
            doc = self._load()
            day = self._day_key(ts)
            if doc.get("dailyKey") != day:
                doc["dailyKey"] = day
                doc["daily"] = 0
            hour = self._hour_key(ts)
            doc["hourly"][hour] = doc.get("hourly", {}).get(hour, 0) + 1
            doc["daily"] = doc.get("daily", 0) + 1
            ckey = self._contact_key(target)
            contact = doc.setdefault("contacts", {}).setdefault(ckey, {})
            if contact.get("hourKey") != hour:
                contact["hourKey"] = hour
                contact["hourCount"] = 0
            contact["hourCount"] = contact.get("hourCount", 0) + 1
            contact["lastTs"] = ts
            self._prune(doc, ts)
            self._save(doc)

    def status(self) -> Dict[str, Any]:
        ts = self._now()
        with self._lock:
            doc = self._load()
            day = self._day_key(ts)
            hour = self._hour_key(ts)
            return {
                "dailySent": doc.get("daily", 0),
                "dailyLimit": self.global_daily,
                "hourlySent": doc.get("hourly", {}).get(hour, 0),
                "hourlyLimit": self.global_hourly,
                "perContactHourlyLimit": self.per_contact_hourly,
                "minReplyGapSeconds": self.min_reply_gap_seconds,
            }
