# ChatGPT / Codex Instructions

Before doing any work in this repository:

1. Read `README.md`.
2. Read `AI_WORKFLOW.md`.
3. Read `HANDOFF.md`.
4. Inspect the latest relevant commits/branch state.

Treat GitHub as shared memory with Claude. If Claude last worked on the task, resume from the latest pushed checkpoint instead of asking the user to restate recoverable context.

Before stopping, especially if context/token budget is becoming constrained, create a recoverable checkpoint: run relevant checks, commit, push, and update `HANDOFF.md` with exact next steps and current status.

Follow `AI_WORKFLOW.md` for branch naming, takeover, checkpoint, and conflict-avoidance rules.
