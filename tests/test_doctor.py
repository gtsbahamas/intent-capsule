#!/usr/bin/env python3
"""
Doctor-command tests (stdlib unittest only — zero new deps).

Covers the read-only diagnostic: it reports python3 / queue path / plugin root /
hook lines; a healthy install exits 0 with every critical line OK; a broken
(unwritable) queue path reports FAIL and exits non-zero; doctor never mutates the
queue.

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_doctor.py
"""
import os, sys, io, tempfile, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intent_queue as iq  # noqa: E402


def _run():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = iq.cmd_doctor()
    return rc, buf.getvalue()


class Doctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name

    def tearDown(self):
        iq.QUEUE = self._orig
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_reports_all_four_checks(self):
        # =[1]: lists python3, queue path, plugin root, hook surfacing
        _, out = _run()
        self.assertIn("python3", out)
        self.assertIn("queue path", out)
        self.assertIn("plugin root", out)
        self.assertIn("surfacing hook", out)
        self.assertIn(iq.QUEUE, out)            # actual resolved path, not a boolean

    def test_healthy_install_exits_zero(self):
        # =[2] (healthy half): writable queue dir + repo plugin root + hooks.json -> OK, exit 0
        rc, out = _run()
        self.assertEqual(rc, 0)
        self.assertIn("doctor: OK", out)
        self.assertNotIn("[FAIL]", out)

    def test_broken_queue_path_fails(self):
        # =[2] (broken half): unwritable/missing queue dir -> FAIL + nonzero exit
        iq.QUEUE = "/no/such/directory/queue.jsonl"
        rc, out = _run()
        self.assertEqual(rc, 1)
        self.assertIn("[FAIL]", out)
        self.assertIn("doctor: FAIL", out)

    def test_doctor_is_read_only(self):
        # constraint: doctor never mutates the queue
        with open(iq.QUEUE, "w") as f:
            f.write('{"id":"x","status":"pending"}\n')
        with open(iq.QUEUE, "rb") as f:
            before = f.read()
        _run()
        with open(iq.QUEUE, "rb") as f:
            self.assertEqual(f.read(), before)


if __name__ == "__main__":
    unittest.main()
