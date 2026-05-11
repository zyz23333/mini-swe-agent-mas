# Design: Interactive Root Agent CLI

Status: draft

Parent: `.scratch/interactive-root-agent-cli/PRD.md`

Related decisions:

- `docs/adr/0007-use-opaque-agent-ids-and-agent-scoped-artifacts.md`
- `docs/adr/0004-track-step-side-effect-recovery-risk.md`

## Purpose

This document turns the PRD decisions into an implementation-oriented design for the Interactive Root Agent CLI redesign.

The PRD describes the product behavior. This design describes the stable concepts, data shapes, command routing, workflow lifecycle, module boundaries, and test strategy needed to implement the behavior without reintroducing the old `run`-scoped or root-encoded coupling.

## Design Summary

The External MAS CLI becomes an entrypoint into durable Interactive Root Agents.

- `mini-mas` creates a new Interactive Root Agent and enters its command terminal.
- `mini-mas spawn ...` creates a new Interactive Root Agent, submits one `mini-mas spawn ...` command through it, prints Child Agent metadata, then detaches.
- `mini-mas status` lists existing Interactive Root Agents for discovery.
- `mini-mas resume <root-agent-id>` re-enters an existing Interactive Root Agent only when it is Waiting for Command.

The CLI process is not an Agent and does not perform MAS-governed actions directly. It only starts or discovers Root Agent workflows, sends Root Command Signals, waits for Root Command Results, and renders output.

Root identity is structural:

- A Root Agent has no Parent Agent.
- An Interactive Root Agent is recognized by DBOS workflow type/name plus the absence of a parent workflow.
- Agent Metadata does not contain `is_root`, `interaction_mode`, `spawn_index`, `run_id`, or tree-position fields.

Artifacts are scoped per Agent:

- Every Agent owns one Agent Artifact Directory.
- Every Agent writes one Trajectory Artifact under that directory.
- Artifact paths are derived from Agent ID only, not Root Agent ID, run ID, sibling order, or encoded tree paths.

## Goals

- Replace the `run`-first external CLI model with an Interactive Root Agent model.
- Keep Direct Child Authority as the only authority policy in v1.
- Make every CLI-submitted MAS governance action enter through a Root Agent.
- Make Root Agent discovery possible without a global root, root index, or root metadata flags.
- Make Agent IDs opaque and durable.
- Make artifact paths depend on Agent identity only.
- Preserve existing workflow-layer MAS command behavior inside Agents.
- Keep the first implementation small enough to ship through the existing issue slices.

## Non-Goals

- No global root Agent.
- No Root Agent index table.
- No `run_id`.
- No `is_root` field in Agent Metadata.
- No `interaction_mode` field in Agent Metadata.
- No durable `spawn_index` or sibling-order metadata.
- No root-scoped or run-scoped artifact directory.
- No naked external `wait`, `continue`, or `close` command in v1.
- No Root Agent close/delete/cleanup command in v1.
- No multi-terminal attachment to the same Root Agent in v1.
- No new Root Command Result schema unless the existing MAS Agent command result shape proves insufficient.
- No exactly-once spawn recovery semantics in this design.
- No Workspace Isolation design in this document.

## Terminology

Use the names from `CONTEXT.md`.

Important terms for this design:

- External MAS CLI: the real `mini-mas` process used outside an Agent.
- Interactive Root Agent: a parentless Root Agent that waits for CLI-submitted commands and remains resumable.
- Root Command Signal: one external-to-Root message carrying one bash-shaped command and a command ID.
- Root Command Result: a command-id-scoped DBOS event containing the result of one Root Command Signal.
- Standalone MAS Command: a bash command beginning with `mini-mas` that occupies the entire action command.
- Agent Metadata: stable identity and artifact description for one Agent.
- Waiting for Command: the lifecycle state meaning an Interactive Root Agent is idle and resumable.

## Invariants

These invariants should be enforced by tests and by small validation helpers.

- Agent ID shape is `mas-<random-hex>`.
- Agent ID is opaque; callers must not parse root, parent, sibling order, or tree position from it.
- DBOS workflow ID equals Agent ID for MAS Agents.
- Root Agent identity is `parent_workflow_id is None` at the DBOS workflow structure level.
- Interactive Root Agent discovery filters parentless workflows by workflow type/name.
- Agent Metadata contains only identity and artifact fields:
  - `agent_id`
  - `parent_agent_id`
  - `agent_artifact_directory`
  - `trajectory_artifact_path`
- `parent_agent_id` is `None` only for Root Agents.
- Agent Metadata does not contain `root_agent_id`.
- Agent Metadata does not contain `is_root`.
- Agent Metadata does not contain `interaction_mode`.
- Agent Metadata does not contain `spawn_index`.
- Agent Metadata does not contain `run_id`.
- Artifact paths are derived from `agent_id`.
- Multi-spawn result order may be preserved in the current command result only.
- The Root Agent has no tree-wide authority under the Direct Child Authority Policy.
- External `status` is discovery, not MAS governance.
- External `spawn` and `resume` enter MAS governance through an Interactive Root Agent.

