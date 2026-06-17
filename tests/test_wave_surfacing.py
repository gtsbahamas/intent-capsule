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
import os, sys, io, tempfile, unittest
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

    def test_three_node_cycle_broken_by_done_node(self):
        items = [_cap("a", on="b"), _cap("b", on="c"), _cap("c", on="a", status="done")]
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

    def test_blocked_cycle_reported(self):
        a = _cap("a", on="b"); b = _cap("b", on="a")
        self._seed([a, b])
        out = self._next()
        self.assertIn("dependency cycle", out)
        self.assertNotIn("# intent capsule", out)

    def test_dep_gating_is_cross_project(self):
        a = _cap("a", on="b"); a["source"] = "projX"
        b = _cap("b");         b["source"] = "projY"
        self._seed([a, b])
        buf = io.StringIO()
        with redirect_stdout(buf):
            iq.cmd_next(project="projX")
        out = buf.getvalue()
        self.assertIn("all blocked", out)
        self.assertIn("waiting on: b", out)
        self.assertNotIn("intent capsule 'a'", out)


class PickupSplit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name

    def tearDown(self):
        iq.QUEUE = self._orig
        os.unlink(self.tmp.name)

    def _pickup(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            iq.cmd_pickup(show_all=True)
        return buf.getvalue()

    def test_ready_and_blocked_are_partitioned(self):
        iq.save([_cap("a", on="b"), _cap("b")])
        out = self._pickup()
        self.assertIn("Ready now", out)
        self.assertIn("Blocked", out)
        # b is ready, a is blocked waiting on b  ((?s) so . spans newlines)
        self.assertRegex(out, r"(?s)Ready now.*\*\*b\*\*")
        self.assertRegex(out, r"(?s)Blocked.*\*\*a\*\*")
        self.assertIn("waiting on b", out)

    def test_typo_dep_surfaced_only_alongside_a_real_dep(self):
        # b is a real queued id; ghost is a typo -> ghost surfaces as a note
        iq.save([_cap("a", on="b ghost"), _cap("b")])
        self.assertIn("unknown id 'ghost'", self._pickup())

    def test_pure_free_text_on_emits_no_notes(self):
        # no token matches a queued id -> treated as prose, silent (no per-word spam)
        iq.save([_cap("solo", on="the auth module and csv exporter")])
        self.assertNotIn("unknown id", self._pickup())

    def test_cycle_reported(self):
        iq.save([_cap("a", on="b"), _cap("b", on="a")])
        out = self._pickup()
        self.assertIn("dependency cycle", out)

    def test_all_blocked_shows_blocked_section_without_cta(self):
        iq.save([_cap("a", on="b"), _cap("b", on="a")])  # mutual block, no ready
        out = self._pickup()
        self.assertNotIn("Ready now", out)
        self.assertIn("Blocked", out)
        self.assertNotIn("Run `intent-queue next`", out)


class BackwardCompat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name

    def tearDown(self):
        iq.QUEUE = self._orig
        os.unlink(self.tmp.name)

    def test_free_text_on_with_no_matching_ids_is_served_unchanged(self):
        # a pre-existing capsule whose on: names features, not queued ids
        a = _cap("only", on="the auth module and the csv exporter")
        iq.save([a])
        buf = io.StringIO()
        with redirect_stdout(buf):
            iq.cmd_next(show_all=True)
        self.assertIn("intent capsule 'only'", buf.getvalue())
        self.assertEqual(iq._select(iq.load(), "only")["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
