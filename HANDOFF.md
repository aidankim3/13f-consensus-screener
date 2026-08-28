# Shared AI Handoff

active_agent: none
status: READY_FOR_NEXT_TASK
current_branch: main
latest_checkpoint: 6dbc1373a940d7f672ffd249f77e6fea606820fc

## Current Goal

No active task. This file is the shared checkpoint between Claude and ChatGPT/Codex.

## Completed

- Added bidirectional Claude ↔ ChatGPT/Codex collaboration rules in `AI_WORKFLOW.md`.

## In Progress

- None.

## Next Steps

1. The next agent should read `README.md`, `AI_WORKFLOW.md`, and this file.
2. When starting a task, set `active_agent`, `status`, `current_branch`, and `Current Goal`.
3. Keep this file updated at meaningful checkpoints and before handing off.

## Blockers / Known Bugs

- None recorded here. Consult project documentation and issues for existing product-level limitations.

## Files Touched

- `AI_WORKFLOW.md`
- `HANDOFF.md`

## Tests

- Not applicable; collaboration metadata only.

## Important Decisions

- GitHub repository state is the shared source of truth.
- Either Claude or ChatGPT/Codex may take over when the other lacks tokens/context.
- Small pushed commits are preferred so either agent can resume with minimal loss.
