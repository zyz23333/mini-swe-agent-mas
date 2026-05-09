"""DBOS workflows for the MAS subsystem boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from inspect import isawaitable

from minisweagent.exceptions import InterruptAgentFlow
from minisweagent.mas.artifacts import (
    make_artifact_metadata,
    save_trajectory_artifact,
    validate_root_workflow_id,
    validate_workflow_id,
)
from minisweagent.mas.commands import MasCommandClassification, MasCommandKind, classify_mas_command
from minisweagent.mas.runtime import load_dbos
from minisweagent.mas.status import (
    FIRST_OBSERVABLE_EVENT_KEY,
    STATUS_EVENT_KEY,
    LifecycleState,
    format_specific_status,
    format_status_tree,
    make_status_snapshot,
    query_specific_status_async,
    query_status_tree_async,
)

_dbos = load_dbos()
child_agent_queue = _dbos.Queue("mini_mas_child_agent_workflows")
PARENT_DIRECTION_TOPIC = "mini_mas_parent_direction"
PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS = 60 * 60 * 24 * 30


async def _maybe_await(value):
    return await value if isawaitable(value) else value


@dataclass
class AgentWorkflowState:
    """Mutable state for one ordinary Agent Workflow loop."""

    messages: list[dict]
    cost: float = 0.0
    n_calls: int = 0
    spawn_count: int = 0
    first_observable_published: bool = False
    spawned_child_workflow_ids: set[str] | None = None


async def _publish_status_snapshot(
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> None:
    snapshot = make_status_snapshot(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )
    try:
        await _maybe_await(_dbos.DBOS.set_event_async(STATUS_EVENT_KEY, snapshot.to_event()))
    except Exception:
        if _dbos.DBOS.workflow_id is not None:
            raise


async def _publish_first_observable_event(
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> dict[str, str]:
    """Publish the one-time child event that parent wait operations synchronize on."""
    snapshot = make_status_snapshot(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )
    event = snapshot.to_event()
    try:
        await _maybe_await(_dbos.DBOS.set_event_async(FIRST_OBSERVABLE_EVENT_KEY, event))
    except Exception:
        if _dbos.DBOS.workflow_id is not None:
            raise
    return event


async def _publish_first_observable_event_once(
    state: AgentWorkflowState,
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> dict[str, str] | None:
    if state.first_observable_published:
        return None
    state.first_observable_published = True
    return await _publish_first_observable_event(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


async def _wait_for_parent_direction_signal() -> dict | str:
    """Keep the child workflow waiting until the parent sends an actual direction signal."""
    while True:
        signal = await _maybe_await(
            _dbos.DBOS.recv_async(PARENT_DIRECTION_TOPIC, timeout_seconds=PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS)
        )
        if signal is not None:
            return signal


def _format_detached_spawn_output(metadata: dict[str, str], task: str) -> str:
    return "\n".join(
        [
            "Detached spawn started",
            f"task: {task}",
            f"workflow_id: {metadata['workflow_id']}",
            f"run_directory: {metadata['run_directory']}",
            f"trajectory_artifact_path: {metadata['trajectory_artifact_path']}",
            "",
        ]
    )


def _next_child_workflow_id(parent_workflow_id: str, spawn_index: int) -> str:
    validate_workflow_id(parent_workflow_id)
    if spawn_index < 1:
        raise ValueError("Child spawn index must start at 1")
    return f"{parent_workflow_id}-c{spawn_index:03d}"


async def _enqueue_child_agent_workflow(*, root_workflow_id: str, child_workflow_id: str, task: str) -> None:
    with _dbos.SetWorkflowID(child_workflow_id):
        await child_agent_queue.enqueue_async(child_agent_workflow, root_workflow_id, child_workflow_id, task)


async def _spawn_detached_child(
    *,
    root_workflow_id: str,
    parent_workflow_id: str,
    spawn_index: int,
    task: str,
    existing_child_workflow_ids: set[str],
) -> dict:
    child_workflow_id = _next_child_workflow_id(parent_workflow_id, spawn_index)
    metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=child_workflow_id)
    if child_workflow_id not in existing_child_workflow_ids:
        await _enqueue_child_agent_workflow(
            root_workflow_id=root_workflow_id,
            child_workflow_id=child_workflow_id,
            task=task,
        )
        existing_child_workflow_ids.add(child_workflow_id)

    return {
        "output": _format_detached_spawn_output(metadata, task),
        "returncode": 0,
        "exception_info": "",
        "extra": {
            "mas_command": ["spawn", task],
            "child_workflow_id": child_workflow_id,
            **metadata,
        },
    }


async def _dispatch_mas_command(
    classification: MasCommandClassification,
    *,
    root_workflow_id: str | None,
    workflow_id: str | None,
    spawn_index: int,
    existing_child_workflow_ids: set[str],
) -> dict:
    """Dispatch a validated standalone MAS command at workflow-control level."""
    if classification.arguments[:1] == ["status"]:
        if root_workflow_id is None:
            return {
                "output": "mini-mas status requires Agent Workflow context.\n",
                "returncode": 2,
                "exception_info": "missing_agent_workflow_context",
                "extra": {"mas_command_error": "missing_agent_workflow_context"},
            }
        if len(classification.arguments) == 1:
            snapshots = await query_status_tree_async(_dbos.DBOS, root_workflow_id)
            output = format_status_tree(snapshots, root_workflow_id=root_workflow_id)
            return {
                "output": output,
                "returncode": 0,
                "exception_info": "",
                "extra": {"mas_command": classification.arguments},
            }
        if len(classification.arguments) == 2:
            target_workflow_id = classification.arguments[1]
            snapshot = await query_specific_status_async(
                _dbos.DBOS,
                root_workflow_id=root_workflow_id,
                workflow_id=target_workflow_id,
            )
            if snapshot is None:
                return {
                    "output": f"Workflow not found in current Agent Workflow Tree: {target_workflow_id}\n",
                    "returncode": 1,
                    "exception_info": "workflow_not_found",
                    "extra": {
                        "mas_command": classification.arguments,
                        "mas_command_error": "workflow_not_found",
                    },
                }
            return {
                "output": format_specific_status(snapshot),
                "returncode": 0,
                "exception_info": "",
                "extra": {"mas_command": classification.arguments},
            }
        return {
            "output": "Usage: mini-mas status [workflow-id]\n",
            "returncode": 2,
            "exception_info": "invalid_status_arguments",
            "extra": {"mas_command_error": "invalid_status_arguments"},
        }

    if classification.arguments[:1] == ["spawn"]:
        if root_workflow_id is None or workflow_id is None:
            return {
                "output": "mini-mas spawn requires Agent Workflow context.\n",
                "returncode": 2,
                "exception_info": "missing_agent_workflow_context",
                "extra": {"mas_command_error": "missing_agent_workflow_context"},
            }
        task = " ".join(classification.arguments[1:]).strip()
        if not task:
            return {
                "output": 'Usage: mini-mas spawn "task"\n',
                "returncode": 2,
                "exception_info": "missing_spawn_task",
                "extra": {"mas_command_error": "missing_spawn_task"},
            }
        return await _spawn_detached_child(
            root_workflow_id=root_workflow_id,
            parent_workflow_id=workflow_id,
            spawn_index=spawn_index,
            task=task,
            existing_child_workflow_ids=existing_child_workflow_ids,
        )

    command_text = " ".join(classification.arguments)
    output = f"MAS command accepted: {command_text}\n"
    return {
        "output": output,
        "returncode": 0,
        "exception_info": "",
        "extra": {"mas_command": classification.arguments},
    }


def _reject_mas_shell_composition(classification: MasCommandClassification) -> dict:
    return {
        "output": f"{classification.error}\n",
        "returncode": 2,
        "exception_info": classification.error,
        "extra": {"mas_command_error": "non_standalone_mas_command"},
    }


@_dbos.DBOS.step()
async def query_model_step(model, messages: list[dict]) -> dict:
    """Query the model through a DBOS checkpointed step."""
    return await asyncio.to_thread(model.query, messages)


@_dbos.DBOS.step()
async def execute_bash_step(env, action: dict) -> dict:
    """Execute ordinary bash through a DBOS checkpointed step."""
    return await asyncio.to_thread(env.execute, action)


async def _execute_agent_workflow_outputs(
    *,
    message: dict,
    env,
    root_workflow_id: str | None = None,
    workflow_id: str | None = None,
    spawn_index: int = 0,
    existing_child_workflow_ids: set[str] | None = None,
) -> list[dict]:
    """Execute bash-shaped Agent Workflow actions with workflow-layer MAS interception."""
    outputs = []
    existing_child_workflow_ids = existing_child_workflow_ids if existing_child_workflow_ids is not None else set()
    current_spawn_index = spawn_index
    for action in message.get("extra", {}).get("actions", []):
        classification = classify_mas_command(action.get("command", ""))
        if classification.kind == MasCommandKind.STANDALONE:
            if classification.arguments[:1] == ["spawn"]:
                current_spawn_index += 1
            outputs.append(
                await _dispatch_mas_command(
                    classification,
                    root_workflow_id=root_workflow_id,
                    workflow_id=workflow_id,
                    spawn_index=current_spawn_index,
                    existing_child_workflow_ids=existing_child_workflow_ids,
                )
            )
        elif classification.kind == MasCommandKind.INVALID:
            outputs.append(_reject_mas_shell_composition(classification))
        else:
            outputs.append(await _maybe_await(execute_bash_step(env, action)))
    return outputs


async def execute_agent_workflow_actions(*, message: dict, model, env, template_vars: dict | None = None) -> list[dict]:
    """Execute one model message and return model-specific observation messages."""
    template_vars = template_vars or {}
    child_workflow_ids = template_vars.get("existing_child_workflow_ids", set())
    existing_ids = child_workflow_ids if isinstance(child_workflow_ids, set) else set(child_workflow_ids)
    outputs = await _execute_agent_workflow_outputs(
        message=message,
        env=env,
        root_workflow_id=template_vars.get("root_workflow_id"),
        workflow_id=template_vars.get("workflow_id"),
        spawn_index=template_vars.get("spawn_index", 0),
        existing_child_workflow_ids=existing_ids,
    )
    return model.format_observation_messages(message, outputs, template_vars)


def _template_vars(*, model, env, state: AgentWorkflowState, task: str, root_workflow_id: str, workflow_id: str) -> dict:
    data = {}
    if hasattr(env, "get_template_vars"):
        data |= env.get_template_vars()
    if hasattr(model, "get_template_vars"):
        data |= model.get_template_vars()
    data |= {
        "task": task,
        "n_model_calls": state.n_calls,
        "model_cost": state.cost,
        "root_workflow_id": root_workflow_id,
        "workflow_id": workflow_id,
        "spawn_index": state.spawn_count,
        "existing_child_workflow_ids": state.spawned_child_workflow_ids or set(),
    }
    return data


def _terminal_result(*, root_workflow_id: str, workflow_id: str, terminal_message: dict, state: AgentWorkflowState) -> dict:
    terminal_extra = terminal_message.get("extra", {})
    terminal_state = terminal_extra.get("exit_status", "unknown")
    submission = terminal_extra.get("submission", "")
    model_stats = {
        "instance_cost": state.cost,
        "api_calls": state.n_calls,
    }
    metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)
    return {
        "status": terminal_state,
        "terminal_state": terminal_state,
        "submission": submission,
        "model_stats": model_stats,
        **metadata,
    }


def _latest_error_for_terminal(terminal_state: str, terminal_message: dict) -> str:
    if _lifecycle_state_for_terminal(terminal_state) != "failed":
        return ""
    return terminal_message.get("content", "")


def _lifecycle_state_for_terminal(terminal_state: str) -> LifecycleState:
    if terminal_state == "limits_exceeded":
        return "limits_exceeded"
    if terminal_state in {"failed", "error", "Exception"}:
        return "failed"
    return "closed"


def _limits_exceeded_message(model) -> dict:
    return model.format_message(
        role="exit",
        content="limits_exceeded",
        extra={"exit_status": "limits_exceeded", "submission": ""},
    )


def _initial_messages(model, task: str) -> list[dict]:
    return [
        model.format_message(role="system", content="You are a mini-swe-agent MAS Root Agent Workflow."),
        model.format_message(role="user", content=task),
    ]


async def _run_agent_workflow_loop(
    *,
    root_workflow_id: str,
    workflow_id: str,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None = None,
) -> AgentWorkflowState:
    state = AgentWorkflowState(messages=list(initial_messages) if initial_messages is not None else _initial_messages(model, task))
    state.spawned_child_workflow_ids = set()
    while True:
        if 0 < step_limit <= state.n_calls:
            state.messages.append(_limits_exceeded_message(model))
            return state

        state.n_calls += 1
        try:
            message = query_model_step(model, state.messages)
            message = await _maybe_await(message)
            state.cost += message.get("extra", {}).get("cost", 0.0)
            state.messages.append(message)
            observations = await execute_agent_workflow_actions(
                message=message,
                model=model,
                env=env,
                template_vars=_template_vars(
                    model=model,
                    env=env,
                    state=state,
                    task=task,
                    root_workflow_id=root_workflow_id,
                    workflow_id=workflow_id,
                ),
            )
            state.spawn_count += sum(
                1
                for action in message.get("extra", {}).get("actions", [])
                if classify_mas_command(action.get("command", "")).arguments[:1] == ["spawn"]
            )
            state.messages.extend(observations)
        except InterruptAgentFlow as flow:
            state.messages.extend(flow.messages)

        if state.messages and state.messages[-1].get("role") == "exit":
            return state


@_dbos.DBOS.step()
async def save_root_trajectory_artifact_step(
    root_workflow_id: str,
    *,
    status: str = "started",
    messages: list[dict] | None = None,
    model_stats: dict | None = None,
    submission: str = "",
) -> dict[str, str]:
    """Persist the Root Agent Workflow trajectory through a DBOS step."""
    await asyncio.to_thread(
        save_trajectory_artifact,
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        status=status,
        messages=messages,
        model_stats=model_stats,
        submission=submission,
    )
    return make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=root_workflow_id)


@_dbos.DBOS.step()
async def save_child_trajectory_artifact_step(
    root_workflow_id: str,
    workflow_id: str,
    *,
    status: str = "started",
    messages: list[dict] | None = None,
    model_stats: dict | None = None,
    submission: str = "",
) -> dict[str, str]:
    """Persist a Child Agent Workflow trajectory through a DBOS step."""
    await asyncio.to_thread(
        save_trajectory_artifact,
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        status=status,
        messages=messages,
        model_stats=model_stats,
        submission=submission,
    )
    return make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)


async def _run_agent_workflow(
    *,
    root_workflow_id: str,
    workflow_id: str,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None,
) -> dict:
    await _publish_status_snapshot(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state="running",
    )
    if model is None or env is None:
        metadata = (
            await _maybe_await(save_root_trajectory_artifact_step(root_workflow_id))
            if workflow_id == root_workflow_id
            else await _maybe_await(save_child_trajectory_artifact_step(root_workflow_id, workflow_id))
        )
        return {"status": "started", "terminal_state": "started", **metadata}

    state = await _run_agent_workflow_loop(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        model=model,
        env=env,
        task=task,
        step_limit=step_limit,
        initial_messages=initial_messages,
    )
    result = _terminal_result(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        terminal_message=state.messages[-1],
        state=state,
    )
    lifecycle_state = _lifecycle_state_for_terminal(result["terminal_state"])
    latest_error = _latest_error_for_terminal(result["terminal_state"], state.messages[-1])

    if workflow_id != root_workflow_id and result["terminal_state"] == "Submitted":
        waiting_result = {
            **result,
            "status": "waiting_for_parent",
            "terminal_state": "waiting_for_parent",
            "latest_submission": result["submission"],
        }
        await _publish_status_snapshot(
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            lifecycle_state="waiting_for_parent",
            latest_submission=result["submission"],
        )
        await _publish_first_observable_event_once(
            state,
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            lifecycle_state="waiting_for_parent",
            latest_submission=result["submission"],
        )
        await _maybe_await(
            save_child_trajectory_artifact_step(
                root_workflow_id,
                workflow_id,
                status="waiting_for_parent",
                messages=state.messages,
                model_stats=result["model_stats"],
                submission=result["submission"],
            )
        )
        # This receive is intentionally in async workflow code, not a DBOS step.
        waiting_result["parent_direction_signal"] = await _wait_for_parent_direction_signal()
        return waiting_result

    await _publish_status_snapshot(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=result["submission"],
        latest_error=latest_error,
    )
    if workflow_id != root_workflow_id and lifecycle_state in {"failed", "limits_exceeded"}:
        await _publish_first_observable_event_once(
            state,
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            lifecycle_state=lifecycle_state,
            latest_submission=result["submission"],
            latest_error=latest_error,
        )
    if workflow_id == root_workflow_id:
        await _maybe_await(
            save_root_trajectory_artifact_step(
                root_workflow_id,
                status=result["terminal_state"],
                messages=state.messages,
                model_stats=result["model_stats"],
                submission=result["submission"],
            )
        )
    else:
        await _maybe_await(
            save_child_trajectory_artifact_step(
                root_workflow_id,
                workflow_id,
                status=result["terminal_state"],
                messages=state.messages,
                model_stats=result["model_stats"],
                submission=result["submission"],
            )
        )
    return result


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
    """Root Agent Workflow for the ordinary non-child-coordination MAS path."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    return await _run_agent_workflow(
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        model=model,
        env=env,
        task=task,
        step_limit=step_limit,
        initial_messages=initial_messages,
    )


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
    """Child Agent Workflow started by detached spawn through the child queue."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    workflow_id = validate_workflow_id(workflow_id)
    return await _run_agent_workflow(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        model=model,
        env=env,
        task=task,
        step_limit=step_limit,
        initial_messages=initial_messages,
    )
