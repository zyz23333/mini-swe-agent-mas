"""Runtime wiring for the DBOS-backed MAS command path."""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from typing import Any

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


def _format_run_result(*, workflow_id: str, result: Any | None, wait: bool) -> dict[str, Any]:
    data: dict[str, Any] = {"workflow_id": workflow_id}
    if wait:
        data["result"] = result
    return data


def start_root_agent_workflow(
    *,
    workflow_id: str | None = None,
    wait: bool = False,
    system_database_url: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS, launch it, and start a minimal Root Agent Workflow."""
    dbos_module = load_dbos()

    dbos_module.DBOS(config=make_dbos_config(system_database_url=system_database_url))

    from minisweagent.mas.workflows import root_agent_workflow

    dbos_module.DBOS.launch()

    assigned_workflow_id = workflow_id or make_root_workflow_id()
    with dbos_module.SetWorkflowID(assigned_workflow_id):
        handle = dbos_module.DBOS.start_workflow(root_agent_workflow)

    started_workflow_id = _handle_workflow_id(handle)
    result = handle.get_result() if wait else None
    return _format_run_result(workflow_id=started_workflow_id, result=result, wait=wait)
