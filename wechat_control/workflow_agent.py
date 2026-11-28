"""Self-Authoring & Self-Debugging Workflow Agent Studio (v3.1).

Turns plain-language user requests (e.g. "extract customer WeChat IDs from Feishu,
self-introduce, add friend with '飞书引流' remark, and enroll into SalesCRM") into:
  1. An OpenSpec-style structured WorkflowSpec (proposal, target apps, safety boundaries,
     independent verification assertions, and optional Omini Critic review).
  2. A static linter-hardened multi-step workflow using AppUseStudio's 8 GUI primitives
     plus 6 bounded cognitive/logic/tool/assertion primitives.
  3. A closed-loop self-debugging cycle (Run -> Evaluate Assertions -> Diagnose Root Cause
     -> Patch Version -> Re-Run) with three-tier verification (dry_run / shadow / live),
     AUTH_GATE immediate stops, and anti-loop fingerprint circuit breakers.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .app_use_meta_algo import (
    SemanticElementGrounder,
    classify_app_risk_tier,
    classify_step_failure,
    detect_modal_blocker,
    optimize_and_enrich_steps,
    score_workflow_readiness,
)
from .app_use_studio import (
    INDEPENDENT_EVIDENCE_SOURCES,
    SUPPORTED_STEP_ACTIONS,
    WHITELISTED_BUILTIN_TOOLS,
    _extract_json_object,
    _slugify,
)
from .io_utils import atomic_write_json

if TYPE_CHECKING:
    from .engine import WeChatControlEngine


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_APP_ALIAS_CATALOG: List[Tuple[Tuple[str, ...], Dict[str, str]]] = [
    (
        ("飞书", "feishu", "lark"),
        {"bundleID": "com.bytedance.macos.feishu", "name": "Feishu (Lark)", "category": "im_social"},
    ),
    (
        ("企业微信", "企微", "wecom", "wework"),
        {"bundleID": "com.tencent.WeWorkMac", "name": "WeCom", "category": "im_social"},
    ),
    (
        ("钉钉", "dingtalk"),
        {"bundleID": "com.alibaba.DingTalkMac", "name": "DingTalk", "category": "im_social"},
    ),
    (
        ("抖音", "douyin", "tiktok"),
        {"bundleID": "com.ss.iphone.ugc.Aweme", "name": "Douyin", "category": "im_social"},
    ),
    (
        ("小红书", "xiaohongshu", "xhs", "rednote"),
        {"bundleID": "com.xingin.xhs", "name": "Xiaohongshu", "category": "im_social"},
    ),
    (
        ("微信", "wechat", "绿泡泡", "vx", "wx"),
        {"bundleID": "com.tencent.xinWeChat", "name": "WeChat", "category": "im_social"},
    ),
    (
        ("计算器", "calculator", "calc"),
        {"bundleID": "com.apple.calculator", "name": "Calculator", "category": "productivity"},
    ),
    (
        ("文本编辑", "textedit", "文档", "简报", "纪要"),
        {"bundleID": "com.apple.TextEdit", "name": "TextEdit", "category": "productivity"},
    ),
    (
        ("备忘录", "notes"),
        {"bundleID": "com.apple.Notes", "name": "Notes", "category": "productivity"},
    ),
    (
        ("safari", "chrome", "浏览器"),
        {"bundleID": "com.apple.Safari", "name": "Safari", "category": "browser"},
    ),
]

_BUNDLE_FRIENDLY_LABELS: Dict[str, str] = {
    "com.bytedance.macos.feishu": "飞书",
    "com.tencent.xinWeChat": "微信",
    "com.tencent.WeWorkMac": "企业微信",
    "com.alibaba.DingTalkMac": "钉钉",
    "com.ss.iphone.ugc.Aweme": "抖音",
    "com.xingin.xhs": "小红书",
    "com.apple.calculator": "计算器",
    "com.apple.TextEdit": "文本编辑",
    "com.apple.Notes": "备忘录",
    "com.apple.Safari": "Safari 浏览器",
}

_IM_CHANNEL_PROFILES: Dict[str, Dict[str, Any]] = {
    "com.bytedance.macos.feishu": {
        "bundleID": "com.bytedance.macos.feishu",
        "name": "Feishu (Lark)",
        "category": "im_social",
        "slug": "feishu",
        "label": "飞书",
        "defaultRemark": "飞书引流-",
        "acquireTag": "飞书获客",
        "funnelTag": "飞书引流",
        "keywords": ("飞书", "feishu", "lark"),
    },
    "com.alibaba.DingTalkMac": {
        "bundleID": "com.alibaba.DingTalkMac",
        "name": "DingTalk",
        "category": "im_social",
        "slug": "dingtalk",
        "label": "钉钉",
        "defaultRemark": "钉钉引流-",
        "acquireTag": "钉钉获客",
        "funnelTag": "钉钉引流",
        "keywords": ("钉钉", "dingtalk"),
    },
    "com.tencent.WeWorkMac": {
        "bundleID": "com.tencent.WeWorkMac",
        "name": "WeCom",
        "category": "im_social",
        "slug": "wecom",
        "label": "企业微信",
        "defaultRemark": "企微引流-",
        "acquireTag": "企微获客",
        "funnelTag": "企微引流",
        "keywords": ("企业微信", "企微", "wecom", "wework"),
    },
    "com.ss.iphone.ugc.Aweme": {
        "bundleID": "com.ss.iphone.ugc.Aweme",
        "name": "Douyin",
        "category": "im_social",
        "slug": "douyin",
        "label": "抖音",
        "defaultRemark": "抖音引流-",
        "acquireTag": "抖音获客",
        "funnelTag": "抖音引流",
        "keywords": ("抖音", "douyin", "tiktok"),
    },
    "com.xingin.xhs": {
        "bundleID": "com.xingin.xhs",
        "name": "Xiaohongshu",
        "category": "im_social",
        "slug": "xiaohongshu",
        "label": "小红书",
        "defaultRemark": "小红书引流-",
        "acquireTag": "小红书获客",
        "funnelTag": "小红书引流",
        "keywords": ("小红书", "xiaohongshu", "xhs", "rednote"),
    },
}


def _friendly_app_label(bundle_id: str) -> str:
    bid = str(bundle_id or "").strip()
    if bid in _BUNDLE_FRIENDLY_LABELS:
        return _BUNDLE_FRIENDLY_LABELS[bid]
    low = bid.casefold()
    for k, label in _BUNDLE_FRIENDLY_LABELS.items():
        if k.casefold() == low:
            return label
    return bid


def _detect_explicit_im_channel(
    goal: str = "",
    targets: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    by_lower_bid = {k.casefold(): v for k, v in _IM_CHANNEL_PROFILES.items()}
    for t in targets or []:
        bid = str(t.get("bundleID") or "").strip().casefold()
        if bid in by_lower_bid:
            return dict(by_lower_bid[bid])
    low = str(goal or "").casefold()
    best_pos: Optional[int] = None
    best_profile: Optional[Dict[str, Any]] = None
    for profile in _IM_CHANNEL_PROFILES.values():
        positions = [low.find(kw) for kw in profile["keywords"] if kw in low]
        if positions:
            mpos = min(positions)
            if best_pos is None or mpos < best_pos:
                best_pos = mpos
                best_profile = profile
    return dict(best_profile) if best_profile else None


def _resolve_im_channel(
    goal: str = "",
    targets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    detected = _detect_explicit_im_channel(goal=goal, targets=targets)
    if detected:
        return detected
    return dict(_IM_CHANNEL_PROFILES["com.bytedance.macos.feishu"])


def detect_apps_from_goal(
    goal: str,
    installed_apps: Optional[List[Dict[str, Any]]] = None,
    explicit_apps: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Detect ordered target macOS applications from explicit selection or plain-language goal."""
    apps_list = list(installed_apps or [])
    by_bid = {str(a.get("bundleID") or "").casefold(): a for a in apps_list if a.get("bundleID")}
    by_name = {str(a.get("name") or "").casefold(): a for a in apps_list if a.get("name")}
    selected: List[Dict[str, Any]] = []
    seen_bids: set[str] = set()

    def _add_candidate(cand: Dict[str, Any]) -> None:
        bid = str(cand.get("bundleID") or "").strip()
        key = (bid or str(cand.get("name") or "")).casefold()
        if not key or key in seen_bids:
            return
        seen_bids.add(key)
        resolved = by_bid.get(bid.casefold()) or by_name.get(str(cand.get("name") or "").casefold())
        merged = dict(resolved) if resolved else {}
        merged.setdefault("bundleID", bid)
        merged.setdefault("name", cand.get("name") or bid)
        merged.setdefault("appPath", cand.get("appPath") or "")
        merged.setdefault("category", cand.get("category") or "productivity")
        selected.append(merged)

    for raw in explicit_apps or []:
        tok = str(raw or "").strip()
        if not tok:
            continue
        low = tok.casefold()
        if low in by_bid:
            _add_candidate(by_bid[low])
            continue
        if low in by_name:
            _add_candidate(by_name[low])
            continue
        matched_alias = False
        for keywords, meta in _APP_ALIAS_CATALOG:
            if any(k in low for k in keywords):
                _add_candidate(meta)
                matched_alias = True
                break
        if not matched_alias:
            _add_candidate({"bundleID": tok if "." in tok else "", "name": tok})

    goal_low = str(goal or "").casefold()
    scan_low_without_wecom = re.sub(r"企业微信", "____", goal_low)
    # Preserve order of appearance in user's goal sentence
    found_pos: List[Tuple[int, Dict[str, str]]] = []
    for keywords, meta in _APP_ALIAS_CATALOG:
        haystack = scan_low_without_wecom if meta.get("bundleID") == "com.tencent.xinWeChat" else goal_low
        positions = [haystack.find(kw) for kw in keywords if kw in haystack]
        if positions:
            found_pos.append((min(positions), meta))
    found_pos.sort(key=lambda item: item[0])
    for _, meta in found_pos:
        _add_candidate(meta)

    for inst in apps_list:
        nm = str(inst.get("name") or "").strip()
        if nm and len(nm) >= 3 and nm.casefold() in goal_low:
            _add_candidate(inst)

    if not selected and apps_list:
        _add_candidate(apps_list[0])
    return selected


SCENARIO_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "feishu_to_wechat_crm",
        "title": "飞书客户引流加微信 + CRM 建档",
        "badge": "跨应用热销场景",
        "goal": "从飞书客户聊天中提取微信号，用智拓巨浪话术自报家门加微信，备注飞书引流并写入后端CRM档案",
        "targetApps": ["com.bytedance.macos.feishu", "com.tencent.xinWeChat"],
        "recommendedMode": "shadow",
    },
    {
        "id": "feishu_digest_to_doc",
        "title": "飞书待办汇总生成工作简报",
        "badge": "办公协同",
        "goal": "读取飞书当前聊天或待办内容，提炼关键事项并在文本编辑中新建简报文档保存",
        "targetApps": ["com.bytedance.macos.feishu", "com.apple.TextEdit"],
        "recommendedMode": "shadow",
    },
    {
        "id": "calc_to_textedit_report",
        "title": "计算器自动验算 + 文本编辑出报告",
        "badge": "本机零风险实测",
        "goal": "打开计算器计算 125*8 并提取数值结果，随后切换到文本编辑新建文档写入计算简报并回读验证",
        "targetApps": ["com.apple.calculator", "com.apple.TextEdit"],
        "recommendedMode": "live",
    },
]


