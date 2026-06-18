#!/usr/bin/env python3
"""
Strict-flag-clarify tests (stdlib unittest only — zero new deps).

Covers the disambiguation of the strict gate: `validate --help` makes clear the
gate is plan-ops-only (not a v-intent completeness lint); the new --strict-planops
name and the back-compat --strict alias both trigger the same plan-ops gate.

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_strict_flag.py
"""
import os, sys, shutil, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IQ = os.path.join(ROOT, "intent_queue.py")


def run(args, env_extra, stdin=None):
    return subprocess.run([sys.executable, IQ, *args], capture_output=True, text=True,
                          input=stdin, env=dict(os.environ, **env_extra))


class StrictFlagClarify(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.q = os.path.join(self.d, "queue.jsonl")
        self.env = {"INTENT_QUEUE": self.q}

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_validate_help_clarifies_scope(self):
        # =[1]: validate --help makes clear strict gates plan-ops only, not completeness
        r = run(["validate", "--help"], self.env)
        self.assertEqual(r.returncode, 0)
        out = r.stdout.lower()
        self.assertIn("plan-ops", out)
        self.assertIn("not", out)            # states what it does NOT cover
        self.assertIn("completeness", out)

    def test_strict_alias_and_new_name_both_gate_planops(self):
        # =[2]: --strict (alias) and --strict-planops both trigger the plan-ops gate identically
        cap = "@good\ndo: a thing\n=: done\n+dup <dup\n"   # completeness OK, plan-ops self-dep
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        f.write(cap); f.close()
        try:
            r_plain = run(["validate", "--file", f.name], self.env)
            r_alias = run(["validate", "--strict", "--file", f.name], self.env)
            r_new = run(["validate", "--strict-planops", "--file", f.name], self.env)
        finally:
            os.unlink(f.name)
        self.assertEqual(r_plain.returncode, 0)   # no strict gate -> completeness passes
        self.assertEqual(r_alias.returncode, 1)   # alias triggers the plan-ops gate
        self.assertEqual(r_new.returncode, 1)     # new name triggers the plan-ops gate
        self.assertIn("self-dep", r_alias.stdout + r_alias.stderr)
        self.assertIn("self-dep", r_new.stdout + r_new.stderr)


if __name__ == "__main__":
    unittest.main()
