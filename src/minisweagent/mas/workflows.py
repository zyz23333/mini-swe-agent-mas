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
from minisweagent.mas.commands import MasCommandClassification, MasCommandKind, classify_mas_command
from minisweagent.mas.runtime import load_dbos
from minisweagent.mas.status import (
    FIRST_OBSERVABLE_EVENT_KEY,
    STATUS_EVENT_KEY,
    LifecycleState,
    format_direct_child_statuses,
    format_specific_status,
    make_status_snapshot,
    query_direct_child_status_async,
    query_direct_child_statuses_async,
    root_id_for_workflow,
)

_dbos = load_dbos()
child_agent_queue = _dbos.Queue("mini_mas_child_agent_workflows")
PARENT_DIRECTION_TOPIC = "mini_mas_parent_direction"
PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS = 60 * 60 * 24 * 30


async def _maybe_await(value):
    return await value if isawaitable(value) else value


def _current_agent_workflow_id() -> str | None:
    """Return the current DBOS workflow ID only when DBOS exposes a real workflow context."""
    workflow_id = _dbos.DBOS.workflow_id
    return workflow_id if isinstance(workflow_id, str) else None


@dataclass
class AgentWorkflowState:
    """Mutable state for one ordinary Agent Workflow loop."""

    messages: list[dict]
    cost: float = 0.0
    n_calls: int = 0
    spawn_count: int = 0
    first_observable_published: bool = False
    spawned_child_workflow_ids: set[str] | None = None


@dataclass(frozen=True)
class SpawnCommandRequest:
    """Parsed workflow-layer spawn command options."""

    tasks: list[str]
    wait: bool = False
    wait_all: bool = False
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class WaitCommandRequest:
    """Parsed workflow-layer wait command options."""

    workflow_id: str | None = None
    wait_all: bool = False
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class ContinueCommandRequest:
    """Parsed workflow-layer continuation command options."""

    workflow_id: str
    content: str


@dataclass(frozen=True)
class CloseCommandRequest:
    """Parsed workflow-layer close command options."""

    workflow_id: str


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


def _format_child_metadata_lines(child: dict[str, str]) -> list[str]:
    return [
        f"task: {child['task']}",
        f"workflow_id: {child['workflow_id']}",
        f"run_directory: {child['run_directory']}",
        f"trajectory_artifact_path: {child['trajectory_artifact_path']}",
    ]


def _format_detached_spawn_output(children: list[dict[str, str]]) -> str:
    lines = ["Detached spawn started", f"child_count: {len(children)}"]
    for index, child in enumerate(children):
        if index:
            lines.append("")
        lines.extend(_format_child_metadata_lines(child))
    return "\n".join(lines) + "\n"


def _snapshot_workflow_id(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("workflow_id", ""))


def _format_still_running_ids(still_running_ids: list[str]) -> str:
    return ", ".join(still_running_ids) if still_running_ids else "none"


def _format_ready_snapshot(snapshot: dict[str, Any]) -> list[str]:
    lines = [
        f"ready_workflow_id: {snapshot['workflow_id']}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
    ]
    if snapshot.get("latest_submission"):
        lines.append(f"latest_submission: {snapshot['latest_submission']}")
    if snapshot.get("latest_error"):
        lines.append(f"latest_error: {snapshot['latest_error']}")
    lines.extend(
        [
            f"run_directory: {snapshot['run_directory']}",
            f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
        ]
    )
    return lines


def _format_wait_summary_output(
    *,
    command_name: str,
    wait_all: bool,
    timed_out: bool,
    children: list[dict[str, str]],
    ready_snapshots: list[dict[str, Any]],
    still_running_ids: list[str],
) -> str:
    lines = [
        f"{command_name} {'timed out' if timed_out else 'completed'}",
        f"wait_mode: {'all' if wait_all else 'any'}",
        f"child_count: {len(children)}",
        f"ready_child_count: {len(ready_snapshots)}",
        f"still_running_child_workflow_ids: {_format_still_running_ids(still_running_ids)}",
        "",
        "started_children:",
    ]
    for index, child in enumerate(children):
        if index:
            lines.append("")
        lines.extend(_format_child_metadata_lines(child))
    if ready_snapshots:
        lines.extend(["", "ready_children:"])
        for index, snapshot in enumerate(ready_snapshots):
            if index:
                lines.append("")
            lines.extend(_format_ready_snapshot(snapshot))
    return "\n".join(lines) + "\n"


