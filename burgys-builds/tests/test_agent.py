"""The agent-facing contract: capabilities, client, state file."""
import json
import threading
import unittest
from pathlib import Path

from helpers import ControllerCase

from bb import agentstate
from bb import states as S
from bb.agent_client import (BurgysClient, BurgysDenied, BurgysInvalid,
                             BurgysRefused, BurgysUnreachable, load_token)
from bb.api import serve


class AgentCase(ControllerCase):
    #: Without a worker the queue is never drained, which is the right
    #: default for a human at a keyboard and the wrong one for an agent.
    with_worker = True

    def setUp(self):
        super().setUp()
        self.server = serve(self.controller, "127.0.0.1", 0,
                            worker=self.with_worker)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        if self.server.worker is not None:
            self.addCleanup(self.server.worker.stop)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.tokens = {e["name"]: e["token"] for e in self.server.tokens.tokens()}

    def client(self, name="agent"):
        return BurgysClient(self.url, token=self.tokens[name], timeout=10)


class TestCapabilities(AgentCase):
    def test_it_names_what_this_token_may_do(self):
        caps = self.client("agent").capabilities()
        self.assertEqual(caps["identity"]["name"], "agent")
        self.assertIn("preflight", caps["identity"]["scopes"])
        self.assertNotIn("build", caps["identity"]["scopes"])

    def test_the_release_token_sees_more(self):
        caps = self.client("release").capabilities()
        self.assertIn("build", caps["identity"]["scopes"])
        self.assertIn("release", caps["identity"]["scopes"])

    def test_routes_are_marked_allowed_or_not_for_the_caller(self):
        caps = self.client("agent").capabilities()
        by_path = {(r["method"], r["path"]): r for r in caps["routes"]}
        preflight = next(r for (m, p), r in by_path.items() if p == "/preflight")
        self.assertTrue(preflight["allowed_for_you"])
        approve = next(r for (m, p), r in by_path.items() if "approve" in p)
        self.assertFalse(approve["allowed_for_you"])

    def test_it_publishes_the_state_vocabulary(self):
        caps = self.client().capabilities()
        self.assertEqual(sorted(caps["build_states"]), sorted(S.ALL))
        self.assertIn("BLOCKED_BY_COST_GUARD", caps["terminal_states"])
        self.assertIn("AD_HOC", caps["modes"])

    def test_the_policy_tells_an_agent_what_it_is_up_against(self):
        policy = self.client().capabilities()["policy"]
        self.assertFalse(policy["paid_services_allowed"])
        self.assertIn("max_real_builds_per_project_per_day", policy)
        self.assertIn("executor_produces_real_ipa", policy)
        self.assertFalse(policy["publish_configured"])

    def test_capabilities_needs_a_token_like_everything_else(self):
        import urllib.error
        import urllib.request
        try:
            urllib.request.urlopen(f"{self.url}/capabilities", timeout=10)
            self.fail("should require a token")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 401)


