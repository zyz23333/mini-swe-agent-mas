# Support Detached Spawn with deterministic Child Agent Workflow IDs

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Implement `mini-mas spawn "task"` inside a Parent Agent Workflow as a Detached Spawn. The command should start a Child Agent Workflow through the child workflow queue, return immediately to the parent with child identifiers and artifact paths, and use deterministic Workflow Tree IDs so DBOS recovery does not create duplicate descendants.

This slice should make one parent-to-child delegation path work end to end without waiting for the child submission.

## Acceptance criteria

- [ ] A Parent Agent Workflow can emit `mini-mas spawn "task"` as a Standalone MAS Command.
- [ ] Detached Spawn starts a Child Agent Workflow through a DBOS queue for child-agent concurrency control.
- [ ] The command returns immediately with child Workflow Tree ID, Run Directory, and Trajectory Artifact path.
- [ ] Child Workflow Tree IDs append deterministic `-cNNN` segments to the parent workflow ID.
- [ ] Replaying or recovering the parent spawn path does not create duplicate child workflow IDs for the same logical spawn.
- [ ] The child belongs to the same Run Directory as the Root Agent Workflow.
- [ ] Tests cover detached spawn output, queue usage, deterministic child IDs, and artifact path visibility.

## Blocked by

- .scratch/dbos-mas/issues/02-persist-run-directory-and-trajectory-artifact-paths.md
- .scratch/dbos-mas/issues/03-parse-and-reject-non-standalone-mas-commands.md
- .scratch/dbos-mas/issues/04-execute-model-and-bash-steps-through-dbos-checkpoints.md