class WorkflowSpecLinter:
    """Static safety, loop-freedom, and anti-self-certification linter."""

    @staticmethod
    def lint(workflow: Dict[str, Any], spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        steps = list(workflow.get("steps") or [])
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        tapp = dict(workflow.get("targetApp") or {})
        cur_risk = classify_app_risk_tier(
            str(tapp.get("bundleID") or ""),
            str(tapp.get("name") or ""),
            str(tapp.get("appPath") or ""),
            category=str(tapp.get("category") or ""),
        )
        produced_from_read: set[str] = set()
        seen_human_gate_since_risk = False
        has_assertion = False

        for pos, st in enumerate(steps):
            if not isinstance(st, dict):
                continue
            idx = int(st.get("step") or pos + 1)
            action = str(st.get("action") or "").strip().lower()
            if action not in SUPPORTED_STEP_ACTIONS:
                errors.append({"code": "UNKNOWN_ACTION", "step": idx, "message": f"未知动作类型 `{action}`"})
                continue

            if action == "switch_app":
                sw_tapp = st.get("targetApp") if isinstance(st.get("targetApp"), dict) else {}
                cur_risk = classify_app_risk_tier(
                    str(sw_tapp.get("bundleID") or st.get("bundleID") or st.get("bundleId") or tapp.get("bundleID") or ""),
                    str(sw_tapp.get("name") or st.get("appName") or ""),
                    str(sw_tapp.get("appPath") or st.get("appPath") or ""),
                )
                seen_human_gate_since_risk = False

            if action == "pause_for_human":
                seen_human_gate_since_risk = True

            if action in ("inspect_ui", "wait_and_read"):
                if st.get("captureAs"):
                    produced_from_read.add(str(st["captureAs"]).strip())
                if st.get("expectText") or st.get("captureAs"):
                    has_assertion = True

            if action == "llm_extract":
                out_v = str(st.get("captureAs") or st.get("outputVar") or "extracted_value").strip()
                produced_from_read.add(out_v)

            if action == "builtin_tool":
                tool_name = str(st.get("tool") or "").strip()
                if tool_name not in WHITELISTED_BUILTIN_TOOLS:
                    errors.append(
                        {
                            "code": "UNWHITELISTED_TOOL",
                            "step": idx,
                            "message": f"builtin_tool `{tool_name}` 不在安全白名单中",
                        }
                    )
                if st.get("captureAs"):
                    produced_from_read.add(str(st["captureAs"]).strip())
                if tool_name == "wechat_add_friend" and not seen_human_gate_since_risk:
                    errors.append(
                        {
                            "code": "MISSING_OUTBOUND_GATE",
                            "step": idx,
                            "message": "调用 wechat_add_friend 前缺少 pause_for_human 安全确认门禁",
                        }
                    )
                if tool_name in ("crm_enroll", "memory_add", "wechat_add_friend") and not st.get("idempotencyKey"):
                    warnings.append(
                        {
                            "code": "MISSING_IDEMPOTENCY_KEY",
                            "step": idx,
                            "message": f"{tool_name} 建议显式设置 idempotencyKey 防止重复调试多次落账",
                        }
                    )

            if action == "focus_and_type" and bool(st.get("submitAfter")) and cur_risk.get("tier") == "high_risk_social":
                if not seen_human_gate_since_risk:
                    errors.append(
                        {
                            "code": "MISSING_OUTBOUND_GATE",
                            "step": idx,
                            "message": "高风险社交应用开启 submitAfter=true 自动发送前必须保留 pause_for_human 门禁",
                        }
                    )

            if action == "branch_if" and st.get("jumpToStep") is not None:
                try:
                    j_step = int(st["jumpToStep"])
                    if j_step <= idx:
                        errors.append(
                            {
                                "code": "CYCLE_DETECTED",
                                "step": idx,
                                "message": f"branch_if 不允许向后或原地跳转 (step {idx} -> {j_step})",
                            }
                        )
                except Exception:
                    errors.append({"code": "INVALID_JUMP", "step": idx, "message": "jumpToStep 必须为整数步骤号"})

            if action == "assert_check":
                has_assertion = True
                ev_src = str(st.get("evidenceSource") or "").strip()
                t_var = str(st.get("targetVar") or "").strip()
                if ev_src not in INDEPENDENT_EVIDENCE_SOURCES:
                    errors.append(
                        {
                            "code": "SELF_CERTIFIED_ASSERTION",
                            "step": idx,
                            "message": f"assert_check 必须声明独立 evidenceSource ({', '.join(INDEPENDENT_EVIDENCE_SOURCES)})",
                        }
                    )
                elif ev_src == "captured_var_from_read" and t_var and t_var not in produced_from_read:
                    errors.append(
                        {
                            "code": "SELF_CERTIFIED_ASSERTION",
                            "step": idx,
                            "message": f"assert_check 引用 `{t_var}` 但前序步骤未产生读取产物，疑似输入自证",
                        }
                    )

        if not has_assertion:
            errors.append(
                {
                    "code": "MISSING_ASSERTIONS",
                    "step": 0,
                    "message": "工作流缺少独立验收断言 (assert_check 或 wait_and_read expectText/captureAs)",
                }
            )

        score = max(0, 100 - len(errors) * 25 - len(warnings) * 5)
        return {
            "ok": len(errors) == 0,
            "score": score,
            "errors": errors,
            "warnings": warnings,
        }

    @staticmethod
    def auto_harden(workflow: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Deterministically inject outbound human gates and idempotency keys where missing."""
        wf = copy.deepcopy(workflow)
        steps = list(wf.get("steps") or [])
        fixes: List[str] = []

        tapp = dict(wf.get("targetApp") or {})
        cur_risk = classify_app_risk_tier(
            str(tapp.get("bundleID") or ""),
            str(tapp.get("name") or ""),
            str(tapp.get("appPath") or ""),
        )
        seen_gate = False
        hardened_steps: List[Dict[str, Any]] = []

        for st in steps:
            if not isinstance(st, dict):
                continue
            s_copy = dict(st)
            act = str(s_copy.get("action") or "").strip().lower()
            if act == "switch_app":
                sw = s_copy.get("targetApp") if isinstance(s_copy.get("targetApp"), dict) else {}
                cur_risk = classify_app_risk_tier(
                    str(sw.get("bundleID") or s_copy.get("bundleID") or tapp.get("bundleID") or ""),
                    str(sw.get("name") or s_copy.get("appName") or ""),
                    str(sw.get("appPath") or s_copy.get("appPath") or ""),
                )
                seen_gate = False
            elif act == "pause_for_human":
                seen_gate = True

            needs_gate = (
                act == "builtin_tool" and str(s_copy.get("tool") or "").strip() == "wechat_add_friend"
            ) or (
                act == "focus_and_type" and bool(s_copy.get("submitAfter")) and cur_risk.get("tier") == "high_risk_social"
            )
            if needs_gate and not seen_gate:
                hardened_steps.append(
                    {
                        "step": len(hardened_steps) + 1,
                        "action": "pause_for_human",
                        "title": "高风险外发前人工确认门禁",
                        "description": "安全护栏：确认提取客户信息与外发话术无误后，再允许实机执行外发动作。",
                        "message": "请核对客户账号与拟发送话术后确认继续。",
                    }
                )
                seen_gate = True
                fixes.append("已自动注入高风险外发前人工确认门禁 (pause_for_human)")

            if act == "builtin_tool":
                tname = str(s_copy.get("tool") or "").strip()
                if tname in ("crm_enroll", "memory_add", "wechat_add_friend") and not s_copy.get("idempotencyKey"):
                    s_copy["idempotencyKey"] = f"{wf.get('id', 'wf')}:{tname}:{{{{source_user}}}}"
                    fixes.append(f"已为 `{tname}` 补全幂等防重键 idempotencyKey")

            hardened_steps.append(s_copy)

        for idx, st in enumerate(hardened_steps, start=1):
            st["step"] = idx
        wf["steps"] = hardened_steps
        return wf, fixes


class WorkflowAuthorDebugger:
    """OpenSpec-driven self-authoring & closed-loop self-debugging Workflow Agent."""

    def __init__(
        self,
        engine: "WeChatControlEngine",
        *,
        sessions_path: Optional[Path] = None,
    ) -> None:
        self.engine = engine
        self.sessions_path = (
            Path(sessions_path)
            if sessions_path
            else (self.engine.auth_gate.auth_file.parent / "workflow_agent_sessions.json")
        )
        self.sessions_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_sessions()
        self.chats_path = self.sessions_path.parent / "workflow_agent_chats.json"
        self._chats_state = self._load_chats()

    def _load_sessions(self) -> Dict[str, Any]:
        if self.sessions_path.is_file():
            try:
                data = json.loads(self.sessions_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
                    return data
            except Exception:
                pass
        return {"schema": "openbot.workflow-agent-sessions/1", "sessions": {}, "order": []}

    def _save_sessions(self) -> None:
        self.sessions_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.sessions_path, self._state)

    def _load_chats(self) -> Dict[str, Any]:
        if self.chats_path.is_file():
            try:
                data = json.loads(self.chats_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("chats"), dict):
                    data.setdefault("order", [])
                    if not isinstance(data.get("activeContactChats"), dict):
                        data["activeContactChats"] = {}
                    return data
            except Exception:
                pass
        return {
            "schema": "openbot.workflow-agent-chats/1",
            "chats": {},
            "order": [],
            "activeContactChats": {},
        }

    def _save_chats(self) -> None:
        self.chats_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.chats_path, self._chats_state)

    def get_contact_active_chat(self, contact: str) -> str:
        c_key = str(contact or "").strip()
        if not c_key:
            return ""
        amap = self._chats_state.get("activeContactChats") or {}
        cid = str(amap.get(c_key) or "").strip()
        if not cid:
            return ""
        sess = (self._chats_state.get("chats") or {}).get(cid)
        if not isinstance(sess, dict) or sess.get("phase") == "built_and_debugged":
            return ""
        return cid

    def set_contact_active_chat(self, contact: str, chat_id: str) -> None:
        c_key = str(contact or "").strip()
        if not c_key:
            return
        amap = self._chats_state.setdefault("activeContactChats", {})
        cid = str(chat_id or "").strip()
        if cid:
            amap[c_key] = cid
        else:
            amap.pop(c_key, None)
        self._save_chats()

    def list_chat_sessions(self, *, limit: int = 20) -> Dict[str, Any]:
        cmap = self._chats_state.get("chats") or {}
        order = self._chats_state.get("order") or list(cmap.keys())
        items = [cmap[cid] for cid in order if cid in cmap][: max(1, min(100, int(limit or 20)))]
        return {"ok": True, "count": len(cmap), "chats": items}

    @staticmethod
    def list_templates() -> Dict[str, Any]:
        return {"ok": True, "templates": list(SCENARIO_TEMPLATES)}

    def list_sessions(self, *, limit: int = 20) -> Dict[str, Any]:
        smap = self._state.get("sessions") or {}
        order = self._state.get("order") or list(smap.keys())
        items = [smap[sid] for sid in order if sid in smap][: max(1, min(100, int(limit)))]
        return {"ok": True, "count": len(smap), "sessions": items}

    def get_session(self, session_id: str) -> Dict[str, Any]:
        sid = str(session_id or "").strip()
        s = (self._state.get("sessions") or {}).get(sid)
        if not isinstance(s, dict):
            return {"ok": False, "error_code": "session_not_found", "error": f"未找到调试会话 {sid}"}
        return {"ok": True, "session": s}

    @staticmethod
    def _select_blueprint_id(goal: str, targets: List[Dict[str, Any]]) -> str:
        low = str(goal or "").casefold()
        bids = {str(t.get("bundleID") or "").casefold() for t in targets}
        im_ch = _detect_explicit_im_channel(goal=goal, targets=targets)
        wants_wechat_crm = any(
            k in low for k in ("微信", "wechat", "crm", "档案", "备注", "加好友", "微信号", "引流", "获客")
        ) or ("com.tencent.xinwechat" in bids and not im_ch)
        if im_ch and (
            wants_wechat_crm or "com.tencent.xinwechat" in bids
        ):
            return "feishu_to_wechat_crm" if im_ch["slug"] == "feishu" else "im_to_wechat_crm"
        if im_ch:
            return "feishu_digest_to_doc" if im_ch["slug"] == "feishu" else "im_digest_to_doc"
        if ("com.apple.calculator" in bids or "计算器" in low or "calc" in low) and (
            "com.apple.textedit" in bids or "文本编辑" in low or "简报" in low or "文档" in low
        ):
            return "calc_to_textedit_report"
        if "com.apple.calculator" in bids or "计算器" in low or "calc" in low:
            return "calc_verify"
        return "generic_unseen_app"

    def _synthesize_from_blueprint(
        self,
        *,
        bp_id: str,
        goal: str,
        targets: List[Dict[str, Any]],
        inspections: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        primary = targets[0] if targets else {"bundleID": "", "name": "Target App", "category": "productivity"}
        slug = _slugify(f"{bp_id}_{primary.get('name') or 'app'}", "wfagent")
        wf_id = f"wf_ag_{slug}_{hashlib.sha1(f'{bp_id}|{goal}|{time.time()}'.encode('utf-8')).hexdigest()[:8]}"

        if bp_id in ("feishu_to_wechat_crm", "im_to_wechat_crm"):
            ch = _resolve_im_channel(goal=goal, targets=targets)
            source_app = next(
                (t for t in targets if str(t.get("bundleID") or "").casefold() == str(ch["bundleID"]).casefold()),
                None,
            ) or {
                "bundleID": ch["bundleID"],
                "name": ch["name"],
                "category": "im_social",
            }
            label = str(ch["label"])
            c_slug = str(ch["slug"])
            rem_prefix = str(ch["defaultRemark"])
            acq_tag = str(ch["acquireTag"])
            funnel_tag = str(ch["funnelTag"])
            wechat = {"bundleID": "com.tencent.xinWeChat", "name": "WeChat", "category": "im_social"}
            return {
                "id": wf_id,
                "name": f"{label}获客引流加微信 + CRM 建档 (自建)",
                "goal": goal,
                "summary": f"从{label}消息提取客户微信号 -> 用主体与顾问身份生成自报家门话术 -> 微信备注「{rem_prefix}客户」加好友(人工确认门禁) -> 写入 SalesCRM 与本我记忆并做独立断言验收。",
                "targetApp": source_app,
                "parameters": [
                    {
                        "name": "source_user",
                        "label": f"{label}客户昵称",
                        "defaultValue": f"{label}咨询客户",
                        "required": True,
                        "description": f"来源{label}对话客户名称，用于生成微信备注及 CRM 档案名称。",
                    },
                    {
                        "name": "raw_message",
                        "label": f"可选预设聊天文本（留空则从{label}窗口现扫）",
                        "defaultValue": "",
                        "required": False,
                        "description": f"测试或单条处理时可直接传入{label}私信原文；留空则自动扫描当前{label}窗口。",
                    },
                ],
                "steps": [
                    {
                        "step": 1,
                        "action": "switch_app",
                        "title": f"切换到{label}并检查登录态",
                        "description": f"定位{label}桌面窗口，检测是否存在扫码/登录阻断。",
                        "targetApp": source_app,
                        "launchIfNeeded": True,
                    },
                    {
                        "step": 2,
                        "action": "inspect_ui",
                        "title": f"读取{label}当前聊天内容",
                        "description": f"通过 AXUIElement 与 Vision OCR 采集当前{label}窗口文本。",
                        "captureAs": f"{c_slug}_chat_text",
                        "optionalIfVar": "raw_message",
                        "extractMode": "full",
                        "saveScreenshot": True,
                    },
                    {
                        "step": 3,
                        "action": "llm_extract",
                        "title": f"从{label}内容抽取客户微信号/手机号",
                        "description": f"优先从{label}采集文本或预设聊天内容识别合法微信号/手机号。",
                        "sourceVar": f"{c_slug}_chat_text",
                        "fallbackSourceVar": "raw_message",
                        "extractor": "wechat_accounts",
                        "captureAs": "wechat_account",
                        "required": True,
                    },
                    {
                        "step": 4,
                        "action": "branch_if",
                        "title": "校验是否成功提取到微信号",
                        "description": "未识别出微信号时安全跳过后续加好友与建档动作。",
                        "var": "wechat_account",
                        "operator": "not_empty",
                        "onFalse": "stop_ok",
                    },
                    {
                        "step": 5,
                        "action": "llm_draft",
                        "title": "生成自报家门加好友话术（智拓巨浪）",
                        "description": "读取租户主体配置与知识库话术，生成不带黑话的自报家门验证语。",
                        "template": f"你好呀，我是{{businessName}}的{{ownerName}}，刚在{label}收到你发来的消息，这边加你微信详聊～",
                        "kbQuery": "加好友 验证 话术",
                        "captureAs": "friend_greeting",
                    },
                    {
                        "step": 6,
                        "action": "switch_app",
                        "title": "切换至微信准备加好友",
                        "description": "切换目标上下文至 WeChat，并启用高风控社交拟真节流。",
                        "targetApp": wechat,
                        "launchIfNeeded": False,
                    },
                    {
                        "step": 7,
                        "action": "pause_for_human",
                        "title": "外发加好友前人工确认门禁",
                        "description": "高风控安全护栏：实机发送好友申请前由操作员确认账号、备注与验证语。",
                        "message": f"即将添加微信 {{{{wechat_account}}}}，备注 {rem_prefix}{{{{source_user}}}}，请确认后继续。",
                    },
                    {
                        "step": 8,
                        "action": "builtin_tool",
                        "title": f"添加微信好友并设置备注「{rem_prefix}{{{{source_user}}}}」",
                        "description": f"调用内置安全加好友工具，填入自报家门验证语与{funnel_tag}备注。",
                        "tool": "wechat_add_friend",
                        "idempotencyKey": f"{c_slug}_wx:{{{{wechat_account}}}}",
                        "captureAs": "wechat_add_receipt",
                        "params": {
                            "account": "{{wechat_account}}",
                            "greeting": "{{friend_greeting}}",
                            "remark": f"{rem_prefix}{{{{source_user}}}}",
                            "source_channel": c_slug,
                            "source_user": "{{source_user}}",
                        },
                    },
                    {
                        "step": 9,
                        "action": "builtin_tool",
                        "title": f"在 SalesCRM 登记「{acq_tag}」客户档案",
                        "description": f"创建或更新客户档案，打上{acq_tag}、{funnel_tag}标签并记录原消息与备注。",
                        "tool": "crm_enroll",
                        "idempotencyKey": f"{c_slug}_crm:{{{{wechat_account}}}}",
                        "captureAs": "crm_receipt",
                        "params": {
                            "target": f"{rem_prefix}{{{{source_user}}}}",
                            "stage": "方案推进",
                            "alias": "{{source_user}}",
                            "tags": [acq_tag, funnel_tag, f"渠道:{label}", "已留微信号"],
                            "note": f"来源渠道：{acq_tag}（{funnel_tag}） | {label}昵称：{{{{source_user}}}} | 微信号/手机号：{{{{wechat_account}}}} | 微信备注：{rem_prefix}{{{{source_user}}}}",
                        },
                    },
                    {
                        "step": 10,
                        "action": "builtin_tool",
                        "title": f"写入本我记忆「{acq_tag}」线索事实",
                        "description": "同步沉淀至 SoulMemory 便于后续微信接管对话识别客户来源。",
                        "tool": "memory_add",
                        "idempotencyKey": f"{c_slug}_mem:{{{{wechat_account}}}}",
                        "captureAs": "memory_receipt",
                        "params": {
                            "target": f"{rem_prefix}{{{{source_user}}}}",
                            "category": "fact",
                            "content": f"客户来源:{acq_tag}({funnel_tag}),{label}昵称 {{{{source_user}}}},通过账号 {{{{wechat_account}}}} 引流至微信",
                        },
                    },
                    {
                        "step": 11,
                        "action": "assert_check",
                        "title": "独立验收：核对 CRM 建档回执成功",
                        "description": "基于 tool_result 独立核验 CRM 档案与加好友回执，拒绝输入自证。",
                        "evidenceSource": "tool_result",
                        "targetVar": "crm_receipt",
                        "operator": "contains",
                        "expected": funnel_tag,
                    },
                ],
                "verification": f"核对抽取的微信号、外发门禁/Shadow预览、CRM「{acq_tag}」建档回执及本我记忆落盘。",
            }

        if bp_id in ("feishu_digest_to_doc", "im_digest_to_doc"):
            ch = _resolve_im_channel(goal=goal, targets=targets)
            source_app = next(
                (t for t in targets if str(t.get("bundleID") or "").casefold() == str(ch["bundleID"]).casefold()),
                None,
            ) or {
                "bundleID": ch["bundleID"],
                "name": ch["name"],
                "category": "im_social",
            }
            label = str(ch["label"])
            c_slug = str(ch["slug"])
            textedit = {"bundleID": "com.apple.TextEdit", "name": "TextEdit", "category": "productivity"}
            digest_title = f"{label}协同简报"
            return {
                "id": wf_id,
                "name": f"{label}待办提取 -> 文本编辑工作简报 (自建)",
                "goal": goal,
                "summary": f"读取{label}当前聊天/待办 -> 提炼要点 -> 切换文本编辑新建文档写入简报并回读验收。",
                "targetApp": source_app,
                "parameters": [],
                "steps": [
                    {
                        "step": 1,
                        "action": "switch_app",
                        "title": f"探测{label}窗口与登录状态",
                        "targetApp": source_app,
                        "launchIfNeeded": True,
                    },
                    {
                        "step": 2,
                        "action": "inspect_ui",
                        "title": f"扫描{label}窗口待办与消息",
                        "captureAs": f"{c_slug}_raw_text",
                        "extractMode": "full",
                        "saveScreenshot": True,
                    },
                    {
                        "step": 3,
                        "action": "llm_extract",
                        "title": f"提炼{label}关键沟通内容",
                        "sourceVar": f"{c_slug}_raw_text",
                        "extractor": "llm",
                        "captureAs": f"{c_slug}_points",
                        "required": True,
                    },
                    {
                        "step": 4,
                        "action": "llm_draft",
                        "title": f"整理结构化{label}工作简报",
                        "template": f"【{{businessName}} · {digest_title}】\n整理人：{{ownerName}}\n要点摘要：\n{{{c_slug}_points}}",
                        "captureAs": "digest_doc",
                    },
                    {
                        "step": 5,
                        "action": "switch_app",
                        "title": "切换到文本编辑",
                        "targetApp": textedit,
                        "launchIfNeeded": True,
                    },
                    {
                        "step": 6,
                        "action": "press_shortcut",
                        "title": "新建空白简报文档 (Cmd+N)",
                        "combo": "cmd+n",
                        "delayMs": 120,
                    },
                    {
                        "step": 7,
                        "action": "focus_and_type",
                        "title": f"写入{label}工作简报正文",
                        "text": "{{digest_doc}}",
                        "relX": 0.5,
                        "relY": 0.5,
                        "clearFirst": True,
                        "submitAfter": False,
                    },
                    {
                        "step": 8,
                        "action": "wait_and_read",
                        "title": "回读文档内容确认写入成功",
                        "delaySec": 0.4,
                        "expectText": digest_title,
                        "saveScreenshot": True,
                    },
                    {
                        "step": 9,
                        "action": "assert_check",
                        "title": "独立断言：确认文档出现简报标题",
                        "evidenceSource": "post_ui_readback",
                        "operator": "contains",
                        "expected": digest_title,
                    },
                ],
                "verification": f"TextEdit 实测回读 OCR/AX 中包含「{digest_title}」与摘录要点。",
            }

        if bp_id == "calc_to_textedit_report":
            calc = {"bundleID": "com.apple.calculator", "name": "Calculator", "category": "productivity"}
            textedit = {"bundleID": "com.apple.TextEdit", "name": "TextEdit", "category": "productivity"}
            return {
                "id": wf_id,
                "name": "计算器验算 -> 文本编辑简报 (跨应用实测)",
                "goal": goal,
                "summary": "打开计算器计算表达式 -> 提取真实计算数值 -> 文本编辑新建文档写入简报 -> 独立回读断言验证。",
                "targetApp": calc,
                "parameters": [
                    {
                        "name": "expression",
                        "label": "计算按键序列",
                        "defaultValue": "1,2,5,*,8,return",
                        "required": True,
                        "description": "逗号分隔的计算器按键序列",
                    }
                ],
                "steps": [
                    {"step": 1, "action": "activate_app", "title": "激活计算器", "launchIfNeeded": True},
                    {"step": 2, "action": "press_shortcut", "title": "清空计算器", "combo": "escape", "delayMs": 90},
                    {"step": 3, "action": "press_shortcut", "title": "输入计算表达式", "sequence": "{{expression}}", "delayMs": 90},
                    {"step": 4, "action": "wait_and_read", "title": "回读计算器屏幕结果", "delaySec": 0.4, "captureAs": "calc_screen", "saveScreenshot": True},
                    {"step": 5, "action": "llm_extract", "title": "提取数值结果", "sourceVar": "calc_screen", "extractor": "number", "captureAs": "calc_value", "required": True},
                    {"step": 6, "action": "switch_app", "title": "切换到文本编辑", "targetApp": textedit, "launchIfNeeded": True},
                    {"step": 7, "action": "press_shortcut", "title": "新建文档 (Cmd+N)", "combo": "cmd+n", "delayMs": 120},
                    {"step": 8, "action": "focus_and_type", "title": "写入验算报告", "text": "WeChatBot 实机跨应用验算结果：{{calc_value}}", "relX": 0.5, "relY": 0.5, "clearFirst": True},
                    {"step": 9, "action": "wait_and_read", "title": "回读文本编辑窗口验证", "delaySec": 0.4, "captureAs": "doc_readback", "saveScreenshot": True},
                    {"step": 10, "action": "assert_check", "title": "独立断言：文档显示计算结果", "evidenceSource": "post_ui_readback", "operator": "contains", "expected": "{{calc_value}}"},
                ],
                "verification": "文本编辑窗口回读中包含真实计算结果数值。",
            }

        if bp_id == "calc_verify":
            calc = {"bundleID": "com.apple.calculator", "name": "Calculator", "category": "productivity"}
            return {
                "id": wf_id,
                "name": "计算器自动执行与断言验收",
                "goal": goal,
                "summary": "在计算器执行指定运算并对最终屏幕回读做独立断言验收。",
                "targetApp": calc,
                "parameters": [
                    {"name": "expression", "label": "按键序列", "defaultValue": "1,2,5,*,8,return", "required": True},
                    {"name": "expected_result", "label": "期望显示", "defaultValue": "1000", "required": True},
                ],
                "steps": [
                    {"step": 1, "action": "activate_app", "title": "激活计算器", "launchIfNeeded": True},
                    {"step": 2, "action": "press_shortcut", "title": "Escape 清零", "combo": "escape", "delayMs": 90},
                    {"step": 3, "action": "press_shortcut", "title": "键入计算序列", "sequence": "{{expression}}", "delayMs": 90},
                    {"step": 4, "action": "wait_and_read", "title": "等待刷新并读取计算器结果", "delaySec": 0.5, "waitUntilChanged": True, "captureAs": "calc_output", "saveScreenshot": True},
                    {"step": 5, "action": "assert_check", "title": "独立回读断言结果正确", "evidenceSource": "post_ui_readback", "operator": "contains", "expected": "{{expected_result}}"},
                ],
                "verification": "post_ui_readback 中可识别出预期数值 {{expected_result}}。",
            }

        # generic_unseen_app
        base_syn = self.engine.app_use.build_sop_and_workflow(
            goal=goal,
            bundle_id=str(primary.get("bundleID") or ""),
            app_name=str(primary.get("name") or ""),
            app_path=str(primary.get("appPath") or ""),
            inspect_live=False,
            save=False,
            pre_inspection=inspections.get(str(primary.get("bundleID") or primary.get("name") or "")),
        )
        wf = dict(base_syn.get("workflow") or {})
        steps = list(wf.get("steps") or [])
        if not any(s.get("action") == "assert_check" for s in steps):
            steps.append(
                {
                    "step": len(steps) + 1,
                    "action": "assert_check",
                    "title": "独立验证执行后界面非空",
                    "description": "依据最后一步窗口 AX+OCR 回读验证目标界面内容就绪。",
                    "evidenceSource": "post_ui_readback",
                    "operator": "not_empty",
                    "expected": "",
                }
            )
        wf["id"] = wf_id
        wf["steps"] = steps
        return wf

    def _run_omini_critic(self, *, spec: Dict[str, Any], lint_res: Dict[str, Any]) -> Dict[str, Any]:
        omini_bin = self.engine.app_use._find_cli_binary("omini")
        if not omini_bin:
            return {"ok": False, "skipped": True, "reason": "未检测到本地 omini CLI"}
        req_id = str(uuid.uuid4())
        prompt = (
            "请以严格架构 critic 审查以下自动化工作流 Spec 与静态 Linter 结果，指出潜在阻塞或假通过风险（<=220字）：\n"
            + json.dumps({"spec": spec, "lint": lint_res}, ensure_ascii=False)[:2200]
        )
        try:
            proc = self.engine.app_use._cli_runner(
                [omini_bin, "ask", "--role", "critic", "--id", req_id],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=35.0,
                env={**__import__("os").environ, "HOME": "/Users/mac"},
            )
            out = (proc.stdout or "").strip()
            if out.startswith("{"):
                parsed = json.loads(out)
                txt = str(parsed.get("responseText") or "").strip()
                if txt:
                    return {"ok": True, "requestId": req_id, "review": txt[:1200], "model": parsed.get("actualModel")}
            return {"ok": proc.returncode == 0, "requestId": req_id, "review": out[:1200]}
        except Exception as exc:
            return {"ok": False, "requestId": req_id, "error": str(exc)}

    def propose_spec(
        self,
        goal: str,
        *,
        target_apps: Optional[List[str]] = None,
        agent_id: str = "",
        inspect_live: bool = True,
        use_omini_critic: bool = False,
    ) -> Dict[str, Any]:
        """Generate an OpenSpec-style structured proposal, safety boundary, and draft workflow."""
        clean_goal = str(goal or "").strip()
        if not clean_goal:
            return {"ok": False, "error_code": "missing_goal", "error": "请用自然语言描述你想搭建的新场景或工作流目标。"}

        apps_res = self.engine.app_use.list_apps()
        installed = list(apps_res.get("apps") or [])
        targets = detect_apps_from_goal(clean_goal, installed_apps=installed, explicit_apps=target_apps)
        inspections: Dict[str, Dict[str, Any]] = {}
        auth_gates: List[Dict[str, Any]] = []

        if inspect_live:
            for t in targets[:3]:
                key = str(t.get("bundleID") or t.get("name") or "")
                if not key:
                    continue
                insp = self.engine.app_use.inspect_app(
                    bundle_id=str(t.get("bundleID") or ""),
                    app_name=str(t.get("name") or ""),
                    app_path=str(t.get("appPath") or ""),
                    launch_if_needed=False,
                    allow_activate=False,
                    max_nodes=140,
                )
                if insp.get("ok"):
                    inspections[key] = insp
                    modal = insp.get("modalStatus") or detect_modal_blocker(insp)
                    if modal.get("kind") == "auth_or_risk_gate":
                        auth_gates.append({"app": t.get("name"), "bundleID": t.get("bundleID"), "signals": modal.get("signals") or []})

        bp_id = self._select_blueprint_id(clean_goal, targets)
        draft_wf = self._synthesize_from_blueprint(bp_id=bp_id, goal=clean_goal, targets=targets, inspections=inspections)

        # Optional LLM enhancement when user picks a non-heuristic Agent and scenario is generic
        chosen_agent = str(agent_id or "").strip() or "local:heuristic"
        if not chosen_agent.startswith("local:") and bp_id == "generic_unseen_app":
            syn = self.engine.app_use.build_sop_and_workflow(
                goal=clean_goal,
                bundle_id=str((targets[0] if targets else {}).get("bundleID") or ""),
                app_name=str((targets[0] if targets else {}).get("name") or ""),
                agent_id=chosen_agent,
                inspect_live=False,
                save=False,
                pre_inspection=inspections.get(str((targets[0] if targets else {}).get("bundleID") or "")),
            )
            if syn.get("ok") and isinstance(syn.get("workflow"), dict):
                llm_wf = dict(syn["workflow"])
                if not any(s.get("action") == "assert_check" for s in (llm_wf.get("steps") or [])):
                    llm_wf["steps"] = list(llm_wf.get("steps") or []) + [
                        {
                            "step": len(llm_wf.get("steps") or []) + 1,
                            "action": "assert_check",
                            "title": "独立验证执行后界面非空",
                            "evidenceSource": "post_ui_readback",
                            "operator": "not_empty",
                            "expected": "",
                        }
                    ]
                draft_wf = llm_wf

        hardened_wf, fixes = WorkflowSpecLinter.auto_harden(draft_wf)
        lint_res = WorkflowSpecLinter.lint(hardened_wf)

        spec_id = f"spec_{hashlib.sha1(f'{clean_goal}|{time.time()}'.encode('utf-8')).hexdigest()[:8]}"
        spec: Dict[str, Any] = {
            "specId": spec_id,
            "blueprintId": bp_id,
            "proposal": clean_goal,
            "targetApps": [
                {
                    "bundleID": t.get("bundleID", ""),
                    "name": t.get("name", ""),
                    "riskTier": classify_app_risk_tier(str(t.get("bundleID") or ""), str(t.get("name") or "")).get("tier"),
                }
                for t in targets
            ],
            "inputs": [p.get("name") for p in (hardened_wf.get("parameters") or []) if p.get("name")],
            "outputs": [s.get("captureAs") for s in (hardened_wf.get("steps") or []) if s.get("captureAs")],
            "safetyBoundaries": [
                "禁止未通过白名单的外部工具与任意脚本执行",
                "禁止断言引用用户输入自证（强制要求动作后独立观测）",
                "高风险社交应用外发前强制 pause_for_human 门禁与 Shadow 预览拦截",
            ]
            + fixes,
            "acceptanceCriteria": [
                str(s.get("title") or "")
                for s in (hardened_wf.get("steps") or [])
                if s.get("action") in ("assert_check", "wait_and_read")
            ],
            "authGatesDetected": auth_gates,
            "lintReport": lint_res,
        }
        if use_omini_critic:
            spec["ominiCriticReview"] = self._run_omini_critic(spec=spec, lint_res=lint_res)

        return {
            "ok": True,
            "spec": spec,
            "workflow": hardened_wf,
            "lintReport": lint_res,
            "autoFixes": fixes,
        }

    def _compute_step_diff(self, before_steps: List[Dict[str, Any]], after_steps: List[Dict[str, Any]]) -> List[str]:
        diffs: List[str] = []
        if len(before_steps) != len(after_steps):
            diffs.append(f"步骤数从 {len(before_steps)} 调整为 {len(after_steps)}")
        max_len = min(len(before_steps), len(after_steps))
        for i in range(max_len):
            b, a = before_steps[i], after_steps[i]
            if b != a:
                b_desc = (
                    b.get("sequence")
                    or b.get("expected")
                    or b.get("template")
                    or (b.get("params") or {}).get("remark")
                    or b.get("targetAxTitle")
                    or b.get("combo")
                    or b.get("title")
                    or ""
                )
                a_desc = (
                    a.get("sequence")
                    or a.get("expected")
                    or a.get("template")
                    or (a.get("params") or {}).get("remark")
                    or a.get("targetAxTitle")
                    or a.get("combo")
                    or a.get("title")
                    or ""
                )
                diffs.append(f"Step {i + 1} [{a.get('action')}]: {b.get('delaySec', '-')}/{b_desc} -> {a.get('delaySec', '-')}/{a_desc}")
        return diffs or ["调整参数或插入前置恢复动作"]

    def _diagnose_and_patch(
        self,
        *,
        workflow: Dict[str, Any],
        run_res: Dict[str, Any],
        agent_id: str = "",
    ) -> Dict[str, Any]:
        """Classify failure and produce a bounded structural patch for the next debug round."""
        wf = copy.deepcopy(workflow)
        steps = list(wf.get("steps") or [])
        failed_idx = int(run_res.get("failedStep") or 0)
        step_results = list(run_res.get("stepResults") or [])

        # Also catch soft failures (e.g. wait_and_read expectText mismatch)
        failed_rec: Optional[Dict[str, Any]] = None
        if failed_idx > 0:
            failed_rec = next((r for r in reversed(step_results) if int(r.get("step") or 0) == failed_idx), None)
        if failed_rec is None:
            failed_rec = next((r for r in step_results if r.get("ok") is False), None)
            if failed_rec:
                failed_idx = int(failed_rec.get("step") or 0)

        target_pos = next((i for i, s in enumerate(steps) if int(s.get("step") or i + 1) == failed_idx), None)
        if target_pos is None and steps:
            target_pos = len(steps) - 1
            failed_idx = int(steps[target_pos].get("step") or len(steps))

        failed_step = dict(steps[target_pos]) if target_pos is not None else {}
        err_msg = str(run_res.get("error") or (failed_rec or {}).get("error") or run_res.get("error_code") or "step_failed")

        # Probe current app state read-only for diagnosis
        tapp = dict(wf.get("targetApp") or {})
        live_insp: Optional[Dict[str, Any]] = None
        if tapp.get("bundleID") or tapp.get("name"):
            probe = self.engine.app_use.inspect_app(
                bundle_id=str(tapp.get("bundleID") or ""),
                app_name=str(tapp.get("name") or ""),
                app_path=str(tapp.get("appPath") or ""),
                launch_if_needed=False,
                allow_activate=False,
                max_nodes=140,
            )
            if probe.get("ok"):
                live_insp = probe

        failure_info = classify_step_failure(failed_step, err_msg, live_insp)
        cat = str(failure_info.get("category") or "ELEMENT_DRIFT")
        if run_res.get("error_code") in ("EXTRACTION_EMPTY", "ASSERTION_FAILED", "TOOL_PARAM_ERROR", "UNWHITELISTED_TOOL"):
            cat = str(run_res["error_code"])
            if cat == "EXTRACTION_EMPTY":
                failure_info["category"] = "EXTRACTION_EMPTY"
            elif cat == "ASSERTION_FAILED":
                failure_info["category"] = "ASSERTION_FAILED"
            elif cat in ("TOOL_PARAM_ERROR", "UNWHITELISTED_TOOL"):
                failure_info["category"] = "TOOL_PARAM_ERROR"

        if failed_rec and failed_rec.get("failureCategory") == "AUTH_GATE":
            cat = "AUTH_GATE"

        err_key = str(run_res.get("error_code") or err_msg[:48])
        fingerprint = f"{failed_idx}|{cat}|{err_key}"

        if cat == "AUTH_GATE":
            return {
                "halt": True,
                "haltReason": "paused_auth_gate",
                "failureCategory": "AUTH_GATE",
                "fingerprint": fingerprint,
                "diagnosis": failure_info.get("reason") or "检测到登录或权限弹窗，已安全暂停，不做选择器改写。",
                "patchedWorkflow": wf,
                "patchSummary": "无（AUTH_GATE 禁止改写脚本）",
            }

        patched_steps = copy.deepcopy(steps)
        patch_summary = ""
        changed = False

        # 1. Modal occlusion -> insert Escape before failed step
        if cat == "MODAL_OCCLUSION" and target_pos is not None:
            patched_steps.insert(
                target_pos,
                {
                    "step": target_pos + 1,
                    "action": "press_shortcut",
                    "title": "自动修复：关闭干扰模态弹窗",
                    "combo": str(failure_info.get("dismissCombo") or "escape"),
                    "delayMs": 120,
                },
            )
            patch_summary = "在失败步骤前插入 Escape 关闭遮挡弹窗"
            changed = True

        # 2. Missing nav / not frontmost -> insert activate_app before failed step
        elif cat in ("NOT_FRONTMOST", "MISSING_NAV_STEP") and target_pos is not None:
            patched_steps.insert(
                target_pos,
                {
                    "step": target_pos + 1,
                    "action": "activate_app",
                    "title": f"自动修复：前置并唤醒 {tapp.get('name') or '目标应用'}",
                    "launchIfNeeded": True,
                },
            )
            patch_summary = "插入 activate_app 确保目标应用前置就绪"
            changed = True

        # 3. Element drift -> SemanticElementGrounder re-anchor
        elif cat == "ELEMENT_DRIFT" and target_pos is not None and failed_step.get("action") in ("click_element", "focus_and_type"):
            g = SemanticElementGrounder.resolve_best(failed_step, live_insp, min_score=0.32)
            if g.get("ok") and g.get("point"):
                b = g.get("anchorBundle") or {}
                s_new = dict(failed_step)
                s_new["x"] = float(g["point"][0])
                s_new["y"] = float(g["point"][1])
                for k in ("relX", "relY", "targetAxId", "targetAxTitle", "targetRole", "neighborTexts"):
                    if b.get(k) not in (None, "", []):
                        s_new[k] = b[k]
                patched_steps[target_pos] = s_new
                patch_summary = f"通过 SemanticElementGrounder 重定位元素 ({g.get('source', '')}, conf={g.get('confidence', 0)})"
                changed = True

        # 4. Timing lag / readback mismatch / assertion failed -> diagnose delay, missing wait/clear, or prior step
        elif cat in ("TIMING_LAG", "READBACK_MISMATCH", "ASSERTION_FAILED") and target_pos is not None:
            act = str(failed_step.get("action") or "")
            if act == "wait_and_read":
                s_new = dict(failed_step)
                s_new["delaySec"] = min(4.0, round(float(s_new.get("delaySec") or 0.4) + 1.0, 2))
                s_new["waitUntilChanged"] = True
                patched_steps[target_pos] = s_new
                patch_summary = f"提升 wait_and_read 等待至 {s_new['delaySec']}s 并开启 waitUntilChanged"
                changed = True
            elif act == "assert_check":
                # Check if there is a preceding wait_and_read we can harden (delaySec + waitUntilChanged),
                # or missing press_shortcut(escape) before press_shortcut(sequence) for Calculator-like bugs.
                prev_wait_pos = next(
                    (i for i in range(target_pos - 1, -1, -1) if str(patched_steps[i].get("action") or "") == "wait_and_read"),
                    None,
                )
                prev_seq_pos = next(
                    (i for i in range(target_pos - 1, -1, -1) if str(patched_steps[i].get("action") or "") == "press_shortcut" and patched_steps[i].get("sequence")),
                    None,
                )
                has_escape = any(
                    str(s.get("action") or "") == "press_shortcut" and str(s.get("combo") or "").lower() == "escape"
                    for s in patched_steps[:target_pos]
                )
                if prev_seq_pos is not None and not has_escape:
                    patched_steps.insert(
                        prev_seq_pos,
                        {
                            "step": prev_seq_pos + 1,
                            "action": "press_shortcut",
                            "title": "自动修复：计算前先连按两次 Escape 彻底清零 (AC)",
                            "combo": "escape",
                            "repeat": 2,
                            "delayMs": 120,
                        },
                    )
                    patch_summary = "诊断出连续按键前未清零，已在 sequence 前自动插入双 Escape (AC) 清零步骤"
                    changed = True
                elif prev_wait_pos is None:
                    patched_steps.insert(
                        target_pos,
                        {
                            "step": target_pos + 1,
                            "action": "wait_and_read",
                            "title": "自动修复：补充断言前界面稳定回读",
                            "delaySec": 0.8,
                            "waitUntilChanged": True,
                            "saveScreenshot": True,
                        },
                    )
                    patch_summary = "断言前缺少界面回读步骤，已自动插入 wait_and_read"
                    changed = True
                elif (
                    prev_seq_pos is not None
                    and str(patched_steps[prev_seq_pos].get("sequence") or "").strip().lower().endswith(",return")
                ):
                    seq_cur = dict(patched_steps[prev_seq_pos])
                    seq_cur["sequence"] = str(seq_cur["sequence"])[:-len(",return")] + ",=,return"
                    seq_cur["delayMs"] = max(120, int(seq_cur.get("delayMs") or 95))
                    patched_steps[prev_seq_pos] = seq_cur
                    patch_summary = "诊断出部分窗口回车键未触发求值，已将末尾 ,return 补全为 ,=,return 并放宽按键间隔"
                    changed = True
                elif prev_wait_pos is not None and float(patched_steps[prev_wait_pos].get("delaySec") or 0) < 0.8:
                    w_new = dict(patched_steps[prev_wait_pos])
                    w_new["delaySec"] = min(3.0, round(float(w_new.get("delaySec") or 0.2) + 0.9, 2))
                    w_new["waitUntilChanged"] = True
                    patched_steps[prev_wait_pos] = w_new
                    patch_summary = f"诊断出回读过快导致断言失败，已将 Step {prev_wait_pos + 1} 等待调至 {w_new['delaySec']}s"
                    changed = True

        # 5. Extraction empty -> broaden extractor or switch source to live readback / insert inspect_ui
        elif cat == "EXTRACTION_EMPTY" and target_pos is not None:
            s_new = dict(failed_step)
            if str(s_new.get("extractor") or "") == "regex" and not s_new.get("_broadened"):
                s_new["extractor"] = "wechat_accounts" if "微信号" in str(wf.get("goal") or "") else "llm"
                s_new["_broadened"] = True
                patched_steps[target_pos] = s_new
                patch_summary = f"将严格正则抽取放宽为 `{s_new['extractor']}` 智能抽取"
                changed = True
            elif target_pos == 0 or str(patched_steps[target_pos - 1].get("action") or "") not in ("inspect_ui", "wait_and_read"):
                patched_steps.insert(
                    target_pos,
                    {
                        "step": target_pos + 1,
                        "action": "inspect_ui",
                        "title": "自动修复：抽取前补充界面 OCR/AX 采集",
                        "captureAs": str(s_new.get("sourceVar") or "auto_readback_text"),
                        "saveScreenshot": True,
                    },
                )
                patch_summary = "抽取前缺少最新界面采集，已自动插入 inspect_ui"
                changed = True

        # 6. Tool param error -> map missing account/target from capturedVars
        elif cat == "TOOL_PARAM_ERROR" and target_pos is not None:
            s_new = dict(failed_step)
            tparams = dict(s_new.get("params") or {})
            cap_vars = dict(run_res.get("capturedVars") or {})
            if not tparams.get("account") and cap_vars.get("wechat_account"):
                tparams["account"] = "{{wechat_account}}"
                s_new["params"] = tparams
                patched_steps[target_pos] = s_new
                patch_summary = "补全 builtin_tool 缺失参数 account={{wechat_account}}"
                changed = True
            elif not tparams.get("target") and (cap_vars.get("source_user") or (wf.get("parameters") or [])):
                tparams["target"] = "{{source_user}}"
                s_new["params"] = tparams
                patched_steps[target_pos] = s_new
                patch_summary = "补全 builtin_tool 缺失参数 target={{source_user}}"
                changed = True

        # 7. Optional LLM Debugger fallback if deterministic patchers did not resolve
        if not changed and agent_id and not str(agent_id).startswith("local:") and not str(agent_id).startswith("cli:"):
            mid = str(agent_id).split(":", 1)[1] if str(agent_id).startswith("magpie:") else str(agent_id)
            dbg_prompt = (
                "你是自动化工作流自调试专家。请针对当前失败步骤返回单步修复 JSON：\n"
                '{"operation":"modify_step"|"insert_before","stepIndex":1,"patch":{...},"diagnosis":"原因"}\n'
                "禁止禁用或删除 assert_check。只输出 JSON。"
            )
            ctx = {
                "failedStep": failed_step,
                "error": err_msg,
                "failureCategory": cat,
                "stepsCount": len(steps),
                "ocrSample": (live_insp or {}).get("ocrPreview", "")[:500],
            }
            llm = self.engine.models.generate_chat_reply(
                [{"role": "system", "content": dbg_prompt}, {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
                model_id=mid,
                max_tokens=600,
                temperature=0.1,
                timeout=20.0,
            )
            if llm.get("ok"):
                parsed = _extract_json_object(str(llm.get("replyText") or ""))
                if isinstance(parsed, dict) and isinstance(parsed.get("patch"), dict) and target_pos is not None:
                    op = str(parsed.get("operation") or "modify_step")
                    if op == "insert_before" and str(parsed["patch"].get("action") or "") in SUPPORTED_STEP_ACTIONS:
                        patched_steps.insert(target_pos, dict(parsed["patch"]))
                        patch_summary = str(parsed.get("diagnosis") or "AI 调试器前置插入恢复步骤")
                        changed = True
                    elif op == "modify_step":
                        merged = dict(patched_steps[target_pos], **parsed["patch"])
                        if merged.get("action") == patched_steps[target_pos].get("action"):
                            patched_steps[target_pos] = merged
                            patch_summary = str(parsed.get("diagnosis") or "AI 调试器修正失败步骤参数")
                            changed = True

        for i, s in enumerate(patched_steps, start=1):
            s["step"] = i
        wf["steps"] = self.engine.app_use._normalize_steps(patched_steps)
        wf, harden_fixes = WorkflowSpecLinter.auto_harden(wf)
        lint_after = WorkflowSpecLinter.lint(wf)
        if not lint_after.get("ok"):
            return {
                "halt": True,
                "haltReason": "linter_rejected_patch",
                "failureCategory": cat,
                "fingerprint": fingerprint,
                "diagnosis": f"补丁未通过安全 Linter 审查: {lint_after.get('errors')}",
                "patchedWorkflow": workflow,
                "patchSummary": patch_summary or "被 Linter 拦截",
            }

        revs = list(wf.get("revisionHistory") or [])
        revs.append(
            {
                "version": int(wf.get("version") or 1),
                "savedAt": _utc_iso_now(),
                "reason": patch_summary or f"自调试诊断修复 ({cat})",
                "name": str(workflow.get("name") or ""),
                "parameters": copy.deepcopy(workflow.get("parameters") or []),
                "steps": copy.deepcopy(steps),
                "sopMarkdown": workflow.get("sopMarkdown") or "",
            }
        )
        wf["revisionHistory"] = revs[-12:]
        wf["version"] = int(wf.get("version") or 1) + 1
        wf["sopMarkdown"] = self.engine.app_use._render_sop_markdown(wf)
        step_diffs = self._compute_step_diff(steps, wf["steps"])
        if harden_fixes:
            step_diffs.extend(harden_fixes)

        return {
            "halt": False,
            "changed": changed,
            "failureCategory": cat,
            "fingerprint": fingerprint,
            "diagnosis": failure_info.get("reason") or err_msg,
            "patchSummary": patch_summary or f"已尝试针对 {cat} 生成新版本 v{wf['version']}",
            "stepDiffs": step_diffs,
            "patchedWorkflow": wf,
        }

    def author_and_debug(
        self,
        goal: str,
        *,
        target_apps: Optional[List[str]] = None,
        agent_id: str = "",
        mode: str = "shadow",
        max_debug_rounds: int = 4,
        confirm_run: bool = False,
        respect_human_guard: bool = True,
        inspect_live: bool = True,
        use_omini_critic: bool = False,
        auto_export_skill: bool = False,
        params: Optional[Dict[str, Any]] = None,
        initial_workflow: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """End-to-end Spec -> Synthesize v1 -> Run -> Diagnose -> Patch -> Verify loop."""
        eff_mode = str(mode or "shadow").strip().lower()
        if eff_mode not in ("dry_run", "shadow", "live"):
            eff_mode = "shadow"
        if eff_mode == "live" and not confirm_run:
            return {
                "ok": False,
                "error_code": "confirmation_required",
                "error": "实机联跑调试 (mode='live') 须显式传入 confirm_run=true。",
            }

        rounds_budget = max(1, min(5, int(max_debug_rounds or 4)))
        if isinstance(initial_workflow, dict):
            cur_wf, _ = WorkflowSpecLinter.auto_harden(dict(initial_workflow))
            spec_res = {
                "ok": True,
                "spec": {
                    "specId": f"spec_{uuid.uuid4().hex[:8]}",
                    "proposal": cur_wf.get("goal") or goal or cur_wf.get("name") or "",
                    "lintReport": WorkflowSpecLinter.lint(cur_wf),
                },
            }
        else:
            spec_res = self.propose_spec(
                goal,
                target_apps=target_apps,
                agent_id=agent_id,
                inspect_live=inspect_live,
                use_omini_critic=use_omini_critic,
            )
            if not spec_res.get("ok"):
                return spec_res
            cur_wf = dict(spec_res["workflow"])

        spec_doc = dict(spec_res["spec"])
        session_id = f"wfa_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        cur_wf["debugSessionId"] = session_id
        cur_wf["spec"] = spec_doc
        self.engine.app_use.save_workflow(cur_wf, sop_markdown=str(cur_wf.get("sopMarkdown") or ""))

        debug_rounds: List[Dict[str, Any]] = []
        patch_diffs_history: List[Dict[str, Any]] = []
        prev_fingerprint = ""
        final_status = "max_rounds_reached"
        final_run: Dict[str, Any] = {}
        exported_skill: Optional[Dict[str, Any]] = None

        for r_idx in range(1, rounds_budget + 1):
            run_res = self.engine.app_use.run_workflow(
                workflow_id=str(cur_wf["id"]),
                params=params,
                dry_run=(eff_mode == "dry_run"),
                execution_mode=eff_mode,
                confirm_run=confirm_run,
                respect_human_guard=respect_human_guard,
                self_heal=True,
                heal_agent_id=agent_id,
            )
            final_run = run_res
            step_results = list(run_res.get("stepResults") or [])
            soft_fail = next((sr for sr in step_results if sr.get("ok") is False), None)
            auth_paused = any(sr.get("failureCategory") == "AUTH_GATE" for sr in step_results)
            assertions_ok = bool(run_res.get("allAssertionsPassed", True))

            shot_path = str((run_res.get("finalReadback") or {}).get("savedPath") or "")
            raw_previews = list(run_res.get("shadowPreviews") or [])
            round_entry: Dict[str, Any] = {
                "round": r_idx,
                "workflowVersion": int(cur_wf.get("version") or 1),
                "executionMode": eff_mode,
                "evidenceLevel": run_res.get("evidenceLevel", ""),
                "ok": bool(run_res.get("ok")) and soft_fail is None and assertions_ok and not auth_paused,
                "pausedForHuman": bool(run_res.get("pausedForHuman")),
                "shadowPreviewsCount": len(raw_previews),
                "shadowPreviews": copy.deepcopy(raw_previews[:8]),
                "assertionResults": run_res.get("assertionResults") or [],
                "errorCode": run_res.get("error_code") or ("ASSERTION_FAILED" if not assertions_ok else ("AUTH_GATE" if auth_paused else "")),
                "error": run_res.get("error") or (f"Step {soft_fail.get('step')} 未满足验收条件" if soft_fail else ""),
                "screenshotPath": shot_path,
                "artifactName": Path(shot_path).name if shot_path else "",
            }

            if auth_paused:
                final_status = "paused_auth_gate"
                round_entry["haltReason"] = "AUTH_GATE"
                debug_rounds.append(round_entry)
                break

            if run_res.get("error_code") == "human_activity_guard_paused":
                final_status = "paused_human_guard"
                round_entry["haltReason"] = "human_activity_guard_paused"
                debug_rounds.append(round_entry)
                break

            if round_entry["ok"]:
                if eff_mode == "dry_run":
                    cur_wf["verificationStatus"] = "dry_run_only"
                    final_status = "dry_run_passed"
                elif eff_mode == "shadow":
                    cur_wf["verificationStatus"] = "shadow_verified"
                    final_status = "shadow_verified"
                else:
                    cur_wf["verificationStatus"] = "verified"
                    final_status = "verified"
                cur_wf["compiledDeterministic"] = eff_mode in ("shadow", "live")
                cur_wf["evidenceLevel"] = run_res.get("evidenceLevel", "")
                cur_wf["verifiedAt"] = _utc_iso_now()
                cur_wf["readiness"] = score_workflow_readiness(cur_wf)
                cur_wf["sopMarkdown"] = self.engine.app_use._render_sop_markdown(cur_wf)
                self.engine.app_use.save_workflow(cur_wf, sop_markdown=cur_wf["sopMarkdown"])
                if auto_export_skill:
                    exported_skill = self.engine.app_use.export_workflow_as_skill(str(cur_wf["id"]))
                debug_rounds.append(round_entry)
                break

            # Failure path -> Diagnose & Patch (unless already on last round)
            if soft_fail is not None and not run_res.get("failedStep"):
                sf_err = str(soft_fail.get("error") or "").strip()
                if not sf_err:
                    sf_err = (
                        "window_not_found"
                        if soft_fail.get("action") == "inspect_ui"
                        else f"expectText '{soft_fail.get('expectText') or ''}' mismatch"
                    )
                run_res = {
                    **run_res,
                    "failedStep": soft_fail.get("step"),
                    "error": run_res.get("error") or sf_err,
                }
            diag = self._diagnose_and_patch(workflow=cur_wf, run_res=run_res, agent_id=agent_id)
            round_entry["failureCategory"] = diag.get("failureCategory")
            round_entry["fingerprint"] = diag.get("fingerprint")
            round_entry["diagnosis"] = diag.get("diagnosis")
            round_entry["patchSummary"] = diag.get("patchSummary")
            round_entry["stepDiffs"] = diag.get("stepDiffs") or []

            if diag.get("halt"):
                final_status = str(diag.get("haltReason") or "paused_auth_gate")
                debug_rounds.append(round_entry)
                break

            fp = str(diag.get("fingerprint") or "")
            if prev_fingerprint and fp == prev_fingerprint:
                final_status = "needs_human_demo"
                round_entry["haltReason"] = "duplicate_failure_fingerprint"
                round_entry["lastTwoPatchDiffs"] = patch_diffs_history[-2:]
                debug_rounds.append(round_entry)
                break
            prev_fingerprint = fp

            if r_idx < rounds_budget:
                cur_wf = dict(diag["patchedWorkflow"])
                self.engine.app_use.save_workflow(cur_wf, sop_markdown=str(cur_wf.get("sopMarkdown") or ""))
                patch_diffs_history.append(
                    {"round": r_idx, "toVersion": cur_wf.get("version"), "summary": diag.get("patchSummary"), "diffs": diag.get("stepDiffs") or []}
                )
            debug_rounds.append(round_entry)

        session_doc: Dict[str, Any] = {
            "sessionId": session_id,
            "goal": str(goal or cur_wf.get("goal") or ""),
            "mode": eff_mode,
            "status": final_status,
            "ok": final_status in ("verified", "shadow_verified", "dry_run_passed"),
            "workflowId": cur_wf.get("id", ""),
            "workflowVersion": cur_wf.get("version", 1),
            "verificationStatus": cur_wf.get("verificationStatus", "unverified"),
            "roundsUsed": len(debug_rounds),
            "maxDebugRounds": rounds_budget,
            "spec": spec_doc,
            "debugRounds": debug_rounds,
            "patchDiffs": patch_diffs_history,
            "lastRun": final_run,
            "exportedSkill": exported_skill,
            "createdAt": _utc_iso_now(),
        }
        smap = self._state.setdefault("sessions", {})
        smap[session_id] = session_doc
        order = [sid for sid in (self._state.get("order") or []) if sid != session_id]
        self._state["order"] = [session_id] + order[:49]
        self._save_sessions()

        return {
            **session_doc,
            "workflow": cur_wf,
        }

    def debug_existing_workflow(
        self,
        workflow_id: str,
        *,
        mode: str = "shadow",
        max_debug_rounds: int = 3,
        confirm_run: bool = False,
        respect_human_guard: bool = True,
        agent_id: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the closed-loop self-debugger against an already saved App-Use workflow."""
        wid = str(workflow_id or "").strip()
        stored = (self.engine.app_use._state.get("workflows") or {}).get(wid)
        if not isinstance(stored, dict):
            return {"ok": False, "error_code": "workflow_not_found", "error": f"未找到流程 {wid}"}
        return self.author_and_debug(
            str(stored.get("goal") or stored.get("name") or wid),
            agent_id=agent_id,
            mode=mode,
            max_debug_rounds=max_debug_rounds,
            confirm_run=confirm_run,
            respect_human_guard=respect_human_guard,
            inspect_live=False,
            params=params,
            initial_workflow=dict(stored),
        )

    # ------------------------------------------------------------------
    # Conversational Chat-to-Workflow & Chat-to-Edit (v3.2)
    # ------------------------------------------------------------------

    @staticmethod
    def _expr_to_key_sequence(expr: str) -> str:
        clean = (
            str(expr or "")
            .strip()
            .replace("×", "*")
            .replace("x", "*")
            .replace("X", "*")
            .replace("÷", "/")
            .replace("＝", "=")
            .replace(" ", "")
            .rstrip("=")
        )
        if not clean:
            return ""
        return ",".join(list(clean)) + ",return"

    @staticmethod
    def _detect_existing_remark_prefix(wf: Dict[str, Any]) -> str:
        for st in wf.get("steps") or []:
            if not isinstance(st, dict):
                continue
            params = st.get("params") if isinstance(st.get("params"), dict) else {}
            for key in ("remark", "target"):
                val = str(params.get(key) or "").strip()
                if "{{source_user}}" in val:
                    head = val.split("{{source_user}}", 1)[0].strip()
                    if head:
                        return head
        return "飞书引流-"

    @staticmethod
    def _rewrite_remark_prefix_in_workflow(wf: Dict[str, Any], new_prefix: str) -> bool:
        raw_prefix = str(new_prefix or "").strip()
        if not raw_prefix:
            return False
        old_full = WorkflowAuthorDebugger._detect_existing_remark_prefix(wf)
        old_clean = old_full.rstrip("-_:：") or "飞书引流"
        new_clean = raw_prefix.rstrip("-_:：") or raw_prefix
        sep = "" if raw_prefix.endswith(("-", "_", ":", "：")) else "-"
        new_full = f"{raw_prefix}{sep}"
        changed = False

        if isinstance(wf.get("summary"), str) and old_clean in wf["summary"]:
            wf["summary"] = wf["summary"].replace(old_full, new_full).replace(old_clean, new_clean)
            changed = True

        for st in wf.get("steps") or []:
            if not isinstance(st, dict):
                continue
            for field in ("title", "message", "description"):
                val = st.get(field)
                if isinstance(val, str) and (old_full in val or old_clean in val):
                    st[field] = val.replace(old_full, new_full).replace(old_clean, new_clean)
                    changed = True
            params = st.get("params")
            if isinstance(params, dict):
                for pkey in ("remark", "target"):
                    if pkey in params and isinstance(params[pkey], str):
                        pval = params[pkey]
                        if "{{source_user}}" in pval:
                            params[pkey] = f"{new_full}{{{{source_user}}}}"
                        elif old_full in pval or old_clean in pval:
                            params[pkey] = pval.replace(old_full, new_full).replace(old_clean, new_clean)
                        else:
                            params[pkey] = f"{new_full}{pval}"
                        changed = True
                for pkey in ("note", "content"):
                    if pkey in params and isinstance(params[pkey], str) and (old_full in params[pkey] or old_clean in params[pkey]):
                        params[pkey] = params[pkey].replace(old_full, new_full).replace(old_clean, new_clean)
                        changed = True
                if isinstance(params.get("tags"), list):
                    new_tags = []
                    for tg in params["tags"]:
                        ts = str(tg)
                        if ts == old_clean:
                            new_tags.append(new_clean)
                            changed = True
                        else:
                            new_tags.append(ts)
                    if new_clean not in new_tags and st.get("tool") == "crm_enroll":
                        new_tags.append(new_clean)
                        changed = True
                    params["tags"] = new_tags
            if st.get("action") == "assert_check":
                exp = str(st.get("expected") or "")
                if exp == old_clean or old_clean in exp:
                    st["expected"] = new_clean if exp == old_clean else exp.replace(old_full, new_full).replace(old_clean, new_clean)
                    changed = True
        return changed

    @staticmethod
    def _rewrite_greeting_in_workflow(
        wf: Dict[str, Any],
        *,
        skip_greeting: bool = False,
        new_greeting: str = "",
    ) -> bool:
        steps = list(wf.get("steps") or [])
        changed = False
        if skip_greeting:
            filtered: List[Dict[str, Any]] = []
            for st in steps:
                if (
                    isinstance(st, dict)
                    and st.get("action") == "llm_draft"
                    and (
                        str(st.get("captureAs") or "") == "friend_greeting"
                        or "话术" in str(st.get("title") or "")
                        or "自报家门" in str(st.get("title") or "")
                        or "验证" in str(st.get("kbQuery") or "")
                    )
                ):
                    changed = True
                    continue
                if isinstance(st, dict) and st.get("action") == "builtin_tool" and st.get("tool") == "wechat_add_friend":
                    params = dict(st.get("params") or {})
                    if params.get("greeting") != "":
                        params["greeting"] = ""
                        st["params"] = params
                        changed = True
                filtered.append(st)
            wf["steps"] = filtered
            return changed

        clean_greet = str(new_greeting or "").strip()
        if not clean_greet:
            return False
        updated_draft = False
        for st in steps:
            if isinstance(st, dict) and st.get("action") == "llm_draft":
                st["template"] = clean_greet
                updated_draft = True
                changed = True
        if not updated_draft:
            for st in steps:
                if isinstance(st, dict) and st.get("action") == "builtin_tool" and st.get("tool") == "wechat_add_friend":
                    params = dict(st.get("params") or {})
                    params["greeting"] = clean_greet
                    st["params"] = params
                    changed = True
        return changed

    @staticmethod
    def _is_confirm_trigger(text: str, *, current_phase: str = "clarifying") -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        low = raw.casefold().strip("！!。.~～，, ")
        explicit_phrases = (
            "开始调试",
            "直接生成",
            "生成并调试",
            "确认并调试",
            "确认并自动调试",
            "确认生成",
            "立即生成",
            "开始生成",
        )
        if any(p in low for p in explicit_phrases):
            return True
        if current_phase == "ready_to_build":
            if re.search(r"(?:不需要|不用|不要|需要|保留)(?:人工)?(?:确认|门禁)", low):
                return False
            short_ok = ("确认", "开始", "好", "好的", "可以", "行", "没问题", "就这么办", "ok", "yes", "confirm", "go")
            if low in short_ok:
                return True
        return False

    def _parse_chat_slots(self, text: str, cfg: Dict[str, Any]) -> None:
        raw = str(text or "").strip()
        low = raw.casefold()
        if not cfg.get("goal"):
            cfg["goal"] = raw
        turns = list(cfg.get("_turns") or [])
        if raw and (not turns or turns[-1] != raw):
            turns.append(raw)
        cfg["_turns"] = turns

        # 1. Detect explicit app mentions without falling back to an unrelated default app
        scan_low_no_wecom = re.sub(r"企业微信", "____", low)
        found_pos: List[Tuple[int, str]] = []
        for keywords, meta in _APP_ALIAS_CATALOG:
            haystack = scan_low_no_wecom if meta.get("bundleID") == "com.tencent.xinWeChat" else low
            pos = [haystack.find(kw) for kw in keywords if kw in haystack]
            if pos:
                found_pos.append((min(pos), str(meta.get("bundleID") or "")))
        found_pos.sort(key=lambda item: item[0])
        apps = list(cfg.get("targetApps") or [])
        for _, bid in found_pos:
            if bid and bid not in apps:
                apps.append(bid)

        # 2. Action intent (generalized across Feishu / DingTalk / WeCom / Douyin / Xiaohongshu)
        combined_text = f"{cfg.get('goal') or ''} {raw}".strip()
        target_objs = [{"bundleID": b} for b in apps]
        detected_im = _detect_explicit_im_channel(goal=combined_text, targets=target_objs)

        if any(k in low for k in ("提取微信号", "微信号", "加微信", "加好友", "crm", "建档", "获客", "引流")):
            ch = detected_im or _resolve_im_channel(goal=combined_text, targets=target_objs)
            cfg["actionType"] = "feishu_to_wechat_crm" if ch["slug"] == "feishu" else "im_to_wechat_crm"
            if ch["bundleID"] not in apps and detected_im is not None:
                apps.insert(0, str(ch["bundleID"]))
            if "com.tencent.xinWeChat" not in apps:
                apps.append("com.tencent.xinWeChat")
        elif any(k in low for k in ("汇总", "待办", "简报", "写文档", "生成文档", "文本编辑", "纪要")) and "计算器" not in low:
            ch = detected_im or _resolve_im_channel(goal=combined_text, targets=target_objs)
            cfg["actionType"] = "feishu_digest_to_doc" if ch["slug"] == "feishu" else "im_digest_to_doc"
            if ch["bundleID"] not in apps and detected_im is not None:
                apps.insert(0, str(ch["bundleID"]))
            if "com.apple.TextEdit" not in apps:
                apps.append("com.apple.TextEdit")
        elif "计算器" in low or "calc" in low or re.search(r"\d+(?:\.\d+)?\s*[+\-*/×÷]\s*\d+(?:\.\d+)?", raw):
            if "com.apple.calculator" not in apps:
                apps.append("com.apple.calculator")
            if any(k in low for k in ("文本编辑", "简报", "文档", "报告")):
                cfg["actionType"] = "calc_to_textedit_report"
                if "com.apple.TextEdit" not in apps:
                    apps.append("com.apple.TextEdit")
            elif not cfg.get("actionType"):
                cfg["actionType"] = "calc_verify"

        cfg["targetApps"] = apps

        # 3. Remark prefix
        m_rem = re.search(
            r"备注(?:前缀|名称|格式)?\s*(?:用|设为|为|是|改成|改为|换成|[:：])?\s*[「『\"“']?([A-Za-z0-9\u4e00-\u9fff_-]{2,24})[」』\"”']?",
            raw,
        )
        if m_rem:
            cand = m_rem.group(1).strip()
            if cand not in ("前缀", "什么", "怎么", "不需要", "不用", "无", "为空", "需要", "确认", "格式"):
                cfg["remarkPrefix"] = cand
        else:
            m_bare_rem = re.match(r"^[「『\"“']?([A-Za-z0-9\u4e00-\u9fff_]{2,20}-)[」』\"”']?$", raw)
            if m_bare_rem:
                cfg["remarkPrefix"] = m_bare_rem.group(1).strip()

        # 4. Greeting / self-introduction
        if re.search(r"(?:不需要|不用|不要|去掉|取消|不发)(?:发|发送)?(?:自我介绍|验证语|打招呼|开场白)", raw):
            cfg["skipGreeting"] = True
            cfg["greeting"] = ""
        else:
            if "发自报家门话术" in raw:
                cfg["skipGreeting"] = False
            m_gr = re.search(
                r"(?:自我介绍|验证语|话术|打招呼语)\s*(?:用|设为|为|改成|改为|换成|[:：])\s*[「『\"“']?([^，。,;；」』\"”'\n]{3,120})[」』\"”']?",
                raw,
            )
            if m_gr:
                cfg["skipGreeting"] = False
                cfg["greeting"] = m_gr.group(1).strip()

        # 5. Confirm gate
        if re.search(r"(?:不需要|不用|不要|免|取消|关闭)(?:我|人工|操作员)?(?:确认|门禁)", raw):
            cfg["requireConfirm"] = False
            cfg["_confirmAnswered"] = True
        elif re.search(
            r"(?:需要|保留|开启|加|要)(?:我|人工|操作员)?(?:确认|门禁)|人工确认|shadow试跑|仅shadow|仅影子模式",
            low,
        ):
            cfg["requireConfirm"] = True
            cfg["_confirmAnswered"] = True
            if "仅影子模式" in raw or "仅shadow" in low:
                cfg["mode"] = "shadow"

        # 6. Calculator expression & expected output
        m_expr = re.search(r"(\d+(?:\.\d+)?\s*[+\-*/×÷]\s*\d+(?:\.\d+)?)", raw)
        if m_expr:
            cfg["calcExpression"] = m_expr.group(1).strip()
        m_exp = re.search(r"(?:期望|预期|结果|断言)(?:为|是|改成|改为|[:：])?\s*(\d+(?:\.\d+)?)", raw)
        if m_exp:
            cfg["calcExpected"] = m_exp.group(1).strip()

    def _missing_chat_questions(self, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        questions: List[Dict[str, Any]] = []
        apps = list(cfg.get("targetApps") or [])
        goal_text = str(cfg.get("goal") or "")
        action_type = str(cfg.get("actionType") or "")
        target_objs = [{"bundleID": b} for b in apps]
        source_im = _detect_explicit_im_channel(goal=goal_text, targets=target_objs)

        if not apps:
            questions.append(
                {
                    "id": "target_apps",
                    "question": "这个流程主要涉及哪些桌面应用？",
                    "options": ["飞书 + 微信", "钉钉 + 微信", "飞书 + 文本编辑", "计算器 + 文本编辑"],
                }
            )
        if source_im is not None and not action_type:
            questions.append(
                {
                    "id": "action_type",
                    "question": f"你想让{source_im['label']}同步具体完成什么动作？",
                    "options": ["提取微信号加微信", "汇总待办写文档"],
                }
            )
        needs_wechat_details = action_type in ("feishu_to_wechat_crm", "im_to_wechat_crm") or (
            "com.tencent.xinWeChat" in apps and action_type not in ("feishu_digest_to_doc", "im_digest_to_doc")
        )
        if needs_wechat_details:
            ch = source_im or _resolve_im_channel(goal=goal_text, targets=target_objs)
            if not str(cfg.get("remarkPrefix") or "").strip():
                questions.append(
                    {
                        "id": "remark_prefix",
                        "question": "加微信好友时，希望统一使用什么备注前缀？",
                        "options": [f"备注用{ch['defaultRemark']}", f"备注用{ch['label']}VIP-", "备注用潜客-"],
                    }
                )
            if not cfg.get("_confirmAnswered"):
                questions.append(
                    {
                        "id": "confirm_gate",
                        "question": "外发加好友前是否保留人工确认门禁？另外需要发自我介绍话术吗？",
                        "options": [
                            "需要人工确认 + 发自报家门话术（推荐）",
                            "需要人工确认，不发自我介绍",
                            "仅影子模式自动试跑",
                        ],
                    }
                )
        elif not action_type and apps and source_im is None and "com.apple.calculator" not in apps:
            if not cfg.get("_confirmAnswered"):
                questions.append(
                    {
                        "id": "confirm_gate",
                        "question": "执行关键写入或外发动作前，是否需要人工确认门禁？",
                        "options": ["需要人工确认（推荐）", "不需要确认"],
                    }
                )
        return questions[:3]

    def _apply_chat_config_to_workflow(self, wf: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
        edited = copy.deepcopy(wf)
        remark_prefix = str(cfg.get("remarkPrefix") or "").strip()
        if remark_prefix:
            self._rewrite_remark_prefix_in_workflow(edited, remark_prefix)

        if cfg.get("skipGreeting") or cfg.get("greeting"):
            self._rewrite_greeting_in_workflow(
                edited,
                skip_greeting=bool(cfg.get("skipGreeting")),
                new_greeting=str(cfg.get("greeting") or ""),
            )

        require_confirm = bool(cfg.get("requireConfirm", True))
        confirm_explicit = bool(cfg.get("_confirmAnswered", False))
        steps = list(edited.get("steps") or [])
        has_wechat_add = any(isinstance(s, dict) and s.get("tool") == "wechat_add_friend" for s in steps)
        has_gate = any(isinstance(s, dict) and s.get("action") == "pause_for_human" for s in steps)
        if require_confirm and confirm_explicit and not has_gate:
            insert_idx = next(
                (i for i, s in enumerate(steps) if isinstance(s, dict) and s.get("action") in ("focus_and_type", "builtin_tool", "assert_check")),
                len(steps),
            )
            steps.insert(
                insert_idx,
                {
                    "step": insert_idx + 1,
                    "action": "pause_for_human",
                    "title": "执行前人工确认门禁",
                    "description": "安全护栏：人工核对当前提取结果与参数后再继续执行。",
                    "message": "请核对当前数据后确认继续。",
                },
            )
        elif not require_confirm and not has_wechat_add:
            steps = [s for s in steps if not (isinstance(s, dict) and s.get("action") == "pause_for_human")]

        if cfg.get("calcExpression"):
            seq = self._expr_to_key_sequence(str(cfg["calcExpression"]))
            if seq:
                for s in steps:
                    if isinstance(s, dict) and s.get("action") == "press_shortcut" and s.get("sequence"):
                        s["sequence"] = seq
                for p in edited.get("parameters") or []:
                    if isinstance(p, dict) and p.get("name") == "expression":
                        p["defaultValue"] = seq
        if cfg.get("calcExpected"):
            exp_val = str(cfg["calcExpected"]).strip()
            for s in steps:
                if isinstance(s, dict) and s.get("action") == "assert_check":
                    s["expected"] = exp_val
            for p in edited.get("parameters") or []:
                if isinstance(p, dict) and p.get("name") == "expected_result":
                    p["defaultValue"] = exp_val

        for idx, st in enumerate(steps, start=1):
            if isinstance(st, dict):
                st["step"] = idx
        edited["steps"] = self.engine.app_use._normalize_steps(steps)
        edited, _ = WorkflowSpecLinter.auto_harden(edited)
        edited["sopMarkdown"] = self.engine.app_use._render_sop_markdown(edited)
        return edited

    def _build_chat_spec_and_workflow(self, cfg: Dict[str, Any], *, agent_id: str = "") -> Dict[str, Any]:
        base_goal = str(cfg.get("goal") or "").strip()
        target_objs = [{"bundleID": b} for b in (cfg.get("targetApps") or [])]
        ch = _resolve_im_channel(goal=base_goal, targets=target_objs)
        goal_parts = [base_goal]
        if cfg.get("actionType") in ("feishu_to_wechat_crm", "im_to_wechat_crm"):
            goal_parts.append(f"从{ch['label']}提取微信号加微信好友并写入CRM")
        elif cfg.get("actionType") in ("feishu_digest_to_doc", "im_digest_to_doc"):
            goal_parts.append(f"读取{ch['label']}待办并汇总写入文本编辑简报")
        if cfg.get("remarkPrefix"):
            goal_parts.append(f"备注前缀 {cfg['remarkPrefix']}")
        combined_goal = "；".join([p for p in goal_parts if p])

        spec_res = self.propose_spec(
            combined_goal,
            target_apps=list(cfg.get("targetApps") or []) or None,
            agent_id=agent_id,
            inspect_live=False,
            use_omini_critic=False,
        )
        if not spec_res.get("ok"):
            return spec_res
        wf = self._apply_chat_config_to_workflow(spec_res["workflow"], cfg)
        lint_res = WorkflowSpecLinter.lint(wf)
        spec = dict(spec_res["spec"])
        spec["lintReport"] = lint_res
        spec["acceptanceCriteria"] = [
            str(s.get("title") or "")
            for s in (wf.get("steps") or [])
            if s.get("action") in ("assert_check", "wait_and_read")
        ]
        return {"ok": True, "spec": spec, "workflow": wf, "lintReport": lint_res}

    @staticmethod
    def _public_collected_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
        apps = list(cfg.get("targetApps") or [])
        return {
            "goal": str(cfg.get("goal") or ""),
            "targetApps": apps,
            "targetAppLabels": [_friendly_app_label(b) for b in apps],
            "remarkPrefix": str(cfg.get("remarkPrefix") or ""),
            "greeting": str(cfg.get("greeting") or ""),
            "skipGreeting": bool(cfg.get("skipGreeting", False)),
            "requireConfirm": bool(cfg.get("requireConfirm", True)),
            "mode": str(cfg.get("mode") or "shadow"),
        }

    def chat_turn(
        self,
        message: str,
        *,
        chat_id: str = "",
        agent_id: str = "",
        mode: str = "shadow",
        auto_run_on_confirm: bool = True,
        confirm_run: bool = False,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Multi-turn conversational workflow authoring: clarify -> ready_to_build -> built_and_debugged."""
        clean_msg = str(message or "").strip()
        if not clean_msg:
            return {"ok": False, "error_code": "missing_message", "error": "请输入你想搭建的工作流需求或回复内容。"}

        eff_mode = str(mode or "shadow").strip().lower()
        if eff_mode not in ("dry_run", "shadow", "live"):
            eff_mode = "shadow"

        cmap = self._chats_state.setdefault("chats", {})
        cid = str(chat_id or "").strip()
        now = _utc_iso_now()
        if cid and isinstance(cmap.get(cid), dict):
            session = copy.deepcopy(cmap[cid])
        else:
            if not cid or not cid.startswith("wfchat_"):
                cid = f"wfchat_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
            session = {
                "chatId": cid,
                "phase": "clarifying",
                "collectedConfig": {
                    "goal": "",
                    "targetApps": [],
                    "actionType": "",
                    "remarkPrefix": "",
                    "greeting": "",
                    "skipGreeting": False,
                    "requireConfirm": True,
                    "_confirmAnswered": False,
                    "mode": eff_mode,
                    "_turns": [],
                },
                "messages": [],
                "questions": [],
                "spec": None,
                "workflow": None,
                "debugSession": None,
                "createdAt": now,
                "updatedAt": now,
            }

        cfg = dict(session.get("collectedConfig") or {})
        cfg["mode"] = eff_mode
        prev_phase = str(session.get("phase") or "clarifying")
        confirm_requested = self._is_confirm_trigger(clean_msg, current_phase=prev_phase)

        messages = list(session.get("messages") or [])
        messages.append({"role": "user", "text": clean_msg, "at": now})

        if not confirm_requested:
            self._parse_chat_slots(clean_msg, cfg)
        elif prev_phase == "clarifying":
            # Allow combined messages like "需要确认，直接生成" to still capture slot answers
            self._parse_chat_slots(clean_msg, cfg)
        eff_mode = str(cfg.get("mode") or eff_mode).strip().lower()

        questions = self._missing_chat_questions(cfg)
        if confirm_requested and questions and any(
            p in clean_msg for p in ("直接生成", "开始调试", "生成并调试", "确认生成")
        ):
            # User explicitly asks to build immediately with safe defaults
            ch = _detect_explicit_im_channel(
                goal=str(cfg.get("goal") or ""),
                targets=[{"bundleID": b} for b in (cfg.get("targetApps") or [])],
            )
            if ch is not None and not cfg.get("actionType"):
                cfg["actionType"] = "feishu_to_wechat_crm" if ch["slug"] == "feishu" else "im_to_wechat_crm"
                if "com.tencent.xinWeChat" not in (cfg.get("targetApps") or []):
                    cfg.setdefault("targetApps", []).append("com.tencent.xinWeChat")
            if cfg.get("actionType") in ("feishu_to_wechat_crm", "im_to_wechat_crm") and not cfg.get("remarkPrefix"):
                eff_ch = ch or _resolve_im_channel(
                    goal=str(cfg.get("goal") or ""),
                    targets=[{"bundleID": b} for b in (cfg.get("targetApps") or [])],
                )
                cfg["remarkPrefix"] = eff_ch["defaultRemark"]
            if not cfg.get("_confirmAnswered"):
                cfg["requireConfirm"] = True
                cfg["_confirmAnswered"] = True
            questions = []

        spec = session.get("spec")
        workflow = session.get("workflow")
        debug_session = session.get("debugSession")

        if questions:
            phase = "clarifying"
            q_lines = [f"{idx}. {q['question']}" for idx, q in enumerate(questions, start=1)]
            assistant_reply = "我已记下你的目标，请再确认以下细节即可生成工作流：\n" + "\n".join(q_lines)
        else:
            built = self._build_chat_spec_and_workflow(cfg, agent_id=agent_id)
            if not built.get("ok"):
                return built
            spec = built["spec"]
            workflow = built["workflow"]

            if confirm_requested and auto_run_on_confirm:
                if eff_mode == "live" and not confirm_run:
                    return {
                        "ok": False,
                        "error_code": "confirmation_required",
                        "error": "实机联跑调试 (mode='live') 须显式传入 confirm_run=true。",
                    }
                dbg = self.author_and_debug(
                    str(workflow.get("goal") or cfg.get("goal") or ""),
                    target_apps=list(cfg.get("targetApps") or []) or None,
                    agent_id=agent_id,
                    mode=eff_mode,
                    max_debug_rounds=3,
                    confirm_run=confirm_run,
                    respect_human_guard=True,
                    inspect_live=False,
                    params=params,
                    initial_workflow=copy.deepcopy(workflow),
                )
                debug_session = dbg
                workflow = dbg.get("workflow") or workflow
                phase = "built_and_debugged"
                assistant_reply = (
                    f"已完成工作流《{workflow.get('name', '自建流程')}》构建与调试"
                    f"（模式：{eff_mode}，状态：{dbg.get('status')}，版本：v{workflow.get('version', 1)}）。"
                )
            else:
                phase = "ready_to_build"
                assistant_reply = (
                    f"需求已清晰！我已为你草拟《{workflow.get('name', '自建流程')}》"
                    f"（共 {len(workflow.get('steps') or [])} 步，静态安全检查 {built['lintReport']['score']} 分）。"
                    "回复「确认」或「开始调试」即可自动创建并试跑验证。"
                )

        reply_at = _utc_iso_now()
        messages.append({"role": "assistant", "text": assistant_reply, "at": reply_at})

        session["phase"] = phase
        session["collectedConfig"] = cfg
        session["messages"] = messages[-40:]
        session["questions"] = questions
        session["spec"] = spec
        session["workflow"] = workflow
        session["debugSession"] = debug_session
        session["updatedAt"] = reply_at

        cmap[cid] = session
        order = [x for x in (self._chats_state.get("order") or []) if x != cid]
        self._chats_state["order"] = [cid] + order[:49]
        self._save_chats()

        return {
            "ok": True,
            "chatId": cid,
            "phase": phase,
            "assistantReply": assistant_reply,
            "questions": questions,
            "collectedConfig": self._public_collected_config(cfg),
            "messages": session["messages"],
            "spec": spec,
            "workflow": workflow,
            "debugSession": debug_session,
        }

    def chat_edit_workflow(
        self,
        workflow_id: str,
        instruction: str,
        *,
        agent_id: str = "",
        mode: str = "shadow",
        auto_verify: bool = True,
        confirm_run: bool = False,
        respect_human_guard: bool = True,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Natural-language workflow editor with WorkflowSpecLinter safety guard and auto-verification."""
        wid = str(workflow_id or "").strip()
        inst = str(instruction or "").strip()
        stored = (self.engine.app_use._state.get("workflows") or {}).get(wid)
        if not isinstance(stored, dict):
            return {"ok": False, "error_code": "workflow_not_found", "error": f"未找到流程 {wid}"}
        if not inst:
            return {"ok": False, "error_code": "missing_instruction", "error": "请用自然语言描述要修改的流程内容。"}

        eff_mode = str(mode or "shadow").strip().lower()
        if eff_mode not in ("dry_run", "shadow", "live"):
            eff_mode = "shadow"
        if eff_mode == "live" and auto_verify and not confirm_run:
            return {
                "ok": False,
                "error_code": "confirmation_required",
                "error": "实机验证 (mode='live') 须显式传入 confirm_run=true。",
            }

        before_wf = copy.deepcopy(stored)
        before_steps = copy.deepcopy(before_wf.get("steps") or [])
        prev_version = int(before_wf.get("version") or 1)

        # (0) Natural-language undo / rollback
        if re.match(
            r"^(?:撤销|回滚|撤回|恢复|退回)(?:到)?(?:上次|本次|最近一次)?(?:的)?(?:修改|改动|编辑|版本|上一版|上个版本)?$",
            inst,
        ):
            rb = self.engine.app_use.rollback_workflow(wid, revision_index=-1)
            if rb.get("ok") and isinstance(rb.get("workflow"), dict):
                rb_wf = rb["workflow"]
                restored_ver = rb_wf.get("rolledBackFromVersion") or rb_wf.get("version") or 1
                return {
                    "ok": True,
                    "rolledBack": True,
                    "workflowId": wid,
                    "previousVersion": prev_version,
                    "newVersion": int(rb_wf.get("version") or 1),
                    "appliedEdits": [f"已撤销上次修改并回滚至历史版本 v{restored_ver}"],
                    "stepDiffs": [],
                    "lintReport": {"ok": True, "score": 100, "errors": [], "warnings": []},
                    "workflow": rb_wf,
                }
            return {
                "ok": False,
                "error_code": "no_revision_to_rollback",
                "error": str(rb.get("error") or "当前流程暂无可撤销的历史版本。"),
                "workflowId": wid,
                "previousVersion": prev_version,
                "workflow": before_wf,
            }

        edited_wf = copy.deepcopy(before_wf)
        steps = list(edited_wf.get("steps") or [])
        applied_edits: List[str] = []

        # (a) Remark prefix rewrite
        m_rem = re.search(
            r"(?:把|将)?(?:微信)?备注(?:前缀|名称|格式)?(?:从\s*[^\s，。,;；]+\s*)?(?:改成|改为|换成|修改为|设为|变成)\s*[「『\"“']?([^\s，。,;；」』\"”']+)[」』\"”']?",
            inst,
        )
        remark_matched_no_target = False
        if m_rem:
            new_prefix = m_rem.group(1).strip()
            if self._rewrite_remark_prefix_in_workflow(edited_wf, new_prefix):
                steps = list(edited_wf.get("steps") or [])
                applied_edits.append(f"将微信备注/CRM档案前缀及断言更新为「{new_prefix}」")
            else:
                remark_matched_no_target = True

        # (b) Greeting / self-intro rewrite or removal
        if re.search(r"(?:不要|不用|不需要|去掉|取消|删除|关闭)(?:发|发送)?(?:自我介绍|验证语|加好友话术|开场白)", inst):
            if self._rewrite_greeting_in_workflow(edited_wf, skip_greeting=True):
                steps = list(edited_wf.get("steps") or [])
                applied_edits.append("移除自我介绍生成步骤并清空加好友验证语")
        else:
            m_greet = re.search(
                r"(?:把|将)?(?:加好友)?(?:验证语|话术|自我介绍|打招呼语|开场白)(?:改成|改为|换成|修改为|设为)\s*[「『\"“']?(.+?)[」』\"”']?(?=$|[，。；;]|(?:并且|并把|并改|同时))",
                inst,
            )
            if m_greet:
                new_greet = m_greet.group(1).strip()
                if self._rewrite_greeting_in_workflow(edited_wf, skip_greeting=False, new_greeting=new_greet):
                    steps = list(edited_wf.get("steps") or [])
                    applied_edits.append(f"将加好友验证语/话术更新为「{new_greet}」")

        # (c) Forward-only branch_if insertion
        m_branch = re.search(
            r"(?:在)?第\s*(\d+)\s*步(?:之后|后面|后)?(?:加|插入|增加|添加)(?:一个|一条)?(?:条件)?(?:判断|分支)(.*)",
            inst,
        )
        is_old_cust_skip = "老客户" in inst and ("跳过" in inst or "判断" in inst)
        if m_branch or is_old_cust_skip:
            if m_branch:
                after_num = max(1, min(len(steps), int(m_branch.group(1))))
                tail_txt = str(m_branch.group(2) or inst)
            else:
                after_num = next(
                    (i + 1 for i, s in enumerate(steps) if isinstance(s, dict) and s.get("action") in ("llm_extract", "inspect_ui")),
                    min(len(steps), 2),
                )
                tail_txt = inst

            m_jump_back = re.search(r"跳(?:回|转)?第\s*(\d+)\s*步", tail_txt)
            jump_step = int(m_jump_back.group(1)) if m_jump_back else None
            on_false = "stop_ok" if any(k in tail_txt for k in ("停止", "结束", "中止")) else "skip_next"

            var_name = "wechat_account"
            if "老客户" in tail_txt:
                var_name = "customer_tag"
                op = "not_equals"
                val = "老客户"
            else:
                for s in reversed(steps[:after_num]):
                    if isinstance(s, dict) and s.get("captureAs"):
                        var_name = str(s["captureAs"])
                        break
                op = "not_empty"
                val = ""

            branch_step: Dict[str, Any] = {
                "step": after_num + 1,
                "action": "branch_if",
                "title": "条件判断：老客户跳过" if "老客户" in tail_txt else f"条件判断：校验 {var_name}",
                "description": inst,
                "var": var_name,
                "operator": op,
                "onFalse": "jump_to_step" if jump_step is not None else on_false,
            }
            if val:
                branch_step["value"] = val
            if jump_step is not None:
                branch_step["jumpToStep"] = jump_step

            steps.insert(after_num, branch_step)
            edited_wf["steps"] = steps
            applied_edits.append(f"在第 {after_num} 步后插入条件判断 branch_if ({var_name} {op} -> {branch_step['onFalse']})")

        # (d) Safety gate insertion (pause_for_human)
        m_gate = re.search(
            r"(?:在)?(?:第\s*(\d+)\s*步|([^\s，。,;；]+?))?(?:之)?前(?:加|插入|增加|添加)(?:一个)?(?:人工确认|确认门禁|人工门禁|门禁|确认点)|^(?:加|插入|增加|添加)(?:一个)?(?:人工确认|确认门禁|人工门禁|门禁)$",
            inst,
        )
        if m_gate:
            step_num_s = m_gate.group(1)
            target_kw = str(m_gate.group(2) or "").strip()
            if step_num_s:
                ins_idx = max(0, min(len(steps), int(step_num_s) - 1))
            elif target_kw:
                ins_idx = next(
                    (
                        i
                        for i, s in enumerate(steps)
                        if isinstance(s, dict)
                        and (
                            target_kw in str(s.get("title") or "")
                            or target_kw in str(s.get("tool") or "")
                            or target_kw in str(s.get("action") or "")
                            or (target_kw in ("加好友", "微信", "外发") and s.get("tool") == "wechat_add_friend")
                            or (target_kw in ("写入", "提交", "CRM", "建档") and s.get("action") in ("focus_and_type", "builtin_tool"))
                        )
                    ),
                    max(0, len(steps) - 1),
                )
            else:
                ins_idx = next(
                    (
                        i
                        for i, s in enumerate(steps)
                        if isinstance(s, dict) and s.get("action") in ("builtin_tool", "focus_and_type")
                    ),
                    max(0, len(steps) - 1),
                )
            steps.insert(
                ins_idx,
                {
                    "step": ins_idx + 1,
                    "action": "pause_for_human",
                    "title": "人工确认门禁",
                    "description": "安全护栏：人工核对当前状态与参数后再继续执行后续步骤。",
                    "message": "请核对当前状态与参数后确认继续。",
                },
            )
            edited_wf["steps"] = steps
            applied_edits.append(f"在第 {ins_idx + 1} 步前插入人工确认门禁 (pause_for_human)")

        # (e) Calculator expression & assertion update
        m_expr = re.search(
            r"(?:把|将)?(?:计算)?表达式(?:从\s*[^\s，。,;；]+\s*)?(?:改成|改为|换成|修改为|设为)\s*([0-9+\-*/×÷().]+)",
            inst,
        )
        if m_expr:
            raw_expr = m_expr.group(1).strip()
            key_seq = self._expr_to_key_sequence(raw_expr)
            if key_seq:
                for s in steps:
                    if (
                        isinstance(s, dict)
                        and s.get("action") == "press_shortcut"
                        and not s.get("combo")
                        and (
                            "sequence" in s
                            or "表达式" in str(s.get("title") or "")
                            or "计算" in str(s.get("title") or "")
                        )
                    ):
                        s["sequence"] = key_seq
                for p in edited_wf.get("parameters") or []:
                    if isinstance(p, dict) and p.get("name") == "expression":
                        p["defaultValue"] = key_seq
                applied_edits.append(f"将计算表达式更新为 {raw_expr} ({key_seq})")

        m_assert = re.search(
            r"(?:把|将)?(?:预期|期望|验收)?断言(?:结果|值|文本)?(?:改成|改为|换成|修改为|设为)\s*[「『\"“']?([^\s，。,;；」』\"”']+)[」』\"”']?",
            inst,
        )
        if m_assert:
            new_expected = m_assert.group(1).strip()
            for s in steps:
                if isinstance(s, dict) and s.get("action") == "assert_check":
                    s["expected"] = new_expected
            for p in edited_wf.get("parameters") or []:
                if isinstance(p, dict) and p.get("name") == "expected_result":
                    p["defaultValue"] = new_expected
            applied_edits.append(f"将 assert_check 预期结果更新为「{new_expected}」")

        # (f) Wait delay update
        m_wait = re.search(
            r"(?:把|将)?(?:第\s*(\d+)\s*步(?:的)?)?(?:等待|延迟|延时|回读等待)(?:时间|时长)?(?:改成|改为|换成|设为)\s*(\d+(?:\.\d+)?)\s*(ms|毫秒|s|S|秒)?",
            inst,
        )
        if m_wait:
            target_step = int(m_wait.group(1)) if m_wait.group(1) else None
            raw_num = float(m_wait.group(2))
            unit = str(m_wait.group(3) or "s").casefold()
            delay_sec = round(max(0.05, min(30.0, raw_num / 1000.0 if unit in ("ms", "毫秒") else raw_num)), 3)
            wait_updated = False
            for idx, s in enumerate(steps, start=1):
                if not isinstance(s, dict):
                    continue
                if target_step is not None and idx != target_step:
                    continue
                if s.get("action") == "wait_and_read":
                    s["delaySec"] = delay_sec
                    wait_updated = True
            if not wait_updated and target_step is not None and 1 <= target_step <= len(steps):
                if steps[target_step - 1].get("action") == "press_shortcut":
                    steps[target_step - 1]["delayMs"] = int(delay_sec * 1000)
                    wait_updated = True
            if wait_updated:
                applied_edits.append(f"将等待延时更新为 {delay_sec}s")

        # (g) Step deletion
        m_del = re.search(r"(?:删除|删掉|去掉|移除)第\s*(\d+)\s*步", inst)
        removed_last_assertion = False
        if m_del:
            del_num = int(m_del.group(1))
            if del_num < 1 or del_num > len(steps):
                return {
                    "ok": False,
                    "error_code": "invalid_step_index",
                    "error": f"步骤号 {del_num} 超出当前步骤范围 (1..{len(steps)})",
                    "workflowId": wid,
                    "previousVersion": prev_version,
                    "workflow": before_wf,
                }
            removed_step = steps.pop(del_num - 1)
            if isinstance(removed_step, dict) and removed_step.get("action") == "assert_check":
                if not any(isinstance(s, dict) and s.get("action") == "assert_check" for s in steps):
                    removed_last_assertion = True
            edited_wf["steps"] = steps
            applied_edits.append(f"删除第 {del_num} 步 ({removed_step.get('title') or removed_step.get('action')})")

        # (h) Rename workflow
        m_rename = re.search(
            r"(?:把|将)?(?:这个|当前)?(?:流程|工作流)(?:名称|名字|标题)?(?:改成|改为|换成|修改为|重命名为|叫作?|设为)\s*[「『\"“']?([^，。,;；」』\"”'\n]{2,48})[」』\"”']?|^重命名为\s*[「『\"“']?([^，。,;；」』\"”'\n]{2,48})[」』\"”']?",
            inst,
        )
        if m_rename:
            new_name = str(m_rename.group(1) or m_rename.group(2) or "").strip()
            if new_name:
                edited_wf["name"] = new_name
                applied_edits.append(f"将流程重命名为「{new_name}」")

        # (i) Append CRM tag
        m_tag = re.search(
            r"(?:给|为|在)?(?:crm|CRM|客户档案|档案)?(?:追加|添加|加上|加|新增|打上)(?:一个|个)?(?:客户)?标签\s*[「『\"“']?([^\s，。,;；」』\"”']{1,24})[」』\"”']?",
            inst,
        )
        if m_tag:
            new_tag = m_tag.group(1).strip()
            tag_applied = False
            for s in steps:
                if isinstance(s, dict) and s.get("tool") == "crm_enroll":
                    params_dict = dict(s.get("params") or {})
                    dedup_tags: List[str] = []
                    for tg in list(params_dict.get("tags") or []):
                        ts = str(tg).strip()
                        if ts and ts not in dedup_tags:
                            dedup_tags.append(ts)
                    if new_tag and new_tag not in dedup_tags:
                        dedup_tags.append(new_tag)
                    params_dict["tags"] = dedup_tags
                    s["params"] = params_dict
                    tag_applied = True
            if tag_applied:
                edited_wf["steps"] = steps
                applied_edits.append(f"为 CRM 客户档案追加标签「{new_tag}」")

        # (j) Change CRM funnel stage
        m_stage = re.search(
            r"(?:把|将)?(?:crm|CRM|客户)?(?:漏斗)?阶段(?:改成|改为|换成|设为|调整为)\s*[「『\"“']?([^\s，。,;；」』\"”']{2,16})[」』\"”']?",
            inst,
        )
        if m_stage:
            raw_stage = m_stage.group(1).strip()
            stage_aliases = {
                "初步触达": "初步接触",
                "跟进中": "沟通中",
                "深度跟进": "深入沟通",
                "成交": "已成交",
                "流失": "退出/失败",
                "放弃": "退出/失败",
            }
            valid_stages = {
                "新线索", "初步接触", "沟通中", "深入沟通",
                "已报价", "方案推进", "已成交", "暂缓", "退出/失败",
            }
            norm_stage = stage_aliases.get(raw_stage, raw_stage)
            if norm_stage in valid_stages:
                stage_applied = False
                for s in steps:
                    if isinstance(s, dict) and s.get("tool") == "crm_enroll":
                        params_dict = dict(s.get("params") or {})
                        params_dict["stage"] = norm_stage
                        s["params"] = params_dict
                        stage_applied = True
                if stage_applied:
                    edited_wf["steps"] = steps
                    applied_edits.append(f"将 CRM 漏斗阶段调整为「{norm_stage}」")

        # Optional LLM fallback if no deterministic edit rule matched
        if not applied_edits and agent_id and not str(agent_id).startswith(("local:", "cli:")):
            mid = str(agent_id).split(":", 1)[1] if str(agent_id).startswith("magpie:") else str(agent_id)
            edit_prompt = (
                "你是自动化工作流编辑编译器。请将用户自然语言修改指令编译为 JSON 补丁：\n"
                '{"operation":"modify_step"|"insert_before"|"delete_step","stepIndex":1,"patch":{...},"summary":"..."}\n'
                "禁止禁用 assert_check 或移除高风险门禁。只输出 JSON。"
            )
            llm = self.engine.models.generate_chat_reply(
                [
                    {"role": "system", "content": edit_prompt},
                    {"role": "user", "content": json.dumps({"instruction": inst, "steps": steps}, ensure_ascii=False)},
                ],
                model_id=mid,
                max_tokens=700,
                temperature=0.1,
                timeout=20.0,
            )
            if llm.get("ok"):
                parsed = _extract_json_object(str(llm.get("replyText") or ""))
                if isinstance(parsed, dict):
                    op = str(parsed.get("operation") or "")
                    s_idx = max(1, min(len(steps), int(parsed.get("stepIndex") or 1)))
                    patch_obj = parsed.get("patch") if isinstance(parsed.get("patch"), dict) else {}
                    if op == "modify_step" and patch_obj:
                        steps[s_idx - 1] = dict(steps[s_idx - 1], **patch_obj)
                        applied_edits.append(str(parsed.get("summary") or f"AI 修改第 {s_idx} 步"))
                    elif op == "insert_before" and str(patch_obj.get("action") or "") in SUPPORTED_STEP_ACTIONS:
                        steps.insert(s_idx - 1, dict(patch_obj))
                        applied_edits.append(str(parsed.get("summary") or f"AI 在第 {s_idx} 步前插入步骤"))
                    elif op == "delete_step" and 1 <= s_idx <= len(steps):
                        steps.pop(s_idx - 1)
                        applied_edits.append(str(parsed.get("summary") or f"AI 删除第 {s_idx} 步"))

        if not applied_edits:
            err_code = "remark_field_not_found" if remark_matched_no_target else "unrecognized_edit_instruction"
            err_msg = (
                "当前流程不包含微信备注或 CRM 档案字段，无法修改备注前缀。"
                if remark_matched_no_target
                else "暂未识别该修改指令，请尝试：改备注前缀、改验证语、给CRM加标签/改阶段、重命名流程、撤销/回滚上一版、第N步后加判断、加人工确认门禁、改计算表达式/断言、改等待时间或删除第N步。"
            )
            return {
                "ok": False,
                "error_code": err_code,
                "error": err_msg,
                "workflowId": wid,
                "previousVersion": prev_version,
                "workflow": before_wf,
            }

        for idx, s in enumerate(steps, start=1):
            if isinstance(s, dict):
                s["step"] = idx
        edited_wf["steps"] = self.engine.app_use._normalize_steps(steps)

        # Static safety linter guard: reject unsafe edits without corrupting stored workflow
        lint_res = WorkflowSpecLinter.lint(edited_wf)
        if removed_last_assertion:
            errs = list(lint_res.get("errors") or [])
            errs.append({"code": "MISSING_ASSERTIONS", "step": 0, "message": "禁止删除最后一个独立验收断言 assert_check"})
            lint_res["errors"] = errs
            lint_res["ok"] = False
            lint_res["score"] = max(0, int(lint_res.get("score", 100)) - 25)
        if not lint_res.get("ok"):
            return {
                "ok": False,
                "error_code": "unsafe_edit_rejected",
                "error": f"修改未通过安全 Linter 审查，已拦截且保留原流程：{lint_res.get('errors')}",
                "lintReport": lint_res,
                "workflowId": wid,
                "previousVersion": prev_version,
                "workflow": before_wf,
            }

        revs = list(before_wf.get("revisionHistory") or [])
        revs.append(
            {
                "version": prev_version,
                "savedAt": _utc_iso_now(),
                "reason": f"对话改流程: {inst[:80]}",
                "name": str(before_wf.get("name") or ""),
                "parameters": copy.deepcopy(before_wf.get("parameters") or []),
                "steps": copy.deepcopy(before_steps),
                "sopMarkdown": before_wf.get("sopMarkdown") or "",
            }
        )
        edited_wf["revisionHistory"] = revs[-12:]
        new_version = prev_version + 1
        edited_wf["version"] = new_version
        edited_wf["sopMarkdown"] = self.engine.app_use._render_sop_markdown(edited_wf)

        self.engine.app_use.save_workflow(edited_wf, sop_markdown=edited_wf["sopMarkdown"])
        step_diffs = self._compute_step_diff(before_steps, edited_wf["steps"])

        verification_run: Optional[Dict[str, Any]] = None
        if auto_verify:
            verification_run = self.author_and_debug(
                str(edited_wf.get("goal") or edited_wf.get("name") or wid),
                agent_id=agent_id,
                mode=eff_mode,
                max_debug_rounds=2,
                confirm_run=confirm_run,
                respect_human_guard=respect_human_guard,
                inspect_live=False,
                params=params,
                initial_workflow=copy.deepcopy(edited_wf),
            )
            if isinstance(verification_run.get("workflow"), dict):
                edited_wf = verification_run["workflow"]

        return {
            "ok": True,
            "workflowId": wid,
            "previousVersion": prev_version,
            "newVersion": int(edited_wf.get("version") or new_version),
            "appliedEdits": applied_edits,
            "stepDiffs": step_diffs,
            "lintReport": lint_res,
            "workflow": edited_wf,
            "verificationRun": verification_run,
        }
