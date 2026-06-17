#!/usr/bin/env python3
"""
Deterministic strict-validator tests (stdlib unittest only — zero new deps).

Covers the four adversarial-bucket failure modes the model executes ~31% of the time
(self-dep, unknown-id, op-char-id, dup-id), the no-false-positive guarantee on real
v-intent capsules, the `+new` exemption, and the CLI exit codes for an unattended
pipeline (`validate --strict`).

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_strict_validate.py
"""
import os, sys, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intent_queue as iq  # noqa: E402

PLAN_IDS = ["auth-flow", "dark-mode", "csv-export", "rate-limit"]
EXAMPLE_CAPSULE = os.path.join(ROOT, "examples", "example-capsule.txt")


def reasons(rej):
    return " | ".join(r.reason for r in rej)


class SelfDep(unittest.TestCase):
    def test_new_node_blocked_by_itself_is_rejected(self):
        rej = iq.strict_validate("+dup <dup")
        self.assertTrue(rej)
        self.assertIn("self-dep", reasons(rej))

    def test_node_blocking_itself_is_rejected(self):
        rej = iq.strict_validate("~dark-mode >dark-mode", plan_ids=PLAN_IDS)
        self.assertTrue(any("self-dep" in r.reason for r in rej))


class UnknownId(unittest.TestCase):
    def test_unknown_id_with_plan_is_rejected(self):
        rej = iq.strict_validate("v nonexistent-xyz", plan_ids=PLAN_IDS)
        self.assertTrue(rej)
        self.assertIn("unknown id", reasons(rej))

    def test_same_capsule_with_id_present_passes(self):
        # the criterion: the same op, but the id IS in the plan -> no rejection
        self.assertEqual(iq.strict_validate("v dark-mode", plan_ids=PLAN_IDS), [])

    def test_unknown_id_skipped_without_a_plan(self):
        # can't know what's unknown with no plan supplied
        self.assertEqual(iq.strict_validate("v whatever-id"), [])

    def test_new_then_reference_in_same_capsule_is_known(self):
        # a +new id is exempt AND becomes known to later ops in the same capsule
        rej = iq.strict_validate("+brand-new-thing\nv brand-new-thing", plan_ids=PLAN_IDS)
        self.assertFalse(any("unknown id" in r.reason for r in rej))


class OpCharId(unittest.TestCase):
    def test_new_id_starting_with_op_char_is_rejected(self):
        rej = iq.strict_validate("+x-1")
        self.assertTrue(rej)
        self.assertIn("op char", reasons(rej))

    def test_new_id_starting_with_rm_is_rejected(self):
        rej = iq.strict_validate("+rm-thing")
        self.assertTrue(any("op char" in r.reason for r in rej))

    def test_kebab_new_id_is_fine(self):
        self.assertEqual(iq.strict_validate("+brand-new-feature"), [])


class DupId(unittest.TestCase):
    def test_duplicate_target_id_in_one_capsule_is_rejected(self):
        rej = iq.strict_validate("v dark-mode\nv dark-mode", plan_ids=PLAN_IDS)
        self.assertTrue(rej)
        self.assertIn("duplicate id", reasons(rej))

    def test_distinct_ids_are_fine(self):
        self.assertEqual(iq.strict_validate("v dark-mode\nv csv-export", plan_ids=PLAN_IDS), [])


class NoFalsePositives(unittest.TestCase):
    def test_shipped_example_v_intent_capsule_passes(self):
        with open(EXAMPLE_CAPSULE) as f:
            text = f.read()
        # the v-intent tags !:/~:/?:/=: must NOT be mistaken for plan-ops ops
        self.assertEqual(iq.strict_validate(text, plan_ids=PLAN_IDS), [])

    def test_v_intent_bang_tilde_question_tags_are_not_ops(self):
        cap = "@x\ndo: build a thing\n!: must not crash\n~: prefer a worker\n?: only when N>0\n=: it works"
        self.assertEqual(iq.strict_validate(cap, plan_ids=PLAN_IDS), [])

    def test_clean_planops_batch_passes(self):
        self.assertEqual(
            iq.strict_validate("+new-feature\nv dark-mode\n~csv-export", plan_ids=PLAN_IDS), [])


class CliExitCodes(unittest.TestCase):
    """The unattended-pipeline contract: nonzero exit on a deterministic violation."""

    def _run(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(text); path = f.name
        plan = os.path.join(ROOT, "example_plan.json")
        try:
            return subprocess.run(
                [sys.executable, os.path.join(ROOT, "intent_queue.py"),
                 "validate", "--strict", "--plan", plan, "--file", path],
                capture_output=True, text=True)
        finally:
            os.unlink(path)

    def test_self_dep_exits_nonzero(self):
        r = self._run("@bad\ndo: x\n=: y\n+dup <dup")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("self-dep", r.stdout)

    def test_clean_v_intent_capsule_exits_zero(self):
        r = self._run("@good\ndo: build a thing\nin: file.ts\n=: it works")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
