# Introduce opaque Agent IDs and Agent-scoped artifacts

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md

## What to build

Replace tree-encoded MAS Agent IDs and root/run-scoped artifact assumptions with opaque `mas-<random-hex>` Agent IDs and per-Agent artifact metadata. A Root Agent and a Child Agent should both use the same Agent ID shape, expose stable Agent Metadata, and write Trajectory Artifacts under Agent Artifact Directories keyed by Agent ID. Parent-child relationships should come from workflow parent metadata, not ID prefixes or artifact paths.

## Acceptance criteria

- [ ] Root Agents and Child Agents use opaque `mas-<random-hex>` Agent IDs that do not encode root identity, parent identity, sibling order, or tree position.
- [ ] DBOS workflow ID equals Agent ID for MAS Agents.
- [ ] Agent Metadata includes Agent ID, optional Parent Agent ID, Agent Artifact Directory, and Trajectory Artifact path.
- [ ] Trajectory Artifacts live under Agent Artifact Directories keyed by Agent ID, not under root/run directories.
- [ ] Existing direct-child authority behavior continues to derive parent-child relationships from workflow parent metadata rather than ID shape.
- [ ] Multi-spawn command result order may be preserved in the returned list, but sibling order is not stored as durable Agent metadata.

## Blocked by

None - can start immediately
