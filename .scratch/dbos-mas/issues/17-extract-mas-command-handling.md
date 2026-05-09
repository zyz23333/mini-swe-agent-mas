# Extract MAS Command Handling behind one Interface

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Move workflow-layer **MAS Command** handling behind one deep **Module** so the **Agent Workflow** loop no longer owns the `status`, `spawn`, `wait`, `continue`, and `close` dispatch tree directly. The loop should classify bash-shaped actions, reject non-standalone `mini-mas` usage, send standalone commands to the new command handler, and execute ordinary bash through the existing checkpointed bash step.

The new **Module** should preserve the current model-visible behavior while hiding command routing, command-specific argument parsing, and result construction behind a small **Interface**.

## Acceptance criteria

- [ ] `execute_agent_workflow_actions` still returns model-specific observation messages for standalone **MAS Commands**, invalid shell compositions, and ordinary bash actions.
- [ ] Standalone `mini-mas` commands continue to be intercepted in workflow code, not inside environment execution or DBOS steps.
- [ ] Non-standalone `mini-mas` shell compositions still return a clear model-visible correction.
- [ ] Ordinary bash actions still execute through `execute_bash_step`.
- [ ] Existing tests covering command classification, action execution dispatch, ordinary bash fallback, and model-specific observation formatting pass.

## Blocked by

- .scratch/dbos-mas/issues/16-record-mas-deep-module-refactor-map.md
