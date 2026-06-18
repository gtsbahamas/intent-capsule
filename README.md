# intent-capsule

Capture work intent at peak context, encode it in a terse convention an LLM already understands, and replay it cold in a later (or different) context-poor session — without the silent omissions that kill handoffs.

**One line:** catch your smartest moment in a bottle so a forgetful (or brand-new) executor can finish the job right.

---

## The problem

The best understanding of any piece of work exists at one moment: peak context, in the head of whoever is deep in it. That understanding then dies two ways:

- It **rots** — you come back next week and you've forgotten which detail was load-bearing.
- It **can't travel** — someone else (or a fresh AI session after a `/clear`) has to do it and can't read your mind.

A normal note doesn't fix this, because people told to "be brief" silently drop the two things that matter most: **where the work goes** and **what done looks like**.

## The idea

A capsule is a note with **labeled boxes you're not allowed to leave blank**. It's written in a terse shorthand of words/symbols the model already knows (in-distribution — a brand-new symbol language was tested and *hurts* comprehension), and the legend is taught once in a cached prefix so the teaching cost is paid at a ~90% discount.

```
@<id>  do: <one-line: what to build>   in: <files/layer>   needs: <capsule-ids>   group: <label>   on: <provenance>
!: <hard constraint>   ~: <soft pref>   ?: <gate>   =: <acceptance>   why: <the nuance>
```

- **Required:** `id`, `do`, and at least one `=` (acceptance). The queue *rejects* a capsule missing these — at capture, while context is fresh and the gap is cheap to fix.
- **Recommended:** `in`, `why`.
- Repeatable: `!`, `~`, `=` (one rule/criterion per line). Single: `do`, `in`, `on`, `needs`, `group`, `?`, `why`.

### Fields

| Field | Role | Notes |
|---|---|---|
| `do:` | What to build (required) | One line. |
| `in:` | Files or layer the work lives in | Recommended. |
| `needs:` | Space/comma-separated capsule ids this capsule depends on | **Gates surfacing** — a capsule stays hidden in `next`/`pickup` until all its `needs:` ids are `done`. |
| `group:` | Organizational label | `pickup` prints a per-group progress rollup, e.g. `shipsafe — 4/10 done (2 ready, 4 blocked)`. |
| `on:` | Provenance prose | Context the executor needs ("what to know before starting"). **Not gated** — does not block surfacing. |
| `!:` | Hard constraint | Repeatable. |
| `~:` | Soft preference | Repeatable. |
| `?:` | Gate/prerequisite question | |
| `=:` | Acceptance criterion | Repeatable (required ≥ 1). Attested one-for-one by `done --proof`. |
| `why:` | The nuance | Recommended — load-bearing context that prose drops. |

See [`examples/example-capsule.txt`](examples/example-capsule.txt) for a full one.

## Why it works (measured, not vibes)

Two regimes, one mechanism — depends on whether the intent is simple or rich (full method + stats in [`RESULTS.md`](RESULTS.md)):

| Intent type | Convention vs plain English | Tokens | Why use it |
|---|---|---|---|
| **Simple plan-ops** | 95.0% vs 96.7% fidelity — statistical parity (p=0.69) | **~64% fewer** | **compression** |
| **Rich implementation** | 10.0/10 vs 9.67, won head-to-head 3–0 (9 ties) | ~40% *more* | **completeness** |

For rich intent the convention costs *more* tokens — and that's the point. Terse prose's weak dimensions were exactly `where` (1.83/2) and `acceptance` (1.83/2); the labeled fields are a checklist that refuses those omissions. **Proof point:** one of these capsules was authored at peak context and built correctly by a later "stranger" session that had zero memory of writing it.

> The instinct is "shorthand = save tokens." For *rich* intent that's wrong — prose is shorter. The win is **completeness**. Lead with that.

## The honest caveat (don't skip)

