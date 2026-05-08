# Convert MAS coordination to async Agent Workflows

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Refactor the MAS Agent Workflow layer from synchronous DBOS workflow-control calls to async DBOS workflows and awaited DBOS workflow-control APIs. This is a prerequisite for waited spawn, first-observable waiting, Continuation Signals, Close Signals, and recursive Descendant Agent Workflow coordination.

This slice should preserve the external behavior already implemented for `mini-mas run`, `mini-mas status`, and detached `mini-mas spawn`, while changing the internal workflow-control shape so later coordination slices do not need to mix feature work with architecture migration.

## Acceptance criteria

- [ ] `root_agent_workflow` and `child_agent_workflow` are async DBOS workflows.
- [ ] MAS command dispatch, child workflow startup, status lookup, and workflow-control helpers are awaitable at the Agent Workflow layer.
- [ ] Detached Spawn still returns child Workflow Tree IDs, Run Directory, and Trajectory Artifact paths without waiting for child submission or final completion.
- [ ] Existing model query, bash execution, and trajectory persistence remain behind DBOS step boundaries.
- [ ] Workflow-control operations such as child workflow creation, waiting, DBOS events, send, and receive remain outside DBOS steps.
- [ ] Runtime startup and tests use async DBOS APIs or async-compatible wrappers where DBOS requires them.
- [ ] Tests cover the existing `mini-mas run`, `mini-mas status`, detached spawn, MAS command routing, and trajectory persistence behavior after the async refactor.

## Blocked by

- .scratch/dbos-mas/issues/05-support-detached-spawn-with-deterministic-child-ids.md
- .scratch/dbos-mas/issues/06-expose-child-status-events-through-mini-mas-status.md

