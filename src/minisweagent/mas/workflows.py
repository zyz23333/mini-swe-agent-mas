"""DBOS workflows for the MAS subsystem boundary."""

from __future__ import annotations

from minisweagent.mas.artifacts import make_artifact_metadata, save_trajectory_artifact, validate_root_workflow_id
from minisweagent.mas.runtime import load_dbos

_dbos = load_dbos()


@_dbos.DBOS.step()
def save_root_trajectory_artifact_step(root_workflow_id: str) -> dict[str, str]:
    """Persist the Root Agent Workflow trajectory through a DBOS step."""
    save_trajectory_artifact(
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        status="started",
    )
    return make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=root_workflow_id)


@_dbos.DBOS.workflow()
def root_agent_workflow(root_workflow_id: str) -> dict[str, str]:
    """Minimal Root Agent Workflow that writes its deterministic Trajectory Artifact."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    metadata = save_root_trajectory_artifact_step(root_workflow_id)
    return {"status": "started", **metadata}
