# Cached Intent Convention — Results

*Experiment run 2026-06-11. Model under test: Claude Opus 4.8 (`claude-opus-4-8`). Paraphraser: Haiku 4.5.*

## The question

Can you talk to a strong model in a **terse shorthand** (to save tokens) instead of plain English, without the model getting the instruction wrong? And does **prompt caching** make a custom shorthand worth the cost of teaching it?

This came out of a `kill-it-or-climb` pressure-test. The verdict there:

- ❌ **"Invent a brand-new symbolic language for LLMs"** — killed by research. Out-of-distribution symbol languages *hurt* comprehension; the model goes near-random on novel symbol sets.
- ❌ **"Build cache infra / a token-compressor"** — already exists (Anthropic `cache_control`, TOON, LLMLingua). Use them.
- ✅ **Crystallized kernel:** a terse, **in-distribution** intent convention (words/symbols the model already knows), defined **once in a cached prefix** so the teaching cost is paid at 10% and amortized. The cache isn't how you afford a smarter model — it's how you afford a *custom convention*.

This experiment tested whether that kernel actually holds.

## Part 1 — Cost (measured, official Claude tokenizer)

Six real intents from `plan.json`, verbose English vs the shorthand:

| | tokens |
|---|---|
| 6 intents, verbose English | 171 |
| 6 intents, convention | 61 |
| **Saving** | **110 (64% fewer)** |
| Legend (taught once) | 114 |

Break-even on the 114-token legend tax:
- **Without cache:** 6 intents (you pay the teach-tax every call).
- **With 5-min cache:** ~1 intent (legend read is 90% off, amortized across the window).

So the cache is the mechanism that makes a custom convention pay off immediately instead of after six messages. *(Note: v2/v3 quote notes, so real savings is slightly under 64%; not precisely re-measured.)*

## Part 2 — Fidelity (does the model obey it?)

### Method (why it's trustworthy)
- **Back-translation oracle:** ground truth is a randomly generated plan mutation that exists *before* the model runs. Render it → shorthand AND → English, execute both, compare output to the original. No grading-own-homework.
- **Paired arms** (same mutation both ways) → headline is the *delta*, tested with **McNemar**.
- **n=120 mutations, k=3 runs each** (flake), **Wilson 95% CIs**, adversarial bucket for loud-fail, real ids + collision-prone notes from `plan.json`.
- English arm paraphrased by a **different** model (Haiku) so it can't share the renderer's blind spot.

### The trajectory (all on the identical shared dataset)

| Grammar | Convention | English | Delta | Significant? |
|---|---|---|---|---|
| **v1** (naive) | 75.0% [66.6, 81.9] | 90.8% | −15.8pt | **yes**, p<0.001 |
| **v2** (quoted notes, free `+new`) | 86.7% [79.4, 91.6] | 99.2% | −12.5pt | **yes**, p<0.001 |
| **v3** (`x`→`rm`) | **95.0%** [89.5, 97.7] | 96.7% | **−1.7pt** | **NO**, p=0.69 |

Paired convention-vs-itself across versions:
- v1→v2: **23 fixed, 9 broke** (p=0.02)
- v2→v3: **10 fixed, 0 broke** (p=0.002)

**v3 reaches parity with plain English** (gap not statistically significant) at ~64% fewer tokens.

### What each fix addressed (failures were bugs, not comprehension limits)

| Bug | Symptom | Fix | Result |
|---|---|---|---|
| Delimiter collision | `;`/`@`/`<`/`>` inside a note broke parsing | quote notes `:"..."`, newline-separate batches | collision failures 69% → 12% (residual is edge cases); notes verbatim 63% → 98% |
| Over-eager id guard | `+new` with a fresh id rejected as "unknown id" | exempt `new` from the unknown-id check | bucket 13 → 0; also lifted English (it tripped the same guard) |
| Mis-grounded op token | `x` (drop) read as "done" — wrong direction | rename drop `x` → `rm` | 8 misparses → 0; reached parity |

### The final residual is the model being *right*
5 of v3's 6 remaining "failures" are the model correctly **refusing degenerate inputs** the generator created (a node blocking itself). The ground truth was wrong, not the model. True fidelity is effectively at English's level.

## Verdict

The crystallized kernel holds, fully:
1. **Cheaper** — ~64% fewer tokens (official tokenizer).
2. **Cache pays from message one** — break-even math.
3. **Parity fidelity** — 95.0% vs 96.7% English, p=0.69, at n=120/k=3.

The "new language" stayed dead. The **cached in-distribution convention** is real and measured.

## Honest caveats (do not skip)

- **Adversarial safety did not improve** — loud-fail 94% (v1) → 75% (v2) → 69% (v3). Relaxing the id guard to stop killing legit `+new` also made the model more permissive on malformed input. ~31% of garbage lines get executed instead of rejected. **Production needs a deterministic validation layer in code** *before* applying any mutation — do not trust the model for this. **This now exists** as `strict_validate()` in [`intent_queue.py`](intent_queue.py): a stdlib-only (no LLM, no network) gate that deterministically rejects the four adversarial-bucket modes — self-dep, unknown-id (vs a supplied plan), op-char-id, duplicate-id — wired into `validate --strict --plan`, a `--strict` gate on `next`/`pickup`, and `add`; tested in [`tests/`](tests/). It is targeted at those four modes, not a full grammar linter (invalid status/owner vocab and unknown ops stay out of scope), so it does not "fix" the 69% loud-fail number — it removes the model from the safety decision for the modes that matter.
- **Scope:** parity established for Opus 4.8, plan-mutation intents, n=120, one seed. Other models/domains need a re-run (the harness does it with one flag).
- **Token saving** for v2/v3 is slightly under the v1 64% figure (note quoting), not precisely re-measured.

