# Add an authority policy strategy to MAS command handling

Status: done
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Introduce a narrow authority-policy strategy seam inside MAS command handling. `MasCommandHandler` should remain the single implementation for parsing already-classified Standalone MAS Commands, maintaining spawn allocation state, calling coordination functions, and formatting command results. The replaceable strategy should be limited to Coordination Authority decisions.

This is a behavior-preserving refactor for the current MVP. The default policy must remain the Direct Child Authority Policy. The refactor must not add subtree-wide authority, Root Agent tree-wide authority, external operator authority, Authority Grants, or any broader target scope.

## Concrete Design

Do not make the whole command handler a strategy. Avoid this shape:

```python
MasCommandHandler(strategy=DirectChildCommandHandler())
MasCommandHandler(strategy=TreeCommandHandler())
```

That design would duplicate `spawn`, `status`, `wait`, `continue`, and `close` behavior across several handlers and make command semantics diverge by authority model.

Instead, keep one `MasCommandHandler` and inject only an authority policy:

```python
class MasCommandHandler:
    def __init__(self, authority: CoordinationAuthorityPolicy | None = None) -> None:
        self.next_spawn_index = 1
        self.authority = authority or DirectChildAuthorityPolicy()
```

The handler owns:

```text
- command dispatch after shell-level MAS classification
- spawn cursor state
- command argument parsing
- deciding which commands require authority checks
- calling coordination functions for spawn/wait/status/signal operations
- converting command outcomes into model-visible observation dictionaries
```

The authority policy owns only:

```text
- listing the children visible under the current Coordination Authority Model
- validating whether a parent workflow may observe/wait for a target workflow
- validating whether a parent workflow may continue/close a target workflow
- enforcing lifecycle requirements such as waiting_for_parent for continue/close
```

Recommended interface:

```python
class CoordinationAuthorityPolicy(Protocol):
    async def list_observable_children(
        self,
        *,
        parent_workflow_id: str,
    ) -> list[dict[str, Any]]:
        ...

    async def require_observable_child(
        self,
        *,
        parent_workflow_id: str,
        target_workflow_id: str,
        command_name: str,
    ) -> dict[str, Any] | AuthorityCommandError:
        ...

    async def require_waiting_child(
        self,
        *,
        parent_workflow_id: str,
        target_workflow_id: str,
        command_name: str,
    ) -> dict[str, Any] | AuthorityCommandError:
        ...
```

`DirectChildAuthorityPolicy` should be the default implementation. It should preserve the current MVP semantics:

```text
- derive parent identity from the current Agent Workflow context before policy use
- validate direct-child scope from DBOS workflow metadata, not workflow ID prefixes
- reject targeting the current workflow
- reject targeting the root workflow as a special parent override
- reject siblings, ancestors, grandchildren, descendants beyond one level, and workflows outside the direct child boundary
- require lifecycle_state == waiting_for_parent for continue and close
- treat waiting_for_child as a local parent coordination state, not a parent-actionable child state
```

For no-target commands, the handler should call the policy instead of hard-coding direct-child behavior:

```python
snapshots = await self.authority.list_observable_children(
    parent_workflow_id=parent_workflow_id,
)
```

Use this for `mini-mas status` without a target and `mini-mas wait` without a target. Under the default policy this still lists direct children only. The interface exists so future authority models can change visibility without duplicating the whole command handler.

For target commands, the handler should parse the target workflow ID from command arguments, then call the authority policy:

```python
snapshot_or_error = await self.authority.require_observable_child(
    parent_workflow_id=parent_workflow_id,
    target_workflow_id=target_workflow_id,
    command_name="status",
)
```

For `continue` and `close`, use:

```python
snapshot_or_error = await self.authority.require_waiting_child(
    parent_workflow_id=parent_workflow_id,
    target_workflow_id=target_workflow_id,
    command_name="continue",
)
```

The authority policy must not:

