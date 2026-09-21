"""Client for Buergys Agent (master brief, section 19).

The brief is explicit: the agent must not run shell commands blindly.  So it
gets this instead - a small, dependency-free client that speaks the local
API and turns refusals into distinguishable exceptions, because an agent
needs to tell "I am not allowed to" apart from "the system says no" apart
from "it broke".

    from bb.agent_client import BurgysClient

    bb = BurgysClient()                      # reads the token file
    if not bb.capabilities()["policy"]["executor_produces_real_ipa"]:
        ...                                   # no Mac; only dry runs are honest
    report = bb.preflight("thy-gnosis")
    if report["ok"]:
        build = bb.request_build("thy-gnosis", dry_run=True)
        final = bb.wait_for(build["build_id"])

Nothing here can spend money: the cost guard lives on the server side, and
the agent token cannot start a real build at all.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8787"
TERMINAL = frozenset({"SUCCESS", "FAILED", "BLOCKED", "BLOCKED_BY_COST_GUARD",
                      "CANCELLED"})


class BurgysError(Exception):
    """Base class, so an agent can catch everything from here in one line."""


class BurgysUnreachable(BurgysError):
    """The controller is not running, or not answering."""


class BurgysDenied(BurgysError):
    """The token does not carry the scope this call needs (HTTP 401).

    Retrying will not help.  Either use the release token, or ask a human.
    """


class BurgysRefused(BurgysError):
    """The controller understood and said no (HTTP 409).

    Cost guard, build limit, illegal state.  ``state`` carries the build
    state the controller would move to, when it named one.
    """

    def __init__(self, message: str, state: str | None = None) -> None:
        super().__init__(message)
        self.state = state


class BurgysInvalid(BurgysError):
    """The request was malformed or the input failed validation (HTTP 400)."""


class BurgysRateLimited(BurgysError):
    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _default_token_file() -> Path:
    return Path.home() / ".burgys" / "agent_token"


def load_token(name: str = "agent", token_file=None) -> str:
    """Read a token by name from the token file.

    ``agent`` may read, run preflight and prepare; ``release`` may
    additionally start a real build, approve one and publish.
    """
    path = Path(token_file) if token_file else _default_token_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BurgysError(
            f"Keine Tokendatei unter {path}. Auf dem Controller einmal "
            "`python -m bb.cli init` ausfuehren.") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise BurgysError(f"Tokendatei {path} ist nicht lesbar: {exc}") from None
    for entry in data.get("tokens") or []:
        if entry.get("name") == name:
            return entry["token"]
    available = ", ".join(t.get("name", "?") for t in data.get("tokens") or [])
    raise BurgysError(f"Kein Token namens {name!r}. Vorhanden: {available}")


class BurgysClient:
    def __init__(self, url: str = DEFAULT_URL, token: str | None = None, *,
                 token_name: str = "agent", token_file=None,
                 timeout: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.token = token if token is not None else load_token(token_name,
                                                                token_file)

    # -- plumbing ------------------------------------------------------
    def _call(self, method: str, path: str, body: dict | None = None,
              query: dict | None = None) -> Any:
        target = self.url + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            target, data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/json",
                     **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            payload = {}
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:  # noqa: BLE001 - an error page is not fatal here
                pass
            message = payload.get("error") or f"HTTP {exc.code}"
            if exc.code == 401:
                raise BurgysDenied(message) from None
            if exc.code == 409:
                raise BurgysRefused(message, payload.get("state")) from None
            if exc.code == 429:
                raise BurgysRateLimited(
                    message, int(payload.get("retry_after") or 60)) from None
            if exc.code in (400, 404):
                raise BurgysInvalid(message) from None
            raise BurgysError(f"{exc.code}: {message}") from None
        except urllib.error.URLError as exc:
            raise BurgysUnreachable(
                f"Buergys Builds ist unter {self.url} nicht erreichbar: "
                f"{exc.reason}") from None

    # -- reading -------------------------------------------------------
    def health(self) -> dict:
        request = urllib.request.Request(self.url + "/health")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise BurgysUnreachable(str(exc.reason)) from None

    def capabilities(self) -> dict:
        return self._call("GET", "/capabilities")

    def status(self) -> dict:
        return self._call("GET", "/status")

    def queue(self) -> dict:
        return self._call("GET", "/queue")

    #: The API version this client was written against.  A server reporting
    #: something else may have changed a shape underneath us.
    EXPECTED_API_VERSION = 1

    def projects(self) -> list:
        return self._call("GET", "/projects")["projects"]

    def check_api_version(self) -> int:
        """Return the server's API version, complaining if it is unexpected."""
        version = int(self.capabilities().get("api_version", 0))
        if version != self.EXPECTED_API_VERSION:
            raise BurgysError(
                f"Buergys Builds spricht API-Version {version}, dieser Client "
                f"erwartet {self.EXPECTED_API_VERSION}")
        return version

    def project(self, project_id: str) -> dict:
        return self._call("GET", f"/projects/{project_id}")

    def build(self, build_id: str) -> dict:
        return self._call("GET", f"/builds/{build_id}")

    def logs(self, build_id: str, tail: int = 500) -> list:
        return self._call("GET", f"/builds/{build_id}/logs",
                          query={"tail": tail})["lines"]

    def artifacts(self, build_id: str) -> dict:
        return self._call("GET", f"/builds/{build_id}/artifacts")

    def audit(self, limit: int = 100, project: str | None = None) -> list:
        query: dict = {"limit": limit}
        if project:
            query["project"] = project
        return self._call("GET", "/audit", query=query)["entries"]

    def published(self) -> dict:
        return self._call("GET", "/published")["published"]

    # -- doing ---------------------------------------------------------
    def preflight(self, project: str, mode: str = "AD_HOC",
                  commit: str | None = None) -> dict:
        body = {"project": project, "mode": mode}
        if commit:
            body["commit"] = commit
        return self._call("POST", "/preflight", body)

    def request_build(self, project: str, mode: str = "AD_HOC", *,
                      dry_run: bool = True, commit: str | None = None) -> dict:
        """Ask for a build.

        ``dry_run`` defaults to True on purpose: the expensive, outward-facing
        thing should be the one you have to ask for explicitly.
        """
        body: dict = {"project": project, "mode": mode, "dry_run": dry_run}
        if commit:
            body["commit"] = commit
        return self._call("POST", "/builds", body)

    def cancel(self, build_id: str) -> dict:
        return self._call("POST", f"/builds/{build_id}/cancel", {})

    def approve(self, build_id: str) -> dict:
        """Needs the release token - it is the human-approval gate."""
        return self._call("POST", f"/builds/{build_id}/approve", {})

    def publish(self, build_id: str, *, apply: bool = False) -> dict:
        """Put an OTA release on the install page.  Needs the release token."""
        return self._call("POST", f"/builds/{build_id}/publish",
                          {"dry_run": not apply})

    # -- waiting -------------------------------------------------------
    def wait_for(self, build_id: str, *, interval: float = 5.0,
                 timeout: float = 2400.0) -> dict:
        """Poll until the build is finished, and return the final manifest.

        Stops at WAITING_APPROVAL too: that state waits for a person, and an
        agent spinning on it would wait for ever.
        """
        deadline = time.monotonic() + timeout
        state = "?"
        while True:
            try:
                manifest = self.build(build_id)
            except BurgysRateLimited as exc:
                # Polling too eagerly is our problem, not a reason to give
                # up on a build that is still running.  Wait it out.
                wait = min(exc.retry_after, max(0.0, deadline - time.monotonic()))
                if wait <= 0:
                    raise BurgysError(
                        f"{build_id}: Rate Limit und Zeitlimit erreicht") from None
                time.sleep(wait)
                continue
            state = manifest.get("status")
            if state in TERMINAL or state == "WAITING_APPROVAL":
                return manifest
            if time.monotonic() >= deadline:
                raise BurgysError(
                    f"{build_id} ist nach {timeout:.0f}s noch {state}")
            time.sleep(interval)

    # -- convenience ---------------------------------------------------
    def can(self, scope: str) -> bool:
        return scope in (self.capabilities().get("identity", {}).get("scopes") or [])

    def ready_for_real_builds(self) -> tuple:
        """``(ready, reasons)`` - why a real build would not work right now."""
        caps = self.capabilities()
        policy = caps["policy"]
        reasons = []
        if not policy["executor_produces_real_ipa"]:
            reasons.append(
                f"Executor {policy['executor']!r} erzeugt keine echte IPA")
        if "build" not in (caps["identity"]["scopes"] or []):
            reasons.append("Dieses Token darf keinen echten Build starten")
        if policy["approval_required_for_real_builds"]:
            reasons.append("Jeder echte Build wartet auf eine menschliche Freigabe")
        return (not reasons), reasons
