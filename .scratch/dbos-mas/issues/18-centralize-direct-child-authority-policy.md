# Centralize Direct Child Authority Policy

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Create a deep **Module** for the **Direct Child Authority Policy**. Workflow-layer `status`, `wait`, `continue`, and `close` handling should ask this **Module** whether the current **Parent Agent Workflow** may observe, wait for, continue, or close a target **Child Agent Workflow**.

The **Module** should derive authority from `DBOS.workflow_id` through the current **Agent Workflow** context and DBOS workflow metadata. It must not rely on caller-supplied current workflow IDs, `root_workflow_id`, Workflow Tree ID prefix scans, or external operator identity as authority inputs.

## Acceptance criteria

- [ ] All parent-direction commands use one **Direct Child Authority Policy** path for direct-child validation.
- [ ] A **Parent Agent Workflow** can coordinate only direct **Child Agent Workflows** under the current MVP policy.
- [ ] Grandchildren, siblings, ancestors, workflows outside the tree, the **Root Agent Workflow**, and the current **Agent Workflow** are rejected consistently.
- [ ] `continue` and `close` are allowed only for direct children whose latest status is `waiting_for_parent`.
- [ ] `waiting_for_child` does not authorize `continue` or `close`.
- [ ] Existing direct-child authority tests pass without weakening assertions.

## Blocked by

- .scratch/dbos-mas/issues/17-extract-mas-command-handling.md
