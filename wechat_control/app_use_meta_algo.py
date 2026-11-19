"""Meta-RPA generalization & multi-window concurrency algorithms (v2.8.0).

Pure Python 3.9+ standard library implementation providing:
1. SemanticElementGrounder: bilingual EN/ZH + CJK bigram + synonym + Gaussian spatial +
   relational neighbor topology grounding with confidence & margin calibration.
2. UI state hashing, modal blocker classification (auth/risk gate vs dismissible modal),
   topology-driven App Archetype inference (zero hardcoded app names), and persistent
   AppUIStateGraph.
3. Trajectory optimization, anchor enrichment & 0-100 Generalization Readiness scoring.
4. Failure-taxonomy classifier guiding bounded runtime self-healing.
5. ForegroundHIDLease for safe concurrent multi-window App-Use scheduling.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import random
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Set, Tuple

from .io_utils import atomic_write_json


_BIDI_MARKS_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

UI_SYNONYM_GROUPS: Tuple[Set[str], ...] = (
    {"send", "submit", "post", "enter", "reply", "confirm", "ok", "发送", "提交", "确定", "确认", "回复"},
    {"search", "find", "lookup", "query", "filter", "搜索", "查找", "查询", "检索", "筛选"},
    {"new", "create", "add", "compose", "plus", "新建", "创建", "添加", "新增", "发起"},
    {"close", "cancel", "dismiss", "skip", "later", "abort", "关闭", "取消", "跳过", "稍后", "放弃"},
    {"settings", "preferences", "config", "options", "设置", "偏好", "配置", "选项"},
    {"input", "prompt", "editor", "message", "textbox", "输入", "提问", "正文", "消息", "内容"},
    {"clear", "reset", "ac", "clean", "erase", "清空", "清零", "清除", "重置"},
    {"save", "export", "download", "done", "finish", "保存", "导出", "下载", "完成"},
    {"copy", "paste", "cut", "复制", "粘贴", "剪切"},
    {"back", "next", "prev", "continue", "返回", "上一步", "下一步", "继续"},
)

INPUT_ROLES: Set[str] = {
    "AXTextArea",
    "AXTextField",
    "AXSearchField",
    "AXComboBox",
    "AXPopUpButton",
}
CLICK_ROLES: Set[str] = {
    "AXButton",
    "AXMenuItem",
    "AXTab",
    "AXLink",
    "AXCheckBox",
    "AXRadioButton",
    "AXPopUpButton",
    "AXCell",
}

AUTH_RISK_KEYWORDS: Tuple[str, ...] = (
    "请扫码",
    "扫码登录",
    "扫一扫登录",
    "请登录",
    "登录账号",
    "账户登录",
    "sign in",
    "log in",
    "two-factor",
    "2fa",
    "verification code",
    "验证码",
    "enter password",
    "输入密码",
    "password",
    "密码",
    "确认付款",
    "确认支付",
    "立即付款",
    "pay now",
    "永久删除",
    "无法撤销",
    "wants to access",
    "allow access",
    "允许访问",
)

DISMISSIBLE_MODAL_KEYWORDS: Tuple[str, ...] = (
    "软件更新",
    "检查更新",
    "新版本",
    "update available",
    "check for updates",
    "稍后提醒",
    "以后再说",
    "not now",
    "remind me later",
    "skip this version",
    "你要保留此新文稿",
    "放弃更改",
    "don't save",
    "discard changes",
)

SECONDARY_DIALOG_TITLES: Set[str] = {
    "保存",
    "save",
    "更新",
    "software update",
    "update",
    "alert",
}


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_ui_text(value: Any) -> str:
    """Strip macOS BiDi markers (e.g. LRM '\\u200e') and surrounding whitespace."""
    return _BIDI_MARKS_RE.sub("", str(value or "")).strip()


def tokenize_bilingual(text: Any) -> List[str]:
    """Tokenize mixed English/CJK strings into lowercase words + CJK unigrams/bigrams."""
    s = clean_ui_text(text).casefold()
    if not s:
        return []
    tokens: List[str] = []
    seen: Set[str] = set()

    def _add(tok: str) -> None:
        if tok and tok not in seen:
            seen.add(tok)
            tokens.append(tok)

    for m in _ASCII_TOKEN_RE.findall(s):
        _add(m)
    for run in _CJK_RUN_RE.findall(s):
        if len(run) >= 2:
            for i in range(len(run) - 1):
                _add(run[i : i + 2])
        for ch in run:
            _add(ch)
    return tokens


def _synonym_groups_for(raw_text: str, tokens: Set[str]) -> Set[int]:
    groups: Set[int] = set()
    low = clean_ui_text(raw_text).casefold()
    for idx, grp in enumerate(UI_SYNONYM_GROUPS):
        for term in grp:
            if term in tokens:
                groups.add(idx)
                break
            is_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in term)
            if len(term) >= 2 and is_cjk and term in low:
                groups.add(idx)
                break
    return groups


def compute_lexical_similarity(query: Any, candidate_text: Any) -> float:
    """Bilingual lexical similarity combining SequenceMatcher, Jaccard & EN/ZH synonym overlap."""
    q = clean_ui_text(query).casefold()
    c = clean_ui_text(candidate_text).casefold()
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0

    seq_ratio = SequenceMatcher(None, q, c).ratio()
    q_list = tokenize_bilingual(q)
    c_list = tokenize_bilingual(c)
    q_set = set(q_list)
    c_set = set(c_list)
    jaccard = (len(q_set & c_set) / float(len(q_set | c_set))) if (q_set and c_set) else 0.0

    q_grps = _synonym_groups_for(q, q_set)
    c_grps = _synonym_groups_for(c, c_set)
    syn_score = 0.88 if (q_grps & c_grps) else 0.0

    sub_score = 0.0
    if len(q) >= 2 and q in c:
        sub_score = 0.92
    elif len(c) >= 2 and c in q:
        sub_score = 0.85

    return round(min(1.0, max(seq_ratio, jaccard, syn_score, sub_score)), 4)


def _extract_rel_center(
    item: Dict[str, Any],
    point: Tuple[float, float],
    win_bounds: Dict[str, Any],
) -> Optional[Tuple[float, float]]:
    rc = item.get("relCenter")
    if isinstance(rc, dict) and "x" in rc and "y" in rc:
        try:
            return (float(rc["x"]), float(rc["y"]))
        except Exception:
            pass
    try:
        w = float(win_bounds.get("width") or 0.0)
        h = float(win_bounds.get("height") or 0.0)
        if w > 1.0 and h > 1.0:
            wx = float(win_bounds.get("x") or 0.0)
            wy = float(win_bounds.get("y") or 0.0)
            return (round((point[0] - wx) / w, 4), round((point[1] - wy) / h, 4))
    except Exception:
        pass
    return None


def _item_labels(item: Dict[str, Any]) -> List[str]:
    vals: List[str] = []
    for k in ("title", "description", "identifier", "text"):
        v = clean_ui_text(item.get(k))
        if v and v not in vals:
            vals.append(v)
    val = clean_ui_text(item.get("value"))
    if val and len(val) <= 60 and val not in vals:
        vals.append(val)
    return vals


def _collect_candidates(inspection: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(inspection, dict):
        return []
    win = inspection.get("window") or {}
    win_bounds = (win.get("bounds") if isinstance(win, dict) else {}) or {}
    if not win_bounds and isinstance(inspection.get("uiSummary"), dict):
        win_bounds = inspection["uiSummary"].get("windowBounds") or {}

    out: List[Dict[str, Any]] = []
    for ctrl in inspection.get("axControls") or []:
        if not isinstance(ctrl, dict):
            continue
        center = ctrl.get("center") or {}
        if "x" not in center or "y" not in center:
            continue
        try:
            pt = (float(center["x"]), float(center["y"]))
        except Exception:
            continue
        rel = _extract_rel_center(ctrl, pt, win_bounds)
        out.append(
            {
                "kind": "ax",
                "point": pt,
                "relCenter": rel,
                "role": str(ctrl.get("role") or ""),
                "identifier": clean_ui_text(ctrl.get("identifier")),
                "labels": _item_labels(ctrl),
                "enabled": ctrl.get("enabled", True) is not False,
                "bounds": ctrl.get("bounds") if isinstance(ctrl.get("bounds"), dict) else {},
                "element": ctrl,
            }
        )

    for ocr in inspection.get("ocrElements") or []:
        if not isinstance(ocr, dict):
            continue
        sc = ocr.get("screenCenter") or ocr.get("center") or {}
        if "x" not in sc or "y" not in sc:
            continue
        try:
            pt = (float(sc["x"]), float(sc["y"]))
        except Exception:
            continue
        rel = _extract_rel_center(ocr, pt, win_bounds)
        txt = clean_ui_text(ocr.get("text"))
        out.append(
            {
                "kind": "ocr",
                "point": pt,
                "relCenter": rel,
                "role": "",
                "identifier": "",
                "labels": [txt] if txt else [],
                "enabled": True,
                "bounds": ocr.get("bbox") if isinstance(ocr.get("bbox"), dict) else {},
                "confidence": float(ocr.get("confidence", 0.85) or 0.85),
                "element": ocr,
            }
        )
    return out


class SemanticElementGrounder:
    """Multi-factor desktop UI element grounder across AX controls and Vision OCR."""

    W_ID_ROLE = 0.35
    W_LEX = 0.30
    W_POS = 0.18
    W_REL = 0.12
    W_AFF = 0.05
    POS_SIGMA = 0.18
    NEIGHBOR_RADIUS = 0.22

    @classmethod
    def extract_anchor_bundle(
        cls,
        candidate: Dict[str, Any],
        inspection: Optional[Dict[str, Any]],
        *,
        max_neighbors: int = 3,
    ) -> Dict[str, Any]:
        """Build a drift-resistant anchor bundle with relative coordinates and neighbor labels."""
        el = candidate.get("element") if isinstance(candidate.get("element"), dict) else {}
        rel = candidate.get("relCenter")
        labels = candidate.get("labels") or []
        self_lows = {lb.casefold() for lb in labels if lb}

        all_cands = _collect_candidates(inspection)
        neighbors_scored: List[Tuple[float, str]] = []
        seen_n: Set[str] = set()
        if isinstance(rel, tuple) and len(rel) == 2:
            rx, ry = rel
            for other in all_cands:
                orel = other.get("relCenter")
                if not isinstance(orel, tuple):
                    continue
                dist = math.hypot(orel[0] - rx, orel[1] - ry)
                if dist <= 0.002 or dist >= cls.NEIGHBOR_RADIUS:
                    continue
                for lb in other.get("labels") or []:
                    low = lb.casefold()
                    if not lb or len(lb) > 36 or low in self_lows or low in seen_n:
                        continue
                    seen_n.add(low)
                    neighbors_scored.append((dist, lb))
        neighbors_scored.sort(key=lambda x: x[0])

        ax_title = clean_ui_text(el.get("title") or el.get("description") or el.get("text"))
        ax_id = clean_ui_text(el.get("identifier"))
        bundle: Dict[str, Any] = {
            "targetAxId": ax_id,
            "targetAxTitle": ax_title,
            "targetRole": str(candidate.get("role") or ""),
            "neighborTexts": [lb for _, lb in neighbors_scored[:max_neighbors]],
        }
        if isinstance(rel, tuple):
            bundle["relX"] = round(rel[0], 4)
            bundle["relY"] = round(rel[1], 4)
        return bundle

    @classmethod
    def rank_candidates(
        cls,
        step: Dict[str, Any],
        inspection: Optional[Dict[str, Any]],
        *,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        cands = _collect_candidates(inspection)
        if not cands:
            return []

        win = (inspection or {}).get("window") or {}
        win_bounds = (win.get("bounds") if isinstance(win, dict) else {}) or {}
        if not win_bounds and isinstance((inspection or {}).get("uiSummary"), dict):
            win_bounds = (inspection or {})["uiSummary"].get("windowBounds") or {}

        action = str(step.get("action") or "").strip().lower()
        q_id = clean_ui_text(step.get("targetAxId")).casefold()
        explicit_lex = clean_ui_text(step.get("targetAxTitle") or step.get("matchText")).casefold()
        fallback_lex = clean_ui_text(step.get("title")).casefold()
        q_role = clean_ui_text(step.get("targetRole"))
        neighbor_texts = [clean_ui_text(x).casefold() for x in (step.get("neighborTexts") or []) if clean_ui_text(x)]

        q_rx = step.get("relX")
        q_ry = step.get("relY")
        if (q_rx is None or q_ry is None) and step.get("x") is not None and step.get("y") is not None:
            try:
                w = float(win_bounds.get("width") or 0.0)
                h = float(win_bounds.get("height") or 0.0)
                if w > 1.0 and h > 1.0:
                    q_rx = (float(step["x"]) - float(win_bounds.get("x") or 0.0)) / w
                    q_ry = (float(step["y"]) - float(win_bounds.get("y") or 0.0)) / h
            except Exception:
                pass
        has_pos_query = q_rx is not None and q_ry is not None
        has_lex_query = bool(explicit_lex)

        # Precompute spatial index of labels for relational scoring if neighborTexts given
        rel_items: List[Tuple[Tuple[float, float], List[str]]] = []
        if neighbor_texts:
            for item in cands:
                if isinstance(item.get("relCenter"), tuple) and item.get("labels"):
                    rel_items.append((item["relCenter"], [lb.casefold() for lb in item["labels"]]))

        ranked: List[Dict[str, Any]] = []
        for idx, cand in enumerate(cands):
            c_role = cand["role"]
            c_id = cand["identifier"].casefold()
            c_kind = cand["kind"]
            c_rel = cand["relCenter"]
            labels = cand["labels"]

            # 1) ID + Role structural signal
            if q_role and c_role == q_role:
                role_fit = 1.0
            elif action == "focus_and_type":
                role_fit = 1.0 if c_role in INPUT_ROLES else (0.25 if c_kind == "ocr" else 0.15)
            elif action == "click_element":
                role_fit = 0.95 if c_role in CLICK_ROLES else (0.45 if c_kind == "ocr" else 0.3)
            else:
                role_fit = 0.7 if c_kind == "ax" else 0.5

            if q_id:
                if c_id == q_id:
                    id_fit = 1.0
                elif c_id and (q_id in c_id or c_id in q_id):
                    id_fit = 0.7
                else:
                    id_fit = 0.0
                s_id_role = 0.65 * id_fit + 0.35 * role_fit
            else:
                s_id_role = 0.75 * role_fit

            # 2) Bilingual lexical signal
            if explicit_lex:
                s_lex = max((compute_lexical_similarity(explicit_lex, lb) for lb in labels), default=0.0)
            elif not q_id and not has_pos_query and fallback_lex:
                s_lex = 0.85 * max((compute_lexical_similarity(fallback_lex, lb) for lb in labels), default=0.0)
            else:
                # Purely positional/structural query with no lexical hint
                s_lex = 0.42 if (has_pos_query or q_id or q_role) else 0.0

            # 3) Resolution-independent Gaussian spatial prior
            if has_pos_query and isinstance(c_rel, tuple):
                dx = c_rel[0] - float(q_rx)
                dy = c_rel[1] - float(q_ry)
                s_pos = math.exp(-(dx * dx + dy * dy) / (2.0 * (cls.POS_SIGMA ** 2)))
            else:
                s_pos = 0.0

            # 4) Relational neighbor topology
            if neighbor_texts and isinstance(c_rel, tuple):
                rx, ry = c_rel
                nearby_labels: List[str] = []
                for o_rel, o_labels in rel_items:
                    dist = math.hypot(o_rel[0] - rx, o_rel[1] - ry)
                    if 0.002 < dist <= cls.NEIGHBOR_RADIUS:
                        nearby_labels.extend(o_labels)
                hits = 0.0
                for nt in neighbor_texts:
                    best_n = max(
                        (
                            1.0 if (nt in nl or nl in nt) else compute_lexical_similarity(nt, nl)
                            for nl in nearby_labels
                        ),
                        default=0.0,
                    )
                    if best_n >= 0.65:
                        hits += 1.0
                s_rel = hits / float(len(neighbor_texts))
            else:
                s_rel = 0.0

            # 5) Interactive affordance
            b = cand.get("bounds") or {}
            try:
                non_tiny = (not b) or (float(b.get("width", 12)) >= 6.0 and float(b.get("height", 12)) >= 6.0)
            except Exception:
                non_tiny = True
            if c_kind == "ax":
                s_aff = 1.0 if (cand["enabled"] and non_tiny) else 0.2
            else:
                s_aff = 0.72 if (cand.get("confidence", 0.8) >= 0.4 and non_tiny) else 0.3

            # Reject completely irrelevant candidates when lexical query is explicit & neither ID nor position matches
            if has_lex_query and s_lex < 0.20 and not (q_id and c_id == q_id) and s_pos < 0.75:
                total = (
                    0.5 * cls.W_ID_ROLE * s_id_role
                    + cls.W_LEX * s_lex
                    + 0.4 * cls.W_POS * s_pos
                    + cls.W_REL * s_rel
                    + cls.W_AFF * s_aff
                )
            else:
                total = (
                    cls.W_ID_ROLE * s_id_role
                    + cls.W_LEX * s_lex
                    + cls.W_POS * s_pos
                    + cls.W_REL * s_rel
                    + cls.W_AFF * s_aff
                )

            src_tag = (
                f"sem_ax:{cand['identifier'] or (labels[0] if labels else c_role)}"
                if c_kind == "ax"
                else f"sem_ocr:{(labels[0] if labels else 'ocr')[:24]}"
            )
            ranked.append(
                {
                    "_idx": idx,
                    "_cand": cand,
                    "point": cand["point"],
                    "relCenter": {"x": c_rel[0], "y": c_rel[1]} if isinstance(c_rel, tuple) else None,
                    "source": src_tag,
                    "kind": c_kind,
                    "role": c_role,
                    "identifier": cand["identifier"],
                    "labels": labels[:3],
                    "score": round(total, 4),
                    "breakdown": {
                        "idRole": round(s_id_role, 3),
                        "lexical": round(s_lex, 3),
                        "spatial": round(s_pos, 3),
                        "relational": round(s_rel, 3),
                        "affordance": round(s_aff, 3),
                    },
                }
            )

        ranked.sort(key=lambda r: (r["score"], r["breakdown"]["lexical"], r["breakdown"]["spatial"]), reverse=True)
        out: List[Dict[str, Any]] = []
        for row in ranked[: max(1, int(top_k))]:
            clean_row = {k: v for k, v in row.items() if not k.startswith("_")}
            clean_row["element"] = row["_cand"]["element"]
            out.append(clean_row)
        return out

    @classmethod
    def resolve_best(
        cls,
        step: Dict[str, Any],
        inspection: Optional[Dict[str, Any]],
        *,
        min_score: float = 0.38,
    ) -> Dict[str, Any]:
        top = cls.rank_candidates(step, inspection, top_k=5)
        if not top:
            return {
                "ok": False,
                "point": None,
                "source": "unresolved",
                "confidence": 0.0,
                "margin": 0.0,
                "secondScore": 0.0,
                "candidates": [],
                "anchorBundle": {},
            }
        best = top[0]
        second_score = float(top[1]["score"]) if len(top) > 1 else 0.0
        conf = float(best["score"])
        margin = round(conf - second_score, 4)
        ok = conf >= float(min_score)

        # Build anchor bundle from the winning candidate's underlying dict
        pseudo_cand = {
            "element": best["element"],
            "role": best["role"],
            "identifier": best["identifier"],
            "labels": best["labels"],
            "relCenter": (
                (best["relCenter"]["x"], best["relCenter"]["y"])
                if isinstance(best.get("relCenter"), dict)
                else None
            ),
        }
        anchor_bundle = cls.extract_anchor_bundle(pseudo_cand, inspection) if ok else {}
        return {
            "ok": ok,
            "point": best["point"] if ok else None,
            "source": best["source"] if ok else "unresolved",
            "confidence": conf,
            "margin": margin,
            "secondScore": second_score,
            "candidates": [{k: v for k, v in r.items() if k != "element"} for r in top],
            "anchorBundle": anchor_bundle,
        }


# ----------------------------------------------------------------------
# Algorithm 2: Modal Classification, UI State Hash, Archetypes & State Graph
# ----------------------------------------------------------------------


def detect_modal_blocker(inspection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect whether current app UI is blocked by auth/risk gate vs dismissible modal."""
    if not isinstance(inspection, dict):
        return {"kind": "none", "requiresHuman": False, "signals": []}

    blobs: List[str] = []
    win = inspection.get("window") or {}
    if isinstance(win, dict) and win.get("title"):
        blobs.append(clean_ui_text(win["title"]))
    for w in inspection.get("windows") or []:
        if isinstance(w, dict) and w.get("title"):
            blobs.append(clean_ui_text(w["title"]))
    for t in inspection.get("axTexts") or []:
        ct = clean_ui_text(t)
        if ct:
            blobs.append(ct)
    for c in (inspection.get("axControls") or [])[:60]:
        if isinstance(c, dict):
            for k in ("title", "description", "value"):
                ct = clean_ui_text(c.get(k))
                if ct:
                    blobs.append(ct)
    if inspection.get("ocrPreview"):
        blobs.append(clean_ui_text(inspection["ocrPreview"]))

    joined = " | ".join(blobs).casefold()
    auth_hits = [kw for kw in AUTH_RISK_KEYWORDS if kw in joined]
    if auth_hits:
        return {
            "kind": "auth_or_risk_gate",
            "requiresHuman": True,
            "signals": auth_hits[:5],
            "dismissCombo": "",
        }

    dismiss_hits = [kw for kw in DISMISSIBLE_MODAL_KEYWORDS if kw in joined]
    has_sheet = any(
        isinstance(c, dict) and str(c.get("role") or "") in ("AXSheet", "AXDialog")
        for c in (inspection.get("axControls") or [])[:40]
    )
    secondary_dialog = any(
        isinstance(w, dict)
        and not w.get("isMainWindow")
        and clean_ui_text(w.get("title")).casefold() in SECONDARY_DIALOG_TITLES
        for w in (inspection.get("windows") or [])[1:]
    )
    if dismiss_hits or has_sheet or secondary_dialog:
        sigs = list(dismiss_hits[:4])
        if has_sheet:
            sigs.append("AXSheet")
        if secondary_dialog:
            sigs.append("secondary_dialog_window")
        return {
            "kind": "dismissible_modal",
            "requiresHuman": False,
            "signals": sigs,
            "dismissCombo": "escape",
        }
    return {"kind": "none", "requiresHuman": False, "signals": [], "dismissCombo": ""}


