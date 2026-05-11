# Harden Root CLI error and timeout boundaries

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md
.scratch/interactive-root-agent-cli/DESIGN.md

## What to build

Harden the first-version Interactive Root Agent CLI error paths so CLI input errors, Root unavailable states, Root Command Result wait timeouts, command execution errors, and DBOS query failures match the design. This issue should not add new MAS governance commands, Root cleanup behavior, a Root index, or a global root.

## Acceptance criteria

- [ ] Invalid external CLI arguments fail before starting workflows where possible.
- [ ] `mini-mas spawn --timeout <seconds> "task"` without `--wait` returns a usage error and does not start a Root Agent.
- [ ] `mini-mas resume not-an-agent-id` returns a usage error and does not attach.
- [ ] `mini-mas resume <child-agent-id>` clearly reports that the target is not an Interactive Root Agent.
- [ ] Resume unavailable errors include Agent ID and lifecycle state and recommend `mini-mas status` plus retrying `mini-mas resume <root-agent-id>` later.
- [ ] Root Command Result wait timeout reports that the command may still be running, includes `root_agent_id`, recommends status/resume, and does not cancel children.
- [ ] CLI-side Root Command Result wait timeout does not mark the Root Agent failed.
- [ ] Recoverable Root command execution failures publish non-zero Root Command Results and do not kill the Root command loop.
- [ ] DBOS query or configuration errors fail visibly and preserve the underlying exception message.
- [ ] Error and help text do not suggest `close-root`, Root cleanup, a global root, a Root index, or run IDs.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/03-deliver-root-command-signals-and-results-end-to-end.md
- .scratch/interactive-root-agent-cli/issues/04-implement-resume-terminal-over-root-command-loop.md
- .scratch/interactive-root-agent-cli/issues/05-add-external-root-discovery-status.md
- .scratch/interactive-root-agent-cli/issues/08-map-one-shot-waited-spawn-options.md
- .scratch/interactive-root-agent-cli/issues/09-enforce-single-active-root-attachment.md
