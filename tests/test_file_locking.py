#!/usr/bin/env python3
"""
File-locking tests (stdlib unittest only — zero new deps).

Covers the cross-process lock around the whole read-modify-write: two concurrent
adds both land (neither row lost); a crashed lock holder does not deadlock the next
call (fcntl auto-release; lockfile stale-break in the fallback); a genuinely held
lock times out cleanly (returns 1 with a message, no traceback).

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_file_locking.py
"""
import os, sys, io, threading, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intent_queue as iq  # noqa: E402


def _add(text, source="p"):
    with redirect_stdout(io.StringIO()):
        return iq.cmd_add(text, source)


class FileLocking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        self._timeout = iq.LOCK_TIMEOUT
        iq.QUEUE = self.tmp.name

    def tearDown(self):
        iq.QUEUE = self._orig
        iq.LOCK_TIMEOUT = self._timeout
        for p in (self.tmp.name, self.tmp.name + ".lock"):
            if os.path.exists(p):
                os.unlink(p)

    def test_concurrent_adds_both_land(self):
        # =[1]: two adds fired concurrently both land — neither row is lost
        def add(i):
            iq.cmd_add(f"@c{i}\ndo: x\n=: d\n", "p")
        threads = [threading.Thread(target=add, args=(i,)) for i in range(2)]
        with redirect_stdout(io.StringIO()):
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        ids = sorted(r["id"] for r in iq.load())
        self.assertEqual(ids, ["c0", "c1"])

    def test_stale_lockfile_does_not_deadlock_fcntl(self):
        # =[2] fcntl path: a leftover lockfile (not flock-held) must not block the next call
        open(iq.QUEUE + ".lock", "w").close()
        self.assertEqual(_add("@a\ndo: x\n=: d\n"), 0)
        self.assertIn("a", [r["id"] for r in iq.load()])

    def test_stale_lockfile_reclaimed_in_fallback(self):
        # =[2] fallback path (fcntl unavailable): a stale lockfile is reclaimed via stale-break
        with mock.patch.object(iq, "fcntl", None), mock.patch.object(iq, "LOCK_STALE", 0):
            open(iq.QUEUE + ".lock", "w").close()
            self.assertEqual(_add("@b\ndo: x\n=: d\n"), 0)
        self.assertIn("b", [r["id"] for r in iq.load()])

    def test_held_lock_times_out_cleanly(self):
        # a genuinely held lock -> QueueLocked -> decorator returns 1 + message (no traceback)
        iq.LOCK_TIMEOUT = 0.2
        with iq._queue_lock():
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = iq.cmd_add("@z\ndo: x\n=: d\n", "p")
            self.assertEqual(rc, 1)
            self.assertIn("locked by another process", buf.getvalue())
        # lock released after the with-block: a subsequent add succeeds
        self.assertEqual(_add("@after\ndo: x\n=: d\n"), 0)


if __name__ == "__main__":
    unittest.main()
