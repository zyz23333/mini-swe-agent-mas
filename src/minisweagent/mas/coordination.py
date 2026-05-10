"""MAS-specific DBOS workflow-control coordination adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from minisweagent.mas.artifacts import make_artifact_metadata, validate_workflow_id
from minisweagent.mas.runtime import load_dbos

from .status_events import (
    FIRST_OBSERVABLE_EVENT_KEY,
    STATUS_EVENT_KEY,
    LifecycleState,
    make_status_snapshot,
    query_direct_child_status_async,
    query_direct_child_statuses_async,
    root_id_for_workflow,
)

_dbos = load_dbos()


async def _maybe_await(value: Any) -> Any:
    return await value if isawaitable(value) else value


def _snapshot_workflow_id(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("workflow_id", ""))


def _is_missing_dbos_runtime_error(exc: Exception) -> bool:
    return "No DBOS was created yet" in str(exc)


def _has_active_dbos_runtime(dbos_api: Any) -> bool:
    """Best-effort check used only to keep direct unit-test workflow calls lightweight."""
    module = getattr(dbos_api, "__module__", "")
    dbos_module = __import__(module, fromlist=["_dbos_global_instance"]) if module else None
    return getattr(dbos_module, "_dbos_global_instance", None) is not None


@dataclass(frozen=True)
class SpawnChildrenResult:
    """Structured Child Coordination result for detached child startup."""

    children: list[dict[str, str]]

    @property
    def child_workflow_ids(self) -> list[str]:
        return [child["workflow_id"] for child in self.children]


@dataclass(frozen=True)
class ChildWaitResult:
    """Structured Child Coordination result for First Observable Event waits."""

    children: list[dict[str, str]]
    ready_snapshots: list[dict[str, Any]]
    still_running_ids: list[str]
    timed_out: bool
    wait_mode: str


def current_workflow_id() -> str | None:
    """Return the current DBOS workflow ID only when DBOS exposes a real workflow context."""
    workflow_id = _dbos.DBOS.workflow_id
    return workflow_id if isinstance(workflow_id, str) else None


async def enqueue_child_agent_workflow(*, root_workflow_id: str, child_workflow_id: str, task: str) -> None:
    """Start a Child Agent Workflow through the configured DBOS child queue."""
    from minisweagent.mas import mas_agent

    with _dbos.SetWorkflowID(child_workflow_id):
        await mas_agent.child_agent_queue.enqueue_async(
            mas_agent.child_agent_workflow,
            root_workflow_id,
            child_workflow_id,
            task,
        )


async def publish_status(
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> None:
    """Publish the latest lightweight Child Status Event."""
    snapshot = make_status_snapshot(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )
    try:
        await _maybe_await(_dbos.DBOS.set_event_async(STATUS_EVENT_KEY, snapshot.to_event()))
    except Exception as exc:
        if _has_active_dbos_runtime(_dbos.DBOS):
            raise
        if not _is_missing_dbos_runtime_error(exc):
            raise


async def publish_first_observable(
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> dict[str, str]:
    """Publish the one-time event that parent waits synchronize on."""
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
    except Exception as exc:
        if _has_active_dbos_runtime(_dbos.DBOS):
            raise
        if not _is_missing_dbos_runtime_error(exc):
            raise
    return event


async def query_direct_child_statuses(parent_workflow_id: str) -> list[dict[str, Any]]:
    """Query direct child statuses through DBOS workflow metadata."""
    try:
        return await query_direct_child_statuses_async(_dbos.DBOS, parent_workflow_id)
    except Exception as exc:
        if _has_active_dbos_runtime(_dbos.DBOS) or not _is_missing_dbos_runtime_error(exc):
            raise
        return []


async def query_direct_child_status(
    *,
    parent_workflow_id: str,
    child_workflow_id: str,
) -> dict[str, Any] | None:
    """Query one direct child status through DBOS workflow metadata."""
    try:
        return await query_direct_child_status_async(
            _dbos.DBOS,
            parent_workflow_id=parent_workflow_id,
            child_workflow_id=child_workflow_id,
        )
    except Exception as exc:
        if _has_active_dbos_runtime(_dbos.DBOS) or not _is_missing_dbos_runtime_error(exc):
            raise
        return None


async def wait_for_first_observable_event(
    workflow_id: str,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    """Wait for one Child Agent Workflow First Observable Event."""
    event = await _maybe_await(_dbos.DBOS.get_event_async(workflow_id, FIRST_OBSERVABLE_EVENT_KEY, timeout_seconds))
    return event if isinstance(event, dict) else None


async def wait_for_first_observable_events(
    *,
    child_workflow_ids: list[str],
    wait_all: bool,
    timeout_seconds: float | None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Wait for First Observable Events with wait-any, wait-all, and timeout behavior."""
    if not child_workflow_ids:
        return [], [], False

    per_child_timeout = timeout_seconds if timeout_seconds is not None else 60
    waits = [
        asyncio.create_task(wait_for_first_observable_event(workflow_id, per_child_timeout))
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


async def wait_for_direct_child_first_observable_events(
    *,
    parent_workflow_id: str,
    child_workflow_ids: list[str],
    wait_all: bool,
    timeout_seconds: float | None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Publish transient wait status around direct child First Observable Event waiting."""
    root_workflow_id = root_id_for_workflow(parent_workflow_id)
    await publish_status(
        root_workflow_id=root_workflow_id,
        workflow_id=parent_workflow_id,
        lifecycle_state="waiting_for_child",
    )
    try:
        return await wait_for_first_observable_events(
            child_workflow_ids=child_workflow_ids,
            wait_all=wait_all,
            timeout_seconds=timeout_seconds,
        )
    finally:
        await publish_status(
            root_workflow_id=root_workflow_id,
            workflow_id=parent_workflow_id,
            lifecycle_state="running",
        )


async def send_parent_direction(*, target_workflow_id: str, signal: dict[str, Any], topic: str) -> None:
    """Send a parent-direction signal to a direct child workflow."""
    await _maybe_await(_dbos.DBOS.send_async(target_workflow_id, signal, topic))


async def receive_parent_direction(*, topic: str, timeout_seconds: float) -> dict | str | None:
    """Receive one parent-direction workflow message."""
    return await _maybe_await(_dbos.DBOS.recv_async(topic, timeout_seconds=timeout_seconds))


async def spawn_children(
    *,
    root_workflow_id: str,
    parent_workflow_id: str,
    first_spawn_index: int,
    tasks: list[str],
) -> SpawnChildrenResult:
    """Allocate deterministic child IDs and enqueue Child Agent Workflows."""
    children = []
    for offset, task in enumerate(tasks):
        child_workflow_id = next_child_workflow_id(parent_workflow_id, first_spawn_index + offset)
        metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=child_workflow_id)
        await enqueue_child_agent_workflow(
            root_workflow_id=root_workflow_id,
            child_workflow_id=child_workflow_id,
            task=task,
        )
        children.append({"task": task, **metadata})
    return SpawnChildrenResult(children=children)


async def wait_for_spawned_children(
    *,
    parent_workflow_id: str,
    children: list[dict[str, str]],
    wait_all: bool,
    timeout_seconds: float | None,
) -> ChildWaitResult:
    """Wait over freshly spawned children without mutating running children on timeout."""
    return await wait_for_children(
        parent_workflow_id=parent_workflow_id,
        children=children,
        wait_all=wait_all,
        timeout_seconds=timeout_seconds,
        wait_mode="all" if wait_all else "any",
    )


async def wait_for_children(
    *,
    parent_workflow_id: str,
    children: list[dict[str, str]],
    wait_all: bool,
    timeout_seconds: float | None,
    wait_mode: str,
) -> ChildWaitResult:
    """Synchronize direct children on First Observable Events."""
    ready_snapshots, still_running_ids, timed_out = await wait_for_direct_child_first_observable_events(
        parent_workflow_id=parent_workflow_id,
        child_workflow_ids=[child["workflow_id"] for child in children],
        wait_all=wait_all,
        timeout_seconds=timeout_seconds,
    )
    return ChildWaitResult(
        children=children,
        ready_snapshots=ready_snapshots,
        still_running_ids=still_running_ids,
        timed_out=timed_out,
        wait_mode=wait_mode,
    )


def next_child_workflow_id(parent_workflow_id: str, spawn_index: int) -> str:
    """Return the deterministic Workflow Tree ID for a child sibling index."""
    validate_workflow_id(parent_workflow_id)
    if spawn_index < 1:
        raise ValueError("Child spawn index must start at 1")
    return f"{parent_workflow_id}-c{spawn_index:03d}"