## CLI Surface

### Command Matrix

| External command | Behavior | Governance path | Root handling |
| --- | --- | --- | --- |
| `mini-mas` | Create a new Interactive Root Agent and enter terminal | Commands entered later go through Root Command Signal | New Root remains resumable after detach |
| `mini-mas spawn ...` | Create a new Interactive Root Agent, submit initial spawn command, print Child metadata | Root executes `mini-mas spawn ...` internally | New Root remains resumable after command returns |
| `mini-mas status` | List Interactive Root Agents only | External discovery; not a MAS governance command | Does not attach |
| `mini-mas resume <root-agent-id>` | Enter terminal for an existing Root | User input goes through Root Command Signal | Allowed only when Root is Waiting for Command |

Unsupported in v1:

| External command | v1 behavior |
| --- | --- |
| `mini-mas wait ...` | Not a naked external command |
| `mini-mas continue ...` | Not a naked external command |
| `mini-mas close ...` | Not a naked external command |
| `mini-mas run ...` | Retired from the primary CLI surface |
| `mini-mas close-root ...` | Not introduced |

Workflow-layer commands inside an Agent remain available when issued as Standalone MAS Commands:

- `mini-mas spawn ...`
- `mini-mas status [agent-id]`
- `mini-mas wait [agent-id]`
- `mini-mas continue <agent-id> <message>`
- `mini-mas close <agent-id>`

### Plain `mini-mas`

Plain `mini-mas` starts a new Interactive Root Agent and attaches a local terminal.

Expected high-level output:

```text
agent_id: mas-...
lifecycle_state: waiting_for_command
agent_artifact_directory: .mini-mas/agents/mas-...
trajectory_artifact_path: .mini-mas/agents/mas-.../trajectory.traj.json
```

After the metadata banner, the terminal accepts bash-shaped input. The exact prompt format is deferred.

Terminal input rules:

- A full standalone `mini-mas ...` command is handled as a MAS Command.
- Prefix-free shorthand such as `status` is not added in v1.
- Ordinary bash commands are executed by the Root Agent and recorded in its Trajectory Artifact.
- Composed commands containing `mini-mas`, such as `mini-mas status && echo done`, remain invalid for MAS interception.

### External `mini-mas spawn ...`

External one-shot spawn is a convenience over the same Root command path.

It performs this sequence:

1. Create a new Interactive Root Agent.
2. Wait until the Root publishes `waiting_for_command`.
3. Send a Root Command Signal with a command equivalent to the user's external spawn invocation.
4. Wait for the command-id-scoped Root Command Result.
5. Print the Root Agent ID and Child Agent metadata.
6. Detach.

For one task:

```text
root_agent_id: mas-...

agent_id: mas-...
parent_agent_id: mas-...
agent_artifact_directory: .mini-mas/agents/mas-...
trajectory_artifact_path: .mini-mas/agents/mas-.../trajectory.traj.json
```

For multiple tasks:

```text
root_agent_id: mas-...

children:
- agent_id: mas-...
  parent_agent_id: mas-...
  agent_artifact_directory: .mini-mas/agents/mas-...
  trajectory_artifact_path: .mini-mas/agents/mas-.../trajectory.traj.json
- agent_id: mas-...
  parent_agent_id: mas-...
  agent_artifact_directory: .mini-mas/agents/mas-...
  trajectory_artifact_path: .mini-mas/agents/mas-.../trajectory.traj.json
```

The exact rendering can stay consistent with existing MAS command output. The contract is the data: Root Agent ID is present for resume, and Child Agent artifact metadata is prominent. Root artifact paths are not printed by default for one-shot spawn.

### External `mini-mas status`

External status is discovery only.

It should:

- Query DBOS workflows with no parent.
- Filter to Interactive Root Agent workflow type/name.
- Include failed and otherwise non-resumable Interactive Root Agents.
- Print Root Agent ID, lifecycle state, Agent Artifact Directory, and Trajectory Artifact path.

It should not:

- Enter MAS governance.
- Show child counts.
- Show child statuses.
- Show latest command history.
- Show latest Root command.
- Read or summarize trajectories.

The status view can be minimal:

```text
Interactive Root Agents

agent_id: mas-...
lifecycle_state: waiting_for_command
agent_artifact_directory: .mini-mas/agents/mas-...
trajectory_artifact_path: .mini-mas/agents/mas-.../trajectory.traj.json

agent_id: mas-...
lifecycle_state: running
agent_artifact_directory: .mini-mas/agents/mas-...
trajectory_artifact_path: .mini-mas/agents/mas-.../trajectory.traj.json
```

### External `mini-mas resume <root-agent-id>`

Resume attaches a local terminal to an existing Interactive Root Agent.

Resume should:

- Validate the Agent ID shape.
- Query the workflow and confirm it is an Interactive Root Agent.
- Confirm the workflow has no parent.
- Read the latest Root lifecycle event.
- Allow attach only when lifecycle state is `waiting_for_command`.
- Print Root metadata once before accepting input.
- Send each input line as a Root Command Signal.
- Print each Root Command Result.
- Detach without closing the Root when the terminal exits.

