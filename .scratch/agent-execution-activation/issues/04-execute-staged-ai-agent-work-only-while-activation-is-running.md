# Execute staged AI Agent work only while activation is running

Status: needs-triage

## What to build

Prove the end-to-end AI Agent Execution boundary. AI Agent work queued before activation should execute only after `mini-mas agent activate` is running, activation should be able to start before any work exists and consume work queued later, and stopping activation should remove execution capacity without mutating durable Agent state.

## Acceptance criteria

- [ ] AI Agent work queued before `mini-mas agent activate` is consumed after activation starts.
- [ ] `mini-mas agent activate` can start before any AI Agent work exists and later consume work queued while activation is running.
- [ ] Stopping `mini-mas agent activate` deactivates AI Agent Execution without closing queued, running, waiting, or recovery-required Agents.
- [ ] Activation shutdown does not delete queued work or Agent artifacts.
- [ ] Activation does not continue, accept, close, cancel, or otherwise make MAS Governance decisions for Agents.
- [ ] Tests cover the staged-before-activation and queued-after-activation paths through stable CLI/runtime boundaries.

## Blocked by

- `.scratch/agent-execution-activation/issues/02-queue-spawned-child-agents-as-inactive-ai-agent-work.md`
- `.scratch/agent-execution-activation/issues/03-add-foreground-mini-mas-agent-activate-execution-command.md`
