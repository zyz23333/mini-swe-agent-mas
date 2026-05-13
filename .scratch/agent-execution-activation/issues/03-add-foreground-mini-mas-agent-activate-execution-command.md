# Add foreground `mini-mas agent activate` execution command

Status: needs-triage

## What to build

Add `mini-mas agent activate` as the explicit foreground command that activates AI Agent Execution for the active MAS Runtime State Store while the command is running. The command should listen only to `mini_mas_ai_agent_workflows`, remain active even when no AI Agent work is queued, and communicate the side-effect risk through a startup notice without adding a second confirmation prompt.

## Acceptance criteria

- [ ] The External MAS CLI exposes `mini-mas agent activate`.
- [ ] `mini-mas agent activate` launches DBOS with an explicit queue-listening policy for `mini_mas_ai_agent_workflows` only.
- [ ] The command remains running in the foreground when no AI Agent work is currently queued.
- [ ] The command starts without a second confirmation prompt.
- [ ] The command prints a startup notice warning that queued AI Agent work may call models, execute bash actions, and modify the Shared Workspace.
- [ ] The startup notice includes the active workspace, MAS Runtime State Store, AI Agent queue, side-effect warning, and Ctrl-C deactivation guidance when those values are available.
- [ ] Tests prove activation does not create, continue, close, accept, cancel, or delete any Agent by itself.

## Blocked by

- `.scratch/agent-execution-activation/issues/01-constrain-ordinary-mini-mas-to-interactive-agent-queue.md`
