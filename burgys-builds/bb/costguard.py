"""Cost guard (master brief, section 4) - a hard system requirement.

The guard classifies every resource the controller can reach.  Anything
classified PAID is refused while ``paid_services_allowed`` is false, and a
FREE_TIER resource whose free allowance is exhausted is refused too: there
is deliberately no automatic paid fallback anywhere in this module.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from .errors import CostGuardBlocked
from .store import FileLock, read_json, write_json

FREE = "FREE"
FREE_TIER = "FREE_TIER"
PAID = "PAID"

#: GitHub-hosted **standard** macOS runner labels. These - and only these -
#: are free and unlimited on public repositories.
#:
#: This is an allowlist, not a denylist, because the failure mode matters:
#: a label we have never heard of might be a larger runner, and a larger
#: runner is charged even on a public repository. Anything not listed here
#: is refused rather than guessed at.
STANDARD_MACOS_RUNNERS = frozenset({
    "macos-latest", "macos-14", "macos-15", "macos-26",
    "macos-15-intel", "macos-26-intel", "xcode-27",
})

#: Substrings that mark a larger (charged) runner even on a public repo.
#: Only used to give a clearer refusal message - the allowlist above is what
#: actually decides.
LARGER_RUNNER_MARKERS = ("xlarge", "large", "-8core", "-12core", "-16core",
                         "-24core", "-32core", "-64core", "arm64-", "self-hosted")


def check_runner_label(label: str) -> dict:
    """Decide whether a ``runs-on`` label may be used.

    Returns ``{"allowed": bool, "label": str, "reason": str}``.  A label is
    allowed only if it is on :data:`STANDARD_MACOS_RUNNERS` verbatim.
    """
    raw = (label or "").strip()
    normalised = raw.lower()
    if not normalised:
        return {"allowed": False, "label": raw,
                "reason": "Kein runs-on-Label angegeben. Buergys Builds raet nicht, "
                          "welcher Runner gemeint ist."}
    if normalised in STANDARD_MACOS_RUNNERS:
        return {"allowed": True, "label": raw,
                "reason": f"{raw} ist ein GitHub-Standard-Runner - auf oeffentlichen "
                          "Repositories kostenlos."}
    hint = ""
    if any(m in normalised for m in LARGER_RUNNER_MARKERS):
        hint = " Das Label sieht nach einem Larger Runner aus, der auch auf "\
               "oeffentlichen Repositories kostenpflichtig ist."
    return {"allowed": False, "label": raw,
            "reason": f"{raw} steht nicht auf der Liste der erlaubten "
                      f"Standard-Runner ({', '.join(sorted(STANDARD_MACOS_RUNNERS))})."
                      + hint}

#: What each known resource costs.  Adding a resource is a deliberate act;
#: an unknown resource is treated as PAID, never as free.
RESOURCES: dict[str, dict[str, Any]] = {
    "windows_local": {
        "cost": FREE,
        "note": "Sebastians HP. Strom, sonst nichts.",
    },
    "github_actions_macos_public_repo": {
        "cost": FREE_TIER,
        "note": "GitHub-hosted STANDARD macOS runner (macos-latest / macos-15 / "
                "macos-26 / xcode-27) on a PUBLIC repository. GitHub: 'Use of the "
                "standard GitHub-hosted runners is free and unlimited on public "
                "repositories.' Larger runners are charged even on public repos - "
                "never select one. Geprueft 2026-09-20, siehe docs/COST_MODEL.md.",
        "needs_runner_label": True,
        # No documented minute cap for public repos, but we still meter it so
        # that a rule change cannot run up a bill unnoticed.
        "free_minutes_per_month": 2000,
    },
    "github_actions_macos_private_repo": {
        "cost": PAID,
        "note": "macOS minutes on a private repo bill at 10x. Needs Sebastians ok.",
        "needs_runner_label": True,
    },
    "github_pages": {
        "cost": FREE,
        "note": "OTA hosting for public repos.",
    },
    "codemagic": {"cost": PAID, "note": "Die Kosten, die wir loswerden wollen."},
    "xcode_cloud": {"cost": PAID, "note": "Free tier exists but is account bound."},
    "macstadium": {"cost": PAID, "note": "Cloud Mac."},
    "aws_mac": {"cost": PAID, "note": "24h minimum allocation."},
    "azure_mac": {"cost": PAID, "note": "Cloud Mac."},
    "local_mac": {
        "cost": FREE,
        "note": "Ein eigener Mac mini. Noch nicht vorhanden.",
    },
    "paid_artifact_storage": {"cost": PAID, "note": "Nicht noetig, lokal reicht."},
}


class CostGuard:
    """Decides whether a resource may be used, and meters the free tiers.

    The ledger lives on disk so that a restart cannot reset a month's usage
    (brief section 21) and is locked so that two controllers cannot both
    think they are within the allowance.
    """

    def __init__(self, config, paths=None) -> None:
        self.config = config
        self.paths = paths or config.paths()
        self.allowed = bool(config.get("paid_services_allowed", False))

    # -- ledger ---------------------------------------------------------
    @property
    def ledger_path(self):
        return self.paths.root / "cost_ledger.json"

    def _load(self) -> dict:
        return read_json(self.ledger_path, default={}) or {}

    @staticmethod
    def _period(when: _dt.datetime | None = None) -> str:
        return f"{(when or _dt.datetime.now()):%Y-%m}"

    def usage(self, resource: str, when: _dt.datetime | None = None) -> float:
        return float(self._load().get(self._period(when), {}).get(resource, 0.0))

    def record_minutes(self, resource: str, minutes: float,
                       when: _dt.datetime | None = None) -> float:
        """Add metered minutes to the ledger and return the new total."""
        if minutes < 0:
            raise ValueError("minutes must not be negative")
        with FileLock(self.paths.root / ".cost_ledger.lock"):
            data = self._load()
            period = data.setdefault(self._period(when), {})
            period[resource] = round(float(period.get(resource, 0.0)) + float(minutes), 3)
            write_json(self.ledger_path, data)
            return period[resource]

    # -- decisions ------------------------------------------------------
    def classify(self, resource: str) -> dict:
        """An unknown resource is PAID.  Fail closed, always."""
        return RESOURCES.get(resource, {
            "cost": PAID,
            "note": "Unbekannte Ressource - vom Cost Guard als kostenpflichtig behandelt.",
        })

    def decide(self, resource: str, minutes: float = 0.0,
               runner_label: str | None = None) -> dict:
        """Return a decision dict without raising.  Used by the dashboard.

        ``runner_label`` is the executor's ``runs-on`` value.  A GitHub
        executor must pass it: a free public repository still costs money if
        the job lands on a larger runner.
        """
        spec = self.classify(resource)
        cost = spec["cost"]
        if spec.get("needs_runner_label"):
            verdict = check_runner_label(runner_label)
            if not verdict["allowed"]:
                return {"allowed": False, "resource": resource, "cost": PAID,
                        "runner_label": runner_label,
                        "reason": "Runner abgelehnt: " + verdict["reason"]}
        if cost == FREE:
            return {"allowed": True, "resource": resource, "cost": cost,
                    "reason": "kostenlos"}
        if cost == PAID:
            if self.allowed:
                return {"allowed": True, "resource": resource, "cost": cost,
                        "reason": "PAID_SERVICES_ALLOWED=true - von Sebastian freigegeben"}
            return {"allowed": False, "resource": resource, "cost": cost,
                    "reason": f"{resource} ist kostenpflichtig und "
                              "PAID_SERVICES_ALLOWED=false. "
                              f"Hinweis: {spec.get('note', '')}".strip()}
        # FREE_TIER
        cap = float(spec.get("free_minutes_per_month") or 0)
        used = self.usage(resource)
        if cap and used + minutes > cap:
            return {"allowed": False, "resource": resource, "cost": cost,
                    "used_minutes": used, "cap_minutes": cap,
                    "reason": f"Freikontingent fuer {resource} erschoepft "
                              f"({used:.0f}/{cap:.0f} Minuten in diesem Monat). "
                              "Kein automatischer kostenpflichtiger Fallback."}
        return {"allowed": True, "resource": resource, "cost": cost,
                "used_minutes": used, "cap_minutes": cap, "reason": "im Freikontingent"}

    def check(self, resource: str, minutes: float = 0.0,
              runner_label: str | None = None) -> dict:
        """Raise :class:`CostGuardBlocked` unless the resource may be used."""
        decision = self.decide(resource, minutes, runner_label)
        if not decision["allowed"]:
            raise CostGuardBlocked(decision["reason"])
        return decision

    def status(self) -> dict:
        period = self._period()
        return {
            "paid_services_allowed": self.allowed,
            "period": period,
            "metered": self._load().get(period, {}),
            "resources": {k: v["cost"] for k, v in sorted(RESOURCES.items())},
        }
