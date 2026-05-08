# Persist deterministic Run Directory and Trajectory Artifact paths

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Make `mini-mas run` create deterministic artifact locations for a Root Agent Workflow. Every MAS run should have a Run Directory scoped by the Root Workflow Tree ID, and the Root Agent Workflow should write a Trajectory Artifact to a deterministic path that can be returned to users and inspected with ordinary shell tools.

This slice should make artifact creation visible through the External MAS CLI without introducing history, logs, grep, diff, or inspector commands.

## Acceptance criteria

- [ ] Root Workflow Tree IDs use the `mas-<16hex>` form.
- [ ] `mini-mas run` creates a Run Directory under `.mini-mas/runs/<root-workflow-id>/`.
- [ ] The Root Agent Workflow writes a Trajectory Artifact under `.mini-mas/runs/<root-workflow-id>/trajectories/<workflow-id>.traj.json`.
- [ ] Repeated trajectory saves for the same workflow use the same path and safely overwrite the artifact.
- [ ] CLI output includes the Root Workflow Tree ID, Run Directory, and exact Trajectory Artifact path.
- [ ] Tests cover root ID shape, run directory path generation, trajectory artifact path generation, and CLI-visible output.

## Blocked by

- .scratch/dbos-mas/issues/01-add-mini-mas-run-isolated-cli.md

