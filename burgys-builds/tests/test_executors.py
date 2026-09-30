"""Executor failures: offline, build error, no artifact, timeout, disk full."""
import unittest

from helpers import ControllerCase

from bb import states as S
from bb.errors import DiskFull, ExecutorUnavailable
from bb.executors import (AVAILABLE, OFFLINE, MacExecutor, MacJob, MacJobResult,
                          get_executor, register)


@register
class _FailingExecutor(MacExecutor):
    name = "test-failing"
    cost_resource = "windows_local"
    produces_real_ipa = True

    def availability(self): return AVAILABLE
    def submit(self, job): return "h"
    def poll(self, handle):
        return MacJobResult(state="FAILED", detail="xcodebuild: Command CompileSwift failed")


@register
class _LyingExecutor(MacExecutor):
    """Reports success but produces nothing - the dangerous failure mode."""
    name = "test-lying"
    cost_resource = "windows_local"
    produces_real_ipa = True

    def availability(self): return AVAILABLE
    def submit(self, job): return "h"
    def poll(self, handle):
        return MacJobResult(state="SUCCESS", detail="alles bestens", artifact_path=None)


@register
class _HangingExecutor(MacExecutor):
    name = "test-hanging"
    cost_resource = "windows_local"
    produces_real_ipa = True

    def availability(self): return AVAILABLE
    def submit(self, job): return "h"
    def poll(self, handle):
        return MacJobResult(state=S.MAC_BUILDING, detail="laeuft und laeuft")


@register
class _PaidExecutor(MacExecutor):
    """Ein echter, kostenpflichtiger Executor (wie Codemagic): submit darf ein Probelauf nie erreichen."""
    name = "test-paid"
    cost_resource = "windows_local"
    produces_real_ipa = True
    submitted: list = []

    def availability(self): return AVAILABLE
    def submit(self, job):
        _PaidExecutor.submitted.append(job.build_id)
        return "h"
    def poll(self, handle):
        return MacJobResult(state="SUCCESS", detail="echter Build", artifact_path=None)


class TestDryRunNeverPays(ControllerCase):
    config_overrides = {"default_executor": "test-paid"}

    def setUp(self):
        super().setUp()
        _PaidExecutor.submitted.clear()

    def test_a_dry_run_never_reaches_a_paid_executor(self):
        self.controller.request_build("testapp", "AD_HOC", requested_by="agent", dry_run=True)
        done = self.controller.run_next(poll_interval=0)
        self.assertEqual(_PaidExecutor.submitted, [], "der Probelauf hat den Executor beauftragt")
        self.assertEqual(done.status, S.SUCCESS)
        self.assertIn("DRY RUN", done.display_status())
        self.assertIn("nicht beauftragt", " ".join(h.get("note", "") for h in done.get("state_history")))
        self.assertEqual(done.get("mac_minutes"), 0.0)
        self.assertIsNone(done.get("artifact_sha256"))

    def test_a_real_build_still_reaches_the_executor(self):
        self.controller.request_build("testapp", "AD_HOC", requested_by="sebastian",
                                      approved_by="sebastian")
        done = self.controller.run_next(poll_interval=0)
        self.assertEqual(_PaidExecutor.submitted, [done.build_id])


