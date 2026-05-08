# Handle MAS Commands at the Workflow Layer

MAS commands are handled at the DBOS workflow layer, while ordinary model calls, bash execution, and trajectory persistence are wrapped as DBOS steps. This keeps `DBOS.enqueue_workflow`, `DBOS.recv`, and related workflow-control operations out of step functions and preserves a clear boundary between MAS coordination and ordinary shell execution.

**Consequences**

The MAS agent loop cannot simply wrap the existing `env.execute(action)` call as one DBOS step. It must inspect each action first, dispatch standalone `mini-mas` commands in workflow code, and only send ordinary bash commands into `execute_bash_step`.
