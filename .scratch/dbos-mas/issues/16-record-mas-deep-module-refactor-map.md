# Record MAS deep Module refactor map

Status: done
Category: enhancement
Type: HITL

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Record a short architecture refactor map for the current **Agent Workflow** implementation before moving code. The map should name the intended deep **Modules**, their **Interfaces**, and the **Seams** where DBOS workflow-control, **MAS Command Interception**, **Direct Child Authority Policy**, **First Observable Events**, and **Remote Interactive Agent** continuation behavior belong.

This issue is a design confirmation slice. It should preserve the current MAS MVP semantics and make later AFK refactors explicit enough that agents do not invent broader **Coordination Authority Models**, extra command fallbacks, or new DBOS behavior while reducing and renaming `workflows.py`.

## Resolved direction

The target main module name is `minisweagent.mas.mas_agent`, chosen to stay close to mini-swe-agent's existing agent-centered design language. The refactor should make the MAS implementation read like an Agent loop first, while keeping DBOS workflow registration and workflow-control constraints explicit.

This refactor map should describe a behavior-preserving extraction. The goal is not to redesign MAS semantics. The current **MAS Command Interception**, **Direct Child Authority Policy**, **Child Status Events**, **First Observable Events**, **Continuation Signals**, **Close Signals**, and **Remote Interactive Agent** waiting behavior must remain intact.

`MasAgent` should be a plain per-workflow orchestration object with an interface shaped similarly to mini-swe-agent's `DefaultAgent`: `run`, `step`, `query`, `execute_actions`, `add_messages`, and `get_template_vars`. This resemblance is an interface and readability goal, not an inheritance requirement.

`MasAgent` must not be registered as a DBOS class and must not expose DBOS-decorated instance methods. DBOS supports decorated class methods only through DBOS class registration and, for instance methods, recoverable configured instances. MAS agent instances carry per-run dynamic model, environment, message, and coordination state, so DBOS recovery must not depend on recovering a dynamic `MasAgent` instance or a `DBOSConfiguredInstance.config_name`.

DBOS-decorated workflows and steps should remain module-level functions:

- `root_agent_workflow` and `child_agent_workflow` remain async `@DBOS.workflow()` functions.
- `query_model_step`, `execute_bash_step`, and trajectory persistence functions remain module-level `@DBOS.step()` functions.
- Module-level workflow entrypoints may construct a plain `MasAgent` and await its `run` method.
- DBOS workflow-control operations such as child workflow enqueueing, waiting for child events, sending parent direction messages, and receiving parent direction messages remain in async workflow code, not inside DBOS steps.

The later rename should prefer `mas_agent.py` as the new module and may keep `workflows.py` temporarily as a compatibility shim that re-exports the new module. New code should import `minisweagent.mas.mas_agent`.

`MasAgent` should stay a thin Agent loop rather than becoming the new large coordination module. Its `execute_actions` path should read like mini-swe-agent's agent loop: execute bash-shaped actions through a MAS-aware action executor, format model-specific observations, and append those observations. It should not inline the details of `spawn`, `wait`, `status`, `continue`, `close`, child event polling, signal payload construction, or direct-child authority validation.

The refactor map should therefore name the intended deep modules around `MasAgent`:

- `mas_agent.py`: plain `MasAgent`, module-level DBOS workflow entrypoints, module-level DBOS step wrappers, and the top-level Agent Workflow orchestration.
- `commands.py`: shell-level MAS command classification for bash-shaped model actions. This module owns the rule that only whole-action Standalone MAS Commands are intercepted and shell compositions containing `mini-mas` are rejected.
- `command_dispatch.py`: Standalone MAS Command dispatch from already-classified commands to workflow-layer command handlers, including MAS subcommand request parsing and observation-result shaping.
- `coordination.py`: workflow-control orchestration for spawn, wait, status, continue, and close while preserving the Direct Child Authority Policy.
- `authority.py`: Direct Child Authority Policy validation for explicit child targets. This module should implement only the fixed MVP direct-child policy, not a pluggable authority framework.
- `status_events.py`: Child Status Event and First Observable Event data shapes, keys, publication, lookup, waiting helpers, and status snapshot formatting.
- `signals.py`: parent-direction message topic, Continuation Signal and Close Signal payload construction, recognition, and continuation user-message metadata shape.

