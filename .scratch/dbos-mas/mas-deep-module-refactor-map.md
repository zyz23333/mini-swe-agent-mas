# MAS Deep Module Refactor Map

## Purpose

This note records the intended behavior-preserving deep module extraction for the MAS Agent Workflow implementation. It is an implementation refactor map and AFK-agent guide, not a new MAS semantics proposal.

Later refactor slices must preserve the current MAS MVP behavior:

- **MAS Command Interception** stays at the Agent Workflow layer.
- **Direct Child Authority Policy** remains the fixed MVP Coordination Authority Model.
- **Child Status Events** and **First Observable Events** remain lightweight DBOS event shapes.
- **Continuation Signals** and **Close Signals** remain parent-to-child DBOS messages.
- **Remote Interactive Agent** workflows keep waiting for parent direction after submission.

Do not use this map to introduce broader authority scopes, command fallbacks, non-DBOS backends, or new workflow behavior.

## Target Modules

### `mas_agent.py`

Owns the plain per-workflow MAS Agent loop and module-level DBOS workflow entrypoints.

Responsibilities:

- Define a plain `MasAgent` orchestration object shaped similarly to mini-swe-agent's `DefaultAgent` interface: `run`, `step`, `query`, `execute_actions`, `add_messages`, and `get_template_vars`.
- Keep `MasAgent` as a normal Python object, not a DBOS-registered class and not a holder of DBOS-decorated instance methods.
- Keep `root_agent_workflow` and `child_agent_workflow` as async module-level `@DBOS.workflow()` functions.
- Keep model query, ordinary bash execution, and trajectory persistence as module-level `@DBOS.step()` wrappers.
- Construct `MasAgent` inside workflow entrypoints and await its `run` method.
- Keep the top-level Agent Workflow loop readable as an Agent loop first.

Non-responsibilities:

- Do not inline `spawn`, `wait`, `status`, `continue`, or `close` coordination logic.
- Do not inline child event polling, signal payload construction, or direct-child authority validation.
- Do not make DBOS recovery depend on reconstructing a dynamic `MasAgent` instance or a `DBOSConfiguredInstance.config_name`.

The eventual rename should prefer `mas_agent.py` as the new module. `workflows.py` may temporarily remain as a compatibility shim that re-exports the new module.

### `commands.py`

Owns shell-level MAS command classification for bash-shaped model actions.

Responsibilities:

- Classify each raw action command as ordinary bash, a valid Standalone MAS Command, or an invalid shell composition containing `mini-mas`.
- Own the rule that only whole-action Standalone MAS Commands are intercepted.
- Reject shell compositions containing `mini-mas` before ordinary bash execution.

Non-responsibilities:

- Do not dispatch MAS subcommands.
- Do not parse `spawn`, `wait`, `status`, `continue`, or `close` arguments beyond the shell-level classification boundary.
- Do not duplicate command safety parsing elsewhere.

### `command_dispatch.py`

Owns Standalone MAS Command dispatch from already-classified commands to workflow-layer command handlers.

Responsibilities:

- Accept an already-classified `MasCommandClassification` whose kind is `STANDALONE`.
- Parse MAS subcommand arguments such as `spawn`, `wait`, `status`, `continue`, and `close`.
- Convert structured coordination results into the model-facing bash observation dictionary shape: `output`, `returncode`, `exception_info`, and `extra`.

Non-responsibilities:

- Do not re-parse the raw shell command or create a second interpretation of Standalone MAS Command safety.
- Do not directly own DBOS workflow-control details.
- Do not own Direct Child Authority Policy logic.

The intended action execution route is:

1. Classify the action command once in `commands.py`.
2. Dispatch Standalone MAS Commands through `command_dispatch.py`.
3. Reject invalid MAS shell compositions before bash execution.
4. Send only ordinary bash actions to `execute_bash_step`.

### `coordination.py`

Owns MAS workflow-control orchestration for `spawn`, `wait`, `status`, `continue`, and `close`.

Responsibilities:

- Start Child Agent Workflows through the child workflow queue.
- Wait for direct children through First Observable Events.
- Query direct child status data.
- Coordinate Continuation Signal and Close Signal delivery.
- Return structured MAS domain results and errors, such as spawned child metadata, waited-spawn readiness data, wait timeout state, target status snapshots, sent signal payloads, and structured command errors.

Non-responsibilities:

- Do not build model-facing observation dictionaries.
- Do not redefine command-line syntax.
- Do not broaden the Direct Child Authority Policy.

### `authority.py`

Owns Direct Child Authority Policy validation.

Responsibilities:

