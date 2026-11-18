"""Multi-window concurrent scheduling pipeline & fast/slow two-tier coordinator.

Implements four composable, deterministic, unit-testable components:
1. `PerceptualDHashFilter` (LeetCode 461 Hamming distance): skips redundant OCR
   when a window's 64-bit perceptual difference hash changes below threshold.
2. `SlidingWindowCoalescer` (LeetCode 56 interval merging): debounces rapid
   consecutive messages from the same contact within `window_seconds=1.8`.
3. `AgingPriorityScheduler` (LeetCode 1834 min-heap + starvation aging + concurrent
   thinking + single-writer mutex): executes `think_fn` across windows via
   `ThreadPoolExecutor` and serializes UI `send_fn` via `threading.Lock()`.
4. `TwoTierWindowCoordinator`: routes allowlisted pop-out chat windows into the
   zero-switch fast lane, deduplicates them out of the main-window fallback list,
   and isolates non-allowlisted pop-outs as read-only protected windows.
"""

from __future__ import annotations

import heapq
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .live_inspector import _matches_target
from .safety import normalize_chat_name


def _normalize_dhash_hex(hex_str: str) -> int:
    clean = str(hex_str or "").strip().lower()
    if clean.startswith("0x"):
        clean = clean[2:]
    if not clean:
        raise ValueError("Empty dHash64 hex string")
    return int(clean, 16) & ((1 << 64) - 1)


class PerceptualDHashFilter:
    """LeetCode 461 Hamming-distance filter on 64-bit window difference hashes."""

    def __init__(self, default_threshold: int = 4) -> None:
        self.default_threshold = max(0, int(default_threshold))
        self._lock = threading.RLock()
        self._fingerprints: Dict[int, str] = {}
        self.ocr_skipped_by_dhash: int = 0
        self.ocr_triggered: int = 0

    @staticmethod
    def hamming_distance(hex_a: str, hex_b: str) -> int:
        """Return the bitwise Hamming distance between two 64-bit hex strings."""
        a_int = _normalize_dhash_hex(hex_a)
        b_int = _normalize_dhash_hex(hex_b)
        return bin(a_int ^ b_int).count("1")

    def should_run_ocr(
        self,
        window_id: int,
        dhash64: str,
        threshold: Optional[int] = None,
    ) -> Tuple[bool, int]:
        """Decide whether a window changed enough (`distance >= threshold`) to run OCR."""
        eff_thresh = self.default_threshold if threshold is None else max(0, int(threshold))
        wid = int(window_id)
        clean = str(dhash64 or "").strip().lower()
        if clean.startswith("0x"):
            clean = clean[2:]

        with self._lock:
            if not clean:
                self.ocr_triggered += 1
                return True, 64
            try:
                _normalize_dhash_hex(clean)
            except ValueError:
                self.ocr_triggered += 1
                return True, 64

            prev = self._fingerprints.get(wid)
            if prev is None:
                self._fingerprints[wid] = clean
                self.ocr_triggered += 1
                return True, 64

            dist = self.hamming_distance(prev, clean)
            if dist < eff_thresh:
                self.ocr_skipped_by_dhash += 1
                return False, dist

            self._fingerprints[wid] = clean
            self.ocr_triggered += 1
            return True, dist

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "defaultThreshold": self.default_threshold,
                "ocrSkippedByDHash": self.ocr_skipped_by_dhash,
                "ocrTriggered": self.ocr_triggered,
                "trackedWindows": len(self._fingerprints),
            }

    def reset(self, window_id: Optional[int] = None) -> None:
        with self._lock:
            if window_id is None:
                self._fingerprints.clear()
                self.ocr_skipped_by_dhash = 0
                self.ocr_triggered = 0
            else:
                self._fingerprints.pop(int(window_id), None)


