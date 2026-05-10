# Add an authority policy strategy to MAS command handling

Status: needs-triage
Category: refactor
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

- [ ] `MasCommandHandler` remains the only MAS command handler implementation and is not replaced by per-authority handler classes.
- [ ] `MasCommandHandler` accepts an optional authority policy object and defaults to `DirectChildAuthorityPolicy`.
- [ ] The injected strategy is limited to Coordination Authority decisions and does not parse commands, allocate child IDs, send DBOS messages, wait on events, or format command results.
- [ ] A `CoordinationAuthorityPolicy` interface or equivalent narrow contract exists for authority policy behavior.
- [ ] The policy contract supports listing observable children for no-target `status` and `wait` commands.
- [ ] The policy contract supports requiring an observable target child for target `status` and `wait` commands.
- [ ] The policy contract supports requiring a waiting target child for `continue` and `close`.
- [ ] `DirectChildAuthorityPolicy` implements the contract and remains the default policy.
- [ ] Default `mini-mas status` and `mini-mas wait` still list/wait over direct children only.
- [ ] Targeted `status`, `wait`, `continue`, and `close` still validate Direct Child Authority Policy from DBOS workflow metadata.
- [ ] `continue` and `close` still require the target lifecycle state to be `waiting_for_parent`.
- [ ] `waiting_for_child` still does not authorize continuation or close.
- [ ] No subtree-wide, tree-wide root, granted, or external-operator authority behavior is added.
- [ ] Existing MAS command, authority, coordination, status-event, signal, runtime, and CLI behavior tests pass without weakening assertions.

## Blocked by

- .scratch/dbos-mas/issues/27-simplify-mas-command-handler-dbos-context.md

## Comments

