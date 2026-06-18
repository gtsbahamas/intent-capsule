#!/usr/bin/env python3
"""
Row-schema-v1 tests (stdlib unittest only — zero new deps).

Covers the stamped row metadata (schema_version, updated_at, completed_by,
source_path_hash): a fresh add carries all four; a legacy row back-fills on load
and re-saves without error; `done` stamps completed_by and bumps updated_at.

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_row_schema.py
"""
import os, sys, io, json, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intent_queue as iq  # noqa: E402


def _add(text, source="proj"):
    with redirect_stdout(io.StringIO()):
        return iq.cmd_add(text, source)


class RowSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name

    def tearDown(self):
        iq.QUEUE = self._orig
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_fresh_row_has_all_schema_fields(self):
        # =[1]: a freshly added row has schema_version, updated_at, completed_by(null), source_path_hash
        self.assertEqual(_add("@x\ndo: a thing\n=: it is done\n"), 0)
        row = iq.load()[0]
        self.assertEqual(row["schema_version"], iq.SCHEMA_VERSION)
        self.assertTrue(row["updated_at"])
        self.assertIsNone(row["completed_by"])
        self.assertTrue(row["source_path_hash"])  # hash of the current project path

    def test_legacy_row_backfills_and_resaves(self):
        # =[2]: an old row (no new fields) loads, back-fills, and re-saves without error
        legacy = {"id": "old", "status": "pending", "created": "2026-01-01T00:00:00+00:00",
                  "source": "p", "capsule": "", "parsed": {"id": "old", "do": "x", "=": ["d"]},
                  "started": None, "done": None, "proof": None}
        with open(iq.QUEUE, "w") as f:
            f.write(json.dumps(legacy) + "\n")
        r = iq.load()[0]
        self.assertEqual(r["schema_version"], 0)            # 0 == pre-v1, back-filled
        self.assertIsNone(r["completed_by"])
        self.assertIsNone(r["source_path_hash"])
        self.assertEqual(r["updated_at"], legacy["created"])  # falls back to created
        iq.save(iq.load())                                   # re-save must not raise

    def test_done_stamps_completed_by_and_bumps_updated_at(self):
        # =[3]: `done` stamps completed_by and bumps updated_at
        self.assertEqual(_add("@y\ndo: a\n=: c1\n"), 0)
        rows = iq.load()
        rows[0]["updated_at"] = "2000-01-01T00:00:00+00:00"  # force an old stamp
        iq.save(rows)
        with mock.patch("intent_queue._actor", return_value="tester"):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(iq.cmd_done("y", ["=[1] met by the test"]), 0)
        done = iq.load()[0]
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["completed_by"], "tester")
        self.assertNotEqual(done["updated_at"], "2000-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
