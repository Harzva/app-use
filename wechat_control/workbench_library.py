"""Read-only views of the independent workbench profile's existing local records."""
from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

_LIMIT = 40
_MAX_JSON = 8 * 1024 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


@contextmanager
def _within(root, path, *, directory=False):
    """Open with no symlink following, relative to the candidate's profile."""
    parts = path.relative_to(root).parts
    if any(part == ".." for part in parts):
        raise ValueError("path outside candidate profile")
    if not parts and not directory:
        raise ValueError("file is the candidate root")
    fd = os.open(root, _DIR_FLAGS)
    try:
        for idx, part in enumerate(parts):
            nxt = os.open(
                part, _DIR_FLAGS if directory or idx < len(parts) - 1 else _FILE_FLAGS,
                dir_fd=fd,
            )
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def _load(root, path):
    try:
        with _within(root, path) as fd:
            f = os.fstat(fd)
            if not stat.S_ISREG(f.st_mode) or f.st_size > _MAX_JSON:
                return {}
            with os.fdopen(os.dup(fd), "rb") as reader:
                raw = reader.read(_MAX_JSON + 1)
        value = json.loads(raw) if len(raw) <= _MAX_JSON else None
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _project(row, strings=(), numbers=(), flags=()):
    if not isinstance(row, dict):
        return {}
    return {
        **{key: row[key][:256] for key in strings if isinstance(row.get(key), str)},
        **{key: row[key] for key in numbers if type(row.get(key)) is int},
        **{key: row[key] for key in flags if type(row.get(key)) is bool},
    }


def _archive(root, catalog_dir, filename, date_field, strings, numbers=(), *, excluded=()):
    try:
        with _within(root, catalog_dir, directory=True) as fd:
            folders = sorted(
                (name for name in os.listdir(fd) if not name.startswith(".") and name not in excluded),
                reverse=True,
            )[:512]
    except (OSError, ValueError):
        return []
    items = [
        _project(_load(root, catalog_dir / folder / filename), strings, numbers)
        for folder in folders
    ]
    return sorted(
        (item for item in items if item), key=lambda item: item.get(date_field, ""), reverse=True
    )[:_LIMIT]


def records(engine, view):
    engine._require("status")
    root = engine.auth_gate.auth_file.absolute().parent
    if view == "contacts":
        data = _load(root, engine.bindings.bindings_file.absolute()).get("bindings")
        projected = [
            _project(row, ("target", "alias", "role", "careLevel", "updatedAt"), flags=("specialCare",))
            for row in (data.values() if isinstance(data, dict) else [])
        ]
        projected = sorted(
            (row for row in projected if row.get("target")),
            key=lambda row: row.get("updatedAt", ""), reverse=True,
        )
        # Keep fields expected by the existing Contacts view.
        return {"contacts": [{"alias": "", "role": ""} | row for row in projected]}
    if view == "archive":
        exports = engine.article_exporter.export_root.absolute()
        return {
            "articles": _archive(root, exports, "metadata.json", "exported_at",
                                 ("title", "account", "exported_at"), ("downloaded_image_count",),
                                 excluded=("accounts", "channels")),
            "accounts": _archive(root, exports / "accounts", "account_catalog.json", "exportedAt",
                                 ("accountName", "exportedAt"),
                                 ("totalDiscovered", "exportedCount", "failedCount")),
            "channels": _archive(root, exports / "channels", "channels_catalog.json", "exportedAt",
                                 ("authorName", "exportedAt"), ("exportedCount", "failedCount")),
        }
    if view == "soul":
        store = _load(root, engine.soul_profiler.store_path.absolute())
        profiles = store.get("contactProfiles")
        rows = [
            _project(row, ("target", "matchedTitle", "role", "careLevel", "personalityTag",
                           "mbtiEstimate"), ("rapportScore",), ("bound",))
            for row in (profiles.values() if isinstance(profiles, dict) else [])
        ]
        return {
            "generatedAt": _project(store, ("updatedAt",)).get("updatedAt", ""),
            "ownerProfile": _project(store.get("ownerProfile"), ("archetypeTag", "mbtiEstimate")),
            "contactProfiles": [row for row in rows if row.get("target") or row.get("matchedTitle")][:_LIMIT],
        }
    if view == "models":
        # A catalog from the loaded local configuration, not a sync/probe.
        state = engine.models.state
        providers = state.get("providers") or {}
        return {
            "source": "local-configuration",
            "networkChecked": False,
            **_project(state, ("activeProviderId", "activeModelId", "fallbackModelId"),
                       flags=("llmReplyEnabled",)),
            "providers": [
                _project(row, ("id", "name", "vendor", "defaultModel"), flags=("enabled", "isGateway"))
                for row in providers.values() if isinstance(row, dict)
            ][:_LIMIT],
        }
    raise ValueError("unknown read-only workbench view")
