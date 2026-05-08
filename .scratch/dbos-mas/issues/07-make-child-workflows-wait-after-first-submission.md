# Make Child Agent Workflows wait after first submission

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Make a Child Agent Workflow enter `waiting_for_parent` after producing its first submission. The child should not terminate immediately after a submission; instead, it should publish lightweight status and wait for either a Continuation Signal or a Close Signal from its Parent Agent Workflow.

This slice should prove the Remote Interactive Agent lifecycle up to first submission and waiting state.

## Acceptance criteria

- [ ] A Child Agent Workflow records its first submission as `latest_submission`.
- [ ] After first submission, the child enters `waiting_for_parent` rather than terminating.
- [ ] The Parent Agent Workflow can observe the child's waiting state through `mini-mas status`.
- [ ] The child's Trajectory Artifact includes the submitted output and remains available at the deterministic artifact path.
- [ ] Error and `limits_exceeded` paths publish appropriate terminal or latest error status.
- [ ] Tests cover first submission, transition to `waiting_for_parent`, status visibility, and trajectory persistence.

## Blocked by

- .scratch/dbos-mas/issues/05-support-detached-spawn-with-deterministic-child-ids.md
- .scratch/dbos-mas/issues/06-expose-child-status-events-through-mini-mas-status.md

