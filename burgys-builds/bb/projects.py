"""Project registry.

A project is only buildable if it is listed here: the registry doubles as
the path allowlist demanded by section 20 of the brief.  Nothing in this
module ever takes a filesystem path from an API caller.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import DEFAULT_PROJECTS_FILE
from .errors import ConfigError, UnknownProject, ValidationError
from .ids import derive_code, validate_branch, validate_project_code, validate_project_id
from .store import read_json

MODE_AD_HOC = "AD_HOC"
MODE_DEVELOPMENT = "DEVELOPMENT"
MODE_APP_STORE = "APP_STORE_RELEASE"
MODES = (MODE_DEVELOPMENT, MODE_AD_HOC, MODE_APP_STORE)

# Migration states from section 25.
CODEMAGIC_ACTIVE = "CODEMAGIC_ACTIVE"
BURGYS_PARALLEL = "BURGYS_BUILDS_PARALLEL"
BURGYS_VERIFIED = "BURGYS_BUILDS_VERIFIED"
CODEMAGIC_DISABLED = "CODEMAGIC_DISABLED"
MIGRATION_STATES = (CODEMAGIC_ACTIVE, BURGYS_PARALLEL, BURGYS_VERIFIED, CODEMAGIC_DISABLED)


class Project:
    def __init__(self, data: dict) -> None:
        self.raw = dict(data)
        self.id = validate_project_id(data.get("id", ""))
        self.name = str(data.get("name") or self.id)
        self.code = validate_project_code(data.get("code") or derive_code(self.name))
        self.repository = str(data.get("repository") or "")
        self.branch = validate_branch(data.get("branch") or "main")
        self.local_path = data.get("local_path") or ""
        self.kind = str(data.get("kind") or "xcodegen-webview")
        self.bundle_id = str(data.get("bundle_id") or "")
        self.scheme = str(data.get("scheme") or "")
        self.xcodeproj = str(data.get("xcodeproj") or (self.scheme + ".xcodeproj" if self.scheme else ""))
        self.marketing_version = str(data.get("marketing_version") or "")
        self.display_name = str(data.get("display_name") or self.name)
        self.team_id = str(data.get("team_id") or "")
        self.preflight_command = data.get("preflight_command") or []
        self.required_files = list(data.get("required_files") or [])
        self.signing = dict(data.get("signing") or {})
        self.ota = dict(data.get("ota") or {})
        self.modes = tuple(data.get("modes") or (MODE_AD_HOC,))
        self.migration_state = str(data.get("migration_state") or CODEMAGIC_ACTIVE)
        self.enabled = bool(data.get("enabled", True))
        self._validate()

    def _validate(self) -> None:
        if self.migration_state not in MIGRATION_STATES:
            raise ConfigError(f"{self.id}: unknown migration_state {self.migration_state!r}")
        for mode in self.modes:
            if mode not in MODES:
                raise ConfigError(f"{self.id}: unknown mode {mode!r}")
        if self.bundle_id and not all(
            part and part.replace("-", "").isalnum() for part in self.bundle_id.split(".")
        ):
            raise ConfigError(f"{self.id}: implausible bundle id {self.bundle_id!r}")

    # -- paths ---------------------------------------------------------
    def path(self) -> Path:
        """The checkout on the HP.  Raises if the project has no local path."""
        if not self.local_path:
            raise ConfigError(
                f"{self.id}: kein local_path konfiguriert - Buergys Builds "
                "arbeitet nur auf Pfaden aus der Allowlist."
            )
        return Path(os.path.expandvars(os.path.expanduser(self.local_path))).resolve()

    def resolve_in_project(self, relative: str) -> Path:
        """Resolve ``relative`` inside the checkout, refusing to escape it."""
        root = self.path()
        if os.path.isabs(relative) or "\x00" in relative:
            raise ValidationError(f"{self.id}: {relative!r} must be a relative path")
        target = (root / relative).resolve()
        if target != root and root not in target.parents:
            raise ValidationError(f"{self.id}: {relative!r} escapes the project directory")
        return target

    def supports(self, mode: str) -> bool:
        return mode in self.modes

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "code": self.code,
            "repository": self.repository, "branch": self.branch,
            "kind": self.kind, "bundle_id": self.bundle_id, "scheme": self.scheme,
            "display_name": self.display_name, "team_id": self.team_id,
            "marketing_version": self.marketing_version,
            "modes": list(self.modes), "migration_state": self.migration_state,
            "enabled": self.enabled,
            "local_path_configured": bool(self.local_path),
            "ota_slug": self.ota.get("slug"),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project {self.id} ({self.code})>"


class Registry:
    def __init__(self, projects: list) -> None:
        self._by_id: dict[str, Project] = {}
        for p in projects:
            if p.id in self._by_id:
                raise ConfigError(f"duplicate project id {p.id!r}")
            codes = {x.code for x in self._by_id.values()}
            if p.code in codes:
                raise ConfigError(
                    f"duplicate project code {p.code!r} - build ids would collide"
                )
            self._by_id[p.id] = p

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Registry":
        path = Path(path) if path is not None else DEFAULT_PROJECTS_FILE
        data = read_json(path, default=None)
        if data is None:
            return cls([])
        if not isinstance(data, list):
            raise ConfigError(f"{path}: expected a list of projects")
        return cls([Project(d) for d in data])

    def all(self, include_disabled: bool = False) -> list:
        return [p for p in self._by_id.values() if include_disabled or p.enabled]

    def get(self, project_id: str) -> Project:
        validate_project_id(project_id)
        try:
            project = self._by_id[project_id]
        except KeyError:
            raise UnknownProject(
                f"unbekanntes Projekt {project_id!r}. Bekannt: "
                + (", ".join(sorted(self._by_id)) or "(keines)")
            ) from None
        if not project.enabled:
            raise UnknownProject(f"Projekt {project_id!r} ist deaktiviert")
        return project

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, project_id: object) -> bool:
        return project_id in self._by_id
