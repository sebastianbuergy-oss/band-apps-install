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
