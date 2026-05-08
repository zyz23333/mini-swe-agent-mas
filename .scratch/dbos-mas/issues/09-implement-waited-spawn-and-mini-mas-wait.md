# Implement Waited Spawn and `mini-mas wait` synchronization

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Implement synchronization commands for First Observable Events. `mini-mas spawn --wait` should start Child Agent Workflows and default to wait-any behavior, `mini-mas spawn --wait --timeout <seconds>` should bound only that waited-spawn wait phase, and `mini-mas wait` should let a Parent Agent Workflow wait for one workflow, all currently relevant workflows, any currently relevant workflow, or a bounded timeout.

The commands should return lightweight status and exact artifact paths, not full trajectory history.

## Acceptance criteria

- [ ] `mini-mas spawn "task A" "task B"` starts one Child Agent Workflow per repeated task argument.
- [ ] `mini-mas spawn --wait "task A" "task B"` defaults to wait-any behavior and returns when any started child sets a First Observable Event.
- [ ] `mini-mas spawn --wait --all "task A" "task B"` waits until all started children set First Observable Events.
- [ ] `mini-mas spawn --wait --timeout <seconds> "task A" "task B"` returns timeout information when no started child sets a First Observable Event before the deadline.
- [ ] `mini-mas spawn --wait --all --timeout <seconds> "task A" "task B"` returns partial ready snapshots and still-running child IDs when not all children become observable before the deadline.
- [ ] Waited Spawn timeout does not cancel, close, fail, retry, or otherwise stop started Child Agent Workflows.
- [ ] `mini-mas spawn --timeout <seconds> "task"` without `--wait` is rejected as invalid because Detached Spawn has no wait phase.
- [ ] Detached multi-spawn returns all started child workflow IDs, Run Directory, and exact Trajectory Artifact paths without waiting.
- [ ] Waited multi-spawn returns all started child metadata plus ready child snapshots and still-running child IDs.
- [ ] `mini-mas wait <workflow-id>` waits for a specific descendant First Observable Event.
- [ ] `mini-mas wait --all` gathers all currently relevant child First Observable Events.
- [ ] `mini-mas wait --any` returns when any currently relevant child sets a First Observable Event.
- [ ] `mini-mas wait --timeout <seconds>` returns bounded timeout information when children are still running.
- [ ] Waited Spawn and `mini-mas wait` wait on child DBOS events keyed by child workflow identifiers, not on `WorkflowHandle.get_result()` or final DBOS workflow completion.
- [ ] Child-to-parent observable state uses DBOS events; parent-to-child Continuation Signals and Close Signals remain DBOS messages.
- [ ] Wait results include workflow IDs, lifecycle states, latest submission or error when present, Run Directory, and exact Trajectory Artifact paths.
- [ ] Tests cover single-child and multi-child spawn, detached multi-spawn, waited spawn default wait-any, waited spawn `--all`, waited spawn wait-any timeout, waited spawn wait-all partial timeout, invalid detached spawn timeout, wait for one, `--all`, `--any`, timeout behavior, and no dedicated history/log output.

## Blocked by

- .scratch/dbos-mas/issues/08-make-child-workflows-wait-after-first-submission.md
