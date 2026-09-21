"""The shared state file (master brief, section 18).

``.burgys/state.json`` is what Buergys Agent, Claude and Codex read before
they do anything.  Until now it was maintained by hand, which means it was
accurate exactly as long as someone remembered - not a basis for an agent.

This module writes it from what the controller actually knows, atomically,
so a reader never sees half a file.  The hand-written fields that describe
*intent* (decisions, open tasks) are preserved: only the machine-observable
parts are overwritten.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from . import states as S
from .store import read_json, write_json

SCHEMA_VERSION = 1

#: Keys this module owns.  Everything else in the file is left alone, so a
#: human can keep notes there without them being wiped on the next write.
OWNED = ("schema_version", "project", "current_commit", "last_agent",
         "last_handoff", "system_status", "builds", "updated_at")


def _repo_root(paths) -> Path:
    """The repository the controller lives in, not the data directory."""
    return Path(__file__).resolve().parent.parent.parent


def state_path(config=None, paths=None) -> Path:
    """Where the shared state file lives.

    ``agent_state_file`` wins when set - which is what keeps a test run from
    writing into the repository's own ``.burgys/state.json``.
    """
    configured = (config or {}).get("agent_state_file") if config else None
    if configured:
        return Path(configured).expanduser()
    return _repo_root(paths) / ".burgys" / "state.json"


def snapshot(controller) -> dict:
    """The machine-observable half of the state file.

    Deliberately cheap and entirely local: it reads manifests and the queue
    and asks the executor for its *declared* nature, never for its live
    availability.  Probing a GitHub executor means an HTTP round trip, and
    this runs often enough that a network call here would make every build
    slower and every offline machine hang.
    """
    from .store import disk_status

    builds = controller.list_builds(limit=50)
    running = [m for m in builds if not S.is_terminal(m.status)]
    waiting = [m for m in builds if m.status == S.WAITING_APPROVAL]
    last_success = next((m for m in builds
                         if m.status == S.SUCCESS and not m.is_dry_run), None)
    from .executors import get_executor

    executor_name = controller.config.get("default_executor") or "none"
    try:
        produces_real_ipa = get_executor(executor_name).produces_real_ipa
    except Exception:  # noqa: BLE001 - an unknown executor is not a crash here
        produces_real_ipa = False
    today = _dt.date.today().isoformat()
    todays = [m for m in builds if (m.get("created_at") or "")[:10] == today]
    disk = disk_status(controller.paths.root,
                       int(controller.config.get("min_free_bytes", 0)),
                       int(controller.config.get("warn_free_bytes", 0)))
    return {
        "schema_version": SCHEMA_VERSION,
        "project": "burgys-builds",
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "system_status": {
            "windows_controller": "ONLINE",
            # Declared, not probed - see the docstring.
            "mac_executor_name": executor_name,
            "mac_executor_produces_real_ipa": produces_real_ipa,
            "cost_guard": not controller.cost_guard.allowed,
            "disk": disk["level"],
        },
        "builds": {
            "today": {
                "total": len(todays),
                "success": sum(1 for m in todays if m.status == S.SUCCESS),
                "failed": sum(1 for m in todays
                              if m.status in (S.FAILED, S.BLOCKED,
                                              S.BLOCKED_BY_COST_GUARD)),
                "dry_runs": sum(1 for m in todays if m.is_dry_run),
            },
            "queue_length": controller.queue.snapshot()["length"],
            "running": [m.build_id for m in running],
            "waiting_approval": [m.build_id for m in waiting],
            "last_success": (
                {"build_id": last_success.build_id,
                 "project": last_success.get("project"),
                 "commit": last_success.get("commit"),
                 "version": last_success.get("version"),
                 "build_number": last_success.get("build_number"),
                 "artifact_sha256": last_success.get("artifact_sha256"),
                 "finished_at": last_success.get("finished_at")}
                if last_success else None),
        },
    }


def update(controller, *, agent: str | None = None,
           current_commit: str | None = None, path=None) -> Path:
    """Merge a fresh snapshot into the state file, keeping human notes."""
    target = Path(path) if path is not None else state_path(controller.config,
                                                            controller.paths)
    existing = read_json(target, default={}) or {}
    merged = dict(existing)
    merged.update(snapshot(controller))
    if agent:
        merged["last_agent"] = agent
    if current_commit is not None:
        merged["current_commit"] = current_commit
    else:
        merged.setdefault("current_commit", existing.get("current_commit", ""))
    merged.setdefault("last_handoff", existing.get("last_handoff", ""))
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, merged)
    return target


def read(config=None, paths=None, path=None) -> dict[str, Any]:
    return read_json(Path(path) if path is not None
                     else state_path(config, paths), default={}) or {}
