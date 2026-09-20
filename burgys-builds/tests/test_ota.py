"""OTA: manifest, refusals, install page (brief section 10)."""
import unittest
import zipfile
from pathlib import Path

from helpers import ControllerCase

from bb import ota
from bb.errors import ValidationError
from bb.projects import Project

REPO = Path(__file__).resolve().parents[2]
LIVE_IPA = REPO / "thy-gnosis.ipa"
LIVE_PLIST = REPO / "thy-gnosis.plist"

BASE = "https://sebastianbuergy-oss.github.io/band-apps-install"


class TestManifestPlist(unittest.TestCase):
    @unittest.skipUnless(LIVE_PLIST.exists(), "live plist not in this checkout")
    def test_generated_plist_matches_the_live_one_byte_for_byte(self):
        generated = ota.manifest_plist(
            bundle_id="com.sebastianbuergy.thygnosis", bundle_version="1.0",
            title="Thy Gnosis", ipa_url=f"{BASE}/thy-gnosis.ipa",
            icon_url=f"{BASE}/thy-gnosis-icon.png")
        self.assertEqual(generated.strip(),
                         LIVE_PLIST.read_text(encoding="utf-8").strip())

    def test_plain_http_is_refused(self):
        with self.assertRaises(ValidationError):
            ota.manifest_plist(bundle_id="a.b", bundle_version="1", title="t",
                               ipa_url="http://example.invalid/a.ipa",
                               icon_url=f"{BASE}/i.png")

    def test_xml_special_characters_are_escaped(self):
        plist = ota.manifest_plist(
            bundle_id="a.b", bundle_version="1", title="Rock & Roll <live>",
            ipa_url=f"{BASE}/a.ipa", icon_url=f"{BASE}/i.png")
        self.assertIn("Rock &amp; Roll &lt;live&gt;", plist)
        self.assertNotIn("<live>", plist)

    def test_install_url_uses_itms_services(self):
        url = ota.install_url(BASE, "thy-gnosis.plist")
        self.assertTrue(url.startswith("itms-services://?action=download-manifest&url=https://"))


class TestOtaRefusals(ControllerCase):
    def _project(self) -> Project:
        return self.controller.registry.get("testapp")

    def _manifest(self, **overrides) -> dict:
        base = {"build_id": "BB-20260920-TST-001", "mode": "AD_HOC",
                "dry_run": False, "commit": "abc1234"}
        base.update(overrides)
        return base

    def _ipa_info(self, **overrides) -> dict:
        info = {
            "bundle_id": "com.example.testapp", "has_code_signature": True,
            "version": "1.0", "build_number": "1", "sha256": "0" * 64, "bytes": 10,
            "profile": {"name": "TestApp adhoc", "expired": False,
                        "provisioned_device_count": 2, "get_task_allow": False,
                        "provisions_all_devices": False, "expires": "2099-01-01"},
        }
        info.update(overrides)
        return info

    def test_a_clean_ad_hoc_build_is_publishable(self):
        self.assertEqual(
            ota.check_publishable(self._project(), self._manifest(), self._ipa_info()), [])

    def test_a_dry_run_is_never_published(self):
        problems = ota.check_publishable(
            self._project(), self._manifest(dry_run=True), self._ipa_info())
        self.assertTrue(any("Mock" in p or "Dry-Run" in p for p in problems))

    def test_an_app_store_signed_ipa_is_refused_for_ota(self):
        info = self._ipa_info(profile={"name": "TestApp adhoc", "expired": False,
                                       "provisioned_device_count": 0,
                                       "get_task_allow": False,
                                       "provisions_all_devices": False})
        problems = ota.check_publishable(self._project(), self._manifest(), info)
        self.assertTrue(any("APP_STORE" in p for p in problems))

    def test_an_expired_profile_is_refused(self):
        info = self._ipa_info()
        info["profile"]["expired"] = True
        problems = ota.check_publishable(self._project(), self._manifest(), info)
        self.assertTrue(any("abgelaufen" in p for p in problems))

    def test_a_wrong_bundle_id_is_refused(self):
        problems = ota.check_publishable(
            self._project(), self._manifest(),
            self._ipa_info(bundle_id="com.example.somethingelse"))
        self.assertTrue(any("Bundle ID" in p for p in problems))

    def test_an_unsigned_ipa_is_refused(self):
        problems = ota.check_publishable(
            self._project(), self._manifest(), self._ipa_info(has_code_signature=False))
        self.assertTrue(any("Codesignatur" in p for p in problems))

    def test_a_profile_other_than_the_configured_one_is_refused(self):
        info = self._ipa_info()
        info["profile"]["name"] = "Irgendein anderes Profil"
        problems = ota.check_publishable(self._project(), self._manifest(), info)
        self.assertTrue(any("statt des konfigurierten" in p for p in problems))

    def test_app_store_mode_is_not_an_ota_mode(self):
        problems = ota.check_publishable(
            self._project(), self._manifest(mode="APP_STORE_RELEASE"), self._ipa_info())
        self.assertTrue(any("nicht fuer OTA" in p for p in problems))

    def test_prepare_reports_every_problem_at_once(self):
        with self.assertRaises(ValidationError) as ctx:
            ota.prepare(self._project(), self._manifest(dry_run=True),
                        LIVE_IPA if LIVE_IPA.exists() else __file__,
                        base_url=BASE, out_dir=self.tmp / "ota",
                        ipa_info=self._ipa_info(has_code_signature=False))
        message = str(ctx.exception)
        self.assertIn("Dry-Run", message)
        self.assertIn("Codesignatur", message)


