# Implement resume terminal over the Root command loop

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md
.scratch/interactive-root-agent-cli/DESIGN.md

## What to build

Implement `mini-mas resume <root-agent-id>` as an attachment to an existing Interactive Root Agent command loop. Resume should print Root Agent metadata once, accept user input, send each input as a Root Command Signal, print the Root Command Result, and detach without closing the Root Agent when the terminal exits.

## Acceptance criteria

- [ ] `mini-mas resume <root-agent-id>` re-enters an existing Interactive Root Agent only when it is `waiting_for_command`.
- [ ] Resume validates the Agent ID shape before querying or attaching.
- [ ] Resume rejects unknown Root Agent IDs with a clear error.
- [ ] Resume rejects Child Agent IDs because the target is not a parentless Interactive Root Agent.
- [ ] Resume rejects parentless workflows that are not Interactive Root Agent workflow types.
- [ ] Resume rejects Root Agents in `running`, `waiting_for_child`, `failed`, `closed`, or `limits_exceeded`.
- [ ] Resume unavailable messages include the Root Agent ID and lifecycle state and direct the user to `mini-mas status` and retrying `mini-mas resume <root-agent-id>` later.
- [ ] Resume prints Root Agent metadata once before accepting input.
- [ ] User input is sent to the Root Agent as Root Command Signals.
- [ ] Full standalone `mini-mas ...` commands are accepted; prefix-free MAS shorthand is not added.
- [ ] Ordinary bash commands are accepted and executed by the Root Agent.
- [ ] Ordinary bash actions and observations are recorded in the Root Agent Trajectory Artifact.
- [ ] Exiting the terminal detaches and returns the Root Agent to `waiting_for_command` without closing it.
- [ ] The Interactive Root terminal does not create or reuse a prompt-history file.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/03-deliver-root-command-signals-and-results-end-to-end.md
