#!/usr/bin/env python3
"""WeChat Official Account & reader article exporter to Markdown (.md) + local assets."""

from __future__ import annotations

import hashlib
import html as html_lib
import ipaddress
import json
import mimetypes
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

MAX_ARTICLE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024


DEFAULT_WECHAT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) MacWechat"
)


def _slugify(text: str, max_len: int = 48) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "-", (text or "").strip())
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._ ")
    if not cleaned:
        cleaned = "wechat-article"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("-._ ")
    return cleaned or "wechat-article"


def _guess_extension(url: str, content_type: str = "", data: bytes = b"") -> str:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    wx_fmt = (qs.get("wx_fmt") or [""])[0].lower().strip()
    fmt_map = {
        "jpeg": "jpg",
        "jpg": "jpg",
        "png": "png",
        "gif": "gif",
        "webp": "webp",
        "svg": "svg",
        "bmp": "bmp",
    }
    if wx_fmt in fmt_map:
        return fmt_map[wx_fmt]

    ct = (content_type or "").split(";")[0].strip().lower()
    if ct:
        ct_map = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/gif": "gif",
            "image/webp": "webp",
            "image/svg+xml": "svg",
            "image/bmp": "bmp",
        }
        if ct in ct_map:
            return ct_map[ct]
        guessed = mimetypes.guess_extension(ct)
        if guessed:
            return guessed.lstrip(".")

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if b"<svg" in data[:256].lower():
        return "svg"

    suffix = Path(parsed.path).suffix.lower().lstrip(".")
    if suffix in {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"}:
        return "jpg" if suffix == "jpeg" else suffix
    return "png"


def _normalize_image_url(raw_url: str) -> str:
    url = html_lib.unescape((raw_url or "").strip())
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    return url


def _validate_safe_http_url(
    url: str,
    *,
    allowed_hosts: Optional[Set[str]] = None,
    allow_loopback: bool = False,
) -> Tuple[bool, str]:
    """Validate URL uses http(s) and does not target localhost/private/link-local SSRF ranges."""
    clean = (url or "").strip()
    if not clean:
        return False, "empty_url"
    try:
        parsed = urllib.parse.urlsplit(clean)
    except Exception:
        return False, "malformed_url"
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"disallowed_scheme:{scheme or 'none'}"
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return False, "missing_hostname"

    is_loopback_name = hostname in ("localhost", "127.0.0.1", "::1") or hostname.endswith(".localhost")
    if is_loopback_name and not allow_loopback:
        return False, f"ssrf_blocked_loopback:{hostname}"
    if hostname.endswith(".local") and not allow_loopback:
        return False, f"ssrf_blocked_local_domain:{hostname}"

    try:
        ip_obj = ipaddress.ip_address(hostname)
        if ip_obj.is_loopback:
            if not allow_loopback:
                return False, f"ssrf_blocked_loopback_ip:{hostname}"
        elif ip_obj.is_private or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_reserved or ip_obj.is_unspecified:
            return False, f"ssrf_blocked_private_or_link_local_ip:{hostname}"
    except ValueError:
        pass

    if allowed_hosts:
        normalized = {h.strip().lower().lstrip(".") for h in allowed_hosts if h and h.strip()}
        if not (hostname in normalized or any(hostname.endswith("." + h) for h in normalized)):
            if not (allow_loopback and is_loopback_name):
                return False, f"host_not_in_allowlist:{hostname}"

    return True, ""


def _read_bounded_response(resp: Any, max_bytes: int) -> bytes:
    """Read HTTP response safely with strict Content-Length + streaming byte cap."""
    cl_raw = ""
    if getattr(resp, "headers", None) is not None:
        cl_raw = str(resp.headers.get("Content-Length") or "").strip()
    if cl_raw.isdigit() and int(cl_raw) > max_bytes:
        raise ValueError(f"response_exceeds_max_bytes:{int(cl_raw)}>{max_bytes}")
    data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response_exceeds_max_bytes:>{max_bytes}")
    return data


class WeChatArticleHTMLParser(HTMLParser):
    """Lightweight stdlib HTML parser extracting metadata, clean Markdown, and images."""

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
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: Dict[str, str] = {}
        self.title: str = ""
        self.author: str = ""
        self.publish_time: str = ""
        self.images: List[Dict[str, Any]] = []
        self._seen_img_urls: Dict[str, int] = {}

        # Metadata target tracking
        self._meta_capture_key: Optional[str] = None
        self._meta_capture_depth: int = 0
        self._meta_buffer: List[str] = []

        # Content root tracking (#js_content -> <article> -> <body>)
        self._js_content_depth: int = 0
        self._has_js_content: bool = False
        self._fallback_depth: int = 0
        self._skip_depth: int = 0

        # Active streams (prefer #js_content if seen; else fallback_chunks)
        self._js_tokens: List[str] = []
        self._fallback_tokens: List[str] = []

        self._list_stack: List[Tuple[str, int]] = []
        self._link_stack: List[Optional[str]] = []
        self._in_pre: bool = False
        self._in_code: bool = False
        self._in_blockquote: int = 0
        self._heading_level: int = 0
        self._bold_depth: int = 0
        self._italic_depth: int = 0

    @property
    def _active_tokens(self) -> Optional[List[str]]:
        if self._js_content_depth > 0:
            return self._js_tokens
        if not self._has_js_content and self._fallback_depth > 0:
            return self._fallback_tokens
        return None

    def _emit(self, text: str) -> None:
        buf = self._active_tokens
        if buf is not None and text:
            buf.append(text)

    def handle_starttag(self, tag: str, attrs_list: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        elem_id = attrs.get("id", "").strip()
        classes = attrs.get("class", "").lower().split()

        if tag == "meta":
            prop = (attrs.get("property") or attrs.get("name") or "").strip().lower()
            content = attrs.get("content", "").strip()
            if prop and content:
                self.meta[prop] = content
            return

        # Track metadata text nodes outside content
        if self._meta_capture_key is not None:
            self._meta_capture_depth += 1
        elif elem_id == "activity-name" or "rich_media_title" in classes:
            self._meta_capture_key = "title"
            self._meta_capture_depth = 1
            self._meta_buffer = []
        elif elem_id == "js_name" or "rich_media_meta_nickname" in classes:
            self._meta_capture_key = "author"
            self._meta_capture_depth = 1
            self._meta_buffer = []
        elif elem_id == "publish_time":
            self._meta_capture_key = "publish_time"
            self._meta_capture_depth = 1
            self._meta_buffer = []

        # Track #js_content / fallback root depths
        if self._js_content_depth > 0:
            self._js_content_depth += 1
        elif elem_id == "js_content" or "rich_media_content" in classes:
            self._has_js_content = True
            self._js_content_depth = 1

        if self._fallback_depth > 0:
            self._fallback_depth += 1
        elif tag in {"article", "body"} and self._js_content_depth == 0:
            self._fallback_depth = 1

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if self._active_tokens is None:
            return

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_level = int(tag[1])
            self._emit(f"\n\n{'#' * self._heading_level} ")
        elif tag == "blockquote":
            self._in_blockquote += 1
            self._emit("\n\n> ")
        elif tag in {"ul", "ol"}:
            self._list_stack.append((tag, 0))
            self._emit("\n")
        elif tag == "li":
            if self._list_stack:
                ltype, count = self._list_stack[-1]
                count += 1
                self._list_stack[-1] = (ltype, count)
                indent = "  " * max(0, len(self._list_stack) - 1)
                prefix = f"{count}. " if ltype == "ol" else "- "
                self._emit(f"\n{indent}{prefix}")
            else:
                self._emit("\n- ")
        elif tag == "pre":
            self._in_pre = True
            self._emit("\n\n```\n")
        elif tag == "code":
            if not self._in_pre:
                self._in_code = True
                self._emit("`")
        elif tag in {"strong", "b"}:
            if self._bold_depth == 0:
                self._emit("**")
            self._bold_depth += 1
        elif tag in {"em", "i"}:
            if self._italic_depth == 0:
                self._emit("*")
            self._italic_depth += 1
        elif tag == "a":
            href = html_lib.unescape(attrs.get("href", "").strip())
            if href.startswith("http://") or href.startswith("https://"):
                self._link_stack.append(href)
                self._emit("[")
            else:
                self._link_stack.append(None)
        elif tag == "br":
            self._emit("\n" if self._in_pre else "  \n")
        elif tag == "hr":
            self._emit("\n\n---\n\n")
        elif tag in {"p", "section", "tr"}:
            self._emit("\n\n" if tag != "tr" else "\n")
        elif tag == "img":
            raw_src = (
                attrs.get("data-src")
                or attrs.get("data-backup-src")
                or attrs.get("data-original")
                or attrs.get("src")
                or ""
            )
            img_url = _normalize_image_url(raw_src)
            if img_url and not img_url.startswith("data:image/svg+xml"):
                if img_url in self._seen_img_urls:
                    idx = self._seen_img_urls[img_url]
                else:
                    idx = len(self.images) + 1
                    self._seen_img_urls[img_url] = idx
                    alt_raw = html_lib.unescape(attrs.get("alt") or attrs.get("data-alt") or "").strip()
                    alt = re.sub(r"[\r\n\[\]]+", " ", alt_raw).strip() or f"图片 {idx}"
                    self.images.append(
                        {
                            "index": idx,
                            "url": img_url,
                            "alt": alt,
                            "placeholder": f"__WECHAT_IMG_{idx}__",
                        }
                    )
                entry = self.images[idx - 1]
                self._emit(f"\n\n![{entry['alt']}]({entry['placeholder']})\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if self._meta_capture_key is not None:
            self._meta_capture_depth -= 1
            if self._meta_capture_depth <= 0:
                captured = re.sub(r"\s+", " ", "".join(self._meta_buffer)).strip()
                if captured:
                    if self._meta_capture_key == "title" and not self.title:
                        self.title = captured
                    elif self._meta_capture_key == "author" and not self.author:
                        self.author = captured
                    elif self._meta_capture_key == "publish_time" and not self.publish_time:
                        self.publish_time = captured
                self._meta_capture_key = None
                self._meta_buffer = []

        if self._skip_depth > 0:
            if tag in self.SKIP_TAGS:
                self._skip_depth -= 1
            self._decrement_root_depths()
            return

        if self._active_tokens is not None:
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                self._heading_level = 0
                self._emit("\n\n")
            elif tag == "blockquote":
                self._in_blockquote = max(0, self._in_blockquote - 1)
                self._emit("\n\n")
            elif tag in {"ul", "ol"}:
                if self._list_stack:
                    self._list_stack.pop()
                self._emit("\n\n")
            elif tag == "pre":
                self._in_pre = False
                self._emit("\n```\n\n")
            elif tag == "code":
                if self._in_code:
                    self._in_code = False
                    self._emit("`")
            elif tag in {"strong", "b"}:
                if self._bold_depth > 0:
                    self._bold_depth -= 1
                    if self._bold_depth == 0:
                        self._emit("**")
            elif tag in {"em", "i"}:
                if self._italic_depth > 0:
                    self._italic_depth -= 1
                    if self._italic_depth == 0:
                        self._emit("*")
            elif tag == "a":
                href = self._link_stack.pop() if self._link_stack else None
                if href:
                    self._emit(f"]({href})")
            elif tag in {"p", "section"}:
                self._emit("\n\n")
            elif tag == "td":
                self._emit(" | ")

        self._decrement_root_depths()

    def _decrement_root_depths(self) -> None:
        if self._js_content_depth > 0:
            self._js_content_depth -= 1
        if self._fallback_depth > 0:
            self._fallback_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._meta_capture_key is not None:
            self._meta_buffer.append(data)

        if self._skip_depth > 0 or self._active_tokens is None:
            return

        if self._in_pre:
            self._emit(data)
            return

        collapsed = re.sub(r"[ \t\r\n]+", " ", data)
        if not collapsed:
            return
        if collapsed == " ":
            prev = self._active_tokens[-1] if self._active_tokens else ""
            if not prev or prev.endswith(("\n", " ", "**", "*", "[", "`", "> ")):
                return
        self._emit(collapsed)

    def get_markdown(self) -> str:
        tokens = self._js_tokens if self._has_js_content and self._js_tokens else self._fallback_tokens
        raw = "".join(tokens)
        lines = [line.rstrip() for line in raw.splitlines()]
        cleaned_lines: List[str] = []
        blank_run = 0
        for line in lines:
            stripped = line.strip()
            # Clean empty emphasis artifacts like "** **" or "* *"
            if stripped in {"**", "****", "*", "** **", "* *"}:
                stripped = ""
                line = ""
            if not stripped:
                blank_run += 1
                if blank_run <= 1 and cleaned_lines:
                    cleaned_lines.append("")
            else:
                blank_run = 0
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()


class WeChatArticleExporter:
    """Exports open WeChat articles or mp.weixin.qq.com URLs to .md + local assets."""

    def __init__(self, inspector: Any, export_root: Path, *, allow_loopback_urls: bool = False) -> None:
        self.inspector = inspector
        self.export_root = Path(export_root)
        self.allow_loopback_urls = bool(allow_loopback_urls)

    @staticmethod
    def _read_clipboard() -> str:
        try:
            proc = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3.0)
            return proc.stdout if proc.returncode == 0 else ""
        except Exception:
            return ""

    @staticmethod
    def _write_clipboard(text: str) -> None:
        try:
            subprocess.run(["pbcopy"], input=text, text=True, capture_output=True, timeout=3.0)
        except Exception:
            pass

    @staticmethod
    def _extract_js_var(html: str, var_name: str) -> str:
        patterns = [
            rf"var\s+{re.escape(var_name)}\s*=\s*(?:htmlDecode\()?['\"]([^'\"]+)['\"]",
            rf"{re.escape(var_name)}\s*:\s*['\"]([^'\"]+)['\"]",
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                return html_lib.unescape(m.group(1)).strip()
        return ""

    @staticmethod
    def _crop_png(src_path: Path, dst_path: Path, x: int, y: int, width: int, height: int) -> bool:
        if width <= 4 or height <= 4 or not src_path.exists():
            return False
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                [
                    "sips",
                    "-c",
                    str(max(1, int(height))),
                    str(max(1, int(width))),
                    "--cropOffset",
                    str(max(0, int(y))),
                    str(max(0, int(x))),
                    str(src_path),
                    "--out",
                    str(dst_path),
                ],
                capture_output=True,
                text=True,
                timeout=8.0,
            )
            return proc.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 0
        except Exception:
            return False

    def extract_url_from_open_wechat_article(self) -> Dict[str, Any]:
        """Try to click the article tab `...` menu -> '复制链接' and capture clipboard URL."""
        staging_dir = self.export_root / ".staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        status = self.inspector._activate_and_get_status()
        windows = status.get("windows") or []
        if not windows:
            return {"ok": False, "error": "no_visible_wechat_window"}
        bounds = windows[0].get("bounds") or {}
        win_x = float(bounds.get("x", 0))
        win_y = float(bounds.get("y", 0))
        win_w = float(bounds.get("width", 1029))

        snap1 = staging_dir / "copy_link_probe_1.png"
        ocr1 = self.inspector._run_native(["capture-ocr", "--out", str(snap1)], 15.0)
        elements = ocr1.get("elements") or []

        split_x = max(460.0, win_w * 0.50)
        # Look for the top reader tab pill (y between 8 and 56 in right pane)
        tab_candidates = [
            el for el in elements
            if float(el.get("bbox", {}).get("x", 0)) >= split_x
            and 8.0 <= float(el.get("bbox", {}).get("y", 999)) <= 56.0
            and len(str(el.get("text", "")).strip()) >= 4
        ]
        tab_candidates.sort(key=lambda e: float(e.get("bbox", {}).get("width", 0)), reverse=True)

        if not tab_candidates:
            return {"ok": False, "error": "no_article_tab_pill_detected"}

        pill = tab_candidates[0]["bbox"]
        # Click the '...' trigger near the right edge of the tab pill
        dots_rel_x = min(win_w - 60.0, float(pill["x"]) + float(pill["width"]) - 8.0)
        dots_rel_y = float(pill["y"]) + float(pill["height"]) / 2.0
        prev_clip = self._read_clipboard()

        self.inspector._run_native(
            ["click", "--x", f"{win_x + dots_rel_x:.1f}", "--y", f"{win_y + dots_rel_y:.1f}"],
            5.0,
        )
        time.sleep(0.45)

        snap2 = staging_dir / "copy_link_menu_2.png"
        ocr2 = self.inspector._run_native(["capture-ocr", "--out", str(snap2)], 15.0)
        menu_items = ocr2.get("elements") or []
        copy_item = None
        for el in menu_items:
            txt = str(el.get("text", "")).replace(" ", "")
            if any(k in txt for k in ("复制链接", "CopyLink", "拷贝链接")):
                copy_item = el
                break

        if copy_item is None:
            # Dismiss any open menu cleanly by clicking neutral header whitespace
            self.inspector._run_native(
                ["click", "--x", f"{win_x + split_x + 40:.1f}", "--y", f"{win_y + 16:.1f}"],
                5.0,
            )
            return {
                "ok": False,
                "error": "copy_link_menu_item_not_found",
                "menuCandidates": [e.get("text") for e in menu_items if float(e.get("bbox", {}).get("x", 0)) > split_x],
            }

        cbox = copy_item["center"]
        self.inspector._run_native(
            ["click", "--x", f"{win_x + float(cbox['x']):.1f}", "--y", f"{win_y + float(cbox['y']):.1f}"],
            5.0,
        )
        time.sleep(0.3)
        new_clip = self._read_clipboard().strip()
        if prev_clip and new_clip != prev_clip:
            self._write_clipboard(prev_clip)

        if new_clip.startswith(("http://", "https://")) and new_clip != prev_clip:
            return {"ok": True, "url": new_clip, "method": "wechat_tab_copy_link"}
        if "mp.weixin.qq.com" in new_clip:
            m = re.search(r"https?://mp\.weixin\.qq\.com/\S+", new_clip)
            if m:
                return {"ok": True, "url": m.group(0), "method": "wechat_tab_copy_link"}
        return {"ok": False, "error": "clipboard_did_not_receive_url", "clipboardPreview": new_clip[:80]}

    DEFAULT_WECHAT_IMAGE_HOSTS: Set[str] = {
        "mmbiz.qpic.cn",
        "mmbiz.qlogo.cn",
        "wx.qlogo.cn",
        "qlogo.cn",
        "qpic.cn",
        "res.wx.qq.com",
        "weixin.qq.com",
        "qq.com",
        "myqcloud.com",
    }

    def download_article_images(
        self,
        image_entries: List[Dict[str, Any]],
        assets_dir: Path,
        referer: str = "https://mp.weixin.qq.com/",
        timeout: float = 15.0,
        allowed_hosts: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Download WeChat data-src/src images locally with anti-hotlink Referer, SSRF guard & size cap."""
        assets_dir.mkdir(parents=True, exist_ok=True)
        effective_hosts = allowed_hosts if allowed_hosts is not None else (
            self.DEFAULT_WECHAT_IMAGE_HOSTS if "mp.weixin.qq.com" in (referer or "") else None
        )
        results: List[Dict[str, Any]] = []
        for entry in image_entries:
            idx = int(entry["index"])
            url = str(entry["url"])
            alt = str(entry.get("alt") or f"图片 {idx}")
            placeholder = str(entry.get("placeholder") or f"__WECHAT_IMG_{idx}__")
            record: Dict[str, Any] = {
                "index": idx,
                "original_url": url,
                "alt": alt,
                "placeholder": placeholder,
                "local_rel_path": "",
                "local_abs_path": "",
                "ok": False,
                "error": "",
                "size_bytes": 0,
                "sha256": "",
            }
            try:
                safe_ok, safe_err = _validate_safe_http_url(
                    url,
                    allowed_hosts=effective_hosts,
                    allow_loopback=self.allow_loopback_urls,
                )
                if not safe_ok:
                    raise ValueError(safe_err)
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": DEFAULT_WECHAT_UA,
                        "Referer": referer,
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = _read_bounded_response(resp, MAX_IMAGE_BYTES)
                    ct = resp.headers.get("Content-Type", "")
                if not data:
                    raise ValueError("empty_image_response")
                ext = _guess_extension(url, content_type=ct, data=data)
                filename = f"img_{idx:03d}.{ext}"
                target = assets_dir / filename
                target.write_bytes(data)
                record.update(
                    {
                        "ok": True,
                        "local_rel_path": f"assets/{filename}",
                        "local_abs_path": str(target),
                        "size_bytes": len(data),
                        "mime_type": ct or f"image/{ext}",
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            except Exception as exc:
                record["error"] = str(exc)
            results.append(record)
        return results

    def export_from_html(
        self,
        html: str,
        *,
        source_url: str = "",
        output_dir: Optional[Path] = None,
        download_images: bool = True,
        extra_assets: Optional[List[Dict[str, Any]]] = None,
        mode: str = "html_url",
        fetch_timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """Parse article HTML -> clean Markdown + local downloaded images in assets/."""
        parser = WeChatArticleHTMLParser()
        parser.feed(html)
        parser.close()

        title = (
            parser.title
            or parser.meta.get("og:title")
            or parser.meta.get("twitter:title")
            or self._extract_js_var(html, "msg_title")
            or "未命名微信文章"
        )
        author = (
            parser.author
            or parser.meta.get("author")
            or self._extract_js_var(html, "nickname")
            or ""
        )
        publish_time = parser.publish_time or self._extract_js_var(html, "publish_time") or ""
        if not publish_time:
            ct = self._extract_js_var(html, "ct")
            if ct.isdigit():
                publish_time = datetime.fromtimestamp(int(ct), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

        body_md = parser.get_markdown()
        exported_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target_dir = Path(output_dir) if output_dir else (self.export_root / f"{stamp}_{_slugify(title)}")
        assets_dir = target_dir / "assets"
        target_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

        img_records: List[Dict[str, Any]] = []
        if download_images and parser.images:
            referer = source_url if source_url.startswith("http") else "https://mp.weixin.qq.com/"
            img_records = self.download_article_images(
                parser.images,
                assets_dir=assets_dir,
                referer=referer,
                timeout=fetch_timeout,
            )
            for rec in img_records:
                replacement = rec["local_rel_path"] if rec["ok"] else rec["original_url"]
                body_md = body_md.replace(rec["placeholder"], replacement)
        else:
            for entry in parser.images:
                body_md = body_md.replace(entry["placeholder"], entry["url"])
                img_records.append(
                    {
                        "index": entry["index"],
                        "original_url": entry["url"],
                        "alt": entry["alt"],
                        "local_rel_path": "",
                        "local_abs_path": "",
                        "ok": False,
                        "error": "download_disabled" if not download_images else "",
                    }
                )

        if extra_assets:
            for asset in extra_assets:
                src = Path(str(asset.get("path") or ""))
                if src.exists():
                    dest = assets_dir / src.name
                    if src.resolve() != dest.resolve():
                        shutil.copy2(src, dest)
                    img_records.append(
                        {
                            "index": len(img_records) + 1,
                            "original_url": "",
                            "alt": str(asset.get("caption") or src.name),
                            "local_rel_path": f"assets/{src.name}",
                            "local_abs_path": str(dest),
                            "ok": True,
                            "size_bytes": dest.stat().st_size,
                        }
                    )

        downloaded_count = sum(1 for r in img_records if r.get("ok"))
        frontmatter = [
            "---",
            f"title: {json.dumps(title, ensure_ascii=False)}",
            f"author: {json.dumps(author, ensure_ascii=False)}",
            f"publish_time: {json.dumps(publish_time, ensure_ascii=False)}",
            f"source_url: {json.dumps(source_url, ensure_ascii=False)}",
            f"export_mode: {json.dumps(mode, ensure_ascii=False)}",
            f"exported_at: {json.dumps(exported_at, ensure_ascii=False)}",
            f"image_count: {downloaded_count}",
            "---",
            "",
        ]
        header_lines = [f"# {title}", ""]
        meta_bits = []
        if author:
            meta_bits.append(f"作者/公众号：{author}")
        if publish_time:
            meta_bits.append(f"发布时间：{publish_time}")
        if source_url:
            meta_bits.append(f"[原文链接]({source_url})")
        if meta_bits:
            header_lines.append("> " + " | ".join(meta_bits))
            header_lines.append("")

        full_md = "\n".join(frontmatter + header_lines) + body_md.strip() + "\n"
        md_path = target_dir / "article.md"
        md_path.write_text(full_md, encoding="utf-8")

        slug = target_dir.name
        metadata = {
            "ok": True,
            "slug": slug,
            "mode": mode,
            "title": title,
            "author": author,
            "publish_time": publish_time,
            "source_url": source_url,
            "exported_at": exported_at,
            "article_dir": str(target_dir),
            "markdown_path": str(md_path),
            "assets_dir": str(assets_dir),
            "image_count": len(img_records),
            "downloaded_image_count": downloaded_count,
            "images": img_records,
            "markdown_chars": len(full_md),
            "markdown_preview": full_md[:3000],
        }
        meta_path = target_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata["metadata_path"] = str(meta_path)
        metadata["markdown_content"] = full_md
        return metadata

    def export_from_url(
        self,
        url: str,
        *,
        output_dir: Optional[Path] = None,
        download_images: bool = True,
        extra_assets: Optional[List[Dict[str, Any]]] = None,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """Fetch mp.weixin.qq.com (or any safe article URL) and export .md + local assets."""
        clean_url = (url or "").strip()
        safe_ok, safe_err = _validate_safe_http_url(clean_url, allow_loopback=self.allow_loopback_urls)
        if not safe_ok:
            return {"ok": False, "error": f"Blocked or invalid article URL ({safe_err}): {clean_url!r}"}
        req = urllib.request.Request(
            clean_url,
            headers={
                "User-Agent": DEFAULT_WECHAT_UA,
                "Referer": "https://mp.weixin.qq.com/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = _read_bounded_response(resp, MAX_ARTICLE_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
        html = raw_bytes.decode(charset, errors="replace")
        if any(flag in html for flag in ("环境异常", "当前环境异常", "去验证")) and "js_content" not in html:
            return {
                "ok": False,
                "error": "wechat_verification_wall",
                "source_url": clean_url,
            }
        return self.export_from_html(
            html,
            source_url=clean_url,
            output_dir=output_dir,
            download_images=download_images,
            extra_assets=extra_assets,
            mode="html_url",
            fetch_timeout=timeout,
        )

    @staticmethod
    def _group_ocr_lines(
        elements: List[Dict[str, Any]],
        *,
        x_min: float,
        y_min: float,
        y_max: float,
    ) -> List[Dict[str, Any]]:
        rows = [
            el for el in elements
            if float(el.get("bbox", {}).get("x", 0)) >= x_min
            and y_min <= float(el.get("bbox", {}).get("y", 0)) <= y_max
            and str(el.get("text", "")).strip()
        ]
        rows.sort(key=lambda e: (float(e["bbox"]["y"]), float(e["bbox"]["x"])))
        merged: List[Dict[str, Any]] = []
        for el in rows:
            box = el["bbox"]
            txt = str(el["text"]).strip()
            if merged and abs(float(box["y"]) - merged[-1]["y"]) <= 8.0:
                prev = merged[-1]
                prev["text"] = f"{prev['text']} {txt}".strip()
                right = max(prev["x"] + prev["width"], float(box["x"]) + float(box["width"]))
                prev["x"] = min(prev["x"], float(box["x"]))
                prev["width"] = right - prev["x"]
                prev["height"] = max(prev["height"], float(box["height"]))
                prev["bottom"] = prev["y"] + prev["height"]
            else:
                x = float(box["x"])
                y = float(box["y"])
                w = float(box["width"])
                h = float(box["height"])
                merged.append(
                    {
                        "text": txt,
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                        "bottom": y + h,
                    }
                )
        return merged

    def export_from_wechat_window(
        self,
        *,
        max_scroll_pages: int = 4,
        try_copy_link: bool = True,
        output_dir: Optional[Path] = None,
        download_images: bool = True,
    ) -> Dict[str, Any]:
        """Export the article currently displayed in the active WeChat reader pane."""
        status = self.inspector._activate_and_get_status()
        windows = status.get("windows") or []
        if not windows:
            return {"ok": False, "error": "no_visible_wechat_window"}

        bounds = windows[0].get("bounds") or {}
        win_w = int(round(float(bounds.get("width", 1029))))
        win_h = int(round(float(bounds.get("height", 640))))

        staging_dir = self.export_root / ".staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        initial_full = staging_dir / "initial_window.png"
        ocr0 = self.inspector._run_native(["capture-ocr", "--out", str(initial_full)], 15.0)
        els0 = ocr0.get("elements") or []
        img_w = int(ocr0.get("imageWidth") or win_w)
        img_h = int(ocr0.get("imageHeight") or win_h)
        scale_x = img_w / max(1.0, float(win_w))
        scale_y = img_h / max(1.0, float(win_h))

        right_split_x = int(win_w * 0.56) if win_w >= 880 else 0
        has_right_pane = any(float(e.get("bbox", {}).get("x", 0)) >= right_split_x + 15 for e in els0)
        pane_x = right_split_x if has_right_pane else 0
        pane_w = max(200, win_w - pane_x)
        body_y_top = 56
        body_y_bottom = max(body_y_top + 120, win_h - 56)

        initial_pane_shot = staging_dir / "window_page_01.png"
        self._crop_png(
            initial_full,
            initial_pane_shot,
            int(round(pane_x * scale_x)),
            int(round(body_y_top * scale_y)),
            int(round(pane_w * scale_x)),
            int(round((body_y_bottom - body_y_top) * scale_y)),
        )

        # Path 1: Try extracting the canonical mp.weixin.qq.com URL from the open tab
        url_probe: Dict[str, Any] = {"ok": False, "skipped": not try_copy_link}
        if try_copy_link:
            url_probe = self.extract_url_from_open_wechat_article()
            if url_probe.get("ok") and url_probe.get("url"):
                try:
                    html_res = self.export_from_url(
                        url_probe["url"],
                        output_dir=output_dir,
                        download_images=download_images,
                        extra_assets=[{"path": str(initial_pane_shot), "caption": "微信内阅读窗首页截图"}],
                    )
                    if html_res.get("ok") and html_res.get("markdown_chars", 0) >= 180:
                        html_res["extract_method"] = "wechat_tab_copy_link"
                        return html_res
                except Exception as exc:
                    url_probe["fetch_error"] = str(exc)

        # Path 2: Visual multi-page scroll + Vision OCR + Figure Gap Crop
        temp_pages_dir = staging_dir / f"run_{int(time.time())}"
        temp_pages_dir.mkdir(parents=True, exist_ok=True)

        pages_data: List[Dict[str, Any]] = []
        seen_signatures: set[str] = set()
        detected_title_lines: List[str] = []
        detected_author = ""
        markdown_blocks: List[str] = []
        saved_assets: List[Dict[str, Any]] = []

        scroll_rx = min(0.92, (pane_x + pane_w * 0.52) / max(1.0, float(win_w)))
        scroll_ry = 0.52

        for page_idx in range(1, max(1, int(max_scroll_pages)) + 1):
            if page_idx == 1:
                full_shot = initial_full
                ocr_res = ocr0
            else:
                self.inspector._run_native(
                    [
                        "scroll",
                        "--rx",
                        f"{scroll_rx:.3f}",
                        "--ry",
                        f"{scroll_ry:.3f}",
                        "--dy",
                        "-360",
                        "--units",
                        "pixel",
                        "--steps",
                        "5",
                    ],
                    6.0,
                )
                time.sleep(0.42)
                full_shot = temp_pages_dir / f"raw_page_{page_idx:02d}.png"
                ocr_res = self.inspector._run_native(["capture-ocr", "--out", str(full_shot)], 15.0)

            els = ocr_res.get("elements") or []
            p_img_w = int(ocr_res.get("imageWidth") or win_w)
            p_img_h = int(ocr_res.get("imageHeight") or win_h)
            psx = p_img_w / max(1.0, float(win_w))
            psy = p_img_h / max(1.0, float(win_h))

            page_shot = temp_pages_dir / f"page_{page_idx:02d}.png"
            self._crop_png(
                full_shot,
                page_shot,
                int(round(pane_x * psx)),
                int(round(body_y_top * psy)),
                int(round(pane_w * psx)),
                int(round((body_y_bottom - body_y_top) * psy)),
            )
            saved_assets.append(
                {
                    "kind": "page_snapshot",
                    "page": page_idx,
                    "temp_path": page_shot,
                    "filename": page_shot.name,
                    "caption": f"第 {page_idx} 页阅读快照",
                }
            )

            lines = self._group_ocr_lines(
                els,
                x_min=float(pane_x + 12),
                y_min=float(body_y_top + 4),
                y_max=float(body_y_bottom - 4),
            )
            page_sig = "|".join(line["text"] for line in lines)
            if page_idx > 1 and page_sig and page_sig in seen_signatures:
                # Reached end of article; stop scrolling further
                saved_assets.pop()
                break
            if page_sig:
                seen_signatures.add(page_sig)

            # On page 1, parse top title & metadata lines
            body_lines = list(lines)
            if page_idx == 1 and lines:
                title_cutoff_y = body_y_top + 88
                for ln in lines:
                    if ln["y"] <= title_cutoff_y and ln["height"] >= 19.0:
                        detected_title_lines.append(ln["text"])
                    elif any(k in ln["text"] for k in ("原创", "年", "月")) and ln["y"] <= body_y_top + 135:
                        detected_author = ln["text"]
                body_lines = [
                    ln for ln in lines
                    if ln["text"] not in detected_title_lines and ln["text"] != detected_author
                ]

            # Detect visual gaps (embedded images/charts/diagrams between text blocks)
            fig_idx = 0
            prev_bottom = float(body_y_top + 8)
            emitted_lines_on_page: List[str] = []
            for ln in body_lines:
                gap = ln["y"] - prev_bottom
                if gap >= 78.0 and prev_bottom > body_y_top + 35:
                    fig_idx += 1
                    crop_y = int(round((prev_bottom + 6.0) * psy))
                    crop_h = int(round((gap - 12.0) * psy))
                    fig_name = f"fig_p{page_idx:02d}_{fig_idx:02d}.png"
                    fig_path = temp_pages_dir / fig_name
                    if self._crop_png(
                        full_shot,
                        fig_path,
                        int(round((pane_x + 14) * psx)),
                        crop_y,
                        int(round((pane_w - 28) * psx)),
                        crop_h,
                    ):
                        saved_assets.append(
                            {
                                "kind": "figure_crop",
                                "page": page_idx,
                                "temp_path": fig_path,
                                "filename": fig_name,
                                "caption": f"文章插图 p{page_idx}-{fig_idx}",
                            }
                        )
                        emitted_lines_on_page.append(f"\n![文章插图 p{page_idx}-{fig_idx}](assets/{fig_name})\n")

                txt = ln["text"]
                if txt not in markdown_blocks[-6:]:
                    emitted_lines_on_page.append(txt)
                    markdown_blocks.append(txt)
                prev_bottom = max(prev_bottom, ln["bottom"])

            # Check if a large bottom figure fills the lower viewport of the pane
            tail_gap = float(body_y_bottom) - prev_bottom
            if tail_gap >= 110.0 and body_lines:
                fig_idx += 1
                fig_name = f"fig_p{page_idx:02d}_{fig_idx:02d}.png"
                fig_path = temp_pages_dir / fig_name
                if self._crop_png(
                    full_shot,
                    fig_path,
                    int(round((pane_x + 14) * psx)),
                    int(round((prev_bottom + 6.0) * psy)),
                    int(round((pane_w - 28) * psx)),
                    int(round((tail_gap - 12.0) * psy)),
                ):
                    saved_assets.append(
                        {
                            "kind": "figure_crop",
                            "page": page_idx,
                            "temp_path": fig_path,
                            "filename": fig_name,
                            "caption": f"文章插图 p{page_idx}-{fig_idx}",
                        }
                    )
                    emitted_lines_on_page.append(f"\n![文章插图 p{page_idx}-{fig_idx}](assets/{fig_name})\n")

            pages_data.append(
                {
                    "page": page_idx,
                    "lines": emitted_lines_on_page,
                }
            )

        tab_title = ""
        for el in els0:
            if float(el.get("bbox", {}).get("x", 0)) >= pane_x and float(el.get("bbox", {}).get("y", 999)) <= 52:
                cand = str(el.get("text", "")).strip()
                if len(cand) > len(tab_title):
                    tab_title = cand

        title = "".join(detected_title_lines).strip() or tab_title or "微信窗口文章导出"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target_dir = Path(output_dir) if output_dir else (self.export_root / f"{stamp}_{_slugify(title)}")
        assets_dir = target_dir / "assets"
        target_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

        img_records: List[Dict[str, Any]] = []
        for idx, asset in enumerate(saved_assets, start=1):
            src = Path(asset["temp_path"])
            if not src.exists():
                continue
            dest = assets_dir / asset["filename"]
            shutil.copy2(src, dest)
            raw_b = dest.read_bytes()
            img_records.append(
                {
                    "index": idx,
                    "kind": asset["kind"],
                    "page": asset["page"],
                    "alt": asset["caption"],
                    "local_rel_path": f"assets/{dest.name}",
                    "local_abs_path": str(dest),
                    "size_bytes": len(raw_b),
                    "sha256": hashlib.sha256(raw_b).hexdigest(),
                    "ok": True,
                }
            )

        exported_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        body_lines_md: List[str] = []
        for page_info in pages_data:
            pnum = page_info["page"]
            body_lines_md.append(f"<!-- Page {pnum} -->")
            for item in page_info["lines"]:
                body_lines_md.append(item)
            body_lines_md.append("")

        snapshot_gallery = [
            f"- 第 {r['page']} 页原图快照：![{r['alt']}]({r['local_rel_path']})"
            for r in img_records
            if r.get("kind") == "page_snapshot"
        ]

        md_parts = [
            "---",
            f"title: {json.dumps(title, ensure_ascii=False)}",
            f"author: {json.dumps(detected_author, ensure_ascii=False)}",
            f"export_mode: \"window_ocr_scroll\"",
            f"exported_at: {json.dumps(exported_at, ensure_ascii=False)}",
            f"pages_captured: {len(pages_data)}",
            f"image_count: {len(img_records)}",
            "---",
            "",
            f"# {title}",
            "",
        ]
        if detected_author:
            md_parts.extend([f"> {detected_author}", ""])
        if url_probe.get("error"):
            md_parts.extend([f"> 提取说明：已通过微信阅读窗口逐页 OCR + 区域插图裁切导出（未获取到原文链接原因：`{url_probe.get('error')}`）。", ""])

        md_parts.extend(body_lines_md)
        if snapshot_gallery:
            md_parts.extend(["## 原文阅读页面逐页截图存档", ""] + snapshot_gallery + [""])

        full_md = "\n".join(md_parts)
        md_path = target_dir / "article.md"
        md_path.write_text(full_md, encoding="utf-8")

        metadata = {
            "ok": True,
            "slug": target_dir.name,
            "mode": "window_ocr_scroll",
            "title": title,
            "author": detected_author,
            "publish_time": "",
            "source_url": url_probe.get("url", ""),
            "url_probe": url_probe,
            "exported_at": exported_at,
            "pages_captured": len(pages_data),
            "article_dir": str(target_dir),
            "markdown_path": str(md_path),
            "assets_dir": str(assets_dir),
            "image_count": len(img_records),
            "downloaded_image_count": len(img_records),
            "images": img_records,
            "markdown_chars": len(full_md),
            "markdown_preview": full_md[:3000],
        }
        meta_path = target_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata["metadata_path"] = str(meta_path)
        metadata["markdown_content"] = full_md
        return metadata

    def list_exported_articles(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.export_root.exists():
            return []
        items: List[Dict[str, Any]] = []
        for meta_file in self.export_root.glob("*/metadata.json"):
            if meta_file.parent.name.startswith(".") or meta_file.parent.name in ("accounts", "channels"):
                continue
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                items.append(data)
            except Exception:
                continue
        items.sort(key=lambda d: str(d.get("exported_at", "")), reverse=True)
        return items[: max(1, int(limit))]

    # ------------------------------------------------------------------
    # Official Account / Service Account All Articles Batch Exporter
    # ------------------------------------------------------------------

    @staticmethod
    def parse_account_album_or_feed_html(
        html: str,
        base_url: str = "https://mp.weixin.qq.com",
    ) -> Dict[str, Any]:
        """Extract Official/Service Account name and article links from album, history HTML, or text."""
        account_name = ""
        for pat in (
            r'id=["\']js_name["\'][^>]*>(.*?)</',
            r'class=["\'][^"\']*album__author-name[^"\']*["\'][^>]*>(.*?)</',
            r'var\s+nickname\s*=\s*["\']([^"\']+)["\']',
            r'<title[^>]*>(.*?)</title>',
        ):
            m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if m:
                cleaned = re.sub(r"<[^>]+>", "", html_lib.unescape(m.group(1))).strip()
                if cleaned and cleaned not in ("微信公众平台",):
                    account_name = cleaned
                    break

        entries: List[Dict[str, Any]] = []
        seen_urls: Set[str] = set()

        def _add_entry(raw_url: str, title: str = "", publish_time: str = "", digest: str = "") -> None:
            u = html_lib.unescape((raw_url or "").strip()).replace("\\/", "/")
            if not u:
                return
            if u.startswith("/"):
                u = urllib.parse.urljoin(base_url, u)
            elif u.startswith("//"):
                u = "https:" + u
            if not u.startswith(("http://", "https://")):
                return
            if u in seen_urls:
                return
            seen_urls.add(u)
            clean_title = re.sub(r"<[^>]+>", "", html_lib.unescape(title or "")).strip()
            entries.append(
                {
                    "title": clean_title,
                    "url": u,
                    "publish_time": html_lib.unescape(publish_time or "").strip(),
                    "digest": html_lib.unescape(digest or "").strip(),
                }
            )

        # 1) Album items (mp/appmsgalbum) or feed cards with data-link / data-title
        for m in re.finditer(
            r'<li[^>]*?(?:data-link=["\']([^"\']+)["\'])[^>]*?>.*?'
            r'(?:data-title=["\']([^"\']*)["\'])?',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            link = m.group(1)
            title = m.group(2) or ""
            if not title:
                tm = re.search(r'class=["\'][^"\']*title[^"\']*["\'][^>]*>(.*?)</', m.group(0), re.IGNORECASE | re.DOTALL)
                if tm:
                    title = tm.group(1)
            pm = re.search(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)', m.group(0))
            _add_entry(link, title=title, publish_time=pm.group(1) if pm else "")

        # 2) <a href="..."> links pointing to WeChat articles or local /s/ routes
        for m in re.finditer(
            r'<a\b([^>]*\bhref=["\']([^"\']+)["\'][^>]*)>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            attrs_raw, href, inner = m.group(1), m.group(2), m.group(3)
            if "mp.weixin.qq.com/s" in href or "/s?" in href or "/s/" in href or "data-article" in attrs_raw:
                dt = re.search(r'data-title=["\']([^"\']+)["\']', attrs_raw, re.IGNORECASE)
                _add_entry(href, title=dt.group(1) if dt else inner)

        # 3) Embedded msgList / JSON content_url fields
        for m in re.finditer(
            r'"title"\s*:\s*"([^"]{2,160})"[^}]*?"content_url"\s*:\s*"([^"]+)"',
            html,
            re.IGNORECASE | re.DOTALL,
        ):
            _add_entry(m.group(2), title=m.group(1))

        # 4) Fallback plain-text URLs (for chat records or .txt/.md lists)
        for m in re.finditer(r"https?://[^\s<>\"')]+", html):
            cand = m.group(0).rstrip(".,;]")
            if "mp.weixin.qq.com/s" in cand or "/s/" in cand or "/s?" in cand:
                _add_entry(cand)

        return {
            "ok": True,
            "accountName": account_name,
            "count": len(entries),
            "articles": entries,
        }

    def export_account_articles(
        self,
        *,
        account_name: str = "",
        album_url: str = "",
        album_html: str = "",
        article_urls: Optional[List[str]] = None,
        articles_html_list: Optional[List[Dict[str, str]]] = None,
        from_file: Optional[Path] = None,
        scan_open_window: bool = False,
        scroll_pages: int = 4,
        download_images: bool = True,
        max_articles: int = 50,
    ) -> Dict[str, Any]:
        """Batch-export all articles of a WeChat Official Account / Service Account into INDEX.md + folders."""
        resolved_account = (account_name or "").strip()
        candidates: List[Dict[str, Any]] = []
        seen_keys: Set[str] = set()

        def _push_candidate(item: Dict[str, Any]) -> None:
            url = str(item.get("url") or "").strip()
            html_body = str(item.get("html") or "").strip()
            title = str(item.get("title") or "").strip()
            key = url or (f"html:{hashlib.sha1(html_body.encode('utf-8')).hexdigest()[:12]}" if html_body else f"ocr:{title}")
            if not key or key in seen_keys:
                return
            seen_keys.add(key)
            candidates.append(item)

        if album_html.strip():
            parsed_album = self.parse_account_album_or_feed_html(album_html)
            if not resolved_account and parsed_album.get("accountName"):
                resolved_account = parsed_album["accountName"]
            for it in parsed_album.get("articles") or []:
                _push_candidate(it)

        clean_album_url = (album_url or "").strip()
        if clean_album_url:
            safe_ok, safe_err = _validate_safe_http_url(clean_album_url, allow_loopback=self.allow_loopback_urls)
            if not safe_ok:
                return {"ok": False, "error": f"Blocked or invalid album URL ({safe_err}): {clean_album_url!r}"}
            req = urllib.request.Request(
                clean_album_url,
                headers={
                    "User-Agent": DEFAULT_WECHAT_UA,
                    "Referer": "https://mp.weixin.qq.com/",
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                raw_album = _read_bounded_response(resp, MAX_ARTICLE_BYTES)
                charset = resp.headers.get_content_charset() or "utf-8"
            fetched_html = raw_album.decode(charset, errors="replace")
            parsed_album = self.parse_account_album_or_feed_html(fetched_html, base_url=clean_album_url)
            if not resolved_account and parsed_album.get("accountName"):
                resolved_account = parsed_album["accountName"]
            for it in parsed_album.get("articles") or []:
                _push_candidate(it)

        if from_file is not None:
            src_path = Path(from_file)
            if not src_path.is_file():
                return {"ok": False, "error": f"Source file not found: {src_path}"}
            raw_text = src_path.read_text(encoding="utf-8", errors="replace")
            parsed_file = self.parse_account_album_or_feed_html(raw_text)
            if not resolved_account and parsed_file.get("accountName"):
                resolved_account = parsed_file["accountName"]
            for it in parsed_file.get("articles") or []:
                _push_candidate(it)

        for raw_u in article_urls or []:
            u = str(raw_u or "").strip()
            if u:
                _push_candidate({"title": "", "url": u, "publish_time": ""})

        for item in articles_html_list or []:
            if isinstance(item, dict) and (item.get("html") or item.get("url")):
                _push_candidate(
                    {
                        "title": str(item.get("title") or ""),
                        "url": str(item.get("url") or ""),
                        "publish_time": str(item.get("publish_time") or ""),
                        "html": str(item.get("html") or ""),
                    }
                )

        ocr_scans: List[Dict[str, Any]] = []
        if scan_open_window and not candidates:
            status = self.inspector._activate_and_get_status()
            windows = status.get("windows") or []
            if not windows:
                return {"ok": False, "error": "no_visible_wechat_window"}
            bounds = windows[0].get("bounds") or {}
            win_w = int(round(float(bounds.get("width", 1029))))
            win_h = int(round(float(bounds.get("height", 640))))
            staging_dir = self.export_root / ".staging" / f"account_scan_{int(time.time())}"
            staging_dir.mkdir(parents=True, exist_ok=True)
            seen_lines: Set[str] = set()
            for page_idx in range(1, max(1, int(scroll_pages)) + 1):
                if page_idx > 1:
                    self.inspector._run_native(
                        ["scroll", "--rx", "0.62", "--ry", "0.55", "--dy", "-420", "--units", "pixel", "--steps", "5"],
                        6.0,
                    )
                    time.sleep(0.4)
                shot = staging_dir / f"feed_page_{page_idx:02d}.png"
                ocr = self.inspector._run_native(["capture-ocr", "--out", str(shot)], 15.0)
                lines = self._group_ocr_lines(
                    ocr.get("elements") or [],
                    x_min=max(220.0, win_w * 0.24),
                    y_min=52.0,
                    y_max=max(140.0, win_h - 40.0),
                )
                if not resolved_account and lines:
                    resolved_account = lines[0]["text"][:40]
                for ln in lines:
                    txt = str(ln.get("text") or "").strip()
                    if len(txt) < 6 or txt in seen_lines:
                        continue
                    if any(noise in txt for noise in ("发送消息", "不再关注", "全部消息", "发消息", "查看历史消息")):
                        continue
                    seen_lines.add(txt)
                    ocr_scans.append({"title": txt, "page": page_idx, "snapshot": str(shot)})

        if not candidates and not ocr_scans:
            return {
                "ok": False,
                "error": "no_articles_discovered",
                "hint": "Provide album_url, album_html, article_urls, from_file, or open the Service/Official Account feed with scan_open_window=True.",
            }

        resolved_account = resolved_account or "微信服务号与公众号归档"
        exported_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bundle_dir = self.export_root / "accounts" / f"{stamp}_{_slugify(resolved_account, 40)}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        exported_articles: List[Dict[str, Any]] = []
        failed_articles: List[Dict[str, Any]] = []
        capped_candidates = candidates[: max(1, int(max_articles))]

        for idx, cand in enumerate(capped_candidates, start=1):
            sub_slug = _slugify(cand.get("title") or f"article-{idx:03d}", 36)
            sub_dir = bundle_dir / f"{idx:03d}_{sub_slug}"
            try:
                if cand.get("html"):
                    res = self.export_from_html(
                        str(cand["html"]),
                        source_url=str(cand.get("url") or ""),
                        output_dir=sub_dir,
                        download_images=download_images,
                        mode="account_batch_html",
                    )
                elif cand.get("url"):
                    res = self.export_from_url(
                        str(cand["url"]),
                        output_dir=sub_dir,
                        download_images=download_images,
                    )
                else:
                    res = {"ok": False, "error": "missing_html_and_url"}

                if res.get("ok"):
                    if not cand.get("title"):
                        cand["title"] = res.get("title") or sub_slug
                    exported_articles.append(
                        {
                            "index": idx,
                            "title": res.get("title") or cand.get("title"),
                            "author": res.get("author") or resolved_account,
                            "publish_time": res.get("publish_time") or cand.get("publish_time", ""),
                            "source_url": cand.get("url") or res.get("source_url", ""),
                            "markdown_rel_path": f"{sub_dir.name}/article.md",
                            "markdown_path": res.get("markdown_path", ""),
                            "image_count": res.get("downloaded_image_count", 0),
                            "mode": res.get("mode", "html_url"),
                        }
                    )
                else:
                    failed_articles.append({"index": idx, "url": cand.get("url", ""), "error": res.get("error", "export_failed")})
            except Exception as exc:
                failed_articles.append({"index": idx, "url": cand.get("url", ""), "error": str(exc)})

        for idx, item in enumerate(ocr_scans[: max(1, int(max_articles))], start=len(exported_articles) + 1):
            sub_dir = bundle_dir / f"{idx:03d}_{_slugify(item['title'], 36)}"
            assets_dir = sub_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            snap_src = Path(item["snapshot"])
            rel_snap = ""
            if snap_src.exists():
                snap_dest = assets_dir / snap_src.name
                shutil.copy2(snap_src, snap_dest)
                rel_snap = f"assets/{snap_dest.name}"
            md_text = "\n".join(
                [
                    "---",
                    f"title: {json.dumps(item['title'], ensure_ascii=False)}",
                    f"account: {json.dumps(resolved_account, ensure_ascii=False)}",
                    "export_mode: \"account_feed_window_ocr\"",
                    f"exported_at: {json.dumps(exported_at, ensure_ascii=False)}",
                    "---",
                    "",
                    f"# {item['title']}",
                    "",
                    f"> 服务号/公众号：{resolved_account} | 扫描页码：第 {item['page']} 页",
                    "",
                    f"![历史消息列表截图]({rel_snap})" if rel_snap else "",
                ]
            ).strip() + "\n"
            md_path = sub_dir / "article.md"
            md_path.write_text(md_text, encoding="utf-8")
            exported_articles.append(
                {
                    "index": idx,
                    "title": item["title"],
                    "author": resolved_account,
                    "publish_time": "",
                    "source_url": "",
                    "markdown_rel_path": f"{sub_dir.name}/article.md",
                    "markdown_path": str(md_path),
                    "image_count": 1 if rel_snap else 0,
                    "mode": "account_feed_window_ocr",
                }
            )

        index_lines = [
            f"# {resolved_account} · 历史文章批量导出目录",
            "",
            f"- 导出时间: `{exported_at}`",
            f"- 发现文章数: `{len(capped_candidates) + len(ocr_scans)}` | 成功导出: `{len(exported_articles)}` | 失败: `{len(failed_articles)}`",
            "",
            "| # | 标题 | 发布时间 | 本地图片 | Markdown 文件 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in exported_articles:
            index_lines.append(
                f"| {row['index']} | {row['title']} | {row.get('publish_time') or '-'} | {row['image_count']} | [{row['markdown_rel_path']}]({row['markdown_rel_path']}) |"
            )
        if failed_articles:
            index_lines.extend(["", "## 跳过/失败列表", ""])
            for fail in failed_articles:
                index_lines.append(f"- #{fail['index']} `{fail.get('url', '')}`: {fail.get('error', '')}")
        index_md_path = bundle_dir / "INDEX.md"
        index_md_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")

        catalog = {
            "ok": len(exported_articles) > 0,
            "kind": "account_articles",
            "slug": bundle_dir.name,
            "accountName": resolved_account,
            "albumUrl": clean_album_url,
            "exportedAt": exported_at,
            "catalogDir": str(bundle_dir),
            "indexMarkdownPath": str(index_md_path),
            "totalDiscovered": len(capped_candidates) + len(ocr_scans),
            "exportedCount": len(exported_articles),
            "failedCount": len(failed_articles),
            "articles": exported_articles,
            "failedArticles": failed_articles,
        }
        catalog_path = bundle_dir / "account_catalog.json"
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        catalog["catalogJsonPath"] = str(catalog_path)
        return catalog

    def list_exported_accounts(self, limit: int = 20) -> List[Dict[str, Any]]:
        accounts_dir = self.export_root / "accounts"
        if not accounts_dir.exists():
            return []
        items: List[Dict[str, Any]] = []
        for cat_file in accounts_dir.glob("*/account_catalog.json"):
            try:
                items.append(json.loads(cat_file.read_text(encoding="utf-8")))
            except Exception:
                continue
        items.sort(key=lambda d: str(d.get("exportedAt", "")), reverse=True)
        return items[: max(1, int(limit))]

    # ------------------------------------------------------------------
    # WeChat Channels (视频号) Creator Video Downloader & Cache Scanner
    # ------------------------------------------------------------------

    @staticmethod
    def _is_mp4_or_mov_bytes(data: bytes) -> bool:
        return len(data) >= 12 and (data[4:8] == b"ftyp" or b"moov" in data[:64] or b"mdat" in data[:64])

    @staticmethod
    def _maybe_xor_decode_media(data: bytes, decode_key: Optional[Any] = None) -> Tuple[bytes, bool]:
        """Decode WeChat Channels encrypted media stream prefix when decode_key is explicitly supplied."""
        if len(data) < 12 or data[4:8] == b"ftyp":
            return data, False
        if decode_key in (None, "", 0, "0"):
            return data, False
        try:
            key_int = int(decode_key, 0) if isinstance(decode_key, str) else int(decode_key)
        except (TypeError, ValueError):
            return data, False
        if key_int <= 0:
            return data, False
        key_bytes = key_int.to_bytes(8, byteorder="little", signed=False)
        prefix_len = min(len(data), 131072)
        buf = bytearray(data)
        for i in range(prefix_len):
            buf[i] ^= key_bytes[i % 8]
        decoded = bytes(buf)
        if decoded[4:8] == b"ftyp":
            return decoded, True
        # Also test big-endian byte order fallback
        key_bytes_be = key_int.to_bytes(8, byteorder="big", signed=False)
        buf2 = bytearray(data)
        for i in range(prefix_len):
            buf2[i] ^= key_bytes_be[i % 8]
        decoded_be = bytes(buf2)
        if decoded_be[4:8] == b"ftyp":
            return decoded_be, True
        return data, False

    def export_channels_videos(
        self,
        *,
        author_name: str = "",
        video_items: Optional[List[Dict[str, Any]]] = None,
        video_urls: Optional[List[str]] = None,
        manifest_path: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
        scan_open_window: bool = False,
        scroll_pages: int = 4,
        download_media: bool = True,
        max_videos: int = 50,
    ) -> Dict[str, Any]:
        """Export WeChat Channels (视频号) creator videos via stream URLs/manifest, local media cache scan, or live window OCR."""
        resolved_author = (author_name or "").strip()
        candidates: List[Dict[str, Any]] = []

        if manifest_path is not None:
            mpath = Path(manifest_path)
            if not mpath.is_file():
                return {"ok": False, "error": f"Channels manifest not found: {mpath}"}
            raw = mpath.read_text(encoding="utf-8", errors="replace").strip()
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    if not resolved_author:
                        resolved_author = str(loaded.get("author") or loaded.get("authorName") or loaded.get("creator") or "").strip()
                    loaded_items = loaded.get("videos") or loaded.get("items") or []
                elif isinstance(loaded, list):
                    loaded_items = loaded
                else:
                    loaded_items = []
                for entry in loaded_items:
                    if isinstance(entry, dict):
                        candidates.append(entry)
                    elif isinstance(entry, str) and entry.strip():
                        candidates.append({"url": entry.strip()})
            except json.JSONDecodeError:
                for u in re.findall(r"https?://[^\s<>\"')]+", raw):
                    candidates.append({"url": u})

        for it in video_items or []:
            if isinstance(it, dict):
                candidates.append(dict(it))
        for raw_u in video_urls or []:
            u = str(raw_u or "").strip()
            if u:
                candidates.append({"url": u})

        exported_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        resolved_author = resolved_author or "微信视频号归档"
        bundle_dir = self.export_root / "channels" / f"{stamp}_{_slugify(resolved_author, 40)}"
        videos_dir = bundle_dir / "videos"
        covers_dir = bundle_dir / "covers"
        notes_dir = bundle_dir / "notes"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        videos_dir.mkdir(parents=True, exist_ok=True)
        covers_dir.mkdir(parents=True, exist_ok=True)
        notes_dir.mkdir(parents=True, exist_ok=True)

        exported_videos: List[Dict[str, Any]] = []
        failed_videos: List[Dict[str, Any]] = []
        seen_hashes: Set[str] = set()

        # 1) Remote / manifest video streams
        for idx, item in enumerate(candidates[: max(1, int(max_videos))], start=1):
            v_url = str(item.get("video_url") or item.get("url") or "").strip()
            c_url = str(item.get("cover_url") or item.get("thumb_url") or "").strip()
            title = str(item.get("title") or item.get("description") or f"视频号作品_{idx:03d}").strip()
            decode_key = item.get("decode_key") or item.get("decodeKey")
            pub_time = str(item.get("publish_time") or "").strip()
            duration = item.get("duration") or ""
            slug = _slugify(title, 36)

            rec: Dict[str, Any] = {
                "index": idx,
                "title": title,
                "author": resolved_author,
                "source_url": v_url,
                "cover_url": c_url,
                "publish_time": pub_time,
                "duration": duration,
                "video_rel_path": "",
                "video_abs_path": "",
                "cover_rel_path": "",
                "note_rel_path": "",
                "size_bytes": 0,
                "sha256": "",
                "xor_decoded": False,
                "mode": "stream_url",
                "ok": False,
            }

            if download_media and v_url:
                safe_ok, safe_err = _validate_safe_http_url(v_url, allow_loopback=self.allow_loopback_urls)
                if not safe_ok:
                    failed_videos.append({"index": idx, "url": v_url, "error": safe_err})
                    continue
                try:
                    req = urllib.request.Request(
                        v_url,
                        headers={
                            "User-Agent": DEFAULT_WECHAT_UA,
                            "Referer": "https://channels.weixin.qq.com/",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=25.0) as resp:
                        raw_bytes = _read_bounded_response(resp, MAX_VIDEO_BYTES)
                    decoded_bytes, was_decoded = self._maybe_xor_decode_media(raw_bytes, decode_key)
                    if not decoded_bytes:
                        raise ValueError("empty_video_response")
                    sha = hashlib.sha256(decoded_bytes).hexdigest()
                    if sha in seen_hashes:
                        continue
                    seen_hashes.add(sha)
                    out_mp4 = videos_dir / f"video_{idx:03d}_{slug}.mp4"
                    out_mp4.write_bytes(decoded_bytes)
                    rec.update(
                        {
                            "ok": True,
                            "video_rel_path": f"videos/{out_mp4.name}",
                            "video_abs_path": str(out_mp4),
                            "size_bytes": len(decoded_bytes),
                            "sha256": sha,
                            "xor_decoded": was_decoded,
                            "valid_mp4_header": self._is_mp4_or_mov_bytes(decoded_bytes),
                        }
                    )
                except Exception as exc:
                    failed_videos.append({"index": idx, "url": v_url, "error": str(exc)})
                    continue
            else:
                rec["ok"] = True
                rec["mode"] = "metadata_catalog_only"

            if c_url:
                csafe, _ = _validate_safe_http_url(c_url, allow_loopback=self.allow_loopback_urls)
                if csafe:
                    try:
                        creq = urllib.request.Request(c_url, headers={"User-Agent": DEFAULT_WECHAT_UA})
                        with urllib.request.urlopen(creq, timeout=15.0) as cresp:
                            cdata = _read_bounded_response(cresp, MAX_IMAGE_BYTES)
                            cct = cresp.headers.get("Content-Type", "")
                        if cdata:
                            cext = _guess_extension(c_url, content_type=cct, data=cdata)
                            cout = covers_dir / f"cover_{idx:03d}_{slug}.{cext}"
                            cout.write_bytes(cdata)
                            rec["cover_rel_path"] = f"covers/{cout.name}"
                    except Exception:
                        pass

            note_path = notes_dir / f"video_{idx:03d}_{slug}.md"
            note_path.write_text(
                "\n".join(
                    [
                        f"# {title}",
                        "",
                        f"- 视频号创作者: `{resolved_author}`",
                        f"- 发布时间: `{pub_time or '-'}` | 时长: `{duration or '-'}`",
                        f"- 本地视频文件: [{rec['video_rel_path'] or '仅元数据'}](../{rec['video_rel_path']})" if rec["video_rel_path"] else "- 本地视频文件: 未下载",
                        f"- SHA-256: `{rec['sha256']}`" if rec["sha256"] else "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            rec["note_rel_path"] = f"notes/{note_path.name}"
            exported_videos.append(rec)

        # 2) Local WeChat Channels / Finder cache scanner (mp4/mov or ftyp magic bytes)
        if cache_dir is not None:
            cdir = Path(cache_dir)
            if cdir.is_dir():
                for fp in sorted(cdir.rglob("*")):
                    if len(exported_videos) >= max_videos:
                        break
                    if not fp.is_file() or fp.stat().st_size < 16 or fp.stat().st_size > MAX_VIDEO_BYTES:
                        continue
                    is_ext = fp.suffix.lower() in (".mp4", ".mov", ".m4v")
                    head = fp.read_bytes()[:64]
                    if not is_ext and not self._is_mp4_or_mov_bytes(head):
                        continue
                    raw_v = fp.read_bytes()
                    sha = hashlib.sha256(raw_v).hexdigest()
                    if sha in seen_hashes:
                        continue
                    seen_hashes.add(sha)
                    idx = len(exported_videos) + 1
                    slug = _slugify(fp.stem, 32)
                    dest = videos_dir / f"cache_{idx:03d}_{slug}.mp4"
                    shutil.copy2(fp, dest)
                    note_path = notes_dir / f"cache_{idx:03d}_{slug}.md"
                    note_path.write_text(f"# {fp.name}\n\n- 来源缓存: `{fp}`\n- 文件大小: `{len(raw_v)}` bytes\n- SHA-256: `{sha}`\n", encoding="utf-8")
                    exported_videos.append(
                        {
                            "index": idx,
                            "title": fp.stem,
                            "author": resolved_author,
                            "source_path": str(fp),
                            "video_rel_path": f"videos/{dest.name}",
                            "video_abs_path": str(dest),
                            "cover_rel_path": "",
                            "note_rel_path": f"notes/{note_path.name}",
                            "size_bytes": len(raw_v),
                            "sha256": sha,
                            "mode": "local_cache_scan",
                            "ok": True,
                        }
                    )

        # 3) Live WeChat Channels window OCR + scroll cover capture
        if scan_open_window and not exported_videos:
            status = self.inspector._activate_and_get_status()
            windows = status.get("windows") or []
            if not windows:
                return {"ok": False, "error": "no_visible_wechat_window"}
            bounds = windows[0].get("bounds") or {}
            win_w = int(round(float(bounds.get("width", 1029))))
            win_h = int(round(float(bounds.get("height", 640))))
            seen_titles: Set[str] = set()
            for page_idx in range(1, max(1, int(scroll_pages)) + 1):
                if page_idx > 1:
                    self.inspector._run_native(
                        ["scroll", "--rx", "0.52", "--ry", "0.55", "--dy", "-420", "--units", "pixel", "--steps", "5"],
                        6.0,
                    )
                    time.sleep(0.45)
                cover_shot = covers_dir / f"channels_page_{page_idx:02d}.png"
                ocr = self.inspector._run_native(["capture-ocr", "--out", str(cover_shot)], 15.0)
                lines = self._group_ocr_lines(
                    ocr.get("elements") or [],
                    x_min=20.0,
                    y_min=52.0,
                    y_max=max(140.0, win_h - 40.0),
                )
                for ln in lines:
                    txt = str(ln.get("text") or "").strip()
                    if len(txt) < 4 or txt in seen_titles:
                        continue
                    seen_titles.add(txt)
                    idx = len(exported_videos) + 1
                    note_path = notes_dir / f"ocr_{idx:03d}_{_slugify(txt, 28)}.md"
                    note_path.write_text(
                        f"# {txt}\n\n- 视频号创作者: `{resolved_author}`\n- 页码截图: ![cover](../covers/{cover_shot.name})\n",
                        encoding="utf-8",
                    )
                    exported_videos.append(
                        {
                            "index": idx,
                            "title": txt,
                            "author": resolved_author,
                            "video_rel_path": "",
                            "cover_rel_path": f"covers/{cover_shot.name}",
                            "note_rel_path": f"notes/{note_path.name}",
                            "size_bytes": 0,
                            "mode": "channels_window_ocr",
                            "ok": True,
                        }
                    )
                    if len(exported_videos) >= max_videos:
                        break

        if not exported_videos and not failed_videos:
            return {
                "ok": False,
                "error": "no_channels_videos_discovered",
                "hint": "Provide manifest_path, video_items/video_urls, cache_dir, or scan_open_window=True.",
            }

        idx_lines = [
            f"# {resolved_author} · 微信视频号全部视频导出目录",
            "",
            f"- 导出时间: `{exported_at}`",
            f"- 导出条目数: `{len(exported_videos)}` | 失败: `{len(failed_videos)}`",
            "",
            "| # | 视频标题 | 提取模式 | 文件大小 | 本地视频 / 封面 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in exported_videos:
            media_link = f"[{row['video_rel_path']}]({row['video_rel_path']})" if row.get("video_rel_path") else (f"[{row['cover_rel_path']}]({row['cover_rel_path']})" if row.get("cover_rel_path") else "-")
            idx_lines.append(
                f"| {row['index']} | {row['title']} | `{row['mode']}` | {row.get('size_bytes', 0)} B | {media_link} |"
            )
        index_md_path = bundle_dir / "CHANNELS_INDEX.md"
        index_md_path.write_text("\n".join(idx_lines) + "\n", encoding="utf-8")

        catalog = {
            "ok": len(exported_videos) > 0,
            "kind": "channels_videos",
            "slug": bundle_dir.name,
            "authorName": resolved_author,
            "exportedAt": exported_at,
            "bundleDir": str(bundle_dir),
            "videosDir": str(videos_dir),
            "coversDir": str(covers_dir),
            "indexMarkdownPath": str(index_md_path),
            "exportedCount": len(exported_videos),
            "failedCount": len(failed_videos),
            "videos": exported_videos,
            "failedVideos": failed_videos,
        }
        cat_path = bundle_dir / "channels_catalog.json"
        cat_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        catalog["catalogJsonPath"] = str(cat_path)
        return catalog

    def list_exported_channels(self, limit: int = 20) -> List[Dict[str, Any]]:
        channels_dir = self.export_root / "channels"
        if not channels_dir.exists():
            return []
        items: List[Dict[str, Any]] = []
        for cat_file in channels_dir.glob("*/channels_catalog.json"):
            try:
                items.append(json.loads(cat_file.read_text(encoding="utf-8")))
            except Exception:
                continue
        items.sort(key=lambda d: str(d.get("exportedAt", "")), reverse=True)
        return items[: max(1, int(limit))]
