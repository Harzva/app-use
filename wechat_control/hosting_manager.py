"""首页「一键托管好友」的后台托管循环（自 engine.py 拆出的独立模块）。

对托管目标按固定间隔反复执行 monitor_once(auto_reply=True, confirm_send=True)；
状态原子落盘 logs/hosting_state.json，崩溃后由 engine.resume_from_state 自动恢复。
"""
from __future__ import annotations

import json
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .io_utils import atomic_write_json
from .resource_governor import govern as _govern_logs


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HostingManager:
    """首页「一键托管好友」的后台托管循环。

    对托管目标按固定间隔反复执行 monitor_once(auto_reply=True, confirm_send=True)，
    即「机器人只负责被托管好友的真实回复」。单轮失败不终止托管；
    全部请求复用注入的 fetchImpl/native 超时；状态原子落盘供首页展示。
    """

    def __init__(
        self,
        engine: "WeChatControlEngine",
        state_path: Path,
        interval_seconds: float = 3.5,
    ) -> None:
        self._engine = engine
        self._state_path = Path(state_path)
        self._interval = max(2.0, float(interval_seconds))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._targets: List[str] = []
        self._enabled = False
        self._started_at: Optional[str] = None
        self._last_round: Dict[str, Any] = {}
        self._history_appended_total = 0
        self._last_govern_at = 0.0
        self._govern_interval = 3600.0  # 资源治理（日志轮转/孤儿快照清理）每小时一次

    def start(self, targets: List[str]) -> Dict[str, Any]:
        clean = [str(t).strip() for t in (targets or []) if str(t).strip()]
        if not clean:
            return {"ok": False, "error": "HOSTING_TARGETS_REQUIRED"}
        with self._lock:
            already = bool(self._enabled and self._thread and self._thread.is_alive())
            self._targets = clean
            self._enabled = True
            self._started_at = self._utc_now()
            if not already:
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="wechat-hosting-loop", daemon=True)
                self._thread.start()
        self._persist()
        return {"ok": True, **self.status()}

    def add_target(self, target: str, *, auto_start: bool = True) -> Dict[str, Any]:
        """将单个联系人增量加入托管目标列表；默认若未运行则启动托管循环。"""
        clean = str(target or "").strip()
        if not clean:
            return {"ok": False, "error": "HOSTING_TARGET_REQUIRED"}
        from .safety import normalize_chat_name

        norm_new = normalize_chat_name(clean).casefold()
        with self._lock:
            existing_keys = {normalize_chat_name(t).casefold() for t in self._targets if str(t).strip()}
            if norm_new not in existing_keys:
                self._targets = [*self._targets, clean]
            already_running = bool(self._enabled and self._thread and self._thread.is_alive())
            if auto_start:
                self._enabled = True
                if not self._started_at:
                    self._started_at = self._utc_now()
                if not already_running:
                    self._stop.clear()
                    self._thread = threading.Thread(target=self._run, name="wechat-hosting-loop", daemon=True)
                    self._thread.start()
        self._persist()
        return {"ok": True, "added": clean, **self.status()}

    def remove_target(self, target: str) -> Dict[str, Any]:
        """从托管目标列表移除单个联系人；列表清空时自动停止托管循环。"""
        clean = str(target or "").strip()
        if not clean:
            return {"ok": False, "error": "HOSTING_TARGET_REQUIRED"}
        from .safety import normalize_chat_name

        norm_rm = normalize_chat_name(clean).casefold()
        thread_to_join: Optional[threading.Thread] = None
        with self._lock:
            kept: List[str] = []
            removed = False
            for item in self._targets:
                if normalize_chat_name(item).casefold() == norm_rm:
                    removed = True
                else:
                    kept.append(item)
            self._targets = kept
            if not self._targets and self._enabled:
                self._enabled = False
                self._started_at = None
                self._stop.set()
                thread_to_join = self._thread
        if thread_to_join and thread_to_join.is_alive():
            thread_to_join.join(timeout=5.0)
        self._persist()
        return {"ok": True, "removed": clean, "wasPresent": removed, **self.status()}

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            self._enabled = False
            self._targets = []
            self._started_at = None
            self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
        self._persist()
        return self.status()

    def resume_from_state(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """进程异常退出后，从落盘状态恢复托管循环。

        语义：磁盘状态 enabled=true 且 targets 非空（即上次没有正常 stop）→ 恢复；
        已在运行则幂等跳过。是否恢复由 engine 决定（含授权 fail-closed 检查）。
        """
        if not isinstance(doc, dict) or not doc.get("enabled"):
            return {"ok": False, "reason": "hosting_not_enabled_on_disk"}
        targets = [str(t).strip() for t in (doc.get("targets") or []) if str(t).strip()]
        if not targets:
            return {"ok": False, "reason": "hosting_targets_missing"}
        with self._lock:
            if self._enabled and self._thread and self._thread.is_alive():
                return {"ok": True, "resumed": False, "alreadyRunning": True, **self.status()}
            self._targets = targets
            self._enabled = True
            self._started_at = self._utc_now()
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="wechat-hosting-loop", daemon=True)
            self._thread.start()
        self._persist()
        return {"ok": True, "resumed": True, "targets": targets, **self.status()}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "running": bool(self._enabled and self._thread and self._thread.is_alive()),
                "targets": list(self._targets),
                "intervalSeconds": self._interval,
                "sendMode": "confirm_send",
                "startedAt": self._started_at,
                "lastRound": dict(self._last_round),
                "historyAppendedTotal": self._history_appended_total,
            }

    def _maybe_govern(self) -> None:
        """低频资源治理：日志轮转与孤儿快照清理（每小时一次，失败不影响托管）。"""
        import time as _time
        now = _time.time()
        if now - self._last_govern_at < self._govern_interval:
            return
        self._last_govern_at = now
        try:
            rep = _govern_logs(self._engine.plugin_root)
            if rep.get("snapshots", {}).get("removed") or any(
                (rep.get(k) or {}).get("rotated") for k in ("rotate_audit.jsonl", "rotate_monitor_events.jsonl")
            ):
                self._engine.audit.log("resource_governor", "ok", {"freedTotalBytes": rep.get("freedTotalBytes", 0)})
        except Exception:
            pass  # 治理失败不影响托管主循环

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                res = self._engine.monitor_once(auto_reply=True, confirm_send=True)
                self._last_round = {
                    "at": self._utc_now(),
                    "ok": bool(res.get("ok")),
                    "repliesDispatched": int(res.get("repliesDispatched", 0) or 0),
                }
                self._engine.audit.log(
                    "hosting_loop",
                    "round",
                    {"targets": list(self._targets), "repliesDispatched": self._last_round["repliesDispatched"]},
                )
                try:
                    sync_res = self._engine.sync_hosting_histories()
                    self._history_appended_total += int(sync_res.get("appended", 0) or 0)
                except Exception:
                    pass  # 历史回写失败不影响托管主循环
            except Exception as exc:  # 单轮失败不终止托管：记录后继续下一轮
                self._last_round = {"at": self._utc_now(), "ok": False, "error": str(exc)}
                try:
                    self._engine.audit.log("hosting_loop", "error", {"error": str(exc)})
                except Exception:
                    pass
            self._persist()
            self._maybe_govern()
            # 轮询间隔抖动 ±15%：固定周期是「固定模式操作序列」特征（反自动化对抗）
            self._stop.wait(self._interval * random.uniform(0.85, 1.15))

    def _persist(self) -> None:
        doc = self.status()
        try:
            atomic_write_json(self._state_path, doc)
        except OSError:
            pass

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
