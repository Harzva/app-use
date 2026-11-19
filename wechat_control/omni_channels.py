"""Unified Multi-Channel App-Use RPA + Open-Source Connector Hub (v2.5.0).

Generalizes WeChatBot's native AX + Vision OCR + Bezier/Paste RPA + SalesCRM
pipeline across 6 channels in priority order:
  1. Feishu (飞书 / Lark) — Electron Desktop RPA + lark-oapi WS/IM/Webhook
  2. DingTalk (钉钉) — Desktop RPA + ego-browser Web + dingtalk-stream/Webhook
  3. Xiaohongshu (小红书) — ego-browser Web/Creator RPA + xhs-publisher anti-ban
  4. Douyin (抖音) — Desktop + ego-browser Web/Creator comment/DM lead-gen RPA
  5. WeChat (微信) & 6. WeCom (企业微信) — existing native dual-app RPA
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .io_utils import atomic_write_json

REAL_USER_HOME = Path("/Users/mac") if Path("/Users/mac").is_dir() else Path.home()
EGO_BROWSER_BIN = REAL_USER_HOME / ".local" / "bin" / "ego-browser"
XHS_PUBLISHER_BIN = REAL_USER_HOME / ".local" / "bin" / "xhs-publisher"

CHANNEL_ORDER: Tuple[str, ...] = (
    "feishu",
    "dingtalk",
    "xiaohongshu",
    "douyin",
    "wechat",
    "wecom",
)

CHANNEL_ALIASES: Dict[str, str] = {
    "feishu": "feishu",
    "lark": "feishu",
    "飞书": "feishu",
    "dingtalk": "dingtalk",
    "ding": "dingtalk",
    "钉钉": "dingtalk",
    "xiaohongshu": "xiaohongshu",
    "xhs": "xiaohongshu",
    "rednote": "xiaohongshu",
    "小红书": "xiaohongshu",
    "douyin": "douyin",
    "tiktok": "douyin",
    "抖音": "douyin",
    "wechat": "wechat",
    "微信": "wechat",
    "wecom": "wecom",
    "wework": "wecom",
    "企业微信": "wecom",
    "企微": "wecom",
}

CHANNEL_SPECS: Dict[str, Dict[str, Any]] = {
    "feishu": {
        "channelId": "feishu",
        "label": "飞书 (Feishu / Lark)",
        "shortLabel": "飞书",
        "category": "enterprise_im",
        "priority": 1,
        "bundleIds": ["com.bytedance.macos.feishu", "com.electron.lark"],
        "appPaths": [
            "/Applications/Lark.app",
            "/Applications/Feishu.app",
            "/Volumes/SanDisk/Applications/Lark.app",
            "/Volumes/SanDisk/Applications/Feishu.app",
            str(REAL_USER_HOME / "Applications/Lark.app"),
        ],
        "webUrls": {
            "home": "https://www.feishu.cn/messenger/",
            "im": "https://www.feishu.cn/messenger/",
            "open_platform": "https://open.feishu.cn/app",
            "download": "https://www.feishu.cn/download",
        },
        "electronAx": True,
        "supportsRpa": True,
        "supportsVoiceCall": True,
        "supportsWebRpa": True,
        "supportsOpenProtocol": True,
        "defaultMode": "desktop_rpa",
        "loginHints": ["扫码登录", "请使用飞书扫码", "登录飞书", "验证码登录", "使用密码登录", "Sign in to Lark"],
    },
    "dingtalk": {
        "channelId": "dingtalk",
        "label": "钉钉 (DingTalk)",
        "shortLabel": "钉钉",
        "category": "enterprise_im",
        "priority": 2,
        "bundleIds": ["com.alibaba.DingTalkMac"],
        "appPaths": [
            "/Volumes/SanDisk/Applications/DingTalk.app",
            "/Volumes/SanDisk/Applications/钉钉.app",
            "/Applications/DingTalk.app",
            "/Applications/钉钉.app",
            str(REAL_USER_HOME / "Applications/DingTalk.app"),
        ],
        "webUrls": {
            "home": "https://im.dingtalk.com/",
            "im": "https://im.dingtalk.com/",
            "open_platform": "https://open-dev.dingtalk.com/",
            "download": "https://www.dingtalk.com/download",
        },
        "electronAx": True,
        "supportsRpa": True,
        "supportsVoiceCall": True,
        "supportsWebRpa": True,
        "supportsOpenProtocol": True,
        "defaultMode": "web_or_rpa",
        "loginHints": ["扫码登录", "钉钉扫码", "密码登录", "欢迎使用钉钉"],
    },
    "xiaohongshu": {
        "channelId": "xiaohongshu",
        "label": "小红书 (Xiaohongshu)",
        "shortLabel": "小红书",
        "category": "social_leadgen",
        "priority": 3,
        "bundleIds": ["com.xingin.xhs"],
        "appPaths": [
            "/Applications/小红书.app",
            "/Applications/REDnote.app",
            "/Volumes/SanDisk/Applications/小红书.app",
            str(REAL_USER_HOME / "Applications/小红书.app"),
        ],
        "webUrls": {
            "home": "https://www.xiaohongshu.com/explore",
            "im": "https://www.xiaohongshu.com/notification",
            "creator": "https://creator.xiaohongshu.com/",
            "search": "https://www.xiaohongshu.com/search_result?keyword={query}",
        },
        "electronAx": False,
        "supportsRpa": True,
        "supportsVoiceCall": False,
        "supportsWebRpa": True,
        "supportsOpenProtocol": False,
        "defaultMode": "ego_browser_web",
        "loginHints": ["登录后查看搜索结果", "扫码登录", "手机号登录", "App扫码登录"],
    },
    "douyin": {
        "channelId": "douyin",
        "label": "抖音 (Douyin)",
        "shortLabel": "抖音",
        "category": "social_leadgen",
        "priority": 4,
        "bundleIds": ["com.bytedance.douyin.desktop"],
        "appPaths": [
            "/Applications/抖音.app",
            "/Applications/Douyin.app",
            "/Volumes/SanDisk/Applications/抖音.app",
            "/Volumes/SanDisk/Applications/Douyin.app",
            str(REAL_USER_HOME / "Applications/抖音.app"),
        ],
        "webUrls": {
            "home": "https://www.douyin.com/",
            "im": "https://creator.douyin.com/creator-micro/data/following/chat",
            "creator": "https://creator.douyin.com/",
            "search": "https://www.douyin.com/search/{query}",
            "download": "https://www.douyin.com/downloadpage/pc",
        },
        "electronAx": True,
        "supportsRpa": True,
        "supportsVoiceCall": False,
        "supportsWebRpa": True,
        "supportsOpenProtocol": False,
        "defaultMode": "ego_browser_web",
        "loginHints": ["登录解锁更多精彩内容", "扫码登录", "验证码登录"],
    },
    "wechat": {
        "channelId": "wechat",
        "label": "微信 (WeChat)",
        "shortLabel": "微信",
        "category": "private_domain",
        "priority": 5,
        "bundleIds": ["com.tencent.xinWeChat"],
        "appPaths": ["/Applications/WeChat.app", "/Volumes/SanDisk/Applications/WeChat.app"],
        "webUrls": {},
        "electronAx": False,
        "supportsRpa": True,
        "supportsVoiceCall": True,
        "supportsWebRpa": False,
        "supportsOpenProtocol": False,
        "defaultMode": "desktop_rpa",
        "loginHints": ["微信登录", "扫码登录"],
    },
    "wecom": {
        "channelId": "wecom",
        "label": "企业微信 (WeCom)",
        "shortLabel": "企业微信",
        "category": "private_domain",
        "priority": 6,
        "bundleIds": ["com.tencent.WeWorkMac"],
        "appPaths": [
            "/Volumes/SanDisk/Applications/企业微信.app",
            "/Volumes/SanDisk/Applications/WeCom.app",
            "/Applications/企业微信.app",
            "/Applications/WeCom.app",
        ],
        "webUrls": {},
        "electronAx": False,
        "supportsRpa": True,
        "supportsVoiceCall": True,
        "supportsWebRpa": False,
        "supportsOpenProtocol": False,
        "defaultMode": "desktop_rpa",
        "loginHints": ["企业微信登录", "扫码登录"],
    },
}

OPEN_SOURCE_CHANNEL_STACKS: Dict[str, List[Dict[str, str]]] = {
    "global": [
        {
            "repo": "langbot-app/LangBot",
            "role": "Multi-IM Agent Gateway",
            "note": "开源多平台机器人框架，原生支持飞书/钉钉/企微 + MCP/Dify/LLM 对接",
        },
        {
            "repo": "AstrBotDevs/AstrBot",
            "role": "Agent + Knowledge IM Hub",
            "note": "支持飞书/钉钉/QQ/企微的长连接插件生态与知识库问答",
        },
        {
            "repo": "bytedance/UI-TARS-desktop",
            "role": "Desktop GUI Agent Reference",
            "note": "开源桌面 GUI App-Use 参考架构（与本机 wechat-vision-ax AX+OCR 同构）",
        },
    ],
    "feishu": [
        {
            "repo": "larksuite/oapi-sdk-python",
            "role": "Official WebSocket Long-Connection (lark-oapi)",
            "note": "无需公网 IP/Webhook 域名，通过 wss:// 长连接实时收发飞书事件与消息",
        },
        {
            "repo": "larksuite/lark-openapi-mcp (@larksuiteoapi/lark-mcp)",
            "role": "Official Feishu MCP Tools",
            "note": "暴露飞书消息、文档、日历、多维表格标准化 MCP 工具",
        },
        {
            "repo": "Built-in HMAC Webhook + IM REST Bridge",
            "role": "Zero-Dep Native Connector",
            "note": "内置无三方依赖 HMAC-SHA256 群机器人签名发送 & Tenant IM API 发信",
        },
    ],
    "dingtalk": [
        {
            "repo": "open-dingtalk/dingtalk-stream-sdk-python",
            "role": "Official Stream Mode SDK",
            "note": "无需公网回调 IP，长连接接收钉钉机器人对话、卡片事件并直接回包",
        },
        {
            "repo": "Built-in DingTalk Webhook + ego-browser im.dingtalk.com",
            "role": "Hybrid RPA + Signed Webhook",
            "note": "内置 HMAC-SHA256 钉钉加签机器人发送 + Web 端与桌面端双重 RPA",
        },
    ],
    "xiaohongshu": [
        {
            "repo": "xpzouying/xiaohongshu-mcp",
            "role": "Xiaohongshu MCP Inspiration",
            "note": "搜索笔记、读取详情、未读通知/评论抓取与合规互动流程参考",
        },
        {
            "repo": "BodaFu/auto-rednote & puyujian/xhssx",
            "role": "Logged-in Browser Lead-Gen RPA",
            "note": "复用本地已登录浏览器会话，配合话术去 AI 味、防封频率锁识别专业号/笔记线索",
        },
        {
            "repo": "Local xhs-publisher CLI",
            "role": "Installed Local Anti-Ban Guard",
            "note": "本机已集成 /Users/mac/.local/bin/xhs-publisher（夜间门禁、配额台账、文案审计）",
        },
    ],
    "douyin": [
        {
            "repo": "cs-lazy-tools/ChatGPT-On-CS",
            "role": "Multi-Platform Private-Domain CS",
            "note": "抖音/小红书多端统一客服引流模式，结合知识库识别高意向线索入私域",
        },
        {
            "repo": "dreammis/social-auto-upload",
            "role": "Douyin Creator Automation Reference",
            "note": "抖音创作者后台评论区/私信与多平台矩阵运营架构参考",
        },
    ],
    "wechat": [
        {"repo": "Aurora-73/SalesCRM (vendored)", "role": "15D CRM Funnel", "note": "已深度集成的 15 维线索转化与跟进引擎"},
    ],
    "wecom": [
        {"repo": "Native Dual-App AX+VoIP Engine", "role": "WeCom Dual RPA", "note": "企业微信消息、外部客户群与 VoIP 通话协同"},
    ],
}

_AI_SLOP_WORDS: Tuple[str, ...] = (
    "赋能",
    "一站式",
    "颠覆",
    "全能",
    "闭环",
    "抓手",
    "解锁新体验",
    "效率神器",
    "宝子们",
)

_OFF_PLATFORM_PATTERNS: Tuple[Tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"(?:加|添?加我?|私信拿)\s*(?:[Vv微微信vxVX]+)\s*[:：]?\s*[A-Za-z0-9_-]*"), "off_platform_wechat", "私信交流细节"),
    (re.compile(r"\+[VvXx](?:[：:\s]*[A-Za-z0-9_-]{3,})?"), "off_platform_vx", "私信发你资料"),
    (re.compile(r"微信号\s*[:：]?\s*[A-Za-z0-9_-]*"), "off_platform_wxid", "看主页或私信沟通"),
    (re.compile(r"QQ\s*群?\s*[:：]?\s*\d*", re.IGNORECASE), "off_platform_qq", "私信沟通"),
    (re.compile(r"https?://\S+", re.IGNORECASE), "external_url", "主页看详细介绍"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "phone_number", "私信留个联系方式"),
)

_LEAD_HOT_KEYWORDS: Tuple[str, ...] = (
    "报价",
    "多少钱",
    "怎么买",
    "购买",
    "下单",
    "付费",
    "收费",
    "费用",
    "私有化",
    "部署",
    "试用",
    "合作",
    "渠道",
    "代理",
    "商务",
)

_LEAD_WARM_KEYWORDS: Tuple[str, ...] = (
    "怎么用",
    "求链接",
    "发我",
    "看一下",
    "支持什么",
    "文档",
    "开源",
    "github",
    "联系",
    "私信",
    "有兴趣",
    "想要",
    "求推荐",
    "怎么接入",
)

_TIMESTAMP_OCR_RE = re.compile(
    r"^(?:\d{1,2}:\d{2}|昨天|今天|前天|\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2})$"
)


def normalize_channel_id(raw: Optional[str]) -> str:
    key = str(raw or "").strip().lower()
    if not key:
        return "feishu"
    return CHANNEL_ALIASES.get(key, key)


def _hmac_sha256_b64(key: bytes, msg: bytes) -> str:
    digest = hmac.new(key, msg, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _http_json_post(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: float = 12.0) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_text = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw_text) if raw_text else {}
            except Exception:
                parsed = {"raw": raw_text}
            return {"ok": True, "status": resp.status, "response": parsed}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": exc.code, "error": err_body or str(exc)}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc)}


def sanitize_public_channel_reply(channel: str, text: str, *, soften: bool = True) -> Dict[str, Any]:
    """Strip Markdown, AI buzzwords, and off-platform bait for XHS / Douyin anti-ban safety."""
    ch = normalize_channel_id(channel)
    original = str(text or "").strip()
    cleaned = original
    warnings: List[str] = []

    if ch in ("xiaohongshu", "douyin"):
        # Strip Markdown formatting
        md_cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        md_cleaned = re.sub(r"`([^`]+)`", r"\1", md_cleaned)
        md_cleaned = re.sub(r"^#{1,6}\s+", "", md_cleaned, flags=re.MULTILINE)
        md_cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", md_cleaned)
        if md_cleaned != cleaned:
            warnings.append("stripped_markdown")
            cleaned = md_cleaned

        for bad in _AI_SLOP_WORDS:
            if bad in cleaned:
                warnings.append(f"ai_slop:{bad}")
                if soften:
                    cleaned = cleaned.replace(bad, "")

        for pat, code, replacement in _OFF_PLATFORM_PATTERNS:
            if pat.search(cleaned):
                warnings.append(code)
                if soften:
                    cleaned = pat.sub(replacement, cleaned)

        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
        if soften:
            cleaned = re.sub(r"^[，,。！!？?\s]+", "", cleaned).strip()
        if ch == "xiaohongshu" and len(cleaned) > 300:
            warnings.append("length_gt_300")
            if soften:
                cleaned = cleaned[:297].rstrip() + "..."
    post_violations = any(pat.search(cleaned) for pat, _, _ in _OFF_PLATFORM_PATTERNS)
    return {
        "channel": ch,
        "original": original,
        "sanitized": cleaned,
        "modified": cleaned != original,
        "warnings": warnings,
        "compliant": (not post_violations) and (ch != "xiaohongshu" or len(cleaned) <= 300),
    }


def score_lead_intent(text: str) -> Tuple[str, int, List[str]]:
    """Score incoming message/comment commercial intent into hot / warm / cold."""
    content = str(text or "").strip()
    low = content.casefold()
    matched: List[str] = []
    score = 0
    for kw in _LEAD_HOT_KEYWORDS:
        if kw in low:
            matched.append(kw)
            score += 35
    for kw in _LEAD_WARM_KEYWORDS:
        if kw in low:
            matched.append(kw)
            score += 18
    if "?" in content or "？" in content:
        score += 10
    score = min(100, score)
    tier = "hot" if score >= 50 else ("warm" if score >= 20 else "cold")
    return tier, score, matched


class FeishuOpenSourceBridge:
    """Feishu / Lark open-source protocol bridge (HMAC Webhook + IM REST + lark-oapi readiness)."""

    def __init__(self, http_requester: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._post = http_requester or _http_json_post

    @staticmethod
    def build_webhook_signature(secret: str, timestamp: Optional[int] = None) -> Tuple[str, str]:
        ts = str(int(timestamp if timestamp is not None else time.time()))
        string_to_sign = f"{ts}\n{secret}".encode("utf-8")
        # Per Feishu custom bot spec: sign = Base64(HmacSHA256("", timestamp + "\n" + secret))
        sign = _hmac_sha256_b64(string_to_sign, b"")
        return ts, sign

    def runtime_status(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "larkOapiInstalled": importlib.util.find_spec("lark_oapi") is not None,
            "larkMcpInstalled": shutil.which("lark-mcp") is not None,
            "webhookConfigured": bool(str(cfg.get("webhook_url") or "").strip()),
            "appCredentialsConfigured": bool(str(cfg.get("app_id") or "").strip() and str(cfg.get("app_secret") or "").strip()),
        }

    def send_webhook_text(
        self,
        webhook_url: str,
        text: str,
        *,
        secret: str = "",
        dry_run: bool = True,
        timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        clean_url = str(webhook_url or "").strip()
        if not clean_url:
            return {"ok": False, "error_code": "feishu_webhook_missing", "error": "未配置飞书机器人 Webhook URL"}
        payload: Dict[str, Any] = {"msg_type": "text", "content": {"text": str(text or "")}}
        if secret:
            ts, sign = self.build_webhook_signature(secret, timestamp=timestamp)
            payload["timestamp"] = ts
            payload["sign"] = sign
        if dry_run:
            return {"ok": True, "dryRun": True, "mode": "feishu_webhook", "url": clean_url, "payload": payload}
        res = self._post(clean_url, payload)
        resp_body = res.get("response") or {}
        biz_ok = res.get("ok") and resp_body.get("code", resp_body.get("StatusCode", 0)) in (0, None)
        return {
            "ok": bool(biz_ok),
            "dryRun": False,
            "mode": "feishu_webhook",
            "status": res.get("status"),
            "response": resp_body,
            "error": res.get("error") or (resp_body.get("msg") if not biz_ok else ""),
        }

    def send_im_message(
        self,
        *,
        app_id: str,
        app_secret: str,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
        base_url: str = "https://open.feishu.cn",
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        if not (app_id and app_secret):
            return {"ok": False, "error_code": "feishu_app_credentials_missing", "error": "未配置飞书 app_id / app_secret"}
        if not receive_id:
            return {"ok": False, "error_code": "missing_receive_id", "error": "缺少飞书接收方 receive_id"}
        msg_payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": str(text or "")}, ensure_ascii=False),
        }
        send_url = f"{base_url.rstrip('/')}/open-apis/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}"
        if dry_run:
            return {"ok": True, "dryRun": True, "mode": "feishu_open_api", "url": send_url, "payload": msg_payload}
        tok_url = f"{base_url.rstrip('/')}/open-apis/auth/v3/tenant_access_token/internal"
        tok_res = self._post(tok_url, {"app_id": app_id, "app_secret": app_secret})
        token = str((tok_res.get("response") or {}).get("tenant_access_token") or "")
        if not token:
            return {"ok": False, "error_code": "feishu_token_failed", "error": tok_res.get("error") or "获取 tenant_access_token 失败", "detail": tok_res}
        send_res = self._post(send_url, msg_payload, headers={"Authorization": f"Bearer {token}"})
        body = send_res.get("response") or {}
        biz_ok = send_res.get("ok") and body.get("code", 0) == 0
        return {
            "ok": bool(biz_ok),
            "dryRun": False,
            "mode": "feishu_open_api",
            "status": send_res.get("status"),
            "response": body,
            "error": send_res.get("error") or (body.get("msg") if not biz_ok else ""),
        }


class DingTalkOpenSourceBridge:
    """DingTalk open-source protocol bridge (HMAC Signed Webhook + dingtalk-stream readiness)."""

    def __init__(self, http_requester: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self._post = http_requester or _http_json_post

    @staticmethod
    def build_signed_webhook_url(webhook_url: str, secret: str = "", timestamp_ms: Optional[int] = None) -> str:
        clean_url = str(webhook_url or "").strip()
        if not secret or not clean_url:
            return clean_url
        ts = str(int(timestamp_ms if timestamp_ms is not None else round(time.time() * 1000)))
        string_to_sign = f"{ts}\n{secret}".encode("utf-8")
        raw_sig = _hmac_sha256_b64(secret.encode("utf-8"), string_to_sign)
        sep = "&" if "?" in clean_url else "?"
        return f"{clean_url}{sep}timestamp={ts}&sign={urllib.parse.quote_plus(raw_sig)}"

    def runtime_status(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "dingtalkStreamInstalled": importlib.util.find_spec("dingtalk_stream") is not None,
            "webhookConfigured": bool(str(cfg.get("webhook_url") or "").strip()),
        }

    def send_webhook_text(
        self,
        webhook_url: str,
        text: str,
        *,
        secret: str = "",
        dry_run: bool = True,
        timestamp_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not str(webhook_url or "").strip():
            return {"ok": False, "error_code": "dingtalk_webhook_missing", "error": "未配置钉钉机器人 Webhook URL"}
        signed_url = self.build_signed_webhook_url(webhook_url, secret=secret, timestamp_ms=timestamp_ms)
        payload = {"msgtype": "text", "text": {"content": str(text or "")}}
        if dry_run:
            return {"ok": True, "dryRun": True, "mode": "dingtalk_webhook", "url": signed_url, "payload": payload}
        res = self._post(signed_url, payload)
        resp_body = res.get("response") or {}
        biz_ok = res.get("ok") and resp_body.get("errcode", 0) == 0
        return {
            "ok": bool(biz_ok),
            "dryRun": False,
            "mode": "dingtalk_webhook",
            "status": res.get("status"),
            "response": resp_body,
            "error": res.get("error") or (resp_body.get("errmsg") if not biz_ok else ""),
        }


class XiaohongshuPublisherBridge:
    """Read-only & copy-audit bridge to local `/Users/mac/.local/bin/xhs-publisher`."""

    def __init__(self, binary_path: Path = XHS_PUBLISHER_BIN) -> None:
        self.binary_path = Path(binary_path)

    def available(self) -> bool:
        return self.binary_path.is_file()

    def rate_status(self) -> Dict[str, Any]:
        if not self.available():
            return {"ok": False, "available": False, "error": f"xhs-publisher not found at {self.binary_path}"}
        env = dict(os.environ, HOME=str(REAL_USER_HOME))
        try:
            proc = subprocess.run(
                [str(self.binary_path), "rate-status"],
                capture_output=True,
                text=True,
                timeout=8.0,
                env=env,
            )
            out = (proc.stdout or "").strip()
            try:
                data = json.loads(out) if out else {}
            except Exception:
                data = {"raw": out}
            return {"ok": proc.returncode == 0, "available": True, "data": data, "stderr": (proc.stderr or "").strip()}
        except Exception as exc:
            return {"ok": False, "available": True, "error": str(exc)}

    def validate_copy(self, title: str, body: str) -> Dict[str, Any]:
        if not self.available():
            return {"ok": True, "available": False, "localFallback": True}
        env = dict(os.environ, HOME=str(REAL_USER_HOME))
        try:
            proc = subprocess.run(
                [str(self.binary_path), "validate-copy", "--title", title[:20] or "经验分享", "--body", body],
                capture_output=True,
                text=True,
                timeout=8.0,
                env=env,
            )
            out = (proc.stdout or "").strip()
            try:
                parsed = json.loads(out) if out else {}
            except Exception:
                parsed = {"raw": out}
            return {"ok": proc.returncode == 0, "available": True, "result": parsed, "stderr": (proc.stderr or "").strip()}
        except Exception as exc:
            return {"ok": False, "available": True, "error": str(exc)}


class EgoBrowserSocialBridge:
    """Safe web/creator-center RPA over local `/Users/mac/.local/bin/ego-browser` (logged-in Ego Lite)."""

    TASK_SPACE_NAME = "omni-channel-rpa"

    def __init__(self, binary_path: Path = EGO_BROWSER_BIN) -> None:
        self.binary_path = Path(binary_path)

    def available(self) -> bool:
        return self.binary_path.is_file()

    def _run_node(self, script_body: str, *, timeout: float = 28.0) -> Dict[str, Any]:
        if not self.available():
            return {"ok": False, "available": False, "error": f"ego-browser not found at {self.binary_path}"}
        env = dict(os.environ, HOME=str(REAL_USER_HOME))
        try:
            proc = subprocess.run(
                [str(self.binary_path), "nodejs"],
                input=script_body,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "available": True, "error_code": "ego_browser_timeout", "error": f"ego-browser timed out after {timeout}s"}
        except Exception as exc:
            return {"ok": False, "available": True, "error": str(exc)}

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        combined_lines = stdout.splitlines() + stderr.splitlines()
        for line in reversed(combined_lines):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        data.setdefault("ok", proc.returncode == 0)
                        data.setdefault("available", True)
                        return data
                except Exception:
                    pass
        return {
            "ok": False,
            "available": True,
            "returncode": proc.returncode,
            "error": stderr or stdout or "Empty output from ego-browser",
        }

    def probe_web(self, channel: str, *, target_view: str = "home", query: str = "") -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        spec = CHANNEL_SPECS.get(ch) or {}
        web_urls = spec.get("webUrls") or {}
        url_tpl = web_urls.get(target_view) or web_urls.get("home") or ""
        if not url_tpl:
            return {"ok": False, "channel": ch, "error": f"{ch} 无需 Web 浏览器通道"}
        url = url_tpl.format(query=urllib.parse.quote(query)) if "{query}" in url_tpl else url_tpl
        login_hints = spec.get("loginHints") or []

        script = f"""
