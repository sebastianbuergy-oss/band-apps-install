"""Cost guard (brief section 4) - the hard requirement."""
import unittest

from helpers import ControllerCase

from bb.costguard import PAID, CostGuard
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
        decision = guard.decide(resource, minutes=1)
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


if __name__ == "__main__":
    unittest.main()
