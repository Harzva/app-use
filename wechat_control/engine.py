"""Unified macOS WeChat RPA + Vision OCR + WeChatBridge Control Engine.

Combines:
- Native Swift `wechat-vision-ax` binary (AXUIElement + VNRecognizeTextRequest + CGEvent)
- Safety guards (`safety.py`): ReadbackVerifier (3x circuit breaker), OutgoingMessageRegistry,
  GroupAllowlistGuard, HumanJitter, AuditLogger
- WeChatBridge importer (`bridge_importer.py`): `.zip` / `聊天记录.txt` ingestion & export
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import socket
import subprocess
import urllib.parse
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .agent_dispatcher import WeChatAgentDispatcher
from .article_exporter import WeChatArticleExporter
from .auth_gate import StudioAuthGate, StudioPluginUnauthorizedError
from .benchmark_suite import WeChatRPABenchmarkSuite
from .botstudio_bridge import BotStudioBridgeManager
from .bridge_importer import WeChatBridgeImporter
from .contact_profiler import ContactBindingStore, ContactStyleProfiler, ContextualAIChatGenerator
from .human_activity_guard import HumanActivityGuard
from .knowledge_kf_engine import DEFAULT_OPENBOT_KNOWLEDGE_DB, PersonaSwitchEngine, WeChatKnowledgeStore
from .live_inspector import WeChatLiveInspector, _matches_target, _slugify_target
from .magpie_provider_hub import MagpieProviderHub
from .media_link_analyzer import WeChatMediaLinkAnalyzer
from .realtime_monitor import _looks_like_timestamp, WeChatRealtimeMonitor
from .sales_crm_hub import WeChatSalesCRMHub
from .soul_memory_profiler import SoulMemoryProfiler
from .ui_schema import WeChatUIProtocolNavigator
from .safety import (
    AntiBanGuard,
    AuditLogger,
    GroupAllowlistGuard,
    HumanJitter,
    OutgoingMessageRegistry,
    ReadbackVerifier,
    normalize_chat_name,
)

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BINARY_PATH = DEFAULT_ROOT / "bin" / "wechat-vision-ax"
DEFAULT_AUDIT_LOG = DEFAULT_ROOT / "logs" / "audit.jsonl"
DEFAULT_AUTH_FILE = DEFAULT_ROOT / "config" / "studio_auth.json"
DEFAULT_BINDINGS_FILE = DEFAULT_ROOT / "config" / "bound_contacts.json"
DEFAULT_MODEL_PROVIDERS_FILE = DEFAULT_ROOT / "config" / "model_providers.json"
DEFAULT_KB_DB = DEFAULT_ROOT / "config" / "wechat_knowledge.sqlite"
DEFAULT_PERSONAS_FILE = DEFAULT_ROOT / "config" / "personas.json"
DEFAULT_SOUL_MEMORIES_FILE = DEFAULT_ROOT / "config" / "soul_memories.json"
DEFAULT_MONITOR_STATE = DEFAULT_ROOT / "logs" / "monitor_state.json"
DEFAULT_MONITOR_EVENTS = DEFAULT_ROOT / "logs" / "monitor_events.jsonl"
DEFAULT_SNAPSHOTS_DIR = DEFAULT_ROOT / "logs" / "snapshots"
DEFAULT_REPORTS_DIR = DEFAULT_ROOT / "logs"
DEFAULT_HOSTING_STATE = DEFAULT_ROOT / "logs" / "hosting_state.json"


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
        interval_seconds: float = 45.0,
    ) -> None:
        self._engine = engine
        self._state_path = Path(state_path)
        self._interval = max(5.0, float(interval_seconds))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._targets: List[str] = []
        self._enabled = False
        self._started_at: Optional[str] = None
        self._last_round: Dict[str, Any] = {}
        self._history_appended_total = 0

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
            # 轮询间隔抖动 ±15%：固定周期是「固定模式操作序列」特征（反自动化对抗）
            self._stop.wait(self._interval * random.uniform(0.85, 1.15))

    def _persist(self) -> None:
        doc = self.status()
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._state_path)
        except OSError:
            pass

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()


class WeChatControlEngine:
    """Orchestrates AX tree inspection, Vision OCR fallback, safe sending, and archive import."""

    def __init__(
        self,
        *,
        binary_path: Optional[Path] = None,
        audit_log_path: Optional[Path] = None,
        auth_file_path: Optional[Path] = None,
        bindings_file_path: Optional[Path] = None,
        models_config_path: Optional[Path] = None,
        model_http_requester: Optional[Any] = None,
        knowledge_db_path: Optional[Path] = None,
        personas_file_path: Optional[Path] = None,
        monitor_state_path: Optional[Path] = None,
        monitor_events_path: Optional[Path] = None,
        snapshots_dir: Optional[Path] = None,
        reports_dir: Optional[Path] = None,
        dedup_window_seconds: float = 120.0,
        allowed_groups: Optional[Iterable[str]] = None,
        jitter: Optional[HumanJitter] = None,
    ) -> None:
        self.plugin_root = DEFAULT_ROOT
        self.binary_path = Path(binary_path or os.environ.get("WECHAT_PLUGIN_NATIVE_BINARY") or DEFAULT_BINARY_PATH)
        env_audit = os.environ.get("WECHAT_PLUGIN_AUDIT_LOG")
        resolved_audit = Path(audit_log_path) if audit_log_path else (Path(env_audit) if env_audit else DEFAULT_AUDIT_LOG)
        self.audit = AuditLogger(resolved_audit)
        env_auth = os.environ.get("WECHAT_PLUGIN_AUTH_FILE")
        resolved_auth = Path(auth_file_path) if auth_file_path else (Path(env_auth) if env_auth else DEFAULT_AUTH_FILE)
        self.auth_gate = StudioAuthGate(resolved_auth)
        env_bindings = os.environ.get("WECHAT_PLUGIN_BINDINGS_FILE")
        resolved_bindings = (
            Path(bindings_file_path)
            if bindings_file_path
            else (Path(env_bindings) if env_bindings else DEFAULT_BINDINGS_FILE)
        )
        self.bindings = ContactBindingStore(resolved_bindings)
        self.profiler = ContactStyleProfiler()
        self.dedup = OutgoingMessageRegistry(dedup_window_seconds=dedup_window_seconds)
        self.allowlist = GroupAllowlistGuard(allowed_groups)
        self.jitter = jitter or HumanJitter()
        self.importer = WeChatBridgeImporter()
        resolved_snapshots = Path(snapshots_dir) if snapshots_dir else DEFAULT_SNAPSHOTS_DIR
        resolved_reports = Path(reports_dir) if reports_dir else DEFAULT_REPORTS_DIR
        self.inspector = WeChatLiveInspector(
            lambda args, timeout=15.0: self._run_native(args, timeout),
            snapshots_dir=resolved_snapshots,
            reports_dir=resolved_reports,
        )

        env_kb = os.environ.get("WECHAT_PLUGIN_KB_DB")
        if knowledge_db_path:
            resolved_kb = Path(knowledge_db_path)
        elif env_kb:
            resolved_kb = Path(env_kb)
        elif bindings_file_path or env_bindings:
            resolved_kb = resolved_bindings.parent / "wechat_knowledge.sqlite"
        elif auth_file_path:
            resolved_kb = Path(auth_file_path).parent / "wechat_knowledge.sqlite"
        else:
            resolved_kb = DEFAULT_KB_DB
        self.knowledge = WeChatKnowledgeStore(resolved_kb)

        env_models = os.environ.get("WECHAT_PLUGIN_MODELS_CONFIG")
        if models_config_path:
            resolved_models_cfg = Path(models_config_path)
        elif env_models:
            resolved_models_cfg = Path(env_models)
        elif bindings_file_path or env_bindings:
            resolved_models_cfg = resolved_bindings.parent / "model_providers.json"
        elif auth_file_path:
            resolved_models_cfg = Path(auth_file_path).parent / "model_providers.json"
        else:
            resolved_models_cfg = DEFAULT_MODEL_PROVIDERS_FILE
        self.models = MagpieProviderHub(
            plugin_root=self.plugin_root,
            config_path=resolved_models_cfg,
            http_requester=model_http_requester,
        )

        env_personas = os.environ.get("WECHAT_PLUGIN_PERSONAS_FILE")
        if personas_file_path:
            resolved_personas = Path(personas_file_path)
        elif env_personas:
            resolved_personas = Path(env_personas)
        elif bindings_file_path or env_bindings:
            resolved_personas = resolved_bindings.parent / "personas.json"
        elif auth_file_path:
            resolved_personas = Path(auth_file_path).parent / "personas.json"
        else:
            resolved_personas = DEFAULT_PERSONAS_FILE
        self.personas = PersonaSwitchEngine(resolved_personas, model_hub=self.models)

        env_mon_state = os.environ.get("WECHAT_PLUGIN_MONITOR_STATE")
        if monitor_state_path:
            resolved_mon_state = Path(monitor_state_path)
        elif env_mon_state:
            resolved_mon_state = Path(env_mon_state)
        elif reports_dir:
            resolved_mon_state = resolved_reports / "monitor_state.json"
        elif audit_log_path or env_audit:
            resolved_mon_state = resolved_audit.parent / "monitor_state.json"
        else:
            resolved_mon_state = DEFAULT_MONITOR_STATE

        env_mon_events = os.environ.get("WECHAT_PLUGIN_MONITOR_EVENTS")
        if monitor_events_path:
            resolved_mon_events = Path(monitor_events_path)
        elif env_mon_events:
            resolved_mon_events = Path(env_mon_events)
        elif reports_dir:
            resolved_mon_events = resolved_reports / "monitor_events.jsonl"
        elif audit_log_path or env_audit:
            resolved_mon_events = resolved_audit.parent / "monitor_events.jsonl"
        else:
            resolved_mon_events = DEFAULT_MONITOR_EVENTS

        self.monitor = WeChatRealtimeMonitor(
            self,
            state_path=resolved_mon_state,
            events_path=resolved_mon_events,
        )

        env_article_exports = os.environ.get("WECHAT_PLUGIN_ARTICLE_EXPORTS")
        if env_article_exports:
            resolved_article_exports = Path(env_article_exports)
        elif reports_dir:
            resolved_article_exports = resolved_reports / "exports" / "articles"
        elif audit_log_path or env_audit:
            resolved_article_exports = resolved_audit.parent / "exports" / "articles"
        else:
            resolved_article_exports = self.plugin_root / "exports" / "articles"
        self.article_exporter = WeChatArticleExporter(
            self.inspector,
            export_root=resolved_article_exports,
        )

        self.human_guard = HumanActivityGuard(
            state_path=resolved_mon_state.parent / "human_guard_state.json",
            hid_query_fn=lambda: self._run_native(["hid-idle"], 4.0),
        )
        self.antiban = AntiBanGuard(
            state_path=resolved_mon_state.parent / "antiban_state.json",
            per_contact_hourly=int(os.environ.get("WECHAT_PLUGIN_ANTIBAN_CONTACT_HOURLY", "8") or 8),
            global_hourly=int(os.environ.get("WECHAT_PLUGIN_ANTIBAN_HOURLY", "15") or 15),
            global_daily=int(os.environ.get("WECHAT_PLUGIN_ANTIBAN_DAILY", "60") or 60),
            min_reply_gap_seconds=int(os.environ.get("WECHAT_PLUGIN_ANTIBAN_GAP", "90") or 90),
        )
        self.ui_protocol = WeChatUIProtocolNavigator(self)

        env_soul = os.environ.get("WECHAT_PLUGIN_SOUL_FILE")
        if env_soul:
            resolved_soul = Path(env_soul)
        elif bindings_file_path or env_bindings:
            resolved_soul = resolved_bindings.parent / "soul_memories.json"
        elif auth_file_path:
            resolved_soul = Path(auth_file_path).parent / "soul_memories.json"
        else:
            resolved_soul = DEFAULT_SOUL_MEMORIES_FILE

        self.soul_profiler = SoulMemoryProfiler(
            histories_dir=self.inspector.reports_dir / "contacts",
            reports_dir=resolved_reports,
            store_path=resolved_soul,
            analytics_provider=lambda: self.profile_contacts(),
            bindings_provider=lambda: self.bindings.list_bindings(),
            persona_sync_cb=lambda owner: self.personas.upsert_persona({
                "id": "owner-digital-twin",
                "name": "🎭 号主本人数字分身 · 原生性格与记忆",
                "mbti": str(owner.get("mbtiEstimate") or "ENTJ").split(" ")[0],
                "interactionStyle": "builder",
                "tone": str(owner.get("speakingStyle", {}).get("toneTag") or "简练自然"),
                "guidelines": str(owner.get("digitalTwinSystemPrompt") or ""),
                "maxChars": 140,
            }),
        )
        self.benchmark_suite = WeChatRPABenchmarkSuite(self)
        self.botstudio_bridge = BotStudioBridgeManager(self)
        self.media_analyzer = WeChatMediaLinkAnalyzer(self)
        self.agent_dispatcher = WeChatAgentDispatcher(self)
        self.sales_crm = WeChatSalesCRMHub(self, db_path=resolved_kb.parent / "sales_crm.sqlite")
        self.hosting_manager = HostingManager(
            self,
            state_path=resolved_mon_state.parent / "hosting_state.json",
            interval_seconds=max(5.0, float(os.environ.get("WECHAT_PLUGIN_HOSTING_INTERVAL", "45") or 45)),
        )
        # 托管自动恢复：上次异常退出（enabled=true 未走 stop）时重启引擎恢复托管。
        # fail-closed：授权被撤销则不恢复，只落审计。
        try:
            _hosting_state_doc = json.loads(
                (resolved_mon_state.parent / "hosting_state.json").read_text(encoding="utf-8"))
        except Exception:
            _hosting_state_doc = None
        if isinstance(_hosting_state_doc, dict) and _hosting_state_doc.get("enabled"):
            _auth_ok = bool((self.auth_status().get("authorization") or {}).get("authorized"))
            if not _auth_ok:
                self.audit.log("hosting_resume", "denied", {"reason": "authorization_revoked"})
            else:
                _resume = self.hosting_manager.resume_from_state(_hosting_state_doc)
                if _resume.get("resumed"):
                    self.audit.log("hosting_resume", "ok", {"targets": _resume.get("targets")})

    def _require(self, capability: str) -> Dict[str, Any]:
        try:
            return self.auth_gate.require_capability(capability)
        except StudioPluginUnauthorizedError as exc:
            self.audit.log("auth_gate", "denied", {"capability": capability, "error": str(exc)})
            raise

    def capture_wechat_ocr(self, out_path: Path, *, timeout: float = 30.0,
                           window_title: str = "微信") -> Dict[str, Any]:
        """只截微信窗口做 OCR（--window-title 定位），避免截到覆盖在上面的无关窗口。

        两层兜底：
        1. 窗口不存在（window_not_found）→ 退回不带 title 的调用（保留自动拉起能力）
        2. 截图成功但 OCR 为空（窗口被其他应用完全遮挡时 macOS 返回空白）→ 激活微信后重截一次
        """
        res = self._run_native(["capture-ocr", "--window-title", window_title, "--out", str(out_path)], timeout)
        if not res.get("ok"):
            if res.get("error_code") in ("window_not_found", "no_window"):
                fallback = self._run_native(["capture-ocr", "--out", str(out_path)], timeout)
                fallback["fallbackUsed"] = True
                fallback["fallbackReason"] = res.get("error_code")
                return fallback
            if res.get("error_code") != "window_occluded":
                return res
        # 窗口被完全遮挡（原生层返回 window_occluded / 空结果）→ 激活微信后重截一次
        if res.get("error_code") == "window_occluded" or not (res.get("elements") or []):
            self._run_native(["activate"], 10.0)
            time.sleep(0.8)
            retry = self._run_native(
                ["capture-ocr", "--window-title", window_title, "--out", str(out_path)], timeout)
            if retry.get("ok") and (retry.get("elements") or []):
                retry["retriedAfterActivate"] = True
                return retry
            retry["occluded"] = True
            return retry
        return res

    def _enhance_lowres_ocr(self, args: List[str], data: Dict[str, Any], *, timeout: float) -> Dict[str, Any]:
        """Re-run Vision OCR on a 2x upscaled image when 1x non-Retina captures (<900px) drop small chat text."""
        if not data.get("ok") or not args or args[0] not in ("capture-ocr", "ocr"):
            return data
        img_w = int(data.get("imageWidth") or 0)
        img_h = int(data.get("imageHeight") or 0)
        if not (0 < img_w < 900 and 0 < img_h < 900):
            return data

        flag = "--out" if "--out" in args else ("--image" if "--image" in args else "")
        if not flag:
            return data
        idx = args.index(flag) + 1
        if idx >= len(args):
            return data
        img_path = Path(args[idx])
        if not img_path.exists() or img_path.stat().st_size <= 100:
            return data

        try:
            with tempfile.NamedTemporaryFile(suffix=".png") as tf:
                upscale = subprocess.run(
                    ["/usr/bin/sips", "-Z", str(max(img_w, img_h) * 2), str(img_path), "--out", tf.name],
                    capture_output=True,
                    timeout=5.0,
                )
                if upscale.returncode != 0:
                    return data
                proc2 = subprocess.run(
                    [str(self.binary_path), "ocr", "--image", tf.name],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                ocr2 = json.loads((proc2.stdout or "").strip() or "{}")
                els2 = ocr2.get("elements") or []
                if not ocr2.get("ok") or len(els2) < len(data.get("elements") or []):
                    return data
                sx = img_w / float(ocr2.get("imageWidth") or (img_w * 2))
                sy = img_h / float(ocr2.get("imageHeight") or (img_h * 2))
                rescaled: List[Dict[str, Any]] = []
                for el in els2:
                    bbox = el.get("bbox") or {}
                    center = el.get("center") or {}
                    item = dict(el)
                    item["bbox"] = {
                        "x": int(round(float(bbox.get("x", 0.0)) * sx)),
                        "y": int(round(float(bbox.get("y", 0.0)) * sy)),
                        "width": int(round(float(bbox.get("width", 0.0)) * sx)),
                        "height": int(round(float(bbox.get("height", 0.0)) * sy)),
                    }
                    item["center"] = {
                        "x": int(round(float(center.get("x", 0.0)) * sx)),
                        "y": int(round(float(center.get("y", 0.0)) * sy)),
                    }
                    rescaled.append(item)
                rescaled.sort(key=lambda e: (e["center"]["y"], e["center"]["x"]))
                data["elements"] = rescaled
                data["count"] = len(rescaled)
                data["upscaled2x"] = True
        except Exception:
            pass
        return data

    def _run_native(self, args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
        if not self.binary_path.exists():
            return {
                "ok": False,
                "error_code": "native_binary_missing",
                "error": f"Native binary not compiled at {self.binary_path}",
            }
        cmd_name = args[0] if args else ""
        mutating_input = cmd_name in ("click", "scroll", "focus-input", "paste-and-verify")
        rpa_x: Optional[float] = None
        rpa_y: Optional[float] = None
        if mutating_input:
            try:
                if "--x" in args:
                    rpa_x = float(args[args.index("--x") + 1])
                if "--y" in args:
                    rpa_y = float(args[args.index("--y") + 1])
            except Exception:
                rpa_x = None
                rpa_y = None
            if hasattr(self, "human_guard"):
                self.human_guard.record_rpa_action(action=cmd_name, cursor_x=rpa_x, cursor_y=rpa_y)

        cmd = [str(self.binary_path)] + args
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error_code": "native_timeout",
                "error": f"Native command timed out after {timeout}s: {' '.join(args)}",
            }
        finally:
            if mutating_input and hasattr(self, "human_guard"):
                self.human_guard.record_rpa_action(action=cmd_name, cursor_x=rpa_x, cursor_y=rpa_y)

        stdout = (proc.stdout or "").strip()
        if not stdout:
            return {
                "ok": False,
                "error_code": "empty_native_output",
                "error": (proc.stderr or "").strip() or f"Exit code {proc.returncode}",
                "returncode": proc.returncode,
            }
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                data.setdefault("returncode", proc.returncode)
                return self._enhance_lowres_ocr(args, data, timeout=timeout)
        except json.JSONDecodeError:
            pass
        return {
            "ok": False,
            "error_code": "invalid_native_json",
            "error": stdout[:400],
            "returncode": proc.returncode,
        }

    # ------------------------------------------------------------------
    # Bot Studio Authorization Controls & Diagnostics
    # ------------------------------------------------------------------

    def auth_status(self) -> Dict[str, Any]:
        return {"ok": True, "authorization": self.auth_gate.get_state()}

    def auth_grant(
        self,
        capabilities: Optional[Iterable[str]] = None,
        *,
        authorized_by: str = "bot-studio-owner",
        note: str = "",
    ) -> Dict[str, Any]:
        state = self.auth_gate.grant(capabilities, authorized_by=authorized_by, note=note)
        self.audit.log("auth_grant", "ok", {"grantId": state.get("grantId"), "capabilities": state.get("capabilities")})
        return {"ok": True, "authorization": state}

    def auth_revoke(self, *, reason: str = "Revoked by Bot Studio user") -> Dict[str, Any]:
        state = self.auth_gate.revoke(reason=reason)
        self.audit.log("auth_revoke", "ok", {"grantId": state.get("grantId"), "reason": reason})
        return {"ok": True, "authorization": state}

    def get_status(self) -> Dict[str, Any]:
        self._require("status")
        res = self._run_native(["status"])
        self.audit.log("status", "ok" if res.get("ok") else "error", {"wechatRunning": res.get("wechatRunning")})
        return res

    def request_permissions(self, *, open_settings: bool = True) -> Dict[str, Any]:
        args = ["request-permissions"]
        if not open_settings:
            args.append("--no-settings")
        res = self._run_native(args)
        self.audit.log(
            "request_permissions",
            "ok" if res.get("ok") else "error",
            {
                "accessibilityTrusted": res.get("accessibilityTrusted"),
                "postEventTrusted": res.get("postEventTrusted"),
                "screenCaptureTrusted": res.get("screenCaptureTrusted"),
                "openedSystemSettings": res.get("openedSystemSettings"),
            },
        )
        return res

    def doctor(self) -> Dict[str, Any]:
        binary_exists = self.binary_path.exists()
        status = self._run_native(["status"]) if binary_exists else {"ok": False}
        auth_state = self.auth_gate.get_state()

        recommendations: List[str] = []
        if not binary_exists:
            recommendations.append("Compile native/wechat_vision_ax.swift into bin/wechat-vision-ax via swiftc -O.")
        if not auth_state.get("authorized"):
            recommendations.append(
                "Plugin is currently unauthorized (fail-closed). Enable in Bot Studio or run `auth-grant` to authorize capabilities."
            )
        if not status.get("accessibilityTrusted"):
            recommendations.append(
                "Grant Accessibility permission to your terminal/OpenBot host in macOS System Settings -> Privacy & Security -> Accessibility for full AXUIElement control."
            )
        if not status.get("screenCaptureTrusted"):
            recommendations.append(
                "Grant Screen Recording permission for window-level Vision OCR fallback."
            )
        if not status.get("wechatRunning"):
            recommendations.append("Launch WeChat desktop app (com.tencent.xinWeChat).")
        elif status.get("windowCount", 0) == 0:
            recommendations.append("Open or un-minimize the WeChat main window.")

        report: Dict[str, Any] = {
            "ok": True,
            "pluginId": "openbot.plugin.wechat-rpa-control",
            "binaryPath": str(self.binary_path),
            "binaryReady": binary_exists,
            "studioAuthorization": auth_state,
            "auditLogPath": str(self.audit.log_path),
            "dedupWindowSeconds": self.dedup.dedup_window_seconds,
            "allowlistEnabled": self.allowlist.enabled,
            "allowedGroups": self.allowlist.list_allowed(),
            "status": status,
            "recommendations": recommendations,
        }
        self.audit.log("doctor", "ok", {"binaryReady": binary_exists, "authorized": bool(auth_state.get("authorized"))})
        return report

    # ------------------------------------------------------------------
    # Vision OCR & AX Inspection
    # ------------------------------------------------------------------

    def render_test_image(self, out_path: Path, text: Optional[str] = None) -> Dict[str, Any]:
        args = ["render-test-image", "--out", str(out_path)]
        if text is not None:
            args.extend(["--text", text])
        return self._run_native(args)

    def ocr_image(self, image_path: Path, languages: str = "zh-Hans,en-US") -> Dict[str, Any]:
        self._require("ocr")
        res = self._run_native(["ocr", "--image", str(image_path), "--langs", languages])
        self.audit.log(
            "ocr_image",
            "ok" if res.get("ok") else "error",
            {"imagePath": str(image_path), "count": res.get("count", 0)},
        )
        return res

    def ocr_wechat_window(self, save_path: Optional[Path] = None) -> Dict[str, Any]:
        self._require("ocr")
        args = ["capture-ocr"]
        if save_path is not None:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            args.extend(["--out", str(save_path)])
        res = self._run_native(args)
        self.audit.log(
            "ocr_window",
            "ok" if res.get("ok") else "error",
            {"count": res.get("count", 0), "savedPath": str(save_path) if save_path else None},
        )
        return res

    def get_ax_tree(self, depth: int = 8, max_nodes: int = 1200) -> Dict[str, Any]:
        self._require("read_sessions")
        return self._run_native(["ax-tree", "--depth", str(depth), "--max-nodes", str(max_nodes)])

    def list_sessions(self) -> Dict[str, Any]:
        self._require("read_sessions")
        ax = self.get_ax_tree(depth=8)
        if ax.get("ok") and ax.get("sessionItems"):
            sessions = []
            for item in ax["sessionItems"]:
                label = item.get("value") or item.get("title") or item.get("description") or item.get("identifier", "")
                sessions.append({
                    "name": label,
                    "identifier": item.get("identifier", ""),
                    "center": item.get("center"),
                    "source": "accessibility",
                })
            return {"ok": True, "source": "accessibility", "count": len(sessions), "sessions": sessions}

        ocr = self.ocr_wechat_window()
        if ocr.get("ok"):
            img_w = max(ocr.get("imageWidth", 1000), 1)
            img_h = max(ocr.get("imageHeight", 800), 1)
            split_x = max(218.0, min(310.0, img_w * 0.38))
            sidebar_items = [
                el for el in ocr.get("elements", [])
                if 62.0 <= el.get("center", {}).get("x", 0) <= split_x
                and el.get("center", {}).get("y", 0) >= 0.08 * img_h
            ]
            return {
                "ok": True,
                "source": "vision_ocr_fallback",
                "count": len(sidebar_items),
                "sessions": sidebar_items,
            }

        return {
            "ok": False,
            "error_code": ocr.get("error_code") or ax.get("error_code") or "unavailable",
            "error": ocr.get("error") or ax.get("error") or "Neither AX nor Screen Recording OCR succeeded.",
            "ax_error": ax.get("error"),
            "ocr_error": ocr.get("error"),
        }

    def read_messages(self, limit: int = 20) -> Dict[str, Any]:
        self._require("read_messages")
        ax = self.get_ax_tree(depth=10)
        if ax.get("ok") and ax.get("messageItems"):
            msgs = ax["messageItems"][-limit:]
            return {
                "ok": True,
                "source": "accessibility",
                "currentChat": ax.get("currentChat", {}),
                "count": len(msgs),
                "messages": msgs,
            }

        ocr = self.ocr_wechat_window()
        if ocr.get("ok"):
            img_w = max(ocr.get("imageWidth", 1000), 1)
            img_h = max(ocr.get("imageHeight", 800), 1)
            split_x = max(218.0, min(310.0, img_w * 0.38))
            msgs = [
                el for el in ocr.get("elements", [])
                if el.get("center", {}).get("x", 0) > split_x + 4.0
                and 58.0 <= el.get("center", {}).get("y", 0) <= (img_h - 108.0)
            ][-limit:]
            return {
                "ok": True,
                "source": "vision_ocr_fallback",
                "count": len(msgs),
                "messages": msgs,
            }

        return {
            "ok": False,
            "error_code": ocr.get("error_code") or ax.get("error_code") or "unavailable",
            "error": ocr.get("error") or ax.get("error") or "Unable to read messages via AX or Vision OCR.",
        }

    def inspect_live_wechat(
        self,
        *,
        max_session_pages: int = 2,
        max_contact_pages: int = 4,
    ) -> Dict[str, Any]:
        """Perform a complete read-only live inspection of open WeChat sessions, messages, and contacts."""
        self._require("read_sessions")
        self._require("read_messages")
        self._require("read_contacts")
        self._require("ocr")
        report = self.inspector.inspect_live(
            max_session_pages=max_session_pages,
            max_contact_pages=max_contact_pages,
        )
        self.audit.log(
            "inspect_live",
            "ok",
            {
                "sessionCount": report.get("sessionCount", 0),
                "contactItemCount": report.get("contactItemCount", 0),
                "reportMarkdownPath": report.get("reportMarkdownPath"),
            },
        )
        return report

    # ------------------------------------------------------------------
    # Safe Message Sending Pipeline
    # ------------------------------------------------------------------

    def send_text(
        self,
        target: str,
        text: str,
        *,
        dry_run: bool = True,
        silent_mode: bool = True,
        confirm_send: bool = False,
        allowed_groups: Optional[Iterable[str]] = None,
        apply_jitter: bool = False,
        simulate_readback: Optional[str] = None,
        skip_navigation: bool = False,
        expected_window_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Safely execute or dry-run the WeChat send state machine.

        Defaults to `dry_run=True` and `silent_mode=True` so tests/exploratory calls never
        dispatch real Enter keystrokes without explicit confirmation (`confirm_send=True`).
        """
        will_send = bool((not dry_run) and confirm_send and not silent_mode)
        self._require("send_text_live" if will_send else "send_text_dry_run")
        if expected_window_id is not None:
            protocol = self._run_native(["status"], timeout=4).get("reviewedSendProtocol")
            if not will_send or not skip_navigation or protocol != 1:
                return {"ok": False, "status": "unsupported_review_driver"}
        clean_target = (target or "").strip()
        if not text or not text.strip():
            res = {
                "ok": False,
                "status": "rejected_empty_text",
                "error": "Outgoing message text cannot be empty.",
            }
            self.audit.log("send_text", "rejected_empty_text", {"target": clean_target})
            return res

        if allowed_groups is not None:
            guard = GroupAllowlistGuard(allowed_groups)
        elif self.allowlist.enabled:
            guard = GroupAllowlistGuard(list(self.allowlist.list_allowed()) + self.bindings.bound_targets())
        else:
            guard = self.allowlist
        if not guard.is_allowed(clean_target):
            res = {
                "ok": False,
                "status": "blocked_whitelist",
                "target": clean_target,
                "normalizedTarget": normalize_chat_name(clean_target),
                "allowedGroups": guard.list_allowed(),
                "error": f"Target {clean_target!r} is not in allowed_groups.",
            }
            self.audit.log("send_text", "blocked_whitelist", res)
            return res

        allowed_dedup, fp, elapsed = self.dedup.check_and_record(clean_target, text, record_now=True)
        if not allowed_dedup:
            res = {
                "ok": False,
                "status": "blocked_duplicate",
                "target": clean_target,
                "fingerprint": fp,
                "secondsSinceLast": elapsed,
                "dedupWindowSeconds": self.dedup.dedup_window_seconds,
                "error": f"Duplicate message to {clean_target!r} blocked inside {self.dedup.dedup_window_seconds}s window.",
            }
            self.audit.log("send_text", "blocked_duplicate", res)
            return res

        if apply_jitter and not dry_run:
            self.jitter.sleep_before_action()

        if dry_run:
            # Optional readback sanity check in Python (e.g., when testing 3x circuit breaker)
            readback_text = text if simulate_readback is None else simulate_readback
            try:
                ReadbackVerifier.verify(text, readback_text)
            except Exception as exc:
                res = {
                    "ok": False,
                    "status": "circuit_breaker" if "circuit breaker" in str(exc).lower() else "readback_mismatch",
                    "target": clean_target,
                    "fingerprint": fp,
                    "error": str(exc),
                }
                self.audit.log("send_text", res["status"], res)
                return res

            res = {
                "ok": True,
                "status": "dry_run_ok",
                "mode": "dry_run",
                "sent": False,
                "target": clean_target,
                "normalizedTarget": normalize_chat_name(clean_target),
                "textLength": len(text),
                "fingerprint": fp,
            }
            self.audit.log("send_text", "dry_run_ok", res)
            return res

        matched_title = clean_target
        if not skip_navigation:
            nav = self.inspector.select_session(clean_target)
            if not nav.get("ok"):
                res = {
                    "ok": False,
                    "status": "target_navigation_failed",
                    "target": clean_target,
                    "navigation": nav,
                    "error": nav.get("error", f"Failed to navigate to {clean_target!r}."),
                }
                self.audit.log("send_text", "target_navigation_failed", res)
                return res
            matched_title = str(nav.get("matchedTitle") or clean_target)

        # Live or silent-UI verification via native binary
        native_args = ["paste-and-verify", "--text", text]
        if expected_window_id is not None:
            native_args += ["--review-window", str(expected_window_id), "--review-title", clean_target]
        if will_send:
            native_args.append("--send")
        else:
            native_args.append("--silent")

        native_res = self._run_native(native_args, timeout=25.0)
        status_label = "sent" if (native_res.get("ok") and native_res.get("sent")) else (
            "silent_verified" if native_res.get("ok") else native_res.get("error_code", "native_error")
        )

        post_send_snapshot: Optional[str] = None
        if expected_window_id is None and will_send and native_res.get("ok") and native_res.get("sent"):
            time.sleep(0.40)
            slug = _slugify_target(clean_target)
            snap_file = self.inspector.snapshots_dir / f"sent_{slug}_{int(time.time() * 1000)}.png"
            self.inspector.snapshots_dir.mkdir(parents=True, exist_ok=True)
            cap = self._run_native(["capture-ocr", "--out", str(snap_file)], timeout=15.0)
            if cap.get("ok"):
                post_send_snapshot = str(snap_file)

        result: Dict[str, Any] = {
            "ok": bool(native_res.get("ok")),
            "status": status_label,
            "mode": "live_send" if will_send else "silent_verify",
            "target": clean_target,
            "matchedChatTitle": matched_title,
            "fingerprint": fp,
            "native": native_res,
        }
        if post_send_snapshot:
            result["postSendSnapshot"] = post_send_snapshot
        audit_payload = result if expected_window_id is None else {"fingerprint": fp, "stage": "workbench"}
        self.audit.log("send_text", status_label, audit_payload)
        return result

    # ------------------------------------------------------------------
    # Bound Contacts, Deep Observation, Friend Style & Frequency Analytics
    # ------------------------------------------------------------------

    def bind_contact(
        self,
        target: str,
        *,
        alias: str = "",
        role: str = "friend",
        ai_persona: str = "warm-companion",
        scheduled_enabled: bool = True,
        cron_hint: str = "0 9,21 * * *",
        auto_reply_enabled: bool = True,
        notes: str = "",
        special_care: Optional[bool] = None,
        care_level: Optional[str] = None,
        care_tags: Optional[Iterable[str]] = None,
        follow_up_days: Optional[int] = None,
        bound_agent_id: Optional[str] = None,
        bound_agent_name: Optional[str] = None,
        bound_agent_type: Optional[str] = None,
        vision_model_id: Optional[str] = None,
        auto_dispatch_instructions: Optional[bool] = None,
        auto_analyze_links_and_media: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        res = self.bindings.bind_contact(
            target,
            alias=alias,
            role=role,
            ai_persona=ai_persona,
            scheduled_enabled=scheduled_enabled,
            cron_hint=cron_hint,
            auto_reply_enabled=auto_reply_enabled,
            notes=notes,
            special_care=special_care,
            care_level=care_level,
            care_tags=care_tags,
            follow_up_days=follow_up_days,
            bound_agent_id=bound_agent_id,
            bound_agent_name=bound_agent_name,
            bound_agent_type=bound_agent_type,
            vision_model_id=vision_model_id,
            auto_dispatch_instructions=auto_dispatch_instructions,
            auto_analyze_links_and_media=auto_analyze_links_and_media,
        )
        self.audit.log(
            "bind_contact",
            "ok",
            {
                "target": target,
                "role": role,
                "careLevel": res["binding"].get("careLevel"),
                "specialCare": res["binding"].get("specialCare"),
                "boundAgentId": res["binding"].get("boundAgentId"),
                "visionModelId": res["binding"].get("visionModelId"),
            },
        )
        return res

    def set_special_care(
        self,
        target: str,
        *,
        enabled: bool = True,
        care_level: Optional[str] = None,
        care_tags: Optional[Iterable[str]] = None,
        follow_up_days: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        res = self.bindings.set_special_care(
            target,
            enabled=enabled,
            care_level=care_level,
            care_tags=care_tags,
            follow_up_days=follow_up_days,
            notes=notes,
        )
        self.audit.log(
            "set_special_care",
            "ok",
            {
                "target": target,
                "enabled": enabled,
                "careLevel": res["binding"].get("careLevel"),
                "specialCare": res["binding"].get("specialCare"),
            },
        )
        return res

    def unbind_contact(self, target: str) -> Dict[str, Any]:
        self._require("status")
        res = self.bindings.unbind_contact(target)
        self.audit.log("unbind_contact", "ok" if res.get("ok") else "not_found", {"target": target})
        return res

    def list_bindings(self) -> Dict[str, Any]:
        self._require("status")
        items = self.bindings.list_bindings()
        return {
            "ok": True,
            "count": len(items),
            "bindings": items,
            "bindingsFile": str(self.bindings.bindings_file),
        }

    # ------------------------------------------------------------------
    # Vision Stack, Link/Image/Video Deep Reader, Friend Agent Dispatch & Sidebar Dock
    # ------------------------------------------------------------------

    def get_vision_stack_info(self) -> Dict[str, Any]:
        self._require("status")
        return self.agent_dispatcher.inspect_vision_stack()

    def analyze_media_or_link(
        self,
        *,
        kind: str = "link",
        url: Optional[str] = None,
        image_path: Optional[str] = None,
        video_path: Optional[str] = None,
        video_url: Optional[str] = None,
        crop_region: Optional[Dict[str, int]] = None,
        from_viewer_window: bool = False,
        source_snapshot: Optional[str] = None,
        window_title: str = "图片和视频",
        contact: str = "",
        context_text: str = "",
        frame_count: int = 3,
        model_id: str = "auto/deepseek-v4.1-flash",
        allow_loopback: bool = False,
        html_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        clean_kind = (kind or "link").strip().lower()
        if clean_kind == "link":
            if not url:
                return {"ok": False, "error": "URL is required when kind='link'."}
            res = self.media_analyzer.analyze_link(
                url,
                contact=contact,
                context_text=context_text,
                model_id=model_id,
                allow_loopback=allow_loopback,
                html_override=html_override,
            )
        elif clean_kind in ("image", "image_or_card", "card"):
            res = self.media_analyzer.analyze_image_or_card(
                image_path=Path(image_path) if image_path else None,
                crop_region=crop_region,
                from_viewer_window=from_viewer_window,
                source_snapshot=Path(source_snapshot) if source_snapshot else None,
                window_title=window_title,
                contact=contact,
                context_text=context_text,
                model_id=model_id,
            )
        elif clean_kind == "video":
            res = self.media_analyzer.analyze_video(
                video_path=Path(video_path) if video_path else None,
                video_url=video_url or url,
                from_viewer_window=from_viewer_window,
                window_title=window_title,
                contact=contact,
                context_text=context_text,
                frame_count=frame_count,
                model_id=model_id,
            )
        else:
            return {"ok": False, "error": f"Unsupported media kind: {clean_kind}"}

        self.audit.log(
            "analyze_media",
            "ok" if res.get("ok") else "error",
            {
                "kind": clean_kind,
                "contact": contact,
                "modelId": model_id,
                "analysisId": res.get("analysisId"),
            },
        )
        return res

    def dispatch_friend_instructions(
        self,
        contact: str,
        *,
        include_live_media: bool = True,
        execute_with_agent: bool = True,
        extra_messages: Optional[List[Dict[str, Any]]] = None,
        model_id: Optional[str] = None,
        html_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        res = self.agent_dispatcher.dispatch_contact_tasks(
            contact,
            include_live_media=include_live_media,
            execute_with_agent=execute_with_agent,
            extra_messages=extra_messages,
            model_id=model_id,
            html_overrides=html_overrides,
        )
        self.audit.log(
            "agent_dispatch",
            "ok" if res.get("ok") else "error",
            {
                "contact": contact,
                "tasksCount": res.get("tasksCount", 0),
                "mediaAnalysesCount": res.get("mediaAnalysesCount", 0),
                "dispatchId": res.get("dispatchId"),
            },
        )
        return res

    def get_agent_tasks(self, limit: int = 20) -> Dict[str, Any]:
        self._require("status")
        items = self.agent_dispatcher.list_recent_tasks(limit=limit)
        return {"ok": True, "count": len(items), "tasks": items}

    def get_media_analyses(self, limit: int = 20) -> Dict[str, Any]:
        self._require("status")
        items = self.media_analyzer.list_recent_analyses(limit=limit)
        return {"ok": True, "count": len(items), "analyses": items}

    def dock_app_to_wechat(self, mode: str = "verify") -> Dict[str, Any]:
        self._require("status")
        clean_mode = (mode or "verify").strip().lower()
        app_candidates = [
            self.plugin_root / "dist" / "WeChat Bot.app",
            Path("/Users/mac/Applications/WeChat Bot.app"),
        ]
        app_bundle = next((p for p in app_candidates if p.is_dir()), None)
        exe = (app_bundle / "Contents" / "MacOS" / "wechat-studio-app") if app_bundle else None
        if exe is None or not exe.is_file():
            return {"ok": False, "appReady": False, "error": "WeChat Bot.app binary not found."}

        try:
            proc = subprocess.run([str(exe), "--verify-dock"], capture_output=True, text=True, timeout=8.0)
            raw = (proc.stdout or "").strip()
            verify_data = json.loads(raw) if raw.startswith("{") else {"ok": proc.returncode == 0, "stdout": raw, "stderr": proc.stderr}
        except Exception as exc:
            return {"ok": False, "appReady": True, "appBundle": str(app_bundle), "error": str(exc)}

        if clean_mode == "verify":
            verify_data["appReady"] = True
            verify_data["appBundle"] = str(app_bundle)
            return verify_data

        tile_result: Optional[Dict[str, Any]] = None
        if clean_mode == "tile":
            target_frame = verify_data.get("tiledWeChatTargetQuartzFrame") or (verify_data.get("calculatedDockPlan") or {}).get("wechatTargetFrame")
            if isinstance(target_frame, dict) and target_frame.get("width") and target_frame.get("height"):
                cmd = [
                    "set-window-frame",
                    "--x", str(int(round(float(target_frame.get("x", 0))))),
                    "--y", str(int(round(float(target_frame.get("y", 30))))),
                    "--width", str(int(round(float(target_frame.get("width", 960))))),
                    "--height", str(int(round(float(target_frame.get("height", 960))))),
                ]
                tile_result = self._run_native(cmd, 8.0)

        launch_flag = "--tile-wechat" if clean_mode == "tile" else "--dock-wechat"
        launched = False
        launch_err = ""
        try:
            # First notify any already-running WeChat Bot.app instance; if none running, open bundle with args.
            chk = subprocess.run(["pgrep", "-x", "wechat-studio-app"], capture_output=True, text=True, timeout=3.0)
            if chk.returncode == 0 and chk.stdout.strip():
                subprocess.run([str(exe), "--notify-dock", clean_mode], capture_output=True, text=True, timeout=5.0)
                launched = True
            else:
                subprocess.Popen(
                    ["open", "-a", str(app_bundle), "--args", launch_flag],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                launched = True
        except Exception as exc:
            launch_err = str(exc)

        out: Dict[str, Any] = {
            **verify_data,
            "ok": bool(verify_data.get("ok")) and launched,
            "appReady": True,
            "mode": clean_mode,
            "launchFlag": launch_flag,
            "appBundle": str(app_bundle),
            "launched": launched,
            "launchError": launch_err,
        }
        if tile_result is not None:
            out["tileResult"] = tile_result
        self.audit.log(
            "dock_app_to_wechat",
            "ok" if out.get("ok") else "error",
            {"mode": clean_mode, "wechatFound": out.get("wechatFound"), "launched": launched},
        )
        return out

    def observe_contact(self, target: str, *, scroll_pages: int = 4) -> Dict[str, Any]:
        self._require("read_sessions")
        self._require("read_messages")
        self._require("ocr")
        res = self.inspector.observe_contact_history(target, scroll_pages=scroll_pages)
        self.audit.log(
            "observe_contact",
            "ok" if res.get("ok") else "error",
            {"target": target, "recordCount": res.get("recordCount", 0), "historyPath": res.get("historyPath")},
        )
        return res

    def profile_contacts(self, target: Optional[str] = None) -> Dict[str, Any]:
        self._require("status")
        report_file = self.inspector.reports_dir / "wechat_management_report.json"
        inspection_report: Optional[Dict[str, Any]] = None
        if report_file.exists():
            try:
                inspection_report = json.loads(report_file.read_text(encoding="utf-8"))
            except Exception:
                inspection_report = None

        analytics = self.profiler.generate_analytics_report(
            inspection_report=inspection_report,
            histories_dir=self.inspector.reports_dir / "contacts",
            bindings=self.bindings.list_bindings(),
            reports_dir=self.inspector.reports_dir,
            focus_target=target,
        )
        self.audit.log(
            "profile_contacts",
            "ok",
            {
                "focusTarget": target,
                "profileCount": analytics.get("profileCount", 0),
                "reportMarkdownPath": analytics.get("reportMarkdownPath"),
            },
        )
        return analytics

    def _recent_messages_for(self, target: str) -> List[str]:
        contacts_dir = self.inspector.reports_dir / "contacts"
        if contacts_dir.exists():
            for hp in sorted(contacts_dir.glob("*_history.json")):
                try:
                    data = json.loads(hp.read_text(encoding="utf-8"))
                    if _matches_target(target, str(data.get("target") or "")) or _matches_target(
                        target, str(data.get("matchedTitle") or "")
                    ):
                        msgs = [
                            str(r.get("text", ""))
                            for r in (data.get("records") or [])
                            if r.get("kind") == "message" and r.get("text")
                        ]
                        if msgs:
                            return msgs[-6:]
                except Exception:
                    continue
        report_file = self.inspector.reports_dir / "wechat_management_report.json"
        if report_file.exists():
            try:
                rep = json.loads(report_file.read_text(encoding="utf-8"))
                for sess in rep.get("sessions") or []:
                    title = str(sess.get("fullTitle") or sess.get("listTitleSnippet") or "")
                    if _matches_target(target, title) and sess.get("visibleMessages"):
                        return list(sess["visibleMessages"][:6])
            except Exception:
                pass
        return []

    def chat_test(
        self,
        target: str,
        *,
        mode: str = "scheduled",
        text: Optional[str] = None,
        confirm_send: bool = False,
        silent_verify: bool = False,
    ) -> Dict[str, Any]:
        binding = self.bindings.get_binding(target)
        recent = self._recent_messages_for(target)
        message_text = ContextualAIChatGenerator.build_message(
            target,
            mode=mode,
            custom_text=text,
            binding=binding,
            recent_messages=recent,
        )
        if confirm_send:
            dry_run = False
            silent_mode = False
        elif silent_verify:
            dry_run = False
            silent_mode = True
        else:
            dry_run = True
            silent_mode = True

        res = self.send_text(
            target=target,
            text=message_text,
            dry_run=dry_run,
            silent_mode=silent_mode,
            confirm_send=confirm_send,
        )
        res["chatTestMode"] = mode
        res["generatedText"] = message_text
        res["binding"] = binding
        return res

    def batch_send(
        self,
        items: List[Dict[str, str]],
        *,
        dry_run: bool = True,
        silent_mode: bool = True,
        confirm_send: bool = False,
        allowed_groups: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        ok_count = 0
        blocked_count = 0
        for idx, item in enumerate(items):
            if idx > 0 and not dry_run:
                self.jitter.sleep_before_action()
            res = self.send_text(
                item.get("target", ""),
                item.get("text", ""),
                dry_run=dry_run,
                silent_mode=silent_mode,
                confirm_send=confirm_send,
                allowed_groups=allowed_groups,
                apply_jitter=False,
            )
            results.append(res)
            if res.get("ok"):
                ok_count += 1
            else:
                blocked_count += 1
        return {
            "ok": blocked_count == 0,
            "total": len(items),
            "succeeded": ok_count,
            "blockedOrFailed": blocked_count,
            "results": results,
        }

    # ------------------------------------------------------------------
    # Customer Service Knowledge Base, Terminology, Persona & Real-time Monitor
    # ------------------------------------------------------------------

    def kb_list(
        self,
        *,
        kind: Optional[str] = None,
        library: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        self._require("status")
        return self.knowledge.list_entries(kind=kind, library=library, limit=limit)

    def kb_search(
        self,
        query: str,
        *,
        kind: Optional[str] = None,
        library: Optional[str] = None,
        external_only: bool = True,
        limit: int = 6,
    ) -> Dict[str, Any]:
        self._require("status")
        return self.knowledge.search_context(
            query,
            kind=kind,
            library=library,
            external_only=external_only,
            limit=limit,
        )

    def kb_save(
        self,
        *,
        title: str,
        body: str,
        kind: str = "knowledge",
        library: str = "shared",
        keywords: Optional[Iterable[str]] = None,
        synonyms: Optional[Iterable[str]] = None,
        source: str = "wechat-plugin",
        external: bool = True,
        status: str = "published",
        entry_id: Optional[str] = None,
        expected_revision: int = 0,
    ) -> Dict[str, Any]:
        self._require("status")
        res = self.knowledge.save_entry(
            title=title,
            body=body,
            kind=kind,
            library=library,
            keywords=keywords,
            synonyms=synonyms,
            source=source,
            external=external,
            status=status,
            entry_id=entry_id,
            expected_revision=expected_revision,
        )
        self.audit.log("kb_save", "ok", {"entryId": res["entry"]["id"], "kind": kind, "title": title})
        return res

    def kb_withdraw(self, entry_id: str, *, expected_revision: int = 1) -> Dict[str, Any]:
        self._require("status")
        res = self.knowledge.withdraw_entry(entry_id, expected_revision=expected_revision)
        self.audit.log("kb_withdraw", "ok", {"entryId": entry_id, "revision": res["entry"]["revision"]})
        return res

    def kb_sync_openbot(self, source_db_path: Optional[Path] = None) -> Dict[str, Any]:
        self._require("status")
        target_src = Path(source_db_path) if source_db_path else DEFAULT_OPENBOT_KNOWLEDGE_DB
        res = self.knowledge.sync_from_openbot_knowledge(target_src)
        self.audit.log(
            "kb_sync_openbot",
            "ok" if res.get("ok") else "skipped",
            {
                "sourceDb": str(target_src),
                "importedEntries": res.get("importedEntries", 0),
                "importedStyles": res.get("importedStyles", 0),
            },
        )
        return res

    def persona_list(self) -> Dict[str, Any]:
        self._require("status")
        return self.personas.list_personas()

    def persona_switch(
        self,
        target: str,
        persona_id: str,
        *,
        mbti: Optional[str] = None,
        interaction_style: Optional[str] = None,
        custom_note: str = "",
    ) -> Dict[str, Any]:
        self._require("status")
        res = self.personas.switch_contact_persona(
            self.bindings,
            target,
            persona_id,
            mbti=mbti,
            interaction_style=interaction_style,
            custom_note=custom_note,
        )
        self.audit.log(
            "persona_switch",
            "ok",
            {"target": target, "personaId": res["persona"]["id"], "mbti": res["persona"]["mbti"]},
        )
        return res

    def preview_smart_reply(
        self,
        target: str,
        incoming_text: str,
        *,
        persona_override: Optional[str] = None,
        model_id: Optional[str] = None,
        use_llm: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        binding = self.bindings.get_binding(target)
        recent = self._recent_messages_for(target)
        memory_context = self.soul_profiler.get_contact_memory_context(target)
        return self.personas.generate_smart_reply(
            target,
            incoming_text,
            knowledge_store=self.knowledge,
            binding=binding,
            persona_override=persona_override,
            recent_messages=recent,
            memory_context=memory_context,
            model_hub=self.models,
            model_id=model_id,
            use_llm=use_llm,
        )

    # ------------------------------------------------------------------
    # Magpie Multi-Provider & Multi-Model Hub
    # ------------------------------------------------------------------

    def list_models(
        self,
        *,
        refresh: bool = False,
        provider_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        return self.models.get_summary(refresh=refresh, provider_filter=provider_filter)

    def select_model(
        self,
        *,
        model_id: str = "",
        contact: Optional[str] = None,
        provider_id: Optional[str] = None,
        fallback_model_id: Optional[str] = None,
        llm_enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        res = self.models.use_model(
            model_id=model_id,
            contact=contact,
            provider_id=provider_id,
            fallback_model_id=fallback_model_id,
            llm_enabled=llm_enabled,
        )
        self.audit.log(
            "model_select",
            "ok",
            {
                "activeModelId": res.get("activeModelId"),
                "fallbackModelId": res.get("fallbackModelId"),
                "contact": contact,
                "llmReplyEnabled": res.get("llmReplyEnabled"),
            },
        )
        return res

    def probe_model(
        self,
        *,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        prompt: str = "请用不超过20个字回复：收到测试，状态正常。",
    ) -> Dict[str, Any]:
        self._require("status")
        res = self.models.probe_model(model_id=model_id, provider_id=provider_id, prompt=prompt)
        self.audit.log(
            "model_probe",
            "ok" if res.get("ok") else "failed",
            {
                "modelId": res.get("modelId"),
                "providerId": res.get("providerId"),
                "latencyMs": res.get("latencyMs"),
                "statusCode": res.get("statusCode"),
            },
        )
        return res

    def save_provider(
        self,
        *,
        provider_id: Optional[str] = None,
        name: str = "",
        base_url: str = "",
        api: str = "openai-completions",
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
        default_model: str = "",
        vendor: str = "Custom",
        enabled: bool = True,
        gateway_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        if (not provider_id or provider_id == "magpie-gateway") and gateway_url:
            summary = self.models.configure_gateway(gateway_url=gateway_url, api_key=api_key)
            res: Dict[str, Any] = {"ok": True, "summary": summary}
        else:
            pid = str(provider_id or "custom-openai").strip()
            res = self.models.upsert_provider(
                provider_id=pid,
                name=name or pid,
                base_url=base_url or gateway_url or "",
                api=api,
                api_key=api_key,
                api_key_env=api_key_env,
                default_model=default_model,
                vendor=vendor,
                enabled=enabled,
            )
        self.audit.log(
            "provider_save",
            "ok",
            {"providerId": provider_id or "magpie-gateway", "hasKey": bool(api_key)},
        )
        return res

    def monitor_status(self) -> Dict[str, Any]:
        self._require("status")
        return self.monitor.get_status()

    def activate_wechat(self) -> Dict[str, Any]:
        self._require("status")
        res = self._run_native(["activate"], 12.0)
        self.audit.log(
            "activate_wechat",
            "ok" if res.get("ok") else "failed",
            {"recoveryMethod": res.get("recoveryMethod"), "windowCount": res.get("windowCount", 0)},
        )
        return res

    def takeover_contact(self, target: str, reason: str = "") -> Dict[str, Any]:
        self._require("status")
        res = self.monitor.takeover_contact(target, reason=reason)
        self.audit.log("takeover_contact", "ok", {"target": target, "reason": reason})
        return res

    def resume_contact(self, target: str) -> Dict[str, Any]:
        self._require("status")
        res = self.monitor.resume_contact(target)
        self.audit.log("resume_contact", "ok", {"target": target})
        return res

    def monitor_once(
        self,
        *,
        target: Optional[str] = None,
        auto_reply: bool = True,
        confirm_send: bool = False,
    ) -> Dict[str, Any]:
        self._require("read_sessions")
        self._require("read_messages")
        self._require("ocr")
        if auto_reply:
            self._require("send_text_live" if confirm_send else "send_text_dry_run")
        res = self.monitor.poll_once(
            target_filter=target,
            auto_reply=auto_reply,
            confirm_send=confirm_send,
        )
        self.audit.log(
            "monitor_once",
            "ok" if res.get("ok") else "error",
            {"target": target, "confirmSend": confirm_send, "repliesDispatched": res.get("repliesDispatched", 0)},
        )
        return res

    def monitor_loop(
        self,
        *,
        interval_seconds: float = 2.5,
        max_cycles: Optional[int] = None,
        target: Optional[str] = None,
        auto_reply: bool = True,
        confirm_send: bool = False,
    ) -> Dict[str, Any]:
        self._require("read_sessions")
        self._require("read_messages")
        self._require("ocr")
        if auto_reply:
            self._require("send_text_live" if confirm_send else "send_text_dry_run")
        return self.monitor.run_loop(
            interval_seconds=interval_seconds,
            max_cycles=max_cycles,
            target_filter=target,
            auto_reply=auto_reply,
            confirm_send=confirm_send,
        )

    # ------------------------------------------------------------------
    # 首页「一键托管好友」：勾选好友 → 开启托管（机器人只负责被托管好友的真发送回复）

    def start_hosting(self, targets: List[str]) -> Dict[str, Any]:
        """为 targets 确保绑定存在且 auto_reply_enabled=True，并启动托管循环（真发送）。"""
        clean = [str(t).strip() for t in (targets or []) if str(t).strip()]
        if not clean:
            return {"ok": False, "error": "HOSTING_TARGETS_REQUIRED"}
        self._require("read_sessions")
        self._require("read_messages")
        self._require("ocr")
        self._require("send_text_live")
        applied: List[str] = []
        for target in clean:
            existing = self.bindings.get_binding(target) or {}
            res = self.bind_contact(
                target,
                alias=str(existing.get("alias", "")),
                role=str(existing.get("role", "friend")),
                auto_reply_enabled=True,
            )
            if res.get("ok"):
                applied.append(target)
        if not applied:
            return {"ok": False, "error": "HOSTING_BIND_FAILED"}
        res = self.hosting_manager.start(applied)
        self.audit.log(
            "hosting_start",
            "ok" if res.get("ok") else "failed",
            {"targets": applied, "intervalSeconds": res.get("intervalSeconds")},
        )
        return {"ok": bool(res.get("ok")), "applied": applied, **res}

    def stop_hosting(
        self,
        targets: Optional[List[str]] = None,
        disable_replies: bool = False,
    ) -> Dict[str, Any]:
        """停止托管循环；disable_replies=True 时同时把 targets 的 auto_reply_enabled 置 False。"""
        res = self.hosting_manager.stop()
        disabled: List[str] = []
        if disable_replies:
            for target in targets or []:
                clean = str(target).strip()
                if not clean:
                    continue
                existing = self.bindings.get_binding(clean) or {}
                res_one = self.bind_contact(
                    clean,
                    alias=str(existing.get("alias", "")),
                    role=str(existing.get("role", "friend")),
                    auto_reply_enabled=False,
                )
                if res_one.get("ok"):
                    disabled.append(clean)
        self.audit.log("hosting_stop", "ok", {"disabledReplies": disabled})
        return {"ok": True, "disabledReplies": disabled, **res}

    def hosting_status(self) -> Dict[str, Any]:
        self._require("status")
        return {"ok": True, **self.hosting_manager.status()}

    def permissions_status(self) -> Dict[str, Any]:
        """实时检查 macOS 三项关键权限（辅助功能/系统事件/屏幕录制），供启动引导面板。

        每次都真实调用原生 status（不缓存），确保用户在系统设置里改完点「重新检查」立即生效。
        """
        self._require("status")
        try:
            res = self._run_native(["status"], 8.0)
        except Exception as exc:
            return {"ok": False, "error": f"native_probe_failed: {exc}"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "native status failed")}
        accessibility = bool(res.get("accessibilityTrusted"))
        post_event = bool(res.get("postEventTrusted"))
        screen_capture = bool(res.get("screenCaptureTrusted"))
        items = [
            {"id": "accessibility", "name": "辅助功能", "granted": accessibility,
             "purpose": "读取微信窗口内容、定位会话与输入框",
             "pane": "Privacy_Accessibility",
             "deepLink": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"},
            {"id": "post_event", "name": "系统事件控制", "granted": post_event,
             "purpose": "模拟点击与键盘输入，用于自动回复发送",
             "pane": "Privacy_Accessibility",
             "deepLink": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"},
            {"id": "screen_capture", "name": "屏幕录制", "granted": screen_capture,
             "purpose": "截屏识别聊天文字（Vision OCR），没有它巡检是“睁眼瞎”",
             "pane": "Privacy_ScreenRecording",
             "deepLink": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenRecording"},
        ]
        return {
            "ok": True,
            "items": items,
            "allGranted": accessibility and post_event and screen_capture,
            "wechatRunning": bool(res.get("wechatRunning")),
            "wechatPid": res.get("wechatPid"),
        }

    def sync_hosting_histories(self) -> Dict[str, Any]:
        """把托管轮询观察到的新往来消息回写进联系人历史文件（准实时）。

        数据源：monitor_events 里的 auto_reply_sent / preview_reply / takeover_draft_only
        （带 target + incomingText + replyText）。按 (方向,文本) 去重、限长 500 条、原子写。
        """
        self._require("status")
        events = self.monitor.recent_events(limit=120)
        interesting = [e for e in events if e.get("event") in (
            "auto_reply_sent", "preview_reply", "takeover_draft_only", "handoff_requested", "manual_send",
        ) and e.get("target")]
        if not interesting:
            return {"ok": True, "appended": 0, "files": []}
        contacts_dir = self.inspector.reports_dir / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        appended = 0
        touched: List[str] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        def _slug6(target: str) -> str:
            return hashlib.sha1(normalize_chat_name(target).encode("utf-8")).hexdigest()[:6]

        def _record_key(direction: str, text: str, marker: str) -> str:
            raw = f"{direction}|{text}|{marker}"
            return hashlib.sha1(raw.encode("utf-8")).hexdigest()

        by_file: Dict[str, Dict[str, Any]] = {}
        for e in interesting:
            target = str(e.get("target"))
            slug = _slugify_target(target) or _slug6(target)
            fname = contacts_dir / f"{target}_{slug}_history.json"
            doc = by_file.get(str(fname))
            if doc is None:
                if fname.exists():
                    try:
                        doc = json.loads(fname.read_text(encoding="utf-8"))
                    except Exception:
                        doc = None
                if not isinstance(doc, dict) or not doc.get("target"):
                    doc = {
                        "ok": True,
                        "target": target,
                        "matchedTitle": target,
                        "slug": slug,
                        "observedAt": now_iso,
                        "pages": [],
                        "recordCount": 0,
                        "records": [],
                    }
                doc.setdefault("records", [])
                doc["target"] = target
                doc["matchedTitle"] = doc.get("matchedTitle") or target
                doc.setdefault("recordKeys", [])
                by_file[str(fname)] = doc
            keys = set(doc.get("recordKeys") or [])
            for r in doc.get("records", []):
                keys.add(_record_key(str(r.get("direction") or ""), str(r.get("text") or ""), str(r.get("timeMarker") or "")))
                # 内容级去重（无 marker 也算重复）：同一轮遮挡重试会对同一消息重复发 auto_reply_sent 事件，
                # 该事件无 timeMarker，若 key 含时间则去重必然失效
                keys.add(_record_key(str(r.get("direction") or ""), str(r.get("text") or ""), ""))
            incoming = str(e.get("incomingText") or "").strip()
            reply = str(e.get("replyText") or "").strip()
            marker = str(e.get("timeMarker") or now_iso[:16].replace("T", " "))
            for direction, text in (("peer", incoming), ("self", reply)):
                if not text:
                    continue
                if _looks_like_timestamp(text):
                    continue  # OCR 时间戳行误分类为 message，不入历史
                k = _record_key(direction, text, marker)
                k_no_time = _record_key(direction, text, "")
                if k in keys or k_no_time in keys:
                    continue
                keys.add(k)
                keys.add(k_no_time)
                doc["records"].append({
                    "text": text,
                    "kind": "message",
                    "direction": direction,
                    "timeMarker": marker,
                    "ts": now_iso,
                    # actor 区分：auto_reply_sent/takeover/handoff 来自机器人托管；manual_send 来自人工本人
                    "source": "manual_human" if e.get("event") == "manual_send" else "hosting",
                })
                appended += 1
            doc["recordKeys"] = list(keys)[-800:]
            records = doc["records"]
            if len(records) > 500:
                doc["records"] = records[-500:]
            doc["recordCount"] = len(doc["records"])
            doc["historyPath"] = str(fname)
            touched.append(str(fname))

        for fname_str, doc in by_file.items():
            try:
                tmp = Path(fname_str + ".tmp")
                tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(Path(fname_str))
            except OSError:
                pass
        if appended:
            self.audit.log("hosting_history_sync", "ok", {"appended": appended, "files": len(touched)})
        return {"ok": True, "appended": appended, "files": touched}

    def hosting_friends(self) -> Dict[str, Any]:
        """好友清单 + 每人的托管/接管状态，供首页勾选列表渲染。"""
        self._require("status")
        mon = self.monitor.get_status(event_limit=0)
        contacts_state = mon.get("contacts", {}) or {}

        def _taken_over(target: str) -> bool:
            for key in (normalize_chat_name(target).casefold(), target):
                entry = contacts_state.get(key)
                if entry:
                    return bool(entry.get("takenOver"))
            return False

        friends: List[Dict[str, Any]] = []
        seen = set()
        binding_alias: Dict[str, str] = {}
        for b in self.bindings.list_bindings():
            t = str(b.get("target") or "")
            if t:
                binding_alias[normalize_chat_name(t).casefold()] = str(b.get("alias") or "")
        try:
            profiles = (self.profile_contacts() or {}).get("profiles", []) or []
        except Exception:
            profiles = []
        for p in profiles:
            target = str(p.get("target") or "")
            if not target or p.get("isFolderContainer"):
                continue
            key = normalize_chat_name(target).casefold()
            seen.add(key)
            friends.append({
                "target": target,
                "matchedTitle": binding_alias.get(key) or p.get("matchedTitle") or target,
                "bound": bool(p.get("bound")),
                "autoReplyEnabled": bool(p.get("autoReplyEnabled", False)),
                "takenOver": _taken_over(target),
                "careLevel": p.get("careLevel") or "normal",
            })
        # 已绑定但暂无画像样本的联系人也要出现在列表里
        for b in self.bindings.list_bindings():
            target = str(b.get("target") or "")
            if not target:
                continue
            key = normalize_chat_name(target).casefold()
            if key in seen:
                continue
            seen.add(key)
            friends.append({
                "target": target,
                "matchedTitle": b.get("alias") or target,
                "bound": True,
                "autoReplyEnabled": bool(b.get("autoReplyEnabled", True)),
                "takenOver": _taken_over(target),
                "careLevel": b.get("careLevel") or "normal",
            })
        friends.sort(key=lambda f: (not f["autoReplyEnabled"], not f["bound"], f["target"].casefold()))
        return {"ok": True, "friends": friends, "hosting": self.hosting_manager.status()}

    # ------------------------------------------------------------------
    # 历史聊天导入：扫描 *_history.json（含外部盘旧数据目录），勾选导入或一键全部导入

    def list_history_sources(self, source_dir: Optional[str] = None) -> Dict[str, Any]:
        self._require("status")
        raw = str(source_dir or "").strip()
        root = Path(raw).expanduser() if raw else (self.inspector.reports_dir / "contacts")
        sources: List[Dict[str, Any]] = []
        if root.exists():
            for f in sorted(root.glob("*_history.json")):
                target = f.stem
                record_count = 0
                observed_at = None
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    target = str(d.get("target") or f.stem)
                    record_count = int(d.get("recordCount") or len(d.get("records") or []) or 0)
                    observed_at = d.get("observedAt")
                except Exception:
                    pass
                sources.append({
                    "file": str(f),
                    "target": target,
                    "recordCount": record_count,
                    "observedAt": observed_at,
                    "alreadyImported": (self.inspector.reports_dir / "contacts" / f.name).exists(),
                })
        return {"ok": True, "sourceDir": str(root), "sources": sources}

    def import_histories(
        self,
        source_dir: Optional[str] = None,
        targets: Optional[List[str]] = None,
        import_all: bool = False,
    ) -> Dict[str, Any]:
        """把选中的（或全部）联系人历史导入当前工作区 logs/contacts/，并刷新画像。"""
        self._require("status")
        listing = self.list_history_sources(source_dir)
        sources = listing.get("sources", [])
        if import_all:
            selected = list(sources)
        else:
            want = {str(t).strip().casefold() for t in (targets or []) if str(t).strip()}
            selected = [s for s in sources if str(s.get("target", "")).strip().casefold() in want]
        if not selected:
            return {"ok": False, "error": "HISTORY_TARGETS_NOT_FOUND", "sourceDir": listing.get("sourceDir")}
        dest_dir = self.inspector.reports_dir / "contacts"
        dest_dir.mkdir(parents=True, exist_ok=True)
        imported: List[Dict[str, Any]] = []
        for s in selected:
            src = Path(s["file"])
            dest = dest_dir / src.name
            shutil.copy2(src, dest)
            imported.append({"target": s.get("target"), "file": str(dest), "recordCount": s.get("recordCount")})
        refreshed = self.profile_contacts() or {}
        profiles = refreshed.get("profiles", []) or []
        touched_names = {str(i.get("target")).casefold() for i in imported}
        touched = [
            {"target": p.get("target"), "messageCount": p.get("messageCount"), "bound": p.get("bound")}
            for p in profiles
            if str(p.get("target", "")).casefold() in touched_names
        ]
        self.audit.log("history_import", "ok", {
            "targets": [i.get("target") for i in imported],
            "sourceDir": listing.get("sourceDir"),
        })
        return {"ok": True, "imported": imported, "profilesTouched": touched}

    def _latest_inbound_by_target(self) -> Dict[str, Dict[str, str]]:
        """从联系人历史文件提取每位联系人的最近一条客户来信（含导入历史与托管实时回写）。"""
        out: Dict[str, Dict[str, str]] = {}
        contacts_dir = self.inspector.reports_dir / "contacts"
        if not contacts_dir.exists():
            return out
        for f in sorted(contacts_dir.glob("*_history.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            target = str(doc.get("target") or "").strip()
            if not target:
                continue
            latest = None
            for r in doc.get("records", []):
                if r.get("direction") == "peer" and str(r.get("text") or "").strip():
                    latest = r  # 顺序遍历，保留最后一条 peer 记录
            if not latest:
                continue
            key = normalize_chat_name(target).casefold()
            # 排序键：实时回写记录带 ISO ts；导入旧历史只有 timeMarker 时退回文件级 observedAt
            sort_at = str(latest.get("ts") or doc.get("observedAt") or "")
            out[key] = {
                "target": target,
                "text": str(latest.get("text")).strip()[:120],
                "at": str(latest.get("timeMarker") or latest.get("ts") or ""),
                "sortAt": sort_at,
            }
        return out

    def _recent_threads_by_target(self, limit: int = 8) -> Dict[str, Dict[str, Any]]:
        """每位联系人最近 limit 条往来消息（peer/self，时间正序），供首页点会话行带入上下文。"""
        out: Dict[str, Dict[str, Any]] = {}
        contacts_dir = self.inspector.reports_dir / "contacts"
        if not contacts_dir.exists():
            return out
        for f in sorted(contacts_dir.glob("*_history.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            target = str(doc.get("target") or "").strip()
            if not target:
                continue
            messages = []
            for r in doc.get("records", []):
                if r.get("kind") not in ("message", "media_note"):
                    continue
                text = str(r.get("text") or "").strip()
                if not text:
                    continue
                messages.append({
                    "direction": str(r.get("direction") or "peer"),
                    "kind": str(r.get("kind") or "message"),
                    "source": str(r.get("source") or "history"),
                    "text": text[:200],
                    "at": str(r.get("timeMarker") or r.get("ts") or ""),
                    "confidence": (lambda v: round(float(v), 2) if v is not None else None)(r.get("confidence")),
                })
            if not messages:
                continue
            key = normalize_chat_name(target).casefold()
            out[key] = {"target": target, "messages": messages[-limit:]}
        return out

    def import_chatlog_to_histories(
        self,
        source_path: str,
        target: str,
        owner_name: str = "",
    ) -> Dict[str, Any]:
        """把微信聊天记录文件（.zip/.txt/目录）解析后直接写进联系人历史（进入画像/往来上下文/来信兜底）。

        方向判定：sender == owner_name → self（我方），否则 peer（对方）。
        owner_name 留空时全部按 peer 记录（sender 保留在 record 里可后补修正）。
        """
        self._require("import_chatlog")
        clean_target = str(target or "").strip()
        if not clean_target:
            return {"ok": False, "error": "CHATLOG_TARGET_REQUIRED"}
        res = self.import_chatlog(Path(source_path))
        bundle = res.get("bundle") or {}
        records = bundle.get("records") or []
        if not records:
            return {"ok": False, "error": "CHATLOG_NO_RECORDS_PARSED", "sourcePath": str(source_path)}
        owner = str(owner_name or "").strip()
        slug = _slugify_target(clean_target) or hashlib.sha1(normalize_chat_name(clean_target).encode("utf-8")).hexdigest()[:6]
        contacts_dir = self.inspector.reports_dir / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        dest = contacts_dir / f"{clean_target}_{slug}_history.json"
        now_iso = datetime.now(timezone.utc).isoformat()
        history_records = []
        for r in records:
            content = str(r.get("content") or "").strip()
            if not content:
                continue
            sender = str(r.get("sender") or "")
            history_records.append({
                "text": content[:200],
                "kind": "message",
                "direction": "self" if owner and sender == owner else "peer",
                "sender": sender,
                "timeMarker": str(r.get("timestamp") or ""),
                "ts": now_iso,
                "source": "chatlog-import",
            })
        doc = {
            "ok": True,
            "target": clean_target,
            "matchedTitle": clean_target,
            "slug": slug,
            "observedAt": now_iso,
            "pages": [],
            "recordCount": len(history_records),
            "records": history_records,
            "historyPath": str(dest),
            "sourceChatlog": str(source_path),
        }
        tmp = Path(str(dest) + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(dest)
        refreshed = self.profile_contacts() or {}
        profiles = refreshed.get("profiles", []) or []
        touched = [
            {"target": p.get("target"), "messageCount": p.get("messageCount"), "bound": p.get("bound")}
            for p in profiles if str(p.get("target", "")).casefold() == normalize_chat_name(clean_target).casefold()
        ]
        self.audit.log("chatlog_import", "ok", {
            "target": clean_target, "records": len(history_records), "source": str(source_path),
        })
        return {
            "ok": True,
            "target": clean_target,
            "imported": len(history_records),
            "historyFile": str(dest),
            "participants": bundle.get("participants") or [],
            "profilesTouched": touched,
        }

    def recent_history_thread(self, target: str, limit: int = 6) -> str:
        """单联系人最近 limit 条往来（peer/self，正序），拼成片段注入自动回复上下文。"""
        clean = str(target or "").strip()
        if not clean:
            return ""
        contacts_dir = self.inspector.reports_dir / "contacts"
        if not contacts_dir.exists():
            return ""
        # slug 因来源不同而异（AX 巡检 / 导入 / chatlog 文件），按前缀 glob 取最新文件
        matches = sorted(
            contacts_dir.glob(f"{clean}_*_history.json"),
            key=lambda p: p.stat().st_mtime,
        )
        if not matches:
            return ""
        try:
            doc = json.loads(matches[-1].read_text(encoding="utf-8"))
        except Exception:
            return ""
        lines = []
        for r in doc.get("records", []):
            if r.get("kind") not in ("message", "media_note"):
                continue
            text = str(r.get("text") or "").strip()
            if not text:
                continue
            who = "我方" if r.get("direction") == "self" else "对方"
            at = str(r.get("timeMarker") or r.get("ts") or "")
            lines.append(f"{who}：{text[:80]}（{at}）")
        if not lines:
            return ""
        return "\n".join(lines[-limit:])

    def llm_gateway_status(self) -> Dict[str, Any]:
        """LLM 网关探活：Magpie 网关挂掉时回复会静默降级为模板——首页必须可见。"""
        self._require("status")
        try:
            llm_enabled = bool(self.models.is_llm_enabled())
        except Exception:
            llm_enabled = False
        try:
            gateway_url = str(getattr(self.models, "state", {}).get("gatewayUrl") or "")
        except Exception:
            gateway_url = ""
        if not gateway_url:
            try:
                from .magpie_provider_hub import DEFAULT_GATEWAY_URL
                gateway_url = DEFAULT_GATEWAY_URL
            except Exception:
                gateway_url = ""
        reachable = False
        parsed = urllib.parse.urlparse(gateway_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=0.8):
                reachable = True
        except OSError:
            reachable = False
        note = ""
        if not llm_enabled:
            note = "LLM 回复开关未开启"
        elif not reachable:
            note = "网关不可达，自动回复正降级为模板话术——请启动 Magpie"
        return {
            "ok": True,
            "llmEnabled": llm_enabled,
            "gatewayUrl": gateway_url,
            "reachable": reachable,
            "note": note,
        }

    def relaunch_llm_gateway(self) -> Dict[str, Any]:
        """一键自愈：网关不可达时拉起 Magpie 应用并复探活。

        只做「open -a magpie」（macOS 标准启动），不杀进程、不改配置；拉起失败时如实报因。
        """
        self._require("status")
        before = self.llm_gateway_status()
        if before.get("reachable"):
            return {"ok": True, "alreadyUp": True, "gateway": before}
        app_dir = Path.home() / "Applications" / "magpie.app"
        system_dir = Path("/Applications/magpie.app")
        if not app_dir.exists() and not system_dir.exists():
            return {"ok": False, "error": "MAGPIE_APP_NOT_FOUND", "searched": [str(app_dir), str(system_dir)]}
        try:
            res = subprocess.run(["/usr/bin/open", "-a", "magpie"], capture_output=True, timeout=10.0)
            if res.returncode != 0:
                return {"ok": False, "error": "OPEN_FAILED", "stderr": res.stderr.decode("utf-8", "replace")[:200]}
        except Exception as exc:
            return {"ok": False, "error": f"OPEN_ERROR: {exc}"}
        # 给网关起监听的时间，然后复探
        time.sleep(2.0)
        after = self.llm_gateway_status()
        self.audit.log("llm_gateway_relaunch", "ok" if after.get("reachable") else "still_down",
                       {"gatewayUrl": after.get("gatewayUrl")})
        return {"ok": True, "relaunched": True, "gateway": after}

    def append_media_note(self, target: str, note: str) -> bool:
        """把链接/图片深读摘要持久化进联系人历史（kind=media_note），供后续回复上下文引用。"""
        clean = str(target or "").strip()
        note_text = str(note or "").strip()
        if not clean or not note_text:
            return False
        contacts_dir = self.inspector.reports_dir / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        matches = sorted(
            contacts_dir.glob(f"{clean}_*_history.json"),
            key=lambda p: p.stat().st_mtime,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        if not matches:
            # 该联系人尚无历史文件：创建一个（与 sync_hosting_histories 的结构一致）
            slug = _slugify_target(clean) or hashlib.sha1(normalize_chat_name(clean).encode("utf-8")).hexdigest()[:6]
            path = contacts_dir / f"{clean}_{slug}_history.json"
            doc = {
                "ok": True, "target": clean, "matchedTitle": clean, "slug": slug,
                "observedAt": now_iso, "pages": [], "recordCount": 0,
                "records": [], "recordKeys": [], "historyPath": str(path),
            }
        else:
            path = matches[-1]
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return False
            if not isinstance(doc, dict) or not doc.get("target"):
                return False
        doc.setdefault("records", [])
        doc["records"].append({
            "text": note_text[:200],
            "kind": "media_note",
            "direction": "system",
            "ts": now_iso,
            "source": "deep_read",
        })
        if len(doc["records"]) > 500:
            doc["records"] = doc["records"][-500:]
        doc["recordCount"] = len(doc["records"])
        doc["historyPath"] = str(path)
        try:
            tmp = Path(str(path) + ".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            self.audit.log("media_note_persist", "ok", {"target": clean, "note": note_text[:80]})
            return True
        except OSError:
            return False

    def voice_to_text_via_menu(self, bubble_x: float, bubble_y: float, menu_item: str = "转文字") -> Dict[str, Any]:
        """利用微信生态自带的语音转文字：右键语音气泡 → 点菜单「转文字」→ 前后帧 diff 读结果。

        bubble_x/bubble_y 为屏幕绝对坐标（capture-ocr 输出即绝对坐标）。
        流程每步失败如实返回 error_code，不伪装成功。
        """
        self._require("read_messages")
        self._require("ocr")

        def _capture(elements_only: bool = False) -> Dict[str, Any]:
            cap = self._run_native(["capture-ocr", "--out", str(self.inspector.snapshots_dir / "voice_menu_probe.png")], 15.0)
            if not cap.get("ok"):
                return {}
            if elements_only:
                return {str(e.get("text", "")).strip(): e.get("center") for e in cap.get("elements") or [] if e.get("text")}
            return cap

        # 1) 右键语音气泡 → 上下文菜单
        self._run_native(["right-click", "--x", str(bubble_x), "--y", str(bubble_y)], 10.0)
        time.sleep(0.9)
        menu = _capture(elements_only=True)
        target_center = None
        for text, center in menu.items():
            if menu_item in text and center:
                target_center = center
                break
        if not target_center:
            return {"ok": False, "error_code": "voice_menu_item_not_found",
                    "menuItems": list(menu.keys())[:10], "hint": f"未在菜单里找到「{menu_item}」"}
        # 2) 点击菜单项
        self._run_native(["click", "--x", str(target_center.get("x")), "--y", str(target_center.get("y"))], 10.0)
        time.sleep(1.6)  # 微信转文字识别中
        # 3) 读转出的文字（转文字结果通常出现在原气泡附近的新增文本行）
        after_cap = _capture()
        after_text = str(after_cap.get("text") or "")
        before_text = ""
        try:
            before_path = self.inspector.snapshots_dir / "voice_menu_probe.png"
            res = self._run_native(["ocr", "--image", str(before_path)], 15.0)
            before_text = str(res.get("text") or "")
        except Exception:
            pass
        # 帧间 diff：新增的行即转文字结果（去掉菜单残留）
        before_lines = {ln.strip() for ln in before_text.splitlines() if ln.strip()}
        new_lines = [ln.strip() for ln in after_text.splitlines()
                     if ln.strip() and ln.strip() not in before_lines and menu_item not in ln]
        converted = " ".join(new_lines).strip()
        if not converted:
            return {"ok": False, "error_code": "voice_text_empty", "hint": "转换后未见新增文本（可能语音为空或界面差异）"}
        return {"ok": True, "text": converted[:300]}

    def push_pending_draft_to_workbench(self, target: str, msgid: str, incoming: str, draft: str) -> Dict[str, Any]:
        """人工接管期间生成的回复草稿同步进待办审阅台，让人工真的看得到、能一键发送。

        幂等：同 msgid 重复触发不会产生重复待办（draft id 由 msgid 确定性派生）。
        """
        self._require("status")
        from .saved_drafts import SavedDraftStore

        draft = str(draft or "").strip()
        incoming = str(incoming or "").strip()
        if not draft or not incoming:
            return {"ok": False, "error": "EMPTY_DRAFT"}
        # msgid（微信侧唯一）→ 32 位 hex 的确定性 draft id
        digest = hashlib.sha1(f"{normalize_chat_name(target)}|{msgid}".encode("utf-8")).hexdigest()
        store = SavedDraftStore(self.auth_gate.auth_file.parent / "workbench" / "saved-drafts.sqlite")
        try:
            store.save({
                "id": digest[:32],
                "version": 0,
                "target": str(target)[:256],
                "incoming": incoming[:3000],
                "draft": draft[:3000],
            })
        except Exception as exc:
            code = getattr(exc, "code", "")
            if code == "saved_draft_changed":
                return {"ok": False, "error": "SAVED_DRAFT_CHANGED"}
            return {"ok": False, "error": str(exc)[:160]}
        self.audit.log("pending_draft_to_workbench", "ok", {"target": target, "draftId": digest[:32]})
        return {"ok": True, "draftId": digest[:32]}

    def avatar_capture(self, target: str, snapshot_path: str = "", crop: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        """按会话行坐标从巡检快照裁剪头像，保存到 avatars 目录，返回可访问 URL。"""
        self._require("status")
        clean = normalize_chat_name(str(target or ""))
        if not clean:
            return {"ok": False, "error": "AVATAR_TARGET_REQUIRED"}
        out_dir = self.inspector.snapshots_dir.parent / "avatars"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{clean}.png"
        snap = Path(snapshot_path) if snapshot_path else (self.inspector.snapshots_dir / "sessions_overview_p0.png")
        if not snap.is_file():
            snap = self.inspector.snapshots_dir / "monitor_poll_cur.png"
        if not snap.is_file():
            return {"ok": False, "error": "NO_SNAPSHOT"}
        region = crop or {"x": 8, "y": 40, "width": 40, "height": 40}
        res = self._run_native([
            "ocr", "--image", str(snap),
            "--crop", f"{int(region['x'])},{int(region['y'])},{int(region['width'])},{int(region['height'])}",
            "--out", str(out_path),
        ], 15.0)
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or res.get("error_code") or "crop_failed")}
        if not out_path.is_file() or out_path.stat().st_size < 200:
            return {"ok": False, "error": "EMPTY_AVATAR"}
        return {"ok": True, "target": clean, "url": f"/avatars/{clean}.png", "path": str(out_path)}

    def get_web_overview(self) -> Dict[str, Any]:
        """Aggregate dashboard state for the local Web Control Console."""
        self._require("status")
        doc = self.doctor()
        analytics = self.profile_contacts()
        mon = self.monitor.get_status(event_limit=30)
        kb = self.knowledge.list_entries(limit=120)
        kb_entries = kb.get("entries", [])
        by_kind: Dict[str, int] = {}
        for item in kb_entries:
            k = str(item.get("kind") or "knowledge")
            by_kind[k] = by_kind.get(k, 0) + 1
        pers = self.personas.list_personas()
        bindings_list = self.bindings.list_bindings()

        # Collect recent verified snapshots cleanly
        snap_entries: List[Dict[str, Any]] = []
        seen_names: set[str] = set()
        for base_dir in (self.inspector.snapshots_dir, self.plugin_root / "logs"):
            if not base_dir.exists():
                continue
            for p in sorted(base_dir.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True):
                if p.name in seen_names:
                    continue
                seen_names.add(p.name)
                snap_entries.append({
                    "name": p.name,
                    "url": f"/snapshots/{p.name}",
                    "mtime": p.stat().st_mtime,
                    "sizeBytes": p.stat().st_size,
                })
                if len(snap_entries) >= 12:
                    break

        # Kimi discussion artifact (optional)
        kimi_path = self.plugin_root / "logs" / "kimi_scenario_discussion.json"
        kimi_discussion: Optional[Dict[str, Any]] = None
        if kimi_path.exists():
            try:
                kimi_discussion = json.loads(kimi_path.read_text(encoding="utf-8"))
            except Exception:
                kimi_discussion = None

        # Recent audit entries (tail)
        audit_entries: List[Dict[str, Any]] = []
        if self.audit.log_path.exists():
            try:
                lines = [ln.strip() for ln in self.audit.log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                for ln in reversed(lines[-20:]):
                    try:
                        audit_entries.append(json.loads(ln))
                    except Exception:
                        continue
            except Exception:
                pass

        mcp_config = {
            "mcpServers": {
                "wechat-rpa-control": {
                    "command": "python3",
                    "args": ["-m", "wechat_control.cli", "serve-mcp"],
                    "cwd": str(self.plugin_root),
                }
            }
        }

        return {
            "ok": True,
            "pluginId": doc.get("pluginId"),
            "pluginRoot": str(self.plugin_root),
            "authorization": doc.get("studioAuthorization"),
            "doctor": doc,
            "wechatStatus": doc.get("status"),
            "monitor": mon,
            "latestInbound": self._latest_inbound_by_target(),
            "recentThreads": self._recent_threads_by_target(),
            "antiban": self.antiban.status(),
            "llmGateway": self.llm_gateway_status(),
            "bindings": bindings_list,
            "analytics": analytics,
            "personas": pers,
            "models": self.models.get_summary(refresh=False),
            "knowledgeSummary": {
                "count": kb.get("count", 0),
                "byKind": by_kind,
                "entries": kb_entries[:60],
                "dbPath": kb.get("dbPath"),
                "style": kb.get("style"),
            },
            "snapshots": snap_entries,
            "auditRecent": audit_entries,
            "kimiDiscussion": kimi_discussion,
            "mcpConfig": mcp_config,
            "exportedArticles": self.article_exporter.list_exported_articles(limit=20),
            "exportedArticlesCount": len(self.article_exporter.list_exported_articles(limit=100)),
            "exportedAccounts": self.article_exporter.list_exported_accounts(limit=20),
            "exportedChannels": self.article_exporter.list_exported_channels(limit=20),
            "humanGuard": self.human_guard.check_can_operate(doc.get("status")),
            "uiProtocolSummary": {
                "schemaVersion": self.ui_protocol.get_protocol_schema().get("schemaVersion"),
                "viewsCount": self.ui_protocol.get_protocol_schema().get("viewsCount"),
                "regionsCount": self.ui_protocol.get_protocol_schema().get("regionsCount"),
                "targetsCount": self.ui_protocol.get_protocol_schema().get("targetsCount"),
            },
            "soulSummary": self.soul_profiler.get_profiles(),
            "benchmarkSummary": self.benchmark_suite.get_latest_report(),
            "botStudioBridge": self.botstudio_bridge.get_status(),
            "visionStack": self.get_vision_stack_info(),
            "agentTasks": self.get_agent_tasks(limit=12),
            "mediaAnalyses": self.get_media_analyses(limit=12),
            "sidebarDockStatus": self.dock_app_to_wechat("verify"),
            "salesCrm": self.sales_crm.get_overview(auto_sync=True),
        }

    # ------------------------------------------------------------------
    # Human Activity Guard & Standardized UI Protocol
    # ------------------------------------------------------------------

    def get_human_guard_status(self) -> Dict[str, Any]:
        """Inspect real-time human mouse/keyboard idle state and cooldown status."""
        self._require("status")
        return self.human_guard.check_can_operate()

    def configure_human_guard(
        self,
        *,
        enabled: Optional[bool] = None,
        idle_resume_seconds: Optional[float] = None,
        cooldown_seconds: Optional[float] = None,
        reset_cooldown: bool = False,
    ) -> Dict[str, Any]:
        """Update human mouse/keyboard detection cooldown and resume idle thresholds."""
        self._require("status")
        res = self.human_guard.configure(
            enabled=enabled,
            idle_resume_seconds=idle_resume_seconds,
            cooldown_seconds=cooldown_seconds,
            reset_cooldown=reset_cooldown,
        )
        self.audit.log(
            "configure_human_guard",
            "ok",
            {
                "enabled": res.get("enabled"),
                "idleResumeSeconds": res.get("idleResumeSeconds"),
                "cooldownSeconds": res.get("cooldownSeconds"),
                "resetCooldown": reset_cooldown,
            },
        )
        return res

    def get_ui_schema(self) -> Dict[str, Any]:
        """Return the standardized WeChat UI view/region/target protocol schema."""
        self._require("status")
        return self.ui_protocol.get_protocol_schema()

    def inspect_ui_state(self, *, refresh_ocr: bool = False) -> Dict[str, Any]:
        """Recognize active WeChat UI view and resolve live coordinates for all targets."""
        self._require("status")
        if refresh_ocr:
            self._require("ocr")
        return self.ui_protocol.inspect_ui_state(refresh_ocr=refresh_ocr)

    def navigate_ui(
        self,
        target_id: str,
        *,
        dry_run: bool = False,
        respect_human_guard: bool = True,
    ) -> Dict[str, Any]:
        """Execute or dry-run a protocolized semantic UI navigation action."""
        self._require("status")
        if not dry_run:
            self._require("ocr")
        res = self.ui_protocol.navigate_target(
            target_id,
            dry_run=dry_run,
            respect_human_guard=respect_human_guard,
        )
        self.audit.log(
            "navigate_ui",
            "ok" if res.get("ok") else ("blocked" if res.get("blockedByHumanGuard") else "failed"),
            {"targetId": target_id, "dryRun": dry_run, "blocked": res.get("blockedByHumanGuard", False)},
        )
        return res

    # ------------------------------------------------------------------
    # WeChat Article Export (Markdown + Local Assets)
    # ------------------------------------------------------------------

    def export_article(
        self,
        *,
        url: Optional[str] = None,
        from_window: bool = True,
        max_scroll_pages: int = 4,
        download_images: bool = True,
        try_copy_link: bool = True,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Export an open WeChat article or mp.weixin.qq.com URL to Markdown + local images."""
        self._require("status")
        out_path = Path(output_dir) if output_dir else None
        clean_url = (url or "").strip()
        if clean_url:
            res = self.article_exporter.export_from_url(
                clean_url,
                output_dir=out_path,
                download_images=download_images,
            )
        elif from_window:
            self._require("ocr")
            res = self.article_exporter.export_from_wechat_window(
                max_scroll_pages=max_scroll_pages,
                try_copy_link=try_copy_link,
                output_dir=out_path,
                download_images=download_images,
            )
        else:
            return {"ok": False, "error": "Either url or from_window=True must be provided."}

        self.audit.log(
            "export_article",
            "ok" if res.get("ok") else "failed",
            {
                "mode": res.get("mode", "url" if clean_url else "window"),
                "title": res.get("title", ""),
                "markdownPath": res.get("markdown_path", ""),
                "downloadedImages": res.get("downloaded_image_count", 0),
                "error": res.get("error", ""),
            },
        )
        return res

    def list_exported_articles(self, limit: int = 20) -> Dict[str, Any]:
        """List previously exported Markdown articles & local image bundles."""
        self._require("status")
        items = self.article_exporter.list_exported_articles(limit=limit)
        return {
            "ok": True,
            "exportRoot": str(self.article_exporter.export_root),
            "count": len(items),
            "articles": items,
        }

    def export_account_articles(
        self,
        *,
        account_name: str = "",
        album_url: str = "",
        album_html: str = "",
        article_urls: Optional[List[str]] = None,
        articles_html_list: Optional[List[Dict[str, str]]] = None,
        from_file: Optional[str] = None,
        scan_open_window: bool = False,
        scroll_pages: int = 4,
        download_images: bool = True,
        max_articles: int = 50,
    ) -> Dict[str, Any]:
        """Batch-export historical articles from a WeChat Official/Service Account."""
        self._require("status")
        if scan_open_window:
            self._require("ocr")
        res = self.article_exporter.export_account_articles(
            account_name=account_name,
            album_url=album_url,
            album_html=album_html,
            article_urls=article_urls,
            articles_html_list=articles_html_list,
            from_file=Path(from_file) if from_file else None,
            scan_open_window=scan_open_window,
            scroll_pages=scroll_pages,
            download_images=download_images,
            max_articles=max_articles,
        )
        self.audit.log(
            "export_account_articles",
            "ok" if res.get("ok") else "failed",
            {
                "accountName": res.get("accountName", account_name),
                "totalExported": res.get("exportedCount", 0),
                "totalDiscovered": res.get("totalDiscovered", 0),
                "indexPath": res.get("indexMarkdownPath", ""),
                "error": res.get("error", ""),
            },
        )
        return res

    def list_exported_accounts(self, limit: int = 20) -> Dict[str, Any]:
        """List previously batch-exported Official/Service Account archives."""
        self._require("status")
        items = self.article_exporter.list_exported_accounts(limit=limit)
        return {
            "ok": True,
            "exportRoot": str(self.article_exporter.export_root / "accounts"),
            "count": len(items),
            "accounts": items,
        }

    def export_channels_videos(
        self,
        *,
        author_name: str = "",
        video_items: Optional[List[Dict[str, Any]]] = None,
        video_urls: Optional[List[str]] = None,
        manifest_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        scan_open_window: bool = False,
        scroll_pages: int = 4,
        download_media: bool = True,
        max_videos: int = 50,
    ) -> Dict[str, Any]:
        """Batch-export WeChat Channels (视频号) author videos to local MP4/index archives."""
        self._require("status")
        if scan_open_window:
            self._require("ocr")
        res = self.article_exporter.export_channels_videos(
            author_name=author_name,
            video_items=video_items,
            video_urls=video_urls,
            manifest_path=Path(manifest_path) if manifest_path else None,
            cache_dir=Path(cache_dir) if cache_dir else None,
            scan_open_window=scan_open_window,
            scroll_pages=scroll_pages,
            download_media=download_media,
            max_videos=max_videos,
        )
        self.audit.log(
            "export_channels_videos",
            "ok" if res.get("ok") else "failed",
            {
                "authorName": res.get("authorName", author_name),
                "exportedCount": res.get("exportedCount", 0),
                "failedCount": res.get("failedCount", 0),
                "indexPath": res.get("indexMarkdownPath", ""),
                "error": res.get("error", ""),
            },
        )
        return res

    def list_exported_channels(self, limit: int = 20) -> Dict[str, Any]:
        """List previously exported WeChat Channels author video archives."""
        self._require("status")
        items = self.article_exporter.list_exported_channels(limit=limit)
        return {
            "ok": True,
            "exportRoot": str(self.article_exporter.export_root / "channels"),
            "count": len(items),
            "channels": items,
        }

    # ------------------------------------------------------------------
    # WeChatBridge Dual-Persona Soul, Memory & Benchmark Suite
    # ------------------------------------------------------------------

    def get_soul_profiles(
        self,
        *,
        target: Optional[str] = None,
        rebuild: bool = False,
        use_llm: bool = False,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return or rebuild Owner Self-Soul, Friend Psychological Profiles & Episodic Memories."""
        self._require("status")
        if rebuild:
            res = self.soul_profiler.build_profiles(
                target=target,
                use_llm=use_llm,
                model_hub=self.models,
                model_id=model_id,
            )
            self.audit.log(
                "build_soul_profiles",
                "ok",
                {
                    "target": target,
                    "useLlm": use_llm,
                    "contactCount": res.get("totalContactsAnalyzed", 0),
                },
            )
            return res
        return self.soul_profiler.get_profiles(target=target)

    def add_soul_memory(
        self,
        target: str,
        content: str,
        *,
        category: str = "fact",
        time_marker: str = "",
    ) -> Dict[str, Any]:
        """Persist a custom or episodic memory item for a contact and refresh their Soul Profile."""
        self._require("status")
        res = self.soul_profiler.add_memory_note(
            target,
            content,
            category=category,
            time_marker=time_marker,
        )
        self.audit.log(
            "add_soul_memory",
            "ok",
            {"target": target, "category": category},
        )
        return res

    def import_bridge_to_soul(
        self,
        source_path: Path,
        *,
        contact_name: Optional[str] = None,
        owner_sender: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ingest a WeChatBridge `.zip`/`聊天记录.txt` archive directly into Owner & Friend Soul/Memories."""
        self._require("import_chatlog")
        bundle = self.importer.load(Path(source_path))
        res = self.soul_profiler.ingest_bridge_archive(
            bundle,
            contact_name=contact_name,
            owner_sender=owner_sender,
        )
        self.audit.log(
            "import_bridge_to_soul",
            "ok",
            {
                "sourcePath": str(source_path),
                "contactName": res.get("contactName"),
                "selfCount": res.get("selfCount", 0),
                "peerCount": res.get("peerCount", 0),
            },
        )
        return res

    def run_benchmark(self, *, include_tests: bool = False) -> Dict[str, Any]:
        """Execute deterministic benchmarks across all WeChat RPA + Soul + Safety modules."""
        self._require("status")
        res = self.benchmark_suite.run_all(include_tests=include_tests)
        self.audit.log(
            "run_benchmark",
            "ok" if res.get("ok") else "partial",
            {
                "overallScore": res.get("overallScore"),
                "passedModules": res.get("passedModules"),
                "totalModules": res.get("totalModules"),
            },
        )
        return res

    def get_benchmark_report(self) -> Dict[str, Any]:
        """Return latest benchmark report and Kimi (codexma) acceptance status."""
        self._require("status")
        return self.benchmark_suite.get_latest_report()

    # ------------------------------------------------------------------
    # Standalone Software, Native DSH Plugin & Bot Studio Bridge
    # ------------------------------------------------------------------

    def get_botstudio_bridge_status(self) -> Dict[str, Any]:
        """Inspect standalone .app, native dsh.plugin.json, and Bot Studio workbench integration."""
        self._require("status")
        return self.botstudio_bridge.get_status()

    def compile_dsh_plugin_for_botstudio(self) -> Dict[str, Any]:
        """Compile dsh.plugin.json via dsh2codex into 4-Tab Bot Studio preset, package, and standalone page."""
        self._require("status")
        res = self.botstudio_bridge.compile_dsh_to_botstudio()
        self.audit.log(
            "botstudio_compile_dsh",
            "ok" if res.get("ok") else "error",
            {
                "engine": res.get("engine"),
                "dsh2codexVerified": res.get("dsh2codexVerified"),
                "presetId": res.get("presetId"),
            },
        )
        return res

    def export_botstudio_integration_bundle(self, out_path: Optional[str] = None) -> Dict[str, Any]:
        """Compile DSH manifest and export the unified Bot Studio integration bundle JSON."""
        self._require("status")
        target = Path(out_path) if out_path else None
        res = self.botstudio_bridge.export_integration_bundle(out_path=target)
        self.audit.log(
            "botstudio_export_bundle",
            "ok" if res.get("ok") else "error",
            {
                "bundlePath": res.get("bundlePath"),
                "dsh2codexVerified": res.get("dsh2codexVerified"),
                "engine": res.get("engine"),
            },
        )
        return res

    def rebuild_standalone_app(self, *, install_to_host: bool = True) -> Dict[str, Any]:
        """Rebuild and sign the standalone .app bundles without interactive prompts."""
        self._require("status")
        res = self.botstudio_bridge.rebuild_standalone_app(install_to_host=install_to_host)
        signing = res.get("signing") if isinstance(res.get("signing"), dict) else {}
        self.audit.log(
            "botstudio_rebuild_app",
            "ok" if res.get("ok") else "error",
            {
                "installToHost": bool(install_to_host),
                "zeroPopupVerified": signing.get("zeroPopupVerified"),
                "usesCdhash": signing.get("usesCdhash"),
                "returncode": res.get("returncode"),
            },
        )
        return res

    def install_to_host(
        self,
        *,
        launch_standalone: bool = False,
        launch_bot_studio: bool = False,
    ) -> Dict[str, Any]:
        """Install standalone WeChat Bot.app to /Users/mac/Applications and register in Bot Studio."""
        self._require("status")
        res = self.botstudio_bridge.install_to_host(
            launch_standalone=launch_standalone,
            launch_bot_studio=launch_bot_studio,
        )
        self.audit.log(
            "botstudio_install_host",
            "ok" if res.get("ok") else "error",
            {
                "installedApps": res.get("installedApps"),
                "registered": (res.get("botStudioRegistration") or {}).get("registered"),
                "launched": res.get("launched"),
            },
        )
        return res

    # ------------------------------------------------------------------
    # Aurora-73/SalesCRM open-source marketing CRM foundation
    # ------------------------------------------------------------------
    def crm_overview(self, *, auto_sync: bool = True) -> Dict[str, Any]:
        return self.sales_crm.get_overview(auto_sync=auto_sync)

    def crm_sync_from_wechat(self) -> Dict[str, Any]:
        res = self.sales_crm.sync_from_wechat()
        self.audit.log("crm_sync", "ok", {"synced": res.get("syncedContacts"), "ingested": res.get("ingestedMessages")})
        return res

    def crm_enroll_contact(
        self,
        target: str,
        *,
        stage: str = "新线索",
        note: str = "",
        follow_up: Optional[str] = None,
        deal_value: float = 0.0,
        alias: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        res = self.sales_crm.enroll_contact(
            target,
            stage=stage,
            note=note,
            follow_up=follow_up,
            deal_value=deal_value,
            alias=alias,
            tags=tags,
        )
        self.audit.log("crm_enroll", "ok", {"target": target, "stage": stage})
        return res

    def crm_update_record(
        self,
        target: str,
        *,
        stage: str,
        note: str,
        follow_up: Optional[str] = None,
        deal_value: Optional[float] = None,
    ) -> Dict[str, Any]:
        res = self.sales_crm.update_record(
            target,
            stage=stage,
            note=note,
            follow_up=follow_up,
            deal_value=deal_value,
        )
        self.audit.log("crm_update", "ok", {"target": target, "stage": stage})
        return res

    def crm_complete_reminder(self, target: str) -> Dict[str, Any]:
        res = self.sales_crm.complete_reminder(target)
        self.audit.log("crm_complete_reminder", "ok", {"target": target})
        return res

    def crm_reschedule_reminder(self, target: str, follow_up: str) -> Dict[str, Any]:
        res = self.sales_crm.reschedule_reminder(target, follow_up)
        self.audit.log("crm_reschedule_reminder", "ok", {"target": target, "follow_up": follow_up})
        return res

    def crm_list_reminders(self, *, now_ts: Optional[int] = None) -> Dict[str, Any]:
        return self.sales_crm.list_reminders(now_ts=now_ts)

    def crm_analyze_contact(
        self,
        target: str,
        *,
        incoming_text: str = "",
        formula_overrides: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        return self.sales_crm.analyze_contact(
            target,
            incoming_text=incoming_text,
            formula_overrides=formula_overrides,
        )

    def crm_evaluate_formulas(
        self,
        target: str,
        *,
        overrides: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        return self.sales_crm.evaluate_formulas(target, overrides=overrides)

    def crm_adopt_draft(
        self,
        target: str,
        *,
        rank_index: int = 1,
        send_mode: str = "adopt_only",
    ) -> Dict[str, Any]:
        res = self.sales_crm.adopt_draft(target, rank_index=rank_index, send_mode=send_mode)
        self.audit.log("crm_adopt_draft", "ok", {"target": target, "rank_index": rank_index, "send_mode": send_mode})
        return res

    def crm_merge_accounts(self, primary_target: str, secondary_target: str, *, alias: str = "") -> Dict[str, Any]:
        res = self.sales_crm.merge_accounts(primary_target, secondary_target, alias=alias)
        self.audit.log("crm_merge_accounts", "ok", {"primary": primary_target, "secondary": secondary_target})
        return res
    # ------------------------------------------------------------------

    def import_chatlog(self, source_path: Path, output_dir: Optional[Path] = None) -> Dict[str, Any]:
        self._require("import_chatlog")
        t0 = time.monotonic()
        bundle = self.importer.load(Path(source_path))
        exported: Dict[str, str] = {}
        if output_dir is not None:
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(source_path).stem or "chatlog"
            md_path = self.importer.export_markdown(bundle, out_dir / f"{stem}.md")
            jsonl_path = self.importer.export_jsonl(bundle, out_dir / f"{stem}.jsonl")
            exported["markdown"] = str(md_path)
            exported["jsonl"] = str(jsonl_path)

        elapsed_ms = round((time.monotonic() - t0) * 1000.0, 2)
        payload = {
            "ok": True,
            "elapsedMs": elapsed_ms,
            "bundle": bundle.to_dict(include_raw=False),
            "exportedFiles": exported,
        }
        self.audit.log(
            "import_chatlog",
            "ok",
            {
                "sourcePath": str(source_path),
                "recordCount": len(bundle.records),
                "attachmentCount": len(bundle.attachments),
                "exported": exported,
            },
        )
        return payload
