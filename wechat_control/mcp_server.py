"""Standard MCP (Model Context Protocol) JSON-RPC 2.0 stdio server + HTTP JSON API."""

from __future__ import annotations

import hmac
from html import escape as _escape_html
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .auth_gate import ALL_CAPABILITIES, StudioPluginUnauthorizedError
from .background_observer import BackgroundObserver
from .engine import WeChatControlEngine
from .io_utils import atomic_write_text
from .saved_drafts import SavedDraftError, SavedDraftStore

def _maybe_unquote_target(t: str) -> str:
    """服务端兜底：前端某些旧入口可能传 URL 编码的 target，统一解码。"""
    from urllib.parse import unquote
    t = str(t or "").strip()
    if "%" in t:
        try:
            dec = unquote(t)
            if dec != t and "%" not in dec:
                return dec
        except Exception:
            pass
    return t
from .web_console import render_mobile_remote_html, render_web_console_html
from .workbench import ReviewLedger, Workbench, WorkbenchError
from .workbench_library import records as workbench_records


def _render_user_guide_fallback_html(engine: WeChatControlEngine) -> str:
    """Render a clean friendly fallback HTML guide when docs/user-guide.html is absent."""
    md_res = engine.get_user_guide_markdown()
    md_text = str(md_res.get("markdown") or "").strip()
    if md_text:
        body_block = (
            '<pre style="white-space:pre-wrap;word-break:break-word;font-family:inherit;'
            'line-height:1.75;background:rgba(128,128,128,0.08);padding:20px;border-radius:12px;">'
            f"{_escape_html(md_text)}</pre>"
        )
    else:
        body_block = (
            '<div style="padding:24px;border-radius:12px;background:rgba(128,128,128,0.08);">'
            "<p>本地网页版使用手册正在准备中。您可以直接返回控制台查看内置使用手册，或访问在线网页版手册。</p>"
            "</div>"
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        "  <title>WeChat Bot 使用手册</title>\n"
        '  <style>:root{color-scheme:light dark;}body{max-width:860px;margin:0 auto;padding:28px 20px;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif;line-height:1.7;}header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid rgba(128,128,128,0.25);}a.btn{display:inline-block;padding:6px 12px;border-radius:8px;border:1px solid rgba(128,128,128,0.35);text-decoration:none;color:inherit;font-size:13px;}</style>\n'
        "</head>\n"
        "<body>\n"
        "  <header>\n"
        '    <h1 style="margin:0;font-size:22px;">📖 WeChat Bot 使用手册</h1>\n'
        '    <div style="display:flex;gap:8px;flex-wrap:wrap;">\n'
        '      <a class="btn" href="/">返回控制台</a>\n'
        '      <a class="btn" href="https://harzva.github.io/app-use/user-guide.html" target="_blank" rel="noopener">🔗 在线网页版</a>\n'
        "    </div>\n"
        "  </header>\n"
        f"  <main>{body_block}</main>\n"
        "</body>\n"
        "</html>\n"
    )

MCP_PROTOCOL_VERSION = "2024-11-05"
def _read_plugin_version() -> str:
    """单一事实源：版本统一从 plugin.manifest.json 读取（build 脚本强制四处一致）。"""
    try:
        manifest = Path(__file__).resolve().parent.parent / "plugin.manifest.json"
        return str(json.loads(manifest.read_text()).get("version") or "?")
    except Exception:
        return "?"


