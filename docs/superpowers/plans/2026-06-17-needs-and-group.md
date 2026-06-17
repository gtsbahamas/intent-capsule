# needs: + group: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give machine dependencies their own grammar field (`needs:`, which gates surfacing) and make capsule grouping first-class (`group:`, with a progress rollup in `pickup`), so the grammar matches how the queue is actually used. `on:` reverts to pure provenance prose.

**Architecture:** Phase 1 moves gating off `on:` onto a new `needs:` field — the dependency helpers (`_classify`, `_find_cycles`) read `needs` instead of `on`; no other gating logic changes. Phase 2 adds a pure `_group_rollup` helper and a `Groups:` section in `cmd_pickup`. No jsonl schema change; the two new parsed fields are optional. Spec: `docs/superpowers/specs/2026-06-17-needs-and-group-design.md`.

**Tech Stack:** Python 3 stdlib only. Single module `intent_queue.py`, tests `tests/test_wave_surfacing.py` (+ existing `tests/test_strict_validate.py`). Run `python3 -m unittest discover -s tests`.

---

## File Structure

- **Modify** `intent_queue.py`: parser globals (`SINGLE`, `TAG_RE`); `_classify` and `_find_cycles` (read `needs`); `cmd_pickup` (unknown-note source + reworded text; new `Groups:` rollup); add pure helper `_group_rollup`; update the module-docstring grammar legend.
- **Modify** `tests/test_wave_surfacing.py`: extend the `_cap` helper with a `needs=` param; migrate dependency-expressing tests from `on=` to `needs=`; add migration + parser + rollup tests.
- **Modify** `README.md`: document `needs:`/`group:` and `on:`-as-provenance.

---

### Task 1: Parser recognizes `needs:` and `group:`

**Files:**
- Modify: `intent_queue.py:34` (`SINGLE`) and `intent_queue.py:38` (`TAG_RE`)
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test** — append this class to `tests/test_wave_surfacing.py` before the `if __name__` block:

```python
class GrammarFields(unittest.TestCase):
    def test_needs_and_group_parse_as_single_fields(self):
        cap = "@x\ndo: a thing\nneeds: dep-one dep-two\ngroup: shipsafe\n=: works"
        p = iq.parse_capsule(cap)
        self.assertEqual(p.get("needs"), "dep-one dep-two")
        self.assertEqual(p.get("group"), "shipsafe")

    def test_needs_and_group_are_optional(self):
        p = iq.parse_capsule("@x\ndo: a thing\n=: works")
        errs, _ = iq.check(p)
        self.assertEqual(errs, [])  # neither is required
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.GrammarFields -v`
Expected: FAIL — `needs`/`group` lines aren't matched by `TAG_RE`, so `p.get("needs")` is `None`.

- [ ] **Step 3: Implement** — in `intent_queue.py` change line 34 from:

```python
SINGLE = {"do","in","on","why","?"}          # at most one
```
to:
```python
SINGLE = {"do","in","on","needs","group","why","?"}   # at most one
```

and change line 38 from:
```python
TAG_RE = re.compile(r"^(do|in|on|why|[!~?=]):\s*(.*)$")
```
to:
```python
TAG_RE = re.compile(r"^(do|in|on|needs|group|why|[!~?=]):\s*(.*)$")
```

- [ ] **Step 4: Run, verify pass**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.GrammarFields -v`
Expected: PASS (2 tests). Then run the whole file `python3 -m unittest tests.test_wave_surfacing -v` — expect no regressions (existing wave tests still green; they use `on=` which still parses).

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(grammar): recognize needs: and group: as single fields"
```

---

### Task 2: Migrate gating from `on:` to `needs:`

**Files:**
- Modify: `intent_queue.py` — `_classify` (the `_dep_tokens(...get("on"...))` read), `_find_cycles` (same read + docstring), `cmd_pickup` (the unknown-note `any(... get("on" ...))` guard and the note text)
- Test: `tests/test_wave_surfacing.py` — extend `_cap`, migrate dep tests, add migration proof

