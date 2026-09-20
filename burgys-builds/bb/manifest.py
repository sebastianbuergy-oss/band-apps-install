"""Build manifest (master brief, section 14).

One JSON file per build, written atomically after every state change, so
that the queue, the dashboard, Buergys Agent and a restarted controller all
read the same truth.  Secrets never enter it - :func:`bb.redact.redact` runs
on the way in.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from . import states as S
from .errors import ValidationError
from .ids import validate_build_id
from .redact import redact
from .store import FileLock, read_json, write_json

SCHEMA_VERSION = 1


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class BuildManifest:
    def __init__(self, data: dict) -> None:
        self.data = data

    # -- construction ---------------------------------------------------
    @classmethod
    def create(cls, *, build_id: str, project, commit: str, branch: str,
               mode: str, build_number: int, requested_by: str,
               executor: str, dry_run: bool = False) -> "BuildManifest":
        validate_build_id(build_id)
        return cls({
            "schema_version": SCHEMA_VERSION,
            "build_id": build_id,
            "project": project.id,
            "project_name": project.name,
            "repository": project.repository,
            "branch": branch,
            "commit": commit,
            "version": project.marketing_version,
            "build_number": str(build_number),
            "bundle_id": project.bundle_id,
            "mode": mode,
            "requested_by": requested_by,
            "status": S.DISCOVERED,
            "executor": executor,
            "dry_run": bool(dry_run),
            "reused_from": None,
            "artifact_sha256": None,
            "artifact_path": None,
            "artifact_bytes": None,
            "created_at": _now(),
            "updated_at": _now(),
            "finished_at": None,
            "failure_reason": None,
            "approval": None,
            "preflight": None,
            "mac_minutes": 0.0,
            "windows_seconds": 0.0,
            "ota": None,
            "state_history": [{"state": S.DISCOVERED, "at": _now(), "note": "angelegt"}],
            "state_history_states": [S.DISCOVERED],
        })

    @classmethod
    def load(cls, path: str | Path) -> "BuildManifest | None":
        data = read_json(path)
        return cls(data) if data else None

    # -- accessors ------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def build_id(self) -> str:
        return self.data["build_id"]

    @property
    def status(self) -> str:
        return self.data["status"]

    @property
    def is_dry_run(self) -> bool:
        return bool(self.data.get("dry_run"))

    def display_status(self) -> str:
        """Never let a dry run read as a successful iOS build (section 28)."""
        if self.is_dry_run and self.status == S.SUCCESS:
            return "SUCCESS (DRY RUN - kein echter iOS-Build)"
        if self.data.get("reused_from") and self.status == S.SUCCESS:
            return f"SUCCESS (Artefakt aus {self.data['reused_from']} wiederverwendet)"
        return self.status

    # -- mutation -------------------------------------------------------
    def set_state(self, new_state: str, note: str = "", **fields: Any) -> "BuildManifest":
        S.check_transition(self.status, new_state)
        self.data["status"] = new_state
        self.data["updated_at"] = _now()
        entry = {"state": new_state, "at": self.data["updated_at"]}
        if note:
            entry["note"] = note
        self.data["state_history"].append(entry)
        self.data["state_history_states"].append(new_state)
        if S.is_terminal(new_state):
            self.data["finished_at"] = self.data["updated_at"]
        self.update(**fields)
        return self

    def update(self, **fields: Any) -> "BuildManifest":
        for key, value in fields.items():
            if key in ("status", "state_history", "state_history_states", "build_id"):
                raise ValidationError(f"{key} darf nicht direkt gesetzt werden")
            self.data[key] = value
        self.data["updated_at"] = _now()
        return self

    # -- persistence ----------------------------------------------------
    def save(self, paths) -> Path:
        directory = paths.build_dir(self.build_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "manifest.json"
        with FileLock(directory / ".manifest.lock", timeout=15):
            write_json(target, redact(self.data))
        return target

    def to_dict(self) -> dict:
        out = redact(dict(self.data))
        out["display_status"] = self.display_status()
        return out


class BuildNumbers:
    """Monotonic build numbers per project.

    CFBundleVersion must never go backwards for App Store builds, and
    Codemagic has already handed out numbers we cannot see from here.  The
    floor is therefore configuration, not a guess: without it, App Store
    mode refuses to allocate.
    """

    def __init__(self, paths) -> None:
        self.paths = paths

    def _file(self, project_id: str) -> Path:
        from .ids import validate_project_id
        from .store import safe_child

        validate_project_id(project_id)
        return safe_child(self.paths.projects, project_id, "build_number.json")

    def peek(self, project_id: str, floor: int = 0) -> int:
        data = read_json(self._file(project_id), default={}) or {}
        return max(int(data.get("last") or 0), int(floor)) + 1

    def allocate(self, project_id: str, floor: int = 0) -> int:
        path = self._file(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(path.parent / ".build_number.lock", timeout=15):
            data = read_json(path, default={}) or {}
            nxt = max(int(data.get("last") or 0), int(floor)) + 1
            write_json(path, {"last": nxt, "at": _now()})
            return nxt

    def sequence_for_day(self, project_code: str, day: _dt.date) -> int:
        """Next ``NNN`` for ``BB-YYYYMMDD-CODE-NNN``."""
        prefix = f"BB-{day:%Y%m%d}-{project_code}-"
        used = [
            int(d.name[len(prefix):])
            for d in self.paths.builds.glob(prefix + "*")
            if d.is_dir() and d.name[len(prefix):].isdigit()
        ]
        return max(used, default=0) + 1
