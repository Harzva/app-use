"""Unified CLI entrypoint for OpenBot macOS WeChat RPA + OCR + WeChatBridge Control Hub."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

from .auth_gate import ALL_CAPABILITIES, READ_ONLY_CAPABILITIES, StudioPluginUnauthorizedError
from .engine import WeChatControlEngine
from .mcp_server import WeChatMCPServer, serve_http


def _print_json(data: Any) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if isinstance(data, dict) and data.get("ok") is False:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wechat-control",
        description="OpenBot macOS WeChat RPA + Vision OCR + WeChatBridge Unified Control CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Diagnose permissions, WeChat state, Studio authorization, and safety locks.")
    sub.add_parser("govern", help="Rotate oversized jsonl logs and prune orphan snapshots (safe to run anytime).")
    req_perm = sub.add_parser(
        "request-permissions",
        help="Trigger official macOS Accessibility/PostEvent permission prompts and open Privacy & Security settings.",
    )
    req_perm.add_argument(
        "--no-settings",
        action="store_true",
        help="Trigger native permission prompt only without opening System Settings.",
    )
    sub.add_parser("auth-status", help="Inspect current Bot Studio plugin authorization state.")

    p_grant = sub.add_parser("auth-grant", help="Authorize WeChat plugin capabilities from Bot Studio.")
    p_grant.add_argument(
        "--cap",
        action="append",
        dest="caps",
        help=f"Specific capability ({', '.join(ALL_CAPABILITIES)}); omit for default safe set.",
    )
    p_grant.add_argument("--read-only", action="store_true", help="Grant read-only inspection & OCR capabilities only.")
    p_grant.add_argument("--all", action="store_true", help="Grant all capabilities including send_text_live.")
    p_grant.add_argument("--by", default="bot-studio-owner", help="Authorizing owner label.")
    p_grant.add_argument("--note", default="", help="Optional authorization note.")

    p_rev = sub.add_parser("auth-revoke", help="Revoke Bot Studio plugin authorization immediately.")
    p_rev.add_argument("--reason", default="Revoked by Bot Studio user", help="Revocation reason.")

    sub.add_parser("status", help="Inspect current WeChat process, windows, and active chat title.")
    sub.add_parser("sessions", help="List visible WeChat sessions via AX or Vision OCR fallback.")

    p_live = sub.add_parser(
        "inspect-live",
        help="Read-only walkthrough of open WeChat Chats & Contacts tabs, exporting JSON + Markdown reports.",
    )
    p_live.add_argument("--session-pages", type=int, default=2, help="Max scroll pages in Chats list.")
    p_live.add_argument("--contact-pages", type=int, default=4, help="Max scroll pages in Contacts list.")

    p_msgs = sub.add_parser("messages", help="Read recent visible messages in active chat.")
    p_msgs.add_argument("--limit", type=int, default=20, help="Maximum messages to return.")

    p_ocr = sub.add_parser("ocr", help="Run native macOS Vision OCR on an image or WeChat window.")
    p_ocr.add_argument("--image", type=Path, help="Image path; omit to capture WeChat window.")
    p_ocr.add_argument("--out", type=Path, help="Optional path to save captured window PNG.")

    p_send = sub.add_parser("send", help="Safely test or dispatch a WeChat text message.")
    p_send.add_argument("--target", required=True, help="Target contact or group chat name.")
    p_send.add_argument("--text", required=True, help="Message text.")
    p_send.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate verification & audit logging without touching UI (default).",
    )
    p_send.add_argument(
        "--silent-verify",
        action="store_true",
        help="Paste into WeChat input box and run 3x readback check, then clear without pressing Return.",
    )
    p_send.add_argument(
        "--confirm-send",
        action="store_true",
        help="Explicitly authorize pressing Return to send live message (disables dry-run & silent-verify).",
    )
    p_send.add_argument(
        "--allow-group",
        action="append",
        dest="allowed_groups",
        help="Repeatable allowlist entry restricting allowed targets.",
    )

    p_imp = sub.add_parser("import-chatlog", help="Import WeChat .zip or 聊天记录.txt into Markdown & JSONL.")
    p_imp.add_argument("--input", required=True, type=Path, help="Path to forwarded .zip, .txt, or folder.")
    p_imp.add_argument("--out-dir", type=Path, help="Directory to export .md and .jsonl files.")

    p_exp = sub.add_parser("export-article", help="Export open WeChat article or mp.weixin.qq.com URL to Markdown + local images.")
    p_exp.add_argument("--url", help="Optional WeChat mp.weixin.qq.com article URL to fetch directly.")
    p_exp.add_argument("--from-window", action="store_true", help="Export from the currently open WeChat reader pane (default when --url is omitted).")
    p_exp.add_argument("--pages", type=int, default=4, help="Max viewport scroll pages when exporting from WeChat window.")
    p_exp.add_argument("--no-copy-link", action="store_true", help="Skip clicking tab '...' -> 复制链接 and go straight to scroll OCR.")
    p_exp.add_argument("--no-images", action="store_true", help="Do not download remote images locally.")
    p_exp.add_argument("--out-dir", type=Path, help="Optional custom output directory for article.md and assets/.")

    p_explist = sub.add_parser("exported-articles", help="List exported Markdown articles and local asset directories.")
    p_explist.add_argument("--limit", type=int, default=20, help="Max number of exported articles to list.")

    p_expacc = sub.add_parser(
        "export-account",
        help="Batch-export all historical articles from a WeChat Official/Service Account.",
    )
    p_expacc.add_argument("--account", default="", help="Official/Service Account name.")
    p_expacc.add_argument("--album-url", default="", help="Official Account album / tag / homepage URL.")
    p_expacc.add_argument("--urls", nargs="+", default=None, help="Explicit article URLs to batch-export.")
    p_expacc.add_argument("--from-file", type=Path, default=None, help="Local HTML album or URL/JSON manifest file.")
    p_expacc.add_argument("--scan-window", action="store_true", help="Scroll & OCR open WeChat Official/Service Account window.")
    p_expacc.add_argument("--scroll-pages", type=int, default=4, help="Scroll pages when scanning open window.")
    p_expacc.add_argument("--max-articles", type=int, default=50, help="Max articles to export.")
    p_expacc.add_argument("--no-images", action="store_true", help="Skip downloading remote article images.")
    p_expacc.add_argument("--list", action="store_true", help="List previously exported account archives.")
    p_expacc.add_argument("--limit", type=int, default=20, help="Max account archives to list with --list.")

    p_expch = sub.add_parser(
        "export-channels",
        help="Batch-export all videos from a WeChat Channels (视频号) author via URLs, manifest, local cache, or window OCR.",
    )
    p_expch.add_argument("--author", default="", help="WeChat Channels author name.")
    p_expch.add_argument("--video-urls", nargs="+", default=None, help="Direct Channels video URLs to download.")
    p_expch.add_argument("--manifest", type=Path, default=None, help="Manifest JSON/JSONL/text file with video metadata or decode_key.")
    p_expch.add_argument("--cache-dir", type=Path, default=None, help="Local WeChat Channels cache folder containing MP4/MOV/ftyp files.")
    p_expch.add_argument("--scan-window", action="store_true", help="Scroll & OCR open WeChat Channels author window.")
    p_expch.add_argument("--scroll-pages", type=int, default=4, help="Scroll pages when scanning open Channels window.")
    p_expch.add_argument("--max-videos", type=int, default=50, help="Max videos to export.")
    p_expch.add_argument("--no-media", action="store_true", help="Skip downloading/copying video binaries (index & metadata only).")
    p_expch.add_argument("--list", action="store_true", help="List previously exported Channels archives.")
    p_expch.add_argument("--limit", type=int, default=20, help="Max Channels archives to list with --list.")

    sub.add_parser("ui-schema", help="Inspect the standardized WeChat UI view/region/target protocol schema.")
    p_uistate = sub.add_parser("ui-state", help="Detect active WeChat UI view and resolve live target coordinates.")
    p_uistate.add_argument("--refresh-ocr", action="store_true", help="Run Vision OCR on active WeChat window to resolve dynamic targets.")

    p_uinav = sub.add_parser("ui-navigate", help="Navigate or dry-run a standardized WeChat UI target (e.g. menu.settings).")
    p_uinav.add_argument("--target", required=True, help="Standardized target ID (e.g. nav.contacts, menu.settings, chat.header_more_drawer).")
    p_uinav.add_argument("--dry-run", action="store_true", help="Resolve coordinates without clicking.")
    p_uinav.add_argument("--ignore-human-guard", action="store_true", help="Bypass the anti-steal-mouse guard for explicit manual invocation.")

    p_mom = sub.add_parser(
        "moments",
        help="Read friends' Moments (朋友圈) feed, per-contact stats, and like/comment with dry-run safety.",
    )
    p_mom.add_argument(
        "action", nargs="?", default="stats",
        choices=["read", "posts", "post", "stats", "policy", "plan", "like", "unlike", "comment", "suggest-comment", "run-plan", "log"],
        help="read: 滚动读取信息流；stats: 按联系人汇总；like/unlike/comment: 对一条帖子互动（默认 dry-run）；suggest-comment: AI 拟写评论。",
    )
    p_mom.add_argument("--key", default=None, help="Post key (mom_xxx) returned by `moments posts`.")
    p_mom.add_argument("--author", default=None, help="Contact display name; picks their newest eligible post.")
    p_mom.add_argument("--text", default=None, help="Comment text (required for `comment`).")
    p_mom.add_argument("--style", default="natural", help="Comment suggestion style for `suggest-comment` (e.g. natural).")
    p_mom.add_argument(
        "--mode", choices=["dry_run", "silent_verify", "live"], default="dry_run",
        help="dry_run: verify the 赞/评论 menu without clicking; silent_verify: paste the comment and read it back, "
             "then discard; live: actually send (needs moments_interact_live grant).",
    )
    p_mom.add_argument("--limit", type=int, default=30, help="Max posts / contacts / log items to return.")
    p_mom.add_argument("--max-posts", type=int, default=40, help="`read`: stop after this many complete posts.")
    p_mom.add_argument("--max-pages", type=int, default=90, help="`read`: max scroll frames.")
    p_mom.add_argument("--include-partial", action="store_true", help="`posts`: include posts only partially read.")
    p_mom.add_argument("--set-policy", default=None, help="`policy`: JSON object merged into the auto-interaction policy.")

    p_cb = sub.add_parser(
        "call-brief",
        help="Generate a pre-call brief and spoken phone script card for a WeChat contact.",
    )
    p_cb.add_argument("target", help="Contact display name or remark.")
    p_cb.add_argument(
        "--goal",
        choices=["general", "followup", "quote", "care", "recovery", "custom"],
        default="general",
        help="Call goal preset.",
    )
    p_cb.add_argument("--custom-goal", dest="custom_goal", default="", help="Custom goal description when --goal custom.")
    p_cb.add_argument("--no-llm", action="store_true", help="Build fast local summary without calling LLM.")

    p_guard = sub.add_parser("human-guard", help="Inspect or configure human mouse/keyboard idle detection & cooldown guard.")
    p_guard.add_argument("--enable", action="store_true", help="Enable human activity guard.")
    p_guard.add_argument("--disable", action="store_true", help="Disable human activity guard.")
    p_guard.add_argument("--idle-seconds", type=float, help="Seconds mouse/keyboard must remain idle before resuming.")
    p_guard.add_argument("--cooldown-seconds", type=float, help="Cooldown window seconds after human intervention.")
    p_guard.add_argument("--reset", action="store_true", help="Clear active cooldown window immediately.")

    p_bind = sub.add_parser("bind-contact", help="Bind a WeChat contact or group with scheduled/AI interaction policy.")
    p_bind.add_argument("--target", required=True, help="Contact or group chat name to bind.")
    p_bind.add_argument("--alias", default="", help="Optional remark/alias.")
    p_bind.add_argument("--role", default="friend", help="Role tag: friend | group | customer | test.")
    p_bind.add_argument("--ai-persona", default="warm-companion", help="AI chat persona description.")
    p_bind.add_argument("--scheduled", action="store_true", help="Enable scheduled check-in messages.")
    p_bind.add_argument("--disable-scheduled", action="store_true", help="Disable scheduled check-in messages.")
    p_bind.add_argument("--cron", default="0 9,21 * * *", help="Scheduled cron expression hint.")
    p_bind.add_argument("--auto-reply", action="store_true", help="Enable AI auto-reply policy.")
    p_bind.add_argument("--disable-auto-reply", action="store_true", help="Disable AI auto-reply policy.")
    p_bind.add_argument("--note", default="", help="Binding note.")
    p_bind.add_argument("--special-care", action="store_true", help="Mark as Special Care (特别关心).")
    p_bind.add_argument("--care-level", choices=["special_care", "vip", "normal"], default=None, help="Priority care tier.")
    p_bind.add_argument("--care-tag", action="append", default=None, help="Repeatable care tag (e.g. 特别关心, 重点关照).")
    p_bind.add_argument("--follow-up-days", type=int, default=None, help="Proactive follow-up reminder threshold in days.")
    p_bind.add_argument("--agent-id", default=None, help="Bind a specific Agent ID to this contact/group.")
    p_bind.add_argument("--agent-name", default=None, help="Human-readable bound Agent name.")
    p_bind.add_argument("--agent-type", default=None, help="Bound Agent type (botstudio, dsh, openbot, custom).")
    p_bind.add_argument("--vision-model", default=None, help="Preferred multimodal VLM ID (e.g. auto/deepseek-v4.1-flash).")
    p_bind.add_argument("--auto-dispatch", dest="auto_dispatch", action="store_true", default=None, help="Automatically dispatch friend instructions to bound Agent.")
    p_bind.add_argument("--no-auto-dispatch", dest="auto_dispatch", action="store_false", help="Disable automatic instruction dispatch.")
    p_bind.add_argument("--auto-analyze-media", dest="auto_analyze_media", action="store_true", default=None, help="Automatically deep-read links, cards, and videos.")
    p_bind.add_argument("--no-auto-analyze-media", dest="auto_analyze_media", action="store_false", help="Disable automatic link/media analysis.")

    p_analyze = sub.add_parser("analyze-media", help="Deep-read a URL link, chat image/card, or video using 2x OCR + DeepSeek Flash.")
    p_analyze.add_argument("--kind", choices=["link", "image", "video"], default="link", help="Media type to analyze.")
    p_analyze.add_argument("--url", default=None, help="URL link or video URL to inspect.")
    p_analyze.add_argument("--image", default=None, help="Path to image file to inspect.")
    p_analyze.add_argument("--video", default=None, help="Path to local video file to inspect.")
    p_analyze.add_argument("--crop", default=None, help="Crop region x,y,w,h from --snapshot or monitor snapshot.")
    p_analyze.add_argument("--snapshot", default=None, help="Source snapshot path when using --crop.")
    p_analyze.add_argument("--from-viewer", action="store_true", help="Capture open WeChat '图片和视频' viewer window.")
    p_analyze.add_argument("--window-title", default="图片和视频", help="Viewer window title when using --from-viewer.")
    p_analyze.add_argument("--contact", default="", help="Originating friend or group name.")
    p_analyze.add_argument("--context", default="", help="Surrounding message context text.")
    p_analyze.add_argument("--frame-count", type=int, default=3, help="Keyframes to extract for video analysis.")
    p_analyze.add_argument("--model-id", default="auto/deepseek-v4.1-flash", help="Multimodal VLM ID.")
    p_analyze.add_argument("--allow-loopback", action="store_true", help="Allow localhost URL fetch for local testing.")

    p_dispatch = sub.add_parser("agent-dispatch", help="Parse friend instructions/links/media and dispatch tasks to bound Agent.")
    p_dispatch.add_argument("--target", required=True, help="Contact or group name to scan and dispatch.")
    p_dispatch.add_argument("--no-media", action="store_true", help="Skip live link/viewer media analysis.")
    p_dispatch.add_argument("--parse-only", action="store_true", help="Only parse structured instructions without calling bound Agent LLM.")
    p_dispatch.add_argument("--model-id", default=None, help="Override bound vision/execution model ID.")

    p_dock = sub.add_parser("dock-sidebar", help="Dock or verify WeChat Bot.app pinned beside the active WeChat window.")
    p_dock.add_argument("--mode", choices=["verify", "dock", "tile"], default="verify", help="Dock action mode.")

    p_sc = sub.add_parser(
        "special-care",
        aliases=["care"],
        help="Set or update Special Care / VIP priority tier for a contact or group.",
    )
    p_sc.add_argument("target_pos", nargs="?", default=None, help="Contact or group chat name.")
    p_sc.add_argument("--target", dest="target_flag", default=None, help="Contact or group chat name.")
    p_sc.add_argument("--level", choices=["special_care", "vip", "normal"], default="special_care", help="Care tier.")
    p_sc.add_argument("--disable", action="store_true", help="Demote back to normal tier.")
    p_sc.add_argument("--tag", action="append", default=None, help="Repeatable tag label.")
    p_sc.add_argument("--follow-up-days", type=int, default=None)
    p_sc.add_argument("--note", default=None)

    sub.add_parser(
        "web-overview",
        aliases=["overview"],
        help="Output aggregated JSON payload backing the Web Control Console.",
    )

    p_unbind = sub.add_parser("unbind-contact", help="Remove a bound WeChat contact or group.")
    p_unbind.add_argument("--target", required=True, help="Target name to unbind.")

    sub.add_parser("list-bindings", help="List all bound WeChat contacts and groups.")

    p_obs = sub.add_parser("observe-contact", help="Navigate to a bound contact/group and capture multi-page history.")
    p_obs.add_argument("--target", required=True, help="Target contact or group chat name.")
    p_obs.add_argument("--pages", type=int, default=4, help="Scroll pages to capture upward.")

    p_prof = sub.add_parser("profile-contact", help="Generate friend style, frequency & active time analytics report.")
    p_prof.add_argument("--target", default=None, help="Optional single contact/group name to focus on.")
    p_prof.add_argument("--all", action="store_true", help="Profile all discovered and bound contacts.")

    p_ct = sub.add_parser("chat-test", help="Run a contextual scheduled or AI chat test against a bound contact/group.")
    p_ct.add_argument("--target", required=True, help="Target contact or group chat name.")
    p_ct.add_argument("--mode", choices=["scheduled", "ai", "ai_chat", "custom"], default="scheduled")
    p_ct.add_argument("--text", default=None, help="Optional custom message override.")
    p_ct.add_argument("--confirm-send", action="store_true", help="Press Return and dispatch live message.")
    p_ct.add_argument("--silent-verify", action="store_true", help="Verify paste in UI without pressing Return.")

    p_kbl = sub.add_parser("kb-list", help="List entries in the local WeChat customer-service knowledge & terminology store.")
    p_kbl.add_argument("--kind", default=None, help="Optional kind filter (terminology, knowledge, script, faq).")
    p_kbl.add_argument("--library", default=None, help="Optional library filter (shared, bot).")
    p_kbl.add_argument("--limit", type=int, default=200)

    p_kbs = sub.add_parser("kb-search", help="Search knowledge & terminology using FTS5 trigram + Chinese bigram matching.")
    p_kbs.add_argument("--query", required=True, help="Search query or customer message.")
    p_kbs.add_argument("--kind", default=None)
    p_kbs.add_argument("--library", default=None)
    p_kbs.add_argument("--limit", type=int, default=6)

    p_kba = sub.add_parser("kb-add", help="Add or publish a terminology/knowledge/script/faq entry.")
    p_kba.add_argument("--title", required=True)
    p_kba.add_argument("--body", required=True)
    p_kba.add_argument("--kind", choices=["terminology", "knowledge", "script", "faq"], default="knowledge")
    p_kba.add_argument("--library", default="shared")
    p_kba.add_argument("--keyword", action="append", default=[])
    p_kba.add_argument("--synonym", action="append", default=[])
    p_kba.add_argument("--source", default="cli")

    p_kbsync = sub.add_parser("kb-sync", help="Import published entries from OpenBot bot-knowledge/knowledge.sqlite.")
    p_kbsync.add_argument("--source-db", type=Path, default=None)

    sub.add_parser("persona-list", help="List available switchable personas, MBTI types, and interaction styles.")

    p_ps = sub.add_parser("persona-switch", help="Switch persona/MBTI/interaction style for a bound contact or group.")
    p_ps.add_argument("--target", required=True)
    p_ps.add_argument("--persona", required=True, help="Persona id or style name (e.g. warm-friend, wecom-kf-pro).")
    p_ps.add_argument("--mbti", default=None)
    p_ps.add_argument("--style", default=None, help="Interaction style (challenger, builder, neutral, supporter).")
    p_ps.add_argument("--note", default="")

    p_rp = sub.add_parser(
        "reply-preview",
        aliases=["ask"],
        help="Preview KB + persona smart reply for an incoming message.",
    )
    p_rp.add_argument("target_pos", nargs="?", default=None)
    p_rp.add_argument("incoming_pos", nargs="?", default=None)
    p_rp.add_argument("--target", dest="target_flag", default=None)
    p_rp.add_argument("--incoming", dest="incoming_flag", default=None)
    p_rp.add_argument("--persona", default=None)
    p_rp.add_argument("--model", default=None, help="Optional Magpie or custom provider model ID override.")
    p_rp.add_argument("--no-llm", action="store_true", help="Force deterministic KB template without calling LLM.")

    p_models = sub.add_parser("models", help="List Magpie gateway models and multi-vendor providers.")
    p_models.add_argument("--provider", default=None, help="Filter by route group / provider id (e.g. auto, deepseek, mistral).")
    p_models.add_argument("--refresh", action="store_true", help="Force refresh model catalog from Magpie gateway.")

    p_mset = sub.add_parser("model-set", help="Set global default or per-contact model via Magpie Hub.")
    p_mset.add_argument("model_id", nargs="?", default="", help="Model ID (e.g. auto/deepseek-v4-pro, mistral/mistral-large-4).")
    p_mset.add_argument("--contact", default=None, help="Optional contact name for per-contact model override.")
    p_mset.add_argument("--provider", default=None, help="Explicit provider ID.")
    p_mset.add_argument("--fallback", default=None, help="Fallback model ID when primary fails.")
    p_mset.add_argument("--enable-llm", dest="llm_flag", action="store_true", default=None)
    p_mset.add_argument("--disable-llm", dest="llm_flag", action="store_false")

    p_mprobe = sub.add_parser("model-probe", help="Live-probe a model via Magpie or configured provider.")
    p_mprobe.add_argument("model_id", nargs="?", default=None, help="Model ID to probe (defaults to activeModelId).")
    p_mprobe.add_argument("--provider", default=None)
    p_mprobe.add_argument("--prompt", default="请用不超过20个字回复：收到测试，状态正常。")

    p_psave = sub.add_parser("provider-save", help="Configure Magpie gateway or add/update a custom OpenAI-compatible provider.")
    p_psave.add_argument("--id", dest="provider_id", default="magpie-gateway")
    p_psave.add_argument("--name", default="")
    p_psave.add_argument("--base-url", default="")
    p_psave.add_argument("--gateway-url", default=None)
    p_psave.add_argument("--api", default="openai-completions")
    p_psave.add_argument("--api-key", default=None)
    p_psave.add_argument("--api-key-env", default=None)
    p_psave.add_argument("--default-model", default="")
    p_psave.add_argument("--vendor", default="Custom")
    p_psave.add_argument("--disabled", action="store_true")

    p_watch = sub.add_parser("watch", help="Run real-time WeChat monitor & smart auto-responder (--once or daemon loop).")
    p_watch.add_argument("--target", default=None, help="Optional single contact/group target filter.")
    p_watch.add_argument("--interval", type=float, default=2.5, help="Polling interval in seconds for loop mode.")
    p_watch.add_argument("--once", action="store_true", help="Run a single poll cycle and exit.")
    p_watch.add_argument("--max-cycles", type=int, default=None, help="Optional max cycles before stopping.")
    p_watch.add_argument("--no-auto-reply", action="store_true", help="Observe only without generating/sending replies.")
    p_watch.add_argument("--confirm-send", action="store_true", help="Dispatch live auto-replies via 3x readback + Return.")

    sub.add_parser("monitor-status", help="Inspect real-time monitor daemon state and per-contact checkpoints.")

    p_to = sub.add_parser("takeover", help="Mark a contact/group as human-taken-over (drafts only, no auto-send).")
    p_to.add_argument("--target", required=True)
    p_to.add_argument("--reason", default="")

    p_res = sub.add_parser("resume-contact", help="Resume AI auto-reply for a previously taken-over contact/group.")
    p_res.add_argument("--target", required=True)

    p_soul = sub.add_parser(
        "soul-profile",
        help="Analyze local chat records / WeChatBridge archives for Owner Self-Soul & Friend Psychological/Memory profiles.",
    )
    p_soul.add_argument("--target", default=None, help="Optional single contact or group filter.")
    p_soul.add_argument("--rebuild", action="store_true", help="Re-analyze all local chat logs and persist updates.")
    p_soul.add_argument("--use-llm", action="store_true", help="Also run Magpie LLM deep insight synthesis.")
    p_soul.add_argument("--model", default=None, help="Optional Magpie model ID override.")
    p_soul.add_argument("--import-archive", type=Path, default=None, help="Optional WeChatBridge .zip / 聊天记录.txt archive to ingest.")
    p_soul.add_argument("--contact-name", default=None, help="Contact name override when importing WeChatBridge archive.")
    p_soul.add_argument("--owner-sender", default=None, help="Owner sender display name inside WeChatBridge archive.")

    p_mem = sub.add_parser("memory-add", help="Add an explicit fact, event, or shared memory to a contact's Soul profile.")
    p_mem.add_argument("--target", required=True)
    p_mem.add_argument("--content", required=True)
    p_mem.add_argument("--category", choices=["fact", "event", "shared", "preference"], default="fact")
    p_mem.add_argument("--time-marker", default="")

    p_bench = sub.add_parser("benchmark", help="Run or inspect the 8-module WeChat RPA + Soul + Kimi acceptance benchmark.")
    p_bench.add_argument("--run", action="store_true", help="Execute fresh benchmark suite (otherwise returns latest).")
    p_bench.add_argument("--with-tests", action="store_true", help="Also execute full unittest discovery during benchmark.")

    p_crm = sub.add_parser(
        "crm",
        help="Aurora-73/SalesCRM open-source marketing CRM (15D metrics, BQ/BSP/BWS/PV formulas, reminders, Top 1-3 drafts).",
    )
    p_crm.add_argument("--sync", action="store_true", help="Incrementally sync WeChat contacts, chat logs, Soul & media into SalesCRM.")
    p_crm.add_argument("--reminders", action="store_true", help="List due and upcoming Beijing-time follow-up reminders.")
    p_crm.add_argument("--target", default=None, help="Target contact name, wxid, or person ID.")
    p_crm.add_argument("--enroll", action="store_true", help="Explicitly enroll --target into CRM funnel.")
    p_crm.add_argument("--update", action="store_true", help="Update stage, note, follow-up, and deal value for --target.")
    p_crm.add_argument("--stage", default=None, help="CRM funnel stage (新线索/初步触达/跟进中/方案推进/已报价/已成交/退出/失败).")
    p_crm.add_argument("--note", default="", help="Follow-up note (<= 2000 chars).")
    p_crm.add_argument("--follow-up", dest="follow_up", default=None, help="Beijing-time follow-up YYYY-MM-DDTHH:MM.")
    p_crm.add_argument("--deal-value", dest="deal_value", type=float, default=None, help="Expected deal amount (CNY).")
    p_crm.add_argument("--alias", default="", help="Optional contact alias or merged name.")
    p_crm.add_argument("--merge", default=None, help="Secondary contact name/account to merge into --target.")
    p_crm.add_argument("--complete-reminder", dest="complete_reminder", action="store_true", help="Mark --target due reminder completed.")
    p_crm.add_argument("--reschedule", default=None, help="Reschedule --target reminder to Beijing time YYYY-MM-DDTHH:MM.")
    p_crm.add_argument("--formulas", action="store_true", help="Evaluate SalesCRM BQ/BSP/BWS/PV/action formulas for --target.")
    p_crm.add_argument("--incoming", default="", help="Optional incoming message text for Top 1-3 follow-up draft generation.")
    p_crm.add_argument("--adopt-rank", dest="adopt_rank", type=int, choices=[1, 2, 3], default=None, help="Adopt Top 1-3 draft for --target.")
    p_crm.add_argument("--send-mode", dest="send_mode", choices=["adopt_only", "dry_run", "silent_verify"], default="adopt_only")
    p_crm.add_argument("--no-auto-sync", dest="no_auto_sync", action="store_true", help="Skip auto-sync on overview read.")

    p_bridge = sub.add_parser(
        "botstudio-bridge",
        help="Inspect, compile via dsh2codex, or export standalone + DSH + Bot Studio integration bundle.",
    )
    p_bridge.add_argument("--status", action="store_true", help="Return standalone + DSH + Bot Studio integration status.")
    p_bridge.add_argument("--compile-dsh", action="store_true", help="Compile dsh.plugin.json via dsh2codex into 4-Tab preset & page.")
    p_bridge.add_argument("--export-bundle", action="store_true", help="Export unified botstudio_integration_bundle.json.")
    p_bridge.add_argument("--install", action="store_true", help="Install WeChat Bot.app to /Users/mac/Applications and register inside Bot Studio.")
    p_bridge.add_argument("--open-app", action="store_true", help="Launch standalone WeChat Bot.app after install.")
    p_bridge.add_argument("--open-botstudio", action="store_true", help="Launch Bot Studio.app after install.")
    p_bridge.add_argument("--out", default=None, help="Optional output path for integration bundle JSON.")

    p_app = sub.add_parser(
        "launch-app",
        help="Verify or launch standalone WeChat Bot.app.",
    )
    p_app.add_argument("--verify-headless", action="store_true", help="Run headless verification check on standalone macOS .app.")
    p_app.add_argument("--open", action="store_true", help="Open WeChat Bot.app in macOS Finder/Dock.")
    p_app.add_argument("--dock", action="store_true", help="Launch or dock WeChat Bot.app as WeChat sidebar.")
    p_app.add_argument("--tile", action="store_true", help="Tile WeChat and WeChat Bot.app side-by-side.")

    sub.add_parser("serve-mcp", help="Run MCP JSON-RPC 2.0 server over stdin/stdout.")

    p_http = sub.add_parser(
        "serve-http",
        aliases=["console"],
        help="Run local Web Control Console & HTTP JSON API server.",
    )
    p_http.add_argument("--host", default="127.0.0.1")
    p_http.add_argument("--port", type=int, default=18788)

    p_tp = sub.add_parser(
        "train-playbook",
        help="Zero-FDE self-training: discover corpora, mine terms, synthesize playbooks, and approve drafts.",
    )
    p_tp.add_argument("--discover", action="store_true", help="Discover high-value WeChat sessions and local archives.")
    p_tp.add_argument("--archive", action="append", default=[], help="Repeatable path to .zip or *聊天记录*.txt archive.")
    p_tp.add_argument("--contact", action="append", default=[], help="Repeatable contact name from local observed histories.")
    p_tp.add_argument("--owner", default=None, help="Owner name for sender disambiguation.")
    p_tp.add_argument("--pack", default=None, help="Industry sales pack ID (default general_sales).")
    p_tp.add_argument("--approve", action="append", default=[], help="Approve draft KB entry ID(s).")
    p_tp.add_argument("--use-llm", action="store_true", help="Use configured LLM to enrich mined terms and scripts.")
    p_tp.add_argument("--no-auto-publish", action="store_true", help="Keep all synthesized entries as drafts.")

    p_tc = sub.add_parser(
        "test-contact",
        help="Manage internal test contacts (sandboxed from SalesCRM and allowed `#` directives).",
    )
    p_tc.add_argument("action", nargs="?", default="list", choices=["list", "add", "remove"], help="Action to perform.")
    p_tc.add_argument("target", nargs="?", default=None, help="Contact display name.")
    p_tc.add_argument("--name", default=None, help="Contact display name.")
    p_tc.add_argument("--note", default="", help="Optional note for test contact.")

    p_qd = sub.add_parser(
        "quality-dashboard",
        help="Inspect 1-5 star quality dashboard, run sparring regression, or rate a turn.",
    )
    p_qd.add_argument("--days", type=int, default=7, help="Lookback window in days.")
    p_qd.add_argument("--regression", action="store_true", help="Run regression suite over low-star/`#`-critiqued turns.")
    p_qd.add_argument("--limit", type=int, default=20, help="Max regression cases.")
    p_qd.add_argument("--rate-turn", type=int, default=None, help="Submit rating for turn ID.")
    p_qd.add_argument("--stars", type=int, default=None, help="Star rating 1..5.")
    p_qd.add_argument("--tag", action="append", default=[], help="Repeatable issue tag.")
    p_qd.add_argument("--comment", default="", help="Rating or critique comment.")

    p_waf = sub.add_parser(
        "wechat-add-friend",
        help="Search or send a WeChat friend request by WeChat ID or phone number.",
    )
    p_waf.add_argument("--account", required=True, help="Target WeChat ID or 11-digit phone number.")
    p_waf.add_argument("--greeting", default="", help="Friend verification greeting message.")
    p_waf.add_argument("--remark", default="", help="Optional WeChat remark name.")
    p_waf.add_argument("--source-user", default="", help="Optional source platform username (e.g. Douyin nickname).")
    p_waf.add_argument("--dry-run", action="store_true", default=True, help="Dry-run without sending (default).")
    p_waf.add_argument("--probe-ui", action="store_true", help="Open WeChat Add Friend UI and lookup without clicking Add.")
    p_waf.add_argument("--confirm-send", action="store_true", help="Actually send the friend request.")
    p_waf.add_argument("--force", action="store_true", help="Bypass dedup/cooldown/daily limit guard.")

    p_dyf = sub.add_parser(
        "douyin-funnel",
        help="Run or inspect the Douyin DM -> WeChat account extraction -> WeChat add-friend funnel.",
    )
    p_dyf.add_argument(
        "--action",
        default="overview",
        choices=["overview", "extract", "run", "add-wechat"],
        help="Funnel action to perform.",
    )
    p_dyf.add_argument("--target", default="", help="Douyin user name or lead ID.")
    p_dyf.add_argument("--account", default="", help="WeChat account when using add-wechat.")
    p_dyf.add_argument("--text", default="", help="Sample incoming text when using --action extract.")
    p_dyf.add_argument("--auto-reply", action="store_true", help="Also draft/send ask-WeChat DM replies.")
    p_dyf.add_argument("--auto-add-wechat", action="store_true", help="Also dry-run/add captured WeChat IDs.")
    p_dyf.add_argument("--dry-run", action="store_true", default=True, help="Dry-run mode (default).")
    p_dyf.add_argument("--probe-ui", action="store_true", help="Probe live WeChat/Douyin UI without sending.")
    p_dyf.add_argument("--confirm-send", action="store_true", help="Authorize live send / friend request.")

    p_wfa = sub.add_parser(
        "workflow-agent",
        help="Self-authoring & self-debugging cross-app Workflow Agent (Spec -> Build -> Debug -> Verify).",
    )
    p_wfa.add_argument(
        "--action",
        default="templates",
        choices=["templates", "spec", "author-debug", "debug", "sessions", "chat", "chat-edit"],
        help="Workflow agent action.",
    )
    p_wfa.add_argument("--goal", default="", help="Plain-language cross-app workflow goal.")
    p_wfa.add_argument("--app", action="append", default=[], help="Target app name or bundle ID (repeatable).")
    p_wfa.add_argument("--agent-id", default="", help="Optional planner/debugger agent ID.")
    p_wfa.add_argument("--mode", default="shadow", choices=["dry_run", "shadow", "live"], help="Verification mode.")
    p_wfa.add_argument("--max-rounds", type=int, default=4, help="Max self-debugging rounds (1-5).")
    p_wfa.add_argument("--confirm-run", action="store_true", help="Confirm real live execution when --mode live.")
    p_wfa.add_argument("--use-omini-critic", action="store_true", help="Also run Omini critic audit on generated Spec.")
    p_wfa.add_argument("--export-skill", action="store_true", help="Export verified workflow as SKILL.md.")
    p_wfa.add_argument("--workflow-id", default="", help="Existing workflow ID for --action debug or chat-edit.")
    p_wfa.add_argument("--chat-id", default="", help="Existing workflow-agent chat session ID for --action chat.")
    p_wfa.add_argument("--message", default="", help="User chat message for --action chat.")
    p_wfa.add_argument("--edit-instruction", default="", help="Natural-language edit instruction for --action chat-edit.")
    p_wfa.add_argument("--no-auto-verify", action="store_true", help="Skip automatic verification run after --action chat-edit.")
    p_wfa.add_argument("--params", default="{}", help="JSON runtime parameters override.")
    p_wfa.add_argument("--ignore-human-guard", action="store_true", help="Ignore human input guard during controlled verification.")
    p_wfa.add_argument("--no-inspect", action="store_true", help="Skip initial live window probe.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    engine = WeChatControlEngine()

    try:
        if args.command == "doctor":
            return _print_json(engine.doctor())
        if args.command == "request-permissions":
            return _print_json(engine.request_permissions(open_settings=not args.no_settings))
        if args.command == "auth-status":
            return _print_json(engine.auth_status())
        if args.command == "auth-grant":
            caps = None
            if args.all:
                caps = ["*"]
            elif args.read_only:
                caps = list(READ_ONLY_CAPABILITIES)
            elif args.caps:
                caps = args.caps
            return _print_json(engine.auth_grant(caps, authorized_by=args.by, note=args.note))
        if args.command == "auth-revoke":
            return _print_json(engine.auth_revoke(reason=args.reason))
        if args.command == "status":
            return _print_json(engine.get_status())
        if args.command == "sessions":
            return _print_json(engine.list_sessions())
        if args.command == "inspect-live":
            return _print_json(
                engine.inspect_live_wechat(
                    max_session_pages=args.session_pages,
                    max_contact_pages=args.contact_pages,
                )
            )
        if args.command == "messages":
            return _print_json(engine.read_messages(limit=args.limit))
        if args.command == "ocr":
            if args.image:
                return _print_json(engine.ocr_image(args.image))
            return _print_json(engine.ocr_wechat_window(save_path=args.out))
        if args.command == "send":
            if args.confirm_send:
                dry_run = False
                silent_mode = False
            elif args.silent_verify:
                dry_run = False
                silent_mode = True
            else:
                dry_run = True
                silent_mode = True
            res = engine.send_text(
                target=args.target,
                text=args.text,
                dry_run=dry_run,
                silent_mode=silent_mode,
                confirm_send=args.confirm_send,
                allowed_groups=args.allowed_groups,
            )
            return _print_json(res)
        if args.command == "moments":
            action = args.action or "stats"
            if action == "read":
                return _print_json(engine.moments_read_feed(max_posts=args.max_posts, max_pages=args.max_pages))
            if action == "posts":
                return _print_json(engine.moments_list_posts(
                    limit=args.limit, author=args.author or "", include_partial=args.include_partial,
                ))
            if action == "post":
                return _print_json(engine.moments.get_post(args.key or ""))
            if action == "stats":
                return _print_json(engine.moments_stats(limit=args.limit))
            if action == "policy":
                if args.set_policy is None:
                    return _print_json(engine.moments_get_policy())
                try:
                    updates = json.loads(args.set_policy)
                except json.JSONDecodeError as exc:
                    return _print_json({"ok": False, "error": f"--set-policy 不是合法的 JSON：{exc}"})
                return _print_json(engine.moments_set_policy(updates))
            if action == "plan":
                return _print_json(engine.moments_plan(limit=args.limit))
            if action == "run-plan":
                return _print_json(engine.moments_execute_plan(mode=args.mode, limit=args.limit))
            if action == "log":
                return _print_json(engine.moments_log(limit=args.limit))
            if action == "suggest-comment":
                return _print_json(engine.moments_suggest_comment(args.key or "", style=args.style or "natural"))
            if action == "comment" and not (args.text or "").strip():
                return _print_json({"ok": False, "error_code": "comment_text_required", "error": "comment 需要用 --text 提供评论内容"})
            return _print_json(engine.moments_interact(
                args.key or "", author=args.author or "", action=action, text=args.text or "", mode=args.mode,
            ))
        if args.command == "call-brief":
            return _print_json(
                engine.get_pre_call_brief(
                    args.target,
                    goal=args.goal,
                    custom_goal=args.custom_goal,
                    use_llm=not bool(args.no_llm),
                )
            )
        if args.command == "import-chatlog":
            res = engine.import_chatlog(args.input, output_dir=args.out_dir)
            return _print_json(res)
        if args.command == "export-article":
            from_window = bool(args.from_window or not args.url)
            res = engine.export_article(
                url=args.url,
                from_window=from_window,
                max_scroll_pages=args.pages,
                download_images=not args.no_images,
                try_copy_link=not args.no_copy_link,
                output_dir=str(args.out_dir) if args.out_dir else None,
            )
            return _print_json(res)
        if args.command == "exported-articles":
            return _print_json(engine.list_exported_articles(limit=args.limit))
        if args.command == "export-account":
            if args.list:
                return _print_json(engine.list_exported_accounts(limit=args.limit))
            return _print_json(
                engine.export_account_articles(
                    account_name=args.account,
                    album_url=args.album_url,
                    article_urls=args.urls,
                    from_file=str(args.from_file) if args.from_file else None,
                    scan_open_window=bool(args.scan_window),
                    scroll_pages=args.scroll_pages,
                    download_images=not bool(args.no_images),
                    max_articles=args.max_articles,
                )
            )
        if args.command == "export-channels":
            if args.list:
                return _print_json(engine.list_exported_channels(limit=args.limit))
            return _print_json(
                engine.export_channels_videos(
                    author_name=args.author,
                    video_urls=args.video_urls,
                    manifest_path=str(args.manifest) if args.manifest else None,
                    cache_dir=str(args.cache_dir) if args.cache_dir else None,
                    scan_open_window=bool(args.scan_window),
                    scroll_pages=args.scroll_pages,
                    download_media=not bool(args.no_media),
                    max_videos=args.max_videos,
                )
            )
        if args.command == "ui-schema":
            return _print_json(engine.get_ui_schema())
        if args.command == "ui-state":
            return _print_json(engine.inspect_ui_state(refresh_ocr=bool(args.refresh_ocr)))
        if args.command == "ui-navigate":
            return _print_json(
                engine.navigate_ui(
                    args.target,
                    dry_run=bool(args.dry_run),
                    respect_human_guard=not bool(args.ignore_human_guard),
                )
            )
        if args.command == "human-guard":
            enabled_arg = True if args.enable else (False if args.disable else None)
            if (
                enabled_arg is None
                and args.idle_seconds is None
                and args.cooldown_seconds is None
                and not args.reset
            ):
                return _print_json(engine.get_human_guard_status())
            return _print_json(
                engine.configure_human_guard(
                    enabled=enabled_arg,
                    idle_resume_seconds=args.idle_seconds,
                    cooldown_seconds=args.cooldown_seconds,
                    reset_cooldown=bool(args.reset),
                )
            )
        if args.command == "bind-contact":
            scheduled_enabled = False if args.disable_scheduled else (True if args.scheduled else True)
            auto_reply_enabled = False if args.disable_auto_reply else (True if args.auto_reply else True)
            return _print_json(
                engine.bind_contact(
                    args.target,
                    alias=args.alias,
                    role=args.role,
                    ai_persona=args.ai_persona,
                    scheduled_enabled=scheduled_enabled,
                    cron_hint=args.cron,
                    auto_reply_enabled=auto_reply_enabled,
                    notes=args.note,
                    special_care=True if args.special_care else None,
                    care_level=args.care_level,
                    care_tags=args.care_tag,
                    follow_up_days=args.follow_up_days,
                    bound_agent_id=args.agent_id,
                    bound_agent_name=args.agent_name,
                    bound_agent_type=args.agent_type,
                    vision_model_id=args.vision_model,
                    auto_dispatch_instructions=args.auto_dispatch,
                    auto_analyze_links_and_media=args.auto_analyze_media,
                )
            )
        if args.command == "analyze-media":
            crop_dict = None
            if args.crop:
                parts = [p.strip() for p in str(args.crop).split(",")]
                if len(parts) != 4:
                    parser.error("--crop expects x,y,w,h (4 comma-separated integers)")
                try:
                    crop_dict = {
                        "x": int(parts[0]),
                        "y": int(parts[1]),
                        "width": int(parts[2]),
                        "height": int(parts[3]),
                    }
                except ValueError:
                    parser.error("--crop values must be integers")
            return _print_json(
                engine.analyze_media_or_link(
                    kind=args.kind,
                    url=args.url,
                    image_path=args.image,
                    video_path=args.video,
                    crop_region=crop_dict,
                    from_viewer_window=bool(args.from_viewer),
                    source_snapshot=args.snapshot,
                    window_title=args.window_title,
                    contact=args.contact,
                    context_text=args.context,
                    frame_count=args.frame_count,
                    model_id=args.model_id,
                    allow_loopback=bool(args.allow_loopback),
                )
            )
        if args.command == "agent-dispatch":
            return _print_json(
                engine.dispatch_friend_instructions(
                    args.target,
                    include_live_media=not bool(args.no_media),
                    execute_with_agent=not bool(args.parse_only),
                    model_id=args.model_id,
                )
            )
        if args.command == "dock-sidebar":
            return _print_json(engine.dock_app_to_wechat(mode=args.mode))
        if args.command in ("special-care", "care"):
            target_val = args.target_flag or args.target_pos
            if not target_val:
                parser.error("special-care/care requires a target (positional or --target)")
            return _print_json(
                engine.set_special_care(
                    target_val,
                    enabled=not args.disable,
                    care_level="normal" if args.disable else args.level,
                    care_tags=args.tag,
                    follow_up_days=args.follow_up_days,
                    notes=args.note,
                )
            )
        if args.command in ("web-overview", "overview"):
            return _print_json(engine.get_web_overview())
        if args.command == "unbind-contact":
            return _print_json(engine.unbind_contact(args.target))
        if args.command == "list-bindings":
            return _print_json(engine.list_bindings())
        if args.command == "observe-contact":
            return _print_json(engine.observe_contact(args.target, scroll_pages=args.pages))
        if args.command == "profile-contact":
            focus = None if args.all else args.target
            return _print_json(engine.profile_contacts(focus))
        if args.command == "chat-test":
            return _print_json(
                engine.chat_test(
                    args.target,
                    mode=args.mode,
                    text=args.text,
                    confirm_send=args.confirm_send,
                    silent_verify=args.silent_verify,
                )
            )
        if args.command == "kb-list":
            return _print_json(engine.kb_list(kind=args.kind, library=args.library, limit=args.limit))
        if args.command == "kb-search":
            return _print_json(
                engine.kb_search(args.query, kind=args.kind, library=args.library, limit=args.limit)
            )
        if args.command == "kb-add":
            return _print_json(
                engine.kb_save(
                    title=args.title,
                    body=args.body,
                    kind=args.kind,
                    library=args.library,
                    keywords=args.keyword,
                    synonyms=args.synonym,
                    source=args.source,
                )
            )
        if args.command == "kb-sync":
            return _print_json(engine.kb_sync_openbot(args.source_db))
        if args.command == "persona-list":
            return _print_json(engine.persona_list())
        if args.command == "persona-switch":
            return _print_json(
                engine.persona_switch(
                    args.target,
                    args.persona,
                    mbti=args.mbti,
                    interaction_style=args.style,
                    custom_note=args.note,
                )
            )
        if args.command in ("reply-preview", "ask"):
            rp_target = args.target_flag or args.target_pos
            rp_incoming = args.incoming_flag or args.incoming_pos
            if not rp_target or not rp_incoming:
                parser.error("reply-preview/ask requires target and incoming message (--target/--incoming or positional)")
            return _print_json(
                engine.preview_smart_reply(
                    rp_target,
                    rp_incoming,
                    persona_override=args.persona,
                    model_id=args.model,
                    use_llm=False if args.no_llm else None,
                )
            )
        if args.command == "models":
            return _print_json(engine.list_models(refresh=args.refresh, provider_filter=args.provider))
        if args.command == "model-set":
            return _print_json(
                engine.select_model(
                    model_id=args.model_id,
                    contact=args.contact,
                    provider_id=args.provider,
                    fallback_model_id=args.fallback,
                    llm_enabled=args.llm_flag,
                )
            )
        if args.command == "model-probe":
            return _print_json(
                engine.probe_model(
                    model_id=args.model_id,
                    provider_id=args.provider,
                    prompt=args.prompt,
                )
            )
        if args.command == "provider-save":
            return _print_json(
                engine.save_provider(
                    provider_id=args.provider_id,
                    name=args.name,
                    base_url=args.base_url,
                    api=args.api,
                    api_key=args.api_key,
                    api_key_env=args.api_key_env,
                    default_model=args.default_model,
                    vendor=args.vendor,
                    enabled=not args.disabled,
                    gateway_url=args.gateway_url,
                )
            )
        if args.command == "watch":
            auto_reply = not args.no_auto_reply
            if args.once:
                return _print_json(
                    engine.monitor_once(
                        target=args.target,
                        auto_reply=auto_reply,
                        confirm_send=args.confirm_send,
                    )
                )
            return _print_json(
                engine.monitor_loop(
                    interval_seconds=args.interval,
                    max_cycles=args.max_cycles,
                    target=args.target,
                    auto_reply=auto_reply,
                    confirm_send=args.confirm_send,
                )
            )
        if args.command == "monitor-status":
            return _print_json(engine.monitor_status())
        if args.command == "takeover":
            return _print_json(engine.takeover_contact(args.target, reason=args.reason))
        if args.command == "resume-contact":
            return _print_json(engine.resume_contact(args.target))
        if args.command == "soul-profile":
            if args.import_archive:
                return _print_json(
                    engine.import_bridge_to_soul(
                        args.import_archive,
                        contact_name=args.contact_name or args.target,
                        owner_sender=args.owner_sender,
                    )
                )
            return _print_json(
                engine.get_soul_profiles(
                    target=args.target,
                    rebuild=bool(args.rebuild or args.use_llm),
                    use_llm=bool(args.use_llm),
                    model_id=args.model,
                )
            )
        if args.command == "memory-add":
            return _print_json(
                engine.add_soul_memory(
                    args.target,
                    args.content,
                    category=args.category,
                    time_marker=args.time_marker,
                )
            )
        if args.command == "crm":
            if args.sync:
                return _print_json(engine.crm_sync_from_wechat())
            if args.reminders:
                return _print_json(engine.crm_list_reminders())
            if args.merge:
                if not args.target:
                    raise ValueError("--merge 必须配合 --target 使用。")
                return _print_json(engine.crm_merge_accounts(args.target, args.merge, alias=args.alias or ""))
            if args.enroll:
                if not args.target:
                    raise ValueError("--enroll 必须配合 --target 使用。")
                return _print_json(
                    engine.crm_enroll_contact(
                        args.target,
                        stage=args.stage or "新线索",
                        note=args.note or "",
                        follow_up=args.follow_up,
                        deal_value=float(args.deal_value or 0.0),
                        alias=args.alias or "",
                    )
                )
            if args.update:
                if not args.target:
                    raise ValueError("--update 必须配合 --target 使用。")
                return _print_json(
                    engine.crm_update_record(
                        args.target,
                        stage=args.stage or "跟进中",
                        note=args.note or "",
                        follow_up=args.follow_up,
                        deal_value=args.deal_value,
                    )
                )
            if args.complete_reminder:
                if not args.target:
                    raise ValueError("--complete-reminder 必须配合 --target 使用。")
                return _print_json(engine.crm_complete_reminder(args.target))
            if args.reschedule:
                if not args.target:
                    raise ValueError("--reschedule 必须配合 --target 使用。")
                return _print_json(engine.crm_reschedule_reminder(args.target, args.reschedule))
            if args.adopt_rank is not None:
                if not args.target:
                    raise ValueError("--adopt-rank 必须配合 --target 使用。")
                return _print_json(
                    engine.crm_adopt_draft(
                        args.target,
                        rank_index=int(args.adopt_rank),
                        send_mode=args.send_mode or "adopt_only",
                    )
                )
            if args.formulas:
                if not args.target:
                    raise ValueError("--formulas 必须配合 --target 使用。")
                return _print_json(engine.crm_evaluate_formulas(args.target))
            if args.target:
                return _print_json(engine.crm_analyze_contact(args.target, incoming_text=args.incoming or ""))
            return _print_json(engine.crm_overview(auto_sync=not args.no_auto_sync))
        if args.command == "benchmark":
            if args.run or args.with_tests:
                return _print_json(engine.run_benchmark(include_tests=bool(args.with_tests)))
            return _print_json(engine.get_benchmark_report())
        if args.command == "botstudio-bridge":
            if args.install:
                return _print_json(
                    engine.install_to_host(
                        launch_standalone=bool(args.open_app),
                        launch_bot_studio=bool(args.open_botstudio),
                    )
                )
            if args.export_bundle:
                return _print_json(engine.export_botstudio_integration_bundle(out_path=args.out))
            if args.compile_dsh:
                return _print_json(engine.compile_dsh_plugin_for_botstudio())
            return _print_json(engine.get_botstudio_bridge_status())
        if args.command == "launch-app":
            installed_app = Path("/Users/mac/Applications/WeChat Bot.app")
            app_bundle = (
                installed_app
                if (installed_app / "Contents" / "MacOS" / "wechat-studio-app").is_file()
                else (engine.plugin_root / "dist" / "WeChat Bot.app")
            )
            exe_path = app_bundle / "Contents" / "MacOS" / "wechat-studio-app"
            if not exe_path.is_file():
                exe_path = engine.plugin_root / "bin" / "wechat-studio-app"
            if args.tile:
                return _print_json(engine.dock_app_to_wechat(mode="tile"))
            if args.dock:
                return _print_json(engine.dock_app_to_wechat(mode="dock"))
            if args.open:
                subprocess.run(["open", str(app_bundle)], check=False)
                return _print_json({"ok": True, "opened": str(app_bundle)})
            if not exe_path.is_file():
                return _print_json({"ok": False, "error": f"Standalone app binary not found: {exe_path}"})
            proc = subprocess.run([str(exe_path), "--verify-headless"], capture_output=True, text=True, timeout=15.0)
            if proc.returncode == 0 and proc.stdout.strip():
                print(proc.stdout.strip())
                return 0
            return _print_json({
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            })
        if args.command == "serve-mcp":
            WeChatMCPServer(engine).serve_stdio()
            return 0
        if args.command in ("serve-http", "console"):
            print(f"OpenBot WeChat Web Control Console -> http://{args.host}:{args.port}/", flush=True)
            serve_http(engine, host=args.host, port=args.port)
            return 0
        if args.command == "govern":
            from .resource_governor import govern as _govern
            print(json.dumps(_govern(engine.plugin_root), ensure_ascii=False, indent=2))
            return 0
        if args.command == "train-playbook":
            if args.approve:
                return _print_json(engine.approve_training_drafts(args.approve))
            if args.discover and not args.archive and not args.contact:
                return _print_json(engine.discover_training_corpus())
            return _print_json(
                engine.run_self_training(
                    archive_paths=args.archive or None,
                    contact_targets=args.contact or None,
                    owner_name=args.owner,
                    industry_pack=args.pack,
                    use_llm=bool(args.use_llm),
                    auto_publish_safe=not bool(args.no_auto_publish),
                )
            )
        if args.command == "test-contact":
            if args.action == "list":
                return _print_json(engine.list_test_contacts())
            cname = (args.name or args.target or "").strip()
            if not cname:
                parser.error("test-contact add/remove requires a contact name (--name or positional target)")
            return _print_json(
                engine.set_test_contact(
                    cname,
                    enabled=(args.action == "add"),
                    note=args.note,
                )
            )
        if args.command == "quality-dashboard":
            if args.rate_turn is not None:
                if args.stars is None:
                    parser.error("quality-dashboard --rate-turn requires --stars 1..5")
                return _print_json(
                    engine.submit_reply_rating(
                        args.rate_turn,
                        stars=args.stars,
                        tags=args.tag,
                        comment=args.comment,
                    )
                )
            if args.regression:
                return _print_json(engine.run_sparring_regression(limit=args.limit))
            return _print_json(engine.get_quality_dashboard(days=args.days))
        if args.command == "wechat-add-friend":
            is_live = bool(args.confirm_send)
            return _print_json(
                engine.wechat_add_friend(
                    args.account,
                    greeting=args.greeting,
                    remark=args.remark,
                    source_user=args.source_user,
                    dry_run=not is_live,
                    probe_ui=bool(args.probe_ui),
                    confirm_send=is_live,
                    force=bool(args.force),
                )
            )
        if args.command == "douyin-funnel":
            is_live = bool(args.confirm_send)
            if args.action == "overview":
                return _print_json(engine.douyin_funnel_overview())
            if args.action == "extract":
                msgs = [{"sender": args.target or "抖音访客", "direction": "incoming", "text": args.text}] if args.text else []
                return _print_json(engine.douyin_funnel_ingest(msgs, douyin_user=args.target, source="cli"))
            if args.action == "add-wechat":
                return _print_json(
                    engine.douyin_funnel_add_wechat(
                        args.account or args.target,
                        dry_run=not is_live,
                        probe_ui=bool(args.probe_ui),
                        confirm_send=is_live,
                    )
                )
            return _print_json(
                engine.douyin_funnel_run_cycle(
                    target=args.target,
                    auto_reply=bool(args.auto_reply),
                    auto_add_wechat=bool(args.auto_add_wechat),
                    dry_run=not is_live,
                    probe_ui=bool(args.probe_ui),
                    confirm_send=is_live,
                )
            )
        if args.command == "workflow-agent":
            import json as _json
            try:
                parsed_params = _json.loads(args.params or "{}")
                if not isinstance(parsed_params, dict):
                    parsed_params = {}
            except Exception:
                parsed_params = {}
            if args.action == "templates":
                return _print_json(engine.workflow_agent_templates())
            if args.action == "sessions":
                return _print_json(engine.workflow_agent_list_sessions())
            if args.action == "chat":
                return _print_json(
                    engine.workflow_agent_chat_turn(
                        args.message or args.goal,
                        chat_id=args.chat_id,
                        agent_id=args.agent_id,
                        mode=args.mode,
                        auto_run_on_confirm=True,
                        confirm_run=bool(args.confirm_run),
                        params=parsed_params,
                    )
                )
            if args.action == "chat-edit":
                return _print_json(
                    engine.workflow_agent_chat_edit(
                        args.workflow_id,
                        args.edit_instruction or args.message or args.goal,
                        agent_id=args.agent_id,
                        mode=args.mode,
                        auto_verify=not bool(args.no_auto_verify),
                        confirm_run=bool(args.confirm_run),
                        respect_human_guard=not bool(args.ignore_human_guard),
                        params=parsed_params,
                    )
                )
            if args.action == "spec":
                return _print_json(
                    engine.workflow_agent_propose_spec(
                        args.goal,
                        target_apps=args.app or None,
                        agent_id=args.agent_id,
                        inspect_live=not bool(args.no_inspect),
                        use_omini_critic=bool(args.use_omini_critic),
                    )
                )
            if args.action == "debug":
                return _print_json(
                    engine.workflow_agent_debug_existing(
                        args.workflow_id,
                        mode=args.mode,
                        max_debug_rounds=args.max_rounds,
                        confirm_run=bool(args.confirm_run),
                        respect_human_guard=not bool(args.ignore_human_guard),
                        agent_id=args.agent_id,
                        params=parsed_params,
                    )
                )
            return _print_json(
                engine.workflow_agent_author_and_debug(
                    args.goal,
                    target_apps=args.app or None,
                    agent_id=args.agent_id,
                    mode=args.mode,
                    max_debug_rounds=args.max_rounds,
                    confirm_run=bool(args.confirm_run),
                    respect_human_guard=not bool(args.ignore_human_guard),
                    inspect_live=not bool(args.no_inspect),
                    use_omini_critic=bool(args.use_omini_critic),
                    auto_export_skill=bool(args.export_skill),
                    params=parsed_params,
                )
            )
        parser.print_help()
        return 2
    except StudioPluginUnauthorizedError as exc:
        return _print_json({
            "ok": False,
            "error_code": exc.code,
            "capability": exc.capability,
            "error": str(exc),
        })


if __name__ == "__main__":
    sys.exit(main())
