"""Queue, parallelism and restart recovery (brief sections 5, 17 and 21)."""
import unittest

from helpers import ControllerCase

from bb import states as S
from bb.errors import ValidationError


class TestQueue(ControllerCase):
    def setUp(self):
        super().setUp()
        self.queue = self.controller.queue

    def test_priority_then_arrival(self):
        self.queue.enqueue("BB-20260920-TST-001", "testapp", "AD_HOC")
        self.queue.enqueue("BB-20260920-TST-002", "other", "AD_HOC", priority=10)
        self.queue.enqueue("BB-20260920-TST-003", "third", "AD_HOC")
        order = [e["build_id"] for e in self.queue.snapshot()["waiting"]]
        self.assertEqual(order[0], "BB-20260920-TST-002")
        self.assertEqual(order[1:], ["BB-20260920-TST-001", "BB-20260920-TST-003"])

    def test_no_duplicate_entries(self):
        self.queue.enqueue("BB-20260920-TST-001", "testapp", "AD_HOC")
        with self.assertRaises(ValidationError):
            self.queue.enqueue("BB-20260920-TST-001", "testapp", "AD_HOC")

    def test_only_one_job_per_project_at_a_time(self):
        """Claude and Codex must not build the same project twice at once."""
        self.queue.enqueue("BB-20260920-TST-001", "testapp", "AD_HOC")
        self.queue.enqueue("BB-20260920-TST-002", "testapp", "AD_HOC")
        self.queue.enqueue("BB-20260920-TST-003", "otherapp", "AD_HOC")
        first = self.queue.claim("dryrun")
        second = self.queue.claim("dryrun")
        self.assertEqual(first["build_id"], "BB-20260920-TST-001")
        self.assertEqual(second["project"], "otherapp",
                         "a second job for the same project must not be claimed")
        self.assertIsNone(self.queue.claim("dryrun"))

    def test_release_frees_the_project(self):
        self.queue.enqueue("BB-20260920-TST-001", "testapp", "AD_HOC")
        self.queue.enqueue("BB-20260920-TST-002", "testapp", "AD_HOC")
        first = self.queue.claim("dryrun")
        self.queue.release(first["build_id"])
        self.assertEqual(self.queue.claim("dryrun")["build_id"], "BB-20260920-TST-002")

    def test_invalid_build_id_refused(self):
        with self.assertRaises(ValidationError):
            self.queue.enqueue("../../etc/passwd", "testapp", "AD_HOC")


class TestRestartRecovery(ControllerCase):
    def test_a_job_on_the_mac_is_marked_interrupted_not_restarted(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian")
        self.controller.queue.claim("dryrun")
        manifest.set_state(S.WINDOWS_TESTING).set_state(S.READY)
        manifest.set_state(S.QUEUED).set_state(S.WAITING_MAC)
        manifest.set_state(S.MAC_BUILDING, note="Strom weg")
        manifest.save(self.controller.paths)

        fresh = self.rebuild_controller()
        report = fresh.queue.recover(fresh.audit)

        self.assertIn(manifest.build_id, report["interrupted"])
        self.assertEqual([], report["requeued"], "a macOS job must not restart itself")
        after = fresh.get(manifest.build_id)
        self.assertEqual(after.status, S.FAILED)
        self.assertEqual(after.get("failure_reason"), "INTERRUPTED_BY_RESTART")
        self.assertEqual(fresh.queue.snapshot()["length"], 0)

    def test_a_job_that_had_not_reached_the_mac_is_requeued(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian")
        self.controller.queue.claim("dryrun")
        manifest.set_state(S.WINDOWS_TESTING, note="lokal, kein Mac beteiligt")
        manifest.save(self.controller.paths)

        fresh = self.rebuild_controller()
        report = fresh.queue.recover(fresh.audit)
        self.assertIn(manifest.build_id, report["requeued"])
        self.assertEqual(fresh.queue.snapshot()["length"], 1)

    def test_finished_builds_are_cleared_from_the_queue(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian", dry_run=True)
        self.controller.run_next(poll_interval=0)
        self.controller.queue.enqueue(manifest.build_id, "testapp", "AD_HOC")
        fresh = self.rebuild_controller()
        report = fresh.queue.recover(fresh.audit)
        self.assertIn(manifest.build_id, report["cleared"])

    def test_logs_and_manifests_survive_a_restart(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian", dry_run=True)
        self.controller.run_next(poll_interval=0)
        fresh = self.rebuild_controller()
        self.assertEqual(fresh.get(manifest.build_id).status, S.SUCCESS)
        self.assertTrue(fresh.logs(manifest.build_id))


if __name__ == "__main__":
    unittest.main()
