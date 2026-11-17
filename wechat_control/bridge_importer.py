"""WeChatBridge-compatible chat history archive (.zip / 聊天记录.txt) importer.

Ported and extended from freestylefly/WeChatBridge:
- WeChatNativeArchive.swift (safe in-memory ZIP inspection, path traversal guard, CRC verification)
- WeChatForward.swift (WeChatTranscriptRecord.parse supporting WeChat 4.x native `·Sender` format)
Also supports classic `Sender YYYY-MM-DD HH:MM:SS` exported chat logs and exports Obsidian-ready
Markdown + Agent/RAG-ready JSONL bundles.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class UnsafeArchiveError(ValueError):
    """Raised when a ZIP archive fails path traversal or structural safety checks."""


@dataclass
class TranscriptRecord:
    """Single parsed message record inside a forwarded or exported WeChat transcript."""

    index: int
    sender: str
    timestamp: str
    content: str
    msg_type: str = "text"
    attachments: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "sender": self.sender,
            "timestamp": self.timestamp,
            "msg_type": self.msg_type,
            "content": self.content,
            "attachments": self.attachments,
        }


@dataclass
class ArchiveAttachment:
    """Metadata and digest for an attachment inside a forwarded WeChat archive."""

    relative_path: str
    size_bytes: int
    sha256: str
    extension: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "extension": self.extension,
        }


@dataclass
class TranscriptBundle:
    """Complete parsed WeChat transcript package with records and verified attachments."""

    source_path: str
    source_sha256: str
    transcript_entry: str
    participants: List[str]
    records: List[TranscriptRecord]
    attachments: List[ArchiveAttachment]
    raw_text: str

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "transcript_entry": self.transcript_entry,
            "participants": self.participants,
            "record_count": len(self.records),
            "attachment_count": len(self.attachments),
            "records": [r.to_dict() for r in self.records],
            "attachments": [a.to_dict() for a in self.attachments],
        }
        if include_raw:
            data["raw_text"] = self.raw_text
        return data


# WeChat 4.x native archive header pattern:
# ·发送者
# 2026年11月15日 09:30
_WECHAT4_RECORD_RE = re.compile(
    r"(?m)^·([^\n]+)\n(\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}(?::\d{2})?)\n"
)

# Classic text log header pattern:
# 发送者 2026-11-15 09:30:12  OR  发送者 2026/11/15 09:30
_CLASSIC_RECORD_RE = re.compile(
    r"(?m)^([^\n:：]{1,64}?)\s+(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s*\n"
)

_IMAGE_TAG_RE = re.compile(r"\[(?:图片|Image|Photo)(?:[:：]\s*([^\]]+))?\]", re.IGNORECASE)
_FILE_TAG_RE = re.compile(r"\[(?:文件|File|附件)(?:[:：]\s*([^\]]+))?\]", re.IGNORECASE)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _infer_msg_type_and_refs(content: str, known_attachments: List[str]) -> Tuple[str, List[str]]:
    refs: List[str] = []
    msg_type = "text"

    img_matches = _IMAGE_TAG_RE.findall(content)
    file_matches = _FILE_TAG_RE.findall(content)

    if img_matches:
        msg_type = "image"
        for m in img_matches:
            if m.strip():
                refs.append(m.strip())
    if file_matches:
        msg_type = "file" if msg_type == "text" else "mixed"
        for m in file_matches:
            if m.strip():
                refs.append(m.strip())

    for att in known_attachments:
        base = Path(att).name
        if base and base in content and att not in refs:
            refs.append(att)

    return msg_type, refs


def validate_zip_member_name(name: str, seen_canonical: Dict[str, str]) -> str:
    """Enforce WeChatNativeArchive.swift path-traversal and alias collision protections."""
    if not name or "\\" in name or ":" in name:
        raise UnsafeArchiveError(f"Rejected unsafe archive entry path: {name!r}")
    if any(unicodedata.category(ch).startswith("C") for ch in name):
        raise UnsafeArchiveError(f"Rejected control characters in archive path: {name!r}")

    trimmed = name[:-1] if name.endswith("/") else name
    parts = trimmed.split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise UnsafeArchiveError(f"Rejected path traversal / empty component in entry: {name!r}")

    for idx in range(1, len(parts) + 1):
        prefix = "/".join(parts[:idx])
        canon = unicodedata.normalize("NFC", prefix).lower()
        prior = seen_canonical.get(canon)
        if prior is not None and prior != prefix:
            raise UnsafeArchiveError(
                f"Rejected case/normalization alias collision: {prefix!r} vs {prior!r}"
            )
        seen_canonical[canon] = prefix

    return trimmed


def parse_transcript_text(body: str, known_attachments: Optional[List[str]] = None) -> List[TranscriptRecord]:
    """Parse WeChat 4.x native (`·Sender\\nYYYY年M月D日 HH:MM`) or classic transcript text."""
    attachments = known_attachments or []
    cleaned = body.replace("\r\n", "\n").lstrip("\ufeff").strip("\n")
    if not cleaned:
        return []

    matches = list(_WECHAT4_RECORD_RE.finditer(cleaned))
    if not matches:
        matches = list(_CLASSIC_RECORD_RE.finditer(cleaned))

    records: List[TranscriptRecord] = []
    if matches:
        for i, m in enumerate(matches):
            sender = m.group(1).strip()
            ts = m.group(2).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
            content = cleaned[start:end].strip()
            msg_type, refs = _infer_msg_type_and_refs(content, attachments)
            records.append(
                TranscriptRecord(
                    index=i + 1,
                    sender=sender,
                    timestamp=ts,
                    content=content,
                    msg_type=msg_type,
                    attachments=refs,
                )
            )
        return records

    # Fallback: line-by-line non-empty blocks
    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip() and not ln.strip().startswith("-----")]
    for i, ln in enumerate(lines):
        msg_type, refs = _infer_msg_type_and_refs(ln, attachments)
        records.append(
            TranscriptRecord(
                index=i + 1,
                sender="unknown",
                timestamp="",
                content=ln,
                msg_type=msg_type,
                attachments=refs,
            )
        )
    return records


class WeChatBridgeImporter:
    """Imports WeChat merged-forward `.zip` bundles, `.txt` transcripts, or extracted folders."""

    MAX_TOTAL_EXPANDED_BYTES = 512 * 1024 * 1024  # 512 MiB
    MAX_TEXT_ENTRY_BYTES = 16 * 1024 * 1024       # 16 MiB

    def load(self, source: Path) -> TranscriptBundle:
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(f"Chatlog source not found: {src}")
        if src.is_dir():
            return self._load_directory(src)
        if src.suffix.lower() == ".zip":
            return self._load_zip(src)
        return self._load_text_file(src)

    def _load_text_file(self, txt_path: Path) -> TranscriptBundle:
        raw_bytes = txt_path.read_bytes()
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        records = parse_transcript_text(text)
        participants = sorted({r.sender for r in records if r.sender and r.sender != "unknown"})
        return TranscriptBundle(
            source_path=str(txt_path),
            source_sha256=_sha256_bytes(raw_bytes),
            transcript_entry=txt_path.name,
            participants=participants,
            records=records,
            attachments=[],
            raw_text=text,
        )

    def _load_directory(self, folder: Path) -> TranscriptBundle:
        txt_candidates: List[Path] = []
        attachments: List[ArchiveAttachment] = []
        for item in sorted(folder.rglob("*")):
            if not item.is_file():
                continue
            rel = str(item.relative_to(folder))
            if item.suffix.lower() == ".txt":
                txt_candidates.append(item)
            else:
                data = item.read_bytes()
                attachments.append(
                    ArchiveAttachment(
                        relative_path=rel,
                        size_bytes=len(data),
                        sha256=_sha256_bytes(data),
                        extension=item.suffix.lower(),
                    )
                )

        if not txt_candidates:
            raise FileNotFoundError(f"No .txt transcript found inside directory: {folder}")

        chosen = next((p for p in txt_candidates if p.name == "聊天记录.txt"), txt_candidates[0])
        raw_bytes = chosen.read_bytes()
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        records = parse_transcript_text(text, [a.relative_path for a in attachments])
        participants = sorted({r.sender for r in records if r.sender and r.sender != "unknown"})
        return TranscriptBundle(
            source_path=str(folder),
            source_sha256=_sha256_bytes(raw_bytes),
            transcript_entry=str(chosen.relative_to(folder)),
            participants=participants,
            records=records,
            attachments=attachments,
            raw_text=text,
        )

    def _load_zip(self, zip_path: Path) -> TranscriptBundle:
        zip_bytes = zip_path.read_bytes()
        zip_sha = _sha256_bytes(zip_bytes)

        seen_canonical: Dict[str, str] = {}
        total_expanded = 0
        txt_entries: List[Tuple[str, str, List[TranscriptRecord]]] = []
        attachments: List[ArchiveAttachment] = []

        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()
            if not infos:
                raise UnsafeArchiveError("Archive is empty.")

            # Validate all member paths and uncompressed sizes before reading content
            valid_files: List[zipfile.ZipInfo] = []
            for info in infos:
                clean_rel = validate_zip_member_name(info.filename, seen_canonical)
                total_expanded += info.file_size
                if total_expanded > self.MAX_TOTAL_EXPANDED_BYTES:
                    raise UnsafeArchiveError("Archive expanded size exceeds safety limit.")
                if info.is_dir():
                    continue
                valid_files.append(info)

            att_names = [
                inf.filename for inf in valid_files
                if not inf.filename.lower().endswith(".txt")
            ]

            for info in valid_files:
                data = zf.read(info.filename)
                if info.filename.lower().endswith(".txt") and len(data) <= self.MAX_TEXT_ENTRY_BYTES:
                    text = data.decode("utf-8-sig", errors="replace")
                    recs = parse_transcript_text(text, att_names)
                    txt_entries.append((info.filename, text, recs))
                else:
                    attachments.append(
                        ArchiveAttachment(
                            relative_path=info.filename,
                            size_bytes=len(data),
                            sha256=_sha256_bytes(data),
                            extension=Path(info.filename).suffix.lower(),
                        )
                    )

        if not txt_entries:
            raise ValueError(f"No .txt transcript found inside archive: {zip_path}")

        native = next((item for item in txt_entries if Path(item[0]).name == "聊天记录.txt"), None)
        chosen_entry, chosen_text, chosen_records = native or max(txt_entries, key=lambda x: len(x[2]))
        participants = sorted({r.sender for r in chosen_records if r.sender and r.sender != "unknown"})

        return TranscriptBundle(
            source_path=str(zip_path),
            source_sha256=zip_sha,
            transcript_entry=chosen_entry,
            participants=participants,
            records=chosen_records,
            attachments=attachments,
            raw_text=chosen_text,
        )

    @staticmethod
    def export_markdown(bundle: TranscriptBundle, output_path: Path) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(timezone.utc).isoformat()
        participants_yaml = ", ".join(json.dumps(p, ensure_ascii=False) for p in bundle.participants)
        lines: List[str] = [
            "---",
            f"source_path: {json.dumps(bundle.source_path, ensure_ascii=False)}",
            f"source_sha256: {bundle.source_sha256}",
            f"transcript_entry: {json.dumps(bundle.transcript_entry, ensure_ascii=False)}",
            f"participants: [{participants_yaml}]",
            f"record_count: {len(bundle.records)}",
            f"attachment_count: {len(bundle.attachments)}",
            f"imported_at: {now_iso}",
            "---",
            "",
            f"# 微信聊天记录导入 ({len(bundle.records)} 条)",
            "",
        ]
        for rec in bundle.records:
            header = f"### {rec.index}. {rec.sender}"
            if rec.timestamp:
                header = f"{header} — {rec.timestamp}"
            lines.append(header)
            lines.append("")
            lines.append(rec.content or f"[{rec.msg_type}]")
            if rec.attachments:
                att_str = ", ".join(rec.attachments)
                lines.append("")
                lines.append(f"> 附件: {att_str}")
            lines.append("")

        if bundle.attachments:
            lines.append("## 附件清单")
            lines.append("")
            for att in bundle.attachments:
                lines.append(f"- `{att.relative_path}` ({att.size_bytes} bytes, sha256: `{att.sha256[:16]}...`)")
            lines.append("")

        out.write_text("\n".join(lines), encoding="utf-8")
        return out

    @staticmethod
    def export_jsonl(bundle: TranscriptBundle, output_path: Path) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for rec in bundle.records:
                payload = rec.to_dict()
                payload["source_sha256"] = bundle.source_sha256
                payload["transcript_entry"] = bundle.transcript_entry
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return out