class TestCodemagicKennungen(unittest.TestCase):
    def test_a_yaml_workflow_name_is_accepted_and_junk_is_not(self):
        from bb.executors.codemagic import CodemagicExecutor
        from bb.errors import ValidationError
        ok = CodemagicExecutor({"app_id": "6abd043937a2d4978e51a2be", "workflow_id": "ios-testflight", "token_file": "x"})
        ok.kennungen_pruefen()
        for schlecht in ("ios testflight", "ios/testflight", "", "x" * 65):
            with self.assertRaises(ValidationError):
                CodemagicExecutor({"app_id": "6abd043937a2d4978e51a2be", "workflow_id": schlecht, "token_file": "x"}).kennungen_pruefen()
        with self.assertRaises(ValidationError):
            CodemagicExecutor({"app_id": "../etc", "workflow_id": "ios-testflight", "token_file": "x"}).kennungen_pruefen()


    def test_the_build_number_travels_to_codemagic(self):
        from bb.executors.codemagic import CodemagicExecutor
        ex = CodemagicExecutor({"app_id": "6abd043937a2d4978e51a2be", "workflow_id": "ios-testflight", "token_file": "x"})
        job = MacJob(build_id="BB-1", project_id="p", repository="r", branch="main", commit="c", mode="APP_STORE_RELEASE",
                     scheme="Runner", xcodeproj="ios/Runner.xcodeproj", bundle_id="ch.b.x", build_number=7, marketing_version="1.0", profile_name="p")
        koerper = ex.auftrag(job)
        self.assertEqual(koerper["environment"]["variables"]["BURGYS_BUILD_NUMBER"], "7")
        self.assertEqual(koerper["workflowId"], "ios-testflight")
        self.assertEqual(koerper["branch"], "main")


class TestMacOffline(ControllerCase):
    config_overrides = {"default_executor": "none"}

    def test_no_mac_blocks_with_an_explanation(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian")
        done = self.controller.run_next(poll_interval=0)
        self.assertEqual(done.status, S.BLOCKED)
        self.assertIn("Kein macOS-Executor", done.get("failure_reason"))

    def test_the_refusal_is_not_a_success(self):
        self.controller.request_build("testapp", "AD_HOC", requested_by="sebastian")
        done = self.controller.run_next(poll_interval=0)
        self.assertNotEqual(done.status, S.SUCCESS)
        self.assertNotIn("SUCCESS", done.display_status())

    def test_the_executor_reports_offline(self):
        self.assertEqual(get_executor("none").availability(), OFFLINE)


class TestBuildFailures(ControllerCase):
    def _run_with(self, executor_name):
        self.config["default_executor"] = executor_name
        controller = self.rebuild_controller(default_executor=executor_name)
        controller.request_build("testapp", "AD_HOC", requested_by="sebastian")
        return controller, controller.run_next(poll_interval=0)

    def test_compile_failure_is_reported_verbatim(self):
        _, done = self._run_with("test-failing")
        self.assertEqual(done.status, S.FAILED)
        self.assertIn("CompileSwift", done.get("failure_reason"))

    def test_success_without_an_artifact_is_treated_as_a_failure(self):
        """An executor claiming success with no IPA must not become SUCCESS."""
        _, done = self._run_with("test-lying")
        self.assertEqual(done.status, S.FAILED)
        self.assertIn("liefert aber keine IPA", done.get("failure_reason"))

    def test_a_hanging_job_is_cancelled_at_the_timeout(self):
        controller = self.rebuild_controller(default_executor="test-hanging")
        controller.request_build("testapp", "AD_HOC", requested_by="sebastian")
        done = controller.run_next(poll_interval=0, max_wait_minutes=0)
        self.assertIn(done.status, (S.BLOCKED, S.FAILED))
        self.assertIn("Minuten", done.get("failure_reason"))

    def test_a_dry_run_never_claims_to_be_a_real_build(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="claude", dry_run=True)
        done = self.controller.run_next(poll_interval=0)
        self.assertEqual(done.status, S.SUCCESS)
        self.assertIn("DRY RUN", done.display_status())
        self.assertIsNone(done.get("artifact_sha256"))
        self.assertIsNone(done.get("ota"))


class TestApprovalGate(ControllerCase):
    """Brief section 29: a real macOS build waits for Sebastian.

    A mutation run showed this gate could be removed without any test
    noticing, so it gets its own coverage.
    """

    config_overrides = {"require_approval_for_mac_builds": True}

    def test_a_real_build_stops_at_waiting_approval(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="agent")
        self.assertEqual(manifest.status, S.WAITING_APPROVAL)

    def test_an_unapproved_build_never_reaches_the_queue(self):
        self.controller.request_build("testapp", "AD_HOC", requested_by="agent")
        self.assertEqual(self.controller.queue.snapshot()["length"], 0)
        self.assertIsNone(self.controller.run_next(poll_interval=0))

    def test_a_dry_run_does_not_need_approval(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="agent", dry_run=True)
        self.assertEqual(manifest.status, S.QUEUED)

    def test_approval_queues_it_and_is_recorded(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="agent")
        approved = self.controller.approve(manifest.build_id, "sebastian")
        self.assertEqual(approved.status, S.QUEUED)
        self.assertEqual(approved.get("approval")["by"], "sebastian")
        self.assertEqual(self.controller.queue.snapshot()["length"], 1)
        self.assertTrue([e for e in self.controller.audit.read(20)
                         if e["action"] == "approval.granted"])

    def test_approving_something_that_is_not_waiting_is_refused(self):
        from bb.errors import ValidationError

        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="agent", dry_run=True)
        with self.assertRaises(ValidationError):
            self.controller.approve(manifest.build_id, "sebastian")

    def test_app_store_needs_approval_even_when_the_setting_is_off(self):
        controller = self.rebuild_controller(
            require_approval_for_mac_builds=False)
        import json

        from bb.projects import Project, Registry
        data = json.loads(json.dumps(self.project_data))
        data["build_number_floor"] = 50
        data["signing"]["APP_STORE_RELEASE"] = {
            "profile_name": "p", "expires": "2099-01-01",
            "certificate_common_name": "Apple Distribution: Test (TEAM123456)",
            "expects_provisioned_devices": False, "app_store_apple_id": "123"}
        controller.registry = Registry([Project(data)])
        manifest = controller.request_build(
            "testapp", "APP_STORE_RELEASE", requested_by="agent")
        self.assertEqual(manifest.status, S.WAITING_APPROVAL)


