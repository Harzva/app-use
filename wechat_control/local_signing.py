"""Stable local leaf-certificate code signing & verification for WeChat Bot & Studio.

Avoids ad-hoc (`cdhash`) signature churn so macOS TCC / Keychain permissions
do not repeatedly prompt on every recompile. Never touches HarvisBar or Bot Studio
signing directories, and never interacts with GUI Keychain dialogs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SigningError(RuntimeError):
    """Raised when local code signing configuration or verification fails."""


def _real_home() -> Path:
    mac_home = Path("/Users/mac")
    if (mac_home / "Library" / "Keychains" / "login.keychain-db").exists():
        return mac_home
    return Path.home()


REAL_HOME = _real_home()
DEFAULT_SIGNING_CONFIG_PATH = (
    REAL_HOME / "Library" / "Application Support" / "WeChatBot" / "signing" / "local-signing.json"
)
DEFAULT_KEYCHAIN_PATH = REAL_HOME / "Library" / "Keychains" / "login.keychain-db"

KNOWN_BUNDLE_IDS: Dict[str, str] = {
    "WeChat Bot.app": "com.openbot.wechat-bot",
    "wechat-studio-app": "com.openbot.wechat-studio-app",
    "wechat-vision-ax": "com.openbot.wechat-vision-ax",
}


def _codesign_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(REAL_HOME)
    return env


def load_signing_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and cryptographically validate WeChatBot's local leaf-signing configuration."""
    env_override = os.environ.get("WECHAT_BOT_SIGNING_CONFIG", "").strip()
    path = Path(config_path or env_override or DEFAULT_SIGNING_CONFIG_PATH)
    if path.is_symlink() or not path.is_file():
        raise SigningError(f"Signing config missing or not a regular file: {path}")
    meta = path.stat()
    if meta.st_uid != os.getuid() or (meta.st_mode & 0o022):
        raise SigningError(f"Signing config has unsafe ownership or permissions: {path}")

    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if int(cfg.get("schemaVersion") or 0) != 1:
            raise ValueError("unsupported schemaVersion")
        name = str(cfg["name"]).strip()
        sha1 = str(cfg["certificateSha1"]).strip().upper()
        sha256 = str(cfg["certificateSha256"]).strip().lower()
        bundle_ids = cfg["bundleIdentifiers"]
        if not name or not re.fullmatch(r"[A-F0-9]{40}", sha1) or not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("invalid certificate fingerprint format")
        if not isinstance(bundle_ids, list) or not bundle_ids:
            raise ValueError("bundleIdentifiers must be a non-empty list")
        cert_path = Path(cfg["certificatePath"])
        if not cert_path.is_absolute() or cert_path.is_symlink() or not cert_path.is_file():
            raise ValueError(f"invalid certificatePath: {cert_path}")
        der = ssl.PEM_cert_to_DER_cert(cert_path.read_text(encoding="utf-8"))
        if hashlib.sha1(der).hexdigest().upper() != sha1 or hashlib.sha256(der).hexdigest().lower() != sha256:
            raise ValueError("certificate PEM digest mismatch")
    except Exception as exc:
        raise SigningError(f"Invalid WeChatBot signing config ({path}): {exc}") from exc

    return {
        "schemaVersion": 1,
        "name": name,
        "certificateSha1": sha1,
        "certificateSha256": sha256,
        "certificatePath": str(cert_path),
        "bundleIdentifiers": [str(b) for b in bundle_ids],
        "configPath": str(path),
        "keychainPath": str(DEFAULT_KEYCHAIN_PATH),
    }


def build_designated_requirement(bundle_id: str, certificate_sha1: str) -> str:
    """Return a stable designated requirement bound to bundle_id + leaf cert (no cdhash)."""
    return f'identifier "{bundle_id}" and certificate leaf = H"{certificate_sha1.lower()}"'


def _infer_bundle_id(target_path: Path, explicit_bundle_id: Optional[str] = None) -> str:
    if explicit_bundle_id and explicit_bundle_id.strip():
        return explicit_bundle_id.strip()
    plist_path = target_path / "Contents" / "Info.plist"
    if plist_path.is_file():
        with plist_path.open("rb") as fh:
            info = plistlib.load(fh)
        bid = str(info.get("CFBundleIdentifier") or "").strip()
        if bid:
            return bid
    if target_path.name in KNOWN_BUNDLE_IDS:
        return KNOWN_BUNDLE_IDS[target_path.name]
    raise SigningError(f"Cannot infer bundle identifier for {target_path}; pass --bundle-id explicitly")


