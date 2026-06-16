---
name: intent-capsule
description: Capture work intent at peak context as a v-intent capsule and queue it, or drain a queued capsule cold in a fresh session. Use when the user wants to hand off work across a /clear or to a later session, mentions "capture this", "queue this for later", "intent capsule", or when pending capsules surface on session start and the user agrees to work one.
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# Intent capsule — capture and cold-replay

Preserve the best understanding of a piece of work — which exists once, at peak context — so a later or context-less executor finishes it right instead of re-deriving it or silently dropping the parts that matter (where the code goes, what done looks like).

## The CLI

Run the queue via `intent-queue` if it is on PATH, otherwise:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/intent_queue.py" <args>
```

The queue is a JSONL file (default `~/.claude/intent-queue.jsonl`, override `INTENT_QUEUE`). It is global on disk but project-scoped on surface (by `--source` / current dir), so a session only sees this project's capsules.

## The capsule grammar

```
@<id>  do: <one-line: what to build>   in: <files/layer>   on: <deps/ids>
!: <hard constraint>   ~: <soft pref>   ?: <gate>   =: <acceptance>   why: <the nuance>
```

Required: `id`, `do`, and at least one `=` (acceptance). Recommended: `in`, `why`. Repeatable: `!`, `~`, `=`.

## Capturing (at peak context)

When the user wants to hand off work, draft a capsule with them, then:

```bash
intent-queue validate --file capsule.txt      # dry-run completeness check
intent-queue add --source <project> --file capsule.txt   # rejects if missing do/= 
```

The contract is the point: `add` refuses an incomplete capsule **now**, while context is fresh and the gap is cheap to fix — not weeks later, cold.

## Draining (in a fresh session) — ASK FIRST

When pending capsules surface on session start, **offer; never auto-run**:

1. Tell the user what's queued (`intent-queue pickup`) and ask whether to drain the oldest.
2. Only on a yes: `intent-queue next` (drains oldest pending → in_progress, prints the capsule).
3. Treat the capsule as a cold brief — `do`/`in`/`on`/`!`/`?`/`=`/`why` carry everything. Build to the `=` acceptance criteria.
4. When done and **verified** (criteria actually met, not merely code written), attest each criterion in order:

```bash
intent-queue done <id> --proof "=[1] how it was met" --proof "=[2] ..." --proof "=[3] ..."
```

`done` refuses to close a capsule with criteria unless you attest each one — it is not a rubber-stamp.

## Rules

- **Ask first.** Surface and offer; never drain or execute a capsule without the user's go-ahead.
- **Never `drop` a capsule you don't understand** — that discards captured work. Read `CONCEPT.md` / `RESULTS.md` first.
- **The model is not the safety layer.** If anything applies capsules automatically, a deterministic validator must reject malformed/garbage capsules before they run.
- A capsule drained but never finished resurfaces as an orphan (`intent-queue reap --yes`, or auto-reclaimed by the next `next`), so a crashed executor doesn't lose the work.
