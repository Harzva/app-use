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
from .engine import WeChatControlEngine
from .human_activity_guard import HumanActivityGuard
from .knowledge_kf_engine import PersonaSwitchEngine, WeChatKnowledgeStore
from .live_inspector import WeChatLiveInspector
from .magpie_provider_hub import MagpieProviderHub, map_magpie_model
from .mcp_server import WeChatMCPServer, create_http_server, serve_http
from .realtime_monitor import WeChatRealtimeMonitor
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
    "DirtyInputCircuitBreakerError",
    "GroupAllowlistGuard",
    "HumanActivityGuard",
    "HumanJitter",
    "MagpieProviderHub",
    "OutgoingMessageRegistry",
    "PersonaSwitchEngine",
    "ReadbackMismatchError",
    "ReadbackVerifier",
    "StudioAuthGate",
    "StudioPluginUnauthorizedError",
    "TranscriptBundle",
    "TranscriptRecord",
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
    "create_http_server",
    "map_magpie_model",
    "render_web_console_html",
    "serve_http",
]