```text
- parse MAS command syntax
- allocate child workflow IDs
- maintain spawn cursor state
- enqueue child workflows
- wait on First Observable Events
- send Continuation Signals or Close Signals
- receive parent-direction messages
- format model-visible command results
```

Future broader authority models must be introduced through separate issues or ADRs before use. This issue creates only the policy seam and keeps `DirectChildAuthorityPolicy` as the default behavior.

## Acceptance criteria

- [x] `MasCommandHandler` remains the only MAS command handler implementation and is not replaced by per-authority handler classes.
- [x] `MasCommandHandler` accepts an optional authority policy object and defaults to `DirectChildAuthorityPolicy`.
- [x] The injected strategy is limited to Coordination Authority decisions and does not parse commands, allocate child IDs, send DBOS messages, wait on events, or format command results.
- [x] A `CoordinationAuthorityPolicy` interface or equivalent narrow contract exists for authority policy behavior.
- [x] The policy contract supports listing observable children for no-target `status` and `wait` commands.
- [x] The policy contract supports requiring an observable target child for target `status` and `wait` commands.
- [x] The policy contract supports requiring a waiting target child for `continue` and `close`.
- [x] `DirectChildAuthorityPolicy` implements the contract and remains the default policy.
- [x] Default `mini-mas status` and `mini-mas wait` still list/wait over direct children only.
- [x] Targeted `status`, `wait`, `continue`, and `close` still validate Direct Child Authority Policy from DBOS workflow metadata.
- [x] `continue` and `close` still require the target lifecycle state to be `waiting_for_parent`.
- [x] `waiting_for_child` still does not authorize continuation or close.
- [x] No subtree-wide, tree-wide root, granted, or external-operator authority behavior is added.
- [x] Existing MAS command, authority, coordination, status-event, signal, runtime, and CLI behavior tests pass without weakening assertions.

## Blocked by

- .scratch/dbos-mas/issues/27-simplify-mas-command-handler-dbos-context.md

## Comments

> *This was generated by AI during triage.*

> *This was generated by AI during execution.*
>
> Implemented the narrow Coordination Authority policy strategy seam for MAS command handling:
> - Added `CoordinationAuthorityPolicy` with `list_observable_children`, `require_observable_child`, and `require_waiting_child`.
> - Updated `MasCommandHandler` to accept optional `authority` and default to `DirectChildAuthorityPolicy`.
> - Routed no-target `status` and `wait` through `authority.list_observable_children`.
> - Routed targeted `status` and `wait` through `authority.require_observable_child`.
> - Routed `continue` and `close` through `authority.require_waiting_child`.
> - Kept spawn allocation, MAS syntax parsing, DBOS wait/send operations, and result formatting in `MasCommandHandler` and coordination code.
> - Removed the old `AuthorizedChild`, `require_direct_child`, `require_waiting_direct_child`, and `direct_child_metadata` paths rather than keeping compatibility code.
> - Updated the MAS deep-module refactor map to describe the current authority contract.
>
> Verification:
> - `uv run --python 3.11 pytest tests/run/test_mini_mas.py -q -k 'authority_policy or no_target_status_and_wait or mas_command_handler_execute_signature'` passed: 5 passed, 101 deselected.
> - `uv run --python 3.11 pytest tests/run/test_mini_mas.py -q` passed: 106 passed.
> - `uv run --python 3.11 --extra dev ruff check` passed.
> - `uv run --python 3.11 pytest tests -q` passed: 625 passed, 33 skipped, 1 warning.
> - `git diff --check` passed.
> - `make lint`, `make test-backend`, and `make test-frontend` were not run because this checkout has no `Makefile`.

## Agent Brief

**Category:** enhancement
**Summary:** Add a narrow Coordination Authority policy strategy seam to MAS command handling while preserving the current Direct Child Authority Policy behavior.

**Current behavior:**
`MasCommandHandler` is the single workflow-layer dispatcher for classified Standalone MAS Commands. It parses command arguments, owns deterministic child spawn allocation state, calls MAS coordination functions, applies Direct Child Authority Policy checks for targeted commands, and formats model-visible command results.

