"""Storage, redaction, ids, manifests, audit log and concurrency."""
import json
import os
import threading
import unittest

from helpers import ControllerCase

from bb import states as S
from bb.errors import ValidationError
from bb.ids import (derive_code, make_build_id, parse_build_id, validate_branch,
                    validate_commit, validate_project_id)
from bb.redact import MASK, redact, redact_text
from bb.store import FileLock, read_json, safe_child, sha256_file, write_json


class TestRedaction(unittest.TestCase):
    def test_secret_keys_are_masked(self):
        data = {"api_token": "abc", "ASC_KEY_ID": "K", "privateKeyPem": "x",
                "certificate_password": "p", "bundle_id": "com.a.b", "version": "1.0"}
        out = redact(data)
        for key in ("api_token", "ASC_KEY_ID", "privateKeyPem", "certificate_password"):
            self.assertEqual(out[key], MASK, key)
        self.assertEqual(out["bundle_id"], "com.a.b")
        self.assertEqual(out["version"], "1.0")

    def test_nested_structures_are_walked(self):
        out = redact({"a": [{"token": "t"}, {"safe": "s"}]})
        self.assertEqual(out["a"][0]["token"], MASK)
        self.assertEqual(out["a"][1]["safe"], "s")

    def test_assignments_in_free_text_are_masked(self):
        for text, secret in [
            ("export CM_API_TOKEN=gho_0123456789abcdefghijklmn", "gho_0123456789abcdefghijklmn"),
            ('APP_STORE_CONNECT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----abc"', "abc"),
            ("password: hunter2hunter2", "hunter2hunter2"),
        ]:
            self.assertNotIn(secret, redact_text(text), text)

    def test_pem_blocks_are_collapsed(self):
        pem = ("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADAN\n-----END PRIVATE KEY-----")
        self.assertNotIn("MIIEvQIBADAN", redact_text(pem))

    def test_long_base64_blobs_are_masked(self):
        blob = "A" * 80
        self.assertNotIn(blob, redact_text(f"cert: {blob}"))

    def test_checksums_survive_redaction(self):
        """A SHA-256 is 64 hex chars, which the base64-ish pattern matched.

        Every manifest and the install page exist to show this value, so
        redacting it destroyed the one thing the brief asks for in section 14.
        """
        sha = "9fa8f7c2543be9f58b8fe3ad1bdbd1df616ce568948e0c86f10c4394bb661275"
        self.assertEqual(redact_text(sha), sha)
        self.assertEqual(redact({"artifact_sha256": sha})["artifact_sha256"], sha)
        self.assertEqual(redact({"ipa_sha256": sha})["ipa_sha256"], sha)
        self.assertIn(sha, redact_text(f"shasum: {sha}  artifact/app.ipa"))

    def test_key_material_that_merely_looks_like_a_digest_is_still_redacted(self):
        # Right alphabet, wrong length for any digest.
        self.assertEqual(redact_text("a" * 70), MASK)
        # Real base64 with mixed case and padding.
        blob = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCxyzabcdef1234=="
        self.assertNotIn(blob, redact_text(blob))

    def test_harmless_lookalike_keys_survive(self):
        out = redact({"auth_required": True, "auth_mode": "bearer"})
        self.assertEqual(out["auth_required"], True)
        self.assertEqual(out["auth_mode"], "bearer")

    def test_the_audit_log_redacts_on_the_way_in(self):
        pass  # covered by TestAuditLog below


