"""Model-visible result formatting for workflow-layer MAS commands."""

from __future__ import annotations

from typing import Any

from minisweagent.mas.coordination import ChildWaitResult
from minisweagent.mas.status import format_direct_child_statuses, format_specific_status


class MasCommandResultFormatter:
    """Own the stable observation dictionary shape for MAS command results."""

    def accepted(self, *, mas_command: list[str]) -> dict[str, Any]:
        command_text = " ".join(mas_command)
        return self.success(
            output=f"MAS command accepted: {command_text}\n",
            extra={"mas_command": mas_command},
        )

    def missing_agent_workflow_context(self, command_name: str) -> dict[str, Any]:
        return self.error(
            output=f"mini-mas {command_name} requires Agent Workflow context.\n",
            returncode=2,
            exception_info="missing_agent_workflow_context",
            mas_command_error="missing_agent_workflow_context",
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
            extra={"waited": False, "ready_children": [], "still_running_child_workflow_ids": []},
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
                "still_running_child_workflow_ids": wait_result.still_running_ids,
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
                "still_running_child_workflow_ids": wait_result.still_running_ids,
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
                "continued_workflow_id": target_workflow_id,
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
                "closed_workflow_id": target_workflow_id,
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
        child_workflow_ids = [child["workflow_id"] for child in children]
        result_extra: dict[str, Any] = {
            "mas_command": mas_command,
            "spawned_child_count": len(children),
            "child_workflow_ids": child_workflow_ids,
            "children": children,
        }
        if len(children) == 1:
            result_extra["child_workflow_id"] = children[0]["workflow_id"]
            result_extra.update({key: value for key, value in children[0].items() if key != "task"})
        result_extra.update(extra)
        return self.success(output=output, extra=result_extra)


def _format_child_metadata_lines(child: dict[str, str]) -> list[str]:
    return [
        f"task: {child['task']}",
        f"workflow_id: {child['workflow_id']}",
        f"run_directory: {child['run_directory']}",
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
    lines = [
        f"ready_workflow_id: {snapshot['workflow_id']}",
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
        f"still_running_child_workflow_ids: {_format_still_running_ids(still_running_ids)}",
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
    lines = [
        "Continuation signal sent",
        f"workflow_id: {target_workflow_id}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
        f"message: {content}",
        f"run_directory: {snapshot['run_directory']}",
        f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
    ]
    return "\n".join(lines) + "\n"


def _format_close_output(*, target_workflow_id: str, snapshot: dict[str, Any]) -> str:
    lines = [
        "Close signal sent",
        f"workflow_id: {target_workflow_id}",
        f"lifecycle_state: {snapshot['lifecycle_state']}",
    ]
    if snapshot.get("latest_submission"):
        lines.append(f"latest_submission: {snapshot['latest_submission']}")
    lines.extend(
        [
            f"run_directory: {snapshot['run_directory']}",
            f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
        ]
    )
    return "\n".join(lines) + "\n"
