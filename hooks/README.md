# Agent integration

The payoff of the queue is a **fresh session surfacing pending capsules on its own and asking before it acts**. Two pieces: a hook that *surfaces*, and an instruction that makes the agent *ask first*.

## 1. Surface on session start (Claude Code)

`session-start-pickup.sh` runs `intent-queue pickup` and prints the pending capsules for the current project. Claude Code injects a hook's stdout into the session as context.

Add to `~/.claude/settings.json` (or a project `.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "intent-queue pickup" } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "intent-queue pickup" } ] }
    ]
  }
}
```

(You can point at `hooks/session-start-pickup.sh` instead of `intent-queue pickup` directly — same effect.) `pickup` prints nothing and exits 0 when the queue is empty, so it is safe on every event. It is project-scoped by default (basename of `CLAUDE_PROJECT_DIR` / cwd), so a session only sees *this* project's capsules.

## 2. Make the agent ask first (don't auto-run)

Surfacing alone isn't enough — the agent should *offer*, never silently execute. Put an instruction like this in your `CLAUDE.md` (or the system prompt of whatever agent you use):

> If the injected context shows pending intent capsules for this project, ask the
> user whether to drain the oldest (`intent-queue next`) before starting new work.
> Ask first — never auto-run. When you finish one, attest each acceptance
> criterion via `intent-queue done <id> --proof ...`. Never `drop` a capsule you
> don't understand — read CONCEPT.md / RESULTS.md first.

## Other agents

Nothing here is Claude-specific except the `settings.json` wiring. Any agent with a session-start or pre-prompt hook can run `intent-queue pickup` and inject the output; the ask-first instruction goes wherever that agent reads standing instructions.
