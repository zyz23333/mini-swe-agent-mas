# Record MAS deep Module refactor map

Status: needs-triage
Category: enhancement
Type: HITL

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Record a short architecture refactor map for the current **Agent Workflow** implementation before moving code. The map should name the intended deep **Modules**, their **Interfaces**, and the **Seams** where DBOS workflow-control, **MAS Command Interception**, **Direct Child Authority Policy**, **First Observable Events**, and **Remote Interactive Agent** continuation behavior belong.

This issue is a design confirmation slice. It should preserve the current MAS MVP semantics and make later AFK refactors explicit enough that agents do not invent broader **Coordination Authority Models**, extra command fallbacks, or new DBOS behavior while reducing `workflows.py`.

## Acceptance criteria

- [ ] A concise design note exists under `.scratch/dbos-mas/` or `docs/adr/` describing the target deep **Modules** and their **Interfaces**.
- [ ] The note explicitly preserves **MAS Command Interception**, **Direct Child Authority Policy**, **Child Status Events**, **First Observable Events**, **Continuation Signals**, and **Close Signals**.
- [ ] The note states that DBOS workflow-control operations remain in async **Agent Workflow** code and that model calls, bash execution, and trajectory persistence remain DBOS steps.
- [ ] The note calls out which future behavior is out of scope for this refactor, including **Authority Grants**, **Workspace Isolation**, and Operation Ledger policy.
- [ ] No production code behavior changes in this slice.

## Blocked by

None - can start immediately
