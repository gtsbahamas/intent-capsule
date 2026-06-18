#!/usr/bin/env python3
"""
Partial-execution-state tests (stdlib unittest only — zero new deps).

Covers the additive `progress` verb: a capsule can record M<N attested criteria
while staying in_progress; list and pickup surface the partial state; `done` still
refuses to close unless ALL N criteria are attested; partial attestations survive a
load()/save() round-trip.

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_partial_execution.py
"""
import os, sys, io, tempfile, unittest
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
CAP3 = "@multi\ndo: a multi-step thing\n=: criterion one\n=: criterion two\n=: criterion three\n"


class PartialExecution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name
        self.assertEqual(_add(CAP3), 0)

    def tearDown(self):
        iq.QUEUE = self._orig
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_records_subset_and_stays_in_progress(self):
        # =[1]: record M<N criteria; row stores which are met; status stays in_progress
        rc, _ = _run(iq.cmd_progress, "multi", ["=[1] did one", "=[3] did three"])
        self.assertEqual(rc, 0)
        row = iq.load()[0]
        self.assertEqual(row["status"], "in_progress")     # not done
        self.assertEqual(set(row["progress"].keys()), {"1", "3"})
        self.assertEqual(row["progress"]["1"]["criterion"], "criterion one")
        self.assertEqual(row["progress"]["3"]["attestation"], "did three")

    def test_progress_accumulates_across_calls(self):
        _run(iq.cmd_progress, "multi", ["=[1] one"])
        _run(iq.cmd_progress, "multi", ["=[2] two"])
        self.assertEqual(set(iq.load()[0]["progress"].keys()), {"1", "2"})

    def test_list_and_pickup_show_partial(self):
        # =[2]: list and pickup surface "M/N criteria met"
        _run(iq.cmd_progress, "multi", ["=[1] one", "=[2] two"])
        _, out_list = _run(iq.cmd_list, "active")
        self.assertIn("2/3 criteria met", out_list)
        _, out_pickup = _run(iq.cmd_pickup, show_all=True)
        self.assertIn("2/3 criteria met", out_pickup)
        self.assertIn("multi", out_pickup)

    def test_done_still_refuses_without_all_criteria(self):
        # =[3]: done refuses unless ALL N attested, even after partial progress
        _run(iq.cmd_progress, "multi", ["=[1] one", "=[2] two"])
        rc, out = _run(iq.cmd_done, "multi", ["=[1] only one proof"])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", out)
        self.assertEqual(iq.load()[0]["status"], "in_progress")   # not closed
        # and it DOES close when all three are attested
        rc2, _ = _run(iq.cmd_done, "multi", ["=[1] a", "=[2] b", "=[3] c"])
        self.assertEqual(rc2, 0)
        self.assertEqual(iq.load()[0]["status"], "done")

    def test_partial_survives_round_trip(self):
        # =[4]: partial attestations survive a load()/save() round-trip intact
        _run(iq.cmd_progress, "multi", ["=[2] middle"])
        before = iq.load()
        iq.save(before)
        after = iq.load()
        self.assertEqual(after[0]["progress"], before[0]["progress"])
        self.assertEqual(after[0]["progress"]["2"]["criterion"], "criterion two")

    def test_bare_proof_without_index_is_refused(self):
        rc, out = _run(iq.cmd_progress, "multi", ["did something but no index marker"])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", out)

    def test_out_of_range_criterion_is_refused(self):
        rc, out = _run(iq.cmd_progress, "multi", ["=[9] nonexistent criterion"])
        self.assertEqual(rc, 1)
        self.assertIn("out of range", out)


if __name__ == "__main__":
    unittest.main()