Resume should reject:

- Unknown Root Agent ID.
- Non-root Agent ID.
- Parentless workflow that is not an Interactive Root Agent.
- Root lifecycle state other than `waiting_for_command`.
- Concurrent attachment.

## Data Model

### Agent ID

Agent IDs are durable opaque IDs.

Shape:

```text
mas-<random-hex>
```

The implementation can choose the hex length, but it should be long enough to make collision risk negligible. The existing `mas-<16hex>` shape can be kept unless there is a concrete reason to increase it.

Validation rules:

- Must match the configured opaque Agent ID regex.
- Must not accept `-cNNN` child path suffixes after the migration.
- Must not expose helpers such as `root_id_for_workflow()` that parse a Root ID from a Child ID.
- Must not derive parent relationships from strings.

### Agent Metadata

The public Agent Metadata shape should be:

```python
{
    "agent_id": "mas-...",
    "parent_agent_id": None,
    "agent_artifact_directory": ".mini-mas/agents/mas-...",
    "trajectory_artifact_path": ".mini-mas/agents/mas-.../trajectory.traj.json",
}
```

For a Child Agent:

```python
{
    "agent_id": "mas-...",
    "parent_agent_id": "mas-...",
    "agent_artifact_directory": ".mini-mas/agents/mas-...",
    "trajectory_artifact_path": ".mini-mas/agents/mas-.../trajectory.traj.json",
}
```

Compatibility note:

- Existing code uses `workflow_id`, `root_workflow_id`, and `run_directory`.
- The redesign should move new external/user-facing output to `agent_id`, `parent_agent_id`, and `agent_artifact_directory`.
- Internal transitional helpers may map between workflow naming and Agent naming while issues are implemented, but the durable artifact and CLI contract should use Agent terminology.

Fields intentionally omitted:

- `root_agent_id`
- `root_workflow_id`
- `run_id`
- `run_directory`
- `is_root`
- `interaction_mode`
- `spawn_index`
- `child_index`
- `tree_path`

`root_agent_id` may appear in one-shot spawn output as contextual CLI output, but it is not part of per-Agent metadata.

### Artifact Layout

Proposed layout:

```text
.mini-mas/
  agents/
    mas-<root-id>/
      trajectory.traj.json
    mas-<child-id>/
      trajectory.traj.json
```

The artifact root name `agents` is intentionally not `runs`.

Per-Agent helper responsibilities:

- `make_agent_artifact_directory(agent_id) -> Path`
- `make_trajectory_artifact_path(agent_id) -> Path`
- `make_agent_metadata(agent_id, parent_agent_id) -> dict`
- `save_trajectory_artifact(agent_id, parent_agent_id, ...) -> Path`

The Trajectory Artifact should contain enough metadata to identify its Agent and parent:

```python
{
    "info": {
        "agent_id": "mas-...",
        "parent_agent_id": "mas-...",
        "agent_artifact_directory": ".mini-mas/agents/mas-...",
        "trajectory_artifact_path": ".mini-mas/agents/mas-.../trajectory.traj.json",
        "model_stats": {...},
        "config": {...},
        "mini_version": "...",
        "exit_status": "...",
        "terminal_state": "...",
        "submission": "...",
    },
    "messages": [...],
    "trajectory_format": "mini-swe-agent-1.1",
}
```

Root Agent Trajectory Artifacts record Root terminal actions and observations. They are the durable history source for interactive input.

### Status Snapshot

The Root and Child status event shape should use Agent naming:

```python
{
    "agent_id": "mas-...",
    "parent_agent_id": "mas-...",
    "lifecycle_state": "running",
    "agent_artifact_directory": ".mini-mas/agents/mas-...",
    "trajectory_artifact_path": ".mini-mas/agents/mas-.../trajectory.traj.json",
    "latest_submission": "...",
    "latest_error": "...",
}
```

For Root Agents, `parent_agent_id` is `None`.

Root discovery should not depend on `parent_agent_id` inside this event. The event is descriptive. The structural source of truth is DBOS workflow parent metadata.

### Lifecycle States

Add `waiting_for_command` to the existing lifecycle vocabulary.

Root lifecycle states used by this design:

| State | Meaning |
| --- | --- |
| `waiting_for_command` | Root is idle and can be resumed |
| `running` | Root is executing ordinary bash or detached MAS command |
| `waiting_for_child` | Root is executing `mini-mas wait` or `mini-mas spawn --wait` |
| `failed` | Root command loop or workflow failed |
| `limits_exceeded` | Root reached an applicable limit |
| `closed` | Existing terminal state vocabulary; Root closure is not user-facing in v1 |

Child lifecycle states continue to include:

- `running`
- `waiting_for_parent`
- `waiting_for_child`
- `closed`
- `failed`
- `limits_exceeded`

## DBOS Workflow Model

### Workflow Types

Use separate workflow functions for distinct Agent roles:

