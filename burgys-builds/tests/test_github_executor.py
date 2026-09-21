"""GitHubMacExecutor against a local stub of the Actions API.

The real API is not reachable from a test, and pointing at it would cost
money and need a token.  The stub speaks the same shapes, which is enough to
exercise the parts that can go wrong: finding the run, following the
download redirect *without* handing the token to another host, and unpacking
an archive that arrived over the network.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from helpers import ControllerCase

from bb.errors import ExecutorUnavailable, ValidationError
from bb.executors import MacJob, get_executor

# Derived, never hard-coded: a literal date here passes on the day it is
# written and starts failing at midnight.  (It did.)
BUILD_ID = f"BB-{_dt.date.today():%Y%m%d}-TST-001"


def make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def ipa_zip(ipa_bytes=b"fake-ipa-payload", *, checksum=None, name=BUILD_ID):
    digest = checksum if checksum is not None else hashlib.sha256(ipa_bytes).hexdigest()
    return make_zip({
        f"{name}.ipa": ipa_bytes,
        f"{name}.sha256": f"{digest}  artifact/{name}.ipa\n",
    })


class _Stub(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    @property
    def state(self):
        return self.server.state

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """Record the dispatched build id and answer about *that* one."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode()) if length else {}
        except (ValueError, json.JSONDecodeError):
            body = {}
        dispatched = (body.get("inputs") or {}).get("build_id")
        if dispatched:
            self.state["build_id"] = dispatched
        self.state["dispatched"] = True
        self._json(204, {})

    def do_GET(self):
        st = self.state
        path = self.path.split("?")[0]
        if path.endswith("/runs"):
            build_id = st.get("build_id") or BUILD_ID
            return self._json(200, {"workflow_runs": [{
                "id": 4242, "status": st["status"], "conclusion": st["conclusion"],
                "name": f"{build_id} ThyGnosis AD_HOC",
                "display_title": f"{build_id} ThyGnosis AD_HOC"}]})
        if path == "/repos/o/r/actions/runs/4242":
            return self._json(200, {"id": 4242, "status": st["status"],
                                    "conclusion": st["conclusion"]})
        if path == "/repos/o/r/actions/runs/4242/artifacts":
            artifacts = [dict(a, name=st.get("build_id") or a["name"])
                         if a.get("name") == BUILD_ID else a
                         for a in st["artifacts"]]
            return self._json(200, {"artifacts": artifacts})
        if path == "/repos/o/r/actions/artifacts/9/zip":
            # Record whether credentials reached the API endpoint (they should)
            st["auth_on_api"] = self.headers.get("Authorization")
            host = self.headers.get("Host")
            self.send_response(302)
            self.send_header("Location", f"http://{host}/blob/9")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/blob/9":
            # ...and whether they reached the blob host (they must NOT).
            st["auth_on_blob"] = self.headers.get("Authorization")
            payload = st["zip"]
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/repos/o/r/actions/artifacts/8/zip":
            self.send_response(302)
            self.send_header("Location", "ftp://elsewhere.invalid/x.zip")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json(404, {"message": "not found"})


class GitHubExecutorCase(ControllerCase):
    def setUp(self):
        super().setUp()
        self.token_file = self.tmp / "gh_token"
        self.token_file.write_text("ghp_teststub_token_value", encoding="utf-8")
        self.server = _Stub(("127.0.0.1", 0), _Handler)
        self.server.state = {
            "status": "completed", "conclusion": "success",
            "artifacts": [{"id": 9, "name": BUILD_ID, "expired": False,
                           "size_in_bytes": 100}],
            "zip": ipa_zip(), "auth_on_api": None, "auth_on_blob": None,
            "dispatched": False,
        }
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def executor(self, **over):
        cfg = {"repo": "o/r", "visibility": "public", "runs_on": "macos-latest",
               "token_file": str(self.token_file), "api_base": self.base}
        cfg.update(over)
        return get_executor("github", cfg)

    def job(self):
        return MacJob(build_id=BUILD_ID, project_id="testapp",
                      repository="https://example.invalid/r", branch="main",
                      commit="a" * 40, mode="AD_HOC", scheme="TestApp",
                      xcodeproj="TestApp.xcodeproj", bundle_id="com.example.testapp",
                      build_number=1, marketing_version="1.0",
                      profile_name="TestApp adhoc")


