"""Local Mac executor - the future ``Burgys-iOS-Runner``.

When Sebastian buys a Mac mini, this is the only file that has to grow: the
queue, the cost guard, the manifests, the OTA pipeline and the dashboard
above it do not change.  Until a host is configured it reports OFFLINE and
refuses work, exactly like :mod:`bb.executors.none`.

The transport is deliberately plain SSH with a key, no agent on the Mac,
because that is the smallest thing that can work and the easiest to audit.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from pathlib import Path

from ..errors import ExecutorUnavailable
from ..redact import redact_text
from . import AVAILABLE, BUSY, OFFLINE, MacExecutor, MacJob, MacJobResult, register


@register
class LocalMacExecutor(MacExecutor):
    name = "local"
    cost_resource = "local_mac"
    produces_real_ipa = True

    def __init__(self, config=None) -> None:
        super().__init__(config)
        self.host = self.config.get("host") or ""          # e.g. burgys-runner.local
        self.user = self.config.get("user") or ""
        self.identity = self.config.get("identity_file") or ""
        self.remote_root = self.config.get("remote_root") or "~/burgys-builds"
        self.runner_script = self.config.get("runner_script") or "burgys-runner.sh"
        self._jobs: dict[str, dict] = {}

    def configured(self) -> bool:
        return bool(self.host and self.user and shutil.which("ssh"))

    def _ssh(self, *remote_args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if self.identity:
            cmd += ["-i", str(Path(self.identity).expanduser())]
        cmd += [f"{self.user}@{self.host}", *remote_args]
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)

    def availability(self) -> str:
        if not self.configured():
            return OFFLINE
        try:
            res = self._ssh("test", "-d", shlex.quote(self.remote_root), timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return OFFLINE
        if res.returncode != 0:
            return OFFLINE
        busy = self._ssh("test", "-e", shlex.quote(self.remote_root + "/.busy"), timeout=20)
        return BUSY if busy.returncode == 0 else AVAILABLE

    def submit(self, job: MacJob) -> str:
        if not self.configured():
            raise ExecutorUnavailable(
                "LocalMacExecutor: kein Mac konfiguriert (host/user fehlen). "
                "Vorgesehen fuer den spaeteren Burgys-iOS-Runner."
            )
        # Every value is passed as a separate argv entry; nothing is
        # interpolated into a shell string.
        args = [
            f"{self.remote_root}/{self.runner_script}",
            "--build-id", job.build_id,
            "--repo", job.repository,
            "--commit", job.commit,
            "--mode", job.mode,
            "--scheme", job.scheme,
            "--xcodeproj", job.xcodeproj,
            "--bundle-id", job.bundle_id,
            "--build-number", str(job.build_number),
            "--marketing-version", job.marketing_version,
            "--profile", job.profile_name,
        ]
        res = self._ssh("nohup", *[shlex.quote(a) for a in args], ">/dev/null", "2>&1", "&")
        if res.returncode != 0:
            raise ExecutorUnavailable(
                f"Runner liess sich nicht starten: {redact_text(res.stderr)[:300]}"
            )
        handle = f"local:{job.build_id}"
        self._jobs[handle] = {"build_id": job.build_id, "since": time.time()}
        return handle

    def poll(self, handle: str) -> MacJobResult:
        entry = self._jobs.get(handle)
        if entry is None:
            return MacJobResult(state="FAILED", detail=f"unbekannter Handle {handle}")
        minutes = (time.time() - entry["since"]) / 60.0
        status_file = f"{self.remote_root}/state/{entry['build_id']}.status"
        res = self._ssh("cat", shlex.quote(status_file), timeout=30)
        if res.returncode != 0:
            return MacJobResult(state="MAC_BUILDING", detail="Runner meldet noch nichts",
                                minutes=minutes)
        state = res.stdout.strip().splitlines()[0] if res.stdout.strip() else "MAC_BUILDING"
        return MacJobResult(state=state, detail=redact_text(res.stdout)[:500], minutes=minutes)

    def cancel(self, handle: str) -> bool:
        entry = self._jobs.get(handle)
        if entry is None or not self.configured():
            return False
        cancel_file = f"{self.remote_root}/state/{entry['build_id']}.cancel"
        return self._ssh("touch", shlex.quote(cancel_file), timeout=20).returncode == 0