@unittest.skipUnless(LIVE_IPA.exists(), "live IPA not in this checkout")
class TestOtaWithARealIpa(ControllerCase):
    project_overrides = {
        "bundle_id": "com.sebastianbuergy.thygnosis",
        "signing": {"AD_HOC": {"profile_name": "ThyGnosis ios_app_adhoc 20260913",
                               "certificate_common_name": "Apple Distribution: Sebastian Brgy (38A4N26LD5)",
                               "expires": "2027-08-14",
                               "expects_provisioned_devices": True}},
        "ota": {"slug": "thy-gnosis", "title": "Thy Gnosis",
                "plist": "thy-gnosis.plist", "ipa": "thy-gnosis.ipa",
                "icon": "thy-gnosis-icon.png"},
    }

    def test_prepare_produces_manifest_qr_and_checksum(self):
        manifest = {"build_id": "BB-20260920-TST-001", "mode": "AD_HOC",
                    "dry_run": False, "commit": "0123456789abcdef"}
        out = self.tmp / "ota-out"
        release = ota.prepare(self.controller.registry.get("testapp"), manifest,
                              LIVE_IPA, base_url=BASE, out_dir=out)
        self.assertEqual(len(release["ipa_sha256"]), 64)
        self.assertEqual(release["ipa_bytes"], LIVE_IPA.stat().st_size)
        self.assertEqual(release["device_count"], 2)
        self.assertTrue((out / "thy-gnosis.plist").exists())
        self.assertTrue((out / "qr.svg").exists())
        self.assertTrue((out / "qr.png").read_bytes().startswith(b"\x89PNG"))
        self.assertTrue(release["install_url"].startswith("itms-services://"))

    def test_install_page_shows_version_build_commit_and_checksum(self):
        manifest = {"build_id": "BB-20260920-TST-001", "mode": "AD_HOC",
                    "dry_run": False, "commit": "0123456789abcdef"}
        release = ota.prepare(self.controller.registry.get("testapp"), manifest,
                              LIVE_IPA, base_url=BASE, out_dir=self.tmp / "o")
        page = ota.render_install_page([release])
        for needle in ("Thy Gnosis", "Version 1.0", "Build 1", "01234567",
                       release["ipa_sha256"], "itms-services://", "<svg"):
            self.assertIn(needle, page)
        self.assertIn('name="robots" content="noindex', page)


if __name__ == "__main__":
    unittest.main()
