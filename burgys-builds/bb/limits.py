"""Build limit and duplicate detection (master brief, section 5).

"Real build" means a job that actually occupies a macOS executor.  Preflight,
Windows tests and dry runs are explicitly *not* counted, so the limit never
discourages the free work we want to happen on the HP.
"""
from __future__ import annotations

import datetime as _dt
from typing import Iterable

from . import states as S
from .errors import BuildLimitReached
from .store import read_json

WINDOW = _dt.timedelta(hours=24)

#: A build that reached one of these states occupied (or is occupying) a Mac.
COUNTS_AS_REAL = frozenset({
    S.WAITING_MAC, S.MAC_BUILDING, S.SIGNING, S.EXPORTING, S.VERIFYING,
    S.SUCCESS,
})


def _parse(ts: str | None) -> _dt.datetime | None:
    if not ts:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def counts_as_real_build(manifest: dict) -> bool:
    """True when this manifest represents a job that used a macOS executor."""
    if manifest.get("dry_run"):
        return False
    if manifest.get("reused_from"):
        # Re-published an existing artifact; no Mac was involved.
        return False
    if manifest.get("status") in COUNTS_AS_REAL:
        return True
    return bool(set(manifest.get("state_history_states") or []) & COUNTS_AS_REAL)


class BuildLimiter:
    def __init__(self, config, paths=None) -> None:
        self.config = config
        self.paths = paths or config.paths()
        self.max_per_day = int(config.get("max_real_builds_per_project_per_day", 20))

    def _manifests(self, project: str) -> Iterable[dict]:
        builds = self.paths.builds
        if not builds.exists():
            return []
        out = []
        for d in builds.iterdir():
            if not d.is_dir():
                continue
            m = read_json(d / "manifest.json")
            if m and m.get("project") == project:
                out.append(m)
        return out

    def recent_real_builds(self, project: str,
                           now: _dt.datetime | None = None) -> list:
        now = now or _dt.datetime.now()
        cutoff = now - WINDOW
        found = []
        for m in self._manifests(project):
            created = _parse(m.get("created_at"))
            if created is None or created < cutoff:
                continue
            if counts_as_real_build(m):
                found.append(m)
        return sorted(found, key=lambda m: m.get("created_at") or "")

    def status(self, project: str, now: _dt.datetime | None = None) -> dict:
        used = len(self.recent_real_builds(project, now))
        return {
            "project": project,
            "used": used,
            "limit": self.max_per_day,
            "remaining": max(0, self.max_per_day - used),
            "window_hours": 24,
        }

    def check(self, project: str, now: _dt.datetime | None = None) -> dict:
        st = self.status(project, now)
        if st["remaining"] <= 0:
            raise BuildLimitReached(
                f"{project}: {st['used']}/{st['limit']} echte Builds in den "
                "letzten 24 Stunden. Limit erreicht - kein weiterer macOS-Job. "
                "Preflight und lokale Tests bleiben erlaubt."
            )
        return st

    # -- duplicate detection -------------------------------------------
    def find_reusable(self, project: str, commit: str, mode: str) -> dict | None:
        """An existing successful build of the same commit in the same mode.

        Only a build whose artifact is still on disk with a recorded
        SHA-256 qualifies - a manifest alone is not an artifact.
        """
        best = None
        for m in self._manifests(project):
            if m.get("status") != S.SUCCESS:
                continue
            if (m.get("commit") or "").lower() != (commit or "").lower():
                continue
            if m.get("mode") != mode:
                continue
            if not m.get("artifact_sha256") or not m.get("artifact_path"):
                continue
            from pathlib import Path

            artifact = Path(m["artifact_path"])
            if not artifact.exists():
                continue
            if best is None or (m.get("created_at") or "") > (best.get("created_at") or ""):
                best = m
        return best
