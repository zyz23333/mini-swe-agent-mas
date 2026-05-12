# Use Separate Queues for Interactive and AI Agent Workflows

MAS uses separate DBOS queues for interactive command-handling Agents and autonomous AI Agents. `mini_mas_interactive_workflows` is consumed by the default `mini-mas` runtime so Interactive Agents can become available when the CLI is running, while `mini_mas_ai_agent_workflows` is consumed only when the user runs `mini-mas agent activate` because those workflows may call models, execute bash actions, and modify the shared workspace.

**Considered Options**

- Start Interactive Agents as direct DBOS workflows and queue only Child Agents.
- Put all MAS workflows on one queue and filter by workflow name in code.
- Use separate queues so DBOS queue listening controls which category of work a process is authorized to execute.

**Consequences**

Interactive capability is not Root-specific: an Interactive Root Agent is the parentless Interactive Agent entered by the External MAS CLI, and future non-root Interactive Agents can use the same interactive queue. Ordinary `mini-mas` runtime activation should listen only to the interactive queue; AI Agent execution requires explicit activation through `mini-mas agent activate`. Activation is a foreground capability, so it remains running and waits for future queued AI Agent work even when no AI Agents are currently queued. Whether AI Agent execution is active is communicated by the activation command's startup notice rather than an Agent lifecycle state, prompt indicator, or `mini-mas status` output. The command starts without a second confirmation prompt because invoking it is already the explicit execution authorization.
