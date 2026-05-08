# Implement Waited Spawn and `mini-mas wait` synchronization

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Implement synchronization commands for first observable child submissions. `mini-mas spawn --wait` should start Child Agent Workflows and wait for first submissions, while `mini-mas wait` should let a Parent Agent Workflow wait for one workflow, all currently relevant workflows, any currently relevant workflow, or a bounded timeout.

The commands should return lightweight status and exact artifact paths, not full trajectory history.

## Acceptance criteria

- [ ] `mini-mas spawn --wait` waits for first observable child submissions, not final workflow completion.
- [ ] `mini-mas wait <workflow-id>` waits for a specific descendant submission or terminal status.
- [ ] `mini-mas wait --all` gathers all currently relevant child submissions or terminal statuses.
- [ ] `mini-mas wait --any` returns when any currently relevant child produces a submission or terminal status.
- [ ] `mini-mas wait --timeout <seconds>` returns bounded timeout information when children are still running.
- [ ] Wait results include workflow IDs, lifecycle states, latest submission or error when present, Run Directory, and exact Trajectory Artifact paths.
- [ ] Tests cover waited spawn, wait for one, `--all`, `--any`, timeout behavior, and no dedicated history/log output.

## Blocked by

- .scratch/dbos-mas/issues/07-make-child-workflows-wait-after-first-submission.md

