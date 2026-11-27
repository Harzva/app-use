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
import re
import shutil
import socket
import subprocess
import urllib.parse
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .agent_dispatcher import WeChatAgentDispatcher
from .app_use_studio import AppUseStudio
from .article_exporter import WeChatArticleExporter
from .auth_gate import StudioAuthGate, StudioPluginUnauthorizedError
from .benchmark_suite import WeChatRPABenchmarkSuite
from .botstudio_bridge import BotStudioBridgeManager
from .bridge_importer import WeChatBridgeImporter
from .call_brief import PreCallBriefEngine
from .coevolution_engine import DualProductCoevolutionEngine
from .contact_profiler import ContactBindingStore, ContactStyleProfiler, ContextualAIChatGenerator
from .corpus_discovery import CorpusDiscoveryEngine
from .doc_ingestor import ALLOWED_TEST_CONTACTS, AppWindowBinder, DocumentKnowledgeIngestor
from .human_activity_guard import HumanActivityGuard
from .knowledge_kf_engine import DEFAULT_OPENBOT_KNOWLEDGE_DB, PersonaSwitchEngine, WeChatKnowledgeStore
from .live_inspector import WeChatLiveInspector, _matches_target, _slugify_target
from .magpie_provider_hub import MagpieProviderHub
from .media_link_analyzer import WeChatMediaLinkAnalyzer
from .moments_hub import WeChatMomentsHub
from .multi_window_scheduler import MultiWindowScheduler
from .omni_channels import OmniChannelHub
from .playbook_trainer import SelfTrainingPlaybookEngine
from .realtime_monitor import _looks_like_timestamp, WeChatRealtimeMonitor
from .sales_crm_hub import WeChatSalesCRMHub
from .soul_memory_profiler import SoulMemoryProfiler
from .supervisor_eval import SupervisorEvalEngine, is_blocked_outbound_directive
from .tenant_profile import (
    DEFAULT_INDUSTRY_PACK,
    TenantProfileStore,
    list_sales_packs,
    load_sales_pack,
)
from .ui_schema import WeChatUIProtocolNavigator
from .io_utils import atomic_write_json
from .safety import (
    AntiBanGuard,
    AuditLogger,
    GroupAllowlistGuard,
    HumanJitter,
    OutgoingMessageRegistry,
    ReadbackVerifier,
    normalize_chat_name,
)

_BUNDLE_RES = Path(__file__).resolve().parent.parent

WORKOS_POST_PRESETS: Dict[str, Dict[str, str]] = {
    "private_ops": {
        "label": "私域运营专员",
        "goal": "接待咨询，回答产品与技术问题，收集客户需求并沉淀常见问答 SOP",
    },
    "tech_consultant": {
        "label": "售前技术顾问",
        "goal": "专业拆解技术问题、对比方案差异与部署边界，推动意向客户深入沟通",
    },
    "community_steward": {
        "label": "社群管家",
        "goal": "识别群内发言人意图，结合 @元宝/小微 深读整理干货要点并保持群内礼貌分寸",
    },
}

BORDER_OVERLAY_COLORS: Dict[str, str] = {
    "idle": "#10B981",
    "thinking": "#3B82F6",
    "human_paused": "#F59E0B",
}

_BOGUS_OCR_FRAGMENTS: Tuple[str, ...] = (
    "~/",
    ".json",
    "orkbuddy",
    "直接提问示例",
    "不用记工具名",
    "床头朝哪边",
    "语音输入",
    "做一条短视频",
    "botstudio 频道做",
    "挪了下床头",
    "睡得不太踏实",
    "整理成表格",
    "独立复核一下",
    "报错是什么原因",
    "@*、",
    "©*",
)


def _is_bogus_ocr_target(name: Any) -> bool:
    """Reject chat-bubble fragments that leaked into session lists when inspecting pop-outs."""
    raw = str(name or "").strip()
    if not raw:
        return True
    low = raw.casefold()
    if any(tok in low for tok in _BOGUS_OCR_FRAGMENTS):
        return True
    if raw.endswith(("?", "？", "。", "!", "！")) and len(raw) >= 5:
        return True
    if raw.startswith(("把 ", "用 ", "给 ", "有具体", "长按鼠标", "哟，", "©", "@*")):
        return True
    return False


def _resolve_default_binary_path(bundle_res: Path = _BUNDLE_RES) -> Path:
    """解析原生 wechat-vision-ax 二进制路径：开发仓在 bin/，安装版在 Contents/MacOS 或 Resources/。"""
    candidates = [
        bundle_res / "bin" / "wechat-vision-ax",
        bundle_res.parent / "MacOS" / "wechat-vision-ax",
        bundle_res / "wechat-vision-ax",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _copy_file_atomic(src: Path, dst: Path) -> bool:
    """安全复制单个文件到目标位置（SQLite 用只读 backup，普通文件写 tmp + os.replace）。"""
    import sqlite3
    import uuid

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        if src.suffix == ".sqlite":
            src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
            try:
                dst_conn = sqlite3.connect(str(tmp), timeout=5.0)
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
            finally:
                src_conn.close()
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = dst.with_name(dst.name + suffix)
                if sidecar.exists():
                    sidecar.unlink(missing_ok=True)
        else:
            shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _migrate_legacy_runtime_data(bundle_res: Path, target_root: Path) -> Dict[str, Any]:
    """首次从旧源码/包内数据目录平滑迁移运行时数据到 bundle 外稳定目录。"""
    if (Path(bundle_res) / "customer_build.marker").is_file():
        return {"migrated": False, "reason": "customer_build_marker"}
    try:
        if target_root.resolve() == bundle_res.resolve():
            return {"migrated": False, "reason": "same_root"}
    except Exception:
        if target_root == bundle_res:
            return {"migrated": False, "reason": "same_root"}

    sentinel = target_root / ".runtime_migrated_v1"
    if (
        sentinel.exists()
        and (target_root / "config" / "bound_contacts.json").exists()
        and (target_root / "config" / "studio_auth.json").exists()
    ):
        return {"migrated": False, "reason": "already_migrated"}

    candidates: List[Path] = []
    repo_marker = bundle_res / "repo_root.txt"
    try:
        if repo_marker.is_file():
            raw_repo = repo_marker.read_text(encoding="utf-8").strip()
            if raw_repo:
                candidates.append(Path(raw_repo))
    except Exception:
        pass
    candidates.append(bundle_res)

    config_files = (
        "studio_auth.json",
        "bound_contacts.json",
        "model_providers.json",
        "personas.json",
        "soul_memories.json",
        "sales_crm.sqlite",
        "wechat_knowledge.sqlite",
    )
    log_files = (
        "hosting_state.json",
        "monitor_state.json",
        "monitor_events.jsonl",
        "antiban_state.json",
        "human_guard_state.json",
        "soul_memory_profiles.json",
        "soul_memory_report.md",
        "contact_analytics_report.json",
        "contact_analytics_report.md",
        "wechat_management_report.json",
        "wechat_management_report.md",
        "media_link_analyses.jsonl",
    )
    log_subdirs = ("contacts", "media_analyses", "snapshots", "avatars")

    # 若目标尚未建立有效绑定或授权（如 2.4.61 首次空跑自动生成的空库），允许首迁覆盖默认空文件
    overwrite_seeded = (
        not sentinel.exists()
        and not (target_root / "config" / "bound_contacts.json").exists()
        and not (target_root / "config" / "studio_auth.json").exists()
    )
    copied: List[str] = []
    migrated_from: Optional[str] = None

    for src_root in candidates:
        try:
            if not src_root.is_dir() or src_root.resolve() == target_root.resolve():
                continue
        except Exception:
            continue

        src_has_user_cfg = (
            (src_root / "config" / "studio_auth.json").is_file()
            or (src_root / "config" / "bound_contacts.json").is_file()
        )
        allow_overwrite_cfg = overwrite_seeded and src_has_user_cfg

        for fname in config_files:
            src_file = src_root / "config" / fname
            dst_file = target_root / "config" / fname
            if src_file.is_file() and (not dst_file.exists() or allow_overwrite_cfg):
                if _copy_file_atomic(src_file, dst_file):
                    copied.append(f"config/{fname}")
                    migrated_from = migrated_from or str(src_root)

        for fname in log_files:
            src_file = src_root / "logs" / fname
            dst_file = target_root / "logs" / fname
            if src_file.is_file() and not dst_file.exists():
                if _copy_file_atomic(src_file, dst_file):
                    copied.append(f"logs/{fname}")
                    migrated_from = migrated_from or str(src_root)

        for sub in log_subdirs:
            src_sub = src_root / "logs" / sub
            dst_sub = target_root / "logs" / sub
            try:
                if src_sub.is_dir():
                    for item in src_sub.iterdir():
                        if item.is_file():
                            dst_item = dst_sub / item.name
                            if not dst_item.exists() and _copy_file_atomic(item, dst_item):
                                copied.append(f"logs/{sub}/{item.name}")
                                migrated_from = migrated_from or str(src_root)
            except Exception:
                pass

        if allow_overwrite_cfg:
            overwrite_seeded = False

    try:
        target_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            sentinel,
            {
                "schema": "openbot.wechat-runtime-migration/1",
                "migratedAt": datetime.now(timezone.utc).isoformat(),
                "sourceRoot": migrated_from,
                "copiedCount": len(copied),
                "copied": copied[:80],
            },
        )
    except Exception:
        pass
    return {"migrated": bool(copied), "copiedCount": len(copied), "sourceRoot": migrated_from}


# 安装版（.app 内）运行时数据必须落在 bundle 外：包内写入会破坏代码签名（sealed resource），
# 且 install_if_needed 的 rm -rf 会连用户历史数据一起删掉。开发版仍用仓库目录。
if str(_BUNDLE_RES).endswith(".app/Contents/Resources"):
    DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "WeChatBot"
    _migrate_legacy_runtime_data(_BUNDLE_RES, DEFAULT_ROOT)
else:
    DEFAULT_ROOT = _BUNDLE_RES
DEFAULT_BINARY_PATH = _resolve_default_binary_path(_BUNDLE_RES)
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


