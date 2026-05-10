# Handle MAS Commands at the Workflow Layer

MAS commands are handled at the DBOS workflow layer, while ordinary model calls, bash execution, and trajectory persistence are wrapped as DBOS steps. This keeps `DBOS.enqueue_workflow`, `DBOS.recv`, and related workflow-control operations out of step functions and preserves a clear boundary between MAS-governed Agent Interactions and ordinary shell execution.

MAS preserves mini-swe-agent's existing action parsing contract: model adapters continue to parse every model action into a bash-shaped `{"command": ...}` action, and model adapters continue to format observations from execution outputs. MAS does not add a separate `mini-mas` model tool, does not modify model-side action parsers, and does not put MAS Governance behavior inside the environment implementation.

**Consequences**

The MAS agent loop cannot simply wrap the existing `env.execute(action)` call as one DBOS step. It must inspect each action first, dispatch standalone `mini-mas` commands in workflow code, and only send ordinary bash commands into `execute_bash_step`.

The MAS agent loop should keep the same high-level data flow as the existing agent loop:

```text
model message -> actions -> outputs -> model-specific observation messages
```

The only extra branch is in the action execution phase:

```text
standalone mini-mas command -> workflow-layer MAS dispatcher
ordinary bash command       -> execute_bash_step
```
