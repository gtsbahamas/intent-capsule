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
@<id>  do: <one-line: what to build>   in: <files/layer>   on: <deps/ids>
!: <hard constraint>   ~: <soft pref>   ?: <gate>   =: <acceptance>   why: <the nuance>
```

- **Required:** `id`, `do`, and at least one `=` (acceptance). The queue *rejects* a capsule missing these — at capture, while context is fresh and the gap is cheap to fix.
- **Recommended:** `in`, `why`.
- Repeatable: `!`, `~`, `=` (one rule/criterion per line). Single: `do`, `in`, `on`, `?`, `why`.

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

**The model is not the safety layer.** ~31% of malformed/garbage capsule lines get executed rather than rejected, so any pipeline that runs capsules automatically needs a **deterministic code-level validator** (reject self-deps, unknown ids, etc.) *before* applying. The `done` gate is an *attestation* (the executor states how each `=` was met), not a verifier — it forces engagement, it doesn't guarantee truth. Numbers are Opus-class, one seed, n=12–120: directional, not a chasm.

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
/plugin marketplace add <your-org>/intent-capsule
/plugin install intent-capsule
```

The plugin's `SessionStart`/`UserPromptSubmit` hooks run `intent-queue pickup` via `${CLAUDE_PLUGIN_ROOT}`, and the `/intent-capsule` skill carries the capture/drain lifecycle and the ask-first rule. For frequent capture you'll still want the CLI on your PATH (above) so `intent-queue add` is one word.

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

Other commands: `list [--status pending|active|all]`, `drop <id> --yes`, `reap [--older-than MIN] [--yes]`.

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
intent_queue.py      # the CLI (stdlib only) — capture / validate / queue / pickup / next / done / reap
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
