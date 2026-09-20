"""The macOS executor layer (master brief, section 7).

Buergys Builds must not be welded to one provider.  Everything that needs a
Mac goes through :class:`MacExecutor`; today the only honest implementation
is :class:`~bb.executors.none.NoMacExecutor`, because Sebastian has no Mac
and no approved paid Mac.  A future Mac mini plugs in as
``Burgys-iOS-Runner`` without the pipeline above it changing.
"""
from __future__ import annotations

import abc
import datetime as _dt
from typing import Any

from ..errors import ConfigError, ExecutorUnavailable

AVAILABLE = "AVAILABLE"
BUSY = "BUSY"
OFFLINE = "OFFLINE"


class MacJob:
    """Everything a Mac needs, and nothing it does not.

    No secrets travel in this object: the executor resolves its own
    credentials from its own secret store at the far end.
    """

    def __init__(self, *, build_id: str, project_id: str, repository: str,
                 branch: str, commit: str, mode: str, scheme: str,
                 xcodeproj: str, bundle_id: str, build_number: int,
                 marketing_version: str, profile_name: str,
                 team_id: str = "", dry_run: bool = False) -> None:
        self.build_id = build_id
        self.project_id = project_id
        self.repository = repository
        self.branch = branch
        self.commit = commit
        self.mode = mode
        self.scheme = scheme
        self.xcodeproj = xcodeproj
        self.bundle_id = bundle_id
        self.build_number = build_number
        self.marketing_version = marketing_version
        self.profile_name = profile_name
        self.team_id = team_id
        self.dry_run = dry_run

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class MacJobResult:
    def __init__(self, *, state: str, detail: str = "", artifact_path: str | None = None,
                 log_excerpt: str = "", minutes: float = 0.0,
                 simulated: bool = False, raw: Any = None) -> None:
        self.state = state
        self.detail = detail
        self.artifact_path = artifact_path
        self.log_excerpt = log_excerpt
        self.minutes = minutes
        #: True whenever no real Xcode ran.  Never allowed to reach a user
        #: surface as a successful iOS build (brief, section 28).
        self.simulated = simulated
        self.raw = raw

    def to_dict(self) -> dict:
        return {"state": self.state, "detail": self.detail,
                "artifact_path": self.artifact_path, "minutes": self.minutes,
                "simulated": self.simulated}


class MacExecutor(abc.ABC):
    """Interface every Mac backend implements."""

    #: Stable name used in manifests, the audit log and the dashboard.
    name = "abstract"
    #: Which cost-guard resource this executor consumes.
    cost_resource = "unknown"
    #: True only when a real Xcode toolchain runs.  A dry-run backend is False.
    produces_real_ipa = False

    def __init__(self, config: dict | None = None) -> None:
        self.config = dict(config or {})

    @abc.abstractmethod
    def availability(self) -> str:
        """AVAILABLE, BUSY or OFFLINE.  Must never raise."""

    @abc.abstractmethod
    def submit(self, job: MacJob) -> str:
        """Start the job, return an opaque handle.  Raises on refusal."""

    @abc.abstractmethod
    def poll(self, handle: str) -> MacJobResult:
        """Current state of a submitted job."""

    def cancel(self, handle: str) -> bool:
        return False

    def fetch_artifact(self, handle: str, dest_dir) -> str | None:
        return None

    def describe(self) -> dict:
        return {
            "name": self.name,
            "availability": self.availability(),
            "cost_resource": self.cost_resource,
            "produces_real_ipa": self.produces_real_ipa,
            "checked_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }


_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    _REGISTRY[cls.name] = cls
    return cls


def _load_backends() -> None:
    """Import the backends so that ``@register`` has run.

    Done lazily and in one place: importing them at module scope would make
    :mod:`bb.executors` and its own submodules import each other.
    """
    from . import dryrun, github, local, none  # noqa: F401  (registration)


def available_executors() -> list:
    _load_backends()
    return sorted(_REGISTRY)


def get_executor(name: str, config: dict | None = None) -> MacExecutor:
    _load_backends()
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise ConfigError(
            f"unbekannter Executor {name!r}. Bekannt: {', '.join(available_executors())}"
        ) from None
    return cls(config)


__all__ = [
    "AVAILABLE", "BUSY", "OFFLINE", "MacExecutor", "MacJob", "MacJobResult",
    "ExecutorUnavailable", "get_executor", "available_executors", "register",
]
