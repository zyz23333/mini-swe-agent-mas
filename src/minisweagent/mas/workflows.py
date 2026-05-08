"""DBOS workflows for the MAS subsystem boundary."""

from __future__ import annotations

from minisweagent.mas.runtime import load_dbos

_dbos = load_dbos()


@_dbos.DBOS.workflow()
def root_agent_workflow() -> dict[str, str]:
    """Minimal Root Agent Workflow for the first MAS CLI slice."""
    return {"status": "started"}
