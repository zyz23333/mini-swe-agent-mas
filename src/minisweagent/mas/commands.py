"""MAS command classification for bash-shaped model actions."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Any

from minisweagent.mas import agent_interactions
from minisweagent.mas.agent_interactions import ChildWaitResult
from minisweagent.mas.artifacts import validate_agent_id
from minisweagent.mas.authority import AuthorityCommandError, AuthorityPolicy, DirectChildAuthorityPolicy
from minisweagent.mas.signals import PARENT_DIRECTION_TOPIC, make_close_signal, make_continuation_signal

from .status_events import format_direct_child_statuses, format_specific_status, normalize_agent_snapshot

MAS_COMMAND_NAME = "mini-mas"
STANDALONE_CORRECTION = "mini-mas must be issued as a standalone command, not inside shell composition."
SHELL_CONTROL_TOKENS = frozenset(
    {
        "&",
        "&&",
        "(",
        ")",
        ";",
        ";;",
        ";&",
        ";;&",
        "<",
        "<<",
        "<<<",
        ">",
        ">>",
        "|",
        "|&",
        "||",
    }
)
SHELL_KEYWORDS = frozenset({"case", "do", "done", "elif", "else", "esac", "fi", "for", "if", "then", "until", "while"})


class MasCommandKind(str, Enum):
    """Routing decision for a bash-shaped model command."""

    STANDALONE = "standalone"
    ORDINARY_BASH = "ordinary_bash"
    INVALID = "invalid"


@dataclass(frozen=True)
class MasCommandClassification:
    """Parsed MAS command routing result."""

    kind: MasCommandKind
    command: str
    arguments: list[str]
    error: str = ""


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _is_environment_assignment(token: str) -> bool:
    name, separator, _value = token.partition("=")
    return bool(separator) and name.isidentifier()


def _contains_shell_composition(tokens: list[str]) -> bool:
    return any(
        token in SHELL_CONTROL_TOKENS or token in SHELL_KEYWORDS or _is_environment_assignment(token)
        for token in tokens
    )


def classify_mas_command(command: str) -> MasCommandClassification:
    """Classify a bash-shaped action command before Agent execution."""
    stripped_command = command.strip()
    if MAS_COMMAND_NAME not in stripped_command:
        return MasCommandClassification(
            kind=MasCommandKind.ORDINARY_BASH,
            command=stripped_command,
            arguments=[],
        )

    try:
        tokens = _shell_tokens(stripped_command)
    except ValueError as exc:
        return MasCommandClassification(
            kind=MasCommandKind.INVALID,
            command=stripped_command,
            arguments=[],
            error=f"{STANDALONE_CORRECTION} Could not parse command: {exc}",
        )

    if tokens and tokens[0] == MAS_COMMAND_NAME and MAS_COMMAND_NAME not in tokens[1:] and not _contains_shell_composition(tokens):
        return MasCommandClassification(
            kind=MasCommandKind.STANDALONE,
            command=stripped_command,
            arguments=tokens[1:],
        )

    if MAS_COMMAND_NAME in tokens or MAS_COMMAND_NAME in stripped_command:
        return MasCommandClassification(
            kind=MasCommandKind.INVALID,
            command=stripped_command,
            arguments=[],
            error=STANDALONE_CORRECTION,
        )

    return MasCommandClassification(
        kind=MasCommandKind.ORDINARY_BASH,
        command=stripped_command,
        arguments=[],
    )


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


class MasCommandResultFormatter:
    """Own the stable observation dictionary shape for MAS command results."""

    def accepted(self, *, mas_command: list[str]) -> dict[str, Any]:
        command_text = " ".join(mas_command)
        return self.success(
            output=f"MAS command accepted: {command_text}\n",
            extra={"mas_command": mas_command},
        )

    def missing_agent_context(self, command_name: str) -> dict[str, Any]:
        return self.error(
            output=f"mini-mas {command_name} requires Agent context.\n",
            returncode=2,
            exception_info="missing_agent_context",
            mas_command_error="missing_agent_context",
        )

    def invalid_arguments(
        self,
        *,
        output: str,
        exception_info: str,
        mas_command_error: str,
    ) -> dict[str, Any]:
        return self.error(
            output=output,
            returncode=2,
            exception_info=exception_info,
            mas_command_error=mas_command_error,
        )

    def authority_error(self, result: dict[str, Any], *, mas_command: list[str]) -> dict[str, Any]:
        return {
            **result,
            "extra": {"mas_command": mas_command, **result.get("extra", {})},
        }

    def direct_child_statuses(
        self,
        *,
        mas_command: list[str],
        snapshots: list[dict[str, Any]],
        parent_workflow_id: str,
    ) -> dict[str, Any]:
        return self.success(
            output=format_direct_child_statuses(snapshots, parent_workflow_id=parent_workflow_id),
            extra={"mas_command": mas_command},
        )

    def specific_status(self, *, mas_command: list[str], snapshot: dict[str, Any]) -> dict[str, Any]:
        return self.success(output=format_specific_status(snapshot), extra={"mas_command": mas_command})

    def detached_spawn(self, *, mas_command: list[str], children: list[dict[str, str]]) -> dict[str, Any]:
        return self._spawn_result(
            mas_command=mas_command,
            children=children,
            output=_format_detached_spawn_output(children),
            extra={"waited": False, "ready_children": [], "still_running_child_agent_ids": []},
        )

    def spawn_waited(
        self,
        *,
        mas_command: list[str],
        children: list[dict[str, str]],
        wait_result: ChildWaitResult,
    ) -> dict[str, Any]:
        return self._spawn_result(
            mas_command=mas_command,
            children=children,
            output=_format_wait_summary_output(
                command_name="Waited spawn",
                wait_mode=wait_result.wait_mode,
                timed_out=wait_result.timed_out,
                children=children,
                ready_snapshots=wait_result.ready_snapshots,
                still_running_ids=wait_result.still_running_ids,
            ),
            extra={
                "waited": True,
                "wait_mode": wait_result.wait_mode,
                "timed_out": wait_result.timed_out,
                "ready_children": wait_result.ready_snapshots,
                "still_running_child_agent_ids": wait_result.still_running_ids,
            },
        )

    def no_child_workflows(self, *, mas_command: list[str]) -> dict[str, Any]:
        return self.error(
            output="No current child workflows found for mini-mas wait.\n",
            returncode=1,
            exception_info="no_child_workflows",
            mas_command_error="no_child_workflows",
            mas_command=mas_command,
        )

    def wait_summary(
        self,
        *,
        mas_command: list[str],
        children: list[dict[str, str]],
        wait_result: ChildWaitResult,
    ) -> dict[str, Any]:
        return self.success(
            output=_format_wait_summary_output(
                command_name="mini-mas wait",
                wait_mode=wait_result.wait_mode,
                timed_out=wait_result.timed_out,
                children=children,
                ready_snapshots=wait_result.ready_snapshots,
                still_running_ids=wait_result.still_running_ids,
            ),
            extra={
                "mas_command": mas_command,
                "wait_mode": wait_result.wait_mode,
                "timed_out": wait_result.timed_out,
                "ready_children": wait_result.ready_snapshots,
                "still_running_child_agent_ids": wait_result.still_running_ids,
                "children": children,
            },
        )

    def continuation_sent(
        self,
        *,
        mas_command: list[str],
        target_workflow_id: str,
        content: str,
        target_status: dict[str, Any],
        signal: dict[str, Any],
    ) -> dict[str, Any]:
        return self.success(
            output=_format_continue_output(
                target_workflow_id=target_workflow_id,
                content=content,
                snapshot=target_status,
            ),
            extra={
                "mas_command": mas_command,
                "continued_agent_id": target_workflow_id,
                "continuation_signal": signal,
                "target_status": target_status,
            },
        )

    def close_sent(
        self,
        *,
        mas_command: list[str],
        target_workflow_id: str,
        target_status: dict[str, Any],
        signal: dict[str, Any],
    ) -> dict[str, Any]:
        return self.success(
            output=_format_close_output(target_workflow_id=target_workflow_id, snapshot=target_status),
            extra={
                "mas_command": mas_command,
                "closed_agent_id": target_workflow_id,
                "close_signal": signal,
                "target_status": target_status,
            },
        )

    def success(self, *, output: str, extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "output": output,
            "returncode": 0,
            "exception_info": "",
            "extra": extra,
        }

    def error(
        self,
        *,
        output: str,
        returncode: int,
        exception_info: str,
        mas_command_error: str,
        mas_command: list[str] | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, Any] = {"mas_command_error": mas_command_error}
        if mas_command is not None:
            extra = {"mas_command": mas_command, **extra}
        return {
            "output": output,
            "returncode": returncode,
            "exception_info": exception_info,
            "extra": extra,
        }

    def _spawn_result(
        self,
        *,
        mas_command: list[str],
        children: list[dict[str, str]],
        output: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        child_agent_ids = [child["agent_id"] for child in children]
        result_extra: dict[str, Any] = {
            "mas_command": mas_command,
            "spawned_child_count": len(children),
            "child_agent_ids": child_agent_ids,
            "children": children,
        }
        if len(children) == 1:
            result_extra["child_agent_id"] = children[0]["agent_id"]
            result_extra.update({key: value for key, value in children[0].items() if key != "task"})
        result_extra.update(extra)
        return self.success(output=output, extra=result_extra)


class MasCommandHandler:
    """Parse and dispatch classified Standalone MAS Commands in the workflow layer."""

    def __init__(
        self,
        *,
        authority: AuthorityPolicy | None = None,
        result_formatter: MasCommandResultFormatter | None = None,
    ) -> None:
        self.authority = authority or DirectChildAuthorityPolicy()
        self.result_formatter = result_formatter or MasCommandResultFormatter()

    async def execute(self, classification: MasCommandClassification) -> dict[str, Any]:
        if classification.kind != MasCommandKind.STANDALONE:
            raise ValueError("MasCommandHandler only accepts classified standalone MAS commands")

        command_name = classification.arguments[0] if classification.arguments else ""
        if command_name == "status":
            return await self._status(classification)
        if command_name == "spawn":
            return await self._spawn(classification)
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
            return self.result_formatter.missing_agent_context("status")
        if len(classification.arguments) == 1:
            snapshots = await self.authority.list_observable_children(parent_workflow_id=current_workflow_id)
            return self.result_formatter.direct_child_statuses(
                mas_command=classification.arguments,
                snapshots=snapshots,
                parent_workflow_id=current_workflow_id,
            )
        if len(classification.arguments) == 2:
            target_workflow_id = classification.arguments[1]
            authority_result = await self.authority.require_observable_child(
                parent_workflow_id=current_workflow_id,
                target_workflow_id=target_workflow_id,
                command_name="status",
            )
            error = _authority_result_error(authority_result)
            if error is not None:
                return self.result_formatter.authority_error(error, mas_command=classification.arguments)
            snapshot = _authority_result_snapshot(authority_result)
            return self.result_formatter.specific_status(mas_command=classification.arguments, snapshot=snapshot)
        return self.result_formatter.invalid_arguments(
            output="Usage: mini-mas status [agent-id]\n",
            exception_info="invalid_status_arguments",
            mas_command_error="invalid_status_arguments",
        )

    async def _spawn(self, classification: MasCommandClassification) -> dict[str, Any]:
        current_workflow_id = self._validated_context("spawn")
        if current_workflow_id is None:
            return self.result_formatter.missing_agent_context("spawn")
        try:
            request = _parse_spawn_arguments(classification.arguments)
        except ValueError as exc:
            return self.result_formatter.invalid_arguments(
                output=f"{exc}\n",
                exception_info=str(exc),
                mas_command_error="invalid_spawn_arguments",
            )
        spawn_result = await agent_interactions.spawn_children(
            parent_workflow_id=current_workflow_id,
            tasks=request.tasks,
        )
        children = spawn_result.children
        if request.wait:
            wait_result = await agent_interactions.wait_for_spawned_children(
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
            return self.result_formatter.missing_agent_context("wait")
        try:
            request = _parse_wait_arguments(classification.arguments)
        except ValueError as exc:
            return self.result_formatter.invalid_arguments(
                output=f"{exc}\n",
                exception_info=str(exc),
                mas_command_error="invalid_wait_arguments",
            )
        if request.workflow_id is not None:
            authority_result = await self.authority.require_observable_child(
                parent_workflow_id=current_workflow_id,
                target_workflow_id=request.workflow_id,
                command_name="wait",
            )
            error = _authority_result_error(authority_result)
            if error is not None:
                return self.result_formatter.authority_error(error, mas_command=classification.arguments)
            children = [_child_metadata_from_snapshot(_authority_result_snapshot(authority_result))]
        else:
            snapshots = await self.authority.list_observable_children(parent_workflow_id=current_workflow_id)
            children = [_child_metadata_from_snapshot(snapshot) for snapshot in snapshots]
        if not children:
            return self.result_formatter.no_child_workflows(mas_command=classification.arguments)
        wait_all = request.wait_all or request.workflow_id is not None
        wait_mode = "one" if request.workflow_id is not None else ("all" if wait_all else "any")
        wait_result = await agent_interactions.wait_for_children(
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
            return self.result_formatter.missing_agent_context("continue")
        try:
            request = _parse_continue_arguments(classification.arguments)
        except ValueError as exc:
            return self.result_formatter.invalid_arguments(
                output=f"{exc}\n",
                exception_info=str(exc),
                mas_command_error="invalid_continue_arguments",
            )
        authority_result = await self.authority.require_waiting_child(
            parent_workflow_id=current_workflow_id,
            target_workflow_id=request.workflow_id,
            command_name="continue",
        )
        error = _authority_result_error(authority_result)
        if error is not None:
            return self.result_formatter.authority_error(error, mas_command=classification.arguments)
        snapshot = _authority_result_snapshot(authority_result)
        signal = make_continuation_signal(
            source_workflow_id=current_workflow_id,
            target_workflow_id=request.workflow_id,
            content=request.content,
        )
        await agent_interactions.send_parent_direction(
            target_workflow_id=request.workflow_id,
            signal=signal,
            topic=PARENT_DIRECTION_TOPIC,
        )
        return self.result_formatter.continuation_sent(
            mas_command=classification.arguments,
            target_workflow_id=request.workflow_id,
            content=request.content,
            target_status=snapshot,
            signal=signal,
        )

    async def _close(self, classification: MasCommandClassification) -> dict[str, Any]:
        current_workflow_id = self._validated_context("close")
        if current_workflow_id is None:
            return self.result_formatter.missing_agent_context("close")
        try:
            request = _parse_close_arguments(classification.arguments)
        except ValueError as exc:
            return self.result_formatter.invalid_arguments(
                output=f"{exc}\n",
                exception_info=str(exc),
                mas_command_error="invalid_close_arguments",
            )
        authority_result = await self.authority.require_waiting_child(
            parent_workflow_id=current_workflow_id,
            target_workflow_id=request.workflow_id,
            command_name="close",
        )
        error = _authority_result_error(authority_result)
        if error is not None:
            return self.result_formatter.authority_error(error, mas_command=classification.arguments)
        snapshot = _authority_result_snapshot(authority_result)
        signal = make_close_signal(
            source_workflow_id=current_workflow_id,
            target_workflow_id=request.workflow_id,
        )
        await agent_interactions.send_parent_direction(
            target_workflow_id=request.workflow_id,
            signal=signal,
            topic=PARENT_DIRECTION_TOPIC,
        )
        return self.result_formatter.close_sent(
            mas_command=classification.arguments,
            target_workflow_id=request.workflow_id,
            target_status=snapshot,
            signal=signal,
        )

    def _validated_context(self, command_name: str) -> str | None:
        workflow_id = agent_interactions.current_workflow_id()
        if workflow_id is None:
            return None
        try:
            return validate_agent_id(workflow_id)
        except ValueError as exc:
            raise ValueError(f"Invalid Agent context for mini-mas {command_name}: {workflow_id}") from exc


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
            raise ValueError("mini-mas wait accepts at most one Agent ID")
        workflow_id = validate_agent_id(argument)
        index += 1

    if workflow_id is not None and (wait_any or wait_all):
        raise ValueError("mini-mas wait for one workflow cannot also use --any or --all")
    if wait_any and wait_all:
        raise ValueError("mini-mas wait cannot use both --any and --all")
    return WaitCommandRequest(workflow_id=workflow_id, wait_all=wait_all, timeout_seconds=timeout_seconds)


def _parse_continue_arguments(arguments: list[str]) -> ContinueCommandRequest:
    if len(arguments) != 3:
        raise ValueError('Usage: mini-mas continue <agent-id> "message"')
    workflow_id = validate_agent_id(arguments[1])
    content = arguments[2]
    if not content:
        raise ValueError('Usage: mini-mas continue <agent-id> "message"')
    return ContinueCommandRequest(workflow_id=workflow_id, content=content)


def _parse_close_arguments(arguments: list[str]) -> CloseCommandRequest:
    if len(arguments) != 2:
        raise ValueError("Usage: mini-mas close <agent-id>")
    return CloseCommandRequest(workflow_id=validate_agent_id(arguments[1]))


def _authority_result_error(result: Any) -> dict[str, Any] | None:
    if isinstance(result, AuthorityCommandError):
        return result.to_command_result()
    return None


def _authority_result_snapshot(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return normalize_agent_snapshot(result)
    raise TypeError(f"Unsupported Authority Policy result: {type(result)!r}")


def _child_metadata_from_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    snapshot = normalize_agent_snapshot(snapshot)
    metadata = {
        "task": "",
        "agent_id": str(snapshot["agent_id"]),
        "agent_artifact_directory": str(snapshot["agent_artifact_directory"]),
        "trajectory_artifact_path": str(snapshot["trajectory_artifact_path"]),
    }
    if snapshot.get("parent_agent_id"):
        metadata["parent_agent_id"] = str(snapshot["parent_agent_id"])
    return metadata


def _format_child_metadata_lines(child: dict[str, str]) -> list[str]:
    return [
        f"task: {child['task']}",
        f"agent_id: {child['agent_id']}",
        *([f"parent_agent_id: {child['parent_agent_id']}"] if child.get("parent_agent_id") else []),
        f"agent_artifact_directory: {child['agent_artifact_directory']}",
        f"trajectory_artifact_path: {child['trajectory_artifact_path']}",
    ]


def _format_detached_spawn_output(children: list[dict[str, str]]) -> str:
    lines = ["Detached spawn started", f"child_count: {len(children)}"]
    for index, child in enumerate(children):
        if index:
            lines.append("")
        lines.extend(_format_child_metadata_lines(child))
    return "\n".join(lines) + "\n"


def _format_still_running_ids(still_running_ids: list[str]) -> str:
    return ", ".join(still_running_ids) if still_running_ids else "none"


def _format_ready_snapshot(snapshot: dict[str, Any]) -> list[str]:
    snapshot = normalize_agent_snapshot(snapshot)
    lines = [
        f"ready_agent_id: {snapshot['agent_id']}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
    ]
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


def _format_wait_summary_output(
    *,
    command_name: str,
    wait_mode: str,
    timed_out: bool,
    children: list[dict[str, str]],
    ready_snapshots: list[dict[str, Any]],
    still_running_ids: list[str],
) -> str:
    lines = [
        f"{command_name} {'timed out' if timed_out else 'completed'}",
        f"wait_mode: {wait_mode}",
        f"child_count: {len(children)}",
        f"ready_child_count: {len(ready_snapshots)}",
        f"still_running_child_agent_ids: {_format_still_running_ids(still_running_ids)}",
        "",
        "started_children:",
    ]
    for index, child in enumerate(children):
        if index:
            lines.append("")
        lines.extend(_format_child_metadata_lines(child))
    if ready_snapshots:
        lines.extend(["", "ready_children:"])
        for index, snapshot in enumerate(ready_snapshots):
            if index:
                lines.append("")
            lines.extend(_format_ready_snapshot(snapshot))
    return "\n".join(lines) + "\n"


def _format_continue_output(*, target_workflow_id: str, content: str, snapshot: dict[str, Any]) -> str:
    snapshot = normalize_agent_snapshot(snapshot)
    lines = [
        "Continuation signal sent",
        f"agent_id: {target_workflow_id}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
        f"message: {content}",
        f"agent_artifact_directory: {snapshot['agent_artifact_directory']}",
        f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
    ]
    return "\n".join(lines) + "\n"


def _format_close_output(*, target_workflow_id: str, snapshot: dict[str, Any]) -> str:
    snapshot = normalize_agent_snapshot(snapshot)
    lines = [
        "Close signal sent",
        f"agent_id: {target_workflow_id}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
    ]
    if snapshot.get("latest_submission"):
        lines.append(f"latest_submission: {snapshot['latest_submission']}")
    lines.extend(
        [
            f"agent_artifact_directory: {snapshot['agent_artifact_directory']}",
            f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
        ]
    )
    return "\n".join(lines) + "\n"
