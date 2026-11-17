"""Isolated WKWebView recommendation preview; no native WeChat or model access."""
import argparse
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import threading
import time
from pathlib import Path

from .engine import WeChatControlEngine
from .mcp_server import create_http_server
from .workbench import ReviewLedger, Workbench, WorkbenchError

SAMPLES = [
    ("演练同事", "🧪 unknown_topic_724", "10:40"),
    ("演练好友", "请问试用期限是几天？", "10:41"),
]


class PreviewWorkbench(Workbench):
    def status(self):
        return {"connection": "isolated", "canRead": True, "canSend": False}

    def capture(self):
        name, text, stamp = SAMPLES[-1]
        return sample_view(name, text, stamp)

    def confirm(self, *args):
        raise WorkbenchError("preview_no_send", 403)


def sample_view(name, text, stamp):
    return {"headerTitle": name, "token": "isolated-fixture",
            "bubbles": [{"direction": "peer", "text": text, "timeMarker": stamp}]}


def start_preview(data):
    data.mkdir(mode=0o700, parents=True, exist_ok=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("the preview cannot contact an external service")

    engine = WeChatControlEngine(
        binary_path=data / "no-driver", audit_log_path=data / "audit.jsonl",
        auth_file_path=data / "auth.json", bindings_file_path=data / "bindings.json",
        models_config_path=data / "models.json", knowledge_db_path=data / "knowledge.sqlite",
        personas_file_path=data / "personas.json", snapshots_dir=data / "snapshots",
        reports_dir=data / "reports", monitor_state_path=data / "monitor.json",
        monitor_events_path=data / "monitor.jsonl", model_http_requester=forbidden,
    )
    engine.models.state["llmReplyEnabled"] = False
    engine.auth_grant(capabilities=["status", "read_messages"], authorized_by="isolated-preview")
    if not engine.knowledge.search_context("请问试用期限是几天？").get("entries"):
        engine.knowledge.save_entry(title="试用期限", kind="faq", keywords=["试用期限"],
                                  body="试用期是七天。到期后可在工作台查看续期选项。")
    wb = PreviewWorkbench(engine, ReviewLedger(data / "inbox.sqlite"), idle_wait=0)
    for args in SAMPLES:
        row = wb.ingest_view(sample_view(*args))
        if row["state"] == "new":
            wb.recommend(row["id"])
    return engine, wb


def progress(data):
    ledger = data / "inbox.sqlite"
    if not ledger.is_file():
        return {"mode": "isolated", "available": False}
    with sqlite3.connect(ledger.absolute().as_uri() + "?mode=ro", uri=True, timeout=3) as db:
        counts = dict(db.execute(
            "SELECT state,count(*) FROM review WHERE state IN ('new','ready','manual','adopted','deferred') GROUP BY state"))
        adopted = db.execute("SELECT count(*) FROM review_event WHERE stage='adopted'").fetchone()[0]
        deferred = db.execute("SELECT count(*) FROM review_event WHERE stage='deferred'").fetchone()[0]
        return {"mode": "isolated", "available": True, "tasksByStatus": counts,
                "draftsAdopted": adopted, "deferred": deferred, "sendEnabled": False}


def serve_mcp(data):
    # Stdio-only. No capability to write progress, inspect chats, or invoke other tools.
    tool = {"name": "wechat_workbench_progress", "description": "Read aggregate isolated workbench progress",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False}}
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or "id" not in request:
                continue
            method, params = request.get("method"), request.get("params") or {}
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "wechat-workbench-progress", "version": "1.0.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [tool]}
            elif method == "tools/call" and params.get("name") == tool["name"] and not params.get("arguments"):
                result = {"content": [{"type": "text", "text": json.dumps(progress(data))}]}
            else:
                raise ValueError("method or tool unavailable")
            output = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (sqlite3.Error, AttributeError, ValueError, TypeError):
            output = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                      "error": {"code": -32601, "message": "Request unavailable"}}
        print(json.dumps(output), flush=True)


def validate_integrated_live(data, options, *, resources=None, builds=None):
    """Recheck the signed-bundle and fresh, private SanDisk profile contract in the service."""
    resources = resources or Path(__file__).resolve().parents[1]
    builds = builds or Path("/Volumes/SanDisk/Builds/wechat-studio")
    run = resources.parents[2] if len(resources.parents) > 2 else builds
    if (len(options) != 3 or not resources.is_absolute() or run.parent != builds
            or resources != run / "WeBot.app" / "Contents" / "Resources"
            or resources.resolve() != resources
            or not (resources / "integrated-rehearsal").is_file()):
        raise ValueError("live pilot requires the bundled WeBot candidate on SanDisk")
    driver, title, fact = options
    expected = resources / "wechat-vision-ax"
    if Path(driver) != expected or expected.resolve() != expected or not expected.is_file() or not os.access(expected, os.X_OK):
        raise ValueError("live pilot requires the bundled native driver")
    if (data.parent != run
            or not re.fullmatch(r"live-test-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.profile", data.name)
            or data.resolve() != data or not data.is_dir()
            or stat.S_IMODE(data.stat().st_mode) != 0o700 or any(data.iterdir())):
        raise ValueError("live pilot requires an unused, private candidate profile under its SanDisk run")
    for value, maximum in ((title, 120), (fact, 260)):
        if (not value or value != value.strip() or len(value) > maximum or value.startswith("-")
                or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in value)):
            raise ValueError("live pilot requires a precise conversation title and short test knowledge")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["serve", "progress-mcp", "guided-serve", "guided-live", "integrated-serve", "integrated-live"])
    parser.add_argument("data", type=Path)
    parser.add_argument("live_options", nargs="*")
    args = parser.parse_args()
    if args.mode in ("guided-serve", "guided-live", "integrated-serve", "integrated-live"):
        from .guided_preview import serve
        if args.mode == "integrated-live":
            try:
                validate_integrated_live(args.data, args.live_options)
            except (OSError, ValueError) as exc:
                parser.error(str(exc))
            serve(args.data, *args.live_options, integrated=True)
        elif args.mode == "guided-live" and len(args.live_options) == 3:
            serve(args.data, *args.live_options)
        elif args.mode in ("guided-serve", "integrated-serve") and not args.live_options:
            serve(args.data, integrated=args.mode == "integrated-serve")
        else:
            parser.error("invalid guided preview arguments")
        return
    if args.mode == "progress-mcp":
        serve_mcp(args.data)
        return
    parent = os.getppid()

    def stop_when_orphaned():
        while True:
            if os.getppid() != parent:
                os._exit(0)
            time.sleep(1)

    threading.Thread(target=stop_when_orphaned, daemon=True).start()
    engine, wb = start_preview(args.data)
    key = secrets.token_hex(32)
    with create_http_server(engine, port=0, workbench=wb, preview_secret=key) as server:
        print(json.dumps({"port": server.server_port, "token": key, "mode": "isolated"}), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