def _parse_timeout_seconds(raw_timeout: str) -> float:
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as exc:
        raise ValueError("Spawn timeout must be a number of seconds") from exc
    if timeout_seconds < 0:
        raise ValueError("Spawn timeout must be non-negative")
    return timeout_seconds


def _parse_spawn_arguments(arguments: list[str]) -> SpawnCommandRequest:
    wait = False
    wait_all = False
    timeout_seconds: float | None = None
    tasks = []
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--wait":
            wait = True
            index += 1
            continue
        if argument == "--all":
            wait_all = True
            index += 1
            continue
        if argument == "--timeout":
            if index + 1 >= len(arguments):
                raise ValueError("Spawn timeout requires a number of seconds")
            timeout_seconds = _parse_timeout_seconds(arguments[index + 1])
            index += 2
            continue
        if argument.startswith("--"):
            raise ValueError(f"Unsupported spawn option: {argument}")
        tasks.append(argument)
        index += 1

    if timeout_seconds is not None and not wait:
        raise ValueError("mini-mas spawn --timeout requires --wait because Detached Spawn has no wait phase")
    if wait_all and not wait:
        raise ValueError("mini-mas spawn --all requires --wait")
    if not tasks:
        raise ValueError('Usage: mini-mas spawn [--wait] [--all] [--timeout seconds] "task" [...]')
    return SpawnCommandRequest(tasks=tasks, wait=wait, wait_all=wait_all, timeout_seconds=timeout_seconds)


def _spawn_task_count(arguments: list[str]) -> int:
    try:
        return len(_parse_spawn_arguments(arguments).tasks)
    except ValueError:
        return 1


def _parse_wait_arguments(arguments: list[str]) -> WaitCommandRequest:
    wait_any = False
    wait_all = False
    timeout_seconds: float | None = None
    workflow_id: str | None = None
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--any":
            wait_any = True
            index += 1
            continue
        if argument == "--all":
            wait_all = True
            index += 1
            continue
        if argument == "--timeout":
            if index + 1 >= len(arguments):
                raise ValueError("Wait timeout requires a number of seconds")
            timeout_seconds = _parse_timeout_seconds(arguments[index + 1])
            index += 2
            continue
        if argument.startswith("--"):
            raise ValueError(f"Unsupported wait option: {argument}")
        if workflow_id is not None:
            raise ValueError("mini-mas wait accepts at most one workflow ID")
        workflow_id = validate_workflow_id(argument)
        index += 1

    if workflow_id is not None and (wait_any or wait_all):
        raise ValueError("mini-mas wait for one workflow cannot also use --any or --all")
    if wait_any and wait_all:
        raise ValueError("mini-mas wait cannot use both --any and --all")
    return WaitCommandRequest(workflow_id=workflow_id, wait_all=wait_all, timeout_seconds=timeout_seconds)


def _parse_continue_arguments(arguments: list[str]) -> ContinueCommandRequest:
    if len(arguments) != 3:
        raise ValueError('Usage: mini-mas continue <workflow-id> "message"')
    workflow_id = validate_workflow_id(arguments[1])
    content = arguments[2]
    if not content:
        raise ValueError('Usage: mini-mas continue <workflow-id> "message"')
    return ContinueCommandRequest(workflow_id=workflow_id, content=content)


def _parse_close_arguments(arguments: list[str]) -> CloseCommandRequest:
    if len(arguments) != 2:
        raise ValueError("Usage: mini-mas close <workflow-id>")
    return CloseCommandRequest(workflow_id=validate_workflow_id(arguments[1]))


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
        "task": task,
        **metadata,
    }


async def _spawn_detached_children(
    *,
    root_workflow_id: str,
    parent_workflow_id: str,
    first_spawn_index: int,
    tasks: list[str],
    existing_child_workflow_ids: set[str],
) -> list[dict[str, str]]:
    children = []
    for offset, task in enumerate(tasks):
        children.append(
            await _spawn_detached_child(
                root_workflow_id=root_workflow_id,
                parent_workflow_id=parent_workflow_id,
                spawn_index=first_spawn_index + offset,
                task=task,
                existing_child_workflow_ids=existing_child_workflow_ids,
            )
        )
    return children