SERVER_INFO = {
    "name": "openbot-wechat-rpa-control",
    "version": _read_plugin_version(),
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
        "name": "wechat_consult_ai_assistant",
        "description": "Consult WeChat native AI assistants (@元宝 in chat or forward/relay to 小微/元宝 session) to summarize shared links, Channels videos, and Official Account articles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "default": ""},
                "content_hint": {"type": "string", "default": ""},
                "assistant": {"type": "string", "enum": ["auto", "yuanbao", "xiaowei"], "default": "auto"},
                "mode": {"type": "string", "enum": ["auto", "at_yuanbao", "relay_xiaowei"], "default": "auto"},
                "wait_seconds": {"type": "number", "default": 5.5},
                "dry_run": {"type": "boolean", "default": False},
                "model_id": {"type": "string", "default": "auto/deepseek-v4.1-flash"},
            },
            "required": [],
        },
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
        "name": "wechat_voice_call",
        "description": "Place, join an active call, answer, inspect, or hang up a native WeChat, WeCom, Feishu, or DingTalk VoIP voice/video call with live AI voice dialogue and safe mic restore.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "default": ""},
                "action": {"type": "string", "enum": ["dial", "join", "answer", "hangup", "status"], "default": "dial"},
                "app": {"type": "string", "enum": ["wechat", "wecom", "feishu", "dingtalk", "all"], "default": "wechat"},
                "call_type": {"type": "string", "enum": ["audio", "video"], "default": "audio"},
                "greeting": {"type": "string", "default": ""},
                "instructions": {"type": "string", "default": ""},
                "auto_voice_agent": {"type": "boolean", "default": True},
                "dry_run": {"type": "boolean", "default": False},
                "confirm_send": {"type": "boolean", "default": False},
                "target_window_id": {"type": "integer"},
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
        "name": "wechat_moments_read",
        "description": "Scroll the WeChat Moments (朋友圈) feed from the newest post and store the posts seen (author, text, time, likes, comments). Read-only; returns WeChat to the chat view afterwards.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_posts": {"type": "integer", "default": 40},
                "max_pages": {"type": "integer", "default": 90},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_moments_posts",
        "description": "List stored Moments posts (newest first), optionally for one contact, or fetch one by post_key.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 30},
                "author": {"type": "string", "default": ""},
                "post_key": {"type": "string", "default": ""},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_moments_stats",
        "description": "Per-contact Moments statistics: posts seen, likes and comments given/received, recent posts still awaiting a like, plus rate-limiter and policy state.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 40}},
            "required": [],
        },
    },
    {
        "name": "wechat_moments_policy",
        "description": "Read the Moments auto-interaction policy, or update it by passing a partial `updates` object (autoLike.enabled / scope / contacts / exclude / maxAgeDays, comment.enabled / templates).",
        "inputSchema": {
            "type": "object",
            "properties": {"updates": {"type": "object", "default": None}},
            "required": [],
        },
    },
    {
        "name": "wechat_moments_plan",
        "description": "List the Moments interactions the policy allows (likes to give, comment templates), for review before executing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "max_age_days": {"type": "integer", "default": None},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_moments_interact",
        "description": "Like / unlike / comment on a Moments post. Defaults to dry_run: opens the post's 赞/评论 menu, verifies it is where expected and stops. silent_verify pastes the comment and reads it back without sending. live sends and requires the moments_interact_live grant.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "post_key": {"type": "string", "default": ""},
                "author": {"type": "string", "default": ""},
                "action": {"type": "string", "enum": ["like", "unlike", "comment"], "default": "like"},
                "text": {"type": "string", "default": ""},
                "mode": {"type": "string", "enum": ["dry_run", "silent_verify", "live"], "default": "dry_run"},
                "execute_plan": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 5},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_moments_suggest_comment",
        "description": "Generate a natural, spoken-style Moments comment suggestion (plus 2 alternatives) for a stored post key using Soul profile and post context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "post_key": {"type": "string", "default": "", "description": "Stored Moments post key (mom_xxx)."},
                "style": {"type": "string", "default": "natural"},
            },
            "required": ["post_key"],
        },
    },
    {
        "name": "wechat_call_brief",
        "description": "Generate a pre-call brief and spoken phone script card for a WeChat contact by aggregating chat history, Soul memory, Moments posts, bindings, and SalesCRM data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Contact display name or remark."},
                "goal": {
                    "type": "string",
                    "enum": ["general", "followup", "quote", "care", "recovery", "custom"],
                    "default": "general",
                },
                "custom_goal": {"type": "string", "default": ""},
                "use_llm": {"type": "boolean", "default": True},
            },
            "required": ["target"],
        },
    },
    {
        "name": "wechat_salescrm_analyze",
        "description": "Run Aurora-73/SalesCRM 15-dimensional quantitative analysis, stage recognition, timeline detection, and Top 1-3 follow-up draft generation for a WeChat contact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "default": "心安"},
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
                "target": {"type": "string", "default": "心安"},
                "overrides": {"type": "object", "default": {}},
            },
            "required": ["target"],
        },
    },
    {
        "name": "omni_channels_status",
        "description": "List all 6 channels (Feishu/Lark, DingTalk, Xiaohongshu, Douyin, WeChat, WeCom), installed desktop/web/open-source capabilities, and optional live probe.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "default": "all"},
                "probe_live": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "omni_channel_inspect",
        "description": "Inspect sessions, comments, or visible messages for Feishu, DingTalk, Xiaohongshu, Douyin, WeChat, or WeCom.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "default": "feishu"},
                "action": {"type": "string", "enum": ["sessions", "messages"], "default": "sessions"},
                "target": {"type": "string", "default": ""},
                "query": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 20},
                "launch_if_needed": {"type": "boolean", "default": False},
            },
            "required": ["channel"],
        },
    },
    {
        "name": "omni_channel_send",
        "description": "Safely send or dry-run verify a message/reply on Feishu, DingTalk, Xiaohongshu, Douyin, WeChat, or WeCom (via Desktop RPA, ego-browser web RPA, or HMAC Webhook/OpenAPI).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "target": {"type": "string", "default": ""},
                "text": {"type": "string"},
                "mode": {"type": "string", "enum": ["auto", "rpa", "web", "webhook", "open_api"], "default": "auto"},
                "dry_run": {"type": "boolean", "default": True},
                "confirm_send": {"type": "boolean", "default": False},
            },
            "required": ["channel", "text"],
        },
    },
    {
        "name": "omni_channel_leads",
        "description": "Extract commercial intent leads from Feishu, DingTalk, Xiaohongshu, or Douyin interactions and optionally enroll hot/warm leads into SalesCRM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "target": {"type": "string", "default": ""},
                "query": {"type": "string", "default": ""},
                "sync_crm": {"type": "boolean", "default": True},
            },
            "required": ["channel"],
        },
    },
    {
        "name": "app_use_list_apps",
        "description": "Discover running and installed macOS applications across System, Applications, User, and SanDisk, automatically tagging AI Agent Apps vs standard productivity apps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_installed": {"type": "boolean", "default": True},
                "category": {"type": "string", "enum": ["all", "agent_app", "productivity", "im_social", "dev_tool", "browser"], "default": "all"},
                "running_only": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "app_use_list_agents",
        "description": "List all selectable Agent backends (Magpie multi-model routing groups, custom providers, local CLI agents, and offline AX+OCR heuristic planner) for App-Use SOP synthesis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "refresh_models": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "app_use_inspect",
        "description": "Inspect live AXUIElement controls, inputs, buttons, window geometry, and Apple Vision OCR text of ANY macOS app (including Agent Apps) by bundle_id or app_name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bundle_id": {"type": "string", "default": ""},
                "app_name": {"type": "string", "default": ""},
                "app_path": {"type": "string", "default": ""},
                "launch_if_needed": {"type": "boolean", "default": False},
                "allow_activate": {"type": "boolean", "default": True},
                "max_nodes": {"type": "integer", "default": 350},
            },
            "required": [],
        },
    },
    {
        "name": "app_use_build_sop",
        "description": "Use any chosen Agent backend (Magpie model, local CLI agent, or heuristic planner) to automatically generate BOTH a structured SOP Markdown and an executable RPA Workflow JSON for any macOS app.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "bundle_id": {"type": "string", "default": ""},
                "app_name": {"type": "string", "default": ""},
                "app_path": {"type": "string", "default": ""},
                "agent_id": {"type": "string", "default": ""},
                "provider_id": {"type": "string"},
                "custom_agent_prompt": {"type": "string", "default": ""},
                "inspect_live": {"type": "boolean", "default": True},
                "launch_if_needed": {"type": "boolean", "default": False},
                "attach_screenshot": {"type": "boolean", "default": False},
                "save": {"type": "boolean", "default": True},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "app_use_run_workflow",
        "description": "Validate (dry_run=true) or live-execute (dry_run=false, confirm_run=true) a saved or ad-hoc App-Use RPA workflow with HumanActivityGuard protection, OCR/AX readback, output capture, and runtime self-healing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "workflow": {"type": "object"},
                "params": {"type": "object"},
                "dry_run": {"type": "boolean", "default": True},
                "confirm_run": {"type": "boolean", "default": False},
                "respect_human_guard": {"type": "boolean", "default": True},
                "self_heal": {"type": "boolean", "default": True},
                "auto_patch_workflow": {"type": "boolean", "default": False},
                "heal_agent_id": {"type": "string", "default": ""},
                "dispatch_mode": {"type": "string", "enum": ["auto", "headless_ax_first", "foreground_hid_only"], "default": "auto"},
            },
            "required": [],
        },
    },
    {
        "name": "app_use_explore_and_build",
        "description": "Autonomously observe, plan, act (when dry_run=false and confirm_run=true), verify, and compile a reusable App-Use SOP + parameterized workflow on a macOS desktop app.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "bundle_id": {"type": "string"},
                "app_name": {"type": "string"},
                "app_path": {"type": "string"},
                "agent_id": {"type": "string"},
                "max_turns": {"type": "integer", "default": 6},
                "dry_run": {"type": "boolean", "default": True},
                "confirm_run": {"type": "boolean", "default": False},
                "respect_human_guard": {"type": "boolean", "default": True},
                "launch_if_needed": {"type": "boolean", "default": True},
                "save": {"type": "boolean", "default": True},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "app_use_run_pipeline",
        "description": "Execute a cross-app multi-stage RPA pipeline passing captured output variables ({{var}}) from one macOS app workflow into downstream app stages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pipeline_id": {"type": "string"},
                "pipeline": {"type": "object"},
                "initial_params": {"type": "object"},
                "dry_run": {"type": "boolean", "default": True},
                "confirm_run": {"type": "boolean", "default": False},
                "respect_human_guard": {"type": "boolean", "default": True},
                "self_heal": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    },
    {
        "name": "app_use_record_demo",
        "description": "Start, inspect, or stop-and-compile a human desktop demonstration recorder into a parameterized App-Use SOP + workflow.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "status", "stop_and_compile"],
                    "default": "status",
                },
                "max_duration_sec": {"type": "number", "default": 180.0},
                "poll_interval_sec": {"type": "number", "default": 0.45},
                "target_bundle_id": {"type": "string", "default": ""},
                "goal_hint": {"type": "string", "default": ""},
                "agent_id": {"type": "string", "default": ""},
                "save": {"type": "boolean", "default": True},
            },
            "required": ["action"],
        },
    },
    {
        "name": "app_use_export_skill",
        "description": "Export a saved App-Use workflow and SOP into a portable SKILL.md bundle directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "out_dir": {"type": "string"},
            },
            "required": ["workflow_id"],
        },
    },
    {
        "name": "app_use_generalize_app",
        "description": "4-phase zero-hardcoding generalization pipeline for any unseen macOS app: Inspect+Archetype -> Agent Synthesis -> Trajectory Optimize+Readiness Score -> DryRun+Export SKILL.md.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "bundle_id": {"type": "string"},
                "app_name": {"type": "string"},
                "app_path": {"type": "string"},
                "agent_id": {"type": "string"},
                "mode": {"type": "string", "enum": ["auto", "explore", "synthesize"], "default": "auto"},
                "max_turns": {"type": "integer", "default": 4},
                "launch_if_needed": {"type": "boolean", "default": True},
                "dry_run_verify": {"type": "boolean", "default": True},
                "export_skill": {"type": "boolean", "default": True},
                "save": {"type": "boolean", "default": True},
                "custom_agent_prompt": {"type": "string"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "app_use_state_graph",
        "description": "Inspect the learned App-Use UI transition graph (nodes & verified transitions) for one bundle_id or global summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bundle_id": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "app_use_install_meta_skill",
        "description": "Install or update the global app-use-meta-builder SKILL.md across ~/.agents/skills, Antigravity, Codex, Managed Codex, and OpenCode.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "install_global": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    },
    {
        "name": "app_use_watch_parallel",
        "description": "Concurrently observe multiple desktop app windows without stealing focus (--no-activate) and return UI stateHashes, modal blockers, and inferred archetypes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "targets": {"type": "array", "items": {"type": "object"}},
                "include_ocr": {"type": "boolean", "default": False},
                "max_workers": {"type": "integer", "default": 4},
            },
            "required": ["targets"],
        },
    },
    {
        "name": "app_use_run_parallel",
        "description": "Execute multiple App-Use workflows concurrently with parallel perception/wait and serialized ForegroundHIDLease mutex protection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "jobs": {"type": "array", "items": {"type": "object"}},
                "dry_run": {"type": "boolean", "default": True},
                "confirm_run": {"type": "boolean", "default": False},
                "respect_human_guard": {"type": "boolean", "default": True},
                "self_heal": {"type": "boolean", "default": True},
                "max_workers": {"type": "integer", "default": 4},
                "dispatch_mode": {"type": "string", "enum": ["auto", "headless_ax_first", "foreground_hid_only"], "default": "auto"},
            },
            "required": ["jobs"],
        },
    },
    {
        "name": "app_use_concurrency_status",
        "description": "Get live multi-window App-Use concurrency swimlane telemetry, ForegroundHIDLease contention stats, and anti-ban pacer stats.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "app_use_risk_profile",
        "description": "Inspect anti-ban risk tier classification and recommended dispatch mode for a macOS app (safe_native vs moderate_agent_or_web vs high_risk_social).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bundle_id": {"type": "string", "default": ""},
                "app_name": {"type": "string", "default": ""},
                "app_path": {"type": "string", "default": ""},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_onboarding_status",
        "description": "Get zero-FDE tenant onboarding status, active mode (legacy vs customer), available L1 sales packs, and test contacts.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_onboarding_setup",
        "description": "Complete zero-FDE tenant onboarding: configure owner/business/product, apply industry sales pack, withdraw legacy seeds, and register test contacts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner_name": {"type": "string"},
                "business_name": {"type": "string", "default": ""},
                "product_summary": {"type": "string", "default": ""},
                "industry_pack": {"type": "string", "default": "general_sales"},
                "owner_aliases": {"type": "array", "items": {"type": "string"}},
                "admin_contacts": {"type": "array", "items": {"type": "string"}},
                "test_contacts": {"type": "array", "items": {"type": "string"}},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_sales_packs",
        "description": "List bundled L1/L2 sales packs available for customer onboarding.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wechat_training_discover",
        "description": "Discover high-value WeChat sales conversations and local exported .zip/.txt chat archives for zero-FDE self-training.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "search_dirs": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 20},
                "include_live_sessions": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_training_run",
        "description": "Run self-training pipeline over chat archives/sessions/docs to mine vocabulary, synthesize risk-gated playbooks, and publish safe entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "archive_paths": {"type": "array", "items": {"type": "string"}},
                "contact_targets": {"type": "array", "items": {"type": "string"}},
                "raw_conversations": {"type": "array", "items": {"type": "object"}},
                "doc_texts": {"type": "array", "items": {"type": "object"}},
                "owner_name": {"type": "string"},
                "industry_pack": {"type": "string"},
                "use_llm": {"type": "boolean", "default": False},
                "auto_publish_safe": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_training_approve",
        "description": "Approve and publish risk-flagged draft playbooks from self-training with optional title/body edits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_ids": {"type": "array", "items": {"type": "string"}},
                "edits": {"type": "object"},
            },
            "required": ["entry_ids"],
        },
    },
    {
        "name": "wechat_test_contact",
        "description": "List, mark, or unmark internal test contacts (sandboxed from SalesCRM and allowed `#` supervisor directives).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "add", "remove"], "default": "list"},
                "name": {"type": "string", "default": ""},
                "note": {"type": "string", "default": ""},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_sparring_chat",
        "description": "Run a simulated customer sparring turn without live WeChat UI and return reply + 5D autoScore + turnId.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "contact_name": {"type": "string", "default": "模拟测试客户"},
                "persona_id": {"type": "string"},
                "use_llm": {"type": "boolean"},
                "record": {"type": "boolean", "default": True},
            },
            "required": ["message"],
        },
    },
    {
        "name": "wechat_sparring_regression",
        "description": "Re-run historical `#`-critiqued and low-star sparring turns to verify constraints are no longer violated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "use_llm": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "wechat_supervisor_directive",
        "description": "Execute an authorized `#` supervisor directive (critique rewrite, `#评分`, `#话术`, `#词汇`, `#接管`/`#恢复`).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "default": "模拟测试客户"},
                "text": {"type": "string"},
                "channel": {"type": "string", "default": "workbench"},
                "use_llm": {"type": "boolean", "default": False},
            },
            "required": ["text"],
        },
    },
    {
        "name": "wechat_supervisor_rate",
        "description": "Submit 1-5 star rating, issue tags, and optional rewrite for a sparring turn (adjusts KB weights & constraints).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "turn_id": {"type": "integer"},
                "stars": {"type": "integer"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "comment": {"type": "string", "default": ""},
                "rewritten_reply": {"type": "string", "default": ""},
            },
            "required": ["turn_id", "stars"],
        },
    },
    {
        "name": "wechat_quality_dashboard",
        "description": "Get 1-5 star rating distribution, 5D auto-score averages, top issue tags, and KB entry quality weights.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7}},
            "required": [],
        },
    },
    {
        "name": "wechat_user_guide",
        "description": "Read the user-facing operation manual (docs/USER_GUIDE.md).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
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
        if name == "wechat_consult_ai_assistant":
            return self.engine.consult_wechat_assistant(
                target=str(args.get("target") or args.get("contact") or ""),
                content_hint=str(args.get("content_hint") or args.get("text") or args.get("url") or ""),
                assistant=str(args.get("assistant") or "auto"),
                mode=str(args.get("mode") or "auto"),
                bubbles=args.get("bubbles"),
                wait_seconds=float(args.get("wait_seconds", 5.5)),
                dry_run=bool(args.get("dry_run", False)),
                model_id=str(args.get("model_id") or "auto/deepseek-v4.1-flash"),
            )
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
        if name == "wechat_voice_call":
            return self.engine.voice_call(
                target=str(args.get("target") or ""),
                action=str(args.get("action") or "dial"),
                app=str(args.get("app") or "wechat"),
                call_type=str(args.get("call_type") or "audio"),
                greeting=str(args.get("greeting") or ""),
                instructions=str(args.get("instructions") or ""),
                auto_voice_agent=bool(args.get("auto_voice_agent", True)),
                dry_run=bool(args.get("dry_run", False)),
                confirm_send=bool(args.get("confirm_send", False)),
                target_window_id=int(args["target_window_id"]) if args.get("target_window_id") else None,
            )
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
        if name == "wechat_moments_read":
            return self.engine.moments_read_feed(
                max_posts=int(args.get("max_posts", 40)), max_pages=int(args.get("max_pages", 90))
            )
        if name == "wechat_moments_posts":
            if args.get("post_key"):
                return self.engine.moments.get_post(str(args.get("post_key")))
            return self.engine.moments_list_posts(
                limit=int(args.get("limit", 30)), author=str(args.get("author") or "")
            )
        if name == "wechat_moments_stats":
            return self.engine.moments_stats(limit=int(args.get("limit", 40)))
        if name == "wechat_moments_policy":
            updates = args.get("updates")
            if isinstance(updates, dict):
                return self.engine.moments_set_policy(updates)
            return self.engine.moments_get_policy()
        if name == "wechat_moments_plan":
            raw_days = args.get("max_age_days")
            return self.engine.moments_plan(
                limit=int(args.get("limit", 20)), max_age_days=int(raw_days) if raw_days is not None else None
            )
        if name == "wechat_moments_interact":
            mode = str(args.get("mode") or "dry_run")
            if bool(args.get("execute_plan", False)):
                return self.engine.moments_execute_plan(mode=mode, limit=int(args.get("limit", 5)))
            return self.engine.moments_interact(
                str(args.get("post_key") or ""), author=str(args.get("author") or ""),
                action=str(args.get("action") or "like"), text=str(args.get("text") or ""), mode=mode,
            )
        if name == "wechat_moments_suggest_comment":
            return self.engine.moments_suggest_comment(
                str(args.get("post_key") or args.get("postKey") or ""),
                style=str(args.get("style") or "natural"),
            )
        if name == "wechat_call_brief":
            raw_use_llm = args.get("use_llm") if "use_llm" in args else args.get("useLlm", True)
            use_llm = (
                raw_use_llm.strip().lower() not in ("0", "false", "no")
                if isinstance(raw_use_llm, str)
                else bool(raw_use_llm)
            )
            return self.engine.get_pre_call_brief(
                str(args.get("target") or ""),
                goal=str(args.get("goal") or "general"),
                custom_goal=str(args.get("custom_goal") or args.get("customGoal") or ""),
                use_llm=use_llm,
            )
        if name == "wechat_salescrm_analyze":
            return self.engine.crm_analyze_contact(
                str(args.get("target") or "心安"),
                incoming_text=str(args.get("incoming_text") or ""),
            )
        if name == "wechat_salescrm_formulas":
            return self.engine.crm_evaluate_formulas(
                str(args.get("target") or "心安"),
                overrides=args.get("overrides") if isinstance(args.get("overrides"), dict) else None,
            )
        if name == "omni_channels_status":
            return self.engine.omni_overview(
                probe_live=bool(args.get("probe_live", False)),
                channel=str(args.get("channel") or "all"),
            )
        if name == "omni_channel_inspect":
            action = str(args.get("action") or "sessions").strip().lower()
            if action == "messages":
                return self.engine.omni_read_messages(
                    str(args.get("channel") or "feishu"),
                    target=str(args.get("target") or ""),
                    limit=int(args.get("limit", 20)),
                    launch_if_needed=bool(args.get("launch_if_needed", False)),
                )
            return self.engine.omni_list_sessions(
                str(args.get("channel") or "feishu"),
                limit=int(args.get("limit", 20)),
                query=str(args.get("query") or args.get("target") or ""),
                launch_if_needed=bool(args.get("launch_if_needed", False)),
            )
        if name == "omni_channel_send":
            return self.engine.omni_send(
                str(args["channel"]),
                str(args.get("target") or ""),
                str(args["text"]),
                mode=str(args.get("mode") or "auto"),
                dry_run=bool(args.get("dry_run", True)),
                confirm_send=bool(args.get("confirm_send", False)),
            )
        if name == "omni_channel_leads":
            return self.engine.omni_extract_leads(
                str(args["channel"]),
                target=str(args.get("target") or ""),
                query=str(args.get("query") or ""),
                messages=args.get("messages") if isinstance(args.get("messages"), list) else None,
                sync_crm=bool(args.get("sync_crm", True)),
            )
        if name == "app_use_list_apps":
            return self.engine.app_use_list_apps(
                include_installed=bool(args.get("include_installed", True)),
                category=str(args.get("category") or "all"),
                running_only=bool(args.get("running_only", False)),
            )
        if name == "app_use_list_agents":
            return self.engine.app_use_list_agents(
                refresh_models=bool(args.get("refresh_models", False)),
            )
        if name == "app_use_inspect":
            return self.engine.app_use_inspect_app(
                bundle_id=str(args.get("bundle_id") or ""),
                app_name=str(args.get("app_name") or ""),
                app_path=str(args.get("app_path") or ""),
                launch_if_needed=bool(args.get("launch_if_needed", False)),
                allow_activate=bool(args.get("allow_activate", True)),
                max_nodes=int(args.get("max_nodes", 350)),
            )
        if name == "app_use_build_sop":
            return self.engine.app_use_build_sop(
                str(args.get("goal") or ""),
                bundle_id=str(args.get("bundle_id") or ""),
                app_name=str(args.get("app_name") or ""),
                app_path=str(args.get("app_path") or ""),
                agent_id=str(args.get("agent_id") or ""),
                provider_id=args.get("provider_id") or None,
                custom_agent_prompt=str(args.get("custom_agent_prompt") or ""),
                inspect_live=bool(args.get("inspect_live", True)),
                launch_if_needed=bool(args.get("launch_if_needed", False)),
                attach_screenshot=bool(args.get("attach_screenshot", False)),
                save=bool(args.get("save", True)),
            )
        if name == "app_use_run_workflow":
            return self.engine.app_use_run_workflow(
                workflow_id=args.get("workflow_id") or None,
                workflow=args.get("workflow") if isinstance(args.get("workflow"), dict) else None,
                params=args.get("params") if isinstance(args.get("params"), dict) else None,
                dry_run=bool(args.get("dry_run", True)),
                confirm_run=bool(args.get("confirm_run", False)),
                respect_human_guard=bool(args.get("respect_human_guard", True)),
                self_heal=bool(args.get("self_heal", True)),
                auto_patch_workflow=bool(args.get("auto_patch_workflow", False)),
                heal_agent_id=str(args.get("heal_agent_id") or ""),
                dispatch_mode=str(args.get("dispatch_mode") or "auto"),
            )
        if name == "app_use_explore_and_build":
            return self.engine.app_use_explore(
                goal=str(args.get("goal") or ""),
                bundle_id=str(args.get("bundle_id") or ""),
                app_name=str(args.get("app_name") or ""),
                app_path=str(args.get("app_path") or ""),
                agent_id=str(args.get("agent_id") or ""),
                max_turns=int(args.get("max_turns", 6) or 6),
                dry_run=bool(args.get("dry_run", True)),
                confirm_run=bool(args.get("confirm_run", False)),
                respect_human_guard=bool(args.get("respect_human_guard", True)),
                launch_if_needed=bool(args.get("launch_if_needed", True)),
                save=bool(args.get("save", True)),
            )
        if name == "app_use_run_pipeline":
            return self.engine.app_use_run_pipeline(
                pipeline_id=args.get("pipeline_id") or None,
                pipeline=args.get("pipeline") if isinstance(args.get("pipeline"), dict) else None,
                initial_params=args.get("initial_params") if isinstance(args.get("initial_params"), dict) else None,
                dry_run=bool(args.get("dry_run", True)),
                confirm_run=bool(args.get("confirm_run", False)),
                respect_human_guard=bool(args.get("respect_human_guard", True)),
                self_heal=bool(args.get("self_heal", True)),
            )
        if name == "app_use_record_demo":
            action = str(args.get("action") or "status").strip().lower()
            if action == "start":
                return self.engine.app_use_recording_start(
                    max_duration_sec=float(args.get("max_duration_sec", 180.0)),
                    poll_interval_sec=float(args.get("poll_interval_sec", 0.45)),
                    target_bundle_id=str(args.get("target_bundle_id") or ""),
                )
            if action in ("stop", "stop_and_compile", "compile"):
                return self.engine.app_use_recording_stop_and_compile(
                    goal_hint=str(args.get("goal_hint") or ""),
                    agent_id=str(args.get("agent_id") or ""),
                    save=bool(args.get("save", True)),
                )
            return self.engine.app_use_recording_status()
        if name == "app_use_export_skill":
            return self.engine.app_use_export_skill(
                str(args.get("workflow_id") or ""),
                out_dir=args.get("out_dir") or None,
            )
        if name == "app_use_generalize_app":
            return self.engine.app_use_generalize_app(
                goal=str(args.get("goal") or ""),
                bundle_id=str(args.get("bundle_id") or ""),
                app_name=str(args.get("app_name") or ""),
                app_path=str(args.get("app_path") or ""),
                agent_id=str(args.get("agent_id") or ""),
                mode=str(args.get("mode") or "auto"),
                max_turns=int(args.get("max_turns", 4) or 4),
                launch_if_needed=bool(args.get("launch_if_needed", True)),
                dry_run_verify=bool(args.get("dry_run_verify", True)),
                export_skill=bool(args.get("export_skill", True)),
                save=bool(args.get("save", True)),
                custom_agent_prompt=str(args.get("custom_agent_prompt") or ""),
            )
        if name == "app_use_state_graph":
            return self.engine.app_use_get_state_graph(bundle_id=args.get("bundle_id") or None)
        if name == "app_use_install_meta_skill":
            return self.engine.app_use_install_meta_skill(
                install_global=bool(args.get("install_global", True)),
            )
        if name == "app_use_watch_parallel":
            return self.engine.app_use_watch_parallel(
                targets=list(args.get("targets") or []),
                include_ocr=bool(args.get("include_ocr", False)),
                max_workers=int(args.get("max_workers", 4) or 4),
            )
        if name == "app_use_run_parallel":
            return self.engine.app_use_run_parallel(
                jobs=list(args.get("jobs") or []),
                dry_run=bool(args.get("dry_run", True)),
                confirm_run=bool(args.get("confirm_run", False)),
                respect_human_guard=bool(args.get("respect_human_guard", True)),
                self_heal=bool(args.get("self_heal", True)),
                max_workers=int(args.get("max_workers", 4) or 4),
                dispatch_mode=str(args.get("dispatch_mode") or "auto"),
            )
        if name == "app_use_concurrency_status":
            return self.engine.app_use_concurrency_status()
        if name == "app_use_risk_profile":
            return self.engine.app_use_risk_profile(
                bundle_id=str(args.get("bundle_id") or ""),
                app_name=str(args.get("app_name") or ""),
                app_path=str(args.get("app_path") or ""),
            )
        if name == "wechat_onboarding_status":
            return self.engine.get_onboarding_status()
        if name == "wechat_onboarding_setup":
            return self.engine.setup_tenant_onboarding(
                owner_name=args.get("owner_name"),
                business_name=args.get("business_name"),
                product_summary=args.get("product_summary"),
                industry_pack=args.get("industry_pack"),
                owner_aliases=args.get("owner_aliases"),
                admin_contacts=args.get("admin_contacts"),
                test_contacts=args.get("test_contacts"),
            )
        if name == "wechat_sales_packs":
            return {"ok": True, "packs": self.engine.list_available_sales_packs()}
        if name == "wechat_training_discover":
            return self.engine.discover_training_corpus(
                search_dirs=args.get("search_dirs"),
                limit=int(args.get("limit", 20)),
                include_live_sessions=bool(args.get("include_live_sessions", True)),
            )
        if name == "wechat_training_run":
            return self.engine.run_self_training(
                archive_paths=args.get("archive_paths"),
                contact_targets=args.get("contact_targets"),
                raw_conversations=args.get("raw_conversations"),
                doc_texts=args.get("doc_texts"),
                owner_name=args.get("owner_name"),
                industry_pack=args.get("industry_pack"),
                use_llm=bool(args.get("use_llm", False)),
                auto_publish_safe=bool(args.get("auto_publish_safe", True)),
            )
        if name == "wechat_training_approve":
            return self.engine.approve_training_drafts(
                args.get("entry_ids") or [],
                edits=args.get("edits"),
            )
        if name == "wechat_test_contact":
            action = str(args.get("action") or "list").strip().lower()
            if action == "list":
                return self.engine.list_test_contacts()
            return self.engine.set_test_contact(
                str(args.get("name") or ""),
                enabled=(action != "remove"),
                note=str(args.get("note") or ""),
            )
        if name == "wechat_sparring_chat":
            return self.engine.sparring_simulate_turn(
                str(args.get("message") or ""),
                contact_name=str(args.get("contact_name") or "模拟测试客户"),
                persona_id=args.get("persona_id") or None,
                use_llm=args.get("use_llm") if "use_llm" in args else None,
                record=bool(args.get("record", True)),
            )
        if name == "wechat_sparring_regression":
            return self.engine.run_sparring_regression(
                limit=int(args.get("limit", 20)),
                use_llm=bool(args.get("use_llm", False)),
            )
        if name == "wechat_supervisor_directive":
            return self.engine.handle_supervisor_hashtag(
                str(args.get("contact") or "模拟测试客户"),
                str(args.get("text") or ""),
                channel=str(args.get("channel") or "workbench"),
                use_llm=bool(args.get("use_llm", False)),
            )
        if name == "wechat_supervisor_rate":
            return self.engine.submit_reply_rating(
                int(args["turn_id"]),
                stars=int(args["stars"]),
                tags=args.get("tags") or (),
                comment=str(args.get("comment") or ""),
                rewritten_reply=str(args.get("rewritten_reply") or ""),
            )
        if name == "wechat_quality_dashboard":
            return self.engine.get_quality_dashboard(days=int(args.get("days", 7)))
        if name == "wechat_user_guide":
            return self.engine.get_user_guide_markdown()
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

        def _send_bytes(
            self,
            code: int,
            data: bytes,
            content_type: str,
            *,
            private: bool = False,
            no_cache: bool = False,
            cache_control: Optional[str] = None,
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if private:
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            elif no_cache:
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            elif cache_control:
                self.send_header("Cache-Control", cache_control)
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
                elif path in ("/mobile", "/mobile/"):
                    self._send_html(200, render_mobile_remote_html())
                elif path == "/user-guide":
                    guide_res = engine.get_user_guide_html()
                    if guide_res.get("ok") and guide_res.get("html"):
                        self._send_html(200, str(guide_res["html"]))
                    else:
                        self._send_html(200, _render_user_guide_fallback_html(engine))
                elif path.startswith("/assets/user-guide/"):
                    raw_rel = path[len("/assets/user-guide/") :]
                    raw_name = unquote(raw_rel)
                    ext = Path(raw_name).suffix.lower() if raw_name else ""
                    mime_map = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".webp": "image/webp",
                    }
                    if (
                        not raw_name
                        or raw_name.startswith(".")
                        or "/" in raw_name
                        or "\\" in raw_name
                        or ".." in raw_name
                        or "\x00" in raw_name
                        or "%" in raw_name
                        or Path(raw_name).name != raw_name
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", raw_name)
                        or ext not in mime_map
                    ):
                        self._send_json(400, {"ok": False, "error": "Invalid user-guide asset filename"})
                        return
                    candidate_dirs: List[Path] = []
                    seen_dirs: set[Path] = set()
                    for root_attr in ("bundle_root", "plugin_root"):
                        root_val = getattr(engine, root_attr, None)
                        if root_val:
                            try:
                                d_res = (Path(root_val) / "docs" / "assets" / "user-guide").resolve()
                            except OSError:
                                continue
                            if d_res not in seen_dirs:
                                seen_dirs.add(d_res)
                                candidate_dirs.append(d_res)
                    found_file: Optional[Path] = None
                    for base_resolved in candidate_dirs:
                        try:
                            cand = (base_resolved / raw_name).resolve()
                            if cand.parent == base_resolved and cand.is_file():
                                found_file = cand
                                break
                        except OSError:
                            continue
                    if found_file is None:
                        self._send_json(404, {"ok": False, "error": f"User guide asset not found: {raw_name}"})
                        return
                    self._send_bytes(
                        200,
                        found_file.read_bytes(),
                        mime_map[ext],
                        cache_control="public, max-age=3600",
                    )
                    return
                elif path == "/api/workos/harness":
                    self._send_json(200, engine.get_workos_harness_summary())
                elif path == "/api/workos/windows":
                    app_filter = (query.get("app") or ["all"])[0]
                    res = engine.list_app_windows(app=app_filter)
                    status_code = 400 if res.get("error_code") == "unsupported_app" else 200
                    self._send_json(status_code, res)
                elif path == "/api/workos/scheduler":
                    self._send_json(200, engine.get_scheduler_status())
                elif path == "/api/workos/border-overlay":
                    self._send_json(200, engine.get_border_overlay_status(refresh_windows=True))
                elif path == "/api/workos/coevolution":
                    self._send_json(200, engine.coevolution.get_summary())
                elif path == "/health":
                    self._send_json(200, {"ok": True, "service": SERVER_INFO["name"], "version": SERVER_INFO.get("version")})
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
                elif path == "/api/watch-contacts":
                    self._send_json(200, engine.list_watched_contacts())
                elif path == "/api/permissions":
                    self._send_json(200, engine.permissions_status())
                elif path == "/api/diagnostics":
                    deep = parse_qs(parsed.query).get("deep", ["0"])[0] in ("1", "true", "yes")
                    self._send_json(200, engine.diagnostics(deep=deep))
                elif path == "/api/llm-gateway/relaunch":
                    self._send_json(200, engine.relaunch_llm_gateway())
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
                elif path == "/api/meeting-copilot-state":
                    state_p = engine.plugin_root / "logs" / "meeting_copilot_state.json"
                    if state_p.is_file():
                        self._send_json(200, json.loads(state_p.read_text(encoding="utf-8")))
                    else:
                        self._send_json(200, {"ok": True, "status": "idle", "inMeeting": False})
                elif path == "/api/voice-call":
                    self._send_json(200, engine.get_voice_call_status())
                elif path == "/api/botstudio-bridge":
                    self._send_json(200, engine.get_botstudio_bridge_status())
                elif path == "/api/crm/overview":
                    auto_sync = str((query.get("auto_sync") or ["1"])[0]).lower() not in ("0", "false", "no")
                    self._send_json(200, engine.crm_overview(auto_sync=auto_sync))
                elif path == "/api/moments/posts":
                    self._send_json(200, engine.moments_list_posts(
                        limit=int((query.get("limit") or ["30"])[0]),
                        author=(query.get("author") or [""])[0],
                        include_partial=str((query.get("include_partial") or ["0"])[0]) in ("1", "true", "yes"),
                    ))
                elif path == "/api/moments/stats":
                    self._send_json(200, engine.moments_stats(limit=int((query.get("limit") or ["40"])[0])))
                elif path == "/api/moments/policy":
                    self._send_json(200, engine.moments_get_policy())
                elif path == "/api/moments/plan":
                    raw_days = (query.get("max_age_days") or [None])[0]
                    self._send_json(200, engine.moments_plan(
                        limit=int((query.get("limit") or ["20"])[0]),
                        max_age_days=int(raw_days) if raw_days not in (None, "") else None,
                    ))
                elif path == "/api/moments/log":
                    self._send_json(200, engine.moments_log(limit=int((query.get("limit") or ["50"])[0])))
                elif path == "/api/call-brief":
                    target = _maybe_unquote_target((query.get("target") or [""])[0])
                    goal = str((query.get("goal") or ["general"])[0] or "general")
                    custom_goal = str((query.get("custom_goal") or query.get("customGoal") or [""])[0] or "")
                    raw_use_llm = str((query.get("use_llm") or query.get("useLlm") or ["1"])[0]).strip().lower()
                    use_llm = raw_use_llm not in ("0", "false", "no")
                    res = engine.get_pre_call_brief(
                        target,
                        goal=goal,
                        custom_goal=custom_goal,
                        use_llm=use_llm,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/crm/reminders":
                    self._send_json(200, engine.crm_list_reminders())
                elif path == "/api/omni/channels":
                    probe_live = str((query.get("probe") or ["0"])[0]).lower() in ("1", "true", "yes")
                    ch = str((query.get("channel") or ["all"])[0])
                    self._send_json(200, engine.omni_overview(probe_live=probe_live, channel=ch))
                elif path == "/api/omni/sessions":
                    ch = str((query.get("channel") or ["feishu"])[0])
                    limit = int((query.get("limit") or ["20"])[0] or 20)
                    q_str = str((query.get("query") or [""])[0])
                    launch = str((query.get("launch") or ["0"])[0]).lower() in ("1", "true", "yes")
                    self._send_json(200, engine.omni_list_sessions(ch, limit=limit, query=q_str, launch_if_needed=launch))
                elif path == "/api/omni/messages":
                    ch = str((query.get("channel") or ["feishu"])[0])
                    target = _maybe_unquote_target((query.get("target") or [""])[0])
                    limit = int((query.get("limit") or ["20"])[0] or 20)
                    launch = str((query.get("launch") or ["0"])[0]).lower() in ("1", "true", "yes")
                    self._send_json(200, engine.omni_read_messages(ch, target=target, limit=limit, launch_if_needed=launch))
                elif path == "/api/app-use/apps":
                    include_installed = str((query.get("include_installed") or ["1"])[0]).lower() not in ("0", "false", "no")
                    cat = str((query.get("category") or ["all"])[0])
                    running_only = str((query.get("running_only") or ["0"])[0]).lower() in ("1", "true", "yes")
                    self._send_json(200, engine.app_use_list_apps(include_installed=include_installed, category=cat, running_only=running_only))
                elif path == "/api/app-use/agents":
                    refresh = str((query.get("refresh") or ["0"])[0]).lower() in ("1", "true", "yes")
                    self._send_json(200, engine.app_use_list_agents(refresh_models=refresh))
                elif path == "/api/app-use/workflows":
                    bid = str((query.get("bundle_id") or [""])[0]) or None
                    self._send_json(200, engine.app_use_list_workflows(bundle_id=bid))
                elif path == "/api/app-use/pipelines":
                    self._send_json(200, engine.app_use_list_pipelines())
                elif path == "/api/app-use/runs":
                    try:
                        limit = int((query.get("limit") or ["30"])[0] or 30)
                    except Exception:
                        limit = 30
                    limit = max(1, min(limit, 200))
                    self._send_json(200, engine.app_use_list_runs(limit=limit))
                elif path == "/api/app-use/recording":
                    self._send_json(200, engine.app_use_recording_status())
                elif path == "/api/app-use/state-graph":
                    bid = str((query.get("bundle_id") or [""])[0]) or None
                    self._send_json(200, engine.app_use_get_state_graph(bundle_id=bid))
                elif path == "/api/app-use/concurrency-status":
                    self._send_json(200, engine.app_use_concurrency_status())
                elif path == "/api/app-use/risk-profile":
                    bid = str((query.get("bundle_id") or query.get("bundleId") or [""])[0])
                    aname = str((query.get("app_name") or query.get("appName") or [""])[0])
                    apath = str((query.get("app_path") or query.get("appPath") or [""])[0])
                    self._send_json(200, engine.app_use_risk_profile(bundle_id=bid, app_name=aname, app_path=apath))
                elif path == "/api/onboarding/status":
                    self._send_json(200, engine.get_onboarding_status())
                elif path == "/api/sales-packs":
                    self._send_json(200, {"ok": True, "packs": engine.list_available_sales_packs()})
                elif path == "/api/test-contacts":
                    self._send_json(200, engine.list_test_contacts())
                elif path == "/api/sparring/turns":
                    cname = (query.get("contact") or query.get("contactName") or [None])[0]
                    limit_val = int((query.get("limit") or ["30"])[0] or 30)
                    self._send_json(200, engine.list_sparring_turns(contact_name=cname, limit=limit_val))
                elif path == "/api/supervisor/dashboard":
                    days_val = int((query.get("days") or ["7"])[0] or 7)
                    self._send_json(200, engine.get_quality_dashboard(days=days_val))
                elif path == "/api/docs/user-guide":
                    res = engine.get_user_guide_markdown()
                    self._send_json(200 if res.get("ok") else 404, res)
                elif path.startswith("/api/app-use/artifact/"):
                    raw_name = unquote(path[len("/api/app-use/artifact/"):]).strip()
                    if (
                        not raw_name
                        or raw_name.startswith(".")
                        or len(raw_name) <= 4
                        or "/" in raw_name
                        or "\\" in raw_name
                        or ".." in raw_name
                        or "\x00" in raw_name
                        or not raw_name.lower().endswith(".png")
                        or Path(raw_name).name != raw_name
                    ):
                        self._send_json(400, {"ok": False, "error": "Invalid artifact filename"})
                        return
                    candidate_dirs = [
                        Path("/Volumes/SanDisk/Builds/WeChatBot/app-use-runs"),
                        Path("/Volumes/SanDisk/Builds/WeChatBot/app-use-verify"),
                    ]
                    insp_snaps = getattr(getattr(engine, "inspector", None), "snapshots_dir", None)
                    if insp_snaps:
                        insp_path = Path(insp_snaps)
                        candidate_dirs.extend(
                            [
                                insp_path,
                                insp_path / "app-use-runs",
                                insp_path / "app-use-verify",
                            ]
                        )
                    studio_snaps = getattr(getattr(engine, "app_use", None), "runs_dir", None)
                    if studio_snaps:
                        candidate_dirs.append(Path(studio_snaps))
                    found_file: Optional[Path] = None
                    for base_dir in candidate_dirs:
                        try:
                            base_resolved = base_dir.resolve()
                            cand = (base_resolved / raw_name).resolve()
                            if cand.parent == base_resolved and cand.is_file():
                                found_file = cand
                                break
                        except Exception:
                            continue
                    if found_file is None:
                        self._send_json(404, {"ok": False, "error": f"Artifact not found: {raw_name}"})
                        return
                    self._send_bytes(200, found_file.read_bytes(), "image/png", no_cache=True)
                    return
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
                        self._send_bytes(200, candidate.read_bytes(), "image/png", no_cache=True)
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
                if path in {"/api/search-send-image", "/api/annotate-send-image"}:
                    manual_trigger = body.get("manualTrigger", body.get("manual_trigger")) is True
                    if manual_trigger and not self._workbench_allowed(post=True):
                        self._send_json(403, {"ok": False, "error_code": "local_origin_required"}, private=True)
                        return
                    if manual_trigger and self.headers.get_content_type() != "application/json":
                        self._send_json(415, {"ok": False, "error_code": "json_required"}, private=True)
                        return
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
                        res = engine.resume_contact(_maybe_unquote_target(str(body.get("target") or "")))
                    else:
                        res = engine.takeover_contact(
                            _maybe_unquote_target(str(body.get("target") or "")),
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
                elif path == "/api/watch-contacts":
                    action = str(body.get("action") or "watch").strip().lower()
                    target = str(body.get("target") or "").strip()
                    if action in ("unwatch", "remove", "disable", "stop"):
                        res = engine.unwatch_contact(target)
                    else:
                        res = engine.watch_contact(
                            target,
                            alias=str(body.get("alias") or ""),
                            role=str(body.get("role") or "friend"),
                            care_level=body.get("care_level"),
                            auto_start_hosting=bool(body.get("auto_start_hosting", True)),
                        )
                    status = 400 if res.get("error_code") == "missing_target" else (200 if res.get("ok") else 400)
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
                        speed_mode=body.get("speed_mode") or body.get("speedMode") or None,
                        task_goal=body.get("task_goal") or body.get("taskGoal") or None,
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
                elif path == "/api/avatar":
                    res = engine.avatar_capture(
                        target=str(body.get("target") or ""),
                        snapshot_path=str(body.get("snapshot_path") or ""),
                        crop=body.get("crop") if isinstance(body.get("crop"), dict) else None,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/avatars/refresh":
                    targets_raw = body.get("targets")
                    targets_arg = (
                        [str(x).strip() for x in targets_raw if str(x).strip()]
                        if isinstance(targets_raw, list)
                        else None
                    )
                    res = engine.refresh_avatars(
                        targets=targets_arg,
                        capture_fresh=bool(body.get("capture_fresh", body.get("captureFresh", True))),
                    )
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
                elif path == "/api/permissions/repair":
                    # 清除本 App 的失效授权记录并重新登记当前版本：会改动系统隐私设置，必须显式确认。
                    # services 只处理指定项（向导传当前缺失的那一项），不再连已正常的辅助功能一起清掉。
                    if not bool(body.get("confirm")):
                        self._send_json(400, {"ok": False, "error": "CONFIRM_REQUIRED"})
                    else:
                        raw_services = body.get("services")
                        if raw_services is None and body.get("service"):
                            raw_services = [body.get("service")]
                        services = [str(s) for s in raw_services] if isinstance(raw_services, list) else None
                        try:
                            self._send_json(200, engine.repair_permissions(services=services))
                        except ValueError as exc:
                            self._send_json(400, {"ok": False, "error": "INVALID_SERVICES", "detail": str(exc)})
                elif path == "/api/permissions/request":
                    # 只向 macOS 申请登记（系统弹窗 + 把本 App 加进对应面板列表），不清除任何已有授权
                    only = body.get("service") or body.get("only") or None
                    try:
                        self._send_json(200, engine.request_permissions(open_settings=False, only=str(only) if only else None))
                    except ValueError as exc:
                        self._send_json(400, {"ok": False, "error": "INVALID_SERVICE", "detail": str(exc)})
                elif path == "/api/moments/read":
                    # 读取朋友圈：会在用户的微信里滚动，受人工活动守卫约束；结束后切回聊天页
                    self._send_json(200, engine.moments_read_feed(
                        max_posts=int(body.get("maxPosts", body.get("max_posts", 40))),
                        max_pages=int(body.get("maxPages", body.get("max_pages", 90))),
                    ))
                elif path == "/api/moments/policy":
                    updates = body.get("updates") if isinstance(body.get("updates"), dict) else body
                    self._send_json(200, engine.moments_set_policy(updates))
                elif path == "/api/moments/interact":
                    self._send_json(200, engine.moments_interact(
                        str(body.get("postKey") or body.get("post_key") or ""),
                        author=str(body.get("author") or ""),
                        action=str(body.get("action") or "like"),
                        text=str(body.get("text") or ""),
                        mode=str(body.get("mode") or "dry_run"),
                    ))
                elif path == "/api/moments/run-plan":
                    self._send_json(200, engine.moments_execute_plan(
                        mode=str(body.get("mode") or "dry_run"), limit=int(body.get("limit") or 5),
                    ))
                elif path == "/api/moments/suggest-comment":
                    res = engine.moments_suggest_comment(
                        str(body.get("postKey") or body.get("post_key") or ""),
                        style=str(body.get("style") or "natural"),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/call-brief":
                    raw_use_llm = body.get("use_llm") if "use_llm" in body else body.get("useLlm", True)
                    use_llm = (
                        raw_use_llm.strip().lower() not in ("0", "false", "no")
                        if isinstance(raw_use_llm, str)
                        else bool(raw_use_llm)
                    )
                    res = engine.get_pre_call_brief(
                        _maybe_unquote_target(str(body.get("target") or "")),
                        goal=str(body.get("goal") or "general"),
                        custom_goal=str(body.get("custom_goal") or body.get("customGoal") or ""),
                        use_llm=use_llm,
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
                elif path == "/api/wechat-ai-assist":
                    res = engine.consult_wechat_assistant(
                        target=str(body.get("target") or body.get("contact") or ""),
                        content_hint=str(body.get("contentHint") or body.get("content_hint") or body.get("text") or body.get("url") or ""),
                        assistant=str(body.get("assistant") or "auto"),
                        mode=str(body.get("mode") or "auto"),
                        bubbles=body.get("bubbles"),
                        bubble_coords=body.get("bubbleCoords") or body.get("bubble_coords"),
                        wait_seconds=float(body.get("waitSeconds", body.get("wait_seconds", 5.5))),
                        dry_run=bool(body.get("dryRun", body.get("dry_run", False))),
                        model_id=str(body.get("modelId") or body.get("model_id") or "auto/deepseek-v4.1-flash"),
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
                elif path == "/api/workos/goal":
                    res = engine.configure_workos_post(
                        speed_mode=body.get("speed_mode") if "speed_mode" in body else body.get("speedMode"),
                        post_preset=body.get("post_preset") if "post_preset" in body else body.get("postPreset"),
                        task_goal=body.get("task_goal") if "task_goal" in body else body.get("taskGoal"),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/workos/learn-correction":
                    res = engine.learn_from_correction(
                        target=str(body.get("target") or ""),
                        incoming_text=str(body.get("incoming_text") or body.get("incomingText") or ""),
                        corrected_reply=str(body.get("corrected_reply") or body.get("correctedReply") or ""),
                        original_draft=str(body.get("original_draft") or body.get("originalDraft") or ""),
                        title=str(body.get("title") or ""),
                        kind=str(body.get("kind") or "script"),
                        keywords=body.get("keywords") if isinstance(body.get("keywords"), list) else None,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/workos/bind-window":
                    raw_wid = body.get("windowID") if "windowID" in body else body.get("window_id")
                    parsed_wid: Optional[int] = None
                    if raw_wid not in (None, "", 0, "0", False):
                        try:
                            parsed_wid = int(raw_wid)
                        except (TypeError, ValueError):
                            self._send_json(400, {"ok": False, "error_code": "invalid_window_id", "error": f"Invalid windowID: {raw_wid!r}"})
                            return
                    res = engine.bind_app_window(
                        app_id=str(
                            body.get("appId")
                            if "appId" in body
                            else (body.get("app_id") if "app_id" in body else "auto")
                        ),
                        window_id=parsed_wid,
                        window_title=str(
                            body.get("windowTitle")
                            if "windowTitle" in body
                            else (body.get("window_title") or "")
                        ),
                        app_label=body.get("appLabel") if "appLabel" in body else body.get("app_label"),
                        follow_up_isolation=bool(
                            body.get("followUpIsolation", body.get("follow_up_isolation", True))
                        ),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/workos/popout-windows":
                    raw_targets = body.get("targets")
                    if isinstance(raw_targets, list):
                        targets = [str(t) for t in raw_targets if str(t).strip()]
                    elif str(body.get("target") or "").strip():
                        targets = [str(body.get("target") or "").strip()]
                    else:
                        targets = None
                    res = engine.open_watched_popout_windows(targets=targets)
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/workos/doc-ingest/preview":
                    raw_use_llm = body.get("use_llm") if "use_llm" in body else body.get("useLlm")
                    raw_max_pages = body.get("max_pages") if "max_pages" in body else body.get("maxPages")
                    res = engine.preview_doc_ingest(
                        raw_text=str(
                            body.get("raw_text")
                            if "raw_text" in body
                            else (body.get("rawText") or body.get("text") or "")
                        ),
                        file_path=body.get("file_path") if "file_path" in body else body.get("filePath"),
                        file_bytes_b64=(
                            body.get("file_bytes_b64")
                            if "file_bytes_b64" in body
                            else (body.get("fileBytesB64") or body.get("file_b64"))
                        ),
                        filename=str(
                            body.get("filename")
                            if "filename" in body
                            else (body.get("fileName") or "")
                        ),
                        instruction=str(body.get("instruction") or "希望你能够替代我去和顾客聊天"),
                        doc_name=str(
                            body.get("doc_name")
                            if "doc_name" in body
                            else (body.get("docName") or "")
                        ),
                        use_llm=raw_use_llm if isinstance(raw_use_llm, bool) else None,
                        max_pages=int(raw_max_pages or 12),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/workos/doc-ingest/confirm":
                    raw_items = body.get("items")
                    if not isinstance(raw_items, list):
                        self._send_json(400, {"ok": False, "error_code": "invalid_items", "error": "items must be a JSON array."})
                        return
                    res = engine.confirm_doc_ingest(
                        items=raw_items,
                        strategy=str(body.get("strategy") or "bind_kb"),
                        doc_name=str(
                            body.get("doc_name")
                            if "doc_name" in body
                            else (body.get("docName") or "")
                        ),
                        apply_prompt_target=bool(
                            body.get("apply_prompt_target", body.get("applyPromptTarget", False))
                        ),
                        instruction=str(body.get("instruction") or ""),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/workos/scheduler/run":
                    res = engine.run_multi_window_schedule_round(
                        auto_think=bool(body.get("auto_think", body.get("autoThink", False))),
                        dry_run=bool(body.get("dry_run", body.get("dryRun", True))),
                        app=str(body.get("app") or "all"),
                        dhash_threshold=int(
                            body.get("dhash_threshold")
                            if "dhash_threshold" in body
                            else (body.get("dhashThreshold") or 4)
                        ),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/workos/border-overlay":
                    raw_enabled = body.get("enabled") if "enabled" in body else None
                    raw_state = (
                        body.get("state")
                        if "state" in body
                        else (
                            body.get("modeColorState")
                            if "modeColorState" in body
                            else body.get("mode_color_state")
                        )
                    )
                    res = engine.configure_border_overlay(
                        enabled=bool(raw_enabled) if raw_enabled is not None else None,
                        state=str(raw_state) if raw_state is not None else None,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/workos/coevolution/sync":
                    self._send_json(200, engine.coevolution.sync_to_botstudio())
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
                        manual_trigger=bool(body.get("manualTrigger", body.get("manual_trigger", True))),
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
                elif path == "/api/send-sticker":
                    res = engine.send_wechat_sticker(
                        target=str(body.get("target") or ""),
                        tab=str(body.get("tab") or "favorites"),
                        slot=int(body.get("slot") or 0),
                        emoji_code=str(body.get("emoji_code") or body.get("emojiCode") or ""),
                        dry_run=bool(body.get("dry_run", body.get("dryRun", False))),
                        confirm_send=bool(body.get("confirm_send", body.get("confirmSend", True))),
                        skip_navigation=bool(body.get("skip_navigation", body.get("skipNavigation", False))),
                        target_window_id=int(body["target_window_id"]) if body.get("target_window_id") else None,
                        manual_trigger=bool(body.get("manualTrigger", body.get("manual_trigger", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/search-send-image":
                    res = engine.search_and_send_web_image(
                        target=str(body.get("target") or ""),
                        query=str(body.get("query") or ""),
                        caption=str(body.get("caption") or ""),
                        dry_run=bool(body.get("dry_run", body.get("dryRun", False))),
                        confirm_send=bool(body.get("confirm_send", body.get("confirmSend", True))),
                        target_window_id=int(body["target_window_id"]) if body.get("target_window_id") else None,
                        manual_trigger=manual_trigger,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/annotate-send-image":
                    raw_kw = body.get("keywords")
                    kw_list = (
                        [str(k).strip() for k in raw_kw if str(k).strip()]
                        if isinstance(raw_kw, list)
                        else [k.strip() for k in str(raw_kw or "").split(",") if k.strip()]
                    )
                    res = engine.annotate_and_send_peer_image(
                        target=str(body.get("target") or ""),
                        image_path=str(body.get("image_path") or body.get("imagePath") or ""),
                        keywords=kw_list or None,
                        note=str(body.get("note") or ""),
                        boxes=body.get("boxes") if isinstance(body.get("boxes"), list) else None,
                        dry_run=bool(body.get("dry_run", body.get("dryRun", False))),
                        confirm_send=bool(body.get("confirm_send", body.get("confirmSend", True))),
                        target_window_id=int(body["target_window_id"]) if body.get("target_window_id") else None,
                        manual_trigger=manual_trigger,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/join-meeting-botstudio":
                    res = engine.join_tencent_meeting_and_start_botstudio(
                        target=str(body.get("target") or ""),
                        meeting_code=str(body.get("meeting_code") or body.get("meetingCode") or ""),
                        password=str(body.get("password") or ""),
                        agenda=str(body.get("agenda") or ""),
                        click_card=bool(body.get("click_card", body.get("clickCard", True))),
                        dry_run=bool(body.get("dry_run", body.get("dryRun", False))),
                        confirm_send=bool(body.get("confirm_send", body.get("confirmSend", True))),
                        target_window_id=int(body["target_window_id"]) if body.get("target_window_id") else None,
                        manual_trigger=bool(body.get("manualTrigger", body.get("manual_trigger", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/voice-call":
                    res = engine.voice_call(
                        target=str(body.get("target") or ""),
                        action=str(body.get("action") or "dial"),
                        app=str(body.get("app") or "wechat"),
                        call_type=str(body.get("call_type") or body.get("callType") or "audio"),
                        greeting=str(body.get("greeting") or ""),
                        instructions=str(body.get("instructions") or ""),
                        auto_voice_agent=bool(body.get("auto_voice_agent", body.get("autoVoiceAgent", True))),
                        idle_input_uid=str(body.get("idle_input_uid") or body.get("idleInputUid") or ""),
                        dry_run=bool(body.get("dry_run", body.get("dryRun", False))),
                        confirm_send=bool(body.get("confirm_send", body.get("confirmSend", True))),
                        skip_navigation=bool(body.get("skip_navigation", body.get("skipNavigation", False))),
                        target_window_id=int(body["target_window_id"]) if body.get("target_window_id") else None,
                        manual_trigger=bool(body.get("manualTrigger", body.get("manual_trigger", True))),
                    )
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
                                    str(body.get("target") or "心安"),
                                    incoming_text=str(body.get("incoming_text") or body.get("incomingText") or ""),
                                    formula_overrides=ov if isinstance(ov, dict) else None,
                                ),
                            )
                        elif path == "/api/crm/formulas":
                            ov = body.get("overrides") or body.get("formula_overrides")
                            self._send_json(
                                200,
                                engine.crm_evaluate_formulas(
                                    str(body.get("target") or "心安"),
                                    overrides=ov if isinstance(ov, dict) else None,
                                ),
                            )
                        elif path == "/api/crm/adopt-draft":
                            self._send_json(
                                200,
                                engine.crm_adopt_draft(
                                    str(body.get("target") or "心安"),
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
                elif path == "/api/omni/probe":
                    res = engine.omni_probe(
                        str(body.get("channel") or "feishu"),
                        launch_if_needed=bool(body.get("launch_if_needed", body.get("launchIfNeeded", False))),
                        include_web=bool(body.get("include_web", body.get("includeWeb", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/omni/send":
                    res = engine.omni_send(
                        str(body.get("channel") or "feishu"),
                        str(body.get("target") or ""),
                        str(body.get("text") or ""),
                        mode=str(body.get("mode") or "auto"),
                        dry_run=bool(body.get("dry_run", body.get("dryRun", True))),
                        confirm_send=bool(body.get("confirm_send", body.get("confirmSend", False))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/omni/leads":
                    res = engine.omni_extract_leads(
                        str(body.get("channel") or "feishu"),
                        target=str(body.get("target") or ""),
                        query=str(body.get("query") or ""),
                        messages=body.get("messages") if isinstance(body.get("messages"), list) else None,
                        sync_crm=bool(body.get("sync_crm", body.get("syncCrm", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/omni/config":
                    updates = body.get("updates") if isinstance(body.get("updates"), dict) else body
                    res = engine.omni_update_config(updates if isinstance(updates, dict) else {})
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/omni/finish-browser":
                    self._send_json(200, engine.omni_finish_browser_space())
                elif path == "/api/omni/open-auth":
                    res = engine.omni_open_auth(
                        str(body.get("channel") or "feishu"),
                        action_type=str(body.get("action_type") or body.get("actionType") or "auto"),
                        target_view=str(body.get("target_view") or body.get("targetView") or "home"),
                        dry_run=bool(body.get("dry_run", body.get("dryRun", False))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/inspect":
                    raw_wid = body.get("window_id") if "window_id" in body else body.get("windowId")
                    res = engine.app_use_inspect_app(
                        bundle_id=str(body.get("bundle_id") or body.get("bundleId") or ""),
                        app_name=str(body.get("app_name") or body.get("appName") or ""),
                        app_path=str(body.get("app_path") or body.get("appPath") or ""),
                        window_id=int(raw_wid) if raw_wid not in (None, "", 0) else None,
                        window_title=str(body.get("window_title") or body.get("windowTitle") or ""),
                        launch_if_needed=bool(body.get("launch_if_needed", body.get("launchIfNeeded", False))),
                        allow_activate=bool(body.get("allow_activate", body.get("allowActivate", True))),
                        max_nodes=int(body.get("max_nodes") or body.get("maxNodes") or 350),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/build-sop":
                    res = engine.app_use_build_sop(
                        str(body.get("goal") or ""),
                        bundle_id=str(body.get("bundle_id") or body.get("bundleId") or ""),
                        app_name=str(body.get("app_name") or body.get("appName") or ""),
                        app_path=str(body.get("app_path") or body.get("appPath") or ""),
                        agent_id=str(body.get("agent_id") or body.get("agentId") or ""),
                        provider_id=body.get("provider_id") or body.get("providerId") or None,
                        custom_agent_prompt=str(body.get("custom_agent_prompt") or body.get("customAgentPrompt") or ""),
                        inspect_live=bool(body.get("inspect_live", body.get("inspectLive", True))),
                        launch_if_needed=bool(body.get("launch_if_needed", body.get("launchIfNeeded", False))),
                        attach_screenshot=bool(body.get("attach_screenshot", body.get("attachScreenshot", False))),
                        save=bool(body.get("save", True)),
                        parameters_hint=body.get("parameters_hint") or body.get("parametersHint"),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/save-workflow":
                    wf = body.get("workflow") if isinstance(body.get("workflow"), dict) else body
                    res = engine.app_use_save_workflow(
                        wf if isinstance(wf, dict) else {},
                        sop_markdown=str(body.get("sop_markdown") or body.get("sopMarkdown") or ""),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/delete-workflow":
                    wid = str(body.get("workflow_id") or body.get("workflowId") or body.get("id") or "")
                    res = engine.app_use_delete_workflow(wid)
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/run":
                    res = engine.app_use_run_workflow(
                        workflow_id=body.get("workflow_id") or body.get("workflowId") or None,
                        workflow=body.get("workflow") if isinstance(body.get("workflow"), dict) else None,
                        params=body.get("params") if isinstance(body.get("params"), dict) else None,
                        dry_run=bool(body.get("dry_run", body.get("dryRun", True))),
                        confirm_run=bool(body.get("confirm_run", body.get("confirmRun", False))),
                        respect_human_guard=bool(body.get("respect_human_guard", body.get("respectHumanGuard", True))),
                        self_heal=bool(body.get("self_heal", body.get("selfHeal", True))),
                        auto_patch_workflow=bool(body.get("auto_patch_workflow", body.get("autoPatchWorkflow", False))),
                        heal_agent_id=str(body.get("heal_agent_id") or body.get("healAgentId") or ""),
                        dispatch_mode=str(body.get("dispatch_mode") or body.get("dispatchMode") or "auto"),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/export-kb":
                    wid = str(body.get("workflow_id") or body.get("workflowId") or body.get("id") or "")
                    res = engine.app_use_export_sop_to_kb(wid)
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/explore":
                    try:
                        max_turns = int(body.get("max_turns", body.get("maxTurns", 6)) or 6)
                    except Exception:
                        max_turns = 6
                    res = engine.app_use_explore(
                        goal=str(body.get("goal") or ""),
                        bundle_id=str(body.get("bundle_id") or body.get("bundleId") or ""),
                        app_name=str(body.get("app_name") or body.get("appName") or ""),
                        app_path=str(body.get("app_path") or body.get("appPath") or ""),
                        agent_id=str(body.get("agent_id") or body.get("agentId") or ""),
                        max_turns=max_turns,
                        dry_run=bool(body.get("dry_run", body.get("dryRun", True))),
                        confirm_run=bool(body.get("confirm_run", body.get("confirmRun", False))),
                        respect_human_guard=bool(body.get("respect_human_guard", body.get("respectHumanGuard", True))),
                        launch_if_needed=bool(body.get("launch_if_needed", body.get("launchIfNeeded", True))),
                        save=bool(body.get("save", True)),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/pipelines/save":
                    pl = body.get("pipeline") if isinstance(body.get("pipeline"), dict) else body
                    res = engine.app_use_save_pipeline(pl if isinstance(pl, dict) else {})
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/pipelines/delete":
                    pid = str(body.get("pipeline_id") or body.get("pipelineId") or body.get("id") or "")
                    res = engine.app_use_delete_pipeline(pid)
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/pipelines/run":
                    init_p = (
                        body.get("initial_params")
                        if isinstance(body.get("initial_params"), dict)
                        else (body.get("initialParams") if isinstance(body.get("initialParams"), dict) else None)
                    )
                    res = engine.app_use_run_pipeline(
                        pipeline_id=body.get("pipeline_id") or body.get("pipelineId") or None,
                        pipeline=body.get("pipeline") if isinstance(body.get("pipeline"), dict) else None,
                        initial_params=init_p,
                        dry_run=bool(body.get("dry_run", body.get("dryRun", True))),
                        confirm_run=bool(body.get("confirm_run", body.get("confirmRun", False))),
                        respect_human_guard=bool(body.get("respect_human_guard", body.get("respectHumanGuard", True))),
                        self_heal=bool(body.get("self_heal", body.get("selfHeal", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/recording/start":
                    try:
                        max_dur = float(body.get("max_duration_sec", body.get("maxDurationSec", 180.0)))
                    except Exception:
                        max_dur = 180.0
                    try:
                        poll_iv = float(body.get("poll_interval_sec", body.get("pollIntervalSec", 0.45)))
                    except Exception:
                        poll_iv = 0.45
                    res = engine.app_use_recording_start(
                        max_duration_sec=max_dur,
                        poll_interval_sec=poll_iv,
                        target_bundle_id=str(body.get("target_bundle_id") or body.get("targetBundleId") or ""),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/recording/stop":
                    res = engine.app_use_recording_stop_and_compile(
                        goal_hint=str(body.get("goal_hint") or body.get("goalHint") or ""),
                        agent_id=str(body.get("agent_id") or body.get("agentId") or ""),
                        save=bool(body.get("save", True)),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/rollback":
                    wid = str(body.get("workflow_id") or body.get("workflowId") or body.get("id") or "")
                    try:
                        rev_idx = int(body.get("revision_index", body.get("revisionIndex", -1)))
                    except Exception:
                        rev_idx = -1
                    res = engine.app_use_rollback_workflow(wid, revision_index=rev_idx)
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/export-skill":
                    wid = str(body.get("workflow_id") or body.get("workflowId") or body.get("id") or "")
                    res = engine.app_use_export_skill(
                        wid,
                        out_dir=body.get("out_dir") or body.get("outDir") or None,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/generalize":
                    try:
                        max_turns = int(body.get("max_turns", body.get("maxTurns", 4)) or 4)
                    except Exception:
                        max_turns = 4
                    res = engine.app_use_generalize_app(
                        goal=str(body.get("goal") or ""),
                        bundle_id=str(body.get("bundle_id") or body.get("bundleId") or ""),
                        app_name=str(body.get("app_name") or body.get("appName") or ""),
                        app_path=str(body.get("app_path") or body.get("appPath") or ""),
                        agent_id=str(body.get("agent_id") or body.get("agentId") or ""),
                        mode=str(body.get("mode") or "auto"),
                        max_turns=max_turns,
                        launch_if_needed=bool(body.get("launch_if_needed", body.get("launchIfNeeded", True))),
                        dry_run_verify=bool(body.get("dry_run_verify", body.get("dryRunVerify", True))),
                        export_skill=bool(body.get("export_skill", body.get("exportSkill", True))),
                        save=bool(body.get("save", True)),
                        custom_agent_prompt=str(body.get("custom_agent_prompt") or body.get("customAgentPrompt") or ""),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/install-meta-skill":
                    res = engine.app_use_install_meta_skill(
                        install_global=bool(body.get("install_global", body.get("installGlobal", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/ground-preview":
                    step_obj = body.get("step") if isinstance(body.get("step"), dict) else body
                    res = engine.app_use_ground_preview(
                        step_obj if isinstance(step_obj, dict) else {},
                        bundle_id=str(body.get("bundle_id") or body.get("bundleId") or ""),
                        app_name=str(body.get("app_name") or body.get("appName") or ""),
                        app_path=str(body.get("app_path") or body.get("appPath") or ""),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/watch-parallel":
                    try:
                        mw = int(body.get("max_workers", body.get("maxWorkers", 4)) or 4)
                    except Exception:
                        mw = 4
                    res = engine.app_use_watch_parallel(
                        targets=list(body.get("targets") or []),
                        include_ocr=bool(body.get("include_ocr", body.get("includeOcr", False))),
                        max_workers=mw,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/app-use/run-parallel":
                    try:
                        mw = int(body.get("max_workers", body.get("maxWorkers", 4)) or 4)
                    except Exception:
                        mw = 4
                    res = engine.app_use_run_parallel(
                        jobs=list(body.get("jobs") or []),
                        dry_run=bool(body.get("dry_run", body.get("dryRun", True))),
                        confirm_run=bool(body.get("confirm_run", body.get("confirmRun", False))),
                        respect_human_guard=bool(body.get("respect_human_guard", body.get("respectHumanGuard", True))),
                        self_heal=bool(body.get("self_heal", body.get("selfHeal", True))),
                        max_workers=mw,
                        dispatch_mode=str(body.get("dispatch_mode") or body.get("dispatchMode") or "auto"),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/onboarding/setup":
                    res = engine.setup_tenant_onboarding(
                        owner_name=body.get("owner_name") if "owner_name" in body else body.get("ownerName"),
                        business_name=body.get("business_name") if "business_name" in body else body.get("businessName"),
                        product_summary=body.get("product_summary") if "product_summary" in body else body.get("productSummary"),
                        industry_pack=body.get("industry_pack") if "industry_pack" in body else body.get("industryPack"),
                        owner_aliases=body.get("owner_aliases") if "owner_aliases" in body else body.get("ownerAliases"),
                        admin_contacts=body.get("admin_contacts") if "admin_contacts" in body else body.get("adminContacts"),
                        test_contacts=body.get("test_contacts") if "test_contacts" in body else body.get("testContacts"),
                        apply_pack=bool(body.get("apply_pack", body.get("applyPack", True))),
                        withdraw_legacy_seeds=bool(body.get("withdraw_legacy_seeds", body.get("withdrawLegacySeeds", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/training/discover":
                    res = engine.discover_training_corpus(
                        search_dirs=body.get("search_dirs") if "search_dirs" in body else body.get("searchDirs"),
                        limit=int(body.get("limit") or 20),
                        include_live_sessions=bool(body.get("include_live_sessions", body.get("includeLiveSessions", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/training/run":
                    res = engine.run_self_training(
                        archive_paths=body.get("archive_paths") if "archive_paths" in body else body.get("archivePaths"),
                        contact_targets=body.get("contact_targets") if "contact_targets" in body else body.get("contactTargets"),
                        raw_conversations=body.get("raw_conversations") if "raw_conversations" in body else body.get("rawConversations"),
                        doc_texts=body.get("doc_texts") if "doc_texts" in body else body.get("docTexts"),
                        owner_name=body.get("owner_name") if "owner_name" in body else body.get("ownerName"),
                        industry_pack=body.get("industry_pack") if "industry_pack" in body else body.get("industryPack"),
                        use_llm=bool(body.get("use_llm", body.get("useLlm", False))),
                        auto_publish_safe=bool(body.get("auto_publish_safe", body.get("autoPublishSafe", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/training/approve":
                    entry_ids = body.get("entry_ids") if "entry_ids" in body else body.get("entryIds")
                    res = engine.approve_training_drafts(
                        entry_ids if isinstance(entry_ids, list) else [],
                        edits=body.get("edits") if isinstance(body.get("edits"), dict) else None,
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/test-contacts":
                    action = str(body.get("action") or "").strip().lower()
                    enabled = bool(body.get("enabled", action not in ("remove", "unmark", "disable", "delete")))
                    name = str(body.get("name") or body.get("target") or "").strip()
                    res = engine.set_test_contact(
                        name,
                        enabled=enabled,
                        note=str(body.get("note") or ""),
                        auto_bind=bool(body.get("auto_bind", body.get("autoBind", True))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/sparring/chat":
                    res = engine.sparring_simulate_turn(
                        str(body.get("message") or body.get("incoming_text") or body.get("incomingText") or ""),
                        contact_name=str(body.get("contact_name") or body.get("contactName") or "模拟测试客户"),
                        persona_id=body.get("persona_id") or body.get("personaId") or None,
                        use_llm=body.get("use_llm") if "use_llm" in body else body.get("useLlm"),
                        model_id=body.get("model_id") or body.get("modelId") or None,
                        record=bool(body.get("record", True)),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/sparring/regression":
                    res = engine.run_sparring_regression(
                        limit=int(body.get("limit") or 20),
                        use_llm=bool(body.get("use_llm", body.get("useLlm", False))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/supervisor/directive":
                    res = engine.handle_supervisor_hashtag(
                        str(body.get("contact") or body.get("target") or "模拟测试客户"),
                        str(body.get("text") or body.get("directive") or ""),
                        channel=str(body.get("channel") or "workbench"),
                        use_llm=bool(body.get("use_llm", body.get("useLlm", False))),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
                elif path == "/api/supervisor/rate":
                    raw_tid = body.get("turn_id") if "turn_id" in body else body.get("turnId")
                    if raw_tid is None:
                        self._send_json(400, {"ok": False, "error": "turnId is required"})
                        return
                    res = engine.submit_reply_rating(
                        int(raw_tid),
                        stars=int(body.get("stars") or 0),
                        tags=body.get("tags") or (),
                        comment=str(body.get("comment") or ""),
                        rewritten_reply=str(body.get("rewritten_reply") or body.get("rewrittenReply") or ""),
                    )
                    self._send_json(200 if res.get("ok") else 400, res)
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
    # pidfile：App 更新后据此停掉旧版本 console，自动切换到新代码（版本感知升级）
    # bundle 外稳定位置：装进 App 包内会破坏签名（sealed resource）
    pidfile = Path.home() / "Library" / "Application Support" / "WeChatBot" / "console.pid"
    try:
        pidfile.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(pidfile, str(os.getpid()))
    except Exception:
        pass
    try:
        server.serve_forever()
    finally:
        try:
            pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        server.server_close()
