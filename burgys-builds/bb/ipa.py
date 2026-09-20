"""Read an .ipa without a Mac.

An IPA is a zip; Info.plist is a binary plist that :mod:`plistlib` handles;
``embedded.mobileprovision`` is a CMS blob whose payload is a plain XML
plist we can slice out without OpenSSL.  That is enough to verify on
Windows that the artifact we are about to publish is the one we asked for.

The provisioned device UDIDs are deliberately *counted*, never stored:
they identify Sebastian's and Lynn's phones.
"""
from __future__ import annotations

import datetime as _dt
import plistlib
import zipfile
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .store import sha256_file


def _payload_app_prefix(zf: zipfile.ZipFile) -> str:
    for name in zf.namelist():
        parts = name.split("/")
        if len(parts) >= 2 and parts[0] == "Payload" and parts[1].endswith(".app"):
            return f"Payload/{parts[1]}/"
    raise ValidationError("kein Payload/*.app im IPA - das ist keine gueltige IPA")


def _profile_plist(raw: bytes) -> dict:
    start = raw.find(b"<?xml")
    end = raw.find(b"</plist>")
    if start == -1 or end == -1:
        raise ValidationError("embedded.mobileprovision enthaelt kein lesbares Plist")
    return plistlib.loads(raw[start:end + len(b"</plist>")])


def inspect(ipa_path: str | Path) -> dict[str, Any]:
    """Everything we can honestly learn about an IPA on Windows."""
    path = Path(ipa_path)
    if not path.exists():
        raise ValidationError(f"IPA fehlt: {path}")
    out: dict[str, Any] = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"{path} ist kein lesbares Zip/IPA: {exc}") from None
    with zf:
        prefix = _payload_app_prefix(zf)
        out["app_bundle"] = prefix.split("/")[1]
        info = plistlib.loads(zf.read(prefix + "Info.plist"))
        out.update({
            "bundle_id": info.get("CFBundleIdentifier"),
            "bundle_name": info.get("CFBundleName"),
            "display_name": info.get("CFBundleDisplayName"),
            "version": info.get("CFBundleShortVersionString"),
            "build_number": info.get("CFBundleVersion"),
            "minimum_os": info.get("MinimumOSVersion"),
            "sdk": info.get("DTSDKName"),
            "xcode": info.get("DTXcode"),
            "uses_non_exempt_encryption": info.get("ITSAppUsesNonExemptEncryption"),
        })
        out["has_code_signature"] = any(
            n.startswith(prefix + "_CodeSignature/") for n in zf.namelist()
        )
        try:
            profile = _profile_plist(zf.read(prefix + "embedded.mobileprovision"))
        except KeyError:
            out["profile"] = None
        else:
            entitlements = profile.get("Entitlements", {}) or {}
            expires = profile.get("ExpirationDate")
            out["profile"] = {
                "name": profile.get("Name"),
                "uuid": profile.get("UUID"),
                "team_name": profile.get("TeamName"),
                "team_ids": list(profile.get("TeamIdentifier") or []),
                "created": _iso(profile.get("CreationDate")),
                "expires": _iso(expires),
                "expired": bool(expires and expires < _dt.datetime.now()),
                # Count only - a UDID identifies a person's phone.
                "provisioned_device_count": len(profile.get("ProvisionedDevices") or []),
                "provisions_all_devices": bool(profile.get("ProvisionsAllDevices")),
                "application_identifier": entitlements.get("application-identifier"),
                "get_task_allow": entitlements.get("get-task-allow"),
                "certificate_count": len(profile.get("DeveloperCertificates") or []),
            }
        out["web_index_present"] = (prefix + "web/index.html") in zf.namelist()
    return out


def _iso(value: Any) -> str | None:
    if isinstance(value, _dt.datetime):
        return value.isoformat(timespec="seconds")
    return None


def distribution_kind(info: dict) -> str:
    """AD_HOC / APP_STORE / DEVELOPMENT, as far as the profile shows it."""
    profile = info.get("profile")
    if not profile:
        return "UNKNOWN"
    if profile.get("get_task_allow"):
        return "DEVELOPMENT"
    if profile.get("provisioned_device_count"):
        return "AD_HOC"
    if profile.get("provisions_all_devices"):
        return "ENTERPRISE"
    return "APP_STORE"
