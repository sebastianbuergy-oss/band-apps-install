"""burgys publish - the last manual step, and the one an agent cannot do by hand."""
import unittest
from pathlib import Path

from helpers import ControllerCase, make_ipa

from bb import ota, publish
from bb import states as S
from bb.errors import ConfigError, ValidationError
from bb.store import read_json


class PublishCase(ControllerCase):
    def setUp(self):
        super().setUp()
        self.target = self.tmp / "pages"
        self.target.mkdir()
        self.config["ota_publish_dir"] = str(self.target)
        self.controller.config["ota_publish_dir"] = str(self.target)

    def _released_build(self, *, build_number="1", version="1.0"):
        """A finished ad-hoc build with a real OTA release next to it."""
        controller = self.controller
        manifest = controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian", dry_run=True)
        # Turn it into a realistic successful ad-hoc build.
        ipa = make_ipa(self.tmp / f"app-{build_number}.ipa",
                       build_number=build_number, version=version)
        manifest.data["dry_run"] = False
        manifest.data["build_number"] = build_number
        manifest.data["version"] = version
        while manifest.status != S.SUCCESS:
            nxt = {S.QUEUED: S.VERIFYING, S.VERIFYING: S.SUCCESS}.get(manifest.status)
            if nxt is None:
                nxt = S.QUEUED
            manifest.set_state(nxt)
        release = ota.prepare(
            controller.registry.get("testapp"), manifest.data, ipa,
            base_url=controller.config["ota_base_url"],
            out_dir=controller.paths.ota / manifest.build_id)
        manifest.update(ota=release.to_dict(),
                        artifact_sha256=release["ipa_sha256"],
                        artifact_path=str(ipa))
        manifest.save(controller.paths)
        return manifest, release


class TestPublishRefusals(PublishCase):
    def test_without_a_configured_directory_it_refuses(self):
        self.controller.config["ota_publish_dir"] = ""
        manifest, _ = self._released_build()
        with self.assertRaises(ConfigError) as ctx:
            publish.plan(self.controller, manifest.build_id)
        self.assertIn("ota_publish_dir", str(ctx.exception))

    def test_a_directory_that_does_not_exist_is_refused(self):
        self.controller.config["ota_publish_dir"] = str(self.tmp / "nirgends")
        manifest, _ = self._released_build()
        with self.assertRaises(ConfigError):
            publish.plan(self.controller, manifest.build_id)

    def test_a_dry_run_build_is_never_published(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="claude", dry_run=True)
        self.controller.run_next(poll_interval=0)
        with self.assertRaises(ValidationError) as ctx:
            publish.plan(self.controller, manifest.build_id)
        self.assertIn("Dry-Run", str(ctx.exception))

    def test_a_build_without_an_ota_release_is_refused(self):
        manifest, _ = self._released_build()
        manifest.update(ota=None)
        manifest.save(self.controller.paths)
        with self.assertRaises(ValidationError) as ctx:
            publish.plan(self.controller, manifest.build_id)
        self.assertIn("kein OTA-Release", str(ctx.exception))

    def test_a_tampered_artifact_is_caught_before_it_reaches_the_page(self):
        """The checksum is re-taken from disk, not trusted from the manifest."""
        manifest, release = self._released_build()
        ipa = self.controller.paths.ota / manifest.build_id / release["ipa_name"]
        ipa.write_bytes(ipa.read_bytes() + b"tampered")
        with self.assertRaises(ValidationError) as ctx:
            publish.plan(self.controller, manifest.build_id)
        self.assertIn("SHA-256", str(ctx.exception))

    def test_a_missing_ota_folder_is_reported(self):
        import shutil

        manifest, _ = self._released_build()
        shutil.rmtree(self.controller.paths.ota / manifest.build_id)
        with self.assertRaises(ValidationError) as ctx:
            publish.plan(self.controller, manifest.build_id)
        self.assertIn("fehlen", str(ctx.exception))

    def test_an_unknown_build_is_refused(self):
        with self.assertRaises(ValidationError):
            publish.plan(self.controller, "BB-20260920-TST-999")


