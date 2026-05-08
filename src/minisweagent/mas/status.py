"""Lightweight MAS Agent Workflow status snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from minisweagent.mas.artifacts import make_artifact_metadata, validate_root_workflow_id, validate_workflow_id

STATUS_EVENT_KEY = "mini_mas_status"
LifecycleState = Literal["running", "waiting_for_parent", "closed", "failed", "limits_exceeded"]
LIFECYCLE_STATES: tuple[LifecycleState, ...] = (
    "running",
    "waiting_for_parent",
    "closed",
    "failed",
    "limits_exceeded",
)


@dataclass(frozen=True)
class AgentStatusSnapshot:
    """Lightweight status data exposed through DBOS events."""

    root_workflow_id: str
    workflow_id: str
    lifecycle_state: LifecycleState
    run_directory: str
    trajectory_artifact_path: str
    latest_submission: str = ""
    latest_error: str = ""

    def to_event(self) -> dict[str, str]:
        data = {
            "root_workflow_id": self.root_workflow_id,
            "workflow_id": self.workflow_id,
            "workflow_tree_id": self.workflow_id,
            "lifecycle_state": self.lifecycle_state,
            "run_directory": self.run_directory,
            "trajectory_artifact_path": self.trajectory_artifact_path,
        }
        if self.latest_submission:
            data["latest_submission"] = self.latest_submission
        if self.latest_error:
            data["latest_error"] = self.latest_error
        return data


def make_status_snapshot(
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> AgentStatusSnapshot:
    """Build the status snapshot shape stored in DBOS events."""
    if lifecycle_state not in LIFECYCLE_STATES:
        raise ValueError(f"Unsupported MAS lifecycle state: {lifecycle_state}")
    metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)
    return AgentStatusSnapshot(
        root_workflow_id=metadata["root_workflow_id"],
        workflow_id=metadata["workflow_id"],
        lifecycle_state=lifecycle_state,
        run_directory=metadata["run_directory"],
        trajectory_artifact_path=metadata["trajectory_artifact_path"],
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


def root_id_for_workflow(workflow_id: str) -> str:
    """Return the Root Agent Workflow ID encoded in a Workflow Tree ID."""
    workflow_id = validate_workflow_id(workflow_id)
    return validate_root_workflow_id(workflow_id[:20])


def is_descendant_or_self(*, root_workflow_id: str, workflow_id: str) -> bool:
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    workflow_id = validate_workflow_id(workflow_id)
    return workflow_id == root_workflow_id or workflow_id.startswith(f"{root_workflow_id}-c")


def _status_from_events(events: dict[str, Any]) -> dict[str, Any] | None:
    status = events.get(STATUS_EVENT_KEY)
    return status if isinstance(status, dict) else None


def query_status_tree(dbos_api: Any, root_workflow_id: str) -> list[dict[str, Any]]:
    """Query current status snapshots for one Agent Workflow Tree without waiting for descendants."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    workflow_statuses = dbos_api.list_workflows(
        workflow_id_prefix=root_workflow_id,
        load_input=False,
        load_output=False,
    )
    snapshots = []
    for workflow_status in workflow_statuses:
        workflow_id = getattr(workflow_status, "workflow_id", "")
        if not is_descendant_or_self(root_workflow_id=root_workflow_id, workflow_id=workflow_id):
            continue
        snapshot = _status_from_events(dbos_api.get_all_events(workflow_id))
        if snapshot is not None:
            snapshots.append(snapshot)
    return sorted(snapshots, key=lambda snapshot: snapshot["workflow_id"])


def query_specific_status(dbos_api: Any, *, root_workflow_id: str, workflow_id: str) -> dict[str, Any] | None:
    """Query one descendant status snapshot without waiting for workflow completion."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    workflow_id = validate_workflow_id(workflow_id)
    if not is_descendant_or_self(root_workflow_id=root_workflow_id, workflow_id=workflow_id):
        return None
    return _status_from_events(dbos_api.get_all_events(workflow_id))


def _format_snapshot(snapshot: dict[str, Any]) -> list[str]:
    lines = [
        f"workflow_id: {snapshot['workflow_id']}",
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


def format_status_tree(snapshots: list[dict[str, Any]], *, root_workflow_id: str) -> str:
    """Format a status tree as a bash observation."""
    lines = [f"Agent Workflow Tree: {root_workflow_id}"]
    if not snapshots:
        lines.append("No status snapshots found.")
        return "\n".join(lines) + "\n"
    for index, snapshot in enumerate(snapshots):
        if index:
            lines.append("")
        lines.extend(_format_snapshot(snapshot))
    return "\n".join(lines) + "\n"


def format_specific_status(snapshot: dict[str, Any]) -> str:
    return "\n".join(_format_snapshot(snapshot)) + "\n"
