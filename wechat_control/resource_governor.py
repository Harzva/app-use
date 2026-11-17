"""资源治理：24h 长驻运行的日志轮转与孤儿快照清理。

长期运行的三类增长源（磁盘体检结论）：
1. audit.jsonl 每次引擎操作追加、无轮转——超限后归档一代；
2. monitor_events.jsonl 非重复事件持续追加——同上；
3. nav_{联系人}_*.png 孤儿快照：联系人移除后永不清理——按 mtime 清理。
固定名覆盖写快照（monitor_poll_cur.png 等）不增长，不触碰。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List

from .io_utils import atomic_write_text

DEFAULT_JSONL_MAX_BYTES = 5 * 1024 * 1024   # 5MB 触发轮转
DEFAULT_SNAPSHOT_MAX_AGE_DAYS = 7.0          # 孤儿快照保留 7 天


def rotate_jsonl(path: Path | str, *, max_bytes: int = DEFAULT_JSONL_MAX_BYTES) -> Dict[str, Any]:
    """超限 JSONL 归档一代：path -> path.old（覆盖上一代归档），主文件清空续写。

    返回 {"rotated": bool, "sizeBytes": int, "archivedTo": str|None}。
    读侧（诊断尾部 20 条）在轮转瞬间仍能看到完整行——先写归档再清空，无截断窗口。
    """
    target = Path(path)
    if not target.exists():
        return {"rotated": False, "sizeBytes": 0, "archivedTo": None}
    size = target.stat().st_size
    if size < max_bytes:
        return {"rotated": False, "sizeBytes": size, "archivedTo": None}
    archive = target.with_name(target.name + ".old")
    # 先落归档，再原子清空主文件（避免清空成功但归档失败导致数据丢失）
    data = target.read_bytes()
    atomic_write_text(archive, data.decode("utf-8", "replace"))
    atomic_write_text(target, "")
    return {"rotated": True, "sizeBytes": size, "archivedTo": str(archive)}


def prune_orphan_snapshots(
    directory: Path | str,
    *,
    max_age_days: float = DEFAULT_SNAPSHOT_MAX_AGE_DAYS,
    protected_prefixes: tuple = (),
    now_ts: float | None = None,
) -> Dict[str, Any]:
    """清理超龄快照（默认 7 天）。固定名覆盖写文件也会被超龄清理——它们可随时重拍。

    protected_prefixes 中的文件永不清理（如 benchmark 用的合成图）。
    """
    d = Path(directory)
    now = now_ts if now_ts is not None else time.time()
    cutoff = now - max_age_days * 86400.0
    removed: List[str] = []
    freed_bytes = 0
    if not d.is_dir():
        return {"removed": removed, "freedBytes": 0, "scanned": 0}
    scanned = 0
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        scanned += 1
        if any(f.name.startswith(p) for p in protected_prefixes):
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            try:
                freed_bytes += f.stat().st_size
                f.unlink()
                removed.append(f.name)
            except OSError:
                pass
    return {"removed": removed, "freedBytes": freed_bytes, "scanned": scanned}


def govern(
    root: Path | str,
    *,
    jsonl_max_bytes: int = DEFAULT_JSONL_MAX_BYTES,
    snapshot_max_age_days: float = DEFAULT_SNAPSHOT_MAX_AGE_DAYS,
    now_ts: float | None = None,
) -> Dict[str, Any]:
    """对 logs/ 执行一轮治理，返回报告（可进 diagnostics/事件流）。"""
    root = Path(root)
    logs = root / "logs"
    report: Dict[str, Any] = {"ok": True, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    for name in ("audit.jsonl", "monitor_events.jsonl"):
        report[f"rotate_{name}"] = rotate_jsonl(logs / name, max_bytes=jsonl_max_bytes)
    snap_dir = logs / "snapshots"
    report["snapshots"] = prune_orphan_snapshots(
        snap_dir,
        max_age_days=snapshot_max_age_days,
        protected_prefixes=("synth_",),
        now_ts=now_ts,
    )
    report["freedTotalBytes"] = (
        (report["snapshots"].get("freedBytes") or 0)
        + sum(
            (report.get(f"rotate_{n}") or {}).get("sizeBytes", 0)
            for n in ("audit.jsonl", "monitor_events.jsonl")
            if (report.get(f"rotate_{n}") or {}).get("rotated")
        )
    )
    return report
