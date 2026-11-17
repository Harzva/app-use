"""Magpie Open-Source Multi-Provider & Multi-Model Hub for WeChat RPA Control.

Direct Python adaptation of the open-source Magpie ecosystem vendored under
`vendor/magpie/`:
  - `@straydragon/dsh-x-magpie@0.7.2` (`mapModel`, `effortsOf`, `inputOf`,
    `REASONING_LEVELS`, `/v1/models` sync logic)
  - `@harzva/dsh-magpie-openbot` (`MagpieManager`: SHA-256 profile ID
    `magpie_<hash>`, loopback gateway validation, masked credential storage)
  - `openbot-magpie.js` (`secretSafe`, model selection & status payloads)

Supports:
  1. Live Magpie Local Gateway (`http://127.0.0.1:3425/v1`), auto-discovering all
     routed upstream providers (`auto`, `deepseek`, `mistral`, `opencode-go`,
     `qwen-vip`, `qwen-needed`, `teamroouter`, `zcode`, `zhitro`, `group`).
  2. Multi-vendor direct OpenAI/Anthropic-compatible provider registry stored in
     `config/model_providers.json` (with API keys strictly masked in outputs).
  3. Active global model, fallback model, per-contact model bindings, live latency
     probing, and LLM chat completions with deterministic KB fallback.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GATEWAY_URL = "http://127.0.0.1:3425"
DEFAULT_GATEWAY_KEY = "magpie"
SUPPORTED_APIS = ("openai-completions", "openai-responses", "anthropic-messages")
ROUTE_MODALITIES = ("text", "image")
REASONING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")

CURATED_RECOMMENDED_IDS = [
    "auto/deepseek-v4-pro",
    "auto/deepseek-v4.1-flash",
    "auto/glm-5.3",
    "auto/glm-5.3-flash",
    "auto/minimax-m3.1-flash",
    "mistral/mistral-large-4",
    "opencode-go/kimi-k2.5",
    "zcode/glm-5-turbo",
    "group/smart-split",
]

DEFAULT_MAGPIE_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "auto/deepseek-v4-pro",
        "display_name": "DeepSeek V4 Pro",
        "magpie_label": "DeepSeek V4 Pro · routing group",
        "owned_by": "deepseek",
        "context_window": 1048576,
        "max_output_tokens": 393216,
        "reasoning": True,
        "tool_call": True,
        "modalities": {"input": ["text"], "output": ["text"]},
        "supported_reasoning_levels": [{"effort": "high"}, {"effort": "max"}],
    },
    {
        "id": "auto/deepseek-v4.1-flash",
        "display_name": "DeepSeek V4.1 Flash",
        "magpie_label": "DeepSeek V4.1 Flash · routing group",
        "owned_by": "qwen-vip",
        "context_window": 1048576,
        "max_output_tokens": 384000,
        "reasoning": True,
        "tool_call": True,
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}, {"effort": "max"}],
    },
    {
        "id": "auto/glm-5.3",
        "display_name": "GLM-5.3",
        "magpie_label": "GLM-5.3 · routing group",
        "owned_by": "zcode",
        "context_window": 202752,
        "max_output_tokens": 131072,
        "reasoning": True,
        "tool_call": True,
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "supported_reasoning_levels": [{"effort": "none"}, {"effort": "high"}],
    },
    {
        "id": "auto/glm-5.3-flash",
        "display_name": "GLM-5.3 Flash",
        "magpie_label": "GLM-5.3 Flash · routing group",
        "owned_by": "zhitro",
        "context_window": 200000,
        "max_output_tokens": 128000,
        "reasoning": True,
        "tool_call": True,
        "modalities": {"input": ["text"], "output": ["text"]},
        "supported_reasoning_levels": [{"effort": "none"}, {"effort": "low"}],
    },
    {
        "id": "auto/minimax-m3.1-flash",
        "display_name": "MiniMax M3.1 Flash",
        "magpie_label": "MiniMax M3.1 Flash · routing group",
        "owned_by": "opencode-go",
        "context_window": 200000,
        "max_output_tokens": 128000,
        "reasoning": True,
        "tool_call": True,
        "modalities": {"input": ["text"], "output": ["text"]},
        "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
    },
    {
        "id": "mistral/mistral-large-4",
        "display_name": "Mistral Large 4",
        "magpie_label": "Mistral Large 4 · mistral",
        "owned_by": "mistral",
        "context_window": 262144,
        "max_output_tokens": 65536,
        "reasoning": True,
        "tool_call": True,
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
    },
    {
        "id": "opencode-go/kimi-k2.5",
        "display_name": "Kimi K2.5",
        "magpie_label": "Kimi K2.5 · opencode-go",
        "owned_by": "opencode-go",
        "context_window": 262144,
        "max_output_tokens": 65536,
        "reasoning": True,
        "tool_call": True,
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
    },
    {
        "id": "group/smart-split",
        "display_name": "难题给强模型，简单的给便宜模型",
        "magpie_label": "难题给强模型，简单的给便宜模型 · routing group",
        "owned_by": "deepseek",
        "context_window": 1048576,
        "max_output_tokens": 393216,
        "reasoning": True,
        "tool_call": True,
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "supported_reasoning_levels": [
            {"effort": "none"},
            {"effort": "low"},
            {"effort": "high"},
            {"effort": "max"},
        ],
    },
]

BUILTIN_PROVIDER_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "magpie-gateway",
        "name": "Magpie 多供应商聚合网关",
        "vendor": "Magpie",
        "api": "openai-completions",
        "baseUrl": DEFAULT_GATEWAY_URL,
        "apiKeyEnv": "MAGPIE_GATEWAY_KEY",
        "defaultModel": "auto/deepseek-v4-pro",
        "description": "本机 Magpie 统一网关，自动聚合 DeepSeek/GLM/Qwen/Kimi/Mistral/MiniMax/OpenCode 等供应商与智能路由组。",
        "isGateway": True,
        "enabled": True,
    },
    {
        "id": "deepseek-official",
        "name": "DeepSeek 官方直连",
        "vendor": "DeepSeek",
        "api": "openai-completions",
        "baseUrl": "https://api.deepseek.com/v1",
        "apiKeyEnv": "DEEPSEEK_API_KEY",
        "defaultModel": "deepseek-chat",
        "description": "DeepSeek 官方 OpenAI 兼容接口（deepseek-chat / deepseek-reasoner）。",
        "isGateway": False,
        "enabled": False,
    },
    {
        "id": "moonshot-kimi",
        "name": "Moonshot Kimi",
        "vendor": "Moonshot",
        "api": "openai-completions",
        "baseUrl": "https://api.moonshot.cn/v1",
        "apiKeyEnv": "MOONSHOT_API_KEY",
        "defaultModel": "kimi-k2.5",
        "description": "月之暗面 Kimi 开放平台接口，擅长中文语境共情对话与长上下文。",
        "isGateway": False,
        "enabled": False,
    },
    {
        "id": "zhipu-glm",
        "name": "智谱 GLM (BigModel)",
        "vendor": "ZhipuAI",
        "api": "openai-completions",
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "apiKeyEnv": "ZHIPU_API_KEY",
        "defaultModel": "glm-4.7-flash",
        "description": "智谱开放平台 API，兼容 OpenAI Chat Completions 协议。",
        "isGateway": False,
        "enabled": False,
    },
    {
        "id": "aliyun-qwen",
        "name": "阿里云百炼 Qwen",
        "vendor": "Alibaba Cloud",
        "api": "openai-completions",
        "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "apiKeyEnv": "DASHSCOPE_API_KEY",
        "defaultModel": "qwen-plus",
        "description": "阿里云百炼 OpenAI 兼容模式，低延迟高稳定性。",
        "isGateway": False,
        "enabled": False,
    },
    {
        "id": "mistral-ai",
        "name": "Mistral AI",
        "vendor": "Mistral",
        "api": "openai-completions",
        "baseUrl": "https://api.mistral.ai/v1",
        "apiKeyEnv": "MISTRAL_API_KEY",
        "defaultModel": "mistral-large-latest",
        "description": "Mistral 官方多语种旗舰模型接口。",
        "isGateway": False,
        "enabled": False,
    },
    {
        "id": "minimax-official",
        "name": "MiniMax 开放平台",
        "vendor": "MiniMax",
        "api": "openai-completions",
        "baseUrl": "https://api.minimax.chat/v1",
        "apiKeyEnv": "MINIMAX_API_KEY",
        "defaultModel": "MiniMax-Text-01",
        "description": "MiniMax 开放平台对话补全接口。",
        "isGateway": False,
        "enabled": False,
    },
    {
        "id": "openrouter",
        "name": "OpenRouter 聚合",
        "vendor": "OpenRouter",
        "api": "openai-completions",
        "baseUrl": "https://openrouter.ai/api/v1",
        "apiKeyEnv": "OPENROUTER_API_KEY",
        "defaultModel": "deepseek/deepseek-chat",
        "description": "OpenRouter 全球多模型统一入口。",
        "isGateway": False,
        "enabled": False,
    },
    {
        "id": "ollama-local",
        "name": "Ollama 本地模型",
        "vendor": "Ollama",
        "api": "openai-completions",
        "baseUrl": "http://127.0.0.1:11434/v1",
        "apiKeyEnv": "",
        "defaultModel": "qwen2.5:14b",
        "description": "完全离线的本机 Ollama OpenAI 兼容端点，零外网数据出境。",
        "isGateway": False,
        "enabled": False,
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_int(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return int(value)
    return 0


def _efforts_of(row: Dict[str, Any]) -> Any:
    """Port of `effortsOf` from vendored `@straydragon/dsh-x-magpie`."""
    if row.get("reasoning") is False:
        return False
    levels = row.get("supported_reasoning_levels")
    if not isinstance(levels, list) or not levels:
        return None
    mapping: Dict[str, str] = {}
    for entry in levels:
        effort = entry.get("effort") if isinstance(entry, dict) else entry
        if not isinstance(effort, str) or not effort:
            continue
        level = "off" if effort == "none" else effort
        if level in REASONING_LEVELS:
            mapping[level] = effort
    return mapping or None


def _input_of(row: Dict[str, Any]) -> Optional[List[str]]:
    """Port of `inputOf` from vendored `@straydragon/dsh-x-magpie`."""
    modalities = (row.get("modalities") or {}).get("input") if isinstance(row.get("modalities"), dict) else row.get("input")
    if not isinstance(modalities, list):
        return None
    seen: List[str] = []
    for item in modalities:
        if isinstance(item, str) and item in ROUTE_MODALITIES and item not in seen:
            seen.append(item)
    return seen or None


def map_magpie_model(row: Dict[str, Any], source_provider: str = "magpie-gateway") -> Optional[Dict[str, Any]]:
    """Port of `mapModel` from vendored `@straydragon/dsh-x-magpie` with provider metadata."""
    if not isinstance(row, dict):
        return None
    model_id = str(row.get("id") or "").strip()
    if not model_id:
        return None

    route_prefix = model_id.split("/", 1)[0] if "/" in model_id else source_provider
    owned_by = str(row.get("owned_by") or route_prefix or source_provider).strip()
    display_name = str(row.get("display_name") or row.get("name") or model_id).strip()
    magpie_label = str(row.get("magpie_label") or display_name).strip()
    context_window = _positive_int(row.get("context_window") or row.get("context_length"))
    max_tokens = _positive_int(row.get("max_output_tokens") or row.get("maxTokens"))
    input_modalities = _input_of(row) or ["text"]
    efforts = _efforts_of(row)

    return {
        "id": model_id,
        "name": display_name,
        "displayName": display_name,
        "magpieLabel": magpie_label,
        "routeGroup": route_prefix,
        "ownedBy": owned_by,
        "providerId": source_provider,
        "contextWindow": context_window,
        "maxTokens": max_tokens,
        "input": input_modalities,
        "vision": "image" in input_modalities,
        "reasoning": bool(row.get("reasoning") is not False and (efforts or row.get("reasoning") is True)),
        "reasoningEfforts": efforts if efforts is not False else {},
        "toolCall": bool(row.get("tool_call") or ("tools" in (row.get("supported_parameters") or []))),
        "recommended": model_id in CURATED_RECOMMENDED_IDS,
    }


def _strip_thinking_tags(text: str) -> str:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", str(text or ""), flags=re.IGNORECASE).strip()
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_gateway_url(url: str, *, allow_remote: bool = False) -> str:
    raw = str(url or "").strip().rstrip("/")
    if not raw:
        raise ValueError("网关地址不能为空")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"无效的网关地址: {url}")
    if not allow_remote:
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "http" or host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Magpie 本地网关仅支持本机 HTTP 地址 (127.0.0.1 / localhost)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Magpie 网关 URL 不应包含用户名、密码或查询参数")
        return f"http://{host.replace('localhost', '127.0.0.1')}:{parsed.port or 3425}"
    return raw


def _api_endpoint(base_url: str, suffix: str) -> str:
    clean_base = str(base_url or DEFAULT_GATEWAY_URL).strip().rstrip("/")
    clean_suffix = "/" + suffix.lstrip("/")
    if re.search(r"/v\d+$", clean_base):
        return f"{clean_base}{clean_suffix}"
    return f"{clean_base}/v1{clean_suffix}"


def _is_loopback(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def _default_http_request(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 12.0,
) -> Tuple[int, Dict[str, Any]]:
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req_headers = {"Accept": "application/json"}
    if payload is not None:
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method.upper())
    # Bypass system HTTP proxies for local Magpie / Ollama endpoints (matching magpie_task.py)
    handlers = [urllib.request.ProxyHandler({})] if _is_loopback(url) else []
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        try:
            err_json = json.loads(raw) if raw.strip() else {"error": raw}
        except json.JSONDecodeError:
            err_json = {"error": raw}
        return exc.code, err_json


class MagpieProviderHub:
    """Unified multi-provider model registry & completion router inspired by Magpie."""

    def __init__(
        self,
        *,
        plugin_root: Optional[Path] = None,
        config_path: Optional[Path] = None,
        http_requester: Optional[Callable[..., Tuple[int, Dict[str, Any]]]] = None,
    ) -> None:
        self.plugin_root = Path(plugin_root) if plugin_root else DEFAULT_PLUGIN_ROOT
        self.config_path = (
            Path(config_path)
            if config_path
            else self.plugin_root / "config" / "model_providers.json"
        )
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._request = http_requester or _default_http_request
        self._cached_models: List[Dict[str, Any]] = []
        self._gateway_reachable: bool = False
        self._last_sync_at: Optional[str] = None
        self._last_sync_error: Optional[str] = None
        self._recent_calls: List[Dict[str, Any]] = []
        self.state = self._load_or_init_state()

    def _default_state(self) -> Dict[str, Any]:
        providers: Dict[str, Dict[str, Any]] = {}
        for tmpl in BUILTIN_PROVIDER_TEMPLATES:
            item = dict(tmpl)
            item["apiKey"] = DEFAULT_GATEWAY_KEY if item["id"] == "magpie-gateway" else ""
            item["customModels"] = [item["defaultModel"]] if not item.get("isGateway") else []
            providers[item["id"]] = item
        return {
            "version": 1,
            "gatewayUrl": DEFAULT_GATEWAY_URL,
            "activeProviderId": "magpie-gateway",
            "activeModelId": "auto/deepseek-v4-pro",
            "fallbackModelId": "auto/deepseek-v4.1-flash",
            "llmReplyEnabled": True,
            "temperature": 0.4,
            "maxTokens": 1024,
            "timeoutSec": 15.0,
            "contactModelBindings": {},
            "providers": providers,
            "profiles": {},
        }

    def _load_or_init_state(self) -> Dict[str, Any]:
        state = self._default_state()
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key in (
                        "gatewayUrl",
                        "activeProviderId",
                        "activeModelId",
                        "fallbackModelId",
                        "llmReplyEnabled",
                        "temperature",
                        "maxTokens",
                        "timeoutSec",
                    ):
                        if key in loaded:
                            state[key] = loaded[key]
                    if isinstance(loaded.get("contactModelBindings"), dict):
                        state["contactModelBindings"] = dict(loaded["contactModelBindings"])
                    if isinstance(loaded.get("profiles"), dict):
                        state["profiles"] = dict(loaded["profiles"])
                    if isinstance(loaded.get("providers"), dict):
                        for pid, pdata in loaded["providers"].items():
                            if isinstance(pdata, dict):
                                merged = dict(state["providers"].get(pid, {}))
                                merged.update(pdata)
                                merged["id"] = pid
                                state["providers"][pid] = merged
            except (OSError, json.JSONDecodeError):
                pass
        else:
            self._save_state(state)
        return state

    def _save_state(self, state: Optional[Dict[str, Any]] = None) -> None:
        target = state if state is not None else self.state
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(target, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_llm_enabled(self) -> bool:
        return bool(self.state.get("llmReplyEnabled", True))

    def _resolve_provider_api_key(self, provider: Dict[str, Any]) -> str:
        env_name = str(provider.get("apiKeyEnv") or "").strip()
        if env_name and os.environ.get(env_name):
            return os.environ[env_name].strip()
        saved = str(provider.get("apiKey") or "").strip()
        if saved:
            return saved
        if provider.get("id") == "magpie-gateway":
            return DEFAULT_GATEWAY_KEY
        return ""

    def _mask_provider(self, provider: Dict[str, Any]) -> Dict[str, Any]:
        """Never leak raw API keys to Web UI or API callers (matching `openbot-magpie.js`)."""
        resolved = self._resolve_provider_api_key(provider)
        env_name = str(provider.get("apiKeyEnv") or "").strip()
        return {
            "id": provider.get("id", ""),
            "name": provider.get("name", provider.get("id", "")),
            "vendor": provider.get("vendor", "Custom"),
            "api": provider.get("api", "openai-completions"),
            "baseUrl": provider.get("baseUrl", ""),
            "apiKeyEnv": env_name,
            "defaultModel": provider.get("defaultModel", ""),
            "description": provider.get("description", ""),
            "isGateway": bool(provider.get("isGateway", False)),
            "enabled": bool(provider.get("enabled", True)),
            "hasKey": bool(resolved),
            "maskedKey": "••••••••" if resolved else "",
            "customModels": list(provider.get("customModels") or []),
        }

    def configure_gateway(
        self,
        *,
        gateway_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Port of `MagpieManager.configure` for the Magpie loopback gateway."""
        next_url = (
            _normalize_gateway_url(gateway_url, allow_remote=False)
            if gateway_url is not None and str(gateway_url).strip()
            else self.state.get("gatewayUrl", DEFAULT_GATEWAY_URL)
        )
        self.state["gatewayUrl"] = next_url
        magpie_provider = dict(self.state["providers"].get("magpie-gateway") or {})
        magpie_provider["baseUrl"] = next_url
        if api_key is not None:
            cleaned_key = str(api_key).strip()
            if "\n" in cleaned_key or "\r" in cleaned_key or "\0" in cleaned_key:
                raise ValueError("网关密钥包含非法控制字符")
            if cleaned_key:
                magpie_provider["apiKey"] = cleaned_key
        magpie_provider["enabled"] = True
        self.state["providers"]["magpie-gateway"] = magpie_provider
        self._save_state()
        return self.get_summary(refresh=False)

    def upsert_provider(
        self,
        *,
        provider_id: str,
        name: str,
        base_url: str,
        api: str = "openai-completions",
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
        default_model: str = "",
        vendor: str = "Custom",
        enabled: bool = True,
        custom_models: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Add or update an OpenAI/Anthropic-compatible provider cleanly without secret leakage."""
        pid = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(provider_id or "").strip().lower()).strip("-")
        if not pid:
            raise ValueError("provider_id 不能为空")
        if api not in SUPPORTED_APIS:
            raise ValueError(f"不支持的 API 协议 {api}，可选: {', '.join(SUPPORTED_APIS)}")
        allow_remote = pid != "magpie-gateway"
        normalized_url = _normalize_gateway_url(base_url, allow_remote=allow_remote)

        existing = dict(self.state["providers"].get(pid) or {})
        resolved_models = list(custom_models or existing.get("customModels") or [])
        if default_model and default_model not in resolved_models:
            resolved_models.insert(0, default_model)

        entry = {
            "id": pid,
            "name": str(name or existing.get("name") or pid).strip(),
            "vendor": str(vendor or existing.get("vendor") or "Custom").strip(),
            "api": api,
            "baseUrl": normalized_url,
            "apiKeyEnv": str(api_key_env if api_key_env is not None else existing.get("apiKeyEnv") or "").strip(),
            "defaultModel": str(default_model or existing.get("defaultModel") or (resolved_models[0] if resolved_models else "")).strip(),
            "description": str(existing.get("description") or f"{vendor} 自定义多模型供应商接入").strip(),
            "isGateway": pid == "magpie-gateway",
            "enabled": bool(enabled),
            "customModels": resolved_models,
            "apiKey": existing.get("apiKey", ""),
        }
        if api_key is not None and str(api_key).strip() and str(api_key).strip() != "••••••••":
            entry["apiKey"] = str(api_key).strip()
        if pid == "magpie-gateway":
            self.state["gatewayUrl"] = normalized_url

        self.state["providers"][pid] = entry
        self._save_state()
        return {"ok": True, "provider": self._mask_provider(entry), "summary": self.get_summary(refresh=False)}

    def sync_models(self, *, force: bool = False) -> Dict[str, Any]:
        """Port of `MagpieManager.sync` + `magpie_task.py` `live_models()`."""
        if self._cached_models and not force and self._last_sync_at:
            return self._build_catalog_snapshot()

        gateway_provider = self.state["providers"].get("magpie-gateway") or {}
        gateway_url = str(gateway_provider.get("baseUrl") or self.state.get("gatewayUrl") or DEFAULT_GATEWAY_URL)
        gateway_key = self._resolve_provider_api_key(gateway_provider) or DEFAULT_GATEWAY_KEY
        models_url = _api_endpoint(gateway_url, "/models")

        discovered: List[Dict[str, Any]] = []
        gateway_online = False
        sync_error: Optional[str] = None

        try:
            status, payload = self._request(
                "GET",
                models_url,
                headers={"Authorization": f"Bearer {gateway_key}"},
                payload=None,
                timeout=6.0,
            )
            rows = payload.get("data") if isinstance(payload, dict) else None
            if status == 200 and isinstance(rows, list):
                gateway_online = True
                for row in rows:
                    mapped = map_magpie_model(row, source_provider="magpie-gateway")
                    if mapped:
                        discovered.append(mapped)
            else:
                sync_error = f"Magpie 网关返回状态 {status}"
        except Exception as exc:
            sync_error = str(exc)

        if not discovered:
            for row in DEFAULT_MAGPIE_CATALOG:
                mapped = map_magpie_model(row, source_provider="magpie-gateway")
                if mapped:
                    mapped["offlineFallbackCatalog"] = True
                    discovered.append(mapped)

        # Also append configured non-gateway providers' custom models
        existing_ids = {m["id"] for m in discovered}
        for pid, provider in self.state.get("providers", {}).items():
            if pid == "magpie-gateway" or not provider.get("enabled"):
                continue
            model_names = list(provider.get("customModels") or [])
            if provider.get("defaultModel") and provider["defaultModel"] not in model_names:
                model_names.insert(0, provider["defaultModel"])
            for model_name in model_names:
                qualified = f"{pid}/{model_name}" if "/" not in model_name else model_name
                if qualified in existing_ids:
                    continue
                existing_ids.add(qualified)
                discovered.append(
                    {
                        "id": qualified,
                        "name": model_name,
                        "displayName": model_name,
                        "magpieLabel": f"{provider.get('name', pid)} · {model_name}",
                        "routeGroup": pid,
                        "ownedBy": provider.get("vendor") or pid,
                        "providerId": pid,
                        "contextWindow": 131072,
                        "maxTokens": 8192,
                        "input": ["text"],
                        "vision": False,
                        "reasoning": True,
                        "reasoningEfforts": {},
                        "toolCall": True,
                        "recommended": False,
                    }
                )

        # Sort recommended first, then route group & id
        discovered.sort(key=lambda m: (0 if m.get("recommended") else 1, m.get("routeGroup", ""), m.get("id", "")))

        self._cached_models = discovered
        self._gateway_reachable = gateway_online
        self._last_sync_at = _utc_now()
        self._last_sync_error = sync_error
        return self._build_catalog_snapshot()

    def _build_catalog_snapshot(self) -> Dict[str, Any]:
        groups: Dict[str, int] = {}
        for m in self._cached_models:
            grp = str(m.get("routeGroup") or m.get("ownedBy") or "other")
            groups[grp] = groups.get(grp, 0) + 1
        return {
            "gatewayOnline": self._gateway_reachable,
            "gatewayUrl": self.state.get("gatewayUrl", DEFAULT_GATEWAY_URL),
            "lastSyncAt": self._last_sync_at,
            "syncError": self._last_sync_error,
            "modelCount": len(self._cached_models),
            "providerGroups": [{"name": k, "count": v} for k, v in sorted(groups.items())],
            "models": self._cached_models,
        }

    def resolve_profile_id(self, base_url: str, model_id: str) -> str:
        """Exact port of `MagpieManager.useModel` SHA-256 profile ID (`magpie_<16hex>`)."""
        digest = hashlib.sha256(f"{base_url}\0{model_id}".encode("utf-8")).hexdigest()[:16]
        return f"magpie_{digest}"

    def use_model(
        self,
        *,
        model_id: str,
        contact: Optional[str] = None,
        provider_id: Optional[str] = None,
        fallback_model_id: Optional[str] = None,
        llm_enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Select active global model or bind a model to a specific contact, creating a named profile."""
        clean_model = str(model_id or "").strip()
        if llm_enabled is not None:
            self.state["llmReplyEnabled"] = bool(llm_enabled)
        if fallback_model_id is not None and str(fallback_model_id).strip():
            self.state["fallbackModelId"] = str(fallback_model_id).strip()

        profile_created: Optional[Dict[str, Any]] = None
        if clean_model:
            resolved_provider_id = provider_id or self._infer_provider_for_model(clean_model)
            provider = self.state["providers"].get(resolved_provider_id) or self.state["providers"].get("magpie-gateway") or {}
            base_url = _api_endpoint(str(provider.get("baseUrl") or self.state.get("gatewayUrl") or DEFAULT_GATEWAY_URL), "")
            base_url = base_url.rstrip("/")
            profile_id = self.resolve_profile_id(base_url, clean_model)
            profile_created = {
                "id": profile_id,
                "name": f"Magpie · {clean_model}",
                "providerId": resolved_provider_id,
                "baseUrl": base_url,
                "model": clean_model,
                "updatedAt": _utc_now(),
            }
            self.state.setdefault("profiles", {})[profile_id] = profile_created

            if contact and str(contact).strip():
                self.state.setdefault("contactModelBindings", {})[str(contact).strip()] = clean_model
            else:
                self.state["activeModelId"] = clean_model
                self.state["activeProviderId"] = resolved_provider_id

        self._save_state()
        return {
            "ok": True,
            "profileId": profile_created["id"] if profile_created else None,
            "profile": profile_created,
            "contact": contact,
            "activeModelId": self.state.get("activeModelId"),
            "fallbackModelId": self.state.get("fallbackModelId"),
            "llmReplyEnabled": bool(self.state.get("llmReplyEnabled", True)),
            "contactModelBindings": dict(self.state.get("contactModelBindings") or {}),
        }

    def _infer_provider_for_model(self, model_id: str) -> str:
        for m in self._cached_models:
            if m.get("id") == model_id and m.get("providerId"):
                return str(m["providerId"])
        prefix = model_id.split("/", 1)[0] if "/" in model_id else ""
        if prefix in self.state.get("providers", {}):
            return prefix
        return "magpie-gateway"

    def resolve_model_for_contact(self, contact_name: Optional[str] = None, explicit_model_id: Optional[str] = None) -> str:
        if explicit_model_id and str(explicit_model_id).strip():
            return str(explicit_model_id).strip()
        if contact_name:
            bound = (self.state.get("contactModelBindings") or {}).get(contact_name)
            if bound:
                return str(bound)
        return str(self.state.get("activeModelId") or "auto/deepseek-v4-pro")

    def _resolve_execution_target(self, model_id: str, provider_id: Optional[str] = None) -> Tuple[str, str, str, str]:
        """Returns `(provider_id, endpoint_url, api_key, wire_model_id)`."""
        chosen_pid = provider_id or self._infer_provider_for_model(model_id)
        providers = self.state.get("providers") or {}
        provider = providers.get(chosen_pid) or providers.get("magpie-gateway") or {}
        base_url = str(provider.get("baseUrl") or self.state.get("gatewayUrl") or DEFAULT_GATEWAY_URL)
        api_key = self._resolve_provider_api_key(provider) or DEFAULT_GATEWAY_KEY
        wire_model = model_id
        if chosen_pid != "magpie-gateway" and model_id.startswith(f"{chosen_pid}/"):
            wire_model = model_id[len(chosen_pid) + 1 :]
        endpoint = _api_endpoint(base_url, "/chat/completions")
        return chosen_pid, endpoint, api_key, wire_model

    def generate_chat_reply(
        self,
        messages: List[Dict[str, Any]],
        *,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        contact_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Call the selected Magpie/custom provider model, falling back cleanly on error."""
        primary_model = self.resolve_model_for_contact(contact_name=contact_name, explicit_model_id=model_id)
        fallback_model = str(self.state.get("fallbackModelId") or "").strip()
        candidates = [primary_model]
        if fallback_model and fallback_model not in candidates and not model_id:
            candidates.append(fallback_model)

        temp_val = float(temperature if temperature is not None else self.state.get("temperature", 0.4))
        max_tok = max(512, int(max_tokens if max_tokens is not None else self.state.get("maxTokens", 1024)))
        req_timeout = float(timeout if timeout is not None else self.state.get("timeoutSec", 15.0))

        last_error = "No model candidate succeeded"
        for candidate in candidates:
            pid, endpoint, api_key, wire_model = self._resolve_execution_target(candidate, provider_id=provider_id)
            started = time.perf_counter()
            try:
                status, data = self._request(
                    "POST",
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}"},
                    payload={
                        "model": wire_model,
                        "messages": messages,
                        "temperature": temp_val,
                        "max_tokens": max_tok,
                    },
                    timeout=req_timeout,
                )
                latency_ms = round((time.perf_counter() - started) * 1000, 1)
                choices = data.get("choices") if isinstance(data, dict) else None
                if status == 200 and isinstance(choices, list) and choices:
                    msg = choices[0].get("message") or {}
                    raw_text = msg.get("content") or ""
                    clean_text = _strip_thinking_tags(str(raw_text))
                    if clean_text:
                        receipt = {
                            "ok": True,
                            "modelId": candidate,
                            "wireModel": wire_model,
                            "providerId": pid,
                            "latencyMs": latency_ms,
                            "statusCode": status,
                            "timestamp": _utc_now(),
                            "preview": clean_text[:60],
                            "usage": data.get("usage") if isinstance(data, dict) else None,
                        }
                        self._recent_calls = [receipt] + self._recent_calls[:19]
                        return {**receipt, "replyText": clean_text, "usedFallback": candidate != primary_model}
                    last_error = f"Model {candidate} returned empty content"
                else:
                    err_detail = data.get("error") if isinstance(data, dict) else data
                    last_error = f"HTTP {status}: {err_detail}"
            except Exception as exc:
                latency_ms = round((time.perf_counter() - started) * 1000, 1)
                last_error = str(exc)

            self._recent_calls = [
                {
                    "ok": False,
                    "modelId": candidate,
                    "providerId": pid,
                    "latencyMs": latency_ms,
                    "error": last_error[:160],
                    "timestamp": _utc_now(),
                }
            ] + self._recent_calls[:19]

        return {
            "ok": False,
            "modelId": primary_model,
            "providerId": provider_id or self._infer_provider_for_model(primary_model),
            "error": last_error,
        }

    @staticmethod
    def _encode_image_data_url(image_path: Path, *, max_dim: int = 1280) -> Optional[Dict[str, Any]]:
        path = Path(image_path)
        if not path.is_file() or path.stat().st_size <= 0:
            return None
        mime = "image/png"
        ext = path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif ext == ".webp":
            mime = "image/webp"

        raw_bytes: Optional[bytes] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tf:
                proc = subprocess.run(
                    [
                        "/usr/bin/sips",
                        "-Z",
                        str(max_dim),
                        "-s",
                        "format",
                        "jpeg",
                        "-s",
                        "formatOptions",
                        "82",
                        str(path),
                        "--out",
                        tf.name,
                    ],
                    capture_output=True,
                    timeout=6.0,
                )
                if proc.returncode == 0 and Path(tf.name).stat().st_size > 100:
                    raw_bytes = Path(tf.name).read_bytes()
                    mime = "image/jpeg"
        except Exception:
            raw_bytes = None

        if raw_bytes is None:
            try:
                raw_bytes = path.read_bytes()
            except Exception:
                return None

        b64 = base64.b64encode(raw_bytes).decode("ascii")
        return {
            "path": str(path),
            "mime": mime,
            "bytes": len(raw_bytes),
            "dataUrl": f"data:{mime};base64,{b64}",
        }

    def analyze_multimodal(
        self,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        image_paths: Optional[List[Path]] = None,
        ocr_context: str = "",
        contact_name: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: int = 900,
        temperature: float = 0.25,
        timeout: float = 22.0,
    ) -> Dict[str, Any]:
        """Run DeepSeek Flash / multimodal VLM analysis over images, video keyframes, or web text."""
        chosen_model = str(model_id or "auto/deepseek-v4.1-flash").strip()
        sys_msg = system_prompt or (
            "你是微信全生态多模态内容解析与智能派活助手。"
            "请结合视觉图像信息、Apple Vision OCR 文字与对话上下文，输出简洁、准确、结构化的中文分析结论。"
        )
        text_parts = [prompt.strip()]
        if ocr_context.strip():
            text_parts.append(f"\n【Apple Vision 2x OCR 提取文本】\n{ocr_context.strip()[:3500]}")
        combined_text = "\n".join(p for p in text_parts if p)

        encoded_images: List[Dict[str, Any]] = []
        for p in (image_paths or [])[:4]:
            enc = self._encode_image_data_url(Path(p))
            if enc:
                encoded_images.append(enc)

        if encoded_images:
            content_blocks: List[Dict[str, Any]] = [{"type": "text", "text": combined_text}]
            for enc in encoded_images:
                content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": enc["dataUrl"]},
                    }
                )
            vision_res = self.generate_chat_reply(
                [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": content_blocks},
                ],
                model_id=chosen_model,
                contact_name=contact_name,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            if vision_res.get("ok"):
                return {
                    **vision_res,
                    "usedMultimodalImage": True,
                    "attachedImageCount": len(encoded_images),
                    "attachedImages": [{"path": e["path"], "mime": e["mime"], "bytes": e["bytes"]} for e in encoded_images],
                    "usedTextFallbackOnVisionError": False,
                }
            # Upstream gateway/route might only support text on a chosen alias; retry with rich OCR + image metadata
            fallback_note = f"\n（注：图像直传未受理 [{vision_res.get('error', '')[:80]}]，请基于高精度 OCR 与上下文继续深入分析。）"
            text_res = self.generate_chat_reply(
                [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": combined_text + fallback_note},
                ],
                model_id=chosen_model,
                contact_name=contact_name,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            return {
                **text_res,
                "usedMultimodalImage": False,
                "attachedImageCount": len(encoded_images),
                "attachedImages": [{"path": e["path"], "mime": e["mime"], "bytes": e["bytes"]} for e in encoded_images],
                "usedTextFallbackOnVisionError": True,
                "visionAttemptError": vision_res.get("error", ""),
            }

        res = self.generate_chat_reply(
            [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": combined_text},
            ],
            model_id=chosen_model,
            contact_name=contact_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return {
            **res,
            "usedMultimodalImage": False,
            "attachedImageCount": 0,
            "attachedImages": [],
            "usedTextFallbackOnVisionError": False,
        }

    def probe_model(
        self,
        *,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        prompt: str = "请用不超过20个字回复：收到测试，状态正常。",
    ) -> Dict[str, Any]:
        """Run a real single-turn probe against a model via Magpie or custom provider."""
        target = model_id or str(self.state.get("activeModelId") or "auto/deepseek-v4-pro")
        pid, endpoint, api_key, wire_model = self._resolve_execution_target(target, provider_id=provider_id)
        started = time.perf_counter()
        try:
            status, data = self._request(
                "POST",
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                payload={
                    "model": wire_model,
                    "messages": [
                        {"role": "system", "content": "你是微信智能助手连通性探针，请简短直接作答。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 120,
                },
                timeout=12.0,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            choices = data.get("choices") if isinstance(data, dict) else None
            if status == 200 and isinstance(choices, list) and choices:
                content = _strip_thinking_tags((choices[0].get("message") or {}).get("content") or "")
                result = {
                    "ok": True,
                    "modelId": target,
                    "wireModel": wire_model,
                    "providerId": pid,
                    "endpoint": endpoint,
                    "statusCode": status,
                    "latencyMs": latency_ms,
                    "replyText": content or "OK",
                    "usage": data.get("usage") if isinstance(data, dict) else None,
                    "probedAt": _utc_now(),
                }
            else:
                result = {
                    "ok": False,
                    "modelId": target,
                    "providerId": pid,
                    "endpoint": endpoint,
                    "statusCode": status,
                    "latencyMs": latency_ms,
                    "error": str(data.get("error") if isinstance(data, dict) else data)[:200],
                    "probedAt": _utc_now(),
                }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            result = {
                "ok": False,
                "modelId": target,
                "providerId": pid,
                "endpoint": endpoint,
                "statusCode": 0,
                "latencyMs": latency_ms,
                "error": str(exc),
                "probedAt": _utc_now(),
            }

        self._recent_calls = [
            {
                "ok": result["ok"],
                "modelId": target,
                "providerId": pid,
                "latencyMs": result["latencyMs"],
                "preview": result.get("replyText", result.get("error", ""))[:60],
                "timestamp": result["probedAt"],
                "probe": True,
            }
        ] + self._recent_calls[:19]
        return result

    def get_summary(self, *, refresh: bool = False, provider_filter: Optional[str] = None) -> Dict[str, Any]:
        """Return secret-safe Magpie hub & multi-provider status for CLI, HTTP & Web UI."""
        snapshot = self.sync_models(force=refresh)
        models = snapshot["models"]
        if provider_filter and provider_filter not in ("all", "*"):
            models = [
                m
                for m in models
                if m.get("routeGroup") == provider_filter
                or m.get("ownedBy") == provider_filter
                or m.get("providerId") == provider_filter
            ]

        masked_providers = [
            self._mask_provider(p)
            for p in self.state.get("providers", {}).values()
        ]
        masked_providers.sort(key=lambda p: (0 if p["isGateway"] else 1, 0 if p["enabled"] else 1, p["id"]))

        return {
            "ok": True,
            "gatewayOnline": snapshot["gatewayOnline"],
            "gatewayUrl": snapshot["gatewayUrl"],
            "lastSyncAt": snapshot["lastSyncAt"],
            "syncError": snapshot["syncError"],
            "activeProviderId": self.state.get("activeProviderId", "magpie-gateway"),
            "activeModelId": self.state.get("activeModelId", "auto/deepseek-v4-pro"),
            "fallbackModelId": self.state.get("fallbackModelId", "auto/deepseek-v4.1-flash"),
            "llmReplyEnabled": bool(self.state.get("llmReplyEnabled", True)),
            "temperature": self.state.get("temperature", 0.4),
            "maxTokens": self.state.get("maxTokens", 240),
            "contactModelBindings": dict(self.state.get("contactModelBindings") or {}),
            "providerGroups": snapshot["providerGroups"],
            "providers": masked_providers,
            "profiles": list((self.state.get("profiles") or {}).values()),
            "totalModelCount": snapshot["modelCount"],
            "models": models,
            "recentCalls": self._recent_calls[:12],
            "provenance": {
                "adaptedFrom": ["@straydragon/dsh-x-magpie@0.7.2", "@harzva/dsh-magpie-openbot"],
                "vendorDir": str(self.plugin_root / "vendor" / "magpie"),
            },
        }