The Direct Child Authority Policy behavior is already implemented, but the command handler still owns direct-child visibility decisions directly. No-target `status` and `wait` paths query direct-child data directly, and targeted commands call direct-child-specific policy methods. This makes it harder to introduce future Coordination Authority Models without duplicating the whole command handler or letting command semantics diverge across handlers.

**Desired behavior:**
`MasCommandHandler` should remain the only MAS command handler implementation. It should accept an optional narrow Coordination Authority policy object and default to the existing Direct Child Authority Policy. The injected policy should own only authority decisions:

- listing Agent Workflows visible under the current Coordination Authority Model
- authorizing an observable target for `status` and `wait`
- authorizing a waiting target for `continue` and `close`
- enforcing lifecycle requirements such as `waiting_for_parent`

The command handler should continue to own command dispatch, command argument parsing, spawn cursor state, child workflow allocation calls, wait/event synchronization calls, parent-direction signal sends, and model-visible result formatting.

Default behavior must be preserved. The default policy remains Direct Child Authority Policy, so the current Parent Agent Workflow may coordinate only its direct Child Agent Workflows. Direct-child scope must continue to come from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`, not from Workflow Tree ID prefixes, Root Agent Workflow IDs, caller-supplied scope, or external/operator identity.

**Key interfaces:**
- `MasCommandHandler` constructor — should accept an optional authority policy object while still defaulting to Direct Child Authority Policy.
- Coordination authority policy contract — should expose a narrow interface for listing observable children, requiring an observable target child, and requiring a waiting target child.
- `DirectChildAuthorityPolicy` — should implement the policy contract and preserve current MVP authority behavior.
- Model-visible MAS command results — should remain behavior-compatible for `status`, `wait`, `continue`, and `close`, including error shape and observation formatting.

**Acceptance criteria:**
- [x] `MasCommandHandler` remains the only MAS command handler implementation and is not replaced by per-authority handler classes.
- [x] `MasCommandHandler` accepts an optional authority policy object and defaults to `DirectChildAuthorityPolicy`.
- [x] The injected authority strategy is limited to Coordination Authority decisions and does not parse MAS command syntax, allocate child workflow IDs, maintain spawn cursor state, enqueue child workflows, wait on First Observable Events, send Continuation Signals or Close Signals, receive parent-direction messages, or format model-visible command results.
- [x] A `CoordinationAuthorityPolicy` interface or equivalent narrow contract exists for authority policy behavior.
- [x] The policy contract supports listing observable children for no-target `status` and `wait` commands.
- [x] The policy contract supports requiring an observable target child for targeted `status` and `wait` commands.
- [x] The policy contract supports requiring a waiting target child for `continue` and `close`.
- [x] `DirectChildAuthorityPolicy` implements the policy contract and remains the default policy.
- [x] Default `mini-mas status` and `mini-mas wait` still list and wait over direct Child Agent Workflows only.
- [x] Targeted `status`, `wait`, `continue`, and `close` still validate Direct Child Authority Policy from DBOS workflow metadata.
- [x] `continue` and `close` still require the target lifecycle state to be `waiting_for_parent`.
- [x] `waiting_for_child` still does not authorize continuation or close.
- [x] No subtree-wide, tree-wide Root Agent Workflow, granted, or external/operator authority behavior is added.
- [x] Existing MAS command, authority, coordination, status-event, signal, runtime, and CLI behavior tests pass without weakening assertions.

**Out of scope:**
- Adding subtree-wide, tree-wide, Root Agent Workflow special, external-operator, or Authority Grant behavior.
- Creating separate command handler classes per Coordination Authority Model.
- Changing MAS command syntax.
- Changing child workflow ID allocation, spawn cursor behavior, DBOS queueing, First Observable Event waiting, Continuation Signal delivery, Close Signal delivery, or parent-direction receive behavior.
- Moving DBOS workflow-control operations into DBOS steps.
- Changing model-visible output formats, return codes, exception info, trajectory artifact paths, run directory paths, or existing CLI behavior.