class TestClient(AgentCase):
    def test_health_needs_no_token(self):
        self.assertEqual(BurgysClient(self.url, token="irrelevant").health()["status"], "ok")

    def test_reading_works(self):
        bb = self.client()
        self.assertEqual([p["id"] for p in bb.projects()], ["testapp"])
        self.assertIn("cost_guard", bb.status())
        self.assertEqual(bb.queue()["length"], 0)

    def test_preflight_and_a_dry_run_go_through(self):
        bb = self.client()
        report = bb.preflight("testapp")
        self.assertTrue(report["ok"], report)
        build = bb.request_build("testapp", dry_run=True)
        self.assertTrue(build["dry_run"])
        final = bb.wait_for(build["build_id"], interval=0.2, timeout=60)
        self.assertEqual(final["status"], S.SUCCESS)
        self.assertIn("DRY RUN", final["display_status"])

    def test_a_real_build_is_denied_to_the_agent_token(self):
        with self.assertRaises(BurgysInvalid) as ctx:
            self.client().request_build("testapp", dry_run=False)
        self.assertIn("Release-Token", str(ctx.exception))

    def test_approving_is_denied_to_the_agent_token(self):
        bb_release = self.client("release")
        self.controller.config["require_approval_for_mac_builds"] = True
        build = bb_release.request_build("testapp", dry_run=False)
        with self.assertRaises(BurgysDenied):
            self.client("agent").approve(build["build_id"])

    def test_an_unknown_project_raises_a_distinguishable_error(self):
        with self.assertRaises(BurgysInvalid):
            self.client().preflight("gibt-es-nicht")

    def test_an_unreachable_controller_raises_its_own_error(self):
        bb = BurgysClient("http://127.0.0.1:1", token="x", timeout=2)
        with self.assertRaises(BurgysUnreachable):
            bb.status()

    def test_wait_for_stops_at_waiting_approval(self):
        """Otherwise an agent would spin for ever on a human gate."""
        self.controller.config["require_approval_for_mac_builds"] = True
        build = self.client("release").request_build("testapp", dry_run=False)
        final = self.client().wait_for(build["build_id"], interval=0.05, timeout=10)
        self.assertEqual(final["status"], S.WAITING_APPROVAL)

    def test_wait_for_sits_out_a_rate_limit_instead_of_failing(self):
        """A long build plus eager polling must not look like a failed build."""
        from unittest import mock

        from bb.agent_client import BurgysRateLimited

        bb = self.client()
        build = bb.request_build("testapp", dry_run=True)
        calls = {"n": 0}
        real = bb.build

        def flaky(build_id):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise BurgysRateLimited("zu viele Anfragen", retry_after=1)
            return real(build_id)

        with mock.patch.object(bb, "build", side_effect=flaky):
            final = bb.wait_for(build["build_id"], interval=0.2, timeout=60)
        self.assertGreaterEqual(calls["n"], 3)
        self.assertEqual(final["status"], S.SUCCESS)

    def test_ready_for_real_builds_explains_itself(self):
        ready, reasons = self.client("agent").ready_for_real_builds()
        self.assertFalse(ready)
        self.assertTrue(any("Token" in r for r in reasons), reasons)

    def test_can_answers_scope_questions(self):
        self.assertTrue(self.client("agent").can("preflight"))
        self.assertFalse(self.client("agent").can("build"))
        self.assertTrue(self.client("release").can("build"))

    def test_the_client_never_needs_a_shell_or_a_path(self):
        """Brief section 19: the agent must not run shell commands blindly."""
        import inspect

        from bb import agent_client
        source = inspect.getsource(agent_client)
        for forbidden in ("subprocess", "os.system", "shell=True", "Popen"):
            self.assertNotIn(forbidden, source)


class TestWorker(AgentCase):
    def test_the_worker_drains_what_the_agent_requests(self):
        bb = self.client()
        ids = [bb.request_build("testapp", dry_run=True)["build_id"]
               for _ in range(1)]
        for build_id in ids:
            self.assertEqual(
                bb.wait_for(build_id, interval=0.2, timeout=60)["status"],
                S.SUCCESS)

    def test_the_worker_is_visible_in_the_status(self):
        self.assertTrue(self.client().status()["worker"]["running"])

    def test_a_build_awaiting_approval_is_never_picked_up(self):
        """The worker may only run what a human already cleared."""
        self.controller.config["require_approval_for_mac_builds"] = True
        build = self.client("release").request_build("testapp", dry_run=False)
        self.assertEqual(build["status"], S.WAITING_APPROVAL)
        import time
        time.sleep(1.0)
        self.assertEqual(self.client().build(build["build_id"])["status"],
                         S.WAITING_APPROVAL)
        self.assertEqual(self.client().queue()["length"], 0)