- `interactive_root_agent_workflow`
- `agent_workflow` or `child_agent_workflow`

The exact function names may differ, but the distinction must be visible in DBOS workflow metadata so external status can filter Interactive Root Agents without reading Agent Metadata flags.

### Workflow IDs

For every MAS Agent:

```text
DBOS workflow ID == Agent ID
```

Root Agent:

```text
workflow_id = mas-...
parent_workflow_id = None
workflow function/type = interactive_root_agent_workflow
```

Child Agent:

```text
workflow_id = mas-...
parent_workflow_id = <Parent Agent ID>
workflow function/type = child Agent workflow
```

### Parent-Child Structure

Parent-child relationships come from DBOS workflow metadata:

- To list direct children, query workflows where `parent_workflow_id == current_agent_id`.
- To discover roots, query workflows where parent is absent and workflow type/name is Interactive Root.
- To validate direct-child authority, prove the target workflow's parent is the current Agent.

No code should use Agent ID prefixes, path segments, or artifact paths to determine parent-child structure.

### Root Discovery Query

External status should use a query equivalent to:

```python
workflows = await dbos_client.list_workflows_async(
    has_parent=False,
    load_input=False,
    load_output=False,
)
roots = [
    workflow
    for workflow in workflows
    if workflow.workflow_name == INTERACTIVE_ROOT_WORKFLOW_NAME
]
```

If the local DBOS version exposes `parent_workflow_id=None` rather than `has_parent=False`, use the local API shape. The semantic requirement is parentless workflow discovery.

Then read each Root's latest status event to render lifecycle and artifact metadata.

## Root Command Protocol

### Signal

A Root Command Signal carries exactly one bash-shaped command.

Proposed shape:

```python
{
    "kind": "root_command",
    "command_id": "cmd-<random-hex>",
    "root_agent_id": "mas-...",
    "command": "mini-mas spawn --wait 'task'",
    "source": "external_cli",
}
```

`root_agent_id` is signal context, not Agent Metadata.

Validation:

- `command_id` must be unique enough for the target Root Agent.
- `root_agent_id` must match the target workflow ID.
- `command` must be a single command string.
- Empty commands should be ignored by the terminal client before sending, or rejected with a normal command result.

Topic naming:

```python
ROOT_COMMAND_TOPIC = "mini_mas_root_command"
```

The exact constant name is less important than keeping Root commands separate from Parent Direction Signals.

### Result

The Root Command Result is command-id-scoped.

Proposed event key:

```python
ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX = "mini_mas_root_command_result:"
event_key = f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}{command_id}"
```

Proposed result shape:

```python
{
    "kind": "root_command_result",
    "command_id": "cmd-...",
    "root_agent_id": "mas-...",
    "command": "mini-mas spawn 'task'",
    "result": {
        "output": "...",
        "returncode": 0,
        "exception_info": "",
        "extra": {...},
    },
}
```

`result` should be the existing MAS Agent command result shape where possible.

For ordinary bash commands, the result should follow the existing environment output shape as wrapped by the model observation formatter. The first implementation can render the same output text currently shown for MAS Agent observations.

### Timeout Behavior

There are two different timeouts:

- CLI wait timeout for receiving a Root Command Result.
- MAS command timeout such as `mini-mas spawn --wait --timeout <seconds>`.

The `--timeout` option on external `mini-mas spawn` belongs to the MAS command. It bounds the Waited Spawn wait phase and does not cancel Child Agents.

The CLI's internal Root Command Result wait timeout should be an implementation guard. If it fires, the CLI should detach with a clear error and tell the user to use `mini-mas status` and `mini-mas resume <root-agent-id>`. It must not assume the Root command failed.

## Interactive Root Agent Loop

The Interactive Root Agent is a long-lived workflow loop.

Pseudo-flow:

```python
async def interactive_root_agent_workflow(agent_id: str) -> dict:
    agent = InteractiveRootAgent(agent_id=agent_id, parent_agent_id=None)
    await agent.save_initial_trajectory()

    while True:
        await agent.publish_status("waiting_for_command")
        signal = await receive_root_command_signal()
        if signal is None:
            continue

        command_id = validate_command_signal(signal, agent_id)
        try:
            lifecycle = lifecycle_for_command(signal["command"])
            await agent.publish_status(lifecycle)
            result = await agent.execute_user_command(signal["command"])
        except Exception as exc:
            result = root_command_exception_result(exc)
            await agent.publish_status("failed", latest_error=str(exc))
        finally:
            await agent.append_command_to_trajectory(signal, result)
            await publish_root_command_result(command_id, result)
```

The workflow should not return after each command. Terminal detach is a client-side event; the Root remains Waiting for Command.

### Command Execution

The Root should reuse the existing bash-shaped human command flow:

```python
message = {
    "role": "user",
    "content": f"User command: \n```bash\n{command}\n```",
    "extra": {"actions": [{"command": command}]},
}
```

Then execute actions through the existing MAS-aware action executor:

