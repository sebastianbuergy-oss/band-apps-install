"""Build queue with restart recovery (master brief, sections 5 and 21).

The queue is a single JSON document guarded by a lock.  That is slower than
a database and far easier to reason about after a power cut, which is the
trade Sebastian's HP wants.
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any

from . import states as S
from .errors import ValidationError
from .ids import validate_build_id
from .manifest import BuildManifest
from .store import FileLock, read_json, write_json


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class BuildQueue:
    def __init__(self, paths) -> None:
        self.paths = paths
        self.path = paths.root / "queue.json"
        self.lock = paths.root / ".queue.lock"

    # -- raw ------------------------------------------------------------
    def _load(self) -> dict:
        data = read_json(self.path, default=None)
        if not data:
            return {"schema_version": 1, "waiting": [], "running": {}, "updated_at": _now()}
        return data

    def _save(self, data: dict) -> None:
        data["updated_at"] = _now()
        write_json(self.path, data)

    # -- queries --------------------------------------------------------
    def snapshot(self) -> dict:
        data = self._load()
        return {
            "waiting": list(data.get("waiting") or []),
            "running": dict(data.get("running") or {}),
            "length": len(data.get("waiting") or []),
            "updated_at": data.get("updated_at"),
        }

    def position(self, build_id: str) -> int | None:
        waiting = self._load().get("waiting") or []
        for i, entry in enumerate(waiting):
            if entry["build_id"] == build_id:
                return i + 1
        return None

    # -- mutations ------------------------------------------------------
    def enqueue(self, build_id: str, project: str, mode: str,
                priority: int = 100) -> dict:
        validate_build_id(build_id)
        with FileLock(self.lock, timeout=15):
            data = self._load()
            waiting = data.setdefault("waiting", [])
            if any(e["build_id"] == build_id for e in waiting):
                raise ValidationError(f"{build_id} steht bereits in der Queue")
            if build_id in (data.get("running") or {}):
                raise ValidationError(f"{build_id} laeuft bereits")
            entry = {"build_id": build_id, "project": project, "mode": mode,
                     "priority": int(priority), "queued_at": _now()}
            waiting.append(entry)
            # Stable sort: priority first, then arrival.  No starvation.
            waiting.sort(key=lambda e: (e["priority"], e["queued_at"]))
            self._save(data)
            return entry

    def claim(self, executor: str, project: str | None = None) -> dict | None:
        """Take the next job.  One job per project at a time (section 17)."""
        with FileLock(self.lock, timeout=15):
            data = self._load()
            waiting = data.setdefault("waiting", [])
            running = data.setdefault("running", {})
            busy_projects = {e["project"] for e in running.values()}
            for i, entry in enumerate(waiting):
                if project and entry["project"] != project:
                    continue
                if entry["project"] in busy_projects:
                    continue
                waiting.pop(i)
                entry = dict(entry, claimed_at=_now(), executor=executor,
                             owner_pid=os.getpid())
                running[entry["build_id"]] = entry
                self._save(data)
                return entry
            return None

    def release(self, build_id: str) -> bool:
        with FileLock(self.lock, timeout=15):
            data = self._load()
            removed = (data.setdefault("running", {}).pop(build_id, None) is not None)
            before = len(data.get("waiting") or [])
            data["waiting"] = [e for e in data.get("waiting") or []
                               if e["build_id"] != build_id]
            removed = removed or len(data["waiting"]) != before
            self._save(data)
            return removed

    def requeue(self, build_id: str) -> bool:
        with FileLock(self.lock, timeout=15):
            data = self._load()
            entry = data.setdefault("running", {}).pop(build_id, None)
            if entry is None:
                return False
            entry.pop("claimed_at", None)
            entry.pop("owner_pid", None)
            entry["queued_at"] = _now()
            data.setdefault("waiting", []).append(entry)
            data["waiting"].sort(key=lambda e: (e["priority"], e["queued_at"]))
            self._save(data)
            return True

    # -- recovery -------------------------------------------------------
    def recover(self, audit=None) -> dict:
        """Reconcile disk state after a restart.

        A job that was on a Mac when the controller died is marked
        interrupted rather than restarted: re-dispatching it automatically
        could spend macOS minutes twice (section 21, "keine Builds
        automatisch doppelt starten").
        """
        report: dict[str, Any] = {"interrupted": [], "requeued": [], "cleared": [],
                                  "at": _now()}
        with FileLock(self.lock, timeout=30):
            data = self._load()
            running = data.setdefault("running", {})
            for build_id, entry in list(running.items()):
                manifest = BuildManifest.load(self.paths.build_dir(build_id) / "manifest.json")
                if manifest is None:
                    running.pop(build_id)
                    report["cleared"].append(build_id)
                    continue
                if S.is_terminal(manifest.status):
                    running.pop(build_id)
                    report["cleared"].append(build_id)
                    continue
                if manifest.status in S.ON_MAC or manifest.status == S.WAITING_MAC:
                    running.pop(build_id)
                    manifest.set_state(
                        S.FAILED,
                        note="Controller-Neustart waehrend eines macOS-Jobs - "
                             "als unterbrochen markiert, nicht automatisch neu gestartet",
                        failure_reason="INTERRUPTED_BY_RESTART",
                    ).save(self.paths)
                    report["interrupted"].append(build_id)
                else:
                    running.pop(build_id)
                    entry.pop("claimed_at", None)
                    entry["queued_at"] = _now()
                    data.setdefault("waiting", []).append(entry)
                    report["requeued"].append(build_id)
            data["waiting"] = sorted(data.get("waiting") or [],
                                     key=lambda e: (e["priority"], e["queued_at"]))
            # Drop waiting entries whose manifest is gone or already finished.
            kept = []
            for entry in data["waiting"]:
                manifest = BuildManifest.load(
                    self.paths.build_dir(entry["build_id"]) / "manifest.json")
                if manifest is None or S.is_terminal(manifest.status):
                    report["cleared"].append(entry["build_id"])
                    continue
                kept.append(entry)
            data["waiting"] = kept
            self._save(data)
        if audit is not None:
            from .audit import BUILD_STATE

            for build_id in report["interrupted"]:
                audit.record(BUILD_STATE, build_id=build_id, result="interrupted",
                             detail="Neustart-Recovery")
        return report
