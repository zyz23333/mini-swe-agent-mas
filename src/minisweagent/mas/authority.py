"""Direct Child Authority Policy for workflow-layer MAS Governance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from minisweagent.mas import agent_interactions
from minisweagent.mas.artifacts import validate_workflow_id

from .status_events import root_id_for_workflow


@dataclass(frozen=True)
class AuthorityCommandError:
    """Structured model-visible error returned by the authority policy."""

    output: str
    returncode: int
    exception_info: str
    extra: dict[str, Any]

    def to_command_result(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "returncode": self.returncode,
            "exception_info": self.exception_info,
            "extra": dict(self.extra),
        }


AuthorityResult = dict[str, Any] | AuthorityCommandError


class AuthorityPolicy(Protocol):
    """Narrow authority strategy contract used by MAS command dispatch."""

    async def list_observable_children(self, *, parent_workflow_id: str) -> list[dict[str, Any]]:
        """List child snapshots visible to the current parent workflow."""
        ...

    async def require_observable_child(
        self,
        *,
        parent_workflow_id: str,
        target_workflow_id: str,
        command_name: str,
    ) -> AuthorityResult:
        """Authorize observing or waiting for a targeted child workflow."""
        ...

    async def require_waiting_child(
        self,
        *,
        parent_workflow_id: str,
        target_workflow_id: str,
        command_name: str,
    ) -> AuthorityResult:
        """Authorize sending parent-direction control to a waiting child workflow."""
        ...


class DirectChildAuthorityPolicy:
    """Fixed MVP authority policy for direct Child Agent Interactions."""

    async def list_observable_children(self, *, parent_workflow_id: str) -> list[dict[str, Any]]:
        parent_workflow_id = validate_workflow_id(parent_workflow_id)
        return await agent_interactions.query_direct_child_statuses(parent_workflow_id)

    async def require_observable_child(
        self,
        *,
        parent_workflow_id: str,
        target_workflow_id: str,
        command_name: str,
    ) -> AuthorityResult:
        parent_workflow_id = validate_workflow_id(parent_workflow_id)
        target_workflow_id = validate_workflow_id(target_workflow_id)

        if target_workflow_id == parent_workflow_id:
            return _cannot_target_current_workflow(command_name)
        if target_workflow_id == root_id_for_workflow(parent_workflow_id):
            return _cannot_target_root_workflow(command_name)

        snapshot = await agent_interactions.query_direct_child_status(
            parent_workflow_id=parent_workflow_id,
            child_workflow_id=target_workflow_id,
        )
        if snapshot is None:
            return _workflow_not_direct_child(parent_workflow_id, target_workflow_id)
        return snapshot

    async def require_waiting_child(
        self,
        *,
        parent_workflow_id: str,
        target_workflow_id: str,
        command_name: str,
    ) -> AuthorityResult:
        direct_child = await self.require_observable_child(
            parent_workflow_id=parent_workflow_id,
            target_workflow_id=target_workflow_id,
            command_name=command_name,
        )
        if isinstance(direct_child, AuthorityCommandError):
            return direct_child
        if direct_child.get("lifecycle_state") != "waiting_for_parent":
            return AuthorityCommandError(
                output=f"Workflow is not waiting for parent direction: {target_workflow_id}\n",
                returncode=1,
                exception_info="workflow_not_waiting_for_parent",
                extra={"mas_command_error": "workflow_not_waiting_for_parent"},
            )
        return direct_child


def _cannot_target_current_workflow(command_name: str) -> AuthorityCommandError:
    return AuthorityCommandError(
        output=f"Cannot {command_name} the current Agent Workflow.\n",
        returncode=1,
        exception_info=f"cannot_{command_name}_current_workflow",
        extra={"mas_command_error": f"cannot_{command_name}_current_workflow"},
    )


def _cannot_target_root_workflow(command_name: str) -> AuthorityCommandError:
    return AuthorityCommandError(
        output=f"Cannot {command_name} the Root Agent Workflow.\n",
        returncode=1,
        exception_info=f"cannot_{command_name}_root_workflow",
        extra={"mas_command_error": f"cannot_{command_name}_root_workflow"},
    )


def _workflow_not_direct_child(parent_workflow_id: str, target_workflow_id: str) -> AuthorityCommandError:
    return AuthorityCommandError(
        output=f"Workflow is not a direct Child Agent Workflow of {parent_workflow_id}: {target_workflow_id}\n",
        returncode=1,
        exception_info="workflow_not_direct_child",
        extra={"mas_command_error": "workflow_not_direct_child"},
    )