def ensure_keychain_signing_ready(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Verify the pinned local codesigning identity is available in login keychain."""
    cfg = config or load_signing_config()
    keychain = str(cfg.get("keychainPath") or DEFAULT_KEYCHAIN_PATH)
    proc = subprocess.run(
        ["/usr/bin/security", "find-identity", "-p", "codesigning", "-v", keychain],
        env=_codesign_env(),
        capture_output=True,
        text=True,
        timeout=6.0,
    )
    if proc.returncode != 0:
        raise SigningError(f"security find-identity failed: {(proc.stderr or proc.stdout).strip()}")
    if cfg["certificateSha1"] not in proc.stdout.upper():
        raise SigningError(
            f"Pinned codesigning identity {cfg['certificateSha1']} ({cfg['name']}) not found in {keychain}"
        )
    return {
        "ok": True,
        "mode": "local-leaf-certificate",
        "name": cfg["name"],
        "certificateSha1": cfg["certificateSha1"],
        "certificateSha256": cfg["certificateSha256"],
        "keychainPath": keychain,
        "configPath": cfg["configPath"],
    }


def _sign_single(target: Path, bundle_id: str, config: Dict[str, Any], *, is_bundle: bool) -> None:
    if bundle_id not in config["bundleIdentifiers"]:
        raise SigningError(f"Bundle identifier '{bundle_id}' is not authorized in {config['configPath']}")

    req = build_designated_requirement(bundle_id, config["certificateSha1"])
    req_tmp_dir = Path("/Volumes/SanDisk/Builds")
    tmp_dir_arg = str(req_tmp_dir) if req_tmp_dir.is_dir() and os.access(req_tmp_dir, os.W_OK) else None

    fd, tmp_name = tempfile.mkstemp(prefix="wechat-req-", suffix=".txt", dir=tmp_dir_arg)
    req_path = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, f"designated => {req}\n".encode("utf-8"))
        os.close(fd)

        cmd = [
            "/usr/bin/codesign",
            "--force",
            "--timestamp=none",
            "--keychain",
            str(config.get("keychainPath") or DEFAULT_KEYCHAIN_PATH),
            "--sign",
            config["certificateSha1"],
            "-r",
            str(req_path),
        ]
        if not is_bundle:
            cmd.extend(["--identifier", bundle_id])
        cmd.append(str(target))

        try:
            proc = subprocess.run(
                cmd,
                env=_codesign_env(),
                capture_output=True,
                text=True,
                timeout=10.0,
            )
        except subprocess.TimeoutExpired as exc:
            raise SigningError(
                f"codesign timed out on {target} (Keychain key partition-list may need codesign permission)"
            ) from exc
        if proc.returncode != 0:
            raise SigningError((proc.stderr or proc.stdout or f"codesign exit {proc.returncode}").strip())
    finally:
        try:
            req_path.unlink()
        except OSError:
            pass


def sign_macho_or_bundle(
    target_path: Path,
    bundle_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Sign a Mach-O executable or macOS .app bundle with the stable local leaf certificate."""
    target = Path(target_path)
    if not target.exists():
        raise SigningError(f"Signing target does not exist: {target}")

    cfg = config or load_signing_config()
    ensure_keychain_signing_ready(cfg)
    bid = _infer_bundle_id(target, bundle_id)
    is_bundle = target.suffix == ".app" and target.is_dir()

    if is_bundle:
        plist_path = target / "Contents" / "Info.plist"
        main_exec_name = ""
        if plist_path.is_file():
            with plist_path.open("rb") as fh:
                main_exec_name = str(plistlib.load(fh).get("CFBundleExecutable") or "")
        macos_dir = target / "Contents" / "MacOS"
        if macos_dir.is_dir():
            for helper in sorted(macos_dir.iterdir()):
                if not helper.is_file() or helper.is_symlink() or helper.name == main_exec_name:
                    continue
                helper_bid = KNOWN_BUNDLE_IDS.get(helper.name, bid)
                _sign_single(helper, helper_bid, cfg, is_bundle=False)
        _sign_single(target, bid, cfg, is_bundle=True)
    else:
        _sign_single(target, bid, cfg, is_bundle=False)

    return verify_stable_signature(target, bundle_id=bid, config=cfg)


def verify_stable_signature(
    target_path: Path,
    bundle_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Verify strict code signature, pinned leaf certificate Authority, and non-cdhash requirement."""
    target = Path(target_path)
    if not target.exists():
        raise SigningError(f"Verify target does not exist: {target}")
    cfg = config or load_signing_config()
    bid = _infer_bundle_id(target, bundle_id)
    req = build_designated_requirement(bid, cfg["certificateSha1"])
    is_bundle = target.suffix == ".app" and target.is_dir()

    verify_cmd = ["/usr/bin/codesign", "--verify"]
    if is_bundle:
        verify_cmd.append("--deep")
    verify_cmd.extend(["--strict", "--test-requirement", f"={req}", str(target)])
    v_proc = subprocess.run(verify_cmd, env=_codesign_env(), capture_output=True, text=True, timeout=8.0)
    if v_proc.returncode != 0:
        raise SigningError(
            f"codesign verification failed for {target}: {(v_proc.stderr or v_proc.stdout).strip()}"
        )

    inspect_proc = subprocess.run(
        ["/usr/bin/codesign", "-dvv", "-r-", str(target)],
        env=_codesign_env(),
        capture_output=True,
        text=True,
        timeout=8.0,
    )
    if inspect_proc.returncode != 0:
        raise SigningError(f"codesign inspect failed for {target}: {inspect_proc.stderr.strip()}")
    combined = (inspect_proc.stdout or "") + "\n" + (inspect_proc.stderr or "")
    lines = [line.strip() for line in combined.splitlines() if line.strip()]

    expected_req_line = f"designated => {req}"
    if expected_req_line not in lines:
        raise SigningError(f"Designated requirement mismatch for {target}; expected '{expected_req_line}'")
    if "Signature=adhoc" in lines:
        raise SigningError(f"Ad-hoc signature forbidden for {target}")
    if any(line.startswith("designated =>") and "cdhash" in line for line in lines):
        raise SigningError(f"Designated requirement must not depend on cdhash for {target}")
    if f"Authority={cfg['name']}" not in lines:
        raise SigningError(f"Signing Authority mismatch for {target}; expected Authority={cfg['name']}")
    if f"Identifier={bid}" not in lines:
        raise SigningError(f"Signing Identifier mismatch for {target}; expected Identifier={bid}")

    return {
        "ok": True,
        "path": str(target),
        "bundleId": bid,
        "mode": "local-leaf-certificate",
        "authority": cfg["name"],
        "certificateSha1": cfg["certificateSha1"],
        "certificateSha256": cfg["certificateSha256"],
        "designatedRequirement": req,
        "usesCdhash": False,
        "zeroPopupVerified": True,
    }


def _bundle_file_digests(bundle_dir: Path) -> Dict[str, str]:
    digests: Dict[str, str] = {}
    for p in sorted(bundle_dir.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = p.relative_to(bundle_dir).as_posix()
            digests[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return digests


def bundle_needs_reinstall(src_bundle: Path, dst_bundle: Path, bundle_id: Optional[str] = None) -> bool:
    """Return False if dst_bundle already exists, passes stable signature check, and matches src_bundle."""
    if not dst_bundle.is_dir() or not src_bundle.is_dir():
        return True
    try:
        verify_stable_signature(dst_bundle, bundle_id=bundle_id)
    except SigningError:
        return True
    return _bundle_file_digests(src_bundle) != _bundle_file_digests(dst_bundle)


def get_signing_status(targets: Optional[List[Tuple[Path, Optional[str]]]] = None) -> Dict[str, Any]:
    """Return local signing readiness and per-artifact verification status."""
    try:
        cfg = load_signing_config()
        ready = ensure_keychain_signing_ready(cfg)
    except SigningError as exc:
        return {"ok": False, "mode": "unconfigured", "error": str(exc), "targets": []}

    checked: List[Dict[str, Any]] = []
    for path, bid in (targets or []):
        target = Path(path)
        if not target.exists():
            checked.append({"path": str(target), "ok": False, "exists": False})
            continue
        try:
            checked.append(verify_stable_signature(target, bundle_id=bid, config=cfg))
        except SigningError as exc:
            checked.append({"path": str(target), "ok": False, "exists": True, "error": str(exc)})

    return {
        **ready,
        "zeroPopupVerified": all(bool(item.get("ok")) for item in checked) if checked else True,
        "targets": checked,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="WeChat Bot stable local leaf-certificate signing helper")
    parser.add_argument("action", choices=["status", "sign", "verify"])
    parser.add_argument("--path", type=Path, help="Target binary or .app bundle")
    parser.add_argument("--bundle-id", default=None, help="Explicit bundle identifier")
    args = parser.parse_args(argv)

    try:
        if args.action == "status":
            out = get_signing_status([(args.path, args.bundle_id)] if args.path else None)
        elif args.action == "sign":
            if not args.path:
                raise SigningError("--path is required for sign")
            out = sign_macho_or_bundle(args.path, bundle_id=args.bundle_id)
        else:
            if not args.path:
                raise SigningError("--path is required for verify")
            out = verify_stable_signature(args.path, bundle_id=args.bundle_id)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1
    except SigningError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