The exact filenames may be refined during the design note, but the responsibility split should prevent `mas_agent.py` from accumulating the same mixed responsibilities currently concentrated in `workflows.py`.

Deep modules should not freely reach into the concrete `_dbos.DBOS` object. Introduce a thin `DBOSCoordinationAdapter` for the DBOS workflow-control primitives MAS needs. This adapter is not a generic port layer and should not imply support for non-DBOS backends. Its purpose is to stop DBOS coordination calls from spreading across command, coordination, event, and signal modules.

The adapter should expose only MAS workflow-control capabilities such as:

- current Agent Workflow identity from DBOS workflow context
- child workflow enqueueing through the child workflow queue
- direct child workflow metadata lookup
- Child Status Event publication and lookup
- First Observable Event publication and waiting
- waiting over several child First Observable Events
- Continuation Signal and Close Signal delivery through DBOS messages
- receiving parent direction messages inside a Child Agent Workflow

`DBOSCoordinationAdapter` methods may be called only from the async Agent Workflow path. DBOS step wrappers must not receive this adapter and must not call it. This is a MAS architecture constraint, not a claim that every DBOS workflow-control API is technically invalid inside a DBOS step. Model query, ordinary bash execution, and trajectory persistence remain separate module-level DBOS steps rather than adapter methods so MAS coordination remains visible at the Agent Workflow layer.

DBOS does technically support some communication and event operations from steps, such as sending messages or setting events, while other workflow-control operations, such as starting or enqueueing child workflows, require workflow context and are invalid from a step. MAS should still default to keeping coordination adapter calls out of step wrappers because MAS command handling, direct-child authority validation, child event synchronization, and parent-direction signaling are part of Agent Workflow orchestration. If a future slice wants a specific DBOS step to call `DBOS.set_event`, `DBOS.send`, or another communication primitive directly, that slice must document why the call belongs inside that step and what the recovery semantics are.

The adapter must not change authority semantics. It should preserve the current rule that workflow-layer MAS commands derive the current Parent Agent Workflow from DBOS workflow context and coordinate only direct Child Agent Workflows validated through DBOS parent workflow metadata.

Direct Child Authority Policy should be visible as its own small module rather than hidden inside coordination command handlers. `authority.py` should provide focused helpers such as `require_direct_child` and `require_waiting_direct_child`, returning the authorized child status snapshot or a structured command error. It must reject current-workflow targets, Root Agent Workflow targets, non-direct children, siblings, ancestors, descendants beyond one level, and workflows outside the direct child boundary.

`authority.py` must not introduce **Authority Grants**, subtree-wide authority, tree-wide Root Agent Workflow authority, caller-supplied current workflow IDs, workflow-prefix authorization, or external operator authority. Future **Coordination Authority Models** remain out of scope for this refactor map.

`commands.py` and `command_dispatch.py` should have a one-way boundary. `commands.py` classifies the raw bash-shaped command string as ordinary bash, valid Standalone MAS Command, or invalid shell composition. `command_dispatch.py` should accept an already-classified `MasCommandClassification` whose kind is `STANDALONE`; it should not re-parse the raw shell command or create a second interpretation of Standalone MAS Command safety. It may parse MAS subcommand arguments from `classification.arguments`, such as `spawn`, `wait`, `status`, `continue`, and `close`, then call coordination handlers.

The action execution path should therefore be: classify action command once, dispatch standalone MAS commands through `command_dispatch.py`, reject invalid MAS shell compositions without entering bash execution, and send only ordinary bash actions to `execute_bash_step`.

The current `status.py` responsibility should become `status_events.py` rather than a broad `events.py`. The module should own MAS lightweight observable state: `LifecycleState`, `AgentStatusSnapshot`, `STATUS_EVENT_KEY`, `FIRST_OBSERVABLE_EVENT_KEY`, Child Status Event publication and lookup, First Observable Event publication and waiting, and simple status snapshot formatting. Parent-direction DBOS messages are not status events and should belong to `signals.py`.

