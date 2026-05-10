# Map one-shot waited spawn options to existing MAS wait semantics

Status: needs-triage

## Parent

.scratch/interactive-root-agent-cli/PRD.md

## What to build

Support `--wait`, `--all`, and `--timeout` on external one-shot `mini-mas spawn` by routing them through the Interactive Root Agent to the existing workflow-layer Waited Spawn behavior. The command should wait for First Observable Events, not final workflow results, and keep spawned children running on timeout.

## Acceptance criteria

- [ ] `mini-mas spawn --wait "task"` waits for a First Observable Event using wait-any behavior.
- [ ] `mini-mas spawn --wait --all "task A" "task B"` waits until all started children become observable or timeout.
- [ ] `mini-mas spawn --wait --timeout <seconds> "task"` bounds only the wait phase.
- [ ] Timeout returns available ready child data and still-running child IDs without cancelling, closing, failing, or retrying children.
- [ ] `mini-mas spawn --timeout <seconds> "task"` without `--wait` remains invalid.
- [ ] The Interactive Root Agent is `waiting_for_child` during the waited phase and returns to `waiting_for_command` after the one-shot command detaches.

## Blocked by

- .scratch/interactive-root-agent-cli/issues/06-implement-one-shot-detached-spawn-through-interactive-root.md
- .scratch/interactive-root-agent-cli/issues/07-support-one-shot-multi-spawn-result-order.md
