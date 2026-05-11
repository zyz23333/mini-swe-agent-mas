# Retire run-first external CLI behavior for the new Root CLI surface

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md
.scratch/interactive-root-agent-cli/DESIGN.md

## What to build

Complete the CLI surface transition from the previous `run`-first MAS interface to the Interactive Root Agent CLI model. The first-version external CLI should emphasize `mini-mas`, `spawn`, `status`, and `resume`, avoid naked external governance commands, and keep Root closure and cleanup out of scope.

## Acceptance criteria

- [ ] CLI help and command descriptions present `mini-mas`, `spawn`, `status`, and `resume` as the first-version Root CLI surface.
- [ ] The old `run`-first wording and root/run-scoped output are removed from the new primary CLI path.
- [ ] Naked external `wait`, `continue`, and `close` are not introduced as supported bypasses around Interactive Root Agent context.
- [ ] External `wait`, `continue`, and `close` are absent or rejected as unsupported external governance commands.
- [ ] Workflow-layer `mini-mas wait`, `mini-mas continue`, and `mini-mas close` remain available inside an Agent as Standalone MAS Commands.
- [ ] No `close-root`, Root cleanup, Root index, global root, or run ID behavior is added.
- [ ] Help and error text do not suggest Root Agent closure, cleanup, `close-root`, a Root index, a global root, or run IDs.
- [ ] Error messages direct users toward `mini-mas status` and `mini-mas resume <root-agent-id>` when they need to re-enter a Root Agent.
- [ ] Tests cover the final command help and unsupported command boundaries.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/05-add-external-root-discovery-status.md
- .scratch/interactive-root-agent-cli/issues/06-implement-one-shot-detached-spawn-through-interactive-root.md
- .scratch/interactive-root-agent-cli/issues/08-map-one-shot-waited-spawn-options.md
- .scratch/interactive-root-agent-cli/issues/09-enforce-single-active-root-attachment.md