class TestDispatchAndPoll(GitHubExecutorCase):
    def test_configured_only_with_repo_and_token(self):
        self.assertTrue(self.executor().configured())
        self.assertFalse(self.executor(token_file="").configured())
        self.assertFalse(self.executor(repo="").configured())

    def test_submit_dispatches_and_poll_reports_success(self):
        ex = self.executor()
        handle = ex.submit(self.job())
        self.assertTrue(self.server.state["dispatched"])
        self.assertEqual(ex.poll(handle).state, "SUCCESS")

    def test_a_running_job_reports_mac_building(self):
        self.server.state.update(status="in_progress", conclusion=None)
        ex = self.executor()
        self.assertEqual(ex.poll(ex.submit(self.job())).state, "MAC_BUILDING")

    def test_a_failed_run_is_reported_as_failed(self):
        self.server.state.update(status="completed", conclusion="failure")
        ex = self.executor()
        result = ex.poll(ex.submit(self.job()))
        self.assertEqual(result.state, "FAILED")

    def test_availability_reflects_running_jobs(self):
        self.server.state.update(status="in_progress", conclusion=None)
        self.assertEqual(self.executor().availability(), "BUSY")
        self.server.state.update(status="completed", conclusion="success")
        self.assertEqual(self.executor().availability(), "AVAILABLE")

    def test_an_unreachable_api_is_offline_not_a_crash(self):
        self.assertEqual(
            self.executor(api_base="http://127.0.0.1:1").availability(), "OFFLINE")


