# Execute ordinary model and bash steps through DBOS checkpoints

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Implement the ordinary Agent Workflow path for model calls and bash execution through DBOS steps. A Root Agent Workflow should query a deterministic model, execute ordinary bash through a DBOS step, format observations through the existing model adapter behavior, persist the trajectory, and return terminal state when the task submits or limits are exceeded.

Workflow-control operations must remain outside DBOS steps. This slice should make the non-MAS-command path durable and testable before child coordination is added.

## Acceptance criteria

- [ ] Model calls run through a DBOS step and successful model responses can be replayed by DBOS recovery.
- [ ] Ordinary bash execution runs through a DBOS step and successful command outputs can be replayed by DBOS recovery.
- [ ] Standalone MAS Commands remain routed to workflow-layer dispatch rather than into an ordinary bash step.
- [ ] The Agent Workflow preserves the high-level data flow `model message -> actions -> outputs -> model-specific observation messages`.
- [ ] `limits_exceeded` is represented as a terminal MVP state.
- [ ] Tests use deterministic model and environment doubles, not real model providers.
- [ ] Tests validate externally visible behavior: command result, observation message shape, terminal state, and saved Trajectory Artifact.

## Blocked by

- .scratch/dbos-mas/issues/01-add-mini-mas-run-isolated-cli.md
- .scratch/dbos-mas/issues/02-persist-run-directory-and-trajectory-artifact-paths.md

