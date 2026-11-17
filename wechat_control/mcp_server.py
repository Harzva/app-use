"""Standard MCP (Model Context Protocol) JSON-RPC 2.0 stdio server + HTTP JSON API."""

from __future__ import annotations

import hmac
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .auth_gate import ALL_CAPABILITIES, StudioPluginUnauthorizedError
from .background_observer import BackgroundObserver
from .engine import WeChatControlEngine
from .saved_drafts import SavedDraftError, SavedDraftStore
from .web_console import render_web_console_html
from .workbench import ReviewLedger, Workbench, WorkbenchError
from .workbench_library import records as workbench_records

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {
    "name": "openbot-wechat-rpa-control",
    "version": "2.4.0",
}

MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "wechat_doctor",
        "description": "Diagnose macOS Accessibility/Screen Recording permissions, WeChat running state, Studio authorization, and safety locks.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_auth_status",
        "description": "Inspect current Bot Studio fail-closed authorization status and granted capabilities.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_status",
        "description": "Return current WeChat PID, visible windows, and hybrid AX+Vision current chat title.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_inspect_live",
        "description": "Read-only walkthrough of open WeChat Chats & Contacts tabs via Vision OCR, generating Markdown/JSON reports.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_session_pages": {"type": "integer", "default": 2},
                "max_contact_pages": {"type": "integer", "default": 4},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_list_sessions",
        "description": "List visible WeChat sessions via AXUIElement tree with Vision OCR sidebar fallback.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_read_messages",
        "description": "Read visible messages from the currently open WeChat conversation via AX or Vision OCR.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "Maximum messages to return."}
            },
            "required": [],
        },
    },
    {
        "name": "wechat_ocr",
        "description": "Run native macOS Vision (VNRecognizeTextRequest zh-Hans/en-US) OCR on an image or the WeChat window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Optional image path; omits to capture live WeChat window."},
                "save_path": {"type": "string", "description": "Optional PNG output path when capturing live WeChat window."},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_send_text",
        "description": "Safe WeChat text sender with allowlist, 120s dedup lock, 3x readback circuit breaker, and dry_run default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target contact or group chat name."},
                "text": {"type": "string", "description": "Message text to verify/send."},
                "dry_run": {"type": "boolean", "default": True, "description": "Defaults to true for safe simulation."},
                "silent_mode": {"type": "boolean", "default": True, "description": "Verify paste without pressing Return."},
                "confirm_send": {"type": "boolean", "default": False, "description": "Must be true (with dry_run=false, silent_mode=false) to send live."},
                "allowed_groups": {"type": "array", "items": {"type": "string"}, "description": "Optional target allowlist."},
            },
            "required": ["target", "text"],
        },
    },
    {
        "name": "wechat_import_chatlog",
        "description": "Import a WeChat forwarded ZIP archive, 聊天记录.txt, or directory into Obsidian Markdown & JSONL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Path to .zip, .txt, or folder."},
                "output_dir": {"type": "string", "description": "Optional output directory to write .md and .jsonl files."},
            },
            "required": ["source_path"],
        },
    },
    {
        "name": "wechat_bind_contact",
        "description": "Bind a WeChat contact or group with scheduled test check-in, Special Care tier, and AI chat persona settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "alias": {"type": "string", "default": ""},
                "role": {"type": "string", "default": "friend"},
                "ai_persona": {"type": "string", "default": "warm-companion"},
                "scheduled_enabled": {"type": "boolean", "default": True},
                "cron_hint": {"type": "string", "default": "0 9,21 * * *"},
                "auto_reply_enabled": {"type": "boolean", "default": True},
                "notes": {"type": "string", "default": ""},
                "special_care": {"type": "boolean"},
                "care_level": {"type": "string", "enum": ["special_care", "vip", "normal"]},
                "care_tags": {"type": "array", "items": {"type": "string"}},
                "follow_up_days": {"type": "integer"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_set_special_care",
        "description": "Set or update a contact/group's Special Care priority tier (special_care / vip / normal) and tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "enabled": {"type": "boolean", "default": True},
                "care_level": {"type": "string", "enum": ["special_care", "vip", "normal"], "default": "special_care"},
                "care_tags": {"type": "array", "items": {"type": "string"}},
                "follow_up_days": {"type": "integer"},
                "notes": {"type": "string"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_web_overview",
        "description": "Return aggregated dashboard state, Special Care analytics, monitor stream, and KB summary.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_list_bindings",
        "description": "List all bound WeChat contacts/groups and their interaction policies.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_observe_contact",
        "description": "Navigate to a bound WeChat contact/group, scroll upward through message history, and persist structured OCR records.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "scroll_pages": {"type": "integer", "default": 4},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_profile_contact",
        "description": "Analyze friend communication styles, content categories, frequency, and active time-of-day distributions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Optional contact/group filter; omit for all."}
            },
            "required": [],
        },
    },
    {
        "name": "wechat_chat_test",
        "description": "Run a scheduled check-in or AI chat test against a bound contact/group (dry_run by default unless confirm_send=true).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "mode": {"type": "string", "default": "scheduled"},
                "text": {"type": "string"},
                "confirm_send": {"type": "boolean", "default": False},
                "silent_verify": {"type": "boolean", "default": False},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_kb_search",
        "description": "Search the local WeChat customer-service knowledge base and domain terminology dictionary via FTS5.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "library": {"type": "string"},
                "limit": {"type": "integer", "default": 6},
            },
            "required": ["query"],
        },
    },
    {
        "name": "wechat_kb_save",
        "description": "Create or update a terminology, knowledge, script, or faq entry in the local knowledge store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "kind": {"type": "string", "default": "knowledge"},
                "library": {"type": "string", "default": "shared"},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "synonyms": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "wechat_persona_switch",
        "description": "Switch the active persona, MBTI, and interaction style for a bound WeChat contact or group.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "persona_id": {"type": "string"},
                "mbti": {"type": "string"},
                "interaction_style": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["target", "persona_id"],
        },
    },
    {
        "name": "wechat_reply_preview",
        "description": "Generate a KB-grounded and persona-styled reply preview for a contact message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "incoming_text": {"type": "string"},
                "persona_override": {"type": "string"},
            },
            "required": ["target", "incoming_text"],
        },
    },
    {
        "name": "wechat_watch_once",
        "description": "Run one real-time WeChat monitor scan & guarded auto-reply cycle (dry-run unless confirm_send=true).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "auto_reply": {"type": "boolean", "default": True},
                "confirm_send": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_monitor_status",
        "description": "Inspect real-time monitor daemon status, heartbeats, and per-contact deduplication checkpoints.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "wechat_export_article",
        "description": "Export an open WeChat article or mp.weixin.qq.com URL to a local Markdown (.md) file with localized assets/ images.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Optional WeChat article URL (https://mp.weixin.qq.com/s/...)."},
                "from_window": {"type": "boolean", "default": True},
                "max_scroll_pages": {"type": "integer", "default": 4},
                "download_images": {"type": "boolean", "default": True},
                "try_copy_link": {"type": "boolean", "default": True},
                "output_dir": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_list_exported_articles",
        "description": "List previously exported WeChat Markdown articles and local image bundles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_export_account_articles",
        "description": "Batch-export all historical articles of a WeChat Official/Service Account via album URL, explicit URLs, local HTML/manifest file, or live window OCR scroll.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string", "description": "Official or Service Account name."},
                "album_url": {"type": "string", "description": "Optional mp.weixin.qq.com album or homepage URL."},
                "article_urls": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit list of article URLs."},
                "from_file": {"type": "string", "description": "Optional local album HTML or URL/JSON manifest file path."},
                "scan_open_window": {"type": "boolean", "default": False},
                "scroll_pages": {"type": "integer", "default": 4},
                "download_images": {"type": "boolean", "default": True},
                "max_articles": {"type": "integer", "default": 50},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_export_channels_videos",
        "description": "Batch-export WeChat Channels (视频号) creator videos via stream URLs/manifest (supporting decode_key XOR prefix decode), local cache MP4/MOV scan, or live window OCR.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "author_name": {"type": "string", "description": "Channels creator author name."},
                "video_urls": {"type": "array", "items": {"type": "string"}, "description": "Optional direct stream URLs."},
                "manifest_path": {"type": "string", "description": "Optional JSON/JSONL/text manifest file path."},
                "cache_dir": {"type": "string", "description": "Optional local WeChat Channels cache directory."},
                "scan_open_window": {"type": "boolean", "default": False},
                "scroll_pages": {"type": "integer", "default": 4},
                "download_media": {"type": "boolean", "default": True},
                "max_videos": {"type": "integer", "default": 50},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_ui_schema",
        "description": "Get standardized macOS WeChat UI views, chat window regions, settings targets, and navigation protocol schema.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "wechat_ui_state",
        "description": "Inspect active WeChat UI view, split-pane layout geometry, resolved target coordinates, and human activity guard status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "refresh_ocr": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_navigate_ui",
        "description": "Navigate or dry-run a standardized semantic WeChat UI target (e.g. nav.contacts, menu.settings, chat.header_more_drawer).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
                "respect_human_guard": {"type": "boolean", "default": True},
            },
            "required": ["target_id"],
        },
    },
    {
        "name": "wechat_human_guard",
        "description": "Query or configure human mouse/keyboard idle detection & anti-contention cooldown guard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "idle_resume_seconds": {"type": "number"},
                "cooldown_seconds": {"type": "number"},
                "reset_cooldown": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_takeover_contact",
        "description": "Pause or resume AI auto-reply on a contact/group via human takeover.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "action": {"type": "string", "default": "takeover"},
                "reason": {"type": "string"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_list_models",
        "description": "List Magpie gateway models and configured multi-vendor providers (secret-masked).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "refresh": {"type": "boolean", "default": False},
                "provider_filter": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_select_model",
        "description": "Select global default or per-contact model via Magpie Multi-Provider Hub.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "contact": {"type": "string"},
                "provider_id": {"type": "string"},
                "fallback_model_id": {"type": "string"},
                "llm_enabled": {"type": "boolean"},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_probe_model",
        "description": "Probe live connectivity and latency for a model via Magpie or configured provider.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "provider_id": {"type": "string"},
                "prompt": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_save_provider",
        "description": "Configure Magpie gateway or register a custom OpenAI/Anthropic-compatible provider.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider_id": {"type": "string"},
                "name": {"type": "string"},
                "base_url": {"type": "string"},
                "gateway_url": {"type": "string"},
                "api_key": {"type": "string"},
                "api_key_env": {"type": "string"},
                "default_model": {"type": "string"},
                "vendor": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_soul_profile",
        "description": "Get or rebuild WeChat Owner Self-Soul, Friend Psychological Profiles & Episodic Memories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "rebuild": {"type": "boolean", "default": False},
                "use_llm": {"type": "boolean", "default": False},
                "model_id": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_memory_add",
        "description": "Add a persistent fact, episodic event, or shared context memory to a WeChat contact's Soul profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string", "default": "fact"},
                "time_marker": {"type": "string"},
            },
            "required": ["target", "content"],
        },
    },
    {
        "name": "wechat_run_benchmark",
        "description": "Run the 8-module WeChat RPA + Soul Memory + Kimi acceptance benchmark suite.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_tests": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_bind_agent",
        "description": "Bind an Agent (Bot Studio / DSH / OpenBot / custom) and multimodal vision model (e.g. auto/deepseek-v4.1-flash) to a WeChat contact or group while preserving existing care/persona settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "agent_id": {"type": "string"},
                "agent_name": {"type": "string"},
                "agent_type": {"type": "string", "default": "botstudio"},
                "vision_model_id": {"type": "string", "default": "auto/deepseek-v4.1-flash"},
                "auto_dispatch_instructions": {"type": "boolean", "default": True},
                "auto_analyze_links_and_media": {"type": "boolean", "default": True},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_analyze_media",
        "description": "Deep-read a URL link, cropped chat image/article card, or video using 2x Apple Vision OCR + DeepSeek Flash VLM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["link", "image", "video"], "default": "link"},
                "url": {"type": "string"},
                "image_path": {"type": "string"},
                "video_path": {"type": "string"},
                "video_url": {"type": "string"},
                "crop_region": {"type": "object"},
                "from_viewer_window": {"type": "boolean", "default": False},
                "source_snapshot": {"type": "string"},
                "window_title": {"type": "string", "default": "图片和视频"},
                "contact": {"type": "string", "default": ""},
                "context_text": {"type": "string", "default": ""},
                "frame_count": {"type": "integer", "default": 3},
                "model_id": {"type": "string", "default": "auto/deepseek-v4.1-flash"},
                "allow_loopback": {"type": "boolean", "default": False},
                "html_override": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_agent_dispatch",
        "description": "Parse instructions, links, and media from a bound friend/group chat and dispatch tasks to their bound Agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "include_live_media": {"type": "boolean", "default": True},
                "execute_with_agent": {"type": "boolean", "default": True},
                "extra_messages": {"type": "array", "items": {"type": "object"}},
                "model_id": {"type": "string"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_vision_stack",
        "description": "Inspect the two-layer vision stack (Apple Vision 2x OCR monitor layer + DeepSeek Flash multimodal VLM layer).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_dock_sidebar",
        "description": "Verify, dock, or side-by-side tile WeChat Bot.app pinned as a magnetic sidebar alongside the WeChat window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["verify", "dock", "tile"], "default": "verify"},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_botstudio_bridge",
        "description": "Inspect standalone .app status, compile native dsh.plugin.json via dsh2codex, silently rebuild/sign standalone .app bundles without prompts, or export the Bot Studio integration bundle.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "compile_dsh", "export_bundle", "install", "rebuild_app", "compile_all"],
                    "default": "status",
                },
                "out_path": {"type": "string"},
                "install_to_host": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_salescrm_pipeline",
        "description": "Manage the Aurora-73/SalesCRM marketing funnel: sync WeChat contacts/chats, enroll/update customers, list/complete/reschedule Beijing-time reminders, merge accounts, or adopt Top 1-3 follow-up drafts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "overview",
                        "sync",
                        "reminders",
                        "enroll",
                        "update",
                        "complete_reminder",
                        "reschedule",
                        "merge_accounts",
                        "adopt_draft",
                    ],
                    "default": "overview",
                },
                "target": {"type": "string", "default": ""},
                "stage": {"type": "string", "default": "跟进中"},
                "note": {"type": "string", "default": ""},
                "follow_up": {"type": "string", "default": ""},
                "deal_value": {"type": "number", "default": 0.0},
                "alias": {"type": "string", "default": ""},
                "secondary_target": {"type": "string", "default": ""},
                "rank_index": {"type": "integer", "default": 1},
                "send_mode": {"type": "string", "default": "adopt_only"},
                "auto_sync": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_salescrm_analyze",
        "description": "Run Aurora-73/SalesCRM 15-dimensional quantitative analysis, stage recognition, timeline detection, and Top 1-3 follow-up draft generation for a WeChat contact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "default": "联系人A"},
                "incoming_text": {"type": "string", "default": ""},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_salescrm_formulas",
        "description": "Evaluate Aurora-73/SalesCRM BQ, BSP, BWS, PV, and sales_action formulas for a contact with optional parameter overrides.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "default": "联系人A"},
                "overrides": {"type": "object", "default": {}},
            },
            "required": ["target"],
        },
    },
]


