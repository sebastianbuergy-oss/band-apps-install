"""Publishing an OTA release (master brief, section 10; task BB-009).

Until now the last step was a handful of manual copies, which is exactly the
kind of step that goes wrong at 23:00 and the kind Buergys Agent cannot do
at all.  This module makes it one command.

It stays deliberately cautious, because the target is the page the band
installs from (decision BB-D-007):

* ``ota_publish_dir`` is empty by default - without it, publishing refuses;
* nothing happens without ``--apply``; the default is a report;
* the IPA is re-verified and re-hashed before it is copied;
* only the files belonging to *this* app are touched - another band's
  release on the same page is never disturbed;
* nothing is ever deleted.

Committing and pushing stays a human act.  This writes files; git is yours.
"""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path

from . import states as S
from .errors import ConfigError, ValidationError
from .ota import render_install_page
from .store import read_json, sha256_file, write_json

#: Records which build is currently live per project.
LEDGER = "published.json"


def _publish_dir(config) -> Path:
    raw = (config.get("ota_publish_dir") or "").strip()
    if not raw:
        raise ConfigError(
            "ota_publish_dir ist nicht konfiguriert. Buergys Builds "
            "veroeffentlicht nichts auf eine Seite, die es nicht kennt. "
            "In config/burgys.json den Pfad zum Pages-Repo eintragen, "
            "z. B. \"C:\\\\Users\\\\<user>\\\\Projekte\\\\band-apps-install\".")
    path = Path(raw).expanduser()
    if not path.exists():
        raise ConfigError(f"ota_publish_dir zeigt auf {path} - das gibt es nicht")
    if not path.is_dir():
        raise ConfigError(f"ota_publish_dir zeigt auf {path} - kein Verzeichnis")
    return path.resolve()


def ledger_path(config) -> Path:
    return _publish_dir(config) / LEDGER


def read_ledger(config) -> dict:
    return read_json(ledger_path(config), default={}) or {}


def check_publishable(controller, build_id: str) -> tuple:
    """``(manifest, release, problems)`` - every reason at once."""
    manifest = controller.get(build_id)
    problems = []
    if manifest.status != S.SUCCESS:
        problems.append(f"Build ist {manifest.display_status()}, nicht SUCCESS")
    if manifest.is_dry_run:
        problems.append("Dry-Run-Build: es existiert keine IPA")
    release = manifest.get("ota")
    if not release:
        problems.append("kein OTA-Release am Build - nur Ad-Hoc-Builds haben eines")
        return manifest, None, problems

    source = controller.paths.ota / build_id
    if not source.exists():
        problems.append(f"OTA-Daten fehlen unter {source}")
        return manifest, release, problems

    for name in (release["ipa_name"], release["plist_name"]):
        if not (source / name).exists():
            problems.append(f"{name} fehlt in {source}")

    ipa = source / release["ipa_name"]
    if ipa.exists():
        actual = sha256_file(ipa)
        if actual != release.get("ipa_sha256"):
            problems.append(
                f"SHA-256 der IPA stimmt nicht mehr: {actual[:16]}... statt "
                f"{str(release.get('ipa_sha256'))[:16]}... - Artefakt veraendert")
    return manifest, release, problems


def plan(controller, build_id: str) -> dict:
    """What publishing this build would change."""
    config = controller.config
    target = _publish_dir(config)
    manifest, release, problems = check_publishable(controller, build_id)
    if problems:
        raise ValidationError(
            "Veroeffentlichung abgelehnt:\n  - " + "\n  - ".join(problems))

    source = controller.paths.ota / build_id
    copies = []
    for name in (release["ipa_name"], release["plist_name"]):
        src = source / name
        dst = target / name
        copies.append({
            "name": name,
            "bytes": src.stat().st_size,
            "replaces": dst.exists(),
        })
    icon = release.get("icon_name")
    icon_present = bool(icon and (target / icon).exists())

    ledger = read_ledger(config)
    previous = ledger.get(manifest.get("project"))
    return {
        "build_id": build_id,
        "project": manifest.get("project"),
        "app": release.get("app"),
        "version": release.get("version"),
        "build_number": release.get("build_number"),
        "commit": release.get("commit_short"),
        "sha256": release.get("ipa_sha256"),
        "target": str(target),
        "copies": copies,
        "icon_name": icon,
        "icon_present": icon_present,
        "replaces_build": (previous or {}).get("build_id"),
        "index_html": "index.html",
    }


def apply(controller, build_id: str, *, dry_run: bool = True,
          write_index: bool = True) -> dict:
    """Copy the release into the publish directory.

    Returns the plan, annotated with what was actually done.
    """
    result = plan(controller, build_id)
    result["dry_run"] = dry_run
    if dry_run:
        return result

    config = controller.config
    target = Path(result["target"])
    source = controller.paths.ota / build_id
    manifest = controller.get(build_id)
    release = manifest.get("ota")

    for entry in result["copies"]:
        shutil.copy2(source / entry["name"], target / entry["name"])

    ledger = read_ledger(config)
    ledger[result["project"]] = {
        "build_id": build_id,
        "app": release.get("app"),
        "slug": release.get("slug"),
        "version": release.get("version"),
        "build_number": release.get("build_number"),
        "commit": release.get("commit"),
        "commit_short": release.get("commit_short"),
        "ipa_name": release.get("ipa_name"),
        "plist_name": release.get("plist_name"),
        "icon_name": release.get("icon_name"),
        "ipa_sha256": release.get("ipa_sha256"),
        "ipa_bytes": release.get("ipa_bytes"),
        "ipa_mb": release.get("ipa_mb"),
        "minimum_os": release.get("minimum_os"),
        "install_url": release.get("install_url"),
        "page_url": release.get("page_url"),
        "published_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    write_json(target / LEDGER, ledger)

    if write_index:
        # Rebuilt from the whole ledger, so publishing one app never drops
        # another app's entry from the page.
        page = render_install_page(
            sorted(ledger.values(), key=lambda r: r.get("app") or ""))
        (target / "index.html").write_text(page, encoding="utf-8", newline="\n")
        result["index_written"] = True

    from .audit import OTA_PUBLISHED

    controller.audit.record(
        OTA_PUBLISHED, actor="publish", project=result["project"],
        build_id=build_id, detail={"target": str(target),
                                   "sha256": result["sha256"]})
    result["published_at"] = ledger[result["project"]]["published_at"]
    return result


def live(config) -> dict:
    """What is currently published, per project.  Empty if not configured."""
    try:
        return read_ledger(config)
    except ConfigError:
        return {}