- [ ] **Step 1: Write the failing test + extend the test helper**

First, extend the `_cap` helper in `tests/test_wave_surfacing.py`. It currently is:

```python
def _cap(id_, on="", do="x", accept=("done",), status="pending"):
    """Build a queue item shaped like cmd_add produces."""
    return {"id": id_, "status": status, "created": "2026-06-17T00:00:00+00:00",
            "source": "test", "capsule": "", "started": None, "done": None, "proof": None,
            "parsed": {"id": id_, "do": do, "on": on, "=": list(accept)}}
```

Replace it with (adds a `needs` param + `group`, both optional):

```python
def _cap(id_, on="", needs="", group="", do="x", accept=("done",), status="pending"):
    """Build a queue item shaped like cmd_add produces."""
    return {"id": id_, "status": status, "created": "2026-06-17T00:00:00+00:00",
            "source": "test", "capsule": "", "started": None, "done": None, "proof": None,
            "parsed": {"id": id_, "do": do, "on": on, "needs": needs, "group": group,
                       "=": list(accept)}}
```

Then add this migration-proof class before the `if __name__` block:

```python
class GatingMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.tmp.close()
        self._orig = iq.QUEUE
        iq.QUEUE = self.tmp.name

    def tearDown(self):
        iq.QUEUE = self._orig
        os.unlink(self.tmp.name)

    def test_on_no_longer_gates(self):
        # a:on=b (provenance), b pending. Post-migration on: does NOT gate -> a is served.
        a = _cap("a", on="b"); a["created"] = "2026-06-17T00:00:00+00:00"
        b = _cap("b");         b["created"] = "2026-06-17T01:00:00+00:00"
        iq.save([a, b])
        buf = io.StringIO()
        with redirect_stdout(buf):
            iq.cmd_next(show_all=True)
        # oldest by created is a; since on: doesn't gate, a is served
        self.assertIn("intent capsule 'a'", buf.getvalue())

    def test_needs_gates(self):
        a = _cap("a", needs="b"); b = _cap("b")
        iq.save([a, b])
        buf = io.StringIO()
        with redirect_stdout(buf):
            iq.cmd_next(show_all=True)
        self.assertIn("intent capsule 'b'", buf.getvalue())  # b served, a blocked on needs
```

- [ ] **Step 2: Run, verify the migration test fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.GatingMigration -v`
Expected: `test_on_no_longer_gates` FAILS — gating still reads `on:`, so `a` is blocked and `b` is served instead of `a`. (`test_needs_gates` also fails — `needs` isn't read yet.)

- [ ] **Step 3: Implement — point the helpers at `needs`**

In `intent_queue.py`, in `_classify`, change the loop source from `"on"` to `"needs"`:

```python
    for tok in _dep_tokens(item.get("parsed", {}).get("needs", "")):
```

In `_find_cycles`, change the adjacency read from `"on"` to `"needs"`:

```python
        adj[it["id"]] = [t for t in _dep_tokens(it.get("parsed", {}).get("needs", "")) if t in active]
```

and update its docstring first line `Cycles in the `on:` graph` → `Cycles in the `needs:` graph`.

In `cmd_pickup`, the unknown-note guard currently reads:

```python
            if c["unknown"] and any(t in smap for t in _dep_tokens(it.get("parsed", {}).get("on", ""))):
```
change `"on"` → `"needs"`:
```python
            if c["unknown"] and any(t in smap for t in _dep_tokens(it.get("parsed", {}).get("needs", ""))):
```
and the note text below it currently reads:
```python
        for cid, u in notes:
            print(f"  note: {cid}: on: references unknown id {u!r} (non-gating)")
```
change `on:` → `needs:` in the message:
```python
        for cid, u in notes:
            print(f"  note: {cid}: needs: references unknown id {u!r} (non-gating)")
