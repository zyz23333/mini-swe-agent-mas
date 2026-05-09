# Move Child Workflow spawn and wait behavior into a Child Coordination Module

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Move **Detached Spawn**, **Waited Spawn**, and `mini-mas wait` behavior into a Child Coordination **Module**. The **Module** should own deterministic child Workflow Tree ID allocation, child workflow enqueueing, child metadata, wait-any and wait-all synchronization, timeout summaries, and still-running child workflow IDs.

The workflow-layer command handler should call this **Module** instead of assembling child spawning and waiting behavior inline.

## Acceptance criteria

- [ ] `mini-mas spawn` still starts one **Child Agent Workflow** per task and returns child workflow IDs, run directory, and trajectory artifact paths.
- [ ] Child Workflow Tree IDs remain deterministic and use the existing `-cNNN` suffix behavior.
- [ ] `mini-mas spawn` remains detached by default.
- [ ] `mini-mas spawn --wait` defaults to wait-any behavior.
- [ ] `mini-mas spawn --wait --all` waits until all started children first become observable.
- [ ] `mini-mas spawn --wait --timeout` returns ready children and still-running child workflow IDs without cancelling, closing, failing, or retrying children.
- [ ] `mini-mas wait` behavior remains compatible for wait-any, wait-all, one direct child, and timeout paths.

## Blocked by

- .scratch/dbos-mas/issues/18-centralize-direct-child-authority-policy.md
- .scratch/dbos-mas/issues/19-introduce-dbos-coordination-adapter.md