class TestWithoutAWorker(AgentCase):
    with_worker = False

    def test_the_queue_is_not_drained_and_the_status_says_so(self):
        bb = self.client()
        build = bb.request_build("testapp", dry_run=True)
        import time
        time.sleep(0.5)
        self.assertEqual(bb.build(build["build_id"])["status"], S.QUEUED)
        worker = bb.status()["worker"]
        self.assertFalse(worker["running"])
        self.assertIn("burgys run", worker["note"])


class TestTokenLoading(ControllerCase):
    def test_load_token_reads_by_name(self):
        from bb.auth import TokenStore

        store = TokenStore(self.tmp / "tokens.json")
        store.ensure()
        agent = load_token("agent", self.tmp / "tokens.json")
        release = load_token("release", self.tmp / "tokens.json")
        self.assertNotEqual(agent, release)
        self.assertGreater(len(agent), 20)

    def test_a_missing_token_file_says_what_to_run(self):
        from bb.agent_client import BurgysError

        with self.assertRaises(BurgysError) as ctx:
            load_token("agent", self.tmp / "nope.json")
        self.assertIn("bb.cli init", str(ctx.exception))

    def test_an_unknown_token_name_lists_what_exists(self):
        from bb.agent_client import BurgysError
        from bb.auth import TokenStore

        TokenStore(self.tmp / "t.json").ensure()
        with self.assertRaises(BurgysError) as ctx:
            load_token("admin", self.tmp / "t.json")
        self.assertIn("agent", str(ctx.exception))


class TestAgentState(ControllerCase):
    def test_the_controller_writes_the_state_file(self):
        target = self.tmp / "state.json"
        agentstate.update(self.controller, agent="codex", path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["last_agent"], "codex")
        self.assertTrue(data["system_status"]["cost_guard"])
        self.assertIn("builds", data)

    def test_human_written_fields_are_preserved(self):
        """A person's notes must survive the next machine write."""
        target = self.tmp / "state.json"
        target.write_text(json.dumps({
            "active_tasks": ["BB-013"], "notes": "von Hand geschrieben",
            "current_commit": "abc1234"}), encoding="utf-8")
        agentstate.update(self.controller, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["active_tasks"], ["BB-013"])
        self.assertEqual(data["notes"], "von Hand geschrieben")
        self.assertEqual(data["current_commit"], "abc1234")

    def test_it_follows_a_build_through(self):
        target = self.tmp / "state.json"
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="agent", dry_run=True)
        self.controller.run_next(poll_interval=0)
        agentstate.update(self.controller, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["builds"]["today"]["dry_runs"], 1)
        self.assertEqual(data["builds"]["running"], [])
        # A dry run is not a real success, so it must not be advertised as one.
        self.assertIsNone(data["builds"]["last_success"])

    def test_a_real_success_is_reported_with_its_checksum(self):
        target = self.tmp / "state.json"
        manifest = self.controller.request_build(
            "testapp", "AD_HOC", requested_by="s", dry_run=True)
        sha = "1" * 64
        manifest.data["dry_run"] = False
        manifest.update(artifact_sha256=sha)
        while manifest.status != S.SUCCESS:
            nxt = {S.QUEUED: S.VERIFYING, S.VERIFYING: S.SUCCESS}.get(
                manifest.status, S.QUEUED)
            manifest.set_state(nxt)
        manifest.save(self.controller.paths)
        agentstate.update(self.controller, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["builds"]["last_success"]["artifact_sha256"], sha)

    def test_a_broken_state_write_never_kills_a_build(self):
        from unittest import mock

        with mock.patch("bb.agentstate.update", side_effect=OSError("disk gone")):
            manifest = self.controller.request_build(
                "testapp", "AD_HOC", requested_by="s", dry_run=True)
            done = self.controller.run_next(poll_interval=0)
        self.assertEqual(done.status, S.SUCCESS)


if __name__ == "__main__":
    unittest.main()
