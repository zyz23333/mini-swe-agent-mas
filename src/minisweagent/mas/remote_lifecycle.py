"""Remote Interactive Agent continuation and neutral-close lifecycle."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from minisweagent.mas.status import LifecycleState

PARENT_DIRECTION_TOPIC = "mini_mas_parent_direction"
PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS = 60 * 60 * 24 * 30

ParentDirectionReceiver = Callable[[], Awaitable[dict | str]]
StatusPublisher = Callable[[LifecycleState], Awaitable[None]]
FirstObservablePublisher = Callable[[LifecycleState], Awaitable[dict[str, str] | None]]
TrajectorySaver = Callable[[str], Awaitable[dict[str, str]]]


def make_continuation_signal(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
    content: str,
) -> dict[str, str]:
    """Build the parent-to-child message payload used for MAS continuation."""
    return {
        "type": "continuation",
        "signal_type": "mas_continuation",
        "content": content,
        "source_workflow_id": source_workflow_id,
        "target_workflow_id": target_workflow_id,
    }


def make_close_signal(*, source_workflow_id: str, target_workflow_id: str) -> dict[str, str]:
    """Build the neutral parent-to-child message payload used to close a waiting child."""
    return {
        "type": "close",
        "signal_type": "mas_close",
        "source_workflow_id": source_workflow_id,
        "target_workflow_id": target_workflow_id,
    }


def is_continuation_signal(signal: dict | str) -> bool:
    return isinstance(signal, dict) and (
        signal.get("type") == "continuation" or signal.get("signal_type") == "mas_continuation"
    )


def is_close_signal(signal: dict | str) -> bool:
    return isinstance(signal, dict) and (signal.get("type") == "close" or signal.get("signal_type") == "mas_close")


def continuation_user_message(model, signal: dict) -> dict:
    """Represent parent continuation as a normal model-facing user message."""
    return model.format_message(
        role="user",
        content=str(signal.get("content", "")),
        extra={
            "mas": {
                "signal_type": "mas_continuation",
                "source_workflow_id": str(signal.get("source_workflow_id", "")),
                "target_workflow_id": str(signal.get("target_workflow_id", "")),
            }
        },
    )


class RemoteInteractiveAgentLifecycle:
    """Workflow-layer lifecycle boundary for child submission continuation and close."""

    def __init__(
        self,
        *,
        root_workflow_id: str,
        workflow_id: str,
        receive_parent_direction: ParentDirectionReceiver | None = None,
    ) -> None:
        self.root_workflow_id = root_workflow_id
        self.workflow_id = workflow_id
        self._receive_parent_direction = receive_parent_direction

    def make_continuation_signal(self, *, source_workflow_id: str, content: str) -> dict[str, str]:
        return make_continuation_signal(
            source_workflow_id=source_workflow_id,
            target_workflow_id=self.workflow_id,
            content=content,
        )

    def make_close_signal(self, *, source_workflow_id: str) -> dict[str, str]:
        return make_close_signal(source_workflow_id=source_workflow_id, target_workflow_id=self.workflow_id)

    def is_continuation_signal(self, signal: dict | str) -> bool:
        return is_continuation_signal(signal)

    def is_close_signal(self, signal: dict | str) -> bool:
        return is_close_signal(signal)

    def continuation_user_message(self, model, signal: dict) -> dict:
        return continuation_user_message(model, signal)

    def should_wait_for_parent(self, result: dict[str, Any]) -> bool:
        return self.workflow_id != self.root_workflow_id and result["terminal_state"] == "Submitted"

    async def receive_parent_direction(self) -> dict | str:
        if self._receive_parent_direction is None:
            raise RuntimeError("RemoteInteractiveAgentLifecycle requires a parent-direction receiver")
        return await self._receive_parent_direction()

    async def wait_after_submission(
        self,
        result: dict[str, Any],
        *,
        publish_waiting_status: StatusPublisher,
        publish_first_observable: FirstObservablePublisher,
        save_trajectory: TrajectorySaver,
    ) -> dict[str, Any]:
        """Publish the child waiting state, save history, and wait for parent direction."""
        waiting_result = self.waiting_result_for_submission(result)
        await publish_waiting_status("waiting_for_parent")
        await publish_first_observable("waiting_for_parent")
        await save_trajectory("waiting_for_parent")
        waiting_result["parent_direction_signal"] = await self.receive_parent_direction()
        return waiting_result

    async def close_after_parent_signal(
        self,
        waiting_result: dict[str, Any],
        *,
        publish_closed_status: StatusPublisher,
        save_trajectory: TrajectorySaver,
    ) -> dict[str, Any]:
        """Close a waiting child neutrally without acceptance or rejection semantics."""
        closed_result = {
            **waiting_result,
            "status": "closed",
            "terminal_state": "closed",
        }
        await publish_closed_status("closed")
        await save_trajectory("closed")
        return closed_result

    def waiting_result_for_submission(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            **result,
            "status": "waiting_for_parent",
            "terminal_state": "waiting_for_parent",
            "latest_submission": result["submission"],
        }
