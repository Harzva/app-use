"""Multimodal Link, Image/Article Card, and Video Deep Reader (2x Vision OCR + DeepSeek Flash)."""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .article_exporter import DEFAULT_WECHAT_UA, _read_bounded_response, _validate_safe_http_url
from .io_utils import atomic_write_json

if TYPE_CHECKING:
    from .engine import WeChatControlEngine


DEFAULT_VISION_MODEL_ID = "auto/deepseek-v4.1-flash"
MAX_WEB_BYTES = 8 * 1024 * 1024


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _GenericPageHTMLParser(HTMLParser):
    """Lightweight stdlib HTML parser extracting title, meta tags, hero image, and clean body text."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}
    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "blockquote",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "tr",
        "br",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title = ""
        self.meta: Dict[str, str] = {}
        self.images: List[str] = []
        self.paragraphs: List[str] = []
        self._buf: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs if k}
        if t in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if t == "title":
            self._in_title = True
        elif t == "meta":
            key = (attr_map.get("property") or attr_map.get("name") or "").strip().lower()
            val = html_lib.unescape((attr_map.get("content") or "").strip())
            if key and val:
                self.meta[key] = val
        elif t == "img":
            src = (attr_map.get("src") or attr_map.get("data-src") or "").strip()
            if src and not src.startswith("data:"):
                self.images.append(html_lib.unescape(src))
        elif t in self.BLOCK_TAGS:
            self._flush_buf()

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if t == "title":
            self._in_title = False
        elif t in self.BLOCK_TAGS and self._skip_depth == 0:
            self._flush_buf()

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title += data
            return
        cleaned = re.sub(r"\s+", " ", data).strip()
        if cleaned:
            self._buf.append(cleaned)

    def _flush_buf(self) -> None:
        if self._buf:
            line = " ".join(self._buf).strip()
            self._buf.clear()
            if len(line) >= 2 and (not self.paragraphs or self.paragraphs[-1] != line):
                self.paragraphs.append(line)


def _extract_json_block(raw_text: str) -> Optional[Dict[str, Any]]:
    text = (raw_text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None


class WeChatMediaLinkAnalyzer:
    """Deep reader & multimodal analyzer for WeChat links, image/article cards, and videos."""

    def __init__(self, engine: "WeChatControlEngine") -> None:
        self.engine = engine
        self.analysis_dir = self.engine.inspector.reports_dir / "media_analyses"
        self.analysis_log = self.engine.inspector.reports_dir / "media_link_analyses.jsonl"
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.analysis_log.parent.mkdir(parents=True, exist_ok=True)

    def _record_analysis(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            "ts": _utc_iso_now(),
            "analysisId": payload.get("analysisId"),
            "kind": payload.get("kind"),
            "contact": payload.get("contact", ""),
            "title": payload.get("title", ""),
            "url": payload.get("url", ""),
            "modelId": payload.get("modelId", DEFAULT_VISION_MODEL_ID),
            "ocrCount": payload.get("ocrCount", 0),
            "summary": payload.get("summary", ""),
            "friendIntent": payload.get("friendIntent", ""),
            "recommendedReply": payload.get("recommendedReply", ""),
            "artifactPath": payload.get("artifactPath", ""),
        }
        try:
            with self.analysis_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(compact, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return payload

    def list_recent_analyses(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.analysis_log.exists():
            return []
        try:
            lines = [ln.strip() for ln in self.analysis_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
            out: List[Dict[str, Any]] = []
            for ln in reversed(lines[-max(1, int(limit)) :]):
                try:
                    item = json.loads(ln)
                    if isinstance(item, dict):
                        out.append(item)
                except Exception:
                    continue
            return out
        except Exception:
            return []

    def _run_2x_ocr(self, image_path: Path, *, min_upscale_width: int = 900) -> Dict[str, Any]:
        """Run macOS Apple Vision OCR on an image, auto-upscaling crops with sips for tiny text."""
        path = Path(image_path)
        if not path.is_file():
            return {"ok": False, "error": f"Image file not found: {path}", "elements": [], "text": ""}

        res1 = self.engine._run_native(["ocr", "--image", str(path)], 15.0)
        els1 = res1.get("elements") or []
        img_w = int(res1.get("imageWidth") or 0)
        img_h = int(res1.get("imageHeight") or 0)

        # Force 2x super-resolution when source image width < min_upscale_width (e.g. cropped chat thumbnails)
        best = res1
        if res1.get("ok") and not res1.get("upscaled2x") and 0 < max(img_w, img_h) < min_upscale_width * 2:
            up_path = self.analysis_dir / f"{path.stem}_2x.png"
            target_dim = min(2600, max(img_w, img_h) * 2)
            try:
                proc = subprocess.run(
                    ["/usr/bin/sips", "-Z", str(target_dim), str(path), "--out", str(up_path)],
                    capture_output=True,
                    timeout=6.0,
                )
                if proc.returncode == 0 and up_path.is_file():
                    res2 = self.engine._run_native(["ocr", "--image", str(up_path)], 15.0)
                    els2 = res2.get("elements") or []
                    if res2.get("ok") and len(els2) >= len(els1):
                        res2["upscaled2x"] = True
                        res2["upscaledPath"] = str(up_path)
                        best = res2
            except Exception:
                pass

        elements = best.get("elements") or []
        text = "\n".join(str(el.get("text") or "").strip() for el in elements if str(el.get("text") or "").strip())
        return {
            "ok": bool(best.get("ok")),
            "imagePath": str(path),
            "upscaledPath": best.get("upscaledPath"),
            "upscaled2x": bool(best.get("upscaled2x")),
            "imageWidth": best.get("imageWidth", img_w),
            "imageHeight": best.get("imageHeight", img_h),
            "count": len(elements),
            "elements": elements,
            "text": text,
        }

    def _synthesize_with_deepseek(
        self,
        *,
        kind: str,
        title: str,
        ocr_text: str,
        body_text: str = "",
        image_paths: Optional[List[Path]] = None,
        contact: str = "",
        context_text: str = "",
        url: str = "",
        model_id: str = DEFAULT_VISION_MODEL_ID,
    ) -> Dict[str, Any]:
        prompt = (
            f"分析对象类型: {kind}\n"
            f"来源好友: {contact or '未知好友'}\n"
            f"标题/窗口: {title or '未命名'}\n"
            f"链接: {url or '无'}\n"
            f"聊天附言上下文: {context_text or '无'}\n"
            f"正文或元信息摘录:\n{(body_text or '无')[:2200]}\n\n"
            "请严格输出 JSON（不要多余解释），包含以下字段：\n"
            "{\n"
            '  "summary": "用2-4句清晰总结这条链接/图文/视频的核心内容与关键事实",\n'
            '  "keyPoints": ["要点1", "要点2", "要点3"],\n'
            '  "friendIntent": "好友发送此内容的真实意图、需求或隐含指令",\n'
            '  "actionPlan": "我方/绑定智能体应该执行什么具体动作",\n'
            '  "recommendedReply": "可以直接发给该好友的简练自然微信回复（<=120字）"\n'
            "}"
        )
        llm_res = self.engine.models.analyze_multimodal(
            prompt=prompt,
            image_paths=image_paths,
            ocr_context=ocr_text,
            contact_name=contact or None,
            model_id=model_id or DEFAULT_VISION_MODEL_ID,
            max_tokens=900,
            temperature=0.2,
            timeout=25.0,
        )
        raw_reply = str(llm_res.get("replyText") or "").strip()
        parsed = _extract_json_block(raw_reply) if raw_reply else None

        if parsed:
            return {
                "ok": bool(llm_res.get("ok")),
                "modelId": llm_res.get("modelId", model_id),
                "usedMultimodalImage": bool(llm_res.get("usedMultimodalImage")),
                "usedTextFallbackOnVisionError": bool(llm_res.get("usedTextFallbackOnVisionError")),
                "latencyMs": llm_res.get("latencyMs"),
                "summary": str(parsed.get("summary") or raw_reply[:240]).strip(),
                "keyPoints": list(parsed.get("keyPoints") or [])[:5],
                "friendIntent": str(parsed.get("friendIntent") or "").strip(),
                "actionPlan": str(parsed.get("actionPlan") or "").strip(),
                "recommendedReply": str(parsed.get("recommendedReply") or "").strip(),
                "rawLlmText": raw_reply,
            }

        # Clean fallback if gateway is unreachable or returns plain text
        snippet_lines = [ln.strip() for ln in (body_text or ocr_text).splitlines() if ln.strip()][:5]
        fallback_summary = raw_reply or (
            f"已提取 {kind}「{title or url or '媒体内容'}」，"
            + (f"核心文本：{' / '.join(snippet_lines)[:180]}" if snippet_lines else "已完成 OCR 与结构化解析。")
        )
        return {
            "ok": bool(llm_res.get("ok")),
            "modelId": llm_res.get("modelId", model_id),
            "usedMultimodalImage": bool(llm_res.get("usedMultimodalImage")),
            "usedTextFallbackOnVisionError": bool(llm_res.get("usedTextFallbackOnVisionError")),
            "latencyMs": llm_res.get("latencyMs"),
            "error": llm_res.get("error", ""),
            "summary": fallback_summary,
            "keyPoints": snippet_lines[:3],
            "friendIntent": f"{contact or '好友'}分享了{kind}，希望我们理解内容并给与反馈或执行后续指令。",
            "actionPlan": f"结合正文/OCR 提取结论回复 {contact or '好友'} 或触发绑定智能体处理。",
            "recommendedReply": f"看完你发的「{title or '内容'}」啦，重点我这边已经梳理清楚，下一步按你的节奏推进～",
            "rawLlmText": raw_reply,
        }

    def analyze_link(
        self,
        url: str,
        *,
        contact: str = "",
        context_text: str = "",
        model_id: str = DEFAULT_VISION_MODEL_ID,
        allow_loopback: bool = False,
        html_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch/open a URL sent by a WeChat contact, run OCR on hero image if any, and summarize via DeepSeek Flash."""
        clean_url = (url or "").strip()
        if clean_url and "://" not in clean_url and "." in clean_url:
            clean_url = "https://" + clean_url
        if not html_override:
            safe_ok, reason = _validate_safe_http_url(clean_url, allow_loopback=allow_loopback)
            if not safe_ok:
                return {"ok": False, "error_code": "invalid_or_blocked_url", "error": reason, "url": clean_url}

        parsed_url = urllib.parse.urlsplit(clean_url)
        host = (parsed_url.hostname or "").lower()
        analysis_id = f"link_{hashlib.sha1(clean_url.encode('utf-8')).hexdigest()[:10]}_{int(time.time())}"

        if host.endswith("mp.weixin.qq.com") and not html_override:
            exp = self.engine.article_exporter.export_from_url(
                clean_url,
                download_images=True,
            )
            if exp.get("ok"):
                md_text = ""
                md_path = exp.get("markdown_path")
                if md_path and Path(md_path).is_file():
                    md_text = Path(md_path).read_text(encoding="utf-8", errors="replace")
                img_ocr_chunks: List[str] = []
                hero_paths: List[Path] = []
                for p_str in (exp.get("local_images") or [])[:2]:
                    p_obj = Path(p_str)
                    if p_obj.is_file():
                        hero_paths.append(p_obj)
                        ocr_res = self._run_2x_ocr(p_obj)
                        if ocr_res.get("text"):
                            img_ocr_chunks.append(ocr_res["text"])
                ocr_combined = "\n".join(img_ocr_chunks)
                llm = self._synthesize_with_deepseek(
                    kind="wechat_article",
                    title=str(exp.get("title") or clean_url),
                    ocr_text=ocr_combined,
                    body_text=md_text,
                    image_paths=hero_paths,
                    contact=contact,
                    context_text=context_text,
                    url=clean_url,
                    model_id=model_id,
                )
                result = {
                    "ok": True,
                    "analysisId": analysis_id,
                    "kind": "wechat_article",
                    "contentType": "article",
                    "url": clean_url,
                    "contact": contact,
                    "title": exp.get("title") or clean_url,
                    "markdownPath": md_path,
                    "downloadedImages": [str(p) for p in hero_paths],
                    "ocrCount": sum(1 for ln in ocr_combined.splitlines() if ln.strip()),
                    "ocrText": ocr_combined,
                    "bodyExcerpt": md_text[:1500],
                    **llm,
                }
                art_path = self.analysis_dir / f"{analysis_id}.json"
                atomic_write_json(art_path, result, newline=False)
                result["artifactPath"] = str(art_path)
                return self._record_analysis(result)

        # Generic URL fetch (YoBot, GitHub repo, documentation, web apps)
        raw_html = html_override or ""
        fetch_status = 200
        fetch_error = ""
        if not raw_html:
            try:
                req = urllib.request.Request(
                    clean_url,
                    headers={
                        "User-Agent": DEFAULT_WECHAT_UA,
                        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    },
                )
                with urllib.request.urlopen(req, timeout=12.0) as resp:
                    fetch_status = getattr(resp, "status", 200)
                    raw_bytes = _read_bounded_response(resp, MAX_WEB_BYTES)
                    raw_html = raw_bytes.decode("utf-8", errors="replace")
            except Exception as exc:
                fetch_error = str(exc)
                fetch_status = 0

        content_type = "github_repo" if "github.com" in host else "webapp"
        title = clean_url
        description = ""
        body_excerpt = ""
        hero_images: List[Path] = []
        ocr_combined = ""

        if raw_html:
            parser = _GenericPageHTMLParser()
            try:
                parser.feed(raw_html)
            except Exception:
                pass
            title = html_lib.unescape(
                parser.meta.get("og:title") or parser.title or clean_url
            ).strip()
            description = (
                parser.meta.get("og:description")
                or parser.meta.get("description")
                or ""
            ).strip()
            paragraphs = []
            if description:
                paragraphs.append(f"[Meta摘要] {description}")
            paragraphs.extend(parser.paragraphs[:45])
            body_excerpt = "\n".join(paragraphs)[:4000]

            # Download og:image or primary image (if safe http(s) URL) to inspect visually / via OCR
            candidate_imgs: List[str] = []
            if parser.meta.get("og:image"):
                candidate_imgs.append(parser.meta["og:image"])
            candidate_imgs.extend(parser.images[:2])
            for idx, raw_img in enumerate(candidate_imgs[:2]):
                resolved_img = urllib.parse.urljoin(clean_url, raw_img)
                ok_img, _ = _validate_safe_http_url(resolved_img, allow_loopback=allow_loopback)
                if not ok_img:
                    continue
                try:
                    ireq = urllib.request.Request(resolved_img, headers={"User-Agent": DEFAULT_WECHAT_UA})
                    with urllib.request.urlopen(ireq, timeout=8.0) as iresp:
                        ibytes = _read_bounded_response(iresp, 5 * 1024 * 1024)
                        if len(ibytes) > 256 and not ibytes.lstrip().startswith(b"<svg"):
                            img_file = self.analysis_dir / f"{analysis_id}_hero_{idx}.png"
                            img_file.write_bytes(ibytes)
                            hero_images.append(img_file)
                except Exception:
                    continue

        if hero_images:
            ocr_parts: List[str] = []
            for hp in hero_images:
                ocr_res = self._run_2x_ocr(hp)
                if ocr_res.get("text"):
                    ocr_parts.append(ocr_res["text"])
            ocr_combined = "\n".join(ocr_parts)

        # If page is a pure JS SPA shell or fetch failed temporarily, pass context honestly
        if not body_excerpt and description:
            body_excerpt = description
        if not body_excerpt and fetch_error:
            body_excerpt = f"网页抓取遇到网络限制或需要浏览器渲染 ({fetch_error})；请结合 URL 结构与好友上下文给出保守分析。"

        llm = self._synthesize_with_deepseek(
            kind=content_type,
            title=title,
            ocr_text=ocr_combined,
            body_text=body_excerpt,
            image_paths=hero_images,
            contact=contact,
            context_text=context_text,
            url=clean_url,
            model_id=model_id,
        )

        result = {
            "ok": bool(raw_html) or bool(llm.get("ok")),
            "analysisId": analysis_id,
            "kind": "link",
            "contentType": content_type,
            "url": clean_url,
            "fetchStatus": fetch_status,
            "fetchError": fetch_error,
            "contact": contact,
            "title": title,
            "description": description,
            "heroImages": [str(p) for p in hero_images],
            "ocrCount": sum(1 for ln in ocr_combined.splitlines() if ln.strip()),
            "ocrText": ocr_combined,
            "bodyExcerpt": body_excerpt[:1800],
            **llm,
        }
        art_path = self.analysis_dir / f"{analysis_id}.json"
        atomic_write_json(art_path, result, newline=False)
        result["artifactPath"] = str(art_path)
        return self._record_analysis(result)

    def analyze_image_or_card(
        self,
        *,
        image_path: Optional[Path] = None,
        crop_region: Optional[Dict[str, int]] = None,
        from_viewer_window: bool = False,
        source_snapshot: Optional[Path] = None,
        window_title: str = "图片和视频",
        contact: str = "",
        context_text: str = "",
        model_id: str = DEFAULT_VISION_MODEL_ID,
    ) -> Dict[str, Any]:
        """Inspect a standalone image, cropped chat thumbnail/card, or open WeChat media viewer window."""
        analysis_id = f"img_{int(time.time() * 1000)}"
        target_image: Optional[Path] = None
        ocr_info: Dict[str, Any] = {"elements": [], "text": "", "count": 0}
        source_mode = "image_path"

        if from_viewer_window:
            source_mode = "wechat_viewer_window"
            snap_out = self.analysis_dir / f"{analysis_id}_viewer.png"
            cap = self.engine._run_native(
                ["capture-ocr", "--window-title", window_title or "图片和视频", "--out", str(snap_out)],
                15.0,
            )
            if not cap.get("ok"):
                # Fall back to capturing main WeChat window if viewer window was closed
                cap = self.engine._run_native(["capture-ocr", "--out", str(snap_out)], 15.0)
                source_mode = "wechat_main_window_fallback"
            if not cap.get("ok"):
                return {
                    "ok": False,
                    "error_code": cap.get("error_code", "viewer_capture_failed"),
                    "error": cap.get("error", "Failed to capture WeChat viewer window."),
                }
            target_image = snap_out
            els = cap.get("elements") or []
            ocr_info = {
                "ok": True,
                "imagePath": str(snap_out),
                "upscaled2x": bool(cap.get("upscaled2x")),
                "count": len(els),
                "elements": els,
                "text": "\n".join(str(e.get("text") or "").strip() for e in els if str(e.get("text") or "").strip()),
                "windowTitle": cap.get("windowTitle", ""),
            }
        elif crop_region is not None:
            source_mode = "cropped_chat_region"
            base_snap = Path(source_snapshot) if source_snapshot else (self.engine.inspector.snapshots_dir / "monitor_poll_cur.png")
            if not base_snap.is_file():
                cap = self.engine._run_native(["capture-ocr", "--out", str(base_snap)], 15.0)
                if not cap.get("ok"):
                    return {"ok": False, "error": "Unable to obtain snapshot for cropping."}
            x = int(crop_region.get("x", 0))
            y = int(crop_region.get("y", 0))
            w = max(16, int(crop_region.get("width", 400)))
            h = max(16, int(crop_region.get("height", 400)))
            crop_out = self.analysis_dir / f"{analysis_id}_crop.png"
            crop_res = self.engine._run_native(
                ["ocr", "--image", str(base_snap), "--crop", f"{x},{y},{w},{h}", "--out", str(crop_out)],
                15.0,
            )
            if not crop_res.get("ok"):
                return {"ok": False, "error": crop_res.get("error", "Crop OCR failed.")}
            target_image = crop_out
            ocr_info = self._run_2x_ocr(crop_out, min_upscale_width=1000)
        elif image_path is not None:
            target_image = Path(image_path)
            if not target_image.is_file():
                return {"ok": False, "error_code": "file_not_found", "error": f"Image not found: {target_image}"}
            ocr_info = self._run_2x_ocr(target_image)
        else:
            return {"ok": False, "error": "Provide image_path, crop_region, or from_viewer_window=True."}

        img_list = [target_image] if target_image and target_image.is_file() else []
        if ocr_info.get("upscaledPath") and Path(str(ocr_info["upscaledPath"])).is_file():
            img_list = [Path(str(ocr_info["upscaledPath"]))]

        title = f"{contact or '微信'} 图文/图片解析 ({source_mode})"
        llm = self._synthesize_with_deepseek(
            kind="image_or_card",
            title=title,
            ocr_text=str(ocr_info.get("text") or ""),
            body_text=f"图片尺寸: {ocr_info.get('imageWidth')}x{ocr_info.get('imageHeight')} | 2x超分: {ocr_info.get('upscaled2x')}",
            image_paths=img_list,
            contact=contact,
            context_text=context_text,
            model_id=model_id,
        )

        result = {
            "ok": True,
            "analysisId": analysis_id,
            "kind": "image_or_card",
            "sourceMode": source_mode,
            "contact": contact,
            "title": title,
            "imagePath": str(target_image) if target_image else None,
            "upscaledPath": ocr_info.get("upscaledPath"),
            "upscaled2x": bool(ocr_info.get("upscaled2x")),
            "imageWidth": ocr_info.get("imageWidth"),
            "imageHeight": ocr_info.get("imageHeight"),
            "ocrCount": int(ocr_info.get("count") or 0),
            "ocrText": str(ocr_info.get("text") or ""),
            **llm,
        }
        art_path = self.analysis_dir / f"{analysis_id}.json"
        atomic_write_json(art_path, result, newline=False)
        result["artifactPath"] = str(art_path)
        return self._record_analysis(result)

    def _extract_local_video_frames(self, video_path: Path, out_dir: Path, *, frame_count: int = 3) -> Tuple[List[Dict[str, Any]], str, float]:
        out_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg_bin = shutil.which("ffmpeg")
        frames: List[Dict[str, Any]] = []
        duration_sec = 0.0
        method = "none"

        # 1. Try native AVFoundation extractor inside wechat-vision-ax first (fast, zero-dependency, evenly spaced)
        ax_res = self.engine._run_native(
            ["extract-video-frames", "--video", str(video_path), "--out-dir", str(out_dir), "--count", str(frame_count)],
            20.0,
        )
        if ax_res.get("ok") and ax_res.get("frames"):
            duration_sec = float(ax_res.get("durationSeconds") or 0.0)
            return list(ax_res["frames"]), "avfoundation_keyframe", duration_sec

        # 2. Try ffmpeg if installed
        if ffmpeg_bin:
            try:
                proc = subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-i",
                        str(video_path),
                        "-vf",
                        "fps=1",
                        "-frames:v",
                        str(max(1, frame_count)),
                        str(out_dir / "ff_%02d.png"),
                    ],
                    capture_output=True,
                    timeout=25.0,
                )
                if proc.returncode == 0:
                    for idx, p in enumerate(sorted(out_dir.glob("ff_*.png")), start=1):
                        frames.append({"index": idx, "timestampSeconds": float(idx - 1), "path": str(p)})
                    if frames:
                        return frames, "ffmpeg", duration_sec
            except Exception:
                pass

        # 3. Fallback to macOS QuickLook thumbnailer (`qlmanage -t`)
        ql_bin = shutil.which("qlmanage") or "/usr/bin/qlmanage"
        if Path(ql_bin).exists():
            try:
                proc = subprocess.run(
                    [ql_bin, "-t", "-s", "1024", "-o", str(out_dir), str(video_path)],
                    capture_output=True,
                    timeout=10.0,
                )
                if proc.returncode == 0:
                    thumbs = sorted(out_dir.glob("*.png"))
                    for idx, tp in enumerate(thumbs[:frame_count], start=1):
                        frames.append({"index": idx, "timestampSeconds": 0.0, "path": str(tp)})
                    if frames:
                        return frames, "qlmanage_thumbnail", duration_sec
            except Exception:
                pass

        return frames, method, duration_sec

    def analyze_video(
        self,
        *,
        video_path: Optional[Path] = None,
        video_url: Optional[str] = None,
        from_viewer_window: bool = False,
        window_title: str = "图片和视频",
        contact: str = "",
        context_text: str = "",
        frame_count: int = 3,
        model_id: str = DEFAULT_VISION_MODEL_ID,
    ) -> Dict[str, Any]:
        """Extract video keyframes (AVFoundation/ffmpeg/qlmanage or live window burst), OCR subtitles, and summarize via DeepSeek Flash."""
        analysis_id = f"vid_{int(time.time() * 1000)}"
        frames_dir = self.analysis_dir / analysis_id
        frames_dir.mkdir(parents=True, exist_ok=True)
        resolved_video: Optional[Path] = Path(video_path) if video_path else None
        download_note = ""

        if video_url and not resolved_video:
            ok_u, reason = _validate_safe_http_url(video_url, allow_loopback=False)
            if not ok_u:
                return {"ok": False, "error_code": "invalid_video_url", "error": reason}
            try:
                req = urllib.request.Request(video_url, headers={"User-Agent": DEFAULT_WECHAT_UA})
                with urllib.request.urlopen(req, timeout=20.0) as resp:
                    ctype = str(resp.headers.get("Content-Type") or "").lower()
                    data = _read_bounded_response(resp, 60 * 1024 * 1024)
                    if "text/html" in ctype:
                        return self.analyze_link(
                            video_url,
                            contact=contact,
                            context_text=context_text,
                            model_id=model_id,
                            html_override=data.decode("utf-8", errors="replace"),
                        )
                    dl_path = frames_dir / "source_video.mp4"
                    dl_path.write_bytes(data)
                    resolved_video = dl_path
            except Exception as exc:
                download_note = f"视频直链下载失败: {exc}"

        extracted_frames: List[Dict[str, Any]] = []
        extract_method = "none"
        duration_sec = 0.0

        if resolved_video is not None and resolved_video.is_file():
            extracted_frames, extract_method, duration_sec = self._extract_local_video_frames(
                resolved_video,
                frames_dir,
                frame_count=frame_count,
            )
        elif from_viewer_window:
            extract_method = "wechat_viewer_burst"
            cnt = max(1, min(4, int(frame_count)))
            for idx in range(cnt):
                out_f = frames_dir / f"burst_{idx + 1:02d}.png"
                cap = self.engine._run_native(
                    ["capture-ocr", "--window-title", window_title or "图片和视频", "--out", str(out_f)],
                    12.0,
                )
                if not cap.get("ok"):
                    cap = self.engine._run_native(["capture-ocr", "--out", str(out_f)], 12.0)
                    extract_method = "wechat_window_burst_fallback"
                if cap.get("ok") and out_f.is_file():
                    extracted_frames.append(
                        {
                            "index": idx + 1,
                            "timestampSeconds": round(idx * 0.55, 2),
                            "path": str(out_f),
                            "precomputedElements": cap.get("elements") or [],
                        }
                    )
                if idx + 1 < cnt:
                    time.sleep(0.55)

        timeline: List[Dict[str, Any]] = []
        frame_paths: List[Path] = []
        all_ocr_lines: List[str] = []
        seen_lines: set[str] = set()

        for fr in extracted_frames:
            fpath = Path(str(fr["path"]))
            if not fpath.is_file():
                continue
            frame_paths.append(fpath)
            if fr.get("precomputedElements"):
                els = fr["precomputedElements"]
            else:
                ocr_res = self._run_2x_ocr(fpath)
                els = ocr_res.get("elements") or []
            lines = [str(e.get("text") or "").strip() for e in els if str(e.get("text") or "").strip()]
            for ln in lines:
                if ln not in seen_lines:
                    seen_lines.add(ln)
                    all_ocr_lines.append(f"[t={fr.get('timestampSeconds', 0)}s] {ln}")
            timeline.append(
                {
                    "index": fr.get("index"),
                    "timestampSeconds": fr.get("timestampSeconds", 0.0),
                    "path": str(fpath),
                    "ocrLines": lines,
                }
            )

        ocr_combined = "\n".join(all_ocr_lines)
        title = f"{contact or '微信'} 视频多帧解析 ({resolved_video.name if resolved_video else (video_url or window_title)})"
        body_meta = (
            f"抽取方式: {extract_method} | 时长: {duration_sec:.2f}s | 关键帧数: {len(frame_paths)}。"
            + (f" 备注: {download_note}" if download_note else "")
        )
        llm = self._synthesize_with_deepseek(
            kind="video",
            title=title,
            ocr_text=ocr_combined,
            body_text=body_meta,
            image_paths=frame_paths[:3],
            contact=contact,
            context_text=context_text,
            url=video_url or "",
            model_id=model_id,
        )

        result = {
            "ok": bool(frame_paths) or bool(llm.get("ok")),
            "analysisId": analysis_id,
            "kind": "video",
            "contact": contact,
            "title": title,
            "videoPath": str(resolved_video) if resolved_video else None,
            "videoUrl": video_url,
            "extractMethod": extract_method,
            "durationSeconds": duration_sec,
            "frameCount": len(frame_paths),
            "frameTimeline": timeline,
            "ocrCount": len(all_ocr_lines),
            "ocrText": ocr_combined,
            **llm,
        }
        art_path = self.analysis_dir / f"{analysis_id}.json"
        atomic_write_json(art_path, result, newline=False)
        result["artifactPath"] = str(art_path)
        return self._record_analysis(result)
