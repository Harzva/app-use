"""App window binding (WeChat + WeCom) and conversational document-to-knowledge ingestion.

Provides:
- `AppWindowBinder`: Persists the active target application (`wechat` | `wecom` | `auto`)
  and specific window ID/title while strictly preserving contact allowlist isolation.
- `DocumentKnowledgeIngestor`: Extracts text from `.pdf` (via native `extract-pdf-text`
  PDFKit + Vision OCR fallback), `.txt`/`.md`/`.json`, base64 uploads, or pasted raw text;
  chunks into structured KB drafts (`knowledge` / `terminology` / `faq` / `script`);
  presents Thiflow-style strategy comparison (`bind_kb` recommended vs `merge_prompt`);
  and executes batch `save_entry(..., library="shared", source="doc-ingest", external=True, status="published")`.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .io_utils import atomic_write_json
from .knowledge_kf_engine import KINDS, _guard_secrets, split_search_terms

SUPPORTED_APP_IDS: Tuple[str, ...] = ("auto", "wechat", "wecom")
APP_LABELS: Dict[str, str] = {
    "auto": "自动跟随",
    "wechat": "微信",
    "wecom": "企业微信",
}
APP_BUNDLE_IDS: Dict[str, str] = {
    "wechat": "com.tencent.xinWeChat",
    "wecom": "com.tencent.WeWorkMac",
}
ALLOWED_TEST_CONTACTS: Tuple[str, ...] = ("安晓心", "心安", "openbot")

SUPPORTED_DOC_EXTENSIONS: Tuple[str, ...] = (".pdf", ".txt", ".md", ".markdown", ".json")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MiB cap for base64 uploads
MAX_TEXT_CHARS = 120_000

STRATEGY_OPTIONS: List[Dict[str, Any]] = [
    {
        "id": "bind_kb",
        "recommended": True,
        "title": "绑进知识库（推荐）",
        "desc": "保持现有营销人设不变，AI 回答精准按产品资料作答",
    },
    {
        "id": "merge_prompt",
        "recommended": False,
        "title": "直接优化岗位提示词",
        "desc": "把关键卖点并入 AI 员工任务目标",
    },
]

_INTERNAL_SCRUB_RE: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"RealtimeMessageMonitor|RealtimeMonitor", re.I), "实时巡检"),
    (re.compile(r"VNRecognize\w*|Vision\s*OCR", re.I), "图文识别"),
    (re.compile(r"CGWindow\w*", re.I), "窗口截图"),
    (re.compile(r"CGEvent\w*", re.I), "界面操作"),
    (re.compile(r"AXUIElement", re.I), "界面组件"),
    (re.compile(r"FTS5", re.I), "知识库"),
)

_HEADING_MD_RE = re.compile(r"^#{1,4}\s+(.+?)\s*$")
_HEADING_BRACKET_RE = re.compile(r"^【([^】]{1,36})】\s*(.*)$")
_HEADING_NUM_RE = re.compile(r"^(?:[一二三四五六七八九十]{1,3}[、.．]|\d{1,2}[、.．])\s*(.{2,32})$")
_LABEL_LINE_RE = re.compile(
    r"^(核心卖点|产品卖点|卖点|核心优势|产品优势|产品亮点|核心亮点|亮点|产品简介|产品介绍|简介|功效|特点|适用人群|核心功能|"
    r"使用方法与步骤|使用方法及步骤|使用方法|使用步骤|操作步骤|操作流程|使用指南|使用方式|操作说明|使用说明|用法用量|用法与用量|用法|冲泡方法|安装步骤|"
    r"注意事项|注意|禁忌(?:说明)?|安全提示|温馨提示|保存方法|储存条件|售后政策|售后|保修说明|"
    r"规格参数|产品参数|技术参数|规格|参数|主要成分|成分材质|"
    r"常见问题|常见FAQ|FAQ|常见问答|客服话术|推荐话术|接待话术|话术|异议处理)\s*[：:]\s*(.*)$",
    re.I,
)
_QA_Q_RE = re.compile(r"^(?:Q\d*|问)\s*[：:.\s]\s*(.+)$", re.I)
_QA_A_RE = re.compile(r"^(?:A\d*|答)\s*[：:.\s]\s*(.+)$", re.I)
_METADATA_LINE_RE = re.compile(r"^(?:产品名称|产品型号|产品品牌|名称|品牌|型号|产品)\s*[：:]\s*(.{1,40})$")

_FAQ_HINT_RE = re.compile(r"(常见问题|\bFAQ\b|问[：:]|Q\d*[：:]|为什么|怎么办|适合什么|能不能|可以吗|多久见效)", re.I)
_SCRIPT_HINT_RE = re.compile(r"(话术|口径|回复模板|接待语|异议处理|安抚话术)", re.I)
_CAUTION_HINT_RE = re.compile(
    r"(注意|禁忌|禁止|切勿|不要|警告|风险|过敏|孕妇|哺乳期|保存|保质期|储存|售后|退换|参数|规格|成分|材质|电压|温度)",
    re.I,
)
_USAGE_HINT_RE = re.compile(
    r"(使用|步骤|怎么用|用法|用量|操作|流程|教程|安装|开机|冲泡|涂抹|清洁|维护|更换|滤芯|配对|第[一二三四五六七八九十\d]+步|\bstep\s*\d+)",
    re.I,
)
_SELLING_HINT_RE = re.compile(
    r"(卖点|优势|亮点|核心|特色|功效|特点|主打|专利|升级|对比|介绍|简介)",
    re.I,
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scrub_internal_terms(text: str) -> str:
    out = str(text or "")
    for pat, repl in _INTERNAL_SCRUB_RE:
        out = pat.sub(repl, out)
    return out


class AppWindowBinder:
    """Manages and persists the bound desktop app window (`wechat` | `wecom` | `auto`)."""

    SUPPORTED_APPS = SUPPORTED_APP_IDS
    ALLOWED_TEST_CONTACTS = ALLOWED_TEST_CONTACTS

    def __init__(self, state_path: Path | str) -> None:
        self.state_path = Path(state_path)
        self._lock = threading.RLock()

    @staticmethod
    def normalize_app_id(app_id: Optional[str]) -> str:
        raw = unicodedata.normalize("NFKC", str(app_id or "")).strip().lower()
        if raw in ("", "auto", "自动", "自动跟随", "all"):
            return "auto"
        if raw in ("wechat", "wx", "微信", "com.tencent.xinwechat"):
            return "wechat"
        if raw in ("wecom", "wework", "企微", "企业微信", "com.tencent.weworkmac"):
            return "wecom"
        raise ValueError(
            f"Unsupported appId {app_id!r}. Only 'wechat', 'wecom', and 'auto' are supported."
        )

    def _default_state(self) -> Dict[str, Any]:
        return {
            "schema": "openbot.app-window-binding/1",
            "appId": "auto",
            "appLabel": APP_LABELS["auto"],
            "windowID": None,
            "windowTitle": "",
            "followUpIsolation": True,
            "updatedAt": _utc_iso_now(),
        }

    def _normalize_loaded(self, raw: Any) -> Dict[str, Any]:
        base = self._default_state()
        if not isinstance(raw, dict):
            return base
        try:
            app_id = self.normalize_app_id(raw.get("appId"))
        except ValueError:
            app_id = "auto"
        wid = raw.get("windowID")
        try:
            clean_wid = int(wid) if wid not in (None, "", 0, "0", False) and int(wid) > 0 else None
        except (TypeError, ValueError):
            clean_wid = None
        clean_title = re.sub(r"\s+", " ", str(raw.get("windowTitle") or "")).strip()[:120]
        if app_id == "auto" and clean_wid is None:
            clean_title = ""
        clean_label = str(raw.get("appLabel") or APP_LABELS[app_id]).strip() or APP_LABELS[app_id]
        return {
            "schema": "openbot.app-window-binding/1",
            "appId": app_id,
            "appLabel": clean_label,
            "windowID": clean_wid,
            "windowTitle": clean_title,
            "followUpIsolation": bool(raw.get("followUpIsolation", True)),
            "updatedAt": str(raw.get("updatedAt") or base["updatedAt"]),
        }

    def get_binding(self) -> Dict[str, Any]:
        with self._lock:
            try:
                if self.state_path.is_file():
                    raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                    return self._normalize_loaded(raw)
            except Exception:
                pass
            return self._default_state()

    def bind(
        self,
        app_id: str = "auto",
        *,
        window_id: Optional[int] = None,
        window_title: str = "",
        app_label: Optional[str] = None,
        follow_up_isolation: bool = True,
    ) -> Dict[str, Any]:
        clean_app = self.normalize_app_id(app_id)
        if window_id in (None, "", 0, "0", False):
            clean_wid: Optional[int] = None
        else:
            try:
                parsed_wid = int(window_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid windowID: {window_id!r}") from exc
            clean_wid = parsed_wid if parsed_wid > 0 else None

        clean_title = re.sub(r"\s+", " ", str(window_title or "")).strip()[:120]
        if clean_app == "auto" and clean_wid is None:
            clean_title = ""

        clean_label = str(app_label or APP_LABELS[clean_app]).strip() or APP_LABELS[clean_app]
        payload = {
            "schema": "openbot.app-window-binding/1",
            "appId": clean_app,
            "appLabel": clean_label,
            "windowID": clean_wid,
            "windowTitle": clean_title,
            "followUpIsolation": bool(follow_up_isolation),
            "updatedAt": _utc_iso_now(),
        }
        with self._lock:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.state_path, payload)
        return dict(payload)

    def reset(self) -> Dict[str, Any]:
        return self.bind("auto", window_id=None, window_title="", follow_up_isolation=True)


class DocumentKnowledgeIngestor:
    """Conversational document ingestion & structured knowledge drafting for WorkOS."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def _managed_temp_dir(self) -> Path:
        reports_dir = getattr(getattr(self.engine, "inspector", None), "reports_dir", None)
        base = Path(reports_dir) if reports_dir else Path(self.engine.plugin_root) / "logs"
        tmp_dir = base / "doc_ingest_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir

    @staticmethod
    def _flatten_json_text(obj: Any, prefix: str = "") -> List[str]:
        lines: List[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = str(k).strip()
                label = f"{prefix}.{key}" if prefix else key
                if isinstance(v, (dict, list)):
                    lines.extend(DocumentKnowledgeIngestor._flatten_json_text(v, label))
                elif v is not None and str(v).strip():
                    lines.append(f"{label}：{str(v).strip()}")
        elif isinstance(obj, list):
            for idx, item in enumerate(obj, 1):
                if isinstance(item, (dict, list)):
                    lines.extend(DocumentKnowledgeIngestor._flatten_json_text(item, f"{prefix}[{idx}]" if prefix else f"条目{idx}"))
                elif item is not None and str(item).strip():
                    lines.append(f"{prefix}：{str(item).strip()}" if prefix else str(item).strip())
        elif obj is not None and str(obj).strip():
            lines.append(f"{prefix}：{str(obj).strip()}" if prefix else str(obj).strip())
        return lines

    def _decode_b64_to_managed_file(self, file_bytes_b64: str, filename: str) -> Tuple[Path, str]:
        raw_str = str(file_bytes_b64 or "").strip()
        if raw_str.startswith("data:") and ";base64," in raw_str[:128]:
            raw_str = raw_str.split(";base64,", 1)[1]
        b64_clean = re.sub(r"\s+", "", raw_str)
        if not b64_clean:
            raise ValueError("Uploaded base64 file content is empty.")
        try:
            raw_bytes = base64.b64decode(b64_clean, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Invalid base64 file payload: {exc}") from exc
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Uploaded file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.")

        orig_name = Path(str(filename or "").strip() or "document").name
        safe_name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", orig_name).strip("._") or "document"
        suffix = Path(safe_name).suffix.lower()
        if not suffix:
            suffix = ".pdf" if raw_bytes[:5] == b"%PDF-" else ".txt"
            safe_name = f"{safe_name}{suffix}"
        if suffix not in SUPPORTED_DOC_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension {suffix!r}. Supported: {', '.join(SUPPORTED_DOC_EXTENSIONS)}"
            )

        tmp_dir = self._managed_temp_dir()
        target_path = (tmp_dir / f"ingest_{uuid.uuid4().hex[:10]}_{safe_name}").resolve()
        if target_path.parent != tmp_dir.resolve():
            raise ValueError("Invalid target filename.")
        target_path.write_bytes(raw_bytes)
        return target_path, orig_name

    def _extract_text_from_file(self, file_path: Path, *, max_pages: int = 12) -> Dict[str, Any]:
        path = Path(file_path).expanduser()
        if not path.is_file():
            return {
                "ok": False,
                "error_code": "file_not_found",
                "error": f"未找到资料文件：{path}",
            }
        ext = path.suffix.lower()
        if ext == ".pdf":
            pages_limit = str(max(1, min(50, int(max_pages))))
            native_res = self.engine._run_native(
                ["extract-pdf-text", "--pdf", str(path), "--max-pages", pages_limit],
                timeout=45.0,
            )
            if not native_res.get("ok"):
                return {
                    "ok": False,
                    "error_code": native_res.get("error_code") or "pdf_extract_failed",
                    "error": native_res.get("error") or "PDF 解析失败",
                    "native": native_res,
                }
            pages = native_res.get("pages") or []
            extracted = str(native_res.get("text") or "").strip()
            if not extracted and isinstance(pages, list):
                extracted = "\n\n".join(
                    str(p.get("text") or "").strip()
                    for p in pages
                    if isinstance(p, dict) and str(p.get("text") or "").strip()
                )
            return {
                "ok": True,
                "sourceType": "pdf",
                "text": extracted[:MAX_TEXT_CHARS],
                "pageCount": int(native_res.get("pageCount") or len(pages) or 1),
                "processedPages": int(native_res.get("processedPages") or len(pages) or 1),
                "truncated": bool(native_res.get("truncated", False)),
                "pages": pages,
            }

        if ext in (".txt", ".md", ".markdown"):
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return {"ok": False, "error_code": "read_failed", "error": str(exc)}
            return {
                "ok": True,
                "sourceType": "markdown" if ext in (".md", ".markdown") else "text",
                "text": raw[:MAX_TEXT_CHARS],
                "pageCount": 1,
                "processedPages": 1,
                "pages": [],
            }

        if ext == ".json":
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
                parsed = json.loads(raw)
                flat = "\n".join(self._flatten_json_text(parsed))
                text_out = flat.strip() or raw
            except Exception:
                text_out = path.read_text(encoding="utf-8", errors="replace")
            return {
                "ok": True,
                "sourceType": "json",
                "text": text_out[:MAX_TEXT_CHARS],
                "pageCount": 1,
                "processedPages": 1,
                "pages": [],
            }

        return {
            "ok": False,
            "error_code": "unsupported_file_type",
            "error": f"不支持的文件格式 {ext!r}，仅支持 .pdf、.txt、.md、.json。",
        }

    @staticmethod
    def _clean_doc_text(text: str) -> str:
        norm = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        norm = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", norm)
        norm = re.sub(r"\*\*([^*\n]{1,120})\*\*", r"\1", norm)
        norm = re.sub(r"`([^`\n]{1,80})`", r"\1", norm)
        norm = re.sub(r"\n{3,}", "\n\n", norm)
        return _scrub_internal_terms(norm).strip()

    @staticmethod
    def _infer_product_hint(doc_name: str, cleaned_text: str) -> str:
        generic_stems = {
            "product", "doc", "document", "manual", "guide", "upload",
            "file", "info", "spec", "readme", "test", "sample", "untitled",
        }
        doc_stem = ""
        if doc_name:
            stem = Path(doc_name).stem.strip()
            stem = re.sub(r"^[a-f0-9]{8,}_", "", stem)
            stem = re.sub(r"(?:说明书|产品手册|产品资料|指南|白皮书|手册)$", "", stem).strip(" _-·")
            if 2 <= len(stem) <= 22 and stem.casefold() not in generic_stems:
                doc_stem = stem
        for line in cleaned_text.splitlines()[:8]:
            s = line.strip()
            m_name = _METADATA_LINE_RE.match(s)
            if m_name and len(m_name.group(1).strip()) >= 2:
                return m_name.group(1).strip()[:32]
            m_md = _HEADING_MD_RE.match(s)
            if m_md:
                cand = m_md.group(1).strip()
                if (
                    2 <= len(cand) <= 32
                    and not _SELLING_HINT_RE.fullmatch(cand)
                    and not _USAGE_HINT_RE.fullmatch(cand)
                    and not _CAUTION_HINT_RE.fullmatch(cand)
                    and not _FAQ_HINT_RE.fullmatch(cand)
                ):
                    return cand if not doc_stem else doc_stem
        return doc_stem

    @staticmethod
    def _classify_chunk(heading: str, body: str) -> Tuple[str, str]:
        combined = f"{heading}\n{body}"
        if _QA_Q_RE.match(heading) or _FAQ_HINT_RE.search(heading):
            return "常见FAQ", "faq"
        if _SCRIPT_HINT_RE.search(heading):
            return "推荐话术", "script"
        if _CAUTION_HINT_RE.search(heading):
            return "注意事项", "terminology"
        if _USAGE_HINT_RE.search(heading):
            return "使用方法与步骤", "knowledge"
        if _SELLING_HINT_RE.search(heading):
            return "核心卖点", "knowledge"

        # Content-based scoring fallback when heading is absent or generic
        if _SCRIPT_HINT_RE.search(combined):
            return "推荐话术", "script"
        if _FAQ_HINT_RE.search(combined) and ("？" in combined or "?" in combined):
            return "常见FAQ", "faq"
        caution_hits = len(_CAUTION_HINT_RE.findall(combined))
        usage_hits = len(_USAGE_HINT_RE.findall(combined))
        selling_hits = len(_SELLING_HINT_RE.findall(combined))
        if caution_hits >= max(usage_hits, selling_hits) and caution_hits > 0:
            return "注意事项", "terminology"
        if usage_hits >= selling_hits and usage_hits > 0:
            return "使用方法与步骤", "knowledge"
        return "核心卖点", "knowledge"

    @staticmethod
    def _build_keywords_and_synonyms(
        *,
        product_hint: str,
        category: str,
        title: str,
        body: str,
        kind: str,
    ) -> Tuple[List[str], List[str]]:
        kw: List[str] = []
        syn: List[str] = []
        seen_kw: set[str] = set()
        seen_syn: set[str] = set()

        def _add_kw(val: str) -> None:
            v = str(val or "").strip()
            if len(v) >= 2 and v.casefold() not in seen_kw:
                seen_kw.add(v.casefold())
                kw.append(v[:32])

        def _add_syn(val: str) -> None:
            v = str(val or "").strip()
            if len(v) >= 2 and v.casefold() not in seen_syn and v.casefold() not in seen_kw:
                seen_syn.add(v.casefold())
                syn.append(v[:36])

        if product_hint:
            _add_kw(product_hint)

        category_boosts = {
            "核心卖点": (["卖点", "核心卖点", "优势", "特点", "亮点"], ["产品优势", "有什么卖点", "怎么样"]),
            "使用方法与步骤": (["怎么使用", "使用方法", "怎么用", "使用", "步骤", "用法"], ["操作步骤", "使用指南", "怎么操作", "如何使用"]),
            "注意事项": (["注意事项", "注意", "禁忌", "参数", "规格"], ["需要注意", "风险提示", "参数规格"]),
            "常见FAQ": (["常见问题", "FAQ", "解答", "问答"], ["常见问答", "怎么解决"]),
            "推荐话术": (["客服话术", "话术", "回复", "口径"], ["推荐回复", "接待口径"]),
        }
        for tok in split_search_terms(f"{title} {body[:260]}", max_terms=6):
            _add_kw(tok)
            if len(kw) >= 5:
                break

        for k in category_boosts.get(category, ([], []))[0]:
            _add_kw(k)
        for s in category_boosts.get(category, ([], []))[1]:
            _add_syn(s)

        if kind == "faq" and title:
            _add_syn(title[:32])
        if product_hint:
            _add_syn(f"{product_hint}{category}")

        return kw[:12], syn[:8]

    def _chunk_and_structure(self, cleaned_text: str, *, doc_name: str = "") -> List[Dict[str, Any]]:
        product_hint = self._infer_product_hint(doc_name, cleaned_text)
        lines = cleaned_text.splitlines()
        has_substantive_content = any(
            ln.strip() and not _METADATA_LINE_RE.match(ln.strip())
            for ln in lines
        )

        sections: List[Tuple[str, List[str]]] = []
        cur_heading = ""
        cur_lines: List[str] = []

        def _flush() -> None:
            nonlocal cur_heading, cur_lines
            body = "\n".join(ln for ln in cur_lines if ln.strip()).strip()
            if body:
                sections.append((cur_heading.strip(), [body]))
            cur_heading = ""
            cur_lines = []

        i = 0
        while i < len(lines):
            raw_line = lines[i].strip()
            if not raw_line:
                if cur_lines and cur_lines[-1] != "":
                    cur_lines.append("")
                i += 1
                continue

            if has_substantive_content and not cur_heading and _METADATA_LINE_RE.match(raw_line):
                i += 1
                continue

            m_q = _QA_Q_RE.match(raw_line)
            if m_q:
                _flush()
                q_text = m_q.group(1).strip()
                a_parts: List[str] = []
                j = i + 1
                while j < len(lines):
                    nxt = lines[j].strip()
                    if not nxt:
                        if a_parts:
                            break
                        j += 1
                        continue
                    m_a = _QA_A_RE.match(nxt)
                    if m_a:
                        a_parts.append(m_a.group(1).strip())
                        j += 1
                        continue
                    if _QA_Q_RE.match(nxt) or _HEADING_MD_RE.match(nxt) or _HEADING_BRACKET_RE.match(nxt) or _LABEL_LINE_RE.match(nxt):
                        break
                    if a_parts:
                        a_parts.append(nxt)
                        j += 1
                    else:
                        break
                if a_parts:
                    sections.append((f"问：{q_text}", [" ".join(a_parts)]))
                    i = j
                    continue

            m_md = _HEADING_MD_RE.match(raw_line)
            if m_md:
                _flush()
                cur_heading = m_md.group(1).strip()
                i += 1
                continue

            m_brk = _HEADING_BRACKET_RE.match(raw_line)
            if m_brk:
                _flush()
                cur_heading = m_brk.group(1).strip()
                rest = m_brk.group(2).strip()
                if rest:
                    cur_lines.append(rest)
                i += 1
                continue

            m_lbl = _LABEL_LINE_RE.match(raw_line)
            if m_lbl:
                _flush()
                cur_heading = m_lbl.group(1).strip()
                rest = m_lbl.group(2).strip()
                if rest:
                    cur_lines.append(rest)
                i += 1
                continue

            m_num = _HEADING_NUM_RE.match(raw_line)
            if m_num and not raw_line.endswith(("。", ".", "！", "!", "；", ";")) and len(raw_line) <= 34:
                # Avoid splitting numbered step lines inside a usage section
                if not cur_heading or not _USAGE_HINT_RE.search(cur_heading):
                    _flush()
                    cur_heading = m_num.group(1).strip()
                    i += 1
                    continue

            cur_lines.append(re.sub(r"^[-*•]\s+", "", raw_line))
            i += 1
        _flush()

        # Fallback: split single dense prose block into sentence-level categorized chunks
        if len(sections) <= 1:
            single_text = sections[0][1][0] if sections else cleaned_text
            clauses = [c.strip() for c in re.split(r"(?<=[。！？；\n])", single_text) if c.strip()]
            non_meta_clauses = [c for c in clauses if not _METADATA_LINE_RE.match(c)]
            if non_meta_clauses:
                clauses = non_meta_clauses
            if len(clauses) >= 2:
                grouped: Dict[str, List[str]] = {}
                for clause in clauses:
                    cat, _ = self._classify_chunk("", clause)
                    grouped.setdefault(cat, []).append(clause)
                if len(grouped) >= 2:
                    sections = [(cat, [" ".join(parts)]) for cat, parts in grouped.items()]
                elif len(single_text) > 360:
                    # Break long single-category block into ~240 char readable paragraphs
                    sections = []
                    buf: List[str] = []
                    buf_len = 0
                    for clause in clauses:
                        buf.append(clause)
                        buf_len += len(clause)
                        if buf_len >= 220:
                            sections.append(("", [" ".join(buf)]))
                            buf, buf_len = [], 0
                    if buf:
                        sections.append(("", [" ".join(buf)]))

        items: List[Dict[str, Any]] = []
        seen_pairs: set[Tuple[str, str]] = set()
        for idx, (heading, body_parts) in enumerate(sections, 1):
            raw_body = re.sub(r"\s+", " ", " ".join(body_parts)).strip()
            if len(raw_body) < 4:
                continue
            if len(sections) > 1 and not heading and (
                _METADATA_LINE_RE.match(raw_body)
                or (product_hint and raw_body.strip("。：: ") == product_hint)
            ):
                continue
            category, kind = self._classify_chunk(heading, raw_body)
            clean_heading = re.sub(r"^问[：:]\s*", "", heading).strip()
            if clean_heading:
                if product_hint and product_hint not in clean_heading and len(clean_heading) <= 22:
                    title = f"{product_hint} · {clean_heading}"
                else:
                    title = clean_heading[:44]
            else:
                prefix = f"{product_hint} · " if product_hint else ""
                title = f"{prefix}{category}"[:44]

            body_trimmed = raw_body[:600].strip()
            sig = (title, body_trimmed)
            if sig in seen_pairs:
                continue
            seen_pairs.add(sig)
            kw, syn = self._build_keywords_and_synonyms(
                product_hint=product_hint,
                category=category,
                title=title,
                body=body_trimmed,
                kind=kind,
            )
            items.append({
                "id": f"draft_{len(items) + 1}",
                "selected": True,
                "category": category,
                "kind": kind,
                "title": title,
                "body": body_trimmed,
                "keywords": kw,
                "synonyms": syn,
                "confidence": 0.92 if heading else 0.85,
            })
            if len(items) >= 24:
                break
        return items

    def _refine_items_with_llm(
        self,
        cleaned_text: str,
        *,
        doc_name: str,
        instruction: str,
    ) -> Optional[List[Dict[str, Any]]]:
        models = getattr(self.engine, "models", None)
        if models is None or not hasattr(models, "is_llm_enabled") or not models.is_llm_enabled():
            return None
        snippet = cleaned_text[:4500]
        sys_prompt = (
            "你是私域客服知识工程助手。请把用户上传的产品资料拆解为结构化知识条目 JSON 数组。\n"
            "必须覆盖文档中的：核心卖点(kind=knowledge)、使用方法与步骤(kind=knowledge)、"
            "注意事项与规格参数(kind=terminology)、常见FAQ/客户话术(kind=faq或script)。\n"
            "每个元素格式严格为："
            '{"category":"核心卖点|使用方法与步骤|注意事项|常见FAQ|推荐话术",'
            '"kind":"knowledge|terminology|faq|script",'
            '"title":"简短清晰标题(含产品名,<=40字)",'
            '"body":"面向真实客户的清晰准确内容(<=400字,禁止泄露内部调试词)",'
            '"keywords":["关键词1","关键词2","关键词3"],'
            '"synonyms":["同义问法1","同义问法2"]}\n'
            "只输出纯 JSON 数组，不要输出任何额外说明文字。"
        )
        user_prompt = (
            f"资料名称：{doc_name or '未命名资料'}\n"
            f"主人指令：{instruction}\n\n"
            f"资料正文：\n{snippet}"
        )
        try:
            res = models.generate_chat_reply(
                [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.2,
                max_tokens=1600,
                timeout=8.0,
            )
        except Exception:
            return None
        if not res.get("ok") or not res.get("replyText"):
            return None
        raw_reply = str(res["replyText"]).strip()
        fence = re.search(r"```(?:json)?\s*(\[.*\])\s*```", raw_reply, flags=re.S | re.I)
        json_text = fence.group(1) if fence else raw_reply
        arr_m = re.search(r"\[.*\]", json_text, flags=re.S)
        if not arr_m:
            return None
        try:
            parsed = json.loads(arr_m.group(0))
        except Exception:
            return None
        if not isinstance(parsed, list):
            return None

        refined: List[Dict[str, Any]] = []
        for idx, entry in enumerate(parsed[:20], 1):
            if not isinstance(entry, dict):
                continue
            title = _scrub_internal_terms(str(entry.get("title") or "").strip())[:48]
            body = _scrub_internal_terms(str(entry.get("body") or "").strip())[:600]
            if not title or len(body) < 4:
                continue
            try:
                _guard_secrets(title, body)
            except ValueError:
                continue
            raw_kind = str(entry.get("kind") or "knowledge").strip().lower()
            kind = raw_kind if raw_kind in KINDS else "knowledge"
            category = str(entry.get("category") or "").strip() or (
                "注意事项" if kind == "terminology" else ("常见FAQ" if kind == "faq" else ("推荐话术" if kind == "script" else "核心卖点"))
            )
            kws = [str(k).strip()[:32] for k in (entry.get("keywords") or []) if str(k).strip()][:10]
            syns = [str(s).strip()[:36] for s in (entry.get("synonyms") or []) if str(s).strip()][:6]
            if not kws:
                kws = split_search_terms(f"{title} {body}", max_terms=8)
            refined.append({
                "id": f"draft_{idx}",
                "selected": True,
                "category": category,
                "kind": kind,
                "title": title,
                "body": body,
                "keywords": kws,
                "synonyms": syns,
                "confidence": 0.95,
            })
        return refined or None

    def preview(
        self,
        *,
        raw_text: str = "",
        file_path: Optional[str | Path] = None,
        file_bytes_b64: Optional[str] = None,
        filename: str = "",
        instruction: str = "希望你能够替代我去和顾客聊天",
        doc_name: str = "",
        use_llm: Optional[bool] = None,
        max_pages: int = 12,
    ) -> Dict[str, Any]:
        clean_instruction = re.sub(r"\s+", " ", str(instruction or "")).strip() or "希望你能够替代我去和顾客聊天"
        resolved_doc_name = str(doc_name or "").strip()
        source_type = "raw_text"
        page_count: Optional[int] = None
        processed_pages: Optional[int] = None
        truncated = False
        extracted_text = ""

        temp_file_to_clean: Optional[Path] = None
        try:
            if file_path is not None and str(file_path).strip():
                p = Path(str(file_path).strip()).expanduser()
                if not resolved_doc_name:
                    resolved_doc_name = p.name
                ext_res = self._extract_text_from_file(p, max_pages=max_pages)
                if not ext_res.get("ok"):
                    return ext_res
                extracted_text = str(ext_res.get("text") or "").strip()
                source_type = str(ext_res.get("sourceType") or "file")
                page_count = ext_res.get("pageCount")
                processed_pages = ext_res.get("processedPages")
                truncated = bool(ext_res.get("truncated", False))
            elif file_bytes_b64 is not None and str(file_bytes_b64).strip():
                try:
                    temp_file_to_clean, orig_name = self._decode_b64_to_managed_file(file_bytes_b64, filename)
                except ValueError as exc:
                    return {"ok": False, "error_code": "invalid_upload", "error": str(exc)}
                if not resolved_doc_name:
                    resolved_doc_name = orig_name
                ext_res = self._extract_text_from_file(temp_file_to_clean, max_pages=max_pages)
                if not ext_res.get("ok"):
                    return ext_res
                extracted_text = str(ext_res.get("text") or "").strip()
                source_type = str(ext_res.get("sourceType") or "file")
                page_count = ext_res.get("pageCount")
                processed_pages = ext_res.get("processedPages")
                truncated = bool(ext_res.get("truncated", False))
        finally:
            if temp_file_to_clean is not None:
                try:
                    temp_file_to_clean.unlink(missing_ok=True)
                except OSError:
                    pass

        pasted = str(raw_text or "").strip()
        if extracted_text and pasted and pasted not in extracted_text:
            combined_raw = f"{extracted_text}\n\n{pasted}"
        else:
            combined_raw = extracted_text or pasted

        cleaned = self._clean_doc_text(combined_raw)
        if not cleaned:
            return {
                "ok": False,
                "error_code": "empty_document",
                "error": "未提取到有效产品资料文本，请上传清晰的文档或粘贴产品介绍内容。",
            }

        try:
            _guard_secrets(cleaned)
        except ValueError as exc:
            return {"ok": False, "error_code": "secret_rejected", "error": str(exc)}

        product_hint = self._infer_product_hint(resolved_doc_name, cleaned)
        chunk_doc_hint = product_hint or resolved_doc_name
        if not resolved_doc_name:
            resolved_doc_name = product_hint or "产品资料"
        elif not str(doc_name or "").strip() and product_hint and product_hint not in resolved_doc_name:
            resolved_doc_name = f"{product_hint}（{resolved_doc_name}）"

        extraction_mode = "rule_chunker"
        items: Optional[List[Dict[str, Any]]] = None
        if use_llm is not False:
            items = self._refine_items_with_llm(
                cleaned,
                doc_name=chunk_doc_hint or resolved_doc_name,
                instruction=clean_instruction,
            )
            if items:
                extraction_mode = "llm_structured"

        if not items:
            items = self._chunk_and_structure(cleaned, doc_name=chunk_doc_hint)

        if not items:
            return {
                "ok": False,
                "error_code": "no_knowledge_items",
                "error": "未能从该资料中拆解出有效的知识条目，请补充产品说明或问答。",
            }

        cat_counts: Dict[str, int] = {}
        for it in items:
            c = str(it.get("category") or "产品知识")
            cat_counts[c] = cat_counts.get(c, 0) + 1
        cat_summary = "、".join(f"{k} {v} 条" for k, v in cat_counts.items())

        selling_items = [it for it in items if it.get("category") in ("核心卖点", "使用方法与步骤")][:2]
        selling_snippet = "；".join(str(it.get("body") or "")[:45] for it in selling_items)
        prompt_preview = (
            f"围绕《{resolved_doc_name}》接待顾客咨询，重点传达：{selling_snippet}"
            if selling_snippet
            else f"围绕《{resolved_doc_name}》接待顾客咨询，{clean_instruction}"
        )[:180]

        confirm_card = {
            "title": "确认执行任务 · 绑进知识库",
            "summary": (
                f"已将《{resolved_doc_name}》拆解为 {len(items)} 条结构化知识（{cat_summary}），"
                "推荐绑进共享知识库：保持现有营销人设不变，AI 回复精准按产品资料作答。"
            ),
            "itemCount": len(items),
            "strategy": "bind_kb",
            "confirmLabel": "确认",
            "cancelLabel": "继续修改",
        }

        return {
            "ok": True,
            "docName": resolved_doc_name,
            "sourceType": source_type,
            "instruction": clean_instruction,
            "extractedTextLength": len(cleaned),
            "extractedPreview": cleaned[:400],
            "pageCount": page_count,
            "processedPages": processed_pages,
            "truncated": truncated,
            "extractionMode": extraction_mode,
            "items": items,
            "itemCount": len(items),
            "recommendedStrategy": "bind_kb",
            "strategyOptions": [dict(opt) for opt in STRATEGY_OPTIONS],
            "confirmCard": confirm_card,
            "promptDraftPreview": prompt_preview,
        }

    def confirm(
        self,
        items: Optional[List[Dict[str, Any]]] = None,
        *,
        strategy: str = "bind_kb",
        doc_name: str = "",
        apply_prompt_target: bool = False,
        instruction: str = "",
    ) -> Dict[str, Any]:
        clean_strategy = str(strategy or "bind_kb").strip().lower()
        if clean_strategy not in ("bind_kb", "merge_prompt"):
            return {
                "ok": False,
                "error_code": "unsupported_strategy",
                "error": f"不支持的执行策略 {strategy!r}，请选择 bind_kb 或 merge_prompt。",
            }

        raw_items = list(items or [])
        selected_items = [
            it for it in raw_items
            if isinstance(it, dict) and bool(it.get("selected", True))
        ]
        if not selected_items:
            return {
                "ok": False,
                "error_code": "no_items_selected",
                "error": "请至少勾选一条知识草稿后再确认入库。",
            }

        clean_doc_name = re.sub(r"\s+", " ", str(doc_name or "")).strip()[:60] or "上传产品资料"
        saved_entries: List[Dict[str, Any]] = []
        entry_ids: List[str] = []

        for it in selected_items:
            title = _scrub_internal_terms(str(it.get("title") or "").strip())[:64]
            body = _scrub_internal_terms(str(it.get("body") or "").strip())[:1000]
            if not title or not body:
                continue
            raw_kind = str(it.get("kind") or "knowledge").strip().lower()
            kind = raw_kind if raw_kind in KINDS else "knowledge"
            raw_kw = it.get("keywords")
            kw_list: List[str] = (
                [str(k).strip() for k in raw_kw if str(k).strip()]
                if isinstance(raw_kw, Iterable) and not isinstance(raw_kw, (str, bytes))
                else []
            )
            if clean_doc_name and clean_doc_name != "上传产品资料":
                stem = re.sub(r"[（(].*$", "", Path(clean_doc_name).stem).strip()
                if stem and stem not in kw_list and stem.casefold() not in {k.casefold() for k in kw_list}:
                    kw_list.insert(0, stem[:32])
            if not kw_list:
                kw_list = split_search_terms(f"{title} {body}", max_terms=8)

            raw_syn = it.get("synonyms")
            syn_list: List[str] = (
                [str(s).strip() for s in raw_syn if str(s).strip()]
                if isinstance(raw_syn, Iterable) and not isinstance(raw_syn, (str, bytes))
                else []
            )
            try:
                saved = self.engine.knowledge.save_entry(
                    title=title,
                    body=body,
                    kind=kind,
                    library="shared",
                    keywords=kw_list[:12],
                    synonyms=syn_list[:8],
                    source="doc-ingest",
                    external=True,
                    status="published",
                )
            except ValueError as exc:
                return {"ok": False, "error_code": "save_entry_failed", "error": str(exc)}

            entry = saved.get("entry") or {}
            saved_entries.append(entry)
            if entry.get("id"):
                entry_ids.append(str(entry["id"]))

        if not saved_entries:
            return {
                "ok": False,
                "error_code": "no_valid_items",
                "error": "勾选的知识条目标题或正文为空，未写入知识库。",
            }

        prompt_updated = False
        updated_task_goal: Optional[str] = None
        if clean_strategy == "merge_prompt" or bool(apply_prompt_target):
            highlights = [
                str(e.get("body") or "")[:45]
                for e in saved_entries[:2]
                if str(e.get("body") or "").strip()
            ]
            instr_note = re.sub(r"\s+", " ", str(instruction or "")).strip()[:40]
            goal_parts = [f"围绕《{clean_doc_name}》接待咨询"]
            if highlights:
                goal_parts.append("核心要点：" + "；".join(highlights))
            elif instr_note:
                goal_parts.append(instr_note)
            proposed_goal = "，".join(goal_parts)[:180]
            post_res = self.engine.configure_workos_post(task_goal=proposed_goal)
            if post_res.get("ok"):
                prompt_updated = True
                updated_task_goal = post_res.get("taskGoal")

        kb_count = int(
            (self.engine.knowledge.list_entries(include_drafts=False, limit=1) or {}).get("count")
            or len(saved_entries)
        )
        self.engine.audit.log(
            "doc_ingest_confirm",
            "ok",
            {
                "docName": clean_doc_name,
                "strategy": clean_strategy,
                "savedCount": len(saved_entries),
                "promptUpdated": prompt_updated,
            },
        )
        return {
            "ok": True,
            "strategy": clean_strategy,
            "docName": clean_doc_name,
            "savedCount": len(saved_entries),
            "entryIds": entry_ids,
            "entries": saved_entries,
            "promptUpdated": prompt_updated,
            "updatedTaskGoal": updated_task_goal,
            "knowledgeEntriesCount": kb_count,
        }
