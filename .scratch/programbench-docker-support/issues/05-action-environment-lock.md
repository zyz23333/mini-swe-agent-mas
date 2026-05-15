# Action Environment Lock

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Implement the per-binding Action Environment Lock that serializes ordinary bash actions targeting the same Action Environment Binding.

## Acceptance criteria

- [ ] Lock identity is derived from workspace/runtime namespace and Action Environment ID.
- [ ] Lock files live under `.mini-mas/runtime/action-environment-locks/`.
- [ ] The implementation uses a process-local lock for in-process concurrency.
- [ ] The implementation uses a POSIX file lock for cross-process concurrency.
- [ ] Same-binding bash actions are serialized by tests.
- [ ] Different-binding actions use different locks and can proceed independently at the lock API level.
- [ ] The lock is held only during one ordinary bash action.
- [ ] The lock is not a TTL lease and does not use a DBOS dynamic queue.
- [ ] Lock setup/acquisition failure maps to an execution-blocked style error.

## Blocked by

- .scratch/programbench-docker-support/issues/03-action-environment-binding-schema-local-compatibility.md

