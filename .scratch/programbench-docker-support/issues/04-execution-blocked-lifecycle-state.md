# Execution Blocked lifecycle state

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Add `execution_blocked` as a non-terminal MAS lifecycle state for Agents whose runtime dependencies are unavailable while their durable Agent context remains continuable.

## Acceptance criteria

- [ ] `LifecycleState` accepts `execution_blocked`.
- [ ] Child Status Events can report `execution_blocked`.
- [ ] First Observable Events can report `execution_blocked`.
- [ ] Parent `status` and `wait` output display `execution_blocked`.
- [ ] Runtime dependency unavailable errors can be represented without terminal `failed`.
- [ ] Invalid durable Agent Execution Config still reaches terminal `failed`.
- [ ] `recovery_required` remains reserved for uncertain external side effect replay and is not implemented as part of this slice.

## Blocked by

- .scratch/programbench-docker-support/issues/03-action-environment-binding-schema-local-compatibility.md

