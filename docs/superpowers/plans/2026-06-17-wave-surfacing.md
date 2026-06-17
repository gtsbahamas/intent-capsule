# Wave Surfacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `on:` dependency field gate capsule surfacing so the flat intent-queue executes like a wave: a capsule stays hidden until its prerequisite capsules are `done`.

**Architecture:** Four pure helper functions compute dependency state from the queue (no I/O, no persistence). `cmd_next` serves the oldest *ready* capsule; `cmd_pickup` splits ready-now vs blocked. Gating is recomputed on every call from the existing `parsed["on"]` + `status` fields — no jsonl schema change, no migration. Spec: `docs/superpowers/specs/2026-06-17-wave-surfacing-design.md`.

**Tech Stack:** Python 3 stdlib only (`re`, `unittest`). Single module `intent_queue.py`. Tests via `python3 -m unittest discover -s tests`.

---

## File Structure

- **Modify** `intent_queue.py` — add four helpers (`_dep_tokens`, `_status_map`, `_classify`, `_find_cycles`) near the other private helpers (after `_age_min`, before `parse_capsule`); rewire the `mine` branch of `cmd_next` and the `mine` block of `cmd_pickup`.
- **Create** `tests/test_wave_surfacing.py` — unit tests for the helpers + integration tests for `next`/`pickup` against a temp queue.

Each helper is pure and independently testable. The command rewires consume them.

---

### Task 1: `_dep_tokens` — tokenize the `on:` string

**Files:**
- Modify: `intent_queue.py` (add after `_age_min`, ~line 53)
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test**

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.DepTokens -v`
Expected: FAIL with `AttributeError: module 'intent_queue' has no attribute '_dep_tokens'`

- [ ] **Step 3: Write minimal implementation**

Add to `intent_queue.py` immediately after the `_age_min` function (after line 53):

```python
def _dep_tokens(on_str):
    """Tokenize an `on:` string into candidate dependency tokens.

    Splits on commas and whitespace. Ids are case-sensitive (no lowercasing),
    so hyphenated capsule ids survive intact. Embedded prose is harmless: only
    tokens that later match a queued id gate anything (see _classify)."""
    if not on_str:
        return []
    return [t for t in re.split(r"[,\s]+", on_str.strip()) if t]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.DepTokens -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(wave): _dep_tokens — tokenize on: dependency strings"
```

---

### Task 2: `_status_map` — id→status over the whole queue

**Files:**
- Modify: `intent_queue.py` (add after `_dep_tokens`)
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test**

Append this class to `tests/test_wave_surfacing.py` (before the `if __name__` block):

```python
class StatusMap(unittest.TestCase):
    def test_maps_id_to_status(self):
        items = [{"id": "a", "status": "done"}, {"id": "b", "status": "pending"}]
        self.assertEqual(iq._status_map(items), {"a": "done", "b": "pending"})

    def test_active_row_wins_over_finished_duplicate(self):
        # a re-queued id (done row + new pending row) must NOT count as satisfied
        items = [{"id": "a", "status": "done"}, {"id": "a", "status": "pending"}]
        self.assertEqual(iq._status_map(items)["a"], "pending")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.StatusMap -v`
Expected: FAIL with `AttributeError: module 'intent_queue' has no attribute '_status_map'`

- [ ] **Step 3: Write minimal implementation**

Add to `intent_queue.py` after `_dep_tokens`:

```python
def _status_map(items):
    """id -> status over the entire queue. If an id appears more than once
    (a finished row plus a re-queued active one), prefer the ACTIVE status so a
    dependency is not treated as satisfied by a stale `done` row."""
    m = {}
    for it in items:
        id_, st = it["id"], it["status"]
        if id_ not in m or (m[id_] in ("done", "dropped") and st in ("pending", "in_progress")):
            m[id_] = st
    return m
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.StatusMap -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(wave): _status_map — id->status, active row wins"
```

---

### Task 3: `_classify` — per-capsule blocker analysis

**Files:**
- Modify: `intent_queue.py` (add after `_status_map`)
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test**

Append this class to `tests/test_wave_surfacing.py`:

```python
def _cap(id_, on="", do="x", accept=("done",), status="pending"):
    """Build a queue item shaped like cmd_add produces."""
    return {"id": id_, "status": status, "created": "2026-06-17T00:00:00+00:00",
            "source": "test", "capsule": "", "started": None, "done": None, "proof": None,
            "parsed": {"id": id_, "do": do, "on": on, "=": list(accept)}}


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.Classify -v`
Expected: FAIL with `AttributeError: module 'intent_queue' has no attribute '_classify'`

- [ ] **Step 3: Write minimal implementation**

Add to `intent_queue.py` after `_status_map`:

```python
def _classify(item, status_map):
    """Blocker analysis for one capsule against the queue's id->status map.

    Returns {ready, waiting, dead, unknown}:
      waiting - dep ids that exist but aren't done (pending/in_progress)
      dead    - dep ids whose capsule was dropped (unsatisfiable)
      unknown - tokens matching no queued id (non-gating; informational)
    ready == no waiting and no dead."""
    waiting, dead, unknown = [], [], []
    for tok in _dep_tokens(item.get("parsed", {}).get("on", "")):
        st = status_map.get(tok)
        if st is None:
            unknown.append(tok)
        elif st == "done":
            continue
        elif st == "dropped":
            dead.append(tok)
        else:                                    # pending / in_progress
            waiting.append(tok)
    return {"ready": not waiting and not dead,
            "waiting": waiting, "dead": dead, "unknown": unknown}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.Classify -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(wave): _classify — ready/waiting/dead/unknown per capsule"
