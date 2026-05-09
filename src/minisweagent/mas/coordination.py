"""MAS-specific DBOS workflow-control coordination adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from inspect import isawaitable
from typing import Any

from minisweagent.mas.status import (
    FIRST_OBSERVABLE_EVENT_KEY,
    STATUS_EVENT_KEY,
    LifecycleState,
    make_status_snapshot,
    query_direct_child_status_async,
    query_direct_child_statuses_async,
    root_id_for_workflow,
)


async def _maybe_await(value: Any) -> Any:
    return await value if isawaitable(value) else value


def _snapshot_workflow_id(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("workflow_id", ""))


def _child_metadata_from_status(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        "task": "",
        "root_workflow_id": str(snapshot["root_workflow_id"]),
        "workflow_id": str(snapshot["workflow_id"]),
        "run_directory": str(snapshot["run_directory"]),
        "trajectory_artifact_path": str(snapshot["trajectory_artifact_path"]),
    }


class DBOSCoordinationAdapter:
    """Thin MAS-specific wrapper around DBOS workflow-control primitives."""

    def __init__(
        self,
        *,
        dbos_api: Any,
        child_agent_queue: Any,
        set_workflow_id: Callable[[str], Any],
        child_agent_workflow: Callable[..., Any],
    ) -> None:
        self.dbos_api = dbos_api
        self.child_agent_queue = child_agent_queue
        self.set_workflow_id = set_workflow_id
        self.child_agent_workflow = child_agent_workflow

    def current_agent_workflow_id(self) -> str | None:
        """Return the current DBOS workflow ID only when DBOS exposes a real workflow context."""
        workflow_id = self.dbos_api.workflow_id
        return workflow_id if isinstance(workflow_id, str) else None

    async def enqueue_child_agent_workflow(self, *, root_workflow_id: str, child_workflow_id: str, task: str) -> None:
        """Start a Child Agent Workflow through the configured DBOS child queue."""
        with self.set_workflow_id(child_workflow_id):
            await self.child_agent_queue.enqueue_async(
                self.child_agent_workflow,
                root_workflow_id,
                child_workflow_id,
                task,
            )

    async def publish_status(
        self,
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
            await _maybe_await(self.dbos_api.set_event_async(STATUS_EVENT_KEY, snapshot.to_event()))
        except Exception:
            if self.dbos_api.workflow_id is not None:
                raise

    async def publish_first_observable(
        self,
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
            await _maybe_await(self.dbos_api.set_event_async(FIRST_OBSERVABLE_EVENT_KEY, event))
        except Exception:
            if self.dbos_api.workflow_id is not None:
                raise
        return event

    async def query_direct_child_statuses(self, parent_workflow_id: str) -> list[dict[str, Any]]:
        """Query direct child statuses through DBOS workflow metadata."""
        return await query_direct_child_statuses_async(self.dbos_api, parent_workflow_id)

    async def query_direct_child_status(
        self,
        *,
        parent_workflow_id: str,
        child_workflow_id: str,
    ) -> dict[str, Any] | None:
        """Query one direct child status through DBOS workflow metadata."""
        return await query_direct_child_status_async(
            self.dbos_api,
            parent_workflow_id=parent_workflow_id,
            child_workflow_id=child_workflow_id,
        )

    async def direct_child_metadata(self, *, parent_workflow_id: str) -> list[dict[str, str]]:
        """Return direct child artifact metadata from latest status snapshots."""
        snapshots = await self.query_direct_child_statuses(parent_workflow_id)
        return sorted((_child_metadata_from_status(snapshot) for snapshot in snapshots), key=lambda child: child["workflow_id"])

    async def wait_for_first_observable_event(
        self,
        workflow_id: str,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        """Wait for one Child Agent Workflow First Observable Event."""
        event = await _maybe_await(
            self.dbos_api.get_event_async(workflow_id, FIRST_OBSERVABLE_EVENT_KEY, timeout_seconds)
        )
        return event if isinstance(event, dict) else None

    async def wait_for_first_observable_events(
        self,
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
            asyncio.create_task(self.wait_for_first_observable_event(workflow_id, per_child_timeout))
            for workflow_id in child_workflow_ids
        ]
        done, pending = await _maybe_await(
            self.dbos_api.asyncio_wait(
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
        self,
        *,
        parent_workflow_id: str,
        child_workflow_ids: list[str],
        wait_all: bool,
        timeout_seconds: float | None,
    ) -> tuple[list[dict[str, Any]], list[str], bool]:
        """Publish transient wait status around direct child First Observable Event waiting."""
        root_workflow_id = root_id_for_workflow(parent_workflow_id)
        await self.publish_status(
            root_workflow_id=root_workflow_id,
            workflow_id=parent_workflow_id,
            lifecycle_state="waiting_for_child",
        )
        try:
            return await self.wait_for_first_observable_events(
                child_workflow_ids=child_workflow_ids,
                wait_all=wait_all,
                timeout_seconds=timeout_seconds,
            )
        finally:
            await self.publish_status(
                root_workflow_id=root_workflow_id,
                workflow_id=parent_workflow_id,
                lifecycle_state="running",
            )

    async def send_parent_direction(self, *, target_workflow_id: str, signal: dict[str, Any], topic: str) -> None:
        """Send a parent-direction signal to a direct child workflow."""
        await _maybe_await(self.dbos_api.send_async(target_workflow_id, signal, topic))

    async def receive_parent_direction(self, *, topic: str, timeout_seconds: float) -> dict | str | None:
        """Receive one parent-direction workflow message."""
        return await _maybe_await(self.dbos_api.recv_async(topic, timeout_seconds=timeout_seconds))
