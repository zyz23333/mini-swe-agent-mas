# Simplify MAS command handling around DBOS workflow context

Status: needs-triage
Category: refactor
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Refactor the MAS command execution path so callers do not pass DBOS workflow context, child workflow allocation state, coordination adapters, or callback dependencies into the command handler.

Each `MasAgent` should own one private command handler instance. The handler should execute Standalone MAS Commands by reading the current parent Agent Workflow identity from `DBOS.workflow_id`, maintaining its own deterministic child spawn cursor, and calling simple module-level MAS coordination functions. The agent loop should only classify bash-shaped actions and route Standalone MAS Commands to this handler.

This is a behavior-preserving simplification. It must not change MAS command syntax, model-visible command output, Direct Child Authority Policy semantics, Child Status Events, First Observable Events, Continuation Signals, Close Signals, workflow IDs, artifact paths, or CLI behavior. DBOS workflow-control operations must remain in async workflow-layer code, while model calls, ordinary bash execution, and trajectory persistence must remain DBOS steps.

## Concrete Design

The target command execution path is:

```text
MasAgent.execute_actions
  -> classify_mas_command(action["command"])
  -> if standalone:
       self.command_handler.execute(classification)
         -> current_workflow_id() reads DBOS.workflow_id
         -> spawn uses handler.next_spawn_index
         -> coordination module calls DBOS workflow-control APIs directly
     elif invalid:
       reject the non-standalone MAS shell composition
     else:
       execute_bash_step(env, action)
  -> model.format_observation_messages(...)
```

`MasAgent` should construct the command handler once:

```python
class MasAgent:
    def __init__(...):
        ...
        self.command_handler = MasCommandHandler()
```

The handler should own spawn allocation state:

```python
class MasCommandHandler:
    def __init__(self) -> None:
        self.next_spawn_index = 1

    async def execute(self, classification: MasCommandClassification) -> dict[str, Any]:
        ...

    async def _spawn(self, arguments: list[str]) -> dict[str, Any]:
        parent_workflow_id = current_workflow_id()
        if parent_workflow_id is None:
            return missing_agent_workflow_context("spawn")

        request = parse_spawn_arguments(arguments)
        root_workflow_id = root_id_for_workflow(parent_workflow_id)

        children = await spawn_children(
            root_workflow_id=root_workflow_id,
            parent_workflow_id=parent_workflow_id,
            first_spawn_index=self.next_spawn_index,
            tasks=request.tasks,
        )
        self.next_spawn_index += len(children)
        ...
```

The handler must not be a module-level singleton. It must be per `MasAgent` instance so concurrent Agent Workflows do not share spawn cursor state.

`execute` must not accept `spawn_index`, `existing_child_workflow_ids`, current workflow callbacks, query callbacks, authority policy objects, child coordinator objects, continuation sender callbacks, or close sender callbacks. Current parent identity is read inside command execution through `DBOS.workflow_id`.

There are three different workflow IDs and they must stay separated:

```text
Current parent workflow ID:
  Source: DBOS.workflow_id.
  Do not pass it through the agent loop or command handler constructor.

Target child workflow ID for status/wait/continue/close:
  Source: the model's command argument, e.g. mini-mas continue <workflow-id> "message".
  Validate it through Direct Child Authority Policy.

New spawned child workflow ID:
  Source: parent_workflow_id + handler.next_spawn_index via next_child_workflow_id(...).
  Generate it inside spawn coordination, not in the agent loop.
```

Do not allocate new child IDs by querying existing direct children and using `max(existing) + 1`. That would mix external DBOS state into workflow replay and can shift task-to-child assignment after a crash. Child allocation should be deterministic from the command sequence: current parent workflow ID plus the handler-local spawn cursor.

`coordination.py` should expose simple module-level functions instead of requiring `DBOSCoordinationAdapter` and `ChildCoordinator` object construction for command execution:

```python
def current_workflow_id() -> str | None: ...
async def publish_status(...): ...
async def publish_first_observable(...): ...
async def query_direct_child_statuses(parent_workflow_id: str) -> list[dict[str, Any]]: ...
async def query_direct_child_status(*, parent_workflow_id: str, child_workflow_id: str) -> dict[str, Any] | None: ...
async def direct_child_metadata(*, parent_workflow_id: str) -> list[dict[str, str]]: ...
async def spawn_children(...): ...
async def wait_for_children(...): ...
async def send_parent_direction(...): ...
async def receive_parent_direction(...): ...
```

If `coordination.py` needs `child_agent_workflow` to enqueue child workflows, import it lazily inside `spawn_children` to avoid top-level circular imports.

`authority.py` should stop receiving direct-child status query callbacks. It can either keep `DirectChildAuthorityPolicy` with no constructor dependencies or become module-level functions. In either case, direct-child checks should call `coordination.query_direct_child_status(...)` and preserve the MVP authority model.

Duplicate child enqueue behavior must be handled deliberately. Remove the process-local `existing_child_workflow_ids` set from the command execution signature. If duplicate deterministic child workflow IDs surface during DBOS replay, investigate the actual DBOS duplicate workflow behavior from the local `references/dbos-transact-py` source or tests, then handle only the precise duplicate-workflow case in `enqueue_child_agent_workflow`. Do not swallow broad exceptions.

## Acceptance criteria

- [ ] Each `MasAgent` instance owns one private `MasCommandHandler` instance.
- [ ] `MasCommandHandler` is not a module-level singleton and does not use global mutable state.
- [ ] `MasCommandHandler.execute(...)` accepts only the classified Standalone MAS Command and no longer accepts `spawn_index` or `existing_child_workflow_ids`.
- [ ] The agent action loop no longer passes current workflow callbacks, query callbacks, authority policy objects, child coordinator objects, continuation sender callbacks, or close sender callbacks into command execution.
- [ ] `MasCommandHandler` maintains a handler-local `next_spawn_index` cursor and uses it only for deterministic spawn allocation.
- [ ] Spawned child workflow IDs are generated inside spawn coordination from `DBOS.workflow_id` plus the handler-local spawn cursor.
- [ ] `status`, `wait`, `continue`, and `close` still get their target child workflow IDs from command arguments and still validate Direct Child Authority Policy.
- [ ] Child workflow allocation does not use `max(existing children) + 1` or any DBOS status/query result as the allocation cursor.
- [ ] `existing_child_workflow_ids` is removed from the command execution path.
- [ ] `coordination.py` exposes module-level DBOS workflow-control functions and command handling no longer requires `DBOSCoordinationAdapter` or `ChildCoordinator` construction.
- [ ] `authority.py` no longer requires direct-child status query callback injection.
- [ ] `MasAgent._publish_status` and first-observable publication call module-level coordination functions directly instead of routing through local pass-through wrappers.
- [ ] Model query still runs through `query_model_step`.
- [ ] Ordinary bash execution still runs through `execute_bash_step`.
- [ ] Trajectory persistence still runs through DBOS step wrappers.
- [ ] Spawn, wait, direct child status lookup, continuation send, close send, and parent-direction receive remain workflow-layer operations and are not moved into DBOS steps.
- [ ] Non-standalone `mini-mas` shell compositions still return the existing model-visible correction and do not enter `execute_bash_step`.
- [ ] Existing MAS command, authority, coordination, status-event, signal, runtime, and CLI behavior tests pass without weakening assertions.

## Blocked by

None - can start immediately.

## Comments

