"""External CLI for DBOS-backed MAS commands."""

from __future__ import annotations

import threading
from typing import Annotated, Any

import typer
from rich.console import Console

from minisweagent.mas.runtime import (
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


@app.callback()
def main(
    ctx: typer.Context,
    system_database_url: Annotated[
        str | None,
        typer.Option(
            "--system-database-url",
            help="DBOS system database URL. Defaults to DBOS_SYSTEM_DATABASE_URL.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """External MAS CLI entrypoint."""
    if ctx.invoked_subcommand is not None:
        return
    result = dict(start_interactive_root_agent_workflow(system_database_url=system_database_url))
    _print_root_metadata_banner(result)


def _print_root_metadata_banner(result: dict[str, Any]) -> None:
    console.print(f"agent_id: {result['agent_id']}")
    console.print(f"lifecycle_state: {result['lifecycle_state']}")
    console.print(f"agent_artifact_directory: {result['agent_artifact_directory']}")
    console.print(f"trajectory_artifact_path: {result['trajectory_artifact_path']}")


def _reject_external_governance_command() -> None:
    console.print(UNSUPPORTED_EXTERNAL_GOVERNANCE_OUTPUT, end="")
    raise typer.Exit(code=UNSUPPORTED_EXTERNAL_GOVERNANCE_RETURNCODE)


@app.command(hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(_ctx: typer.Context) -> None:
    _reject_external_governance_command()


@app.command(
    help="List Interactive Root Agents.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def status(
    ctx: typer.Context,
    system_database_url: Annotated[
        str | None,
        typer.Option(
            "--system-database-url",
            help="DBOS system database URL. Defaults to DBOS_SYSTEM_DATABASE_URL.",
            show_default=False,
        ),
    ] = None,
) -> dict[str, Any]:
    if ctx.args:
        _reject_external_governance_command()

    result = dict(discover_interactive_root_agents(system_database_url=system_database_url))
    console.print(result["output"], end="")
    return result


@app.command(hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def command(_ctx: typer.Context) -> None:
    _reject_external_governance_command()


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
    system_database_url: Annotated[
        str | None,
        typer.Option(
            "--system-database-url",
            help="DBOS system database URL. Defaults to DBOS_SYSTEM_DATABASE_URL.",
            show_default=False,
        ),
    ] = None,
) -> dict[str, Any]:
    result = dict(
        one_shot_spawn_through_interactive_root(
            spawn_arguments=list(ctx.args),
            result_timeout_seconds=result_timeout_seconds,
            system_database_url=system_database_url,
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
    system_database_url: Annotated[
        str | None,
        typer.Option(
            "--system-database-url",
            help="DBOS system database URL. Defaults to DBOS_SYSTEM_DATABASE_URL.",
            show_default=False,
        ),
    ] = None,
) -> dict[str, Any]:
    resume_result = dict(prepare_resume_root_agent(root_agent_id=root_agent_id, system_database_url=system_database_url))
    if resume_result["returncode"] != 0:
        console.print(resume_result["output"], end="")
        raise typer.Exit(code=resume_result["returncode"])

    _print_root_metadata_banner(resume_result)
    last_result: dict[str, Any] = resume_result
    last_returncode = 0
    attachment_token = str(resume_result["attachment_token"])
    stop_heartbeat = threading.Event()
    heartbeat = threading.Thread(
        target=_refresh_attachment_until_stopped,
        kwargs={"root_agent_id": root_agent_id, "attachment_token": attachment_token, "stop_event": stop_heartbeat},
        daemon=True,
    )
    heartbeat.start()
    try:
        for command_text in _iter_terminal_input():
            if command_text == "":
                continue
            last_result = dict(
                send_root_command(
                    root_agent_id=root_agent_id,
                    command=command_text,
                    result_timeout_seconds=result_timeout_seconds,
                    system_database_url=system_database_url,
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
    if last_returncode != 0:
        raise typer.Exit(code=last_returncode)
    return last_result


def _iter_terminal_input():
    """Yield terminal input lines without using prompt-toolkit history."""
    while True:
        try:
            yield input()
        except EOFError:
            return


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
