# Use Async DBOS Workflows for MAS Coordination

MAS Agent Workflows use async DBOS workflows and async DBOS workflow-control APIs for coordination because the core MAS behavior is long-lived waiting, first-submission synchronization, continuation, close signaling, and recursive descendant coordination. Ordinary model calls, bash execution, and trajectory persistence remain behind DBOS step boundaries, but workflow-control operations such as spawn, wait, send, receive, continue, close, and child workflow creation are awaited in the Agent Workflow layer rather than hidden in synchronous blocking calls.

**Considered Options**

- Keep MAS workflows synchronous and use blocking workflow handles or polling for coordination.
- Use async DBOS workflows for the Agent Workflow layer while keeping external side effects behind DBOS steps.

**Consequences**

The MAS implementation has to refactor the current synchronous `root_agent_workflow`, `child_agent_workflow`, command dispatch, and runtime startup paths before implementing waited spawn, continuation, close, and recursive descendant coordination. This keeps the implementation aligned with `wait --any`, bounded waiting, and Remote Interactive Agent signaling semantics instead of drifting toward final-result blocking.