- Standalone `mini-mas ...` goes through MAS Command Interception.
- Invalid composed `mini-mas ...` produces the existing correction result.
- Ordinary bash executes through the bash environment step.

This keeps the Root terminal behavior aligned with `InteractiveAgent` human mode.

### Command Lifecycle Classification

Before execution, the Root can classify lifecycle intent:

| Command | Root lifecycle while executing |
| --- | --- |
| Ordinary bash | `running` |
| `mini-mas spawn ...` without `--wait` | `running` |
| `mini-mas status ...` | `running` |
| `mini-mas continue ...` | `running` |
| `mini-mas close ...` | `running` |
| `mini-mas wait ...` | `waiting_for_child` |
| `mini-mas spawn --wait ...` | `waiting_for_child` |

This classification is only for Root status. The authoritative command parsing and validation still belongs to the MAS command handler.

## Attachment Model

An attachment is an External MAS CLI process that is currently allowed to submit commands to a Root Agent.

In v1:

- One Interactive Root Agent supports at most one active attachment.
- Plain `mini-mas` creates a Root and becomes its first terminal attachment.
- `mini-mas resume <root-agent-id>` creates a terminal attachment to an existing Root.
- `mini-mas spawn ...` creates a one-shot attachment to its new Root.
- The attachment ends when the terminal exits or the one-shot command returns.

### Attachment Gate

The minimal v1 gate can use lifecycle state:

- `waiting_for_command` means attach is allowed.
- `running` means attach is rejected.
- `waiting_for_child` means attach is rejected.
- `failed`, `closed`, and `limits_exceeded` mean attach is rejected.

If lifecycle state alone is insufficient to prevent races, add a small attachment lease event or signal handshake in the Root workflow. That lease is not Agent Metadata and is not a Root index.

The safe attach handshake is:

1. CLI reads Root status and sees `waiting_for_command`.
2. CLI sends an attach/request command or first command with a unique command ID.
3. Root accepts the first received command and transitions out of `waiting_for_command`.
4. Competing clients either time out or receive an unavailable result.

The first implementation should prefer workflow-serialized command acceptance over external locking where possible.

### Detach

Detach does not signal Root closure.

Terminal detach:

- stops the local prompt loop;
- does not send a Close Signal;
- does not close children;
- leaves the Root workflow alive;
- Root publishes `waiting_for_command` after any in-flight command finishes.

One-shot detach:

- happens after the Root Command Result is received or the CLI result wait guard times out;
- does not close the Root;
- does not close children.

## Execution Flows

### Flow: Plain `mini-mas`

```text
User
  -> External CLI: mini-mas
External CLI
  -> DBOS: start interactive_root_agent_workflow with workflow_id mas-...
Interactive Root Agent
  -> Artifact store: write initial Root trajectory
  -> DBOS event: lifecycle_state = waiting_for_command
External CLI
  -> User: print Root metadata banner
  -> User: prompt
User
  -> External CLI: enters command
External CLI
  -> Root: Root Command Signal(command_id, command)
Root
  -> Root: execute command through MAS-aware action flow
  -> Artifact store: append/save Root trajectory
  -> DBOS event: Root Command Result(command_id)
External CLI
  -> User: print result
```

### Flow: `mini-mas resume <root-agent-id>`

```text
External CLI
  -> DBOS: get workflow metadata for root-agent-id
  -> DBOS: confirm no parent and Interactive Root workflow type
  -> DBOS event: read latest Root lifecycle
  -> User: reject unless waiting_for_command
  -> User: print Root metadata banner
  -> User: prompt
```

After attach, command execution is identical to plain `mini-mas`.

### Flow: External `mini-mas status`

```text
External CLI
  -> DBOS: list workflows with no parent
  -> External CLI: filter Interactive Root workflow type/name
  -> DBOS event: read each Root status snapshot
  -> User: print Root discovery list
```

No Root Command Signal is sent.

### Flow: External Detached Spawn

```text
User
  -> External CLI: mini-mas spawn "task"
External CLI
  -> DBOS: start Interactive Root Agent mas-root
Root
  -> DBOS event: waiting_for_command
External CLI
  -> Root: Root Command Signal("mini-mas spawn 'task'")
Root
  -> MAS Command Handler: spawn
MAS Command Handler
  -> DBOS: start Child Agent workflow mas-child with parent mas-root
Child Agent
  -> Artifact store: write child trajectory/status as it runs
Root
  -> Artifact store: save Root trajectory with command observation
  -> DBOS event: Root Command Result(command_id)
External CLI
  -> User: print root_agent_id and child metadata
```

### Flow: External Waited Spawn

```text
User
  -> External CLI: mini-mas spawn --wait --timeout 30 "task"
External CLI
  -> Root: Root Command Signal("mini-mas spawn --wait --timeout 30 'task'")
Root
  -> DBOS event: lifecycle_state = waiting_for_child
Root
  -> MAS Command Handler: spawn children
Root
  -> MAS Command Handler: wait for First Observable Event
Child
  -> DBOS event: First Observable Event
Root
  -> DBOS event: Root Command Result(command_id)
Root
  -> DBOS event: lifecycle_state = waiting_for_command
External CLI
  -> User: print waited spawn result
```