class TestPollInterval(ControllerCase):
    def test_a_zero_poll_interval_is_clamped(self):
        """Polling a hosted API in a tight loop is how you get banned.

        A test once passed poll_interval=0 against a stub and turned a
        missed match into thousands of requests a second.
        """
        from bb.builds import BuildController

        self.assertGreater(BuildController.MIN_POLL_INTERVAL, 0)

        seen = []

        @register
        class _Counting(MacExecutor):
            name = "test-counting"
            cost_resource = "windows_local"
            produces_real_ipa = True

            def availability(self): return AVAILABLE
            def submit(self, job): return "h"
            def poll(self, handle):
                import time as _t
                seen.append(_t.monotonic())
                return MacJobResult(state=S.MAC_BUILDING, detail="laeuft")

        controller = self.rebuild_controller(default_executor="test-counting")
        controller.request_build("testapp", "AD_HOC", requested_by="s")
        controller.run_next(poll_interval=0, max_wait_minutes=0.02)
        gaps = [b - a for a, b in zip(seen, seen[1:])]
        self.assertTrue(seen, "the executor was never polled")
        for gap in gaps:
            self.assertGreaterEqual(
                gap, BuildController.MIN_POLL_INTERVAL * 0.8,
                f"polled every {gap:.3f}s despite the clamp")


class TestDiskFull(ControllerCase):
    def test_a_full_disk_blocks_a_request_before_anything_is_allocated(self):
        config = dict(self.config)
        # Demand more free space than any machine has.
        config["min_free_bytes"] = 1 << 62
        controller = self.rebuild_controller(min_free_bytes=1 << 62)
        with self.assertRaises(DiskFull):
            controller.request_build("testapp", "AD_HOC", requested_by="sebastian")
        self.assertEqual(controller.queue.snapshot()["length"], 0)

    def test_disk_status_reports_a_critical_level(self):
        from bb.store import disk_status

        status = disk_status(self.controller.paths.root, min_free=1 << 62,
                             warn_free=1 << 62)
        self.assertEqual(status["level"], "CRITICAL")

    def test_write_failure_surfaces_as_disk_full(self):
        import errno
        from unittest import mock

        from bb.store import write_json

        with mock.patch("os.replace", side_effect=OSError(errno.ENOSPC, "no space")):
            with self.assertRaises(DiskFull):
                write_json(self.tmp / "x.json", {"a": 1})
        self.assertFalse(list(self.tmp.glob("x.json.*")), "temp file must be cleaned up")


if __name__ == "__main__":
    unittest.main()
