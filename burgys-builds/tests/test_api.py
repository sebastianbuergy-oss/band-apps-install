"""Agent API: authentication, scopes, rate limiting, input validation."""
import json
import threading
import unittest
import urllib.error
import urllib.request

from helpers import ControllerCase

from bb.api import serve


class ApiCase(ControllerCase):
    def setUp(self):
        super().setUp()
        self.server = serve(self.controller, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.tokens = {e["name"]: e["token"] for e in self.server.tokens.tokens()}

    def call(self, method, path, token=None, body=None, headers=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={**({"Authorization": f"Bearer {token}"} if token else {}),
                     **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read().decode()
                return response.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            return exc.code, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)


class TestAuth(ApiCase):
    def test_health_needs_no_token(self):
        self.assertEqual(self.call("GET", "/health")[0], 200)

    def test_everything_else_needs_a_token(self):
        for path in ("/status", "/projects", "/queue", "/audit"):
            self.assertEqual(self.call("GET", path)[0], 401, path)

    def test_a_wrong_token_is_rejected(self):
        self.assertEqual(self.call("GET", "/status", "definitely-not-the-token")[0], 401)

    def test_the_agent_token_may_read_and_preflight(self):
        self.assertEqual(self.call("GET", "/status", self.tokens["agent"])[0], 200)
        status, body = self.call("POST", "/preflight", self.tokens["agent"],
                                 {"project": "testapp", "mode": "AD_HOC"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_the_agent_token_may_not_start_a_real_build(self):
        status, body = self.call("POST", "/builds", self.tokens["agent"],
                                 {"project": "testapp", "mode": "AD_HOC"})
        self.assertEqual(status, 400)
        self.assertIn("Release-Token", body["error"])

    def test_the_agent_token_may_run_a_dry_run(self):
        status, body = self.call("POST", "/builds", self.tokens["agent"],
                                 {"project": "testapp", "mode": "AD_HOC",
                                  "dry_run": True})
        self.assertEqual(status, 202)
        self.assertTrue(body["dry_run"])

    def test_the_release_token_may_start_a_real_build(self):
        status, _ = self.call("POST", "/builds", self.tokens["release"],
                              {"project": "testapp", "mode": "AD_HOC"})
        self.assertEqual(status, 202)

    def test_approval_needs_the_release_token(self):
        controller = self.controller
        controller.config["require_approval_for_mac_builds"] = True
        _, body = self.call("POST", "/builds", self.tokens["release"],
                            {"project": "testapp", "mode": "AD_HOC"})
        build_id = body["build_id"]
        self.assertEqual(
            self.call("POST", f"/builds/{build_id}/approve", self.tokens["agent"])[0], 401)

    def test_denied_calls_are_audited(self):
        self.call("GET", "/status")
        self.assertTrue([e for e in self.controller.audit.read(20)
                         if e["action"] == "api.denied"])

    def test_the_token_file_is_owner_only(self):
        self.assertTrue(self.server.tokens.permissions_ok())


class TestInputValidation(ApiCase):
    def test_path_traversal_in_a_build_id_does_not_match_a_route(self):
        for path in ("/builds/../../etc/passwd/logs",
                     "/builds/..%2f..%2fetc/logs",
                     "/builds/BB-x/logs"):
            self.assertEqual(self.call("GET", path, self.tokens["agent"])[0], 404, path)

    def test_an_unknown_project_is_a_clean_error(self):
        status, body = self.call("POST", "/preflight", self.tokens["agent"],
                                 {"project": "nicht-da"})
        self.assertIn(status, (400, 409))
        self.assertIn("error", body)

    def test_a_project_id_with_a_slash_is_refused(self):
        status, _ = self.call("POST", "/preflight", self.tokens["agent"],
                              {"project": "../../etc/passwd"})
        self.assertEqual(status, 400)

    def test_a_non_json_body_is_refused(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/preflight", method="POST",
            data=b"not json at all",
            headers={"Authorization": f"Bearer {self.tokens['agent']}"})
        try:
            urllib.request.urlopen(request, timeout=10)
            self.fail("should have been rejected")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)

    def test_an_oversized_body_is_refused(self):
        status, _ = self.call("POST", "/preflight", self.tokens["agent"],
                              {"project": "testapp", "junk": "x" * 70000})
        self.assertEqual(status, 400)

    def test_a_silly_tail_parameter_is_refused(self):
        _, body = self.call("POST", "/builds", self.tokens["agent"],
                            {"project": "testapp", "dry_run": True})
        build_id = body["build_id"]
        self.assertEqual(
            self.call("GET", f"/builds/{build_id}/logs?tail=abc",
                      self.tokens["agent"])[0], 400)

    def test_unknown_routes_are_404(self):
        self.assertEqual(self.call("GET", "/etc/passwd", self.tokens["agent"])[0], 404)


class TestRateLimit(ApiCase):
    config_overrides = {"api_rate_limit_per_minute": 5}

    def test_the_limit_kicks_in(self):
        codes = [self.call("GET", "/health")[0] for _ in range(12)]
        self.assertIn(429, codes)


class TestResponseHygiene(ApiCase):
    def test_no_secret_reaches_a_response(self):
        self.controller.audit.record("test", detail={"api_token": "ghp_supersecretvalue",
                                                     "ok": "sichtbar"})
        status, body = self.call("GET", "/audit", self.tokens["agent"])
        raw = json.dumps(body)
        self.assertEqual(status, 200)
        self.assertNotIn("ghp_supersecretvalue", raw)
        self.assertIn("[REDACTED]", raw)
        self.assertIn("sichtbar", raw)

    def test_security_headers_are_set(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/health")
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_the_artifacts_route_returns_names_not_contents(self):
        _, body = self.call("POST", "/builds", self.tokens["agent"],
                            {"project": "testapp", "dry_run": True})
        status, artifacts = self.call(
            "GET", f"/builds/{body['build_id']}/artifacts", self.tokens["agent"])
        self.assertEqual(status, 200)
        self.assertEqual(artifacts["files"], [])
        self.assertTrue(artifacts["dry_run"])

    def test_the_dashboard_needs_a_token(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 401)
        self.assertIn("Token noetig", body)

    def test_the_dashboard_renders_with_a_token(self):
        status, body = self.call("GET", f"/?token={self.tokens['agent']}")
        self.assertEqual(status, 200)
        for needle in ("Buergys", "Cost Guard", "Projekte", "Observability",
                       "macOS-Minuten"):
            self.assertIn(needle, body)
        self.assertNotIn(self.tokens["agent"], body)


if __name__ == "__main__":
    unittest.main()