- Implement only the fixed MVP Direct Child Authority Policy.
- Derive the current Parent Agent Workflow identity from DBOS workflow context through the coordination adapter.
- Validate direct-child scope from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`.
- Provide focused helpers such as `require_direct_child` and `require_waiting_direct_child`.
- Return the authorized child status snapshot or a structured command error.
- Reject the current Agent Workflow, the Root Agent Workflow, non-direct children, siblings, ancestors, descendants beyond one level, and workflows outside the direct child boundary.
- Require `waiting_for_parent` for `continue` and `close`.
- Treat `waiting_for_child` as a local coordination state that does not authorize parent-direction commands.

Non-responsibilities:

- Do not introduce Authority Grants.
- Do not introduce subtree-wide authority.
- Do not introduce tree-wide Root Agent Workflow authority.
- Do not accept caller-supplied current workflow IDs.
- Do not use Workflow Tree ID prefixes for authorization.
- Do not introduce external operator authority.
- Do not become a pluggable authority framework.

Future Coordination Authority Models are out of scope for this refactor map.

### `status_events.py`

Owns lightweight MAS observable state.

Responsibilities:

- Define `LifecycleState`, `AgentStatusSnapshot`, `STATUS_EVENT_KEY`, and `FIRST_OBSERVABLE_EVENT_KEY`.
- Publish and query Child Status Events.
- Publish and wait for First Observable Events.
- Format simple status snapshots.
- Preserve lifecycle states such as `running`, `waiting_for_child`, `waiting_for_parent`, `closed`, `failed`, and `limits_exceeded`.

Non-responsibilities:

- Do not own parent-direction DBOS messages.
- Do not become a generic `events.py` module.

Avoid a broad `events.py` name because it blurs Child Status Events, First Observable Events, parent-direction messages, future Operation Ledger events, and other possible DBOS event or stream concepts.

### `signals.py`

Owns parent-direction message concepts.

Responsibilities:

- Define the parent-direction message topic.
- Build Continuation Signal payloads.
- Build Close Signal payloads.
- Recognize parent-direction messages inside Child Agent Workflows.
- Define continuation user-message metadata shape.

Non-responsibilities:

- Do not publish or query Child Status Events.
- Do not decide whether a parent is authorized to signal a target child.

## DBOS Coordination Adapter

Deep MAS modules should not freely reach into the concrete `_dbos.DBOS` object. Introduce a thin `DBOSCoordinationAdapter` for MAS workflow-control primitives.

The adapter is not a generic port layer and does not imply support for non-DBOS backends. Its purpose is to stop DBOS coordination calls from spreading across command, coordination, event, signal, and authority modules.

The adapter should expose only MAS workflow-control capabilities:

- Current Agent Workflow identity from DBOS workflow context.
- Child workflow enqueueing through the child workflow queue.
- Direct child workflow metadata lookup.
- Child Status Event publication and lookup.
- First Observable Event publication and waiting.
- Waiting over several child First Observable Events.
- Continuation Signal and Close Signal delivery through DBOS messages.
- Receiving parent direction messages inside a Child Agent Workflow.

Adapter methods may be called only from the async Agent Workflow path. DBOS step wrappers must not receive this adapter and must not call it.

Model query, ordinary bash execution, and trajectory persistence remain separate module-level DBOS steps rather than adapter methods so MAS coordination remains visible at the Agent Workflow layer.

DBOS does technically support some communication and event operations from steps, such as sending messages or setting events. MAS should still default to keeping coordination adapter calls out of step wrappers because MAS command handling, direct-child authority validation, child event synchronization, and parent-direction signaling are part of Agent Workflow orchestration. If a future slice wants a specific DBOS step to call a communication primitive directly, that slice must document why the call belongs inside that step and what the recovery semantics are.

The adapter must not change authority semantics.

## Authority Semantics

Workflow-layer `mini-mas status`, `mini-mas wait`, `mini-mas continue`, and `mini-mas close` derive the current Parent Agent Workflow from `DBOS.workflow_id`.

Explicit workflow IDs in `status <workflow-id>`, `wait <workflow-id>`, `continue <workflow-id>`, and `close <workflow-id>` are target identifiers only. They are not scope overrides.

Direct-child scope is resolved from DBOS workflow metadata where:

```text
parent_workflow_id == DBOS.workflow_id
```

`root_workflow_id`, Workflow Tree ID prefixes, caller-supplied current workflow IDs, DBOS API object parameters, and external operator identity are not authority inputs.

The Root Agent Workflow has no special tree-wide Coordination Authority under the MVP Direct Child Authority Policy. The child agent of my child agent is not my child agent.

## Out of Scope

This refactor map does not include:

- Authority Grants.
- Subtree-wide authority.
- Tree-wide Root Agent Workflow authority.
- External operator authority for naked `status`, `wait`, `continue`, or `close` paths.
- New command fallbacks.
- New DBOS behavior.
- Workspace Isolation.
- Operation Ledger policy.
- A generic `events.py` abstraction.
- A non-DBOS backend abstraction.
- Behavior changes to MAS Command Interception, Child Status Events, First Observable Events, Continuation Signals, Close Signals, or Remote Interactive Agent waiting behavior.

## Acceptance Criteria for Refactor Slices

Future slices using this map should preserve these properties:

- Standalone MAS Commands are intercepted at the Agent Workflow layer.
- Non-standalone `mini-mas` shell compositions return a clear model-visible correction and are not executed as ordinary bash.
- Ordinary bash actions still execute through the checkpointed bash step.
- DBOS workflow-control operations remain in async Agent Workflow code.
- Model calls, bash execution, and trajectory persistence remain DBOS steps.
- Parent-direction commands only affect direct Child Agent Workflows whose latest status is `waiting_for_parent`.
- `waiting_for_child` does not authorize `continue` or `close`.
- Grandchildren, siblings, ancestors, workflows outside the tree, the Root Agent Workflow, and the current Agent Workflow are rejected consistently where the current Direct Child Authority Policy requires rejection.
- Existing direct-child authority tests pass without weakening assertions.
