# Changelog

All notable changes to intent-capsule are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semver.

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
