"""统一原子写工具：全仓 JSON/文本状态落盘的唯一入口。

崩溃安全：先写同目录临时文件，再 os.replace 原子替换——
任何时刻磁盘上的目标文件要么是完整旧版，要么是完整新版，绝不出现半截 JSON。
（hosting_state 曾因非原子写导致状态丢失，本模块即为此问题的全仓收口。）
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> Path:
    """原子写文本：同目录唯一 tmp + os.replace（同文件系统内原子）。

    tmp 带进程/线程/随机后缀：并发写同一路径的调用方互不踩踏。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, target)
    return target


def atomic_write_json(
    path: Path | str,
    data: Any,
    *,
    indent: int | None = 2,
    newline: bool = True,
    ensure_ascii: bool = False,
) -> Path:
    """原子写 JSON：序列化失败不会破坏旧文件（先序列化再落盘）。"""
    payload = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    if newline:
        payload += "\n"
    return atomic_write_text(path, payload)
