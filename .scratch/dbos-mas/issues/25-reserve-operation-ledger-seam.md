# Reserve an Operation Ledger seam for DBOS step side-effect recovery

Status: needs-triage
Category: enhancement
Type: HITL

## Parent

.scratch/dbos-mas/PRD.md

## Refactor map reference

This issue must follow `.scratch/dbos-mas/issues/16-record-mas-deep-module-refactor-map.md` and any design note produced from it. Preserve the module boundaries, DBOS step/workflow-control boundaries, and out-of-scope constraints recorded there; do not invent alternate MAS module names, authority models, DBOS behavior, or command fallbacks.

## What to build

Design, but do not implement, the future **Operation Ledger** **Seam** for model query and ordinary bash side-effect recovery. The design should describe where `query_model_step` and `execute_bash_step` would pass through an operation-recording **Interface** so DBOS recovery can later distinguish started, completed, reusable, retryable, and fail-closed operations.

This issue should keep ADR-0004's warning visible: DBOS step checkpointing and `retries_allowed=False` do not provide exactly-once semantics for arbitrary model calls or bash commands.

## Acceptance criteria

- [ ] A design note identifies the future **Operation Ledger** **Interface** for model query and bash execution operations.
- [ ] The note states which data would need stable operation identifiers without choosing a final storage schema.
- [ ] The note preserves the current DBOS rule that model calls and bash execution are external side effects inside steps.
- [ ] The note explains why this slice does not implement the ledger or claim exactly-once semantics.
- [ ] No production recovery policy or persistence schema is introduced without separate approval.

## Blocked by

- .scratch/dbos-mas/issues/21-restore-mini-shaped-agent-workflow-loop.md
