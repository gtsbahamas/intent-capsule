#!/usr/bin/env python3
"""
Export/import tests (stdlib unittest only — zero new deps).

Covers the portable backup/migration path: export then import into an empty queue
reproduces the rows; importing a dump whose ids already exist unfinished does NOT
clobber them (skip+warn) unless --force; a round-trip across a different
INTENT_QUEUE path works (migration); a newer-schema dump is refused.

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_export_import.py
"""
import os, sys, io, json, tempfile, unittest
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


def _norm(row):
    return (row["id"], row["status"], json.dumps(row["parsed"], sort_keys=True))


class ExportImport(unittest.TestCase):
    def setUp(self):
        self.qa = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False); self.qa.close()
        self.qb = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False); self.qb.close()
        self.dump = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False); self.dump.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.qa.name

    def tearDown(self):
        iq.QUEUE = self._orig
        for p in (self.qa.name, self.qb.name, self.dump.name):
            if os.path.exists(p):
                os.unlink(p)

    def test_export_then_import_into_empty_reproduces_rows(self):
        # =[1]: export -> import into empty queue reproduces rows (ids, status, parsed)
        _add("@a\ndo: alpha\n=: d1\n")
        _add("@b\ndo: beta\n=: d2\n")
        original = iq.load()
        _run(iq.cmd_export, self.dump.name)

        iq.QUEUE = self.qb.name                      # empty target
        self.assertEqual(iq.load(), [])
        rc, out = _run(iq.cmd_import, self.dump.name)
        self.assertEqual(rc, 0)
        self.assertIn("2 added", out)
        imported = iq.load()
        self.assertEqual(sorted(_norm(r) for r in imported),
                         sorted(_norm(r) for r in original))

    def test_import_does_not_clobber_existing_unfinished(self):
        # =[2]: importing a dump whose ids exist unfinished does NOT overwrite them
        _add("@a\ndo: original alpha\n=: d1\n")
        _run(iq.cmd_export, self.dump.name)
        # mutate the live row so we can detect a clobber
        rows = iq.load(); rows[0]["parsed"]["do"] = "LOCAL EDIT"; iq.save(rows)

        rc, out = _run(iq.cmd_import, self.dump.name)   # no --force
        self.assertEqual(rc, 0)
        self.assertIn("skipped", out)
        self.assertEqual(iq.load()[0]["parsed"]["do"], "LOCAL EDIT")  # untouched

        # --force overwrites
        rc2, out2 = _run(iq.cmd_import, self.dump.name, force=True)
        self.assertEqual(rc2, 0)
        self.assertIn("overwritten", out2)
        self.assertEqual(iq.load()[0]["parsed"]["do"], "original alpha")

    def test_round_trip_across_different_queue_path(self):
        # =[3]: migration across a different INTENT_QUEUE path
        _add("@mig\ndo: migrate me\n=: d1\n")
        _run(iq.cmd_export, self.dump.name)
        iq.QUEUE = self.qb.name
        _run(iq.cmd_import, self.dump.name)
        ids = [r["id"] for r in iq.load()]
        self.assertEqual(ids, ["mig"])

    def test_newer_schema_dump_is_refused(self):
        bad = {"schema_version": iq.SCHEMA_VERSION + 1, "rows": [{"id": "x", "status": "pending",
               "parsed": {"id": "x", "do": "y", "=": ["d"]}}]}
        with open(self.dump.name, "w") as f:
            json.dump(bad, f)
        rc, out = _run(iq.cmd_import, self.dump.name)
        self.assertEqual(rc, 1)
        self.assertIn("newer than this tool", out)

    def test_garbage_import_is_refused(self):
        with open(self.dump.name, "w") as f:
            f.write("not json at all")
        rc, out = _run(iq.cmd_import, self.dump.name)
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", out)


if __name__ == "__main__":
    unittest.main()
