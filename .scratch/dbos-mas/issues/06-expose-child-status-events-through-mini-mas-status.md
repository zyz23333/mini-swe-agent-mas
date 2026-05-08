# Expose Child Status Events through `mini-mas status`

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Expose lightweight Child Status Events for the current Agent Workflow Tree and make them visible through `mini-mas status`. Parent Agent Workflows and external users should be able to inspect the current tree without reading full trajectories or blocking on child completion.

The status surface should include coarse lifecycle state and fast decision data such as latest submission or latest error, while keeping full history in Trajectory Artifacts.

## Acceptance criteria

- [ ] Child Status Events include coarse states such as `running`, `waiting_for_parent`, `closed`, `failed`, and `limits_exceeded`.
- [ ] `mini-mas status` reports the current Agent Workflow Tree without blocking.
- [ ] `mini-mas status <workflow-id>` reports a specific descendant when it exists.
- [ ] Status output includes workflow ID, lifecycle state, latest submission or latest error when present, Run Directory, and exact Trajectory Artifact path.
- [ ] Full history remains in Trajectory Artifacts, not DBOS events.
- [ ] Tests cover tree status, specific workflow status, latest submission/error fields, and missing workflow behavior.

## Blocked by

- .scratch/dbos-mas/issues/05-support-detached-spawn-with-deterministic-child-ids.md

