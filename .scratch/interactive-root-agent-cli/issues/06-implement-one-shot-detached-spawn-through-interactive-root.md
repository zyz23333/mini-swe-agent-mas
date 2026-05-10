# Implement one-shot detached spawn through an Interactive Root Agent

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md

## What to build

Implement external `mini-mas spawn "task"` as a one-shot command that creates an Interactive Root Agent, sends the first `mini-mas spawn "task"` command through that Root Agent, returns the spawned Child Agent metadata, and detaches while leaving the Root Agent available for later resume.

## Acceptance criteria

- [ ] `mini-mas spawn "task"` creates a new Interactive Root Agent.
- [ ] The first spawn command is executed by the Root Agent through Root Command Signal/Result flow.
- [ ] The spawned Agent is a direct Child Agent of the new Root Agent.
- [ ] Output includes `root_agent_id` for later resume.
- [ ] Output emphasizes the spawned Child Agent metadata, including child Agent ID, Parent Agent ID, Agent Artifact Directory, and Trajectory Artifact path.
- [ ] Output does not show Root Agent artifact paths by default.
- [ ] After returning, the Root Agent is available for `resume` when it is `waiting_for_command`.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/03-deliver-root-command-signals-and-results-end-to-end.md
