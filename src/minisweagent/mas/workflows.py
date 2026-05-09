"""DBOS workflows for the MAS subsystem boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from minisweagent.exceptions import InterruptAgentFlow
from minisweagent.mas.artifacts import (
    make_artifact_metadata,
    save_trajectory_artifact,
    validate_root_workflow_id,
    validate_workflow_id,
)
from minisweagent.mas.authority import DirectChildAuthorityPolicy
from minisweagent.mas.command_dispatch import MasCommandHandler
from minisweagent.mas.commands import MasCommandClassification, MasCommandKind, classify_mas_command
from minisweagent.mas.coordination import ChildCoordinator, DBOSCoordinationAdapter
from minisweagent.mas.runtime import load_dbos
from minisweagent.mas.status import LifecycleState

_dbos = load_dbos()
child_agent_queue = _dbos.Queue("mini_mas_child_agent_workflows")
PARENT_DIRECTION_TOPIC = "mini_mas_parent_direction"
PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS = 60 * 60 * 24 * 30


async def _maybe_await(value):
    return await value if isawaitable(value) else value


def _current_agent_workflow_id() -> str | None:
    return _coordination_adapter().current_agent_workflow_id()


def _coordination_adapter() -> DBOSCoordinationAdapter:
    return DBOSCoordinationAdapter(
        dbos_api=_dbos.DBOS,
        child_agent_queue=child_agent_queue,
        set_workflow_id=_dbos.SetWorkflowID,
        child_agent_workflow=child_agent_workflow,
    )


def _child_coordinator() -> ChildCoordinator:
    return ChildCoordinator(adapter=_coordination_adapter())


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
    await _coordination_adapter().publish_status(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


async def _publish_first_observable_event(
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> dict[str, str]:
    return await _coordination_adapter().publish_first_observable(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


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
        signal = await _coordination_adapter().receive_parent_direction(
            topic=PARENT_DIRECTION_TOPIC,
            timeout_seconds=PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS,
        )
        if signal is not None:
            return signal


def make_continuation_signal(*, source_workflow_id: str, target_workflow_id: str, content: str) -> dict[str, str]:
    """Build the parent-to-child message payload used for MAS continuation."""
    return {
        "type": "continuation",
        "signal_type": "mas_continuation",
        "content": content,
        "source_workflow_id": source_workflow_id,
        "target_workflow_id": target_workflow_id,
    }


def make_close_signal(*, source_workflow_id: str, target_workflow_id: str) -> dict[str, str]:
    """Build the neutral parent-to-child message payload used to close a waiting child."""
    return {
        "type": "close",
        "signal_type": "mas_close",
        "source_workflow_id": source_workflow_id,
        "target_workflow_id": target_workflow_id,
    }


def _format_continue_output(*, target_workflow_id: str, content: str, snapshot: dict[str, Any]) -> str:
    lines = [
        "Continuation signal sent",
        f"workflow_id: {target_workflow_id}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
        f"message: {content}",
        f"run_directory: {snapshot['run_directory']}",
        f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
    ]
    return "\n".join(lines) + "\n"


def _format_close_output(*, target_workflow_id: str, snapshot: dict[str, Any]) -> str:
    lines = [
        "Close signal sent",
        f"workflow_id: {target_workflow_id}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
    ]
    if snapshot.get("latest_submission"):
        lines.append(f"latest_submission: {snapshot['latest_submission']}")
    lines.extend(
        [
            f"run_directory: {snapshot['run_directory']}",
            f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
        ]
    )
    return "\n".join(lines) + "\n"


async def send_continuation_signal_async(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
    content: str,
    target_status: dict[str, Any],
) -> dict[str, Any]:
    """Send a continuation signal after Direct Child Authority Policy validation."""
    signal = make_continuation_signal(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        content=content,
    )
    await _coordination_adapter().send_parent_direction(
        target_workflow_id=target_workflow_id,
        signal=signal,
        topic=PARENT_DIRECTION_TOPIC,
    )
    return {
        "ok": True,
        "output": _format_continue_output(
            target_workflow_id=target_workflow_id,
            content=content,
            snapshot=target_status,
        ),
        "returncode": 0,
        "exception_info": "",
        "extra": {
            "mas_command": ["continue", target_workflow_id, content],
            "continued_workflow_id": target_workflow_id,
            "continuation_signal": signal,
            "target_status": target_status,
        },
    }


async def send_close_signal_async(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
    target_status: dict[str, Any],
) -> dict[str, Any]:
    """Send a neutral close signal after Direct Child Authority Policy validation."""
    signal = make_close_signal(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
    )
    await _coordination_adapter().send_parent_direction(
        target_workflow_id=target_workflow_id,
        signal=signal,
        topic=PARENT_DIRECTION_TOPIC,
    )
    return {
        "ok": True,
        "output": _format_close_output(
            target_workflow_id=target_workflow_id,
            snapshot=target_status,
        ),
        "returncode": 0,
        "exception_info": "",
        "extra": {
            "mas_command": ["close", target_workflow_id],
            "closed_workflow_id": target_workflow_id,
            "close_signal": signal,
            "target_status": target_status,
        },
    }


async def _query_direct_child_statuses(parent_workflow_id: str) -> list[dict[str, Any]]:
    return await _coordination_adapter().query_direct_child_statuses(parent_workflow_id)


async def _query_direct_child_status(parent_workflow_id: str, child_workflow_id: str) -> dict[str, Any] | None:
    return await _coordination_adapter().query_direct_child_status(
        parent_workflow_id=parent_workflow_id,
        child_workflow_id=child_workflow_id,
    )


async def _send_continuation_signal_for_handler(
    source_workflow_id: str, target_workflow_id: str, content: str, target_status: dict[str, Any]
) -> dict[str, Any]:
    return await send_continuation_signal_async(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        content=content,
        target_status=target_status,
    )


async def _send_close_signal_for_handler(
    source_workflow_id: str, target_workflow_id: str, target_status: dict[str, Any]
) -> dict[str, Any]:
    return await send_close_signal_async(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        target_status=target_status,
    )


def _make_mas_command_handler() -> MasCommandHandler:
    authority_policy = DirectChildAuthorityPolicy(query_direct_child_status=_query_direct_child_status)
    return MasCommandHandler(
        current_workflow_id=_current_agent_workflow_id,
        query_direct_child_statuses=_query_direct_child_statuses,
        authority_policy=authority_policy,
        child_coordinator=_child_coordinator(),
        send_continuation_signal=_send_continuation_signal_for_handler,
        send_close_signal=_send_close_signal_for_handler,
    )


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
    spawn_index: int = 0,
    existing_child_workflow_ids: set[str] | None = None,
) -> list[dict]:
    """Execute bash-shaped Agent Workflow actions with workflow-layer MAS interception."""
    outputs = []
    existing_child_workflow_ids = existing_child_workflow_ids if existing_child_workflow_ids is not None else set()
    command_handler = _make_mas_command_handler()
    current_spawn_index = spawn_index
    for action in message.get("extra", {}).get("actions", []):
        classification = classify_mas_command(action.get("command", ""))
        if classification.kind == MasCommandKind.STANDALONE:
            output = await command_handler.execute(
                classification,
                spawn_index=current_spawn_index + 1,
                existing_child_workflow_ids=existing_child_workflow_ids,
            )
            outputs.append(output)
            current_spawn_index += output.get("extra", {}).get("spawned_child_count", 0)
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


def _is_continuation_signal(signal: dict | str) -> bool:
    return isinstance(signal, dict) and (
        signal.get("type") == "continuation" or signal.get("signal_type") == "mas_continuation"
    )


def _is_close_signal(signal: dict | str) -> bool:
    return isinstance(signal, dict) and (signal.get("type") == "close" or signal.get("signal_type") == "mas_close")


def _continuation_user_message(model, signal: dict) -> dict:
    """Represent parent continuation as a normal model-facing user message."""
    return model.format_message(
        role="user",
        content=str(signal.get("content", "")),
        extra={
            "mas": {
                "signal_type": "mas_continuation",
                "source_workflow_id": str(signal.get("source_workflow_id", "")),
                "target_workflow_id": str(signal.get("target_workflow_id", "")),
            }
        },
    )


async def _run_agent_workflow_loop(
    *,
    root_workflow_id: str,
    workflow_id: str,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None = None,
    state: AgentWorkflowState | None = None,
) -> AgentWorkflowState:
    state = state or AgentWorkflowState(
        messages=list(initial_messages) if initial_messages is not None else _initial_messages(model, task)
    )
    if state.spawned_child_workflow_ids is None:
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
            state.messages.extend(observations)
            state.spawn_count += sum(
                observation.get("extra", {}).get("spawned_child_count", 0) for observation in observations
            )
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
    original_workflow_id = _current_agent_workflow_id()
    if original_workflow_id is None:
        _dbos.DBOS.workflow_id = workflow_id
    try:
        return await _run_agent_workflow_with_context(
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            model=model,
            env=env,
            task=task,
            step_limit=step_limit,
            initial_messages=initial_messages,
        )
    finally:
        if original_workflow_id is None:
            _dbos.DBOS.workflow_id = original_workflow_id


async def _run_agent_workflow_with_context(
    *,
    root_workflow_id: str,
    workflow_id: str,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None,
) -> dict:
    if model is None or env is None:
        await _publish_status_snapshot(
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            lifecycle_state="running",
        )
        metadata = (
            await _maybe_await(save_root_trajectory_artifact_step(root_workflow_id))
            if workflow_id == root_workflow_id
            else await _maybe_await(save_child_trajectory_artifact_step(root_workflow_id, workflow_id))
        )
        return {"status": "started", "terminal_state": "started", **metadata}

    state = AgentWorkflowState(
        messages=list(initial_messages) if initial_messages is not None else _initial_messages(model, task)
    )
    while True:
        await _publish_status_snapshot(
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            lifecycle_state="running",
        )
        state = await _run_agent_workflow_loop(
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            model=model,
            env=env,
            task=task,
            step_limit=step_limit,
            state=state,
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
            parent_direction_signal = await _wait_for_parent_direction_signal()
            waiting_result["parent_direction_signal"] = parent_direction_signal
            if _is_continuation_signal(parent_direction_signal):
                state.messages.append(_continuation_user_message(model, parent_direction_signal))
                state.first_observable_published = False
                continue
            if _is_close_signal(parent_direction_signal):
                closed_result = {
                    **waiting_result,
                    "status": "closed",
                    "terminal_state": "closed",
                }
                await _publish_status_snapshot(
                    root_workflow_id=root_workflow_id,
                    workflow_id=workflow_id,
                    lifecycle_state="closed",
                    latest_submission=result["submission"],
                )
                await _maybe_await(
                    save_child_trajectory_artifact_step(
                        root_workflow_id,
                        workflow_id,
                        status="closed",
                        messages=state.messages,
                        model_stats=result["model_stats"],
                        submission=result["submission"],
                    )
                )
                return closed_result
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
