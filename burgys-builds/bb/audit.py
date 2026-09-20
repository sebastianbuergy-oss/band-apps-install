"""Audit log (master brief, section 15).

Append-only JSON Lines, one file per month, every record redacted before it
touches the disk.  Append-only matters: the log is the only evidence that a
signing key was used or that the cost guard stopped something.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Iterator

from .redact import redact
from .store import FileLock

# Actions worth their own constant because other modules must spell them the
# same way for the dashboard and for Buergys Agent.
BUILD_REQUESTED = "build.requested"
BUILD_STARTED = "build.started"
BUILD_STATE = "build.state"
BUILD_CANCELLED = "build.cancelled"
BUILD_FINISHED = "build.finished"
SIGNING_USED = "signing.used"
ARTIFACT_CREATED = "artifact.created"
OTA_PUBLISHED = "ota.published"
APP_STORE_UPLOAD = "appstore.upload"
COST_GUARD_BLOCKED = "costguard.blocked"
LIMIT_BLOCKED = "limit.blocked"
PREFLIGHT_RUN = "preflight.run"
APPROVAL_GRANTED = "approval.granted"
API_DENIED = "api.denied"


class AuditLog:
    def __init__(self, paths) -> None:
        self.paths = paths
        self.dir = Path(paths.root) / "audit"

    def _file(self, when: _dt.datetime | None = None) -> Path:
        when = when or _dt.datetime.now()
        return self.dir / f"audit-{when:%Y-%m}.jsonl"

    def record(self, action: str, *, actor: str = "system", project: str | None = None,
               build_id: str | None = None, commit: str | None = None,
               executor: str | None = None, result: str = "ok",
               detail: Any = None, when: _dt.datetime | None = None) -> dict:
        when = when or _dt.datetime.now(_dt.timezone.utc).astimezone()
        entry = {
            "at": when.isoformat(timespec="seconds"),
            "actor": actor,
            "action": action,
            "project": project,
            "build_id": build_id,
            "commit": commit,
            "executor": executor,
            "result": result,
            "detail": detail,
        }
        entry = redact(entry)
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._file(when)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with FileLock(self.dir / ".audit.lock", timeout=15):
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        return entry

    def read(self, limit: int = 200, project: str | None = None,
             action: str | None = None) -> list:
        """Newest first.  Reads every monthly file, newest month first."""
        out: list = []
        if not self.dir.exists():
            return out
        for path in sorted(self.dir.glob("audit-*.jsonl"), reverse=True):
            for entry in reversed(list(_iter_lines(path))):
                if project and entry.get("project") != project:
                    continue
                if action and entry.get("action") != action:
                    continue
                out.append(entry)
                if len(out) >= limit:
                    return out
        return out


def _iter_lines(path: Path) -> Iterator[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # A torn last line after a crash must not hide the rest.
                    continue
    except FileNotFoundError:
        return