class TestIds(unittest.TestCase):
    def test_derive_code(self):
        self.assertEqual(derive_code("GoSafeHome"), "GSH")
        self.assertEqual(derive_code("thy-gnosis"), "TG")
        self.assertEqual(derive_code("days-of-ruin"), "DOR")

    def test_build_id_round_trip(self):
        import datetime

        build_id = make_build_id("GSH", 1, datetime.date(2026, 9, 20))
        self.assertEqual(build_id, "BB-20260920-GSH-001")
        day, code, seq = parse_build_id(build_id)
        self.assertEqual((code, seq), ("GSH", 1))

    def test_hostile_identifiers_are_refused(self):
        for bad in ("../../etc/passwd", "a/b", "A_B", "", "x" * 60):
            with self.assertRaises(ValidationError, msg=bad):
                validate_project_id(bad)
        for bad in ("HEAD; rm -rf /", "not-hex", "", "z" * 40):
            with self.assertRaises(ValidationError, msg=bad):
                validate_commit(bad)
        for bad in ("../evil", "a b", ""):
            with self.assertRaises(ValidationError, msg=bad):
                validate_branch(bad)


class TestStore(ControllerCase):
    def test_writes_are_atomic_and_leave_no_temp_files(self):
        target = self.tmp / "state.json"
        write_json(target, {"a": 1})
        write_json(target, {"a": 2})
        self.assertEqual(read_json(target), {"a": 2})
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.is_file()),
                         ["state.json", "tokens.json"] if (self.tmp / "tokens.json").exists()
                         else ["state.json"])

    def test_a_corrupt_json_file_is_reported_not_swallowed(self):
        from bb.errors import StorageError

        target = self.tmp / "broken.json"
        target.write_text("{oh no", encoding="utf-8")
        with self.assertRaises(StorageError):
            read_json(target)

    def test_path_traversal_is_refused(self):
        for bad in ("..", ".", "/etc/passwd", "a/b", "a\\b", ""):
            with self.assertRaises(ValidationError, msg=bad):
                safe_child(self.tmp, bad)
        self.assertTrue(str(safe_child(self.tmp, "ok.json")).startswith(str(self.tmp)))

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks on this platform")
    def test_a_symlink_that_escapes_the_root_is_refused(self):
        """The component checks pass here - only the containment check catches it.

        A single plain name, no dots, no separators: everything the per-part
        validation looks at is fine. It is resolving the symlink that reveals
        the target sits outside the root, which is exactly what the final
        containment check is for.
        """
        outside = self.tmp / "outside"
        outside.mkdir()
        root = self.tmp / "root"
        root.mkdir()
        try:
            os.symlink(outside, root / "escape")
        except (OSError, NotImplementedError) as exc:   # Windows without privilege
            self.skipTest(f"cannot create a symlink here: {exc}")
        with self.assertRaises(ValidationError):
            safe_child(root, "escape")

    def test_sha256_matches_hashlib(self):
        import hashlib

        blob = self.tmp / "blob.bin"
        blob.write_bytes(b"burgys" * 1000)
        self.assertEqual(sha256_file(blob),
                         hashlib.sha256(b"burgys" * 1000).hexdigest())

    def test_a_stale_lock_is_broken(self):
        lock_path = self.tmp / ".stale.lock"
        lock_path.mkdir()
        write_json(lock_path / "owner.json", {"pid": 999999, "at": 0})
        with FileLock(lock_path, timeout=2, stale_after=1):
            pass  # must not hang or raise

    def test_a_held_lock_times_out_rather_than_waiting_forever(self):
        from bb.errors import StorageError

        held = FileLock(self.tmp / ".held.lock").acquire()
        try:
            with self.assertRaises(StorageError):
                FileLock(self.tmp / ".held.lock", timeout=0.3).acquire()
        finally:
            held.release()


