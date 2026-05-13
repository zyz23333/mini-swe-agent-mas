# Lock lifecycle and authority regressions around activation

Status: needs-triage

## What to build

Add focused regression coverage that keeps AI Agent Execution as runtime state rather than Agent lifecycle or MAS Governance authority. The implementation should remain aligned with ADR 0009, preserve Direct Child Authority Policy and the External MAS CLI entry model, and avoid implying exactly-once side-effect recovery or Workspace Isolation.

## Acceptance criteria

- [ ] Tests prove no `queued` Agent lifecycle state is introduced.
- [ ] Tests prove Agent status output remains based on Agent-published lifecycle states and existing metadata.
- [ ] Tests prove AI Agent Execution activation state is not stored in Agent metadata, Child Status Event data, or External MAS CLI status output.
- [ ] Tests prove activation does not grant broader Authority over Descendant Agents or peers.
- [ ] Tests prove the existing External MAS CLI entry model still submits governance commands through Interactive Root Agents.
- [ ] Documentation or test names use the project glossary terms from `CONTEXT.md` and remain consistent with ADR 0009.
- [ ] The implementation does not claim to solve exactly-once side-effect recovery for model calls, bash actions, or spawn.
- [ ] The implementation does not claim to solve Workspace Isolation.

## Blocked by

- `.scratch/agent-execution-activation/issues/02-queue-spawned-child-agents-as-inactive-ai-agent-work.md`
- `.scratch/agent-execution-activation/issues/03-add-foreground-mini-mas-agent-activate-execution-command.md`
- `.scratch/agent-execution-activation/issues/04-execute-staged-ai-agent-work-only-while-activation-is-running.md`
- `.scratch/agent-execution-activation/issues/05-keep-mini-mas-status-focused-on-interactive-root-agent-discovery.md`
