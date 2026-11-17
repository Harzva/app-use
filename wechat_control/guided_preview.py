"""Window-scoped auxiliary replies for the independent desktop candidate."""
import json
import os
import secrets
import threading
import time
from pathlib import Path

from .engine import WeChatControlEngine
from .mcp_server import create_http_server
from .workbench import ReviewLedger, Workbench, WorkbenchError

DEMO_CONTACT = "演练好友"
DEMO_QUESTION = "请问试用期限是几天？"


class GuidedWorkbench(Workbench):
    confirmation_state = "adopted"
    recommendation_space = "guided-preview"

    def __init__(self, engine, ledger, target, *, demo=False, idle_wait=90):
        super().__init__(engine, ledger, idle_wait=idle_wait)
        self.demo, self.target = demo, target
        self.control = threading.RLock()
        self.selected = None
        self.active = False
        self.epoch = 0
        self.reason = "select_window"

    def _native(self):
        return self.engine._run_native(["status"], timeout=4)

    def _choices(self, native):
        if native.get("reviewedSendProtocol") != 1 or not native.get("wechatRunning"):
            return []
        pid = native.get("wechatPID")
        if type(pid) is not int or pid < 1:
            return []
        result = []
        for idx, w in enumerate(native.get("windows") or []):
            window = w.get("windowID")
            if type(window) is not int:
                continue
            b = w.get("bounds") or {}
            label = "演练微信窗口" if self.demo else f"微信窗口 {idx+1}"
            if b.get("width") and b.get("height"):
                label += f" · {round(b['width'])} × {round(b['height'])}"
            result.append({"id": f"{pid}:{window}", "label": label, "handle": window})
        return result

    def choices(self):
        return self._choices(self._native())

    def _pause(self, reason):
        self.active = False
        self.epoch += 1
        self.reason = reason

    def status(self):
        n = self._native()
        windows = self._choices(n)
        with self.control:
            current = next((w for w in windows if w["id"] == self.selected), None)
            if self.selected and current is None:
                self.selected = None
                self._pause("window_lost")
            if self.active and not n.get("screenCaptureTrusted"):
                self._pause("screen_permission")
            can_read = bool(current and n.get("screenCaptureTrusted"))
            return {"connection": "isolated" if self.demo else ("ready" if can_read else "live_idle"),
                    "canRead": can_read, "canSend": can_read and len(windows) == 1
                    and bool(n.get("accessibilityTrusted")) and bool(n.get("postEventTrusted"))
                    and self.engine.auth_gate.is_allowed("send_text_live"),
                    "guided": True, "demo": self.demo, "target": self.target,
                    "window": current, "watching": self.active, "monitorReason": self.reason,
                    "screenPermission": bool(n.get("screenCaptureTrusted")), "windows": windows}

    def select(self, token):
        if not isinstance(token, str) or token not in {w["id"] for w in self.choices()}:
            raise WorkbenchError("window_lost")
        # Window replacement and any pending manual send share the same input lock.
        if not self.input_lock.acquire(blocking=False):
            raise WorkbenchError("input_busy")
        try:
            with self.control:
                self.selected = token
                self._pause("monitor_stopped")
        finally:
            self.input_lock.release()
        return self.status()

    def set_monitor(self, action):
        if action not in ("start", "pause"):
            raise WorkbenchError("invalid_action", 400)
        if action == "pause":
            with self.control:
                self._pause("monitor_paused")
        else:
            status = self.status()
            with self.control:
                if not self.selected or not status["window"] or status["window"]["id"] != self.selected:
                    raise WorkbenchError("select_window")
                if not status["canRead"]:
                    raise WorkbenchError("screen_permission")
                self.active = True
                self.epoch += 1
                self.reason = "monitor_watching"
        return self.status()

    def capture(self):
        n = self._native()
        with self.control:
            w = next((w for w in self._choices(n) if w["id"] == self.selected), None)
            if not w:
                self.selected = None
                self._pause("window_lost")
                raise WorkbenchError("window_lost")
        if not n.get("screenCaptureTrusted"):
            raise WorkbenchError("screen_permission")
        view = self.read_window(n, w["handle"])
        if view["headerTitle"] != self.target:
            raise WorkbenchError("conversation_changed")
        return view

    def ingest(self):
        self.engine._require("read_messages")
        with self.control:
            if not self.active:
                raise WorkbenchError("monitor_paused")
            epoch = self.epoch
        if not self.input_lock.acquire(blocking=False):
            return None
        try:
            with self.control:
                if not self.active or epoch != self.epoch:
                    return None
            try:
                view = self.capture()
            except WorkbenchError as exc:
                with self.control:
                    if self.epoch == epoch:
                        self._pause(exc.code)
                raise
            with self.control:
                # A paused or reselected window cannot publish an in-flight result.
                if not self.active or epoch != self.epoch:
                    return None
                row = self.ingest_view(view)
                return self.recommend(row["id"]) if row and row["state"] == "new" else row
        finally:
            self.input_lock.release()

    def monitor_loop(self):
        while True:
            time.sleep(1.5)
            with self.control:
                active = self.active
            if not active:
                continue
            try:
                self.ingest()
            except WorkbenchError:
                pass
            except Exception:
                with self.control:
                    self._pause("capture_failed")


