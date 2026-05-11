# Implement one-shot detached spawn through an Interactive Root Agent

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md
.scratch/interactive-root-agent-cli/DESIGN.md

## What to build

Implement external `mini-mas spawn "task"` as a one-shot command that creates an Interactive Root Agent, sends the first `mini-mas spawn "task"` command through that Root Agent, returns the spawned Child Agent metadata, and detaches while leaving the Root Agent available for later resume.

## Acceptance criteria

- [ ] `mini-mas spawn "task"` creates a new Interactive Root Agent.
- [ ] External one-shot spawn waits for the new Root Agent to publish `waiting_for_command` before sending the first Root Command Signal.
- [ ] The submitted Root Command Signal preserves the user's external spawn invocation as a standalone `mini-mas spawn ...` MAS Command.
- [ ] The first spawn command is executed by the Root Agent through Root Command Signal/Result flow.
- [ ] The spawned Agent is a direct Child Agent of the new Root Agent.
- [ ] Output includes `root_agent_id` for later resume.
- [ ] Output emphasizes the spawned Child Agent metadata, including child Agent ID, Parent Agent ID, Agent Artifact Directory, and Trajectory Artifact path.
- [ ] Output does not show Root Agent artifact paths by default.
- [ ] After returning, the Root Agent is available for `resume` when it is `waiting_for_command`.
- [ ] If waiting for the Root Command Result times out, the CLI reports that the command may still be running, includes `root_agent_id`, recommends `mini-mas status` and `mini-mas resume <root-agent-id>`, and does not cancel children or mark the Root failed.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/03-deliver-root-command-signals-and-results-end-to-end.md