const SPACE_NAME = {json.dumps(self.TASK_SPACE_NAME)};
const TARGET_URL = {json.dumps(url)};
const LOGIN_HINTS = {json.dumps(login_hints, ensure_ascii=False)};
const CHANNEL = {json.dumps(ch)};
const VIEW = {json.dumps(target_view)};
const entry = (await listTaskSpaces()).find((s) => s.name === SPACE_NAME);
const task = !entry
  ? await taskSpace(SPACE_NAME)
  : entry.ownership === "user"
    ? await claimTaskSpace(entry.id)
    : entry.ownership === "agentDelegatedToUser"
      ? await takeOverTaskSpace(entry.id)
      : await taskSpace(entry.id);
let pages = await task.pages();
let page = pages[0];
if (!page) {{
  const tabs = await task.tabs();
  page = tabs[0] ? await task.adopt(tabs[0].page) : await task.newPage();
}}
await page.goto(TARGET_URL, {{ timeout: 18000 }});
await page.waitForLoadState("domcontentloaded", {{ timeout: 10000 }}).catch(() => {{}});
await page.waitForTimeout(1500);
const info = await page.evaluate(({{ hints, channel, view }}) => {{
  const title = document.title || "";
  const url = location.href;
  const text = (document.body?.innerText || "").replace(/\\s+/g, " ").trim();
  const hasLoginModal = Boolean(
    document.querySelector('[class*="login-modal"], [class*="qrcode"], [class*="login-container"], input[type="password"]')
  );
  const matchedHints = hints.filter((h) => text.includes(h));
  const hasExactLoginBtn = [...document.querySelectorAll("button, a, span")].some((el) => {{
    const t = (el.textContent || "").trim();
    return t === "登录" || t === "立即登录" || t === "扫码登录";
  }});
  const webRetiredByVendor = channel === "dingtalk" && (
    url.includes("page.dingtalk.com") || text.includes("系统维护中") || text.includes("下载对应版本客户端")
  );
  const creatorNeedsLogin = (channel === "douyin" || channel === "xiaohongshu") && (
    url.includes("creator.") && (/扫码登录|验证码登录|我是创作者|立即登录/.test(text) || /login|passport/i.test(url))
  );
  const loggedIn = !webRetiredByVendor && !hasLoginModal && matchedHints.length === 0
    && !(channel === "xiaohongshu" && hasExactLoginBtn)
    && !creatorNeedsLogin
    && !/login|passport/i.test(url);
  const inputs = [...document.querySelectorAll('textarea, [contenteditable="true"], input[placeholder*="说"], input[placeholder*="评论"], input[placeholder*="回复"]')].length;
  return {{
    title,
    url,
    targetView: view,
    loggedIn,
    hasLoginModal,
    hasExactLoginBtn,
    webRetiredByVendor,
    creatorNeedsLogin,
    matchedLoginHints: matchedHints,
    interactiveInputCount: inputs,
    previewText: text.slice(0, 500),
  }};
}}, {{ hints: LOGIN_HINTS, channel: CHANNEL, view: VIEW }});
console.log(JSON.stringify({{ ok: true, taskSpaceId: task.spaceId, page: page.label, channel: CHANNEL, ...info }}));
"""
        return self._run_node(script, timeout=34.0)

    def open_login_for_user(self, channel: str, *, target_view: str = "home", custom_url: str = "") -> Dict[str, Any]:
        """Open the target QR/login page in ego lite, hand control to the user, and bring ego lite to front."""
        ch = normalize_channel_id(channel)
        spec = CHANNEL_SPECS.get(ch) or {}
        web_urls = spec.get("webUrls") or {}
        url = custom_url or web_urls.get(target_view) or web_urls.get("home") or ""
        if not url:
            return {"ok": False, "channel": ch, "error": f"{ch} 暂无网页登录地址"}

        script = f"""