Timeout behavior:

- If the waited spawn timeout fires, the Root Command Result reports timed-out wait data.
- Started children continue running.
- Root returns to `waiting_for_command` after publishing the result.

### Flow: Multi-Spawn

```text
mini-mas spawn "task A" "task B"
```

The Root creates one direct Child Agent per task. The command result preserves the order of returned child entries to match the submitted task list.

This order is command-local display data only:

- It is not stored in Agent Metadata.
- It is not encoded in Agent IDs.
- It is not used for authority.
- It is not used in artifact paths.

### Flow: Ordinary Bash in Root Terminal

```text
User enters: git status --short
External CLI sends Root Command Signal
Root wraps command as InteractiveAgent human-mode action
Root executes bash through existing environment step
Root saves action and observation to Root Trajectory Artifact
Root publishes Root Command Result
External CLI prints output
```

Ordinary bash does not become MAS governance unless it is a Standalone MAS Command.

## Authority Model

The Root Agent is a Parent Agent, not a superuser.

Authority rules:

- A Parent Agent can govern only its direct Child Agents by default.
- The Root Agent can govern its direct Child Agents only.
- The Root Agent cannot directly govern grandchildren.
- External CLI `status` is discovery and does not grant authority.
- External CLI `resume` gives the user a terminal into the Root Agent, but commands still execute as that Root Agent under Direct Child Authority.
- External naked `wait`, `continue`, and `close` are not supported in v1 because they would bypass Root context.

Example:

```text
Root mas-a starts Child mas-b.
Child mas-b starts Grandchild mas-c.
Root mas-a may run: mini-mas status mas-b
Root mas-a may not run: mini-mas status mas-c
```

The authority check should use DBOS parent workflow metadata, not Agent ID structure.

## Error Handling

### CLI Input Errors

External CLI should fail fast before starting workflows when arguments are invalid.

Examples:

- `mini-mas spawn --timeout 30 "task"` without `--wait` is invalid.
- `mini-mas resume not-an-agent-id` is invalid.
- `mini-mas resume <child-agent-id>` is invalid because the target is not an Interactive Root Agent.

Use return code `2` for command usage errors where consistent with existing Typer behavior and MAS command result behavior.

### Root Unavailable

If resume targets a Root that is not Waiting for Command:

```text
Root Agent is not available for resume.
agent_id: mas-...
lifecycle_state: running
```

The message should direct the user toward:

- `mini-mas status`
- retrying `mini-mas resume <root-agent-id>` later

It should not suggest closing the Root in v1.

### Command Execution Errors

If a Root command fails during execution:

- Root should publish a Root Command Result with non-zero `returncode`.
- Root should save the command and error observation to its Trajectory Artifact when possible.
- Recoverable command errors should not kill the Root command loop.
- Unrecoverable workflow errors may leave Root lifecycle as `failed`.

### Signal/Result Timeout

If the External CLI times out waiting for Root Command Result:

- Print a clear timeout message.
- Include `root_agent_id`.
- Explain that the command may still be running.
- Recommend `mini-mas status` and `mini-mas resume <root-agent-id>`.
- Do not cancel Child Agents.
- Do not mark the Root failed from the CLI side.

### DBOS Query Errors

DBOS connection/configuration errors should fail visibly and preserve the underlying exception message. Do not silently return empty status lists when the DBOS system database cannot be queried.

## Output Contracts

The first version should keep output human-readable and close to existing MAS output. Tests should assert required fields and behavioral meaning rather than exact whitespace, unless a formatter function is explicitly treated as a stable boundary.

Required Root metadata fields in Root banners and external status:

- `agent_id`
- `lifecycle_state`
- `agent_artifact_directory`
- `trajectory_artifact_path`

Required one-shot spawn fields:

- `root_agent_id`
- per child:
  - `agent_id`
  - `parent_agent_id`
  - `agent_artifact_directory`
  - `trajectory_artifact_path`

Required waited spawn fields should follow existing MAS waited result shape:

- waited flag or waited output text
- wait mode where applicable
- timed-out indication where applicable
- ready child snapshots where applicable
- still-running child IDs where applicable

## Module Boundaries

The current code has these relevant modules:

- `src/minisweagent/mas/cli.py`
- `src/minisweagent/mas/runtime.py`
- `src/minisweagent/mas/mas_agent.py`
- `src/minisweagent/mas/commands.py`
- `src/minisweagent/mas/agent_interactions.py`
- `src/minisweagent/mas/artifacts.py`
- `src/minisweagent/mas/status_events.py`
- `src/minisweagent/agents/interactive.py`

Suggested responsibilities after redesign:

### `mas/cli.py`

Own the external Typer command surface:

- `mini-mas`
- `mini-mas spawn`
- `mini-mas status`
- `mini-mas resume`

Responsibilities:

- parse external arguments;
- call runtime functions;
- render human-readable output;
- return proper exit codes;
- avoid direct Agent Interaction execution.