# HostingManager 已拆分至 hosting_manager.py（保持 import 路径兼容）
from .hosting_manager import HostingManager  # noqa: F401  (re-export)


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
        bundle_root: Optional[Path] = None,
    ) -> None:
        self.bundle_root = Path(bundle_root) if bundle_root else _BUNDLE_RES
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
        self._runtime_allowlist_targets: set[str] = set()
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

        if auth_file_path or env_auth:
            resolved_tenant_dir = resolved_auth.parent
        elif bindings_file_path or env_bindings:
            resolved_tenant_dir = resolved_bindings.parent
        elif knowledge_db_path or env_kb:
            resolved_tenant_dir = resolved_kb.parent
        else:
            resolved_tenant_dir = DEFAULT_ROOT / "config"

        self.tenant = TenantProfileStore(
            resolved_tenant_dir / "tenant_profile.json",
            bundle_root=self.bundle_root,
        )
        tenant_profile = self.tenant.get_profile()
        is_customer_mode = self.tenant.is_customer_mode()
        if is_customer_mode:
            packs_dir = self._resolve_sales_packs_dir()
            pack_id = str(tenant_profile.get("industryPack") or DEFAULT_INDUSTRY_PACK).strip() or DEFAULT_INDUSTRY_PACK
            pack_path: Optional[Path] = (packs_dir / f"{pack_id}.json") if packs_dir else None
            if pack_path is not None and (not pack_path.is_file()) and packs_dir:
                fallback_pack = packs_dir / f"{DEFAULT_INDUSTRY_PACK}.json"
                pack_path = fallback_pack if fallback_pack.is_file() else None
            self.knowledge = WeChatKnowledgeStore(
                resolved_kb,
                seed_mode="sales_pack",
                sales_pack_path=pack_path if (pack_path and pack_path.is_file()) else None,
            )
        else:
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
        # 朋友圈读取与互动：数据落在 logs/moments/，不碰聊天档案
        self.moments = WeChatMomentsHub(self)

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
            analytics_provider=lambda: (self.profile_contacts() if self.auth_gate.is_allowed("status") else {}),
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
            moments_provider=lambda name: self.moments.get_posts_for_contact(name, limit=10),
            tenant_mode="customer" if is_customer_mode else "legacy",
            owner_config=tenant_profile,
        )
        self.corpus_discovery = CorpusDiscoveryEngine(self.importer)
        self.playbook_trainer = SelfTrainingPlaybookEngine()
        self.supervisor_eval = SupervisorEvalEngine(resolved_kb.parent / "supervisor_eval.sqlite")
        for tc in tenant_profile.get("testContacts") or []:
            if str(tc or "").strip():
                try:
                    self.supervisor_eval.mark_test_contact(str(tc).strip())
                except Exception:
                    pass
        self.benchmark_suite = WeChatRPABenchmarkSuite(self)
        self.botstudio_bridge = BotStudioBridgeManager(self)
        self.media_analyzer = WeChatMediaLinkAnalyzer(self)
        self.agent_dispatcher = WeChatAgentDispatcher(self)
        self.sales_crm = WeChatSalesCRMHub(self, db_path=resolved_kb.parent / "sales_crm.sqlite")
        self.call_brief = PreCallBriefEngine(self)
        self.omni_hub = OmniChannelHub(
            self,
            config_path=resolved_auth.parent / "omni_channels.json",
            http_requester=model_http_requester,
        )
        self.app_use = AppUseStudio(
            self,
            store_path=resolved_auth.parent / "app_use_workflows.json",
        )
        self.hosting_manager = HostingManager(
            self,
            state_path=resolved_mon_state.parent / "hosting_state.json",
            interval_seconds=max(4.0, float(os.environ.get("WECHAT_PLUGIN_HOSTING_INTERVAL", "8") or 8)),
        )
        self._workos_lock = threading.RLock()
        self._guard_ctx = threading.local()
        self.workos_state_path = resolved_auth.parent / "workos_state.json"
        self._workos_state = self._load_workos_state()
        self.app_window_binder = AppWindowBinder(resolved_auth.parent / "app_window_binding.json")
        self.doc_ingestor = DocumentKnowledgeIngestor(self)
        self.multi_scheduler = MultiWindowScheduler()
        self.coevolution = DualProductCoevolutionEngine(
            state_path=resolved_reports / "coevolution_state.json",
            corpus_path=resolved_reports / "coevolution_corpus.jsonl",
            knowledge_store=self.knowledge,
            sync_path=resolved_reports / "botstudio_coevolution_sync.json",
        )
        self.border_overlay_state = self._workos_state["borderOverlay"]
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

    INTERACTIVE_NATIVE_CMDS = frozenset({
        "click",
        "right-click",
        "scroll",
        "activate",
        "focus-input",
        "paste-and-verify",
        "send-sticker",
        "paste-image",
        "press-key",
        "join-tencent-meeting",
        "voice-call",
        "app-use-activate",
        "app-use-paste",
    })

    def is_human_guard_enforced(self) -> bool:
        ctx = getattr(self, "_guard_ctx", None)
        return bool(getattr(ctx, "enforced", False)) if ctx is not None else False

    def is_human_guard_bypassed(self) -> bool:
        ctx = getattr(self, "_guard_ctx", None)
        return bool(getattr(ctx, "bypassed", False)) if ctx is not None else False

    @contextmanager
    def enforce_human_guard(self, strict: bool = True):
        if not hasattr(self, "_guard_ctx") or self._guard_ctx is None:
            self._guard_ctx = threading.local()
        prev = getattr(self._guard_ctx, "enforced", False)
        self._guard_ctx.enforced = bool(strict)
        try:
            yield
        finally:
            self._guard_ctx.enforced = prev

    @contextmanager
    def bypass_human_guard(self, bypass: bool = True):
        if not hasattr(self, "_guard_ctx") or self._guard_ctx is None:
            self._guard_ctx = threading.local()
        prev = getattr(self._guard_ctx, "bypassed", False)
        self._guard_ctx.bypassed = bool(bypass)
        try:
            yield
        finally:
            self._guard_ctx.bypassed = prev

    def _check_human_guard_for_action(
        self,
        *,
        manual_trigger: bool = False,
        ignore_human_guard: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if manual_trigger or ignore_human_guard or self.is_human_guard_bypassed() or not hasattr(self, "human_guard"):
            return None
        g = self.human_guard.check_can_operate()
        if g.get("canOperate", True):
            return None
        if (not self.is_human_guard_enforced()) and g.get("status") == "hid_unavailable":
            return None
        return g

    def capture_wechat_ocr(self, out_path: Path, *, timeout: float = 30.0,
                           window_title: str = "微信") -> Dict[str, Any]:
        """只截微信/企业微信目标窗口做 OCR（优先使用已绑定的 --window-id / --app，默认 --window-title 定位）。

        两层兜底：
        1. 窗口不存在（window_not_found）→ 退回不带 title 的调用（保留自动拉起能力）
        2. 截图成功但 OCR 为空（窗口被其他应用完全遮挡时 macOS 返回空白）→ 先校验防抢守卫再决定是否激活重截
        """
        bound = self.app_window_binder.get_binding() if hasattr(self, "app_window_binder") else {}
        bound_app = str(bound.get("appId") or "auto")
        bound_wid = bound.get("windowID")
        bound_title = str(bound.get("windowTitle") or "").strip()
        app_flags = ["--app", bound_app] if bound_app in ("wechat", "wecom") else []

        if bound_wid:
            target_flags = ["--window-id", str(int(bound_wid))]
        else:
            eff_title = bound_title if (bound_title and window_title == "微信") else window_title
            target_flags = ["--window-title", eff_title]

        capture_args = ["capture-ocr", "--no-activate", *target_flags, *app_flags, "--out", str(out_path)]
        res = self._run_native(capture_args, timeout)
        if not res.get("ok"):
            if res.get("error_code") in ("window_not_found", "no_window"):
                fallback = self._run_native(["capture-ocr", "--no-activate", *app_flags, "--out", str(out_path)], timeout)
                fallback["fallbackUsed"] = True
                fallback["fallbackReason"] = res.get("error_code")
                return fallback
            if res.get("error_code") != "window_occluded":
                return res
        # 窗口被完全遮挡（原生层返回 window_occluded / 空结果）→ 若用户正在操作电脑则绝不抢焦点激活
        if res.get("error_code") == "window_occluded" or not (res.get("elements") or []):
            blocked = self._check_human_guard_for_action()
            if blocked is not None:
                return {
                    **res,
                    "ok": False,
                    "occluded": True,
                    "pausedByHumanGuard": True,
                    "humanGuard": blocked,
                }
            act_res = self._run_native(["activate", *app_flags], 10.0)
            if isinstance(act_res, dict) and (act_res.get("blockedByHumanGuard") or act_res.get("error_code") == "human_input_active"):
                return {
                    **res,
                    "ok": False,
                    "occluded": True,
                    "pausedByHumanGuard": True,
                    "humanGuard": act_res.get("humanGuard") or act_res,
                }
            time.sleep(0.8)
            retry = self._run_native(capture_args, timeout)
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
        effective_args = list(args)
        cmd_name = effective_args[0] if effective_args else ""
        is_dry_run = "--dry-run" in effective_args
        is_voice_status = False
        if cmd_name == "voice-call" and "--action" in effective_args:
            act_idx = effective_args.index("--action") + 1
            if act_idx < len(effective_args) and str(effective_args[act_idx]).strip().lower() == "status":
                is_voice_status = True

        is_interactive = (
            cmd_name in self.INTERACTIVE_NATIVE_CMDS
            and not is_dry_run
            and not is_voice_status
            and "--review-window" not in effective_args
        )
        if is_interactive:
            if not self.is_human_guard_bypassed():
                if self.is_human_guard_enforced() and hasattr(self, "human_guard"):
                    g = self.human_guard.check_can_operate()
                    if not g.get("canOperate", True):
                        return {
                            "ok": False,
                            "error_code": "human_input_active",
                            "blockedByHumanGuard": True,
                            "retryable": True,
                            "humanGuard": g,
                            "error": "Human active: native interactive action blocked.",
                        }
                if (
                    "--guard-idle" not in effective_args
                    and "--ignore-human-guard" not in effective_args
                    and "--skip-human-check" not in effective_args
                ):
                    effective_args.extend(["--guard-idle", "1.5"])
            else:
                if (
                    "--guard-idle" not in effective_args
                    and "--ignore-human-guard" not in effective_args
                    and "--skip-human-check" not in effective_args
                ):
                    effective_args.append("--ignore-human-guard")

        mutating_input = cmd_name in (
            "click",
            "right-click",
            "scroll",
            "focus-input",
            "paste-and-verify",
            "send-sticker",
            "paste-image",
            "join-tencent-meeting",
            "voice-call",
        ) and not is_dry_run and not is_voice_status
        rpa_x: Optional[float] = None
        rpa_y: Optional[float] = None
        if mutating_input:
            try:
                if "--x" in effective_args:
                    rpa_x = float(effective_args[effective_args.index("--x") + 1])
                if "--y" in effective_args:
                    rpa_y = float(effective_args[effective_args.index("--y") + 1])
            except Exception:
                rpa_x = None
                rpa_y = None

        cmd = [str(self.binary_path)] + effective_args
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
                "error": f"Native command timed out after {timeout}s: {' '.join(effective_args)}",
            }

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
                if data.get("error_code") in ("human_input_active", "human_keyboard_active", "interrupted_before_return") and hasattr(self, "human_guard"):
                    cp = data.get("cursorPosition") if isinstance(data.get("cursorPosition"), dict) else None
                    self.human_guard.trigger_human_cooldown(
                        reason=str(data.get("reason") or data.get("error_code") or "native_human_interrupt"),
                        cursor_pos=cp,
                    )
                elif mutating_input and data.get("ok") and hasattr(self, "human_guard"):
                    final_pt = data.get("finalCursorPosition") or data.get("clickPoint") or data.get("slotPoint")
                    if isinstance(final_pt, dict) and final_pt.get("x") is not None and final_pt.get("y") is not None:
                        try:
                            rpa_x = float(final_pt["x"])
                            rpa_y = float(final_pt["y"])
                        except Exception:
                            pass
                    self.human_guard.record_rpa_action(action=cmd_name, cursor_x=rpa_x, cursor_y=rpa_y)
                return self._enhance_lowres_ocr(effective_args, data, timeout=timeout)
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
        bound = self.get_bound_app_window() if hasattr(self, "app_window_binder") else {}
        bound_app = str(bound.get("appId") or "auto")
        args = ["status"] + (["--app", bound_app] if bound_app in ("wechat", "wecom") else [])
        res = self._run_native(args)
        self.audit.log("status", "ok" if res.get("ok") else "error", {"wechatRunning": res.get("wechatRunning")})
        return res

    # 权限项 → (tccutil 服务名, request-permissions --only 值)。post_event 与 accessibility 同属「辅助功能」一项。
    PERMISSION_ITEMS: Dict[str, Tuple[str, str]] = {
        "accessibility": ("Accessibility", "accessibility"),
        "post_event": ("Accessibility", "post-event"),
        "screen_capture": ("ScreenCapture", "screen-capture"),
    }
    # 辅助功能与屏幕录制的系统弹窗不能同一瞬间发出（后一个可能被系统丢弃），两步之间留出的间隔
    _permission_prompt_gap_seconds = 2.5

    def request_permissions(self, *, open_settings: bool = True, only: Optional[str] = None) -> Dict[str, Any]:
        """向 macOS 申请权限登记：系统弹出授权提示，并把本 App 加进对应面板的列表。

        不申请的话列表里没有本 App，用户只能手动「+」添加。`only` 只申请当前缺失的那一项。
        """
        args = ["request-permissions"]
        if only:
            if only not in self.PERMISSION_ITEMS:
                raise ValueError(f"Unsupported permission item: {only}")
            args += ["--only", self.PERMISSION_ITEMS[only][1]]
        if not open_settings:
            args.append("--no-settings")
        res = self._run_native(args)
        self.audit.log(
            "request_permissions",
            "ok" if res.get("ok") else "error",
            {
                "only": only or "all",
                "screenCapturePrompted": res.get("screenCapturePrompted"),
                "accessibilityTrusted": res.get("accessibilityTrusted"),
                "postEventTrusted": res.get("postEventTrusted"),
                "screenCaptureTrusted": res.get("screenCaptureTrusted"),
                "openedSystemSettings": res.get("openedSystemSettings"),
            },
        )
        return res

    def _normalize_permission_items(self, services: Optional[Iterable[str]]) -> Dict[str, List[str]]:
        items = (
            [str(s).strip() for s in services if str(s).strip()]
            if services
            else ["accessibility", "post_event", "screen_capture"]
        )
        invalid = [item for item in items if item not in self.PERMISSION_ITEMS]
        if invalid:
            raise ValueError(f"Unsupported permission items: {invalid}")
        ordered: List[str] = []
        tcc_services: List[str] = []
        for item in items:
            if item not in ordered:
                ordered.append(item)
            tcc_service = self.PERMISSION_ITEMS[item][0]
            if tcc_service not in tcc_services:
                tcc_services.append(tcc_service)
        return {"items": ordered, "tccServices": tcc_services}

    # 本 App 的 bundle id：授权自愈时 tccutil reset 只作用于它，不触及其他应用
    DEFAULT_TCC_BUNDLE_ID = "com.openbot.wechat-bot"
    _tccutil_bin = "/usr/bin/tccutil"

    def tcc_bundle_id(self) -> str:
        """解析本 App 的 bundle id：环境变量 > 所在 .app 的 Info.plist > 默认值。"""
        env_bid = str(os.environ.get("WECHAT_BUNDLE_ID") or "").strip()
        if env_bid:
            return env_bid
        try:
            res_dir = Path(__file__).resolve().parent.parent
            if str(res_dir).endswith(".app/Contents/Resources"):
                import plistlib

                bid = plistlib.loads((res_dir.parent / "Info.plist").read_bytes()).get("CFBundleIdentifier")
                if bid:
                    return str(bid)
        except Exception:
            pass
        return self.DEFAULT_TCC_BUNDLE_ID

    def repair_permissions(
        self,
        *,
        reset: bool = True,
        prompt: bool = True,
        services: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """授权自愈：清除绑在旧构建上的失效授权记录，并让 macOS 重新登记当前版本。

        系统设置里的开关可能显示已开，但那条记录绑定的是某个旧构建的代码哈希，macOS 据此把
        当前版本当成另一个应用——开关怎么点都无效，只会被反复要求重新授权。
        tccutil reset 只清除本应用自己的记录（可逆：重新打开开关即可）。

        `services` 只处理指定的权限项（accessibility / post_event / screen_capture）；缺省仍按旧行为
        处理辅助功能与屏幕录制两项。重新登记时辅助功能先申请、隔开间隔再申请屏幕录制。
        """
        bundle_id = self.tcc_bundle_id()
        selected = self._normalize_permission_items(services)
        reset_results: List[Dict[str, Any]] = []
        if reset:
            for service in selected["tccServices"]:
                try:
                    proc = subprocess.run(
                        [self._tccutil_bin, "reset", service, bundle_id],
                        capture_output=True,
                        text=True,
                        timeout=10.0,
                    )
                    reset_results.append({
                        "service": service,
                        "returncode": proc.returncode,
                        "output": ((proc.stdout or "") + (proc.stderr or "")).strip()[:200],
                    })
                except Exception as exc:
                    reset_results.append({"service": service, "returncode": -1, "output": str(exc)[:200]})
        items = selected["items"]
        request: Optional[Dict[str, Any]] = None
        if prompt:
            steps: List[Dict[str, Any]] = []
            if "post_event" in items or "accessibility" in items:
                # 「辅助功能」一项同时覆盖系统事件控制；只有单独指定 post_event 时才只申请它
                ax_item = "post_event" if items == ["post_event"] else "accessibility"
                ax_step = self.request_permissions(open_settings=False, only=ax_item)
                steps.append(ax_step)
                if "screen_capture" in items and not ax_step.get("accessibilityTrusted"):
                    time.sleep(self._permission_prompt_gap_seconds)
            if "screen_capture" in items:
                steps.append(self.request_permissions(open_settings=False, only="screen_capture"))
            request = dict(steps[-1]) if steps else {}
            request["steps"] = steps
        ok = (not reset) or all(r.get("returncode") == 0 for r in reset_results)
        self.audit.log(
            "repair_permissions",
            "ok" if ok else "error",
            {"bundleId": bundle_id, "items": items, "reset": reset_results},
        )
        return {"ok": ok, "bundleId": bundle_id, "items": items, "reset": reset_results, "request": request}

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
        bound = self.get_bound_app_window() if hasattr(self, "app_window_binder") else {}
        bound_app = str(bound.get("appId") or "auto")
        bound_wid = bound.get("windowID")
        args = ["capture-ocr"]
        if bound_wid:
            args.extend(["--window-id", str(int(bound_wid))])
        if bound_app in ("wechat", "wecom"):
            args.extend(["--app", bound_app])
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
        target_window_id: Optional[int] = None,
        manual_trigger: bool = False,
        ignore_human_guard: bool = False,
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

        is_test_contact = bool(
            hasattr(self, "supervisor_eval")
            and self.supervisor_eval.is_test_contact(clean_target)
        )
        if (not is_test_contact) and is_blocked_outbound_directive(text):
            res = {
                "ok": False,
                "status": "blocked_internal_hashtag_directive",
                "error_code": "blocked_internal_hashtag_directive",
                "target": clean_target,
                "error": "Internal `#` supervisor directives are blocked from sending to normal contacts.",
            }
            self.audit.log("send_text", "blocked_internal_hashtag_directive", res)
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
                self.dedup.rollback(fp)
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

        if (not dry_run) and (expected_window_id is None):
            blocked = self._check_human_guard_for_action(
                manual_trigger=manual_trigger,
                ignore_human_guard=ignore_human_guard,
            )
            if blocked is not None:
                self.dedup.rollback(fp)
                res = {
                    "ok": False,
                    "status": "paused_human_active",
                    "blockedByHumanGuard": True,
                    "retryable": True,
                    "target": clean_target,
                    "humanGuard": blocked,
                    "error": f"检测到人工正在操作键鼠，已暂停向 {clean_target!r} 发送消息让路。",
                }
                self.audit.log("send_text", "paused_human_active", res)
                return res

        bypass_ctx = (
            self.bypass_human_guard(True)
            if ((not dry_run) and (manual_trigger or ignore_human_guard))
            else nullcontext()
        )
        with bypass_ctx:
            matched_title = clean_target
            if not skip_navigation:
                nav = self.inspector.select_session(clean_target)
                if not nav.get("ok"):
                    self.dedup.rollback(fp)
                    res = {
                        "ok": False,
                        "status": "target_navigation_failed",
                        "retryable": True,
                        "target": clean_target,
                        "navigation": nav,
                        "error": nav.get("error", f"Failed to navigate to {clean_target!r}."),
                    }
                    self.audit.log("send_text", "target_navigation_failed", res)
                    return res
                matched_title = str(nav.get("matchedTitle") or clean_target)

            # Live or silent-UI verification via native binary
            native_args = ["paste-and-verify", "--text", text]
            effective_wid: Optional[int] = None
            if expected_window_id is not None:
                native_args += ["--review-window", str(expected_window_id), "--review-title", clean_target]
                effective_wid = int(expected_window_id)
            else:
                popout_win = None
                if target_window_id is not None:
                    effective_wid = int(target_window_id)
                elif skip_navigation and hasattr(self, "inspector"):
                    try:
                        popout_win = self.inspector.find_popout_window(clean_target, app="all")
                        if popout_win and popout_win.get("windowID"):
                            effective_wid = int(popout_win["windowID"])
                    except Exception:
                        popout_win = None
                if effective_wid is not None:
                    native_args += ["--window-id", str(effective_wid)]
                    pw_title = str((popout_win or {}).get("title") or "").strip()
                    if pw_title:
                        native_args += ["--window-title", pw_title]
            if will_send:
                native_args.append("--send")
            else:
                native_args.append("--silent")

            native_res = self._run_native(native_args, timeout=25.0)
        status_label = "sent" if (native_res.get("ok") and native_res.get("sent")) else (
            "silent_verified" if native_res.get("ok") else native_res.get("error_code", "native_error")
        )
        send_succeeded = bool(native_res.get("ok")) and ((not will_send) or bool(native_res.get("sent")))
        if not send_succeeded:
            # 打断、未发成功或校验失败时释放 120s 防重锁，确保下轮巡检可立刻恢复重发
            self.dedup.rollback(fp)

        post_send_snapshot: Optional[str] = None
        if expected_window_id is None and will_send and native_res.get("ok") and native_res.get("sent"):
            time.sleep(0.40)
            slug = _slugify_target(clean_target)
            snap_file = self.inspector.snapshots_dir / f"sent_{slug}_{int(time.time() * 1000)}.png"
            self.inspector.snapshots_dir.mkdir(parents=True, exist_ok=True)
            cap_args = ["capture-ocr", "--no-activate", "--out", str(snap_file)]
            if effective_wid is not None:
                cap_args += ["--window-id", str(effective_wid)]
            cap = self._run_native(cap_args, timeout=15.0)
            if cap.get("ok"):
                post_send_snapshot = str(snap_file)

        blocked_by_guard = bool(
            native_res.get("blockedByHumanGuard")
            or native_res.get("error_code") in ("human_input_active", "human_keyboard_active")
        )
        result: Dict[str, Any] = {
            "ok": send_succeeded,
            "status": status_label if send_succeeded or status_label != "sent" else "return_not_dispatched",
            "mode": "live_send" if will_send else "silent_verify",
            "retryable": bool(native_res.get("retryable", not send_succeeded)),
            "target": clean_target,
            "matchedChatTitle": matched_title,
            "fingerprint": fp,
            "native": native_res,
        }
        if blocked_by_guard:
            result["blockedByHumanGuard"] = True
            if isinstance(native_res.get("humanGuard"), dict):
                result["humanGuard"] = native_res["humanGuard"]
            elif hasattr(self, "human_guard"):
                result["humanGuard"] = self.human_guard.check_can_operate()
        if post_send_snapshot:
            result["postSendSnapshot"] = post_send_snapshot
        audit_payload = result if expected_window_id is None else {"fingerprint": fp, "stage": "workbench"}
        self.audit.log("send_text", status_label, audit_payload)
        return result

    def send_wechat_sticker(
        self,
        target: str,
        *,
        tab: str = "favorites",
        slot: int = 0,
        emoji_code: str = "",
        dry_run: bool = False,
        confirm_send: bool = True,
        skip_navigation: bool = False,
        target_window_id: Optional[int] = None,
        manual_trigger: bool = False,
        ignore_human_guard: bool = False,
    ) -> Dict[str, Any]:
        """Send an official WeChat emoji shortcode (`[旺柴]`/`[捂脸]`) or click a favorite/emoji panel sticker."""
        clean_target = str(target or "").strip()
        if not clean_target:
            return {"ok": False, "error": "Target contact is required."}

        clean_emoji = str(emoji_code or "").strip()
        if clean_emoji:
            from .humanizer_affect import normalize_wechat_emojis

            if not (clean_emoji.startswith("[") and clean_emoji.endswith("]")):
                clean_emoji = f"[{clean_emoji}]"
            normalized_emoji = normalize_wechat_emojis(clean_emoji, fallback_emote="[旺柴]")
            return self.send_text(
                clean_target,
                normalized_emoji,
                dry_run=dry_run,
                silent_mode=bool(dry_run or not confirm_send),
                confirm_send=bool(confirm_send and not dry_run),
                skip_navigation=skip_navigation,
                target_window_id=target_window_id,
                manual_trigger=manual_trigger,
                ignore_human_guard=ignore_human_guard,
            )

        will_send = (not dry_run) and bool(confirm_send)
        self._require("send_text_live" if will_send else "send_text_dry_run")
        if self.allowlist.enabled and not self.allowlist.is_allowed(clean_target):
            return {
                "ok": False,
                "status": "blocked_allowlist",
                "target": clean_target,
                "error": f"Target {clean_target!r} is not in allowed groups/contacts.",
            }

        if will_send:
            blocked = self._check_human_guard_for_action(
                manual_trigger=manual_trigger,
                ignore_human_guard=ignore_human_guard,
            )
            if blocked is not None:
                res = {
                    "ok": False,
                    "status": "paused_human_active",
                    "blockedByHumanGuard": True,
                    "retryable": True,
                    "target": clean_target,
                    "humanGuard": blocked,
                    "error": f"检测到人工正在操作键鼠，已暂停发送表情给 {clean_target!r}。",
                }
                self.audit.log("send_sticker", "paused_human_active", res)
                return res

        clean_tab = "emoji" if str(tab or "").strip().lower() == "emoji" else "favorites"
        clean_slot = max(0, min(24, int(slot or 0)))

        bypass_ctx = (
            self.bypass_human_guard(True)
            if (will_send and (manual_trigger or ignore_human_guard))
            else nullcontext()
        )
        with bypass_ctx:
            popout_win = None
            effective_wid: Optional[int] = int(target_window_id) if target_window_id is not None else None
            if effective_wid is None and hasattr(self, "inspector"):
                try:
                    popout_win = self.inspector.find_popout_window(clean_target, app="all")
                    if popout_win and popout_win.get("windowID"):
                        effective_wid = int(popout_win["windowID"])
                except Exception:
                    popout_win = None

            if effective_wid is None and (not skip_navigation) and (not dry_run):
                nav = self.inspector.select_session(clean_target)
                if not nav.get("ok"):
                    return {
                        "ok": False,
                        "status": "target_navigation_failed",
                        "target": clean_target,
                        "error": nav.get("error", f"Failed to select {clean_target!r}"),
                    }

            args = ["send-sticker", "--tab", clean_tab, "--slot", str(clean_slot)]
            if effective_wid is not None:
                args += ["--window-id", str(effective_wid)]
                pw_title = str((popout_win or {}).get("title") or "").strip()
                if pw_title:
                    args += ["--window-title", pw_title]
            if not will_send:
                args.append("--dry-run")

            native_res = self._run_native(args, timeout=15.0)
        res = {
            "ok": bool(native_res.get("ok")),
            "status": "sent" if (will_send and native_res.get("sent")) else ("dry_run_ok" if native_res.get("ok") else native_res.get("error_code", "native_error")),
            "target": clean_target,
            "tab": clean_tab,
            "slot": clean_slot,
            "windowID": effective_wid,
            "native": native_res,
        }
        if native_res.get("blockedByHumanGuard") or native_res.get("error_code") in ("human_input_active", "human_keyboard_active"):
            res["blockedByHumanGuard"] = True
        self.audit.log("send_sticker", res["status"], res)
        return res

    def send_image(
        self,
        target: str,
        image_path: str,
        *,
        caption: str = "",
        dry_run: bool = False,
        confirm_send: bool = True,
        skip_navigation: bool = False,
        target_window_id: Optional[int] = None,
        manual_trigger: bool = False,
        ignore_human_guard: bool = False,
    ) -> Dict[str, Any]:
        """Paste and send an image file directly into WeChat (optionally with a follow-up text caption)."""
        clean_target = str(target or "").strip()
        if not clean_target:
            return {"ok": False, "error": "Target contact is required."}
        img_file = Path(str(image_path or "").strip())
        if not img_file.is_file():
            return {"ok": False, "error_code": "file_not_found", "error": f"Image not found: {img_file}"}

        will_send = (not dry_run) and bool(confirm_send)
        self._require("send_text_live" if will_send else "send_text_dry_run")
        if self.allowlist.enabled and not self.allowlist.is_allowed(clean_target):
            return {
                "ok": False,
                "status": "blocked_allowlist",
                "target": clean_target,
                "error": f"Target {clean_target!r} is not in allowed contacts.",
            }

        if will_send:
            blocked = self._check_human_guard_for_action(
                manual_trigger=manual_trigger,
                ignore_human_guard=ignore_human_guard,
            )
            if blocked is not None:
                res = {
                    "ok": False,
                    "status": "paused_human_active",
                    "blockedByHumanGuard": True,
                    "retryable": True,
                    "target": clean_target,
                    "imagePath": str(img_file),
                    "humanGuard": blocked,
                    "error": f"检测到人工正在操作键鼠，已暂停发送图片给 {clean_target!r}。",
                }
                self.audit.log("send_image", "paused_human_active", res)
                return res

        bypass_ctx = (
            self.bypass_human_guard(True)
            if (will_send and (manual_trigger or ignore_human_guard))
            else nullcontext()
        )
        with bypass_ctx:
            popout_win = None
            effective_wid: Optional[int] = int(target_window_id) if target_window_id is not None else None
            if effective_wid is None and hasattr(self, "inspector"):
                try:
                    popout_win = self.inspector.find_popout_window(clean_target, app="all")
                    if popout_win and popout_win.get("windowID"):
                        effective_wid = int(popout_win["windowID"])
                except Exception:
                    popout_win = None

            if effective_wid is None and (not skip_navigation) and (not dry_run):
                nav = self.inspector.select_session(clean_target)
                if not nav.get("ok"):
                    return {
                        "ok": False,
                        "status": "target_navigation_failed",
                        "target": clean_target,
                        "error": nav.get("error", f"Failed to navigate to {clean_target!r}."),
                    }

            args = ["paste-image", "--image", str(img_file)]
            if effective_wid is not None:
                args += ["--window-id", str(effective_wid)]
                pw_title = str((popout_win or {}).get("title") or "").strip()
                if pw_title:
                    args += ["--window-title", pw_title]
            args.append("--send" if will_send else "--dry-run")

            native_res = self._run_native(args, timeout=20.0)
            img_sent_ok = bool(native_res.get("ok")) and ((not will_send) or bool(native_res.get("sent")))
            caption_res = None
            if img_sent_ok and will_send and str(caption or "").strip():
                caption_res = self.send_text(
                    clean_target,
                    str(caption).strip(),
                    dry_run=False,
                    silent_mode=False,
                    confirm_send=True,
                    skip_navigation=True,
                    target_window_id=effective_wid,
                    manual_trigger=manual_trigger,
                    ignore_human_guard=ignore_human_guard,
                )

        status = "sent" if (will_send and img_sent_ok) else ("dry_run_ok" if native_res.get("ok") else native_res.get("error_code", "native_error"))
        res = {
            "ok": img_sent_ok,
            "status": status,
            "target": clean_target,
            "imagePath": str(img_file),
            "windowID": effective_wid,
            "native": native_res,
            **({"captionSend": caption_res} if caption_res is not None else {}),
        }
        if native_res.get("blockedByHumanGuard") or native_res.get("error_code") in ("human_input_active", "human_keyboard_active"):
            res["blockedByHumanGuard"] = True
        self.audit.log("send_image", status, res)
        return res

    def search_and_send_web_image(
        self,
        target: str,
        query: str,
        *,
        caption: str = "",
        dry_run: bool = False,
        confirm_send: bool = True,
        target_window_id: Optional[int] = None,
        manual_trigger: bool = False,
    ) -> Dict[str, Any]:
        """Search an image on the web for `query` and send (or dry-run) it to `target`."""
        self._require("send_text_live" if (not dry_run and confirm_send) else "send_text_dry_run")
        search_res = self.media_analyzer.search_web_image(query)
        if not search_res.get("ok") or not search_res.get("imagePath"):
            return {"ok": False, "status": "image_search_failed", **search_res}
        send_res = self.send_image(
            target,
            search_res["imagePath"],
            caption=caption or (f"{query} 参考图 [旺柴]" if not dry_run else ""),
            dry_run=dry_run,
            confirm_send=confirm_send,
            target_window_id=target_window_id,
            manual_trigger=manual_trigger,
        )
        return {**send_res, "search": search_res}

    def annotate_and_send_peer_image(
        self,
        target: str,
        *,
        image_path: str = "",
        keywords: Optional[List[str]] = None,
        note: str = "",
        boxes: Optional[List[Dict[str, int]]] = None,
        dry_run: bool = False,
        confirm_send: bool = True,
        target_window_id: Optional[int] = None,
        manual_trigger: bool = False,
    ) -> Dict[str, Any]:
        """Highlight key areas on a peer-sent image using Vision OCR red boxes/callouts and send it back."""
        self._require("send_text_live" if (not dry_run and confirm_send) else "send_text_dry_run")
        ann_res = self.media_analyzer.annotate_image_with_highlights(
            image_path=Path(image_path) if image_path else None,
            target=target,
            keywords=keywords,
            note=note,
            boxes=boxes,
        )
        if not ann_res.get("ok") or not ann_res.get("imagePath"):
            return {"ok": False, "status": "image_annotate_failed", **ann_res}
        send_res = self.send_image(
            target,
            ann_res["imagePath"],
            caption=(f"我帮你在图上框出重点了：{note} [机智]" if note else ""),
            dry_run=dry_run,
            confirm_send=confirm_send,
            target_window_id=target_window_id,
            manual_trigger=manual_trigger,
        )
        return {**send_res, "annotation": ann_res}

    def _start_botstudio_meeting_daemon(
        self,
        *,
        meeting_code: str,
        contact: str = "",
        agenda: str = "",
    ) -> Dict[str, Any]:
        """Ensure Bot Studio live spoken meeting daemon (`bin/botstudio-live-meeting.cjs`) is running."""
        import os
        import subprocess

        bot_studio_bin = Path("/Users/mac/Applications/Bot Studio.app/Contents/MacOS/Bot Studio")
        if not bot_studio_bin.is_file():
            return {"ok": False, "status": "botstudio_not_installed"}

        script_candidates = [
            self.bundle_root / "bin" / "botstudio-live-meeting.cjs",
            self.plugin_root / "bin" / "botstudio-live-meeting.cjs",
            Path(__file__).resolve().parent.parent / "bin" / "botstudio-live-meeting.cjs",
        ]
        script_path = next((p for p in script_candidates if p.is_file()), None)
        if script_path is None:
            return {"ok": False, "status": "meeting_script_missing"}

        logs_dir = self.plugin_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        pid_file = logs_dir / "botstudio_live_meeting.pid"
        if pid_file.is_file():
            try:
                old_pid = int(pid_file.read_text(encoding="utf-8").strip())
                os.kill(old_pid, 0)
                return {"ok": True, "status": "already_running", "pid": old_pid, "meetingCode": meeting_code}
            except Exception:
                pass

        log_fp = open(logs_dir / "botstudio_live_meeting.log", "ab")
        env = dict(os.environ)
        env["HOME"] = str(Path.home())
        env["WECHAT_BOT_DATA_DIR"] = str(self.plugin_root)
        env["ELECTRON_RUN_AS_NODE"] = "1"
        cmd = [
            str(bot_studio_bin),
            str(script_path),
            "--meeting-code",
            str(meeting_code or "7794329581"),
            "--contact",
            str(contact or ""),
            "--agenda",
            str(agenda or ""),
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=log_fp,
            stderr=log_fp,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        return {"ok": True, "status": "started", "pid": proc.pid, "meetingCode": meeting_code}

    def join_tencent_meeting_and_start_botstudio(
        self,
        target: str,
        *,
        meeting_code: str = "",
        password: str = "",
        agenda: str = "",
        click_card: bool = True,
        dry_run: bool = False,
        confirm_send: bool = True,
        target_window_id: Optional[int] = None,
        manual_trigger: bool = False,
        ignore_human_guard: bool = False,
    ) -> Dict[str, Any]:
        """Click WeChat Tencent Meeting card / open wemeet:// and start Bot Studio voice participant."""
        will_live = (not dry_run) and bool(confirm_send)
        self._require("send_text_live" if will_live else "send_text_dry_run")
        clean_target = str(target or "").strip()
        if clean_target and self.allowlist.enabled and not self.allowlist.is_allowed(clean_target):
            return {
                "ok": False,
                "status": "blocked_allowlist",
                "target": clean_target,
                "error": f"Target {clean_target!r} is not in allowed contacts.",
            }

        if will_live:
            blocked = self._check_human_guard_for_action(
                manual_trigger=manual_trigger,
                ignore_human_guard=ignore_human_guard,
            )
            if blocked is not None:
                res = {
                    "ok": False,
                    "status": "paused_human_active",
                    "blockedByHumanGuard": True,
                    "retryable": True,
                    "target": clean_target,
                    "humanGuard": blocked,
                    "error": "检测到人工正在操作键鼠，已暂停加入腾讯会议让路。",
                }
                self.audit.log("join_tencent_meeting_botstudio", "paused_human_active", res)
                return res

        bypass_ctx = (
            self.bypass_human_guard(True)
            if (will_live and (manual_trigger or ignore_human_guard))
            else nullcontext()
        )
        with bypass_ctx:
            popout_win = None
            effective_wid: Optional[int] = int(target_window_id) if target_window_id is not None else None
            if effective_wid is None and clean_target and hasattr(self, "inspector"):
                try:
                    popout_win = self.inspector.find_popout_window(clean_target, app="all")
                    if popout_win and popout_win.get("windowID"):
                        effective_wid = int(popout_win["windowID"])
                except Exception:
                    popout_win = None

            args = ["join-tencent-meeting"]
            if click_card:
                args.append("--click-card")
            if effective_wid is not None:
                args += ["--window-id", str(effective_wid)]
                pw_title = str((popout_win or {}).get("title") or "").strip()
                if pw_title:
                    args += ["--window-title", pw_title]
            clean_code = re.sub(r"\D+", "", str(meeting_code or ""))
            if clean_code:
                args += ["--meeting-code", clean_code]
            if str(password or "").strip():
                args += ["--password", str(password).strip()]
            if not will_live:
                args.append("--dry-run")

            native_res = self._run_native(args, timeout=25.0)
        resolved_code = str(native_res.get("meetingCode") or clean_code)
        botstudio_res: Dict[str, Any] = {"ok": False, "status": "dry_run_skipped"}
        if will_live and native_res.get("ok"):
            botstudio_res = self._start_botstudio_meeting_daemon(
                meeting_code=resolved_code or "7794329581",
                contact=clean_target,
                agenda=agenda,
            )

        blocked_by_guard = bool(
            native_res.get("blockedByHumanGuard")
            or native_res.get("error_code") in ("human_input_active", "human_keyboard_active")
        )
        res = {
            "ok": bool(native_res.get("ok")),
            "status": (
                "in_meeting"
                if native_res.get("joined")
                else (
                    "paused_human_active"
                    if blocked_by_guard
                    else ("needs_password" if native_res.get("needsPassword") else ("dry_run_ok" if not will_live else "initiated"))
                )
            ),
            "target": clean_target,
            "meetingCode": resolved_code,
            "joined": bool(native_res.get("joined")),
            "needsPassword": bool(native_res.get("needsPassword")),
            "windowID": effective_wid,
            "native": native_res,
            "botStudio": botstudio_res,
        }
        if blocked_by_guard:
            res["blockedByHumanGuard"] = True
        self.audit.log("join_tencent_meeting_botstudio", res["status"], res)
        return res

    def _start_voip_voice_daemon(
        self,
        *,
        app: str = "wechat",
        target: str = "",
        greeting: str = "",
        instructions: str = "",
        idle_input_uid: str = "",
        assume_connected: bool = False,
        restart_if_running: bool = False,
    ) -> Dict[str, Any]:
        """Start the live WeChat/WeCom VoIP voice companion daemon (`bin/wechat-voip-call.cjs`)."""
        import os
        import signal
        import subprocess

        bot_studio_bin = Path("/Users/mac/Applications/Bot Studio.app/Contents/MacOS/Bot Studio")
        if not bot_studio_bin.is_file():
            return {"ok": False, "status": "botstudio_not_installed"}

        script_candidates = [
            self.bundle_root / "bin" / "wechat-voip-call.cjs",
            self.plugin_root / "bin" / "wechat-voip-call.cjs",
            Path(__file__).resolve().parent.parent / "bin" / "wechat-voip-call.cjs",
        ]
        script_path = next((p for p in script_candidates if p.is_file()), None)
        if script_path is None:
            return {"ok": False, "status": "voip_script_missing"}

        logs_dir = self.plugin_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        pid_file = logs_dir / "wechat_voip_call.pid"
        if pid_file.is_file():
            try:
                old_pid = int(pid_file.read_text(encoding="utf-8").strip())
                os.kill(old_pid, 0)
                if not restart_if_running:
                    return {"ok": True, "status": "already_running", "pid": old_pid, "app": app, "target": target}
                os.kill(old_pid, signal.SIGTERM)
                import time as _time
                _time.sleep(0.35)
            except Exception:
                pass

        log_fp = open(logs_dir / "wechat_voip_call.log", "ab")
        env = dict(os.environ)
        env["HOME"] = str(Path.home())
        env["WECHAT_BOT_DATA_DIR"] = str(self.plugin_root)
        env["WECHAT_VISION_AX_BIN"] = str(self.binary_path)
        env["ELECTRON_RUN_AS_NODE"] = "1"
        cmd = [
            str(bot_studio_bin),
            str(script_path),
            "--app",
            str(app or "wechat"),
        ]
        if str(target or "").strip():
            cmd += ["--target", str(target).strip()]
        if str(greeting or "").strip():
            cmd += ["--greeting", str(greeting).strip()]
        if str(instructions or "").strip():
            cmd += ["--instructions", str(instructions).strip()]
        if str(idle_input_uid or "").strip():
            cmd += ["--idle-input-uid", str(idle_input_uid).strip()]
        if assume_connected:
            cmd.append("--assume-connected")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fp,
            stderr=log_fp,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        return {"ok": True, "status": "started", "pid": proc.pid, "app": app, "target": target}

    def get_voice_call_status(self) -> Dict[str, Any]:
        """Inspect live WeChat/WeCom VoIP daemon state, CoreAudio input device, and recent call summaries."""
        state_path = self.plugin_root / "logs" / "voip_call_state.json"
        summaries_path = self.plugin_root / "logs" / "voip_call_summaries.json"
        daemon_state: Dict[str, Any] = {}
        if state_path.is_file():
            try:
                daemon_state = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                daemon_state = {}
        summaries: List[Dict[str, Any]] = []
        if summaries_path.is_file():
            try:
                raw_sum = json.loads(summaries_path.read_text(encoding="utf-8"))
                if isinstance(raw_sum, list):
                    summaries = raw_sum[-5:]
            except Exception:
                summaries = []
        native_scan = self._run_native(["voice-call", "--action", "status", "--app-id", "all"], timeout=8.0)
        audio_info = self._run_native(["audio-devices"], timeout=5.0)
        return {
            "ok": True,
            "daemon": daemon_state,
            "calls": native_scan.get("calls") or [],
            "callStatus": native_scan.get("callStatus") or daemon_state.get("callStatus") or "idle",
            "defaultInput": audio_info.get("defaultInput"),
            "inputDevices": audio_info.get("inputDevices") or [],
            "recentSummaries": summaries,
        }

    def voice_call(
        self,
        target: str = "",
        *,
        action: str = "dial",
        app: str = "wechat",
        call_type: str = "audio",
        greeting: str = "",
        instructions: str = "",
        auto_voice_agent: bool = True,
        idle_input_uid: str = "",
        dry_run: bool = False,
        confirm_send: bool = True,
        skip_navigation: bool = False,
        target_window_id: Optional[int] = None,
        manual_trigger: bool = False,
        ignore_human_guard: bool = False,
    ) -> Dict[str, Any]:
        """Place, answer, inspect, or hang up a native WeChat / WeCom VoIP voice/video call with live AI voice agent."""
        import os
        import signal
        import urllib.request

        clean_action = str(action or "dial").strip().lower()
        if clean_action not in ("dial", "join", "answer", "hangup", "status"):
            return {"ok": False, "error_code": "unsupported_action", "error": f"Unsupported action: {clean_action}"}
        clean_app = str(app or "wechat").strip().lower()
        if clean_app == "lark":
            clean_app = "feishu"
        elif clean_app == "ding":
            clean_app = "dingtalk"
        if clean_app not in ("wechat", "wecom", "feishu", "dingtalk", "all", "omni"):
            clean_app = "wechat"
        clean_call_type = "video" if str(call_type or "audio").strip().lower() == "video" else "audio"
        clean_target = str(target or "").strip()

        if clean_action == "status":
            return self.get_voice_call_status()

        will_live = (not dry_run) and bool(confirm_send)
        self._require("send_text_live" if will_live else "send_text_dry_run")

        if clean_action == "dial" and clean_target and self.allowlist.enabled and not self.allowlist.is_allowed(clean_target):
            return {
                "ok": False,
                "status": "blocked_allowlist",
                "target": clean_target,
                "error": f"Target {clean_target!r} is not in allowed contacts.",
            }

        if will_live:
            blocked = self._check_human_guard_for_action(
                manual_trigger=manual_trigger,
                ignore_human_guard=ignore_human_guard,
            )
            if blocked is not None:
                res = {
                    "ok": False,
                    "action": clean_action,
                    "status": "paused_human_active",
                    "blockedByHumanGuard": True,
                    "retryable": True,
                    "target": clean_target,
                    "humanGuard": blocked,
                    "error": f"检测到人工正在操作键鼠，已暂停语音通话操作 ({clean_action})。",
                }
                self.audit.log(f"voice_call_{clean_action}", "paused_human_active", res)
                return res

        with (
            self.bypass_human_guard(True)
            if (will_live and (manual_trigger or ignore_human_guard))
            else nullcontext()
        ):
            return self._voice_call_exec(
                clean_target=clean_target,
                clean_action=clean_action,
                clean_app=clean_app,
                clean_call_type=clean_call_type,
                greeting=greeting,
                instructions=instructions,
                auto_voice_agent=auto_voice_agent,
                idle_input_uid=idle_input_uid,
                dry_run=dry_run,
                confirm_send=confirm_send,
                skip_navigation=skip_navigation,
                target_window_id=target_window_id,
                will_live=will_live,
            )

    def _voice_call_exec(
        self,
        *,
        clean_target: str,
        clean_action: str,
        clean_app: str,
        clean_call_type: str,
        greeting: str,
        instructions: str,
        auto_voice_agent: bool,
        idle_input_uid: str,
        dry_run: bool,
        confirm_send: bool,
        skip_navigation: bool,
        target_window_id: Optional[int],
        will_live: bool,
    ) -> Dict[str, Any]:
        import os
        import signal
        import urllib.request

        saved_mic_file = self.plugin_root / "logs" / "voip_saved_input_device.json"

        if clean_action == "hangup":
            if will_live:
                try:
                    req = urllib.request.Request("http://127.0.0.1:18797/hangup", data=b"{}", method="POST")
                    with urllib.request.urlopen(req, timeout=1.5):
                        pass
                except Exception:
                    pid_file = self.plugin_root / "logs" / "wechat_voip_call.pid"
                    if pid_file.is_file():
                        try:
                            os.kill(int(pid_file.read_text(encoding="utf-8").strip()), signal.SIGTERM)
                        except Exception:
                            pass
            args = ["voice-call", "--action", "hangup", "--app-id", clean_app or "all", "--save-file", str(saved_mic_file)]
            if not will_live:
                args.append("--dry-run")
            native_res = self._run_native(args, timeout=12.0)
            if will_live and saved_mic_file.is_file():
                self._run_native(["set-input-device", "--restore", "--save-file", str(saved_mic_file)], timeout=6.0)
            audio_after = self._run_native(["audio-devices"], timeout=5.0)
            res = {
                "ok": bool(native_res.get("ok")),
                "action": "hangup",
                "status": "dry_run_ok" if not will_live else ("hung_up" if native_res.get("hungUp") else "idle"),
                "native": native_res,
                "defaultInput": audio_after.get("defaultInput"),
            }
            self.audit.log("voice_call_hangup", res["status"], res)
            return res

        if clean_action == "answer":
            args = ["voice-call", "--action", "answer", "--app-id", clean_app or "all"]
            if not will_live:
                args.append("--dry-run")
            native_res = self._run_native(args, timeout=12.0)
            daemon_res: Dict[str, Any] = {"ok": False, "status": "dry_run_skipped"}
            if will_live and native_res.get("ok") and auto_voice_agent:
                answered_app = ((native_res.get("afterState") or {}).get("calls") or [{}])[0].get("appId") or (clean_app if clean_app != "all" else "wechat")
                daemon_res = self._start_voip_voice_daemon(
                    app=str(answered_app),
                    target=clean_target,
                    greeting=greeting,
                    instructions=instructions,
                    idle_input_uid=idle_input_uid,
                    assume_connected=True,
                    restart_if_running=True,
                )
            res = {
                "ok": bool(native_res.get("ok")),
                "action": "answer",
                "status": "dry_run_ok" if not will_live else ("answered" if native_res.get("answered") else "answer_failed"),
                "target": clean_target,
                "native": native_res,
                "voiceDaemon": daemon_res,
            }
            self.audit.log("voice_call_answer", res["status"], res)
            return res

        # action == "dial" or "join"
        if will_live:
            pre_scan = self._run_native(["voice-call", "--action", "status", "--app-id", clean_app or "all"], timeout=6.0)
            if pre_scan.get("callStatus") == "connected":
                connected_app = (
                    (pre_scan.get("calls") or [{}])[0].get("appId")
                    or (clean_app if clean_app not in ("all", "omni") else "wechat")
                )
                daemon_res = self._start_voip_voice_daemon(
                    app=str(connected_app),
                    target=clean_target,
                    greeting=greeting,
                    instructions=instructions,
                    idle_input_uid=idle_input_uid,
                    assume_connected=True,
                    restart_if_running=True,
                )
                res = {
                    "ok": True,
                    "action": clean_action,
                    "app": str(connected_app),
                    "target": clean_target,
                    "alreadyInCall": True,
                    "status": "connected",
                    "native": pre_scan,
                    "voiceDaemon": daemon_res,
                }
                self.audit.log("voice_call_join_connected", res["status"], res)
                return res
            if clean_action == "join":
                if pre_scan.get("callStatus") == "ringing_incoming":
                    return self.voice_call(
                        clean_target,
                        action="answer",
                        app=clean_app,
                        greeting=greeting,
                        instructions=instructions,
                        auto_voice_agent=auto_voice_agent,
                        idle_input_uid=idle_input_uid,
                        dry_run=dry_run,
                        confirm_send=confirm_send,
                    )
                return {"ok": False, "action": "join", "status": "no_active_call", "native": pre_scan}

        effective_wid: Optional[int] = int(target_window_id) if target_window_id is not None else None
        popout_win = None
        if clean_app == "wechat":
            if effective_wid is None and clean_target and hasattr(self, "inspector"):
                try:
                    popout_win = self.inspector.find_popout_window(clean_target, app="wechat")
                    if popout_win and popout_win.get("windowID"):
                        effective_wid = int(popout_win["windowID"])
                except Exception:
                    popout_win = None
            if effective_wid is None and clean_target and (not skip_navigation) and will_live and hasattr(self, "inspector"):
                nav = self.inspector.select_session(clean_target)
                if not nav.get("ok"):
                    return {
                        "ok": False,
                        "action": "dial",
                        "status": "target_navigation_failed",
                        "target": clean_target,
                        "error": nav.get("error", f"Failed to navigate to {clean_target!r}."),
                    }

        args = ["voice-call", "--action", "dial", "--app-id", "all" if clean_app == "all" else clean_app, "--call-type", clean_call_type]
        if clean_app == "all":
            # Default dial app to wechat unless specified
            args[4] = "wechat"
        if effective_wid is not None:
            args += ["--window-id", str(effective_wid)]
            pw_title = str((popout_win or {}).get("title") or "").strip()
            if pw_title:
                args += ["--window-title", pw_title]
        elif clean_target:
            args += ["--target", clean_target]
        if not will_live:
            args.append("--dry-run")

        native_res = self._run_native(args, timeout=15.0)
        daemon_res: Dict[str, Any] = {"ok": False, "status": "dry_run_skipped"}
        if will_live and native_res.get("ok") and auto_voice_agent:
            daemon_res = self._start_voip_voice_daemon(
                app="wecom" if clean_app == "wecom" else "wechat",
                target=clean_target or str(native_res.get("windowTitle") or ""),
                greeting=greeting,
                instructions=instructions,
                idle_input_uid=idle_input_uid,
                assume_connected=False,
                restart_if_running=True,
            )

        res = {
            "ok": bool(native_res.get("ok")),
            "action": "dial",
            "app": "wecom" if clean_app == "wecom" else "wechat",
            "callType": clean_call_type,
            "target": clean_target,
            "windowID": effective_wid or native_res.get("windowID"),
            "status": "dry_run_ok" if not will_live else ("dialing" if native_res.get("initiated") else "dial_failed"),
            "native": native_res,
            "voiceDaemon": daemon_res,
        }
        self.audit.log("voice_call_dial", res["status"], res)
        return res

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

    def consult_wechat_assistant(
        self,
        target: str = "",
        content_hint: str = "",
        *,
        assistant: str = "auto",
        mode: str = "auto",
        bubbles: Optional[List[Dict[str, Any]]] = None,
        bubble_coords: Optional[Dict[str, float]] = None,
        wait_seconds: float = 5.5,
        dry_run: bool = False,
        model_id: str = "auto/deepseek-v4.1-flash",
    ) -> Dict[str, Any]:
        """Consult WeChat native AI assistants (`@元宝` or `小微` session relay) to understand links/videos/articles."""
        self._require("status")
        res = self.media_analyzer.consult_wechat_assistant(
            target=target,
            content_hint=content_hint,
            assistant=assistant,
            mode=mode,
            bubbles=bubbles,
            bubble_coords=bubble_coords,
            wait_seconds=wait_seconds,
            dry_run=dry_run,
            model_id=model_id,
        )
        self.audit.log(
            "wechat_ai_assist",
            "ok" if res.get("ok") else "error",
            {
                "target": target,
                "mode": res.get("mode"),
                "assistant": res.get("assistant"),
                "assistantSessionFound": res.get("assistantSessionFound"),
                "analysisId": res.get("analysisId"),
                "dryRun": dry_run,
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
        filtered_profiles = [
            p for p in (analytics.get("profiles") or [])
            if not _is_bogus_ocr_target(p.get("target") or p.get("matchedTitle"))
        ]
        analytics["profiles"] = filtered_profiles
        analytics["profileCount"] = len(filtered_profiles)
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
        matches = self._find_contact_history_files(target)
        if matches:
            for hp in reversed(matches):
                try:
                    data = json.loads(hp.read_text(encoding="utf-8"))
                    records = data.get("records") or []
                    msgs = [
                        str(r.get("text", ""))
                        for r in records
                        if r.get("kind") == "message" and r.get("text")
                    ]
                    notes = [
                        str(r.get("text", ""))
                        for r in records
                        if r.get("kind") == "media_note" and str(r.get("text") or "").strip()
                    ]
                    merged = msgs[-6:]
                    for note in notes[-2:]:
                        if note not in merged:
                            merged.append(note)
                    if merged:
                        return merged
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
        entry_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        weights = entry_weights
        if weights is None and hasattr(self, "supervisor_eval"):
            try:
                weights = self.supervisor_eval.get_entry_weights()
            except Exception:
                weights = None
        return self.knowledge.search_context(
            query,
            kind=kind,
            library=library,
            external_only=external_only,
            limit=limit,
            entry_weights=weights,
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
        speed_mode: Optional[str] = None,
        task_goal: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        binding = self.bindings.get_binding(target)
        recent = list(self._recent_messages_for(target))

        raw_in = str(incoming_text or "").strip()
        sender_name = ""
        query_incoming = raw_in
        m_spk = re.match(r"^(?!https?:)([^:\s/\n]{1,16}):\s+(.+)$", raw_in, flags=re.S)
        if m_spk:
            sender_name = m_spk.group(1).strip()
            query_incoming = m_spk.group(2).strip() or raw_in

        # Merge recent media/assistant insights (e.g. [元宝深读:] / [小微深读:] / [链接深读:])
        for note in self.recent_media_notes(target, limit=3):
            if note not in recent:
                recent.append(note)

        # Auto deep-read URL if present in manual preview input and not already summarized
        url_m = re.search(r"https?://[^\s<>\"'\]）)]+", query_incoming, flags=re.IGNORECASE)
        if url_m and hasattr(self, "media_analyzer"):
            found_url = url_m.group(0).strip()
            already_read = any(
                "[链接深读:" in m and (found_url[:36] in m or urllib.parse.urlparse(found_url).netloc in m)
                for m in recent
            )
            if not already_read:
                try:
                    lres = self.media_analyzer.analyze_link(
                        found_url,
                        contact=target,
                        context_text=query_incoming,
                        model_id=model_id or (binding or {}).get("visionModelId") or "auto/deepseek-v4.1-flash",
                    )
                    if lres.get("summary"):
                        link_note = f"[链接深读:{lres.get('title', '')}] {lres.get('summary')}"
                        if link_note not in recent:
                            recent.append(link_note)
                        try:
                            self.append_media_note(target, link_note)
                        except Exception:
                            pass
                except Exception:
                    pass

        memory_context = dict(self.soul_profiler.get_contact_memory_context(target) or {})
        try:
            history_snippet = self.recent_history_thread(target, limit=6)
            if history_snippet:
                memory_context["historyThreadSnippet"] = history_snippet
        except Exception:
            pass
        if sender_name:
            memory_context["groupSpeaker"] = sender_name

        with self._workos_lock:
            eff_speed = str(speed_mode or self._workos_state.get("speedMode") or "fast").strip().lower()
            eff_goal = str(task_goal if task_goal is not None else self._workos_state.get("taskGoal") or "").strip()

        neg_constraints: List[Dict[str, Any]] = []
        entry_weights: Optional[Dict[str, float]] = None
        if hasattr(self, "supervisor_eval"):
            try:
                neg_constraints = self.supervisor_eval.match_negative_constraints(query_incoming, limit=3)
                golden_exemplars = self.supervisor_eval.match_golden_exemplars(query_incoming, limit=2)
                entry_weights = self.supervisor_eval.get_entry_weights()
                memory_context["negativeConstraints"] = neg_constraints
                memory_context["goldenExemplars"] = golden_exemplars
                memory_context["entryWeights"] = entry_weights
            except Exception:
                pass

        res = self.personas.generate_smart_reply(
            target,
            query_incoming,
            knowledge_store=self.knowledge,
            binding=binding,
            persona_override=persona_override,
            recent_messages=recent,
            memory_context=memory_context,
            model_hub=self.models,
            model_id=model_id,
            use_llm=use_llm,
            speed_mode=eff_speed,
            task_goal=eff_goal,
            entry_weights=entry_weights,
        )
        if res.get("ok") and hasattr(self, "supervisor_eval") and str(res.get("generationMode") or "") != "empty_input_guard":
            try:
                auto_score = self.supervisor_eval.auto_score_reply(
                    query_incoming,
                    str(res.get("replyText") or ""),
                    matched_entries=res.get("matchedEntries") or (),
                    negative_constraints=neg_constraints,
                )
                res["autoScore"] = auto_score
                if int(auto_score.get("overallScore", 100)) < 70:
                    res["needsHumanReview"] = True
                    if not res.get("humanReviewReason"):
                        res["humanReviewReason"] = "自动评分低于 70 分，建议人工复核"
            except Exception:
                pass
        if (
            res.get("ok")
            and int(res.get("matchedCount") or 0) == 0
            and str(res.get("generationMode") or "") != "empty_input_guard"
            and query_incoming
            and str(target or "").strip()
        ):
            self._record_workos_reflection(
                target=str(target).strip(),
                incoming_text=query_incoming,
                reply_text=str(res.get("replyText") or ""),
            )
        return res

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
        bound = self.get_bound_app_window() if hasattr(self, "app_window_binder") else {}
        bound_app = str(bound.get("appId") or "auto")
        args = ["activate"] + (["--app", bound_app] if bound_app in ("wechat", "wecom") else [])
        res = self._run_native(args, 12.0)
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

    def diagnostics(self, *, deep: bool = False) -> Dict[str, Any]:
        """一键健康诊断：聚合各子系统状态 + 最近事件，供 /api/diagnostics 与排障使用。

        deep=True 附加原生权限探测与 LLM 网关 TCP 探测（较慢）；
        默认浅模式只读内存/磁盘状态。子系统的失败不影响整体报告。
        """
        report: Dict[str, Any] = {
            "ok": True,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
        try:
            manifest_candidates = [
                _BUNDLE_RES / "plugin.manifest.json",
                self.plugin_root / "plugin.manifest.json",
            ]
            manifest = next((p for p in manifest_candidates if p.is_file()), None)
            report["version"] = str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "?") if manifest else "?"
        except Exception:
            report["version"] = "?"
        try:
            report["auth"] = self.auth_status()
        except Exception as exc:
            report["auth"] = {"ok": False, "error": str(exc)}
        try:
            report["hosting"] = self.hosting_manager.status()
        except Exception as exc:
            report["hosting"] = {"ok": False, "error": str(exc)}
        try:
            report["antiban"] = self.antiban.status()
        except Exception as exc:
            report["antiban"] = {"ok": False, "error": str(exc)}
        try:
            report["knowledgeEntries"] = int(
                self.knowledge.list_entries(include_drafts=False, limit=5000).get("count") or 0
            )
        except Exception as exc:
            report["knowledgeEntries"] = {"error": str(exc)}
        try:
            report["monitorState"] = self.monitor.state_summary()
        except Exception as exc:
            report["monitorState"] = {"error": str(exc)}
        try:
            report["recentEvents"] = self.monitor.recent_events(limit=20)
        except Exception as exc:
            report["recentEvents"] = {"error": str(exc)}
        if deep:
            try:
                report["permissions"] = self.permissions_status()
            except Exception as exc:
                report["permissions"] = {"ok": False, "error": str(exc)}
            try:
                report["llmGateway"] = self.llm_gateway_status()
            except Exception as exc:
                report["llmGateway"] = {"ok": False, "error": str(exc)}
        return report

    def hosting_status(self) -> Dict[str, Any]:
        self._require("status")
        return {"ok": True, **self.hosting_manager.status()}

    def permissions_status(self) -> Dict[str, Any]:
        """实时检查 macOS 三项关键权限（辅助功能/系统事件/屏幕录制），供启动引导面板。

        属于只读系统前置体检（不依赖 Studio 插件授权门禁），每次真实调用原生 status（不缓存），
        确保用户在系统设置里改完点「重新检查」立即生效。
        """
        bound = self.get_bound_app_window() if hasattr(self, "app_window_binder") else {}
        bound_app = str(bound.get("appId") or "auto")
        status_args = ["status"] + (["--app", bound_app] if bound_app in ("wechat", "wecom") else [])
        try:
            res = self._run_native(status_args, 8.0)
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
             # 面板标识是 Privacy_ScreenCapture；写成 Privacy_ScreenRecording 系统只会打开「隐私与安全性」总页
             "pane": "Privacy_ScreenCapture",
             "deepLink": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"},
        ]
        return {
            "ok": True,
            "items": items,
            "allGranted": accessibility and post_event and screen_capture,
            "wechatRunning": bool(res.get("wechatRunning")),
            "wechatPid": res.get("wechatPid"),
            "boundWindow": bound,
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
            existing_files = self._find_contact_history_files(target)
            fname = existing_files[-1] if existing_files else (contacts_dir / f"{slug}_history.json")
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
                atomic_write_json(Path(fname_str), doc)
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
            if not target or p.get("isFolderContainer") or _is_bogus_ocr_target(target):
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
            if not target or _is_bogus_ocr_target(target):
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
        # 已打开的独立聊天小窗（如 微信ClawBot / openbot）自动列入可选好友
        if hasattr(self, "inspector") and hasattr(self.inspector, "list_popout_windows"):
            try:
                popouts = self.inspector.list_popout_windows(app="all") or []
            except Exception:
                popouts = []
            for pw in popouts:
                raw_title = str(pw.get("title") or "").strip()
                if not raw_title or _is_bogus_ocr_target(raw_title):
                    continue
                key = normalize_chat_name(raw_title).casefold()
                if key in seen or any(_matches_target(raw_title, f["target"]) for f in friends):
                    continue
                seen.add(key)
                friends.append({
                    "target": raw_title,
                    "matchedTitle": raw_title,
                    "bound": False,
                    "autoReplyEnabled": False,
                    "takenOver": _taken_over(raw_title),
                    "careLevel": "normal",
                    "popoutWindowID": pw.get("windowID"),
                })
        friends.sort(key=lambda f: (not f["autoReplyEnabled"], not f["bound"], f["target"].casefold()))
        return {"ok": True, "friends": friends, "hosting": self.hosting_manager.status()}

    def list_watched_contacts(self) -> Dict[str, Any]:
        """Return currently watched/auto-reply contacts alongside full hosting friends list."""
        friends_doc = self.hosting_friends()
        hosting = friends_doc.get("hosting") or {}
        watched: List[str] = []
        seen: set[str] = set()

        def _push(raw: Any) -> None:
            clean = str(raw or "").strip()
            if not clean or _is_bogus_ocr_target(clean):
                return
            key = normalize_chat_name(clean).casefold()
            if key in seen:
                return
            seen.add(key)
            watched.append(clean)

        for item in (hosting.get("targets") or []):
            _push(item)
        for item in (friends_doc.get("friends") or []):
            if bool(item.get("bound")) and bool(item.get("autoReplyEnabled")):
                _push(item.get("target"))
        return {
            "ok": True,
            "watchedTargets": watched,
            "friends": friends_doc.get("friends", []),
            "hosting": hosting,
        }

    def watch_contact(
        self,
        target: str,
        *,
        alias: str = "",
        role: str = "friend",
        ai_persona: str = "warm-companion",
        care_level: Optional[str] = None,
        auto_start_hosting: bool = True,
    ) -> Dict[str, Any]:
        """Bind a contact for automatic monitoring & reply, and enroll in active hosting."""
        self._require("status")
        clean_target = str(target or "").strip()
        if not clean_target:
            return {
                "ok": False,
                "error_code": "missing_target",
                "error": "Target contact name is required.",
            }
        if auto_start_hosting:
            self._require("read_sessions")
            self._require("read_messages")
            self._require("ocr")
            self._require("send_text_live")

        existing = self.bindings.get_binding(clean_target) or {}
        bind_res = self.bind_contact(
            clean_target,
            alias=alias or str(existing.get("alias") or ""),
            role=role or str(existing.get("role") or "friend"),
            ai_persona=ai_persona or str(existing.get("aiPersona") or "warm-companion"),
            care_level=care_level if care_level is not None else existing.get("careLevel"),
            auto_reply_enabled=True,
        )
        if getattr(self.allowlist, "enabled", False):
            added_to_allowlist = self.allowlist.add_allowed(clean_target)
            if added_to_allowlist:
                self._runtime_allowlist_targets.add(normalize_chat_name(clean_target).casefold())
        hosting_res = self.hosting_manager.add_target(clean_target, auto_start=bool(auto_start_hosting))
        self.audit.log(
            "watch_contact",
            "ok",
            {
                "target": clean_target,
                "autoStartHosting": bool(auto_start_hosting),
                "hostingRunning": bool(hosting_res.get("running")),
            },
        )
        watched = self.list_watched_contacts()
        return {
            "ok": True,
            "target": clean_target,
            "watched": True,
            "autoReplyEnabled": True,
            "binding": bind_res.get("binding"),
            "hosting": self.hosting_manager.status(),
            "watchedTargets": watched.get("watchedTargets", []),
        }

    def unwatch_contact(self, target: str) -> Dict[str, Any]:
        """Disable auto-reply watch on a contact and remove it from active hosting targets."""
        self._require("status")
        clean_target = str(target or "").strip()
        if not clean_target:
            return {
                "ok": False,
                "error_code": "missing_target",
                "error": "Target contact name is required.",
            }
        existing = self.bindings.get_binding(clean_target)
        if existing:
            self.bind_contact(
                str(existing.get("target") or clean_target),
                alias=str(existing.get("alias") or ""),
                role=str(existing.get("role") or "friend"),
                ai_persona=str(existing.get("aiPersona") or "warm-companion"),
                auto_reply_enabled=False,
            )
        norm_key = normalize_chat_name(clean_target).casefold()
        if (
            getattr(self.allowlist, "enabled", False)
            and norm_key in self._runtime_allowlist_targets
            and len(self.allowlist.list_allowed()) > 1
        ):
            self.allowlist.remove_allowed(clean_target)
            self._runtime_allowlist_targets.discard(norm_key)
        self.hosting_manager.remove_target(clean_target)
        self.audit.log("unwatch_contact", "ok", {"target": clean_target})
        watched = self.list_watched_contacts()
        return {
            "ok": True,
            "target": clean_target,
            "watched": False,
            "autoReplyEnabled": False,
            "hosting": self.hosting_manager.status(),
            "watchedTargets": watched.get("watchedTargets", []),
        }

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

    def _load_merged_history(self, target: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """合并某联系人的全部历史文件（AX 巡检 / 独立小窗 / 导入 / chatlog / 实时回写可能各成一个文件），
        按时间顺序合并并去重保留最新条目。"""
        clean = str(target or "").strip()
        contacts_dir = self.inspector.reports_dir / "contacts"
        if not clean or not contacts_dir.exists():
            return None, []
        matches = self._find_contact_history_files(clean)
        raw_merged: List[Dict[str, Any]] = []
        doc_meta: Optional[Dict[str, Any]] = None
        for p in matches:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(doc, dict) or not doc.get("target"):
                continue
            doc_meta = doc
            raw_merged.extend(doc.get("records") or [])
        # Deduplicate preserving the newest canonical file's exact chronological/visual order
        deduped_slots: List[Optional[Dict[str, Any]]] = []
        seen_idx: Dict[str, int] = {}
        for r in raw_merged:
            if not isinstance(r, dict):
                continue
            sig = f"{r.get('kind', '')}||{r.get('direction', '')}||{str(r.get('text') or '').strip()}"
            if sig in seen_idx:
                deduped_slots[seen_idx[sig]] = None
            seen_idx[sig] = len(deduped_slots)
            deduped_slots.append(r)
        deduped = [item for item in deduped_slots if item is not None]
        return doc_meta, deduped

    def _latest_inbound_by_target(self) -> Dict[str, Dict[str, str]]:
        """从合并后的历史记录提取每位联系人的最近一条客户来信。"""
        out: Dict[str, Dict[str, str]] = {}
        contacts_dir = self.inspector.reports_dir / "contacts"
        if not contacts_dir.exists():
            return out
        targets_seen: Dict[str, str] = {}
        for f in sorted(contacts_dir.glob("*_history.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            t = str(doc.get("target") or "").strip()
            if t:
                targets_seen[normalize_chat_name(t).casefold()] = t
        for _, target in targets_seen.items():
            _, merged = self._load_merged_history(target)
            latest = None
            for r in merged:
                if r.get("direction") == "peer" and str(r.get("text") or "").strip():
                    latest = r
            if not latest:
                continue
            out[normalize_chat_name(target).casefold()] = {
                "target": target,
                "text": str(latest.get("text")).strip()[:120],
                "at": str(latest.get("timeMarker") or latest.get("ts") or ""),
                "sortAt": str(latest.get("ts") or ""),
            }
        return out

    def _recent_threads_by_target(self, limit: int = 12) -> Dict[str, Dict[str, Any]]:
        """每位联系人最近 limit 条往来消息（合并全部历史文件，peer/self，时间正序）。"""
        out: Dict[str, Dict[str, Any]] = {}
        contacts_dir = self.inspector.reports_dir / "contacts"
        if not contacts_dir.exists():
            return out
        seen_targets: Dict[str, str] = {}
        for f in sorted(contacts_dir.glob("*_history.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            t = str(doc.get("target") or "").strip()
            if t:
                seen_targets[normalize_chat_name(t).casefold()] = t
        for _, target in seen_targets.items():
            _, merged = self._load_merged_history(target)
            messages = []
            for r in merged:
                if r.get("kind") not in ("message", "media_note"):
                    continue
                text = str(r.get("text") or "").strip()
                if not text:
                    continue
                msg_item: Dict[str, Any] = {
                    "direction": str(r.get("direction") or "peer"),
                    "kind": str(r.get("kind") or "message"),
                    "source": str(r.get("source") or "history"),
                    "text": text[:240],
                    "at": str(r.get("timeMarker") or r.get("ts") or ""),
                    "confidence": (lambda v: round(float(v), 2) if v is not None else None)(r.get("confidence")),
                }
                if r.get("mediaType"):
                    msg_item["mediaType"] = str(r["mediaType"])
                if isinstance(r.get("cardMeta"), dict) and r["cardMeta"]:
                    msg_item["cardMeta"] = dict(r["cardMeta"])
                messages.append(msg_item)
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
        atomic_write_json(dest, doc)
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

    @staticmethod
    def _strip_group_count_suffix(target: str) -> str:
        return re.sub(r"\s*[\(（]\d+[\)）]\s*$", "", str(target or "").strip()).strip()

    def _find_contact_history_files(self, target: str) -> List[Path]:
        """Find persisted history files matching `target` (normalizing `openbot (2)` -> `openbot`), oldest -> newest."""
        clean = str(target or "").strip()
        if not clean:
            return []
        contacts_dir = self.inspector.reports_dir / "contacts"
        if not contacts_dir.exists():
            return []
        base = self._strip_group_count_suffix(clean)
        found: List[Path] = []
        seen: set[Path] = set()
        for prefix in (clean, base):
            if not prefix:
                continue
            for p in contacts_dir.glob(f"{prefix}_*_history.json"):
                if p not in seen:
                    seen.add(p)
                    found.append(p)
        for p in contacts_dir.glob("*_history.json"):
            if p in seen:
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and (
                    _matches_target(clean, str(doc.get("target") or ""))
                    or _matches_target(clean, str(doc.get("matchedTitle") or ""))
                ):
                    seen.add(p)
                    found.append(p)
            except Exception:
                continue
        found.sort(key=lambda p: p.stat().st_mtime)
        return found

    def recent_history_thread(self, target: str, limit: int = 6) -> str:
        """单联系人最近 limit 条往来（peer/self，正序），拼成片段注入自动回复上下文。"""
        matches = self._find_contact_history_files(target)
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
        base_clean = self._strip_group_count_suffix(clean) or clean
        contacts_dir = self.inspector.reports_dir / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        matches = self._find_contact_history_files(clean)
        now_iso = datetime.now(timezone.utc).isoformat()
        if not matches:
            # 该联系人尚无历史文件：创建一个（归一化群名如 openbot (2) -> openbot）
            slug = _slugify_target(base_clean) or hashlib.sha1(normalize_chat_name(base_clean).encode("utf-8")).hexdigest()[:6]
            path = contacts_dir / f"{base_clean}_{slug}_history.json"
            doc = {
                "ok": True, "target": base_clean, "matchedTitle": clean, "slug": slug,
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
        # 内容级去重：同一链接/图片重复识别没有信息增量（遮挡重试会重复触发深读）
        note_key = ("system", note_text[:200])
        existing_keys = {
            (str(r.get("direction") or ""), str(r.get("text") or "").strip()[:200])
            for r in doc.get("records", [])
            if r.get("kind") == "media_note"
        }
        if note_key in existing_keys:
            return {"ok": True, "deduped": True, "target": clean}
        doc["records"].append({
            "text": note_text[:360],
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
            atomic_write_json(path, doc)
            self.audit.log("media_note_persist", "ok", {"target": clean, "note": note_text[:80]})
            return True
        except OSError:
            return False

    def recent_media_notes(
        self,
        target: str,
        *,
        limit: int = 2,
        max_age_seconds: int = 1800,
    ) -> List[str]:
        """读取联系人近期（默认 30 分钟内）的 media_note 摘要，用于小微/元宝深读结果的跨轮引用。"""
        matches = self._find_contact_history_files(target)
        if not matches:
            return []
        try:
            doc = json.loads(matches[-1].read_text(encoding="utf-8"))
        except Exception:
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - max(0, int(max_age_seconds))
        found: List[str] = []
        for r in reversed(doc.get("records", [])):
            if r.get("kind") != "media_note":
                continue
            txt = str(r.get("text") or "").strip()
            if not txt:
                continue
            ts_str = str(r.get("ts") or "").strip()
            if ts_str and max_age_seconds > 0:
                try:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if dt.timestamp() < cutoff:
                        continue
                except Exception:
                    pass
            if txt not in found:
                found.append(txt)
            if len(found) >= max(1, int(limit)):
                break
        found.reverse()
        return found

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

    def forward_bubble_via_menu(
        self,
        bubble_x: float,
        bubble_y: float,
        recipient: str,
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """通过微信右键菜单「转发」把当前气泡（如视频号/公众号卡片）安全转发给已验证的原生助手或白名单联系人。"""
        self._require("send_text_live")
        from .media_link_analyzer import is_wechat_ai_assistant_name

        clean_recipient = str(recipient or "").strip()
        if not clean_recipient:
            return {"ok": False, "error_code": "recipient_required", "error": "Recipient cannot be empty."}
        bound_targets = [str(b.get("target") or "").strip() for b in self.bindings.list_bindings()]
        is_ai = is_wechat_ai_assistant_name(clean_recipient)
        is_explicit_allow = bool(self.allowlist.enabled and self.allowlist.is_allowed(clean_recipient))
        is_bound = any(_matches_target(clean_recipient, bt) for bt in bound_targets if bt)
        if not (is_ai or is_explicit_allow or is_bound):
            return {
                "ok": False,
                "error_code": "recipient_not_allowed",
                "recipient": clean_recipient,
                "error": f"Refusing to forward bubble to non-allowlisted recipient {clean_recipient!r}.",
            }
        if dry_run:
            return {
                "ok": True,
                "dryRun": True,
                "recipient": clean_recipient,
                "isWeChatAiAssistant": is_ai,
                "bubble": {"x": float(bubble_x), "y": float(bubble_y)},
            }

        snap_menu = self.inspector.snapshots_dir / "forward_menu_probe.png"
        self._run_native(["right-click", "--x", str(bubble_x), "--y", str(bubble_y)], 10.0)
        time.sleep(0.6)
        cap_menu = self._run_native(["capture-ocr", "--out", str(snap_menu)], 12.0)
        forward_center = None
        for el in cap_menu.get("elements") or []:
            txt = str(el.get("text") or "").strip()
            if txt.startswith("转发") and isinstance(el.get("center"), dict):
                forward_center = el["center"]
                break
        if not forward_center:
            return {
                "ok": False,
                "error_code": "forward_menu_not_found",
                "recipient": clean_recipient,
                "menuItems": [str(e.get("text") or "") for e in (cap_menu.get("elements") or [])[:12]],
            }
        self._run_native(["click", "--x", str(forward_center.get("x")), "--y", str(forward_center.get("y"))], 10.0)
        time.sleep(0.75)

        snap_picker = self.inspector.snapshots_dir / "forward_picker_probe.png"
        cap_picker = self._run_native(["capture-ocr", "--out", str(snap_picker)], 12.0)
        rec_center = None
        for el in cap_picker.get("elements") or []:
            txt = str(el.get("text") or "").strip()
            if _matches_target(clean_recipient, txt) and isinstance(el.get("center"), dict):
                rec_center = el["center"]
                break
        if not rec_center:
            return {
                "ok": False,
                "error_code": "forward_recipient_not_visible",
                "recipient": clean_recipient,
            }
        self._run_native(["click", "--x", str(rec_center.get("x")), "--y", str(rec_center.get("y"))], 10.0)
        time.sleep(0.35)
        cap_confirm = self._run_native(["capture-ocr", "--out", str(self.inspector.snapshots_dir / "forward_confirm_probe.png")], 12.0)
        sent_ok = False
        for el in reversed(cap_confirm.get("elements") or []):
            txt = str(el.get("text") or "").strip()
            if txt in ("发送", "确定", "Send", "OK") and isinstance(el.get("center"), dict):
                c = el["center"]
                self._run_native(["click", "--x", str(c.get("x")), "--y", str(c.get("y"))], 10.0)
                sent_ok = True
                break
        return {
            "ok": sent_ok,
            "forwarded": sent_ok,
            "recipient": clean_recipient,
            "isWeChatAiAssistant": is_ai,
            "error_code": "" if sent_ok else "forward_confirm_button_not_found",
        }

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

    def _resolve_avatar_crop(self, target: str, snap: Path) -> Dict[str, int]:
        """从巡检报告或快照 OCR 中匹配目标会话行的 avatarRel 坐标，未命中时兜底首行头像坐标。"""
        report_path = self.inspector.reports_dir / "wechat_management_report.json"
        if report_path.is_file():
            try:
                rep = json.loads(report_path.read_text(encoding="utf-8"))
                for s in rep.get("sessions") or []:
                    cand = str(s.get("fullTitle") or s.get("listTitleSnippet") or "").strip()
                    rel = s.get("avatarRel")
                    if cand and isinstance(rel, dict) and _matches_target(cand, target):
                        return {
                            "x": int(round(float(rel.get("x", 70)))),
                            "y": int(round(float(rel.get("y", 66)))),
                            "width": max(16, int(round(float(rel.get("width", 40))))),
                            "height": max(16, int(round(float(rel.get("height", 40))))),
                        }
            except Exception:
                pass
        try:
            ocr_res = self._run_native(["ocr", "--image", str(snap)], 15.0)
            if ocr_res.get("ok") and (ocr_res.get("elements") or []):
                win_w = float(ocr_res.get("imageWidth") or 853.0)
                win_h = float(ocr_res.get("imageHeight") or 1320.0)
                elements = ocr_res.get("elements") or []
                split_x = self.inspector._infer_split_x(elements, win_w)
                rows = self.inspector._cluster_session_rows(elements, split_x, win_h)
                for row in rows:
                    cand = str(row.get("titleSnippet") or "").strip()
                    rel = row.get("avatarRel")
                    if cand and isinstance(rel, dict) and _matches_target(cand, target):
                        return {
                            "x": int(round(float(rel.get("x", 70)))),
                            "y": int(round(float(rel.get("y", 66)))),
                            "width": max(16, int(round(float(rel.get("width", 40))))),
                            "height": max(16, int(round(float(rel.get("height", 40))))),
                        }
        except Exception:
            pass
        return {"x": 70, "y": 66, "width": 40, "height": 40}

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
        region = crop if isinstance(crop, dict) else self._resolve_avatar_crop(clean, snap)
        res = self._run_native([
            "ocr", "--image", str(snap),
            "--crop", f"{int(region['x'])},{int(region['y'])},{int(region['width'])},{int(region['height'])}",
            "--out", str(out_path),
        ], 15.0)
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or res.get("error_code") or "crop_failed")}
        if not out_path.is_file() or out_path.stat().st_size < 200:
            return {"ok": False, "error": "EMPTY_AVATAR"}
        return {"ok": True, "target": clean, "url": f"/avatars/{clean}.png", "path": str(out_path), "crop": region}

    def refresh_avatars(
        self,
        *,
        targets: Optional[List[str]] = None,
        capture_fresh: bool = True,
    ) -> Dict[str, Any]:
        """Batch-capture and refresh sidebar contact avatars from live WeChat/WeCom windows & reports."""
        self._require("ocr" if capture_fresh else "status")
        out_dir = self.inspector.snapshots_dir.parent / "avatars"
        out_dir.mkdir(parents=True, exist_ok=True)
        self.inspector.snapshots_dir.mkdir(parents=True, exist_ok=True)

        sources: List[Tuple[Path, List[Dict[str, Any]]]] = []
        if capture_fresh:
            for app_id, wtitle in (("wechat", "微信"), ("wecom", "企业微信")):
                snap_file = self.inspector.snapshots_dir / f"avatar_refresh_{app_id}.png"
                cmd = ["capture-ocr", "--app", app_id, "--window-title", wtitle, "--out", str(snap_file), "--no-activate"]
                cap = self._run_native(cmd, 16.0)
                if not cap.get("ok") and cap.get("error_code") in ("window_not_found", "no_window"):
                    cap = self._run_native(["capture-ocr", "--app", app_id, "--out", str(snap_file), "--no-activate"], 16.0)
                if not cap.get("ok") and cap.get("error_code") in ("window_occluded", "capture_failed"):
                    cap = self._run_native(["capture-ocr", "--app", app_id, "--window-title", wtitle, "--out", str(snap_file)], 18.0)
                    if not cap.get("ok") and cap.get("error_code") in ("window_not_found", "no_window"):
                        cap = self._run_native(["capture-ocr", "--app", app_id, "--out", str(snap_file)], 18.0)
                if cap.get("ok") and snap_file.is_file() and (cap.get("elements") or []):
                    win_w = float(cap.get("imageWidth") or 853.0)
                    win_h = float(cap.get("imageHeight") or 1320.0)
                    els = cap.get("elements") or []
                    if not self.inspector._is_popout_window(cap, els):
                        split_x = self.inspector._infer_split_x(els, win_w)
                        rows = self.inspector._cluster_session_rows(els, split_x, win_h, image_path=snap_file)
                        if rows:
                            sources.append((snap_file, rows))

        # Fallback to existing overview snapshot + management report
        for fallback_name in ("sessions_overview_p0.png", "monitor_poll_cur.png"):
            fb_snap = self.inspector.snapshots_dir / fallback_name
            if fb_snap.is_file():
                fb_rows: List[Dict[str, Any]] = []
                ocr_res = self._run_native(["ocr", "--image", str(fb_snap)], 14.0)
                if ocr_res.get("ok") and (ocr_res.get("elements") or []):
                    els = ocr_res.get("elements") or []
                    win_w = float(ocr_res.get("imageWidth") or 853.0)
                    win_h = float(ocr_res.get("imageHeight") or 1320.0)
                    if not self.inspector._is_popout_window({"windowTitle": ""}, els):
                        split_x = self.inspector._infer_split_x(els, win_w)
                        fb_rows = self.inspector._cluster_session_rows(els, split_x, win_h)
                if fb_rows:
                    sources.append((fb_snap, fb_rows))

        report_path = self.inspector.reports_dir / "wechat_management_report.json"
        if report_path.is_file():
            fb_snap = self.inspector.snapshots_dir / "sessions_overview_p0.png"
            if fb_snap.is_file():
                try:
                    rep = json.loads(report_path.read_text(encoding="utf-8"))
                    rep_rows: List[Dict[str, Any]] = []
                    for s in rep.get("sessions") or []:
                        if isinstance(s.get("avatarRel"), dict):
                            rep_rows.append(
                                {
                                    "titleSnippet": str(s.get("fullTitle") or s.get("listTitleSnippet") or "").strip(),
                                    "avatarRel": s["avatarRel"],
                                }
                            )
                    if rep_rows:
                        sources.append((fb_snap, rep_rows))
                except Exception:
                    pass

        known_targets: List[str] = []
        seen_t: set[str] = set()

        def _add_known(raw: Any) -> None:
            clean = normalize_chat_name(str(raw or ""))
            if not clean or "/" in clean or "\\" in clean or clean in (".", "..") or _is_bogus_ocr_target(clean):
                return
            low = clean.casefold()
            if low not in seen_t:
                seen_t.add(low)
                known_targets.append(clean)

        for t in (targets or []):
            _add_known(t)
        for b in self.bindings.list_bindings():
            _add_known(b.get("target"))
        for th in (self._recent_threads_by_target() or {}).keys():
            _add_known(th)

        updated: List[str] = []
        updated_set: set[str] = set()

        def _crop_to(save_name: str, snap_p: Path, rel: Dict[str, Any]) -> bool:
            clean_name = normalize_chat_name(save_name)
            if not clean_name or "/" in clean_name or "\\" in clean_name or clean_name in (".", "..") or _is_bogus_ocr_target(clean_name):
                return False
            out_path = (out_dir / f"{clean_name}.png").resolve()
            if out_path.parent != out_dir.resolve():
                return False
            cx = int(round(float(rel.get("x", 70))))
            cy = int(round(float(rel.get("y", 66))))
            cw = max(16, int(round(float(rel.get("width", 40)))))
            ch = max(16, int(round(float(rel.get("height", 40)))))
            crop_res = self._run_native(
                ["ocr", "--image", str(snap_p), "--crop", f"{cx},{cy},{cw},{ch}", "--out", str(out_path)],
                12.0,
            )
            if crop_res.get("ok") and out_path.is_file() and out_path.stat().st_size >= 200:
                if clean_name not in updated_set:
                    updated_set.add(clean_name)
                    updated.append(clean_name)
                return True
            return False

        # Crop matching known targets first, plus newly discovered visible rows
        for snap_p, rows in sources:
            for row in rows:
                rtitle = str(row.get("titleSnippet") or "").strip()
                rel = row.get("avatarRel")
                if not rtitle or not isinstance(rel, dict):
                    continue
                matched_known = False
                for kt in known_targets:
                    if _matches_target(kt, rtitle) or _matches_target(rtitle, kt):
                        _crop_to(kt, snap_p, rel)
                        matched_known = True
                if not matched_known:
                    _crop_to(rtitle, snap_p, rel)

        avatars: Dict[str, str] = {}
        avatar_versions: Dict[str, int] = {}
        for p in sorted(out_dir.glob("*.png")):
            if p.is_file():
                avatars[p.stem] = f"/avatars/{p.name}"
                avatar_versions[p.stem] = int(p.stat().st_mtime * 1000)

        missing = [
            kt
            for kt in known_targets
            if kt not in avatars and kt.lower() not in {k.lower() for k in avatars.keys()}
        ]
        self.audit.log(
            "avatar_refresh",
            "ok",
            {"updatedCount": len(updated), "totalAvatars": len(avatars), "scannedSources": len(sources)},
        )
        return {
            "ok": True,
            "updatedCount": len(updated),
            "updatedTargets": updated,
            "missingTargets": missing,
            "scannedSources": len(sources),
            "avatars": avatars,
            "avatarVersions": avatar_versions,
        }

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

        avatars: Dict[str, str] = {}
        avatar_versions: Dict[str, int] = {}
        avatar_dir = self.inspector.snapshots_dir.parent / "avatars"
        if avatar_dir.is_dir():
            for p in sorted(avatar_dir.glob("*.png")):
                if p.is_file():
                    avatars[p.stem] = f"/avatars/{p.name}"
                    avatar_versions[p.stem] = int(p.stat().st_mtime * 1000)

        return {
            "ok": True,
            "pluginId": doc.get("pluginId"),
            "pluginRoot": str(self.plugin_root),
            "authorization": doc.get("studioAuthorization"),
            "doctor": doc,
            "wechatStatus": doc.get("status"),
            "monitor": mon,
            "avatars": avatars,
            "avatarVersions": avatar_versions,
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
            "coevolution": self.coevolution.get_summary(),
            "tenantProfile": self.tenant.get_profile() if hasattr(self, "tenant") else {},
            "isCustomerMode": self.tenant.is_customer_mode() if hasattr(self, "tenant") else False,
            "testContacts": self.supervisor_eval.list_test_contacts() if hasattr(self, "supervisor_eval") else [],
            "qualityDashboard": self.supervisor_eval.get_quality_dashboard(days=7) if hasattr(self, "supervisor_eval") else {},
            "salesPacks": self.list_available_sales_packs(),
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
    # Moments (朋友圈) read + interaction
    # ------------------------------------------------------------------
    def moments_read_feed(self, *, max_posts: int = 40, max_pages: int = 90, restore_view: bool = True) -> Dict[str, Any]:
        return self.moments.read_feed(max_posts=max_posts, max_pages=max_pages, restore_view=restore_view)

    def moments_list_posts(self, *, limit: int = 30, author: str = "", include_partial: bool = False) -> Dict[str, Any]:
        return self.moments.list_posts(limit=limit, author=author, include_partial=include_partial)

    def moments_stats(self, *, limit: int = 40) -> Dict[str, Any]:
        return self.moments.stats(limit=limit)

    def moments_get_policy(self) -> Dict[str, Any]:
        return self.moments.get_policy()

    def moments_set_policy(self, updates: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return self.moments.set_policy(updates)

    def moments_plan(self, *, limit: int = 20, max_age_days: Optional[int] = None) -> Dict[str, Any]:
        return self.moments.plan(limit=limit, max_age_days=max_age_days)

    def moments_interact(
        self, post_key: str = "", *, author: str = "", action: str = "like", text: str = "",
        mode: str = "dry_run", restore_view: bool = True,
    ) -> Dict[str, Any]:
        """朋友圈点赞 / 取消点赞 / 评论。默认 dry_run；live 需要 moments_interact_live 能力。"""
        return self.moments.interact(
            post_key, author=author, action=action, text=text, mode=mode, restore_view=restore_view
        )

    def moments_execute_plan(
        self, items: Optional[List[Dict[str, Any]]] = None, *, mode: str = "dry_run", limit: int = 5,
        restore_view: bool = True,
    ) -> Dict[str, Any]:
        return self.moments.execute_plan(items, mode=mode, limit=limit, restore_view=restore_view)

    def moments_log(self, *, limit: int = 50) -> Dict[str, Any]:
        return self.moments.interaction_log(limit=limit)

    def moments_suggest_comment(self, post_key: str, *, style: str = "natural") -> Dict[str, Any]:
        """结合帖子内容与好友 Soul 画像拟写自然口语朋友圈评论建议（不发送，不碰微信 UI）。"""
        self._require("read_moments")
        res = self.moments.suggest_comment(post_key, style=style)
        self.audit.log(
            "moments_suggest_comment",
            "ok" if res.get("ok") else "error",
            {
                "postKey": post_key,
                "style": style,
                "usedLlm": bool(res.get("usedLlm")),
                "source": res.get("source"),
            },
        )
        return res

    def get_pre_call_brief(
        self,
        target: str,
        *,
        goal: str = "general",
        custom_goal: str = "",
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """聚合聊天历史、Soul 记忆、朋友圈动态与 SalesCRM 生成电话前一键速览与话术提词卡。"""
        self._require("read_contacts")
        res = self.call_brief.generate_brief(
            target,
            goal=goal,
            custom_goal=custom_goal,
            use_llm=use_llm,
        )
        self.audit.log(
            "call_brief",
            "ok" if res.get("ok") else "error",
            {
                "target": target,
                "goal": goal,
                "usedLlm": bool(res.get("usedLlm")),
                "modelId": res.get("modelId"),
            },
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

    # ------------------------------------------------------------------
    # Thiflow See-Think-Act & Yingdao AI WorkOS Harness (v2.4.69)
    # ------------------------------------------------------------------

    def _default_workos_state(self) -> Dict[str, Any]:
        preset = WORKOS_POST_PRESETS["private_ops"]
        return {
            "speedMode": "fast",
            "postPreset": "private_ops",
            "postLabel": preset["label"],
            "taskGoal": preset["goal"],
            "reflections": [],
            "evolutions": [],
            "borderOverlay": {
                "enabled": False,
                "modeColorState": "idle",
                "activePopoutWindowIDs": [],
                "lastUpdatedAt": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _load_workos_state(self) -> Dict[str, Any]:
        base = self._default_workos_state()
        try:
            if self.workos_state_path.is_file():
                raw = json.loads(self.workos_state_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k in ("speedMode", "postPreset", "postLabel", "taskGoal"):
                        if isinstance(raw.get(k), str) and raw[k].strip():
                            base[k] = raw[k].strip()
                    if isinstance(raw.get("reflections"), list):
                        base["reflections"] = [r for r in raw["reflections"] if isinstance(r, dict)][-30:]
                    if isinstance(raw.get("evolutions"), list):
                        base["evolutions"] = [e for e in raw["evolutions"] if isinstance(e, dict)][-50:]
                    bo = raw.get("borderOverlay")
                    if isinstance(bo, dict):
                        st = str(bo.get("modeColorState") or "idle").strip().lower()
                        if st not in BORDER_OVERLAY_COLORS:
                            st = "idle"
                        raw_wids = bo.get("activePopoutWindowIDs")
                        wids: List[int] = []
                        if isinstance(raw_wids, list):
                            for w in raw_wids:
                                try:
                                    if int(w) > 0:
                                        wids.append(int(w))
                                except (TypeError, ValueError):
                                    pass
                        base["borderOverlay"] = {
                            "enabled": bool(bo.get("enabled", False)),
                            "modeColorState": st,
                            "activePopoutWindowIDs": wids[:20],
                            "lastUpdatedAt": str(bo.get("lastUpdatedAt") or base["borderOverlay"]["lastUpdatedAt"]),
                        }
        except Exception:
            pass
        return base

    def _save_workos_state(self) -> None:
        try:
            self.workos_state_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.workos_state_path, self._workos_state)
        except Exception:
            pass

    def _record_workos_reflection(self, *, target: str, incoming_text: str, reply_text: str) -> None:
        clean_in = re.sub(r"\s+", " ", incoming_text or "").strip()[:160]
        if not clean_in:
            return
        with self._workos_lock:
            refs = list(self._workos_state.get("reflections") or [])
            # Deduplicate identical unanswered prompts across consecutive previews
            refs = [r for r in refs if not (r.get("target") == target and r.get("incomingText") == clean_in)]
            refs.append({
                "target": target,
                "incomingText": clean_in,
                "replyText": re.sub(r"\s+", " ", reply_text or "").strip()[:160],
                "ts": datetime.now(timezone.utc).isoformat(),
                "suggestion": "该来信暂未命中知识库固定条款，建议人工修改后点击「✨ 纠偏沉淀 SOP」。",
            })
            self._workos_state["reflections"] = refs[-30:]
            self._save_workos_state()

    def configure_workos_post(
        self,
        *,
        speed_mode: Optional[str] = None,
        post_preset: Optional[str] = None,
        task_goal: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Configure AI employee post goal and Fast/Deep model speed tier."""
        self._require("status")
        with self._workos_lock:
            if speed_mode is not None:
                sm = str(speed_mode).strip().lower()
                if sm not in ("fast", "deep"):
                    return {"ok": False, "error": f"Unsupported speed_mode: {speed_mode!r}"}
                self._workos_state["speedMode"] = sm
            if post_preset is not None:
                pp = str(post_preset).strip()
                if pp not in WORKOS_POST_PRESETS:
                    return {"ok": False, "error": f"Unsupported post_preset: {post_preset!r}"}
                self._workos_state["postPreset"] = pp
                self._workos_state["postLabel"] = WORKOS_POST_PRESETS[pp]["label"]
                if task_goal is None:
                    self._workos_state["taskGoal"] = WORKOS_POST_PRESETS[pp]["goal"]
            if task_goal is not None:
                clean_goal = re.sub(r"\s+", " ", str(task_goal)).strip()[:200]
                if clean_goal:
                    self._workos_state["taskGoal"] = clean_goal
            self._save_workos_state()
            snapshot = dict(self._workos_state)
        self.audit.log("workos_configure_post", "ok", {
            "speedMode": snapshot["speedMode"],
            "postPreset": snapshot["postPreset"],
            "taskGoal": snapshot["taskGoal"],
        })
        return {"ok": True, **snapshot, "presets": WORKOS_POST_PRESETS}

    def learn_from_correction(
        self,
        target: str,
        incoming_text: str,
        corrected_reply: str,
        *,
        original_draft: str = "",
        title: str = "",
        kind: str = "script",
        keywords: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Thiflow/WorkOS continuous self-learning: save human-corrected reply into FTS5 SOP."""
        self._require("status")
        raw_in = re.sub(r"\s+", " ", str(incoming_text or "")).strip()
        raw_in = re.sub(r"^(?!https?:)[^:\s/\n]{1,16}:\s+", "", raw_in).strip()
        raw_reply = re.sub(r"\s+", " ", str(corrected_reply or "")).strip()
        if not raw_in or not raw_reply:
            return {"ok": False, "error": "incoming_text and corrected_reply are required."}
        clean_kind = str(kind or "script").strip().lower()
        if clean_kind not in ("terminology", "knowledge", "script", "faq"):
            clean_kind = "script"

        clean_reply = self.personas.sanitize_for_customer(raw_reply, max_len=240)
        if not clean_reply:
            return {"ok": False, "error": "Corrected reply became empty after sanitization."}

        clean_title = re.sub(r"\s+", " ", str(title or "")).strip()[:40] or f"纠偏SOP：{raw_in[:24]}"
        extracted_kw: List[str] = [str(k).strip() for k in (keywords or []) if str(k).strip()]
        if not extracted_kw:
            if len(raw_in) <= 28:
                extracted_kw.append(raw_in)
            for tok in re.findall(r"[A-Za-z0-9_.-]{2,20}|[\u4e00-\u9fff]{2,8}", raw_in):
                if tok not in extracted_kw and len(extracted_kw) < 8:
                    extracted_kw.append(tok)
        synonyms = [raw_in[:32]] if raw_in else []

        try:
            saved = self.knowledge.save_entry(
                title=clean_title,
                body=clean_reply,
                kind=clean_kind,
                library="shared",
                keywords=extracted_kw[:8],
                synonyms=synonyms,
                source="workos-self-learn",
                external=True,
                status="published",
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        entry = saved.get("entry") or {}
        evo_item = {
            "id": entry.get("id") or f"evo_{int(time.time() * 1000)}",
            "entryId": entry.get("id"),
            "target": str(target or "").strip(),
            "title": clean_title,
            "incomingText": raw_in[:120],
            "correctedReply": clean_reply[:180],
            "originalDraft": re.sub(r"\s+", " ", str(original_draft or "")).strip()[:120],
            "keywords": extracted_kw[:6],
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        with self._workos_lock:
            evos = list(self._workos_state.get("evolutions") or [])
            evos.append(evo_item)
            self._workos_state["evolutions"] = evos[-50:]
            refs = list(self._workos_state.get("reflections") or [])
            self._workos_state["reflections"] = [
                r for r in refs if r.get("incomingText") != raw_in[:160]
            ]
            self._save_workos_state()
            evo_count = len(self._workos_state["evolutions"])

        self.audit.log("workos_learn_correction", "ok", {
            "entryId": entry.get("id"),
            "target": target,
            "title": clean_title,
        })
        return {"ok": True, "entry": entry, "evolution": evo_item, "evolutionCount": evo_count}

    def get_workos_harness_summary(self) -> Dict[str, Any]:
        """Return Yingdao AI WorkOS 4-pillar Harness summary (Governance, Evaluation, Reflection, Evolution)."""
        self._require("status")
        with self._workos_lock:
            state = dict(self._workos_state)
            reflections = list(reversed(state.get("reflections") or []))
            evolutions = list(reversed(state.get("evolutions") or []))

        bound_targets = [str(b.get("target") or "").strip() for b in self.bindings.list_bindings() if str(b.get("target") or "").strip()]
        hosting = self.hosting_manager.status()
        allowed_targets = (
            self.allowlist.list_allowed()
            if self.allowlist.enabled
            else (list(hosting.get("targets") or []) or bound_targets)
        )
        kb_list = self.knowledge.list_entries(include_drafts=False, limit=5000)
        kb_entries = kb_list.get("entries") or []
        self_learned_entries = [e for e in kb_entries if e.get("source") == "workos-self-learn"]
        doc_ingested_entries = [e for e in kb_entries if e.get("source") == "doc-ingest"]
        bound_window = self.get_bound_app_window() if hasattr(self, "app_window_binder") else {}

        bench_metrics: Dict[str, Any] = {}
        try:
            rep = self.benchmark_suite.get_latest_report() or {}
            latest = rep.get("latest") if isinstance(rep.get("latest"), dict) else rep
            if isinstance(latest, dict) and latest.get("totalCases"):
                bench_metrics = {
                    "totalCases": latest.get("totalCases"),
                    "passed": latest.get("passed"),
                    "passRate": latest.get("passRate"),
                    "jargonLeaks": latest.get("jargonLeaks"),
                    "generatedAt": latest.get("generatedAt"),
                }
        except Exception:
            pass

        hg_raw = getattr(self.human_guard, "_state", {}) or {}
        human_guard_summary = {
            "enabled": bool(hg_raw.get("enabled", True)),
            "status": str(hg_raw.get("status") or "idle_ready"),
            "idleResumeSeconds": float(hg_raw.get("idle_resume_seconds", 45.0)),
            "cooldownSeconds": float(hg_raw.get("cooldown_seconds", 45.0)),
            "interventionsDetected": int(hg_raw.get("interventions_detected") or 0),
        }

        return {
            "ok": True,
            "governance": {
                "allowedTargets": allowed_targets,
                "hostingRunning": bool(hosting.get("running")),
                "sendMode": hosting.get("sendMode"),
                "humanGuard": human_guard_summary,
                "antiban": self.antiban.status(),
                "speedMode": state.get("speedMode", "fast"),
                "postPreset": state.get("postPreset", "private_ops"),
                "postLabel": state.get("postLabel", WORKOS_POST_PRESETS["private_ops"]["label"]),
                "taskGoal": state.get("taskGoal", WORKOS_POST_PRESETS["private_ops"]["goal"]),
                "boundWindow": bound_window,
            },
            "evaluation": {
                "knowledgeEntriesCount": int(kb_list.get("count") or len(kb_entries)),
                "selfLearnedCount": len(self_learned_entries),
                "docIngestedCount": len(doc_ingested_entries),
                "benchmark": bench_metrics,
            },
            "reflection": {
                "pendingCount": len(reflections),
                "items": reflections[:15],
            },
            "evolution": {
                "totalCount": len(evolutions),
                "items": evolutions[:20],
            },
            "scheduler": {
                "dhash": self.multi_scheduler.dhash_filter.stats(),
                "coalescer": self.multi_scheduler.coalescer.stats(),
                "priorityQueue": self.multi_scheduler.priority_scheduler.stats(),
                "lanes": dict(self.multi_scheduler.last_lanes),
                "lastRound": self.multi_scheduler.last_round,
            },
            "borderOverlay": self.get_border_overlay_status(refresh_windows=False),
            "coevolution": self.coevolution.get_summary(),
            "presets": WORKOS_POST_PRESETS,
        }

    # ------------------------------------------------------------------
    # Dual-App Window Binding (WeChat + WeCom) & Document Ingestion (v2.4.70)
    # ------------------------------------------------------------------

    def get_bound_app_window(self) -> Dict[str, Any]:
        """Return currently persisted WeChat / WeCom / auto window binding."""
        binding = self.app_window_binder.get_binding()
        return {"ok": True, **binding}

    def list_app_windows(self, app: str = "all") -> Dict[str, Any]:
        """Scan visible desktop windows for WeChat (`wechat`) and WeCom (`wecom`)."""
        self._require("status")
        clean_app = str(app or "all").strip().lower()
        if clean_app not in ("all", "wechat", "wecom", "auto"):
            return {
                "ok": False,
                "error_code": "unsupported_app",
                "error": f"Unsupported app filter {app!r}. Expected all, wechat, wecom, or auto.",
                "windows": [],
                "boundWindow": self.app_window_binder.get_binding(),
            }
        res = self._run_native(["list-app-windows", "--app", clean_app], timeout=12.0)
        bound = self.app_window_binder.get_binding()
        if not isinstance(res, dict):
            res = {"ok": False, "error": "Invalid native response", "windows": [], "apps": []}
        res.setdefault("windows", [])
        res.setdefault("apps", [])
        allowed_targets = self._collect_effective_allowed_targets()
        enriched_windows: List[Dict[str, Any]] = []
        for win in res.get("windows") or []:
            if not isinstance(win, dict):
                continue
            item = dict(win)
            is_main = bool(item.get("isMainWindow"))
            title = str(item.get("title") or "").strip()
            item["isPopout"] = not is_main
            item["isAllowlistedTarget"] = bool(
                not is_main
                and title
                and any(_matches_target(title, t) for t in allowed_targets)
            )
            enriched_windows.append(item)
        res["windows"] = enriched_windows
        res["boundWindow"] = bound
        return res

    def bind_app_window(
        self,
        app_id: str = "auto",
        window_id: Optional[int] = None,
        window_title: str = "",
        *,
        app_label: Optional[str] = None,
        follow_up_isolation: bool = True,
    ) -> Dict[str, Any]:
        """Bind active target window (`wechat` | `wecom` | `auto`) without loosening contact allowlists."""
        self._require("status")
        try:
            binding = self.app_window_binder.bind(
                app_id,
                window_id=window_id,
                window_title=window_title,
                app_label=app_label,
                follow_up_isolation=follow_up_isolation,
            )
        except ValueError as exc:
            return {"ok": False, "error_code": "unsupported_app", "error": str(exc)}
        self.audit.log(
            "workos_bind_window",
            "ok",
            {
                "appId": binding.get("appId"),
                "windowID": binding.get("windowID"),
                "windowTitle": binding.get("windowTitle"),
                "followUpIsolation": binding.get("followUpIsolation"),
            },
        )
        return {"ok": True, "binding": binding, **binding}

    def preview_doc_ingest(
        self,
        *,
        raw_text: str = "",
        file_path: Optional[str] = None,
        file_bytes_b64: Optional[str] = None,
        filename: str = "",
        instruction: str = "希望你能够替代我去和顾客聊天",
        doc_name: str = "",
        use_llm: Optional[bool] = None,
        max_pages: int = 12,
    ) -> Dict[str, Any]:
        """Extract & structure an uploaded PDF/Markdown/Text/JSON product doc into KB drafts."""
        self._require("status")
        return self.doc_ingestor.preview(
            raw_text=raw_text,
            file_path=file_path,
            file_bytes_b64=file_bytes_b64,
            filename=filename,
            instruction=instruction,
            doc_name=doc_name,
            use_llm=use_llm,
            max_pages=max_pages,
        )

    def confirm_doc_ingest(
        self,
        *,
        items: List[Dict[str, Any]],
        strategy: str = "bind_kb",
        doc_name: str = "",
        apply_prompt_target: bool = False,
        instruction: str = "",
    ) -> Dict[str, Any]:
        """Commit confirmed document knowledge drafts to shared FTS5 KB (and optionally taskGoal)."""
        self._require("status")
        return self.doc_ingestor.confirm(
            items=items,
            strategy=strategy,
            doc_name=doc_name,
            apply_prompt_target=apply_prompt_target,
            instruction=instruction,
        )

    # ------------------------------------------------------------------
    # Multi-Window Concurrent Scheduler & Zero-Risk Border Overlay (v2.4.71)
    # ------------------------------------------------------------------

    def _collect_effective_allowed_targets(self) -> List[str]:
        """Collect allowlisted contacts dynamically combined with active watched/hosted targets."""
        if getattr(self.allowlist, "enabled", False):
            return list(self.allowlist.list_allowed())
        merged: List[str] = []
        seen: set[str] = set()

        def _push(raw: Any) -> None:
            clean = str(raw or "").strip()
            if not clean or _is_bogus_ocr_target(clean):
                return
            key = normalize_chat_name(clean).casefold()
            if key in seen:
                return
            seen.add(key)
            merged.append(clean)

        for item in ALLOWED_TEST_CONTACTS:
            _push(item)
        try:
            hosting_targets = self.hosting_manager.status().get("targets") or []
        except Exception:
            hosting_targets = []
        for item in hosting_targets:
            _push(item)
        for b in self.bindings.list_bindings():
            if bool(b.get("autoReplyEnabled", True)):
                _push(b.get("target"))
        return merged

    def open_watched_popout_windows(self, targets: Optional[List[str]] = None) -> Dict[str, Any]:
        """Open independent WeChat/WeCom pop-out windows for allowed watched contacts."""
        self._require("status")
        if targets:
            requested = [str(t).strip() for t in targets if str(t).strip()]
        else:
            requested = list(self.list_watched_contacts().get("watchedTargets") or [])
        allowed_targets = self._collect_effective_allowed_targets()

        for req in requested:
            if not any(_matches_target(req, allowed) for allowed in allowed_targets):
                return {
                    "ok": False,
                    "error_code": "target_not_allowed",
                    "target": req,
                    "allowedTargets": allowed_targets,
                    "error": f"Refusing to open pop-out window for non-allowlisted target {req!r}.",
                }

        results: List[Dict[str, Any]] = []
        opened_count = 0
        already_count = 0
        not_found: List[str] = []
        for req in requested:
            try:
                res = self.inspector.open_popout_window(req)
            except Exception as exc:
                res = {"ok": False, "target": req, "error_code": "popout_error", "error": str(exc)}
            results.append(res)
            if res.get("ok"):
                if res.get("alreadyPopout"):
                    already_count += 1
                elif res.get("opened"):
                    opened_count += 1
            elif res.get("error_code") == "target_not_found":
                not_found.append(req)
        self.audit.log(
            "open_watched_popout_windows",
            "ok",
            {
                "requestedCount": len(requested),
                "openedCount": opened_count,
                "alreadyPopoutCount": already_count,
                "notFoundCount": len(not_found),
            },
        )
        return {
            "ok": True,
            "requestedTargets": requested,
            "openedCount": opened_count,
            "alreadyPopoutCount": already_count,
            "notFoundTargets": not_found,
            "results": results,
            "popoutWindows": self.inspector.list_popout_windows(app="all"),
        }

    def _resolve_scheduler_allowed_targets(self) -> List[str]:
        return self._collect_effective_allowed_targets()

    @staticmethod
    def _normalize_overlay_state(state: Optional[str]) -> str:
        raw = str(state or "idle").strip().lower()
        if raw in ("idle", "guard", "guarding", "active"):
            return "idle"
        if raw in ("thinking", "think", "busy"):
            return "thinking"
        if raw in ("human_paused", "paused", "human_guard", "pause", "yield"):
            return "human_paused"
        raise ValueError(
            f"Unsupported border overlay state {state!r}. Expected idle, thinking, or human_paused."
        )

    def _effective_overlay_state(self, configured_state: str) -> str:
        eff = configured_state if configured_state in BORDER_OVERLAY_COLORS else "idle"
        if eff == "idle":
            hg_raw = getattr(self.human_guard, "_state", {}) or {}
            if str(hg_raw.get("status") or "").lower() in ("cooldown", "paused", "intervened"):
                return "human_paused"
        return eff

    def get_border_overlay_status(self, *, refresh_windows: bool = True) -> Dict[str, Any]:
        """Return border-overlay status and active allowlisted popout window frames."""
        with self._workos_lock:
            bo = dict(self._workos_state.get("borderOverlay") or {})
        enabled = bool(bo.get("enabled", False))
        eff_state = self._effective_overlay_state(str(bo.get("modeColorState") or "idle"))
        color_hex = BORDER_OVERLAY_COLORS[eff_state]
        active_windows: List[Dict[str, Any]] = []

        if enabled and refresh_windows:
            scan_ok = False
            windows: List[Dict[str, Any]] = []
            try:
                scan = self._run_native(["list-app-windows", "--app", "all"], timeout=6.0)
                if isinstance(scan, dict) and scan.get("ok") and isinstance(scan.get("windows"), list):
                    scan_ok = True
                    windows = scan["windows"]
            except Exception:
                scan_ok = False
            if scan_ok:
                allowed_targets = self._resolve_scheduler_allowed_targets()
                lanes = self.multi_scheduler.coordinator.plan_lanes(allowed_targets, windows)
                popouts = lanes.get("fastLanePopouts") or []
            else:
                popouts = list(self.multi_scheduler.last_lanes.get("fastLanePopouts") or [])
            for pop in popouts:
                wid = int(pop.get("windowID") or 0)
                if wid <= 0:
                    continue
                active_windows.append({
                    "windowID": wid,
                    "title": str(pop.get("title") or pop.get("target") or ""),
                    "appId": str(pop.get("appId") or "wechat"),
                    "state": eff_state,
                    "color": color_hex,
                    "bounds": pop.get("bounds") or {},
                })
            with self._workos_lock:
                self._workos_state["borderOverlay"]["activePopoutWindowIDs"] = [w["windowID"] for w in active_windows]
                self.border_overlay_state = self._workos_state["borderOverlay"]
        elif enabled:
            cached_popouts = {
                int(p.get("windowID") or 0): p
                for p in (self.multi_scheduler.last_lanes.get("fastLanePopouts") or [])
                if int(p.get("windowID") or 0) > 0
            }
            for wid in bo.get("activePopoutWindowIDs") or []:
                try:
                    w_int = int(wid)
                except (TypeError, ValueError):
                    continue
                if w_int > 0:
                    cached = cached_popouts.get(w_int) or {}
                    active_windows.append({
                        "windowID": w_int,
                        "title": str(cached.get("title") or cached.get("target") or ""),
                        "appId": str(cached.get("appId") or "wechat"),
                        "state": eff_state,
                        "color": color_hex,
                        "bounds": cached.get("bounds") or {},
                    })

        return {
            "ok": True,
            "enabled": enabled,
            "state": eff_state,
            "modeColorState": eff_state,
            "color": color_hex,
            "activePopoutWindowIDs": [w["windowID"] for w in active_windows],
            "activeWindows": active_windows,
            "updatedAt": str(bo.get("lastUpdatedAt") or datetime.now(timezone.utc).isoformat()),
        }

    def configure_border_overlay(
        self,
        *,
        enabled: Optional[bool] = None,
        state: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enable/disable or switch color state of the zero-risk popout border overlay."""
        self._require("status")
        with self._workos_lock:
            bo = dict(self._workos_state.get("borderOverlay") or {})
            if enabled is not None:
                bo["enabled"] = bool(enabled)
            if state is not None:
                try:
                    bo["modeColorState"] = self._normalize_overlay_state(state)
                except ValueError as exc:
                    return {"ok": False, "error_code": "invalid_overlay_state", "error": str(exc)}
            bo["lastUpdatedAt"] = datetime.now(timezone.utc).isoformat()
            self._workos_state["borderOverlay"] = bo
            self.border_overlay_state = self._workos_state["borderOverlay"]
            self._save_workos_state()

        status_doc = self.get_border_overlay_status(refresh_windows=bool(bo.get("enabled")))
        with self._workos_lock:
            self._save_workos_state()
        self.audit.log(
            "workos_border_overlay",
            "ok",
            {
                "enabled": status_doc["enabled"],
                "modeColorState": status_doc["modeColorState"],
                "activeCount": len(status_doc["activeWindows"]),
            },
        )
        return status_doc

    def get_scheduler_status(self) -> Dict[str, Any]:
        """Return multi-window scheduler metrics, two-tier lanes, and border overlay state."""
        self._require("status")
        allowed_targets = self._resolve_scheduler_allowed_targets()
        return {
            "ok": True,
            "allowedTargets": allowed_targets,
            "dhash": self.multi_scheduler.dhash_filter.stats(),
            "coalescer": self.multi_scheduler.coalescer.stats(),
            "priorityQueue": self.multi_scheduler.priority_scheduler.stats(),
            "lanes": dict(self.multi_scheduler.last_lanes),
            "lastRound": self.multi_scheduler.last_round,
            "borderOverlay": self.get_border_overlay_status(refresh_windows=False),
        }

    def run_multi_window_schedule_round(
        self,
        *,
        auto_think: bool = False,
        dry_run: bool = True,
        app: str = "all",
        dhash_threshold: int = 4,
    ) -> Dict[str, Any]:
        """Execute one diagnostic/scheduling round across two-tier windows + dHash + aging heap."""
        self._require("status")
        t0 = time.perf_counter()
        clean_app = str(app or "all").strip().lower()
        if clean_app not in ("all", "wechat", "wecom", "auto"):
            return {
                "ok": False,
                "error_code": "unsupported_app",
                "error": f"Unsupported app filter {app!r}.",
            }

        native_res = self._run_native(["dhash-windows", "--app", clean_app], timeout=12.0)
        scan_source = "dhash-windows"
        if not isinstance(native_res, dict) or not native_res.get("ok") or not isinstance(native_res.get("windows"), list):
            native_res = self.list_app_windows(app=clean_app)
            scan_source = "list-app-windows"
            if not isinstance(native_res, dict) or not native_res.get("ok"):
                return {
                    "ok": False,
                    "error_code": (native_res or {}).get("error_code") or "window_scan_failed",
                    "error": (native_res or {}).get("error") or "Failed to scan windows",
                }

        windows = list(native_res.get("windows") or [])
        allowed_targets = self._resolve_scheduler_allowed_targets()
        lanes = self.multi_scheduler.coordinator.plan_lanes(allowed_targets, windows)
        self.multi_scheduler.last_lanes = lanes

        dhash_decisions: List[Dict[str, Any]] = []
        candidate_tasks: List[Dict[str, Any]] = []
        for pop in lanes["fastLanePopouts"]:
            wid = int(pop.get("windowID") or 0)
            dhash_hex = str(pop.get("dHash64") or "")
            should_ocr, dist = self.multi_scheduler.dhash_filter.should_run_ocr(
                wid,
                dhash_hex,
                threshold=dhash_threshold,
            )
            pop["shouldRunOcr"] = should_ocr
            pop["dhashDistance"] = dist
            dhash_decisions.append({
                "windowID": wid,
                "target": pop["target"],
                "dHash64": dhash_hex,
                "distance": dist,
                "shouldRunOcr": should_ocr,
            })
            binding = self.bindings.get_binding(pop["target"]) or {}
            care_level = str(binding.get("careLevel") or ("special_care" if binding.get("specialCare") else "normal"))
            care_weight = 2.0 if care_level == "special_care" else (1.0 if care_level == "vip" else 0.5)
            candidate_tasks.append({
                "target": pop["target"],
                "windowID": wid,
                "isPopout": True,
                "careWeight": care_weight,
                "urgency": 1.0 if should_ocr else 0.2,
                "waitSeconds": 0.0,
                "shouldRunOcr": should_ocr,
                "priorityScore": self.multi_scheduler.priority_scheduler.compute_priority_score(
                    urgency=1.0 if should_ocr else 0.2,
                    care_weight=care_weight,
                    is_popout=True,
                    wait_seconds=0.0,
                ),
            })

        for fb_target in lanes["mainWindowFallbackTargets"]:
            binding = self.bindings.get_binding(fb_target) or {}
            care_level = str(binding.get("careLevel") or ("special_care" if binding.get("specialCare") else "normal"))
            care_weight = 2.0 if care_level == "special_care" else (1.0 if care_level == "vip" else 0.5)
            candidate_tasks.append({
                "target": fb_target,
                "windowID": None,
                "isPopout": False,
                "careWeight": care_weight,
                "urgency": 0.5,
                "waitSeconds": 0.0,
                "shouldRunOcr": True,
                "priorityScore": self.multi_scheduler.priority_scheduler.compute_priority_score(
                    urgency=0.5,
                    care_weight=care_weight,
                    is_popout=False,
                    wait_seconds=0.0,
                ),
            })

        candidate_tasks.sort(key=lambda t: (-float(t["priorityScore"]), t["target"]))
        ready_bursts = self.multi_scheduler.coalescer.drain_ready()

        dispatch_report: Optional[Dict[str, Any]] = None
        if auto_think and candidate_tasks:
            with self._workos_lock:
                prev_state = str((self._workos_state.get("borderOverlay") or {}).get("modeColorState") or "idle")
                if (self._workos_state.get("borderOverlay") or {}).get("enabled"):
                    self._workos_state["borderOverlay"]["modeColorState"] = "thinking"

            def _diagnostic_think(task: Dict[str, Any]) -> Dict[str, Any]:
                res = self.preview_smart_reply(
                    task["target"],
                    "在吗",
                    use_llm=False,
                )
                return {
                    "ok": bool(res.get("ok")),
                    "replyText": res.get("replyText", ""),
                    "dryRun": bool(dry_run),
                }

            try:
                dispatch_report = self.multi_scheduler.priority_scheduler.dispatch_concurrent_replies(
                    candidate_tasks,
                    think_fn=_diagnostic_think,
                    send_fn=None,
                    max_workers=5,
                )
            finally:
                with self._workos_lock:
                    if (self._workos_state.get("borderOverlay") or {}).get("enabled"):
                        self._workos_state["borderOverlay"]["modeColorState"] = prev_state

        with self._workos_lock:
            bo = dict(self._workos_state.get("borderOverlay") or {})
            bo["activePopoutWindowIDs"] = [w["windowID"] for w in lanes["fastLanePopouts"] if w.get("windowID")]
            bo["lastUpdatedAt"] = datetime.now(timezone.utc).isoformat()
            self._workos_state["borderOverlay"] = bo
            self.border_overlay_state = self._workos_state["borderOverlay"]
            self._save_workos_state()

        round_doc = {
            "ok": True,
            "scanSource": scan_source,
            "dryRun": bool(dry_run),
            "autoThink": bool(auto_think),
            "elapsedMs": round((time.perf_counter() - t0) * 1000.0, 2),
            "allowedTargets": allowed_targets,
            "fastLanePopouts": lanes["fastLanePopouts"],
            "mainWindowFallbackTargets": lanes["mainWindowFallbackTargets"],
            "protectedReadOnlyPopouts": lanes["protectedReadOnlyPopouts"],
            "mainWindows": lanes["mainWindows"],
            "dhashDecisions": dhash_decisions,
            "dhash": self.multi_scheduler.dhash_filter.stats(),
            "coalescer": self.multi_scheduler.coalescer.stats(),
            "readyBursts": ready_bursts,
            "priorityQueue": self.multi_scheduler.priority_scheduler.stats(),
            "priorityPlan": candidate_tasks,
            "dispatchReport": dispatch_report,
            "borderOverlay": self.get_border_overlay_status(refresh_windows=False),
        }
        self.multi_scheduler.last_round = {
            "scanSource": scan_source,
            "elapsedMs": round_doc["elapsedMs"],
            "fastLaneCount": len(lanes["fastLanePopouts"]),
            "fallbackCount": len(lanes["mainWindowFallbackTargets"]),
            "protectedCount": len(lanes["protectedReadOnlyPopouts"]),
            "ocrSkippedByDHash": round_doc["dhash"]["ocrSkippedByDHash"],
            "coalescedBursts": round_doc["coalescer"]["coalescedBursts"],
            "updatedAt": bo["lastUpdatedAt"],
        }
        self.audit.log("workos_scheduler_round", "ok", self.multi_scheduler.last_round)
        return round_doc

    # ------------------------------------------------------------------
    # Multi-Channel App-Use RPA + Open-Source Hybrid Hub (v2.5.0)
    # ------------------------------------------------------------------

    def omni_overview(self, *, probe_live: bool = False, channel: str = "all") -> Dict[str, Any]:
        return self.omni_hub.overview(probe_live=probe_live, channel=channel)

    def omni_probe(self, channel: str, *, launch_if_needed: bool = False, include_web: bool = True) -> Dict[str, Any]:
        return self.omni_hub.probe(channel, launch_if_needed=launch_if_needed, include_web=include_web)

    def omni_list_sessions(
        self,
        channel: str,
        *,
        limit: int = 20,
        query: str = "",
        launch_if_needed: bool = False,
    ) -> Dict[str, Any]:
        self._require("read_sessions")
        return self.omni_hub.list_sessions(channel, limit=limit, query=query, launch_if_needed=launch_if_needed)

    def omni_read_messages(
        self,
        channel: str,
        *,
        target: str = "",
        limit: int = 20,
        launch_if_needed: bool = False,
    ) -> Dict[str, Any]:
        self._require("read_messages")
        return self.omni_hub.read_messages(channel, target=target, limit=limit, launch_if_needed=launch_if_needed)

    def omni_send(
        self,
        channel: str,
        target: str,
        text: str,
        *,
        mode: str = "auto",
        dry_run: bool = True,
        confirm_send: bool = False,
    ) -> Dict[str, Any]:
        will_live = (not dry_run) and bool(confirm_send)
        self._require("send_text_live" if will_live else "send_text_dry_run")
        return self.omni_hub.send_message(
            channel,
            target,
            text,
            mode=mode,
            dry_run=dry_run,
            confirm_send=confirm_send,
        )

    def omni_extract_leads(
        self,
        channel: str,
        *,
        target: str = "",
        query: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        sync_crm: bool = True,
    ) -> Dict[str, Any]:
        self._require("read_messages")
        return self.omni_hub.extract_leads(
            channel,
            target=target,
            query=query,
            messages=messages,
            sync_crm=sync_crm,
        )

    def omni_update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        self._require("status")
        return self.omni_hub.update_config(updates)

    def omni_finish_browser_space(self) -> Dict[str, Any]:
        return self.omni_hub.finish_browser_space()

    def omni_open_auth(
        self,
        channel: str,
        *,
        action_type: str = "auto",
        target_view: str = "home",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return self.omni_hub.open_auth_flow(
            channel,
            action_type=action_type,
            target_view=target_view,
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------
    # Universal App-Use & Any-Agent SOP / Workflow Studio (v2.6.0)
    # ------------------------------------------------------------------

    def app_use_list_apps(
        self,
        *,
        include_installed: bool = True,
        category: str = "all",
        running_only: bool = False,
    ) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.list_apps(
            include_installed=include_installed,
            category=category,
            running_only=running_only,
        )

    def app_use_list_agents(self, *, refresh_models: bool = False) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.list_builder_agents(refresh_models=refresh_models)

    def app_use_inspect_app(
        self,
        *,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
        window_id: Optional[int] = None,
        window_title: str = "",
        launch_if_needed: bool = False,
        allow_activate: bool = True,
        max_nodes: int = 350,
    ) -> Dict[str, Any]:
        self._require("ocr")
        return self.app_use.inspect_app(
            bundle_id=bundle_id,
            app_name=app_name,
            app_path=app_path,
            window_id=window_id,
            window_title=window_title,
            launch_if_needed=launch_if_needed,
            allow_activate=allow_activate,
            max_nodes=max_nodes,
        )

    def app_use_build_sop(
        self,
        goal: str,
        *,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
        agent_id: str = "",
        provider_id: Optional[str] = None,
        custom_agent_prompt: str = "",
        inspect_live: bool = True,
        launch_if_needed: bool = False,
        attach_screenshot: bool = False,
        save: bool = True,
        parameters_hint: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        res = self.app_use.build_sop_and_workflow(
            goal=goal,
            bundle_id=bundle_id,
            app_name=app_name,
            app_path=app_path,
            agent_id=agent_id,
            provider_id=provider_id,
            custom_agent_prompt=custom_agent_prompt,
            inspect_live=inspect_live,
            launch_if_needed=launch_if_needed,
            attach_screenshot=attach_screenshot,
            save=save,
            parameters_hint=parameters_hint,
        )
        if res.get("ok"):
            wf = res.get("workflow") or {}
            self.audit.log(
                "app_use_build_sop",
                "ok",
                {
                    "workflowId": wf.get("id"),
                    "bundleID": (wf.get("targetApp") or {}).get("bundleID"),
                    "agentId": (wf.get("builderAgent") or {}).get("agentId"),
                },
            )
        return res

    def app_use_list_workflows(self, *, bundle_id: Optional[str] = None) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.list_workflows(bundle_id=bundle_id)

    def app_use_save_workflow(self, workflow: Dict[str, Any], *, sop_markdown: str = "") -> Dict[str, Any]:
        self._require("status")
        return self.app_use.save_workflow(workflow, sop_markdown=sop_markdown)

    def app_use_delete_workflow(self, workflow_id: str) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.delete_workflow(workflow_id)

    def app_use_run_workflow(
        self,
        *,
        workflow_id: Optional[str] = None,
        workflow: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = True,
        confirm_run: bool = False,
        respect_human_guard: bool = True,
        self_heal: bool = True,
        auto_patch_workflow: bool = False,
        heal_agent_id: str = "",
        dispatch_mode: str = "auto",
    ) -> Dict[str, Any]:
        will_live = (not dry_run) and bool(confirm_run)
        self._require("send_text_live" if will_live else "send_text_dry_run")
        res = self.app_use.run_workflow(
            workflow_id=workflow_id,
            workflow=workflow,
            params=params,
            dry_run=dry_run,
            confirm_run=confirm_run,
            respect_human_guard=respect_human_guard,
            self_heal=self_heal,
            auto_patch_workflow=auto_patch_workflow,
            heal_agent_id=heal_agent_id,
            dispatch_mode=dispatch_mode,
        )
        self.audit.log(
            "app_use_run_workflow",
            "ok" if res.get("ok") else "error",
            {
                "workflowId": res.get("workflowId"),
                "dryRun": bool(dry_run),
                "stepsExecuted": res.get("stepsExecuted", 0),
                "healingCount": len(res.get("healingEvents") or []),
            },
        )
        return res

    def app_use_export_sop_to_kb(self, workflow_id: str) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.export_sop_to_kb(workflow_id)

    def app_use_rollback_workflow(self, workflow_id: str, *, revision_index: int = -1) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.rollback_workflow(workflow_id, revision_index=revision_index)

    def app_use_explore(
        self,
        *,
        goal: str,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
        agent_id: str = "",
        max_turns: int = 6,
        dry_run: bool = True,
        confirm_run: bool = False,
        respect_human_guard: bool = True,
        launch_if_needed: bool = True,
        save: bool = True,
    ) -> Dict[str, Any]:
        will_live = (not dry_run) and bool(confirm_run)
        self._require("send_text_live" if will_live else "send_text_dry_run")
        return self.app_use.explore_and_build_sop(
            goal=goal,
            bundle_id=bundle_id,
            app_name=app_name,
            app_path=app_path,
            agent_id=agent_id,
            max_turns=max_turns,
            dry_run=dry_run,
            confirm_run=confirm_run,
            respect_human_guard=respect_human_guard,
            launch_if_needed=launch_if_needed,
            save=save,
        )

    def app_use_list_pipelines(self) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.list_pipelines()

    def app_use_save_pipeline(self, pipeline: Dict[str, Any]) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.save_pipeline(pipeline)

    def app_use_delete_pipeline(self, pipeline_id: str) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.delete_pipeline(pipeline_id)

    def app_use_run_pipeline(
        self,
        *,
        pipeline_id: Optional[str] = None,
        pipeline: Optional[Dict[str, Any]] = None,
        initial_params: Optional[Dict[str, Any]] = None,
        dry_run: bool = True,
        confirm_run: bool = False,
        respect_human_guard: bool = True,
        self_heal: bool = True,
    ) -> Dict[str, Any]:
        will_live = (not dry_run) and bool(confirm_run)
        self._require("send_text_live" if will_live else "send_text_dry_run")
        return self.app_use.run_pipeline(
            pipeline_id=pipeline_id,
            pipeline=pipeline,
            initial_params=initial_params,
            dry_run=dry_run,
            confirm_run=confirm_run,
            respect_human_guard=respect_human_guard,
            self_heal=self_heal,
        )

    def app_use_recording_start(
        self,
        *,
        max_duration_sec: float = 180.0,
        poll_interval_sec: float = 0.45,
        target_bundle_id: str = "",
    ) -> Dict[str, Any]:
        self._require("ocr")
        return self.app_use.start_recording(
            max_duration_sec=max_duration_sec,
            poll_interval_sec=poll_interval_sec,
            target_bundle_id=target_bundle_id,
        )

    def app_use_recording_status(self) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.recording_status()

    def app_use_recording_stop_and_compile(
        self,
        *,
        goal_hint: str = "",
        agent_id: str = "",
        save: bool = True,
    ) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.stop_recording_and_compile(goal_hint=goal_hint, agent_id=agent_id, save=save)

    def app_use_list_runs(self, *, limit: int = 30) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.list_runs(limit=limit)

    def app_use_export_skill(self, workflow_id: str, *, out_dir: Optional[str] = None) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.export_workflow_as_skill(workflow_id, out_dir=out_dir)

    def app_use_generalize_app(
        self,
        *,
        goal: str,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
        agent_id: str = "",
        mode: str = "auto",
        max_turns: int = 4,
        launch_if_needed: bool = True,
        dry_run_verify: bool = True,
        export_skill: bool = True,
        save: bool = True,
        custom_agent_prompt: str = "",
    ) -> Dict[str, Any]:
        self._require("ocr")
        return self.app_use.generalize_new_app(
            goal=goal,
            bundle_id=bundle_id,
            app_name=app_name,
            app_path=app_path,
            agent_id=agent_id,
            mode=mode,
            max_turns=max_turns,
            launch_if_needed=launch_if_needed,
            dry_run_verify=dry_run_verify,
            export_skill=export_skill,
            save=save,
            custom_agent_prompt=custom_agent_prompt,
        )

    def app_use_get_state_graph(self, *, bundle_id: Optional[str] = None) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.get_state_graph(bundle_id=bundle_id)

    def app_use_install_meta_skill(
        self,
        *,
        install_global: bool = True,
        global_skills_root: Optional[Path] = None,
        symlink_roots: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.install_meta_skill(
            install_global=install_global,
            global_skills_root=global_skills_root,
            symlink_roots=symlink_roots,
        )

    def app_use_ground_preview(
        self,
        step: Dict[str, Any],
        *,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
    ) -> Dict[str, Any]:
        self._require("ocr")
        return self.app_use.preview_grounding(
            step,
            bundle_id=bundle_id,
            app_name=app_name,
            app_path=app_path,
        )

    def app_use_watch_parallel(
        self,
        targets: List[Dict[str, Any]],
        *,
        include_ocr: bool = False,
        max_workers: int = 4,
    ) -> Dict[str, Any]:
        self._require("ocr")
        return self.app_use.watch_windows_parallel(
            targets,
            include_ocr=include_ocr,
            max_workers=max_workers,
        )

    def app_use_run_parallel(
        self,
        jobs: List[Dict[str, Any]],
        *,
        dry_run: bool = True,
        confirm_run: bool = False,
        respect_human_guard: bool = True,
        self_heal: bool = True,
        max_workers: int = 4,
        dispatch_mode: str = "auto",
    ) -> Dict[str, Any]:
        self._require("ocr" if not dry_run else "status")
        return self.app_use.run_workflows_parallel(
            jobs,
            dry_run=dry_run,
            confirm_run=confirm_run,
            respect_human_guard=respect_human_guard,
            self_heal=self_heal,
            max_workers=max_workers,
            dispatch_mode=dispatch_mode,
        )

    def app_use_concurrency_status(self) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.get_concurrency_status()

    def app_use_risk_profile(
        self,
        *,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
    ) -> Dict[str, Any]:
        self._require("status")
        return self.app_use.get_app_risk_profile(
            bundle_id=bundle_id,
            app_name=app_name,
            app_path=app_path,
        )

    # ------------------------------------------------------------------
    # Zero-FDE Onboarding, Self-Training, Test Sandbox & Quality Loop (v3)
    # ------------------------------------------------------------------

    def _resolve_sales_packs_dir(self) -> Path:
        candidates = [
            self.bundle_root / "config_templates" / "sales_packs",
            self.plugin_root / "config_templates" / "sales_packs",
            Path(__file__).resolve().parent.parent / "config_templates" / "sales_packs",
        ]
        for cand in candidates:
            if cand.is_dir():
                return cand
        return candidates[0]

    def _resolve_user_guide_path(self) -> Path:
        candidates = [
            self.bundle_root / "docs" / "USER_GUIDE.md",
            self.plugin_root / "docs" / "USER_GUIDE.md",
            Path(__file__).resolve().parent.parent / "docs" / "USER_GUIDE.md",
        ]
        for cand in candidates:
            if cand.is_file():
                return cand
        return candidates[0]

    def _resolve_user_guide_html_path(self) -> Path:
        candidates = [
            self.bundle_root / "docs" / "user-guide.html",
            self.plugin_root / "docs" / "user-guide.html",
            Path(__file__).resolve().parent.parent / "docs" / "user-guide.html",
        ]
        for cand in candidates:
            if cand.is_file():
                return cand
        return candidates[0]

    def list_available_sales_packs(self) -> List[Dict[str, Any]]:
        packs_dir = self._resolve_sales_packs_dir()
        return list_sales_packs(packs_dir)

    def get_onboarding_status(self) -> Dict[str, Any]:
        profile = self.tenant.get_profile()
        kb_pub = self.knowledge.list_entries(include_drafts=False, limit=1000)
        kb_all = self.knowledge.list_entries(include_drafts=True, limit=1000)
        return {
            "ok": True,
            "profile": profile,
            "isCustomerMode": self.tenant.is_customer_mode(),
            "onboardingCompleted": bool(profile.get("onboardingCompleted")),
            "salesPacks": self.list_available_sales_packs(),
            "publishedKnowledgeCount": int(kb_pub.get("count") or 0),
            "totalKnowledgeCount": int(kb_all.get("count") or 0),
            "testContacts": self.supervisor_eval.list_test_contacts(),
        }

    def setup_tenant_onboarding(
        self,
        owner_name: Optional[str] = None,
        *,
        business_name: Optional[str] = None,
        product_summary: Optional[str] = None,
        industry_pack: Optional[str] = None,
        owner_aliases: Optional[Iterable[str]] = None,
        admin_contacts: Optional[Iterable[str]] = None,
        test_contacts: Optional[Iterable[str]] = None,
        apply_pack: bool = True,
        withdraw_legacy_seeds: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        profile = self.tenant.complete_onboarding(
            owner_name=owner_name,
            business_name=business_name,
            product_summary=product_summary,
            industry_pack=industry_pack,
            owner_aliases=owner_aliases,
            admin_contacts=admin_contacts,
            test_contacts=test_contacts,
            **kwargs,
        )
        self.soul_profiler.set_tenant_context(tenant_mode="customer", owner_config=profile)

        pack_applied: Optional[Dict[str, Any]] = None
        if apply_pack:
            packs_dir = self._resolve_sales_packs_dir()
            pack_id = str(profile.get("industryPack") or DEFAULT_INDUSTRY_PACK).strip() or DEFAULT_INDUSTRY_PACK
            try:
                pack_data = load_sales_pack(pack_id, packs_dir)
                pack_applied = self.knowledge.apply_sales_pack(
                    pack_data,
                    withdraw_legacy_seeds=withdraw_legacy_seeds,
                )
            except FileNotFoundError:
                if withdraw_legacy_seeds:
                    pack_applied = self.knowledge.withdraw_legacy_seeds()
        elif withdraw_legacy_seeds:
            pack_applied = self.knowledge.withdraw_legacy_seeds()

        summary_text = str(profile.get("productSummary") or "").strip()
        biz_text = str(profile.get("businessName") or "").strip()
        if summary_text:
            title = f"{biz_text} · 业务与产品简介" if biz_text else "业务与产品简介"
            try:
                self.knowledge.save_entry(
                    title=title,
                    body=summary_text,
                    kind="knowledge",
                    library="shared",
                    keywords=[k for k in (biz_text, profile.get("ownerName"), "产品介绍", "业务介绍") if k],
                    source="tenant-onboarding",
                    external=True,
                    status="published",
                )
            except Exception:
                pass

        for tc in profile.get("testContacts") or []:
            if str(tc or "").strip():
                self.supervisor_eval.mark_test_contact(str(tc).strip(), note="onboarding")

        return {
            "ok": True,
            "profile": profile,
            "isCustomerMode": self.tenant.is_customer_mode(),
            "salesPackApplied": pack_applied,
            "testContacts": self.supervisor_eval.list_test_contacts(),
        }

    def discover_training_corpus(
        self,
        *,
        search_dirs: Optional[Iterable[Path | str]] = None,
        limit: int = 20,
        include_live_sessions: bool = True,
    ) -> Dict[str, Any]:
        sessions_input: Any = []
        if include_live_sessions:
            mgmt_path = self.inspector.reports_dir / "wechat_management_report.json"
            if mgmt_path.is_file():
                try:
                    sessions_input = json.loads(mgmt_path.read_text(encoding="utf-8"))
                except Exception:
                    sessions_input = []
            if not sessions_input:
                try:
                    sessions_input = self.inspector.list_sessions()
                except Exception:
                    sessions_input = []
        test_names = [c["displayName"] for c in self.supervisor_eval.list_test_contacts()]
        sessions = self.corpus_discovery.discover_wechat_sessions(
            sessions_input,
            histories_dir=self.inspector.reports_dir / "contacts",
            test_contacts=test_names,
            limit=limit,
        )
        archives = self.corpus_discovery.scan_archive_directories(search_dirs=search_dirs)
        return {
            "ok": True,
            "sessions": sessions,
            "archives": archives,
            "sessionCount": len(sessions),
            "archiveCount": len(archives),
        }

    def _load_conversations_for_contacts(self, targets: Iterable[str]) -> List[Dict[str, Any]]:
        histories_dir = self.inspector.reports_dir / "contacts"
        if not histories_dir.is_dir():
            return []
        wanted = {normalize_chat_name(str(t)).casefold() for t in targets if str(t).strip()}
        if not wanted:
            return []
        convs: List[Dict[str, Any]] = []
        for hp in sorted(histories_dir.glob("*_history.json")):
            try:
                doc = json.loads(hp.read_text(encoding="utf-8"))
            except Exception:
                continue
            cname = str(doc.get("matchedTitle") or doc.get("target") or "").strip()
            if not cname:
                continue
            if normalize_chat_name(cname).casefold() not in wanted:
                continue
            records = [
                {
                    "direction": str(r.get("direction") or "peer"),
                    "text": str(r.get("text") or ""),
                    "timestamp": str(r.get("timeMarker") or r.get("ts") or ""),
                }
                for r in (doc.get("records") or [])
                if isinstance(r, dict) and r.get("kind") != "timestamp" and str(r.get("text") or "").strip()
            ]
            if records:
                convs.append({"contact": cname, "sourcePaths": [str(hp)], "records": records})
        return convs

    def run_self_training(
        self,
        *,
        archive_paths: Optional[Iterable[Path | str]] = None,
        contact_targets: Optional[Iterable[str]] = None,
        raw_conversations: Optional[Sequence[Dict[str, Any]]] = None,
        doc_texts: Optional[Sequence[Dict[str, Any]]] = None,
        owner_name: Optional[str] = None,
        industry_pack: Optional[str] = None,
        use_llm: bool = False,
        auto_publish_safe: bool = True,
    ) -> Dict[str, Any]:
        profile = self.tenant.get_profile()
        resolved_owner = str(owner_name or profile.get("ownerName") or "").strip() or None
        aliases = list(profile.get("ownerAliases") or [])

        conversations: List[Dict[str, Any]] = []
        if raw_conversations:
            for item in raw_conversations:
                if isinstance(item, dict):
                    conversations.append(item)
        if archive_paths:
            conversations.extend(
                self.corpus_discovery.batch_import_archives(
                    archive_paths,
                    owner_name=resolved_owner,
                    known_aliases=aliases,
                )
            )
        if contact_targets:
            conversations.extend(self._load_conversations_for_contacts(contact_targets))

        pack_id = str(industry_pack or profile.get("industryPack") or DEFAULT_INDUSTRY_PACK).strip() or DEFAULT_INDUSTRY_PACK
        packs_dir = self._resolve_sales_packs_dir()
        try:
            sales_pack = load_sales_pack(pack_id, packs_dir)
        except Exception:
            sales_pack = {"packId": pack_id, "stages": [], "entries": []}

        report = self.playbook_trainer.train_from_corpora(
            conversations,
            sales_pack=sales_pack,
            knowledge_store=self.knowledge,
            model_hub=self.models if use_llm else None,
            use_llm=use_llm,
            auto_publish_safe=auto_publish_safe,
            report_path=self.inspector.reports_dir / "self_training_report.json",
        )

        # Optional product/FAQ doc texts submitted during wizard step 2
        doc_saved_entries: List[Dict[str, Any]] = []
        for doc_item in (doc_texts or ()):
            if isinstance(doc_item, str):
                raw_doc = doc_item.strip()
                doc_name = "产品资料"
            elif isinstance(doc_item, dict):
                raw_doc = str(doc_item.get("text") or doc_item.get("rawText") or "").strip()
                doc_name = str(doc_item.get("name") or doc_item.get("docName") or "产品资料").strip()
            else:
                continue
            if not raw_doc:
                continue
            redacted = self.playbook_trainer.redact_pii(raw_doc)
            saved = self.knowledge.save_entry(
                title=f"业务资料：{doc_name[:36]}",
                body=redacted[:2400],
                kind="knowledge",
                library="shared",
                keywords=[doc_name, "产品资料"],
                source="self-train-doc",
                external=True,
                status="published" if auto_publish_safe else "draft",
            )
            doc_saved_entries.append(saved["entry"])

        if doc_saved_entries:
            report["docEntries"] = doc_saved_entries
            report["publishedIds"] = list(report.get("publishedIds") or []) + [
                e["id"] for e in doc_saved_entries if e.get("status") == "published"
            ]
            report["draftIds"] = list(report.get("draftIds") or []) + [
                e["id"] for e in doc_saved_entries if e.get("status") != "published"
            ]
        return report

    def approve_training_drafts(
        self,
        entry_ids: Iterable[str],
        *,
        edits: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return self.playbook_trainer.approve_drafts(
            self.knowledge,
            entry_ids,
            edits=edits,
        )

    def set_test_contact(
        self,
        name: str,
        *,
        enabled: bool = True,
        note: str = "",
        auto_bind: bool = True,
    ) -> Dict[str, Any]:
        clean = str(name or "").strip()
        if not clean:
            raise ValueError("Test contact name cannot be empty.")
        if enabled:
            eval_res = self.supervisor_eval.mark_test_contact(clean, note=note)
            self.tenant.add_test_contact(clean)
            if auto_bind and self.bindings.get_binding(clean) is None:
                self.bindings.bind_contact(clean, role="test", auto_reply_enabled=True, notes=note or "内部测试好友")
            return {
                "ok": True,
                "enabled": True,
                "contact": eval_res,
                "testContacts": self.supervisor_eval.list_test_contacts(),
            }
        eval_res = self.supervisor_eval.unmark_test_contact(clean)
        self.tenant.remove_test_contact(clean)
        return {
            "ok": True,
            "enabled": False,
            "contact": eval_res,
            "testContacts": self.supervisor_eval.list_test_contacts(),
        }

    def list_test_contacts(self) -> Dict[str, Any]:
        contacts = self.supervisor_eval.list_test_contacts()
        return {
            "ok": True,
            "count": len(contacts),
            "contacts": contacts,
        }

    def _build_supervisor_reply_generator(self, *, use_llm: bool = False):
        def _gen(
            contact: str,
            trigger_text: str,
            *,
            directive: str = "",
            negative_constraints: Sequence[Dict[str, Any]] = (),
        ) -> str:
            binding = self.bindings.get_binding(contact)
            mem_ctx = dict(self.soul_profiler.get_contact_memory_context(contact) or {})
            entry_weights = self.supervisor_eval.get_entry_weights()
            mem_ctx["negativeConstraints"] = list(negative_constraints) if negative_constraints else self.supervisor_eval.match_negative_constraints(trigger_text, limit=4)
            mem_ctx["goldenExemplars"] = self.supervisor_eval.match_golden_exemplars(trigger_text, limit=2)
            mem_ctx["entryWeights"] = entry_weights
            if directive:
                mem_ctx["supervisorDirective"] = directive
            res = self.personas.generate_smart_reply(
                contact or "模拟测试客户",
                trigger_text,
                knowledge_store=self.knowledge,
                binding=binding,
                memory_context=mem_ctx,
                model_hub=self.models,
                use_llm=use_llm,
                entry_weights=entry_weights,
            )
            return str(res.get("replyText") or "")

        return _gen

    def sparring_simulate_turn(
        self,
        message: str,
        *,
        contact_name: str = "模拟测试客户",
        persona_id: Optional[str] = None,
        use_llm: Optional[bool] = None,
        model_id: Optional[str] = None,
        record: bool = True,
    ) -> Dict[str, Any]:
        clean_msg = str(message or "").strip()
        if not clean_msg:
            return {"ok": False, "error": "message cannot be empty."}
        target = str(contact_name or "模拟测试客户").strip() or "模拟测试客户"
        binding = self.bindings.get_binding(target)
        mem_ctx = dict(self.soul_profiler.get_contact_memory_context(target) or {})
        neg_constraints = self.supervisor_eval.match_negative_constraints(clean_msg, limit=3)
        golden_exemplars = self.supervisor_eval.match_golden_exemplars(clean_msg, limit=2)
        entry_weights = self.supervisor_eval.get_entry_weights()
        mem_ctx["negativeConstraints"] = neg_constraints
        mem_ctx["goldenExemplars"] = golden_exemplars
        mem_ctx["entryWeights"] = entry_weights

        res = self.personas.generate_smart_reply(
            target,
            clean_msg,
            knowledge_store=self.knowledge,
            binding=binding,
            persona_override=persona_id,
            memory_context=mem_ctx,
            model_hub=self.models,
            model_id=model_id,
            use_llm=use_llm,
            entry_weights=entry_weights,
        )
        reply_text = str(res.get("replyText") or "")
        matched_entries = res.get("matchedEntries") or []
        auto_score = self.supervisor_eval.auto_score_reply(
            clean_msg,
            reply_text,
            matched_entries=matched_entries,
            negative_constraints=neg_constraints,
        )
        res["autoScore"] = auto_score
        if int(auto_score.get("overallScore", 100)) < 70:
            res["needsHumanReview"] = True
            if not res.get("humanReviewReason"):
                res["humanReviewReason"] = "自动评分低于 70 分，建议人工复核"

        turn_id = None
        if record:
            matched_ids = [str(e.get("id")) for e in matched_entries if isinstance(e, dict) and e.get("id")]
            turn_rec = self.supervisor_eval.record_turn(
                target,
                clean_msg,
                reply_text,
                channel="sparring_sim",
                matched_entry_ids=matched_ids,
                auto_score=auto_score,
            )
            turn_id = turn_rec.get("turnId")
            res["turnId"] = turn_id

        return {
            **res,
            "contactName": target,
            "turnId": turn_id,
        }

    def handle_supervisor_hashtag(
        self,
        contact: str,
        raw_text: str,
        *,
        channel: str = "wechat",
        use_llm: bool = False,
    ) -> Dict[str, Any]:
        admin_contacts = tuple(self.tenant.get_profile().get("adminContacts") or ())
        reply_gen = self._build_supervisor_reply_generator(use_llm=use_llm)

        def _takeover_cb(target_name: str, action: str) -> Dict[str, Any]:
            if action in ("takeover", "pause"):
                return self.monitor.takeover_contact(target_name, reason=f"supervisor_hashtag:{action}")
            return self.monitor.resume_contact(target_name)

        return self.supervisor_eval.handle_hashtag_directive(
            contact,
            raw_text,
            channel=channel,
            admin_contacts=admin_contacts,
            knowledge_store=self.knowledge,
            reply_generator=reply_gen,
            takeover_cb=_takeover_cb,
        )

    def submit_reply_rating(
        self,
        turn_id: int,
        *,
        stars: int,
        tags: Iterable[str] = (),
        comment: str = "",
        rewritten_reply: str = "",
    ) -> Dict[str, Any]:
        return self.supervisor_eval.submit_rating(
            turn_id,
            stars=stars,
            tags=tags,
            comment=comment,
            rewritten_reply=rewritten_reply,
            knowledge_store=self.knowledge,
        )

    def get_quality_dashboard(self, *, days: int = 7) -> Dict[str, Any]:
        return self.supervisor_eval.get_quality_dashboard(days=days)

    def list_sparring_turns(
        self,
        *,
        contact_name: Optional[str] = None,
        limit: int = 30,
    ) -> Dict[str, Any]:
        limit_n = max(1, min(int(limit), 200))
        with self.supervisor_eval._lock, self.supervisor_eval._connect() as conn:
            if contact_name and str(contact_name).strip():
                norm = normalize_chat_name(str(contact_name).strip()) or str(contact_name).strip()
                rows = conn.execute(
                    "SELECT * FROM sparring_turns WHERE contact_name = ? ORDER BY id DESC LIMIT ?",
                    (norm, limit_n),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sparring_turns ORDER BY id DESC LIMIT ?",
                    (limit_n,),
                ).fetchall()
        turns = [self.supervisor_eval._turn_view(r) for r in rows]
        return {
            "ok": True,
            "count": len(turns),
            "turns": turns,
        }

    def run_sparring_regression(self, *, limit: int = 20, use_llm: bool = False) -> Dict[str, Any]:
        reply_gen = self._build_supervisor_reply_generator(use_llm=use_llm)
        return self.supervisor_eval.run_regression_suite(reply_gen, limit=limit)

    def get_user_guide_markdown(self) -> Dict[str, Any]:
        guide_path = self._resolve_user_guide_path()
        if not guide_path.is_file():
            return {"ok": False, "error": f"User guide not found at {guide_path}", "markdown": ""}
        content = guide_path.read_text(encoding="utf-8")
        return {
            "ok": True,
            "title": "WeChat Bot 使用者操作手册",
            "path": str(guide_path),
            "markdown": content,
        }

    def get_user_guide_html(self) -> Dict[str, Any]:
        """Load the standalone local web user guide HTML from bundle_root or plugin_root."""
        guide_path = self._resolve_user_guide_html_path()
        if not guide_path.is_file():
            return {
                "ok": False,
                "error": f"User guide HTML not found at {guide_path}",
                "path": str(guide_path),
                "html": "",
            }
        content = guide_path.read_text(encoding="utf-8")
        return {
            "ok": True,
            "title": "WeChat Bot 使用手册",
            "path": str(guide_path),
            "html": content,
        }
