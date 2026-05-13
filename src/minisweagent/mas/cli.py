"""External CLI for DBOS-backed MAS commands."""

from __future__ import annotations

import shlex
import threading
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from minisweagent.mas.commands import validate_spawn_arguments
from minisweagent.mas.queues import AI_AGENT_WORKFLOW_QUEUE_NAME
from minisweagent.mas.runtime import (
    MAS_RUNTIME_STATE_STORE_PATH,
    activate_ai_agent_execution,
    discover_interactive_root_agents,
    one_shot_spawn_through_interactive_root,
    prepare_resume_root_agent,
    refresh_root_attachment,
    release_root_attachment,
    send_root_command,
    start_interactive_root_agent_workflow,
)

app = typer.Typer(
    name="mini-mas",
    rich_markup_mode="rich",
    help="Interactive Root Agent CLI. Use plain mini-mas, spawn, status, and resume.",
    invoke_without_command=True,
)
console = Console(highlight=False, soft_wrap=True)
UNSUPPORTED_EXTERNAL_GOVERNANCE_OUTPUT = (
    "Unsupported external MAS governance command.\n"
    "Use mini-mas status to inspect Interactive Root Agents, then re-enter one with "
    "mini-mas resume <root-agent-id>.\n"
)
UNSUPPORTED_EXTERNAL_GOVERNANCE_RETURNCODE = 2
agent_app = typer.Typer(help="AI Agent Execution.")
app.add_typer(agent_app, name="agent")


@app.callback()
def main(ctx: typer.Context) -> None:
    """External MAS CLI entrypoint."""
    if ctx.invoked_subcommand is not None:
        return
    last_returncode = _run_lazy_plain_terminal()
    if last_returncode != 0:
        raise typer.Exit(code=last_returncode)


def _print_root_metadata_banner(result: dict[str, Any]) -> None:
    console.print(f"agent_id: {result['agent_id']}")
    console.print(f"lifecycle_state: {result['lifecycle_state']}")
    console.print(f"agent_artifact_directory: {result['agent_artifact_directory']}")
    console.print(f"trajectory_artifact_path: {result['trajectory_artifact_path']}")


def _reject_external_governance_command() -> None:
    console.print(UNSUPPORTED_EXTERNAL_GOVERNANCE_OUTPUT, end="")
    raise typer.Exit(code=UNSUPPORTED_EXTERNAL_GOVERNANCE_RETURNCODE)


def _format_ai_agent_activation_notice(
    *,
    active_workspace: Path | str,
    runtime_state_store: Path | str,
    queue_name: str,
) -> str:
    lines = [
        "AI Agent Execution activation",
        f"active_workspace: {active_workspace}",
        f"mas_runtime_state_store: {runtime_state_store}",
        f"ai_agent_queue: {queue_name}",
        (
            "side_effect_warning: Queued AI Agent work may call models, execute bash actions, "
            "and modify the Shared Workspace."
        ),
        "Press Ctrl-C to deactivate AI Agent Execution without closing, accepting, cancelling, or deleting Agents.",
    ]
    return "\n".join(lines) + "\n"


