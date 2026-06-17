#!/usr/bin/env python3
"""
Atomic-save tests (stdlib unittest only — zero new deps).

Covers the crash-safety contract of save(): a crash between writing the temp file
and the rename leaves the OLD queue fully intact (never half-written), output is
byte-identical to the previous direct write, the temp file is cleaned up on
failure, and the queue directory is created if missing.

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_atomic_save.py
"""
import os, sys, glob, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intent_queue as iq  # noqa: E402


def _items():
    return [
        {"id": "a", "status": "pending", "do": "first"},
        {"id": "b", "status": "done", "do": "second", "nested": {"x": [1, 2]}},
    ]


def _expected_bytes(items):
    """The exact serialization the pre-atomic save produced."""
    return "".join(iq.json.dumps(it) + "\n" for it in items).encode()


def _leftover_tmps(path):
    d = os.path.dirname(path) or "."
    return glob.glob(os.path.join(d, ".intent-queue.*.tmp"))


class AtomicSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name

    def tearDown(self):
        iq.QUEUE = self._orig
        for f in _leftover_tmps(self.tmp.name):
            os.unlink(f)
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_output_is_byte_identical_to_direct_write(self):
        # =[2]: a normal write produces byte-identical JSONL to the old direct write
        items = _items()
        iq.save(items)
        with open(iq.QUEUE, "rb") as f:
            self.assertEqual(f.read(), _expected_bytes(items))

    def test_round_trips_through_load(self):
        items = _items()
        iq.save(items)
        self.assertEqual(iq.load(), items)

    def test_crash_at_replace_leaves_old_queue_intact(self):
        # =[1]: killing the process between tmp-write and replace leaves the OLD
        # queue fully intact, never half-written.
        original = _items()
        iq.save(original)
        with open(iq.QUEUE, "rb") as f:
            before = f.read()

        new_items = original + [{"id": "c", "status": "pending", "do": "third"}]
        with mock.patch("intent_queue.os.replace",
                        side_effect=RuntimeError("simulated crash at rename")):
            with self.assertRaises(RuntimeError):
                iq.save(new_items)

        # the real queue must be untouched (old content, not truncated/partial)
        with open(iq.QUEUE, "rb") as f:
            self.assertEqual(f.read(), before)
        # and the temp file must not be left behind
        self.assertEqual(_leftover_tmps(iq.QUEUE), [])

    def test_creates_missing_queue_directory(self):
        # ?: the queue dir is created before the temp file is written
        d = tempfile.mkdtemp()
        nested = os.path.join(d, "sub", "dir", "queue.jsonl")
        self._orig2 = iq.QUEUE
        iq.QUEUE = nested
        try:
            iq.save(_items())
            self.assertTrue(os.path.exists(nested))
            self.assertEqual(iq.load(), _items())
        finally:
            iq.QUEUE = self._orig2


if __name__ == "__main__":
    unittest.main()