### `mas/runtime.py`

Own DBOS bootstrapping and external-to-workflow operations:

- initialize DBOS;
- start Interactive Root workflows;
- list Interactive Root workflows;
- send Root Command Signals;
- wait for Root Command Results;
- validate resume preconditions.

Runtime should not implement MAS governance logic. It should address Root workflows and transport commands.

### `mas/mas_agent.py`

Own workflow implementations and Agent loops:

- `interactive_root_agent_workflow`;
- Child Agent workflow;
- Root command receive/execute/result loop;
- trajectory save integration;
- lifecycle publishing.

The Root command loop should reuse the existing action execution path rather than adding a second command executor.

### `mas/commands.py`

Own Standalone MAS Command parsing and dispatch inside an Agent:

- workflow-layer `spawn`;
- workflow-layer `status`;
- workflow-layer `wait`;
- workflow-layer `continue`;
- workflow-layer `close`;
- command result formatting.

External CLI parsing may share option definitions conceptually, but external CLI should route through Root Command Signals rather than calling these handlers directly.

### `mas/agent_interactions.py`

Own MAS-governed interactions between Agents:

- spawn direct children;
- wait for child First Observable Events;
- send Continuation Signals;
- send Close Signals;
- query direct child status through authority policy.

It should stop requiring root-derived Agent ID parsing. Parent-child structure should come from DBOS workflow metadata and explicit parent arguments.

### `mas/artifacts.py`

Own Agent-scoped artifact helpers:

- validate opaque Agent IDs;
- build Agent Artifact Directory;
- build Trajectory Artifact path;
- build Agent Metadata;
- save Trajectory Artifacts.

Remove run/root-scoped naming from public helpers.

### `mas/status_events.py`

Own lifecycle event shapes and formatters:

- include `waiting_for_command`;
- use Agent naming;
- format direct-child status inside Agents;
- format Root discovery status for external CLI;
- query direct child statuses by DBOS parent metadata.

Root discovery may live in `runtime.py` if it needs DBOS client bootstrapping, but formatting should stay separate.

### `agents/interactive.py`

No large change should be required. It is prior art for the command wrapping shape used by human mode.

The Root command loop should reuse this message/action convention:

```python
{"extra": {"actions": [{"command": command}]}}
```

## Implementation Sequence

The existing issues are already ordered as tracer-bullet slices. This is the recommended implementation sequence:

1. Opaque Agent IDs and Agent-scoped artifacts.
2. Minimal Interactive Root Agent lifecycle and metadata banner.
3. Root Command Signal and Root Command Result transport.
4. Resume terminal over the Root command loop.
5. External Root discovery status.
6. One-shot detached spawn through an Interactive Root Agent.
7. One-shot multi-spawn result ordering.
8. One-shot waited spawn options.
9. Single active Root attachment enforcement.
10. Retire run-first external CLI behavior.

The sequence is important because later CLI behavior depends on the Root command transport and artifact identity changes.

## Testing Strategy

Tests should be behavior-first. Avoid asserting private helper names or exact DBOS internals unless those internals are the only stable integration point available.

### Identity and Artifact Tests

Cover:

- Root and Child Agent IDs match opaque `mas-<random-hex>`.
- Child IDs do not encode parent ID.
- Child IDs do not encode sibling order.
- Agent Metadata has only `agent_id`, `parent_agent_id`, `agent_artifact_directory`, and `trajectory_artifact_path`.
- Root metadata has `parent_agent_id is None`.
- Trajectory Artifacts live under Agent Artifact Directories.
- No root/run-scoped artifact paths are used in new behavior.

### Root Lifecycle Tests

Cover:

- Plain `mini-mas` creates a parentless Interactive Root Agent.
- Root publishes `waiting_for_command` when idle.
- Root publishes `running` while executing ordinary bash.
- Root publishes `running` while executing detached spawn.
- Root publishes `waiting_for_child` while executing waited spawn or wait.
- Resume is accepted only from `waiting_for_command`.
- Terminal exit detaches without closing Root.

### Root Command Protocol Tests

Cover:

- CLI sends Root Command Signal with command ID.
- Root executes the command itself.
- CLI does not execute Root actions directly.
- Root publishes command-id-scoped Root Command Result.
- Result shape matches existing MAS Agent command result shape.
- Wrong command ID does not satisfy another pending command wait.

### Terminal Behavior Tests

Cover:

- Full standalone `mini-mas ...` commands are accepted.
- Prefix-free shorthand is not accepted as MAS command.
- Ordinary bash commands execute.
- Ordinary bash commands are recorded in the Root Trajectory Artifact.
- Composed `mini-mas ... && ...` commands remain invalid for MAS interception.
- No prompt-history file is created or reused.

### Discovery Tests

Cover:

- External `mini-mas status` lists parentless Interactive Root Agents.
- External status filters out parentless non-Interactive-Root workflows if any exist.
- External status includes failed Root Agents.
- External status includes lifecycle and artifact metadata.
- External status omits child count, child status, latest command, and history summaries.

