"""State machine (brief section 13) - the contract with Codex and the Agent."""
import unittest

from helpers import ControllerCase  # noqa: F401  (path setup)

from bb import states as S
from bb.errors import TransitionError


class TestStates(unittest.TestCase):
    def test_every_state_has_a_transition_entry(self):
        self.assertEqual(sorted(S.TRANSITIONS), sorted(S.ALL))

    def test_terminal_states_are_dead_ends(self):
        for state in S.TERMINAL:
            self.assertEqual(S.TRANSITIONS[state], frozenset(),
                             f"{state} must not lead anywhere")

    def test_happy_path_is_legal(self):
        path = [S.DISCOVERED, S.PREFLIGHT, S.READY, S.QUEUED, S.WAITING_MAC,
                S.MAC_BUILDING, S.SIGNING, S.EXPORTING, S.VERIFYING, S.SUCCESS]
        for src, dst in zip(path, path[1:]):
            S.check_transition(src, dst)

    def test_illegal_shortcuts_are_refused(self):
        for src, dst in [(S.READY, S.SUCCESS), (S.DISCOVERED, S.MAC_BUILDING),
                         (S.SUCCESS, S.QUEUED), (S.CANCELLED, S.READY),
                         (S.WAITING_MAC, S.EXPORTING)]:
            with self.assertRaises(TransitionError, msg=f"{src} -> {dst}"):
                S.check_transition(src, dst)

    def test_unknown_states_are_refused(self):
        with self.assertRaises(TransitionError):
            S.check_transition(S.READY, "TOTALLY_FINE_HONEST")
        with self.assertRaises(TransitionError):
            S.check_transition("NOPE", S.READY)

    def test_anything_running_can_fail_be_blocked_or_cancelled(self):
        for state in S.ALL:
            if state in S.TERMINAL:
                continue
            for target in (S.FAILED, S.BLOCKED, S.BLOCKED_BY_COST_GUARD, S.CANCELLED):
                self.assertTrue(S.can_transition(state, target), f"{state} -> {target}")


if __name__ == "__main__":
    unittest.main()
