"""Retention: data/ must stop growing, without deleting anything live."""
import datetime as _dt
import unittest
from pathlib import Path

from helpers import ControllerCase

from bb import retention
from bb import states as S
from bb.store import write_json


class RetentionCase(ControllerCase):
    def _build(self, n, *, project="testapp", age_days=0, status=S.SUCCESS,
               artifact=True, ota=False, size=2048):
        build_id = f"BB-{_dt.date.today():%Y%m%d}-TST-{n:03d}"
        created = _dt.datetime.now() - _dt.timedelta(days=age_days)
        paths = self.controller.paths
        directory = paths.build_dir(build_id)
        directory.mkdir(parents=True, exist_ok=True)
        data = {
            "build_id": build_id, "project": project, "status": status,
            "created_at": created.isoformat(timespec="seconds"),
            "mode": "AD_HOC", "dry_run": False,
            "artifact_sha256": ("a" * 64) if artifact else None,
            "state_history_states": [status],
        }
        if ota:
            data["ota"] = {"install_url": "itms-services://x", "ipa_sha256": "a" * 64}
        write_json(directory / "manifest.json", data)
        if artifact:
            art = paths.artifacts / build_id
            art.mkdir(parents=True, exist_ok=True)
            (art / "app.ipa").write_bytes(b"x" * size)
        log = paths.log_file(build_id)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("zeile\n" * 50, encoding="utf-8")
        return build_id


class TestRetentionPlan(RetentionCase):
    config_overrides = {"retention_days_builds": 30, "retention_days_logs": 30,
                        "retention_keep_artifacts_per_project": 3}

    def test_nothing_to_do_on_an_empty_store(self):
        self.assertTrue(retention.plan(self.config, self.controller.paths).empty)

    def test_the_newest_artifacts_are_kept_regardless_of_age(self):
        ids = [self._build(i, age_days=200) for i in range(1, 7)]
        result = retention.plan(self.config, self.controller.paths)
        # Newest three by created_at are the last three created.
        kept = [b for b in ids if b not in result.remove_artifacts]
        self.assertEqual(len(kept), 3, result.to_dict())

    def test_old_builds_are_pruned(self):
        old = self._build(1, age_days=100, artifact=False)
        fresh = self._build(2, age_days=1, artifact=False)
        result = retention.plan(self.config, self.controller.paths)
        self.assertIn(old, result.remove_builds)
        self.assertNotIn(fresh, result.remove_builds)

    def test_a_running_build_is_never_touched(self):
        live = self._build(1, age_days=500, status=S.MAC_BUILDING)
        result = retention.plan(self.config, self.controller.paths)
        self.assertNotIn(live, result.remove_builds)
        self.assertNotIn(live, result.remove_artifacts)
        self.assertEqual(result.kept_reasons[live], "laeuft noch")

    def test_a_published_ota_release_is_never_pruned(self):
        """Its install page points at this artifact by URL and checksum."""
        published = self._build(1, age_days=999, ota=True)
        for i in range(2, 8):
            self._build(i, age_days=1)
        result = retention.plan(self.config, self.controller.paths)
        self.assertNotIn(published, result.remove_artifacts)
        self.assertNotIn(published, result.remove_builds)
        self.assertEqual(result.kept_reasons[published], "OTA veroeffentlicht")

    def test_the_keep_count_is_per_project(self):
        a = [self._build(i, project="testapp", age_days=50) for i in range(1, 5)]
        result = retention.plan(self.config, self.controller.paths)
        self.assertEqual(len(result.remove_artifacts), 1, result.to_dict())

    def test_freed_bytes_are_reported(self):
        for i in range(1, 6):
            self._build(i, age_days=50, size=4096)
        result = retention.plan(self.config, self.controller.paths)
        self.assertGreater(result.freed_bytes, 0)


class TestRetentionApply(RetentionCase):
    config_overrides = {"retention_days_builds": 30, "retention_days_logs": 30,
                        "retention_keep_artifacts_per_project": 1}

    def test_a_dry_run_deletes_nothing(self):
        build_id = self._build(1, age_days=200)
        self._build(2, age_days=1)
        result = retention.apply(self.config, self.controller.paths, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertTrue((self.controller.paths.artifacts / build_id).exists())
        self.assertTrue(self.controller.paths.build_dir(build_id).exists())

    def test_applying_removes_exactly_what_was_planned(self):
        old = self._build(1, age_days=200)
        fresh = self._build(2, age_days=1)
        result = retention.apply(self.config, self.controller.paths, dry_run=False,
                                 audit=self.controller.audit)
        self.assertFalse(result["dry_run"])
        self.assertFalse((self.controller.paths.artifacts / old).exists())
        self.assertFalse(self.controller.paths.build_dir(old).exists())
        self.assertFalse(self.controller.paths.log_file(old).exists())
        # The newest build keeps everything.
        self.assertTrue((self.controller.paths.artifacts / fresh).exists())
        self.assertTrue(self.controller.paths.build_dir(fresh).exists())

    def test_pruning_is_recorded_in_the_audit_log(self):
        self._build(1, age_days=200)
        retention.apply(self.config, self.controller.paths, dry_run=False,
                        audit=self.controller.audit)
        self.assertTrue([e for e in self.controller.audit.read(20)
                         if e.get("actor") == "retention"])

    def test_running_it_twice_is_harmless(self):
        self._build(1, age_days=200)
        retention.apply(self.config, self.controller.paths, dry_run=False)
        second = retention.apply(self.config, self.controller.paths, dry_run=False)
        self.assertEqual(second["builds"], [])

    def test_the_queue_still_works_afterwards(self):
        """Pruning must not leave the controller unable to run."""
        self._build(1, age_days=200)
        retention.apply(self.config, self.controller.paths, dry_run=False)
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian", dry_run=True)
        done = self.controller.run_next(poll_interval=0)
        self.assertEqual(done.status, S.SUCCESS)


class TestRetentionInSystemStatus(ControllerCase):
    def test_the_status_page_reports_what_could_be_freed(self):
        from bb.api import system_status

        status = system_status(self.controller)
        self.assertIn("retention", status)
        for key in ("prunable_builds", "prunable_artifacts", "prunable_logs",
                    "freed_mb"):
            self.assertIn(key, status["retention"])


if __name__ == "__main__":
    unittest.main()
