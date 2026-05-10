# Deliver Root Command Signals and Root Command Results end to end

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md

## What to build

Implement the narrow command transport between the External MAS CLI and an Interactive Root Agent. The CLI should send one bash-shaped command as a Root Command Signal, the Root Agent should execute it through the existing MAS Agent action flow, and the Root Agent should publish a command-id-scoped Root Command Result event that the CLI waits on.

## Acceptance criteria

- [ ] The CLI can send a Root Command Signal containing one command and a command ID to a waiting Interactive Root Agent.
- [ ] The Interactive Root Agent executes the command itself; the CLI does not execute Root Agent actions directly.
- [ ] Ordinary bash commands execute through the existing bash-shaped action flow.
- [ ] Standalone `mini-mas ...` commands still enter MAS Command Interception.
- [ ] The Root Agent publishes a command-id-scoped Root Command Result event.
- [ ] The Root Command Result uses the existing MAS Agent command result shape.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/02-add-interactive-root-agent-idle-lifecycle-and-metadata-banner.md