class TestPublishApply(PublishCase):
    def test_a_dry_run_writes_nothing(self):
        manifest, _ = self._released_build()
        result = publish.apply(self.controller, manifest.build_id, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(list(self.target.iterdir()), [])

    def test_applying_copies_the_ipa_the_plist_and_writes_the_page(self):
        manifest, release = self._released_build()
        result = publish.apply(self.controller, manifest.build_id, dry_run=False)
        self.assertFalse(result["dry_run"])
        names = sorted(p.name for p in self.target.iterdir())
        self.assertIn(release["ipa_name"], names)
        self.assertIn(release["plist_name"], names)
        self.assertIn("index.html", names)
        self.assertIn("published.json", names)

    def test_the_published_ipa_is_byte_identical(self):
        manifest, release = self._released_build()
        publish.apply(self.controller, manifest.build_id, dry_run=False)
        source = self.controller.paths.ota / manifest.build_id / release["ipa_name"]
        self.assertEqual((self.target / release["ipa_name"]).read_bytes(),
                         source.read_bytes())

    def test_the_page_shows_version_commit_and_checksum(self):
        manifest, release = self._released_build()
        publish.apply(self.controller, manifest.build_id, dry_run=False)
        page = (self.target / "index.html").read_text(encoding="utf-8")
        self.assertIn(release["ipa_sha256"], page)
        self.assertIn("itms-services://", page)
        self.assertIn(str(release["version"]), page)
        self.assertIn("<svg", page)

    def test_the_ledger_records_what_is_live(self):
        manifest, release = self._released_build()
        publish.apply(self.controller, manifest.build_id, dry_run=False)
        ledger = read_ledger = publish.live(self.controller.config)
        self.assertEqual(ledger["testapp"]["build_id"], manifest.build_id)
        self.assertEqual(ledger["testapp"]["ipa_sha256"], release["ipa_sha256"])

    def test_publishing_is_recorded_in_the_audit_log(self):
        manifest, _ = self._released_build()
        publish.apply(self.controller, manifest.build_id, dry_run=False)
        entries = [e for e in self.controller.audit.read(20)
                   if e["action"] == "ota.published" and e["actor"] == "publish"]
        self.assertTrue(entries)

    def test_a_newer_build_replaces_the_older_one(self):
        first, _ = self._released_build(build_number="1")
        publish.apply(self.controller, first.build_id, dry_run=False)
        second, rel2 = self._released_build(build_number="2")
        result = publish.apply(self.controller, second.build_id, dry_run=False)
        self.assertEqual(result["replaces_build"], first.build_id)
        ledger = publish.live(self.controller.config)
        self.assertEqual(ledger["testapp"]["build_number"], "2")
        self.assertEqual((self.target / rel2["ipa_name"]).read_bytes().__len__(),
                         (self.controller.paths.ota / second.build_id
                          / rel2["ipa_name"]).stat().st_size)

    def test_another_app_on_the_same_page_is_not_dropped(self):
        """Publishing one band's app must not remove the other band's entry."""
        manifest, _ = self._released_build()
        publish.apply(self.controller, manifest.build_id, dry_run=False)
        # Someone else's release, already on the page.
        from bb.store import write_json
        ledger = publish.live(self.controller.config)
        ledger["andere-band"] = {"app": "Andere Band", "slug": "andere-band",
                                 "version": "2.0", "build_number": "7",
                                 "ipa_name": "andere-band.ipa",
                                 "plist_name": "andere-band.plist",
                                 "icon_name": "andere-band-icon.png",
                                 "ipa_sha256": "b" * 64, "ipa_mb": 3.0,
                                 "install_url": "itms-services://?x",
                                 "page_url": "https://example.invalid/",
                                 "build_id": "BB-20260101-AB-001"}
        write_json(self.target / "published.json", ledger)

        second, _ = self._released_build(build_number="2")
        publish.apply(self.controller, second.build_id, dry_run=False)
        page = (self.target / "index.html").read_text(encoding="utf-8")
        self.assertIn("Andere Band", page)
        self.assertIn("Test App", page)
        self.assertIn("andere-band", publish.live(self.controller.config))

    def test_nothing_is_ever_deleted(self):
        manifest, _ = self._released_build()
        stray = self.target / "wichtig.txt"
        stray.write_text("nicht anfassen", encoding="utf-8")
        publish.apply(self.controller, manifest.build_id, dry_run=False)
        self.assertEqual(stray.read_text(encoding="utf-8"), "nicht anfassen")

    def test_a_published_release_is_protected_from_retention(self):
        from bb import retention

        manifest, _ = self._released_build()
        publish.apply(self.controller, manifest.build_id, dry_run=False)
        plan = retention.plan(self.controller.config, self.controller.paths)
        self.assertNotIn(manifest.build_id, plan.remove_artifacts)
        self.assertEqual(plan.kept_reasons.get(manifest.build_id),
                         "OTA veroeffentlicht")


class TestPublishOverApi(PublishCase):
    def test_publishing_needs_the_release_token(self):
        import json
        import threading
        import urllib.error
        import urllib.request

        from bb.api import serve

        manifest, _ = self._released_build()
        server = serve(self.controller, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        tokens = {e["name"]: e["token"] for e in server.tokens.tokens()}

        def call(token, body):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/builds/{manifest.build_id}/publish",
                method="POST", data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {token}"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read().decode())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode())

        self.assertEqual(call(tokens["agent"], {"dry_run": True})[0], 401)
        status, body = call(tokens["release"], {"dry_run": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["dry_run"])
        self.assertEqual(list(self.target.iterdir()), [])

    def test_the_api_defaults_to_a_dry_run(self):
        """An agent that forgets the flag must not publish by accident."""
        import inspect

        from bb import api
        source = inspect.getsource(api._publish)
        self.assertIn('body.get("dry_run", True)', source)


if __name__ == "__main__":
    unittest.main()