@app.command(hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(_ctx: typer.Context) -> None:
    _reject_external_governance_command()


@app.command(
    help="List Interactive Root Agents.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def status(
    ctx: typer.Context,
) -> dict[str, Any]:
    if ctx.args:
        _reject_external_governance_command()

    result = dict(discover_interactive_root_agents())
    console.print(result["output"], end="")
    return result


@app.command(hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def command(_ctx: typer.Context) -> None:
    _reject_external_governance_command()


@agent_app.command(help="Activate foreground AI Agent Execution for queued AI Agent work.")
def activate() -> dict[str, Any]:
    notice = _format_ai_agent_activation_notice(
        active_workspace=Path.cwd(),
        runtime_state_store=MAS_RUNTIME_STATE_STORE_PATH,
        queue_name=AI_AGENT_WORKFLOW_QUEUE_NAME,
    )
    console.print(notice, end="")
    return dict(activate_ai_agent_execution())


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Create an Interactive Root Agent and spawn Child Agents through it.",
)
def spawn(
    ctx: typer.Context,
    result_timeout_seconds: Annotated[
        float,
        typer.Option("--result-timeout", help="Maximum seconds to wait for the Root Command Result."),
    ] = 60,
) -> dict[str, Any]:
    try:
        validate_spawn_arguments(list(ctx.args))
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    result = dict(
        one_shot_spawn_through_interactive_root(
            spawn_arguments=list(ctx.args),
            result_timeout_seconds=result_timeout_seconds,
        )
    )
    if result["kind"] == "one_shot_spawn_result_timeout":
        console.print(result["output"], end="")
        raise typer.Exit(code=result["returncode"])

    console.print(f"root_agent_id: {result['root_agent_id']}")
    console.print()
    command_result = result["result"]
    console.print(command_result.get("output", ""), end="")
    if command_result.get("returncode", 0) != 0:
        raise typer.Exit(code=command_result["returncode"])
    return result


@app.command(help="Resume an existing Interactive Root Agent terminal.")
def resume(
    root_agent_id: Annotated[str, typer.Argument(help="Interactive Root Agent ID to resume.")],
    result_timeout_seconds: Annotated[
        float,
        typer.Option("--result-timeout", help="Maximum seconds to wait for each Root Command Result."),
    ] = 60,
) -> dict[str, Any]:
    resume_result = dict(prepare_resume_root_agent(root_agent_id=root_agent_id))
    if resume_result["returncode"] != 0:
        console.print(resume_result["output"], end="")
        raise typer.Exit(code=resume_result["returncode"])

    _print_root_metadata_banner(resume_result)
    last_result, last_returncode = _run_attached_terminal(
        root_agent_id=root_agent_id,
        attachment_token=str(resume_result["attachment_token"]),
        result_timeout_seconds=result_timeout_seconds,
    )
    if last_result is None:
        last_result = resume_result
    if last_returncode != 0:
        raise typer.Exit(code=last_returncode)
    return last_result


def _run_lazy_plain_terminal(*, result_timeout_seconds: float = 60) -> int:
    for command_text in _iter_terminal_input():
        if _is_local_terminal_exit(command_text):
            return 0
        if command_text.strip() == "":
            continue
        local_result = _handle_pre_root_local_command(
            command_text,
            result_timeout_seconds=result_timeout_seconds,
        )
        if local_result["handled"]:
            if local_result["attached"]:
                return int(local_result["returncode"])
            continue

        try:
            root_result = dict(start_interactive_root_agent_workflow())
        except Exception as exc:
            console.print(f"Failed to create Interactive Root Agent: {exc}")
            return 1
        root_agent_id = str(root_result["agent_id"])
        resume_result = dict(prepare_resume_root_agent(root_agent_id=root_agent_id))
        if resume_result["returncode"] != 0:
            console.print(resume_result.get("output", ""), end="")
            return int(resume_result["returncode"])

        _print_root_metadata_banner(resume_result)
        _last_result, last_returncode = _run_attached_terminal(
            root_agent_id=root_agent_id,
            attachment_token=str(resume_result["attachment_token"]),
            result_timeout_seconds=result_timeout_seconds,
            initial_command=command_text,
        )
        return last_returncode
    return 0


def _handle_pre_root_local_command(
    command_text: str,
    *,
    result_timeout_seconds: float,
) -> dict[str, bool | int]:
    parsed_command = _parse_pre_root_local_mini_mas_command(command_text)
    if parsed_command is None:
        return {"handled": False, "attached": False, "returncode": 0}

    command_name, command_args = parsed_command
    if command_name == "status" and not command_args:
        result = dict(discover_interactive_root_agents())
        console.print(result["output"], end="")
        return {"handled": True, "attached": False, "returncode": int(result.get("returncode", 0))}

    if command_name == "resume" and len(command_args) == 1:
        root_agent_id = command_args[0]
        resume_result = dict(prepare_resume_root_agent(root_agent_id=root_agent_id))
        if resume_result["returncode"] != 0:
            console.print(resume_result["output"], end="")
            return {"handled": True, "attached": False, "returncode": int(resume_result["returncode"])}

        _print_root_metadata_banner(resume_result)
        _last_result, last_returncode = _run_attached_terminal(
            root_agent_id=root_agent_id,
            attachment_token=str(resume_result["attachment_token"]),
            result_timeout_seconds=result_timeout_seconds,
        )
        return {"handled": True, "attached": True, "returncode": last_returncode}

    return {"handled": False, "attached": False, "returncode": 0}


def _parse_pre_root_local_mini_mas_command(command_text: str) -> tuple[str, list[str]] | None:
    try:
        parts = shlex.split(command_text)
    except ValueError:
        return None
    if len(parts) < 2 or parts[0] != "mini-mas":
        return None
    return parts[1], parts[2:]


def _run_attached_terminal(
    *,
    root_agent_id: str,
    attachment_token: str,
    result_timeout_seconds: float,
    initial_command: str | None = None,
) -> tuple[dict[str, Any] | None, int]:
    last_result: dict[str, Any] | None = None
    last_returncode = 0
    stop_heartbeat = threading.Event()
    heartbeat = threading.Thread(
        target=_refresh_attachment_until_stopped,
        kwargs={"root_agent_id": root_agent_id, "attachment_token": attachment_token, "stop_event": stop_heartbeat},
        daemon=True,
    )
    heartbeat.start()
    try:
        command_iterable = _iter_attached_commands(initial_command=initial_command)
        for command_text in command_iterable:
            if _is_local_terminal_exit(command_text):
                break
            if command_text == "":
                continue
            last_result = dict(
                send_root_command(
                    root_agent_id=root_agent_id,
                    command=command_text,
                    result_timeout_seconds=result_timeout_seconds,
                    attachment_token=attachment_token,
                )
            )
            command_result = last_result["result"]
            console.print(command_result.get("output", ""), end="")
            last_returncode = command_result.get("returncode", 0)
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=1)
        release_root_attachment(root_agent_id=root_agent_id, attachment_token=attachment_token)
    return last_result, last_returncode


def _iter_terminal_input():
    """Yield terminal input lines without using prompt-toolkit history."""
    while True:
        try:
            yield input()
        except EOFError:
            return


def _iter_attached_commands(*, initial_command: str | None = None):
    if initial_command is not None:
        yield initial_command
    yield from _iter_terminal_input()


def _is_local_terminal_exit(command_text: str) -> bool:
    return command_text.strip() in {"exit", "quit"}


def _refresh_attachment_until_stopped(
    *,
    root_agent_id: str,
    attachment_token: str,
    stop_event: threading.Event,
    interval_seconds: float = 30.0,
) -> None:
    """Keep an attached resume terminal's lease alive while waiting for local input."""
    while not stop_event.wait(interval_seconds):
        refresh_root_attachment(root_agent_id=root_agent_id, attachment_token=attachment_token)


@app.command(hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def wait(_ctx: typer.Context) -> None:
    _reject_external_governance_command()


@app.command("continue", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def continue_(_ctx: typer.Context) -> None:
    _reject_external_governance_command()


@app.command(hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def close(_ctx: typer.Context) -> None:
    _reject_external_governance_command()


if __name__ == "__main__":
    app()
