# Keep `mini-mas status` focused on Interactive Root Agent discovery

Status: needs-triage

## What to build

Keep `mini-mas status` as a lightweight Interactive Root Agent discovery command. Status and resume-validation paths should use read-only or control-plane access where feasible, avoid launching execution capacity, and avoid reporting AI Agent Execution activation state or queued AI Agent work.

## Acceptance criteria

- [ ] `mini-mas status` lists Interactive Root Agents only.
- [ ] `mini-mas status` does not report queued AI Agent work.
- [ ] `mini-mas status` does not report whether AI Agent Execution is active.
- [ ] The interactive prompt does not show a persistent AI Agent Execution indicator.
- [ ] Status and resume-validation paths avoid launching a DBOS executor when they only need metadata, where feasible behind a stable control-plane adapter.
- [ ] Tests prove status output remains focused on Interactive Root Agent discovery and excludes activation liveness and AI Agent queue state.

## Blocked by

- `.scratch/agent-execution-activation/issues/01-constrain-ordinary-mini-mas-to-interactive-agent-queue.md`