def compute_ui_state(inspection: Optional[Dict[str, Any]], *, bundle_id: str = "") -> Dict[str, Any]:
    """Compute canonical structural+textual state hash for loop breaking and graph building."""
    if not isinstance(inspection, dict):
        return {
            "stateHash": "empty",
            "bundleID": bundle_id,
            "windowTitle": "",
            "axCount": 0,
            "ocrCount": 0,
            "textDigest": "empty",
            "textsPreview": [],
            "modalStatus": {"kind": "none", "requiresHuman": False, "signals": []},
        }

    eff_bid = str(inspection.get("bundleID") or bundle_id or "").strip().casefold()
    win = inspection.get("window") or {}
    win_title = clean_ui_text(win.get("title") if isinstance(win, dict) else "")
    ax_ctrls = inspection.get("axControls") or []
    ax_sigs = sorted(
        f"{c.get('role','')}:{clean_ui_text(c.get('title') or c.get('identifier'))[:32]}"
        for c in ax_ctrls[:45]
        if isinstance(c, dict)
    )
    texts: List[str] = []
    for t in inspection.get("axTexts") or []:
        ct = clean_ui_text(t)
        if ct and ct not in texts:
            texts.append(ct)
    for ln in clean_ui_text(inspection.get("ocrPreview") or "").splitlines():
        cl = clean_ui_text(ln)
        if cl and cl not in texts:
            texts.append(cl)
    texts_preview = texts[:40]
    text_digest = hashlib.sha1("\n".join(texts_preview).encode("utf-8")).hexdigest()[:12]
    state_material = json.dumps(
        {
            "b": eff_bid,
            "w": win_title,
            "c": ax_sigs,
            "t": text_digest,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    state_hash = hashlib.sha1(state_material.encode("utf-8")).hexdigest()[:16]
    return {
        "stateHash": state_hash,
        "bundleID": str(inspection.get("bundleID") or bundle_id or ""),
        "windowTitle": win_title,
        "axCount": int(inspection.get("axControlCount") or len(ax_ctrls)),
        "ocrCount": int(inspection.get("ocrCount") or len(inspection.get("ocrElements") or [])),
        "textDigest": text_digest,
        "textsPreview": texts_preview,
        "modalStatus": detect_modal_blocker(inspection),
    }


def diff_ui_states(pre_state: Optional[Dict[str, Any]], post_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    pre = pre_state or {}
    post = post_state or {}
    pre_hash = str(pre.get("stateHash") or "")
    post_hash = str(post.get("stateHash") or "")
    pre_texts = list(pre.get("textsPreview") or [])
    post_texts = list(post.get("textsPreview") or [])
    pre_set = set(pre_texts)
    post_set = set(post_texts)
    added = [t for t in post_texts if t not in pre_set]
    removed = [t for t in pre_texts if t not in post_set]
    title_changed = bool(pre.get("windowTitle") != post.get("windowTitle"))
    state_changed = bool((pre_hash and post_hash and pre_hash != post_hash) or added or removed or title_changed)
    pre_modal = (pre.get("modalStatus") or {}).get("kind", "none")
    post_modal = (post.get("modalStatus") or {}).get("kind", "none")
    return {
        "stateChanged": state_changed,
        "titleChanged": title_changed,
        "addedTexts": added[:20],
        "removedTexts": removed[:20],
        "modalAppeared": post_modal if (post_modal != "none" and post_modal != pre_modal) else "",
        "preHash": pre_hash,
        "postHash": post_hash,
    }


def infer_app_archetype(
    inspection: Optional[Dict[str, Any]],
    target_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Infer structural UI archetype purely from AX+OCR topology (zero app-name hardcoding)."""
    insp = inspection if isinstance(inspection, dict) else {}
    meta = target_meta if isinstance(target_meta, dict) else {}

    ax_ctrls = [c for c in (insp.get("axControls") or []) if isinstance(c, dict)]
    inputs = [i for i in (insp.get("inputElements") or []) if isinstance(i, dict)]
    if not inputs and ax_ctrls:
        inputs = [c for c in ax_ctrls if str(c.get("role") or "") in INPUT_ROLES]
    buttons = [b for b in (insp.get("buttonElements") or []) if isinstance(b, dict)]
    if not buttons and ax_ctrls:
        buttons = [c for c in ax_ctrls if str(c.get("role") or "") == "AXButton"]

    ax_count = int(insp.get("axControlCount") or len(ax_ctrls))
    ocr_count = int(insp.get("ocrCount") or len(insp.get("ocrElements") or []))
    ax_texts = [clean_ui_text(x) for x in (insp.get("axTexts") or []) if clean_ui_text(x)]
    win = insp.get("window") or {}
    bounds = (win.get("bounds") if isinstance(win, dict) else {}) or {}
    if not bounds and isinstance(insp.get("uiSummary"), dict):
        bounds = insp["uiSummary"].get("windowBounds") or {}
    win_area = max(1.0, float(bounds.get("width") or 800.0) * float(bounds.get("height") or 600.0))

    has_large_doc_editor = False
    has_bottom_composer = False
    for inp in inputs:
        ib = inp.get("bounds") or {}
        try:
            area = float(ib.get("width") or 0.0) * float(ib.get("height") or 0.0)
        except Exception:
            area = 0.0
        rc = inp.get("relCenter") or {}
        ry = float(rc.get("y") or 0.5) if isinstance(rc, dict) else 0.5
        role = str(inp.get("role") or "")
        if role == "AXTextArea" and area >= 0.28 * win_area:
            has_large_doc_editor = True
        if ry >= 0.65 and role in ("AXTextArea", "AXTextField"):
            has_bottom_composer = True

    has_scroll = any(str(c.get("role") or "") in ("AXScrollArea", "AXWebArea", "AXList") for c in ax_ctrls)
    left_items = 0
    right_items = 0
    for c in ax_ctrls:
        rc = c.get("relCenter") or {}
        if isinstance(rc, dict) and "x" in rc:
            rx = float(rc["x"])
            if rx < 0.35:
                left_items += 1
            elif rx > 0.45:
                right_items += 1

    # Check opaque / custom-rendered first
    if ax_count <= 5 and ocr_count >= 4 and len(inputs) == 0:
        arch_id = "canvas_or_opaque"
        label = "自定义绘制 / 视觉主导型应用 (Canvas / Opaque)"
        conf = 0.84
        attach_shot = True
        hints = [
            "该界面原生 AX 控件较少，优先依赖 Apple Vision OCR 文本坐标或附带截屏交给多模态视觉 Agent 定位。",
            "尽量使用快捷键 (hotkey/combo) 或 ocr matchText 点击。",
        ]
    elif bool(meta.get("isAgentApp")) or (has_bottom_composer and (has_scroll or len(inputs) >= 1)):
        arch_id = "chat_agent_surface"
        label = "对话 / Agent 交互面板 (Chat & Stream)"
        conf = 0.90 if has_bottom_composer else 0.78
        attach_shot = False
        hints = [
            "定位底部输入框填入 {{prompt}} 并回车提交，随后 wait_and_read 开启 waitUntilStable=true 等待流式输出稳定。",
            "使用 captureAs 与 extractMode='ocr_diff' 或 'ax_last' 提取最终回答。",
        ]
    elif has_large_doc_editor and not has_bottom_composer:
        arch_id = "document_editor"
        label = "长文档 / 富文本编辑器 (Document Editor)"
        conf = 0.88
        attach_shot = False
        hints = [
            "适合 focus_and_type 直接写入内容；如需新建或保存，优先使用 cmd+n / cmd+s 快捷键。",
            "写入后通过 AXValue 或 wait_and_read verify 关键词回读。",
        ]
    elif len(buttons) >= 10 and len(ax_texts) >= 1 and len(inputs) == 0:
        arch_id = "keypad_or_tool"
        label = "按钮阵列 / 工具面板型应用 (Keypad / Utility)"
        conf = 0.87
        attach_shot = False
        hints = [
            "键盘快捷键序列 (press_shortcut sequence) 与按按钮标题点击可稳定联动。",
            "在 wait_and_read 开启 waitUntilChanged=true + captureAs='result' 读取动态结果。",
        ]
    elif left_items >= 3 and right_items >= 2 and len(inputs) <= 2:
        arch_id = "list_detail_master"
        label = "左侧列表 + 右侧详情双栏应用 (Master-Detail)"
        conf = 0.80
        attach_shot = False
        hints = [
            "先在左栏 (relX < 0.35) 搜索或点击目标条目，等待右栏刷新后再提取或操作右栏控件。",
        ]
    elif len(inputs) >= 1:
        arch_id = "form_workbench"
        label = "表单 / 搜索工作台 (Form & Search Workbench)"
        conf = 0.82
        attach_shot = False
        hints = [
            "按 AXIdentifier / targetAxTitle / neighborTexts 逐项定位输入栏与提交/搜索按钮，填表提交后用 wait_and_read(waitUntilChanged=true) 验收结果。",
        ]
    else:
        arch_id = "generic_desktop"
        label = "通用 macOS 桌面应用"
        conf = 0.60
        attach_shot = False
        hints = [
            "先 activate_app + inspect_ui 获取控件与 OCR，再组合点击、安全粘贴和 wait_and_read 回读。",
        ]

    return {
        "id": arch_id,
        "label": label,
        "confidence": conf,
        "recommendAttachScreenshot": attach_shot,
        "strategyHints": hints,
        "interactiveSummary": {
            "axCount": ax_count,
            "inputCount": len(inputs),
            "buttonCount": len(buttons),
            "ocrCount": ocr_count,
        },
    }


class AppUIStateGraph:
    """Persistent lightweight UI transition graph accumulated from live App-Use runs & exploration."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("apps"), dict):
                    return raw
            except Exception:
                pass
        return {"schema": "openbot.app-use-state-graph/1", "apps": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, self._data)

    def _ensure_app(self, bundle_id: str, app_name: str = "", archetype_id: str = "") -> Dict[str, Any]:
        apps = self._data.setdefault("apps", {})
        entry = apps.get(bundle_id)
        if not isinstance(entry, dict):
            entry = {
                "bundleID": bundle_id,
                "appName": app_name or bundle_id,
                "archetypeId": archetype_id or "",
                "nodes": {},
                "edges": {},
                "updatedAt": _utc_iso_now(),
            }
            apps[bundle_id] = entry
        if app_name:
            entry["appName"] = app_name
        if archetype_id:
            entry["archetypeId"] = archetype_id
        return entry

    def record_observation(
        self,
        bundle_id: str,
        app_name: str,
        state: Optional[Dict[str, Any]],
        *,
        archetype_id: str = "",
    ) -> None:
        bid = str(bundle_id or "").strip()
        sh = str((state or {}).get("stateHash") or "").strip()
        if not bid or not sh or sh == "empty":
            return
        with self._lock:
            entry = self._ensure_app(bid, app_name=app_name, archetype_id=archetype_id)
            nodes = entry.setdefault("nodes", {})
            cur = nodes.get(sh) or {
                "stateHash": sh,
                "windowTitle": (state or {}).get("windowTitle", ""),
                "archetypeId": archetype_id,
                "modalKind": ((state or {}).get("modalStatus") or {}).get("kind", "none"),
                "visitCount": 0,
            }
            cur["visitCount"] = int(cur.get("visitCount") or 0) + 1
            cur["lastSeenAt"] = _utc_iso_now()
            if (state or {}).get("windowTitle"):
                cur["windowTitle"] = state["windowTitle"]
            nodes[sh] = cur
            if len(nodes) > 120:
                keep = sorted(nodes.items(), key=lambda kv: str(kv[1].get("lastSeenAt") or ""), reverse=True)[:120]
                entry["nodes"] = dict(keep)
            entry["updatedAt"] = _utc_iso_now()
            self._save()

    def record_transition(
        self,
        bundle_id: str,
        app_name: str,
        from_state: Optional[Dict[str, Any]],
        action_sig: str,
        to_state: Optional[Dict[str, Any]],
        *,
        ok: bool = True,
        latency_ms: float = 0.0,
        archetype_id: str = "",
    ) -> None:
        bid = str(bundle_id or "").strip()
        fh = str((from_state or {}).get("stateHash") or "").strip()
        th = str((to_state or {}).get("stateHash") or "").strip()
        sig = str(action_sig or "").strip()[:120]
        if not bid or not sig:
            return
        with self._lock:
            self.record_observation(bid, app_name, from_state, archetype_id=archetype_id)
            self.record_observation(bid, app_name, to_state, archetype_id=archetype_id)
            if not fh or not th or fh == "empty" or th == "empty":
                return
            entry = self._ensure_app(bid, app_name=app_name, archetype_id=archetype_id)
            edges = entry.setdefault("edges", {})
            ekey = f"{fh}|{sig}|{th}"
            cur = edges.get(ekey) or {
                "fromHash": fh,
                "toHash": th,
                "actionSig": sig,
                "count": 0,
                "successCount": 0,
                "stateChangedCount": 0,
                "avgLatencyMs": 0.0,
            }
            prev_n = int(cur.get("count") or 0)
            prev_avg = float(cur.get("avgLatencyMs") or 0.0)
            cur["count"] = prev_n + 1
            if ok:
                cur["successCount"] = int(cur.get("successCount") or 0) + 1
            if fh != th:
                cur["stateChangedCount"] = int(cur.get("stateChangedCount") or 0) + 1
            cur["avgLatencyMs"] = round(((prev_avg * prev_n) + float(latency_ms)) / float(prev_n + 1), 1)
            cur["lastAt"] = _utc_iso_now()
            edges[ekey] = cur
            if len(edges) > 240:
                keep = sorted(edges.items(), key=lambda kv: str(kv[1].get("lastAt") or ""), reverse=True)[:240]
                entry["edges"] = dict(keep)
            entry["updatedAt"] = _utc_iso_now()
            self._save()

    def suggest_known_transitions(self, bundle_id: str, state_hash: str) -> List[Dict[str, Any]]:
        bid = str(bundle_id or "").strip()
        sh = str(state_hash or "").strip()
        if not bid or not sh:
            return []
        with self._lock:
            entry = (self._data.get("apps") or {}).get(bid) or {}
            edges = entry.get("edges") or {}
            matches = [
                dict(e)
                for e in edges.values()
                if isinstance(e, dict) and e.get("fromHash") == sh and int(e.get("successCount") or 0) > 0
            ]
            matches.sort(key=lambda e: (int(e.get("stateChangedCount") or 0), int(e.get("successCount") or 0)), reverse=True)
            return matches[:8]

    def get_app_graph(self, bundle_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            apps = self._data.get("apps") or {}
            if bundle_id:
                bid = str(bundle_id).strip()
                entry = apps.get(bid)
                if not isinstance(entry, dict):
                    return {
                        "ok": True,
                        "bundleID": bid,
                        "nodeCount": 0,
                        "edgeCount": 0,
                        "nodes": [],
                        "edges": [],
                        "path": str(self.path),
                    }
                nodes = list((entry.get("nodes") or {}).values())
                edges = list((entry.get("edges") or {}).values())
                return {
                    "ok": True,
                    "bundleID": bid,
                    "appName": entry.get("appName", bid),
                    "archetypeId": entry.get("archetypeId", ""),
                    "nodeCount": len(nodes),
                    "edgeCount": len(edges),
                    "nodes": nodes,
                    "edges": edges,
                    "updatedAt": entry.get("updatedAt", ""),
                    "path": str(self.path),
                }
            return {
                "ok": True,
                "path": str(self.path),
                **self.summary(),
            }

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            apps = self._data.get("apps") or {}
            items: List[Dict[str, Any]] = []
            total_nodes = 0
            total_edges = 0
            for bid, entry in apps.items():
                if not isinstance(entry, dict):
                    continue
                nc = len(entry.get("nodes") or {})
                ec = len(entry.get("edges") or {})
                total_nodes += nc
                total_edges += ec
                items.append(
                    {
                        "bundleID": bid,
                        "appName": entry.get("appName", bid),
                        "archetypeId": entry.get("archetypeId", ""),
                        "nodeCount": nc,
                        "edgeCount": ec,
                        "updatedAt": entry.get("updatedAt", ""),
                    }
                )
            items.sort(key=lambda x: str(x.get("updatedAt") or ""), reverse=True)
            return {
                "appCount": len(items),
                "totalNodes": total_nodes,
                "totalEdges": total_edges,
                "apps": items,
            }


# ----------------------------------------------------------------------
# Algorithm 3: Trajectory Optimization, Anchor Enrichment & Readiness Score
# ----------------------------------------------------------------------


def step_action_signature(step: Dict[str, Any]) -> str:
    action = str(step.get("action") or "").strip().lower()
    hint = (
        step.get("targetAxId")
        or step.get("targetAxTitle")
        or step.get("matchText")
        or step.get("combo")
        or step.get("sequence")
        or ""
    )
    if not hint and step.get("relX") is not None and step.get("relY") is not None:
        hint = f"{step.get('relX')},{step.get('relY')}"
    return f"{action}:{clean_ui_text(hint)[:48]}"


def optimize_and_enrich_steps(
    steps: List[Dict[str, Any]],
    *,
    inspection: Optional[Dict[str, Any]] = None,
    transition_logs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Collapse redundant activations, prune stagnant no-ops, and attach semantic anchor bundles."""
    stagnant_indices: Set[int] = set()
    for log in transition_logs or []:
        if (
            isinstance(log, dict)
            and log.get("stateChanged") is False
            and isinstance(log.get("stepIndex"), int)
        ):
            stagnant_indices.add(int(log["stepIndex"]))

    cleaned: List[Dict[str, Any]] = []
    prev_action = ""
    for raw_idx, raw in enumerate(steps or [], start=1):
        if not isinstance(raw, dict):
            continue
        st = dict(raw)
        action = str(st.get("action") or "").strip().lower()
        step_num = int(st.get("step") or raw_idx)

        # Collapse duplicate back-to-back activate_app
        if action == "activate_app" and prev_action == "activate_app":
            continue

        # Prune verified stagnant no-op clicks/scrolls lacking assertions/captures
        if (
            action in ("click_element", "scroll")
            and step_num in stagnant_indices
            and not st.get("captureAs")
            and not st.get("expectText")
        ):
            continue

        # Enrich interactive steps with multi-factor anchor bundles when inspection exists
        if inspection and inspection.get("ok") and action in ("click_element", "focus_and_type"):
            if not (st.get("neighborTexts") and st.get("relX") is not None):
                res = SemanticElementGrounder.resolve_best(st, inspection, min_score=0.40)
                bundle = res.get("anchorBundle") or {}
                if bundle:
                    if not st.get("targetAxId") and bundle.get("targetAxId"):
                        st["targetAxId"] = bundle["targetAxId"]
                    if not st.get("targetAxTitle") and bundle.get("targetAxTitle"):
                        st["targetAxTitle"] = bundle["targetAxTitle"]
                    if not st.get("targetRole") and bundle.get("targetRole"):
                        st["targetRole"] = bundle["targetRole"]
                    if st.get("relX") is None and bundle.get("relX") is not None:
                        st["relX"] = bundle["relX"]
                    if st.get("relY") is None and bundle.get("relY") is not None:
                        st["relY"] = bundle["relY"]
                    if not st.get("neighborTexts") and bundle.get("neighborTexts"):
                        st["neighborTexts"] = bundle["neighborTexts"]

        cleaned.append(st)
        prev_action = action

    # Re-index step numbers cleanly
    for idx, st in enumerate(cleaned, start=1):
        st["step"] = idx
    return cleaned


def score_workflow_readiness(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Compute a deterministic 0-100 generalization readiness score for any App-Use workflow."""
    steps = [s for s in (workflow.get("steps") or []) if isinstance(s, dict)]
    recommendations: List[str] = []

    # 1. Interactive semantic/relative anchor strength (30 pts)
    interactive = [s for s in steps if s.get("action") in ("click_element", "focus_and_type")]
    if interactive:
        anchored = 0.0
        for s in interactive:
            has_sem = bool(s.get("targetAxId") or s.get("targetAxTitle") or s.get("matchText"))
            has_rel = s.get("relX") is not None and s.get("relY") is not None
            has_nb = bool(s.get("neighborTexts"))
            if has_sem and has_rel:
                anchored += 1.0 if has_nb else 0.9
            elif has_sem or has_rel:
                anchored += 0.65
        anchor_pts = round(30.0 * (anchored / float(len(interactive))), 1)
        if anchor_pts < 24.0:
            recommendations.append("为 click_element / focus_and_type 步骤补齐 targetAxTitle/relX/neighborTexts 锚点包，以抵抗窗口缩放或 UI 漂移。")
    else:
        anchor_pts = 26.0 if steps else 0.0

    # 2. Post-action verification / readback coverage (25 pts)
    has_wait = any(s.get("action") == "wait_and_read" for s in steps)
    has_expect_or_cap = any(bool(s.get("expectText") or s.get("captureAs") or s.get("waitUntilStable") or s.get("waitUntilChanged")) for s in steps)
    if has_wait and has_expect_or_cap:
        verify_pts = 25.0
    elif has_wait:
        verify_pts = 18.0
        recommendations.append("建议在 wait_and_read 步骤开启 captureAs、expectText、waitUntilChanged 或 waitUntilStable。")
    elif any(s.get("action") == "inspect_ui" for s in steps):
        verify_pts = 10.0
        recommendations.append("建议在关键动作后增加 wait_and_read 回读验收步骤。")
    else:
        verify_pts = 0.0
        recommendations.append("流程缺少回读验收（wait_and_read），无法感知执行是否成功。")

    # 3. Safety & gate hygiene (15 pts)
    has_activate = any(s.get("action") == "activate_app" for s in steps)
    has_gates = bool(workflow.get("safetyGates")) or any(s.get("action") == "pause_for_human" for s in steps)
    safety_pts = (8.0 if has_activate else 0.0) + (7.0 if has_gates else 3.0)
    if not has_activate:
        recommendations.append("建议以 activate_app 作为首步，确保跨应用切换焦点稳定。")

    # 4. Dynamic parameterization & output pipeline capability (15 pts)
    params = workflow.get("parameters") or []
    has_cap = any(bool(s.get("captureAs")) for s in steps)
    param_pts = (10.0 if params else 4.0) + (5.0 if has_cap else 1.0)
    if not params and not has_cap:
        recommendations.append("可将固定输入抽为 {{参数}} 并为末尾读数增加 captureAs，便于跨应用串联复用。")

    # 5. UI structural metadata & archetype awareness (15 pts)
    has_ui_snap = bool((workflow.get("uiProfileSnapshot") or {}).get("windowBounds") or workflow.get("uiProfileSnapshot"))
    has_arch = bool(workflow.get("archetype"))
    meta_pts = (9.0 if has_ui_snap else 0.0) + (6.0 if has_arch else 0.0)
    if not has_ui_snap:
        recommendations.append("建议在实机窗口开启时生成或重新扫描，以保存窗口拓扑指纹与 Archetype 原型。")

    total = round(min(100.0, anchor_pts + verify_pts + safety_pts + param_pts + meta_pts), 1)
    if total >= 85.0:
        grade = "A"
    elif total >= 70.0:
        grade = "B"
    elif total >= 50.0:
        grade = "C"
    else:
        grade = "D"

    return {
        "score": total,
        "grade": grade,
        "breakdown": {
            "semanticAnchors": anchor_pts,
            "verificationReadback": verify_pts,
            "safetyActivation": safety_pts,
            "parameterization": param_pts,
            "topologyMetadata": meta_pts,
        },
        "recommendations": recommendations,
    }


# ----------------------------------------------------------------------
# Algorithm 4: Failure-Taxonomy Classifier for Runtime Self-Healing
# ----------------------------------------------------------------------


def classify_step_failure(
    step: Dict[str, Any],
    error_msg: str,
    live_inspect: Optional[Dict[str, Any]],
    *,
    pre_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Classify a step execution failure into actionable self-healing taxonomy."""
    err_low = clean_ui_text(error_msg).casefold()
    action = str(step.get("action") or "").strip().lower()
    modal = detect_modal_blocker(live_inspect)

    if "not_frontmost" in err_low or "frontmost app is" in err_low:
        return {
            "category": "NOT_FRONTMOST",
            "recommendedStrategy": "reactivate_and_retry",
            "requiresHuman": False,
            "reason": f"目标窗口尚未抢到前台焦点 ({error_msg})",
        }

    if modal.get("kind") == "auth_or_risk_gate":
        return {
            "category": "AUTH_GATE",
            "recommendedStrategy": "pause_for_human",
            "requiresHuman": True,
            "signals": modal.get("signals") or [],
            "reason": f"检测到登录/密码/授权或高风险确认弹窗 ({', '.join(modal.get('signals') or [])})，安全挂起等待人工接管。",
        }

    if modal.get("kind") == "dismissible_modal":
        return {
            "category": "MODAL_OCCLUSION",
            "recommendedStrategy": "dismiss_and_retry",
            "requiresHuman": False,
            "dismissCombo": str(modal.get("dismissCombo") or "escape"),
            "signals": modal.get("signals") or [],
            "reason": f"检测到可关闭模态弹窗 ({', '.join(modal.get('signals') or [])})，尝试发送 Escape 关闭后重试。",
        }

    if action in ("click_element", "focus_and_type") and (
        "unresolved" in err_low
        or "not found" in err_low
        or "failed" in err_low
        or "未" in err_low
    ):
        return {
            "category": "ELEMENT_DRIFT",
            "recommendedStrategy": "semantic_reanchor",
            "requiresHuman": False,
            "reason": "控件坐标或标识发生漂移，使用多因子语义/拓扑锚定重新定位。",
        }

    if action == "wait_and_read" or "expecttext" in err_low or "mismatch" in err_low:
        return {
            "category": "READBACK_MISMATCH" if "expecttext" in err_low else "TIMING_LAG",
            "recommendedStrategy": "wait_for_change_retry",
            "requiresHuman": False,
            "reason": "界面内容尚在刷新或计算结算延迟，等待内容变更后再次采集。",
        }

    return {
        "category": "ELEMENT_DRIFT",
        "recommendedStrategy": "semantic_reanchor",
        "requiresHuman": False,
        "reason": error_msg or "执行异常，尝试单步自愈。",
    }


# ----------------------------------------------------------------------
# Algorithm 5: Foreground HID Micro-Lease for Safe Multi-Window Concurrency
# ----------------------------------------------------------------------


class ForegroundHIDLease:
    """Thread-safe mutex isolating shared macOS foreground focus, cursor & clipboard
    only during active HID mutations, while allowing window-pinned perception, OCR,
    state hashing, and LLM planning across N app windows in parallel.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stats_lock = threading.Lock()
        self._active_holder: Optional[Dict[str, str]] = None
        self._last_holder: Optional[Dict[str, str]] = None
        self._total_acquisitions = 0
        self._contended_acquisitions = 0
        self._total_wait_ms = 0.0

    @contextlib.contextmanager
    def acquire(
        self,
        *,
        job_id: str = "",
        bundle_id: str = "",
        step_action: str = "",
    ) -> Iterator[Dict[str, Any]]:
        t0 = time.perf_counter()
        # Non-blocking probe to detect real contention before blocking wait
        got_fast = self._lock.acquire(blocking=False)
        if not got_fast:
            self._lock.acquire()
        wait_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        holder = {"jobId": job_id, "bundleID": bundle_id, "action": step_action}
        with self._stats_lock:
            self._total_acquisitions += 1
            if not got_fast:
                self._contended_acquisitions += 1
            self._total_wait_ms += wait_ms
            self._active_holder = holder
        info = {"waitMs": wait_ms, "contended": not got_fast, "holder": holder}
        try:
            yield info
        finally:
            with self._stats_lock:
                self._last_holder = holder
                self._active_holder = None
            self._lock.release()

    def stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return {
                "totalAcquisitions": self._total_acquisitions,
                "contendedAcquisitions": self._contended_acquisitions,
                "totalWaitMs": round(self._total_wait_ms, 2),
                "activeHolder": self._active_holder,
                "lastHolder": self._last_holder,
            }


# ----------------------------------------------------------------------
# v2.9.0: Three-Tier Anti-Ban Risk Engine, Pacer & Concurrency Swimlanes
# ----------------------------------------------------------------------

HIGH_RISK_SOCIAL_HINTS: Tuple[str, ...] = (
    "xinwechat",
    "wechat",
    "微信",
    "wework",
    "企业微信",
    "dingtalk",
    "钉钉",
    "feishu",
    "lark",
    "飞书",
    "xiaohongshu",
    "rednote",
    "小红书",
    "douyin",
    "tiktok",
    "抖音",
    "com.tencent.qq",
    "qqmusic",
    "alipay",
    "支付宝",
    "taobao",
    "淘宝",
    "pinduoduo",
    "拼多多",
    "jd.com",
    "eastmoney",
    "同花顺",
    "futu",
    "富途",
    "tigertrade",
    "bank",
    "银行",
)

MODERATE_AGENT_WEB_HINTS: Tuple[str, ...] = (
    "chatgpt",
    "openai",
    "claude",
    "anthropic",
    "gemini",
    "cursor",
    "antigravity",
    "codebuddy",
    "workbuddy",
    "codex",
    "chrome",
    "safari",
    "firefox",
    "arc",
    "edge",
    "brave",
    "ego.lite",
    "electron",
)


def classify_app_risk_tier(
    bundle_id: str,
    app_name: str = "",
    app_path: str = "",
    *,
    category: str = "",
) -> Dict[str, Any]:
    """Classify a macOS app into anti-ban execution risk tiers without hardcoding safe tools."""
    hay = f"{bundle_id} {app_name} {app_path}".casefold()
    cat = str(category or "").strip().lower()

    if any(tok in hay for tok in HIGH_RISK_SOCIAL_HINTS) or cat == "im_social":
        return {
            "tier": "high_risk_social",
            "riskLevel": "high",
            "riskLabel": "高风控社交/金融保护",
            "defaultDispatchMode": "foreground_human_paced",
            "allowHeadlessAxWrite": False,
            "allowBackgroundReadOnly": True,
            "jitterRangeMs": [260, 780],
            "minActionGapMs": 350,
            "maxBackgroundInspectHz": 0.5,
            "advice": "禁止后台无焦点 AX 写入注入；写操作强制走 ForegroundHIDLease 前台真焦点 + 随机人类节奏抖动，避免异常非前景修改事件触发风控。",
        }

    if any(tok in hay for tok in MODERATE_AGENT_WEB_HINTS) or cat in ("agent_app", "browser"):
        return {
            "tier": "moderate_agent_or_web",
            "riskLevel": "medium",
            "riskLabel": "中度 · Agent / WebView 双通道",
            "defaultDispatchMode": "headless_ax_first",
            "allowHeadlessAxWrite": True,
            "allowBackgroundReadOnly": True,
            "jitterRangeMs": [90, 240],
            "minActionGapMs": 120,
            "maxBackgroundInspectHz": 2.0,
            "advice": "支持优先尝试无焦点 AX 直调；若 Electron/WebView 控件不支持或回读未生效，自动平滑降级到 ForegroundHIDLease 前台真键鼠。",
        }

    return {
        "tier": "safe_native",
        "riskLevel": "low",
        "riskLabel": "安全原生 · 无焦点真并发",
        "defaultDispatchMode": "headless_ax_first",
        "allowHeadlessAxWrite": True,
        "allowBackgroundReadOnly": True,
        "jitterRangeMs": [0, 0],
        "minActionGapMs": 0,
        "maxBackgroundInspectHz": 5.0,
        "advice": "本地原生/办公工具无封号风控风险；默认优先走无焦点 AXPress/AXSetValue 直调，不抢焦点、不动鼠标、不占剪贴板，支持多窗口真并行。",
    }


class AntiRiskPacer:
    """Thread-safe per-app human-paced action interval & randomized jitter guard."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_mutation_mono: Dict[str, float] = {}
        self._total_slept_ms: float = 0.0
        self._total_paced_ops: int = 0

    def pace_before_mutation(
        self,
        bundle_id: str,
        risk_profile: Dict[str, Any],
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
        mono_fn: Callable[[], float] = time.monotonic,
    ) -> Dict[str, Any]:
        tier = str(risk_profile.get("tier") or "safe_native")
        j_range = risk_profile.get("jitterRangeMs") or [0, 0]
        try:
            lo = max(0.0, float(j_range[0]))
            hi = max(lo, float(j_range[1]) if len(j_range) > 1 else lo)
        except Exception:
            lo, hi = 0.0, 0.0
        try:
            min_gap_ms = max(0.0, float(risk_profile.get("minActionGapMs") or 0.0))
        except Exception:
            min_gap_ms = 0.0

        key = str(bundle_id or "_global").strip().lower() or "_global"
        jitter_ms = random.uniform(lo, hi) if hi > lo else lo

        with self._lock:
            now = float(mono_fn())
            last_t = self._last_mutation_mono.get(key)
            gap_wait_ms = 0.0
            if last_t is not None and min_gap_ms > 0.0:
                elapsed_ms = max(0.0, (now - last_t) * 1000.0)
                if elapsed_ms < min_gap_ms:
                    gap_wait_ms = min_gap_ms - elapsed_ms
            total_wait_ms = max(0.0, gap_wait_ms + jitter_ms)
            self._last_mutation_mono[key] = now + (total_wait_ms / 1000.0)

        if total_wait_ms > 0.0:
            sleep_fn(total_wait_ms / 1000.0)

        with self._lock:
            self._total_paced_ops += 1
            self._total_slept_ms += total_wait_ms

        return {
            "sleptMs": round(total_wait_ms, 1),
            "tier": tier,
            "bundleID": str(bundle_id or ""),
        }

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "totalPacedOps": self._total_paced_ops,
                "totalSleptMs": round(self._total_slept_ms, 1),
                "trackedApps": sorted(self._last_mutation_mono.keys()),
            }


class ConcurrencyLaneTracker:
    """Thread-safe live swimlane telemetry for parallel App-Use execution & risk routing."""

    def __init__(self, *, max_recent: int = 24) -> None:
        self._lock = threading.Lock()
        self._active: Dict[str, Dict[str, Any]] = {}
        self._recent: Deque[Dict[str, Any]] = deque(maxlen=max(4, int(max_recent or 24)))
        self._total_headless_ops: int = 0
        self._total_hid_ops: int = 0
        self._total_fallback_count: int = 0
        self._total_risk_blocked: int = 0

    def start_lane(
        self,
        lane_id: str,
        *,
        bundle_id: str,
        app_name: str = "",
        risk_tier: str = "",
        dispatch_mode: str = "auto",
        state: str = "observing",
        current_action: str = "",
    ) -> None:
        now_iso = _utc_iso_now()
        with self._lock:
            self._active[lane_id] = {
                "laneId": lane_id,
                "bundleID": bundle_id,
                "appName": app_name or bundle_id,
                "riskTier": risk_tier or "safe_native",
                "dispatchMode": dispatch_mode or "auto",
                "state": state,
                "currentAction": current_action,
                "dispatchChannel": "",
                "headlessAxOps": 0,
                "foregroundHidOps": 0,
                "fallbackCount": 0,
                "riskBlockedCount": 0,
                "hidWaitMs": 0.0,
                "jitterMs": 0.0,
                "note": "",
                "startedAt": now_iso,
                "updatedAt": now_iso,
                "_t0": time.perf_counter(),
            }

    def update_lane(
        self,
        lane_id: str,
        *,
        state: Optional[str] = None,
        current_action: Optional[str] = None,
        dispatch_channel: Optional[str] = None,
        delta_headless: int = 0,
        delta_hid: int = 0,
        delta_fallback: int = 0,
        delta_risk_blocked: int = 0,
        delta_hid_wait_ms: float = 0.0,
        delta_jitter_ms: float = 0.0,
        note: str = "",
    ) -> None:
        with self._lock:
            lane = self._active.get(lane_id)
            if lane is None:
                return
            if state is not None:
                lane["state"] = state
            if current_action is not None:
                lane["currentAction"] = current_action
            if dispatch_channel is not None:
                lane["dispatchChannel"] = dispatch_channel
            if delta_headless:
                lane["headlessAxOps"] = int(lane["headlessAxOps"]) + int(delta_headless)
                self._total_headless_ops += int(delta_headless)
            if delta_hid:
                lane["foregroundHidOps"] = int(lane["foregroundHidOps"]) + int(delta_hid)
                self._total_hid_ops += int(delta_hid)
            if delta_fallback:
                lane["fallbackCount"] = int(lane["fallbackCount"]) + int(delta_fallback)
                self._total_fallback_count += int(delta_fallback)
            if delta_risk_blocked:
                lane["riskBlockedCount"] = int(lane["riskBlockedCount"]) + int(delta_risk_blocked)
                self._total_risk_blocked += int(delta_risk_blocked)
            if delta_hid_wait_ms:
                lane["hidWaitMs"] = round(float(lane["hidWaitMs"]) + float(delta_hid_wait_ms), 1)
            if delta_jitter_ms:
                lane["jitterMs"] = round(float(lane["jitterMs"]) + float(delta_jitter_ms), 1)
            if note:
                lane["note"] = note
            lane["updatedAt"] = _utc_iso_now()

    def finish_lane(
        self,
        lane_id: str,
        *,
        ok: bool = True,
        state: Optional[str] = None,
        error: str = "",
    ) -> None:
        with self._lock:
            lane = self._active.pop(lane_id, None)
            if lane is None:
                return
            t0 = float(lane.pop("_t0", time.perf_counter()))
            lane["elapsedMs"] = round((time.perf_counter() - t0) * 1000.0, 1)
            lane["ok"] = bool(ok)
            lane["state"] = state or ("done" if ok else "failed")
            lane["error"] = str(error or "")
            lane["finishedAt"] = _utc_iso_now()
            lane["updatedAt"] = lane["finishedAt"]
            self._recent.appendleft(lane)

    @staticmethod
    def _public_lane(raw: Dict[str, Any]) -> Dict[str, Any]:
        out = {k: v for k, v in raw.items() if not str(k).startswith("_")}
        if "_t0" in raw and "elapsedMs" not in out:
            out["elapsedMs"] = round((time.perf_counter() - float(raw["_t0"])) * 1000.0, 1)
        return out

    def snapshot(
        self,
        hid_lease_stats: Optional[Dict[str, Any]] = None,
        pacer_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            active_list = [self._public_lane(x) for x in self._active.values()]
            recent_list = [self._public_lane(x) for x in self._recent]
            tot_mut = self._total_headless_ops + self._total_hid_ops
            share = round((self._total_headless_ops / tot_mut) * 100.0, 1) if tot_mut > 0 else 0.0
            metrics = {
                "activeCount": len(active_list),
                "recentCount": len(recent_list),
                "totalHeadlessAxOps": self._total_headless_ops,
                "totalForegroundHidOps": self._total_hid_ops,
                "totalFallbackCount": self._total_fallback_count,
                "totalRiskBlockedHeadless": self._total_risk_blocked,
                "headlessSharePct": share,
            }
        return {
            "ok": True,
            "activeLanes": active_list,
            "recentLanes": recent_list,
            "metrics": metrics,
            "hidLeaseStats": hid_lease_stats or {},
            "pacerStats": pacer_stats or {},
            "updatedAt": _utc_iso_now(),
        }