class WeChatMCPServer:
    """Line-delimited JSON-RPC 2.0 MCP stdio server."""

    def __init__(self, engine: Optional[WeChatControlEngine] = None) -> None:
        self.engine = engine or WeChatControlEngine()

    def _dispatch_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "wechat_doctor":
            return self.engine.doctor()
        if name == "wechat_auth_status":
            return self.engine.auth_status()
        if name == "wechat_status":
            return self.engine.get_status()
        if name == "wechat_inspect_live":
            return self.engine.inspect_live_wechat(
                max_session_pages=int(args.get("max_session_pages", 2)),
                max_contact_pages=int(args.get("max_contact_pages", 4)),
            )
        if name == "wechat_list_sessions":
            return self.engine.list_sessions()
        if name == "wechat_read_messages":
            limit = int(args.get("limit", 20))
            return self.engine.read_messages(limit=limit)
        if name == "wechat_ocr":
            img = args.get("image_path")
            if img:
                return self.engine.ocr_image(Path(img))
            save = args.get("save_path")
            return self.engine.ocr_wechat_window(Path(save) if save else None)
        if name == "wechat_send_text":
            return self.engine.send_text(
                target=str(args.get("target", "")),
                text=str(args.get("text", "")),
                dry_run=bool(args.get("dry_run", True)),
                silent_mode=bool(args.get("silent_mode", True)),
                confirm_send=bool(args.get("confirm_send", False)),
                allowed_groups=args.get("allowed_groups"),
            )
        if name == "wechat_import_chatlog":
            src = Path(str(args["source_path"]))
            out = Path(str(args["output_dir"])) if args.get("output_dir") else None
            return self.engine.import_chatlog(src, output_dir=out)
        if name == "wechat_bind_contact":
            return self.engine.bind_contact(
                str(args["target"]),
                alias=str(args.get("alias", "")),
                role=str(args.get("role", "friend")),
                ai_persona=str(args.get("ai_persona", "warm-companion")),
                scheduled_enabled=bool(args.get("scheduled_enabled", True)),
                cron_hint=str(args.get("cron_hint", "0 9,21 * * *")),
                auto_reply_enabled=bool(args.get("auto_reply_enabled", True)),
                notes=str(args.get("notes", "")),
                special_care=args.get("special_care"),
                care_level=args.get("care_level"),
                care_tags=args.get("care_tags"),
                follow_up_days=args.get("follow_up_days"),
            )
        if name == "wechat_set_special_care":
            return self.engine.set_special_care(
                str(args["target"]),
                enabled=bool(args.get("enabled", True)),
                care_level=args.get("care_level"),
                care_tags=args.get("care_tags"),
                follow_up_days=args.get("follow_up_days"),
                notes=args.get("notes"),
            )
        if name == "wechat_web_overview":
            return self.engine.get_web_overview()
        if name == "wechat_list_bindings":
            return self.engine.list_bindings()
        if name == "wechat_observe_contact":
            return self.engine.observe_contact(
                str(args["target"]),
                scroll_pages=int(args.get("scroll_pages", 4)),
            )
        if name == "wechat_profile_contact":
            tgt = str(args["target"]) if args.get("target") else None
            return self.engine.profile_contacts(tgt)
        if name == "wechat_chat_test":
            return self.engine.chat_test(
                str(args["target"]),
                mode=str(args.get("mode", "scheduled")),
                text=args.get("text"),
                confirm_send=bool(args.get("confirm_send", False)),
                silent_verify=bool(args.get("silent_verify", False)),
            )
        if name == "wechat_kb_search":
            return self.engine.kb_search(
                str(args["query"]),
                kind=args.get("kind"),
                library=args.get("library"),
                limit=int(args.get("limit", 6)),
            )
        if name == "wechat_kb_save":
            return self.engine.kb_save(
                title=str(args["title"]),
                body=str(args["body"]),
                kind=str(args.get("kind", "knowledge")),
                library=str(args.get("library", "shared")),
                keywords=args.get("keywords"),
                synonyms=args.get("synonyms"),
            )
        if name == "wechat_persona_switch":
            return self.engine.persona_switch(
                str(args["target"]),
                str(args["persona_id"]),
                mbti=args.get("mbti"),
                interaction_style=args.get("interaction_style"),
                custom_note=str(args.get("note", "")),
            )
        if name == "wechat_reply_preview":
            return self.engine.preview_smart_reply(
                str(args["target"]),
                str(args["incoming_text"]),
                persona_override=args.get("persona_override"),
                model_id=args.get("model_id"),
                use_llm=args.get("use_llm"),
            )
        if name == "wechat_watch_once":
            return self.engine.monitor_once(
                target=args.get("target"),
                auto_reply=bool(args.get("auto_reply", True)),
                confirm_send=bool(args.get("confirm_send", False)),
            )
        if name == "wechat_monitor_status":
            return self.engine.monitor_status()
        if name == "wechat_export_article":
            return self.engine.export_article(
                url=args.get("url"),
                from_window=bool(args.get("from_window", True)),
                max_scroll_pages=int(args.get("max_scroll_pages", 4)),
                download_images=bool(args.get("download_images", True)),
                try_copy_link=bool(args.get("try_copy_link", True)),
                output_dir=args.get("output_dir"),
            )
        if name == "wechat_list_exported_articles":
            return self.engine.list_exported_articles(limit=int(args.get("limit", 20)))
        if name == "wechat_export_account_articles":
            return self.engine.export_account_articles(
                account_name=str(args.get("account_name") or ""),
                album_url=str(args.get("album_url") or ""),
                album_html=str(args.get("album_html") or ""),
                article_urls=args.get("article_urls"),
                articles_html_list=args.get("articles_html_list"),
                from_file=args.get("from_file"),
                scan_open_window=bool(args.get("scan_open_window", False)),
                scroll_pages=int(args.get("scroll_pages", 4)),
                download_images=bool(args.get("download_images", True)),
                max_articles=int(args.get("max_articles", 50)),
            )
        if name == "wechat_export_channels_videos":
            return self.engine.export_channels_videos(
                author_name=str(args.get("author_name") or ""),
                video_items=args.get("video_items"),
                video_urls=args.get("video_urls"),
                manifest_path=args.get("manifest_path"),
                cache_dir=args.get("cache_dir"),
                scan_open_window=bool(args.get("scan_open_window", False)),
                scroll_pages=int(args.get("scroll_pages", 4)),
                download_media=bool(args.get("download_media", True)),
                max_videos=int(args.get("max_videos", 50)),
            )
        if name == "wechat_ui_schema":
            return self.engine.get_ui_schema()
        if name == "wechat_ui_state":
            return self.engine.inspect_ui_state(refresh_ocr=bool(args.get("refresh_ocr", False)))
        if name == "wechat_navigate_ui":
            return self.engine.navigate_ui(
                str(args["target_id"]),
                dry_run=bool(args.get("dry_run", True)),
                respect_human_guard=bool(args.get("respect_human_guard", True)),
            )
        if name == "wechat_human_guard":
            if (
                args.get("enabled") is None
                and args.get("idle_resume_seconds") is None
                and args.get("cooldown_seconds") is None
                and not bool(args.get("reset_cooldown", False))
            ):
                return self.engine.get_human_guard_status()
            return self.engine.configure_human_guard(
                enabled=args.get("enabled"),
                idle_resume_seconds=args.get("idle_resume_seconds"),
                cooldown_seconds=args.get("cooldown_seconds"),
                reset_cooldown=bool(args.get("reset_cooldown", False)),
            )
        if name == "wechat_takeover_contact":
            action = str(args.get("action", "takeover")).strip().lower()
            if action == "resume":
                return self.engine.resume_contact(str(args["target"]))
            return self.engine.takeover_contact(
                str(args["target"]),
                reason=str(args.get("reason", "")),
            )
        if name == "wechat_list_models":
            return self.engine.list_models(
                refresh=bool(args.get("refresh", False)),
                provider_filter=args.get("provider_filter"),
            )
        if name == "wechat_select_model":
            return self.engine.select_model(
                model_id=str(args.get("model_id") or ""),
                contact=args.get("contact"),
                provider_id=args.get("provider_id"),
                fallback_model_id=args.get("fallback_model_id"),
                llm_enabled=args.get("llm_enabled"),
            )
        if name == "wechat_probe_model":
            return self.engine.probe_model(
                model_id=args.get("model_id"),
                provider_id=args.get("provider_id"),
                prompt=str(args.get("prompt") or "请用不超过20个字回复：收到测试，状态正常。"),
            )
        if name == "wechat_save_provider":
            return self.engine.save_provider(
                provider_id=args.get("provider_id"),
                name=str(args.get("name") or ""),
                base_url=str(args.get("base_url") or ""),
                api_key=args.get("api_key"),
                api_key_env=args.get("api_key_env"),
                default_model=str(args.get("default_model") or ""),
                vendor=str(args.get("vendor") or "Custom"),
                enabled=bool(args.get("enabled", True)),
                gateway_url=args.get("gateway_url"),
            )
        if name == "wechat_soul_profile":
            return self.engine.get_soul_profiles(
                target=args.get("target"),
                rebuild=bool(args.get("rebuild", False)),
                use_llm=bool(args.get("use_llm", False)),
                model_id=args.get("model_id"),
            )
        if name == "wechat_memory_add":
            return self.engine.add_soul_memory(
                str(args["target"]),
                str(args["content"]),
                category=str(args.get("category") or "fact"),
                time_marker=str(args.get("time_marker") or ""),
            )
        if name == "wechat_run_benchmark":
            return self.engine.run_benchmark(include_tests=bool(args.get("include_tests", False)))
        if name == "wechat_bind_agent":
            target = str(arguments["target"])
            existing = self.engine.bindings.get_binding(target) or {}
            return self.engine.bind_contact(
                target,
                alias=str(arguments.get("alias", existing.get("alias", ""))),
                role=str(arguments.get("role", existing.get("role", "friend"))),
                ai_persona=str(arguments.get("ai_persona", existing.get("aiPersona", "warm-companion"))),
                scheduled_enabled=bool(arguments.get("scheduled_enabled", existing.get("scheduledEnabled", True))),
                cron_hint=str(arguments.get("cron_hint", existing.get("cronHint", "0 9,21 * * *"))),
                auto_reply_enabled=bool(arguments.get("auto_reply_enabled", existing.get("autoReplyEnabled", True))),
                notes=str(arguments.get("notes", existing.get("notes", ""))),
                bound_agent_id=arguments.get("agent_id") or arguments.get("bound_agent_id"),
                bound_agent_name=arguments.get("agent_name") or arguments.get("bound_agent_name"),
                bound_agent_type=arguments.get("agent_type") or arguments.get("bound_agent_type"),
                vision_model_id=arguments.get("vision_model_id") or arguments.get("vision_model"),
                auto_dispatch_instructions=arguments.get("auto_dispatch_instructions"),
                auto_analyze_links_and_media=arguments.get("auto_analyze_links_and_media"),
            )
        if name == "wechat_analyze_media":
            return self.engine.analyze_media_or_link(
                kind=str(arguments.get("kind", "link")),
                url=arguments.get("url"),
                image_path=arguments.get("image_path"),
                video_path=arguments.get("video_path"),
                video_url=arguments.get("video_url"),
                crop_region=arguments.get("crop_region"),
                from_viewer_window=bool(arguments.get("from_viewer_window", False)),
                source_snapshot=arguments.get("source_snapshot"),
                window_title=str(arguments.get("window_title", "图片和视频")),
                contact=str(arguments.get("contact", "")),
                context_text=str(arguments.get("context_text", "")),
                frame_count=int(arguments.get("frame_count", 3)),
                model_id=str(arguments.get("model_id", "auto/deepseek-v4.1-flash")),
                allow_loopback=bool(arguments.get("allow_loopback", False)),
                html_override=arguments.get("html_override"),
            )
        if name == "wechat_agent_dispatch":
            return self.engine.dispatch_friend_instructions(
                str(arguments.get("target") or arguments.get("contact") or ""),
                include_live_media=bool(arguments.get("include_live_media", True)),
                execute_with_agent=bool(arguments.get("execute_with_agent", True)),
                extra_messages=arguments.get("extra_messages"),
                model_id=arguments.get("model_id"),
                html_overrides=arguments.get("html_overrides"),
            )
        if name == "wechat_vision_stack":
            return self.engine.get_vision_stack_info()
        if name == "wechat_dock_sidebar":
            return self.engine.dock_app_to_wechat(mode=str(arguments.get("mode", "verify")))
        if name == "wechat_botstudio_bridge":
            action = str(args.get("action") or "status").strip().lower()
            if action in ("rebuild_app", "compile_all"):
                return self.engine.rebuild_standalone_app(
                    install_to_host=bool(args.get("install_to_host", True))
                )
            if action == "install":
                return self.engine.install_to_host(
                    launch_standalone=bool(args.get("launch_standalone", False)),
                    launch_bot_studio=bool(args.get("launch_bot_studio", False)),
                )
            if action == "compile_dsh":
                return self.engine.compile_dsh_plugin_for_botstudio()
            if action == "export_bundle":
                return self.engine.export_botstudio_integration_bundle(out_path=args.get("out_path") or None)
            return self.engine.get_botstudio_bridge_status()
        if name == "wechat_salescrm_pipeline":
            action = str(args.get("action") or "overview").strip().lower()
            target = str(args.get("target") or "").strip()
            if action == "sync":
                return self.engine.crm_sync_from_wechat()
            if action == "reminders":
                return self.engine.crm_list_reminders()
            if action == "enroll":
                return self.engine.crm_enroll_contact(
                    target,
                    stage=str(args.get("stage") or "新线索"),
                    note=str(args.get("note") or ""),
                    follow_up=args.get("follow_up") or None,
                    deal_value=float(args.get("deal_value") or 0.0),
                    alias=str(args.get("alias") or ""),
                )
            if action == "update":
                dv = args.get("deal_value")
                return self.engine.crm_update_record(
                    target,
                    stage=str(args.get("stage") or "跟进中"),
                    note=str(args.get("note") or ""),
                    follow_up=args.get("follow_up") or None,
                    deal_value=float(dv) if dv is not None else None,
                )
            if action == "complete_reminder":
                return self.engine.crm_complete_reminder(target)
            if action == "reschedule":
                return self.engine.crm_reschedule_reminder(target, str(args.get("follow_up") or ""))
            if action == "merge_accounts":
                return self.engine.crm_merge_accounts(
                    target,
                    str(args.get("secondary_target") or ""),
                    alias=str(args.get("alias") or ""),
                )
            if action == "adopt_draft":
                return self.engine.crm_adopt_draft(
                    target,
                    rank_index=int(args.get("rank_index") or 1),
                    send_mode=str(args.get("send_mode") or "adopt_only"),
                )
            return self.engine.crm_overview(auto_sync=bool(args.get("auto_sync", True)))
        if name == "wechat_salescrm_analyze":
            return self.engine.crm_analyze_contact(
                str(args.get("target") or "联系人A"),
                incoming_text=str(args.get("incoming_text") or ""),
            )
        if name == "wechat_salescrm_formulas":
            return self.engine.crm_evaluate_formulas(
                str(args.get("target") or "联系人A"),
                overrides=args.get("overrides") if isinstance(args.get("overrides"), dict) else None,
            )
        raise KeyError(f"Unknown tool: {name}")

    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params") or {}

        # Notifications without id receive no JSON-RPC response
        if req_id is None and method == "notifications/initialized":
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}

        if method == "tools/call":
            tool_name = str(params.get("name", ""))
            tool_args = params.get("arguments") or {}
            try:
                tool_result = self._dispatch_tool(tool_name, tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(tool_result, ensure_ascii=False, indent=2),
                            }
                        ],
                        "isError": not bool(tool_result.get("ok", True)),
                    },
                }
            except KeyError as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": str(exc)},
                }
            except StudioPluginUnauthorizedError as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "ok": False,
                                        "error_code": exc.code,
                                        "capability": exc.capability,
                                        "error": str(exc),
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                        "isError": True,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)}],
                        "isError": True,
                    },
                }

        if req_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def serve_stdio(self) -> None:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
                sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue
            resp = self.handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def create_http_server(
    engine: WeChatControlEngine,
    host: str = "127.0.0.1",
    port: int = 18788,
    *,
    workbench: Optional[Workbench] = None,
    preview_secret: Optional[str] = None,
    guided: bool = False,
    integrated: bool = False,
) -> ThreadingHTTPServer:
    """Build the local HTTP Web Control Console + REST API server."""
    if guided and (preview_secret is None or workbench is None):
        raise ValueError("guided workbench requires an isolated service and session")
    if integrated and not guided:
        raise ValueError("desktop integration requires a guided workbench")
    init_lock = threading.Lock()
    background = BackgroundObserver(engine)
    saved_path = "/api/workbench/saved-drafts"

    def inbox():
        nonlocal workbench
        with init_lock:
            if workbench is None:
                workbench = Workbench(engine, ReviewLedger(engine.auth_gate.auth_file.parent / "workbench" / "inbox.sqlite"))
            return workbench

    class Handler(BaseHTTPRequestHandler):
        def _workbench_allowed(self, *, post=False):
            # Do not expose tasks or local writes through wildcard binds, DNS aliases or cross-origin forms.
            port = self.server.server_port
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            host_header = self.headers.get("Host")
            origin = self.headers.get("Origin")
            return (self.client_address[0] == "127.0.0.1" and host in {"127.0.0.1", "localhost"}
                    and host_header in allowed and self.headers.get("Sec-Fetch-Site") not in {"cross-site", "same-site"}
                    and ((not post and origin is None) or origin == f"http://{host_header}"))

        def _handle_background_observation(self, *, post=False) -> None:
            try:
                if not self._workbench_allowed(post=post):
                    raise WorkbenchError("local_origin_required", 403)
                if post:
                    if self.headers.get_content_type() != "application/json":
                        raise WorkbenchError("json_required", 415)
                    if not 0 < int(self.headers.get("Content-Length", "0")) <= 512:
                        raise WorkbenchError("invalid_body", 400)
                    body = self._read_json()
                    if not isinstance(body, dict) or set(body) != {"action"}:
                        raise WorkbenchError("invalid_body", 400)
                    if body["action"] == "start":
                        data = background.start()
                    elif body["action"] == "stop":
                        data = background.stop()
                    else:
                        raise WorkbenchError("invalid_action", 400)
                else:
                    engine._require("status")
                    data = background.status()
                self._send_json(200, {"ok": True, **data}, private=True)
            except WorkbenchError as exc:
                self._send_json(exc.status, {"ok": False, "error_code": exc.code}, private=True)
            except StudioPluginUnauthorizedError:
                self._send_json(403, {"ok": False, "error_code": "authorization_required"}, private=True)
            except (ValueError, TypeError):
                self._send_json(400, {"ok": False, "error_code": "invalid_body"}, private=True)

        def _handle_workbench(self, path, *, post=False):
            try:
                if preview_secret is not None and not hmac.compare_digest(
                        self.headers.get("X-Workbench-Session", "").encode(), preview_secret.encode()):
                    raise WorkbenchError("local_origin_required", 403)
                if not self._workbench_allowed(post=post):
                    raise WorkbenchError("local_origin_required", 403)
                if not post and path in {"/workbench", "/workbench/"}:
                    html = Path(__file__).with_name("workbench.html").read_bytes()
                    if preview_secret is not None:
                        html = html.replace(b"<!-- workbench-session -->",
                                            f'<meta name="workbench-session" content="{preview_secret}">'.encode())
                    if guided:
                        html = html.replace(b"<!-- guided-mode -->", b'<meta name="guided-mode" content="1">')
                    if integrated:
                        html = html.replace(b"<!-- integrated-mode -->", b'<meta name="integrated-mode" content="1">')
                    self._send_bytes(200, html, "text/html; charset=utf-8", private=True)
                    return
                if path == saved_path or path.startswith(saved_path + "/"):
                    if preview_secret is not None or guided or integrated:
                        raise WorkbenchError("not_found", 404)
                    engine._require("read_messages")
                    store = SavedDraftStore(engine.auth_gate.auth_file.parent / "workbench" / "saved-drafts.sqlite")
                    if not post and path == saved_path:
                        data = {"drafts": store.list()}
                    elif not post:
                        data = {"draft": store.get(path[len(saved_path) + 1:])}
                    elif path == saved_path:
                        if self.headers.get_content_type() != "application/json":
                            raise WorkbenchError("json_required", 415)
                        if not 0 < int(self.headers.get("Content-Length", "0")) <= 80 * 1024:
                            raise SavedDraftError("invalid_saved_draft", 400)
                        data = {"draft": store.save(self._read_json())}
                    elif path.endswith("/state"):
                        if self.headers.get_content_type() != "application/json":
                            raise WorkbenchError("json_required", 415)
                        if not 0 < int(self.headers.get("Content-Length", "0")) <= 512:
                            raise SavedDraftError("invalid_saved_draft_state", 400)
                        identifier = path[len(saved_path) + 1:-len("/state")]
                        data = {"draft": store.set_state(identifier, self._read_json())}
                    else:
                        raise WorkbenchError("not_found", 404)
                elif not post and path == "/api/workbench/status":
                    data = inbox().status()
                elif integrated and not post and path in {
                    "/api/workbench/contacts", "/api/workbench/archive",
                    "/api/workbench/soul", "/api/workbench/models",
                }:
                    data = workbench_records(engine, path.rsplit("/", 1)[-1])
                elif integrated and not post and path == "/api/workbench/knowledge":
                    entries = engine.knowledge.list_entries(space_id=inbox().recommendation_space, limit=40)["entries"]
                    data = {"entries": [
                        {k: entry.get(k, "") for k in ("title", "body", "kind")} for entry in entries
                    ]}
                elif guided and not post and path == "/api/workbench/windows":
                    data = {"windows": inbox().choices()}
                elif not post and path == "/api/workbench/tasks":
                    engine._require("read_messages")
                    data = {"tasks": inbox().ledger.list()}
                elif not post and path.startswith("/api/workbench/tasks/"):
                    engine._require("read_messages")
                    with inbox().ledger.transaction() as db:
                        data = {"task": inbox().ledger.get(db, path.rsplit("/", 1)[-1])}
                elif post:
                    if self.headers.get_content_type() != "application/json":
                        raise WorkbenchError("json_required", 415)
                    if not 0 < int(self.headers.get("Content-Length", "0")) <= 16384:
                        raise WorkbenchError("invalid_body", 400)
                    body = self._read_json()
                    if not isinstance(body, dict):
                        raise WorkbenchError("invalid_body", 400)
                    if integrated and path == "/api/workbench/knowledge":
                        title, text = body.get("title"), body.get("text")
                        if not isinstance(title, str) or not title.strip() or len(title) > 100:
                            raise WorkbenchError("invalid_knowledge", 400)
                        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                            raise WorkbenchError("invalid_knowledge", 400)
                        try:
                            engine.knowledge.save_entry(
                                title=title, body=text, kind="faq", source="wechat-workbench",
                                space_id=inbox().recommendation_space,
                            )
                        except ValueError:
                            raise WorkbenchError("invalid_knowledge", 400) from None
                        data = {}
                    elif guided and path == "/api/workbench/window":
                        data = inbox().select(body.get("window"))
                    elif guided and path == "/api/workbench/monitor":
                        data = inbox().set_monitor(body.get("action"))
                    elif path == "/api/workbench/capture":
                        data = {"task": inbox().ingest()}
                    elif path == "/api/workbench/draft":
                        method = inbox().recommend if preview_secret is not None else inbox().draft
                        data = {"task": method(body.get("id", ""))}
                    elif path == "/api/workbench/adopt" and preview_secret is not None:
                        data = {"task": inbox().adopt(body.get("id", ""), body.get("version"), body.get("choice"))}
                    elif path == "/api/workbench/confirm":
                        if preview_secret is not None and not guided:
                            raise WorkbenchError("preview_no_send", 403)
                        data = {"task": inbox().confirm(body.get("id", ""), body.get("version"), body.get("text"))}
                    else:
                        raise WorkbenchError("not_found", 404)
                else:
                    raise WorkbenchError("not_found", 404)
                self._send_json(200, {"ok": True, **data}, private=True)
            except (WorkbenchError, SavedDraftError) as exc:
                self._send_json(exc.status, {"ok": False, "error_code": exc.code}, private=True)
            except StudioPluginUnauthorizedError:
                self._send_json(403, {"ok": False, "error_code": "authorization_required"}, private=True)
            except (ValueError, TypeError):
                self._send_json(400, {"ok": False, "error_code": "invalid_body"}, private=True)
            except Exception:
                self._send_json(500, {"ok": False, "error_code": "workbench_error"}, private=True)

        def _send_json(self, code: int, data: Dict[str, Any], *, private: bool = False) -> None:
            body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self._send_bytes(code, body, "application/json; charset=utf-8", private=private)

        def _send_html(self, code: int, html: str) -> None:
            self._send_bytes(code, html.encode("utf-8"), "text/html; charset=utf-8")

        def _send_bytes(self, code: int, data: bytes, content_type: str, *, private: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if private:
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path in {"/workbench", "/workbench/"} or path.startswith("/api/workbench/"):
                self._handle_workbench(path)
                return
            if preview_secret is not None:
                self._send_json(404, {"ok": False})
                return
            if path == "/api/background-observation":
                self._handle_background_observation()
                return
            try:
                if path in ("/", "/console", "/index.html"):
                    self._send_html(200, render_web_console_html())
                elif path == "/health":
                    self._send_json(200, {"ok": True, "service": SERVER_INFO["name"]})
                elif path == "/auth/status":
                    self._send_json(200, engine.auth_status())
                elif path in ("/api/overview", "/api/dashboard"):
                    self._send_json(200, engine.get_web_overview())
                elif path == "/api/models":
                    refresh_flag = str((query.get("refresh") or ["0"])[0]).lower() in ("1", "true", "yes")
                    provider_filter = (query.get("provider") or [None])[0]
                    self._send_json(200, engine.list_models(refresh=refresh_flag, provider_filter=provider_filter))
                elif path == "/api/exported-articles":
                    limit_val = int((query.get("limit") or ["20"])[0])
                    self._send_json(200, engine.list_exported_articles(limit=limit_val))
                elif path == "/api/account-exports":
                    limit_val = int((query.get("limit") or ["20"])[0])
                    self._send_json(200, engine.list_exported_accounts(limit=limit_val))
                elif path == "/api/channels-exports":
                    limit_val = int((query.get("limit") or ["20"])[0])
                    self._send_json(200, engine.list_exported_channels(limit=limit_val))
                elif path == "/api/ui-schema":
                    self._send_json(200, engine.get_ui_schema())
                elif path == "/api/ui-state":
                    ocr_flag = str((query.get("refresh_ocr") or ["0"])[0]).lower() in ("1", "true", "yes")
                    self._send_json(200, engine.inspect_ui_state(refresh_ocr=ocr_flag))
                elif path == "/api/human-guard":
                    self._send_json(200, engine.get_human_guard_status())
                elif path == "/api/hosting":
                    friends_doc = engine.hosting_friends()
                    res = {
                        "ok": True,
                        "hosting": friends_doc.get("hosting", {}),
                        "friends": friends_doc.get("friends", []),
                    }
                    self._send_json(200, res)
                elif path == "/api/permissions":
                    self._send_json(200, engine.permissions_status())
                elif path == "/api/llm-gateway/relaunch":
                    self._send_json(200, engine.relaunch_llm_gateway())
                elif path == "/api/avatar":
                    res = engine.avatar_capture(
                        target=str(body.get("target") or ""),
                        snapshot_path=str(body.get("snapshot_path") or ""),
                        crop=body.get("crop") if isinstance(body.get("crop"), dict) else None,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/history-import":
                    source_dir = (query.get("source_dir") or [None])[0]
                    self._send_json(200, engine.list_history_sources(source_dir=source_dir))
                elif path == "/api/soul-profiles":
                    t_filter = (query.get("target") or [None])[0]
                    rebuild_flag = str((query.get("rebuild") or ["0"])[0]).lower() in ("1", "true", "yes")
                    self._send_json(200, engine.get_soul_profiles(target=t_filter, rebuild=rebuild_flag))
                elif path == "/api/benchmark":
                    self._send_json(200, engine.get_benchmark_report())
                elif path == "/api/vision-stack":
                    self._send_json(200, engine.get_vision_stack_info())
                elif path == "/api/agent-tasks":
                    self._send_json(200, engine.get_agent_tasks(limit=25))
                elif path == "/api/media-analyses":
                    self._send_json(200, engine.get_media_analyses(limit=25))
                elif path == "/api/botstudio-bridge":
                    self._send_json(200, engine.get_botstudio_bridge_status())
                elif path == "/api/crm/overview":
                    auto_sync = str((query.get("auto_sync") or ["1"])[0]).lower() not in ("0", "false", "no")
                    self._send_json(200, engine.crm_overview(auto_sync=auto_sync))
                elif path == "/api/crm/reminders":
                    self._send_json(200, engine.crm_list_reminders())
                elif path in ("/botstudio-page", "/botstudio-page/") or path.startswith("/botstudio-page/"):
                    pages_root = engine.botstudio_bridge.pages_dir.resolve()
                    rel_name = "index.html"
                    if path.startswith("/botstudio-page/"):
                        tail = unquote(path[len("/botstudio-page/") :]).strip("/")
                        if tail:
                            rel_name = Path(tail).name
                    allowed_mimes = {
                        "index.html": "text/html; charset=utf-8",
                        "agent.md": "text/markdown; charset=utf-8",
                        "agent.json": "application/json; charset=utf-8",
                        "plugin.json": "application/json; charset=utf-8",
                        "llms.txt": "text/plain; charset=utf-8",
                    }
                    if rel_name not in allowed_mimes:
                        self._send_json(404, {"ok": False, "error": f"Unknown botstudio page asset: {rel_name}"})
                        return
                    target = (pages_root / rel_name).resolve()
                    if target.parent != pages_root:
                        self._send_json(404, {"ok": False, "error": "Invalid botstudio page path"})
                        return
                    if not target.is_file():
                        engine.botstudio_bridge.compile_dsh_to_botstudio()
                    if not target.is_file():
                        self._send_json(404, {"ok": False, "error": f"Standalone page asset missing: {rel_name}"})
                        return
                    self._send_bytes(200, target.read_bytes(), allowed_mimes[rel_name])
                    return
                elif path.startswith("/exports/articles/"):
                    rel = unquote(path[len("/exports/articles/") :]).strip("/")
                    parts = [p for p in rel.split("/") if p]
                    if len(parts) != 3 or parts[1] != "assets":
                        self._send_json(404, {"ok": False, "error": "Invalid article asset path"})
                        return
                    slug, _, fname = parts
                    safe_slug = Path(slug).name
                    safe_fname = Path(fname).name
                    if not safe_slug or safe_slug != slug or not safe_fname or safe_fname != fname:
                        self._send_json(404, {"ok": False, "error": "Invalid article asset path"})
                        return
                    assets_root = (engine.article_exporter.export_root / safe_slug / "assets").resolve()
                    candidate = (assets_root / safe_fname).resolve()
                    ext = candidate.suffix.lower()
                    mime_map = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                        ".svg": "image/svg+xml",
                    }
                    if candidate.parent != assets_root or not candidate.is_file() or ext not in mime_map:
                        self._send_json(404, {"ok": False, "error": f"Article asset not found: {safe_fname}"})
                        return
                    self._send_bytes(200, candidate.read_bytes(), mime_map[ext])
                    return
                elif path.startswith("/snapshots/"):
                    raw_name = unquote(path[len("/snapshots/") :]).strip()
                    safe_name = Path(raw_name).name
                    if (
                        not safe_name
                        or safe_name != raw_name
                        or Path(safe_name).suffix.lower() not in (".png", ".jpg", ".jpeg")
                    ):
                        self._send_json(404, {"ok": False, "error": "Invalid snapshot path"})
                        return
                    for base in (engine.inspector.snapshots_dir, engine.plugin_root / "logs"):
                        candidate = (base / safe_name).resolve()
                        if candidate.parent == base.resolve() and candidate.is_file():
                            ctype = "image/jpeg" if candidate.suffix.lower() in (".jpg", ".jpeg") else "image/png"
                            self._send_bytes(200, candidate.read_bytes(), ctype)
                            return
                    self._send_json(404, {"ok": False, "error": f"Snapshot not found: {safe_name}"})
                elif path.startswith("/avatars/"):
                    # 联系人头像静态路由（路径穿越防护同 /snapshots/）
                    raw_name = unquote(path[len("/avatars/"):]).strip()
                    safe_name = Path(raw_name).name
                    if not safe_name or safe_name != raw_name or Path(safe_name).suffix.lower() != ".png":
                        self._send_json(404, {"ok": False, "error": "Invalid avatar path"})
                        return
                    avatar_base = (engine.inspector.snapshots_dir.parent / "avatars").resolve()
                    candidate = (avatar_base / safe_name).resolve()
                    if candidate.parent == avatar_base and candidate.is_file():
                        self._send_bytes(200, candidate.read_bytes(), "image/png")
                        return
                    self._send_json(404, {"ok": False, "error": f"Avatar not found: {safe_name}"})
                elif path == "/doctor":
                    self._send_json(200, engine.doctor())
                elif path == "/status":
                    self._send_json(200, engine.get_status())
                elif path == "/sessions":
                    self._send_json(200, engine.list_sessions())
                elif path == "/messages":
                    self._send_json(200, engine.read_messages())
                else:
                    self._send_json(404, {"ok": False, "error": f"Unknown endpoint: {path}"})
            except StudioPluginUnauthorizedError as exc:
                self._send_json(
                    403,
                    {
                        "ok": False,
                        "error_code": exc.code,
                        "capability": exc.capability,
                        "error": str(exc),
                        "authorization": engine.auth_gate.get_state(),
                    },
                )

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path.startswith("/api/workbench/"):
                self._handle_workbench(path, post=True)
                return
            if preview_secret is not None:
                self._send_json(404, {"ok": False})
                return
            if path == "/api/background-observation":
                self._handle_background_observation(post=True)
                return
            try:
                body = self._read_json()
                if path == "/api/auth-toggle":
                    action = str(body.get("action") or "grant").strip().lower()
                    if action == "revoke":
                        res = engine.auth_revoke(reason=str(body.get("reason") or "Revoked via Web Control Console"))
                        if res.get("ok"):
                            background.stop()
                    else:
                        caps = body.get("capabilities") or ALL_CAPABILITIES
                        res = engine.auth_grant(
                            caps,
                            authorized_by=str(body.get("authorized_by") or "web-console-user"),
                            note=str(body.get("note") or "Authorized from Web Control Console"),
                        )
                    self._send_json(200, res)
                elif path == "/api/special-care":
                    res = engine.set_special_care(
                        str(body.get("target") or ""),
                        enabled=bool(body.get("enabled", True)),
                        care_level=body.get("care_level"),
                        care_tags=body.get("care_tags"),
                        follow_up_days=body.get("follow_up_days"),
                        notes=body.get("notes"),
                    )
                    self._send_json(200, res)
                elif path == "/api/persona-switch":
                    res = engine.persona_switch(
                        str(body.get("target") or ""),
                        str(body.get("persona_id") or "warm-friend"),
                        mbti=body.get("mbti"),
                        interaction_style=body.get("interaction_style"),
                        custom_note=str(body.get("note") or ""),
                    )
                    self._send_json(200, res)
                elif path == "/api/takeover":
                    action = str(body.get("action") or "takeover").strip().lower()
                    if action == "resume":
                        res = engine.resume_contact(str(body.get("target") or ""))
                    else:
                        res = engine.takeover_contact(
                            str(body.get("target") or ""),
                            reason=str(body.get("reason") or "Web console human takeover"),
                        )
                    self._send_json(200, res)
                elif path == "/api/hosting":
                    action = str(body.get("action") or "enable").strip().lower()
                    targets_raw = body.get("targets")
                    targets = [str(t) for t in targets_raw if str(t).strip()] if isinstance(targets_raw, list) else []
                    if action == "disable":
                        disable_replies = bool(body.get("disable_replies"))
                        res = engine.stop_hosting(targets=targets, disable_replies=disable_replies)
                        status = 200 if res.get("ok") else 400
                    elif action == "enable":
                        res = engine.start_hosting(targets)
                        status = 200 if res.get("ok") else 400
                    else:
                        res = {"ok": False, "error": "UNSUPPORTED_HOSTING_ACTION"}
                        status = 400
                    self._send_json(status, res)
                elif path == "/api/history-import":
                    res = engine.import_histories(
                        source_dir=body.get("source_dir") or None,
                        targets=body.get("targets") if isinstance(body.get("targets"), list) else None,
                        import_all=bool(body.get("import_all")),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/reply-preview":
                    res = engine.preview_smart_reply(
                        str(body.get("target") or ""),
                        str(body.get("incoming_text") or ""),
                        persona_override=body.get("persona_override") or None,
                        model_id=body.get("model_id") or None,
                        use_llm=body.get("use_llm") if "use_llm" in body else None,
                    )
                    self._send_json(200, res)
                elif path == "/api/model-select":
                    res = engine.select_model(
                        model_id=str(body.get("model_id") or ""),
                        contact=body.get("contact") or None,
                        provider_id=body.get("provider_id") or None,
                        fallback_model_id=body.get("fallback_model_id") or None,
                        llm_enabled=body.get("llm_enabled") if "llm_enabled" in body else None,
                    )
                    self._send_json(200, res)
                elif path == "/api/model-probe":
                    res = engine.probe_model(
                        model_id=body.get("model_id") or None,
                        provider_id=body.get("provider_id") or None,
                        prompt=str(body.get("prompt") or "请用不超过20个字回复：收到测试，状态正常。"),
                    )
                    self._send_json(200 if res.get("ok") else 502, res)
                elif path == "/api/provider-save":
                    res = engine.save_provider(
                        provider_id=body.get("provider_id") or None,
                        name=str(body.get("name") or ""),
                        base_url=str(body.get("base_url") or ""),
                        api=str(body.get("api") or "openai-completions"),
                        api_key=body.get("api_key") if "api_key" in body else None,
                        api_key_env=body.get("api_key_env") if "api_key_env" in body else None,
                        default_model=str(body.get("default_model") or ""),
                        vendor=str(body.get("vendor") or "Custom"),
                        enabled=bool(body.get("enabled", True)),
                        gateway_url=body.get("gateway_url") or None,
                    )
                    self._send_json(200, res)
                elif path == "/api/watch-once":
                    res = engine.monitor_once(
                        target=body.get("target") or None,
                        auto_reply=bool(body.get("auto_reply", True)),
                        confirm_send=bool(body.get("confirm_send", False)),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/activate-wechat":
                    res = engine.activate_wechat()
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/export-article":
                    res = engine.export_article(
                        url=body.get("url") or None,
                        from_window=bool(body.get("fromWindow", body.get("from_window", True))),
                        max_scroll_pages=int(body.get("maxScrollPages", body.get("max_scroll_pages", 4))),
                        download_images=bool(body.get("downloadImages", body.get("download_images", True))),
                        try_copy_link=bool(body.get("tryCopyLink", body.get("try_copy_link", True))),
                        output_dir=body.get("outputDir") or body.get("output_dir") or None,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/account-exports":
                    urls_raw = body.get("articleUrls", body.get("article_urls"))
                    if isinstance(urls_raw, str):
                        urls_list = [line.strip() for line in urls_raw.splitlines() if line.strip()]
                    else:
                        urls_list = urls_raw
                    res = engine.export_account_articles(
                        account_name=str(body.get("accountName") or body.get("account_name") or ""),
                        album_url=str(body.get("albumUrl") or body.get("album_url") or ""),
                        album_html=str(body.get("albumHtml") or body.get("album_html") or ""),
                        article_urls=urls_list,
                        articles_html_list=body.get("articlesHtmlList") or body.get("articles_html_list"),
                        from_file=body.get("fromFile") or body.get("from_file") or None,
                        scan_open_window=bool(body.get("scanOpenWindow", body.get("scan_open_window", False))),
                        scroll_pages=int(body.get("scrollPages", body.get("scroll_pages", 4))),
                        download_images=bool(body.get("downloadImages", body.get("download_images", True))),
                        max_articles=int(body.get("maxArticles", body.get("max_articles", 50))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/channels-exports":
                    vurls_raw = body.get("videoUrls", body.get("video_urls"))
                    if isinstance(vurls_raw, str):
                        vurls_list = [line.strip() for line in vurls_raw.splitlines() if line.strip()]
                    else:
                        vurls_list = vurls_raw
                    res = engine.export_channels_videos(
                        author_name=str(body.get("authorName") or body.get("author_name") or ""),
                        video_items=body.get("videoItems") or body.get("video_items"),
                        video_urls=vurls_list,
                        manifest_path=body.get("manifestPath") or body.get("manifest_path") or None,
                        cache_dir=body.get("cacheDir") or body.get("cache_dir") or None,
                        scan_open_window=bool(body.get("scanOpenWindow", body.get("scan_open_window", False))),
                        scroll_pages=int(body.get("scrollPages", body.get("scroll_pages", 4))),
                        download_media=bool(body.get("downloadMedia", body.get("download_media", True))),
                        max_videos=int(body.get("maxVideos", body.get("max_videos", 50))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/ui-navigate":
                    res = engine.navigate_ui(
                        str(body.get("targetId") or body.get("target_id") or ""),
                        dry_run=bool(body.get("dryRun", body.get("dry_run", True))),
                        respect_human_guard=bool(body.get("respectHumanGuard", body.get("respect_human_guard", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/human-guard":
                    res = engine.configure_human_guard(
                        enabled=body.get("enabled"),
                        idle_resume_seconds=body.get("idleResumeSeconds", body.get("idle_resume_seconds")),
                        cooldown_seconds=body.get("cooldownSeconds", body.get("cooldown_seconds")),
                        reset_cooldown=bool(body.get("resetCooldown", body.get("reset_cooldown", False))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/soul-profiles/rebuild":
                    res = engine.get_soul_profiles(
                        target=body.get("target") or None,
                        rebuild=True,
                        use_llm=bool(body.get("useLlm", body.get("use_llm", False))),
                        model_id=body.get("modelId") or body.get("model_id") or None,
                    )
                    self._send_json(200, res)
                elif path == "/api/memory-add":
                    res = engine.add_soul_memory(
                        str(body.get("target") or ""),
                        str(body.get("content") or ""),
                        category=str(body.get("category") or "fact"),
                        time_marker=str(body.get("timeMarker") or body.get("time_marker") or ""),
                    )
                    self._send_json(200, res)
                elif path == "/api/benchmark/run":
                    res = engine.run_benchmark(include_tests=bool(body.get("includeTests", body.get("include_tests", False))))
                    self._send_json(200, res)
                elif path == "/api/bind-agent":
                    target = str(body.get("target") or "")
                    existing = engine.bindings.get_binding(target) or {}
                    res = engine.bind_contact(
                        target,
                        alias=str(body.get("alias", existing.get("alias", ""))),
                        role=str(body.get("role", existing.get("role", "friend"))),
                        ai_persona=str(body.get("ai_persona", existing.get("aiPersona", "warm-companion"))),
                        scheduled_enabled=bool(body.get("scheduled_enabled", existing.get("scheduledEnabled", True))),
                        cron_hint=str(body.get("cron_hint", existing.get("cronHint", "0 9,21 * * *"))),
                        auto_reply_enabled=bool(body.get("auto_reply_enabled", existing.get("autoReplyEnabled", True))),
                        notes=str(body.get("notes", existing.get("notes", ""))),
                        bound_agent_id=body.get("boundAgentId") or body.get("bound_agent_id") or body.get("agentId") or body.get("agent_id"),
                        bound_agent_name=body.get("boundAgentName") or body.get("bound_agent_name") or body.get("agentName") or body.get("agent_name"),
                        bound_agent_type=body.get("boundAgentType") or body.get("bound_agent_type") or body.get("agentType") or body.get("agent_type"),
                        vision_model_id=body.get("visionModelId") or body.get("vision_model_id") or body.get("visionModel"),
                        auto_dispatch_instructions=body.get("autoDispatchInstructions") if "autoDispatchInstructions" in body else body.get("auto_dispatch_instructions"),
                        auto_analyze_links_and_media=body.get("autoAnalyzeLinksAndMedia") if "autoAnalyzeLinksAndMedia" in body else body.get("auto_analyze_links_and_media"),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/analyze-media":
                    res = engine.analyze_media_or_link(
                        kind=str(body.get("kind", "link")),
                        url=body.get("url"),
                        image_path=body.get("imagePath") or body.get("image_path"),
                        video_path=body.get("videoPath") or body.get("video_path"),
                        video_url=body.get("videoUrl") or body.get("video_url"),
                        crop_region=body.get("cropRegion") or body.get("crop_region"),
                        from_viewer_window=bool(body.get("fromViewerWindow", body.get("from_viewer_window", False))),
                        source_snapshot=body.get("sourceSnapshot") or body.get("source_snapshot"),
                        window_title=str(body.get("windowTitle") or body.get("window_title") or "图片和视频"),
                        contact=str(body.get("contact", "")),
                        context_text=str(body.get("contextText") or body.get("context_text") or ""),
                        frame_count=int(body.get("frameCount", body.get("frame_count", 3))),
                        model_id=str(body.get("modelId") or body.get("model_id") or "auto/deepseek-v4.1-flash"),
                        allow_loopback=bool(body.get("allowLoopback", body.get("allow_loopback", False))),
                        html_override=body.get("htmlOverride") or body.get("html_override"),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/agent-dispatch":
                    res = engine.dispatch_friend_instructions(
                        str(body.get("target") or body.get("contact") or ""),
                        include_live_media=bool(body.get("includeLiveMedia", body.get("include_live_media", True))),
                        execute_with_agent=bool(body.get("executeWithAgent", body.get("execute_with_agent", True))),
                        extra_messages=body.get("extraMessages") or body.get("extra_messages"),
                        model_id=body.get("modelId") or body.get("model_id"),
                        html_overrides=body.get("htmlOverrides") or body.get("html_overrides"),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/dock-sidebar":
                    mode = str(body.get("mode") or "dock")
                    res = engine.dock_app_to_wechat(mode=mode)
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/botstudio-bridge":
                    action = str(body.get("action") or "export_bundle").strip().lower()
                    if action in ("rebuild_app", "compile_all"):
                        res = engine.rebuild_standalone_app(
                            install_to_host=bool(body.get("installToHost", body.get("install_to_host", True))),
                        )
                    elif action == "install":
                        res = engine.install_to_host(
                            launch_standalone=bool(body.get("launchStandalone", False)),
                            launch_bot_studio=bool(body.get("launchBotStudio", False)),
                        )
                    elif action == "compile_dsh":
                        res = engine.compile_dsh_plugin_for_botstudio()
                    elif action == "status":
                        res = engine.get_botstudio_bridge_status()
                    else:
                        res = engine.export_botstudio_integration_bundle(out_path=body.get("outPath") or None)
                    self._send_json(200, res)
                elif path == "/api/kb-search":
                    res = engine.kb_search(
                        str(body.get("query") or ""),
                        kind=body.get("kind") or None,
                        library=body.get("library") or None,
                        limit=int(body.get("limit", 12)),
                    )
                    self._send_json(200, res)
                elif path == "/api/kb-save":
                    res = engine.kb_save(
                        title=str(body.get("title") or ""),
                        body=str(body.get("body") or ""),
                        kind=str(body.get("kind") or "knowledge"),
                        library=str(body.get("library") or "shared"),
                        keywords=body.get("keywords"),
                        synonyms=body.get("synonyms"),
                        source=str(body.get("source") or "web-console"),
                    )
                    self._send_json(200, res)
                elif path == "/api/kb-sync":
                    src_db = Path(str(body["source_db"])) if body.get("source_db") else None
                    res = engine.kb_sync_openbot(src_db)
                    self._send_json(200, res)
                elif path == "/inspect-live":
                    res = engine.inspect_live_wechat(
                        max_session_pages=int(body.get("max_session_pages", 2)),
                        max_contact_pages=int(body.get("max_contact_pages", 4)),
                    )
                    self._send_json(200, res)
                elif path == "/ocr":
                    img = body.get("image_path")
                    res = engine.ocr_image(Path(img)) if img else engine.ocr_wechat_window()
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/send":
                    res = engine.send_text(
                        target=str(body.get("target", "")),
                        text=str(body.get("text", "")),
                        dry_run=bool(body.get("dry_run", True)),
                        silent_mode=bool(body.get("silent_mode", True)),
                        confirm_send=bool(body.get("confirm_send", False)),
                        allowed_groups=body.get("allowed_groups"),
                    )
                    # 人工手动发送标记：成功且真发时写事件，供历史回写把它标为 self/人工
                    if res.get("ok") and not bool(body.get("dry_run", True)) and bool(body.get("confirm_send", False)):
                        try:
                            engine.monitor._append_event("manual_send", {
                                "target": str(body.get("target", "")),
                                "replyText": str(body.get("text", ""))[:200],
                                "actor": "human",
                            })
                        except Exception:
                            pass
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/import-chatlog":
                    src = Path(str(body["source_path"]))
                    out = Path(str(body["output_dir"])) if body.get("output_dir") else None
                    res = engine.import_chatlog(src, output_dir=out)
                    self._send_json(200, res)
                elif path == "/api/import-chatlog-file":
                    res = engine.import_chatlog_to_histories(
                        source_path=str(body.get("source_path") or ""),
                        target=str(body.get("target") or ""),
                        owner_name=str(body.get("owner_name") or ""),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path.startswith("/api/crm/"):
                    try:
                        if path == "/api/crm/sync":
                            self._send_json(200, engine.crm_sync_from_wechat())
                        elif path == "/api/crm/enroll":
                            raw_dv = body.get("deal_value") if body.get("deal_value") is not None else body.get("dealValue")
                            self._send_json(
                                200,
                                engine.crm_enroll_contact(
                                    str(body.get("target") or ""),
                                    stage=str(body.get("stage") or "新线索"),
                                    note=str(body.get("note") or ""),
                                    follow_up=body.get("follow_up") if "follow_up" in body else body.get("followUp"),
                                    deal_value=float(raw_dv or 0.0),
                                    alias=str(body.get("alias") or ""),
                                    tags=body.get("tags") if isinstance(body.get("tags"), list) else None,
                                ),
                            )
                        elif path == "/api/crm/update":
                            raw_dv = body.get("deal_value") if body.get("deal_value") is not None else body.get("dealValue")
                            self._send_json(
                                200,
                                engine.crm_update_record(
                                    str(body.get("target") or ""),
                                    stage=str(body.get("stage") or "跟进中"),
                                    note=str(body.get("note") or ""),
                                    follow_up=body.get("follow_up") if "follow_up" in body else body.get("followUp"),
                                    deal_value=float(raw_dv) if raw_dv is not None else None,
                                ),
                            )
                        elif path == "/api/crm/reminder-action":
                            act = str(body.get("action") or "complete").strip().lower()
                            target = str(body.get("target") or "")
                            if act == "reschedule":
                                fu = str(body.get("follow_up") or body.get("followUp") or "")
                                self._send_json(200, engine.crm_reschedule_reminder(target, fu))
                            else:
                                self._send_json(200, engine.crm_complete_reminder(target))
                        elif path == "/api/crm/analyze":
                            ov = body.get("formula_overrides") or body.get("overrides")
                            self._send_json(
                                200,
                                engine.crm_analyze_contact(
                                    str(body.get("target") or "联系人A"),
                                    incoming_text=str(body.get("incoming_text") or body.get("incomingText") or ""),
                                    formula_overrides=ov if isinstance(ov, dict) else None,
                                ),
                            )
                        elif path == "/api/crm/formulas":
                            ov = body.get("overrides") or body.get("formula_overrides")
                            self._send_json(
                                200,
                                engine.crm_evaluate_formulas(
                                    str(body.get("target") or "联系人A"),
                                    overrides=ov if isinstance(ov, dict) else None,
                                ),
                            )
                        elif path == "/api/crm/adopt-draft":
                            self._send_json(
                                200,
                                engine.crm_adopt_draft(
                                    str(body.get("target") or "联系人A"),
                                    rank_index=int(body.get("rank_index") or body.get("rank") or 1),
                                    send_mode=str(body.get("send_mode") or body.get("sendMode") or "adopt_only"),
                                ),
                            )
                        elif path == "/api/crm/merge":
                            self._send_json(
                                200,
                                engine.crm_merge_accounts(
                                    str(body.get("target") or ""),
                                    str(body.get("secondary_target") or body.get("secondaryTarget") or ""),
                                    alias=str(body.get("alias") or ""),
                                ),
                            )
                        else:
                            self._send_json(404, {"ok": False, "error": f"Unknown CRM endpoint: {path}"})
                    except ValueError as exc:
                        self._send_json(400, {"ok": False, "error": str(exc)})
                else:
                    self._send_json(404, {"ok": False, "error": f"Unknown endpoint: {path}"})
            except StudioPluginUnauthorizedError as exc:
                self._send_json(
                    403,
                    {
                        "ok": False,
                        "error_code": exc.code,
                        "capability": exc.capability,
                        "error": str(exc),
                        "authorization": engine.auth_gate.get_state(),
                    },
                )
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})

    class LocalServer(ThreadingHTTPServer):
        def shutdown(self) -> None:
            super().shutdown()
            background.close()

        def server_close(self) -> None:
            background.close()
            super().server_close()

    return LocalServer((host, port), Handler)


def serve_http(engine: WeChatControlEngine, host: str = "127.0.0.1", port: int = 18788) -> None:
    """Serve the local Web Control Console & HTTP REST JSON API indefinitely."""
    server = create_http_server(engine, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
