"""bb.verify - the gate between "the Mac says it worked" and SUCCESS.

These tests exist because a mutation run showed the module's two most
important checks - bundle id and build number - could be deleted without a
single test failing.
"""
import unittest
import zipfile
from pathlib import Path

from helpers import ControllerCase, make_ipa

from bb import states as S
from bb.verify import verify_artifact

REPO = Path(__file__).resolve().parents[2]
LIVE_IPA = REPO / "thy-gnosis.ipa"


def _manifest(**over):
    base = {"build_id": "BB-20260920-TST-001", "mode": "AD_HOC",
            "build_number": "1", "version": "1.0", "dry_run": False}
    base.update(over)
    return base


@unittest.skipUnless(LIVE_IPA.exists(), "live IPA not in this checkout")
class TestVerifyAgainstARealIpa(ControllerCase):
    """Run the real checks against a real signed artifact."""

    project_overrides = {
        "bundle_id": "com.sebastianbuergy.thygnosis",
        "scheme": "ThyGnosis",
        "team_id": "38A4N26LD5",
        "marketing_version": "1.0",
        "signing": {"AD_HOC": {
            "profile_name": "ThyGnosis ios_app_adhoc 20260913",
            "certificate_common_name": "Apple Distribution: Sebastian Brgy (38A4N26LD5)",
            "expires": "2027-08-14", "expects_provisioned_devices": True}},
    }

    def _project(self):
        return self.controller.registry.get("testapp")

    def test_the_shipped_ipa_verifies_against_its_own_metadata(self):
        result = verify_artifact(self._project(), _manifest(), LIVE_IPA)
        self.assertTrue(result["ok"], result["problems"])

    def test_a_wrong_bundle_id_is_caught(self):
        import json

        from bb.projects import Project

        data = json.loads(json.dumps(self.project_data))
        data["bundle_id"] = "com.example.not.this.app"
        result = verify_artifact(Project(data), _manifest(), LIVE_IPA)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Bundle ID" in p for p in result["problems"]),
                        result["problems"])

    def test_a_build_number_that_was_not_patched_in_is_caught(self):
        """The App Store rejects a repeated build number, so this must fail."""
        result = verify_artifact(self._project(), _manifest(build_number="47"),
                                 LIVE_IPA)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Buildnummer" in p for p in result["problems"]),
                        result["problems"])

    def test_a_wrong_marketing_version_is_caught(self):
        result = verify_artifact(self._project(), _manifest(version="9.9"), LIVE_IPA)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Version" in p for p in result["problems"]))

    def test_an_ad_hoc_ipa_offered_as_an_app_store_build_is_caught(self):
        import json

        from bb.projects import Project

        data = json.loads(json.dumps(self.project_data))
        data["modes"] = ["AD_HOC", "APP_STORE_RELEASE"]
        data["signing"]["APP_STORE_RELEASE"] = {
            "profile_name": "ThyGnosis ios_app_store 20260912",
            "certificate_common_name": "Apple Distribution: Sebastian Brgy (38A4N26LD5)",
            "expects_provisioned_devices": False, "app_store_apple_id": "1"}
        result = verify_artifact(Project(data),
                                 _manifest(mode="APP_STORE_RELEASE"), LIVE_IPA)
        self.assertFalse(result["ok"])
        self.assertTrue(any("APP_STORE" in p for p in result["problems"]),
                        result["problems"])

    def test_a_profile_other_than_the_configured_one_is_caught(self):
        import json

        from bb.projects import Project

        data = json.loads(json.dumps(self.project_data))
        data["signing"]["AD_HOC"]["profile_name"] = "Irgendein anderes Profil"
        result = verify_artifact(Project(data), _manifest(), LIVE_IPA)
        self.assertFalse(result["ok"])
        self.assertTrue(any("statt" in p for p in result["problems"]))

    def test_a_foreign_team_is_caught(self):
        import json

        from bb.projects import Project

        data = json.loads(json.dumps(self.project_data))
        data["team_id"] = "ZZZZZZZZZZ"
        result = verify_artifact(Project(data), _manifest(), LIVE_IPA)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Team" in p for p in result["problems"]))


