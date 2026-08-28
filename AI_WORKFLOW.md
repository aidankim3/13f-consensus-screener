# AI Collaboration Workflow

This repository is designed to be worked on interchangeably by Claude and ChatGPT/Codex.
Neither agent is the permanent owner of the project. The agent with available context/tokens may continue from the latest pushed checkpoint.

## Source of truth

Use the repository state as the shared memory:

1. Git history and current branch
2. `HANDOFF.md`
3. `README.md` and project docs
4. Open issues / pull requests when present

Do not rely on private chat history that the other agent cannot see.

## Before starting work

1. Pull/fetch the latest remote state.
2. Read `README.md`, `AI_WORKFLOW.md`, and `HANDOFF.md`.
3. Inspect recent commits and any unmerged branch/PR relevant to the task.
4. Confirm the current goal, files already changed, tests, blockers, and next steps from `HANDOFF.md`.
5. Continue from the latest checkpoint instead of redoing completed work.

## Shared ownership model

- Either Claude or ChatGPT/Codex may start or resume a task.
- `active_agent` in `HANDOFF.md` means "who last worked on the task", not exclusive ownership.
- If the last agent is unavailable, rate-limited, or out of tokens/context, the other agent may immediately take over from the latest pushed checkpoint.
- Prefer small, frequent commits so an abrupt token/context limit loses as little work as possible.
- Never assume another agent can see uncommitted local changes.

## Branch convention

For non-trivial changes, prefer a dedicated branch:

- Claude: `ai/claude/<task-slug>`
- ChatGPT/Codex: `ai/codex/<task-slug>`

If taking over an existing task, continue the existing branch when safe. If there may be unknown local changes from the other agent, create a new branch from the latest pushed commit rather than overwriting work.

## Checkpoint rule

At every meaningful milestone, and especially before stopping or when token/context budget is getting low:

1. Save a working state when practical.
2. Run the relevant tests/checks.
3. Commit the current changes with a descriptive message.
4. Push the branch.
5. Update `HANDOFF.md` with the current state.
6. Commit and push the handoff update.

Do not wait until the very end to write the handoff. Keep it current enough that the other agent can resume after an unexpected cutoff.

## Handoff requirements

`HANDOFF.md` should always contain:

- active agent
- status
- current branch
- current goal
- completed work
- work in progress
- exact next steps
- blockers / known bugs
- files touched
- tests run and their results
- important design decisions
- latest checkpoint commit when known

Keep entries concise and factual. Replace stale status instead of endlessly appending chat-like notes.

## Taking over another agent's work

When resuming work left by the other agent:

1. Read `HANDOFF.md`.
2. Inspect `git log` and the latest diff.
3. Verify the current code before making assumptions.
4. Run the most relevant quick test/check if feasible.
5. Change `active_agent` in `HANDOFF.md` to yourself and continue.

Do not ask the user to repeat information already recoverable from the repository.

## Finishing a task

When a task is complete:

1. Run the relevant tests/checks.
2. Commit and push all intended changes.
3. Update `HANDOFF.md`:
   - `status: READY_FOR_NEXT_TASK`
   - summarize what was completed
   - record any remaining caveats or follow-ups
4. Merge/open a PR according to the user's normal workflow.

## Conflict avoidance

- Do not have both agents independently edit the same files on `main` at the same time.
- Use branches for parallel work.
- Before writing, check whether the remote branch moved since the last read.
- Prefer a clean handoff over duplicate implementation.

The goal is continuity: either agent should be able to stop at any checkpoint and the other should be able to resume with minimal user explanation.