class TestAtomicWriteRetries(ControllerCase):
    """Windows refuses to replace a file another process has open."""

    def test_a_transient_replace_failure_is_retried(self):
        import errno
        from unittest import mock

        from bb.store import write_json

        calls = {"n": 0}
        real = os.replace

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError(errno.EACCES, "file is open in another process")
            return real(src, dst)

        with mock.patch("bb.store.REPLACE_BACKOFF", 0.001), \
                mock.patch("os.replace", side_effect=flaky):
            write_json(self.tmp / "retried.json", {"ok": True})
        self.assertEqual(read_json(self.tmp / "retried.json"), {"ok": True})
        self.assertEqual(calls["n"], 3)

    def test_a_permanent_replace_failure_still_raises_and_cleans_up(self):
        import errno
        from unittest import mock

        from bb.errors import StorageError
        from bb.store import write_json

        with mock.patch("bb.store.REPLACE_BACKOFF", 0.001), \
                mock.patch("os.replace",
                           side_effect=OSError(errno.EACCES, "locked forever")):
            with self.assertRaises(StorageError):
                write_json(self.tmp / "never.json", {"a": 1})
        self.assertFalse(list(self.tmp.glob("never.json*")),
                         "no temp file may be left behind")

    def test_a_non_transient_error_is_not_retried(self):
        import errno
        from unittest import mock

        from bb.errors import DiskFull
        from bb.store import write_json

        with mock.patch("os.replace",
                        side_effect=OSError(errno.ENOSPC, "no space")):
            with self.assertRaises(DiskFull):
                write_json(self.tmp / "full.json", {"a": 1})


class TestTokenFilePermissions(ControllerCase):
    def test_permission_state_is_honest_about_windows(self):
        """Reporting "ok" on Windows would be a claim we have not checked."""
        import os as _os
        from unittest import mock

        from bb.auth import TokenStore

        store = TokenStore(self.tmp / "tok.json")
        store.ensure()
        self.assertEqual(store.permissions_state(), "ok")
        self.assertTrue(store.permissions_ok())
        with mock.patch.object(_os, "name", "nt"):
            self.assertEqual(store.permissions_state(), "unchecked")
            self.assertFalse(store.permissions_ok(),
                             "unchecked must not read as verified")

    def test_a_world_readable_token_file_is_reported(self):
        import stat as _stat

        from bb.auth import TokenStore

        store = TokenStore(self.tmp / "loose.json")
        store.ensure()
        os.chmod(store.path, 0o644)
        self.assertEqual(store.permissions_state(), "too-open")


class TestManifest(ControllerCase):
    def test_illegal_transitions_are_refused_on_the_manifest(self):
        from bb.errors import TransitionError

        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="s", dry_run=True)
        with self.assertRaises(TransitionError):
            manifest.set_state(S.SUCCESS)

    def test_status_cannot_be_set_behind_the_state_machines_back(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="s", dry_run=True)
        with self.assertRaises(ValidationError):
            manifest.update(status=S.SUCCESS)

    def test_the_manifest_holds_every_field_the_brief_asks_for(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="sebastian", dry_run=True)
        for key in ("build_id", "project", "repository", "branch", "commit",
                    "version", "build_number", "mode", "requested_by", "status",
                    "executor", "artifact_sha256", "created_at"):
            self.assertIn(key, manifest.data, key)

    def test_the_checksum_survives_a_save_and_reload(self):
        """The in-memory object kept the value; only disk lost it.

        That is why no test noticed: everything asserted against the live
        manifest. This one goes through the file.
        """
        sha = "9fa8f7c2543be9f58b8fe3ad1bdbd1df616ce568948e0c86f10c4394bb661275"
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="s", dry_run=True)
        manifest.update(artifact_sha256=sha,
                        ota={"ipa_sha256": sha, "app": "Test App"})
        manifest.save(self.controller.paths)

        reloaded = self.rebuild_controller().get(manifest.build_id)
        self.assertEqual(reloaded.get("artifact_sha256"), sha)
        self.assertEqual(reloaded.get("ota")["ipa_sha256"], sha)
        self.assertEqual(reloaded.to_dict()["artifact_sha256"], sha)

    def test_the_checksum_survives_the_audit_log(self):
        sha = "0" * 63 + "f"
        self.controller.audit.record("artifact.created", detail={"sha256": sha})
        self.assertEqual(self.controller.audit.read(1)[0]["detail"]["sha256"], sha)

    def test_no_secret_survives_a_save(self):
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="s", dry_run=True)
        manifest.update(detail={"api_token": "ghp_thisshouldnevershowup"})
        manifest.save(self.controller.paths)
        raw = (self.controller.paths.build_dir(manifest.build_id) / "manifest.json") \
            .read_text(encoding="utf-8")
        self.assertNotIn("ghp_thisshouldnevershowup", raw)

    def test_build_numbers_are_monotonic_and_respect_the_floor(self):
        numbers = self.controller.numbers
        self.assertEqual(numbers.allocate("testapp"), 1)
        self.assertEqual(numbers.allocate("testapp"), 2)
        self.assertEqual(numbers.allocate("testapp", floor=100), 101)
        self.assertEqual(numbers.allocate("testapp"), 102,
                         "a floor must never let the counter go backwards")