```

- [ ] **Step 4: Migrate the existing dependency tests from `on=` to `needs=`**

Every test that used `_cap(..., on="<ids>")` to express a DEPENDENCY (to exercise gating or cycles) must now use `needs="<ids>"`. Apply across `tests/test_wave_surfacing.py`:

- In class `Classify`: `test_unfinished_dep_blocks`, `test_done_dep_is_satisfied`, `test_dropped_dep_is_dead`, `test_unknown_token_is_non_gating` — change `on=` → `needs=`.
- In class `FindCycles`: ALL tests (`test_two_node_cycle_detected`, `test_self_loop_detected`, `test_acyclic_chain_has_no_cycle`, `test_finished_nodes_excluded_from_graph`, `test_three_node_cycle_detected`, `test_three_node_cycle_broken_by_done_node`) — change `on=` → `needs=`.
- In class `NextGating`: `test_serves_dep_before_dependent`, `test_dependent_served_after_dep_done`, `test_all_blocked_reports_and_serves_nothing`, `test_blocked_cycle_reported`, `test_dep_gating_is_cross_project` — change `on=` → `needs=`.
- In class `PickupSplit`: `test_ready_and_blocked_are_partitioned`, `test_typo_dep_surfaced_only_alongside_a_real_dep`, `test_all_blocked_shows_blocked_section_without_cta` — change `on=` → `needs=`.

DO NOT change the two tests that intentionally exercise `on:`-as-prose — they stay `on=`:
- `PickupSplit.test_pure_free_text_on_emits_no_notes` (asserts free-text `on:` emits no notes — still true, notes now read `needs`).
- `BackwardCompat.test_free_text_on_with_no_matching_ids_is_served_unchanged` (asserts an `on:`-prose capsule is served — still true).

Also, in `PickupSplit.test_typo_dep_surfaced_only_alongside_a_real_dep`, the assertion text checks for `"unknown id 'ghost'"` — that substring is still correct (the note text only changed the `on:`/`needs:` prefix, not the `unknown id 'X'` part). Leave the assertion as-is.

- [ ] **Step 5: Run, verify pass**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing -v`
Expected: ALL green (the migrated dep tests now gate via `needs`; `GatingMigration` passes; the two `on:`-prose tests still pass). Then `python3 -m unittest discover -s tests -v` — confirm the 16 strict tests are unaffected.

- [ ] **Step 6: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(wave): gate on needs: not on:; on: reverts to provenance prose"
```

---

### Task 3: `_group_rollup` pure helper

**Files:**
- Modify: `intent_queue.py` — add `_group_rollup` after `_find_cycles`
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test** — append before the `if __name__` block:

```python
class GroupRollup(unittest.TestCase):
    def test_counts_by_group_across_statuses(self):
        items = [
            _cap("s1", group="shipsafe", status="done"),
            _cap("s2", group="shipsafe", status="done"),
            _cap("s3", group="shipsafe"),                       # ready (no needs)
            _cap("s4", group="shipsafe", needs="s3"),           # blocked on s3
            _cap("s5", group="shipsafe", status="dropped"),
            _cap("m1", group="mgo"),                            # ready
            _cap("u1"),                                         # ungrouped -> excluded
        ]
        smap = iq._status_map(items)
        roll = iq._group_rollup(items, smap)
        # sorted by group name: mgo, shipsafe
        self.assertEqual(roll[0], ("mgo", 0, 1, 1, 0, 0))
        self.assertEqual(roll[1], ("shipsafe", 2, 5, 1, 1, 1))

    def test_no_groups_returns_empty(self):
        items = [_cap("a"), _cap("b", needs="a")]
        self.assertEqual(iq._group_rollup(items, iq._status_map(items)), [])
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.GroupRollup -v`
Expected: FAIL — `AttributeError: module 'intent_queue' has no attribute '_group_rollup'`.

- [ ] **Step 3: Implement** — add to `intent_queue.py` after `_find_cycles`:

```python
def _group_rollup(items, status_map):
    """Per-group progress over `items` that carry a group: label. Returns a list of
    (group, done, total, ready, blocked, dropped) sorted by group name. Ungrouped
    capsules are excluded. `total` counts every status; ready/blocked are computed
    via _classify for the non-done, non-dropped members."""
    groups = {}
    for it in items:
        g = it.get("parsed", {}).get("group")
        if not g:
            continue
        d = groups.setdefault(g, {"done": 0, "total": 0, "ready": 0, "blocked": 0, "dropped": 0})
        d["total"] += 1
        st = it["status"]
        if st == "done":
            d["done"] += 1
        elif st == "dropped":
            d["dropped"] += 1
        elif _classify(it, status_map)["ready"]:
            d["ready"] += 1
        else:
            d["blocked"] += 1
    return [(g, v["done"], v["total"], v["ready"], v["blocked"], v["dropped"])
            for g, v in sorted(groups.items())]
