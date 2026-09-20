"""Errors the controller raises.  Every one of them is a *refusal*, never a
partial success: the pipeline stops and the reason is recorded verbatim.
"""


class BurgysError(Exception):
    """Base class.  ``state`` is the build state the caller should move to."""

    state = "FAILED"


class ConfigError(BurgysError):
    """Configuration is missing or contradictory."""

    state = "BLOCKED"


class ValidationError(BurgysError):
    """Untrusted input failed validation (ids, paths, commits, names)."""

    state = "BLOCKED"


class UnknownProject(ValidationError):
    pass


class CostGuardBlocked(BurgysError):
    """A paid resource was requested while PAID_SERVICES_ALLOWED is false."""

    state = "BLOCKED_BY_COST_GUARD"


class BuildLimitReached(BurgysError):
    """The per-project 24h real-build limit is exhausted."""

    state = "BLOCKED"


class PreflightFailed(BurgysError):
    state = "FAILED"


class SigningError(BurgysError):
    """Signing material is missing, expired or contradicts the project."""

    state = "BLOCKED"


class ExecutorUnavailable(BurgysError):
    """No macOS executor can take the job right now."""

    state = "BLOCKED"


class StorageError(BurgysError):
    state = "FAILED"


class DiskFull(StorageError):
    state = "BLOCKED"


class TransitionError(BurgysError):
    """An illegal build-state transition was attempted."""

    state = "FAILED"
