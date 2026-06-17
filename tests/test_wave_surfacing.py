#!/usr/bin/env python3
"""
Wave-surfacing tests (stdlib unittest only — zero new deps).

Covers the four pure helpers (_dep_tokens, _status_map, _classify, _find_cycles)
and the gating behavior wired into `next` and `pickup`: a capsule whose `on:`
names an unfinished queued capsule is blocked; finishing the dep unblocks it;
dropped deps and dependency cycles are surfaced, never silently hidden; and
`on:` tokens matching no queued id stay non-gating (backward compatibility).

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_wave_surfacing.py
"""
import os, sys, io, json, tempfile, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intent_queue as iq  # noqa: E402


class DepTokens(unittest.TestCase):
    def test_splits_on_commas_and_whitespace(self):
        self.assertEqual(iq._dep_tokens("a, b  c,d"), ["a", "b", "c", "d"])

    def test_empty_and_none_yield_empty_list(self):
        self.assertEqual(iq._dep_tokens(""), [])
        self.assertEqual(iq._dep_tokens(None), [])

    def test_is_case_sensitive_and_keeps_hyphenated_ids(self):
        self.assertEqual(iq._dep_tokens("Wiki-Ingest auth-flow"), ["Wiki-Ingest", "auth-flow"])


def _cap(id_, on="", do="x", accept=("done",), status="pending"):
    """Build a queue item shaped like cmd_add produces."""
    return {"id": id_, "status": status, "created": "2026-06-17T00:00:00+00:00",
            "source": "test", "capsule": "", "started": None, "done": None, "proof": None,
            "parsed": {"id": id_, "do": do, "on": on, "=": list(accept)}}


class StatusMap(unittest.TestCase):
    def test_maps_id_to_status(self):
        items = [{"id": "a", "status": "done"}, {"id": "b", "status": "pending"}]
        self.assertEqual(iq._status_map(items), {"a": "done", "b": "pending"})

    def test_active_row_wins_over_finished_duplicate(self):
        # a re-queued id (done row + new pending row) must NOT count as satisfied
        items = [{"id": "a", "status": "done"}, {"id": "a", "status": "pending"}]
        self.assertEqual(iq._status_map(items)["a"], "pending")


def _has_cycle(cycles, ids):
    want = tuple(sorted(ids))
    return any(tuple(sorted(c)) == want for c in cycles)


class Classify(unittest.TestCase):
    def test_no_deps_is_ready(self):
        smap = iq._status_map([_cap("a")])
        self.assertTrue(iq._classify(_cap("a"), smap)["ready"])

    def test_unfinished_dep_blocks(self):
        items = [_cap("a", on="b"), _cap("b")]
        c = iq._classify(items[0], iq._status_map(items))
        self.assertFalse(c["ready"])
        self.assertEqual(c["waiting"], ["b"])

    def test_done_dep_is_satisfied(self):
        items = [_cap("a", on="b"), _cap("b", status="done")]
        self.assertTrue(iq._classify(items[0], iq._status_map(items))["ready"])

    def test_dropped_dep_is_dead(self):
        items = [_cap("a", on="b"), _cap("b", status="dropped")]
        c = iq._classify(items[0], iq._status_map(items))
        self.assertFalse(c["ready"])
        self.assertEqual(c["dead"], ["b"])

    def test_unknown_token_is_non_gating(self):
        items = [_cap("a", on="ghost")]
        c = iq._classify(items[0], iq._status_map(items))
        self.assertTrue(c["ready"])
        self.assertEqual(c["unknown"], ["ghost"])


class FindCycles(unittest.TestCase):
    def test_two_node_cycle_detected(self):
        items = [_cap("a", on="b"), _cap("b", on="a")]
        self.assertTrue(_has_cycle(iq._find_cycles(items), ["a", "b"]))

    def test_self_loop_detected(self):
        items = [_cap("a", on="a")]
        self.assertTrue(_has_cycle(iq._find_cycles(items), ["a"]))

    def test_three_node_cycle_detected(self):
        items = [_cap("a", on="b"), _cap("b", on="c"), _cap("c", on="a")]
        self.assertTrue(_has_cycle(iq._find_cycles(items), ["a", "b", "c"]))

    def test_acyclic_chain_has_no_cycle(self):
        items = [_cap("a", on="b"), _cap("b", on="c"), _cap("c")]
        self.assertEqual(iq._find_cycles(items), [])

    def test_finished_nodes_excluded_from_graph(self):
        # b is done -> edge a->b cannot deadlock, even if b nominally points back
        items = [_cap("a", on="b"), _cap("b", on="a", status="done")]
        self.assertEqual(iq._find_cycles(items), [])


class NextGating(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name

    def tearDown(self):
        iq.QUEUE = self._orig
        os.unlink(self.tmp.name)

    def _seed(self, items):
        iq.save(items)

    def _next(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            iq.cmd_next(show_all=True)        # show_all avoids project-scope filtering in tests
        return buf.getvalue()

    def test_serves_dep_before_dependent(self):
        # a depends on b; both pending -> next must serve b, not a
        a = _cap("a", on="b"); a["created"] = "2026-06-17T00:00:00+00:00"
        b = _cap("b");         b["created"] = "2026-06-17T01:00:00+00:00"  # b newer
        self._seed([a, b])
        out = self._next()
        self.assertIn("intent capsule 'b'", out)
        self.assertNotIn("intent capsule 'a'", out)

    def test_dependent_served_after_dep_done(self):
        a = _cap("a", on="b"); b = _cap("b", status="done")
        self._seed([a, b])
        self.assertIn("intent capsule 'a'", self._next())

    def test_all_blocked_reports_and_serves_nothing(self):
        a = _cap("a", on="b"); b = _cap("b", status="in_progress")
        self._seed([a, b])
        out = self._next()
        self.assertIn("all blocked", out)
        self.assertIn("waiting on: b", out)
        self.assertNotIn("# intent capsule", out)
        # status untouched: a is still pending
        self.assertEqual(iq._select(iq.load(), "a")["status"], "pending")


if __name__ == "__main__":
    unittest.main()