```

- [ ] **Step 4: Run, verify pass**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.GroupRollup -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(group): _group_rollup — per-group progress over the queue"
```

---

### Task 4: Wire the `Groups:` rollup into `cmd_pickup`

**Files:**
- Modify: `intent_queue.py` — `cmd_pickup` (add rollup after the header; hoist `smap`)
- Test: `tests/test_wave_surfacing.py`

- [ ] **Step 1: Write the failing test** — append before the `if __name__` block:

```python
class PickupRollup(unittest.TestCase):
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

    def test_rollup_line_printed_with_counts(self):
        iq.save([
            _cap("s1", group="shipsafe", status="done"),
            _cap("s2", group="shipsafe"),                  # ready
            _cap("s3", group="shipsafe", needs="s2"),      # blocked
        ])
        out = self._pickup()
        self.assertIn("Groups:", out)
        self.assertIn("shipsafe — 1/3 done (1 ready, 1 blocked)", out)

    def test_no_rollup_section_when_no_groups(self):
        iq.save([_cap("a"), _cap("b", needs="a")])
        out = self._pickup()
        self.assertNotIn("Groups:", out)

    def test_ungrouped_capsule_absent_from_rollup_but_listed(self):
        iq.save([_cap("g1", group="shipsafe"), _cap("plain")])
        out = self._pickup()
        self.assertIn("shipsafe — 0/1 done (1 ready)", out)
        self.assertIn("**plain**", out)   # ungrouped still shown in Ready now
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.PickupRollup -v`
Expected: FAIL — no `Groups:` section exists yet.

- [ ] **Step 3: Implement** — in `intent_queue.py`, in `cmd_pickup`, immediately AFTER the header `print(f"## Intent Queue {scope_label} ...")` line and BEFORE the `if mine:` line, insert:

```python
    smap = _status_map(items)
    scoped = [it for it in items if it.get("source") == proj] if proj else items
    rollup = _group_rollup(scoped, smap)
    if rollup:
        print("Groups:")
        for g, done, total, ready, blocked, dropped in rollup:
            extra = [f"{n} {lbl}" for n, lbl in ((ready, "ready"), (blocked, "blocked"), (dropped, "dropped")) if n]
            print(f"- {g} — {done}/{total} done" + (f" ({', '.join(extra)})" if extra else ""))
        print()
```

Then, inside the `if mine:` block, REMOVE the now-duplicate local `smap = _status_map(items)` line (the loop will use the `smap` hoisted above).

- [ ] **Step 4: Run, verify pass**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -m unittest tests.test_wave_surfacing.PickupRollup -v`
Expected: PASS (3 tests). Then the whole file `python3 -m unittest tests.test_wave_surfacing -v` — confirm `PickupSplit`/`NextGating` still green (the hoisted `smap` must not have broken them).

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py tests/test_wave_surfacing.py
git commit -m "feat(group): pickup prints a per-group progress rollup"
```

