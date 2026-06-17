# ChatGPT Review — Assessment vs the Repo

*Written 2026-06-17. Maps every suggestion from the ChatGPT voice brainstorm
([share link](https://chatgpt.com/share/6a332c3c-2c54-83ea-aa3d-201011a8d4e9))
against what intent-capsule actually is and already does. Verdicts cite code in
`intent_queue.py` and the thesis in `CONCEPT.md` / `RESULTS.md`.*

## Provenance caveat

ChatGPT share pages lazy-load; only the **back half** of the brainstorm rendered.
We have ChatGPT's feature recommendations but **not** its opening "Repo Review
Summary" — so this maps the *suggestions*, not GPT's original critique of the code.
The conversation was voice (the `You said:` turns are transcribed speech), which is
why the suggestions are abstract: it was riffing on the word *intent*, not reading
`intent_queue.py`.

## The one-line finding

Most of the list is generic "intent-management system" boilerplate. It re-proposes
things the repo already ships (prioritization, collaboration, pre-execution
validation, ambiguity rejection), proposes two or three things that fight the
project's core thesis, and surfaces **one genuinely new, real gap**: partial
execution state. The "production-ready / mature system" rating is noise — it rated
a hypothetical, sight-unseen.

## The thesis the suggestions have to respect

From `CONCEPT.md`: the discriminator is **a context-rich author handing off to a
later context-poor executor, where silent omission is the dominant failure mode.**
Pickup is **ask-first** (surface, ask, never auto-run). The load-bearing caveat from
`RESULTS.md`: **the model is not the safety layer** (~31% of malformed lines get
executed, not refused), so unattended pipelines need a deterministic code-level gate.

Any suggestion that (a) assumes a live author at execution, (b) makes pickup
auto-fire, or (c) softens the deterministic contract into a fuzzy score is working
*against* the design, not extending it.

## Verdict table

| # | ChatGPT suggestion | Verdict | Evidence |
|---|---|---|---|
| 1 | Refinement module — re-confirm/update intent if conditions evolve | **Mostly scope-creep** | Assumes a live author at execution; capsules replay cold. Legit slice (stale refs) folds into #3. The `?:` gate field already carries "confirm before X". |
| 2 | Pre-execution environment validation | **Already built** (+ queued) | `strict_validate()` + `next --strict` refuse malformed capsules to an unattended executor without burning them (`intent_queue.py:280, :453`). Env-health check is the already-queued `queue-doctor-command`. |
| 3 | Expiration of stale intents | **Worth doing — as a flag, not a delete** | Staleness exists for `in_progress` (`ORPHAN_MIN` → `reap`/auto-reclaim, `:583, :495`). **Pending** capsules never age out. Real small gap. Auto-*delete* is wrong — it discards captured work (violates the drop guard at `:711` and the whole ethos). Correct shape: *flag* old/dangling-`in:` pending capsules. |
| 4 | Sensitive-intent tagging + manual confirmation | **Already built** | Pickup is ask-first by design (`CONCEPT.md`); `?:` gate and `!:` hard-constraint fields already encode "confirm/never". Default is already confirm-first. |
| 5 | Ambiguity checks — prompt for clarification before storing | **Already built (better)** | The anti-omission contract rejects-and-explains at capture if `id`/`do`/`=` missing (`check()` `:210`, `cmd_add` `:380`). "Prompt for clarification" assumes interactive capture; reject-with-reason fits the `btw`-at-peak-context flow better. |
| 6 | Prioritization for overlapping intents | **Already built** | `on:`/`needs:` dependency gating + cycle detection (`_classify` `:94`, `_find_cycles` `:116`), FIFO-by-`created` ordering, `group:` rollups (`_group_rollup` `:158`). GPT didn't know. |
| 7 | Partial rollback/retry for mid-execution failures | **Worth doing — the real one** | `done` is all-or-nothing: every `=` criterion attested → done, else stays `in_progress` (`cmd_done` `:540`). No representation for "3/5 criteria met, blocked on rest". Orphan/reap handles *crash*, not *partial progress*. Genuinely new. Design first — the binary model is deliberately simple. |
| 8 | Configurable validation thresholds | **Against design** | The strict validator is intentionally binary (clean / hard-structural-reject), not a fuzzy score. A threshold weakens the contract — that's softaworks' ≥70 model, which this project deliberately rejects (`COMPETITIVE-LANDSCAPE.md`). |
| 9 | Learning loops — log outcome → refine templates | **Worth doing — later, heavy** | `proof` attestations are already logged per done-capsule (`cmd_done` `:562`). Mining them to suggest better templates fits the RESULTS culture, but it's a research project of its own. Real over-engineering risk. |
| 10 | Shared/collaborative capsules | **Already built** (realistic version) | Queue is global on disk; capsules carry `source`; cross-project handoff + `pickup --all` + project-scoped surfacing already ship (`current_project` `:422`, `_scope` `:430`). True multi-user/auth/merge is a different scale, not in scope. |
| 11 | External triggers — calendar/system-state auto-fire intents | **Scope-creep — changes the product** | Pickup is ask-first, never auto-run. Event-driven auto-execution contradicts that *and* the "model is not the safety layer" caveat. This is an automation engine — a different product. |

## Bucketed

### Already built (ChatGPT couldn't see the code)
Prioritization (#6), realistic collaboration (#10), pre-execution validation (#2),
ambiguity rejection (#5), sensitive/manual-confirm via ask-first + `?:` (#4). Five of
eleven suggestions already ship.

### Worth doing (genuinely new or a real gap)
- **#7 Partial execution state** — the standout. Today a capsule can't say "3 of 5
  acceptance criteria met." Worth a design pass; resist bolting it on.
- **#3 Stale-pending flag** — small, real queue hygiene. As a *flag* on old or
  dangling-`in:` pending capsules. Never auto-delete.
- **#9 Outcome learning loop** — aligned with the RESULTS culture but large; park it.

### Scope-creep / against the thesis
- **#11 External triggers** — auto-fire breaks ask-first.
- **#8 Configurable thresholds** — softens the deterministic contract.
- **#1 Refinement-with-live-author** — there is no author at cold execution.

## What ChatGPT got right (credit where due)

Two real signals through the generic noise: **partial execution** (#7) is a true
hole, and **stale pending capsules** (#3) is a real, if minor, hygiene gap. Both
survive contact with the actual design — provided #3 stays a flag, not a delete.

## Recommendation

Don't chase the GPT list. The sharpest backlog is the **7 capsules already queued
for this project** (atomic JSONL write, file locking, row schema v1, `doctor`,
export/import, project-local mode, strict-flag disambiguation) — you captured those
yourself at high context, against the real code. They beat anything in the brainstorm
on specificity. If you want to fold GPT's signal in, add **one** new capsule for
partial-execution state (#7) and a tiny one for the stale-pending flag (#3), then
drain the queue oldest-first.
