# Support one-shot multi-spawn result order

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md
.scratch/interactive-root-agent-cli/DESIGN.md

## What to build

Extend one-shot external spawn to accept repeated task arguments. One `mini-mas spawn "task A" "task B"` invocation should create one Interactive Root Agent and multiple direct Child Agents. The returned Child Agent entries should preserve the current command result order for display without storing sibling order as durable Agent metadata.

## Acceptance criteria

- [ ] `mini-mas spawn "task A" "task B"` creates one Interactive Root Agent.
- [ ] Each task creates one direct Child Agent under that Root Agent.
- [ ] Output includes one Root Agent ID and one metadata entry per Child Agent.
- [ ] Child Agent entries are returned in the same order as the submitted task arguments.
- [ ] Child Agent IDs do not encode sibling order.
- [ ] Agent Metadata does not store durable sibling-order fields.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/06-implement-one-shot-detached-spawn-through-interactive-root.md
