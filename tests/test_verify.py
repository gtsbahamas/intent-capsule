#!/usr/bin/env python3
"""
Cold independent-verification tests (stdlib unittest only — zero new deps).

Covers the `verify` verb: it records an evidence-backed PASS/FAIL verdict per `=`
criterion of a DONE capsule into a SEPARATE `verification` record, refuses a
rubber-stamp (must attest every criterion), refuses non-done capsules, enforces the
builder-cannot-grade-its-own-work independence guard, sets verified=false on any
FAIL, and never mutates builder-owned fields (do/in/=/proof/status).

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_verify.py
"""
import os, sys, io, copy, tempfile, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intent_queue as iq  # noqa: E402


def _add(text, source="proj"):
    with redirect_stdout(io.StringIO()):
        return iq.cmd_add(text, source)


def _run(fn, *a, **k):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


# a capsule with 3 acceptance criteria
CAP3 = "@vt\ndo: a verifiable thing\n=: criterion one\n=: criterion two\n=: criterion three\n"


class VerifyCold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name
        self._orig_actor = os.environ.pop("INTENT_ACTOR", None)
        self.assertEqual(_add(CAP3), 0)

    def tearDown(self):
        iq.QUEUE = self._orig
        os.environ.pop("INTENT_ACTOR", None)
        if self._orig_actor is not None:
            os.environ["INTENT_ACTOR"] = self._orig_actor
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    # --- helpers -------------------------------------------------------------
    def _close(self):
        """Drain + done the capsule so it's in the 'done' state verify requires."""
        _run(iq.cmd_done, "vt", ["=[1] a", "=[2] b", "=[3] c"])
        self.assertEqual(iq.load()[0]["status"], "done")

    PASS3 = ["=[1] PASS L4: ran it", "=[2] PASS L3: unit test", "=[3] PASS L6: browser"]

    # --- =[1] rubber-stamp refusal ------------------------------------------
    def test_refuses_short_verdict_set(self):
        self._close()
        rc, out = _run(iq.cmd_verify, "vt", ["=[1] PASS L4: only one"])
        self.assertEqual(rc, 1)
        self.assertIn("not a rubber-stamp", out)
        self.assertIn("[MISSING]", out)
        self.assertNotIn("verification", iq.load()[0])   # nothing written

    def test_accepts_exactly_n_verdicts(self):
        self._close()
        rc, out = _run(iq.cmd_verify, "vt", self.PASS3)
        self.assertEqual(rc, 0)
        self.assertIn("VERIFIED", out)

    # --- =[2] writes a verification record, leaves builder fields untouched --
    def test_writes_verification_without_touching_builder_fields(self):
        self._close()
        before = copy.deepcopy(iq.load()[0])
        _run(iq.cmd_verify, "vt", self.PASS3)
        after = iq.load()[0]
        v = after["verification"]
        self.assertTrue(v["verified"])
        self.assertEqual(len(v["verdicts"]), 3)
        self.assertEqual(v["verdicts"][0],
                         {"criterion": "criterion one", "verdict": "PASS",
                          "level": 4, "evidence": "ran it"})
        self.assertIn("verified_at", v)
        self.assertIn("verified_by", v)
        # builder-owned fields are byte-for-byte unchanged
        for f in ("do", "in", "parsed", "proof", "status", "done"):
            self.assertEqual(after.get(f), before.get(f), f"field {f!r} was mutated")

    # --- =[3] refuses a non-done capsule ------------------------------------
    def test_refuses_pending_capsule(self):
        rc, out = _run(iq.cmd_verify, "vt", self.PASS3)   # still pending (never drained/done)
        self.assertEqual(rc, 1)
        self.assertIn("'pending'", out)
        self.assertNotIn("verification", iq.load()[0])

    def test_refuses_in_progress_capsule(self):
        _run(iq.cmd_progress, "vt", ["=[1] started"])     # -> in_progress
        rc, out = _run(iq.cmd_verify, "vt", self.PASS3)
        self.assertEqual(rc, 1)
        self.assertIn("'in_progress'", out)

    # --- =[4] independence guard --------------------------------------------
    def test_refuses_when_verifier_is_builder(self):
        os.environ["INTENT_ACTOR"] = "alice"
        self._close()                                     # built + done as alice
        rc, out = _run(iq.cmd_verify, "vt", self.PASS3)   # alice tries to verify
        self.assertEqual(rc, 1)
        self.assertIn("cannot grade its own work", out)
        self.assertNotIn("verification", iq.load()[0])

    def test_succeeds_when_verifier_differs_from_builder(self):
        os.environ["INTENT_ACTOR"] = "alice"
        self._close()                                     # built as alice
        os.environ["INTENT_ACTOR"] = "bob"                # fresh actor verifies
        rc, out = _run(iq.cmd_verify, "vt", self.PASS3)
        self.assertEqual(rc, 0)
        self.assertEqual(iq.load()[0]["verification"]["verified_by"], "bob")

    # --- =[5] FAIL drives verified=false ------------------------------------
    def test_any_fail_makes_verified_false(self):
        self._close()
        rc, out = _run(iq.cmd_verify, "vt",
                       ["=[1] PASS L4: ok", "=[2] FAIL L2: returns stub data", "=[3] PASS L3: ok"])
        self.assertEqual(rc, 1)                            # non-zero on failed verification
        self.assertIn("VERIFICATION FAILED", out)
        self.assertFalse(iq.load()[0]["verification"]["verified"])

    def test_all_pass_makes_verified_true(self):
        self._close()
        _run(iq.cmd_verify, "vt", self.PASS3)
        self.assertTrue(iq.load()[0]["verification"]["verified"])

    # --- shape guards --------------------------------------------------------
    def test_malformed_verdict_is_refused(self):
        self._close()
        rc, out = _run(iq.cmd_verify, "vt", ["=[1] maybe: no verdict word"])
        self.assertEqual(rc, 1)
        self.assertIn("PASS|FAIL", out)

    def test_out_of_range_criterion_is_refused(self):
        self._close()
        rc, out = _run(iq.cmd_verify, "vt", ["=[9] PASS L4: nope"])
        self.assertEqual(rc, 1)
        self.assertIn("out of range", out)

    def test_duplicate_criterion_is_refused(self):
        self._close()
        rc, out = _run(iq.cmd_verify, "vt",
                       ["=[1] PASS L4: a", "=[1] PASS L4: b", "=[3] PASS L4: c"])
        self.assertEqual(rc, 1)
        self.assertIn("twice", out)

    def test_verification_survives_round_trip(self):
        self._close()
        _run(iq.cmd_verify, "vt", self.PASS3)
        before = iq.load()
        iq.save(before)
        after = iq.load()
        self.assertEqual(after[0]["verification"], before[0]["verification"])


if __name__ == "__main__":
    unittest.main()
