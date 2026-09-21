"""Configuration.

Defaults are the safe ones.  A config file may only be read from the
controller's own ``config/`` directory, and environment variables override
it so that the cost guard can be tightened (never loosened silently) from a
shell.  There is exactly one switch that can allow money to be spent and it
is false here.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .store import read_json

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = PACKAGE_ROOT / "config" / "burgys.json"
DEFAULT_PROJECTS_FILE = PACKAGE_ROOT / "config" / "projects.json"

DEFAULTS: dict[str, Any] = {
    # --- cost ---------------------------------------------------------
    "paid_services_allowed": False,
    # --- build limit --------------------------------------------------
    "max_real_builds_per_project_per_day": 20,
    "reuse_artifact_for_identical_commit": True,
    # --- approval -----------------------------------------------------
    # A real macOS job always needs a human yes until Sebastian turns this
    # off per project; brief section 29.
    "require_approval_for_mac_builds": True,
    "require_approval_for_app_store_upload": True,
    # --- executor -----------------------------------------------------
    "default_executor": "none",
    "mac_job_timeout_minutes": 30,
    # --- storage ------------------------------------------------------
    "data_root": str(PACKAGE_ROOT / "data"),
    "retention_days_builds": 90,
    "retention_days_logs": 90,
    "retention_keep_artifacts_per_project": 10,
    "min_free_bytes": 2 * 1024 ** 3,
    "warn_free_bytes": 10 * 1024 ** 3,
    # --- api ----------------------------------------------------------
    "api_host": "127.0.0.1",
    "api_port": 8787,
    "api_rate_limit_per_minute": 120,
    # Where the agent token lives.  Never the repository.
    "api_token_file": str(Path.home() / ".burgys" / "agent_token"),
    # --- ota ----------------------------------------------------------
    "ota_base_url": "https://sebastianbuergy-oss.github.io/band-apps-install",
    "ota_publish_dir": "",
    # Empty means the repository's own .burgys/state.json (brief, section 18).
    "agent_state_file": "",
}

#: Environment overrides.  Booleans accept 1/true/yes/on.
_ENV = {
    "PAID_SERVICES_ALLOWED": ("paid_services_allowed", "bool"),
    "BURGYS_DATA": ("data_root", "str"),
    "BURGYS_API_HOST": ("api_host", "str"),
    "BURGYS_API_PORT": ("api_port", "int"),
    "BURGYS_API_TOKEN_FILE": ("api_token_file", "str"),
    "BURGYS_MAX_BUILDS_PER_DAY": ("max_real_builds_per_project_per_day", "int"),
    "BURGYS_REQUIRE_APPROVAL": ("require_approval_for_mac_builds", "bool"),
    "BURGYS_OTA_BASE_URL": ("ota_base_url", "str"),
    "BURGYS_AGENT_STATE_FILE": ("agent_state_file", "str"),
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Config(dict):
    """A plain dict with attribute-ish helpers and no surprises."""

    @property
    def data_root(self) -> Path:
        return Path(self["data_root"])

    def paths(self):
        from .store import Paths

        return Paths(self["data_root"])


def load_config(path: str | os.PathLike | None = None,
                env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    cfg = Config(DEFAULTS)
    file_path = Path(path) if path is not None else DEFAULT_CONFIG_FILE
    from_file = read_json(file_path, default={}) or {}
    unknown = sorted(set(from_file) - set(DEFAULTS))
    if unknown:
        # Loud, not silent: a typo in the cost guard key must not read as
        # "the guard is off".
        raise_unknown(file_path, unknown)
    cfg.update(from_file)
    for var, (key, kind) in _ENV.items():
        if var not in env:
            continue
        raw = env[var]
        if kind == "bool":
            cfg[key] = _as_bool(raw)
        elif kind == "int":
            cfg[key] = int(raw)
        else:
            cfg[key] = raw
    cfg["paid_services_allowed"] = _as_bool(cfg["paid_services_allowed"])
    return cfg


def raise_unknown(file_path: Path, unknown: list) -> None:
    from .errors import ConfigError

    raise ConfigError(
        f"{file_path}: unknown configuration key(s) {', '.join(unknown)}. "
        "Refusing to start rather than run with a setting that is silently ignored."
    )
