"""Dry-run executor: exercises the pipeline without a Mac.

Everything it produces is flagged ``simulated`` and every manifest it
touches is flagged ``dry_run``, so that no surface can ever present it as a
successful iOS build (brief, section 28).  It deliberately cannot write an
IPA.
"""
from __future__ import annotations

import time

from . import AVAILABLE, MacExecutor, MacJob, MacJobResult, register


@register
class DryRunExecutor(MacExecutor):
    name = "dryrun"
    cost_resource = "windows_local"
    produces_real_ipa = False

    def __init__(self, config=None) -> None:
        super().__init__(config)
        self._jobs: dict[str, dict] = {}

    def availability(self) -> str:
        return AVAILABLE

    def submit(self, job: MacJob) -> str:
        handle = f"dryrun:{job.build_id}"
        self._jobs[handle] = {"job": job, "at": time.time()}
        return handle

    def poll(self, handle: str) -> MacJobResult:
        entry = self._jobs.get(handle)
        if entry is None:
            return MacJobResult(state="FAILED", detail=f"unbekannter Handle {handle}",
                                simulated=True)
        job = entry["job"]
        return MacJobResult(
            state="SUCCESS",
            detail=(
                "DRY RUN - kein Xcode gelaufen, keine IPA erzeugt. "
                f"Geplant war: {job.scheme} {job.marketing_version} "
                f"({job.build_number}) im Modus {job.mode} mit Profil "
                f"{job.profile_name}."
            ),
            artifact_path=None,
            minutes=0.0,
            simulated=True,
        )

    def cancel(self, handle: str) -> bool:
        return self._jobs.pop(handle, None) is not None