```

---

### Task 4: `_find_cycles` — detect `on:` deadlocks

**Files:**
- Modify: `intent_queue.py` (add after `_classify`)
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test**

Append this class to `tests/test_wave_surfacing.py` (the `_cap` helper from Task 3 is reused):

```python
def _has_cycle(cycles, ids):
    want = tuple(sorted(ids))
    return any(tuple(sorted(c)) == want for c in cycles)


class FindCycles(unittest.TestCase):
    def test_two_node_cycle_detected(self):
        items = [_cap("a", on="b"), _cap("b", on="a")]
        self.assertTrue(_has_cycle(iq._find_cycles(items), ["a", "b"]))

    def test_self_loop_detected(self):
        items = [_cap("a", on="a")]
        self.assertTrue(_has_cycle(iq._find_cycles(items), ["a"]))

    def test_acyclic_chain_has_no_cycle(self):
        items = [_cap("a", on="b"), _cap("b", on="c"), _cap("c")]
        self.assertEqual(iq._find_cycles(items), [])

    def test_finished_nodes_excluded_from_graph(self):
        # b is done -> edge a->b cannot deadlock, even if b nominally points back
        items = [_cap("a", on="b"), _cap("b", on="a", status="done")]
        self.assertEqual(iq._find_cycles(items), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.FindCycles -v`
Expected: FAIL with `AttributeError: module 'intent_queue' has no attribute '_find_cycles'`

- [ ] **Step 3: Write minimal implementation**

Add to `intent_queue.py` after `_classify`:

```python
def _find_cycles(items):
    """Cycles in the `on:` graph restricted to UNFINISHED capsules
    (pending/in_progress). Only unfinished deps can deadlock — a `done` dep is a
    satisfied edge, not a wait. Returns a list of cycles, each a list of ids; a
    capsule depending on itself is a length-1 cycle. Each distinct cycle once."""
    active = {it["id"] for it in items if it["status"] in ("pending", "in_progress")}
    adj = {}
    for it in items:
        if it["status"] not in ("pending", "in_progress"):
            continue
        adj[it["id"]] = [t for t in _dep_tokens(it.get("parsed", {}).get("on", "")) if t in active]
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    stack, cycles, seen = [], [], set()

    def dfs(n):
        color[n] = GRAY
        stack.append(n)
        for m in adj.get(n, []):
            if m == n:
                key = (n,)
                if key not in seen:
                    seen.add(key); cycles.append([n])
            elif color.get(m, BLACK) == GRAY:
                cyc = stack[stack.index(m):]
                key = tuple(sorted(cyc))
                if key not in seen:
                    seen.add(key); cycles.append(cyc)
            elif color.get(m, BLACK) == WHITE:
                dfs(m)
        stack.pop()
        color[n] = BLACK

    for n in adj:
        if color[n] == WHITE:
            dfs(n)
    return cycles
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.FindCycles -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(wave): _find_cycles — detect on: deadlocks over unfinished graph"
```

---

### Task 5: Gate `cmd_next` on readiness

**Files:**
- Modify: `intent_queue.py:330-342` (the `mine` branch of `cmd_next`)
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test**

Append this class to `tests/test_wave_surfacing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.NextGating -v`
Expected: FAIL — `test_serves_dep_before_dependent` fails because the unmodified `cmd_next` serves the oldest by `created` (a, queued first) regardless of deps.

- [ ] **Step 3: Write minimal implementation**

In `intent_queue.py`, replace the `if mine:` block inside `cmd_next` (currently lines 335-342):

```python
    if mine:
        nxt = sorted(mine, key=lambda x: x["created"])[0]
        if _strict_gate(nxt, strict, plan_ids):
            return 1                                         # blocked; status untouched (not saved)
        nxt["status"] = "in_progress"; nxt["started"] = now()
        save(items)
        _emit_capsule(nxt)
        return 0
```

with this readiness-gated version:

```python
    if mine:
        smap = _status_map(items)
        ready = [it for it in mine if _classify(it, smap)["ready"]]
        if ready:
            nxt = sorted(ready, key=lambda x: x["created"])[0]
            if _strict_gate(nxt, strict, plan_ids):
                return 1                                     # blocked; status untouched (not saved)
            nxt["status"] = "in_progress"; nxt["started"] = now()
            save(items)
            _emit_capsule(nxt)
            return 0
        # pending exist in scope but none are ready: report what they wait on and
        # exit WITHOUT flipping status or preempting via orphan reclaim.
        waiting = sorted({d for it in mine for d in _classify(it, smap)["waiting"]})
        dead = sorted({d for it in mine for d in _classify(it, smap)["dead"]})
        msg = f"({len(mine)} pending in scope, all blocked"
        if waiting:
            msg += f" — waiting on: {', '.join(waiting)}"
        if dead:
            msg += f"; dead deps (dropped): {', '.join(dead)}"
        print(msg + ")")
        for cyc in _find_cycles(items):
            print(f"  ⚠ dependency cycle (deadlock): " + " -> ".join(cyc) + f" -> {cyc[0]}")
        return 0
```

(The orphan-reclaim block at step 2 and everything after is unchanged; it is now reached only when `mine` is empty, exactly as before.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.NextGating -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(wave): cmd_next serves oldest READY capsule, reports blockers"
```

---

### Task 6: Split `cmd_pickup` into ready vs blocked

**Files:**
- Modify: `intent_queue.py:468-472` (the `if mine:` loop inside `cmd_pickup`)
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test**

Append this class to `tests/test_wave_surfacing.py`:

```python
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
        # b is ready, a is blocked waiting on b
        self.assertRegex(out, r"Ready now.*\*\*b\*\*")
        self.assertRegex(out, r"Blocked.*\*\*a\*\*")
        self.assertIn("waiting on b", out)

    def test_unknown_dep_note_emitted(self):
        iq.save([_cap("a", on="ghost")])
        out = self._pickup()
        self.assertIn("unknown id 'ghost'", out)

    def test_cycle_reported(self):
        iq.save([_cap("a", on="b"), _cap("b", on="a")])
        out = self._pickup()
        self.assertIn("dependency cycle", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.PickupSplit -v`
Expected: FAIL — the unmodified `cmd_pickup` prints a flat list with no "Ready now"/"Blocked" headers.

- [ ] **Step 3: Write minimal implementation**

In `intent_queue.py`, replace the `if mine:` / `elif proj:` block inside `cmd_pickup` (currently lines 468-474):

```python
    if mine:
        for it in sorted(mine, key=lambda x: x["created"]):
            print(f"- **{it['id']}** — {it['parsed'].get('do','')[:70]}  "
                  f"(accept: {len(it['parsed'].get('=',[]))} criteria)")
        print(f"\nRun `intent-queue next` to drain the oldest.")
    elif proj:
        print(f"(none pending for {proj})")
```

with this ready/blocked split:

```python
    if mine:
        smap = _status_map(items)
        ready, blocked, notes = [], [], []
        for it in sorted(mine, key=lambda x: x["created"]):
            c = _classify(it, smap)
            (ready if c["ready"] else blocked).append((it, c))
            notes += [(it["id"], u) for u in c["unknown"]]
        if ready:
            print("Ready now:")
            for it, _c in ready:
                print(f"- **{it['id']}** — {it['parsed'].get('do','')[:70]}  "
                      f"(accept: {len(it['parsed'].get('=',[]))} criteria)")
        if blocked:
            print(("\n" if ready else "") + "Blocked:")
            for it, c in blocked:
                bits = []
                if c["waiting"]:
                    bits.append("waiting on " + ", ".join(c["waiting"]))
                if c["dead"]:
                    bits.append("dead deps (dropped): " + ", ".join(c["dead"]))
                print(f"- **{it['id']}** — {it['parsed'].get('do','')[:60]}  ({'; '.join(bits)})")
        for cid, u in notes:
            print(f"  note: {cid}: on: references unknown id {u!r} (non-gating)")
        for cyc in _find_cycles(items):
            print(f"  ⚠ dependency cycle (deadlock): " + " -> ".join(cyc) + f" -> {cyc[0]}")
        if ready:
            print(f"\nRun `intent-queue next` to drain the oldest ready capsule.")
    elif proj:
        print(f"(none pending for {proj})")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.PickupSplit -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(wave): cmd_pickup splits ready vs blocked, notes unknown deps + cycles"
```

---

### Task 7: Backward-compatibility guard + full suite

**Files:**
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test**

Append this class to `tests/test_wave_surfacing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.BackwardCompat -v`
Expected: PASS (the helpers already make unmatched tokens non-gating). If it FAILS, a gating helper is wrongly treating prose tokens as deps — fix `_classify` so only `status_map` hits gate.

- [ ] **Step 3: Run the ENTIRE suite (no regressions)**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest discover -s tests -v`
Expected: PASS — the new `test_wave_surfacing` cases AND the pre-existing `test_strict_validate` cases (16) all green.

- [ ] **Step 4: Manual smoke test against a temp queue**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
export INTENT_QUEUE=$(mktemp -t iqsmoke.XXXX.jsonl)
printf '@b\ndo: build the base\n=: base exists\n' | python3 intent_queue.py add --source demo
printf '@a\ndo: build on base\non: b\n=: a exists\n'  | python3 intent_queue.py add --source demo
python3 intent_queue.py pickup --all     # expect: b Ready now, a Blocked (waiting on b)
python3 intent_queue.py next --all       # expect: serves b
python3 intent_queue.py done b --proof "base exists: smoke"
python3 intent_queue.py next --all       # expect: now serves a
rm -f "$INTENT_QUEUE"; unset INTENT_QUEUE
```

Expected: `pickup` shows `b` ready and `a` blocked; first `next` serves `b`; after `done b`, second `next` serves `a`.

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add tests/test_wave_surfacing.py
git commit -m "test(wave): backward-compat guard + full-suite green"
```

---

## Self-Review

**Spec coverage:**
- Tokenize `on:` → Task 1. id→status with active-wins → Task 2. ready/waiting/dead/unknown semantics → Task 3. Cycle detection over unfinished graph → Task 4. `next` serves oldest ready + reports blockers → Task 5. `pickup` ready/blocked split + unknown notes + cycle report → Task 6. Backward compat + no jsonl change → Task 7. `validate` untouched → no task (correct; spec says leave it). All spec sections covered.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command shows expected output.

**Type/name consistency:** `_dep_tokens`, `_status_map`, `_classify` (returns dict with keys `ready/waiting/dead/unknown`), `_find_cycles` (returns `list[list[str]]`) are used with those exact names and shapes in Tasks 5–7. The `_cap` test helper (Task 3) is reused in Tasks 4–7. `iq.QUEUE` monkeypatch + `iq.save`/`iq.load`/`iq._select` match the real module API.