### Spawn Tests

Cover:

- External `mini-mas spawn "task"` creates one Root and one direct Child.
- The Child workflow's DBOS parent is the new Root Agent.
- One-shot output includes Root Agent ID.
- One-shot output emphasizes Child Agent metadata.
- One-shot output omits Root artifact paths by default.
- Root remains resumable after one-shot command returns.

### Multi-Spawn Tests

Cover:

- Repeated task arguments create one Child per task.
- All children share the one Root parent.
- Returned child entries match submitted task order.
- No durable metadata records sibling order.

### Waited Spawn Tests

Cover:

- `--wait` waits for First Observable Event.
- `--wait --all` waits for all started children to become observable.
- `--wait --timeout <seconds>` bounds only the wait phase.
- Timeout does not cancel, close, fail, or retry children.
- `--timeout` without `--wait` is invalid.
- Root is `waiting_for_child` during the wait phase.

### Authority Tests

Cover:

- Root can govern direct children.
- Root cannot govern grandchildren under Direct Child Authority.
- Workflow-layer `status`, `wait`, `continue`, and `close` continue to respect direct-child scope.
- External naked governance commands are not supported bypasses.

### Attachment Tests

Cover:

- Concurrent resume is rejected or clearly reported unavailable.
- Resume while Root is `running` is rejected.
- Resume while Root is `waiting_for_child` is rejected.
- One-shot spawn occupies the Root attachment until result.
- One-shot waited spawn occupies the Root attachment until result or timeout.

### CLI Help and Boundary Tests

Cover:

- Help emphasizes `mini-mas`, `spawn`, `status`, and `resume`.
- `run`-first wording is removed from the primary path.
- No `close-root` appears.
- Unsupported command messages direct users toward status/resume where appropriate.

## Migration Notes

This project has no external users yet, so the implementation can make breaking changes directly.

Breaking changes expected:

- Tree-encoded Child Agent IDs such as `mas-...-c001` stop being valid new Agent IDs.
- `root_workflow_id` and `workflow_id` should stop being the external naming contract.
- `.mini-mas/runs/<root>/...` should stop being the new artifact layout.
- Existing external `run` behavior can be retired from the primary CLI surface.
- Existing external naked coordination commands remain unsupported or are removed from supported help.

Because existing local artifacts may still exist, tests should avoid assuming a clean `.mini-mas` directory unless they create an isolated test workspace.

## Security and Correctness Notes

The main correctness boundary is that the External MAS CLI must not directly execute Root Agent actions.

Preserve these boundaries:

- User commands execute inside the Root workflow.
- MAS governance commands execute inside Agent context.
- Authority checks use workflow parent metadata.
- External discovery does not grant control.
- Artifacts do not imply authority.
- Agent IDs do not imply authority.

Do not add fallback paths where the CLI directly calls `spawn_children`, `wait_for_children`, continuation signaling, or close signaling for user-requested governance commands. Those actions must enter through the Root Agent command loop.

## Deferred Design Topics

### Spawn Recovery

Spawn recovery is explicitly unresolved.

If a process crashes after child workflow creation but before DBOS checkpoints the parent step result, replay may duplicate child creation. This design does not solve that. ADR 0004 tracks the likely need for an Operation Ledger or another recovery mechanism.

Do not introduce durable sibling-order metadata as a recovery workaround.

### Root Cleanup

Root close/delete/cleanup/retention is out of scope for v1.

Future design should answer:

- how a user intentionally closes a Root;
- whether closing a Root affects children;
- how old Root artifacts are retained or removed;
- how failed Root workflows are displayed after cleanup exists.

### Attachment Lease Durability

The v1 model supports one active attachment. Lifecycle gating may be sufficient for the first implementation, but a future design may need an explicit attachment lease if concurrent clients can race at the transport layer.

If added, attachment leases should remain transport/session state, not Agent Metadata.

### Prompt Format

The prompt format is unresolved.

Open choices:

- full Root Agent ID in every prompt;
- shortened Root Agent ID in prompt plus full ID in banner;
- current directory plus shortened Root Agent ID.

This is display-only and should not affect command parsing or metadata.

### Result Schema

Root Command Results use the existing MAS Agent command result shape in v1.

A future narrower schema may be useful if external clients need machine-stable output, but this design intentionally does not create that schema now.

### Workspace Isolation

All Agents currently operate in a Shared Workspace unless configured otherwise. Workspace Isolation is a separate design topic and should not be mixed into this CLI redesign.

## Design Checklist

- [x] Root identity is structural, not a metadata flag.
- [x] External status is discovery, not governance.
- [x] External commands enter through Interactive Root Agents.
- [x] Agent IDs are opaque.
- [x] Artifacts are per-Agent.
- [x] No `run_id`.
- [x] No global root.
- [x] No Root index.
- [x] No `is_root`.
- [x] No `interaction_mode`.
- [x] No durable `spawn_index`.
- [x] Direct Child Authority remains unchanged.
- [x] Spawn recovery is explicitly deferred.