**The model is not the safety layer.** ~31% of malformed/garbage capsule lines get executed rather than rejected, so any pipeline that runs capsules automatically needs a **deterministic code-level validator** *before* applying. That validator now exists: `strict_validate()` in [`intent_queue.py`](intent_queue.py) (stdlib-only, no LLM, no network) deterministically rejects the four adversarial-bucket modes — self-dep, unknown-id (against a supplied plan), op-char-id, and duplicate-id. Wired in three places: `validate --strict-planops --plan plan.json` (nonzero exit on violation), a `--strict-planops` gate on `next`/`pickup` (an unattended pipeline refuses a bad capsule without burning it), and reused by `add`. (`--strict` remains a back-compat alias.) Covered by [`tests/`](tests/). It is named `--strict-planops`, not `--strict`, on purpose: it is a *targeted* gate for those four **plan-ops** modes — **not** a full capsule lint and **not** a v-intent completeness check (required-field completeness is always checked separately). Invalid status/owner vocab and unknown ops are out of scope, by design. The `done` gate is still an *attestation* (the executor states how each `=` was met), not a verifier — it forces engagement, it doesn't guarantee truth. Numbers are Opus-class, one seed, n=12–120: directional, not a chasm.

---

## Install

Pure Python 3 standard library, no dependencies (the experiment harness needs `anthropic`; the tool itself does not).

```bash
git clone <this-repo> intent-capsule
cd intent-capsule
# put the CLI on your PATH:
ln -s "$PWD/intent_queue.py" ~/bin/intent-queue   # or: alias intent-queue="python3 $PWD/intent_queue.py"
```

The queue is a JSONL file. Default `~/.claude/intent-queue.jsonl`; override with `INTENT_QUEUE=/path/to/queue.jsonl`.

### Or install as a Claude Code plugin (zero-config surfacing)

This repo **is** a Claude Code plugin. Installing it auto-wires the surfacing hook and ships the ask-first skill, so a fresh session shows pending capsules and offers to drain them with no manual `settings.json` edits:

```
/plugin marketplace add gtsbahamas/intent-capsule
/plugin install intent-capsule@gts-plugins
```

The plugin's `SessionStart`/`UserPromptSubmit` hooks run `intent-queue pickup` via `${CLAUDE_PLUGIN_ROOT}`, and the `/intent-capsule` skill carries the capture/drain lifecycle and the ask-first rule. For frequent capture you'll still want the CLI on your PATH (above) so `intent-queue add` is one word.

#### Verify your install

After `/plugin install`, confirm it actually loaded:

1. **Plugin enabled** — run `/plugin` and check `intent-capsule` shows as installed/enabled.
2. **Skill present** — type `/intent-capsule`; the skill should be offered.
3. **Surfacing works** — queue a throwaway capsule, then start a new session (or send any prompt) and confirm the `## Intent Queue` block appears in context:
   ```bash
   printf '@verify-test\ndo: confirm the plugin surfaces capsules\n=: the pickup block shows this id\n' \
     | INTENT_QUEUE=/tmp/iq-verify.jsonl intent-queue add --source "$(basename "$PWD")"
   INTENT_QUEUE=/tmp/iq-verify.jsonl intent-queue pickup    # should list verify-test
   rm /tmp/iq-verify.jsonl
   ```
   (Drop the `INTENT_QUEUE=...` overrides to test against your real queue at `~/.claude/intent-queue.jsonl`.)

If the skill is missing or the block never appears, it's almost always a manifest path or a `python3`-not-found issue — check `/plugin` for load errors and that `python3` is on PATH.

## Usage — the lifecycle

```bash
# 1. At peak context, author a capsule (see examples/) and validate it:
intent-queue validate --file my-capsule.txt

# 2. Queue it (reads --file, else stdin, else clipboard via pbpaste). REJECTS if incomplete:
intent-queue add --source my-project < my-capsule.txt

# 3. In a FRESH session, see what's waiting, then drain the oldest cold:
intent-queue pickup
intent-queue next                 # oldest pending -> in_progress, prints the capsule

# 4. When done, ATTEST each acceptance criterion (one --proof per =, in order):
intent-queue done csv-export --proof "=[1] verified: two filters -> only matching rows" \
                             --proof "=[2] header order matches screen, hidden cols excluded" \
                             --proof "=[3] 50k export, button disabled w/ progress, no freeze"
```

