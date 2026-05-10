# Use Async DBOS Workflows for MAS Governance

MAS Agents are backed by async DBOS workflows and async DBOS workflow-control APIs because the core MAS Governance behavior is long-lived waiting, first-submission synchronization, continuation, close signaling, and recursive descendant Agent Interactions. Ordinary model calls, bash execution, and trajectory persistence remain behind DBOS step boundaries, but workflow-control operations such as spawn, wait, send, receive, continue, close, and child workflow creation are awaited in the Agent's DBOS workflow layer rather than hidden in synchronous blocking calls.

**Considered Options**

- Keep MAS Agents backed by synchronous DBOS workflows and use blocking workflow handles or polling for Agent Interactions.
- Use async DBOS workflows for the Agent's DBOS workflow layer while keeping external side effects behind DBOS steps.

**Consequences**

The MAS implementation has to refactor the current synchronous `root_agent_workflow`, `child_agent_workflow`, command dispatch, and runtime startup paths before implementing waited spawn, continuation, close, and recursive descendant Agent Interactions. This keeps the implementation aligned with `wait --any`, bounded waiting, and Remote Interactive Agent signaling semantics instead of drifting toward final-result blocking.
