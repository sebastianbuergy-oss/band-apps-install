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

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..errors import ConfigError, ExecutorUnavailable, ValidationError
from ..redact import redact_text
from . import AVAILABLE, BUSY, OFFLINE, MacExecutor, MacJob, MacJobResult, register

API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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
            API + path, data=data, method=method,
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
