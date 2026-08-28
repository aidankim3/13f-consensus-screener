# Claude Instructions

Before doing any work in this repository:

1. Read `README.md`.
2. Read `AI_WORKFLOW.md`.
3. Read `HANDOFF.md`.
4. Inspect the latest relevant commits/branch state.

Treat GitHub as shared memory with ChatGPT/Codex. If another agent last worked on the task, resume from the latest pushed checkpoint instead of rebuilding the work from chat memory.

Before stopping, especially if token/context budget is low, create a recoverable checkpoint: test what you can, commit, push, and update `HANDOFF.md` with exact next steps and current status.

Follow `AI_WORKFLOW.md` for branch naming, takeover, checkpoint, and conflict-avoidance rules.
