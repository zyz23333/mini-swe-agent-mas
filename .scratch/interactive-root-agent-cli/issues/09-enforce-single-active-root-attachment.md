# Enforce single active Root attachment and resume gating

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md

## What to build

Enforce the first-version attachment model for Interactive Root Agents. A Root Agent can have at most one active terminal attachment or one-shot command attachment. Resume is allowed only when the Root Agent is Waiting for Command. Running commands and waited spawns should make the Root unavailable for another attachment until they return or time out.

## Acceptance criteria

- [ ] A Root Agent accepts `resume` only in `waiting_for_command`.
- [ ] A Root Agent rejects or clearly reports unavailable attachment while it is `running`.
- [ ] A Root Agent rejects or clearly reports unavailable attachment while it is `waiting_for_child`.
- [ ] One-shot `mini-mas spawn` occupies the Root attachment while its submitted command is running.
- [ ] One-shot `mini-mas spawn --wait` occupies the Root attachment until the waited spawn returns or times out.
- [ ] A detached Root Agent returns to `waiting_for_command` when ready for later resume.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/04-implement-resume-terminal-over-root-command-loop.md
- .scratch/interactive-root-agent-cli/issues/06-implement-one-shot-detached-spawn-through-interactive-root.md
- .scratch/interactive-root-agent-cli/issues/08-map-one-shot-waited-spawn-options.md
