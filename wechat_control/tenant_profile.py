"""Tenant profile persistence and L1 sales-pack loader for zero-FDE onboarding."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .io_utils import atomic_write_json
from .safety import normalize_chat_name

TENANT_PROFILE_SCHEMA = "openbot.tenant-profile/1"
CUSTOMER_BUILD_MARKER = "customer_build.marker"
VALID_MODES = ("legacy", "customer")
DEFAULT_INDUSTRY_PACK = "general_sales"
DEFAULT_ADMIN_CONTACTS: Tuple[str, ...] = ("文件传输助手",)
_DEFAULT_BUNDLE_ROOT = Path(__file__).resolve().parent.parent

_FIELD_ALIASES: Dict[str, str] = {
    "mode": "mode",
    "owner_name": "ownerName",
    "ownerName": "ownerName",
    "owner_aliases": "ownerAliases",
    "ownerAliases": "ownerAliases",
    "business_name": "businessName",
    "businessName": "businessName",
    "product_summary": "productSummary",
    "productSummary": "productSummary",
    "industry_pack": "industryPack",
    "industryPack": "industryPack",
    "onboarding_completed": "onboardingCompleted",
    "onboardingCompleted": "onboardingCompleted",
    "admin_contacts": "adminContacts",
    "adminContacts": "adminContacts",
    "test_contacts": "testContacts",
    "testContacts": "testContacts",
}


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_contact_or_alias(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    norm = normalize_chat_name(raw)
    return norm or raw


def _dedupe_str_list(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        items: Iterable[Any] = [part for part in re.split(r"[,，;\n]+", values) if part.strip()]
    elif isinstance(values, Iterable):
        items = values
    else:
        return []
    result: List[str] = []
    seen: set[str] = set()
    for item in items:
        clean = _clean_contact_or_alias(item)
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


class TenantProfileStore:
    """Thread-safe atomic JSON store for tenant identity, mode, and contact scopes."""

    def __init__(
        self,
        config_path: Path | str,
        *,
        bundle_root: Optional[Path | str] = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.bundle_root = Path(bundle_root) if bundle_root is not None else _DEFAULT_BUNDLE_ROOT
        self._lock = threading.Lock()

    def _has_customer_marker(self) -> bool:
        return (self.bundle_root / CUSTOMER_BUILD_MARKER).exists()

    def _default_mode(self) -> str:
        return "customer" if self._has_customer_marker() else "legacy"

    def _default_profile(self) -> Dict[str, Any]:
        return {
            "schema": TENANT_PROFILE_SCHEMA,
            "mode": self._default_mode(),
            "ownerName": "",
            "ownerAliases": [],
            "businessName": "",
            "productSummary": "",
            "industryPack": DEFAULT_INDUSTRY_PACK,
            "onboardingCompleted": False,
            "adminContacts": list(DEFAULT_ADMIN_CONTACTS),
            "testContacts": [],
            "updatedAt": "",
        }

    def _normalize_profile(self, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        profile = self._default_profile()
        if not isinstance(raw, dict):
            return profile

        raw_mode = raw.get("mode")
        if raw_mode in VALID_MODES:
            profile["mode"] = str(raw_mode)
        if self._has_customer_marker() and raw_mode not in VALID_MODES:
            profile["mode"] = "customer"

        profile["ownerName"] = str(raw.get("ownerName") or "").strip()
        profile["ownerAliases"] = _dedupe_str_list(raw.get("ownerAliases"))
        profile["businessName"] = str(raw.get("businessName") or "").strip()
        profile["productSummary"] = str(raw.get("productSummary") or "").strip()
        pack = str(raw.get("industryPack") or "").strip()
        profile["industryPack"] = pack or DEFAULT_INDUSTRY_PACK
        profile["onboardingCompleted"] = bool(raw.get("onboardingCompleted", False))

        if "adminContacts" in raw and raw["adminContacts"] is not None:
            profile["adminContacts"] = _dedupe_str_list(raw.get("adminContacts"))
        else:
            profile["adminContacts"] = list(DEFAULT_ADMIN_CONTACTS)

        profile["testContacts"] = _dedupe_str_list(raw.get("testContacts"))
        profile["updatedAt"] = str(raw.get("updatedAt") or "").strip()
        return profile

    def _load_unlocked(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return self._default_profile()
        try:
            doc = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_profile()
        return self._normalize_profile(doc if isinstance(doc, dict) else None)

    def _save_unlocked(self, data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize_profile(data)
        normalized["schema"] = TENANT_PROFILE_SCHEMA
        normalized["updatedAt"] = _utc_iso_now()
        atomic_write_json(self.config_path, normalized)
        return dict(normalized)

    def load(self) -> Dict[str, Any]:
        """Load and normalize the tenant profile from disk without mutating it."""
        with self._lock:
            return dict(self._load_unlocked())

    def save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate, normalize, and atomically persist the given profile dictionary."""
        if not isinstance(data, dict):
            raise ValueError("Tenant profile data must be a dictionary.")
        if "mode" in data and data["mode"] is not None and data["mode"] not in VALID_MODES:
            raise ValueError(f"Unsupported tenant mode: {data['mode']!r}")
        with self._lock:
            return self._save_unlocked(data)

    def get_profile(self) -> Dict[str, Any]:
        """Return the current normalized tenant profile."""
        return self.load()

    def update_profile(self, **kwargs: Any) -> Dict[str, Any]:
        """Merge partial profile updates and persist atomically."""
        with self._lock:
            current = self._load_unlocked()
            for key, value in kwargs.items():
                if key in ("schema", "updatedAt"):
                    continue
                canonical = _FIELD_ALIASES.get(key)
                if canonical is None:
                    raise ValueError(f"Unknown tenant profile field: {key!r}")
                if canonical == "mode":
                    if value not in VALID_MODES:
                        raise ValueError(f"Unsupported tenant mode: {value!r}")
                    current["mode"] = str(value)
                elif canonical in ("ownerAliases", "adminContacts", "testContacts"):
                    current[canonical] = _dedupe_str_list(value)
                elif canonical == "onboardingCompleted":
                    current["onboardingCompleted"] = bool(value)
                elif canonical == "industryPack":
                    clean_pack = str(value or "").strip()
                    current["industryPack"] = clean_pack or DEFAULT_INDUSTRY_PACK
                else:
                    current[canonical] = str(value or "").strip()
            return self._save_unlocked(current)

    def complete_onboarding(
        self,
        owner_name: Optional[str] = None,
        *,
        business_name: Optional[str] = None,
        product_summary: Optional[str] = None,
        industry_pack: Optional[str] = None,
        owner_aliases: Optional[Iterable[str]] = None,
        admin_contacts: Optional[Iterable[str]] = None,
        test_contacts: Optional[Iterable[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Record onboarding details, mark onboarding completed, and switch mode to customer."""
        updates: Dict[str, Any] = {
            "onboardingCompleted": True,
            "mode": "customer",
        }
        resolved_owner = owner_name if owner_name is not None else kwargs.pop("ownerName", kwargs.pop("owner_name", None))
        if resolved_owner is not None:
            updates["ownerName"] = resolved_owner

        resolved_business = (
            business_name if business_name is not None else kwargs.pop("businessName", kwargs.pop("business_name", None))
        )
        if resolved_business is not None:
            updates["businessName"] = resolved_business

        resolved_summary = (
            product_summary
            if product_summary is not None
            else kwargs.pop("productSummary", kwargs.pop("product_summary", None))
        )
        if resolved_summary is not None:
            updates["productSummary"] = resolved_summary

        resolved_pack = (
            industry_pack if industry_pack is not None else kwargs.pop("industryPack", kwargs.pop("industry_pack", None))
        )
        if resolved_pack is not None:
            updates["industryPack"] = resolved_pack

        resolved_aliases = (
            owner_aliases if owner_aliases is not None else kwargs.pop("ownerAliases", kwargs.pop("owner_aliases", None))
        )
        if resolved_aliases is not None:
            updates["ownerAliases"] = resolved_aliases

        resolved_admins = (
            admin_contacts if admin_contacts is not None else kwargs.pop("adminContacts", kwargs.pop("admin_contacts", None))
        )
        if resolved_admins is not None:
            updates["adminContacts"] = resolved_admins

        resolved_tests = (
            test_contacts if test_contacts is not None else kwargs.pop("testContacts", kwargs.pop("test_contacts", None))
        )
        if resolved_tests is not None:
            updates["testContacts"] = resolved_tests

        if kwargs:
            unknown = ", ".join(sorted(kwargs.keys()))
            raise ValueError(f"Unknown onboarding field(s): {unknown}")

        return self.update_profile(**updates)

    def is_customer_mode(self) -> bool:
        """Return True if customer build marker exists or persisted mode is customer."""
        if self._has_customer_marker():
            return True
        return self.load().get("mode") == "customer"

    def add_test_contact(self, name: str) -> Dict[str, Any]:
        """Add a contact name to testContacts (case-insensitive deduplication)."""
        clean = _clean_contact_or_alias(name)
        if not clean:
            raise ValueError("Test contact name cannot be empty.")
        with self._lock:
            current = self._load_unlocked()
            existing = _dedupe_str_list(current.get("testContacts"))
            if clean.casefold() not in {item.casefold() for item in existing}:
                existing.append(clean)
            current["testContacts"] = existing
            return self._save_unlocked(current)

    def remove_test_contact(self, name: str) -> Dict[str, Any]:
        """Remove a contact name from testContacts if present."""
        clean = _clean_contact_or_alias(name)
        with self._lock:
            current = self._load_unlocked()
            existing = _dedupe_str_list(current.get("testContacts"))
            if not clean:
                return dict(current)
            target_key = clean.casefold()
            filtered = [item for item in existing if item.casefold() != target_key]
            if len(filtered) == len(existing):
                return dict(current)
            current["testContacts"] = filtered
            return self._save_unlocked(current)

    def add_admin_contact(self, name: str) -> Dict[str, Any]:
        """Add a contact name to adminContacts (case-insensitive deduplication)."""
        clean = _clean_contact_or_alias(name)
        if not clean:
            raise ValueError("Admin contact name cannot be empty.")
        with self._lock:
            current = self._load_unlocked()
            existing = _dedupe_str_list(current.get("adminContacts"))
            if clean.casefold() not in {item.casefold() for item in existing}:
                existing.append(clean)
            current["adminContacts"] = existing
            return self._save_unlocked(current)


def list_sales_packs(packs_dir: Path | str) -> List[Dict[str, Any]]:
    """List available L1/L2 sales pack metadata sorted with general_sales first."""
    root = Path(packs_dir)
    if not root.is_dir():
        return []
    summaries: List[Dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        pack_id = str(doc.get("packId") or path.stem).strip()
        if not pack_id:
            continue
        stages = doc.get("stages")
        entries = doc.get("entries")
        summaries.append(
            {
                "packId": pack_id,
                "name": str(doc.get("name") or pack_id).strip(),
                "description": str(doc.get("description") or "").strip(),
                "version": str(doc.get("version") or "1.0").strip(),
                "stageCount": len(stages) if isinstance(stages, (list, dict)) else 0,
                "entryCount": len(entries) if isinstance(entries, list) else 0,
                "path": str(path),
            }
        )
    summaries.sort(key=lambda item: (0 if item["packId"] == DEFAULT_INDUSTRY_PACK else 1, item["packId"]))
    return summaries


def load_sales_pack(pack_id: str, packs_dir: Path | str) -> Dict[str, Any]:
    """Load a full sales pack JSON by packId from packs_dir."""
    clean_id = str(pack_id or "").strip()
    if not clean_id or "/" in clean_id or "\\" in clean_id or ".." in clean_id:
        raise ValueError(f"Invalid sales pack id: {pack_id!r}")
    root = Path(packs_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Sales packs directory not found: {root}")

    direct_path = root / f"{clean_id}.json"
    candidates: List[Path] = []
    if direct_path.is_file():
        candidates.append(direct_path)
    candidates.extend(p for p in sorted(root.glob("*.json")) if p != direct_path)

    for candidate in candidates:
        try:
            doc = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if candidate == direct_path:
                raise ValueError(f"Invalid sales pack JSON in {candidate}: {exc}") from exc
            continue
        if not isinstance(doc, dict):
            if candidate == direct_path:
                raise ValueError(f"Sales pack {candidate} must be a JSON object.")
            continue
        doc_id = str(doc.get("packId") or candidate.stem).strip()
        if candidate == direct_path or doc_id == clean_id:
            return doc

    raise FileNotFoundError(f"Sales pack {clean_id!r} not found in {root}")
