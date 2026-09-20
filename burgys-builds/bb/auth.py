"""Agent authentication (master brief, sections 19 and 20).

Two tokens with different reach, generated on first start and stored
outside the repository with owner-only permissions:

``agent``    read status, run preflight, prepare a build - the things
             Buergys Agent may do unattended.
``release``  additionally start a real macOS build, approve one and trigger
             an App Store upload.  These cost money or reach the outside
             world, so they need the second token on purpose.
"""
from __future__ import annotations

import hmac
import os
import secrets
import stat
from pathlib import Path

from .errors import ConfigError
from .store import read_json, write_json

READ = "read"
PREFLIGHT = "preflight"
PREPARE = "prepare"
BUILD = "build"
RELEASE = "release"

SCOPES = {
    "agent": [READ, PREFLIGHT, PREPARE],
    "release": [READ, PREFLIGHT, PREPARE, BUILD, RELEASE],
}


class TokenStore:
    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path).expanduser()

    def ensure(self) -> dict:
        """Create the token file if it is missing.  Never overwrite one."""
        data = read_json(self.path, default=None)
        if data and data.get("tokens"):
            return data
        data = {
            "note": "Buergys Builds Agent-Tokens. Diese Datei gehoert NICHT "
                    "ins Repository und nicht in ein Backup, das jemand "
                    "anders lesen kann.",
            "tokens": [
                {"name": name, "token": secrets.token_urlsafe(32), "scopes": scopes}
                for name, scopes in SCOPES.items()
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.path, data)
        self._lock_down()
        return data

    def _lock_down(self) -> None:
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            # Windows ignores POSIX modes; NTFS inheritance is the guard there.
            pass

    def permissions_state(self) -> str:
        """``"ok"``, ``"too-open"`` or ``"unchecked"``.

        Windows ignores POSIX modes, so there is nothing for us to read
        there.  Reporting "ok" in that case would be a claim we have not
        earned - the file may well be readable by other local accounts - so
        Windows gets an honest "unchecked" and the CLI says so.
        """
        if os.name == "nt":
            return "unchecked"
        try:
            mode = stat.S_IMODE(self.path.stat().st_mode)
        except OSError:
            return "too-open"
        return "ok" if not (mode & (stat.S_IRWXG | stat.S_IRWXO)) else "too-open"

    def permissions_ok(self) -> bool:
        """True only when we actually verified the mode and it was tight."""
        return self.permissions_state() == "ok"

    def tokens(self) -> list:
        data = read_json(self.path, default=None)
        if not data or not data.get("tokens"):
            raise ConfigError(
                f"Keine Tokendatei unter {self.path}. "
                "`python -m bb.cli init` legt sie an.")
        return data["tokens"]

    def identify(self, presented: str | None) -> dict | None:
        """Return the matching token entry, comparing in constant time."""
        if not presented:
            return None
        for entry in self.tokens():
            if hmac.compare_digest(str(entry.get("token", "")), presented):
                return entry
        return None

    def allows(self, presented: str | None, scope: str) -> dict | None:
        entry = self.identify(presented)
        if entry and scope in (entry.get("scopes") or []):
            return entry
        return None