const SPACE_NAME = {json.dumps(self.TASK_SPACE_NAME)};
const TARGET_URL = {json.dumps(url)};
const entry = (await listTaskSpaces()).find((s) => s.name === SPACE_NAME);
const task = !entry
  ? await taskSpace(SPACE_NAME)
  : entry.ownership === "user"
    ? await claimTaskSpace(entry.id)
    : entry.ownership === "agentDelegatedToUser"
      ? await takeOverTaskSpace(entry.id)
      : await taskSpace(entry.id);
let page = (await task.pages())[0];
if (!page) {{
  const tabs = await task.tabs();
  page = tabs[0] ? await task.adopt(tabs[0].page) : await task.newPage();
}}
await page.goto(TARGET_URL, {{ timeout: 18000 }});
await page.waitForLoadState("domcontentloaded", {{ timeout: 10000 }}).catch(() => {{}});
await page.waitForTimeout(900);
const curUrl = await page.url();
const curTitle = await page.title().catch(() => "");
await task.handOff();
console.log(JSON.stringify({{ ok: true, handedOff: true, taskSpaceId: task.spaceId, channel: {json.dumps(ch)}, targetView: {json.dumps(target_view)}, url: curUrl, title: curTitle }}));
"""
        res = self._run_node(script, timeout=30.0)
        if res.get("ok"):
            for cmd in (
                ["/usr/bin/open", "-a", "/Applications/ego lite.app"],
                ["/usr/bin/osascript", "-e", 'tell application id "com.citrolabs.ego.lite" to activate'],
            ):
                try:
                    subprocess.run(cmd, capture_output=True, text=True, timeout=4.0)
                except Exception:
                    pass
        return res

    def list_interactions(self, channel: str, *, query: str = "", limit: int = 12) -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        spec = CHANNEL_SPECS.get(ch) or {}
        web_urls = spec.get("webUrls") or {}
        if query and web_urls.get("search"):
            target_url = web_urls["search"].format(query=urllib.parse.quote(query))
        else:
            target_url = web_urls.get("im") or web_urls.get("home") or ""
        if not target_url:
            return {"ok": False, "channel": ch, "items": [], "error": f"{ch} 未配置 Web 互动入口"}

        script = f"""
