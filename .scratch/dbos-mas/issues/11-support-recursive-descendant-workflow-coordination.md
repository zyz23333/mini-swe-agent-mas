# Support recursive Descendant Agent Workflow coordination

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Allow a Child Agent Workflow to act as a Parent Agent Workflow for its own children. Recursive delegation should preserve the Agent Workflow Tree, deterministic Workflow Tree IDs, shared Root Run Directory, and the same status, wait, continue, and close coordination semantics used for first-level children.

This slice should demonstrate a root, child, and grandchild workflow coordinated through MAS commands.

## Acceptance criteria

- [ ] A Child Agent Workflow can issue `mini-mas spawn "task"` as a Standalone MAS Command.
- [ ] Grandchild Workflow Tree IDs append another `-cNNN` segment, for example `mas-<16hex>-c001-c001`.
- [ ] Descendant Agent Workflows share the Root Agent Workflow's Run Directory.
- [ ] `mini-mas status` represents recursive parent-child relationships in the Agent Workflow Tree.
- [ ] `mini-mas wait`, `mini-mas continue`, and `mini-mas close` work for descendants according to existing command semantics.
- [ ] Tests cover root-child-grandchild spawning, sibling ID generation, descendant artifact paths, and recursive status/wait behavior.

## Blocked by

- .scratch/dbos-mas/issues/05-support-detached-spawn-with-deterministic-child-ids.md
- .scratch/dbos-mas/issues/08-implement-waited-spawn-and-mini-mas-wait.md
- .scratch/dbos-mas/issues/09-implement-continuation-signal-for-remote-interactive-agents.md
- .scratch/dbos-mas/issues/10-implement-neutral-close-signal-for-remote-interactive-agents.md