---

### Task 5: Docs, full suite, smoke test

**Files:**
- Modify: `intent_queue.py` (module-docstring grammar legend), `README.md`

- [ ] **Step 1: Update the grammar legend in the module docstring.** In `intent_queue.py`, the docstring `Grammar:` block currently reads:

```
Grammar:
  @<id>     do: <build>   in: <files/layer>   on: <deps>
  !: <hard constraint>  ~: <soft pref>  ?: <gate>  =: <acceptance>  why: <nuance>
```

Replace with:

```
Grammar:
  @<id>  do: <build>  in: <files/layer>  needs: <capsule-ids>  group: <label>  on: <provenance>
  !: <hard constraint>  ~: <soft pref>  ?: <gate>  =: <acceptance>  why: <nuance>

  needs: gates surfacing (a capsule waits until its needs-ids are done).
  group: organizational label for the pickup rollup. on: is provenance prose (not gated).
```

- [ ] **Step 2: Update `README.md`.** Find where the grammar/fields are documented and add `needs:` (machine deps, gates surfacing), `group:` (label for the pickup rollup), and clarify `on:` is provenance prose, no longer gated. Match the README's existing format. If the README has no per-field section, add a short "Fields" subsection near the grammar description.

- [ ] **Step 3: Run the full suite**

Run: `cd /Users/tywells/Downloads/projects/intent-capsule && python3 -W error::ResourceWarning -m unittest discover -s tests -v`
Expected: all green (wave + grammar + migration + group + the 16 strict tests).

- [ ] **Step 4: Manual smoke test** (paste output in the report):

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
export INTENT_QUEUE=$(mktemp -t iqsmoke.XXXX).jsonl
printf '@base\ndo: build base\ngroup: demo\n=: base exists\n' | python3 intent_queue.py add --source demo
printf '@feat\ndo: build feat\nneeds: base\ngroup: demo\non: the base module gives the scaffold\n=: feat exists\n' | python3 intent_queue.py add --source demo
echo "--- pickup (expect: Groups: demo 0/2 done (1 ready, 1 blocked); base Ready, feat Blocked on base) ---"
python3 intent_queue.py pickup --all
echo "--- next (expect base; feat is blocked by needs:) ---"
python3 intent_queue.py next --all | grep "intent capsule"
rm -f "$INTENT_QUEUE"; unset INTENT_QUEUE
```

Expected: `pickup` shows `Groups: demo — 0/2 done (1 ready, 1 blocked)`, base Ready, feat Blocked waiting on base; `next` serves base. The `on:` prose on `feat` does NOT block it (only `needs:` does).

- [ ] **Step 5: Commit**

```bash
cd /Users/tywells/Downloads/projects/intent-capsule
git add intent_queue.py README.md
git commit -m "docs: document needs:/group: and on:-as-provenance in legend + README"
```

---

## Self-Review

**Spec coverage:** Grammar `needs:`/`group:` parse → Task 1. Gating migrates to `needs:`, `on:` becomes prose, unknown-note re-sourced → Task 2. `_group_rollup` helper → Task 3. `Groups:` rollup in `pickup`, project-scoped, done-counts-toward-total, ungrouped excluded → Task 4. Docs (legend + README) → Task 5. `btw` skill doc update is explicitly a deferred follow-up (spec), so no task — correct.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; commands show expected output. (Task 5 Step 2 is the one judgment step — README structure varies — but it specifies exactly what to add and the fallback if no field section exists.)

**Type/name consistency:** `_group_rollup(items, status_map)` returns `list[(group, done, total, ready, blocked, dropped)]` — consumed with that exact 6-tuple unpacking in Task 4. `_cap` gains `needs=`/`group=` in Task 2 and is used with them in Tasks 3–4. `_classify`/`_find_cycles` read `parsed["needs"]` consistently after Task 2. The hoisted `smap` in Task 4 replaces the local one removed in the same task.
