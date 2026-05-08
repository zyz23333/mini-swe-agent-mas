# Implement neutral Close Signal for Remote Interactive Agents

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Implement `mini-mas close <workflow-id>` so a Parent Agent Workflow can tell a waiting Child Agent Workflow that no further work is requested. The Close Signal must be neutral: it ends the Remote Interactive Agent without implying acceptance, rejection, cancellation, or abort.

This slice should make the waiting lifecycle complete without adding kill, cancel, retry, fork, or queue mutation commands.

## Acceptance criteria

- [ ] `mini-mas close <workflow-id>` sends a Close Signal to a waiting Child Agent Workflow.
- [ ] A child receiving a Close Signal exits with lifecycle state `closed`.
- [ ] Status and wait output describe the child as `closed` without accepted/rejected/aborted semantics.
- [ ] Closing an already terminal or unknown workflow returns a clear error or no-op response consistent with the CLI behavior chosen in this slice.
- [ ] The child's final Trajectory Artifact remains available at the deterministic artifact path.
- [ ] Tests cover close from waiting state, closed status visibility, neutral wording, and repeated or invalid close behavior.

## Blocked by

- .scratch/dbos-mas/issues/07-make-child-workflows-wait-after-first-submission.md