async def _wait_for_first_observable_event(workflow_id: str, timeout_seconds: float) -> dict[str, Any] | None:
    event = await _maybe_await(_dbos.DBOS.get_event_async(workflow_id, FIRST_OBSERVABLE_EVENT_KEY, timeout_seconds))
    return event if isinstance(event, dict) else None


async def _wait_for_first_observable_events(
    *,
    child_workflow_ids: list[str],
    wait_all: bool,
    timeout_seconds: float | None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    if not child_workflow_ids:
        return [], [], False

    per_child_timeout = timeout_seconds if timeout_seconds is not None else 60
    waits = [
        asyncio.create_task(_wait_for_first_observable_event(workflow_id, per_child_timeout))
        for workflow_id in child_workflow_ids
    ]
    done, pending = await _maybe_await(
        _dbos.DBOS.asyncio_wait(
            waits,
            timeout=timeout_seconds,
            return_when=asyncio.ALL_COMPLETED if wait_all else asyncio.FIRST_COMPLETED,
        )
    )

    ready_snapshots = [task.result() for task in done if task.result() is not None]
    ready_ids = {_snapshot_workflow_id(snapshot) for snapshot in ready_snapshots}
    still_running_ids = [workflow_id for workflow_id in child_workflow_ids if workflow_id not in ready_ids]
    timed_out = not ready_snapshots or (wait_all and len(ready_snapshots) < len(child_workflow_ids))

    for pending_task in pending:
        pending_task.cancel()

    return sorted(ready_snapshots, key=_snapshot_workflow_id), still_running_ids, timed_out


async def _wait_for_direct_child_first_observable_events_with_status(
    *,
    parent_workflow_id: str,
    child_workflow_ids: list[str],
    wait_all: bool,
    timeout_seconds: float | None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Publish the parent's transient child-wait status around First Observable Event waiting."""
    root_workflow_id = root_id_for_workflow(parent_workflow_id)
    await _publish_status_snapshot(
        root_workflow_id=root_workflow_id,
        workflow_id=parent_workflow_id,
        lifecycle_state="waiting_for_child",
    )
    try:
        return await _wait_for_first_observable_events(
            child_workflow_ids=child_workflow_ids,
            wait_all=wait_all,
            timeout_seconds=timeout_seconds,
        )
    finally:
        await _publish_status_snapshot(
            root_workflow_id=root_workflow_id,
            workflow_id=parent_workflow_id,
            lifecycle_state="running",
        )


def _child_metadata_from_status(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        "task": "",
        "root_workflow_id": str(snapshot["root_workflow_id"]),
        "workflow_id": str(snapshot["workflow_id"]),
        "run_directory": str(snapshot["run_directory"]),
        "trajectory_artifact_path": str(snapshot["trajectory_artifact_path"]),
    }


async def _direct_child_metadata(*, parent_workflow_id: str, child_workflow_id: str | None = None) -> list[dict[str, str]]:
    if child_workflow_id is not None:
        snapshot = await query_direct_child_status_async(
            _dbos.DBOS,
            parent_workflow_id=parent_workflow_id,
            child_workflow_id=child_workflow_id,
        )
        return [] if snapshot is None else [_child_metadata_from_status(snapshot)]

    snapshots = await query_direct_child_statuses_async(_dbos.DBOS, parent_workflow_id)
    return sorted((_child_metadata_from_status(snapshot) for snapshot in snapshots), key=lambda child: child["workflow_id"])


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


async def _validate_parent_direction_target(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
    command_name: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate a parent-direction target and return either a status snapshot or an error result."""
    source_workflow_id = validate_workflow_id(source_workflow_id)
    target_workflow_id = validate_workflow_id(target_workflow_id)
    if target_workflow_id == source_workflow_id:
        return None, {
            "ok": False,
            "output": f"Cannot {command_name} the current Agent Workflow.\n",
            "returncode": 1,
            "exception_info": f"cannot_{command_name}_current_workflow",
            "extra": {"mas_command_error": f"cannot_{command_name}_current_workflow"},
        }
    if target_workflow_id == root_id_for_workflow(source_workflow_id):
        return None, {
            "ok": False,
            "output": f"Cannot {command_name} the Root Agent Workflow.\n",
            "returncode": 1,
            "exception_info": f"cannot_{command_name}_root_workflow",
            "extra": {"mas_command_error": f"cannot_{command_name}_root_workflow"},
        }

    snapshot = await query_direct_child_status_async(
        _dbos.DBOS,
        parent_workflow_id=source_workflow_id,
        child_workflow_id=target_workflow_id,
    )
    if snapshot is None:
        return None, {
            "ok": False,
            "output": f"Workflow is not a direct Child Agent Workflow of {source_workflow_id}: {target_workflow_id}\n",
            "returncode": 1,
            "exception_info": "workflow_not_direct_child",
            "extra": {"mas_command_error": "workflow_not_direct_child"},
        }
    if snapshot.get("lifecycle_state") != "waiting_for_parent":
        return None, {
            "ok": False,
            "output": f"Workflow is not waiting for parent direction: {target_workflow_id}\n",
            "returncode": 1,
            "exception_info": "workflow_not_waiting_for_parent",
            "extra": {"mas_command_error": "workflow_not_waiting_for_parent"},
        }
    return snapshot, None


async def send_continuation_signal_async(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
    content: str,
) -> dict[str, Any]:
    """Validate a child workflow and send a continuation signal through DBOS messages."""
    snapshot, error = await _validate_parent_direction_target(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        command_name="continue",
    )
    if error is not None:
        return error

    signal = make_continuation_signal(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        content=content,
    )
    await _maybe_await(_dbos.DBOS.send_async(target_workflow_id, signal, PARENT_DIRECTION_TOPIC))
    return {
        "ok": True,
        "output": _format_continue_output(
            target_workflow_id=target_workflow_id,
            content=content,
            snapshot=snapshot,
        ),
        "returncode": 0,
        "exception_info": "",
        "extra": {
            "mas_command": ["continue", target_workflow_id, content],
            "continued_workflow_id": target_workflow_id,
            "continuation_signal": signal,
            "target_status": snapshot,
        },
    }


async def send_close_signal_async(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
) -> dict[str, Any]:
    """Validate a child workflow and send a neutral close signal through DBOS messages."""
    snapshot, error = await _validate_parent_direction_target(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        command_name="close",
    )
    if error is not None:
        return error

    signal = make_close_signal(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
    )
    await _maybe_await(_dbos.DBOS.send_async(target_workflow_id, signal, PARENT_DIRECTION_TOPIC))
    return {
        "ok": True,
        "output": _format_close_output(
            target_workflow_id=target_workflow_id,
            snapshot=snapshot,
        ),
        "returncode": 0,
        "exception_info": "",
        "extra": {
            "mas_command": ["close", target_workflow_id],
            "closed_workflow_id": target_workflow_id,
            "close_signal": signal,
            "target_status": snapshot,
        },
    }


def _spawn_command_result(
    *,
    request: SpawnCommandRequest,
    children: list[dict[str, str]],
    output: str,
    extra: dict[str, Any] | None = None,
) -> dict:
    child_workflow_ids = [child["workflow_id"] for child in children]
    result_extra: dict[str, Any] = {
        "mas_command": ["spawn", *request.tasks],
        "spawned_child_count": len(children),
        "child_workflow_ids": child_workflow_ids,
        "children": children,
    }
    if len(children) == 1:
        result_extra["child_workflow_id"] = children[0]["workflow_id"]
        result_extra.update({key: value for key, value in children[0].items() if key != "task"})
    if extra:
        result_extra.update(extra)
    return {
        "output": output,
        "returncode": 0,
        "exception_info": "",
        "extra": result_extra,
    }


async def _dispatch_mas_command(
    classification: MasCommandClassification,
    *,
    spawn_index: int,
    existing_child_workflow_ids: set[str],
) -> dict:
    """Dispatch a validated standalone MAS command at workflow-control level."""
    current_workflow_id = _current_agent_workflow_id()
    if classification.arguments[:1] == ["status"]:
        if current_workflow_id is None:
            return {
                "output": "mini-mas status requires Agent Workflow context.\n",
                "returncode": 2,
                "exception_info": "missing_agent_workflow_context",
                "extra": {"mas_command_error": "missing_agent_workflow_context"},
            }
        current_workflow_id = validate_workflow_id(current_workflow_id)
        if len(classification.arguments) == 1:
            snapshots = await query_direct_child_statuses_async(_dbos.DBOS, current_workflow_id)
            output = format_direct_child_statuses(snapshots, parent_workflow_id=current_workflow_id)
            return {
                "output": output,
                "returncode": 0,
                "exception_info": "",
                "extra": {"mas_command": classification.arguments},
            }
        if len(classification.arguments) == 2:
            target_workflow_id = classification.arguments[1]
            snapshot = await query_direct_child_status_async(
                _dbos.DBOS,
                parent_workflow_id=current_workflow_id,
                child_workflow_id=target_workflow_id,
            )
            if snapshot is None:
                return {
                    "output": f"Workflow is not a direct Child Agent Workflow of {current_workflow_id}: {target_workflow_id}\n",
                    "returncode": 1,
                    "exception_info": "workflow_not_direct_child",
                    "extra": {
                        "mas_command": classification.arguments,
                        "mas_command_error": "workflow_not_direct_child",
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
        if current_workflow_id is None:
            return {
                "output": "mini-mas spawn requires Agent Workflow context.\n",
                "returncode": 2,
                "exception_info": "missing_agent_workflow_context",
                "extra": {"mas_command_error": "missing_agent_workflow_context"},
            }
        current_workflow_id = validate_workflow_id(current_workflow_id)
        root_workflow_id = root_id_for_workflow(current_workflow_id)
        try:
            request = _parse_spawn_arguments(classification.arguments)
        except ValueError as exc:
            return {
                "output": f"{exc}\n",
                "returncode": 2,
                "exception_info": str(exc),
                "extra": {"mas_command_error": "invalid_spawn_arguments"},
            }
        children = await _spawn_detached_children(
            root_workflow_id=root_workflow_id,
            parent_workflow_id=current_workflow_id,
            first_spawn_index=spawn_index,
            tasks=request.tasks,
            existing_child_workflow_ids=existing_child_workflow_ids,
        )
        if request.wait:
            ready_snapshots, still_running_ids, timed_out = (
                await _wait_for_direct_child_first_observable_events_with_status(
                    parent_workflow_id=current_workflow_id,
                    child_workflow_ids=[child["workflow_id"] for child in children],
                    wait_all=request.wait_all,
                    timeout_seconds=request.timeout_seconds,
                )
            )
            return _spawn_command_result(
                request=request,
                children=children,
                output=_format_wait_summary_output(
                    command_name="Waited spawn",
                    wait_all=request.wait_all,
                    timed_out=timed_out,
                    children=children,
                    ready_snapshots=ready_snapshots,
                    still_running_ids=still_running_ids,
                ),
                extra={
                    "waited": True,
                    "wait_mode": "all" if request.wait_all else "any",
                    "timed_out": timed_out,
                    "ready_children": ready_snapshots,
                    "still_running_child_workflow_ids": still_running_ids,
                },
            )
        return _spawn_command_result(
            request=request,
            children=children,
            output=_format_detached_spawn_output(children),
            extra={"waited": False, "ready_children": [], "still_running_child_workflow_ids": []},
        )

    if classification.arguments[:1] == ["wait"]:
        if current_workflow_id is None:
            return {
                "output": "mini-mas wait requires Agent Workflow context.\n",
                "returncode": 2,
                "exception_info": "missing_agent_workflow_context",
                "extra": {"mas_command_error": "missing_agent_workflow_context"},
            }
        current_workflow_id = validate_workflow_id(current_workflow_id)
        try:
            request = _parse_wait_arguments(classification.arguments)
        except ValueError as exc:
            return {
                "output": f"{exc}\n",
                "returncode": 2,
                "exception_info": str(exc),
                "extra": {"mas_command_error": "invalid_wait_arguments"},
            }
        children = await _direct_child_metadata(parent_workflow_id=current_workflow_id, child_workflow_id=request.workflow_id)
        if not children:
            output = (
                f"Workflow is not a direct Child Agent Workflow of {current_workflow_id}: {request.workflow_id}\n"
                if request.workflow_id
                else "No current child workflows found for mini-mas wait.\n"
            )
            return {
                "output": output,
                "returncode": 1,
                "exception_info": "workflow_not_direct_child" if request.workflow_id else "no_child_workflows",
                "extra": {
                    "mas_command": classification.arguments,
                    "mas_command_error": "workflow_not_direct_child" if request.workflow_id else "no_child_workflows",
                },
            }
        wait_all = request.wait_all or request.workflow_id is not None
        ready_snapshots, still_running_ids, timed_out = (
            await _wait_for_direct_child_first_observable_events_with_status(
                parent_workflow_id=current_workflow_id,
                child_workflow_ids=[child["workflow_id"] for child in children],
                wait_all=wait_all,
                timeout_seconds=request.timeout_seconds,
            )
        )
        wait_mode = "one" if request.workflow_id is not None else ("all" if wait_all else "any")
        output = _format_wait_summary_output(
            command_name="mini-mas wait",
            wait_all=wait_all,
            timed_out=timed_out,
            children=children,
            ready_snapshots=ready_snapshots,
            still_running_ids=still_running_ids,
        ).replace(f"wait_mode: {'all' if wait_all else 'any'}", f"wait_mode: {wait_mode}", 1)
        return {
            "output": output,
            "returncode": 0,
            "exception_info": "",
            "extra": {
                "mas_command": classification.arguments,
                "wait_mode": wait_mode,
                "timed_out": timed_out,
                "ready_children": ready_snapshots,
                "still_running_child_workflow_ids": still_running_ids,
                "children": children,
            },
        }

    if classification.arguments[:1] == ["continue"]:
        if current_workflow_id is None:
            return {
                "output": "mini-mas continue requires Agent Workflow context.\n",
                "returncode": 2,
                "exception_info": "missing_agent_workflow_context",
                "extra": {"mas_command_error": "missing_agent_workflow_context"},
            }
        current_workflow_id = validate_workflow_id(current_workflow_id)
        try:
            request = _parse_continue_arguments(classification.arguments)
        except ValueError as exc:
            return {
                "output": f"{exc}\n",
                "returncode": 2,
                "exception_info": str(exc),
                "extra": {"mas_command_error": "invalid_continue_arguments"},
            }
        result = await send_continuation_signal_async(
            source_workflow_id=current_workflow_id,
            target_workflow_id=request.workflow_id,
            content=request.content,
        )
        result["extra"] = {"mas_command": classification.arguments, **result.get("extra", {})}
        result.pop("ok", None)
        return result

    if classification.arguments[:1] == ["close"]:
        if current_workflow_id is None:
            return {
                "output": "mini-mas close requires Agent Workflow context.\n",
                "returncode": 2,
                "exception_info": "missing_agent_workflow_context",
                "extra": {"mas_command_error": "missing_agent_workflow_context"},
            }
        current_workflow_id = validate_workflow_id(current_workflow_id)
        try:
            request = _parse_close_arguments(classification.arguments)
        except ValueError as exc:
            return {
                "output": f"{exc}\n",
                "returncode": 2,
                "exception_info": str(exc),
                "extra": {"mas_command_error": "invalid_close_arguments"},
            }
        result = await send_close_signal_async(
            source_workflow_id=current_workflow_id,
            target_workflow_id=request.workflow_id,
        )
        result["extra"] = {"mas_command": classification.arguments, **result.get("extra", {})}
        result.pop("ok", None)
        return result

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
            outputs.append(
                await _dispatch_mas_command(
                    classification,
                    spawn_index=current_spawn_index + 1,
                    existing_child_workflow_ids=existing_child_workflow_ids,
                )
            )
            if classification.arguments[:1] == ["spawn"]:
                current_spawn_index += _spawn_task_count(classification.arguments)
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
            state.spawn_count += sum(
                _spawn_task_count(classification.arguments)
                for action in message.get("extra", {}).get("actions", [])
                for classification in [classify_mas_command(action.get("command", ""))]
                if classification.arguments[:1] == ["spawn"]
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
