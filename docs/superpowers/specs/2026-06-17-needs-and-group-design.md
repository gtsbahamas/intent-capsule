# Machine deps (`needs:`) and group rollup (`group:`)

*Design — 2026-06-17*

## Origin

A meta exercise — pressure-testing "should a capsule spawn a wave?" via `kill-it-or-climb` — measured the live 48-capsule queue and found two things:

1. **`on:` is used as provenance prose, not dependency edges.** Of 48 capsules, zero used `on:` as a literal capsule-id reference; every value is a paragraph of context ("mirror the working sibling wallet_ledger…", "Vercel request semantics…"). The wave-surfacing gating shipped earlier (which keys off `on:` id-matches) therefore fires on none of the real corpus.
2. **Multi-step work is captured as multi-criteria leaves, and grouping already happens by naming prefix** (`mgk-*`, `mgo-*`, `shipsafe-*`) and prose reference ("the 7 mgk-* fix capsules").

Conclusion: the recursive "capsule spawns child capsules" idea was over-built. The evidence-backed need is (a) give machine dependencies their own field so gating has a clean signal, and (b) make the prefix-grouping people already do first-class with a progress rollup.

## Scope

In scope: a `needs:` grammar tag that drives gating (replacing `on:` in that role); a `group:` grammar tag with a per-group rollup in `pickup`. Two ordered phases in one plan.

Out of scope (deliberately): recursive parent→child capsule decomposition; group-level dependencies or ordering; migrating existing capsules' `on:` prose into `needs:` (existing capsules simply have neither new field). No jsonl on-disk shape change beyond the two new optional parsed fields.

## Grammar changes

Two new single-value tags join the capsule grammar:

```
@<id>  do: <build>  in: <files/layer>  needs: <capsule-ids>  group: <label>  on: <provenance prose>
!: <hard constraint>  ~: <soft pref>  ?: <gate>  =: <acceptance>  why: <nuance>
```

- `needs:` — space/comma-separated capsule ids this capsule depends on. Gates surfacing.
- `group:` — a single organizational label. Optional. Drives the rollup only; never gates or orders.
- `on:` — reverts to pure provenance prose ("what you need to know to execute this"). No longer parsed for gating.

Parser: add `needs` and `group` to the `SINGLE` set, and to `TAG_RE`'s alternation: `^(do|in|on|needs|group|why|[!~?=]):\s*(.*)$`. Both are optional (not added to `REQUIRED`). Neither is added to `RECOMMENDED` (a capsule with no deps and no group is normal).

## Phase 1 — migrate gating from `on:` to `needs:`

The dependency helpers already exist and are tested; they change which field they read:

- `_classify(item, status_map)` reads `item["parsed"]["needs"]` instead of `["on"]`.
- `_find_cycles(items)` reads `parsed["needs"]` instead of `["on"]`.
- `_dep_tokens` is unchanged (a generic tokenizer).
- `cmd_next`, `cmd_pickup`, `_print_scope_cycles` are unchanged — they consume the helpers.

Result: a capsule gates only on `needs:`. A capsule whose `on:` happens to contain a real capsule id is **not** blocked (it is provenance, served normally). Existing capsules (no `needs:`) never gate — which matches the measured reality that `on:`-gating fired on zero of them.

The unknown-dep note in `pickup` (the "names a real queued id" heuristic) now keys off `needs:` tokens, not `on:`.

## Phase 2 — `group:` rollup in `pickup`

After the existing header line, `pickup` prints a rollup section for in-scope capsules that have a `group:`, one line per group:

```
Groups:
- shipsafe — 4/10 done (2 ready, 4 blocked)
- mgo — 0/3 done (3 ready)
```

Counting rules:
- Scope: same project scoping as the rest of `pickup` (a capsule belongs to the rollup if it is in scope — `source == proj`, or all when `--all`). Resolved over **all** items in scope, including `done`/`dropped`, so the denominator is the whole group.
- `done` counts toward "N done". `ready`/`blocked` are computed for the non-done, non-dropped members via `_classify` (ready == classify.ready). `dropped` members count toward the total but are reported separately only if present (`; 1 dropped`).
- Capsules with no `group:` are excluded from the rollup entirely; they still appear in the normal Ready/Blocked lists unchanged.
- If no in-scope capsule has a group, the rollup section is omitted (no empty header).

The rollup is display-only; it does not change what `next` serves or how gating works.

## Units

- Parser: `parse_capsule` (+`SINGLE`, `TAG_RE`) — recognizes `needs`/`group`.
- `_classify`, `_find_cycles` — read `needs`.
- A new pure helper `_group_rollup(items_in_scope, status_map) -> list[(group, done, total, ready, blocked, dropped)]` — computes the rollup data (pure, testable).
- `cmd_pickup` — prints the rollup section using the helper.

## Backward compatibility

The existing 48 capsules have neither `needs:` nor `group:`. After this change: they never gate (Phase 1) and never appear in a rollup (Phase 2) — byte-identical surfacing behavior. No migration, no jsonl shape change (the two new keys simply don't exist on old parsed blobs; `_classify` reads `parsed.get("needs","")`).

## Docs

Update the grammar legend in the module docstring and `README.md` to document `needs:`/`group:` and `on:`-as-provenance. Flag the `btw` capture skill (authors capsules at peak context) as a follow-up doc update so new capsules adopt `needs:`/`group:` — not edited in this plan, noted as a ticket.

## Testing (stdlib unittest)

Phase 1:
- The `_cap` test helper gains a `needs=` param. Existing wave tests switch `on=` → `needs=` (they were testing gating, which now lives on `needs:`).
- New: a capsule with `on: <real-id>` (and no `needs:`) is served by `next`, not blocked — proves `on:` no longer gates.
- New: parser recognizes `needs:` and `group:` as single fields.

Phase 2:
- `_group_rollup` returns correct counts for a mixed-status group (done/ready/blocked/dropped).
- `pickup` prints a `Groups:` line with the expected counts; omits the section when no capsule has a group.
- Ungrouped capsules still appear in Ready/Blocked and are absent from the rollup.

## Non-goals / risks

- Risk: adding fields to a deliberately tiny grammar. Mitigated: both are optional, and they replace an overloaded use of `on:` rather than adding net new concepts.
- Risk: `needs:` repeats the low-adoption problem `on:`-as-edges had. Mitigated: `needs:` is a clean dedicated signal (authors who want gating now have an unambiguous field), and the `btw` doc update is flagged to drive adoption.
