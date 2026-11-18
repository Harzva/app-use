#!/usr/bin/env python3
"""Human mouse/keyboard activity detection & anti-contention cooldown guard."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class HumanActivityGuard:
    """Stop RPA automation immediately when human mouse/keyboard activity is detected."""

    def __init__(
        self,
        *,
        state_path: Path,
        hid_query_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        clock_fn: Optional[Callable[[], float]] = None,
        default_idle_resume_seconds: float = 45.0,
        default_cooldown_seconds: float = 45.0,
        cursor_drift_tolerance_px: float = 18.0,
    ) -> None:
        self.state_path = Path(state_path)
        self._hid_query_fn = hid_query_fn
        self._clock = clock_fn or time.time
        self.cursor_drift_tolerance_px = float(cursor_drift_tolerance_px)
        self._state: Dict[str, Any] = {
            "enabled": True,
            "idle_resume_seconds": float(default_idle_resume_seconds),
            "cooldown_seconds": float(default_cooldown_seconds),
            "cursor_drift_tolerance_px": float(cursor_drift_tolerance_px),
            "status": "idle_ready",
            "last_rpa_action_at": 0.0,
            "last_rpa_kind": "",
            "last_rpa_cursor": None,
            "last_observed_cursor": None,
            "last_human_activity_at": 0.0,
            "cooldown_until": 0.0,
            "interventions_detected": 0,
            "last_trigger_reason": "",
            "updated_at": "",
        }
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._state.update(data)
        except Exception:
            pass

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        self.state_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _dist(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> Optional[float]:
        if not isinstance(a, dict) or not isinstance(b, dict):
            return None
        if "x" not in a or "y" not in a or "x" not in b or "y" not in b:
            return None
        try:
            dx = float(a["x"]) - float(b["x"])
            dy = float(a["y"]) - float(b["y"])
            return math.hypot(dx, dy)
        except (TypeError, ValueError):
            return None

    def configure(
        self,
        *,
        enabled: Optional[bool] = None,
        idle_resume_seconds: Optional[float] = None,
        cooldown_seconds: Optional[float] = None,
        reset_cooldown: bool = False,
    ) -> Dict[str, Any]:
        if enabled is not None:
            self._state["enabled"] = bool(enabled)
        if idle_resume_seconds is not None:
            self._state["idle_resume_seconds"] = max(3.0, min(600.0, float(idle_resume_seconds)))
        if cooldown_seconds is not None:
            self._state["cooldown_seconds"] = max(3.0, min(600.0, float(cooldown_seconds)))
        if reset_cooldown:
            self._state["cooldown_until"] = 0.0
            self._state["status"] = "idle_ready" if self._state["enabled"] else "disabled"
            self._state["last_trigger_reason"] = ""
        self._save()
        return self.check_can_operate()

    def record_rpa_action(
        self,
        *,
        action: str = "",
        cursor_x: Optional[float] = None,
        cursor_y: Optional[float] = None,
    ) -> None:
        now = float(self._clock())
        self._state["last_rpa_action_at"] = now
        self._state["last_rpa_kind"] = str(action or "")
        if cursor_x is not None and cursor_y is not None:
            pt = {"x": round(float(cursor_x), 1), "y": round(float(cursor_y), 1)}
            self._state["last_rpa_cursor"] = pt
            self._state["last_observed_cursor"] = pt
        self._save()

    def _query_hid(self) -> Dict[str, Any]:
        if self._hid_query_fn is None:
            return {"ok": False, "error": "no_hid_query_fn"}
        try:
            res = self._hid_query_fn()
            if isinstance(res, dict) and isinstance(res.get("hidIdle"), dict):
                return res["hidIdle"]
            if isinstance(res, dict):
                return res
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "invalid_hid_payload"}

    def check_can_operate(self, hid_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = float(self._clock())
        enabled = bool(self._state.get("enabled", True))
        idle_thresh = float(self._state.get("idle_resume_seconds", 45.0))
        cooldown_sec = float(self._state.get("cooldown_seconds", 45.0))
        tol_px = float(self._state.get("cursor_drift_tolerance_px", self.cursor_drift_tolerance_px))

        if not enabled:
            prev_status = self._state.get("status")
            self._state["status"] = "disabled"
            if prev_status != "disabled":
                self._save()
            return {
                "ok": True,
                "enabled": False,
                "canOperate": True,
                "status": "disabled",
                "idleResumeSeconds": idle_thresh,
                "cooldownSeconds": cooldown_sec,
                "remainingCooldownSeconds": 0.0,
                "anyInputIdleSeconds": None,
                "reason": "guard_disabled",
            }

        raw_hid = hid_info if isinstance(hid_info, dict) else self._query_hid()
        frontmost_app = str(raw_hid.get("frontmostApp") or "").strip() if isinstance(raw_hid, dict) else ""
        hid = raw_hid["hidIdle"] if (isinstance(raw_hid, dict) and isinstance(raw_hid.get("hidIdle"), dict)) else raw_hid
        if not frontmost_app and isinstance(hid, dict):
            frontmost_app = str(hid.get("frontmostApp") or "").strip()

        prev_snapshot = (
            self._state.get("status"),
            round(float(self._state.get("cooldown_until") or 0.0), 3),
            int(self._state.get("interventions_detected") or 0),
            str(self._state.get("last_trigger_reason") or ""),
        )

        # Fail-closed when HID telemetry itself is unavailable or invalid
        has_telemetry = isinstance(hid, dict) and any(
            k in hid for k in ("anyInputIdleSeconds", "mouseIdleSeconds", "keyboardIdleSeconds", "cursorPosition")
        )
        if not isinstance(hid, dict) or (hid.get("ok") is False and not has_telemetry) or not has_telemetry:
            self._state["status"] = "hid_unavailable"
            self._state["last_trigger_reason"] = str((hid or {}).get("error") or "hid_telemetry_unavailable")
            if prev_snapshot[0] != "hid_unavailable":
                self._save()
            return {
                "ok": False,
                "enabled": True,
                "canOperate": False,
                "status": "hid_unavailable",
                "idleResumeSeconds": idle_thresh,
                "cooldownSeconds": cooldown_sec,
                "remainingCooldownSeconds": max(0.0, float(self._state.get("cooldown_until") or 0.0) - now),
                "anyInputIdleSeconds": None,
                "mouseIdleSeconds": None,
                "keyboardIdleSeconds": None,
                "cursorPosition": None,
                "interventionsDetected": int(self._state.get("interventions_detected") or 0),
                "triggerReason": self._state["last_trigger_reason"],
                "reason": "hid_telemetry_unavailable",
            }

        # Fail-closed when macOS SecurityAgent (authentication/keychain prompt) is frontmost
        if "SecurityAgent" in frontmost_app:
            self._state["status"] = "security_agent_paused"
            self._state["last_trigger_reason"] = f"macos_security_agent_frontmost:{frontmost_app}"
            if prev_snapshot[0] != "security_agent_paused":
                self._save()
            return {
                "ok": True,
                "enabled": True,
                "canOperate": False,
                "status": "security_agent_paused",
                "idleResumeSeconds": idle_thresh,
                "cooldownSeconds": cooldown_sec,
                "remainingCooldownSeconds": max(0.0, float(self._state.get("cooldown_until") or 0.0) - now),
                "anyInputIdleSeconds": hid.get("anyInputIdleSeconds"),
                "mouseIdleSeconds": hid.get("mouseIdleSeconds"),
                "keyboardIdleSeconds": hid.get("keyboardIdleSeconds"),
                "cursorPosition": hid.get("cursorPosition") if isinstance(hid.get("cursorPosition"), dict) else None,
                "interventionsDetected": int(self._state.get("interventions_detected") or 0),
                "triggerReason": self._state["last_trigger_reason"],
                "reason": "macos_security_agent_frontmost",
            }

        any_idle_raw = hid.get("anyInputIdleSeconds")
        mouse_idle_raw = hid.get("mouseIdleSeconds")
        kb_idle_raw = hid.get("keyboardIdleSeconds")
        cursor_pos = hid.get("cursorPosition") if isinstance(hid.get("cursorPosition"), dict) else None

        last_rpa_at = float(self._state.get("last_rpa_action_at") or 0.0)
        since_rpa = max(0.0, now - last_rpa_at) if last_rpa_at > 0 else 1e9
        last_rpa_cursor = self._state.get("last_rpa_cursor")
        last_obs_cursor = self._state.get("last_observed_cursor")

        cursor_drift_from_rpa = self._dist(cursor_pos, last_rpa_cursor)
        cursor_drift_from_obs = self._dist(cursor_pos, last_obs_cursor)

        human_triggered = False
        trigger_reason = ""

        # Check cursor displacement caused by human outside RPA self-action window
        if cursor_drift_from_obs is not None and cursor_drift_from_obs > tol_px:
            # Only exempt if an RPA action JUST occurred and cursor sits near that RPA target
            if not (since_rpa <= 1.2 and cursor_drift_from_rpa is not None and cursor_drift_from_rpa <= tol_px):
                human_triggered = True
                trigger_reason = f"mouse_moved_delta_{round(cursor_drift_from_obs, 1)}px"

        if any_idle_raw is not None:
            any_idle = max(0.0, float(any_idle_raw))
            mouse_idle = max(0.0, float(mouse_idle_raw if mouse_idle_raw is not None else any_idle))
            kb_idle = max(0.0, float(kb_idle_raw if kb_idle_raw is not None else any_idle))
            hw_kb_raw = hid.get("hardwareKeyboardIdleSeconds")
            hw_kb_idle = max(0.0, float(hw_kb_raw if hw_kb_raw is not None else kb_idle))

            # Hardware keyboard input is NEVER exempted even right after paste-and-verify,
            # so any physical user typing pauses automation immediately.
            human_typing_active = bool(hid.get("keyboardActive")) and (hw_kb_idle < idle_thresh)
            is_self_rpa_window = (
                since_rpa <= 1.2
                and (cursor_drift_from_rpa is None or cursor_drift_from_rpa <= tol_px)
                and hw_kb_idle >= 2.0
                and kb_idle >= 1.2
            )
            if (any_idle < idle_thresh and not is_self_rpa_window) or (human_typing_active and not (since_rpa <= 1.2 and hw_kb_idle >= 2.0)):
                human_triggered = True
                if not trigger_reason:
                    src = "keyboard" if (kb_idle <= mouse_idle or human_typing_active) else "mouse"
                    trigger_reason = f"{src}_active_idle_{round(min(any_idle, hw_kb_idle), 1)}s_lt_{round(idle_thresh, 0)}s"
        else:
            any_idle = None
            mouse_idle = None
            kb_idle = None

        prev_status = self._state.get("status", "idle_ready")
        cooldown_until = float(self._state.get("cooldown_until") or 0.0)

        if human_triggered:
            inferred_activity_at = (
                now
                if (any_idle is None or "mouse_moved" in trigger_reason)
                else max(0.0, now - any_idle)
            )
            prev_human_at = float(self._state.get("last_human_activity_at") or 0.0)
            is_new_intervention = (
                prev_status != "human_active_cooldown"
                or (inferred_activity_at - prev_human_at) > 1.0
            )
            if is_new_intervention:
                self._state["interventions_detected"] = int(self._state.get("interventions_detected") or 0) + 1
            new_cooldown_until = max(cooldown_until, inferred_activity_at + cooldown_sec)
            self._state["last_human_activity_at"] = max(prev_human_at, inferred_activity_at)
            self._state["cooldown_until"] = new_cooldown_until
            self._state["status"] = "human_active_cooldown"
            self._state["last_trigger_reason"] = trigger_reason
            cooldown_until = new_cooldown_until
        else:
            # Check whether cooldown has expired AND hardware input has remained idle
            in_cooldown = now < cooldown_until
            idle_not_met = (any_idle is not None and any_idle < idle_thresh and since_rpa > 1.2)
            if in_cooldown or idle_not_met:
                self._state["status"] = "human_active_cooldown"
            else:
                self._state["status"] = "idle_ready"

        if cursor_pos is not None:
            self._state["last_observed_cursor"] = cursor_pos

        curr_snapshot = (
            self._state.get("status"),
            round(float(self._state.get("cooldown_until") or 0.0), 3),
            int(self._state.get("interventions_detected") or 0),
            str(self._state.get("last_trigger_reason") or ""),
        )
        if curr_snapshot != prev_snapshot:
            self._save()

        remaining_cooldown = max(0.0, cooldown_until - now) if self._state["status"] == "human_active_cooldown" else 0.0
        remaining_idle = max(0.0, idle_thresh - any_idle) if (any_idle is not None and any_idle < idle_thresh and self._state["status"] == "human_active_cooldown") else 0.0
        wait_seconds = max(remaining_cooldown, remaining_idle)
        can_operate = self._state["status"] != "human_active_cooldown"

        return {
            "ok": True,
            "enabled": True,
            "canOperate": can_operate,
            "status": self._state["status"],
            "idleResumeSeconds": idle_thresh,
            "cooldownSeconds": cooldown_sec,
            "remainingCooldownSeconds": round(wait_seconds, 1),
            "anyInputIdleSeconds": round(any_idle, 1) if any_idle is not None else None,
            "mouseIdleSeconds": round(mouse_idle, 1) if mouse_idle is not None else None,
            "keyboardIdleSeconds": round(kb_idle, 1) if kb_idle is not None else None,
            "cursorPosition": cursor_pos,
            "interventionsDetected": int(self._state.get("interventions_detected") or 0),
            "triggerReason": self._state.get("last_trigger_reason") or "",
            "lastHumanActivityAt": (
                datetime.fromtimestamp(float(self._state["last_human_activity_at"]), tz=timezone.utc).astimezone().isoformat(timespec="seconds")
                if self._state.get("last_human_activity_at")
                else ""
            ),
            "cooldownUntil": (
                datetime.fromtimestamp(cooldown_until, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
                if cooldown_until > 0
                else ""
            ),
        }
