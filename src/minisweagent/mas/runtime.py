"""Runtime wiring for the DBOS-backed MAS command path."""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Mapping
from typing import Any

from minisweagent.mas.artifacts import make_agent_id, make_artifact_metadata, validate_agent_id
from minisweagent.mas.signals import (
    ROOT_COMMAND_TOPIC,
    make_root_command_signal,
    root_command_result_event_key,
)
from minisweagent.mas.status_events import STATUS_EVENT_KEY, normalize_agent_snapshot

MAS_APP_NAME = "mini-swe-agent-mas"
UNSUPPORTED_EXTERNAL_COORDINATION_MESSAGE = (
    "External mini-mas status, wait, continue, and close are unsupported until terminal commands are routed through "
    "an Interactive Root Agent.\n"
)
UNSUPPORTED_EXTERNAL_COORDINATION_ERROR = "external_agent_interaction_unsupported"


def load_dbos():
    """Import DBOS only inside the MAS path."""
    import dbos

    return dbos


def make_dbos_config(*, system_database_url: str | None = None) -> dict[str, str | None]:
    """Build the minimal DBOS configuration for the external MAS CLI."""
    return {
        "name": MAS_APP_NAME,
        "system_database_url": (
            system_database_url if system_database_url is not None else os.environ.get("DBOS_SYSTEM_DATABASE_URL")
        ),
    }


def _handle_workflow_id(handle: Any) -> str:
    if hasattr(handle, "get_workflow_id"):
        return str(handle.get_workflow_id())
    return str(handle.workflow_id)


def make_command_id() -> str:
    """Generate an opaque Root command ID."""
    return f"cmd-{secrets.token_hex(8)}"


def _format_run_result(*, agent_id: str, result: Any | None, wait: bool) -> dict[str, Any]:
    data: dict[str, Any] = make_artifact_metadata(agent_id=agent_id)
    if wait:
        data["result"] = result
    return data


def _format_interactive_root_result(*, agent_id: str, result: Mapping[str, Any] | None) -> dict[str, Any]:
    data: dict[str, Any] = make_artifact_metadata(agent_id=agent_id)
    if result is not None and result.get("lifecycle_state"):
        data["lifecycle_state"] = result["lifecycle_state"]
    return data


def _unsupported_external_agent_interaction_result(*, workflow_id: str) -> dict[str, Any]:
    """Return the shared unsupported result for naked external Agent Interaction commands."""
    return {
        "kind": "unsupported",
        "agent_id": workflow_id,
        "output": UNSUPPORTED_EXTERNAL_COORDINATION_MESSAGE,
        "returncode": 2,
        "exception_info": UNSUPPORTED_EXTERNAL_COORDINATION_ERROR,
        "extra": {"mas_command_error": UNSUPPORTED_EXTERNAL_COORDINATION_ERROR},
    }