const SPACE_NAME = {json.dumps(self.TASK_SPACE_NAME)};
const TARGET_URL = {json.dumps(target_url)};
const LIMIT = {int(max(1, min(30, limit)))};
const CHANNEL = {json.dumps(ch)};
const entry = (await listTaskSpaces()).find((s) => s.name === SPACE_NAME);
const task = !entry
  ? await taskSpace(SPACE_NAME)
  : entry.ownership === "user"
    ? await claimTaskSpace(entry.id)
    : entry.ownership === "agentDelegatedToUser"
      ? await takeOverTaskSpace(entry.id)
      : await taskSpace(entry.id);
let page = (await task.pages())[0];
if (!page) {{
  const tabs = await task.tabs();
  page = tabs[0] ? await task.adopt(tabs[0].page) : await task.newPage();
}}
await page.goto(TARGET_URL, {{ timeout: 18000 }});
await page.waitForLoadState("domcontentloaded", {{ timeout: 10000 }}).catch(() => {{}});
await page.waitForTimeout(1600);
const result = await page.evaluate(({{ limit, channel }}) => {{
  const items = [];
  const selectors = channel === "xiaohongshu"
    ? ['section.note-item', '[class*="note-item"]', '[class*="comment-item"]', '[class*="message-item"]', '[class*="notification"] li']
    : channel === "douyin"
      ? ['[data-e2e="comment-item"]', '[class*="comment-item"]', '[class*="session-item"]', '[class*="search-result-card"]', 'li']
      : ['[class*="conv-item"]', '[class*="session-item"]', '[class*="chat-item"]', 'li'];
  const seen = new Set();
  for (const sel of selectors) {{
    for (const el of document.querySelectorAll(sel)) {{
      const txt = (el.innerText || "").replace(/\\s+/g, " ").trim();
      if (!txt || txt.length < 4 || seen.has(txt)) continue;
      seen.add(txt);
      const linkEl = el.querySelector("a[href]");
      items.push({{
        title: txt.slice(0, 72),
        text: txt.slice(0, 260),
        href: linkEl ? linkEl.href : "",
      }});
      if (items.length >= limit) break;
    }}
    if (items.length >= limit) break;
  }}
  const bodyText = (document.body?.innerText || "").replace(/\\s+/g, " ").trim();
  const loginRequired = /登录后查看|扫码登录|手机号登录|登录解锁/.test(bodyText) || /login|passport/i.test(location.href);
  return {{
    title: document.title || "",
    url: location.href,
    loginRequired,
    count: items.length,
    items,
    previewText: bodyText.slice(0, 380),
  }};
}}, {{ limit: LIMIT, channel: CHANNEL }});
console.log(JSON.stringify({{ ok: true, taskSpaceId: task.spaceId, channel: CHANNEL, ...result }}));
"""
        return self._run_node(script, timeout=34.0)

    def reply_interaction(
        self,
        channel: str,
        target: str,
        text: str,
        *,
        dry_run: bool = True,
        confirm_send: bool = False,
    ) -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        audit = sanitize_public_channel_reply(ch, text, soften=True)
        final_text = audit["sanitized"]
        should_submit = (not dry_run) and confirm_send

        if ch == "xiaohongshu" and should_submit:
            now_h = datetime.now().hour
            if 0 <= now_h < 9 and (now_h > 0 or datetime.now().minute >= 30):
                return {
                    "ok": False,
                    "error_code": "xhs_night_window_guard",
                    "error": "当前处于小红书夜间防封静默窗（00:30-08:30），仅允许 Dry-Run 演练或读取。",
                    "sanitized": audit,
                }

        if not should_submit:
            return {
                "ok": True,
                "dryRun": True,
                "channel": ch,
                "target": target,
                "mode": "ego_browser_web",
                "sent": False,
                "text": final_text,
                "compliance": audit,
            }

        script = f"""
const SPACE_NAME = {json.dumps(self.TASK_SPACE_NAME)};
const REPLY_TEXT = {json.dumps(final_text)};
const entry = (await listTaskSpaces()).find((s) => s.name === SPACE_NAME);
if (!entry) {{
  console.log(JSON.stringify({{ ok: false, error_code: "no_active_web_space", error: "请先打开目标帖子或私信页面后再发送" }}));
  process.exit(0);
}}
const task = entry.ownership === "user"
  ? await claimTaskSpace(entry.id)
  : entry.ownership === "agentDelegatedToUser"
    ? await takeOverTaskSpace(entry.id)
    : await taskSpace(entry.id);
let page = (await task.pages())[0];
if (!page) {{
  const tabs = await task.tabs();
  page = tabs[0] ? await task.adopt(tabs[0].page) : undefined;
}}
if (!page) {{
  console.log(JSON.stringify({{ ok: false, error_code: "no_active_page", error: "没有已打开的网页标签" }}));
  process.exit(0);
}}
const box = await page.evaluate(() => {{
  const el = document.querySelector('textarea, [contenteditable="true"], input[placeholder*="说"], input[placeholder*="评论"], input[placeholder*="回复"]');
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }};
}});
if (!box) {{
  console.log(JSON.stringify({{ ok: false, error_code: "web_input_not_found", error: "当前网页未找到可输入评论/私信框（可能需先扫码登录）" }}));
  process.exit(0);
}}
await page.mouse.click(box.x, box.y, {{ label: "focus reply input" }});
await page.waitForTimeout(250);
await page.keyboard.paste(REPLY_TEXT);
await page.waitForTimeout(450);
await page.keyboard.press("Enter");
await page.waitForTimeout(900);
console.log(JSON.stringify({{ ok: true, sent: true, mode: "ego_browser_web", url: await page.url(), text: REPLY_TEXT }}));
"""
        res = self._run_node(script, timeout=25.0)
        res["compliance"] = audit
        return res

    def finish_space(self) -> Dict[str, Any]:
        script = f"""
const SPACE_NAME = {json.dumps(self.TASK_SPACE_NAME)};
const entry = (await listTaskSpaces()).find((s) => s.name === SPACE_NAME);
if (!entry) {{
  console.log(JSON.stringify({{ ok: true, closed: false, reason: "no_space" }}));
  process.exit(0);
}}
const task = entry.ownership === "user"
  ? await claimTaskSpace(entry.id)
  : entry.ownership === "agentDelegatedToUser"
    ? await takeOverTaskSpace(entry.id)
    : await taskSpace(entry.id);
