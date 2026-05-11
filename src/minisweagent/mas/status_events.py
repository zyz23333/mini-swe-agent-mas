"""Lightweight MAS Agent status snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Literal

from minisweagent.mas.artifacts import make_artifact_metadata, validate_agent_id

STATUS_EVENT_KEY = "mini_mas_status"
FIRST_OBSERVABLE_EVENT_KEY = "mini_mas_first_observable"
LifecycleState = Literal["running", "waiting_for_child", "waiting_for_parent", "closed", "failed", "limits_exceeded"]
LIFECYCLE_STATES: tuple[LifecycleState, ...] = (
    "running",
    "waiting_for_child",
    "waiting_for_parent",
    "closed",
    "failed",
    "limits_exceeded",
)


async def _maybe_await(value: Any) -> Any:
    return await value if isawaitable(value) else value


@dataclass(frozen=True)
class AgentStatusSnapshot:
    """Lightweight status data exposed through DBOS events."""

    agent_id: str
    lifecycle_state: LifecycleState
    agent_artifact_directory: str
    trajectory_artifact_path: str
    parent_agent_id: str = ""
    latest_submission: str = ""
    latest_error: str = ""

    def to_event(self) -> dict[str, str]:
        data = {
            "agent_id": self.agent_id,
            "lifecycle_state": self.lifecycle_state,
            "agent_artifact_directory": self.agent_artifact_directory,
            "trajectory_artifact_path": self.trajectory_artifact_path,
        }
        if self.parent_agent_id:
            data["parent_agent_id"] = self.parent_agent_id
        if self.latest_submission:
            data["latest_submission"] = self.latest_submission
        if self.latest_error:
            data["latest_error"] = self.latest_error
        return data


def make_status_snapshot(
    *,
    agent_id: str,
    parent_agent_id: str | None = None,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> AgentStatusSnapshot:
    """Build the status snapshot shape stored in DBOS events."""
    if lifecycle_state not in LIFECYCLE_STATES:
        raise ValueError(f"Unsupported MAS lifecycle state: {lifecycle_state}")
    metadata = make_artifact_metadata(
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
    )
    return AgentStatusSnapshot(
        agent_id=metadata["agent_id"],
        lifecycle_state=lifecycle_state,
        agent_artifact_directory=metadata["agent_artifact_directory"],
        trajectory_artifact_path=metadata["trajectory_artifact_path"],
        parent_agent_id=metadata.get("parent_agent_id", ""),
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


def _status_from_events(events: dict[str, Any]) -> dict[str, Any] | None:
    status = events.get(STATUS_EVENT_KEY)
    return normalize_agent_snapshot(status) if isinstance(status, dict) else None


def normalize_agent_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a snapshot with canonical Agent Metadata keys."""
    agent_id = validate_agent_id(str(snapshot.get("agent_id") or ""))
    metadata = make_artifact_metadata(
        agent_id=agent_id,
        parent_agent_id=snapshot.get("parent_agent_id"),
    )
    normalized = {
        **metadata,
        "agent_id": agent_id,
        "lifecycle_state": snapshot["lifecycle_state"],
    }
    if snapshot.get("latest_submission"):
        normalized["latest_submission"] = snapshot["latest_submission"]
    if snapshot.get("latest_error"):
        normalized["latest_error"] = snapshot["latest_error"]
    return normalized


async def list_direct_child_agent_ids_async(dbos_api: Any, parent_workflow_id: str) -> list[str]:
    """Return workflow IDs whose DBOS metadata names this workflow as their direct parent."""
    parent_workflow_id = validate_agent_id(parent_workflow_id)
    workflow_statuses = await _maybe_await(
        dbos_api.list_workflows_async(
            parent_workflow_id=parent_workflow_id,
            load_input=False,
            load_output=False,
        )
    )
    workflow_ids = []
    for workflow_status in workflow_statuses:
        workflow_id = getattr(workflow_status, "workflow_id", "")
        if getattr(workflow_status, "parent_workflow_id", None) == parent_workflow_id:
            workflow_ids.append(validate_agent_id(workflow_id))
    return sorted(workflow_ids)


async def query_direct_child_statuses_async(dbos_api: Any, parent_workflow_id: str) -> list[dict[str, Any]]:
    """Query status snapshots for direct children using DBOS parent workflow metadata."""
    snapshots = []
    for workflow_id in await list_direct_child_agent_ids_async(dbos_api, parent_workflow_id):
        snapshot = _status_from_events(await _maybe_await(dbos_api.get_all_events_async(workflow_id)))
        if snapshot is not None:
            snapshots.append(snapshot)
    return sorted(snapshots, key=lambda snapshot: snapshot["agent_id"])


async def query_direct_child_status_async(
    dbos_api: Any, *, parent_workflow_id: str, child_workflow_id: str
) -> dict[str, Any] | None:
    """Query one status snapshot after DBOS metadata proves it is a direct child."""
    parent_workflow_id = validate_agent_id(parent_workflow_id)
    child_workflow_id = validate_agent_id(child_workflow_id)
    workflow_statuses = await _maybe_await(
        dbos_api.list_workflows_async(
            workflow_ids=[child_workflow_id],
            parent_workflow_id=parent_workflow_id,
            load_input=False,
            load_output=False,
        )
    )
    if not any(getattr(status, "parent_workflow_id", None) == parent_workflow_id for status in workflow_statuses):
        return None
    return _status_from_events(await _maybe_await(dbos_api.get_all_events_async(child_workflow_id)))


def _format_snapshot(snapshot: dict[str, Any]) -> list[str]:
    snapshot = normalize_agent_snapshot(snapshot)
    lines = [
        f"agent_id: {snapshot['agent_id']}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
    ]
    if snapshot.get("parent_agent_id"):
        lines.append(f"parent_agent_id: {snapshot['parent_agent_id']}")
    if snapshot.get("latest_submission"):
        lines.append(f"latest_submission: {snapshot['latest_submission']}")
    if snapshot.get("latest_error"):
        lines.append(f"latest_error: {snapshot['latest_error']}")
    lines.extend(
        [
            f"agent_artifact_directory: {snapshot['agent_artifact_directory']}",
            f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
        ]
    )
    return lines


def format_direct_child_statuses(snapshots: list[dict[str, Any]], *, parent_workflow_id: str) -> str:
    """Format direct-child status snapshots as a bash observation."""
    lines = [f"Direct Child Agents for: {parent_workflow_id}"]
    if not snapshots:
        lines.append("No direct Child Agent status snapshots found.")
        return "\n".join(lines) + "\n"
    for index, snapshot in enumerate(snapshots):
        if index:
            lines.append("")
        lines.extend(_format_snapshot(snapshot))
    return "\n".join(lines) + "\n"


def format_specific_status(snapshot: dict[str, Any]) -> str:
    return "\n".join(_format_snapshot(snapshot)) + "\n"
