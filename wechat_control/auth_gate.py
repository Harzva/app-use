"""Bot Studio fail-closed authorization gate for the standalone WeChat RPA plugin."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ALL_CAPABILITIES = (
    "status",
    "ocr",
    "read_sessions",
    "read_contacts",
    "read_messages",
    "import_chatlog",
    "send_text_dry_run",
    "send_text_live",
)

READ_ONLY_CAPABILITIES = (
    "status",
    "ocr",
    "read_sessions",
    "read_contacts",
    "read_messages",
    "import_chatlog",
)

DEFAULT_GRANT_CAPABILITIES = READ_ONLY_CAPABILITIES + ("send_text_dry_run",)


class StudioPluginUnauthorizedError(PermissionError):
    """Raised when Bot Studio has not authorized (or has revoked) a WeChat capability."""

    def __init__(self, message: str, capability: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = "STUDIO_PLUGIN_UNAUTHORIZED"
        self.capability = capability


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StudioAuthGate:
    """Manages explicit Bot Studio authorization receipts on disk (`config/studio_auth.json`)."""

    auth_file: Path

    def get_state(self) -> Dict[str, Any]:
        if not self.auth_file.exists():
            return {
                "schema": "openbot.studio-plugin-auth/1",
                "pluginId": "openbot.plugin.wechat-rpa-control",
                "authorized": False,
                "grantId": None,
                "authorizedBy": None,
                "capabilities": [],
                "updatedAt": None,
                "reason": "Plugin has not been authorized in Bot Studio yet.",
                "digestSha256": None,
            }
        try:
            raw = self.auth_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("auth state must be a JSON object")
            return data
        except Exception as exc:
            return {
                "schema": "openbot.studio-plugin-auth/1",
                "pluginId": "openbot.plugin.wechat-rpa-control",
                "authorized": False,
                "grantId": None,
                "capabilities": [],
                "reason": f"Fail-closed due to invalid auth receipt: {exc}",
            }

    @staticmethod
    def _compute_digest(payload: Dict[str, Any]) -> str:
        clean = {k: v for k, v in payload.items() if k != "digestSha256"}
        canonical = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _write_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        state = dict(state)
        state["digestSha256"] = self._compute_digest(state)
        self.auth_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return state

    def grant(
        self,
        capabilities: Optional[Iterable[str]] = None,
        *,
        authorized_by: str = "bot-studio-owner",
        note: str = "",
    ) -> Dict[str, Any]:
        if capabilities is None:
            selected = list(DEFAULT_GRANT_CAPABILITIES)
        else:
            raw_list = [str(c).strip() for c in capabilities if str(c).strip()]
            if "*" in raw_list or "all" in raw_list:
                selected = list(ALL_CAPABILITIES)
            else:
                invalid = [c for c in raw_list if c not in ALL_CAPABILITIES]
                if invalid:
                    raise ValueError(f"Unsupported capabilities requested: {invalid}")
                selected = sorted(set(raw_list), key=lambda x: ALL_CAPABILITIES.index(x))

        payload: Dict[str, Any] = {
            "schema": "openbot.studio-plugin-auth/1",
            "pluginId": "openbot.plugin.wechat-rpa-control",
            "authorized": True,
            "grantId": f"stgrant_{uuid.uuid4().hex}",
            "authorizedBy": authorized_by,
            "capabilities": selected,
            "note": note,
            "updatedAt": _utc_iso_now(),
        }
        return self._write_state(payload)

    def revoke(self, *, reason: str = "Revoked by Bot Studio user") -> Dict[str, Any]:
        prev = self.get_state()
        payload: Dict[str, Any] = {
            "schema": "openbot.studio-plugin-auth/1",
            "pluginId": "openbot.plugin.wechat-rpa-control",
            "authorized": False,
            "grantId": prev.get("grantId"),
            "authorizedBy": prev.get("authorizedBy"),
            "capabilities": [],
            "note": reason,
            "updatedAt": _utc_iso_now(),
        }
        return self._write_state(payload)

    def is_allowed(self, capability: str) -> bool:
        state = self.get_state()
        if state.get("authorized") is not True:
            return False
        caps = state.get("capabilities") or []
        return capability in caps or "*" in caps

    def require_capability(self, capability: str) -> Dict[str, Any]:
        state = self.get_state()
        if state.get("authorized") is not True:
            raise StudioPluginUnauthorizedError(
                f"Bot Studio plugin authorization is disabled/revoked; capability '{capability}' denied.",
                capability=capability,
            )
        caps: List[str] = list(state.get("capabilities") or [])
        if capability not in caps and "*" not in caps:
            raise StudioPluginUnauthorizedError(
                f"Bot Studio grant '{state.get('grantId')}' does not include capability '{capability}'.",
                capability=capability,
            )
        return state
