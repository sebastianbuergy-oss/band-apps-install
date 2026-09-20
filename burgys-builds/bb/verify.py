"""Post-export verification.

The macOS side can lie by accident - a stale profile, the wrong scheme, a
build number that did not get patched in.  This module re-checks the
finished IPA against what was *asked for*, on Windows, before anything is
published or uploaded.
"""
from __future__ import annotations

from pathlib import Path

from .ipa import distribution_kind, inspect
from .projects import MODE_AD_HOC, MODE_APP_STORE

_EXPECTED_KIND = {
    MODE_AD_HOC: "AD_HOC",
    MODE_APP_STORE: "APP_STORE",
    "DEVELOPMENT": "DEVELOPMENT",
}


def verify_artifact(project, manifest, ipa_path: str | Path) -> dict:
    """Return ``{"ok": bool, "problems": [...], "ipa": {...}}``."""
    info = inspect(ipa_path)
    problems = []

    if info.get("bundle_id") != project.bundle_id:
        problems.append(
            f"Bundle ID {info.get('bundle_id')} statt {project.bundle_id}")
    expected_build = str(manifest.get("build_number") or "")
    if expected_build and str(info.get("build_number")) != expected_build:
        problems.append(
            f"Buildnummer {info.get('build_number')} statt der vergebenen {expected_build}")
    expected_version = str(manifest.get("version") or "")
    if expected_version and str(info.get("version")) != expected_version:
        problems.append(
            f"Version {info.get('version')} statt {expected_version}")
    if not info.get("has_code_signature"):
        problems.append("keine Codesignatur im Bundle")
    if project.kind == "xcodegen-webview" and not info.get("web_index_present"):
        problems.append("web/index.html fehlt im App-Bundle - die WebView haette nichts zu zeigen")

    mode = manifest.get("mode")
    kind = distribution_kind(info)
    expected_kind = _EXPECTED_KIND.get(mode)
    if expected_kind and kind != expected_kind:
        problems.append(f"Signierung ist {kind}, erwartet war {expected_kind}")

    profile = info.get("profile") or {}
    if not profile:
        problems.append("kein embedded.mobileprovision im Bundle")
    else:
        if profile.get("expired"):
            problems.append(f"Profil abgelaufen am {profile.get('expires')}")
        configured = (project.signing.get(mode) or {}).get("profile_name")
        if configured and profile.get("name") != configured:
            problems.append(
                f"Profil {profile.get('name')!r} statt {configured!r}")
        if project.team_id and project.team_id not in (profile.get("team_ids") or []):
            problems.append(
                f"Profil gehoert Team {profile.get('team_ids')}, erwartet {project.team_id}")
        if mode == MODE_AD_HOC and not profile.get("provisioned_device_count"):
            problems.append("Ad-Hoc-IPA ohne registrierte Geraete im Profil")

    return {"ok": not problems, "problems": problems, "ipa": info}
