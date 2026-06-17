# Dependency-aware wave surfacing for intent-queue

*Design — 2026-06-17*

## Origin

A read-only audit of the Hermes operator system (`state.db`, 484 sessions) asked whether intent-capsule should be ported into Hermes. The answer was no — but the audit surfaced *why* Hermes never loses cross-session intent, and one of those mechanisms is a capability intent-capsule lacks:

Hermes executes a plan **wave by wave**. A multi-task remediation plan persisted as a doc on disk; completing "Wave 3 Task 3.2" naturally surfaced 3.3 in the next session. intent-capsule already *captures* a dependency field (`on:`) on every capsule but never *uses* it — `next` serves the oldest pending by creation time, blind to whether its prerequisites are done.

This design makes the `on:` field load-bearing: the flat queue becomes a wave executor, reusing data already captured. No new authoring burden, no schema change.

## Scope

In scope: surface-time dependency gating in `next` and `pickup`, computed from the existing queue.

Out of scope (deliberately deferred): explicit `wave:` grammar fields; linking capsules to an external `plan.json` and gating on its node statuses (a separate "durable plan-doc linkage" feature); any change to the jsonl on-disk shape.

## Data model

No change. Each queued item already carries `parsed["on"]` (a single free-text string, "ids or features it depends on / extends") and a `status` in `{pending, in_progress, done, dropped}`. Gating is computed fresh on every `next`/`pickup` call from these fields. Nothing is persisted, triggered, or migrated.

## Dependency semantics (Approach A)

- **Tokenize** `on:` on commas and whitespace into candidate tokens. Ids are case-sensitive; no lowercasing.
- A token is a **hard dependency** iff it *exactly* matches the `id` of some queued capsule (in any status). Dependency satisfaction is resolved against the **entire** queue, independent of project scope — scope only governs what is surfaced to you, not what is true about completion.
- A dependency is **satisfied** iff that capsule's status is `done`.
- A token matching **no** queued id is **non-gating** (free text / feature name). It does not block. `pickup` emits a soft note: `on: references unknown id "X"` so a typo'd dep id is visible rather than silently inert.
- A dependency whose capsule is **`dropped`** is **unsatisfiable** — a dead blocker. The dependent is surfaced as a deadlock (`blocked: dep "X" was dropped`), never silently hidden.

A capsule is **ready** iff it has no unsatisfied and no dead blockers; otherwise **blocked**.

## Cycle handling

`on:` references can form a cycle (A on B, B on A) over the unfinished subgraph, which would block both capsules forever. At surface time, detect cycles among `{pending, in_progress}` capsules and report each cycle explicitly as a deadlock. Cycle members are never silently dropped from the ready set without explanation.

(The existing `strict_validate` only catches *self*-dependency inside a single capsule's plan-ops grammar; cross-capsule `on:` cycles are a new, separate check living in the surfacing layer.)

## Command behavior changes

### `next`
Among in-scope pending capsules, serve the oldest **ready** one (ordering otherwise unchanged: `created` ascending). Blocked capsules are skipped, not handed out. If pending capsules exist in scope but none are ready, print what they are waiting on and exit 0 without flipping any status — e.g. `(3 pending in scope, all blocked — waiting on: B, C)`. The orphan-reclaim path (step 2) is unchanged; a reclaimed orphan is still served regardless of deps (it was already in flight).

### `pickup`
Split this project's pending capsules into **ready now** and **blocked**. For each blocked capsule, show the dep ids it is waiting on and their states. Surface cycle deadlocks and dead (dropped) blockers as warnings. Emit the soft unknown-dep note for unmatched tokens. The other-projects and orphan sections are unchanged.

### `validate`
Unchanged. `validate` reads a single capsule from file/stdin and has no queue context, so it cannot resolve dep ids. The unknown-dep note lives only where the queue is in hand (`pickup`).

## Units

- `_dep_tokens(on_str) -> list[str]` — tokenize the `on:` string.
- `_status_map(items) -> dict[id, status]` — id→status over the whole queue.
- `_classify(item, status_map) -> {ready: bool, waiting: [...], dead: [...], unknown: [...]}` — per-capsule blocker analysis.
- `_find_cycles(items) -> list[list[id]]` — cycles over the unfinished `on:` subgraph.

`next` and `pickup` consume these. Each unit is pure (no I/O) and independently testable.

## Backward compatibility

Existing queues are unaffected: any `on:` text whose tokens match no queued id is non-gating, so today's free-text deps behave exactly as before. No migration, no jsonl shape change.

## Testing (stdlib unittest, new `tests/test_wave_surfacing.py`)

1. `A on B`, both pending → `next` serves **B** (oldest ready), not A.
2. After `B` done → `next` serves **A**.
3. `A on B,C`; B done, C pending → A blocked; `pickup` shows A waiting on **C**.
4. `A on B`, B dropped → A surfaced as **dead-blocked**, not hidden.
5. Cycle `A on B`, `B on A` → both reported as a **cycle deadlock**.
6. `A on nonexistent` → A **ready** (non-gating); `pickup` shows soft unknown-dep note.
7. `pickup` correctly partitions ready vs blocked.
8. Backward-compat: a pre-existing capsule with free-text `on:` and no matching ids is served unchanged.

## Non-goals / risks

- Overloading the documented free-text `on:` field. Mitigated: only exact id matches gate; everything else is informational.
- Typo'd dep id silently non-gating. Mitigated: the soft unknown-dep note in `pickup`.
