#!/usr/bin/env python3
"""
Project-local-mode tests (stdlib unittest only — zero new deps).

Covers marker-gated queue resolution: a repo with a .intent-capsule/ dir resolves
to <root>/.intent-capsule/queue.jsonl (found by walking up); repos WITHOUT the
marker keep the global default; INTENT_QUEUE overrides and INTENT_QUEUE_GLOBAL
forces global; add writes the project-local file and different repos see different
queues; the CLI/hook (pickup) surfaces the project-local queue; and existing global
capsules are reported for migration, never auto-moved.

Run:  python3 -m unittest discover -s tests
  or: python3 tests/test_project_local.py
"""
import os, sys, io, json, shutil, contextlib, subprocess, tempfile, unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intent_queue as iq  # noqa: E402
IQ = os.path.join(ROOT, "intent_queue.py")


@contextlib.contextmanager
def env(**kw):
    saved = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        yield
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class ResolvePrecedence(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_no_marker_resolves_global(self):
        with env(INTENT_QUEUE=None, INTENT_QUEUE_GLOBAL=None, CLAUDE_PROJECT_DIR=self.d):
            self.assertEqual(iq.resolve_queue(), iq.GLOBAL_QUEUE)

    def test_marker_resolves_project_local(self):
        os.mkdir(os.path.join(self.d, ".intent-capsule"))
        with env(INTENT_QUEUE=None, INTENT_QUEUE_GLOBAL=None, CLAUDE_PROJECT_DIR=self.d):
            self.assertEqual(iq.resolve_queue(),
                             os.path.join(self.d, ".intent-capsule", "queue.jsonl"))

    def test_marker_found_walking_up(self):
        os.mkdir(os.path.join(self.d, ".intent-capsule"))
        sub = os.path.join(self.d, "a", "b"); os.makedirs(sub)
        with env(INTENT_QUEUE=None, INTENT_QUEUE_GLOBAL=None, CLAUDE_PROJECT_DIR=sub):
            self.assertEqual(iq.resolve_queue(),
                             os.path.join(self.d, ".intent-capsule", "queue.jsonl"))

    def test_intent_queue_env_overrides_even_with_marker(self):
        os.mkdir(os.path.join(self.d, ".intent-capsule"))
        with env(INTENT_QUEUE="/tmp/explicit-q.jsonl", INTENT_QUEUE_GLOBAL=None,
                 CLAUDE_PROJECT_DIR=self.d):
            self.assertEqual(iq.resolve_queue(), os.path.abspath("/tmp/explicit-q.jsonl"))

    def test_global_flag_forces_global_even_with_marker(self):
        os.mkdir(os.path.join(self.d, ".intent-capsule"))
        with env(INTENT_QUEUE=None, INTENT_QUEUE_GLOBAL="1", CLAUDE_PROJECT_DIR=self.d):
            self.assertEqual(iq.resolve_queue(), iq.GLOBAL_QUEUE)


class AddWritesProjectLocal(unittest.TestCase):
    def setUp(self):
        self.a = tempfile.mkdtemp(); os.mkdir(os.path.join(self.a, ".intent-capsule"))
        self.b = tempfile.mkdtemp(); os.mkdir(os.path.join(self.b, ".intent-capsule"))
        self._orig = iq.QUEUE

    def tearDown(self):
        iq.QUEUE = self._orig
        shutil.rmtree(self.a, ignore_errors=True)
        shutil.rmtree(self.b, ignore_errors=True)

    def test_two_repos_resolve_to_different_local_queues(self):
        # =[1]: a different project dir sees a different queue
        with env(INTENT_QUEUE=None, INTENT_QUEUE_GLOBAL=None, CLAUDE_PROJECT_DIR=self.a):
            qa = iq.resolve_queue()
        with env(INTENT_QUEUE=None, INTENT_QUEUE_GLOBAL=None, CLAUDE_PROJECT_DIR=self.b):
            qb = iq.resolve_queue()
        self.assertNotEqual(qa, qb)
        self.assertTrue(qa.endswith(os.path.join(".intent-capsule", "queue.jsonl")))

    def test_add_writes_the_project_local_file(self):
        # =[1]: add writes .intent-capsule/queue.jsonl
        iq.QUEUE = os.path.join(self.a, ".intent-capsule", "queue.jsonl")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(iq.cmd_add("@loc\ndo: x\n=: d\n", "proj"), 0)
        self.assertTrue(os.path.exists(iq.QUEUE))
        self.assertEqual([r["id"] for r in iq.load()], ["loc"])


class PickupSurfacesProjectLocalViaCLI(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.d, ".intent-capsule"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_pickup_surfaces_project_local_queue(self):
        # =[3]: the surfacing hook (which calls `intent-queue pickup`) resolves the
        # project-local path. Seed a local queue, run the real CLI, expect the capsule.
        proj = os.path.basename(self.d)
        row = {"id": "localcap", "status": "pending", "created": "2026-06-17T00:00:00+00:00",
               "source": proj, "capsule": "", "parsed": {"id": "localcap", "do": "z", "=": ["d"]},
               "started": None, "done": None, "proof": None}
        qpath = os.path.join(self.d, ".intent-capsule", "queue.jsonl")
        with open(qpath, "w") as f:
            f.write(json.dumps(row) + "\n")
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("INTENT_QUEUE", "INTENT_QUEUE_GLOBAL")}
        clean["CLAUDE_PROJECT_DIR"] = self.d
        r = subprocess.run([sys.executable, IQ, "pickup"], capture_output=True, text=True, env=clean)
        self.assertEqual(r.returncode, 0)
        self.assertIn("localcap", r.stdout)


class MigrationNotice(unittest.TestCase):
    def setUp(self):
        self.proj_dir = tempfile.mkdtemp()
        self.local = os.path.join(self.proj_dir, ".intent-capsule", "queue.jsonl")
        os.makedirs(os.path.dirname(self.local))
        self.gq = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False); self.gq.close()
        self._orig_q, self._orig_g = iq.QUEUE, iq.GLOBAL_QUEUE

    def tearDown(self):
        iq.QUEUE, iq.GLOBAL_QUEUE = self._orig_q, self._orig_g
        shutil.rmtree(self.proj_dir, ignore_errors=True)
        if os.path.exists(self.gq.name):
            os.unlink(self.gq.name)

    def test_global_capsules_reported_not_migrated(self):
        # constraint: do NOT silently migrate; detect + tell the user
        proj = os.path.basename(self.proj_dir)
        grow = {"id": "stuck", "status": "pending", "created": "2026-06-17T00:00:00+00:00",
                "source": proj, "capsule": "", "parsed": {"id": "stuck", "do": "x", "=": ["d"]},
                "started": None, "done": None, "proof": None}
        with open(self.gq.name, "w") as f:
            f.write(json.dumps(grow) + "\n")
        iq.GLOBAL_QUEUE = self.gq.name
        iq.QUEUE = self.local            # resolved to project-local (differs from global)
        with env(CLAUDE_PROJECT_DIR=self.proj_dir):
            buf = io.StringIO()
            with redirect_stdout(buf):
                iq.cmd_pickup()
            out = buf.getvalue()
        self.assertIn("GLOBAL queue", out)
        self.assertIn("export", out)
        # and the global capsule is untouched (not moved)
        with open(self.gq.name) as f:
            self.assertIn("stuck", f.read())


if __name__ == "__main__":
    unittest.main()