class TestAuditLog(ControllerCase):
    def test_entries_are_appended_and_redacted(self):
        self.controller.audit.record(
            "signing.used", actor="sebastian", project="testapp",
            build_id="BB-20260920-TST-001",
            detail={"profile_name": "TestApp adhoc", "p12_password": "geheim"})
        entry = self.controller.audit.read(1)[0]
        self.assertEqual(entry["actor"], "sebastian")
        self.assertEqual(entry["detail"]["profile_name"], "TestApp adhoc")
        self.assertEqual(entry["detail"]["p12_password"], MASK)

    def test_a_torn_last_line_does_not_hide_the_rest(self):
        self.controller.audit.record("a")
        self.controller.audit.record("b")
        path = next(self.controller.audit.dir.glob("audit-*.jsonl"))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('{"at": "2026-')   # power cut mid-write
        actions = [e["action"] for e in self.controller.audit.read(10)]
        self.assertIn("a", actions)
        self.assertIn("b", actions)

    def test_every_action_the_brief_lists_is_recorded_somewhere(self):
        from bb import audit

        for constant in ("BUILD_STARTED", "BUILD_CANCELLED", "SIGNING_USED",
                         "ARTIFACT_CREATED", "OTA_PUBLISHED", "APP_STORE_UPLOAD",
                         "COST_GUARD_BLOCKED"):
            self.assertTrue(hasattr(audit, constant), constant)


class TestConcurrency(ControllerCase):
    def test_two_threads_never_claim_the_same_job(self):
        for i in range(1, 9):
            self.controller.queue.enqueue(f"BB-20260920-TST-{i:03d}", f"p{i}", "AD_HOC")
        claimed, lock = [], threading.Lock()

        def worker():
            while True:
                entry = self.controller.queue.claim("dryrun")
                if entry is None:
                    return
                with lock:
                    claimed.append(entry["build_id"])

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(len(claimed), 8)
        self.assertEqual(len(set(claimed)), 8, "a job was claimed twice")

    def test_parallel_build_number_allocation_hands_out_no_duplicates(self):
        got, lock = [], threading.Lock()

        def worker():
            value = self.controller.numbers.allocate("testapp")
            with lock:
                got.append(value)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(sorted(got), list(range(1, 13)))


if __name__ == "__main__":
    unittest.main()


class TestCrossProcessLocking(ControllerCase):
    """The in-process lock is a convenience; the directory lock is the real one."""

    def test_separate_processes_never_get_the_same_build_number(self):
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        script = (
            "import sys, json;"
            f"sys.path.insert(0, {str(root)!r});"
            "from bb.config import load_config;"
            "from bb.manifest import BuildNumbers;"
            f"cfg = load_config(env={{'BURGYS_DATA': {str(self.controller.paths.root)!r}}});"
            "print(BuildNumbers(cfg.paths().ensure()).allocate('testapp'))"
        )
        procs = [subprocess.Popen([sys.executable, "-c", script],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(8)]
        values = []
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, err.decode()[-400:])
            values.append(int(out.decode().strip()))
        self.assertEqual(sorted(values), list(range(1, 9)),
                         "two processes handed out the same build number")
