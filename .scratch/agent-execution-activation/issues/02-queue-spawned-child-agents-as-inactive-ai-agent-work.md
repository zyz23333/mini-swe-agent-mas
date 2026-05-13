# Queue spawned Child Agents as inactive AI Agent work

Status: needs-triage

## What to build

Make spawned autonomous Child Agents durable AI Agent work that does not execute until AI Agent Execution is explicitly activated. `mini-mas spawn "task"` should still create Child Agent metadata through the Interactive Root Agent path, but the Child Agent workflow should be queued on `mini_mas_ai_agent_workflows` and remain independent from whether execution is currently active.

## Acceptance criteria

- [ ] Detached Spawn and Waited Spawn enqueue autonomous Child Agents on `mini_mas_ai_agent_workflows`.
- [ ] `mini-mas spawn "task"` can create or queue Child Agent work without requiring active AI Agent Execution.
- [ ] Spawned Child Agent metadata remains durable and includes the existing Agent ID, Parent Agent ID, Agent Artifact Directory, and Trajectory Artifact path behavior.
- [ ] Queue placement is not stored as Agent metadata and does not introduce a `queued` Agent lifecycle state.
- [ ] Direct Child Authority Policy is preserved for spawned Child Agents.
- [ ] Tests prove AI Agent work spawned before activation is durable and not consumed by ordinary `mini-mas` runtime activation.

## Blocked by

- `.scratch/agent-execution-activation/issues/01-constrain-ordinary-mini-mas-to-interactive-agent-queue.md`
