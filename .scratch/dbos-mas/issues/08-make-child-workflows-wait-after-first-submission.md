# Make Child Agent Workflows wait after first submission

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Make a Child Agent Workflow enter `waiting_for_parent` after producing its first submission. The child should not terminate immediately after a submission; instead, it should publish lightweight status, set a First Observable Event, and wait for either a Continuation Signal or a Close Signal from its Parent Agent Workflow.

This slice should prove the Remote Interactive Agent lifecycle up to first submission and waiting state.

## Acceptance criteria

- [ ] A Child Agent Workflow records its first submission as `latest_submission`.
- [ ] After first submission, the child enters `waiting_for_parent` rather than terminating.
- [ ] The child sets a First Observable Event when it first reaches `waiting_for_parent`, `failed`, or `limits_exceeded`.
- [ ] The First Observable Event payload includes workflow ID, lifecycle state, latest submission or error, Run Directory, and exact Trajectory Artifact path.
- [ ] The Parent Agent Workflow can observe the child's waiting state through `mini-mas status`.
- [ ] Child-to-parent observable state is published through DBOS events keyed by the child workflow identifier, not through child-to-parent `send`.
- [ ] Waiting for parent direction is implemented in the async Agent Workflow layer with DBOS async receive APIs, not inside a DBOS step or a blocking final-result wait.
- [ ] The child's Trajectory Artifact includes the submitted output and remains available at the deterministic artifact path.
- [ ] Error and `limits_exceeded` paths publish appropriate terminal or latest error status.
- [ ] Tests cover first submission, transition to `waiting_for_parent`, status visibility, and trajectory persistence.

## Blocked by

- .scratch/dbos-mas/issues/05-support-detached-spawn-with-deterministic-child-ids.md
- .scratch/dbos-mas/issues/06-expose-child-status-events-through-mini-mas-status.md
- .scratch/dbos-mas/issues/07-convert-mas-coordination-to-async-agent-workflows.md