Avoid a generic `events.py` module because it would blur Child Status Events, First Observable Events, parent-direction messages, future Operation Ledger events, and other possible DBOS event or stream concepts. The refactor should keep those terms separate.

`coordination.py` should return structured MAS domain results and errors rather than bash observation dictionaries. Examples include spawned child metadata, waited-spawn readiness data, wait timeout state, target status snapshots, sent signal payloads, and structured command errors. `command_dispatch.py` should own conversion from those structured results into the model-facing observation dictionary shape with `output`, `returncode`, `exception_info`, and `extra`.

This keeps workflow-control behavior separate from command presentation. Changes to human/model-readable command output should not require changing spawn, wait, status, continue, close, authority, or status-event logic.

The design note for this slice should live at `.scratch/dbos-mas/mas-deep-module-refactor-map.md`. Do not create a new ADR for this slice unless a later discussion introduces a hard-to-reverse architectural decision beyond the existing ADRs. The current output is an implementation refactor map and AFK-agent guide, so it should stay close to the DBOS MAS PRD and local issue set.

## Illustrative target shape

This sketch is only a shape guide for the future refactor. It is not a request to implement new behavior in this design-confirmation slice.

```python
@_dbos.DBOS.workflow()
async def root_agent_workflow(
    root_workflow_id: str,
    *,
    model=None,
    env=None,
    task: str = "",
    step_limit: int = 0,
    initial_messages: list[dict] | None = None,
) -> dict:
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    agent = MasAgent(
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        model=model,
        env=env,
        step_limit=step_limit,
    )
    return await agent.run(task=task, initial_messages=initial_messages)


@_dbos.DBOS.workflow()
async def child_agent_workflow(
    root_workflow_id: str,
    workflow_id: str,
    task: str,
    *,
    model=None,
    env=None,
    step_limit: int = 0,
    initial_messages: list[dict] | None = None,
) -> dict:
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    workflow_id = validate_workflow_id(workflow_id)
    agent = MasAgent(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        model=model,
        env=env,
        step_limit=step_limit,
    )
    return await agent.run(task=task, initial_messages=initial_messages)


class MasAgent:
    """Plain per-workflow MAS agent loop; not a DBOS-decorated class."""

    async def run(self, task: str = "", initial_messages: list[dict] | None = None) -> dict:
        ...

    async def step(self) -> list[dict]:
        message = await self.query()
        return await self.execute_actions(message)

    async def query(self) -> dict:
        message = await query_model_step(self.model, self.messages)
        self.add_messages(message)
        return message

    async def execute_actions(self, message: dict) -> list[dict]:
        outputs = await self.action_executor.execute(message, template_vars=self.get_template_vars())
        observations = self.model.format_observation_messages(message, outputs, self.get_template_vars())
        return self.add_messages(*observations)

    def add_messages(self, *messages: dict) -> list[dict]:
        self.messages.extend(messages)
        return list(messages)

    def get_template_vars(self, **kwargs) -> dict:
        ...


@_dbos.DBOS.step()
async def query_model_step(model, messages: list[dict]) -> dict:
    return await asyncio.to_thread(model.query, messages)


@_dbos.DBOS.step()
async def execute_bash_step(env, action: dict) -> dict:
    return await asyncio.to_thread(env.execute, action)
```

## Acceptance criteria

- [x] A concise design note exists under `.scratch/dbos-mas/` or `docs/adr/` describing the target deep **Modules** and their **Interfaces**.
- [x] The note explicitly preserves **MAS Command Interception**, **Direct Child Authority Policy**, **Child Status Events**, **First Observable Events**, **Continuation Signals**, and **Close Signals**.
- [x] The note states that DBOS workflow-control operations remain in async **Agent Workflow** code and that model calls, bash execution, and trajectory persistence remain DBOS steps.
- [x] The note calls out which future behavior is out of scope for this refactor, including **Authority Grants**, **Workspace Isolation**, and Operation Ledger policy.
- [x] No production code behavior changes in this slice.

## Blocked by

None - can start immediately
