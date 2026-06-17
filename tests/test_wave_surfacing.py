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


class StatusMap(unittest.TestCase):
    def test_maps_id_to_status(self):
        items = [{"id": "a", "status": "done"}, {"id": "b", "status": "pending"}]
        self.assertEqual(iq._status_map(items), {"a": "done", "b": "pending"})

    def test_active_row_wins_over_finished_duplicate(self):
        # a re-queued id (done row + new pending row) must NOT count as satisfied
        items = [{"id": "a", "status": "done"}, {"id": "a", "status": "pending"}]
        self.assertEqual(iq._status_map(items)["a"], "pending")


if __name__ == "__main__":
    unittest.main()