Other commands: `list [--status pending|active|all]`, `progress <id> --proof "=[i] ..."` (record partial per-criterion progress without closing), `drop <id> --yes`, `reap [--older-than MIN] [--yes]`, `export [--file F]` / `import [--file F] [--force]` (backup + migration), `doctor` (read-only install diagnostic).

### Where the queue lives (marker-gated project-local)

By default the queue is global (`~/.claude/intent-queue.jsonl`). A repo opts into **project-local** storage by creating a `.intent-capsule/` directory — then its capsules live in `<repo>/.intent-capsule/queue.jsonl` and stay isolated from every other project. Resolution precedence (explicit, by design):

1. `INTENT_QUEUE=/abs/path` — explicit override, wins.
2. `INTENT_QUEUE_GLOBAL=1` — force the shared global queue.
3. nearest ancestor with a `.intent-capsule/` dir → `<repo>/.intent-capsule/queue.jsonl`.
4. global `~/.claude/intent-queue.jsonl` — default for repos **without** the marker (unchanged).

Existing global capsules are **never auto-migrated** when you add the marker — `pickup` detects them and prints the `export`/`import` commands to move them deliberately. `intent-queue doctor` reports which mode is active.

### The contract is enforced at both ends
- **Capture:** `add` refuses a capsule missing `do:` or acceptance `=:`.
- **Completion:** `done` refuses to close a capsule with criteria unless you attest *each one* — it's not a rubber-stamp.
- **Crash safety:** a capsule drained but never finished is detectable as an **orphan** (`in_progress` past a threshold) and resurfaces via `reap` (or auto-reclaims on the next `next`), so captured work survives a crashed executor, not just a forgotten one.

## Agent integration (the interesting part)

The payoff is a fresh AI session **surfacing pending capsules on its own** and asking before it acts. The generic pattern: have your agent's session-start hook run `intent-queue pickup` and inject the output into context, with an instruction like:

> If there are pending capsules for this project, ask the user whether to drain the oldest (`intent-queue next`) before starting new work. Ask first — never auto-run. Don't `drop` a capsule you don't understand.

`pickup`/`next` are project-scoped by default (`--source` / current dir basename) so a fresh session only sees *this* project's capsules; `--all` crosses projects. The queue is global on disk so capsules can hand off *between* projects.

## Reproduce the experiment

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# plan-ops fidelity (compression regime). First run pins a seed-deterministic dataset:
python3 harness.py --grammar v3 --k 3 --save-dataset ds_shared.json --tag v3
# point it at your own plan instead of the synthetic one:
PLAN_PATH=your_plan.json python3 harness.py --grammar v3 --k 3 --save-dataset ds.json

# implementation-intent fidelity (completeness regime):
python3 intent_capsule.py
```

## Repo layout

```
intent_queue.py      # the CLI (stdlib only) — capture / validate / queue / pickup / next / done / reap + strict_validate()
tests/               # stdlib unittest suite for the deterministic strict validator
CONCEPT.md           # the concept: explain-like-I'm-10, the mechanism, where it generalizes
RESULTS.md           # the experiment: cost math, fidelity stats, caveats, methodology lessons
harness.py           # plan-ops fidelity harness (grammar v1/v2/v3, McNemar, Wilson CIs)
intent_capsule.py    # implementation-intent fidelity harness (author -> encode -> cold replay -> judge)
example_plan.json    # synthetic plan the harness reads (override with PLAN_PATH)
examples/            # a complete example capsule
bin/intent-queue     # PATH wrapper (symlink onto your PATH)
.claude-plugin/      # Claude Code plugin manifest
hooks/               # hooks.json (plugin auto-wiring) + a standalone hook + integration guide
skills/intent-capsule/  # the /intent-capsule skill (capture/drain lifecycle, ask-first doctrine)
```

## Where it generalizes

The discriminator is always: **a context-rich author, a later context-poor executor, and silent omission as the dominant failure mode.** Beyond AI handoff (the only empirically-tested case), the same shape fits clinical/on-call shift handover, CI/CD infra-as-intent, support tickets surviving reassignment, cold onboarding runbooks, and long-horizon decision memory (where `why:` is load-bearing). See [`CONCEPT.md`](CONCEPT.md) for the full table.

## License

MIT — see [`LICENSE`](LICENSE).