class TestVerifyOnASyntheticArtifact(ControllerCase):
    """The same checks, on a fixture, so they run on every machine.

    The real-IPA class above is the stronger evidence but only exists where
    the artifact does; these run always, including inside a mutation run.
    """

    def _project(self, **over):
        import json

        from bb.projects import Project
        data = json.loads(json.dumps(self.project_data))
        data.update(over)
        return Project(data)

    def test_a_matching_artifact_verifies(self):
        ipa = make_ipa(self.tmp / "ok.ipa")
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertTrue(result["ok"], result["problems"])

    def test_a_wrong_bundle_id_is_caught(self):
        ipa = make_ipa(self.tmp / "wrongid.ipa", bundle_id="com.example.other")
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Bundle ID" in p for p in result["problems"]),
                        result["problems"])

    def test_a_build_number_that_was_not_patched_in_is_caught(self):
        ipa = make_ipa(self.tmp / "oldnum.ipa", build_number="1")
        result = verify_artifact(self._project(), _manifest(build_number="42"), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Buildnummer" in p for p in result["problems"]),
                        result["problems"])

    def test_a_wrong_version_is_caught(self):
        ipa = make_ipa(self.tmp / "ver.ipa", version="0.9")
        result = verify_artifact(self._project(), _manifest(version="1.0"), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Version" in p for p in result["problems"]))

    def test_an_app_store_signed_ipa_offered_as_ad_hoc_is_caught(self):
        ipa = make_ipa(self.tmp / "store.ipa", devices=0)
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Signierung ist APP_STORE" in p for p in result["problems"]),
                        result["problems"])

    def test_a_development_signed_ipa_is_caught(self):
        ipa = make_ipa(self.tmp / "dev.ipa", get_task_allow=True)
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("DEVELOPMENT" in p for p in result["problems"]),
                        result["problems"])

    def test_an_expired_profile_is_caught(self):
        ipa = make_ipa(self.tmp / "exp.ipa", expires="2020-01-01T00:00:00")
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("abgelaufen" in p for p in result["problems"]))

    def test_a_foreign_profile_name_is_caught(self):
        ipa = make_ipa(self.tmp / "prof.ipa", profile_name="Ein anderes Profil")
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("statt" in p for p in result["problems"]))

    def test_a_foreign_team_is_caught(self):
        ipa = make_ipa(self.tmp / "team.ipa", team="ZZZZZZZZZZ")
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Team" in p for p in result["problems"]))

    def test_an_unsigned_bundle_is_caught(self):
        ipa = make_ipa(self.tmp / "unsigned.ipa", signed=False)
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Codesignatur" in p for p in result["problems"]))

    def test_a_missing_web_folder_is_caught(self):
        ipa = make_ipa(self.tmp / "noweb.ipa", web=False)
        result = verify_artifact(self._project(), _manifest(), ipa)
        self.assertFalse(result["ok"])
        self.assertTrue(any("web/index.html" in p for p in result["problems"]))


class TestVerifyRejectsBrokenArtifacts(ControllerCase):
    def test_a_bundle_without_the_web_folder_is_caught(self):
        """A WKWebView shell without web/index.html launches to nothing."""
        ipa = self.tmp / "empty.ipa"
        with zipfile.ZipFile(ipa, "w") as z:
            import plistlib
            z.writestr("Payload/TestApp.app/Info.plist", plistlib.dumps({
                "CFBundleIdentifier": "com.example.testapp",
                "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1"}))
        result = verify_artifact(self.controller.registry.get("testapp"),
                                 _manifest(), ipa)
        self.assertFalse(result["ok"])
        joined = " | ".join(result["problems"])
        self.assertIn("web/index.html", joined)
        self.assertIn("Codesignatur", joined)
        self.assertIn("embedded.mobileprovision", joined)

    def test_a_file_that_is_not_a_zip_is_rejected(self):
        from bb.errors import ValidationError

        bogus = self.tmp / "not.ipa"
        bogus.write_bytes(b"this is not a zip file")
        with self.assertRaises(ValidationError):
            verify_artifact(self.controller.registry.get("testapp"),
                            _manifest(), bogus)


if __name__ == "__main__":
    unittest.main()
