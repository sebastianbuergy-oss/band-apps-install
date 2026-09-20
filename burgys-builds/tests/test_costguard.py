"""Cost guard (brief section 4) - the hard requirement."""
import unittest

from helpers import ControllerCase

from bb.costguard import PAID, CostGuard, check_runner_label
from bb.errors import CostGuardBlocked


class TestCostGuard(ControllerCase):
    def test_default_is_no_paid_services(self):
        self.assertFalse(self.controller.cost_guard.allowed)

    def test_known_paid_resources_are_blocked(self):
        guard = self.controller.cost_guard
        for resource in ("codemagic", "macstadium", "aws_mac", "azure_mac",
                         "xcode_cloud", "paid_artifact_storage",
                         "github_actions_macos_private_repo"):
            with self.assertRaises(CostGuardBlocked, msg=resource):
                guard.check(resource)

    def test_unknown_resources_fail_closed(self):
        """A resource nobody classified must be treated as costing money."""
        guard = self.controller.cost_guard
        self.assertEqual(guard.classify("some-new-cloud-mac-2027")["cost"], PAID)
        with self.assertRaises(CostGuardBlocked):
            guard.check("some-new-cloud-mac-2027")

    def test_free_resources_pass(self):
        for resource in ("windows_local", "github_pages", "local_mac"):
            self.assertTrue(self.controller.cost_guard.decide(resource)["allowed"])

    def test_exhausted_free_tier_blocks_without_paid_fallback(self):
        guard = self.controller.cost_guard
        resource = "github_actions_macos_public_repo"
        guard.record_minutes(resource, 2000)
        # A valid standard-runner label, so the quota is what decides here
        # and not the runner allowlist (covered separately below).
        decision = guard.decide(resource, minutes=1, runner_label="macos-latest")
        self.assertFalse(decision["allowed"])
        self.assertIn("Freikontingent", decision["reason"])
        self.assertIn("Kein automatischer kostenpflichtiger Fallback", decision["reason"])

    def test_ledger_survives_a_restart(self):
        self.controller.cost_guard.record_minutes("github_actions_macos_public_repo", 12.5)
        fresh = self.rebuild_controller()
        self.assertEqual(fresh.cost_guard.usage("github_actions_macos_public_repo"), 12.5)

    def test_explicit_approval_unlocks_paid(self):
        config = dict(self.config)
        config["paid_services_allowed"] = True
        guard = CostGuard(self.config.__class__(config), self.controller.paths)
        self.assertTrue(guard.decide("codemagic")["allowed"])

    def test_a_standard_runner_on_a_public_repo_is_free(self):
        decision = self.controller.cost_guard.decide(
            "github_actions_macos_public_repo", runner_label="macos-latest")
        self.assertTrue(decision["allowed"], decision["reason"])

    def test_build_request_is_blocked_and_audited(self):
        data = dict(self.project_data)
        data["executor"] = "github"
        data["executor_config"] = {"repo": "a/b", "visibility": "private",
                                   "token_file": "/nonexistent"}
        from bb.builds import BuildController
        from bb.projects import Project, Registry

        controller = BuildController(self.config, Registry([Project(data)]))
        with self.assertRaises(CostGuardBlocked):
            controller.request_build("testapp", "AD_HOC", requested_by="agent")
        blocked = [e for e in controller.audit.read(20)
                   if e["action"] == "costguard.blocked"]
        self.assertTrue(blocked, "the refusal must be in the audit log")


class TestRunnerAllowlist(ControllerCase):
    """Requirement: only an explicitly approved list of standard runners.

    A larger runner is charged even on a public repository, so a label we
    cannot vouch for has to be refused rather than assumed free.
    """

    def test_standard_macos_labels_are_allowed(self):
        for label in ("macos-latest", "macos-15", "macos-26", "xcode-27",
                      "macos-15-intel"):
            self.assertTrue(check_runner_label(label)["allowed"], label)

    def test_larger_runners_are_refused(self):
        for label in ("macos-latest-xlarge", "macos-15-xlarge", "macos-14-large",
                      "macos-13-xlarge", "macos-latest-xl"):
            verdict = check_runner_label(label)
            self.assertFalse(verdict["allowed"], label)

    def test_self_hosted_and_foreign_labels_are_refused(self):
        for label in ("self-hosted", "ubuntu-latest", "windows-latest",
                      "macos-99", "some-future-runner"):
            self.assertFalse(check_runner_label(label)["allowed"], label)

    def test_a_missing_label_is_refused_not_assumed_free(self):
        for label in ("", None, "   "):
            verdict = check_runner_label(label)
            self.assertFalse(verdict["allowed"], repr(label))
            self.assertIn("raet nicht", verdict["reason"])

    def test_label_comparison_ignores_case(self):
        self.assertTrue(check_runner_label("MacOS-Latest")["allowed"])

    def test_the_guard_blocks_a_github_executor_without_a_label(self):
        decision = self.controller.cost_guard.decide(
            "github_actions_macos_public_repo", runner_label=None)
        self.assertFalse(decision["allowed"])
        self.assertIn("Runner abgelehnt", decision["reason"])

    def test_the_guard_blocks_a_larger_runner_even_on_a_public_repo(self):
        decision = self.controller.cost_guard.decide(
            "github_actions_macos_public_repo", runner_label="macos-15-xlarge")
        self.assertFalse(decision["allowed"])

    def test_a_build_request_on_a_larger_runner_is_refused_end_to_end(self):
        data = dict(self.project_data)
        data["executor"] = "github"
        data["executor_config"] = {"repo": "a/b", "visibility": "public",
                                   "token_file": "/nonexistent",
                                   "runs_on": "macos-15-xlarge"}
        from bb.builds import BuildController
        from bb.projects import Project, Registry

        controller = BuildController(self.config, Registry([Project(data)]))
        with self.assertRaises(CostGuardBlocked) as ctx:
            controller.request_build("testapp", "AD_HOC", requested_by="agent")
        self.assertIn("Runner abgelehnt", str(ctx.exception))

    def test_the_shipped_workflow_template_uses_an_allowed_runner(self):
        """The template must not drift away from what the guard permits."""
        import re
        from pathlib import Path

        template = Path(__file__).resolve().parents[1] / "templates" / "burgys-ios-build.yml"
        # Only real YAML keys - a "runs-on:" inside a comment is prose.
        labels = [m.group(1) for m in (
            re.match(r"\s*runs-on:\s*(\S+)\s*$", line)
            for line in template.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")) if m]
        self.assertTrue(labels, "template has no runs-on")
        for label in labels:
            self.assertTrue(check_runner_label(label)["allowed"],
                            f"template uses {label}, which the cost guard refuses")


if __name__ == "__main__":
    unittest.main()