class TestFetchArtifact(GitHubExecutorCase):
    def _fetch(self, **over):
        ex = self.executor(**over)
        handle = ex.submit(self.job())
        ex.poll(handle)
        return ex, ex.fetch_artifact(handle, self.tmp / "artifacts")

    def setUp(self):
        super().setUp()
        # These tests drive submit() directly with BUILD_ID, so the stub and
        # the fixture zip already agree.
        self.server.state["build_id"] = BUILD_ID

    def test_the_ipa_lands_on_disk(self):
        _, path = self._fetch()
        self.assertIsNotNone(path)
        self.assertTrue(Path(path).exists())
        self.assertEqual(Path(path).read_bytes(), b"fake-ipa-payload")
        self.assertEqual(Path(path).name, f"{BUILD_ID}.ipa")

    def test_the_token_never_reaches_the_redirect_host(self):
        """The signed blob URL belongs to someone else - it must not get our
        credentials, even though urllib would resend them by default."""
        self._fetch()
        self.assertIsNotNone(self.server.state["auth_on_api"],
                             "the API call itself must be authenticated")
        self.assertIsNone(self.server.state["auth_on_blob"],
                          "the token leaked to the artifact download host")

    def test_a_truncated_download_is_caught_by_the_checksum(self):
        self.server.state["zip"] = ipa_zip(checksum="0" * 64)
        with self.assertRaises(ValidationError) as ctx:
            self._fetch()
        self.assertIn("SHA-256", str(ctx.exception))

    def test_an_unreadable_checksum_file_is_refused(self):
        self.server.state["zip"] = ipa_zip(checksum="nonsense")
        with self.assertRaises(ValidationError):
            self._fetch()

    def test_an_artifact_without_an_ipa_is_refused(self):
        self.server.state["zip"] = make_zip({"build.log": "nothing useful"})
        with self.assertRaises(ValidationError) as ctx:
            self._fetch()
        self.assertIn("keine .ipa", str(ctx.exception))

    def test_two_ipas_are_refused_rather_than_guessed_between(self):
        self.server.state["zip"] = make_zip({"a.ipa": b"one", "b.ipa": b"two"})
        with self.assertRaises(ValidationError) as ctx:
            self._fetch()
        self.assertIn("mehrere", str(ctx.exception))

    def test_a_zip_slip_entry_is_refused(self):
        """The archive arrives over the network; its names are not trusted.

        The message is asserted, not just the exception type: the name check
        and the containment check behind it would otherwise mask each other,
        and a test that passes whichever one is missing pins neither.
        """
        for hostile in ("../../escaped.ipa", "/etc/evil.ipa", "a/../../x.ipa",
                        "C:/windows/evil.ipa", "sub/../../../out.ipa"):
            self.server.state["zip"] = make_zip({hostile: b"payload"})
            with self.assertRaises(ValidationError, msg=hostile) as ctx:
                self._fetch()
            self.assertIn("unzulaessigen Pfad", str(ctx.exception), hostile)
        # Scoped to this test's own tree: /tmp is shared, and a stray file
        # someone else left there would make this pass or fail for the wrong
        # reason.
        escaped = [p for p in self.tmp.rglob("*.ipa")
                   if (self.tmp / "artifacts") not in p.parents]
        self.assertEqual(escaped, [], f"written outside the target dir: {escaped}")
        self.assertEqual(list((self.tmp / "artifacts").glob("*.ipa")), [])

    def test_a_harmless_subdirectory_entry_still_works(self):
        """The guard must not be so blunt that a normal archive is refused."""
        payload = b"nested-ipa"
        digest = hashlib.sha256(payload).hexdigest()
        self.server.state["zip"] = make_zip({
            f"artifact/{BUILD_ID}.ipa": payload,
            f"artifact/{BUILD_ID}.sha256": f"{digest}  x\n"})
        _, path = self._fetch()
        self.assertTrue(Path(path).exists())
        self.assertEqual(Path(path).read_bytes(), payload)

    def test_a_zip_with_absurdly_many_entries_is_refused(self):
        self.server.state["zip"] = make_zip({f"f{i}.txt": b"x" for i in range(200)})
        with self.assertRaises(ValidationError) as ctx:
            self._fetch()
        self.assertIn("Eintraege", str(ctx.exception))

    def test_a_zip_bomb_is_refused_before_it_is_written(self):
        """Compresses to nothing, expands to more than the cap."""
        from unittest import mock

        from bb.executors import github as gh

        self.server.state["zip"] = make_zip({"big.ipa": b"\0" * (4 * 1024 * 1024)})
        with mock.patch.object(gh, "MAX_ARTIFACT_BYTES", 1024 * 1024):
            with self.assertRaises(ValidationError) as ctx:
                self._fetch()
        self.assertIn("gross", str(ctx.exception))
        self.assertFalse(list((self.tmp / "artifacts").glob("*.ipa")),
                         "nothing may be written before the size is known")

    def test_something_that_is_not_a_zip_is_refused(self):
        self.server.state["zip"] = b"this is not a zip archive"
        with self.assertRaises(ValidationError) as ctx:
            self._fetch()
        self.assertIn("kein lesbares Zip", str(ctx.exception))

    def test_an_expired_artifact_says_so(self):
        self.server.state["artifacts"] = [
            {"id": 9, "name": BUILD_ID, "expired": True, "size_in_bytes": 1}]
        with self.assertRaises(ExecutorUnavailable) as ctx:
            self._fetch()
        self.assertIn("abgelaufen", str(ctx.exception))

    def test_a_missing_artifact_names_what_was_there(self):
        self.server.state["artifacts"] = [
            {"id": 9, "name": "etwas-anderes", "expired": False, "size_in_bytes": 1}]
        with self.assertRaises(ExecutorUnavailable) as ctx:
            self._fetch()
        self.assertIn("etwas-anderes", str(ctx.exception))

    def test_a_redirect_to_another_scheme_is_refused(self):
        self.server.state["artifacts"] = [
            {"id": 8, "name": BUILD_ID, "expired": False, "size_in_bytes": 1}]
        with self.assertRaises(ValidationError) as ctx:
            self._fetch()
        self.assertIn("ftp", str(ctx.exception))

    def test_against_the_real_api_only_https_redirects_are_accepted(self):
        """The stub is reached over http; api.github.com must not be."""
        ex = self.executor(api_base="https://api.github.com")
        import urllib.parse
        self.assertEqual(
            urllib.parse.urlparse(ex.api_base).scheme, "https")

    def test_fetch_without_a_submitted_handle_returns_nothing(self):
        self.assertIsNone(self.executor().fetch_artifact("github:unknown",
                                                         self.tmp / "x"))