async def _start_root_agent_workflow_async(
    *,
    workflow_id: str | None = None,
    wait: bool = True,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for DBOS workflow startup and optional result waiting."""
    dbos_module = load_dbos()

    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))

    from minisweagent.mas.mas_agent import root_agent_workflow

    dbos_module.DBOS.launch()

    assigned_workflow_id = validate_agent_id(workflow_id or make_agent_id())
    with dbos_module.SetWorkflowID(assigned_workflow_id):
        handle = await dbos_module.DBOS.start_workflow_async(root_agent_workflow, assigned_workflow_id)

    started_workflow_id = _handle_workflow_id(handle)
    result = await handle.get_result() if wait else None
    return _format_run_result(agent_id=started_workflow_id, result=result, wait=wait)


def start_root_agent_workflow(
    *,
    workflow_id: str | None = None,
    wait: bool = True,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS, launch it, and start a Root Agent through async DBOS APIs."""
    return asyncio.run(
        _start_root_agent_workflow_async(
            workflow_id=workflow_id,
            wait=wait,
            system_database_url=system_database_url,
        )
    )


async def _start_interactive_root_agent_workflow_async(
    *,
    workflow_id: str | None = None,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for starting an Interactive Root Agent and waiting until it is idle."""
    dbos_module = load_dbos()

    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))

    from minisweagent.mas.mas_agent import interactive_root_agent_workflow

    dbos_module.DBOS.launch()

    assigned_workflow_id = validate_agent_id(workflow_id or make_agent_id())
    with dbos_module.SetWorkflowID(assigned_workflow_id):
        handle = await dbos_module.DBOS.start_workflow_async(
            interactive_root_agent_workflow,
            assigned_workflow_id,
            max_commands=None,
        )

    started_workflow_id = _handle_workflow_id(handle)
    result = await dbos_module.DBOS.get_event_async(started_workflow_id, STATUS_EVENT_KEY, 60)
    return _format_interactive_root_result(agent_id=started_workflow_id, result=result)


def start_interactive_root_agent_workflow(
    *,
    workflow_id: str | None = None,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS and start the minimal Interactive Root Agent path."""
    return asyncio.run(
        _start_interactive_root_agent_workflow_async(
            workflow_id=workflow_id,
            system_database_url=system_database_url,
        )
    )


async def _send_root_command_async(
    *,
    root_agent_id: str,
    command: str,
    command_id: str | None = None,
    result_timeout_seconds: float = 60,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for submitting one Root Command Signal and waiting for its scoped result."""
    dbos_module = load_dbos()
    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))
    dbos_module.DBOS.launch()

    root_agent_id = validate_agent_id(root_agent_id)
    command_id = command_id or make_command_id()
    signal = make_root_command_signal(
        command_id=command_id,
        root_agent_id=root_agent_id,
        command=command,
        source="external_cli",
    )
    await dbos_module.DBOS.send_async(root_agent_id, signal, ROOT_COMMAND_TOPIC)
    event = await dbos_module.DBOS.get_event_async(
        root_agent_id,
        root_command_result_event_key(command_id),
        result_timeout_seconds,
    )
    if not isinstance(event, Mapping):
        return {
            "kind": "root_command_result_timeout",
            "command_id": command_id,
            "root_agent_id": root_agent_id,
            "command": command,
            "result": {
                "output": "Timed out waiting for Root Command Result.\n",
                "returncode": 1,
                "exception_info": "root_command_result_timeout",
                "extra": {"mas_command_error": "root_command_result_timeout"},
            },
        }
    return event


def send_root_command(
    *,
    root_agent_id: str,
    command: str,
    command_id: str | None = None,
    result_timeout_seconds: float = 60,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS, send one Root command, and wait on the command-id-scoped result event."""
    return asyncio.run(
        _send_root_command_async(
            root_agent_id=root_agent_id,
            command=command,
            command_id=command_id,
            result_timeout_seconds=result_timeout_seconds,
            system_database_url=system_database_url,
        )
    )


def _resume_invalid_agent_id_result(*, root_agent_id: str, error: ValueError) -> dict[str, Any]:
    return {
        "kind": "resume_unavailable",
        "root_agent_id": root_agent_id,
        "output": f"Invalid Agent ID for resume: {root_agent_id}\n{error}\n",
        "returncode": 2,
        "exception_info": "invalid_agent_id",
        "extra": {"mas_command_error": "invalid_agent_id"},
    }


def _resume_unavailable_result(
    *,
    root_agent_id: str,
    output: str,
    exception_info: str,
    lifecycle_state: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "resume_unavailable",
        "root_agent_id": root_agent_id,
        "output": output,
        "returncode": 2,
        "exception_info": exception_info,
        "extra": {"mas_command_error": exception_info},
    }
    if lifecycle_state:
        result["lifecycle_state"] = lifecycle_state
    return result


def _resume_unavailable_lifecycle_result(*, root_agent_id: str, lifecycle_state: str) -> dict[str, Any]:
    return _resume_unavailable_result(
        root_agent_id=root_agent_id,
        lifecycle_state=lifecycle_state,
        exception_info="root_agent_not_waiting_for_command",
        output=(
            "Root Agent is not available for resume.\n"
            f"root_agent_id: {root_agent_id}\n"
            f"lifecycle_state: {lifecycle_state}\n"
            "Use mini-mas status to inspect Root Agents, then retry "
            f"mini-mas resume {root_agent_id} later when it is waiting_for_command.\n"
        ),
    )


def _is_interactive_root_workflow(workflow_status: Any) -> bool:
    return getattr(workflow_status, "name", "") == "interactive_root_agent_workflow"


def _parent_workflow_id(workflow_status: Any) -> str | None:
    parent_workflow_id = getattr(workflow_status, "parent_workflow_id", None)
    return str(parent_workflow_id) if parent_workflow_id else None


def _root_discovery_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    metadata = normalize_agent_snapshot(dict(snapshot))
    return {
        "agent_id": metadata["agent_id"],
        "lifecycle_state": metadata["lifecycle_state"],
        "agent_artifact_directory": metadata["agent_artifact_directory"],
        "trajectory_artifact_path": metadata["trajectory_artifact_path"],
    }


def _format_root_discovery(snapshots: list[Mapping[str, Any]]) -> str:
    lines = ["Interactive Root Agents"]
    if not snapshots:
        lines.append("No Interactive Root Agents found.")
        return "\n".join(lines) + "\n"

    for index, snapshot in enumerate(snapshots):
        if index:
            lines.append("")
        lines.extend(
            [
                f"agent_id: {snapshot['agent_id']}",
                f"lifecycle_state: {snapshot['lifecycle_state']}",
                f"agent_artifact_directory: {snapshot['agent_artifact_directory']}",
                f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
            ]
        )
    return "\n".join(lines) + "\n"


async def _discover_interactive_root_agents_async(
    *,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for external Interactive Root Agent discovery."""
    dbos_module = load_dbos()
    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))
    dbos_module.DBOS.launch()

    workflow_statuses = await dbos_module.DBOS.list_workflows_async(
        name="interactive_root_agent_workflow",
        has_parent=False,
        load_input=False,
        load_output=False,
    )

    snapshots: list[dict[str, Any]] = []
    for workflow_status in workflow_statuses:
        if _parent_workflow_id(workflow_status) is not None or not _is_interactive_root_workflow(workflow_status):
            continue
        workflow_id = validate_agent_id(str(getattr(workflow_status, "workflow_id", "")))
        snapshot = await dbos_module.DBOS.get_event_async(workflow_id, STATUS_EVENT_KEY, 1)
        if not isinstance(snapshot, Mapping):
            msg = f"Missing lifecycle status event for Interactive Root Agent: {workflow_id}"
            raise RuntimeError(msg)
        snapshots.append(_root_discovery_snapshot(snapshot))

    snapshots = sorted(snapshots, key=lambda snapshot: snapshot["agent_id"])
    return {
        "kind": "interactive_root_discovery",
        "roots": snapshots,
        "output": _format_root_discovery(snapshots),
        "returncode": 0,
    }


def discover_interactive_root_agents(
    *,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS and list parentless Interactive Root Agent workflows."""
    return asyncio.run(_discover_interactive_root_agents_async(system_database_url=system_database_url))


async def _prepare_resume_root_agent_async(
    *,
    root_agent_id: str,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for validating an Interactive Root Agent before resume."""
    try:
        root_agent_id = validate_agent_id(root_agent_id)
    except ValueError as exc:
        return _resume_invalid_agent_id_result(root_agent_id=root_agent_id, error=exc)

    dbos_module = load_dbos()
    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))
    dbos_module.DBOS.launch()

    workflow_status = await dbos_module.DBOS.get_workflow_status_async(root_agent_id)
    if workflow_status is None:
        return _resume_unavailable_result(
            root_agent_id=root_agent_id,
            lifecycle_state="unknown",
            exception_info="unknown_root_agent_id",
            output=(
                f"Unknown Root Agent ID: {root_agent_id}\n"
                f"root_agent_id: {root_agent_id}\n"
                "lifecycle_state: unknown\n"
                "Use mini-mas status to inspect Root Agents.\n"
            ),
        )

    parent_workflow_id = _parent_workflow_id(workflow_status)
    if parent_workflow_id is not None:
        return _resume_unavailable_result(
            root_agent_id=root_agent_id,
            lifecycle_state="unknown",
            exception_info="not_parentless_interactive_root_agent",
            output=(
                "Resume target is not a parentless Interactive Root Agent.\n"
                f"root_agent_id: {root_agent_id}\n"
                "lifecycle_state: unknown\n"
                f"parent_agent_id: {parent_workflow_id}\n"
                "Use mini-mas status to inspect Root Agents.\n"
            ),
        )

    if not _is_interactive_root_workflow(workflow_status):
        return _resume_unavailable_result(
            root_agent_id=root_agent_id,
            lifecycle_state="unknown",
            exception_info="not_interactive_root_agent",
            output=(
                "Resume target is not an Interactive Root Agent workflow.\n"
                f"root_agent_id: {root_agent_id}\n"
                "lifecycle_state: unknown\n"
                f"workflow_name: {getattr(workflow_status, 'name', '')}\n"
                "Use mini-mas status to inspect Root Agents.\n"
            ),
        )

    snapshot = await dbos_module.DBOS.get_event_async(root_agent_id, STATUS_EVENT_KEY, 1)
    if not isinstance(snapshot, Mapping):
        return _resume_unavailable_lifecycle_result(root_agent_id=root_agent_id, lifecycle_state="unknown")

    metadata = normalize_agent_snapshot(dict(snapshot))
    lifecycle_state = str(metadata["lifecycle_state"])
    if lifecycle_state != "waiting_for_command":
        return _resume_unavailable_lifecycle_result(root_agent_id=root_agent_id, lifecycle_state=lifecycle_state)

    return {
        "kind": "resume_ready",
        "root_agent_id": root_agent_id,
        **metadata,
        "returncode": 0,
    }


def prepare_resume_root_agent(
    *,
    root_agent_id: str,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Validate an Interactive Root Agent before the resume terminal attaches."""
    return asyncio.run(
        _prepare_resume_root_agent_async(
            root_agent_id=root_agent_id,
            system_database_url=system_database_url,
        )
    )


async def _get_agent_workflow_status_async(
    *,
    workflow_id: str,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for non-blocking MAS status snapshot or tree lookup."""
    return _unsupported_external_agent_interaction_result(workflow_id=workflow_id)


def get_agent_workflow_status(
    *,
    workflow_id: str,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS and read a non-blocking MAS status snapshot or tree through async DBOS APIs."""
    return asyncio.run(
        _get_agent_workflow_status_async(
            workflow_id=workflow_id,
            system_database_url=system_database_url,
        )
    )


async def _wait_for_agent_workflow_async(
    *,
    workflow_id: str,
    timeout_seconds: float | None = None,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for external waiting on one Child First Observable Event."""
    return _unsupported_external_agent_interaction_result(workflow_id=workflow_id)


def wait_for_agent_workflow(
    *,
    workflow_id: str,
    timeout_seconds: float | None = None,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS and wait for one Child First Observable Event."""
    return asyncio.run(
        _wait_for_agent_workflow_async(
            workflow_id=workflow_id,
            timeout_seconds=timeout_seconds,
            system_database_url=system_database_url,
        )
    )


async def _continue_agent_workflow_async(
    *,
    workflow_id: str,
    message: str,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for external parent-to-child continuation signaling."""
    return _unsupported_external_agent_interaction_result(workflow_id=workflow_id)


def continue_agent_workflow(
    *,
    workflow_id: str,
    message: str,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS and send a continuation signal to one waiting Child Agent."""
    return asyncio.run(
        _continue_agent_workflow_async(
            workflow_id=workflow_id,
            message=message,
            system_database_url=system_database_url,
        )
    )


async def _close_agent_workflow_async(
    *,
    workflow_id: str,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for external parent-to-child neutral close signaling."""
    return _unsupported_external_agent_interaction_result(workflow_id=workflow_id)


def close_agent_workflow(
    *,
    workflow_id: str,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS and send a neutral close signal to one waiting Child Agent."""
    return asyncio.run(
        _close_agent_workflow_async(
            workflow_id=workflow_id,
            system_database_url=system_database_url,
        )
    )
