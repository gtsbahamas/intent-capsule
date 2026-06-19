# Changelog

All notable changes to intent-capsule are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

## [0.3.0] — 2026-06-19

Verification release. Adds the independent grader half of the capsule loop.
Backward-compatible: existing queues load unchanged, and the new `verification`
key needs no migration (rows are open dicts, round-trip preserved).

### Added
- **`verify`** — `intent-queue verify <id> --verdict "=[i] PASS|FAIL L<n>: evidence"`
  records a cold, independent acceptance check of a **done** capsule. Where `done`
  captures the builder's self-attested `proof`, `verify` lets a fresh session
  re-derive a PASS/FAIL verdict per `=` criterion from real evidence, each tagged
  with an evidence level (L0-L9). It writes **only** a separate top-level
  `verification` record (`verified`, `verdicts` carrying criterion/verdict/level/
  evidence, `verified_by`, `verified_at`) and never mutates a builder-owned field
  (`do`/`in`/`=`/`proof`/`status`/`done`), so "what was claimed" and "what was
  independently confirmed" stay distinct signals.
- **Non-rubber-stamp gate** (same spirit as `done`) — one `--verdict` per criterion,
  refusing short/over/blank/duplicate sets with a per-criterion summary block.
- **Independence guard** — refuses when `INTENT_ACTOR` equals the capsule's
  `completed_by` ("a builder cannot grade its own work"). Best-effort by design:
  the actor id is env-driven, so this catches the obvious same-actor case; true
  fresh-session independence is a workflow norm, not Python-provable. `verify` runs
  only on a `done` capsule, under the same cross-process lock as every mutator, and
  exits non-zero when any criterion is `FAIL`.

## [0.2.0] — 2026-06-17

Queue-hardening release. Backward-compatible: existing queues load unchanged, and
repos without the new `.intent-capsule/` marker keep using the global queue exactly
as before.

### Added
- **Atomic `save()`** — writes a temp sibling, `fsync`s, then `os.replace`s, so a
  crash mid-write can no longer truncate the queue and lose every capsule.
- **Stamped row schema v1** — every row carries `schema_version`, `updated_at`,
  `completed_by`, and `source_path_hash`; legacy rows back-fill safely on load.
- **Partial-execution progress** — `intent-queue progress <id> --proof "=[i] ..."`
  records per-criterion progress (e.g. 3/5) without closing; `list`/`pickup` surface
  it. The acceptance-gated `done` is unchanged: it still re-attests every criterion.
- **Export / import** — `intent-queue export [--file F]` and `import [--file F]
  [--force]` for backup and project migration; merge-by-id, never silently clobbering
  an existing unfinished row.
- **`doctor`** — read-only install diagnostic (python3, queue path + writability,
  plugin root, surfacing hook, resolution mode) with scriptable exit codes.
- **Cross-process file locking** — every mutator holds an advisory lock across the
  whole read-modify-write, closing the last-writer-wins race where a concurrent
  add+done dropped a capsule. `fcntl.flock` with an `O_CREAT|O_EXCL` lockfile
  fallback (+ stale-lock breaking).
- **Marker-gated project-local queues** — a repo opts in by creating a
  `.intent-capsule/` directory; its capsules then live in
  `<repo>/.intent-capsule/queue.jsonl`. Precedence: `INTENT_QUEUE` >
  `INTENT_QUEUE_GLOBAL` > project-local marker > global default. Existing global
  capsules are reported for migration, never auto-moved.

### Changed
- **`on:` now gates surfacing** like `needs:` (a capsule waits until the tasks it
  names are done); free-text provenance in `on:` stays non-gating.
- **`--strict` → `--strict-planops`** on `validate`/`next`/`pickup`, with `--strict`
  kept as a back-compat alias. Help text now states the gate covers the four
  plan-ops failure modes only — not v-intent capsule completeness.

### Fixed
- File-handle leak in `read_input()` (`open(file).read()` without close).

## [0.1.0]

Initial release: the v-intent capsule grammar and anti-omission contract, the queue
(`add`/`validate`/`list`/`next`/`done`/`drop`/`reap`/`pickup`), the deterministic
plan-ops strict validator, dependency gating via `needs:`, `group:` rollups,
acceptance-gated `done`, orphan detection/reap, and the Claude Code plugin with
ask-first surfacing.
