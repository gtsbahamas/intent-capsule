#!/bin/sh
# Surface pending intent capsules at the start of a fresh agent session.
#
# For Claude Code: wire this as a SessionStart (and optionally UserPromptSubmit)
# hook — its stdout is injected into the session as additional context, so a
# context-less session sees what work is queued for this project. See
# hooks/README.md for the settings.json snippet and the ask-first instruction.
#
# Requires `intent-queue` on PATH (see bin/intent-queue). Exits 0 and prints
# nothing when the queue is empty, so it is safe to run on every session.
exec intent-queue pickup
