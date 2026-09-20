"""The controller: everything a build goes through, in one place.

Order matters and is the order of the brief's priorities - the cheap,
local, reversible checks run first and the macOS executor is asked last and
only once nothing else can fail.
"""
from __future__ import annotations

import datetime as _dt
import time
from pathlib import Path
from typing import Any

from . import audit as A
from . import preflight as P
from . import states as S
from .buildlog import BuildLog
from .costguard import CostGuard
from .errors import (BurgysError, CostGuardBlocked, ExecutorUnavailable,
                     ValidationError)
from .executors import MacJob, get_executor
from .ids import make_build_id, validate_commit
from .limits import BuildLimiter
from .manifest import BuildManifest, BuildNumbers
from .ota import prepare as ota_prepare
from .projects import MODE_APP_STORE, Registry
from .queue import BuildQueue
from .store import require_disk
from .verify import verify_artifact


class BuildController:
    def __init__(self, config, registry: Registry | None = None) -> None:
        self.config = config
        self.paths = config.paths().ensure()
        self.registry = registry if registry is not None else Registry.load()
        self.queue = BuildQueue(self.paths)
        self.audit = A.AuditLog(self.paths)
        self.cost_guard = CostGuard(config, self.paths)
        self.limiter = BuildLimiter(config, self.paths)
        self.numbers = BuildNumbers(self.paths)

    # -- logging --------------------------------------------------------
    def log(self, build_id: str, text: str, level: str = "INFO") -> None:
        BuildLog(self.paths, build_id).append(text, level)

    def logs(self, build_id: str, tail: int = 500) -> list:
        return BuildLog(self.paths, build_id).read(tail)

    def _state(self, manifest, state: str, note: str = "", **fields) -> None:
        """Change state, persist and log in one move, so the three never drift."""
        manifest.set_state(state, note=note, **fields)
        manifest.save(self.paths)
        self.log(manifest.build_id, f"{state}{(' - ' + note) if note else ''}")

    # -- lookup ---------------------------------------------------------
    def manifest_path(self, build_id: str) -> Path:
        return self.paths.build_dir(build_id) / "manifest.json"

    def get(self, build_id: str) -> BuildManifest:
        manifest = BuildManifest.load(self.manifest_path(build_id))
        if manifest is None:
            raise ValidationError(f"unbekannter Build {build_id}")
        return manifest

    def list_builds(self, project: str | None = None, limit: int = 50) -> list:
        out = []
        if self.paths.builds.exists():
            for directory in sorted(self.paths.builds.iterdir(), reverse=True):
                manifest = BuildManifest.load(directory / "manifest.json")
                if manifest is None:
                    continue
                if project and manifest.get("project") != project:
                    continue
                out.append(manifest)
                if len(out) >= limit:
                    break
        return out

    def executor_for(self, project) -> Any:
        name = (project.raw.get("executor")
                or self.config.get("default_executor") or "none")
        exec_config = dict(project.raw.get("executor_config") or {})
        return get_executor(name, exec_config)

    # -- preflight ------------------------------------------------------
    def preflight(self, project_id: str, mode: str, *, commit: str | None = None,
                  actor: str = "system") -> P.PreflightReport:
        """Free, local, and never counted as a build."""
        project = self.registry.get(project_id)
        report = P.run(project, mode, commit=commit, config=self.config)
        self.audit.record(A.PREFLIGHT_RUN, actor=actor, project=project_id,
                          result="ok" if report.ok else "fail",
                          detail=report.to_dict()["summary"])
        return report

    # -- request --------------------------------------------------------
    def request_build(self, project_id: str, mode: str, *, requested_by: str,
                      commit: str | None = None, dry_run: bool = False,
                      approved_by: str | None = None,
                      allow_reuse: bool | None = None) -> BuildManifest:
        project = self.registry.get(project_id)
        executor = self.executor_for(project)
        self.audit.record(A.BUILD_REQUESTED, actor=requested_by, project=project_id,
                          commit=commit, executor=executor.name,
                          detail={"mode": mode, "dry_run": dry_run})

        if not project.supports(mode):
            raise ValidationError(
                f"{project_id} ist nicht fuer {mode} konfiguriert "
                f"(erlaubt: {', '.join(project.modes)})")
        require_disk(self.paths.root, int(self.config.get("min_free_bytes")))

        # 1. Cost guard, before anything is allocated.  A dry run touches no
        #    paid resource, so it is checked against the local machine.
        resource = "windows_local" if dry_run else executor.cost_resource
        try:
            self.cost_guard.check(resource)
        except CostGuardBlocked as exc:
            self.audit.record(A.COST_GUARD_BLOCKED, actor=requested_by,
                              project=project_id, executor=executor.name,
                              result="blocked", detail=str(exc))
            raise

        # 2. Build limit (a dry run is not a build).
        if not dry_run:
            try:
                self.limiter.check(project_id)
            except BurgysError as exc:
                self.audit.record(A.LIMIT_BLOCKED, actor=requested_by,
                                  project=project_id, result="blocked",
                                  detail=str(exc))
                raise

        # 3. Preflight on Windows, so the Mac is never asked about a problem we
        #    could have seen for free.
        report = P.run(project, mode, commit=commit, config=self.config)
        resolved_commit = report.value("git.commit", "commit") or commit
        branch = report.value("git.commit", "branch") or project.branch
        if resolved_commit:
            validate_commit(resolved_commit)

        # 4. Duplicate detection.
        reuse = None
        if (allow_reuse if allow_reuse is not None
                else self.config.get("reuse_artifact_for_identical_commit")):
            if resolved_commit and not dry_run:
                reuse = self.limiter.find_reusable(project_id, resolved_commit, mode)

        today = _dt.date.today()
        build_id = make_build_id(
            project.code, self.numbers.sequence_for_day(project.code, today), today)
        floor = int(project.raw.get("build_number_floor") or 0)
        if mode == MODE_APP_STORE and not floor:
            raise ValidationError(
                f"{project_id}: build_number_floor fehlt. Codemagic hat fuer "
                "dieses Projekt schon Buildnummern an App Store Connect "
                "geschickt; ohne die zuletzt verwendete Nummer wuerde Buergys "
                "Builds eine kleinere vergeben und der Upload wuerde "
                "abgelehnt. Siehe docs/SIGNING.md.")
        build_number = (int(reuse["build_number"]) if reuse
                        else self.numbers.allocate(project_id, floor))

        manifest = BuildManifest.create(
            build_id=build_id, project=project, commit=resolved_commit or "",
            branch=branch, mode=mode, build_number=build_number,
            requested_by=requested_by, executor=executor.name, dry_run=dry_run)
        manifest.update(preflight=report.to_dict())
        manifest.set_state(S.PREFLIGHT, note="Windows-Preflight laeuft")
        manifest.save(self.paths)

        if not report.ok:
            manifest.set_state(
                S.FAILED, note="Preflight fehlgeschlagen",
                failure_reason="; ".join(r.message for r in report.failures)[:500])
            manifest.save(self.paths)
            self.audit.record(A.BUILD_FINISHED, actor=requested_by, project=project_id,
                              build_id=build_id, commit=resolved_commit,
                              result="preflight_failed")
            return manifest

        if reuse:
            # Reuse is only honest if the artifact still verifies *now*: the
            # old manifest's hash is a claim, the file on disk is the fact.
            manifest.update(reused_from=reuse["build_id"])
            self._state(manifest, S.READY, "identischer Commit bereits gebaut")
            self._state(manifest, S.QUEUED, f"Artefakt aus {reuse['build_id']}")
            self._state(manifest, S.VERIFYING, "vorhandenes Artefakt wird geprueft")
            check = verify_artifact(project, manifest, reuse["artifact_path"])
            if not check["ok"]:
                return self._fail(
                    manifest,
                    BurgysError("Wiederverwendung abgelehnt: "
                                + "; ".join(check["problems"])),
                    note="Artefakt haelt der Pruefung nicht stand")
            info = check["ipa"]
            manifest.update(artifact_path=reuse["artifact_path"],
                            artifact_sha256=info["sha256"],
                            artifact_bytes=info["bytes"])
            self._state(manifest, S.SUCCESS, "kein macOS-Job noetig")
            self.audit.record(A.BUILD_FINISHED, actor=requested_by, project=project_id,
                              build_id=build_id, commit=resolved_commit,
                              result="reused", detail={"from": reuse["build_id"],
                                                       "sha256": info["sha256"]})
            return manifest

        manifest.set_state(S.READY, note="Preflight bestanden")

        needs_approval = (
            approved_by is None
            and (self.config.get("require_approval_for_mac_builds")
                 or mode == MODE_APP_STORE)
            and not dry_run
        )
        if needs_approval:
            manifest.set_state(
                S.WAITING_APPROVAL,
                note="Erster macOS-Job braucht Sebastians Freigabe (Brief, Abschnitt 29)")
            manifest.save(self.paths)
            return manifest

        if approved_by:
            manifest.update(approval={"by": approved_by,
                                      "at": _dt.datetime.now().isoformat(timespec="seconds")})
            self.audit.record(A.APPROVAL_GRANTED, actor=approved_by, project=project_id,
                              build_id=build_id)
        manifest.set_state(S.QUEUED)
        manifest.save(self.paths)
        self.queue.enqueue(build_id, project_id, mode)
        return manifest

    # -- approval and cancellation --------------------------------------
    def approve(self, build_id: str, approved_by: str) -> BuildManifest:
        manifest = self.get(build_id)
        if manifest.status != S.WAITING_APPROVAL:
            raise ValidationError(
                f"{build_id} wartet nicht auf Freigabe (Status {manifest.status})")
        manifest.update(approval={"by": approved_by,
                                  "at": _dt.datetime.now().isoformat(timespec="seconds")})
        manifest.set_state(S.QUEUED, note=f"freigegeben von {approved_by}")
        manifest.save(self.paths)
        self.audit.record(A.APPROVAL_GRANTED, actor=approved_by,
                          project=manifest.get("project"), build_id=build_id)
        self.queue.enqueue(build_id, manifest.get("project"), manifest.get("mode"))
        return manifest

    def cancel(self, build_id: str, actor: str = "sebastian") -> BuildManifest:
        manifest = self.get(build_id)
        if S.is_terminal(manifest.status):
            raise ValidationError(
                f"{build_id} ist bereits {manifest.status} und laesst sich nicht abbrechen")
        project = self.registry.get(manifest.get("project"))
        if manifest.status in S.ON_MAC:
            try:
                self.executor_for(project).cancel(f"{manifest.get('executor')}:{build_id}")
            except Exception:
                pass  # the local state is what matters; the Mac times out
        self.queue.release(build_id)
        manifest.set_state(S.CANCELLED, note=f"abgebrochen von {actor}")
        manifest.save(self.paths)
        self.audit.record(A.BUILD_CANCELLED, actor=actor, project=manifest.get("project"),
                          build_id=build_id)
        return manifest

    # -- execution ------------------------------------------------------
    def run_next(self, *, poll_interval: float = 5.0, max_wait_minutes: float | None = None) -> BuildManifest | None:
        """Claim one queued build and drive it to a terminal state."""
        entry = self.queue.claim(self.config.get("default_executor") or "none")
        if entry is None:
            return None
        build_id = entry["build_id"]
        manifest = self.get(build_id)
        project = self.registry.get(manifest.get("project"))
        executor = self.executor_for(project)
        started = time.time()
        try:
            return self._run(manifest, project, executor, poll_interval,
                             max_wait_minutes, started)
        finally:
            self.queue.release(build_id)

    def _fail(self, manifest: BuildManifest, exc: BaseException,
              note: str = "") -> BuildManifest:
        state = getattr(exc, "state", S.FAILED)
        if not S.can_transition(manifest.status, state):
            state = S.FAILED if S.can_transition(manifest.status, S.FAILED) else manifest.status
        if manifest.status != state:
            manifest.set_state(state, note=note or type(exc).__name__,
                               failure_reason=str(exc)[:1000])
        manifest.save(self.paths)
        self.log(manifest.build_id, f"{state}: {exc}", level="ERROR")
        self.audit.record(A.BUILD_FINISHED, project=manifest.get("project"),
                          build_id=manifest.build_id, result=state,
                          executor=manifest.get("executor"), detail=str(exc)[:500])
        return manifest

    def _run(self, manifest, project, executor, poll_interval, max_wait_minutes,
             started) -> BuildManifest:
        build_id = manifest.build_id
        self.audit.record(A.BUILD_STARTED, actor=manifest.get("requested_by"),
                          project=project.id, build_id=build_id,
                          commit=manifest.get("commit"), executor=executor.name)
        try:
            self._state(manifest, S.WINDOWS_TESTING, "lokale Tests")
            report = P.run(project, manifest.get("mode"), commit=manifest.get("commit"),
                           config=self.config)
            manifest.update(preflight=report.to_dict(),
                            windows_seconds=round(time.time() - started, 1))
            if not report.ok:
                raise BurgysError("; ".join(r.message for r in report.failures)[:500])
            self._state(manifest, S.READY, "lokale Tests bestanden")
            self._state(manifest, S.QUEUED)

            # The cost guard runs again here: minutes are about to be spent.
            resource = ("windows_local" if manifest.is_dry_run
                        else executor.cost_resource)
            self.cost_guard.check(resource)

            self._state(manifest, S.WAITING_MAC, f"Executor {executor.name}")

            job = MacJob(
                build_id=build_id, project_id=project.id,
                repository=project.repository, branch=manifest.get("branch"),
                commit=manifest.get("commit"), mode=manifest.get("mode"),
                scheme=project.scheme, xcodeproj=project.xcodeproj,
                bundle_id=project.bundle_id,
                build_number=int(manifest.get("build_number")),
                marketing_version=manifest.get("version"),
                profile_name=(project.signing.get(manifest.get("mode")) or {}).get("profile_name", ""),
                team_id=project.team_id, dry_run=manifest.is_dry_run,
            )
            handle = executor.submit(job)
            self.audit.record(A.SIGNING_USED, project=project.id, build_id=build_id,
                              executor=executor.name,
                              detail={"profile_name": job.profile_name,
                                      "mode": job.mode})
            self._state(manifest, S.MAC_BUILDING, f"Handle {handle}")

            result = self._await(executor, handle, manifest, poll_interval,
                                 max_wait_minutes)
            manifest.update(mac_minutes=round(result.minutes, 2))
            if not manifest.is_dry_run and result.minutes:
                self.cost_guard.record_minutes(executor.cost_resource, result.minutes)

            if result.state == S.CANCELLED:
                raise BurgysError("Executor meldet: abgebrochen")
            if result.state != "SUCCESS":
                raise BurgysError(result.detail or f"Executor meldet {result.state}")

            self._state(manifest, S.SIGNING, "Signing auf dem Executor abgeschlossen")
            self._state(manifest, S.EXPORTING, "Export")

            if result.simulated or not executor.produces_real_ipa:
                # There is no IPA and there must be no pretence that there is.
                self._state(manifest, S.VERIFYING, "nichts zu pruefen - Dry Run")
                self._state(
                    manifest, S.SUCCESS,
                    "DRY RUN: Pipeline durchlaufen, kein Xcode, keine IPA")
                self.audit.record(A.BUILD_FINISHED, project=project.id,
                                  build_id=build_id, result="dry_run_success",
                                  executor=executor.name)
                return manifest

            artifact_dir = self.paths.artifact_dir(build_id)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact = (result.artifact_path
                        or executor.fetch_artifact(handle, artifact_dir))
            if not artifact or not Path(artifact).exists():
                raise BurgysError("Executor meldet Erfolg, liefert aber keine IPA")

            self._state(manifest, S.VERIFYING, "IPA wird auf Windows geprueft")
            check = verify_artifact(project, manifest, artifact)
            if not check["ok"]:
                raise BurgysError("IPA-Pruefung: " + "; ".join(check["problems"]))
            info = check["ipa"]
            manifest.update(artifact_path=str(artifact),
                            artifact_sha256=info["sha256"],
                            artifact_bytes=info["bytes"])
            self.audit.record(A.ARTIFACT_CREATED, project=project.id,
                              build_id=build_id, executor=executor.name,
                              detail={"sha256": info["sha256"], "bytes": info["bytes"]})

            if manifest.get("mode") == "AD_HOC":
                release = ota_prepare(
                    project, manifest, artifact,
                    base_url=self.config["ota_base_url"],
                    out_dir=self.paths.ota / build_id, ipa_info=info)
                manifest.update(ota=release.to_dict())
                self.audit.record(A.OTA_PUBLISHED, project=project.id,
                                  build_id=build_id,
                                  detail={"install_url": release["install_url"]})

            self._state(manifest, S.SUCCESS, "fertig")
            self.audit.record(A.BUILD_FINISHED, project=project.id, build_id=build_id,
                              result="success", executor=executor.name)
            return manifest
        except BaseException as exc:
            return self._fail(manifest, exc)

    def _await(self, executor, handle, manifest, poll_interval, max_wait_minutes):
        limit = float(max_wait_minutes if max_wait_minutes is not None
                      else self.config.get("mac_job_timeout_minutes", 30))
        deadline = time.time() + limit * 60
        while True:
            result = executor.poll(handle)
            if result.state not in (S.MAC_BUILDING, S.WAITING_MAC, S.SIGNING,
                                    S.EXPORTING):
                return result
            if time.time() > deadline:
                executor.cancel(handle)
                raise ExecutorUnavailable(
                    f"macOS-Job ueberschreitet {limit:.0f} Minuten - abgebrochen, "
                    "damit keine Minuten weiterlaufen")
            time.sleep(poll_interval)
