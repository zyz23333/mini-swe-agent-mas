# Sketch Interactive Root Agent Workflow terminal control

Status: needs-triage
Category: enhancement
Type: Design

## Parent

.scratch/dbos-mas/PRD.md

## What to explore

Define the rough product and architecture direction for an **Interactive Root Agent Workflow**. Opening the MAS terminal should be equivalent to starting a **Root Agent Workflow** that receives terminal user commands through DBOS messages and treats those commands as agent actions, similar to how mini-swe-agent's `InteractiveAgent` human mode wraps user-entered shell commands as `extra.actions`.

This is a design sketch issue, not an implementation-ready slice. A later design pass should decide command syntax, lifecycle, persistence, recovery behavior, and how the external terminal process reconnects to an existing interactive root.

## Current intuition

The existing `mini` interactive human mode provides the model:

- A human-entered command is converted into a `user` message.
- The message contains `extra.actions`.
- Those actions go through the same execution path as model-generated actions.

For MAS, the corresponding shape would be:

- The external `mini-mas` terminal starts or attaches to an **Interactive Root Agent Workflow**.
- The terminal sends user commands to the root workflow through DBOS messages.
- The root workflow receives those commands through an async DBOS receive path.
- Each command is represented as a normal agent message with `extra.actions`.
- Standalone MAS Commands such as `mini-mas spawn "task"` are handled by the workflow-layer MAS dispatcher.
- Ordinary bash commands still execute through checkpointed bash steps.
- The root workflow remains an agent and follows the same **Coordination Authority Model** as other **Parent Agent Workflows**.

## Design constraints to preserve

- Terminal access must not imply tree-wide superuser control.
- The **Root Agent Workflow** should follow the **Direct Child Authority Policy** unless a future **Coordination Authority Model** grants broader authority explicitly.
- `mini-mas spawn` entered at the terminal should create direct children of the root workflow through the same internal MAS coordination path used by model-generated Standalone MAS Commands.
- Terminal user input should be persisted in the root Trajectory Artifact as part of the agent history.
- DBOS workflow-control operations should stay in the async Agent Workflow layer, not inside DBOS steps.
- Ordinary model, bash, and artifact persistence behavior should keep the same checkpointing boundaries as the rest of MAS.

## Open questions

- Should the initial interactive terminal command start a new root workflow every time, or attach to an existing root workflow by Workflow Tree ID?
- What exact DBOS message topic and payload shape should terminal user commands use?
- Should the root terminal command stream support mode switches similar to `InteractiveAgent` human, confirm, and yolo modes, or should the first design only support human-entered commands?
- How should the external terminal receive observations from the root workflow: DBOS events, streams, polling Trajectory Artifacts, or another message channel?
- How should terminal disconnect, reconnect, and root workflow shutdown work?
- Should existing external `mini-mas status`, `wait`, `continue`, and `close` commands remain as direct operator commands, become terminal messages sent to the root workflow, or split into separate operator and agent-terminal surfaces?
- How should this design interact with future **Authority Grants** and broader **Authority Scopes**?

## Out of scope for the sketch

- Implementing the interactive terminal loop.
- Changing existing `mini` behavior.
- Granting tree-wide root control.
- Designing the full future **Coordination Authority Model**.
- Solving Shared Workspace isolation or exactly-once side-effect recovery.
