"""Universal macOS App-Use RPA Engine & Meta-RPA Generalization Studio (v2.9.0).

Generalizes macOS AXUIElement + Apple Vision OCR + CGEvent automation beyond fixed
apps to ANY unseen installed or running macOS application (standard apps AND AI Agent
Apps), providing semantic grounding, topology archetype inference, UI state graphing,
failure-taxonomy self-healing, dual-channel headless AX + anti-ban guarded HID
multi-window concurrency, and portable Skill compilation.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple

from .app_use_meta_algo import (
    AntiRiskPacer,
    AppUIStateGraph,
    ConcurrencyLaneTracker,
    ForegroundHIDLease,
    SemanticElementGrounder,
    classify_app_risk_tier,
    classify_step_failure,
    compute_ui_state,
    detect_modal_blocker,
    diff_ui_states,
    infer_app_archetype,
    optimize_and_enrich_steps,
    score_workflow_readiness,
    step_action_signature,
)
from .io_utils import atomic_write_json

if TYPE_CHECKING:
    from .engine import WeChatControlEngine


SUPPORTED_STEP_ACTIONS = (
    "activate_app",
    "inspect_ui",
    "click_element",
    "focus_and_type",
    "press_shortcut",
    "scroll",
    "wait_and_read",
    "pause_for_human",
)

AGENT_APP_HINTS: Tuple[str, ...] = (
    "chatgpt",
    "openai",
    "doubao",
    "gemini",
    "bot studio",
    "botstudio",
    "openbot",
    "opencode",
    "cursor",
    "claude",
    "grok",
    "zcode",
    "antigravity",
    "windsurf",
    "trae",
    "perplexity",
    "poe",
    "lmstudio",
    "lm studio",
    "jan",
    "cherry studio",
    "chatbox",
    "yuanbao",
    "kimi",
    "deepseek",
    "copilot",
    "qwen",
    "codex",
    "pi agent",
    "pi-agent",
    "workbuddy",
)

IM_SOCIAL_HINTS: Tuple[str, ...] = (
    "wechat",
    "weixin",
    "微信",
    "wework",
    "wecom",
    "企业微信",
    "feishu",
    "lark",
    "飞书",
    "dingtalk",
    "钉钉",
    "xiaohongshu",
    "小红书",
    "douyin",
    "抖音",
    "slack",
    "discord",
    "telegram",
    "qq",
    "tencent meeting",
    "腾讯会议",
)

DEV_TOOL_HINTS: Tuple[str, ...] = (
    "xcode",
    "vscode",
    "visual studio code",
    "terminal",
    "iterm",
    "warp",
    "postman",
    "docker",
    "jetbrains",
    "pycharm",
    "android studio",
    "wechatwebdevtools",
)

BROWSER_HINTS: Tuple[str, ...] = (
    "safari",
    "google chrome",
    "chrome",
    "firefox",
    "arc",
    "microsoft edge",
    "brave",
    "ego lite",
    "egolite",
    "chromium",
)

CATEGORY_LABELS: Dict[str, str] = {
    "agent_app": "AI Agent 应用",
    "im_social": "即时通讯与私域",
    "productivity": "办公 / 系统应用",
    "dev_tool": "开发与工程工具",
    "browser": "浏览器与 Web 载体",
}

SELF_OR_HOST_HINTS: Tuple[str, ...] = (
    "bot studio",
    "botstudio",
    "wechat bot",
    "wechat-studio",
    "harvis",
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(value: str, default: str = "app") -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "")).strip("_").lower()
    return raw[:36] or default


def _sandisk_artifact_dir(engine: "WeChatControlEngine", subdir: str) -> Path:
    sandisk_root = Path("/Volumes/SanDisk")
    if sandisk_root.is_dir():
        target = sandisk_root / "Builds" / "WeChatBot" / subdir
    else:
        target = engine.inspector.snapshots_dir / subdir
    target.mkdir(parents=True, exist_ok=True)
    return target


def classify_mac_app(bundle_id: str, name: str, app_path: str = "") -> Dict[str, Any]:
    """Classify a macOS app into standard vs AI Agent App categories with safety notes."""
    haystack = f"{bundle_id} {name} {app_path}".casefold()
    is_agent = any(tok in haystack for tok in AGENT_APP_HINTS)
    self_or_host = any(tok in haystack for tok in SELF_OR_HOST_HINTS)

    if is_agent:
        category = "agent_app"
    elif any(tok in haystack for tok in IM_SOCIAL_HINTS):
        category = "im_social"
    elif any(tok in haystack for tok in BROWSER_HINTS):
        category = "browser"
    elif any(tok in haystack for tok in DEV_TOOL_HINTS):
        category = "dev_tool"
    else:
        category = "productivity"

    safety_note = ""
    if self_or_host:
        safety_note = "当前控制宿主或同机协同应用：建议仅做界面探测与 Dry-Run 建模，避免脚本误关闭宿主进程。"
    elif is_agent:
        safety_note = "Agent 应用：内置支持定位输入栏 -> 粘贴提示词 -> 回车发送 -> 等待流式输出稳定读取全流程。"
    elif category == "im_social":
        safety_note = "社交/IM 应用：对外发消息动作建议默认保留 Dry-Run 或人类确认门禁。"

    return {
        "category": category,
        "categoryLabel": CATEGORY_LABELS.get(category, "通用桌面应用"),
        "isAgentApp": is_agent,
        "selfOrHost": self_or_host,
        "safetyNote": safety_note,
    }


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract the first valid JSON object from raw LLM/CLI text."""
    text = str(raw_text or "").strip()
    if not text:
        return None
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates = list(fenced) + [text]
    for cand in candidates:
        s = cand.strip()
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(s[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
    return None


def _substitute_params(value: Any, params: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        def _repl(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            if key in params and params[key] is not None:
                return str(params[key])
            return match.group(0)

        return re.sub(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}", _repl, value)
    if isinstance(value, list):
        return [_substitute_params(v, params) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_params(v, params) for k, v in value.items()}
    return value


_BIDI_MARKS_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def _clean_ui_text(value: Any) -> str:
    """Strip macOS RTL/LTR directional marks (e.g. Calculator LRM '\\u200e') and trim."""
    return _BIDI_MARKS_RE.sub("", str(value or "")).strip()


def _extract_captured_value(
    inspect_res: Dict[str, Any],
    *,
    mode: str = "auto",
    pattern: str = "",
    baseline_ocr_lines: Optional[List[str]] = None,
) -> str:
    """Extract structured runtime variable from inspect/wait_and_read AX + OCR output."""
    eff_mode = (mode or "auto").strip().lower()
    ax_texts = [_clean_ui_text(x) for x in (inspect_res.get("axTexts") or []) if _clean_ui_text(x)]
    ocr_raw = _clean_ui_text(inspect_res.get("ocrPreview") or "")
    ocr_lines = [_clean_ui_text(ln) for ln in ocr_raw.splitlines() if _clean_ui_text(ln)]
    combined = "\n".join(ax_texts + ocr_lines) if (ax_texts or ocr_lines) else ocr_raw

    if eff_mode == "ax_last" and ax_texts:
        return ax_texts[-1]
    if eff_mode == "ax_all" and ax_texts:
        return "\n".join(ax_texts)
    if eff_mode == "ocr_diff":
        base_set = set(_clean_ui_text(x) for x in (baseline_ocr_lines or []) if _clean_ui_text(x))
        diff = [ln for ln in ocr_lines if ln not in base_set]
        if diff:
            return "\n".join(diff)
        return "\n".join(ocr_lines)
    if eff_mode == "regex" and pattern:
        m = re.search(pattern, combined, flags=re.MULTILINE)
        if m:
            return _clean_ui_text(m.group(1) if m.groups() else m.group(0))
        return ""
    if eff_mode == "full":
        return ocr_raw or "\n".join(ax_texts)
    # "auto": prefer diff OCR if long baseline exists, else last AX value, else OCR preview
    if baseline_ocr_lines and ocr_lines:
        base_set = set(_clean_ui_text(x) for x in baseline_ocr_lines if _clean_ui_text(x))
        diff = [ln for ln in ocr_lines if ln not in base_set]
        if diff:
            return "\n".join(diff)
    if ax_texts:
        return ax_texts[-1]
    return ocr_raw


class AppUseStudio:
    """Universal macOS App-Use Inspector, Any-Agent SOP/Workflow Builder & Safe Runner."""

    def __init__(
        self,
        engine: "WeChatControlEngine",
        *,
        store_path: Optional[Path] = None,
        cli_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ) -> None:
        self.engine = engine
        self.store_path = (
            Path(store_path)
            if store_path
            else (self.engine.auth_gate.auth_file.parent / "app_use_workflows.json")
        )
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.pipelines_path = self.store_path.parent / "app_use_pipelines.json"
        self.runs_log_path = self.store_path.parent / "app_use_runs.jsonl"
        self.state_graph = AppUIStateGraph(self.store_path.parent / "app_use_state_graphs.json")
        self._hid_lease = ForegroundHIDLease()
        self._risk_pacer = AntiRiskPacer()
        self._lanes = ConcurrencyLaneTracker()
        self._cli_runner = cli_runner or subprocess.run
        self._state: Dict[str, Any] = self._load_store()
        self._pipelines_state: Dict[str, Any] = self._load_pipelines()
        self._rec_lock = threading.RLock()
        self._rec_active = False
        self._rec_thread: Optional[threading.Thread] = None
        self._rec_stop_event = threading.Event()
        self._rec_events: List[Dict[str, Any]] = []
        self._rec_started_at: str = ""
        self._rec_started_mono: float = 0.0
        self._rec_session_id: str = ""

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_store(self) -> Dict[str, Any]:
        if self.store_path.is_file():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("workflows"), dict):
                    return data
            except Exception:
                pass
        return {"schema": "openbot.app-use-workflows/1", "workflows": {}, "order": []}

    def _save_store(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.store_path, self._state)

    def _load_pipelines(self) -> Dict[str, Any]:
        if self.pipelines_path.is_file():
            try:
                data = json.loads(self.pipelines_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("pipelines"), dict):
                    return data
            except Exception:
                pass
        return {"schema": "openbot.app-use-pipelines/1", "pipelines": {}, "order": []}

    def _save_pipelines(self) -> None:
        self.pipelines_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.pipelines_path, self._pipelines_state)

    def _append_run_log(self, record: Dict[str, Any]) -> None:
        try:
            self.runs_log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {"ts": _utc_iso_now(), **record}
            with self.runs_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def list_runs(self, *, limit: int = 30) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        if self.runs_log_path.is_file():
            try:
                lines = [ln.strip() for ln in self.runs_log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                for ln in reversed(lines[-max(1, min(100, int(limit))):]):
                    try:
                        obj = json.loads(ln)
                        if isinstance(obj, dict):
                            items.append(obj)
                    except Exception:
                        continue
            except Exception:
                pass
        return {"ok": True, "count": len(items), "runs": items, "logPath": str(self.runs_log_path)}

    # ------------------------------------------------------------------
    # Discovery: macOS Apps & Any-Agent Backends
    # ------------------------------------------------------------------

    def list_apps(
        self,
        *,
        include_installed: bool = True,
        category: str = "all",
        running_only: bool = False,
    ) -> Dict[str, Any]:
        """List running and installed macOS apps across System, Applications, User, and SanDisk."""
        args = ["list-mac-apps"]
        if running_only or not include_installed:
            args.append("--running-only")
        raw = self.engine._run_native(args, timeout=12.0)
        if not raw.get("ok"):
            return {
                "ok": False,
                "error": raw.get("error") or "list-mac-apps failed",
                "error_code": raw.get("error_code", "list_apps_failed"),
                "apps": [],
            }

        cat_filter = (category or "all").strip().lower()
        enriched: List[Dict[str, Any]] = []
        counts: Dict[str, int] = {
            "total": 0,
            "running": 0,
            "agent_app": 0,
            "productivity": 0,
            "im_social": 0,
            "dev_tool": 0,
            "browser": 0,
        }

        for entry in raw.get("apps") or []:
            if not isinstance(entry, dict):
                continue
            bid = str(entry.get("bundleID") or "")
            name = str(entry.get("name") or "")
            app_path = str(entry.get("appPath") or "")
            cls = classify_mac_app(bid, name, app_path)
            risk_profile = classify_app_risk_tier(bid, name, app_path, category=str(cls.get("category") or ""))
            item = {**entry, **cls, "riskProfile": risk_profile}
            counts["total"] += 1
            if item.get("running"):
                counts["running"] += 1
            counts[cls["category"]] = counts.get(cls["category"], 0) + 1

            if running_only and not item.get("running"):
                continue
            if cat_filter not in ("all", "*", "") and cls["category"] != cat_filter:
                if not (cat_filter == "agent" and cls["isAgentApp"]):
                    continue
            enriched.append(item)

        return {
            "ok": True,
            "frontmostBundleID": raw.get("frontmostBundleID", ""),
            "frontmostName": raw.get("frontmostName", ""),
            "counts": counts,
            "totalCount": len(enriched),
            "apps": enriched,
        }

    def _find_cli_binary(self, binary_name: str) -> Optional[str]:
        search_dirs = [
            "/Users/mac/.local/bin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            os.environ.get("PATH", ""),
        ]
        joined_path = ":".join(d for d in search_dirs if d)
        return shutil.which(binary_name, path=joined_path)

    def list_builder_agents(self, *, refresh_models: bool = False) -> Dict[str, Any]:
        """List all selectable Agents/LLMs: Magpie models, custom providers, local CLIs, heuristic."""
        summary = self.engine.models.get_summary(refresh=refresh_models)
        gateway_online = bool(summary.get("gatewayOnline"))
        active_model = str(summary.get("activeModelId") or "auto/deepseek-v4.1-flash")

        agents: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _add_agent(entry: Dict[str, Any]) -> None:
            aid = str(entry.get("id") or "")
            if not aid or aid in seen_ids:
                return
            seen_ids.add(aid)
            agents.append(entry)

        # 1. Magpie gateway & configured provider models
        raw_models = list(summary.get("models") or [])
        priority_ids = [
            "group/omini-balanced",
            "group/smart-split",
            "group/omini-strong",
            "group/omini-vision",
            "auto/deepseek-v4.1-flash",
            "auto/deepseek-v4-pro",
            "auto/glm-5.3",
            "auto/glm-5.3-flash",
            "opencode-go/kimi-k2.5",
            "mistral/mistral-large-4",
            active_model,
        ]
        ordered_models = sorted(
            raw_models,
            key=lambda m: (
                0 if str(m.get("id")) in priority_ids else 1,
                priority_ids.index(str(m.get("id"))) if str(m.get("id")) in priority_ids else 999,
                0 if m.get("recommended") else 1,
                str(m.get("id") or ""),
            ),
        )
        for m in ordered_models[:24]:
            mid = str(m.get("id") or "").strip()
            if not mid:
                continue
            disp = str(m.get("displayName") or m.get("name") or mid)
            pid = str(m.get("providerId") or "magpie-gateway")
            vision = bool(m.get("vision") or "image" in (m.get("input") or []))
            _add_agent(
                {
                    "id": f"magpie:{mid}",
                    "kind": "magpie_model",
                    "modelId": mid,
                    "providerId": pid,
                    "label": f"{disp} [{pid}]",
                    "description": str(m.get("magpieLabel") or disp),
                    "vision": vision,
                    "available": gateway_online or pid != "magpie-gateway",
                    "recommended": bool(m.get("recommended") or mid == active_model),
                }
            )

        # 2. Local Headless CLI Agents
        cli_specs = [
            ("gemini-api", "Gemini Developer CLI (gemini-api)", "使用 Google Gemini API / Developer credits 无头生成结构化 SOP"),
            ("codex", "Codex CLI Agent (codex exec)", "调用本机 Codex 只读模式编排复杂系统级 App-Use 工作流"),
            ("claude", "Claude Code CLI Agent (claude -p)", "调用本机 Claude 无头输出高质量 SOP 文档与步骤"),
            ("opencode", "OpenCode CLI Agent (opencode run)", "使用 OpenCode 已配置订阅无头规划操作流程"),
            ("omini", "Omini Multi-Model Advisor (omini ask)", "经本机 Omini 路由多模型复核并生成 SOP 方案"),
        ]
        cli_list: List[Dict[str, Any]] = []
        for bin_name, title, desc in cli_specs:
            resolved = self._find_cli_binary(bin_name)
            cli_entry = {
                "id": f"cli:{bin_name}",
                "kind": "cli_agent",
                "binaryName": bin_name,
                "binaryPath": resolved or "",
                "label": title,
                "description": desc,
                "vision": False,
                "available": bool(resolved),
                "recommended": False,
            }
            _add_agent(cli_entry)
            cli_list.append(cli_entry)

        # 3. Deterministic offline fallback planner
        _add_agent(
            {
                "id": "local:heuristic",
                "kind": "local_heuristic",
                "label": "本地 AX+OCR 规则规划引擎 (零 Token 离线秒级生成)",
                "description": "无需外网或额度，直接基于实时 AX 控件树、Vision OCR 坐标与应用特征模板自动编排 SOP 与工作流。",
                "vision": False,
                "available": True,
                "recommended": not gateway_online,
            }
        )

        if gateway_online and "magpie:group/omini-balanced" in seen_ids:
            default_agent_id = "magpie:group/omini-balanced"
        elif gateway_online and f"magpie:{active_model}" in seen_ids:
            default_agent_id = f"magpie:{active_model}"
        else:
            default_agent_id = next(
                (a["id"] for a in agents if a.get("available") and a["kind"] == "magpie_model"),
                "local:heuristic",
            )

        return {
            "ok": True,
            "gatewayOnline": gateway_online,
            "activeModelId": active_model,
            "defaultAgentId": default_agent_id,
            "totalCount": len(agents),
            "agents": agents,
            "cliAgents": cli_list,
        }

    # ------------------------------------------------------------------
    # Target App Resolution & Deep UI Inspection
    # ------------------------------------------------------------------

    def _resolve_target_meta(
        self,
        *,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
    ) -> Dict[str, Any]:
        bid = str(bundle_id or "").strip()
        name = str(app_name or "").strip()
        path = str(app_path or "").strip()

        catalog = self.list_apps(include_installed=True)
        matched: Optional[Dict[str, Any]] = None
        if catalog.get("ok"):
            apps = catalog.get("apps") or []
            if bid:
                matched = next((a for a in apps if str(a.get("bundleID") or "").casefold() == bid.casefold()), None)
            if not matched and path:
                matched = next((a for a in apps if str(a.get("appPath") or "") == path), None)
            if not matched and name:
                low = name.casefold()
                matched = next((a for a in apps if str(a.get("name") or "").casefold() == low), None)
                if not matched:
                    matched = next((a for a in apps if low in str(a.get("name") or "").casefold()), None)

        if matched:
            return matched

        resolved_name = name or (Path(path).stem if path else "") or bid or "Target App"
        cls = classify_mac_app(bid, resolved_name, path)
        return {
            "bundleID": bid,
            "name": resolved_name,
            "appPath": path,
            "running": False,
            "windowCount": 0,
            **cls,
        }

    def inspect_app(
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
        """Inspect ANY macOS app window via AXUIElement + Apple Vision OCR + SanDisk screenshot."""
        bid = str(bundle_id or "").strip()
        name = str(app_name or "").strip()
        path = str(app_path or "").strip()
        if not (bid or name or path):
            return {
                "ok": False,
                "error_code": "missing_target_app",
                "error": "请先选择目标应用（bundle_id / app_name / app_path 至少填一项）。",
            }

        verify_dir = _sandisk_artifact_dir(self.engine, "app-use-verify")
        slug = _slugify(name or bid or Path(path).stem, "app")
        out_png = verify_dir / f"{slug}_inspect_{int(time.time())}.png"

        args = [
            "app-use-inspect",
            "--out",
            str(out_png),
            "--max-nodes",
            str(max(50, min(800, int(max_nodes)))),
        ]
        if bid:
            args.extend(["--bundle-id", bid])
        if name:
            args.extend(["--app-name", name])
        if path:
            args.extend(["--app-path", path])
        if window_id:
            args.extend(["--window-id", str(int(window_id))])
        if window_title:
            args.extend(["--window-title", str(window_title)])
        if launch_if_needed:
            args.append("--launch")
        if not allow_activate:
            args.append("--no-activate")

        res = self.engine._run_native(args, timeout=22.0)
        if not res.get("ok"):
            meta = self._resolve_target_meta(bundle_id=bid, app_name=name, app_path=path)
            return {
                **res,
                "targetApp": meta,
            }

        resolved_bid = str(res.get("bundleID") or bid)
        resolved_name = str(res.get("name") or name)
        resolved_path = str(res.get("appPath") or path)
        cls = classify_mac_app(resolved_bid, resolved_name, resolved_path)
        risk_profile = classify_app_risk_tier(
            resolved_bid,
            resolved_name,
            resolved_path,
            category=str(cls.get("category") or ""),
        )
        target_meta_dict = {
            "bundleID": resolved_bid,
            "name": resolved_name,
            "appPath": resolved_path,
            "pid": res.get("pid"),
            **cls,
            "riskProfile": risk_profile,
        }

        ax_controls = res.get("axControls") or []
        ocr_elements = res.get("ocrElements") or []
        input_els = res.get("inputElements") or []
        button_els = res.get("buttonElements") or []

        ui_state = compute_ui_state(res, bundle_id=resolved_bid)
        archetype = infer_app_archetype(res, target_meta=target_meta_dict)
        modal_status = ui_state.get("modalStatus") or {"kind": "none", "requiresHuman": False, "signals": []}
        try:
            self.state_graph.record_observation(
                resolved_bid,
                resolved_name,
                ui_state,
                archetype_id=str(archetype.get("id") or ""),
            )
        except Exception:
            pass

        ui_summary = {
            "windowTitle": ((res.get("window") or {}).get("title") if isinstance(res.get("window"), dict) else "") or "",
            "windowBounds": ((res.get("window") or {}).get("bounds") if isinstance(res.get("window"), dict) else {}) or {},
            "axControlCount": int(res.get("axControlCount") or len(ax_controls)),
            "inputCount": len(input_els),
            "buttonCount": len(button_els),
            "ocrCount": int(res.get("ocrCount") or len(ocr_elements)),
            "archetype": archetype,
            "uiState": ui_state,
            "modalStatus": modal_status,
            "sampleInputs": [
                {
                    "role": e.get("role"),
                    "identifier": e.get("identifier"),
                    "title": e.get("title") or e.get("description"),
                    "relCenter": e.get("relCenter"),
                    "center": e.get("center"),
                }
                for e in input_els[:6]
            ],
            "sampleButtons": [
                {
                    "title": e.get("title") or e.get("description") or e.get("identifier"),
                    "identifier": e.get("identifier"),
                    "relCenter": e.get("relCenter"),
                }
                for e in button_els[:18]
                if e.get("title") or e.get("description") or e.get("identifier")
            ],
            "sampleOCR": [
                {
                    "text": e.get("text"),
                    "relCenter": e.get("relCenter"),
                    "screenCenter": e.get("screenCenter"),
                }
                for e in ocr_elements[:28]
            ],
            "axTexts": list(res.get("axTexts") or [])[:25],
        }

        return {
            **res,
            **cls,
            "targetApp": target_meta_dict,
            "riskProfile": risk_profile,
            "uiState": ui_state,
            "archetype": archetype,
            "modalStatus": modal_status,
            "uiSummary": ui_summary,
        }

    # ------------------------------------------------------------------
    # Any-Agent SOP + RPA Workflow Synthesis
    # ------------------------------------------------------------------

    def _build_agent_prompt(
        self,
        *,
        target_meta: Dict[str, Any],
        goal: str,
        inspection: Optional[Dict[str, Any]],
        custom_agent_prompt: str = "",
        parameters_hint: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, str]:
        sys_prompt = (
            "你是资深 macOS App-Use RPA 自动化与 SOP 架构师。"
            "请根据目标桌面应用元数据、实时 AXUIElement 控件树与 Apple Vision OCR 快照，以及用户的业务目标，"
            "严格输出一个合法 JSON 对象（不要包裹额外废话），同时包含可执行的 RPA workflow 与人类可读的中文 SOP。\n\n"
            "允许使用的 steps[*].action 枚举：\n"
            "1. activate_app: 激活或拉起目标应用（参数 launchIfNeeded: bool）\n"
            "2. inspect_ui: 重新采集窗口 AX + Vision OCR 状态（参数 saveScreenshot: bool）\n"
            "3. click_element: 按控件定位点击（参数 targetAxTitle/targetAxId/matchText/relX/relY/doubleClick）\n"
            "4. focus_and_type: 聚焦输入框并安全粘贴文本（参数 text 支持 {{变量}}，targetAxTitle/targetAxId/relX/relY, clearFirst: bool, submitAfter: bool, submitKey: 'return'）\n"
            "5. press_shortcut: 发送键盘快捷键或按键序列（参数 combo 如 'cmd+n'/'escape'/'return'，或 sequence 如 '1,2,5,*,8,return'，delayMs）\n"
            "6. scroll: 在窗口内滚轮滚动（参数 relX, relY, dy 负数为向下）\n"
            "7. wait_and_read: 等待后读取窗口最新结果（参数 delaySec, waitUntilStable: bool 对 Agent 流式回答非常关键, pollIntervalSec, maxWaitSec, expectText）\n"
            "8. pause_for_human: 敏感/确认/扫码人工接管停顿（参数 message）\n\n"
            "输出 JSON Schema：\n"
            "{\n"
            '  "name": "简短流程名称",\n'
            '  "summary": "一句话说明流程目标与收益",\n'
            '  "parameters": [{"name": "prompt", "label": "输入参数标签", "defaultValue": "默认测试值", "required": true, "description": "说明"}],\n'
            '  "preconditions": ["前置条件1", "前置条件2"],\n'
            '  "safetyGates": ["安全门禁说明"],\n'
            '  "steps": [\n'
            '    {"step": 1, "action": "activate_app", "title": "步骤标题", "description": "一句话说明", "launchIfNeeded": true}\n'
            '  ],\n'
            '  "verification": "验收标准（读取哪个控件或 OCR 关键词）"\n'
            "}\n"
            "注意：JSON 务必完整闭合且精炼（<=900字），sopMarkdown 可省略或仅写核心要点（系统会自动依据以上结构化字段渲染完整中文 SOP）。"
        )
        if custom_agent_prompt.strip():
            sys_prompt += f"\n\n【用户补充构建 Agent 角色指令】\n{custom_agent_prompt.strip()}"

        profile_payload: Dict[str, Any] = {
            "targetApp": {
                "bundleID": target_meta.get("bundleID"),
                "name": target_meta.get("name"),
                "category": target_meta.get("category"),
                "isAgentApp": bool(target_meta.get("isAgentApp")),
                "running": bool(target_meta.get("running")),
            },
            "goal": goal,
        }
        if parameters_hint:
            profile_payload["parametersHint"] = parameters_hint
        if inspection and inspection.get("ok"):
            raw_sum = dict(inspection.get("uiSummary") or {})
            raw_sum["sampleOCR"] = (raw_sum.get("sampleOCR") or [])[:16]
            raw_sum["sampleButtons"] = (raw_sum.get("sampleButtons") or [])[:14]
            profile_payload["liveUIProfile"] = raw_sum
            profile_payload["liveUIProfile"]["axControlsPreview"] = [
                {
                    k: c.get(k)
                    for k in ("role", "identifier", "title", "description", "value", "relCenter")
                    if c.get(k) not in (None, "", {})
                }
                for c in (inspection.get("axControls") or [])[:16]
            ]
        else:
            profile_payload["liveUIProfile"] = {
                "note": "目标应用当前未激活或未提供实时窗口快照，请先安排 activate_app(launchIfNeeded=true) + inspect_ui，或结合常见 macOS 快捷键与控件标题生成通用自愈步骤。"
            }

        user_prompt = (
            f"请为目标应用「{target_meta.get('name')} ({target_meta.get('bundleID') or 'N/A'})」"
            f"设计完整的 SOP 与可执行 RPA 工作流。\n"
            f"业务需求：{goal}\n\n"
            f"应用与界面上下文 JSON：\n{json.dumps(profile_payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        return sys_prompt, user_prompt

    def _build_heuristic_plan(
        self,
        *,
        target_meta: Dict[str, Any],
        goal: str,
        inspection: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Deterministic offline planner covering Agent Apps, Calculator, Editors, and generic macOS apps."""
        bid = str(target_meta.get("bundleID") or "")
        name = str(target_meta.get("name") or "Target App")
        is_agent = bool(target_meta.get("isAgentApp"))
        low_blob = f"{bid} {name} {goal}".casefold()

        params: List[Dict[str, Any]] = []
        steps: List[Dict[str, Any]] = [
            {
                "step": 1,
                "action": "activate_app",
                "title": f"唤醒并前置 {name}",
                "description": f"确保 {name} 已启动并置于屏幕最前端。",
                "launchIfNeeded": True,
            },
            {
                "step": 2,
                "action": "inspect_ui",
                "title": "扫描当前界面 AX 与 OCR 状态",
                "description": "获取最新窗口坐标、控件树及初始文字状态。",
                "saveScreenshot": True,
            },
        ]

        if "calculator" in low_blob or "计算器" in low_blob:
            params.append(
                {
                    "name": "expression",
                    "label": "计算按键序列",
                    "defaultValue": "1,2,5,*,8,return",
                    "required": True,
                    "description": "逗号分隔的按键序列，如 1,2,5,*,8,return。",
                }
            )
            steps.extend(
                [
                    {
                        "step": 3,
                        "action": "press_shortcut",
                        "title": "清空计算器当前显示",
                        "description": "发送 Escape 键清空计算器缓冲区，避免历史残留影响结果。",
                        "combo": "escape",
                        "delayMs": 90,
                    },
                    {
                        "step": 4,
                        "action": "press_shortcut",
                        "title": "输入计算表达式并求值",
                        "description": "按顺序发送按键序列 {{expression}} 并以回车计算结果。",
                        "sequence": "{{expression}}",
                        "delayMs": 85,
                    },
                    {
                        "step": 5,
                        "action": "wait_and_read",
                        "title": "回读计算结果并截图存证",
                        "description": "等待界面刷新并通过 AX 静态文本与 Apple Vision OCR 回读显示数值。",
                        "delaySec": 0.4,
                        "waitUntilStable": False,
                        "saveScreenshot": True,
                    },
                ]
            )
            verification = "读取计算器显示屏 AXStaticText / Vision OCR 文本，确认包含预期计算结果。"
        elif is_agent:
            params.append(
                {
                    "name": "prompt",
                    "label": "发送给 Agent App 的指令 / 提示词",
                    "defaultValue": "请用三点简述如何做好企业私有化 AI 落地，总字数不超过80字。",
                    "required": True,
                    "description": "将粘贴到目标 Agent 应用对话框中的提示词。",
                }
            )
            steps.extend(
                [
                    {
                        "step": 3,
                        "action": "focus_and_type",
                        "title": f"聚焦 {name} 输入框并提交任务提示词",
                        "description": f"自动查找 {name} 对话输入框，粘贴 {{{{prompt}}}}，核对回读后发送。",
                        "text": "{{prompt}}",
                        "relX": 0.5,
                        "relY": 0.88,
                        "clearFirst": True,
                        "submitAfter": True,
                        "submitKey": "return",
                    },
                    {
                        "step": 4,
                        "action": "wait_and_read",
                        "title": f"等待 {name} 流式回答输出稳定并采集结果",
                        "description": "持续轮询窗口 OCR 与 AX 文本直至流式生成收敛，完整保存回复截屏与文字结果。",
                        "delaySec": 2.0,
                        "waitUntilStable": True,
                        "pollIntervalSec": 1.5,
                        "maxWaitSec": 16.0,
                        "saveScreenshot": True,
                    },
                ]
            )
            verification = f"等待 {name} 输出内容连续两次采样一致且 OCR / AX 可读出非空回答。"
        elif "textedit" in low_blob or "文本编辑" in low_blob or "notes" in low_blob or "备忘录" in low_blob:
            params.append(
                {
                    "name": "content",
                    "label": "写入文档的内容",
                    "defaultValue": f"[{name} SOP 自动验证] 执行目标：{goal[:40]}",
                    "required": True,
                    "description": "粘贴写入目标文档的正文内容。",
                }
            )
            steps.extend(
                [
                    {
                        "step": 3,
                        "action": "press_shortcut",
                        "title": "新建空白文档/编辑区 (Cmd+N)",
                        "description": "发送 Cmd+N 打开全新空白文档，避免覆盖用户原有文稿。",
                        "combo": "cmd+n",
                        "delayMs": 120,
                    },
                    {
                        "step": 4,
                        "action": "focus_and_type",
                        "title": "写入结构化内容并校验回读",
                        "description": "聚焦编辑正文区，粘贴 {{content}} 并通过 AX/OCR 校验回读一致。",
                        "text": "{{content}}",
                        "relX": 0.5,
                        "relY": 0.5,
                        "clearFirst": True,
                        "submitAfter": False,
                    },
                    {
                        "step": 5,
                        "action": "wait_and_read",
                        "title": "读取最终文稿画面并留证",
                        "description": "截图并通过 AX + Vision OCR 确认写入内容完整呈现在文档中。",
                        "delaySec": 0.4,
                        "waitUntilStable": False,
                        "expectText": "{{content}}",
                        "saveScreenshot": True,
                    },
                ]
            )
            verification = "AX 正文值或 Vision OCR 文本包含 {{content}}。"
        else:
            params.append(
                {
                    "name": "inputText",
                    "label": "可选输入文本",
                    "defaultValue": goal[:60],
                    "required": False,
                    "description": "用于填入目标应用焦点输入区域的文本参数。",
                }
            )
            # Pick first visible button if goal matches any live control
            matched_btn = None
            if inspection and inspection.get("ok"):
                for btn in inspection.get("buttonElements") or []:
                    bt = str(btn.get("title") or btn.get("description") or "").strip()
                    if bt and bt.casefold() in goal.casefold():
                        matched_btn = btn
                        break
            if matched_btn:
                b_title = str(matched_btn.get("title") or matched_btn.get("description") or "")
                steps.append(
                    {
                        "step": len(steps) + 1,
                        "action": "click_element",
                        "title": f"点击目标控件「{b_title}」",
                        "description": f"定位并点击界面控件「{b_title}」。",
                        "targetAxTitle": b_title,
                        "targetAxId": str(matched_btn.get("identifier") or ""),
                    }
                )
            elif inspection and (inspection.get("inputElements") or []):
                inp = (inspection.get("inputElements") or [])[0]
                steps.append(
                    {
                        "step": len(steps) + 1,
                        "action": "focus_and_type",
                        "title": "聚焦主输入区并填报内容",
                        "description": "定位窗口内主输入控件，安全粘贴 {{inputText}} 并校验回读。",
                        "text": "{{inputText}}",
                        "targetAxId": str(inp.get("identifier") or ""),
                        "clearFirst": False,
                        "submitAfter": False,
                    }
                )
            else:
                steps.append(
                    {
                        "step": len(steps) + 1,
                        "action": "pause_for_human",
                        "title": "确认交互焦点位置（人工确认点）",
                        "description": "请确认目标窗口处于就绪页面后继续执行后续步骤。",
                        "message": f"请确认 {name} 当前窗口页面正确后再继续。",
                    }
                )
            steps.append(
                {
                    "step": len(steps) + 1,
                    "action": "wait_and_read",
                    "title": "采集执行后窗口 AX + OCR 状态",
                    "description": "等待页面稳定并输出完整截图与 OCR 回读报告。",
                    "delaySec": 0.6,
                    "waitUntilStable": False,
                    "saveScreenshot": True,
                }
            )
            verification = f"执行后 {name} 窗口截屏与 Vision OCR 无报错弹窗，目标元素状态更新。"

        return {
            "name": f"{name} · {goal[:28]}",
            "summary": f"针对「{name}」自动生成的标准操作流程与可回放 RPA 工作流：{goal}",
            "parameters": params,
            "preconditions": [
                f"本机已安装或可拉起 {name} ({bid or 'macOS App'})",
                "已授予辅助功能 (Accessibility)、屏幕录制 (Screen Recording) 与键鼠注入权限",
            ],
            "safetyGates": [
                "默认先执行 Dry-Run 校验控件可达性，实机执行须显式确认且受防抢鼠标守卫 (HumanActivityGuard) 保护",
            ],
            "steps": steps,
            "verification": verification,
        }

    def _invoke_magpie_agent(
        self,
        *,
        model_id: str,
        provider_id: Optional[str],
        sys_prompt: str,
        user_prompt: str,
        inspection: Optional[Dict[str, Any]],
        attach_screenshot: bool,
    ) -> Dict[str, Any]:
        shot_path = None
        if attach_screenshot and inspection and inspection.get("savedPath"):
            cand = Path(str(inspection["savedPath"]))
            if cand.is_file():
                shot_path = cand

        if shot_path is not None:
            ocr_ctx = str(inspection.get("ocrPreview") or "")[:2400] if inspection else ""
            res = self.engine.models.analyze_multimodal(
                prompt=user_prompt,
                system_prompt=sys_prompt,
                image_paths=[shot_path],
                ocr_context=ocr_ctx,
                model_id=model_id,
                max_tokens=2200,
                temperature=0.2,
                timeout=35.0,
            )
        else:
            res = self.engine.models.generate_chat_reply(
                [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model_id=model_id,
                provider_id=provider_id,
                max_tokens=3200,
                temperature=0.2,
                timeout=55.0,
            )
        return res

    def _invoke_cli_agent(
        self,
        *,
        bin_name: str,
        sys_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        bin_path = self._find_cli_binary(bin_name)
        if not bin_path:
            return {"ok": False, "error": f"CLI agent binary not found: {bin_name}"}

        combined_prompt = (
            f"{sys_prompt}\n\n"
            f"注意：你处于只读规划模式，严禁修改任何文件，请直接输出一个合法 JSON 对象。\n\n"
            f"{user_prompt}"
        )
        env = dict(os.environ)
        env["HOME"] = "/Users/mac"
        env["PATH"] = f"/Users/mac/.local/bin:/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '')}"

        if bin_name == "claude":
            cmd = [bin_path, "-p", combined_prompt, "--output-format", "text"]
            stdin_text = None
        elif bin_name == "codex":
            cmd = [bin_path, "exec", "--sandbox", "read-only", combined_prompt]
            stdin_text = None
        elif bin_name == "opencode":
            cmd = [bin_path, "run", combined_prompt]
            stdin_text = None
        elif bin_name == "omini":
            cmd = [bin_path, "ask", "--role", "advisor"]
            stdin_text = combined_prompt
        else:
            # gemini-api and generic read-only CLI wrappers
            cmd = [bin_path, "chat", "--prompt", combined_prompt]
            stdin_text = None

        t0 = time.perf_counter()
        try:
            proc = self._cli_runner(
                cmd,
                input=stdin_text,
                capture_output=True,
                text=True,
                timeout=45.0,
                env=env,
            )
        except Exception as exc:
            return {"ok": False, "error": f"CLI {bin_name} failed: {exc}", "latencyMs": round((time.perf_counter() - t0) * 1000.0, 1)}

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and out:
            return {
                "ok": True,
                "replyText": out,
                "latencyMs": latency_ms,
                "providerId": f"cli:{bin_name}",
                "modelId": bin_name,
            }
        err = (proc.stderr or out or f"returncode={proc.returncode}").strip()
        return {"ok": False, "error": err[:240], "latencyMs": latency_ms}

    @staticmethod
    def _normalize_steps(raw_steps: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_steps, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw_steps[:30], start=1):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip().lower()
            alias_map = {
                "activate": "activate_app",
                "launch": "activate_app",
                "inspect": "inspect_ui",
                "ocr": "inspect_ui",
                "click": "click_element",
                "type": "focus_and_type",
                "paste": "focus_and_type",
                "hotkey": "press_shortcut",
                "shortcut": "press_shortcut",
                "key": "press_shortcut",
                "wait": "wait_and_read",
                "read": "wait_and_read",
                "pause": "pause_for_human",
            }
            action = alias_map.get(action, action)
            if action not in SUPPORTED_STEP_ACTIONS:
                continue
            clean = dict(item)
            clean["step"] = len(normalized) + 1
            clean["action"] = action
            clean["title"] = str(item.get("title") or f"步骤 {len(normalized) + 1}: {action}").strip()
            clean["description"] = str(item.get("description") or "").strip()
            normalized.append(clean)
        return normalized

    @staticmethod
    def _normalize_parameters(raw_params: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if isinstance(raw_params, dict):
            for k, v in list(raw_params.items())[:12]:
                name = str(k or "").strip()
                if not name:
                    continue
                if isinstance(v, dict):
                    out.append(
                        {
                            "name": name,
                            "label": str(v.get("label") or name).strip(),
                            "defaultValue": str(v.get("defaultValue") if v.get("defaultValue") is not None else v.get("default", "")),
                            "required": bool(v.get("required", True)),
                            "description": str(v.get("description") or "").strip(),
                        }
                    )
                else:
                    out.append(
                        {
                            "name": name,
                            "label": name,
                            "defaultValue": str(v if v is not None else ""),
                            "required": True,
                            "description": "",
                        }
                    )
            return out
        if not isinstance(raw_params, list):
            return []
        for item in raw_params[:12]:
            if isinstance(item, dict) and str(item.get("name") or "").strip():
                out.append(
                    {
                        "name": str(item["name"]).strip(),
                        "label": str(item.get("label") or item["name"]).strip(),
                        "defaultValue": str(item.get("defaultValue") if item.get("defaultValue") is not None else ""),
                        "required": bool(item.get("required", True)),
                        "description": str(item.get("description") or "").strip(),
                    }
                )
        return out

    @staticmethod
    def _render_sop_markdown(workflow: Dict[str, Any]) -> str:
        tapp = workflow.get("targetApp") or {}
        bagent = workflow.get("builderAgent") or {}
        lines = [
            f"# SOP：{workflow.get('name') or '桌面应用标准操作流程'}",
            "",
            f"- **目标应用**：{tapp.get('name', 'Unknown')} (`{tapp.get('bundleID') or 'N/A'}`) · {tapp.get('categoryLabel', '')}",
            f"- **生成 Agent**：{bagent.get('label') or bagent.get('agentId') or 'N/A'}（回退模式：{'是' if bagent.get('usedFallback') else '否'}）",
            f"- **流程简介**：{workflow.get('summary') or workflow.get('goal') or ''}",
            "",
            "## 1. 前置条件与安全门禁",
        ]
        for pre in workflow.get("preconditions") or ["目标应用已安装且 macOS 辅助功能 / 屏幕录制权限就绪"]:
            lines.append(f"- {pre}")
        for gate in workflow.get("safetyGates") or []:
            lines.append(f"- **安全门禁**：{gate}")

        params = workflow.get("parameters") or []
        if params:
            lines.extend(["", "## 2. 动态参数说明"])
            for p in params:
                req = "必填" if p.get("required") else "可选"
                lines.append(
                    f"- `{{{{{p['name']}}}}}`（{p.get('label', p['name'])}，{req}）：默认 `{p.get('defaultValue', '')}` — {p.get('description', '')}"
                )

        lines.extend(["", "## 3. 标准操作步骤 (可执行 RPA 映射)"])
        for st in workflow.get("steps") or []:
            lines.append(
                f"{st.get('step', '-')}. **[{st.get('action')}] {st.get('title')}**：{st.get('description') or ''}"
            )

        lines.extend(
            [
                "",
                "## 4. 验收标准",
                f"- {workflow.get('verification') or '最后一步采集的 AX 与 Vision OCR 结果符合预期且无错误弹窗。'}",
            ]
        )
        return "\n".join(lines)

    def build_sop_and_workflow(
        self,
        *,
        goal: str,
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
        pre_inspection: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Inspect target macOS app (if live) and invoke ANY selected Agent to synthesize SOP + RPA Workflow."""
        clean_goal = str(goal or "").strip()
        if not clean_goal:
            return {
                "ok": False,
                "error_code": "missing_goal",
                "error": "请用自然语言输入希望自动建立的业务目标 / SOP 需求。",
            }
        if not (str(bundle_id or "").strip() or str(app_name or "").strip() or str(app_path or "").strip()):
            return {
                "ok": False,
                "error_code": "missing_target_app",
                "error": "请选择目标 macOS 应用（普通应用或 Agent 应用）。",
            }

        target_meta = self._resolve_target_meta(bundle_id=bundle_id, app_name=app_name, app_path=app_path)
        inspection: Optional[Dict[str, Any]] = pre_inspection if isinstance(pre_inspection, dict) and pre_inspection.get("ok") else None
        if inspection is not None:
            target_meta = {**target_meta, **(inspection.get("targetApp") or {}), "running": True}
        elif inspect_live and (target_meta.get("running") or launch_if_needed):
            inspection = self.inspect_app(
                bundle_id=str(target_meta.get("bundleID") or bundle_id),
                app_name=str(target_meta.get("name") or app_name),
                app_path=str(target_meta.get("appPath") or app_path),
                launch_if_needed=launch_if_needed,
                allow_activate=True,
            )
            if inspection.get("ok"):
                target_meta = {**target_meta, **(inspection.get("targetApp") or {}), "running": True}

        agent_catalog = self.list_builder_agents(refresh_models=False)
        chosen_agent_id = str(agent_id or "").strip() or str(agent_catalog.get("defaultAgentId") or "local:heuristic")
        agent_entry = next((a for a in agent_catalog.get("agents") or [] if a.get("id") == chosen_agent_id), None)

        sys_prompt, user_prompt = self._build_agent_prompt(
            target_meta=target_meta,
            goal=clean_goal,
            inspection=inspection,
            custom_agent_prompt=custom_agent_prompt,
            parameters_hint=parameters_hint,
        )

        parsed_plan: Optional[Dict[str, Any]] = None
        used_fallback = False
        fallback_reason = ""
        latency_ms = 0.0
        used_model = ""
        used_provider = ""
        agent_kind = "local_heuristic"
        agent_label = "本地 AX+OCR 规则规划引擎"

        if chosen_agent_id.startswith("local:"):
            parsed_plan = self._build_heuristic_plan(target_meta=target_meta, goal=clean_goal, inspection=inspection)
        elif chosen_agent_id.startswith("cli:"):
            agent_kind = "cli_agent"
            bin_name = chosen_agent_id.split(":", 1)[1].strip()
            agent_label = str((agent_entry or {}).get("label") or f"CLI {bin_name}")
            cli_res = self._invoke_cli_agent(bin_name=bin_name, sys_prompt=sys_prompt, user_prompt=user_prompt)
            latency_ms = float(cli_res.get("latencyMs") or 0.0)
            used_model = str(cli_res.get("modelId") or bin_name)
            used_provider = str(cli_res.get("providerId") or chosen_agent_id)
            if cli_res.get("ok"):
                parsed_plan = _extract_json_object(str(cli_res.get("replyText") or ""))
                if not parsed_plan or not self._normalize_steps(parsed_plan.get("steps")):
                    fallback_reason = "CLI Agent 输出未能解析为有效步骤 JSON，已回退到本地 AX+OCR 智能规划器"
                    parsed_plan = None
            else:
                fallback_reason = str(cli_res.get("error") or "CLI Agent 执行失败")
        else:
            agent_kind = "magpie_model"
            model_id = chosen_agent_id.split(":", 1)[1].strip() if chosen_agent_id.startswith("magpie:") else chosen_agent_id
            eff_pid = provider_id or (agent_entry.get("providerId") if agent_entry else None)
            agent_label = str((agent_entry or {}).get("label") or model_id)
            llm_res = self._invoke_magpie_agent(
                model_id=model_id,
                provider_id=eff_pid,
                sys_prompt=sys_prompt,
                user_prompt=user_prompt,
                inspection=inspection,
                attach_screenshot=attach_screenshot,
            )
            latency_ms = float(llm_res.get("latencyMs") or 0.0)
            used_model = str(llm_res.get("modelId") or model_id)
            used_provider = str(llm_res.get("providerId") or eff_pid or "magpie-gateway")
            if llm_res.get("ok"):
                parsed_plan = _extract_json_object(str(llm_res.get("replyText") or ""))
                if not parsed_plan or not self._normalize_steps(parsed_plan.get("steps")):
                    fallback_reason = f"模型 {used_model} 返回内容未包含可执行 JSON 步骤，已回退本地规则规划器"
                    parsed_plan = None
            else:
                fallback_reason = f"模型 {model_id} 调用未成功: {llm_res.get('error', 'unknown')}"

        if parsed_plan is None:
            used_fallback = not chosen_agent_id.startswith("local:")
            parsed_plan = self._build_heuristic_plan(target_meta=target_meta, goal=clean_goal, inspection=inspection)

        steps = self._normalize_steps(parsed_plan.get("steps"))
        if not steps:
            steps = self._normalize_steps(
                self._build_heuristic_plan(target_meta=target_meta, goal=clean_goal, inspection=inspection).get("steps")
            )
            used_fallback = True
            fallback_reason = fallback_reason or "Empty steps normalized to default plan"

        parameters = self._normalize_parameters(parsed_plan.get("parameters"))
        slug = _slugify(str(target_meta.get("name") or target_meta.get("bundleID") or "app"), "app")
        digest = hashlib.sha1(f"{target_meta.get('bundleID')}|{clean_goal}|{time.time()}".encode("utf-8")).hexdigest()[:8]
        wf_id = f"wf_{slug}_{digest}"
        now_iso = _utc_iso_now()

        workflow: Dict[str, Any] = {
            "id": wf_id,
            "version": 1,
            "revisionHistory": [],
            "name": str(parsed_plan.get("name") or f"{target_meta.get('name')} 自动化 SOP").strip(),
            "goal": clean_goal,
            "summary": str(parsed_plan.get("summary") or clean_goal).strip(),
            "targetApp": {
                "bundleID": str(target_meta.get("bundleID") or ""),
                "name": str(target_meta.get("name") or ""),
                "appPath": str(target_meta.get("appPath") or ""),
                "category": str(target_meta.get("category") or "productivity"),
                "categoryLabel": str(target_meta.get("categoryLabel") or "通用桌面应用"),
                "isAgentApp": bool(target_meta.get("isAgentApp")),
                "selfOrHost": bool(target_meta.get("selfOrHost")),
            },
            "builderAgent": {
                "agentId": chosen_agent_id,
                "kind": agent_kind,
                "label": agent_label,
                "modelId": used_model or chosen_agent_id,
                "providerId": used_provider,
                "latencyMs": latency_ms,
                "usedFallback": used_fallback,
                "fallbackReason": fallback_reason,
                "customPromptApplied": bool(custom_agent_prompt.strip()),
            },
            "parameters": parameters,
            "preconditions": list(parsed_plan.get("preconditions") or []),
            "safetyGates": list(parsed_plan.get("safetyGates") or []),
            "steps": steps,
            "verification": str(parsed_plan.get("verification") or ""),
            "uiProfileSnapshot": (inspection or {}).get("uiSummary") or {},
            "screenshotPath": str((inspection or {}).get("savedPath") or ""),
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }

        raw_md = str(parsed_plan.get("sopMarkdown") or "").strip()
        if len(raw_md) < 35:
            raw_md = self._render_sop_markdown(workflow)
        workflow["sopMarkdown"] = raw_md

        if save:
            self.save_workflow(workflow, sop_markdown=raw_md)

        return {
            "ok": True,
            "saved": bool(save),
            "workflow": workflow,
            "sopMarkdown": raw_md,
            "inspection": (
                {
                    "ok": bool(inspection.get("ok")),
                    "window": inspection.get("window"),
                    "axControlCount": inspection.get("axControlCount", 0),
                    "ocrCount": inspection.get("ocrCount", 0),
                    "savedPath": inspection.get("savedPath", ""),
                }
                if inspection
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Workflow CRUD & Knowledge Base Export
    # ------------------------------------------------------------------

    def list_workflows(self, *, bundle_id: Optional[str] = None) -> Dict[str, Any]:
        wf_map = self._state.get("workflows") or {}
        order = self._state.get("order") or list(wf_map.keys())
        items: List[Dict[str, Any]] = []
        bid_filter = (bundle_id or "").strip().casefold()
        for wid in order:
            wf = wf_map.get(wid)
            if not isinstance(wf, dict):
                continue
            if bid_filter:
                t_bid = str((wf.get("targetApp") or {}).get("bundleID") or "").casefold()
                if t_bid != bid_filter:
                    continue
            items.append(wf)
        return {
            "ok": True,
            "count": len(items),
            "workflows": items,
            "storePath": str(self.store_path),
        }

    def save_workflow(self, workflow: Dict[str, Any], *, sop_markdown: str = "") -> Dict[str, Any]:
        if not isinstance(workflow, dict):
            return {"ok": False, "error": "workflow must be an object."}
        wf = dict(workflow)
        wf_id = str(wf.get("id") or "").strip()
        if not wf_id:
            tapp = wf.get("targetApp") or {}
            wf_id = f"wf_{_slugify(str(tapp.get('name') or 'app'))}_{int(time.time())}"
            wf["id"] = wf_id
        wf["version"] = int(wf.get("version") or 1)
        if not isinstance(wf.get("revisionHistory"), list):
            wf["revisionHistory"] = []
        wf["steps"] = self._normalize_steps(wf.get("steps"))
        wf["parameters"] = self._normalize_parameters(wf.get("parameters"))
        if sop_markdown.strip():
            wf["sopMarkdown"] = sop_markdown.strip()
        elif not str(wf.get("sopMarkdown") or "").strip():
            wf["sopMarkdown"] = self._render_sop_markdown(wf)
        wf["updatedAt"] = _utc_iso_now()
        if not wf.get("createdAt"):
            wf["createdAt"] = wf["updatedAt"]

        wf_map = self._state.setdefault("workflows", {})
        wf_map[wf_id] = wf
        order = [wid for wid in (self._state.get("order") or []) if wid != wf_id]
        self._state["order"] = [wf_id] + order
        self._save_store()
        return {"ok": True, "workflow": wf, "count": len(wf_map)}

    def delete_workflow(self, workflow_id: str) -> Dict[str, Any]:
        wid = str(workflow_id or "").strip()
        wf_map = self._state.setdefault("workflows", {})
        existed = wid in wf_map
        wf_map.pop(wid, None)
        self._state["order"] = [x for x in (self._state.get("order") or []) if x != wid]
        self._save_store()
        return {"ok": True, "deleted": existed, "workflowId": wid, "count": len(wf_map)}

    def export_sop_to_kb(self, workflow_id: str) -> Dict[str, Any]:
        wid = str(workflow_id or "").strip()
        wf = (self._state.get("workflows") or {}).get(wid)
        if not isinstance(wf, dict):
            return {"ok": False, "error_code": "workflow_not_found", "error": f"未找到流程 {wid}"}
        tapp = wf.get("targetApp") or {}
        app_label = str(tapp.get("name") or tapp.get("bundleID") or "macOS App")
        keywords = [
            "app-use",
            "sop",
            app_label,
            str(tapp.get("bundleID") or ""),
            str(tapp.get("category") or ""),
        ]
        res = self.engine.knowledge.save_entry(
            title=f"[App-Use SOP] {wf.get('name') or app_label}",
            body=str(wf.get("sopMarkdown") or self._render_sop_markdown(wf)),
            kind="script",
            library="shared",
            keywords=[k for k in keywords if k],
            synonyms=[app_label, str(wf.get("goal") or "")[:40]],
            source="app-use-studio",
            external=False,
            status="published",
        )
        return {"ok": True, "workflowId": wid, "kbResult": res}

    def rollback_workflow(self, workflow_id: str, *, revision_index: int = -1) -> Dict[str, Any]:
        """Rollback a workflow to a previous archived revision."""
        wid = str(workflow_id or "").strip()
        wf_map = self._state.get("workflows") or {}
        cur = wf_map.get(wid)
        if not isinstance(cur, dict):
            return {"ok": False, "error_code": "workflow_not_found", "error": f"未找到流程 {wid}"}
        revs = list(cur.get("revisionHistory") or [])
        if not revs:
            return {"ok": False, "error_code": "no_revisions", "error": "该流程尚无历史版本可回滚"}
        try:
            snap = revs[int(revision_index)]
        except Exception:
            snap = revs[-1]
        restored = dict(cur)
        restored["steps"] = list(snap.get("steps") or restored.get("steps") or [])
        restored["sopMarkdown"] = str(snap.get("sopMarkdown") or self._render_sop_markdown(restored))
        restored["version"] = int(cur.get("version") or 1) + 1
        restored["rolledBackFromVersion"] = snap.get("version")
        restored["updatedAt"] = _utc_iso_now()
        wf_map[wid] = restored
        self._save_store()
        return {"ok": True, "workflow": restored}

    # ------------------------------------------------------------------
    # Safe Dynamic Self-Healing Execution Engine (v2.7.0)
    # ------------------------------------------------------------------

    @staticmethod
    def _fuzzy_resolve_point(step: Dict[str, Any], inspection: Optional[Dict[str, Any]]) -> Tuple[Optional[Tuple[float, float]], str]:
        """Delegate fuzzy grounding to multi-factor SemanticElementGrounder."""
        res = SemanticElementGrounder.resolve_best(step, inspection, min_score=0.36)
        if res.get("ok") and res.get("point"):
            pt = res["point"]
            return (float(pt[0]), float(pt[1])), str(res.get("source") or "semantic_grounder")
        return None, "unresolved"

    def preview_grounding(
        self,
        step: Dict[str, Any],
        *,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
        inspection: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Preview multi-factor grounding scores and extracted neighbor anchor bundle."""
        insp = inspection
        if insp is None and (bundle_id or app_name or app_path):
            insp = self.inspect_app(
                bundle_id=bundle_id,
                app_name=app_name,
                app_path=app_path,
                launch_if_needed=False,
                allow_activate=False,
            )
            if not insp.get("ok"):
                return insp
        res = SemanticElementGrounder.resolve_best(step, insp, min_score=0.36)
        return {
            **res,
            "targetApp": (insp or {}).get("targetApp") or {"bundleID": bundle_id, "name": app_name},
        }

    def _propose_self_heal(
        self,
        *,
        step: Dict[str, Any],
        error_msg: str,
        live_inspect: Optional[Dict[str, Any]],
        agent_id: str = "",
        pre_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Classify failure taxonomy and generate a bounded 1-step corrective patch."""
        failure = classify_step_failure(step, error_msg, live_inspect, pre_state=pre_state)
        cat = str(failure.get("category") or "ELEMENT_DRIFT")

        if cat == "AUTH_GATE":
            return {
                "strategy": "pause_for_human",
                "failureCategory": "AUTH_GATE",
                "signals": failure.get("signals") or [],
                "reason": failure.get("reason") or "检测到认证/风险确认弹窗，等待人工接管",
                "source": "failure_taxonomy",
            }

        if cat == "NOT_FRONTMOST":
            return {
                "strategy": "reactivate_and_retry",
                "failureCategory": "NOT_FRONTMOST",
                "patchedStep": dict(step),
                "reason": failure.get("reason") or "窗口未前置，尝试重新激活目标窗口后重试",
                "source": "failure_taxonomy",
            }

        if cat == "MODAL_OCCLUSION":
            return {
                "strategy": "dismiss_and_retry",
                "failureCategory": "MODAL_OCCLUSION",
                "dismissCombo": str(failure.get("dismissCombo") or "escape"),
                "patchedStep": dict(step),
                "reason": failure.get("reason") or "关闭模态遮挡弹窗后重试当前步骤",
                "source": "failure_taxonomy",
            }

        if cat == "ELEMENT_DRIFT":
            g = SemanticElementGrounder.resolve_best(step, live_inspect, min_score=0.38)
            if g.get("ok") and g.get("point") and step.get("action") in ("click_element", "focus_and_type"):
                pt = g["point"]
                bundle = g.get("anchorBundle") or {}
                patched = dict(step)
                patched["x"] = float(pt[0])
                patched["y"] = float(pt[1])
                if bundle.get("relX") is not None and bundle.get("relY") is not None:
                    patched["relX"] = bundle["relX"]
                    patched["relY"] = bundle["relY"]
                if bundle.get("targetRole"):
                    patched["targetRole"] = bundle["targetRole"]
                if bundle.get("neighborTexts"):
                    patched["neighborTexts"] = bundle["neighborTexts"]
                if not patched.get("targetAxId") and bundle.get("targetAxId"):
                    patched["targetAxId"] = bundle["targetAxId"]
                if not patched.get("targetAxTitle") and bundle.get("targetAxTitle"):
                    patched["targetAxTitle"] = bundle["targetAxTitle"]
                return {
                    "strategy": "retry_step",
                    "failureCategory": "ELEMENT_DRIFT",
                    "patchedStep": patched,
                    "confidence": g.get("confidence", 0.0),
                    "margin": g.get("margin", 0.0),
                    "reason": f"通过多因子语义+空间+邻域锚定重新定位 ({g.get('source', '')}, conf={g.get('confidence', 0)})",
                    "source": "semantic_grounder",
                }

        chosen_agent = str(agent_id or "").strip()
        if chosen_agent and not chosen_agent.startswith("local:"):
            model_id = chosen_agent.split(":", 1)[1].strip() if chosen_agent.startswith("magpie:") else chosen_agent
            sys_p = (
                "你是 RPA 运行时自愈代理。某一步骤失败了，请根据当前屏幕最新 AX+OCR 状态给出单步修复 JSON：\n"
                '{"strategy":"retry_step"|"dismiss_and_retry"|"pause_for_human"|"abort","dismissCombo":"escape","patchedStep":{...},"reason":"原因"}\n'
                "patchedStep 必须保持 action 合法。只输出纯 JSON。"
            )
            ctx = {
                "failedStep": step,
                "failureCategory": cat,
                "error": error_msg,
                "axControls": (live_inspect or {}).get("axControls", [])[:15],
                "ocrElements": (live_inspect or {}).get("ocrElements", [])[:18],
            }
            llm = self.engine.models.generate_chat_reply(
                [{"role": "system", "content": sys_p}, {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
                model_id=model_id,
                max_tokens=600,
                temperature=0.1,
                timeout=20.0,
            )
            if llm.get("ok"):
                parsed = _extract_json_object(str(llm.get("replyText") or ""))
                if isinstance(parsed, dict) and parsed.get("strategy") in (
                    "retry_step",
                    "dismiss_and_retry",
                    "pause_for_human",
                    "abort",
                ):
                    return {**parsed, "failureCategory": cat, "source": chosen_agent}

        if step.get("action") == "wait_and_read" or cat in ("TIMING_LAG", "READBACK_MISMATCH"):
            patched = dict(step)
            patched["delaySec"] = min(6.0, float(step.get("delaySec") or 0.5) + 1.5)
            patched["waitUntilChanged"] = True
            return {
                "strategy": "retry_step",
                "failureCategory": cat,
                "patchedStep": patched,
                "reason": "延长等待并启用变化检测后重新采集 OCR/AX 回读",
                "source": "wait_backoff",
            }
        return {"strategy": "abort", "failureCategory": cat, "reason": "无可执行的单步自愈策略", "source": "none"}

    @staticmethod
    def _resolve_element_point(step: Dict[str, Any], inspection: Optional[Dict[str, Any]]) -> Tuple[Optional[Tuple[float, float]], str]:
        """Resolve live screen (x, y) via AX title/id -> Vision OCR matchText -> window relX/relY -> explicit x/y."""
        if inspection and inspection.get("ok"):
            ax_id = str(step.get("targetAxId") or "").strip().casefold()
            ax_title = str(step.get("targetAxTitle") or "").strip().casefold()
            for ctrl in inspection.get("axControls") or []:
                c_id = str(ctrl.get("identifier") or "").strip().casefold()
                c_title = str(ctrl.get("title") or "").strip().casefold()
                c_desc = str(ctrl.get("description") or "").strip().casefold()
                center = ctrl.get("center") or {}
                if "x" not in center or "y" not in center:
                    continue
                if ax_id and c_id == ax_id:
                    return (float(center["x"]), float(center["y"])), f"ax_id:{ax_id}"
                if ax_title and (ax_title == c_title or ax_title in c_title or ax_title in c_desc):
                    return (float(center["x"]), float(center["y"])), f"ax_title:{ax_title}"

            match_txt = str(step.get("matchText") or step.get("targetAxTitle") or "").strip().casefold()
            if match_txt:
                for ocr in inspection.get("ocrElements") or []:
                    ot = str(ocr.get("text") or "").strip().casefold()
                    sc = ocr.get("screenCenter") or {}
                    if ot and match_txt in ot and "x" in sc and "y" in sc:
                        return (float(sc["x"]), float(sc["y"])), f"ocr:{match_txt}"

            win = inspection.get("window") or {}
            bounds = win.get("bounds") if isinstance(win, dict) else {}
            if isinstance(bounds, dict) and bounds.get("width") and bounds.get("height"):
                rx = step.get("relX")
                ry = step.get("relY")
                if rx is not None and ry is not None:
                    sx = float(bounds["x"]) + float(rx) * float(bounds["width"])
                    sy = float(bounds["y"]) + float(ry) * float(bounds["height"])
                    return (round(sx, 1), round(sy, 1)), f"rel:({rx},{ry})"

        if step.get("x") is not None and step.get("y") is not None:
            return (float(step["x"]), float(step["y"])), "explicit_xy"
        return None, "unresolved"

    def run_workflow(
        self,
        *,
        workflow_id: Optional[str] = None,
        workflow: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = True,
        confirm_run: bool = False,
        respect_human_guard: bool = True,
        max_steps: int = 25,
        self_heal: bool = True,
        auto_patch_workflow: bool = False,
        heal_agent_id: str = "",
        dispatch_mode: str = "auto",
    ) -> Dict[str, Any]:
        """Validate (dry_run=True) or safely execute (dry_run=False, confirm_run=True) any App-Use workflow."""
        if workflow_id:
            stored = (self._state.get("workflows") or {}).get(str(workflow_id).strip())
            if not isinstance(stored, dict):
                return {"ok": False, "error_code": "workflow_not_found", "error": f"未找到流程 {workflow_id}"}
            wf = dict(stored)
        elif isinstance(workflow, dict):
            wf = dict(workflow)
        else:
            return {"ok": False, "error_code": "missing_workflow", "error": "请提供 workflow_id 或 workflow 定义。"}

        if not dry_run and not confirm_run:
            return {
                "ok": False,
                "error_code": "confirmation_required",
                "error": "实机执行 App-Use 流程须显式传 confirm_run=true。",
            }

        if not dry_run and respect_human_guard:
            guard = self.engine.human_guard.check_can_operate()
            if not guard.get("canOperate", True):
                return {
                    "ok": False,
                    "error_code": "human_activity_guard_paused",
                    "error": "检测到用户正在操作键鼠，防抢鼠标守卫已自动让步暂停本次实机流程。",
                    "humanGuard": guard,
                }

        merged_params: Dict[str, Any] = {}
        for p in wf.get("parameters") or []:
            if isinstance(p, dict) and p.get("name"):
                merged_params[str(p["name"])] = p.get("defaultValue", "")
        if isinstance(params, dict):
            for k, v in params.items():
                if v is not None and str(v) != "":
                    merged_params[str(k)] = v

        raw_steps = self._normalize_steps(wf.get("steps"))[: max(1, min(30, int(max_steps)))]
        tapp = wf.get("targetApp") or {}
        bid = str(tapp.get("bundleID") or "")
        app_name = str(tapp.get("name") or "")
        app_path = str(tapp.get("appPath") or "")

        runs_dir = _sandisk_artifact_dir(self.engine, "app-use-runs")
        run_id = f"run_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        t_start = time.perf_counter()

        def _app_args() -> List[str]:
            out: List[str] = []
            if bid:
                out.extend(["--bundle-id", bid])
            if app_name:
                out.extend(["--app-name", app_name])
            if app_path:
                out.extend(["--app-path", app_path])
            return out

        latest_inspect: Optional[Dict[str, Any]] = None
        if dry_run:
            probe = self.engine._run_native(
                ["app-use-inspect", "--no-activate", "--skip-ocr", "--max-nodes", "140", *_app_args()],
                timeout=5.0,
            )
            if probe.get("ok"):
                latest_inspect = probe
            else:
                snap = wf.get("uiProfileSnapshot") or {}
                if isinstance(snap, dict) and snap.get("windowBounds"):
                    latest_inspect = {
                        "ok": True,
                        "window": {"bounds": snap.get("windowBounds")},
                        "axControls": (snap.get("sampleInputs") or []) + (snap.get("sampleButtons") or []),
                        "ocrElements": snap.get("sampleOCR") or [],
                    }

        step_results: List[Dict[str, Any]] = []
        paused_for_human = False
        final_readback: Dict[str, Any] = {}
        captured_vars: Dict[str, str] = {}
        baseline_ocr_lines: List[str] = []
        healing_events: List[Dict[str, Any]] = []
        workflow_patched = False
        hid_lease_wait_ms = 0.0
        last_pre_state: Optional[Dict[str, Any]] = compute_ui_state(latest_inspect, bundle_id=bid) if latest_inspect else None
        last_action_sig = ""

        risk_profile = classify_app_risk_tier(
            bid,
            app_name,
            app_path,
            category=str(tapp.get("category") or ""),
        )
        req_mode = (dispatch_mode or "auto").strip().lower()
        if req_mode not in ("auto", "headless_ax_first", "foreground_hid_only"):
            req_mode = "auto"
        risk_guard_enforced = False
        if req_mode == "foreground_hid_only":
            effective_headless_allowed = False
        elif not risk_profile.get("allowHeadlessAxWrite"):
            effective_headless_allowed = False
            if req_mode == "headless_ax_first":
                risk_guard_enforced = True
        else:
            effective_headless_allowed = True

        headless_ax_steps = 0
        foreground_hid_steps = 0
        fallback_steps = 0
        total_jitter_ms = 0.0
        lane_ok = False
        lane_final_state: Optional[str] = None
        lane_error = ""

        def _dispatch_summary() -> Dict[str, Any]:
            return {
                "requestedMode": req_mode,
                "effectiveHeadlessAllowed": effective_headless_allowed,
                "riskGuardEnforced": risk_guard_enforced,
                "headlessAxSteps": headless_ax_steps,
                "foregroundHidSteps": foreground_hid_steps,
                "fallbackSteps": fallback_steps,
                "totalJitterMs": round(total_jitter_ms, 1),
            }

        def _pace_if_needed() -> None:
            nonlocal total_jitter_ms
            if (risk_profile.get("minActionGapMs") or 0) > 0 or ((risk_profile.get("jitterRangeMs") or [0, 0])[-1] or 0) > 0:
                if not dry_run:
                    self._lanes.update_lane(run_id, state="human_paced_cooldown", current_action="风控拟真节流")
                pr = self._risk_pacer.pace_before_mutation(bid, risk_profile)
                slept = float(pr.get("sleptMs") or 0.0)
                total_jitter_ms += slept
                if slept > 0 and not dry_run:
                    self._lanes.update_lane(run_id, delta_jitter_ms=slept)

        @contextlib.contextmanager
        def _acquire_hid(step_action: str):
            nonlocal hid_lease_wait_ms
            if not dry_run:
                self._lanes.update_lane(
                    run_id,
                    state="waiting_hid_lease",
                    current_action=step_action,
                    dispatch_channel="foreground_hid",
                )
            with self._hid_lease.acquire(job_id=run_id, bundle_id=bid, step_action=step_action) as li:
                wait_ms = float(li.get("waitMs") or 0.0)
                hid_lease_wait_ms += wait_ms
                if not dry_run:
                    self._lanes.update_lane(
                        run_id,
                        state="holding_hid_lease",
                        current_action=step_action,
                        dispatch_channel="foreground_hid",
                        delta_hid_wait_ms=wait_ms,
                    )
                yield li

        def _ax_selector_args(step_obj: Dict[str, Any], pt_xy: Optional[Tuple[float, float]] = None) -> List[str]:
            out = list(_app_args())
            ident = str(step_obj.get("targetAxIdentifier") or step_obj.get("identifier") or "").strip()
            title = str(
                step_obj.get("targetAxTitle")
                or step_obj.get("targetTitle")
                or step_obj.get("targetOcrText")
                or ""
            ).strip()
            role = str(step_obj.get("targetRole") or "").strip()
            if ident and not ident.startswith("--"):
                out.extend(["--identifier", ident])
            if title and not title.startswith("--"):
                out.extend(["--title", title])
            if role and not role.startswith("--"):
                out.extend(["--role", role])
            if step_obj.get("relX") is not None and step_obj.get("relY") is not None:
                out.extend(["--rel-x", str(step_obj["relX"]), "--rel-y", str(step_obj["relY"])])
            if pt_xy is not None:
                out.extend(["--x", str(pt_xy[0]), "--y", str(pt_xy[1])])
            return out

        def _inspect_args(
            step_obj: Dict[str, Any],
            *,
            out_png: Optional[Path] = None,
            max_nodes: Optional[int] = None,
        ) -> List[str]:
            ic = ["app-use-inspect", *_app_args()]
            if out_png is not None:
                ic.extend(["--out", str(out_png)])
            if max_nodes is not None:
                ic.extend(["--max-nodes", str(max_nodes)])
            if step_obj.get("launchIfNeeded"):
                ic.append("--launch")
            if (req_mode == "headless_ax_first" or (headless_ax_steps > 0 and foreground_hid_steps == 0)) and not step_obj.get("forceForeground"):
                ic.append("--no-activate")
            return ic

        def _maybe_archive_patch(step_idx: int, new_step: Dict[str, Any], reason: str) -> None:
            nonlocal workflow_patched
            if not (auto_patch_workflow and workflow_id and workflow_id in (self._state.get("workflows") or {})):
                return
            stored_wf = dict(self._state["workflows"][workflow_id])
            revs = list(stored_wf.get("revisionHistory") or [])
            revs.append(
                {
                    "version": int(stored_wf.get("version") or 1),
                    "savedAt": stored_wf.get("updatedAt") or _utc_iso_now(),
                    "reason": f"Auto-heal step {step_idx}: {reason}",
                    "steps": list(stored_wf.get("steps") or []),
                    "sopMarkdown": stored_wf.get("sopMarkdown") or "",
                }
            )
            stored_wf["revisionHistory"] = revs[-10:]
            stored_wf["version"] = int(stored_wf.get("version") or 1) + 1
            cur_steps = list(stored_wf.get("steps") or [])
            for pos, s_item in enumerate(cur_steps):
                if int(s_item.get("step") or pos + 1) == step_idx:
                    cur_steps[pos] = {**s_item, **new_step, "step": step_idx}
                    break
            stored_wf["steps"] = self._normalize_steps(cur_steps)
            stored_wf["sopMarkdown"] = self._render_sop_markdown(stored_wf)
            stored_wf["updatedAt"] = _utc_iso_now()
            self._state["workflows"][workflow_id] = stored_wf
            self._save_store()
            workflow_patched = True

        def _capture_from_inspect(step_obj: Dict[str, Any], inspect_res: Dict[str, Any]) -> Optional[Tuple[str, str]]:
            var_name = str(step_obj.get("captureAs") or "").strip()
            if not var_name or not inspect_res.get("ok"):
                return None
            val = _extract_captured_value(
                inspect_res,
                mode=str(step_obj.get("extractMode") or "auto"),
                pattern=str(step_obj.get("extractPattern") or ""),
                baseline_ocr_lines=baseline_ocr_lines,
            )
            captured_vars[var_name] = val
            merged_params[var_name] = val
            return var_name, val

        if not dry_run:
            self._lanes.start_lane(
                run_id,
                bundle_id=bid or app_name or "unknown",
                app_name=app_name or bid,
                risk_tier=str(risk_profile.get("tier") or "safe_native"),
                dispatch_mode=req_mode,
                state="observing",
                current_action="初始化执行",
            )

        try:
            for raw_st in raw_steps:
                st = _substitute_params(raw_st, merged_params)
                idx = int(st.get("step") or len(step_results) + 1)
                action = str(st.get("action") or "")
                step_t0 = time.perf_counter()

                if dry_run:
                    pt, source = self._resolve_element_point(st, latest_inspect)
                    if pt is None and self_heal:
                        f_pt, f_src = self._fuzzy_resolve_point(st, latest_inspect)
                        if f_pt is not None:
                            pt, source = f_pt, f_src
                    step_results.append(
                        {
                            "step": idx,
                            "action": action,
                            "title": st.get("title", ""),
                            "status": "human_gate" if action == "pause_for_human" else "dry_run_validated",
                            "resolvedPoint": {"x": pt[0], "y": pt[1]} if pt else None,
                            "resolutionSource": source,
                            "payload": {k: v for k, v in st.items() if k not in ("step", "title", "description")},
                        }
                    )
                    continue

                if action == "pause_for_human":
                    paused_for_human = True
                    step_results.append(
                        {
                            "step": idx,
                            "action": action,
                            "title": st.get("title", ""),
                            "status": "paused_for_human",
                            "message": str(st.get("message") or st.get("description") or "等待人工接管确认"),
                        }
                    )
                    break

                if action == "activate_app":
                    if effective_headless_allowed and st.get("headlessOptional"):
                        step_results.append(
                            {
                                "step": idx,
                                "action": action,
                                "title": st.get("title", ""),
                                "ok": True,
                                "skippedForHeadless": True,
                                "dispatchChannel": "headless_ax_skipped",
                                "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                            }
                        )
                        continue
                    cmd = ["app-use-activate", *_app_args()]
                    if st.get("launchIfNeeded", True):
                        cmd.append("--launch")
                    _pace_if_needed()
                    with _acquire_hid(action):
                        res = self.engine._run_native(cmd, timeout=16.0)
                    foreground_hid_steps += 1
                    if not dry_run:
                        self._lanes.update_lane(run_id, delta_hid=1)
                    last_action_sig = step_action_signature(st)
                    step_results.append(
                        {
                            "step": idx,
                            "action": action,
                            "title": st.get("title", ""),
                            "ok": bool(res.get("ok")),
                            "dispatchChannel": "foreground_hid",
                            "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                            "detail": res,
                        }
                    )
                    if not res.get("ok"):
                        lane_error = str(res.get("error") or "activate_app failed")
                        return {
                            "ok": False,
                            "runId": run_id,
                            "dryRun": False,
                            "failedStep": idx,
                            "error": lane_error,
                            "riskProfile": risk_profile,
                            "dispatchSummary": _dispatch_summary(),
                            "hidLeaseWaitMs": round(hid_lease_wait_ms, 2),
                            "capturedVars": captured_vars,
                            "healingEvents": healing_events,
                            "stepResults": step_results,
                        }
                    continue

                if action == "inspect_ui":
                    if not dry_run:
                        self._lanes.update_lane(run_id, state="observing", current_action=action)
                    png = runs_dir / f"{run_id}_step{idx}.png"
                    cmd = _inspect_args(st, out_png=png)
                    res = self.engine._run_native(cmd, timeout=20.0)
                    if res.get("ok"):
                        latest_inspect = res
                        baseline_ocr_lines = [
                            _clean_ui_text(ln)
                            for ln in str(res.get("ocrPreview") or "").splitlines()
                            if _clean_ui_text(ln)
                        ]
                        post_state = compute_ui_state(res, bundle_id=bid)
                        if last_pre_state and last_action_sig:
                            try:
                                self.state_graph.record_transition(
                                    bid,
                                    app_name,
                                    last_pre_state,
                                    last_action_sig,
                                    post_state,
                                    ok=True,
                                    latency_ms=round((time.perf_counter() - step_t0) * 1000.0, 1),
                                )
                            except Exception:
                                pass
                        last_pre_state = post_state
                        final_readback = {
                            "ocrPreview": res.get("ocrPreview", ""),
                            "axTexts": [_clean_ui_text(x) for x in (res.get("axTexts") or []) if _clean_ui_text(x)],
                            "savedPath": res.get("savedPath", ""),
                            "artifactName": Path(str(res.get("savedPath") or "")).name if res.get("savedPath") else "",
                        }
                    cap = _capture_from_inspect(st, res)
                    step_results.append(
                        {
                            "step": idx,
                            "action": action,
                            "title": st.get("title", ""),
                            "ok": bool(res.get("ok")),
                            "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                            "axControlCount": res.get("axControlCount", 0),
                            "ocrCount": res.get("ocrCount", 0),
                            "savedPath": res.get("savedPath", ""),
                            "artifactName": Path(str(res.get("savedPath") or "")).name if res.get("savedPath") else "",
                            "ocrPreview": str(res.get("ocrPreview") or "")[:360],
                            "captured": {cap[0]: cap[1]} if cap else None,
                        }
                    )
                    continue

                if action == "click_element":
                    headless_fallback_reason = ""
                    if effective_headless_allowed and not st.get("doubleClick") and not st.get("forceForeground"):
                        if not dry_run:
                            self._lanes.update_lane(run_id, state="ax_headless", current_action=action, dispatch_channel="headless_ax")
                        pt_pre: Optional[Tuple[float, float]] = None
                        if latest_inspect is not None:
                            pt_pre, _ = self._resolve_element_point(st, latest_inspect)
                        ax_cmd = ["app-use-ax-action", *_ax_selector_args(st, pt_pre)]
                        if st.get("axAction"):
                            ax_cmd.extend(["--ax-action", str(st["axAction"])])
                        ax_res = self.engine._run_native(ax_cmd, timeout=8.0)
                        if ax_res.get("ok") and (
                            ax_res.get("channel") == "headless_ax"
                            or "matchedElement" in ax_res
                            or "axError" in ax_res
                        ):
                            headless_ax_steps += 1
                            if not dry_run:
                                self._lanes.update_lane(
                                    run_id,
                                    state="ax_headless",
                                    current_action=action,
                                    dispatch_channel="headless_ax",
                                    delta_headless=1,
                                )
                            last_action_sig = step_action_signature(st)
                            step_results.append(
                                {
                                    "step": idx,
                                    "action": action,
                                    "title": st.get("title", ""),
                                    "ok": True,
                                    "selfHealed": False,
                                    "dispatchChannel": "headless_ax",
                                    "stoleFocus": False,
                                    "touchedClipboard": False,
                                    "matchedElement": ax_res.get("matchedElement"),
                                    "resolutionSource": "ax_headless",
                                    "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                                }
                            )
                            continue
                        headless_fallback_reason = str(ax_res.get("code") or ax_res.get("error") or "ax_action_failed")
                        fallback_steps += 1
                        if not dry_run:
                            self._lanes.update_lane(run_id, delta_fallback=1, note=headless_fallback_reason)
                    elif risk_guard_enforced and not st.get("doubleClick") and not dry_run:
                        self._lanes.update_lane(run_id, delta_risk_blocked=1, note="high_risk_social: headless blocked")

                    if latest_inspect is None:
                        latest_inspect = self.engine._run_native(["app-use-inspect", *_app_args()], timeout=16.0)
                    if latest_inspect and latest_inspect.get("ok"):
                        last_pre_state = compute_ui_state(latest_inspect, bundle_id=bid)
                    pt, source = self._resolve_element_point(st, latest_inspect)
                    if pt is None:
                        latest_inspect = self.engine._run_native(["app-use-inspect", *_app_args()], timeout=16.0)
                        pt, source = self._resolve_element_point(st, latest_inspect)
                    healed_here = False
                    if pt is None and self_heal:
                        heal = self._propose_self_heal(
                            step=st,
                            error_msg="click_element target unresolved",
                            live_inspect=latest_inspect,
                            agent_id=heal_agent_id,
                            pre_state=last_pre_state,
                        )
                        strat = str(heal.get("strategy") or "")
                        if strat == "pause_for_human":
                            paused_for_human = True
                            healing_events.append(
                                {
                                    "step": idx,
                                    "action": action,
                                    "failureCategory": heal.get("failureCategory", "AUTH_GATE"),
                                    "reason": heal.get("reason", ""),
                                    "source": heal.get("source", ""),
                                }
                            )
                            step_results.append(
                                {
                                    "step": idx,
                                    "action": action,
                                    "title": st.get("title", ""),
                                    "status": "paused_for_human",
                                    "failureCategory": heal.get("failureCategory", "AUTH_GATE"),
                                    "message": heal.get("reason", ""),
                                }
                            )
                            break
                        if strat == "dismiss_and_retry" and heal.get("dismissCombo"):
                            _pace_if_needed()
                            with _acquire_hid("heal_dismiss"):
                                self.engine._run_native(["press-key", *_app_args(), "--combo", str(heal["dismissCombo"])], timeout=8.0)
                            latest_inspect = self.engine._run_native(["app-use-inspect", *_app_args()], timeout=16.0)
                        elif strat == "reactivate_and_retry":
                            _pace_if_needed()
                            with _acquire_hid("heal_reactivate"):
                                self.engine._run_native(["app-use-activate", *_app_args()], timeout=14.0)
                            latest_inspect = self.engine._run_native(["app-use-inspect", *_app_args()], timeout=16.0)
                        if strat in ("retry_step", "dismiss_and_retry", "reactivate_and_retry") and isinstance(heal.get("patchedStep"), dict):
                            st_patched = dict(st, **heal["patchedStep"])
                            pt, source = self._resolve_element_point(st_patched, latest_inspect)
                            if pt is None:
                                pt, source = self._fuzzy_resolve_point(st_patched, latest_inspect)
                            if pt is not None:
                                st = st_patched
                                healed_here = True
                                healing_events.append(
                                    {
                                        "step": idx,
                                        "action": action,
                                        "failureCategory": heal.get("failureCategory", ""),
                                        "confidence": heal.get("confidence"),
                                        "margin": heal.get("margin"),
                                        "reason": heal.get("reason", ""),
                                        "source": heal.get("source", ""),
                                        "resolvedPoint": {"x": pt[0], "y": pt[1]},
                                    }
                                )
                                _maybe_archive_patch(idx, st_patched, str(heal.get("reason") or "click re-anchor"))
                    if pt is None:
                        step_results.append(
                            {
                                "step": idx,
                                "action": action,
                                "title": st.get("title", ""),
                                "ok": False,
                                "error": "未能从 AX 或 Vision OCR 定位目标元素坐标",
                            }
                        )
                        lane_error = "click_element target unresolved"
                        return {
                            "ok": False,
                            "runId": run_id,
                            "dryRun": False,
                            "failedStep": idx,
                            "error": lane_error,
                            "riskProfile": risk_profile,
                            "dispatchSummary": _dispatch_summary(),
                            "hidLeaseWaitMs": round(hid_lease_wait_ms, 2),
                            "capturedVars": captured_vars,
                            "healingEvents": healing_events,
                            "stepResults": step_results,
                        }
                    click_cmd = ["click", "--x", str(pt[0]), "--y", str(pt[1])]
                    if st.get("doubleClick"):
                        click_cmd.append("--double")
                    _pace_if_needed()
                    with _acquire_hid(action):
                        res = self.engine._run_native(click_cmd, timeout=10.0)
                    foreground_hid_steps += 1
                    if not dry_run:
                        self._lanes.update_lane(run_id, delta_hid=1)
                    last_action_sig = step_action_signature(st)
                    self.engine.human_guard.record_rpa_action(action=f"app_use:{action}", cursor_x=pt[0], cursor_y=pt[1])
                    click_rec: Dict[str, Any] = {
                        "step": idx,
                        "action": action,
                        "title": st.get("title", ""),
                        "ok": bool(res.get("ok")),
                        "selfHealed": healed_here,
                        "dispatchChannel": "foreground_hid_fallback" if headless_fallback_reason else "foreground_hid",
                        "resolutionSource": source,
                        "clickPoint": {"x": pt[0], "y": pt[1]},
                        "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                    }
                    if headless_fallback_reason:
                        click_rec["headlessFallbackReason"] = headless_fallback_reason
                    step_results.append(click_rec)
                    continue

                if action == "focus_and_type":
                    text_val = str(st.get("text") or "")
                    if latest_inspect and latest_inspect.get("ok"):
                        last_pre_state = compute_ui_state(latest_inspect, bundle_id=bid)
                    pt, source = self._resolve_element_point(st, latest_inspect)

                    headless_fallback_reason = ""
                    if effective_headless_allowed and not st.get("forceForeground") and not text_val.startswith("--"):
                        if not dry_run:
                            self._lanes.update_lane(
                                run_id,
                                state="ax_headless",
                                current_action=action,
                                dispatch_channel="headless_ax",
                            )
                        ax_cmd = ["app-use-ax-set-value", *_ax_selector_args(st, pt), "--text", text_val]
                        if st.get("append"):
                            ax_cmd.append("--append")
                        if st.get("submitAfter"):
                            ax_cmd.append("--submit")
                        ax_res = self.engine._run_native(ax_cmd, timeout=10.0)
                        if ax_res.get("ok") and ax_res.get("verified"):
                            headless_ax_steps += 1
                            if not dry_run:
                                self._lanes.update_lane(
                                    run_id,
                                    state="ax_headless",
                                    current_action=action,
                                    dispatch_channel="headless_ax",
                                    delta_headless=1,
                                )
                            last_action_sig = step_action_signature(st)
                            step_results.append(
                                {
                                    "step": idx,
                                    "action": action,
                                    "title": st.get("title", ""),
                                    "ok": True,
                                    "selfHealed": False,
                                    "verified": True,
                                    "submitted": bool(ax_res.get("submitted")),
                                    "dispatchChannel": "headless_ax",
                                    "stoleFocus": False,
                                    "touchedClipboard": False,
                                    "readbackSource": ax_res.get("readbackSource", "ax_headless"),
                                    "readbackPreview": ax_res.get("readbackPreview", ""),
                                    "matchedElement": ax_res.get("matchedElement"),
                                    "resolutionSource": "ax_headless",
                                    "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                                    "error": "",
                                }
                            )
                            continue
                        headless_fallback_reason = str(ax_res.get("code") or ax_res.get("error") or "ax_set_value_failed")
                        fallback_steps += 1
                        if not dry_run:
                            self._lanes.update_lane(run_id, delta_fallback=1, note=headless_fallback_reason)
                    elif risk_guard_enforced and not dry_run:
                        self._lanes.update_lane(run_id, delta_risk_blocked=1, note="high_risk_social: headless blocked")

                    def _exec_paste(target_pt: Optional[Tuple[float, float]]) -> Dict[str, Any]:
                        nonlocal foreground_hid_steps
                        c = ["app-use-paste", *_app_args(), "--text", text_val]
                        if target_pt is not None:
                            c.extend(["--x", str(target_pt[0]), "--y", str(target_pt[1])])
                        if st.get("clearFirst"):
                            c.append("--clear")
                        if st.get("submitAfter"):
                            c.append("--submit")
                            if st.get("submitKey"):
                                c.extend(["--submit-key", str(st["submitKey"])])
                        if not respect_human_guard:
                            c.append("--skip-human-check")
                        _pace_if_needed()
                        with _acquire_hid(action):
                            out_p = self.engine._run_native(c, timeout=18.0)
                        foreground_hid_steps += 1
                        if not dry_run:
                            self._lanes.update_lane(run_id, delta_hid=1)
                        return out_p

                    res = _exec_paste(pt)
                    healed_here = False
                    if not res.get("ok") and self_heal:
                        latest_inspect = self.engine._run_native(["app-use-inspect", *_app_args()], timeout=16.0)
                        heal = self._propose_self_heal(
                            step=st,
                            error_msg=str(res.get("error") or "focus_and_type failed"),
                            live_inspect=latest_inspect,
                            agent_id=heal_agent_id,
                            pre_state=last_pre_state,
                        )
                        strat = str(heal.get("strategy") or "")
                        if strat == "pause_for_human":
                            paused_for_human = True
                            healing_events.append(
                                {
                                    "step": idx,
                                    "action": action,
                                    "failureCategory": heal.get("failureCategory", "AUTH_GATE"),
                                    "reason": heal.get("reason", ""),
                                    "source": heal.get("source", ""),
                                }
                            )
                            step_results.append(
                                {
                                    "step": idx,
                                    "action": action,
                                    "title": st.get("title", ""),
                                    "status": "paused_for_human",
                                    "failureCategory": heal.get("failureCategory", "AUTH_GATE"),
                                    "message": heal.get("reason", ""),
                                }
                            )
                            break
                        if strat == "reactivate_and_retry":
                            _pace_if_needed()
                            with _acquire_hid("heal_reactivate"):
                                self.engine._run_native(["app-use-activate", *_app_args()], timeout=14.0)
                            latest_inspect = self.engine._run_native(["app-use-inspect", *_app_args()], timeout=16.0)
                        elif strat == "dismiss_and_retry" and heal.get("dismissCombo"):
                            _pace_if_needed()
                            with _acquire_hid("heal_dismiss"):
                                self.engine._run_native(["press-key", *_app_args(), "--combo", str(heal["dismissCombo"])], timeout=8.0)
                            latest_inspect = self.engine._run_native(["app-use-inspect", *_app_args()], timeout=16.0)
                        if strat in ("retry_step", "dismiss_and_retry", "reactivate_and_retry") and isinstance(heal.get("patchedStep"), dict):
                            st_patched = dict(st, **heal["patchedStep"])
                            retry_pt, retry_src = self._resolve_element_point(st_patched, latest_inspect)
                            if retry_pt is None:
                                retry_pt, retry_src = self._fuzzy_resolve_point(st_patched, latest_inspect)
                            res2 = _exec_paste(retry_pt)
                            if res2.get("ok"):
                                res = res2
                                pt, source = retry_pt, retry_src
                                healed_here = True
                                healing_events.append(
                                    {
                                        "step": idx,
                                        "action": action,
                                        "failureCategory": heal.get("failureCategory", ""),
                                        "confidence": heal.get("confidence"),
                                        "margin": heal.get("margin"),
                                        "reason": heal.get("reason", ""),
                                        "source": heal.get("source", ""),
                                    }
                                )
                                _maybe_archive_patch(idx, st_patched, str(heal.get("reason") or "input re-anchor"))

                    last_action_sig = step_action_signature(st)
                    if pt is not None:
                        self.engine.human_guard.record_rpa_action(action=f"app_use:{action}", cursor_x=pt[0], cursor_y=pt[1])
                    else:
                        self.engine.human_guard.record_rpa_action(action=f"app_use:{action}")
                    type_rec: Dict[str, Any] = {
                        "step": idx,
                        "action": action,
                        "title": st.get("title", ""),
                        "ok": bool(res.get("ok")),
                        "selfHealed": healed_here,
                        "verified": bool(res.get("verified")),
                        "submitted": bool(res.get("submitted")),
                        "dispatchChannel": "foreground_hid_fallback" if headless_fallback_reason else "foreground_hid",
                        "readbackSource": res.get("readbackSource", ""),
                        "readbackPreview": res.get("readbackPreview", ""),
                        "resolutionSource": source,
                        "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                        "error": res.get("error", ""),
                    }
                    if headless_fallback_reason:
                        type_rec["headlessFallbackReason"] = headless_fallback_reason
                    step_results.append(type_rec)
                    if not res.get("ok"):
                        lane_error = str(res.get("error") or "focus_and_type failed")
                        return {
                            "ok": False,
                            "runId": run_id,
                            "dryRun": False,
                            "failedStep": idx,
                            "error": lane_error,
                            "riskProfile": risk_profile,
                            "dispatchSummary": _dispatch_summary(),
                            "hidLeaseWaitMs": round(hid_lease_wait_ms, 2),
                            "capturedVars": captured_vars,
                            "healingEvents": healing_events,
                            "stepResults": step_results,
                        }
                    continue

                if action == "press_shortcut":
                    if last_pre_state is None and any(bool(s.get("waitUntilChanged")) for s in raw_steps[len(step_results):]):
                        pre_probe = self.engine._run_native(
                            ["app-use-inspect", "--no-activate", "--skip-ocr", "--max-nodes", "90", *_app_args()],
                            timeout=3.5,
                        )
                        if pre_probe.get("ok"):
                            last_pre_state = compute_ui_state(pre_probe, bundle_id=bid)
                    cmd = ["press-key", *_app_args()]
                    if str(st.get("sequence") or "").strip():
                        cmd.extend(["--sequence", str(st["sequence"]).strip()])
                    else:
                        cmd.extend(["--combo", str(st.get("combo") or "return").strip()])
                    if st.get("delayMs"):
                        cmd.extend(["--delay-ms", str(int(st["delayMs"]))])
                    _pace_if_needed()
                    with _acquire_hid(action):
                        res = self.engine._run_native(cmd, timeout=12.0)
                    foreground_hid_steps += 1
                    if not dry_run:
                        self._lanes.update_lane(run_id, delta_hid=1)
                    last_action_sig = step_action_signature(st)
                    self.engine.human_guard.record_rpa_action(action=f"app_use:{action}")
                    step_results.append(
                        {
                            "step": idx,
                            "action": action,
                            "title": st.get("title", ""),
                            "ok": bool(res.get("ok")),
                            "dispatchChannel": "foreground_hid",
                            "posted": res.get("posted", []),
                            "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                            "error": res.get("error", ""),
                        }
                    )
                    if not res.get("ok"):
                        lane_error = str(res.get("error") or "press_shortcut failed")
                        return {
                            "ok": False,
                            "runId": run_id,
                            "dryRun": False,
                            "failedStep": idx,
                            "error": lane_error,
                            "riskProfile": risk_profile,
                            "dispatchSummary": _dispatch_summary(),
                            "hidLeaseWaitMs": round(hid_lease_wait_ms, 2),
                            "capturedVars": captured_vars,
                            "healingEvents": healing_events,
                            "stepResults": step_results,
                        }
                    continue

                if action == "scroll":
                    if latest_inspect is None:
                        latest_inspect = self.engine._run_native(["app-use-inspect", *_app_args()], timeout=14.0)
                    if latest_inspect and latest_inspect.get("ok"):
                        last_pre_state = compute_ui_state(latest_inspect, bundle_id=bid)
                    pt, source = self._resolve_element_point(
                        {"relX": st.get("relX", 0.5), "relY": st.get("relY", 0.5), **st},
                        latest_inspect,
                    )
                    sx, sy = pt if pt else (400.0, 400.0)
                    dy = int(st.get("dy") or -360)
                    _pace_if_needed()
                    with _acquire_hid(action):
                        res = self.engine._run_native(
                            ["scroll", "--x", str(sx), "--y", str(sy), "--dy", str(dy), "--units", "pixel"],
                            timeout=10.0,
                        )
                    foreground_hid_steps += 1
                    if not dry_run:
                        self._lanes.update_lane(run_id, delta_hid=1)
                    last_action_sig = step_action_signature(st)
                    self.engine.human_guard.record_rpa_action(action=f"app_use:{action}", cursor_x=sx, cursor_y=sy)
                    step_results.append(
                        {
                            "step": idx,
                            "action": action,
                            "title": st.get("title", ""),
                            "ok": bool(res.get("ok")),
                            "dispatchChannel": "foreground_hid",
                            "resolutionSource": source,
                            "dy": dy,
                            "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                        }
                    )
                    continue

                if action == "wait_and_read":
                    if not dry_run:
                        self._lanes.update_lane(run_id, state="observing", current_action=action)
                    delay_sec = max(0.02, min(12.0, float(st.get("delaySec") or 0.5)))
                    time.sleep(delay_sec)
                    png = runs_dir / f"{run_id}_step{idx}.png"
                    res = self.engine._run_native(_inspect_args(st, out_png=png), timeout=20.0)
                    polls = 1

                    if bool(st.get("waitUntilChanged")) and res.get("ok"):
                        pre_texts = list((last_pre_state or {}).get("textsPreview") or [])
                        if pre_texts:
                            chg_deadline = time.perf_counter() + min(8.0, max(1.0, float(st.get("maxWaitSec") or 6.0)))
                            chg_interval = max(0.05, min(1.5, float(st.get("pollIntervalSec") or 0.35)))
                            cur_state = compute_ui_state(res, bundle_id=bid)
                            while list(cur_state.get("textsPreview") or []) == pre_texts and time.perf_counter() < chg_deadline:
                                time.sleep(chg_interval)
                                nxt_chg = self.engine._run_native(_inspect_args(st, out_png=png), timeout=20.0)
                                polls += 1
                                if not nxt_chg.get("ok"):
                                    break
                                res = nxt_chg
                                cur_state = compute_ui_state(res, bundle_id=bid)

                    if bool(st.get("waitUntilStable")) and res.get("ok"):
                        max_wait = max(1.0, min(30.0, float(st.get("maxWaitSec") or 12.0)))
                        poll_interval = max(0.35, min(4.0, float(st.get("pollIntervalSec") or 1.4)))
                        prev_sig = f"{res.get('ocrPreview', '')}|{'|'.join(res.get('axTexts') or [])}"
                        deadline = time.perf_counter() + max_wait
                        while time.perf_counter() < deadline:
                            time.sleep(poll_interval)
                            nxt = self.engine._run_native(_inspect_args(st, out_png=png), timeout=20.0)
                            polls += 1
                            if not nxt.get("ok"):
                                break
                            nxt_sig = f"{nxt.get('ocrPreview', '')}|{'|'.join(nxt.get('axTexts') or [])}"
                            res = nxt
                            if nxt_sig == prev_sig and nxt_sig.strip():
                                break
                            prev_sig = nxt_sig

                    expect = str(st.get("expectText") or "").strip()
                    matched_expect = True
                    if expect:
                        combined = f"{res.get('ocrPreview', '')}\n" + "\n".join(res.get("axTexts") or [])
                        matched_expect = expect.casefold() in combined.casefold()

                    healed_here = False
                    if (not res.get("ok") or not matched_expect) and self_heal:
                        heal = self._propose_self_heal(
                            step=st,
                            error_msg=f"expectText '{expect}' not matched",
                            live_inspect=res if res.get("ok") else latest_inspect,
                            agent_id=heal_agent_id,
                            pre_state=last_pre_state,
                        )
                        if heal.get("strategy") == "pause_for_human":
                            paused_for_human = True
                            healing_events.append(
                                {
                                    "step": idx,
                                    "action": action,
                                    "failureCategory": heal.get("failureCategory", "AUTH_GATE"),
                                    "reason": heal.get("reason", ""),
                                    "source": heal.get("source", ""),
                                }
                            )
                            step_results.append(
                                {
                                    "step": idx,
                                    "action": action,
                                    "title": st.get("title", ""),
                                    "status": "paused_for_human",
                                    "failureCategory": heal.get("failureCategory", "AUTH_GATE"),
                                    "message": heal.get("reason", ""),
                                }
                            )
                            break
                        if heal.get("strategy") == "retry_step":
                            time.sleep(min(2.5, float((heal.get("patchedStep") or {}).get("delaySec") or 1.0)))
                            res_retry = self.engine._run_native(_inspect_args(st, out_png=png), timeout=20.0)
                            polls += 1
                            if res_retry.get("ok"):
                                res = res_retry
                                if expect:
                                    combined = f"{res.get('ocrPreview', '')}\n" + "\n".join(res.get("axTexts") or [])
                                    matched_expect = expect.casefold() in combined.casefold()
                                if matched_expect:
                                    healed_here = True
                                    healing_events.append(
                                        {"step": idx, "action": action, "reason": heal.get("reason", ""), "source": heal.get("source", "")}
                                    )

                    clean_ax = [_clean_ui_text(x) for x in (res.get("axTexts") or []) if _clean_ui_text(x)]
                    if res.get("ok"):
                        latest_inspect = res
                        post_state = compute_ui_state(res, bundle_id=bid)
                        if last_pre_state:
                            try:
                                self.state_graph.record_transition(
                                    bid,
                                    app_name,
                                    last_pre_state,
                                    last_action_sig or "wait_and_read",
                                    post_state,
                                    ok=bool(matched_expect),
                                    latency_ms=round((time.perf_counter() - step_t0) * 1000.0, 1),
                                )
                            except Exception:
                                pass
                        last_pre_state = post_state
                        final_readback = {
                            "ocrPreview": res.get("ocrPreview", ""),
                            "axTexts": clean_ax,
                            "savedPath": res.get("savedPath", ""),
                            "artifactName": Path(str(res.get("savedPath") or "")).name if res.get("savedPath") else "",
                        }
                    cap = _capture_from_inspect(st, res)
                    step_results.append(
                        {
                            "step": idx,
                            "action": action,
                            "title": st.get("title", ""),
                            "ok": bool(res.get("ok")) and matched_expect,
                            "selfHealed": healed_here,
                            "matchedExpectation": matched_expect,
                            "expectText": expect,
                            "polls": polls,
                            "axTexts": clean_ax[:16],
                            "ocrPreview": str(res.get("ocrPreview") or "")[:480],
                            "savedPath": res.get("savedPath", ""),
                            "artifactName": Path(str(res.get("savedPath") or "")).name if res.get("savedPath") else "",
                            "captured": {cap[0]: cap[1]} if cap else None,
                            "elapsedMs": round((time.perf_counter() - step_t0) * 1000.0, 1),
                        }
                    )
                    continue

            lane_ok = True
            lane_final_state = "paused_for_human" if paused_for_human else "done"
        finally:
            if not dry_run:
                self._lanes.finish_lane(run_id, ok=lane_ok, state=lane_final_state, error=lane_error)

        readiness = score_workflow_readiness(wf)
        elapsed_total_ms = round((time.perf_counter() - t_start) * 1000.0, 1)
        if not dry_run and workflow_id and workflow_id in (self._state.get("workflows") or {}):
            try:
                stored_wf = self._state["workflows"][workflow_id]
                st_stats = dict(stored_wf.get("stats") or {})
                prev_runs = int(st_stats.get("runs") or 0)
                prev_succ = int(st_stats.get("successes") or 0)
                prev_heals = int(st_stats.get("heals") or 0)
                prev_avg = float(st_stats.get("avgElapsedMs") or 0.0)
                new_runs = prev_runs + 1
                step_all_ok = all(bool(r.get("ok", True)) for r in step_results if r.get("status") != "paused_for_human")
                new_succ = prev_succ + (1 if step_all_ok else 0)
                stored_wf["stats"] = {
                    "runs": new_runs,
                    "successes": new_succ,
                    "heals": prev_heals + len(healing_events),
                    "successRate": round(new_succ / float(new_runs), 3),
                    "avgElapsedMs": round(((prev_avg * prev_runs) + elapsed_total_ms) / float(new_runs), 1),
                    "lastRunAt": _utc_iso_now(),
                }
                stored_wf["readiness"] = readiness
                self._state["workflows"][workflow_id] = stored_wf
                self._save_store()
            except Exception:
                pass

        sg_summary = self.state_graph.summary()
        dispatch_summary = _dispatch_summary()
        run_doc = {
            "ok": True,
            "runId": run_id,
            "workflowId": wf.get("id", ""),
            "workflowName": wf.get("name", ""),
            "targetApp": tapp,
            "riskProfile": risk_profile,
            "dispatchSummary": dispatch_summary,
            "dryRun": bool(dry_run),
            "pausedForHuman": paused_for_human,
            "params": merged_params,
            "capturedVars": captured_vars,
            "healingEvents": healing_events,
            "workflowPatched": workflow_patched,
            "hidLeaseWaitMs": round(hid_lease_wait_ms, 2),
            "readiness": readiness,
            "stateGraphSummary": sg_summary,
            "stepsExecuted": len(step_results),
            "elapsedMs": elapsed_total_ms,
            "finalReadback": final_readback,
            "stepResults": step_results,
        }
        self._append_run_log(
            {
                "kind": "workflow",
                "runId": run_id,
                "workflowId": run_doc["workflowId"],
                "workflowName": run_doc["workflowName"],
                "targetApp": tapp.get("name") or tapp.get("bundleID") or "",
                "ok": True,
                "dryRun": bool(dry_run),
                "riskTier": risk_profile.get("tier", ""),
                "dispatchSummary": dispatch_summary,
                "stepsExecuted": len(step_results),
                "elapsedMs": run_doc["elapsedMs"],
                "capturedVars": captured_vars,
                "healingCount": len(healing_events),
                "artifactName": final_readback.get("artifactName", ""),
                "savedPath": final_readback.get("savedPath", ""),
            }
        )
        return run_doc

    # ------------------------------------------------------------------
    # Autonomous Observe -> Think -> Act -> Verify Explorer (v2.7.0)
    # ------------------------------------------------------------------

    def explore_and_build_sop(
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
        """Iteratively observe UI, consult selected Agent per turn, verify actions, and compile SOP."""
        clean_goal = str(goal or "").strip()
        if not clean_goal:
            return {"ok": False, "error_code": "missing_goal", "error": "请提供自主探索目标。"}
        if not (str(bundle_id or "").strip() or str(app_name or "").strip() or str(app_path or "").strip()):
            return {"ok": False, "error_code": "missing_target_app", "error": "请指定目标应用。"}
        if not dry_run and not confirm_run:
            return {"ok": False, "error_code": "confirmation_required", "error": "实机自主探索需要 confirm_run=true。"}
        if not dry_run and respect_human_guard:
            guard = self.engine.human_guard.check_can_operate()
            if not guard.get("canOperate", True):
                return {"ok": False, "error_code": "human_activity_guard_paused", "humanGuard": guard, "error": "用户正在操作键鼠，防抢鼠标守卫已暂停实机探索。"}

        target_meta = self._resolve_target_meta(bundle_id=bundle_id, app_name=app_name, app_path=app_path)
        eff_bid = str(target_meta.get("bundleID") or bundle_id or "")
        catalog = self.list_builder_agents(refresh_models=False)
        chosen_agent_id = str(agent_id or "").strip() or str(catalog.get("defaultAgentId") or "local:heuristic")
        turns_cap = max(1, min(10, int(max_turns)))
        trace_steps: List[Dict[str, Any]] = []
        turn_logs: List[Dict[str, Any]] = []
        transition_logs: List[Dict[str, Any]] = []
        visited_state_actions: Set[str] = set()
        stagnant_pairs: Set[str] = set()
        stagnant_streak = 0
        latest_insp: Optional[Dict[str, Any]] = None
        verification = ""
        used_fallback = False

        heuristic_seed = self._build_heuristic_plan(target_meta=target_meta, goal=clean_goal, inspection=None).get("steps") or []

        for turn in range(1, turns_cap + 1):
            cur_insp: Optional[Dict[str, Any]] = None
            if dry_run and not target_meta.get("running") and not launch_if_needed:
                obs_ok = False
                ui_ctx: Dict[str, Any] = {"note": "dry-run 且目标应用未运行"}
                cur_state = compute_ui_state(None, bundle_id=eff_bid)
                cur_arch = infer_app_archetype(None, target_meta=target_meta)
            else:
                insp = self.inspect_app(
                    bundle_id=str(target_meta.get("bundleID") or bundle_id),
                    app_name=str(target_meta.get("name") or app_name),
                    app_path=str(target_meta.get("appPath") or app_path),
                    launch_if_needed=launch_if_needed if not dry_run else False,
                    allow_activate=not dry_run,
                    max_nodes=180,
                )
                cur_insp = insp
                obs_ok = bool(insp.get("ok"))
                if obs_ok:
                    latest_insp = insp
                ui_ctx = insp.get("uiSummary") or {"note": insp.get("error") or "no_window"}
                cur_state = insp.get("uiState") or compute_ui_state(insp if obs_ok else None, bundle_id=eff_bid)
                cur_arch = insp.get("archetype") or infer_app_archetype(insp if obs_ok else None, target_meta=target_meta)

            modal_status = cur_state.get("modalStatus") or {"kind": "none", "requiresHuman": False}
            if modal_status.get("kind") == "auth_or_risk_gate":
                gate_step = {
                    "step": len(trace_steps) + 1,
                    "action": "pause_for_human",
                    "title": "人工认证/高风险确认门禁",
                    "description": f"检测到敏感界面 ({', '.join(modal_status.get('signals') or [])})，暂停交由人工接管",
                    "message": f"请先完成登录/授权/确认后再继续：{', '.join(modal_status.get('signals') or [])}",
                }
                trace_steps.append(gate_step)
                turn_logs.append({"turn": turn, "done": True, "modalGate": modal_status, "reason": "auth_or_risk_gate"})
                break
            if modal_status.get("kind") == "dismissible_modal" and not dry_run:
                esc_step = {
                    "step": len(trace_steps) + 1,
                    "action": "press_shortcut",
                    "title": "关闭干扰弹窗",
                    "combo": str(modal_status.get("dismissCombo") or "escape"),
                }
                self.run_workflow(
                    workflow={"id": "explore_tmp", "name": "explore", "targetApp": target_meta, "steps": [esc_step]},
                    dry_run=False,
                    confirm_run=True,
                    respect_human_guard=respect_human_guard,
                    self_heal=False,
                )
                turn_logs.append({"turn": turn, "done": False, "modalDismissed": modal_status, "step": esc_step})
                continue

            known_edges = self.state_graph.suggest_known_transitions(eff_bid, str(cur_state.get("stateHash") or ""))
            decision: Optional[Dict[str, Any]] = None
            if not chosen_agent_id.startswith("local:"):
                sys_p = (
                    "你是自主 App-Use 探索代理（Observe->Think->Act 循环）。"
                    "请基于业务目标、UI Archetype 原型提示、当前界面状态、状态图谱历史边及已执行历史，决定下一步单个原子动作或结束。\n"
                    "禁止重复 blockedStagnantActions 中的无效状态+动作组合。\n"
                    "只输出严格 JSON：\n"
                    '{"done": false, "reason": "判断理由", "nextStep": {"action": "activate_app|inspect_ui|click_element|focus_and_type|press_shortcut|scroll|wait_and_read|pause_for_human", "title": "...", ...}, "verification": "可选验收标准"}\n'
                    "action 只允许上述枚举；当目标步骤已完备或需收尾时设 done=true。"
                )
                user_p = json.dumps(
                    {
                        "goal": clean_goal,
                        "turn": turn,
                        "maxTurns": turns_cap,
                        "targetApp": {"bundleID": target_meta.get("bundleID"), "name": target_meta.get("name"), "isAgentApp": target_meta.get("isAgentApp")},
                        "archetype": {"id": cur_arch.get("id"), "strategyHints": cur_arch.get("strategyHints")},
                        "stateHash": cur_state.get("stateHash"),
                        "blockedStagnantActions": sorted(stagnant_pairs)[-12:],
                        "knownTransitions": [
                            {"actionSig": e.get("actionSig"), "stateChangedCount": e.get("stateChangedCount")}
                            for e in known_edges[:5]
                        ],
                        "previousSteps": trace_steps,
                        "currentUI": ui_ctx,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                if chosen_agent_id.startswith("cli:"):
                    cli_r = self._invoke_cli_agent(bin_name=chosen_agent_id.split(":", 1)[1], sys_prompt=sys_p, user_prompt=user_p)
                    if cli_r.get("ok"):
                        decision = _extract_json_object(str(cli_r.get("replyText") or ""))
                else:
                    mid = chosen_agent_id.split(":", 1)[1] if chosen_agent_id.startswith("magpie:") else chosen_agent_id
                    llm_r = self.engine.models.generate_chat_reply(
                        [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
                        model_id=mid,
                        max_tokens=700,
                        temperature=0.2,
                        timeout=25.0,
                    )
                    if llm_r.get("ok"):
                        decision = _extract_json_object(str(llm_r.get("replyText") or ""))
                if decision is None:
                    used_fallback = True

            if decision is None:
                if turn - 1 < len(heuristic_seed):
                    decision = {"done": False, "reason": "启发式探索推进", "nextStep": heuristic_seed[turn - 1]}
                else:
                    decision = {"done": True, "reason": "探索序列已完成", "verification": "确认目标界面状态符合预期"}

            if decision.get("verification"):
                verification = str(decision["verification"])
            if decision.get("done"):
                turn_logs.append({"turn": turn, "done": True, "reason": decision.get("reason", "")})
                break

            norm_list = self._normalize_steps([decision.get("nextStep")])
            if not norm_list:
                turn_logs.append({"turn": turn, "done": True, "reason": "Agent 返回空动作，结束探索"})
                break
            step_obj = dict(norm_list[0])
            step_obj["step"] = len(trace_steps) + 1
            sig_key = f"{cur_state.get('stateHash')}|{step_action_signature(step_obj)}"

            if sig_key in stagnant_pairs:
                turn_logs.append(
                    {
                        "turn": turn,
                        "done": True,
                        "cycleBroken": True,
                        "reason": f"防死循环拦截：禁止在同一状态重复无效动作 {step_action_signature(step_obj)}",
                    }
                )
                break
            visited_state_actions.add(sig_key)

            exec_receipt = self.run_workflow(
                workflow={"id": "explore_tmp", "name": "explore", "targetApp": target_meta, "steps": [step_obj]},
                dry_run=dry_run,
                confirm_run=confirm_run,
                respect_human_guard=respect_human_guard,
                self_heal=False,
            )
            trace_steps.append(step_obj)

            state_changed: Optional[bool] = None
            if not dry_run and exec_receipt.get("ok") and step_obj.get("action") not in ("activate_app", "inspect_ui", "wait_and_read"):
                post_obs = self.inspect_app(
                    bundle_id=str(target_meta.get("bundleID") or bundle_id),
                    app_name=str(target_meta.get("name") or app_name),
                    app_path=str(target_meta.get("appPath") or app_path),
                    launch_if_needed=False,
                    allow_activate=False,
                    max_nodes=140,
                )
                if post_obs.get("ok"):
                    latest_insp = post_obs
                    post_state = post_obs.get("uiState") or compute_ui_state(post_obs, bundle_id=eff_bid)
                    diff = diff_ui_states(cur_state, post_state)
                    state_changed = bool(diff.get("stateChanged"))
                    transition_logs.append(
                        {"stepIndex": step_obj["step"], "actionSig": step_action_signature(step_obj), "stateChanged": state_changed}
                    )
                    if not state_changed:
                        stagnant_pairs.add(sig_key)
                        stagnant_streak += 1
                    else:
                        stagnant_streak = 0

            turn_logs.append(
                {
                    "turn": turn,
                    "done": False,
                    "reason": decision.get("reason", ""),
                    "step": step_obj,
                    "ok": bool(exec_receipt.get("ok")),
                    "stateChanged": state_changed,
                    "readback": (exec_receipt.get("finalReadback") or {}).get("ocrPreview", "")[:200],
                }
            )
            if stagnant_streak >= 2 or (not exec_receipt.get("ok") and not dry_run):
                break

        if not trace_steps:
            trace_steps = self._normalize_steps(heuristic_seed)
        optimized_steps = optimize_and_enrich_steps(trace_steps, inspection=latest_insp, transition_logs=transition_logs)
        final_arch = infer_app_archetype(latest_insp, target_meta=target_meta)

        # Infer parameters from {{var}} placeholders
        inferred_names: List[str] = []
        for match in re.findall(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}", json.dumps(optimized_steps, ensure_ascii=False)):
            if match not in inferred_names:
                inferred_names.append(match)
        params = [
            {"name": n, "label": n, "defaultValue": "", "required": True, "description": "自主探索识别的动态参数"}
            for n in inferred_names
        ]

        slug = _slugify(str(target_meta.get("name") or target_meta.get("bundleID") or "app"), "app")
        digest = hashlib.sha1(f"explore|{target_meta.get('bundleID')}|{clean_goal}|{time.time()}".encode("utf-8")).hexdigest()[:8]
        now_iso = _utc_iso_now()
        workflow: Dict[str, Any] = {
            "id": f"wf_exp_{slug}_{digest}",
            "version": 1,
            "revisionHistory": [],
            "mode": "autonomous_explore",
            "verifiedByExploration": not dry_run,
            "name": f"{target_meta.get('name')} · 自主探索 SOP ({clean_goal[:20]})",
            "goal": clean_goal,
            "summary": f"经 {len(turn_logs)} 轮 Observe->Think->Act 自主探索验证生成：{clean_goal}",
            "targetApp": target_meta,
            "archetype": final_arch,
            "builderAgent": {
                "agentId": chosen_agent_id,
                "usedFallback": used_fallback,
                "turns": len(turn_logs),
            },
            "parameters": params,
            "preconditions": [f"已安装 {target_meta.get('name')}"],
            "safetyGates": ["支持 Dry-Run、状态环断路器与实机防抢鼠标门禁"],
            "steps": self._normalize_steps(optimized_steps),
            "verification": verification or "探索末步截屏与 OCR 符合目标预期",
            "uiProfileSnapshot": (latest_insp or {}).get("uiSummary") or {},
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }
        workflow["readiness"] = score_workflow_readiness(workflow)
        workflow["sopMarkdown"] = self._render_sop_markdown(workflow)
        if save:
            self.save_workflow(workflow, sop_markdown=workflow["sopMarkdown"])

        return {
            "ok": True,
            "dryRun": bool(dry_run),
            "turns": len(turn_logs),
            "turnLogs": turn_logs,
            "archetype": final_arch,
            "readiness": workflow["readiness"],
            "workflow": workflow,
            "sopMarkdown": workflow["sopMarkdown"],
        }

    # ------------------------------------------------------------------
    # Cross-App Multi-Stage Pipelines (v2.7.0)
    # ------------------------------------------------------------------

    def list_pipelines(self) -> Dict[str, Any]:
        pmap = self._pipelines_state.get("pipelines") or {}
        order = self._pipelines_state.get("order") or list(pmap.keys())
        items = [pmap[pid] for pid in order if isinstance(pmap.get(pid), dict)]
        return {"ok": True, "count": len(items), "pipelines": items, "path": str(self.pipelines_path)}

    def save_pipeline(self, pipeline: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(pipeline, dict):
            return {"ok": False, "error": "pipeline must be an object"}
        p = dict(pipeline)
        pid = str(p.get("id") or "").strip()
        if not pid:
            pid = f"pipe_{_slugify(str(p.get('name') or 'chain'))}_{int(time.time())}"
            p["id"] = pid
        p["updatedAt"] = _utc_iso_now()
        if not p.get("createdAt"):
            p["createdAt"] = p["updatedAt"]
        pmap = self._pipelines_state.setdefault("pipelines", {})
        pmap[pid] = p
        order = [x for x in (self._pipelines_state.get("order") or []) if x != pid]
        self._pipelines_state["order"] = [pid] + order
        self._save_pipelines()
        return {"ok": True, "pipeline": p, "count": len(pmap)}

    def delete_pipeline(self, pipeline_id: str) -> Dict[str, Any]:
        pid = str(pipeline_id or "").strip()
        pmap = self._pipelines_state.setdefault("pipelines", {})
        existed = pid in pmap
        pmap.pop(pid, None)
        self._pipelines_state["order"] = [x for x in (self._pipelines_state.get("order") or []) if x != pid]
        self._save_pipelines()
        return {"ok": True, "deleted": existed, "pipelineId": pid, "count": len(pmap)}

    def run_pipeline(
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
        """Run a multi-stage cross-app pipeline, piping captured variables between apps."""
        if pipeline_id:
            stored = (self._pipelines_state.get("pipelines") or {}).get(str(pipeline_id).strip())
            if not isinstance(stored, dict):
                return {"ok": False, "error_code": "pipeline_not_found", "error": f"未找到流水线 {pipeline_id}"}
            pipe = dict(stored)
        elif isinstance(pipeline, dict):
            pipe = dict(pipeline)
        else:
            return {"ok": False, "error_code": "missing_pipeline", "error": "请提供 pipeline_id 或 pipeline 定义"}

        if not dry_run and not confirm_run:
            return {"ok": False, "error_code": "confirmation_required", "error": "实机联跑跨应用流水线需 confirm_run=true。"}

        stages = list(pipe.get("stages") or [])
        if not stages:
            return {"ok": False, "error_code": "empty_pipeline", "error": "流水线至少包含 1 个阶段"}

        context_vars: Dict[str, Any] = dict(initial_params or {})
        stage_results: List[Dict[str, Any]] = []
        t0 = time.perf_counter()
        paused = False

        for i, raw_stage in enumerate(stages, start=1):
            if not isinstance(raw_stage, dict):
                continue
            wf_id = str(raw_stage.get("workflowId") or "").strip() or None
            inline_wf = raw_stage.get("workflow") if isinstance(raw_stage.get("workflow"), dict) else None
            mapping = raw_stage.get("paramMapping") if isinstance(raw_stage.get("paramMapping"), dict) else {}
            stage_params = dict(context_vars)
            for k, v in mapping.items():
                stage_params[str(k)] = _substitute_params(v, context_vars)

            res = self.run_workflow(
                workflow_id=wf_id,
                workflow=inline_wf,
                params=stage_params,
                dry_run=dry_run,
                confirm_run=confirm_run,
                respect_human_guard=respect_human_guard,
                self_heal=self_heal,
            )
            rb = res.get("finalReadback") or {}
            cap_vars = dict(res.get("capturedVars") or {})
            context_vars.update(cap_vars)
            if rb.get("ocrPreview"):
                context_vars[f"stage_{i}_ocr"] = _clean_ui_text(rb["ocrPreview"])
            ax_list = rb.get("axTexts") or []
            if ax_list:
                context_vars[f"stage_{i}_ax_last"] = _clean_ui_text(ax_list[-1])

            stage_results.append(
                {
                    "stage": i,
                    "name": raw_stage.get("name") or res.get("workflowName") or f"Stage {i}",
                    "ok": bool(res.get("ok")),
                    "workflowId": wf_id or "",
                    "targetApp": (res.get("targetApp") or {}).get("name") or "",
                    "capturedVars": cap_vars,
                    "finalReadback": rb,
                    "stepsExecuted": res.get("stepsExecuted", 0),
                    "elapsedMs": res.get("elapsedMs", 0.0),
                    "error": res.get("error", ""),
                    "stepResults": res.get("stepResults", []),
                }
            )
            if res.get("pausedForHuman"):
                paused = True
                break
            if not res.get("ok") and not raw_stage.get("continueOnError"):
                return {
                    "ok": False,
                    "pipelineId": pipe.get("id", ""),
                    "pipelineName": pipe.get("name", ""),
                    "dryRun": bool(dry_run),
                    "failedStage": i,
                    "error": res.get("error") or f"Stage {i} failed",
                    "contextVars": context_vars,
                    "stageResults": stage_results,
                }

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        last_rb = stage_results[-1].get("finalReadback") or {} if stage_results else {}
        self._append_run_log(
            {
                "kind": "pipeline",
                "runId": f"pipe_run_{int(time.time() * 1000)}",
                "pipelineId": pipe.get("id", ""),
                "pipelineName": pipe.get("name", "跨应用流水线"),
                "ok": True,
                "dryRun": bool(dry_run),
                "stagesExecuted": len(stage_results),
                "elapsedMs": elapsed_ms,
                "contextVars": context_vars,
                "artifactName": last_rb.get("artifactName", ""),
                "savedPath": last_rb.get("savedPath", ""),
            }
        )
        return {
            "ok": True,
            "pipelineId": pipe.get("id", ""),
            "pipelineName": pipe.get("name", "跨应用流水线"),
            "dryRun": bool(dry_run),
            "pausedForHuman": paused,
            "stagesExecuted": len(stage_results),
            "elapsedMs": elapsed_ms,
            "contextVars": context_vars,
            "stageResults": stage_results,
        }

    # ------------------------------------------------------------------
    # Human Demo Recorder -> Auto-SOP Compiler (v2.7.0)
    # ------------------------------------------------------------------

    def start_recording(
        self,
        *,
        max_duration_sec: float = 180.0,
        poll_interval_sec: float = 0.45,
        target_bundle_id: str = "",
    ) -> Dict[str, Any]:
        """Start read-only polling of foreground app switches, cursor AX clicks, and text inputs."""
        with self._rec_lock:
            if self._rec_active:
                return {
                    "ok": True,
                    "alreadyActive": True,
                    "sessionId": self._rec_session_id,
                    "eventCount": len(self._rec_events),
                }
            self._rec_active = True
            self._rec_stop_event.clear()
            self._rec_events = []
            self._rec_started_at = _utc_iso_now()
            self._rec_started_mono = time.perf_counter()
            self._rec_session_id = f"rec_{int(time.time() * 1000)}"
            session_id = self._rec_session_id
            max_dur = max(5.0, min(600.0, float(max_duration_sec)))
            interval = max(0.2, min(2.0, float(poll_interval_sec)))
            bid_filter = str(target_bundle_id or "").strip().casefold()

            def _poll_loop() -> None:
                last_bid = ""
                last_win_title = ""
                last_text_val = ""
                last_click_sig = ""
                deadline = time.perf_counter() + max_dur
                while not self._rec_stop_event.is_set() and time.perf_counter() < deadline:
                    snap = self.engine._run_native(["app-use-focus-snapshot"], timeout=2.5)
                    if snap.get("ok"):
                        bid = str(snap.get("bundleID") or "")
                        if not bid_filter or bid.casefold() == bid_filter:
                            name = str(snap.get("name") or bid)
                            win_title = str(((snap.get("window") or {}).get("title")) or "")
                            hid = snap.get("hid") or {}
                            focused = snap.get("focusedElement") or {}
                            under = snap.get("elementUnderCursor") or {}

                            with self._rec_lock:
                                if not self._rec_active:
                                    break
                                if bid and bid != last_bid:
                                    last_bid = bid
                                    self._rec_events.append(
                                        {
                                            "type": "app_activated",
                                            "tsMs": snap.get("tsMs"),
                                            "bundleID": bid,
                                            "appName": name,
                                            "windowTitle": win_title,
                                        }
                                    )
                                elif win_title and win_title != last_win_title and last_bid == bid:
                                    self._rec_events.append(
                                        {
                                            "type": "window_changed",
                                            "tsMs": snap.get("tsMs"),
                                            "bundleID": bid,
                                            "appName": name,
                                            "windowTitle": win_title,
                                        }
                                    )
                                last_win_title = win_title

                                click_idle = hid.get("mouseClickIdleSeconds")
                                if click_idle is not None and float(click_idle) <= max(interval * 1.4, 0.7):
                                    c_label = str(under.get("title") or under.get("description") or under.get("identifier") or "")
                                    c_role = str(under.get("role") or "")
                                    sig = f"{bid}|{c_label}|{under.get('relCenter')}"
                                    if sig != last_click_sig and (c_label or snap.get("cursorRelPoint")):
                                        last_click_sig = sig
                                        self._rec_events.append(
                                            {
                                                "type": "element_clicked",
                                                "tsMs": snap.get("tsMs"),
                                                "bundleID": bid,
                                                "appName": name,
                                                "role": c_role,
                                                "targetAxId": str(under.get("identifier") or ""),
                                                "targetAxTitle": c_label,
                                                "relCenter": under.get("relCenter") or snap.get("cursorRelPoint"),
                                            }
                                        )

                                f_val = str(focused.get("value") or "").strip()
                                if f_val and f_val != last_text_val and len(f_val) <= 300:
                                    last_text_val = f_val
                                    self._rec_events.append(
                                        {
                                            "type": "text_entered",
                                            "tsMs": snap.get("tsMs"),
                                            "bundleID": bid,
                                            "appName": name,
                                            "targetAxId": str(focused.get("identifier") or ""),
                                            "role": str(focused.get("role") or ""),
                                            "relCenter": focused.get("relCenter"),
                                            "text": f_val,
                                        }
                                    )

                                if len(self._rec_events) >= 120:
                                    self._rec_active = False
                                    break
                    self._rec_stop_event.wait(interval)

                with self._rec_lock:
                    self._rec_active = False

            th = threading.Thread(target=_poll_loop, name="AppUseDemoRecorder", daemon=True)
            self._rec_thread = th
            th.start()

        return {
            "ok": True,
            "active": True,
            "sessionId": session_id,
            "startedAt": self._rec_started_at,
            "maxDurationSec": max_dur,
        }

    def recording_status(self) -> Dict[str, Any]:
        with self._rec_lock:
            elapsed = round(time.perf_counter() - self._rec_started_mono, 1) if self._rec_started_mono and self._rec_active else 0.0
            return {
                "ok": True,
                "active": bool(self._rec_active),
                "sessionId": self._rec_session_id,
                "startedAt": self._rec_started_at,
                "elapsedSec": elapsed,
                "eventCount": len(self._rec_events),
                "eventsPreview": list(self._rec_events[-20:]),
            }

    def compile_recorded_events(
        self,
        events: List[Dict[str, Any]],
        *,
        goal_hint: str = "",
        agent_id: str = "",
        save: bool = True,
    ) -> Dict[str, Any]:
        """Compile recorded user demonstration events into a parameterized SOP & RPA workflow."""
        clean_events = [e for e in (events or []) if isinstance(e, dict)]
        if not clean_events:
            return {"ok": False, "error_code": "no_recorded_events", "error": "未录制到有效操作事件（请先在目标应用窗口点击或输入）。"}

        first_bid = next((str(e.get("bundleID") or "") for e in clean_events if e.get("bundleID")), "")
        first_name = next((str(e.get("appName") or "") for e in clean_events if e.get("appName")), first_bid or "Recorded App")
        target_meta = self._resolve_target_meta(bundle_id=first_bid, app_name=first_name)

        # Deterministic baseline compilation from events
        heuristic_steps: List[Dict[str, Any]] = [
            {"step": 1, "action": "activate_app", "title": f"唤醒 {target_meta.get('name')}", "launchIfNeeded": True}
        ]
        inferred_params: List[Dict[str, Any]] = []
        param_idx = 1
        for ev in clean_events[:20]:
            etype = str(ev.get("type") or "")
            if etype == "element_clicked":
                rel = ev.get("relCenter") or {}
                step_item: Dict[str, Any] = {
                    "step": len(heuristic_steps) + 1,
                    "action": "click_element",
                    "title": f"点击 {ev.get('targetAxTitle') or ev.get('role') or '目标控件'}",
                    "targetAxId": str(ev.get("targetAxId") or ""),
                    "targetAxTitle": str(ev.get("targetAxTitle") or ""),
                }
                if isinstance(rel, dict) and "x" in rel and "y" in rel:
                    step_item["relX"] = rel["x"]
                    step_item["relY"] = rel["y"]
                heuristic_steps.append(step_item)
            elif etype == "text_entered":
                p_name = "prompt" if param_idx == 1 and target_meta.get("isAgentApp") else f"input_{param_idx}"
                param_idx += 1
                txt_val = str(ev.get("text") or "")
                inferred_params.append(
                    {"name": p_name, "label": f"录制输入 #{len(inferred_params) + 1}", "defaultValue": txt_val, "required": True}
                )
                rel = ev.get("relCenter") or {}
                step_item = {
                    "step": len(heuristic_steps) + 1,
                    "action": "focus_and_type",
                    "title": f"输入参数 {{{{{p_name}}}}}",
                    "text": f"{{{{{p_name}}}}}",
                    "targetAxId": str(ev.get("targetAxId") or ""),
                    "clearFirst": True,
                    "submitAfter": bool(target_meta.get("isAgentApp")),
                }
                if isinstance(rel, dict) and "x" in rel and "y" in rel:
                    step_item["relX"] = rel["x"]
                    step_item["relY"] = rel["y"]
                heuristic_steps.append(step_item)
        heuristic_steps.append(
            {
                "step": len(heuristic_steps) + 1,
                "action": "wait_and_read",
                "title": "回读录制流程执行结果",
                "delaySec": 0.6,
                "waitUntilStable": bool(target_meta.get("isAgentApp")),
                "saveScreenshot": True,
            }
        )

        catalog = self.list_builder_agents(refresh_models=False)
        chosen_agent_id = str(agent_id or "").strip() or str(catalog.get("defaultAgentId") or "local:heuristic")
        parsed_plan: Optional[Dict[str, Any]] = None
        used_fallback = False

        if not chosen_agent_id.startswith("local:"):
            sys_p = (
                "你是人类示范转 RPA/SOP 编译器。请把下面录制的操作轨迹整理成可复用、参数化的标准流程 JSON（含 name, summary, parameters, preconditions, safetyGates, steps, verification）。\n"
                "合法 actions: activate_app, inspect_ui, click_element, focus_and_type, press_shortcut, scroll, wait_and_read, pause_for_human。只输出纯 JSON。"
            )
            user_p = json.dumps(
                {
                    "goalHint": goal_hint or "将人类操作示范提炼为标准 SOP",
                    "targetApp": target_meta,
                    "recordedEvents": clean_events[:25],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if chosen_agent_id.startswith("cli:"):
                cli_r = self._invoke_cli_agent(bin_name=chosen_agent_id.split(":", 1)[1], sys_prompt=sys_p, user_prompt=user_p)
                if cli_r.get("ok"):
                    parsed_plan = _extract_json_object(str(cli_r.get("replyText") or ""))
            else:
                mid = chosen_agent_id.split(":", 1)[1] if chosen_agent_id.startswith("magpie:") else chosen_agent_id
                llm_r = self.engine.models.generate_chat_reply(
                    [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
                    model_id=mid,
                    max_tokens=1600,
                    temperature=0.2,
                    timeout=35.0,
                )
                if llm_r.get("ok"):
                    parsed_plan = _extract_json_object(str(llm_r.get("replyText") or ""))
            if parsed_plan is None or not self._normalize_steps(parsed_plan.get("steps")):
                used_fallback = True
                parsed_plan = None

        steps = self._normalize_steps((parsed_plan or {}).get("steps") or heuristic_steps)
        params = self._normalize_parameters((parsed_plan or {}).get("parameters")) or inferred_params
        slug = _slugify(str(target_meta.get("name") or "demo"), "demo")
        now_iso = _utc_iso_now()
        workflow: Dict[str, Any] = {
            "id": f"wf_rec_{slug}_{int(time.time())}",
            "version": 1,
            "revisionHistory": [],
            "mode": "recorded_demo",
            "name": str((parsed_plan or {}).get("name") or f"{target_meta.get('name')} · 示范录制 SOP"),
            "goal": goal_hint or "由人类桌面操作示范自动归纳",
            "summary": str((parsed_plan or {}).get("summary") or f"基于 {len(clean_events)} 条真实操作轨迹编译的复用流程"),
            "targetApp": target_meta,
            "builderAgent": {"agentId": chosen_agent_id, "usedFallback": used_fallback},
            "parameters": params,
            "preconditions": list((parsed_plan or {}).get("preconditions") or [f"已安装 {target_meta.get('name')}"]),
            "safetyGates": list((parsed_plan or {}).get("safetyGates") or ["实机重放前先运行 Dry-Run 校验"]),
            "steps": steps,
            "verification": str((parsed_plan or {}).get("verification") or "执行末步 OCR/AX 与示范终态一致"),
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }
        workflow["sopMarkdown"] = self._render_sop_markdown(workflow)
        if save:
            self.save_workflow(workflow, sop_markdown=workflow["sopMarkdown"])
        return {
            "ok": True,
            "eventCount": len(clean_events),
            "workflow": workflow,
            "sopMarkdown": workflow["sopMarkdown"],
        }

    def stop_recording_and_compile(
        self,
        *,
        goal_hint: str = "",
        agent_id: str = "",
        save: bool = True,
    ) -> Dict[str, Any]:
        with self._rec_lock:
            self._rec_active = False
            self._rec_stop_event.set()
            th = self._rec_thread
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
        with self._rec_lock:
            events = list(self._rec_events)
            session_id = self._rec_session_id
        compiled = self.compile_recorded_events(events, goal_hint=goal_hint, agent_id=agent_id, save=save)
        return {"sessionId": session_id, **compiled}

    # ------------------------------------------------------------------
    # Portable Agent Skill Exporter (v2.7.0)
    # ------------------------------------------------------------------

    def export_workflow_as_skill(self, workflow_id: str, *, out_dir: Optional[str] = None) -> Dict[str, Any]:
        """Export a saved App-Use workflow + SOP into a standalone portable Agent Skill folder."""
        wid = str(workflow_id or "").strip()
        wf = (self._state.get("workflows") or {}).get(wid)
        if not isinstance(wf, dict):
            return {"ok": False, "error_code": "workflow_not_found", "error": f"未找到流程 {wid}"}

        tapp = wf.get("targetApp") or {}
        slug = _slugify(f"{tapp.get('name', 'app')}_{wf.get('id', '')}", "app_use_skill")
        skill_name = f"appuse-{slug}".replace("_", "-")
        if out_dir and str(out_dir).strip():
            skill_dir = Path(str(out_dir).strip())
        else:
            skill_dir = _sandisk_artifact_dir(self.engine, "exported-skills") / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        wf_json_path = skill_dir / "workflow.json"
        atomic_write_json(wf_json_path, wf)

        params_example = {
            p["name"]: p.get("defaultValue", "")
            for p in (wf.get("parameters") or [])
            if isinstance(p, dict) and p.get("name")
        }
        sop_md = str(wf.get("sopMarkdown") or self._render_sop_markdown(wf))
        desc_safe = str(wf.get("summary") or wf.get("goal") or wf.get("name") or skill_name).replace('"', "'").replace("\n", " ")[:180]
        skill_md = "\n".join(
            [
                "---",
                f"name: {skill_name}",
                f'description: "{desc_safe}"',
                "---",
                "",
                f"# {wf.get('name') or skill_name}",
                "",
                f"- **Workflow ID**: `{wid}`",
                f"- **Target App**: {tapp.get('name', '')} (`{tapp.get('bundleID', '')}`)",
                "",
                "## How Any Agent Invokes This Skill",
                "",
                "### Option 1 — Via MCP (`app_use_run_workflow`)",
                "```json",
                json.dumps(
                    {
                        "tool": "app_use_run_workflow",
                        "arguments": {
                            "workflow_id": wid,
                            "params": params_example,
                            "dry_run": False,
                            "confirm_run": True,
                            "self_heal": True,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "### Option 2 — Via Local HTTP API (`http://127.0.0.1:18788`)",
                "```bash",
                "curl -s -X POST http://127.0.0.1:18788/api/app-use/run \\",
                '  -H "Content-Type: application/json" \\',
                f"  -d '{json.dumps({'workflow_id': wid, 'params': params_example, 'dry_run': True}, ensure_ascii=False)}'",
                "```",
                "",
                "## Standard Operating Procedure (SOP)",
                "",
                sop_md,
                "",
            ]
        )
        skill_md_path = skill_dir / "SKILL.md"
        skill_md_path.write_text(skill_md, encoding="utf-8")

        return {
            "ok": True,
            "workflowId": wid,
            "skillName": skill_name,
            "skillDir": str(skill_dir),
            "skillMdPath": str(skill_md_path),
            "workflowJsonPath": str(wf_json_path),
        }

    # ------------------------------------------------------------------
    # Flagship 4-Phase Unseen App Generalization & Concurrency (v2.8.0)
    # ------------------------------------------------------------------

    def get_state_graph(self, *, bundle_id: Optional[str] = None) -> Dict[str, Any]:
        """Return accumulated UI transition graph for a specific bundle_id or global summary."""
        return self.state_graph.get_app_graph(bundle_id=bundle_id)

    def generalize_new_app(
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
        """4-phase zero-hardcoding generalization pipeline: Inspect+Archetype -> Synthesize -> Optimize+Score -> DryRun+Export Skill."""
        clean_goal = str(goal or "").strip()
        if not clean_goal:
            return {"ok": False, "error_code": "missing_goal", "error": "请提供想要在新 App 上自动构建并打包的业务目标。"}
        if not (str(bundle_id or "").strip() or str(app_name or "").strip() or str(app_path or "").strip()):
            return {"ok": False, "error_code": "missing_target_app", "error": "请选择或指定目标应用。"}

        t0 = time.perf_counter()
        phases: List[Dict[str, Any]] = []
        target_meta = self._resolve_target_meta(bundle_id=bundle_id, app_name=app_name, app_path=app_path)

        # Phase 1: Live Inspection + Topology Archetype + UI State + Modal Classification
        insp = self.inspect_app(
            bundle_id=str(target_meta.get("bundleID") or bundle_id),
            app_name=str(target_meta.get("name") or app_name),
            app_path=str(target_meta.get("appPath") or app_path),
            launch_if_needed=launch_if_needed,
            allow_activate=True,
            max_nodes=240,
        )
        obs_ok = bool(insp.get("ok"))
        if obs_ok:
            target_meta = {**target_meta, **(insp.get("targetApp") or {}), "running": True}
        ui_state = insp.get("uiState") or compute_ui_state(insp if obs_ok else None, bundle_id=str(target_meta.get("bundleID") or bundle_id))
        archetype = insp.get("archetype") or infer_app_archetype(insp if obs_ok else None, target_meta=target_meta)
        modal_status = insp.get("modalStatus") or ui_state.get("modalStatus") or {"kind": "none", "requiresHuman": False}
        eff_bid = str(target_meta.get("bundleID") or bundle_id or "")
        known_transitions = self.state_graph.suggest_known_transitions(eff_bid, str(ui_state.get("stateHash") or ""))
        phases.append(
            {
                "phase": 1,
                "name": "inspect_and_archetype",
                "ok": obs_ok,
                "archetypeId": archetype.get("id"),
                "stateHash": ui_state.get("stateHash"),
                "modalKind": modal_status.get("kind"),
                "knownTransitionsCount": len(known_transitions),
            }
        )

        # Phase 2: Agent-Powered Synthesis or Explore enriched by Archetype Hints
        eff_mode = str(mode or "auto").strip().lower()
        hints_text = "\n".join(f"- {h}" for h in (archetype.get("strategyHints") or []))
        if known_transitions:
            hints_text += "\n- 已有状态迁移先验：" + ", ".join(str(k.get("actionSig") or "") for k in known_transitions[:4])
        combined_custom = (
            f"{custom_agent_prompt.strip()}\n\n[UI Archetype: {archetype.get('id')} ({archetype.get('label')})]\n{hints_text}"
        ).strip()

        if eff_mode == "explore":
            syn = self.explore_and_build_sop(
                goal=clean_goal,
                bundle_id=eff_bid,
                app_name=str(target_meta.get("name") or app_name),
                app_path=str(target_meta.get("appPath") or app_path),
                agent_id=agent_id,
                max_turns=max_turns,
                dry_run=True,
                launch_if_needed=False,
                save=False,
            )
            wf = dict(syn.get("workflow") or {})
        else:
            syn = self.build_sop_and_workflow(
                goal=clean_goal,
                bundle_id=eff_bid,
                app_name=str(target_meta.get("name") or app_name),
                app_path=str(target_meta.get("appPath") or app_path),
                agent_id=agent_id,
                custom_agent_prompt=combined_custom,
                inspect_live=False,
                attach_screenshot=bool(archetype.get("recommendAttachScreenshot")),
                save=False,
                pre_inspection=insp if obs_ok else None,
            )
            wf = dict(syn.get("workflow") or {})

        if not syn.get("ok") or not wf:
            return {
                "ok": False,
                "error_code": syn.get("error_code") or "generalize_synthesis_failed",
                "error": syn.get("error") or "未知应用 SOP 合成失败",
                "phases": phases,
            }
        phases.append(
            {
                "phase": 2,
                "name": "agent_synthesis",
                "ok": True,
                "mode": eff_mode,
                "agentId": (wf.get("builderAgent") or {}).get("agentId"),
                "usedFallback": bool((wf.get("builderAgent") or {}).get("usedFallback")),
                "rawSteps": len(wf.get("steps") or []),
            }
        )

        # Phase 3: Trajectory Optimization + Semantic Anchor Enrichment + Readiness Scoring + Save
        enriched_steps = optimize_and_enrich_steps(wf.get("steps") or [], inspection=insp if obs_ok else None)
        wf["steps"] = self._normalize_steps(enriched_steps)
        wf["archetype"] = archetype
        wf["mode"] = f"generalized_{eff_mode}"
        wf["readiness"] = score_workflow_readiness(wf)
        wf["sopMarkdown"] = self._render_sop_markdown(wf)
        if save:
            self.save_workflow(wf, sop_markdown=wf["sopMarkdown"])
        self.state_graph.record_observation(
            eff_bid,
            str(target_meta.get("name") or app_name or eff_bid),
            ui_state,
            archetype_id=str(archetype.get("id") or ""),
        )
        phases.append(
            {
                "phase": 3,
                "name": "optimize_and_score",
                "ok": True,
                "optimizedSteps": len(wf.get("steps") or []),
                "readinessScore": wf["readiness"].get("score"),
                "readinessGrade": wf["readiness"].get("grade"),
                "saved": bool(save),
            }
        )

        # Phase 4: Dry-Run Pre-Flight Check & Portable Skill Export
        dry_res: Optional[Dict[str, Any]] = None
        if dry_run_verify:
            dry_res = self.run_workflow(workflow=wf, dry_run=True, self_heal=True)
            phases.append(
                {
                    "phase": 4,
                    "name": "dry_run_verify",
                    "ok": bool(dry_res.get("ok")),
                    "stepsValidated": dry_res.get("stepsExecuted", 0),
                }
            )

        exported_skill: Optional[Dict[str, Any]] = None
        if export_skill and save and wf.get("id"):
            exported_skill = self.export_workflow_as_skill(str(wf["id"]))
            phases.append(
                {
                    "phase": 5 if dry_run_verify else 4,
                    "name": "export_skill",
                    "ok": bool(exported_skill.get("ok")),
                    "skillMdPath": exported_skill.get("skillMdPath", ""),
                }
            )

        return {
            "ok": True,
            "elapsedMs": round((time.perf_counter() - t0) * 1000.0, 1),
            "phases": phases,
            "targetApp": target_meta,
            "archetype": archetype,
            "modalStatus": modal_status,
            "uiState": ui_state,
            "readiness": wf["readiness"],
            "workflow": wf,
            "sopMarkdown": wf["sopMarkdown"],
            "dryRunVerification": dry_res,
            "exportedSkill": exported_skill,
            "stateGraph": self.state_graph.get_app_graph(bundle_id=eff_bid),
        }

    def watch_windows_parallel(
        self,
        targets: List[Dict[str, Any]],
        *,
        include_ocr: bool = False,
        max_workers: int = 4,
    ) -> Dict[str, Any]:
        """Concurrently monitor multiple app windows without stealing focus (--no-activate)."""
        clean_targets = [dict(t) for t in (targets or []) if isinstance(t, dict) and (t.get("bundle_id") or t.get("bundleID") or t.get("app_name") or t.get("name") or t.get("window_id") or t.get("windowID"))]
        if not clean_targets:
            return {"ok": False, "error_code": "missing_targets", "error": "请至少提供一个要并行监控的应用/窗口目标。"}

        workers = max(1, min(8, int(max_workers or 4), len(clean_targets)))
        t_wall0 = time.perf_counter()

        def _probe_one(idx: int, spec: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
            wt0 = time.perf_counter()
            bid = str(spec.get("bundle_id") or spec.get("bundleID") or "").strip()
            aname = str(spec.get("app_name") or spec.get("name") or "").strip()
            apath = str(spec.get("app_path") or spec.get("appPath") or "").strip()
            wid = spec.get("window_id") or spec.get("windowID")
            args = ["app-use-inspect", "--no-activate", "--max-nodes", str(int(spec.get("max_nodes") or 160))]
            if not include_ocr:
                args.append("--skip-ocr")
            if bid:
                args.extend(["--bundle-id", bid])
            if aname:
                args.extend(["--app-name", aname])
            if apath:
                args.extend(["--app-path", apath])
            if wid:
                args.extend(["--window-id", str(int(wid))])

            raw = self.engine._run_native(args, timeout=14.0)
            elapsed_ms = round((time.perf_counter() - wt0) * 1000.0, 1)
            eff_bid = str(raw.get("bundleID") or bid)
            eff_name = str(raw.get("name") or aname or eff_bid)
            if not raw.get("ok"):
                return idx, {
                    "ok": False,
                    "bundleID": eff_bid,
                    "name": eff_name,
                    "elapsedMs": elapsed_ms,
                    "error": str(raw.get("error") or raw.get("error_code") or "inspect_failed"),
                }
            meta = self._resolve_target_meta(bundle_id=eff_bid, app_name=eff_name, app_path=apath)
            risk_profile = classify_app_risk_tier(
                eff_bid,
                eff_name,
                apath,
                category=str(meta.get("category") or ""),
            )
            lane_id = f"watch_{int(time.time() * 1000)}_{idx}_{uuid.uuid4().hex[:4]}"
            self._lanes.start_lane(
                lane_id,
                bundle_id=eff_bid or eff_name or f"win_{idx}",
                app_name=eff_name,
                risk_tier=str(risk_profile.get("tier") or "safe_native"),
                dispatch_mode="readonly_parallel",
                state="observing",
                current_action="watch_no_activate",
            )
            state = compute_ui_state(raw, bundle_id=eff_bid)
            arch = infer_app_archetype(raw, target_meta=meta)
            try:
                self.state_graph.record_observation(eff_bid, eff_name, state, archetype_id=str(arch.get("id") or ""))
            except Exception:
                pass
            self._lanes.finish_lane(lane_id, ok=True, state="done")
            win_obj = raw.get("window") if isinstance(raw.get("window"), dict) else {}
            return idx, {
                "ok": True,
                "bundleID": eff_bid,
                "name": eff_name,
                "windowID": win_obj.get("windowID"),
                "windowTitle": win_obj.get("title") or state.get("windowTitle") or "",
                "windowOccluded": bool(raw.get("windowOccluded")),
                "axControlCount": int(raw.get("axControlCount") or 0),
                "ocrCount": int(raw.get("ocrCount") or 0),
                "stateHash": state.get("stateHash"),
                "modalStatus": state.get("modalStatus"),
                "archetype": {"id": arch.get("id"), "label": arch.get("label")},
                "riskProfile": risk_profile,
                "textsPreview": (state.get("textsPreview") or [])[:8],
                "elapsedMs": elapsed_ms,
            }

        results_map: Dict[int, Dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_probe_one, idx, spec) for idx, spec in enumerate(clean_targets)]
            for fut in concurrent.futures.as_completed(futs):
                i, item = fut.result()
                results_map[i] = item

        ordered = [results_map[i] for i in range(len(clean_targets))]
        wall_ms = round((time.perf_counter() - t_wall0) * 1000.0, 1)
        sum_ms = round(sum(float(x.get("elapsedMs") or 0.0) for x in ordered), 1)
        speedup = round(sum_ms / max(wall_ms, 1.0), 2)
        return {
            "ok": True,
            "targetCount": len(ordered),
            "succeededCount": sum(1 for x in ordered if x.get("ok")),
            "wallElapsedMs": wall_ms,
            "sumElapsedMs": sum_ms,
            "speedupRatio": speedup,
            "windows": ordered,
        }

    def run_workflows_parallel(
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
        """Execute N App-Use workflows concurrently: perception & headless AX run in parallel; foreground HID is serialized via ForegroundHIDLease."""
        clean_jobs = [dict(j) for j in (jobs or []) if isinstance(j, dict)]
        if not clean_jobs:
            return {"ok": False, "error_code": "missing_jobs", "error": "请提供至少一个并行执行任务 (jobs)。"}
        if not dry_run and not confirm_run:
            return {"ok": False, "error_code": "confirmation_required", "error": "实机并行运行工作流必须显式传 confirm_run=true。"}

        workers = max(1, min(6, int(max_workers or 4), len(clean_jobs)))
        t_wall0 = time.perf_counter()

        def _exec_one(idx: int, job: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
            wt0 = time.perf_counter()
            job_mode = str(job.get("dispatch_mode") or job.get("dispatchMode") or dispatch_mode or "auto")
            res = self.run_workflow(
                workflow_id=job.get("workflow_id") or job.get("workflowId") or None,
                workflow=job.get("workflow") if isinstance(job.get("workflow"), dict) else None,
                params=job.get("params") if isinstance(job.get("params"), dict) else None,
                dry_run=dry_run,
                confirm_run=confirm_run,
                respect_human_guard=respect_human_guard,
                self_heal=self_heal,
                dispatch_mode=job_mode,
            )
            elapsed_ms = round((time.perf_counter() - wt0) * 1000.0, 1)
            return idx, {**res, "jobIndex": idx, "wallJobMs": elapsed_ms}

        results_map: Dict[int, Dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_exec_one, idx, job) for idx, job in enumerate(clean_jobs)]
            for fut in concurrent.futures.as_completed(futs):
                i, item = fut.result()
                results_map[i] = item

        ordered = [results_map[i] for i in range(len(clean_jobs))]
        wall_ms = round((time.perf_counter() - t_wall0) * 1000.0, 1)
        sum_ms = round(sum(float(x.get("elapsedMs") or x.get("wallJobMs") or 0.0) for x in ordered), 1)
        return {
            "ok": all(bool(x.get("ok")) for x in ordered),
            "dryRun": bool(dry_run),
            "jobCount": len(ordered),
            "succeededCount": sum(1 for x in ordered if x.get("ok")),
            "wallElapsedMs": wall_ms,
            "sumElapsedMs": sum_ms,
            "speedupRatio": round(sum_ms / max(wall_ms, 1.0), 2),
            "hidLeaseStats": self._hid_lease.stats(),
            "concurrencyStatus": self.get_concurrency_status(),
            "results": ordered,
        }

    def get_concurrency_status(self) -> Dict[str, Any]:
        """Return live multi-window concurrency swimlanes, HID lease, and anti-risk pacer telemetry."""
        return self._lanes.snapshot(
            hid_lease_stats=self._hid_lease.stats(),
            pacer_stats=self._risk_pacer.stats(),
        )

    def get_app_risk_profile(
        self,
        *,
        bundle_id: str = "",
        app_name: str = "",
        app_path: str = "",
    ) -> Dict[str, Any]:
        """Classify target app into anti-ban execution tiers (safe_native / moderate_agent_or_web / high_risk_social)."""
        bid = str(bundle_id or "").strip()
        name = str(app_name or "").strip()
        path = str(app_path or "").strip()
        cls = classify_mac_app(bid, name, path)
        profile = classify_app_risk_tier(bid, name, path, category=str(cls.get("category") or ""))
        return {
            "ok": True,
            "bundleID": bid,
            "appName": name,
            "category": cls.get("category", ""),
            "riskProfile": profile,
        }

    @staticmethod
    def _render_meta_skill_markdown() -> str:
        return """---
name: app-use-meta-builder
description: "Meta-RPA Generalization Skill for macOS: turn ANY unseen desktop app into a parameterized SOP workflow + portable SKILL.md via WeChat Bot Universal App-Use Engine (AXUIElement + Vision OCR + Archetype Inference + Self-Healing + Multi-Window Parallel Watch)."
---

# App-Use Meta Builder — 通用未知新 App RPA 元能力技能

当用户要求 **“帮我把某个新 App 做成可复用 RPA / 自动化流程 / SOP / Skill”**、**“泛化到一个没见过的新桌面应用”** 或 **“并行监控多个桌面应用窗口”** 时，按本指南直接调用本地 **WeChat Bot App-Use Engine**（默认 HTTP `http://127.0.0.1:18788` 与 MCP 工具）端到端完成，禁止对每个新 App 写死专用坐标脚本。

## 为什么这套方案能泛化未知 App（且支持多窗口并发）
- **Window-Scoped 精准视野**：通过 macOS `CGWindowID` + `AXUIElement(pid)` 锁定单个目标应用窗口，避免全屏截图冗余噪声和网页 Sandbox 限制（原生桌面 App 如微信、企微、词典、Figma、终端均可直控）。
- **多因子语义+空间+拓扑定位 (`SemanticElementGrounder`)**：融合双语同义词/CJK bigram、`identifier/role`、分辨率无关归一化坐标与邻域参照物 `neighborTexts`，窗口缩放或轻微改版仍可自愈锚定。
- **并发与安全性清晰分层**：多窗口只读巡检/OCR/等待/LLM 规划可在后台线程真并行（`--no-activate`）；仅前台键鼠输入/剪切板由 `ForegroundHIDLease` 微租约原子串行护栏保护。

## 标准 4 步元工作流（Zero-Hardcoding Generalization）

### Phase 1 — 探测目标 App 与拓扑原型（只读无侵入）
- MCP：`app_use_list_apps` → 找到目标应用的 `bundleID` / `appPath`。
- HTTP：`POST http://127.0.0.1:18788/api/app-use/inspect`（返回 `archetype`、`uiState.stateHash`、`modalStatus`、`axControls`、`ocrElements`）。
- 若检测到 `modalStatus.kind == "auth_or_risk_gate"`（登录扫码/密码/支付/不可逆确认），先停下让用户人工处理。

### Phase 2 — 一键泛化生成并自动评分 + 打包为独立 Skill
- **推荐一键元工具（MCP `app_use_generalize_app` 或 `POST /api/app-use/generalize`）**：
```json
{
  "goal": "唤醒目标 App，完成关键操作并回读验收结果",
  "bundle_id": "com.example.TargetApp",
  "agent_id": "magpie:group/omini-balanced",
  "mode": "auto",
  "dry_run_verify": true,
  "export_skill": true,
  "launch_if_needed": true
}
```
- 若流程长或页面动态多跳，用 **`app_use_explore_and_build`**（Observe→Think→Act→Verify 多轮自主探索 + 状态环防死循环）。
- 若界面操作难以用文字说清，调用 **`app_use_record_demo`** 让人类示范操作一次后自动编译成带 `{{变量}}` 的 SOP。

### Phase 3 — Dry-Run 校验、实机联跑与跨应用流水线
1. 先检查返回的 `readiness`（`score` / `grade`）与 `dryRunVerification.ok`。
2. 实机执行必须显式带 `confirm_run: true`：
   - 单应用执行：`app_use_run_workflow`（建议开启 `self_heal: true`；关键读数步骤可设 `waitUntilChanged: true`、`waitUntilStable: true` 与 `captureAs: "var_name"`）。
   - 跨应用联动：`app_use_run_pipeline`（自动把上一阶段采集的 `{{var_name}}` 注入下一款 App）。

### Phase 4 — 多窗口并行关注、风控分级双通道 & 状态图谱复用
- 查询应用反风控分级策略：`app_use_risk_profile`（`GET /api/app-use/risk-profile?bundle_id=...`）：
  - **高风控社交/金融 App**（微信、企微、钉钉、飞书、小红书、抖音等 `high_risk_social`）：硬隔离禁止无焦点后台 AX 写入，强制 `foreground_human_paced`（`ForegroundHIDLease` 前台真实焦点 + 随机拟真节奏抖动），严防非前景注入异常事件触发风控。
  - **安全原生/办公 App**（计算器、文本编辑、词典、Finder 等 `safe_native`）：默认开启 `headless_ax_first`，优先通过无焦点 `AXPress` / `AXSetValue` 直调实现**不抢鼠标、不占剪贴板、零焦点切换真并发**，不支持或校验不通过时自动平滑降级为 `ForegroundHIDLease`。
- 并行观察多个窗口最新文本与弹窗阻断：`app_use_watch_parallel`（或 `POST /api/app-use/watch-parallel`）。
- 并发调度多套流程：`app_use_run_parallel`（支持 `dispatch_mode`: `auto` / `headless_ax_first` / `foreground_hid_only`）。
- 实时多窗口并发泳道监控：`app_use_concurrency_status`（`GET /api/app-use/concurrency-status`）。
- 查看跨运行沉淀下来的页面迁移先验：`app_use_state_graph`（`GET /api/app-use/state-graph`）。

## 安全红线（必须严格遵守）
1. 任何未经用户确认的高风险动作（外发消息、支付、删除、提交表单）必须在关键步骤保留 `pause_for_human`。
2. 实机运行始终尊重 `HumanActivityGuard`；用户键鼠活跃时立即让路。
3. 导出 Skill 与截图存证统一存放在 `/Volumes/SanDisk/Builds/WeChatBot/`，不写内盘垃圾缓存。
"""

    def install_meta_skill(
        self,
        *,
        install_global: bool = True,
        global_skills_root: Optional[Path] = None,
        symlink_roots: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        """Write app-use-meta-builder/SKILL.md to repo and link into host agent skill directories."""
        repo_root = Path(__file__).resolve().parent.parent
        skill_content = self._render_meta_skill_markdown()
        if ".app/Contents/Resources" in str(repo_root):
            repo_skill_path = self.store_path.parent / "skills" / "app-use-meta-builder" / "SKILL.md"
        else:
            repo_skill_path = repo_root / "skills" / "app-use-meta-builder" / "SKILL.md"
        repo_skill_path.parent.mkdir(parents=True, exist_ok=True)
        repo_skill_path.write_text(skill_content, encoding="utf-8")

        installed_paths: List[str] = [str(repo_skill_path)]
        linked_targets: List[Dict[str, str]] = []

        if install_global:
            eff_global_root = Path(global_skills_root) if global_skills_root else Path("/Users/mac/.agents/skills")
            canonical_dir = eff_global_root / "app-use-meta-builder"
            canonical_dir.mkdir(parents=True, exist_ok=True)
            canonical_md = canonical_dir / "SKILL.md"
            canonical_md.write_text(skill_content, encoding="utf-8")
            installed_paths.append(str(canonical_md))

            if symlink_roots is not None:
                candidate_roots = [Path(r) for r in symlink_roots]
            else:
                candidate_roots = [
                    Path("/Users/mac/Library/Application Support/Antigravity Google/home/.gemini/config/skills"),
                    Path("/Users/mac/.codex/skills"),
                    Path("/Users/mac/.codex-managed-agent/accounts/harzva-2a5155e0/skills"),
                    Path("/Users/mac/.config/opencode/skills"),
                ]

            for root_dir in candidate_roots:
                try:
                    # Only install into skill roots whose agent home directory exists
                    if root_dir.name == "skills" and not root_dir.exists():
                        if root_dir.parent.is_dir():
                            root_dir.mkdir(parents=True, exist_ok=True)
                        else:
                            continue
                    if not root_dir.is_dir():
                        continue
                    # Avoid self-linking canonical parent
                    if root_dir.resolve() == eff_global_root.resolve():
                        continue
                    link_path = root_dir / "app-use-meta-builder"
                    if link_path.is_symlink():
                        link_path.unlink()
                        os.symlink(str(canonical_dir), str(link_path))
                        linked_targets.append({"root": str(root_dir), "path": str(link_path), "mode": "symlink"})
                    elif link_path.exists() and link_path.is_dir():
                        md = link_path / "SKILL.md"
                        md.write_text(skill_content, encoding="utf-8")
                        linked_targets.append({"root": str(root_dir), "path": str(md), "mode": "direct_copy"})
                    else:
                        os.symlink(str(canonical_dir), str(link_path))
                        linked_targets.append({"root": str(root_dir), "path": str(link_path), "mode": "symlink"})
                except Exception as exc:
                    linked_targets.append({"root": str(root_dir), "error": str(exc), "mode": "skipped"})

        return {
            "ok": True,
            "skillName": "app-use-meta-builder",
            "repoSkillPath": str(repo_skill_path),
            "installedPaths": installed_paths,
            "linkedTargets": linked_targets,
        }

