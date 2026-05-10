# Add external Root discovery with mini-mas status

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md

## What to build

Implement external `mini-mas status` as a discovery view for Interactive Root Agents. It should list parentless Interactive Root Agent workflows and print Root Agent metadata and lifecycle state without entering MAS Governance or showing child details.

## Acceptance criteria

- [ ] `mini-mas status` lists parentless Interactive Root Agent workflows.
- [ ] Root discovery does not depend on a global root, Root Agent index, `is_root` flag, or interaction-mode flag.
- [ ] The output includes Root Agent ID, lifecycle state, Agent Artifact Directory, and Trajectory Artifact path.
- [ ] Failed or otherwise non-resumable Root Agents are still listed with their lifecycle state.
- [ ] The output does not include Child Agent counts, Child Agent status, latest commands, or history summaries.
- [ ] Workflow-layer `mini-mas status` inside an Agent remains the direct-child status command and is not conflated with external discovery.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/02-add-interactive-root-agent-idle-lifecycle-and-metadata-banner.md
