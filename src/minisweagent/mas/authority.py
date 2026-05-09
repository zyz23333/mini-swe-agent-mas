"""Direct Child Authority Policy for workflow-layer MAS coordination."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from minisweagent.mas.artifacts import validate_workflow_id

from .status_events import root_id_for_workflow

DirectChildStatusLookup = Callable[[str, str], Awaitable[dict[str, Any] | None]]


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


@dataclass(frozen=True)
class AuthorizedChild:
    """Direct child snapshot authorized for a parent workflow command."""

    snapshot: dict[str, Any]

    @property
    def workflow_id(self) -> str:
        return str(self.snapshot["workflow_id"])

    def metadata(self) -> dict[str, str]:
        return {
            "task": "",
            "root_workflow_id": str(self.snapshot["root_workflow_id"]),
            "workflow_id": str(self.snapshot["workflow_id"]),
            "run_directory": str(self.snapshot["run_directory"]),
            "trajectory_artifact_path": str(self.snapshot["trajectory_artifact_path"]),
        }


AuthorityResult = AuthorizedChild | AuthorityCommandError


class DirectChildAuthorityPolicy:
    """Fixed MVP authority policy for explicit direct Child Agent Workflow targets."""

    def __init__(self, *, query_direct_child_status: DirectChildStatusLookup) -> None:
        self.query_direct_child_status = query_direct_child_status

    async def require_direct_child(self, parent_workflow_id: str, target_workflow_id: str) -> AuthorityResult:
        parent_workflow_id = validate_workflow_id(parent_workflow_id)
        target_workflow_id = validate_workflow_id(target_workflow_id)

        if target_workflow_id == parent_workflow_id:
            return _cannot_target_current_workflow("coordinate")
        if target_workflow_id == root_id_for_workflow(parent_workflow_id):
            return _cannot_target_root_workflow("coordinate")

        snapshot = await self.query_direct_child_status(parent_workflow_id, target_workflow_id)
        if snapshot is None:
            return _workflow_not_direct_child(parent_workflow_id, target_workflow_id)
        return AuthorizedChild(snapshot=snapshot)

    async def require_waiting_direct_child(
        self,
        parent_workflow_id: str,
        target_workflow_id: str,
        command_name: str,
    ) -> AuthorityResult:
        direct_child = await self.require_direct_child(parent_workflow_id, target_workflow_id)
        if isinstance(direct_child, AuthorityCommandError):
            return _retarget_current_or_root_error(direct_child, command_name)
        if direct_child.snapshot.get("lifecycle_state") != "waiting_for_parent":
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


def _retarget_current_or_root_error(error: AuthorityCommandError, command_name: str) -> AuthorityCommandError:
    if error.exception_info == "cannot_coordinate_current_workflow":
        return _cannot_target_current_workflow(command_name)
    if error.exception_info == "cannot_coordinate_root_workflow":
        return _cannot_target_root_workflow(command_name)
    return error
