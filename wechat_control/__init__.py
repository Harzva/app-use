"""OpenBot macOS WeChat RPA + OCR + WeChatBridge Unified Plugin Package."""

from __future__ import annotations

from .article_exporter import WeChatArticleExporter, WeChatArticleHTMLParser
from .auth_gate import (
    ALL_CAPABILITIES,
    DEFAULT_GRANT_CAPABILITIES,
    READ_ONLY_CAPABILITIES,
    StudioAuthGate,
    StudioPluginUnauthorizedError,
)
from .bridge_importer import (
    ArchiveAttachment,
    TranscriptBundle,
    TranscriptRecord,
    UnsafeArchiveError,
    WeChatBridgeImporter,
)
from .coevolution_engine import (
    DualProductCoevolutionEngine,
    evaluate_turn_human_likeness,
)
from .corpus_discovery import CorpusDiscoveryEngine
from .engine import WeChatControlEngine
from .human_activity_guard import HumanActivityGuard
from .humanizer_affect import (
    OFFICIAL_WECHAT_EMOJIS,
    EuphoriaAffectEngine,
    blend_persona_partitions,
    humanize_wechat_reply,
    normalize_wechat_emojis,
    parse_sibyl_feedback_command,
)
from .knowledge_kf_engine import PersonaSwitchEngine, WeChatKnowledgeStore
from .live_inspector import WeChatLiveInspector
from .magpie_provider_hub import MagpieProviderHub, map_magpie_model
from .mcp_server import WeChatMCPServer, create_http_server, serve_http
from .multi_window_scheduler import UnreadDeltaTracker
from .playbook_trainer import SelfTrainingPlaybookEngine
from .realtime_monitor import WeChatRealtimeMonitor
from .supervisor_eval import (
    SupervisorEvalEngine,
    is_blocked_outbound_directive,
    is_hashtag_directive,
    parse_hashtag_directive,
)
from .tenant_profile import (
    TenantProfileStore,
    list_sales_packs,
    load_sales_pack,
)
from .ui_schema import WECHAT_UI_SCHEMA_VERSION, WeChatUIProtocolNavigator
from .web_console import render_web_console_html
from .safety import (
    AuditLogger,
    DirtyInputCircuitBreakerError,
    GroupAllowlistGuard,
    HumanJitter,
    OutgoingMessageRegistry,
    ReadbackMismatchError,
    ReadbackVerifier,
)

__all__ = [
    "ALL_CAPABILITIES",
    "DEFAULT_GRANT_CAPABILITIES",
    "READ_ONLY_CAPABILITIES",
    "ArchiveAttachment",
    "AuditLogger",
    "CorpusDiscoveryEngine",
    "DirtyInputCircuitBreakerError",
    "DualProductCoevolutionEngine",
    "EuphoriaAffectEngine",
    "GroupAllowlistGuard",
    "HumanActivityGuard",
    "HumanJitter",
    "MagpieProviderHub",
    "OFFICIAL_WECHAT_EMOJIS",
    "OutgoingMessageRegistry",
    "PersonaSwitchEngine",
    "ReadbackMismatchError",
    "ReadbackVerifier",
    "SelfTrainingPlaybookEngine",
    "StudioAuthGate",
    "StudioPluginUnauthorizedError",
    "SupervisorEvalEngine",
    "TenantProfileStore",
    "TranscriptBundle",
    "TranscriptRecord",
    "UnreadDeltaTracker",
    "UnsafeArchiveError",
    "WeChatArticleExporter",
    "WeChatArticleHTMLParser",
    "WeChatBridgeImporter",
    "WeChatControlEngine",
    "WeChatKnowledgeStore",
    "WeChatLiveInspector",
    "WeChatMCPServer",
    "WeChatRealtimeMonitor",
    "WeChatUIProtocolNavigator",
    "WECHAT_UI_SCHEMA_VERSION",
    "blend_persona_partitions",
    "create_http_server",
    "evaluate_turn_human_likeness",
    "humanize_wechat_reply",
    "is_blocked_outbound_directive",
    "is_hashtag_directive",
    "list_sales_packs",
    "load_sales_pack",
    "map_magpie_model",
    "normalize_wechat_emojis",
    "parse_hashtag_directive",
    "parse_sibyl_feedback_command",
    "render_web_console_html",
    "serve_http",
]