def create_guided(data, driver=None, target=None, fact=None):
    demo = driver is None
    if not demo and not target:
        raise ValueError("An explicitly authorized exact test conversation is required")
    target = DEMO_CONTACT if demo else target
    data.mkdir(mode=0o700, parents=True, exist_ok=True)

    def no_network(*args, **kwargs):
        raise AssertionError("External model access is disabled in this candidate")

    engine = WeChatControlEngine(
        binary_path=driver or data / "unused", audit_log_path=data / "audit.jsonl",
        auth_file_path=data / "auth.json", bindings_file_path=data / "bindings.json",
        knowledge_db_path=data / "knowledge.sqlite", models_config_path=data / "models.json",
        personas_file_path=data / "personas.json", snapshots_dir=data / "snapshots",
        reports_dir=data / "reports", monitor_state_path=data / "monitor.json",
        monitor_events_path=data / "monitor.jsonl", model_http_requester=no_network,
        allowed_groups=[target],
    )
    engine.models.state["llmReplyEnabled"] = False
    engine.auth_grant(capabilities=["status", "read_messages", "send_text_live"], authorized_by="guided-candidate")
    # Every live run starts with a new private profile and one explicit recipient.
    engine.bind_contact(target, role="test", scheduled_enabled=False, auto_reply_enabled=False)
    if demo:
        fact = "试用期是七天。"
    if fact and not engine.knowledge.list_entries(space_id=GuidedWorkbench.recommendation_space, limit=1).get("entries"):
        engine.knowledge.save_entry(title="试用期限" if demo else "操作人提供的测试知识",
                                    body=fact, keywords=["试用期限"] if demo else [], kind="faq",
                                    space_id=GuidedWorkbench.recommendation_space)
    wb = GuidedWorkbench(engine, ReviewLedger(data / "inbox.sqlite"), target, demo=demo, idle_wait=0 if demo else 90)
    state = {"available": True, "calls": 0, "reads": 0, "outgoing": [], "deliver": True, "chat": target}

    if demo:
        def native(args, timeout=20):
            if args == ["status"]:
                return {"ok": True, "reviewedSendProtocol": 1, "wechatPID": 137,
                        "wechatRunning": state["available"], "screenCaptureTrusted": True,
                        "accessibilityTrusted": True, "postEventTrusted": True,
                        "windows": ([{"windowID": 8, "bounds": {"width": 900, "height": 700}}]
                                    if state["available"] else [])}
            if args[0] == "paste-and-verify":
                assert args[-1] == "--send" and args[args.index("--review-window") + 1] == "8"
                state["calls"] += 1
                if state["deliver"]:
                    state["outgoing"].append(args[args.index("--text") + 1])
                return {"ok": True, "sent": True}
            raise AssertionError("No macOS driver is accessible in rehearsal")
        def source(n, window):
            state["reads"] += 1
            if state["chat"] != target:
                raise WorkbenchError("conversation_changed")
            return {"headerTitle": target, "token": f"137:{window}", "window": window,
                    "bubbles": [{"direction": "peer", "text": DEMO_QUESTION, "timeMarker": "10:45"}]
                    + [{"direction": "self", "text": t} for t in state["outgoing"]]}
        engine._run_native = native
        engine.human_guard.check_can_operate = lambda: {"canOperate": True}
        wb.read_window = source
    return engine, wb, state


def serve(data, driver=None, target=None, fact=None, *, integrated=False):
    parent = os.getppid()
    def watchdog():
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)
    threading.Thread(target=watchdog, daemon=True).start()
    engine, wb, _ = create_guided(Path(data), Path(driver) if driver else None, target, fact)
    if integrated and wb.demo:
        archive = engine.article_exporter.export_root / "sample"
        archive.mkdir(parents=True, exist_ok=True)
        sample = archive / "metadata.json"
        if not sample.exists():
            sample.write_text(json.dumps({
                "title": "样本归档：试用须知", "account": "演练资料",
                "exported_at": "2026-11-16T00:00:00+08:00",
            }, ensure_ascii=False), encoding="utf-8")
    threading.Thread(target=wb.monitor_loop, daemon=True).start()
    key = secrets.token_hex(32)
    with create_http_server(engine, port=0, workbench=wb, preview_secret=key,
                            guided=True, integrated=integrated) as server:
        mode = ("studio-integrated" if wb.demo else "studio-integrated-live") if integrated else "isolated"
        print(json.dumps({"port": server.server_port, "token": key, "mode": mode, "protocol": 1}), flush=True)
        server.serve_forever()
