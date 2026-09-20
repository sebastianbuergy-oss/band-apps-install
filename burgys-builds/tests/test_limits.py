"""Build limit and duplicate detection (brief section 5)."""
import datetime as _dt
import unittest

from helpers import ControllerCase

from bb import states as S
from bb.errors import BuildLimitReached


class TestBuildLimit(ControllerCase):
    def _fake_build(self, n: int, *, status=S.SUCCESS, dry_run=False, age_hours=0,
                    commit="abc1234", mode="AD_HOC"):
        """Write a manifest straight to disk - we are testing the counter."""
        from bb.manifest import BuildManifest
        from bb.store import write_json

        build_id = f"BB-{_dt.date.today():%Y%m%d}-TST-{n:03d}"
        created = _dt.datetime.now() - _dt.timedelta(hours=age_hours)
        data = {
            "build_id": build_id, "project": "testapp", "commit": commit,
            "mode": mode, "status": status, "dry_run": dry_run,
            "created_at": created.isoformat(timespec="seconds"),
            "state_history_states": [S.QUEUED, S.WAITING_MAC, status],
            "build_number": n, "artifact_sha256": None, "artifact_path": None,
        }
        directory = self.controller.paths.build_dir(build_id)
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / "manifest.json", data)
        return build_id

    def test_dry_runs_never_count(self):
        for i in range(1, 31):
            self._fake_build(i, dry_run=True)
        self.assertEqual(self.controller.limiter.status("testapp")["used"], 0)
        self.controller.limiter.check("testapp")  # must not raise

    def test_preflight_alone_never_counts(self):
        for i in range(1, 26):
            self._fake_build(i, status=S.FAILED)
            # A build that failed in preflight never reached WAITING_MAC.
            from bb.store import read_json, write_json
            path = self.controller.paths.builds / f"BB-{_dt.date.today():%Y%m%d}-TST-{i:03d}" / "manifest.json"
            data = read_json(path)
            data["state_history_states"] = [S.DISCOVERED, S.PREFLIGHT, S.FAILED]
            write_json(path, data)
        self.assertEqual(self.controller.limiter.status("testapp")["used"], 0)

    def test_twenty_real_builds_exhaust_the_day(self):
        for i in range(1, 21):
            self._fake_build(i)
        status = self.controller.limiter.status("testapp")
        self.assertEqual((status["used"], status["remaining"]), (20, 0))
        with self.assertRaises(BuildLimitReached):
            self.controller.limiter.check("testapp")

    def test_builds_older_than_the_window_do_not_count(self):
        for i in range(1, 21):
            self._fake_build(i, age_hours=25)
        self.assertEqual(self.controller.limiter.status("testapp")["used"], 0)

    def test_limit_blocks_a_request_and_is_audited(self):
        for i in range(1, 21):
            self._fake_build(i)
        with self.assertRaises(BuildLimitReached):
            self.controller.request_build("testapp", "AD_HOC", requested_by="agent")
        self.assertTrue([e for e in self.controller.audit.read(20)
                         if e["action"] == "limit.blocked"])

    def test_a_dry_run_is_still_allowed_at_the_limit(self):
        for i in range(1, 21):
            self._fake_build(i)
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="agent", dry_run=True)
        self.assertNotIn(manifest.status, (S.BLOCKED, S.BLOCKED_BY_COST_GUARD))


class TestDuplicateDetection(ControllerCase):
    def test_no_reuse_without_a_real_artifact_on_disk(self):
        from bb.manifest import BuildManifest
        from bb.store import write_json

        build_id = f"BB-{_dt.date.today():%Y%m%d}-TST-001"
        directory = self.controller.paths.build_dir(build_id)
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / "manifest.json", {
            "build_id": build_id, "project": "testapp", "commit": "deadbeef",
            "mode": "AD_HOC", "status": S.SUCCESS, "dry_run": False,
            "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "artifact_sha256": "0" * 64,
            "artifact_path": str(self.tmp / "gone.ipa"),  # deliberately missing
            "state_history_states": [S.SUCCESS],
        })
        self.assertIsNone(
            self.controller.limiter.find_reusable("testapp", "deadbeef", "AD_HOC"))

    def test_dry_run_results_are_never_reused(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="claude", dry_run=True)
        self.controller.run_next(poll_interval=0)
        commit = manifest.get("commit")
        self.assertIsNone(
            self.controller.limiter.find_reusable("testapp", commit, "AD_HOC"))


if __name__ == "__main__":
    unittest.main()
