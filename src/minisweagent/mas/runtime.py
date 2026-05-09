"""Runtime wiring for the DBOS-backed MAS command path."""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Mapping
from typing import Any

from minisweagent.mas.artifacts import make_artifact_metadata, validate_root_workflow_id, validate_workflow_id
from minisweagent.mas.status import (
    FIRST_OBSERVABLE_EVENT_KEY,
    query_specific_status_async,
    query_status_tree_async,
    root_id_for_workflow,
)

MAS_APP_NAME = "mini-swe-agent-mas"


def load_dbos():
    """Import DBOS only inside the MAS path."""
    import dbos

    return dbos


def make_root_workflow_id() -> str:
    """Return a readable root Workflow Tree ID."""
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


async def _start_root_agent_workflow_async(
    *,
    workflow_id: str | None = None,
    wait: bool = True,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Async implementation for DBOS workflow startup and optional result waiting."""
    dbos_module = load_dbos()

    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))

    from minisweagent.mas.workflows import root_agent_workflow

    dbos_module.DBOS.launch()

    assigned_workflow_id = validate_root_workflow_id(workflow_id or make_root_workflow_id())
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
    """Initialize DBOS, launch it, and start a Root Agent Workflow through async DBOS APIs."""
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
    dbos_module = load_dbos()
    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))

    from minisweagent.mas import workflows  # noqa: F401

    dbos_module.DBOS.launch()

    workflow_id = validate_workflow_id(workflow_id)
    root_workflow_id = root_id_for_workflow(workflow_id)
    if workflow_id == root_workflow_id:
        return {
            "kind": "tree",
            "root_workflow_id": root_workflow_id,
            "snapshots": await query_status_tree_async(dbos_module.DBOS, root_workflow_id),
        }

    snapshot = await query_specific_status_async(
        dbos_module.DBOS,
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
    )
    if snapshot is None:
        return {
            "kind": "missing",
            "root_workflow_id": root_workflow_id,
            "workflow_id": workflow_id,
        }
    return {
        "kind": "single",
        "root_workflow_id": root_workflow_id,
        "workflow_id": workflow_id,
        "snapshot": snapshot,
    }


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
    dbos_module = load_dbos()
    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))

    from minisweagent.mas import workflows  # noqa: F401

    dbos_module.DBOS.launch()

    workflow_id = validate_workflow_id(workflow_id)
    root_workflow_id = root_id_for_workflow(workflow_id)
    event = await dbos_module.DBOS.get_event_async(
        workflow_id,
        FIRST_OBSERVABLE_EVENT_KEY,
        60 if timeout_seconds is None else timeout_seconds,
    )
    metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)
    ready_children = [event] if isinstance(event, dict) else []
    return {
        "workflow_id": workflow_id,
        "root_workflow_id": root_workflow_id,
        "wait_mode": "one",
        "timed_out": not ready_children,
        "ready_children": ready_children,
        "still_running_child_workflow_ids": [] if ready_children else [workflow_id],
        "children": [{"task": "", **metadata}],
    }


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