class SlidingWindowCoalescer:
    """LeetCode 56 interval-merging debouncer per target within `window_seconds`."""

    def __init__(self, window_seconds: float = 1.8) -> None:
        self.window_seconds = max(0.05, float(window_seconds))
        self._lock = threading.RLock()
        self._buffers: Dict[str, Dict[str, Any]] = {}
        self.coalesced_bursts: int = 0
        self.total_messages_merged: int = 0

    @staticmethod
    def merge_intervals(intervals: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """Standard LeetCode 56 overlapping interval merge."""
        sorted_iv = sorted((float(s), float(e)) for s, e in intervals)
        if not sorted_iv:
            return []
        merged: List[Tuple[float, float]] = [sorted_iv[0]]
        for start, end in sorted_iv[1:]:
            prev_s, prev_e = merged[-1]
            if start <= prev_e:
                merged[-1] = (prev_s, max(prev_e, end))
            else:
                merged.append((start, end))
        return merged

    def _emit_buffer_locked(self, key: str) -> Optional[Dict[str, Any]]:
        buf = self._buffers.pop(key, None)
        if not buf or not buf["messages"]:
            return None
        msgs = list(buf["messages"])
        merged_intervals = self.merge_intervals(buf["intervals"])
        coalesced = len(msgs) >= 2
        if coalesced:
            self.coalesced_bursts += 1
            self.total_messages_merged += len(msgs)
        merged_text = " ".join(m for m in msgs if m).strip()
        return {
            "target": buf["target"],
            "mergedText": merged_text,
            "messages": msgs,
            "messageCount": len(msgs),
            "windowStart": buf["first_ts"],
            "windowEnd": buf["last_ts"],
            "mergedIntervals": merged_intervals,
            "coalesced": coalesced,
        }

    def push(
        self,
        target: str,
        text: str,
        *,
        now_ts: Optional[float] = None,
        flush: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Append a message to `target`'s sliding window.

        If a prior buffered burst expired (`now_ts - last_ts > window_seconds`),
        the prior merged burst is returned immediately and a new window starts
        with `text`. When `flush=True`, the updated buffer is flushed and
        returned immediately.
        """
        clean_target = str(target or "").strip()
        clean_text = str(text or "").strip()
        if not clean_target or not clean_text:
            return None
        key = normalize_chat_name(clean_target).casefold()
        ts = time.monotonic() if now_ts is None else float(now_ts)

        with self._lock:
            emitted: Optional[Dict[str, Any]] = None
            existing = self._buffers.get(key)
            if existing is not None:
                if (ts - float(existing["last_ts"])) > self.window_seconds:
                    emitted = self._emit_buffer_locked(key)
                else:
                    existing["messages"].append(clean_text)
                    existing["last_ts"] = ts
                    existing["intervals"].append((ts, ts + self.window_seconds))
                    if flush:
                        return self._emit_buffer_locked(key)
                    return None

            self._buffers[key] = {
                "target": clean_target,
                "messages": [clean_text],
                "first_ts": ts,
                "last_ts": ts,
                "intervals": [(ts, ts + self.window_seconds)],
            }
            if flush:
                flushed = self._emit_buffer_locked(key)
                return flushed if emitted is None else emitted
            return emitted

    def flush(self, target: Optional[str] = None) -> List[Dict[str, Any]]:
        """Flush a single target or all buffered targets immediately."""
        with self._lock:
            if target is not None:
                key = normalize_chat_name(str(target)).casefold()
                one = self._emit_buffer_locked(key)
                return [one] if one is not None else []
            out: List[Dict[str, Any]] = []
            for key in list(self._buffers.keys()):
                item = self._emit_buffer_locked(key)
                if item is not None:
                    out.append(item)
            return out

    def drain_ready(self, *, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        """Emit all target buffers whose sliding window has elapsed by `now_ts`."""
        ts = time.monotonic() if now_ts is None else float(now_ts)
        with self._lock:
            ready_keys = [
                k for k, buf in self._buffers.items()
                if (ts - float(buf["last_ts"])) > self.window_seconds
            ]
            out: List[Dict[str, Any]] = []
            for key in ready_keys:
                item = self._emit_buffer_locked(key)
                if item is not None:
                    out.append(item)
            return out

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "windowSeconds": self.window_seconds,
                "coalescedBursts": self.coalesced_bursts,
                "totalMessagesMerged": self.total_messages_merged,
                "pendingTargets": len(self._buffers),
            }


class AgingPriorityScheduler:
    """LeetCode 1834 min-heap scheduler with anti-starvation aging, concurrent think, and write mutex."""

    def __init__(self, *, min_send_interval_seconds: float = 0.0) -> None:
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._heap: List[Tuple[float, int, Dict[str, Any]]] = []
        self._seq: int = 0
        self.min_send_interval_seconds = max(0.0, float(min_send_interval_seconds))
        self._last_write_ts: float = 0.0
        self.total_dispatched: int = 0

    @staticmethod
    def compute_priority_score(
        *,
        urgency: float = 0.0,
        care_weight: float = 0.0,
        is_popout: bool = False,
        wait_seconds: float = 0.0,
    ) -> float:
        """Compute dynamic scheduling score with starvation aging (+2.5/sec)."""
        return round(
            100.0 * float(urgency)
            + 50.0 * float(care_weight)
            + 15.0 * (1.0 if is_popout else 0.0)
            + 2.5 * max(0.0, float(wait_seconds)),
            4,
        )

    @classmethod
    def score_task(cls, task: Dict[str, Any], *, now_ts: Optional[float] = None) -> float:
        urgency = float(task.get("urgency") or 0.0)
        care_weight = float(task.get("care_weight") if "care_weight" in task else (task.get("careWeight") or 0.0))
        is_popout = bool(task.get("is_popout") if "is_popout" in task else task.get("isPopout", False))
        explicit_wait = float(
            task.get("wait_seconds") if "wait_seconds" in task else (task.get("waitSeconds") or 0.0)
        )
        enqueued_at = task.get("enqueued_at") if "enqueued_at" in task else task.get("enqueuedAt")
        elapsed_wait = 0.0
        if enqueued_at is not None and now_ts is not None:
            elapsed_wait = max(0.0, float(now_ts) - float(enqueued_at))
        return cls.compute_priority_score(
            urgency=urgency,
            care_weight=care_weight,
            is_popout=is_popout,
            wait_seconds=max(explicit_wait, elapsed_wait),
        )

    def enqueue(self, task: Dict[str, Any], *, now_ts: Optional[float] = None) -> Dict[str, Any]:
        ts = time.monotonic() if now_ts is None else float(now_ts)
        item = dict(task)
        item.setdefault("enqueuedAt", ts)
        score = self.score_task(item, now_ts=ts)
        with self._lock:
            self._seq += 1
            heapq.heappush(self._heap, (-score, self._seq, item))
        return {"target": item.get("target", ""), "priorityScore": score, "queueDepth": self.queue_depth()}

    def _reheapify_locked(self, now_ts: float) -> None:
        rebuilt: List[Tuple[float, int, Dict[str, Any]]] = []
        for _, seq_id, item in self._heap:
            score = self.score_task(item, now_ts=now_ts)
            rebuilt.append((-score, seq_id, item))
        heapq.heapify(rebuilt)
        self._heap = rebuilt

    def pop_next(self, *, now_ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
        ts = time.monotonic() if now_ts is None else float(now_ts)
        with self._lock:
            if not self._heap:
                return None
            self._reheapify_locked(ts)
            neg_score, _, item = heapq.heappop(self._heap)
            out = dict(item)
            out["priorityScore"] = round(-neg_score, 4)
            return out

    def peek_ordered(self, *, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        ts = time.monotonic() if now_ts is None else float(now_ts)
        with self._lock:
            self._reheapify_locked(ts)
            ordered = sorted(self._heap, key=lambda tup: (tup[0], tup[1]))
            return [
                {**item, "priorityScore": round(-neg_score, 4)}
                for neg_score, _, item in ordered
            ]

    def queue_depth(self) -> int:
        with self._lock:
            return len(self._heap)

    def dispatch_concurrent_replies(
        self,
        tasks: Optional[Iterable[Dict[str, Any]]],
        think_fn: Callable[[Dict[str, Any]], Any],
        send_fn: Optional[Callable[[Dict[str, Any], Any], Any]] = None,
        *,
        max_workers: int = 5,
        min_send_interval_seconds: Optional[float] = None,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Heap-order tasks, run `think_fn` concurrently, then serialize `send_fn` under one write lock."""
        t0 = time.perf_counter()
        eff_now = time.monotonic() if now_ts is None else float(now_ts)
        if tasks is None:
            task_list: List[Dict[str, Any]] = []
            while True:
                popped = self.pop_next(now_ts=eff_now)
                if popped is None:
                    break
                task_list.append(popped)
        else:
            task_list = [dict(t) for t in tasks]
        if not task_list:
            return {
                "ok": True,
                "taskCount": 0,
                "maxWorkers": max(1, int(max_workers)),
                "thinkPhaseMs": 0.0,
                "sendPhaseMs": 0.0,
                "totalElapsedMs": 0.0,
                "dispatchedOrder": [],
                "results": [],
                "queueDepth": self.queue_depth(),
            }

        local_heap: List[Tuple[float, int, Dict[str, Any]]] = []
        for idx, item in enumerate(task_list):
            score = self.score_task(item, now_ts=eff_now)
            item["priorityScore"] = score
            heapq.heappush(local_heap, (-score, idx, item))

        ordered_tasks: List[Dict[str, Any]] = []
        while local_heap:
            _, _, popped = heapq.heappop(local_heap)
            ordered_tasks.append(popped)

        eff_workers = max(1, min(int(max_workers), len(ordered_tasks)))

        def _think_one(task: Dict[str, Any]) -> Dict[str, Any]:
            started = time.perf_counter()
            try:
                draft = think_fn(task)
                return {
                    "ok": True,
                    "draft": draft,
                    "error": None,
                    "thinkLatencyMs": round((time.perf_counter() - started) * 1000.0, 2),
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "draft": None,
                    "error": str(exc),
                    "thinkLatencyMs": round((time.perf_counter() - started) * 1000.0, 2),
                }

        think_t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=eff_workers) as pool:
            think_outputs = list(pool.map(_think_one, ordered_tasks))
        think_elapsed_ms = round((time.perf_counter() - think_t0) * 1000.0, 2)

        interval = (
            self.min_send_interval_seconds
            if min_send_interval_seconds is None
            else max(0.0, float(min_send_interval_seconds))
        )
        send_t0 = time.perf_counter()
        results: List[Dict[str, Any]] = []
        send_seq = 0
        for task, think_out in zip(ordered_tasks, think_outputs):
            send_res: Any = None
            send_error: Optional[str] = None
            send_order: Optional[int] = None
            if send_fn is not None and think_out["ok"]:
                with self._write_lock:
                    if interval > 0.0 and self._last_write_ts > 0.0:
                        elapsed = time.monotonic() - self._last_write_ts
                        if elapsed < interval:
                            time.sleep(interval - elapsed)
                    send_seq += 1
                    send_order = send_seq
                    try:
                        send_res = send_fn(task, think_out["draft"])
                    except Exception as exc:
                        send_error = str(exc)
                    finally:
                        self._last_write_ts = time.monotonic()
                    with self._lock:
                        self.total_dispatched += 1

            results.append({
                "target": str(task.get("target") or task.get("title") or ""),
                "windowID": task.get("windowID"),
                "priorityScore": task["priorityScore"],
                "thinkOk": think_out["ok"],
                "thinkLatencyMs": think_out["thinkLatencyMs"],
                "thinkError": think_out["error"],
                "draft": think_out["draft"],
                "sendOrder": send_order,
                "sendResult": send_res,
                "sendError": send_error,
            })

        send_elapsed_ms = round((time.perf_counter() - send_t0) * 1000.0, 2)
        total_elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "ok": True,
            "taskCount": len(ordered_tasks),
            "maxWorkers": eff_workers,
            "thinkPhaseMs": think_elapsed_ms,
            "sendPhaseMs": send_elapsed_ms,
            "totalElapsedMs": total_elapsed_ms,
            "dispatchedOrder": [r["target"] for r in results],
            "results": results,
            "queueDepth": self.queue_depth(),
        }

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "queueDepth": len(self._heap),
                "totalDispatched": self.total_dispatched,
                "minSendIntervalSeconds": self.min_send_interval_seconds,
            }