## Methodology lessons (the transferable part)

1. **A small all-green test fools you.** 6/6 by hand → 75% at n=120. A test only counts if it can prove you wrong. Cherry-picked happy paths hide the failures.
2. **A good test diagnoses, it doesn't just score.** The value was localizing *named bugs*, not the number.
3. **Fix one named thing, re-run the identical dataset.** Each fix's effect was isolated and paired-tested. v2→v3 had zero regressions because the change was surgical.
4. **The model can be smarter than your ground truth.** Budget for that when grading.

## Files & re-run

```
harness.py            # the plan-ops fidelity harness (grammar v1/v2/v3, dataset save/load, stats)
intent_capsule.py     # the implementation-intent fidelity harness (Part 3)
example_plan.json     # synthetic plan the harness reads (override with PLAN_PATH=your_plan.json)
tests/                # stdlib unittest suite for the deterministic strict validator
report_*clean.txt     # per-grammar summary (generated)
results_*clean.json   # full per-case results + all failures (generated)

# run the deterministic-validator tests (no API key, no deps):
python3 -m unittest discover -s tests

# re-run the plan-ops grammar test:
export ANTHROPIC_API_KEY="sk-ant-..."
# first run pins a dataset (seed-deterministic) so grammar versions stay comparable:
python3 harness.py --grammar v3 --k 3 --save-dataset ds_shared.json --tag v3clean
# later runs reuse the SAME dataset:
python3 harness.py --grammar v3 --k 3 --load-dataset ds_shared.json --tag v3clean

# re-run the implementation-intent test (Part 3):
python3 intent_capsule.py
```

## Side-finding worth keeping

**Opus 4.8 (`claude-opus-4-8`) has deprecated the `temperature` parameter** — sending it returns HTTP 400 `"temperature is deprecated for this model"`. Run it at native sampling.

---

# Part 3 — Extending the convention to IMPLEMENTATION intent

The first experiment encoded *plan-ops* (done/new/edit/deps). This one tests whether the convention can carry *implementation intent* (richer, nuanced) through a cold replay — the real use case: capture intent at peak context, queue it, execute it in a fresh context-less session.

**Method** (`intent_capsule.py`): for each of 12 implementation intents — author a detailed reference spec at full context (Opus) → compress it two ways at **equal word budget** (v-intent convention vs terse prose) → **cold-replay** each → judge the reconstruction vs the reference on 5 dimensions (what/where/constraints/acceptance/nuance).

**Result (equal budget, n=12):**

| | Convention | Prose |
|---|---|---|
| Fidelity (/10) | **10.00** | 9.67 |
| Head-to-head | **3 wins, 0 losses**, 9 ties | — |
| Capsule tokens (mean) | 400 | 283 |
| Weak dimensions | none (2.0 across) | **where 1.83, acceptance 1.83** |

**The finding flips the reason to use the convention.** For implementation intent it does **not** save tokens (~40% *more* than prose, because the field scaffolding isn't free). Its value is **completeness / anti-omission**: terse prose, told to be brief, silently drops *where the code goes* and *what done looks like*. The convention's labeled fields are a checklist that refuses those omissions.

| | plan-ops | implementation intent |
|---|---|---|
| Convention vs prose fidelity | parity (NS) | convention ≥ prose (3–0) |
| Tokens | convention 64% cheaper | convention ~40% more |
| **Why use it** | **compression** | **completeness** |

*Caveats:* judge scores saturate near 10 (modest discrimination), n=12, single judge model, short features. The edge is directional (3–0, perfect dimensions), not a chasm.

# Part 4 — Capture-to-queue tool

`intent_queue.py` (installed as `intent-queue` on PATH) is the capture half of the workflow:

```
btw authors a v-intent capsule at peak context → copy (C) →
intent-queue add  (reads clipboard, VALIDATES, queues) →
fresh session: intent-queue pickup / next  (drains it cold) → intent-queue done <id>
```

The anti-omission finding is enforced as a **contract**: `add` rejects any capsule missing `do:` or an acceptance `=:` *at capture time*, while context is fresh and the gap is cheap to fix — instead of discovering the silent gap cold, weeks later. Required: `id, do, =`. Recommended (warn): `in, why`. Queue is JSONL at `~/.claude/intent-queue.jsonl` (override `INTENT_QUEUE`). Lifecycle verified end-to-end: validate / add / reject / list / pickup / next / done.

**Auto fresh-session pickup — DONE (rode the existing hook).** `plan-to-context.py` was *already* wired to `SessionStart` + `UserPromptSubmit` (it's what surfaces the plan every turn) and already appends extra subsections to the reliably-surfaced `## Plan` channel (it does this for review comments). Added `gather_intent_queue()` there — three fail-safe edits — so pending capsules surface on every fresh session and every prompt. No new hook. Verified: before (plan only) → `add` → after (queue subsection appears), plan intact, no-queue path safe.

**Still to build:** the `btw`→capsule encoding step (have `btw` emit the v-intent grammar directly). This is itself queued as a dogfood capsule `btw-capsule-encoder`.
