# Restore the Agent Workflow loop to a mini-shaped Interface

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Refactor the **Agent Workflow** runner so its external shape resembles mini-swe-agent's core loop: query model, execute bash-shaped actions with **MAS Command Interception**, append model-specific observations, stop on terminal exit, and save the trajectory. DBOS-specific complexity, command dispatch, status publication, and child lifecycle behavior should sit behind deeper **Modules** and **Adapters**.

This slice should keep `root_agent_workflow` and `child_agent_workflow` as thin async DBOS workflow entrypoints.

## Acceptance criteria

- [ ] `root_agent_workflow` and `child_agent_workflow` remain async DBOS workflows.
- [ ] The core **Agent Workflow** loop has a small **Interface** and does not inline MAS command dispatch internals.
- [ ] Model query still runs through `query_model_step`.
- [ ] Ordinary bash execution still runs through `execute_bash_step`.
- [ ] Trajectory persistence still runs through DBOS steps.
- [ ] Limits exceeded behavior and terminal result behavior remain compatible.
- [ ] Existing workflow registration, step registration, trajectory artifact, ordinary bash, and observation formatting tests pass.

## Blocked by

- .scratch/dbos-mas/issues/17-extract-mas-command-handling.md
- .scratch/dbos-mas/issues/19-introduce-dbos-coordination-adapter.md
