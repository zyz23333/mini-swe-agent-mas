"""Runtime wiring for the DBOS-backed MAS command path."""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Mapping
from typing import Any

from minisweagent.mas.artifacts import make_artifact_metadata, validate_agent_id, validate_root_agent_id

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


def make_root_agent_id() -> str:
    """Return a readable Root Agent ID."""
    return f"mas-{secrets.token_hex(8)}"


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


def _format_run_result(*, root_workflow_id: str, result: Any | None, wait: bool) -> dict[str, Any]:
    data: dict[str, Any] = make_artifact_metadata(
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
    )
    if wait:
        data["result"] = result
    return data


def _unsupported_external_agent_interaction_result(*, workflow_id: str) -> dict[str, Any]:
    """Return the shared unsupported result for naked external Agent Interaction commands."""
    return {
        "kind": "unsupported",
        "workflow_id": workflow_id,
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

    assigned_workflow_id = validate_root_agent_id(workflow_id or make_root_agent_id())
    with dbos_module.SetWorkflowID(assigned_workflow_id):
        handle = await dbos_module.DBOS.start_workflow_async(root_agent_workflow, assigned_workflow_id)

    started_workflow_id = _handle_workflow_id(handle)
    result = await handle.get_result() if wait else None
    return _format_run_result(root_workflow_id=started_workflow_id, result=result, wait=wait)


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


def parent_id_for_workflow(workflow_id: str) -> str:
    """Return the encoded immediate Parent Agent ID for a descendant Agent."""
    workflow_id = validate_agent_id(workflow_id)
    parent_id, separator, _child_suffix = workflow_id.rpartition("-c")
    if not separator:
        return workflow_id
    return validate_agent_id(parent_id)


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
