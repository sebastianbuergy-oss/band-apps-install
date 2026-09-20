"""Build states (master brief, section 13).

The state names are part of the contract between Claude, Codex and Buergys
Agent, so they are spelled exactly as agreed and the legal transitions are
enforced rather than documented.
"""
from __future__ import annotations

from .errors import TransitionError

DISCOVERED = "DISCOVERED"
PREFLIGHT = "PREFLIGHT"
READY = "READY"
WAITING_APPROVAL = "WAITING_APPROVAL"
QUEUED = "QUEUED"
WINDOWS_TESTING = "WINDOWS_TESTING"
WAITING_MAC = "WAITING_MAC"
MAC_BUILDING = "MAC_BUILDING"
SIGNING = "SIGNING"
EXPORTING = "EXPORTING"
VERIFYING = "VERIFYING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"
BLOCKED = "BLOCKED"
BLOCKED_BY_COST_GUARD = "BLOCKED_BY_COST_GUARD"
CANCELLED = "CANCELLED"

ALL = (
    DISCOVERED, PREFLIGHT, READY, WAITING_APPROVAL, QUEUED, WINDOWS_TESTING,
    WAITING_MAC, MAC_BUILDING, SIGNING, EXPORTING, VERIFYING, SUCCESS,
    FAILED, BLOCKED, BLOCKED_BY_COST_GUARD, CANCELLED,
)

#: States from which nothing else can happen.
TERMINAL = frozenset({SUCCESS, FAILED, BLOCKED, BLOCKED_BY_COST_GUARD, CANCELLED})

#: States in which a macOS executor is holding the job.  Used by restart
#: recovery: anything found here after a controller restart was interrupted.
ON_MAC = frozenset({MAC_BUILDING, SIGNING, EXPORTING})

#: States that consume macOS wall-clock time and therefore money later.
BILLABLE_MAC = ON_MAC | {WAITING_MAC}

#: Any state may always fail, be blocked or be cancelled, so those edges are
#: added to every non-terminal state instead of being repeated below.
_ALWAYS = frozenset({FAILED, BLOCKED, BLOCKED_BY_COST_GUARD, CANCELLED})

_FORWARD = {
    DISCOVERED: {PREFLIGHT},
    PREFLIGHT: {READY, WINDOWS_TESTING},
    WINDOWS_TESTING: {READY},
    READY: {WAITING_APPROVAL, QUEUED},
    WAITING_APPROVAL: {QUEUED, READY},
    # QUEUED -> VERIFYING is the artifact-reuse path: an identical
    # commit was already built, so there is nothing to build, only
    # the existing IPA to re-verify.
    QUEUED: {WAITING_MAC, WINDOWS_TESTING, VERIFYING},
    WAITING_MAC: {MAC_BUILDING},
    MAC_BUILDING: {SIGNING},
    SIGNING: {EXPORTING},
    EXPORTING: {VERIFYING},
    VERIFYING: {SUCCESS},
    SUCCESS: set(),
    FAILED: set(),
    BLOCKED: set(),
    BLOCKED_BY_COST_GUARD: set(),
    CANCELLED: set(),
}

TRANSITIONS = {
    state: frozenset(targets | (set() if state in TERMINAL else _ALWAYS))
    for state, targets in _FORWARD.items()
}


def can_transition(src: str, dst: str) -> bool:
    if src not in TRANSITIONS or dst not in ALL:
        return False
    return dst in TRANSITIONS[src]


def check_transition(src: str, dst: str) -> None:
    """Raise :class:`TransitionError` unless ``src -> dst`` is legal."""
    if src not in TRANSITIONS:
        raise TransitionError(f"unknown source state {src!r}")
    if dst not in ALL:
        raise TransitionError(f"unknown target state {dst!r}")
    if dst not in TRANSITIONS[src]:
        raise TransitionError(f"illegal transition {src} -> {dst}")


def is_terminal(state: str) -> bool:
    return state in TERMINAL
