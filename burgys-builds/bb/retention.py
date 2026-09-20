"""Retention (master brief, section 22).

The configuration has always named a retention policy; until now nothing
enforced it, so ``data/`` grew without limit.  This module prunes it.

Two rules, and the safer one always wins:

* a build older than ``retention_days_builds`` may go, and its log with it;
* per project, the newest ``retention_keep_artifacts_per_project`` artifacts
  are kept regardless of age.

Anything still referenced by a published OTA release, and anything that is
not finished yet, is never touched.  Pruning is opt-in per call and reports
what it would do before it does anything (``dry_run=True``).
"""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path

from . import states as S
from .manifest import BuildManifest
from .store import read_json


def _parse(ts: str | None) -> _dt.datetime | None:
    if not ts:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


class RetentionPlan:
    def __init__(self) -> None:
        self.remove_builds: list = []
        self.remove_artifacts: list = []
        self.remove_logs: list = []
        self.kept_reasons: dict = {}
        self.freed_bytes = 0

    @property
    def empty(self) -> bool:
        return not (self.remove_builds or self.remove_artifacts or self.remove_logs)

    def to_dict(self) -> dict:
        return {
            "builds": sorted(self.remove_builds),
            "artifacts": sorted(self.remove_artifacts),
            "logs": sorted(self.remove_logs),
            "freed_bytes": self.freed_bytes,
            "freed_mb": round(self.freed_bytes / 2 ** 20, 1),
            "kept": self.kept_reasons,
        }


def plan(config, paths=None, now: _dt.datetime | None = None) -> RetentionPlan:
    """Work out what could be removed, without removing anything."""
    paths = paths or config.paths()
    now = now or _dt.datetime.now()
    keep_days_builds = int(config.get("retention_days_builds", 90))
    keep_days_logs = int(config.get("retention_days_logs", 90))
    keep_per_project = int(config.get("retention_keep_artifacts_per_project", 10))

    result = RetentionPlan()
    manifests: list = []
    if paths.builds.exists():
        for directory in sorted(paths.builds.iterdir()):
            if not directory.is_dir():
                continue
            manifest = BuildManifest.load(directory / "manifest.json")
            if manifest is not None:
                manifests.append(manifest)

    # Newest first per project, so "keep the last N artifacts" is easy.
    by_project: dict = {}
    for m in sorted(manifests, key=lambda m: m.get("created_at") or "", reverse=True):
        by_project.setdefault(m.get("project") or "?", []).append(m)

    protected_artifacts = set()
    for project, entries in by_project.items():
        with_artifact = [m for m in entries if m.get("artifact_sha256")]
        for m in with_artifact[:keep_per_project]:
            protected_artifacts.add(m.build_id)

    for m in manifests:
        build_id = m.build_id
        created = _parse(m.get("created_at"))
        age_days = (now - created).days if created else 0

        if not S.is_terminal(m.status):
            result.kept_reasons[build_id] = "laeuft noch"
            continue
        if m.get("ota"):
            # A published OTA release points at this artifact by URL and
            # checksum; deleting it would break an install page.
            result.kept_reasons[build_id] = "OTA veroeffentlicht"
            continue

        artifact_dir = paths.artifacts / build_id
        if build_id in protected_artifacts:
            result.kept_reasons[build_id] = "gehoert zu den neuesten Artefakten"
        elif artifact_dir.exists():
            result.freed_bytes += _dir_size(artifact_dir)
            result.remove_artifacts.append(build_id)

        if age_days >= keep_days_builds:
            result.freed_bytes += _dir_size(paths.build_dir(build_id))
            result.remove_builds.append(build_id)

        log = paths.log_file(build_id)
        if log.exists() and age_days >= keep_days_logs:
            result.freed_bytes += log.stat().st_size
            result.remove_logs.append(build_id)

    return result


def apply(config, paths=None, now: _dt.datetime | None = None,
          dry_run: bool = True, audit=None) -> dict:
    """Execute (or merely report) the plan."""
    paths = paths or config.paths()
    result = plan(config, paths, now)
    if dry_run:
        out = result.to_dict()
        out["dry_run"] = True
        return out

    for build_id in result.remove_artifacts:
        shutil.rmtree(paths.artifacts / build_id, ignore_errors=True)
    for build_id in result.remove_logs:
        try:
            paths.log_file(build_id).unlink()
        except OSError:
            pass
    for build_id in result.remove_builds:
        shutil.rmtree(paths.build_dir(build_id), ignore_errors=True)

    out = result.to_dict()
    out["dry_run"] = False
    if audit is not None:
        from .audit import BUILD_STATE

        audit.record(BUILD_STATE, actor="retention", result="pruned",
                     detail={"builds": len(result.remove_builds),
                             "artifacts": len(result.remove_artifacts),
                             "logs": len(result.remove_logs),
                             "freed_mb": out["freed_mb"]})
    return out
