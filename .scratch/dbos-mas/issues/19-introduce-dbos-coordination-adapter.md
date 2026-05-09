# Introduce DBOS Coordination Adapter for status and first observable events

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## Refactor map reference

This issue must follow `.scratch/dbos-mas/issues/16-record-mas-deep-module-refactor-map.md` and any design note produced from it. Preserve the module boundaries, DBOS step/workflow-control boundaries, and out-of-scope constraints recorded there; do not invent alternate MAS module names, authority models, DBOS behavior, or command fallbacks.

## What to build

Introduce a DBOS Coordination **Adapter** that owns the DBOS event and message primitives used by **Agent Workflows**. Business logic should publish **Child Status Events**, publish **First Observable Events**, wait for first observable child states, and receive or send parent-direction messages through this **Adapter** instead of directly touching DBOS event keys throughout `workflows.py`.

This should preserve DBOS constraints: workflow-control operations remain in async workflow code, while ordinary model calls, bash execution, and trajectory persistence remain DBOS steps.

## Acceptance criteria

- [ ] Status publication and **First Observable Event** publication go through the new Coordination **Adapter**.
- [ ] Waiting for first observable child states goes through the Coordination **Adapter** and still supports wait-any, wait-all, and timeout behavior.
- [ ] Parent-direction **Continuation Signals** and **Close Signals** still use DBOS workflow messages outside DBOS steps.
- [ ] `waiting_for_child` is published only as latest lightweight status and never as a **First Observable Event**.
- [ ] Waited spawn and `mini-mas wait` still wait for **First Observable Events**, not final DBOS workflow results.
- [ ] Existing status, waited spawn, wait, continuation, and close tests pass.

## Blocked by

- .scratch/dbos-mas/issues/17-extract-mas-command-handling.md
