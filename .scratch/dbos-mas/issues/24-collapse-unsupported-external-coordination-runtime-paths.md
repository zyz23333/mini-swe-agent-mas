# Collapse unsupported external coordination runtime paths

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Reduce duplication in the External MAS CLI runtime path for unsupported `status`, `wait`, `continue`, and `close` commands. These naked external/operator coordination commands remain unsupported until terminal commands are routed through an **Interactive Root Agent Workflow**, but the unsupported response should be generated through one shared path.

`mini-mas run` remains the only external command that configures DBOS, launches DBOS, and starts a **Root Agent Workflow**.

## Acceptance criteria

- [ ] External `mini-mas status` still reports unsupported external coordination behavior.
- [ ] External `mini-mas wait` still reports unsupported external coordination behavior.
- [ ] External `mini-mas continue` still reports unsupported external coordination behavior.
- [ ] External `mini-mas close` still reports unsupported external coordination behavior.
- [ ] Unsupported external coordination commands do not configure or launch DBOS.
- [ ] `mini-mas run` continues to configure DBOS, launch DBOS, and start `root_agent_workflow` through async DBOS workflow startup.
- [ ] Existing runtime and CLI tests pass.

## Blocked by

None - can start immediately
