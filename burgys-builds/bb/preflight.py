"""Windows-side preflight (master brief, sections 6 and 8).

Everything here runs on the HP for free.  The point is that by the time a
macOS executor is asked for anything, the only remaining unknowns are the
genuinely Apple-specific ones.  A check returns a verdict, never an
exception, so that one failure does not hide the other nine.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import gitinfo
from .errors import ConfigError
from .projects import MODE_AD_HOC, MODE_APP_STORE, Project

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
SKIP = "SKIP"


class Result:
    def __init__(self, name: str, status: str, message: str, detail: Any = None) -> None:
        self.name = name
        self.status = status
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {"check": self.name, "status": self.status,
                "message": self.message, "detail": self.detail}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.status} {self.name}: {self.message}>"


class PreflightReport:
    def __init__(self, project: str, mode: str, results: list) -> None:
        self.project = project
        self.mode = mode
        self.results = results
        self.at = _dt.datetime.now().isoformat(timespec="seconds")

    @property
    def ok(self) -> bool:
        return not any(r.status == FAIL for r in self.results)

    @property
    def failures(self) -> list:
        return [r for r in self.results if r.status == FAIL]

    @property
    def warnings(self) -> list:
        return [r for r in self.results if r.status == WARN]

    def value(self, check: str, key: str, default: Any = None) -> Any:
        for r in self.results:
            if r.name == check and isinstance(r.detail, dict):
                return r.detail.get(key, default)
        return default

    def to_dict(self) -> dict:
        return {
            "project": self.project, "mode": self.mode, "at": self.at,
            "ok": self.ok,
            "summary": {
                "pass": sum(1 for r in self.results if r.status == PASS),
                "fail": len(self.failures),
                "warn": len(self.warnings),
                "skip": sum(1 for r in self.results if r.status == SKIP),
            },
            "results": [r.to_dict() for r in self.results],
        }


# --------------------------------------------------------------------------

def run(project: Project, mode: str = MODE_AD_HOC, *,
        commit: str | None = None, config: dict | None = None) -> PreflightReport:
    config = config or {}
    results: list = []

    def add(name: str, fn: Callable[[], Result]) -> Result:
        try:
            res = fn()
        except Exception as exc:  # a broken check is a failed check, not a crash
            res = Result(name, FAIL, f"Pruefung abgebrochen: {exc}")
        results.append(res)
        return res

    add("project.mode", lambda: _check_mode(project, mode))
    path_res = add("project.path", lambda: _check_path(project))
    if path_res.status == FAIL:
        # Without a checkout nothing below can say anything true.
        for name in ("git.repository", "git.clean", "git.commit", "files.required",
                     "config.bundle_id", "config.display_name", "assets.web",
                     "feed.json", "project.preflight_script"):
            results.append(Result(name, SKIP, "uebersprungen: kein Projektverzeichnis"))
        results.append(_check_signing(project, mode))
        return PreflightReport(project.id, mode, results)

    root = project.path()
    add("git.repository", lambda: _check_repo(root))
    add("git.clean", lambda: _check_clean(root))
    add("git.commit", lambda: _check_commit(root, project, commit))
    add("files.required", lambda: _check_required(project))
    add("config.bundle_id", lambda: _check_bundle_id(project))
    add("config.display_name", lambda: _check_display_name(project))
    add("assets.web", lambda: _check_web_assets(project))
    add("feed.json", lambda: _check_feed(project))
    add("version.build_number", lambda: _check_version(project))
    results.extend(_eigene_schritte(project))
    results.append(_check_signing(project, mode))
    return PreflightReport(project.id, mode, results)


# -- individual checks ------------------------------------------------------

def _eigene_schritte(project: Project) -> list:
    """Wie `add`, aber fuer die mehreren eigenen Pruefschritte eines Projekts."""
    try:
        return _run_project_preflight(project)
    except Exception as exc:  # ein kaputter Schritt ist ein roter Schritt, kein Absturz
        return [Result("project.preflight_script", FAIL, f"Pruefung abgebrochen: {exc}")]



#: Projektarten, deren iOS-Teil von Flutter erzeugt wird. Dort gibt es kein project.yml.
FLUTTER_ARTEN = ("flutter",)


def _ist_flutter(project: Project) -> bool:
    return str(getattr(project, "kind", "")).lower() in FLUTTER_ARTEN


def _pbxproj_bundle_ids(project: Project) -> list:
    """Alle Bundle-IDs aus dem Xcode-Projekt, ohne die der Testziele."""
    pfad = project.resolve_in_project("ios/Runner.xcodeproj/project.pbxproj")
    if not pfad.exists():
        return []
    text = pfad.read_text(encoding="utf-8", errors="replace")
    gefunden = re.findall(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*([^;]+);", text)
    sauber = [w.strip().strip('"') for w in gefunden]
    return [w for w in sauber if not w.endswith("Tests")]


def _plist_wert(project: Project, schluessel: str) -> str | None:
    """Den Wert eines Schluessels aus Info.plist lesen - der <string> direkt nach dem <key>."""
    pfad = project.resolve_in_project("ios/Runner/Info.plist")
    if not pfad.exists():
        return None
    text = pfad.read_text(encoding="utf-8", errors="replace")
    treffer = re.search(
        r"<key>" + re.escape(schluessel) + r"</key>\s*<string>([^<]*)</string>", text)
    return treffer.group(1).strip() if treffer else None


def _check_mode(project: Project, mode: str) -> Result:
    if not project.supports(mode):
        return Result("project.mode", FAIL,
                      f"{project.id} ist nicht fuer {mode} konfiguriert "
                      f"(erlaubt: {', '.join(project.modes)})")
    return Result("project.mode", PASS, f"Modus {mode} ist fuer {project.id} vorgesehen")


def _check_path(project: Project) -> Result:
    try:
        root = project.path()
    except ConfigError as exc:
        return Result("project.path", FAIL, str(exc))
    if not root.exists():
        return Result("project.path", FAIL, f"Projektverzeichnis fehlt: {root}")
    if not root.is_dir():
        return Result("project.path", FAIL, f"{root} ist kein Verzeichnis")
    return Result("project.path", PASS, str(root), {"path": str(root)})


def _check_repo(root: Path) -> Result:
    if not gitinfo.is_repo(root):
        return Result("git.repository", FAIL, f"{root} ist kein Git-Repository")
    return Result("git.repository", PASS, f"Git-Repository, origin {gitinfo.remote_url(root) or '(keines)'}")


def _check_clean(root: Path) -> Result:
    clean, dirty = gitinfo.is_clean(root)
    if clean:
        return Result("git.clean", PASS, "Arbeitsverzeichnis sauber")
    return Result("git.clean", FAIL,
                  f"{len(dirty)} nicht committete Aenderung(en) - ein Build "
                  "muss einem Commit entsprechen",
                  {"dirty": dirty[:20]})


def _check_commit(root: Path, project: Project, commit: str | None) -> Result:
    branch = gitinfo.current_branch(root)
    if commit:
        if not gitinfo.commit_exists(root, commit):
            return Result("git.commit", FAIL, f"Commit {commit} existiert nicht in {root}")
        resolved = commit
    else:
        resolved = gitinfo.head_commit(root)
    behind = gitinfo.behind_remote(root, project.branch)
    detail = {"commit": resolved, "branch": branch,
              "subject": gitinfo.commit_subject(root, resolved), "behind": behind}
    if branch and branch != project.branch:
        return Result("git.commit", WARN,
                      f"Branch {branch} statt {project.branch}, Commit {resolved[:8]}", detail)
    if behind:
        return Result("git.commit", WARN,
                      f"{behind} Commit(s) hinter origin/{project.branch} - erst synchronisieren",
                      detail)
    return Result("git.commit", PASS, f"Commit {resolved[:8]} auf {branch or '?'}", detail)


def _check_required(project: Project) -> Result:
    missing = [rel for rel in project.required_files
               if not project.resolve_in_project(rel).exists()]
    if missing:
        return Result("files.required", FAIL,
                      f"{len(missing)} Pflichtdatei(en) fehlen", {"missing": missing})
    return Result("files.required", PASS,
                  f"alle {len(project.required_files)} Pflichtdateien vorhanden")


def _check_bundle_id(project: Project) -> Result:
    if not project.bundle_id:
        return Result("config.bundle_id", SKIP, "keine Bundle ID konfiguriert")
    if _ist_flutter(project):
        gefunden = _pbxproj_bundle_ids(project)
        if not gefunden:
            return Result("config.bundle_id", FAIL,
                          "ios/Runner.xcodeproj/project.pbxproj fehlt oder nennt keine "
                          "PRODUCT_BUNDLE_IDENTIFIER")
        if project.bundle_id not in gefunden:
            return Result("config.bundle_id", FAIL,
                          f"Das Xcode-Projekt sagt {gefunden[0]}, Buergys Builds erwartet "
                          f"{project.bundle_id} - Widerspruch, kein Build",
                          {"im_projekt": gefunden, "expected": project.bundle_id})
        return Result("config.bundle_id", PASS, project.bundle_id)
    pj = project.resolve_in_project("project.yml")
    if not pj.exists():
        return Result("config.bundle_id", FAIL, "project.yml fehlt")
    text = pj.read_text(encoding="utf-8", errors="replace")
    found = re.findall(r"PRODUCT_BUNDLE_IDENTIFIER:\s*(\S+)", text)
    if not found:
        return Result("config.bundle_id", FAIL, "project.yml nennt keine PRODUCT_BUNDLE_IDENTIFIER")
    if project.bundle_id not in found:
        return Result("config.bundle_id", FAIL,
                      f"project.yml sagt {found[0]}, Buergys Builds erwartet "
                      f"{project.bundle_id} - Widerspruch, kein Build",
                      {"in_project_yml": found, "expected": project.bundle_id})
    return Result("config.bundle_id", PASS, project.bundle_id)


def _check_display_name(project: Project) -> Result:
    if _ist_flutter(project):
        wert = _plist_wert(project, "CFBundleDisplayName")
        if wert is None:
            return Result("config.display_name", WARN,
                          "kein CFBundleDisplayName in ios/Runner/Info.plist")
        if wert.startswith("$("):
            return Result("config.display_name", WARN,
                          f"Anzeigename kommt aus einer Xcode-Variable ({wert})")
        if wert != project.display_name:
            return Result("config.display_name", FAIL,
                          f"Anzeigename {wert!r} statt {project.display_name!r}")
        return Result("config.display_name", PASS, wert)
    pj = project.resolve_in_project("project.yml")
    if not pj.exists():
        return Result("config.display_name", SKIP, "project.yml fehlt")
    text = pj.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"CFBundleDisplayName:\s*(.+)", text)
    if not m:
        return Result("config.display_name", WARN, "kein CFBundleDisplayName in project.yml")
    actual = m.group(1).strip().strip("'\"")
    if actual != project.display_name:
        return Result("config.display_name", FAIL,
                      f"Anzeigename {actual!r} statt {project.display_name!r}")
    return Result("config.display_name", PASS, actual)


_ASSET_REF = re.compile(r'(?:src|href)="((?:img|fonts)/[^"]+)"')
_ASSET_LITERAL = re.compile(r"'([a-z0-9-]+\.(?:jpg|png))'")
_CSS_URL = re.compile(r"url\(([^)]+)\)")


def _check_web_assets(project: Project) -> Result:
    if _ist_flutter(project):
        return Result("assets.web", SKIP,
                      "Flutter bringt seine Oberflaeche selbst mit - keine Web-Dateien zu pruefen")
    index = project.resolve_in_project("web/index.html")
    if not index.exists():
        return Result("assets.web", FAIL, "web/index.html fehlt")
    html = index.read_text(encoding="utf-8", errors="replace")
    web = project.resolve_in_project("web")
    missing = []
    for m in _ASSET_REF.finditer(html):
        rel = m.group(1)
        if "${" in rel:
            continue
        if not (web / rel).exists():
            missing.append(f"web/{rel}")
    for m in _ASSET_LITERAL.finditer(html):
        if not (web / "img" / m.group(1)).exists():
            missing.append(f"web/img/{m.group(1)}")
    for m in _CSS_URL.finditer(html):
        rel = m.group(1).strip("'\"")
        if rel.startswith(("data:", "http:", "https:")) or "${" in rel:
            continue
        if not (web / rel).exists():
            missing.append(f"web/{rel}")
    css = web / "fonts" / "fonts.css"
    if css.exists():
        for m in _CSS_URL.finditer(css.read_text(encoding="utf-8", errors="replace")):
            rel = m.group(1).strip("'\"")
            if rel.startswith(("data:", "http:", "https:")):
                continue
            if not (web / "fonts" / rel).exists():
                missing.append(f"web/fonts/{rel}")
    notes = []
    if "fonts.googleapis.com" in html:
        notes.append("index.html laedt Google Fonts statt der gebuendelten Schriften")
    if "viewport-fit=cover" not in html:
        notes.append("index.html fehlt viewport-fit=cover")
    if missing or notes:
        return Result("assets.web", FAIL,
                      f"{len(missing)} fehlende Datei(en), {len(notes)} Hinweis(e)",
                      {"missing": sorted(set(missing))[:40], "notes": notes})
    return Result("assets.web", PASS, "alle referenzierten Assets sind gebuendelt")


def _check_feed(project: Project) -> Result:
    feed = project.resolve_in_project("feed/feed.json")
    if not feed.exists():
        return Result("feed.json", SKIP, "kein feed/feed.json in diesem Projekt")
    try:
        data = json.loads(feed.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return Result("feed.json", FAIL, f"feed.json ist kein gueltiges JSON: {exc}")
    problems = []
    if not isinstance(data.get("upcoming"), list) or not isinstance(data.get("news"), list):
        problems.append('feed.json braucht die Arrays "upcoming" und "news"')
    for gig in data.get("upcoming") or []:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(gig.get("date", ""))):
            problems.append(f"Konzert ohne ISO-Datum: {str(gig)[:60]}")
    if problems:
        return Result("feed.json", FAIL, f"{len(problems)} Problem(e)", {"problems": problems[:10]})
    return Result("feed.json", PASS,
                  f"{len(data.get('upcoming') or [])} Konzerte, {len(data.get('news') or [])} News")


def _check_version(project: Project) -> Result:
    if _ist_flutter(project):
        pub = project.resolve_in_project("pubspec.yaml")
        if not pub.exists():
            return Result("version.build_number", FAIL, "pubspec.yaml fehlt")
        treffer = re.search(r"^version:\s*([\d.]+)(?:\+(\d+))?",
                            pub.read_text(encoding="utf-8", errors="replace"), re.M)
        if not treffer:
            return Result("version.build_number", FAIL, "pubspec.yaml nennt keine version")
        detail = {"marketing_version": treffer.group(1), "pubspec_build_number": treffer.group(2)}
        if project.marketing_version and treffer.group(1) != project.marketing_version:
            return Result("version.build_number", WARN,
                          f"pubspec.yaml sagt {treffer.group(1)}, Registry sagt "
                          f"{project.marketing_version}", detail)
        return Result("version.build_number", PASS,
                      f"Version {treffer.group(1)}, Buildnummer wird von Buergys Builds vergeben",
                      detail)
    pj = project.resolve_in_project("project.yml")
    if not pj.exists():
        return Result("version.build_number", SKIP, "project.yml fehlt")
    text = pj.read_text(encoding="utf-8", errors="replace")
    marketing = re.search(r"MARKETING_VERSION:\s*'?([\d.]+)'?", text)
    current = re.search(r"CURRENT_PROJECT_VERSION:\s*'?(\d+)'?", text)
    detail = {
        "marketing_version": marketing.group(1) if marketing else None,
        "project_yml_build_number": current.group(1) if current else None,
    }
    if not marketing:
        return Result("version.build_number", FAIL, "keine MARKETING_VERSION in project.yml", detail)
    if project.marketing_version and marketing.group(1) != project.marketing_version:
        return Result("version.build_number", WARN,
                      f"project.yml sagt {marketing.group(1)}, Registry sagt "
                      f"{project.marketing_version}", detail)
    return Result("version.build_number", PASS,
                  f"Version {marketing.group(1)}, Buildnummer wird von Buergys Builds vergeben",
                  detail)


def _preflight_befehle(project: Project) -> list:
    """Ein Befehl oder mehrere. Alt: ["flutter","analyze"]. Neu zusaetzlich:
    [["flutter","analyze"],["flutter","test"]] - jeder Schritt wird einzeln gemeldet."""
    roh = project.preflight_command or []
    if not roh:
        return []
    if all(isinstance(x, (list, tuple)) for x in roh):
        return [list(x) for x in roh if x]
    return [list(roh)]


def _einen_befehl(project: Project, cmd: list, name: str) -> Result:
    exe = shutil.which(cmd[0])
    if not exe:
        return Result(name, WARN,
                      f"{cmd[0]} ist nicht installiert - dieser Schritt wurde nicht ausgefuehrt")
    try:
        res = subprocess.run([exe, *cmd[1:]], cwd=str(project.path()),
                             capture_output=True, text=True, timeout=900, check=False)
    except subprocess.TimeoutExpired:
        return Result(name, FAIL, f"{' '.join(cmd)} hat das Zeitlimit ueberschritten")
    from .redact import redact_text

    tail = redact_text((res.stdout + res.stderr).strip())[-2000:]
    if res.returncode != 0:
        return Result(name, FAIL,
                      f"{' '.join(cmd)} endete mit Code {res.returncode}", {"output": tail})
    return Result(name, PASS, f"{' '.join(cmd)} OK", {"output": tail})


def _run_project_preflight(project: Project) -> list:
    """Die eigenen Pruefschritte des Projekts. Gibt eine Liste zurueck, damit ein roter
    Schritt die anderen nicht verdeckt - jeder Schritt steht einzeln im Bericht."""
    befehle = _preflight_befehle(project)
    if not befehle:
        return [Result("project.preflight_script", SKIP,
                       "kein eigenes Preflight-Script konfiguriert")]
    if len(befehle) == 1:
        return [_einen_befehl(project, befehle[0], "project.preflight_script")]
    return [_einen_befehl(project, cmd, f"project.preflight_script[{i + 1}]")
            for i, cmd in enumerate(befehle)]


def _check_signing(project: Project, mode: str) -> Result:
    """Config-level signing check only.

    Buergys Builds never holds the private key, so this verifies that the
    *declared* signing material is coherent and unexpired.  The binding
    proof - that the IPA really carries this profile - happens after the
    export in :mod:`bb.verify`.
    """
    spec = project.signing.get(mode)
    if not spec:
        return Result("signing.config", FAIL,
                      f"kein Signing fuer {mode} konfiguriert - Signing wird nie improvisiert")
    problems = []
    if not spec.get("profile_name"):
        problems.append("profile_name fehlt")
    if not spec.get("certificate_common_name"):
        problems.append("certificate_common_name fehlt")
    if project.team_id and project.team_id not in (spec.get("certificate_common_name") or ""):
        problems.append(f"Zertifikat nennt Team {project.team_id} nicht")
    today = _dt.date.today()
    for key, label in (("expires", "Provisioning Profile"), ("certificate_expires", "Zertifikat")):
        raw = spec.get(key)
        if not raw:
            continue
        try:
            when = _dt.date.fromisoformat(str(raw))
        except ValueError:
            problems.append(f"{label}: {raw!r} ist kein ISO-Datum")
            continue
        if when < today:
            problems.append(f"{label} ist am {when} abgelaufen")
        elif (when - today).days < 30:
            problems.append(f"{label} laeuft in {(when - today).days} Tagen ab")
    if mode == MODE_AD_HOC and not spec.get("expects_provisioned_devices", True):
        problems.append("Ad-Hoc-Profil ohne registrierte Geraete waere das falsche Profil")
    if mode == MODE_APP_STORE and not spec.get("app_store_apple_id"):
        problems.append("app_store_apple_id fehlt - Upload wuerde scheitern")
    if problems:
        return Result("signing.config", FAIL, "; ".join(problems),
                      {"mode": mode, "problems": problems})
    return Result("signing.config", PASS,
                  f"{spec['profile_name']} gueltig bis {spec.get('expires', '?')}",
                  {"mode": mode, "profile_name": spec["profile_name"]})
