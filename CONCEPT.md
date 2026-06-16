# The Intent Capsule Encoder

## Explain like I'm 10

Imagine you build the coolest LEGO spaceship ever. Right now, your brain knows *everything* about it: which secret button opens the cockpit, which red brick is actually holding the whole wing on, and what you still need to finish.

Two bad things always happen. First, **you forget**: next week you pick it up and go "...wait, what was this button for?" Past-you was a genius; today-you is lost. Second, **someone else can't help**: your friend wants to finish it for you, but they can't see inside your head.

So you leave a note. But normal notes are terrible, because people always forget to write down the boring-important stuff. So instead of a messy note, you use a **form with labeled boxes you're not allowed to leave blank**:

- 📦 **What** am I making?
- 📍 **Where** does it go?
- 🚫 **Never** do this rule
- ✅ **How I'll know** it's actually done

Those boxes are a checklist that *won't let you forget* the parts everyone skips. That's the magic: not that the note is short, but that it refuses to leave a blank. You write the boxes in a tiny shorthand, and the first time you explain what the code means (the key). After that everybody already knows the key, so every future note can be teeny but still say everything.

Then later, a totally fresh person, or a fresh version of an AI after its memory gets wiped, picks up the note and just *does it right*. No questions needed, because every box is filled in. And the best part: this already really happened. One of these notes got built perfectly by a "stranger" session that had zero memory of writing it. The note worked. That is the whole idea: catch your smartest moment in a bottle so a forgetful or brand-new person can still finish the job.

## Concept

The best understanding of any piece of work exists at a single moment: peak context, in the head of the author who is deep in it. That understanding then fails in one of two ways. It **rots** (the author comes back later and has forgotten) or it **cannot travel** (a different executor has to do the work and cannot read the author's mind). The intent capsule preserves that understanding portably. You capture intent at peak context, encode it in a terse convention the model already understands (in-distribution words and symbols, not a new symbol language, which research killed because novel symbol sets push comprehension toward random), cache the legend once so the teaching cost is paid at a 90% discount and amortized, then replay it cold in a later or different context-poor session.

## Approach

The convention is an **anti-omission contract**, and that is the whole point for rich intent. Terse prose, told to be brief, silently drops the two things that matter most: *where the work goes* and *what done looks like*. At equal word budget on implementation intent (n=12, single judge), the convention scored 10.00/10 fidelity vs prose at 9.67 and won the head-to-head 3 to 0 with 9 ties, while prose's weak dimensions were exactly `where` (1.83) and `acceptance` (1.83) and the convention had no weak dimension. It does this not by being shorter (for rich intent it runs ~40% *more* tokens than prose, because the labeled fields are not free) but by being a checklist that refuses the silent gap. That contract is enforced at **both ends of the capsule's life**. At capture, the queue rejects any capsule missing `do:` or a non-blank acceptance `=:` while context is fresh and the gap is cheap to fix, rather than discovering the hole cold weeks later. At completion, `done` is **acceptance-gated**: a capsule that carries criteria cannot be rubber-stamped closed — the executor must attest, against the `=:` list it is shown, how each was met, and that attestation is recorded on the capsule. This is a deliberate *attestation*, not a verifier: it forces the executor to engage the criteria instead of silently flipping a flag, but the model can still attest falsely, so it is a discipline, not a guarantee (the same reason the adversarial-input caveat below still stands). And because an executor can die mid-build, a capsule drained but never finished is not lost: it is detectable as an **orphaned in-progress** item and resurfaces to the queue rather than vanishing — so "captured work survives a context-less executor" holds even when that executor crashes, not only when it forgets. Pickup is **ask-first** (surface the capsule, ask before executing, never auto-run) and **self-orienting**: the surfacing tells a stranger session what the system is and warns it not to discard capsules it does not understand, so captured work survives a context-less executor. For plan-ops intent the same convention instead buys compression: 95.0% fidelity vs 96.7% English (p=0.69, statistical parity) at ~64% fewer tokens. Two regimes, one mechanism: **compression where the intent is simple, completeness where it is rich.** *(Measured on Opus 4.8, one seed; adversarial inputs still need a deterministic code-level validator, since ~31% of malformed lines get executed rather than rejected. The model is not the safety layer.)*

## Where it fits

The discriminator is always the same shape: **there is a context-rich author and a later context-poor executor, and silent omission is the dominant failure mode.** If the author and executor are the same person in the same moment, you do not need this. If the failure mode is something other than dropped context (e.g. raw compute), this does not help.

| # | Domain | Failure mode without it | Fit discriminator |
|---|--------|-------------------------|-------------------|
| 1 | **AI-agent handoff across `/clear` and across projects** | A fresh session loses the author session's understanding and either re-derives it expensively or does the wrong thing. | **Proven here:** the `btw-capsule-encoder` capsule was authored at peak context and built correctly by a later stranger session with no memory of writing it. Fits when work spans context resets. |
| 2 | **Human shift / on-call / clinical handover** | Nuance and the "why" are lost person-to-person; the incoming person acts on an incomplete picture. | Fits when handoff is verbal/ad-hoc and the receiver cannot re-interview the sender. (Reasoned extension, not measured here.) |
| 3 | **CI/CD and infra-as-intent** | An under-specified job/change spec runs anyway and breaks something, because nothing checked it was complete before applying. | Fits when a spec is executed by automation. Pairs with the contract idea: a capsule that rejects itself if incomplete. Requires the deterministic validator the caveats demand. |
| 4 | **Support ticket to resolution, surviving reassignment** | A reassigned agent loses the prior agent's diagnosis and restarts from zero. | Fits when ownership changes mid-resolution and the "what was already ruled out" must travel. (Reasoned extension.) |
| 5 | **Onboarding runbooks executed cold** | A newcomer (human or AI) hits steps that assume context they do not have and silently skip the "how you know it worked." | Fits when the writer is expert and the runner is not, and acceptance criteria are the usual omission. (Reasoned extension.) |
| 6 | **Long-horizon project decision memory** | The *why* behind a choice evaporates before anyone needs it again; future-you reverses a deliberate decision by accident. | Fits when the rationale must outlive the author's memory. The `why:` field is the load-bearing part here. (Reasoned extension.) |
| 7 | **Cross-tool automation, executor unknown at capture** | The capturing tool cannot know which downstream tool/agent will run the intent, so it under-specifies. | Fits when the convention is executor-agnostic by design and the executor is chosen after capture. (Reasoned extension.) |
| 8 | **Compliance / change-intent records** | The recorded action lacks the intent behind it, so an auditor later cannot reconstruct *why* it was done. | Fits when the "why" must outlive the author for accountability, not just execution. (Reasoned extension.) |

*Only domain 1 is empirically tested in this experiment. Domains 2 through 8 share the discriminator and are reasoned extensions, not measured claims. Full evidence: [`RESULTS.md`](./RESULTS.md).*

---

*Updated 2026-06-13: the anti-omission contract now bookends the capsule lifecycle — `done` is acceptance-gated (attest, don't rubber-stamp) and orphaned in-progress capsules resurface via `reap`. The completion gate is an attestation, not verification; adversarial inputs still need the deterministic code-level validator the caveats above demand.*
