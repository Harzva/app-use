"""User-controlled observation of the visible WeChat window without input events."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .auth_gate import StudioPluginUnauthorizedError
from .live_inspector import WeChatLiveInspector


class BackgroundObserver:
    """One observer per local server. Keep only the latest aggregate sample."""

    def __init__(self, engine: Any, *, interval: float = 10.0) -> None:
        self._engine = engine
        self._interval = interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._closed = False
        self._state: Dict[str, Any] = {
            "state": "standby",
            "running": False,
            "checks": 0,
            "lastCheckedAt": None,
            "visibleSessions": None,
            "unreadSessions": None,
            "errorCode": None,
        }

    def _require_observation(self) -> None:
        for capability in ("status", "read_sessions", "ocr"):
            self._engine._require(capability)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start(self) -> Dict[str, Any]:
        self._require_observation()
        with self._lock:
            if self._worker is not None or self._closed:
                return dict(self._state)
            self._stop.clear()
            self._state.update(state="starting", running=True, errorCode=None)
            self._worker = threading.Thread(target=self._run, name="wechat-background-observation", daemon=True)
            self._worker.start()
            return dict(self._state)

    def _request_stop(self) -> None:
        self._stop.set()
        self._state.update(
            state="stopping" if self._worker is not None else "standby",
            running=False, errorCode=None, visibleSessions=None, unreadSessions=None,
        )

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            self._request_stop()
            return dict(self._state)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._request_stop()
            worker = self._worker
        if worker is not None:
            # At most one bounded status/OCR request can remain in flight.
            worker.join(timeout=11.0)

    @staticmethod
    def _result(state: str, *, error: Optional[str] = None, visible: Optional[int] = None,
                unread: Optional[int] = None) -> Dict[str, Any]:
        return {"state": state, "errorCode": error, "visibleSessions": visible, "unreadSessions": unread}

    def _sample(self) -> Dict[str, Any]:
        self._require_observation()
        status = self._engine._run_native(["status"], timeout=3.0)
        if status.get("ok") is not True:
            return self._result("failed", error="native_status_failed")
        # Status orders the main window first. Ignore utility windows too small to show the chat list.
        window = next((w for w in (status.get("windows") or [])
                       if w.get("windowID") and (w.get("bounds") or {}).get("width", 0) >= 420
                       and (w.get("bounds") or {}).get("height", 0) >= 320), None)
        if status.get("wechatRunning") is not True or window is None:
            return self._result("waiting_no_visible_window")
        if status.get("screenCaptureTrusted") is not True:
            return self._result("failed", error="screen_capture_denied")
        self._require_observation()
        if self._stop.is_set():
            return self._result("standby")

        # Passing neither --out nor any input command keeps snapshots in native process memory.
        window_id = window["windowID"]
        frame = self._engine._run_native(
            ["capture-ocr", "--no-activate", "--window-id", str(window_id)], timeout=10.0,
        )
        if frame.get("ok") is not True:
            code = frame.get("error_code")
            if code in ("wechat_not_running", "no_window", "window_not_found"):
                return self._result("waiting_no_visible_window")
            return self._result("failed", error="screen_capture_denied" if code == "screen_capture_denied"
                                else "capture_failed")
        if frame.get("windowID") != window_id:
            return self._result("waiting_no_visible_window")
        self._require_observation()
        bounds = frame.get("windowBounds") or window["bounds"]
        width, height = float(bounds["width"]), float(bounds["height"])
        # Vision centers are in image pixels; the shared chat-list parser expects window points.
        sx = width / float(frame["imageWidth"])
        sy = height / float(frame["imageHeight"])
        elements = [
            {"text": item["text"], "center": {"x": item["center"]["x"] * sx, "y": item["center"]["y"] * sy}}
            for item in (frame.get("elements") or [])
        ]
        rows = WeChatLiveInspector._cluster_session_rows(elements, WeChatLiveInspector._split_x(width), height)
        return self._result("running", visible=len(rows), unread=sum(bool(row["unreadBadge"]) for row in rows))

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                revoked = False
                try:
                    sample = self._sample()
                except StudioPluginUnauthorizedError:
                    sample = self._result("failed", error="authorization_required")
                    revoked = True
                except Exception:
                    # Never put native command output, chat text or raw exceptions into the API.
                    sample = self._result("failed", error="capture_failed")
                with self._lock:
                    if self._stop.is_set():
                        break
                    self._state.update(sample, checks=self._state["checks"] + 1,
                                       lastCheckedAt=datetime.now(timezone.utc).isoformat(),
                                       running=not revoked)
                if revoked or self._stop.wait(self._interval):
                    break
        finally:
            with self._lock:
                if self._stop.is_set():
                    self._state["state"] = "standby"
                self._state["running"] = False
                self._worker = None
