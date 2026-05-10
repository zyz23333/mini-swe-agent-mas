# Add Interactive Root Agent idle lifecycle and metadata banner

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md

## What to build

Add the minimum Interactive Root Agent path: creating a parentless Root Agent, publishing `waiting_for_command` when idle, writing Root Agent artifacts, and printing Root Agent metadata before the prompt for plain `mini-mas`. This slice should make Root Agent creation observable without requiring the full command loop yet.

## Acceptance criteria

- [ ] `mini-mas` without a subcommand creates a parentless Interactive Root Agent.
- [ ] The new Root Agent publishes a `waiting_for_command` lifecycle state when idle.
- [ ] The Root Agent writes per-Agent metadata and a Trajectory Artifact using the Agent-scoped artifact layout.
- [ ] The CLI prints Root Agent metadata once before entering the command prompt.
- [ ] The printed metadata includes Root Agent ID, lifecycle state, Agent Artifact Directory, and Trajectory Artifact path.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/01-introduce-opaque-agent-ids-and-agent-scoped-artifacts.md