if __name__ == "__main__":
    unittest.main()


class TestEndToEndThroughTheController(GitHubExecutorCase):
    """The whole pipeline with a real artifact coming back over HTTP.

    This is what BB-011 was blocking: until fetch_artifact existed, a
    successful run ended in "Executor meldet Erfolg, liefert aber keine IPA".
    """

    def setUp(self):
        super().setUp()
        from helpers import make_ipa

        # A real, inspectable IPA matching the fixture project.
        ipa_path = make_ipa(self.tmp / "built.ipa")
        payload = ipa_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        self.server.state["zip"] = make_zip({
            f"{BUILD_ID}.ipa": payload,
            f"{BUILD_ID}.sha256": f"{digest}  artifact/{BUILD_ID}.ipa\n",
        })
        self.expected_sha = digest

    def _controller(self):
        import json

        from bb.builds import BuildController
        from bb.projects import Project, Registry

        data = json.loads(json.dumps(self.project_data))
        data["executor"] = "github"
        data["executor_config"] = {
            "repo": "o/r", "visibility": "public", "runs_on": "macos-latest",
            "token_file": str(self.token_file), "api_base": self.base}
        config = dict(self.config)
        config["default_executor"] = "github"
        from bb.config import Config
        return BuildController(Config(config), Registry([Project(data)]))

    def test_a_successful_run_produces_a_verified_ipa_and_an_ota_release(self):
        from bb import states as S

        controller = self._controller()
        manifest = controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian")
        self.assertEqual(manifest.status, S.QUEUED)

        done = controller.run_next(poll_interval=0)
        self.assertEqual(done.status, S.SUCCESS,
                         done.get("failure_reason"))
        self.assertFalse(done.is_dry_run)
        self.assertEqual(done.get("artifact_sha256"), self.expected_sha)
        self.assertTrue(Path(done.get("artifact_path")).exists())

        ota = done.get("ota")
        self.assertIsNotNone(ota, "an ad-hoc build must produce an OTA release")
        self.assertEqual(ota["ipa_sha256"], self.expected_sha)
        self.assertTrue(ota["install_url"].startswith("itms-services://"))
        self.assertEqual(ota["device_count"], 2)

        out = controller.paths.ota / done.build_id
        self.assertTrue((out / "qr.svg").exists())
        self.assertTrue((out / "qr.png").read_bytes().startswith(b"\x89PNG"))

        # It counts as a real build now - the limiter must see it.
        self.assertEqual(controller.limiter.status("testapp")["used"], 1)

    def test_a_tampered_artifact_never_becomes_a_success(self):
        from bb import states as S
        from helpers import make_ipa

        # Right checksum file, wrong bundle id inside: the download is intact
        # but the IPA is not the one that was ordered.
        other = make_ipa(self.tmp / "wrong.ipa", bundle_id="com.example.other")
        payload = other.read_bytes()
        self.server.state["zip"] = make_zip({
            f"{BUILD_ID}.ipa": payload,
            f"{BUILD_ID}.sha256": f"{hashlib.sha256(payload).hexdigest()}  x\n",
        })
        controller = self._controller()
        controller.request_build("testapp", "AD_HOC", requested_by="sebastian")
        done = controller.run_next(poll_interval=0)
        self.assertEqual(done.status, S.FAILED)
        self.assertIn("Bundle ID", done.get("failure_reason"))
        self.assertIsNone(done.get("ota"))
