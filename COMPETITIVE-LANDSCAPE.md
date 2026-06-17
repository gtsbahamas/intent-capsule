# Competitive Landscape

*Researched 2026-06-17. Sources cited inline. This is a snapshot; the space moves fast.*

## TL;DR

The general problem (preserving understanding across an AI agent's context resets, a.k.a. "context rot") is **crowded**. Multiple tools ship handoff notes, persistent memory, and terse conventions today. None of them ships the specific combination intent-capsule is built around.

Three primitives, each owned by a different competitor, never combined:

| Primitive | Who owns it today | Who's missing it |
|---|---|---|
| **Field-labeled anti-omission grammar** (refuses to leave `where` / `acceptance` blank) | Spec-driven dev (Kiro/EARS) — at *repo* granularity | Tarvos Baton (prose), Caveman (compresses, doesn't enforce) |
| **Compression via a cached terse convention** | Caveman.MD | Baton, softaworks, SDD, memory |
| **Capture-AND-completion contract** (reject incomplete at capture; acceptance-gate `done`; resurface orphans) | Nobody, combined | Everybody |

intent-capsule's differentiation is the **synthesis** plus a **measured two-regime fidelity study**, not any single primitive. We cannot prove no one has combined these (you can't prove a negative); we searched and didn't find it.

---

## The discriminator (what we actually compete in)

intent-capsule only competes where **a context-rich author hands off to a later context-poor executor, and silent omission is the dominant failure mode.** That narrows the field. Tools that solve raw recall, multi-agent routing, or output cost are adjacent, not competitors. The comparison below is organized by how close each tool sits to that discriminator.

---

## 1. Direct competitors — session handoff

### Tarvos / "the Baton" — the closest competitor

Tarvos is an open-source orchestration layer that chains fresh AI coding-agent sessions. Each outgoing agent writes a **40-line prose handoff note called the Baton** (what was completed, what comes next, gotchas) before stepping aside; the next session reads a shared plan file plus the Baton. ([Agent Wars, 2026-03-13](https://agent-wars.com/news/2026-03-13-tarvos-relay-architecture-for-building-large-projects-with-ai-coding-agents))

What it shares with us: cold-session handoff, a shared on-disk artifact, crash recovery (Tarvos reconstructs the Baton from git history if a session dies before writing it).

Where it diverges, per their own writeup:
- **Prose, not field-labeled.** No labeled sections, no schema. The 40-line cap is enforced "because a longer baton would start recreating the problem it was meant to solve" — and they explicitly concede the tradeoff: *"tight handoff notes also leave less room for capturing the contextual nuance that tends to accumulate on real-world work."* That dropped nuance is exactly the omission our anti-omission contract targets.
- **No acceptance gate on the handoff.** Tarvos has a TUI to accept/reject *merged code* before it lands on main — that gates the code, not the note. There is no "this capsule cannot close until each acceptance criterion is attested."
- **Recovery, not resurfacing.** Git-history reconstruction rebuilds a *missing note*; it is not the same as detecting an unfinished *captured item* and putting it back in a queue.

Naming caveat: search also surfaces a separate "Baton" described as a 24-section template with a 9-question self-test, spec-compliant per agentskills.io. The two may be distinct projects sharing a name; treat "Baton" as ambiguous until disambiguated.

### softaworks/agent-toolkit — `session-handoff` skill

A Claude skill that generates timestamped handoff documents (pre-filled project metadata, git history, modified files), then runs a **validation script for completeness and security**, with guidance not to finalize "if secrets are detected or the score is below 70." Supports handoff chaining (handoff-1 → handoff-2 → …). ([GitHub: softaworks/agent-toolkit](https://github.com/softaworks/agent-toolkit/tree/main/skills/session-handoff), [SKILL.md](https://github.com/softaworks/agent-toolkit/blob/main/skills/session-handoff/SKILL.md))

This is the **closest thing to our capture-side gate** — it validates before finalizing. But:
- The ≥70 gate scores **completeness and security**, not whether the capsule carries testable acceptance criteria.
- It gates **capture only.** There is no acceptance-gated *completion* and no orphan resurfacing. Once handed off, a half-built item isn't tracked back to a queue.
- The artifact is a comprehensive document, not a terse cached convention; no compression regime, no fidelity measurement.

### Claude-Handover plugin

Generates a handover document and then spawns a fresh Claude Code session with the resume command pre-loaded — "passing the baton with one command." ([heyitworks](https://www.heyitworks.tech/blog/claude-handover-context-loss-ai-agent-sessions/)) Solves the *plumbing* of continuation (auto-spawn the next session) rather than the *content contract* (refuse a blank, gate the close). Complementary, not overlapping.

---

## 2. Adjacent — terse cached conventions (our compression regime's cousin)

### Caveman.MD

The terse-convention play. Drops articles, filler, pleasantries, and hedging; ships ~4 compression levels selectable per session; claims roughly 65–75% output-token reduction "without losing task fidelity." Includes `/caveman-compress` for compressing markdown memory files and a cross-agent SQLite+FTS5+vector memory layer exposed via MCP. ([Caveman.MD guide, 2026](https://thepromptshelf.dev/blog/caveman-md-complete-guide-2026/), [getcaveman.dev](https://getcaveman.dev/))

This is intent-capsule's **compression-regime cousin** and the most important tool to be honest about, because the surface pitch ("terse cached convention for agents") sounds identical. The difference is structural:

- Caveman makes output **shorter**. It does **not refuse a blank.** There is no field-labeled grammar that won't let you omit `where` or `acceptance`. Compression without a completeness contract is exactly the failure mode our study measured: terse prose silently drops `where` (1.83/10) and `acceptance` (1.83/10).
- Caveman has **no capture gate, no acceptance-gated completion, no orphan resurfacing.** It's an output-cost tool, not a handoff-fidelity contract.
- We share the "cache the legend once, pay the teaching cost at a discount" idea. We diverge on what the convention is *for*: Caveman = fewer tokens; intent-capsule = no silent omission (and for rich intent we run ~40% *more* tokens than prose on purpose).

Note there's a `Hermes-cavemen` "Terse Mode for Hermes Agent" variant too — same family, same gap.

---

## 3. Adjacent — spec-driven development (owns acceptance criteria, wrong granularity)

Spec-driven development (SDD) is the methodology where versioned structured specs are the source of truth and code is generated against them. **Kiro** (agentic IDE) generates requirements.md (user stories in **EARS notation** — `WHEN [condition] THE SYSTEM SHALL [behavior]`), design.md, and tasks.md. Specs define goal, non-goals, **acceptance criteria**, edge cases, and release evidence before implementation. ([Augment Code: best SDD tools 2026](https://www.augmentcode.com/tools/best-spec-driven-development-tools), [Microsoft Dev Blog](https://developer.microsoft.com/blog/spec-driven-development-ai-native-engineering))

SDD is the one camp that genuinely **owns the acceptance-criteria primitive** (EARS is a real anti-ambiguity grammar). But the granularity and lifecycle differ:

- SDD specs are **repo-level, persistent, source-of-truth artifacts.** An intent capsule is a **per-task, portable, disposable handoff** that travels across sessions and even across projects/tools, then is `done`d and gone.
- SDD assumes the spec is authored up front and code conforms to it. The capsule captures intent **at peak context mid-work** and replays it cold — a different moment in the loop.
- SDD has acceptance criteria but no terse cached-legend compression regime and (to our knowledge) no measured fidelity comparison of convention vs prose at equal word budget.

The honest read: SDD and intent-capsule could **compose** (a capsule could carry an EARS-style `=:`). They are not the same product. SDD is the heavyweight "specs govern the repo" world; the capsule is the lightweight "this one handoff won't drop the ball" world.

---

## 4. Platform risk — Anthropic memory absorbs the problem

On **2026-04-23**, Anthropic put **persistent memory for Claude Managed Agents** into public beta: file-based memories on a filesystem (exportable/editable via API or Console), plus a chat-memory mode that summarizes past conversations across sessions, plus a memory tool that writes context to files so agents accumulate knowledge across sessions. Rakuten reports 97% fewer first-pass errors using it. ([Anthropic: managed agents](https://www.anthropic.com/engineering/managed-agents), [EdTech Innovation Hub](https://www.edtechinnovationhub.com/news/anthropic-brings-persistent-memory-to-claude-managed-agents-in-public-beta), [Context engineering cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools))

This is the real long-term pressure: if the platform makes cross-session recall free, does a handoff convention still matter? Our position:

- Memory is **unstructured accumulation and recall.** It carries *what happened.* It does **not** enforce that a handoff names `where` and `acceptance`, does not reject an incomplete capture, does not acceptance-gate completion, and does not resurface an orphaned in-progress item. It's a substrate, not a contract.
- The industry's own framing supports the gap: the "context dump fallacy" — *"large unstructured context transfers increase noise, degrade reasoning, and cause downstream agents to lose the decision logic behind earlier steps."* ([Fast.io 2026 handoff guide](https://fast.io/resources/ai-agent-handoff-protocol/)) More memory is not the same as a structured, gap-refusing handoff.
- Realistic outcome: the capsule **rides on top of** memory. Memory stores the legend and the capsule history; the convention is still what refuses the blank.

---

## Differentiation matrix

| Capability | intent-capsule | Tarvos/Baton | softaworks | Caveman | SDD (Kiro/EARS) | Anthropic memory |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cross-session cold handoff | ✅ | ✅ | ✅ | ➖ | ➖ | ✅ |
| Field-labeled grammar | ✅ | ❌ (prose) | ➖ (doc) | ❌ | ✅ (EARS) | ❌ |
| Anti-omission contract (refuses blank) | ✅ | ❌ | ➖ (≥70 score) | ❌ | ✅ | ❌ |
| Terse cached-legend compression | ✅ | ➖ (40-line cap) | ❌ | ✅ | ❌ | ➖ |
| Capture-side reject-if-incomplete | ✅ | ❌ | ✅ | ❌ | ➖ | ❌ |
| **Acceptance-gated completion** | ✅ | ❌ | ❌ | ❌ | ➖ | ❌ |
| **Orphan resurfacing (reap)** | ✅ | ➖ (git recover) | ❌ | ❌ | ❌ | ❌ |
| Per-task portable capsule | ✅ | ✅ | ✅ | ➖ | ❌ (repo specs) | ➖ |
| Executor-agnostic by design | ✅ | ➖ | ➖ | ✅ | ➖ | ➖ |
| **Measured two-regime fidelity study** | ✅ | ❌ | ❌ | ➖ (claims, no study) | ❌ | ❌ |

✅ = ships it · ➖ = partial/adjacent · ❌ = absent

The two rows nobody else fills: **acceptance-gated completion** and the **measured two-regime fidelity study**. The capture-AND-completion bookend (reject incomplete in, attest each criterion out, resurface orphans) is the structural claim; the study is the empirical one.

---

## Where intent-capsule is NOT differentiated (be honest)

- **Cold handoff itself is table stakes.** Tarvos, softaworks, Claude-Handover, and platform memory all do it. "We hand off across `/clear`" is not a moat.
- **Acceptance criteria exist elsewhere.** EARS/SDD got there first and more rigorously, at repo granularity. We are not inventing acceptance criteria; we are putting them on a portable per-task capsule with a completion gate.
- **Compression exists elsewhere and is more mature.** Caveman has versioned releases, an MCP memory layer, and adoption. Our compression regime is a measured side-effect, not a product.
- **The empirical edge is small-n.** See caveats.

The defensible core is narrow and specific: *the bookended anti-omission contract (capture gate + acceptance-gated completion + orphan reap) on a terse field-labeled capsule, validated by a two-regime study.* Everything else is shared with the field.

---

## Caveats on this analysis

- **Can't prove a negative.** "Not found combined anywhere" means we searched (Tarvos/Baton, softaworks/agent-toolkit, Caveman, SDD/Kiro/EARS, Anthropic memory, generic handoff-protocol writeups) and didn't find the combination. Someone may have shipped it unindexed.
- **The completion gate is an attestation, not a verifier.** The executor attests each `=:` criterion was met; the model can attest falsely. ~31% of malformed capsule lines get executed rather than rejected. The deterministic code-level validator (the queued `validator-layer` capsule) is the real safety layer; the model is not.
- **Small study.** Fidelity numbers are n=12 (rich intent) / plan-ops parity at one seed, single judge, measured on Opus 4.8. Directional, not definitive.
- **Search quota.** mgrep web quota was exhausted this session; the sweep used built-in WebSearch. Results are US-region.

---

### Sources

- [Agent Wars — Tarvos relay architecture (2026-03-13)](https://agent-wars.com/news/2026-03-13-tarvos-relay-architecture-for-building-large-projects-with-ai-coding-agents)
- [softaworks/agent-toolkit — session-handoff skill](https://github.com/softaworks/agent-toolkit/tree/main/skills/session-handoff) · [SKILL.md](https://github.com/softaworks/agent-toolkit/blob/main/skills/session-handoff/SKILL.md)
- [Claude-Handover (heyitworks)](https://www.heyitworks.tech/blog/claude-handover-context-loss-ai-agent-sessions/)
- [Caveman.MD complete guide 2026](https://thepromptshelf.dev/blog/caveman-md-complete-guide-2026/) · [getcaveman.dev](https://getcaveman.dev/)
- [Augment Code — best spec-driven dev tools 2026](https://www.augmentcode.com/tools/best-spec-driven-development-tools) · [Microsoft Dev Blog — SDD](https://developer.microsoft.com/blog/spec-driven-development-ai-native-engineering)
- [Anthropic — Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents) · [EdTech Innovation Hub — persistent memory beta (2026-04-23)](https://www.edtechinnovationhub.com/news/anthropic-brings-persistent-memory-to-claude-managed-agents-in-public-beta) · [Context engineering cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
- [Fast.io — AI Agent Handoff Protocol 2026 guide](https://fast.io/resources/ai-agent-handoff-protocol/)
