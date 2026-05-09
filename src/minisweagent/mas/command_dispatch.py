"""Workflow-layer MAS command dispatch for classified standalone commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from minisweagent.mas.artifacts import validate_workflow_id
from minisweagent.mas.authority import AuthorityCommandError, AuthorizedChild
from minisweagent.mas.command_results import MasCommandResultFormatter
from minisweagent.mas.commands import MasCommandClassification, MasCommandKind
from minisweagent.mas.coordination import ChildCoordinator
from minisweagent.mas.status import root_id_for_workflow


@dataclass(frozen=True)
class SpawnCommandRequest:
    """Parsed workflow-layer spawn command options."""

    tasks: list[str]
    wait: bool = False
    wait_all: bool = False
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class WaitCommandRequest:
    """Parsed workflow-layer wait command options."""

    workflow_id: str | None = None
    wait_all: bool = False
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class ContinueCommandRequest:
    """Parsed workflow-layer continuation command options."""

    workflow_id: str
    content: str


@dataclass(frozen=True)
class CloseCommandRequest:
    """Parsed workflow-layer close command options."""

    workflow_id: str


StatusList = Callable[[str], Awaitable[list[dict[str, Any]]]]
ContinuationSender = Callable[[str, str, str, dict[str, Any]], Awaitable[dict[str, Any]]]
CloseSender = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]


def _parse_timeout_seconds(raw_timeout: str) -> float:
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as exc:
        raise ValueError("Spawn timeout must be a number of seconds") from exc
    if timeout_seconds < 0:
        raise ValueError("Spawn timeout must be non-negative")
    return timeout_seconds


def _parse_spawn_arguments(arguments: list[str]) -> SpawnCommandRequest:
    wait = False
    wait_all = False
    timeout_seconds: float | None = None
    tasks = []
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--wait":
            wait = True
            index += 1
            continue
        if argument == "--all":
            wait_all = True
            index += 1
            continue
        if argument == "--timeout":
            if index + 1 >= len(arguments):
                raise ValueError("Spawn timeout requires a number of seconds")
            timeout_seconds = _parse_timeout_seconds(arguments[index + 1])
            index += 2
            continue
        if argument.startswith("--"):
            raise ValueError(f"Unsupported spawn option: {argument}")
        tasks.append(argument)
        index += 1

    if timeout_seconds is not None and not wait:
        raise ValueError("mini-mas spawn --timeout requires --wait because Detached Spawn has no wait phase")
    if wait_all and not wait:
        raise ValueError("mini-mas spawn --all requires --wait")
    if not tasks:
        raise ValueError('Usage: mini-mas spawn [--wait] [--all] [--timeout seconds] "task" [...]')
    return SpawnCommandRequest(tasks=tasks, wait=wait, wait_all=wait_all, timeout_seconds=timeout_seconds)


def _parse_wait_arguments(arguments: list[str]) -> WaitCommandRequest:
    wait_any = False
    wait_all = False
    timeout_seconds: float | None = None
    workflow_id: str | None = None
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--any":
            wait_any = True
            index += 1
            continue
        if argument == "--all":
            wait_all = True
            index += 1
            continue
        if argument == "--timeout":
            if index + 1 >= len(arguments):
                raise ValueError("Wait timeout requires a number of seconds")
            timeout_seconds = _parse_timeout_seconds(arguments[index + 1])
            index += 2
            continue
        if argument.startswith("--"):
            raise ValueError(f"Unsupported wait option: {argument}")
        if workflow_id is not None:
            raise ValueError("mini-mas wait accepts at most one workflow ID")
        workflow_id = validate_workflow_id(argument)
        index += 1

    if workflow_id is not None and (wait_any or wait_all):
        raise ValueError("mini-mas wait for one workflow cannot also use --any or --all")
    if wait_any and wait_all:
        raise ValueError("mini-mas wait cannot use both --any and --all")
    return WaitCommandRequest(workflow_id=workflow_id, wait_all=wait_all, timeout_seconds=timeout_seconds)


def _parse_continue_arguments(arguments: list[str]) -> ContinueCommandRequest:
    if len(arguments) != 3:
        raise ValueError('Usage: mini-mas continue <workflow-id> "message"')
    workflow_id = validate_workflow_id(arguments[1])
    content = arguments[2]
    if not content:
        raise ValueError('Usage: mini-mas continue <workflow-id> "message"')
    return ContinueCommandRequest(workflow_id=workflow_id, content=content)


def _parse_close_arguments(arguments: list[str]) -> CloseCommandRequest:
    if len(arguments) != 2:
        raise ValueError("Usage: mini-mas close <workflow-id>")
    return CloseCommandRequest(workflow_id=validate_workflow_id(arguments[1]))


def _authority_result_error(result: Any) -> dict[str, Any] | None:
    if isinstance(result, AuthorityCommandError):
        return result.to_command_result()
    return None


def _authority_result_snapshot(result: Any) -> dict[str, Any]:
    if isinstance(result, AuthorizedChild):
        return result.snapshot
    if isinstance(result, dict):
        return result
    raise TypeError(f"Unsupported Direct Child Authority Policy result: {type(result)!r}")


def _child_metadata_from_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        "task": "",
        "root_workflow_id": str(snapshot["root_workflow_id"]),
        "workflow_id": str(snapshot["workflow_id"]),
        "run_directory": str(snapshot["run_directory"]),
        "trajectory_artifact_path": str(snapshot["trajectory_artifact_path"]),
    }


class MasCommandHandler:
    """Dispatch classified Standalone MAS Commands without owning shell classification."""

    def __init__(
        self,
        *,
        current_workflow_id: Callable[[], str | None],
        query_direct_child_statuses: StatusList | None = None,
        authority_policy: Any | None = None,
        child_coordinator: ChildCoordinator | None = None,
        send_continuation_signal: ContinuationSender | None = None,
        send_close_signal: CloseSender | None = None,
        result_formatter: MasCommandResultFormatter | None = None,
    ) -> None:
        self.current_workflow_id = current_workflow_id
        self.query_direct_child_statuses = query_direct_child_statuses
        self.authority_policy = authority_policy
        self.child_coordinator = child_coordinator
        self.send_continuation_signal = send_continuation_signal
        self.send_close_signal = send_close_signal
        self.result_formatter = result_formatter or MasCommandResultFormatter()

    async def execute(
        self,
        classification: MasCommandClassification,
        *,
        spawn_index: int,
        existing_child_workflow_ids: set[str],
    ) -> dict[str, Any]:
        if classification.kind != MasCommandKind.STANDALONE:
            raise ValueError("MasCommandHandler only accepts classified standalone MAS commands")

        command_name = classification.arguments[0] if classification.arguments else ""
        if command_name == "status":
            return await self._status(classification)
        if command_name == "spawn":
            return await self._spawn(
                classification,
                spawn_index=spawn_index,
                existing_child_workflow_ids=existing_child_workflow_ids,
            )
        if command_name == "wait":
            return await self._wait(classification)
        if command_name == "continue":
            return await self._continue(classification)
        if command_name == "close":
            return await self._close(classification)

        return self.result_formatter.accepted(mas_command=classification.arguments)

    async def _status(self, classification: MasCommandClassification) -> dict[str, Any]:
        current_workflow_id = self._validated_context("status")
        if current_workflow_id is None:
            return self.result_formatter.missing_agent_workflow_context("status")
        if len(classification.arguments) == 1:
            snapshots = await self.query_direct_child_statuses(current_workflow_id)
            return self.result_formatter.direct_child_statuses(
                mas_command=classification.arguments,
                snapshots=snapshots,
                parent_workflow_id=current_workflow_id,
            )
        if len(classification.arguments) == 2:
            target_workflow_id = classification.arguments[1]
            authority_result = await self.authority_policy.require_direct_child(current_workflow_id, target_workflow_id)
            error = _authority_result_error(authority_result)
            if error is not None:
                return self.result_formatter.authority_error(error, mas_command=classification.arguments)
            snapshot = _authority_result_snapshot(authority_result)
            return self.result_formatter.specific_status(mas_command=classification.arguments, snapshot=snapshot)
        return self.result_formatter.invalid_arguments(
            output="Usage: mini-mas status [workflow-id]\n",
            exception_info="invalid_status_arguments",
            mas_command_error="invalid_status_arguments",
        )

    async def _spawn(
        self,
        classification: MasCommandClassification,
        *,
        spawn_index: int,
        existing_child_workflow_ids: set[str],
    ) -> dict[str, Any]:
        current_workflow_id = self._validated_context("spawn")
        if current_workflow_id is None:
            return self.result_formatter.missing_agent_workflow_context("spawn")
        root_workflow_id = root_id_for_workflow(current_workflow_id)
        try:
            request = _parse_spawn_arguments(classification.arguments)
        except ValueError as exc:
            return self.result_formatter.invalid_arguments(
                output=f"{exc}\n",
                exception_info=str(exc),
                mas_command_error="invalid_spawn_arguments",
            )
        spawn_result = await self.child_coordinator.spawn_children(
            root_workflow_id=root_workflow_id,
            parent_workflow_id=current_workflow_id,
            first_spawn_index=spawn_index,
            tasks=request.tasks,
            existing_child_workflow_ids=existing_child_workflow_ids,
        )
        children = spawn_result.children
        if request.wait:
            wait_result = await self.child_coordinator.wait_for_spawned_children(
                parent_workflow_id=current_workflow_id,
                children=children,
                wait_all=request.wait_all,
                timeout_seconds=request.timeout_seconds,
            )
            return self.result_formatter.spawn_waited(
                mas_command=["spawn", *request.tasks],
                children=children,
                wait_result=wait_result,
            )
        return self.result_formatter.detached_spawn(
            mas_command=["spawn", *request.tasks],
            children=children,
        )

    async def _wait(self, classification: MasCommandClassification) -> dict[str, Any]:
        current_workflow_id = self._validated_context("wait")
        if current_workflow_id is None:
            return self.result_formatter.missing_agent_workflow_context("wait")
        try:
            request = _parse_wait_arguments(classification.arguments)
        except ValueError as exc:
            return self.result_formatter.invalid_arguments(
                output=f"{exc}\n",
                exception_info=str(exc),
                mas_command_error="invalid_wait_arguments",
            )
        if request.workflow_id is not None:
            authority_result = await self.authority_policy.require_direct_child(current_workflow_id, request.workflow_id)
            error = _authority_result_error(authority_result)
            if error is not None:
                return self.result_formatter.authority_error(error, mas_command=classification.arguments)
            children = [_child_metadata_from_snapshot(_authority_result_snapshot(authority_result))]
        else:
            children = await self.child_coordinator.direct_child_metadata(parent_workflow_id=current_workflow_id)
        if not children:
            return self.result_formatter.no_child_workflows(mas_command=classification.arguments)
        wait_all = request.wait_all or request.workflow_id is not None
        wait_mode = "one" if request.workflow_id is not None else ("all" if wait_all else "any")
        wait_result = await self.child_coordinator.wait_for_children(
            parent_workflow_id=current_workflow_id,
            children=children,
            wait_all=wait_all,
            timeout_seconds=request.timeout_seconds,
            wait_mode=wait_mode,
        )
        return self.result_formatter.wait_summary(
            mas_command=classification.arguments,
            children=children,
            wait_result=wait_result,
        )

    async def _continue(self, classification: MasCommandClassification) -> dict[str, Any]:
        current_workflow_id = self._validated_context("continue")
        if current_workflow_id is None:
            return self.result_formatter.missing_agent_workflow_context("continue")
        try:
            request = _parse_continue_arguments(classification.arguments)
        except ValueError as exc:
            return self.result_formatter.invalid_arguments(
                output=f"{exc}\n",
                exception_info=str(exc),
                mas_command_error="invalid_continue_arguments",
            )
        authority_result = await self.authority_policy.require_waiting_direct_child(
            current_workflow_id,
            request.workflow_id,
            "continue",
        )
        error = _authority_result_error(authority_result)
        if error is not None:
            return self.result_formatter.authority_error(error, mas_command=classification.arguments)
        snapshot = _authority_result_snapshot(authority_result)
        result = await self.send_continuation_signal(
            current_workflow_id,
            request.workflow_id,
            request.content,
            snapshot,
        )
        result["extra"] = {"mas_command": classification.arguments, **result.get("extra", {})}
        result.pop("ok", None)
        return result

    async def _close(self, classification: MasCommandClassification) -> dict[str, Any]:
        current_workflow_id = self._validated_context("close")
        if current_workflow_id is None:
            return self.result_formatter.missing_agent_workflow_context("close")
        try:
            request = _parse_close_arguments(classification.arguments)
        except ValueError as exc:
            return self.result_formatter.invalid_arguments(
                output=f"{exc}\n",
                exception_info=str(exc),
                mas_command_error="invalid_close_arguments",
            )
        authority_result = await self.authority_policy.require_waiting_direct_child(
            current_workflow_id,
            request.workflow_id,
            "close",
        )
        error = _authority_result_error(authority_result)
        if error is not None:
            return self.result_formatter.authority_error(error, mas_command=classification.arguments)
        snapshot = _authority_result_snapshot(authority_result)
        result = await self.send_close_signal(current_workflow_id, request.workflow_id, snapshot)
        result["extra"] = {"mas_command": classification.arguments, **result.get("extra", {})}
        result.pop("ok", None)
        return result

    def _validated_context(self, command_name: str) -> str | None:
        workflow_id = self.current_workflow_id()
        if workflow_id is None:
            return None
        try:
            return validate_workflow_id(workflow_id)
        except ValueError as exc:
            raise ValueError(f"Invalid Agent Workflow context for mini-mas {command_name}: {workflow_id}") from exc