class TwoTierWindowCoordinator:
    """Routes allowlisted pop-out chats into the fast lane and deduplicates main-window fallbacks."""

    @staticmethod
    def plan_lanes(
        allowed_targets: Iterable[str],
        all_windows: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        clean_targets: List[str] = []
        seen_target_keys: set[str] = set()
        for raw_t in allowed_targets or []:
            t = str(raw_t or "").strip()
            if not t:
                continue
            key = normalize_chat_name(t).casefold()
            if key not in seen_target_keys:
                seen_target_keys.add(key)
                clean_targets.append(t)

        fast_lane_popouts: List[Dict[str, Any]] = []
        protected_read_only_popouts: List[Dict[str, Any]] = []
        main_windows: List[Dict[str, Any]] = []
        fast_lane_keys: set[str] = set()

        for raw_win in all_windows or []:
            if not isinstance(raw_win, dict):
                continue
            title = str(raw_win.get("title") or "").strip()
            is_main = bool(raw_win.get("isMainWindow"))
            wid = int(raw_win.get("windowID") or 0)
            app_id = str(raw_win.get("appId") or "wechat")
            app_label = str(raw_win.get("appLabel") or ("企业微信" if app_id == "wecom" else "微信"))

            if is_main:
                main_windows.append({
                    "windowID": wid,
                    "appId": app_id,
                    "appLabel": app_label,
                    "title": title,
                    "dHash64": str(raw_win.get("dHash64") or ""),
                    "bounds": raw_win.get("bounds") or {},
                })
                continue

            matched_target: Optional[str] = None
            if title:
                for t in clean_targets:
                    if _matches_target(t, title):
                        matched_target = t
                        break

            if matched_target is not None:
                t_key = normalize_chat_name(matched_target).casefold()
                if t_key not in fast_lane_keys:
                    fast_lane_keys.add(t_key)
                    fast_lane_popouts.append({
                        "target": matched_target,
                        "windowID": wid,
                        "appId": app_id,
                        "appLabel": app_label,
                        "title": title,
                        "dHash64": str(raw_win.get("dHash64") or ""),
                        "bounds": raw_win.get("bounds") or {},
                        "zeroSwitch": True,
                        "lane": "fast_popout",
                    })
                    continue

            protected_read_only_popouts.append({
                "windowID": wid,
                "appId": app_id,
                "appLabel": app_label,
                "title": title or (f"窗口#{wid}" if wid else "未命名小窗"),
                "bounds": raw_win.get("bounds") or {},
                "readOnly": True,
                "reason": "duplicate_popout" if matched_target else "non_allowlisted_popout",
            })

        main_window_fallback_targets = [
            t for t in clean_targets
            if normalize_chat_name(t).casefold() not in fast_lane_keys
        ]
        return {
            "fastLanePopouts": fast_lane_popouts,
            "mainWindowFallbackTargets": main_window_fallback_targets,
            "protectedReadOnlyPopouts": protected_read_only_popouts,
            "mainWindows": main_windows,
        }


class MultiWindowScheduler:
    """Facade combining dHash filter, sliding-window coalescer, aging heap, and two-tier lanes."""

    def __init__(
        self,
        *,
        dhash_threshold: int = 4,
        coalesce_window_seconds: float = 1.8,
        min_send_interval_seconds: float = 0.0,
    ) -> None:
        self.dhash_filter = PerceptualDHashFilter(default_threshold=dhash_threshold)
        self.coalescer = SlidingWindowCoalescer(window_seconds=coalesce_window_seconds)
        self.priority_scheduler = AgingPriorityScheduler(
            min_send_interval_seconds=min_send_interval_seconds
        )
        self.coordinator = TwoTierWindowCoordinator()
        self.last_lanes: Dict[str, Any] = {
            "fastLanePopouts": [],
            "mainWindowFallbackTargets": [],
            "protectedReadOnlyPopouts": [],
            "mainWindows": [],
        }
        self.last_round: Optional[Dict[str, Any]] = None