await task.finish({{ keep: [] }});
console.log(JSON.stringify({{ ok: true, closed: true, taskSpaceId: entry.id }}));
"""
        return self._run_node(script, timeout=15.0)


def _installed_app_paths(channel: str) -> List[str]:
    spec = CHANNEL_SPECS.get(channel) or {}
    found: List[str] = []
    for cand in spec.get("appPaths") or []:
        if Path(cand).exists():
            found.append(cand)
    return found


def _parse_ocr_sidebar_and_chat(
    elements: List[Dict[str, Any]],
    *,
    img_w: float,
    img_h: float,
    win_w: float,
    win_h: float,
    login_hints: List[str],
    channel: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    sx = img_w / max(win_w, 1.0)
    sy = img_h / max(win_h, 1.0)

    all_pts: List[Tuple[float, float, str]] = []
    for e in elements:
        txt = str(e.get("text") or "").strip()
        center = e.get("center") or {}
        if not txt or "x" not in center or "y" not in center:
            continue
        all_pts.append((float(center["x"]) / sx, float(center["y"]) / sy, txt))

    has_three_col_nav = channel == "feishu" or any(
        lx < 170.0 and any(lbl in txt for lbl in ("工作台", "应用中心", "多维表格", "云文档"))
        for lx, _, txt in all_pts
    )
    sess_min_x = min(176.0, win_w * 0.14) if has_three_col_nav else 48.0
    split_x = max(420.0, min(635.0, win_w * 0.395)) if has_three_col_nav else max(210.0, min(380.0, win_w * 0.34))

    all_texts = [p[2] for p in all_pts]
    joined_top = " ".join(all_texts)
    matched_login = [h for h in login_hints if h in joined_top]
    login_required = bool(matched_login)

    sidebar_raw: List[Tuple[float, float, str, Dict[str, Any]]] = []
    chat_raw: List[Tuple[float, float, str]] = []
    header_parts: List[Tuple[float, str]] = []

    nav_noise = {"搜索", "消息", "通讯录", "工作台", "日历", "文档", "多维表格", "云文档", "视频会议", "应用中心", "更多", "豆包工作"}
    for lx, ly, txt in all_pts:
        if lx >= split_x and 8.0 <= ly <= 84.0:
            header_parts.append((lx, txt))
            continue
        if sess_min_x <= lx <= split_x and 65.0 <= ly <= max(200.0, win_h - 24.0):
            sidebar_raw.append((ly, lx, txt, {"x": round(lx, 1), "y": round(ly, 1)}))
        elif lx > split_x and 84.0 < ly < max(220.0, win_h - 115.0):
            if "对伙伴的夸赞" in txt:
                continue
            chat_raw.append((ly, lx, txt))

    header_parts.sort(key=lambda item: item[0])
    chat_title = " ".join(p[1] for p in header_parts[:3]).strip()

    sidebar_raw.sort(key=lambda item: (round(item[0] / 12.0), item[1]))
    sessions: List[Dict[str, Any]] = []
    for ly, lx, txt, pt in sidebar_raw:
        if _TIMESTAMP_OCR_RE.match(txt) or txt in nav_noise:
            continue
        if re.fullmatch(r"\d{1,3}", txt):
            continue
        if len(txt) <= 1:
            continue
        if sessions and abs(pt["y"] - sessions[-1]["_y"]) < 36.0:
            sessions[-1]["preview"] = (sessions[-1]["preview"] + " " + txt).strip()
        else:
            sessions.append({
                "title": txt[:56],
                "preview": "",
                "clickPoint": pt,
                "_y": pt["y"],
            })
        if len(sessions) >= limit:
            break
    for s in sessions:
        s.pop("_y", None)

    chat_raw.sort(key=lambda item: (item[0], item[1]))
    mid_x = split_x + (win_w - split_x) * 0.55
    messages: List[Dict[str, Any]] = []
    for ly, lx, txt in chat_raw:
        if _TIMESTAMP_OCR_RE.match(txt):
            continue
        direction = "outgoing" if lx >= mid_x else "incoming"
        messages.append({
            "sender": "我" if direction == "outgoing" else (chat_title or "对方"),
            "direction": direction,
            "text": txt,
            "y": round(ly, 1),
        })
    if len(messages) > limit:
        messages = messages[-limit:]

    return {
        "loginRequired": login_required,
        "matchedLoginHints": matched_login,
        "currentChatTitle": chat_title,
        "sessions": sessions,
        "messages": messages,
        "rawTextSample": all_texts[:30],
    }


class OmniChannelHub:
    """Unified multi-channel App-Use RPA + Open-Source Bridge coordinator."""

    def __init__(
        self,
        engine: Any,
        *,
        config_path: Optional[Path] = None,
        http_requester: Optional[Callable[..., Dict[str, Any]]] = None,
    ) -> None:
        self.engine = engine
        self.config_path = Path(config_path) if config_path else (engine.plugin_root / "config" / "omni_channels.json")
        self.auth_state_path = (
            self.config_path.parent / "omni_auth_state.json"
            if config_path
            else (engine.plugin_root / "logs" / "omni_auth_state.json")
        )
        self.verify_dir = Path("/Volumes/SanDisk/Builds/WeChatBot/omni-verify") if Path("/Volumes/SanDisk/Builds").exists() else (engine.plugin_root / "logs" / "omni-verify")
        self.feishu_bridge = FeishuOpenSourceBridge(http_requester=http_requester)
        self.dingtalk_bridge = DingTalkOpenSourceBridge(http_requester=http_requester)
        self.xhs_publisher = XiaohongshuPublisherBridge()
        self.ego_browser = EgoBrowserSocialBridge()
        self._config = self._load_config()
        self._auth_state = self._load_auth_state()

    def _default_config(self) -> Dict[str, Any]:
        return {
            "version": "1.0",
            "feishu": {"webhook_url": "", "webhook_secret": "", "app_id": "", "app_secret": "", "default_receive_id": ""},
            "dingtalk": {"webhook_url": "", "webhook_secret": ""},
            "xiaohongshu": {"default_query": "", "anti_ban_soften": True},
            "douyin": {"default_query": "", "anti_ban_soften": True},
        }

    def _load_config(self) -> Dict[str, Any]:
        cfg = self._default_config()
        try:
            if self.config_path.is_file():
                raw = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                            cfg[k].update(v)
                        else:
                            cfg[k] = v
        except Exception:
            pass
        return cfg

    def _save_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.config_path, self._config)
        try:
            os.chmod(self.config_path, 0o600)
        except Exception:
            pass

    def _load_auth_state(self) -> Dict[str, Any]:
        try:
            if self.auth_state_path.is_file():
                raw = json.loads(self.auth_state_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
        except Exception:
            pass
        return {}

    def _save_auth_state(self) -> None:
        try:
            self.auth_state_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.auth_state_path, self._auth_state)
        except Exception:
            pass

    def _update_channel_auth_state(self, ch: str, doc: Dict[str, Any]) -> None:
        prev = dict(self._auth_state.get(ch) or {})
        prev.update(doc)
        prev["checkedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._auth_state[ch] = prev
        self._save_auth_state()

    @staticmethod
    def _mask_secret(val: Any) -> str:
        s = str(val or "").strip()
        if not s:
            return ""
        if len(s) <= 8:
            return "*" * len(s)
        return s[:4] + "****" + s[-4:]

    def get_redacted_config(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in self._config.items():
            if not isinstance(v, dict):
                out[k] = v
                continue
            masked: Dict[str, Any] = {}
            for fk, fv in v.items():
                if any(tok in fk.lower() for tok in ("secret", "webhook_url", "token")):
                    masked[fk] = self._mask_secret(fv)
                    masked[f"{fk}_configured"] = bool(str(fv or "").strip())
                else:
                    masked[fk] = fv
            out[k] = masked
        return out

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(updates, dict):
            return {"ok": False, "error": "updates 必须为 JSON 对象"}
        for ch_key, ch_vals in updates.items():
            norm = normalize_channel_id(ch_key)
            if norm not in CHANNEL_SPECS or not isinstance(ch_vals, dict):
                continue
            target = self._config.setdefault(norm, {})
            for field, val in ch_vals.items():
                if val is not None:
                    target[field] = val
        self._save_config()
        return {"ok": True, "config": self.get_redacted_config()}

    def _system_auth_status(self) -> Dict[str, Any]:
        perm = self.engine._run_native(["status", "--app", "wechat"], timeout=8.0)
        mac_ok = bool(
            perm.get("accessibilityTrusted")
            and perm.get("screenCaptureTrusted")
            and perm.get("postEventTrusted")
        )
        auth_state = (self.engine.auth_status().get("authorization") or {}) if hasattr(self.engine, "auth_status") else {}
        caps = set(auth_state.get("capabilities") or [])
        studio_ok = bool(auth_state.get("authorized")) and ("send_text_live" in caps)
        return {
            "macosPermissions": {
                "ready": mac_ok,
                "accessibilityTrusted": bool(perm.get("accessibilityTrusted")),
                "screenCaptureTrusted": bool(perm.get("screenCaptureTrusted")),
                "postEventTrusted": bool(perm.get("postEventTrusted")),
                "label": "✅ macOS 辅助功能/录屏/键鼠控制已授权" if mac_ok else "⚠️ 需在系统设置勾选辅助功能/录屏权限",
            },
            "studioAuth": {
                "ready": studio_ok,
                "authorized": bool(auth_state.get("authorized")),
                "capabilities": sorted(caps),
                "label": "✅ WeChat Bot 全渠道实发能力已授权" if studio_ok else "⚠️ 需点击一键授权 Bot 实发能力",
            },
        }

    def _build_channel_auth_guide(self, cid: str, entry: Dict[str, Any], cached: Dict[str, Any]) -> Dict[str, Any]:
        installed = bool(entry.get("installed"))
        running = bool(entry.get("desktopRunning")) and int(entry.get("desktopWindowCount") or 0) > 0
        open_proto = entry.get("openProtocol") or {}
        webhook_ok = bool(open_proto.get("webhookConfigured") or open_proto.get("appCredentialsConfigured"))

        if cid in ("feishu", "wechat", "wecom"):
            desktop_login_req = cached.get("loginRequired")
            if running:
                if desktop_login_req is True:
                    return {
                        "status": "scan_qr",
                        "badgeText": "📱 待扫码登录",
                        "needsUserAction": True,
                        "summary": f"{entry['shortLabel']}桌面窗口当前处于未登录/扫码页面，请点击唤起窗口并使用手机{entry['shortLabel']}扫码。",
                        "actions": [
                            {"label": f"📲 唤起{entry['shortLabel']}扫码", "actionType": "desktop", "targetView": "home", "style": "solid"},
                            {"label": "🔄 我已扫码，核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                        ],
                    }
                actions = [
                    {"label": f"🪟 唤起{entry['shortLabel']}窗口", "actionType": "desktop", "targetView": "home", "style": "outline"},
                    {"label": "🔄 重新核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                ]
                if cid == "feishu" and not webhook_ok:
                    actions.append({"label": "⚙️ 配开源机器人", "actionType": "open_config", "targetView": "open_platform", "style": "outline"})
                return {
                    "status": "ready",
                    "badgeText": "✅ 已登录就绪",
                    "needsUserAction": False,
                    "summary": f"本机{entry['shortLabel']}桌面端已登录运行，可直接读取会话、回复演练与语音通话。",
                    "actions": actions,
                }
            if installed:
                return {
                    "status": "need_launch",
                    "badgeText": "🚀 待点击启动扫码",
                    "needsUserAction": True,
                    "summary": f"已安装{entry['shortLabel']}客户端，点击下方按钮拉起窗口（若未登录可直接在弹出窗口扫码）。",
                    "actions": [
                        {"label": f"📲 启动{entry['shortLabel']}并登录", "actionType": "desktop", "targetView": "home", "style": "solid"},
                        {"label": "🔄 核验状态", "actionType": "verify", "targetView": "home", "style": "outline"},
                    ],
                }
            return {
                "status": "need_install",
                "badgeText": "📥 需安装客户端",
                "needsUserAction": True,
                "summary": f"本机未检测到{entry['shortLabel']}桌面客户端，可下载安装或通过开源机器人凭据接入。",
                "actions": [
                    {"label": f"⬇️ 下载{entry['shortLabel']}桌面版", "actionType": "download", "targetView": "download", "style": "solid"},
                    {"label": "🔄 重新核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                ],
            }

        if cid == "dingtalk":
            if running and cached.get("loginRequired") is not True:
                return {
                    "status": "ready",
                    "badgeText": "✅ 桌面端已就绪",
                    "needsUserAction": False,
                    "summary": "钉钉桌面客户端已登录运行，支持消息读回、回复演练与语音窗口检测。",
                    "actions": [
                        {"label": "🪟 唤起钉钉窗口", "actionType": "desktop", "targetView": "home", "style": "outline"},
                        {"label": "🔄 重新核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                    ],
                }
            if installed:
                return {
                    "status": "scan_qr" if running else "need_launch",
                    "badgeText": "📱 待启动/扫码" if running else "🚀 待启动扫码",
                    "needsUserAction": True,
                    "summary": "点击下方按钮唤起钉钉桌面客户端，使用手机钉钉扫码登录。",
                    "actions": [
                        {"label": "📲 唤起钉钉扫码", "actionType": "desktop", "targetView": "home", "style": "solid"},
                        {"label": "🔄 我已扫码，核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                    ],
                }
            if webhook_ok:
                return {
                    "status": "ready",
                    "badgeText": "✅ 机器人已配置",
                    "needsUserAction": False,
                    "summary": "已配置钉钉加签机器人 Webhook（可向群发送消息）；若需全量私聊 RPA，可补充安装钉钉 Mac 版。",
                    "actions": [
                        {"label": "⬇️ 下载钉钉 Mac 版", "actionType": "download", "targetView": "download", "style": "outline"},
                        {"label": "🔄 核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                    ],
                }
            return {
                "status": "need_install",
                "badgeText": "📥 需装客户端或配机器人",
                "needsUserAction": True,
                "summary": "钉钉官方已停用旧网页版聊天；请点击『下载钉钉 Mac 版』安装扫码，或在右侧配置钉钉加签机器人 Webhook。",
                "actions": [
                    {"label": "⬇️ 下载钉钉 Mac 版", "actionType": "download", "targetView": "download", "style": "solid"},
                    {"label": "🤖 扫码配钉钉机器人", "actionType": "open_config", "targetView": "open_platform", "style": "outline"},
                    {"label": "🔄 重新核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                ],
            }

        if cid == "xiaohongshu":
            web_logged = bool(cached.get("loggedIn"))
            if web_logged:
                return {
                    "status": "ready",
                    "badgeText": "✅ 网页已扫码就绪",
                    "needsUserAction": False,
                    "summary": "ego 浏览器小红书已登录，可读取通知/评论并做防封合规获客演练（手机发稿仍受夜间静默窗保护）。",
                    "actions": [
                        {"label": "🌐 打开小红书页面", "actionType": "ego_login", "targetView": "home", "style": "outline"},
                        {"label": "🎨 打开创作平台", "actionType": "ego_login", "targetView": "creator", "style": "outline"},
                        {"label": "🔄 重新核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                    ],
                }
            return {
                "status": "scan_qr",
                "badgeText": "📱 待扫码登录",
                "needsUserAction": True,
                "summary": "需在 ego 浏览器扫码登录一次小红书：点下方按钮将自动在最前端弹出二维码，用手机小红书扫一扫后点『我已扫码，核验』。",
                "actions": [
                    {"label": "📲 弹出小红书扫码", "actionType": "ego_login", "targetView": "home", "style": "solid"},
                    {"label": "🎨 创作后台扫码", "actionType": "ego_login", "targetView": "creator", "style": "outline"},
                    {"label": "🔄 我已扫码，核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                ],
            }

        if cid == "douyin":
            home_ok = bool(cached.get("loggedIn"))
            creator_ok = bool(cached.get("creatorLoggedIn"))
            if creator_ok:
                return {
                    "status": "ready",
                    "badgeText": "✅ 创作后台已登录",
                    "needsUserAction": False,
                    "summary": "抖音主站与创作者服务平台均已登录，可直接读取评论/私信并抓取高意向线索入 CRM。",
                    "actions": [
                        {"label": "🎨 打开创作者后台", "actionType": "ego_login", "targetView": "creator", "style": "outline"},
                        {"label": "🔄 重新核验", "actionType": "verify", "targetView": "creator", "style": "outline"},
                    ],
                }
            if home_ok:
                return {
                    "status": "scan_qr",
                    "badgeText": "📱 创作后台待扫码",
                    "needsUserAction": True,
                    "summary": "抖音主站网页已有登录态；如需自动回评论与读私信，还需点击下方按钮扫码登录『抖音创作者服务平台』。",
                    "actions": [
                        {"label": "📲 弹出创作者后台扫码", "actionType": "ego_login", "targetView": "creator", "style": "solid"},
                        {"label": "🌐 打开抖音主站", "actionType": "ego_login", "targetView": "home", "style": "outline"},
                        {"label": "🔄 我已扫码，核验", "actionType": "verify", "targetView": "creator", "style": "outline"},
                    ],
                }
            return {
                "status": "scan_qr",
                "badgeText": "📱 待扫码登录",
                "needsUserAction": True,
                "summary": "点击下方按钮将在最前端弹出抖音扫码页面，用手机抖音扫一扫即可开通评论与私信获客。",
                "actions": [
                    {"label": "📲 弹出抖音创作者扫码", "actionType": "ego_login", "targetView": "creator", "style": "solid"},
                    {"label": "🌐 抖音主站扫码", "actionType": "ego_login", "targetView": "home", "style": "outline"},
                    {"label": "🔄 我已扫码，核验", "actionType": "verify", "targetView": "home", "style": "outline"},
                ],
            }

        return {"status": "need_launch", "badgeText": "待核验", "needsUserAction": True, "summary": "点击探测核验渠道状态。", "actions": []}

    def open_auth_flow(
        self,
        channel: str,
        *,
        action_type: str = "auto",
        target_view: str = "home",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        if ch not in CHANNEL_SPECS:
            return {"ok": False, "error_code": "unknown_channel", "error": f"不支持的渠道: {channel}"}
        spec = CHANNEL_SPECS[ch]
        installed_paths = _installed_app_paths(ch)
        req_action = str(action_type or "auto").strip().lower()
        if req_action == "auto":
            req_action = "desktop" if (installed_paths or ch in ("wechat", "wecom", "feishu")) else (
                "ego_login" if spec.get("supportsWebRpa") and ch != "dingtalk" else "download"
            )

        if dry_run:
            planned_url = (spec.get("webUrls") or {}).get(target_view) or (spec.get("webUrls") or {}).get("home") or ""
            return {
                "ok": True,
                "dryRun": True,
                "channel": ch,
                "actionType": req_action,
                "targetView": target_view,
                "url": planned_url,
            }

        if req_action == "desktop":
            if not installed_paths and not self.engine._run_native(["status", "--app", ch], timeout=6.0).get("appRunning"):
                dl_url = (spec.get("webUrls") or {}).get("download") or ""
                return {"ok": False, "channel": ch, "error_code": f"{ch}_not_installed", "error": f"本机尚未安装{spec['shortLabel']}桌面版", "downloadUrl": dl_url}
            res = self.engine._run_native(["activate", "--app", ch], timeout=15.0)
            return {
                "ok": bool(res.get("ok")),
                "channel": ch,
                "actionType": "desktop",
                "message": f"已将{spec['shortLabel']}窗口前置到桌面，若未登录请用手机端扫码登录，完成后点击「重新核验」。",
                "native": res,
            }

        if req_action == "ego_login":
            res = self.ego_browser.open_login_for_user(ch, target_view=target_view)
            return {
                "ok": bool(res.get("ok")),
                "channel": ch,
                "actionType": "ego_login",
                "targetView": target_view,
                "message": f"已在 ego lite 浏览器最前端打开{spec['shortLabel']}登录页并交接操作权，请用手机扫码后回工作台点击「我已扫码，核验」。",
                "browser": res,
            }

        if req_action == "download":
            dl_url = (spec.get("webUrls") or {}).get("download") or (spec.get("webUrls") or {}).get("home") or ""
            if not dl_url:
                return {"ok": False, "channel": ch, "error": f"{spec['shortLabel']}未配置官方下载链接"}
            try:
                subprocess.run(["/usr/bin/open", dl_url], capture_output=True, text=True, timeout=6.0)
            except Exception as exc:
                return {"ok": False, "channel": ch, "error": str(exc), "downloadUrl": dl_url}
            return {
                "ok": True,
                "channel": ch,
                "actionType": "download",
                "downloadUrl": dl_url,
                "message": f"已在默认浏览器打开{spec['shortLabel']}官方下载页，安装后点「重新核验」即可自动识别桌面客户端。",
            }

        if req_action == "open_config":
            custom_url = (spec.get("webUrls") or {}).get("open_platform") or ""
            opened = False
            if custom_url:
                try:
                    subprocess.run(["/usr/bin/open", custom_url], capture_output=True, text=True, timeout=6.0)
                    opened = True
                except Exception:
                    pass
            return {
                "ok": True,
                "channel": ch,
                "actionType": "open_config",
                "openPlatformUrl": custom_url,
                "browserOpened": opened,
                "message": f"请在右侧「配置飞书/钉钉开源机器人凭据」填写 Webhook（已为你打开{spec['shortLabel']}开放平台参考页）。",
            }

        return {"ok": False, "channel": ch, "error": f"不支持的授权动作: {action_type}"}

    def _desktop_windows_by_channel(self) -> Dict[str, Dict[str, Any]]:
        res = self.engine._run_native(["list-app-windows", "--app", "omni"], timeout=12.0)
        by_ch: Dict[str, Dict[str, Any]] = {}
        for item in res.get("apps") or []:
            cid = str(item.get("appId") or "")
            if cid:
                by_ch[cid] = dict(item)
                by_ch[cid]["windows"] = [w for w in (res.get("windows") or []) if w.get("appId") == cid]
        return by_ch

    def overview(self, *, probe_live: bool = False, channel: str = "all") -> Dict[str, Any]:
        desktop_map = self._desktop_windows_by_channel()
        xhs_cli_ok = self.xhs_publisher.available()
        ego_ok = self.ego_browser.available()
        feishu_cfg = self._config.get("feishu") or {}
        dingtalk_cfg = self._config.get("dingtalk") or {}

        req_norm = "" if str(channel or "all").lower() in ("all", "omni", "") else normalize_channel_id(channel)
        channels_out: List[Dict[str, Any]] = []
        for cid in CHANNEL_ORDER:
            if req_norm and cid != req_norm:
                continue
            spec = CHANNEL_SPECS[cid]
            d_info = desktop_map.get(cid) or {}
            installed_paths = _installed_app_paths(cid)
            is_running = bool(d_info.get("running"))
            entry: Dict[str, Any] = {
                "channelId": cid,
                "label": spec["label"],
                "shortLabel": spec["shortLabel"],
                "priority": spec["priority"],
                "category": spec["category"],
                "installed": bool(installed_paths) or is_running,
                "installedPaths": installed_paths,
                "desktopRunning": is_running,
                "desktopWindowCount": int(d_info.get("windowCount") or 0),
                "pid": d_info.get("pid"),
                "windows": d_info.get("windows") or [],
                "egoBrowserAvailable": ego_ok and bool(spec.get("supportsWebRpa")),
                "supportsVoiceCall": bool(spec.get("supportsVoiceCall")),
                "openSourceStacks": OPEN_SOURCE_CHANNEL_STACKS.get(cid, []),
            }
            if cid == "feishu":
                entry["openProtocol"] = self.feishu_bridge.runtime_status(feishu_cfg)
            elif cid == "dingtalk":
                entry["openProtocol"] = self.dingtalk_bridge.runtime_status(dingtalk_cfg)
            elif cid == "xiaohongshu":
                entry["xhsPublisherCli"] = xhs_cli_ok
            if probe_live:
                entry["probe"] = self.probe(cid, launch_if_needed=False)
            cached_auth = self._auth_state.get(cid) or {}
            entry["authCache"] = cached_auth
            entry["authGuide"] = self._build_channel_auth_guide(cid, entry, cached_auth)
            channels_out.append(entry)

        ready_count = sum(1 for c in channels_out if (c.get("authGuide") or {}).get("status") == "ready")
        action_needed_count = sum(1 for c in channels_out if (c.get("authGuide") or {}).get("needsUserAction"))

        return {
            "ok": True,
            "version": "2.9.0",
            "order": list(CHANNEL_ORDER),
            "readyCount": ready_count,
            "actionNeededCount": action_needed_count,
            "systemAuth": self._system_auth_status(),
            "channels": channels_out,
            "globalOpenSourceFrameworks": OPEN_SOURCE_CHANNEL_STACKS["global"],
            "tools": {
                "egoBrowserAvailable": ego_ok,
                "xhsPublisherAvailable": xhs_cli_ok,
                "nativeBinaryExists": self.engine.binary_path.is_file(),
            },
            "config": self.get_redacted_config(),
        }

    def _capture_ocr_desktop(self, ch: str, shot_file: Path, *, allow_activate: bool = False, timeout: float = 18.0) -> Dict[str, Any]:
        args = ["capture-ocr", "--app", ch, "--out", str(shot_file)]
        if not allow_activate:
            args.append("--no-activate")
        ocr_res = self.engine._run_native(args, timeout=timeout)
        if not ocr_res.get("ok") and not allow_activate and ocr_res.get("error_code") in ("window_occluded", "capture_failed"):
            ocr_res = self.engine._run_native(["capture-ocr", "--app", ch, "--out", str(shot_file)], timeout=timeout)
        return ocr_res

    def probe(self, channel: str, *, launch_if_needed: bool = False, include_web: bool = True) -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        if ch not in CHANNEL_SPECS:
            return {"ok": False, "error_code": "unknown_channel", "error": f"不支持的渠道: {channel}"}

        spec = CHANNEL_SPECS[ch]
        installed_paths = _installed_app_paths(ch)
        desktop_status = self.engine._run_native(["status", "--app", ch], timeout=12.0)

        ax_info: Dict[str, Any] = {}
        ocr_parsed: Dict[str, Any] = {}
        screenshot_path = ""

        if launch_if_needed and installed_paths and (not desktop_status.get("appRunning") or int(desktop_status.get("windowCount") or 0) == 0):
            self.engine._run_native(["activate", "--app", ch], timeout=15.0)
            for _ in range(7):
                time.sleep(0.8)
                desktop_status = self.engine._run_native(["status", "--app", ch], timeout=12.0)
                if desktop_status.get("appRunning") and int(desktop_status.get("windowCount") or 0) > 0:
                    break

        if desktop_status.get("appRunning") and int(desktop_status.get("windowCount") or 0) > 0:
            self.verify_dir.mkdir(parents=True, exist_ok=True)
            shot_file = self.verify_dir / f"{ch}_probe.png"
            ocr_res = self._capture_ocr_desktop(ch, shot_file, allow_activate=launch_if_needed, timeout=18.0)
            if ocr_res.get("ok"):
                screenshot_path = str(shot_file) if shot_file.is_file() else ""
                wb = ocr_res.get("windowBounds") or {}
                ocr_parsed = _parse_ocr_sidebar_and_chat(
                    ocr_res.get("elements") or [],
                    img_w=float(ocr_res.get("imageWidth") or wb.get("width") or 1200),
                    img_h=float(ocr_res.get("imageHeight") or wb.get("height") or 800),
                    win_w=float(wb.get("width") or 1200),
                    win_h=float(wb.get("height") or 800),
                    login_hints=spec.get("loginHints") or [],
                    channel=ch,
                )
            ax_res = self.engine._run_native(["ax-tree", "--app", ch, "--depth", "6", "--max-nodes", "500"], timeout=12.0)
            if ax_res.get("ok"):
                ax_info = {
                    "nodeCount": int(ax_res.get("nodeCount") or 0),
                    "inputElements": len(ax_res.get("inputElements") or []),
                }

        web_probe: Optional[Dict[str, Any]] = None
        creator_probe: Optional[Dict[str, Any]] = None
        if include_web and spec.get("supportsWebRpa") and not (desktop_status.get("appRunning") and int(desktop_status.get("windowCount") or 0) > 0):
            if self.ego_browser.available():
                web_probe = self.ego_browser.probe_web(ch, target_view="home")
                if ch == "douyin" and web_probe.get("ok"):
                    creator_probe = self.ego_browser.probe_web("douyin", target_view="creator")
                    web_probe["creatorUrl"] = creator_probe.get("url")
                    web_probe["creatorLoggedIn"] = bool(creator_probe.get("loggedIn"))

        auth_cache_doc: Dict[str, Any] = {
            "desktopRunning": bool(desktop_status.get("appRunning")),
            "loginRequired": bool(ocr_parsed.get("loginRequired")) if ocr_parsed else None,
        }
        if web_probe is not None:
            auth_cache_doc["loggedIn"] = bool(web_probe.get("loggedIn"))
            auth_cache_doc["webRetiredByVendor"] = bool(web_probe.get("webRetiredByVendor"))
            auth_cache_doc["lastUrl"] = web_probe.get("url") or ""
            if ch == "douyin":
                auth_cache_doc["creatorLoggedIn"] = bool(web_probe.get("creatorLoggedIn"))
        self._update_channel_auth_state(ch, auth_cache_doc)

        extra: Dict[str, Any] = {}
        if ch == "xiaohongshu":
            extra["xhsPublisherRateStatus"] = self.xhs_publisher.rate_status()
        elif ch == "feishu":
            extra["openProtocol"] = self.feishu_bridge.runtime_status(self._config.get("feishu") or {})
        elif ch == "dingtalk":
            extra["openProtocol"] = self.dingtalk_bridge.runtime_status(self._config.get("dingtalk") or {})

        probe_entry = {
            "channelId": ch,
            "shortLabel": spec["shortLabel"],
            "installed": bool(installed_paths) or bool(desktop_status.get("appRunning")),
            "desktopRunning": bool(desktop_status.get("appRunning")),
            "desktopWindowCount": int(desktop_status.get("windowCount") or 0),
            "openProtocol": extra.get("openProtocol") or {},
        }
        auth_guide = self._build_channel_auth_guide(ch, probe_entry, self._auth_state.get(ch) or {})

        return {
            "ok": True,
            "channel": ch,
            "label": spec["label"],
            "installed": bool(installed_paths) or bool(desktop_status.get("appRunning")),
            "installedPaths": installed_paths,
            "desktop": {
                "running": bool(desktop_status.get("appRunning")),
                "pid": desktop_status.get("appPID"),
                "windowCount": int(desktop_status.get("windowCount") or 0),
                "windows": desktop_status.get("windows") or [],
                "ax": ax_info,
                "ocr": ocr_parsed,
                "screenshotPath": screenshot_path,
            },
            "web": web_probe,
            "authGuide": auth_guide,
            "openSourceStacks": OPEN_SOURCE_CHANNEL_STACKS.get(ch, []),
            **extra,
        }

    def list_sessions(
        self,
        channel: str,
        *,
        limit: int = 20,
        query: str = "",
        launch_if_needed: bool = False,
    ) -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        if ch in ("wechat", "wecom") and not query:
            if ch == "wechat":
                res = self.engine.list_sessions()
                res["channel"] = ch
                return res
        if ch not in CHANNEL_SPECS:
            return {"ok": False, "error_code": "unknown_channel", "error": f"不支持的渠道: {channel}"}

        spec = CHANNEL_SPECS[ch]
        status = self.engine._run_native(["status", "--app", ch], timeout=10.0)
        if launch_if_needed and _installed_app_paths(ch) and (not status.get("appRunning") or int(status.get("windowCount") or 0) == 0):
            self.engine._run_native(["activate", "--app", ch], timeout=15.0)
            for _ in range(7):
                time.sleep(0.8)
                status = self.engine._run_native(["status", "--app", ch], timeout=10.0)
                if status.get("appRunning") and int(status.get("windowCount") or 0) > 0:
                    break

        if status.get("appRunning") and int(status.get("windowCount") or 0) > 0:
            self.verify_dir.mkdir(parents=True, exist_ok=True)
            shot = self.verify_dir / f"{ch}_sessions.png"
            ocr = self._capture_ocr_desktop(ch, shot, allow_activate=launch_if_needed, timeout=18.0)
            if ocr.get("ok"):
                wb = ocr.get("windowBounds") or {}
                parsed = _parse_ocr_sidebar_and_chat(
                    ocr.get("elements") or [],
                    img_w=float(ocr.get("imageWidth") or wb.get("width") or 1200),
                    img_h=float(ocr.get("imageHeight") or wb.get("height") or 800),
                    win_w=float(wb.get("width") or 1200),
                    win_h=float(wb.get("height") or 800),
                    login_hints=spec.get("loginHints") or [],
                    channel=ch,
                    limit=limit,
                )
                return {
                    "ok": True,
                    "channel": ch,
                    "source": "desktop_rpa",
                    "loginRequired": parsed["loginRequired"],
                    "currentChatTitle": parsed["currentChatTitle"],
                    "sessions": parsed["sessions"],
                    "messagesPreview": parsed["messages"],
                    "screenshotPath": str(shot) if shot.is_file() else "",
                }

        if spec.get("supportsWebRpa") and self.ego_browser.available():
            web_res = self.ego_browser.list_interactions(ch, query=query, limit=limit)
            return {
                "ok": bool(web_res.get("ok")),
                "channel": ch,
                "source": "ego_browser_web",
                "loginRequired": bool(web_res.get("loginRequired")),
                "url": web_res.get("url") or "",
                "sessions": web_res.get("items") or [],
                "previewText": web_res.get("previewText") or "",
                "error": web_res.get("error") or "",
            }

        return {
            "ok": False,
            "channel": ch,
            "error_code": f"{ch}_unavailable",
            "error": f"{spec['label']} 桌面端未运行且未开启网页通道。",
        }

    def read_messages(
        self,
        channel: str,
        *,
        target: str = "",
        limit: int = 20,
        launch_if_needed: bool = False,
    ) -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        if ch == "wechat":
            res = self.engine.read_messages(limit=limit)
            res["channel"] = ch
            return res
        if ch not in CHANNEL_SPECS:
            return {"ok": False, "error_code": "unknown_channel", "error": f"不支持的渠道: {channel}"}

        spec = CHANNEL_SPECS[ch]
        sess_res = self.list_sessions(ch, limit=max(limit, 20), query=target, launch_if_needed=launch_if_needed)
        if not sess_res.get("ok"):
            return sess_res

        # If Desktop RPA is active and target doesn't match open header, click matching sidebar row
        if sess_res.get("source") == "desktop_rpa" and target and not sess_res.get("loginRequired"):
            cur_title = str(sess_res.get("currentChatTitle") or "")
            if target not in cur_title:
                match = next((s for s in sess_res.get("sessions") or [] if target in str(s.get("title") or "")), None)
                if match and isinstance(match.get("clickPoint"), dict):
                    st = self.engine._run_native(["status", "--app", ch], timeout=8.0)
                    wins = st.get("windows") or []
                    if wins:
                        w0 = wins[0].get("bounds") or {}
                        abs_x = float(w0.get("x") or 0) + float(match["clickPoint"]["x"])
                        abs_y = float(w0.get("y") or 0) + float(match["clickPoint"]["y"])
                        self.engine._run_native(["activate", "--app", ch], timeout=10.0)
                        self.engine._run_native(["click", "--x", f"{abs_x:.1f}", "--y", f"{abs_y:.1f}"], timeout=10.0)
                        time.sleep(0.6)
                        sess_res = self.list_sessions(ch, limit=limit, launch_if_needed=False)

        if sess_res.get("source") == "desktop_rpa":
            return {
                "ok": True,
                "channel": ch,
                "source": "desktop_rpa",
                "loginRequired": bool(sess_res.get("loginRequired")),
                "currentChatTitle": sess_res.get("currentChatTitle") or "",
                "messages": sess_res.get("messagesPreview") or [],
                "sessions": sess_res.get("sessions") or [],
            }
        return {
            "ok": True,
            "channel": ch,
            "source": sess_res.get("source") or "ego_browser_web",
            "loginRequired": bool(sess_res.get("loginRequired")),
            "currentChatTitle": target or spec["label"],
            "messages": [
                {"sender": it.get("title") or "用户", "direction": "incoming", "text": it.get("text") or "", "href": it.get("href") or ""}
                for it in (sess_res.get("sessions") or [])
            ],
        }

    def send_message(
        self,
        channel: str,
        target: str,
        text: str,
        *,
        mode: str = "auto",
        dry_run: bool = True,
        confirm_send: bool = False,
    ) -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        if ch not in CHANNEL_SPECS:
            return {"ok": False, "error_code": "unknown_channel", "error": f"不支持的渠道: {channel}"}
        clean_text = str(text or "").strip()
        if not clean_text:
            return {"ok": False, "error_code": "empty_text", "error": "发送内容不能为空"}

        if ch == "wechat" and str(mode).lower() in ("auto", "rpa"):
            return self.engine.send_text(
                target=target,
                text=clean_text,
                dry_run=dry_run,
                silent_mode=bool(dry_run),
                confirm_send=bool(confirm_send and not dry_run),
            )

        req_mode = str(mode or "auto").strip().lower()
        ch_cfg = self._config.get(ch) or {}

        # Open-source webhook / OpenAPI track for Feishu & DingTalk
        if req_mode in ("webhook", "open_api", "openapi") or (
            req_mode == "auto" and not self.engine._run_native(["status", "--app", ch], timeout=8.0).get("appRunning")
            and (ch_cfg.get("webhook_url") or ch_cfg.get("app_id"))
        ):
            if ch == "feishu":
                if ch_cfg.get("app_id") and ch_cfg.get("app_secret") and (target or ch_cfg.get("default_receive_id")):
                    return self.feishu_bridge.send_im_message(
                        app_id=str(ch_cfg["app_id"]),
                        app_secret=str(ch_cfg["app_secret"]),
                        receive_id=str(target or ch_cfg.get("default_receive_id") or ""),
                        text=clean_text,
                        dry_run=dry_run,
                    )
                if ch_cfg.get("webhook_url"):
                    return self.feishu_bridge.send_webhook_text(
                        str(ch_cfg["webhook_url"]),
                        clean_text,
                        secret=str(ch_cfg.get("webhook_secret") or ""),
                        dry_run=dry_run,
                    )
                if req_mode in ("webhook", "open_api", "openapi"):
                    return {"ok": False, "error_code": "feishu_open_protocol_unconfigured", "error": "请先在配置中填写飞书 Webhook URL 或 AppID/AppSecret"}
            elif ch == "dingtalk":
                if ch_cfg.get("webhook_url"):
                    return self.dingtalk_bridge.send_webhook_text(
                        str(ch_cfg["webhook_url"]),
                        clean_text,
                        secret=str(ch_cfg.get("webhook_secret") or ""),
                        dry_run=dry_run,
                    )
                if req_mode in ("webhook", "open_api", "openapi"):
                    return {"ok": False, "error_code": "dingtalk_webhook_unconfigured", "error": "请先配置钉钉加签机器人 Webhook URL"}

        # Track A: Native Desktop App-Use RPA
        status = self.engine._run_native(["status", "--app", ch], timeout=10.0)
        if status.get("appRunning") and int(status.get("windowCount") or 0) > 0 and req_mode in ("auto", "rpa"):
            # Inspect first so we never attempt typing into a QR login screen
            probe = self.read_messages(ch, target=target, limit=10)
            if probe.get("loginRequired"):
                return {
                    "ok": False,
                    "channel": ch,
                    "error_code": "login_required",
                    "error": f"{CHANNEL_SPECS[ch]['label']} 当前处于未登录/扫码页面，请先登录后再发消息。",
                }
            if dry_run or not confirm_send:
                # Safe non-sending paste readback if chat composer is present
                silent_res = self.engine._run_native(
                    ["paste-and-verify", "--app", ch, "--text", clean_text, "--silent"],
                    timeout=18.0,
                )
                return {
                    "ok": bool(silent_res.get("ok")),
                    "dryRun": True,
                    "channel": ch,
                    "mode": "desktop_rpa",
                    "target": target or probe.get("currentChatTitle") or "",
                    "sent": False,
                    "native": silent_res,
                }
            live_res = self.engine._run_native(
                ["paste-and-verify", "--app", ch, "--text", clean_text, "--send"],
                timeout=22.0,
            )
            self.engine.audit.log("omni_send", "ok" if live_res.get("ok") else "error", {"channel": ch, "target": target})
            return {
                "ok": bool(live_res.get("ok")),
                "dryRun": False,
                "channel": ch,
                "mode": "desktop_rpa",
                "target": target,
                "sent": bool(live_res.get("sent")),
                "native": live_res,
            }

        # Track B: ego-browser Web/Creator RPA (Xiaohongshu / Douyin / Web DingTalk)
        if CHANNEL_SPECS[ch].get("supportsWebRpa") and req_mode in ("auto", "web"):
            return self.ego_browser.reply_interaction(
                ch,
                target,
                clean_text,
                dry_run=dry_run,
                confirm_send=confirm_send,
            )

        # Fallback explicit dry_run plan
        if dry_run:
            audit = sanitize_public_channel_reply(ch, clean_text, soften=True)
            return {
                "ok": True,
                "dryRun": True,
                "simulated": True,
                "channel": ch,
                "target": target,
                "text": audit["sanitized"],
                "compliance": audit,
                "note": f"{CHANNEL_SPECS[ch]['label']} 桌面端未进入对话界面；已生成防封合规演练文本。",
            }

        return {
            "ok": False,
            "channel": ch,
            "error_code": f"{ch}_no_active_transport",
            "error": f"{CHANNEL_SPECS[ch]['label']} 无可用的已登录桌面端、网页端或 Webhook 通道。",
        }

    def extract_leads(
        self,
        channel: str,
        *,
        target: str = "",
        query: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
        sync_crm: bool = True,
    ) -> Dict[str, Any]:
        ch = normalize_channel_id(channel)
        if ch not in CHANNEL_SPECS:
            return {"ok": False, "error_code": "unknown_channel", "error": f"不支持的渠道: {channel}"}
        spec = CHANNEL_SPECS[ch]

        items = list(messages or [])
        source = "provided"
        if not items:
            if query and spec.get("supportsWebRpa") and self.ego_browser.available():
                web = self.ego_browser.list_interactions(ch, query=query, limit=20)
                items = [
                    {"sender": it.get("title") or "访客", "text": it.get("text") or "", "direction": "incoming"}
                    for it in (web.get("items") or [])
                ]
                source = "ego_browser_web"
            else:
                read = self.read_messages(ch, target=target, limit=20)
                items = read.get("messages") or []
                source = read.get("source") or "desktop_rpa"

        leads: List[Dict[str, Any]] = []
        enrolled_names: List[str] = []
        for idx, msg in enumerate(items):
            if str(msg.get("direction") or "incoming") == "outgoing":
                continue
            txt = str(msg.get("text") or "").strip()
            if not txt:
                continue
            tier, score, matched = score_lead_intent(txt)
            sender = str(msg.get("sender") or f"{spec['shortLabel']}访客{idx + 1}").strip()[:40]
            lead_doc = {
                "channel": ch,
                "sender": sender,
                "intentTier": tier,
                "intentScore": score,
                "matchedSignals": matched,
                "text": txt[:240],
                "enrolledInCrm": False,
            }
            if tier in ("hot", "warm"):
                if sync_crm and hasattr(self.engine, "sales_crm"):
                    crm_name = f"[{spec['shortLabel']}]{sender}"
                    try:
                        self.engine.sales_crm.enroll_contact(
                            crm_name,
                            stage="已报价" if "报价" in matched else "沟通中",
                            note=f"[{spec['label']}线索 | {tier.upper()} {score}分] {txt[:180]}",
                            alias=sender if sender != crm_name else "",
                            tags=[f"渠道:{spec['shortLabel']}", f"意向:{tier}"],
                        )
                        lead_doc["enrolledInCrm"] = True
                        lead_doc["crmTarget"] = crm_name
                        enrolled_names.append(crm_name)
                    except Exception as exc:
                        lead_doc["crmError"] = str(exc)
            leads.append(lead_doc)

        leads.sort(key=lambda x: -int(x["intentScore"]))
        return {
            "ok": True,
            "channel": ch,
            "source": source,
            "scannedCount": len(items),
            "leadCount": len(leads),
            "hotOrWarmCount": len([l for l in leads if l["intentTier"] in ("hot", "warm")]),
            "enrolledCount": len(enrolled_names),
            "enrolledTargets": enrolled_names,
            "leads": leads,
        }

    def finish_browser_space(self) -> Dict[str, Any]:
        """Close/finish agent-created ego-browser TaskSpace cleanly."""
        return self.ego_browser.finish_space()
