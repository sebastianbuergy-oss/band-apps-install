"""GitHub Actions macOS executor.

Standard GitHub-hosted macOS runners are free for *public* repositories,
which is what makes this the cheapest honest path to an IPA while Sebastian
has no Mac.  For a private repository the same runner bills at 10x, so the
cost guard classifies the two cases as different resources and this
executor refuses to guess which one it is - the project config has to say.

Nothing here runs without configuration: no token file, no workflow, no
dispatch.  The first real run also needs Sebastian's approval (brief,
section 29); that gate lives in :mod:`bb.builds`, not here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from ..errors import ConfigError, ExecutorUnavailable, ValidationError
from ..redact import redact_text
from . import AVAILABLE, BUSY, OFFLINE, MacExecutor, MacJob, MacJobResult, register

API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

#: An IPA for these apps is ~5 MB.  The cap is generous but finite: an
#: artifact download must not be able to fill Sebastian's disk.
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_ZIP_ENTRIES = 64


@register
class GitHubMacExecutor(MacExecutor):
    name = "github"
    produces_real_ipa = True

    def __init__(self, config=None) -> None:
        super().__init__(config)
        self.repo = self.config.get("repo") or ""
        self.workflow = self.config.get("workflow") or "burgys-ios-build.yml"
        self.ref = self.config.get("ref") or "main"
        self.visibility = (self.config.get("visibility") or "").lower()
        self.token_file = self.config.get("token_file") or ""
        #: The ``runs-on`` label the workflow uses.  The cost guard checks it
        #: against its allowlist: a public repository is only free on a
        #: *standard* runner.
        self.runs_on = self.config.get("runs_on") or ""
        #: Overridable so the tests can point at a local stub, and so a
        #: GitHub Enterprise host works without touching the code.
        self.api_base = (self.config.get("api_base") or API).rstrip("/")
        self._handles: dict[str, dict] = {}

    # -- cost ----------------------------------------------------------
    @property
    def cost_resource(self) -> str:  # type: ignore[override]
        if self.visibility == "public":
            return "github_actions_macos_public_repo"
        if self.visibility == "private":
            return "github_actions_macos_private_repo"
        # Unknown visibility is treated as private, i.e. as costing money.
        return "github_actions_macos_private_repo"

    # -- plumbing ------------------------------------------------------
    def _token(self) -> str:
        if not self.token_file:
            raise ConfigError(
                "GitHubMacExecutor: token_file ist nicht konfiguriert. "
                "Das Token gehoert nie ins Repository."
            )
        path = Path(self.token_file).expanduser()
        if not path.exists():
            raise ConfigError(f"GitHubMacExecutor: Tokendatei fehlt: {path}")
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise ConfigError(f"GitHubMacExecutor: Tokendatei {path} ist leer")
        return token

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        if not REPO_RE.match(self.repo or ""):
            raise ValidationError(f"GitHubMacExecutor: repo {self.repo!r} ist nicht owner/name")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.api_base + path, data=data, method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token()}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "burgys-builds",
                **({"Content-Type": "application/json"} if data else {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = redact_text(exc.read().decode("utf-8", "replace")[:500])
            raise ExecutorUnavailable(
                f"GitHub API {method} {path} -> {exc.code}: {detail}"
            ) from None
        except urllib.error.URLError as exc:
            raise ExecutorUnavailable(f"GitHub nicht erreichbar: {exc.reason}") from None

    @property
    def runner_label(self) -> str:  # type: ignore[override]
        return self.runs_on

    def configured(self) -> bool:
        return bool(self.repo and self.token_file
                    and Path(self.token_file).expanduser().exists())

    # -- interface -----------------------------------------------------
    def availability(self) -> str:
        if not self.configured():
            return OFFLINE
        try:
            runs = self._request(
                "GET", f"/repos/{self.repo}/actions/workflows/{self.workflow}/runs?per_page=5"
            )
        except Exception:
            return OFFLINE
        active = [r for r in runs.get("workflow_runs", [])
                  if r.get("status") in ("queued", "in_progress", "waiting")]
        return BUSY if active else AVAILABLE

    def submit(self, job: MacJob) -> str:
        if not self.configured():
            raise ExecutorUnavailable(
                "GitHubMacExecutor ist nicht konfiguriert (repo/token_file fehlen)"
            )
        started = time.time()
        self._request(
            "POST", f"/repos/{self.repo}/actions/workflows/{self.workflow}/dispatches",
            {
                "ref": self.ref,
                "inputs": {
                    "build_id": job.build_id,
                    "commit": job.commit,
                    "mode": job.mode,
                    "scheme": job.scheme,
                    "build_number": str(job.build_number),
                    "marketing_version": job.marketing_version,
                    "profile_name": job.profile_name,
                },
            },
        )
        handle = f"github:{job.build_id}"
        self._handles[handle] = {"build_id": job.build_id, "since": started, "run_id": None}
        return handle

    def _find_run(self, handle: str) -> dict | None:
        entry = self._handles.get(handle)
        if entry is None:
            return None
        if entry.get("run_id"):
            return self._request("GET", f"/repos/{self.repo}/actions/runs/{entry['run_id']}")
        runs = self._request(
            "GET", f"/repos/{self.repo}/actions/workflows/{self.workflow}/runs?per_page=20"
        )
        for run in runs.get("workflow_runs", []):
            if entry["build_id"] in (run.get("name") or "") or \
               entry["build_id"] in (run.get("display_title") or ""):
                entry["run_id"] = run["id"]
                return run
        return None

    def poll(self, handle: str) -> MacJobResult:
        run = self._find_run(handle)
        if run is None:
            return MacJobResult(state="MAC_BUILDING", detail="Workflow-Run noch nicht sichtbar")
        entry = self._handles.get(handle, {})
        minutes = (time.time() - entry.get("since", time.time())) / 60.0
        status, conclusion = run.get("status"), run.get("conclusion")
        if status != "completed":
            return MacJobResult(state="MAC_BUILDING", detail=f"GitHub: {status}", minutes=minutes)
        if conclusion == "success":
            return MacJobResult(state="SUCCESS", detail="GitHub Actions: success",
                                minutes=minutes, raw={"run_id": run.get("id")})
        if conclusion == "cancelled":
            return MacJobResult(state="CANCELLED", detail="GitHub Actions: cancelled",
                                minutes=minutes)
        return MacJobResult(state="FAILED", detail=f"GitHub Actions: {conclusion}",
                            minutes=minutes, raw={"run_id": run.get("id")})

    def cancel(self, handle: str) -> bool:
        run = self._find_run(handle)
        if not run:
            return False
        self._request("POST", f"/repos/{self.repo}/actions/runs/{run['id']}/cancel")
        return True

    # -- artifact download ---------------------------------------------
    def _artifact_entry(self, run_id: int, name: str) -> dict:
        listing = self._request(
            "GET", f"/repos/{self.repo}/actions/runs/{run_id}/artifacts?per_page=100")
        artifacts = listing.get("artifacts") or []
        for art in artifacts:
            if art.get("name") == name:
                if art.get("expired"):
                    raise ExecutorUnavailable(
                        f"Artefakt {name} ist abgelaufen - GitHub haelt es nur "
                        "begrenzt vor. Build neu anfordern.")
                return art
        available = ", ".join(a.get("name", "?") for a in artifacts) or "(keine)"
        raise ExecutorUnavailable(
            f"Kein Artefakt namens {name} im Run {run_id}. Vorhanden: {available}")

    def _download_zip(self, artifact_id: int) -> bytes:
        """Fetch the artifact zip.

        GitHub answers the download endpoint with a 302 to a *different*
        host (a signed blob URL that needs no credentials).  urllib would
        happily follow that redirect and resend our ``Authorization``
        header to that other host, which would hand the token to whoever
        the redirect points at.  So redirects are not followed
        automatically: we read the ``Location`` ourselves and fetch it with
        no credentials at all.
        """
        path = f"/repos/{self.repo}/actions/artifacts/{artifact_id}/zip"

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        req = urllib.request.Request(
            self.api_base + path, method="GET",
            headers={"Accept": "application/vnd.github+json",
                     "Authorization": f"Bearer {self._token()}",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "burgys-builds"})
        opener = urllib.request.build_opener(_NoRedirect)
        location = None
        try:
            with opener.open(req, timeout=60) as resp:
                if resp.status == 200:
                    return self._read_capped(resp)
                location = resp.headers.get("Location")
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location")
            else:
                detail = redact_text(exc.read().decode("utf-8", "replace")[:300])
                raise ExecutorUnavailable(
                    f"Artefakt-Download {exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            raise ExecutorUnavailable(f"GitHub nicht erreichbar: {exc.reason}") from None

        if not location:
            raise ExecutorUnavailable("GitHub liefert keine Download-URL fuer das Artefakt")
        scheme = urllib.parse.urlparse(location).scheme
        # The redirect may not downgrade the transport.  Against the real
        # api.github.com that means https, full stop; a stub or an internal
        # GitHub Enterprise reached over http may redirect within http.
        api_scheme = urllib.parse.urlparse(self.api_base).scheme or "https"
        allowed = ("https",) if api_scheme == "https" else ("https", "http")
        if scheme not in allowed:
            raise ValidationError(
                f"Artefakt-Download soll nach {scheme}:// gehen, erlaubt ist "
                f"{'/'.join(allowed)} - abgelehnt")
        # Deliberately no Authorization header here: the URL is pre-signed
        # and the host is not ours.
        blob = urllib.request.Request(
            location, method="GET", headers={"User-Agent": "burgys-builds"})
        try:
            with urllib.request.urlopen(blob, timeout=300) as resp:
                return self._read_capped(resp)
        except urllib.error.HTTPError as exc:
            raise ExecutorUnavailable(
                f"Artefakt-Blob {exc.code}") from None
        except urllib.error.URLError as exc:
            raise ExecutorUnavailable(f"Artefakt-Blob nicht erreichbar: {exc.reason}") from None

    @staticmethod
    def _read_capped(resp) -> bytes:
        chunks, total = [], 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise ValidationError(
                    f"Artefakt groesser als {MAX_ARTIFACT_BYTES // 2 ** 20} MB - "
                    "abgebrochen, statt die Platte vollzuschreiben")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _safe_extract(payload: bytes, dest_dir: Path) -> list:
        """Unpack the artifact zip without trusting a single name in it.

        A zip entry may be called ``../../etc/passwd`` or ``C:\\x``; the
        archive comes over the network, so every name is checked and the
        uncompressed size is capped before anything is written.
        """
        dest_dir = Path(dest_dir).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        written = []
        try:
            archive = zipfile.ZipFile(__import__("io").BytesIO(payload))
        except zipfile.BadZipFile as exc:
            raise ValidationError(f"Artefakt ist kein lesbares Zip: {exc}") from None
        with archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise ValidationError(
                    f"Artefakt enthaelt {len(entries)} Eintraege - das ist kein "
                    "Build-Ergebnis")
            if sum(e.file_size for e in entries) > MAX_ARTIFACT_BYTES:
                raise ValidationError("Artefakt entpackt sich zu gross")
            for entry in entries:
                if entry.is_dir():
                    continue
                name = entry.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/") or ":" in name:
                    raise ValidationError(
                        f"Artefakt enthaelt einen unzulaessigen Pfad: {entry.filename!r}")
                target = (dest_dir / name).resolve()
                # Second layer.  The name check above already makes this
                # unreachable today - no name that survives it can resolve
                # outside dest_dir - so it exists for the day someone
                # loosens that check, not for today's inputs.  Keep both.
                if target != dest_dir and dest_dir not in target.parents:
                    raise ValidationError(
                        f"Artefakt-Eintrag {entry.filename!r} zeigt aus dem Zielordner heraus")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as src, open(target, "wb") as out:
                    out.write(src.read())
                written.append(target)
        return written

    def fetch_artifact(self, handle: str, dest_dir) -> str | None:
        """Download the IPA this run produced and return its local path.

        Returns ``None`` rather than raising when there is simply nothing to
        fetch yet; a *broken* artifact raises, because silently returning
        nothing would read as "the build produced no IPA".
        """
        entry = self._handles.get(handle)
        if entry is None:
            return None
        run = self._find_run(handle)
        if not run:
            return None
        art = self._artifact_entry(run["id"], entry["build_id"])
        payload = self._download_zip(art["id"])
        written = self._safe_extract(payload, Path(dest_dir))
        ipas = [p for p in written if p.suffix.lower() == ".ipa"]
        if not ipas:
            raise ValidationError(
                "Artefakt enthaelt keine .ipa: "
                + ", ".join(p.name for p in written))
        if len(ipas) > 1:
            raise ValidationError(
                "Artefakt enthaelt mehrere .ipa-Dateien: "
                + ", ".join(p.name for p in ipas))
        ipa = ipas[0]
        self._verify_checksum(ipa, written)
        return str(ipa)

    @staticmethod
    def _verify_checksum(ipa: Path, written: list) -> None:
        """Check the IPA against the .sha256 the workflow wrote next to it.

        Not a security boundary - both files come from the same place - but
        it catches a truncated download, which otherwise surfaces much later
        as a confusing signature error.
        """
        sidecars = [p for p in written if p.suffix.lower() == ".sha256"]
        if not sidecars:
            return
        text = sidecars[0].read_text(encoding="utf-8", errors="replace").strip()
        expected = text.split()[0].lower() if text else ""
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValidationError(
                f"{sidecars[0].name} enthaelt keine lesbare SHA-256-Summe")
        digest = hashlib.sha256()
        with open(ipa, "rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
        actual = digest.hexdigest()
        if actual != expected:
            raise ValidationError(
                f"SHA-256 der heruntergeladenen IPA stimmt nicht: {actual} "
                f"statt {expected} - Download unvollstaendig oder veraendert")
