"""Preflight, signing preconditions and bad input (brief sections 8 and 9)."""
import json
import unittest

from helpers import ControllerCase, make_checkout

from bb import preflight as P
from bb import states as S
from bb.errors import UnknownProject, ValidationError
from bb.projects import Project, Registry


class TestPreflight(ControllerCase):
    def _project(self, **overrides) -> Project:
        data = json.loads(json.dumps(self.project_data))
        for key, value in overrides.items():
            data[key] = value
        return Project(data)

    def _status(self, report, check):
        return next(r.status for r in report.results if r.name == check)

    def test_clean_checkout_passes(self):
        report = P.run(self._project(), "AD_HOC")
        self.assertTrue(report.ok, [r.message for r in report.failures])

    def test_missing_checkout_fails_and_skips_the_rest(self):
        report = P.run(self._project(local_path=str(self.tmp / "nope")), "AD_HOC")
        self.assertFalse(report.ok)
        self.assertEqual(self._status(report, "project.path"), P.FAIL)
        self.assertEqual(self._status(report, "git.commit"), P.SKIP)

    def test_no_local_path_configured_fails_closed(self):
        report = P.run(self._project(local_path=""), "AD_HOC")
        self.assertFalse(report.ok)
        self.assertIn("Allowlist", report.failures[0].message)

    def test_uncommitted_changes_fail(self):
        (self.checkout / "web" / "index.html").write_text("geaendert", encoding="utf-8")
        report = P.run(self._project(), "AD_HOC")
        self.assertEqual(self._status(report, "git.clean"), P.FAIL)
        self.assertFalse(report.ok)

    def test_bundle_id_mismatch_stops_the_build(self):
        report = P.run(self._project(bundle_id="com.example.something.else"), "AD_HOC")
        self.assertEqual(self._status(report, "config.bundle_id"), P.FAIL)

    def test_missing_required_file_fails(self):
        (self.checkout / "web" / "index.html").unlink()
        report = P.run(self._project(), "AD_HOC")
        self.assertEqual(self._status(report, "files.required"), P.FAIL)

    def test_missing_asset_referenced_by_the_page_fails(self):
        (self.checkout / "web" / "index.html").write_text(
            '<meta name="viewport" content="viewport-fit=cover">'
            '<img src="img/does-not-exist.png">', encoding="utf-8")
        report = P.run(self._project(), "AD_HOC")
        self.assertEqual(self._status(report, "assets.web"), P.FAIL)

    def test_google_fonts_instead_of_bundled_fonts_fails(self):
        (self.checkout / "web" / "index.html").write_text(
            '<meta name="viewport" content="viewport-fit=cover">'
            '<link href="https://fonts.googleapis.com/css2?family=X">', encoding="utf-8")
        report = P.run(self._project(), "AD_HOC")
        self.assertEqual(self._status(report, "assets.web"), P.FAIL)

    def test_broken_feed_json_fails(self):
        (self.checkout / "feed").mkdir()
        (self.checkout / "feed" / "feed.json").write_text("{nope", encoding="utf-8")
        report = P.run(self._project(), "AD_HOC")
        self.assertEqual(self._status(report, "feed.json"), P.FAIL)

    def test_unknown_commit_fails(self):
        report = P.run(self._project(), "AD_HOC", commit="0" * 40)
        self.assertEqual(self._status(report, "git.commit"), P.FAIL)

    def test_malformed_commit_is_rejected_as_input(self):
        with self.assertRaises(ValidationError):
            from bb.ids import validate_commit
            validate_commit("HEAD; rm -rf /")


class TestSigningPreconditions(ControllerCase):
    def _run(self, signing, mode="AD_HOC"):
        data = json.loads(json.dumps(self.project_data))
        data["signing"] = signing
        return P.run(Project(data), mode)

    def _signing_result(self, report):
        return next(r for r in report.results if r.name == "signing.config")

    def test_no_signing_configured_fails(self):
        report = self._run({})
        self.assertEqual(self._signing_result(report).status, P.FAIL)
        self.assertIn("nie improvisiert", self._signing_result(report).message)

    def test_expired_profile_fails(self):
        report = self._run({"AD_HOC": {
            "profile_name": "alt", "expires": "2020-01-01",
            "certificate_common_name": "Apple Distribution: Test (TEAM123456)",
            "expects_provisioned_devices": True}})
        result = self._signing_result(report)
        self.assertEqual(result.status, P.FAIL)
        self.assertIn("abgelaufen", result.message)

    def test_expired_certificate_fails(self):
        report = self._run({"AD_HOC": {
            "profile_name": "p", "expires": "2099-01-01",
            "certificate_expires": "2019-05-05",
            "certificate_common_name": "Apple Distribution: Test (TEAM123456)",
            "expects_provisioned_devices": True}})
        self.assertEqual(self._signing_result(report).status, P.FAIL)

    def test_ad_hoc_without_registered_devices_fails(self):
        report = self._run({"AD_HOC": {
            "profile_name": "p", "expires": "2099-01-01",
            "certificate_common_name": "Apple Distribution: Test (TEAM123456)",
            "expects_provisioned_devices": False}})
        result = self._signing_result(report)
        self.assertEqual(result.status, P.FAIL)
        self.assertIn("registrierte Geraete", result.message)

    def test_certificate_from_another_team_fails(self):
        report = self._run({"AD_HOC": {
            "profile_name": "p", "expires": "2099-01-01",
            "certificate_common_name": "Apple Distribution: Someone Else (XXXXXX)",
            "expects_provisioned_devices": True}})
        self.assertEqual(self._signing_result(report).status, P.FAIL)

    def test_app_store_without_apple_id_fails(self):
        report = self._run({"APP_STORE_RELEASE": {
            "profile_name": "p", "expires": "2099-01-01",
            "certificate_common_name": "Apple Distribution: Test (TEAM123456)",
            "expects_provisioned_devices": False}}, mode="APP_STORE_RELEASE")
        self.assertEqual(self._signing_result(report).status, P.FAIL)


class TestBadRequests(ControllerCase):
    def test_unknown_project(self):
        with self.assertRaises(UnknownProject):
            self.controller.request_build("nicht-da", "AD_HOC", requested_by="agent")

    def test_project_id_shaped_like_a_path_is_refused(self):
        with self.assertRaises(ValidationError):
            self.controller.registry.get("../../etc")

    def test_unsupported_mode(self):
        with self.assertRaises(ValidationError):
            self.controller.request_build("testapp", "DEVELOPMENT", requested_by="agent")

    def test_app_store_without_a_build_number_floor_is_refused(self):
        """Codemagic already handed out numbers; guessing would break uploads."""
        with self.assertRaises(ValidationError) as ctx:
            self.controller.request_build("testapp", "APP_STORE_RELEASE",
                                          requested_by="sebastian")
        self.assertIn("build_number_floor", str(ctx.exception))

    def test_failed_preflight_never_reaches_the_queue(self):
        (self.checkout / "web" / "index.html").unlink()
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian")
        self.assertEqual(manifest.status, S.FAILED)
        self.assertEqual(self.controller.queue.snapshot()["length"], 0)


if __name__ == "__main__":
    unittest.main()
