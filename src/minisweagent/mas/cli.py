"""External CLI for DBOS-backed MAS commands."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.console import Console

from minisweagent.mas.runtime import (
    close_agent_workflow,
    continue_agent_workflow,
    get_agent_workflow_status,
    send_root_command,
    start_interactive_root_agent_workflow,
    start_root_agent_workflow,
    wait_for_agent_workflow,
)

app = typer.Typer(
    rich_markup_mode="rich",
    help="Run DBOS-backed mini-SWE-agent MAS commands.",
    invoke_without_command=True,
)
console = Console(highlight=False, soft_wrap=True)


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


@app.command(help="Start a minimal Root Agent through DBOS.")
def run(
    workflow_id: Annotated[
        str | None,
        typer.Option("--agent-id", "--workflow-id", help="Explicit Root Agent ID. Defaults to a generated mas-<16hex> ID."),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option("--wait", help="Wait for the minimal Root Agent result before returning."),
    ] = True,
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
        start_root_agent_workflow(
            workflow_id=workflow_id,
            wait=wait,
            system_database_url=system_database_url,
        )
    )
    console.print(f"agent_id: {result['agent_id']}")
    console.print(f"agent_artifact_directory: {result['agent_artifact_directory']}")
    console.print(f"trajectory_artifact_path: {result['trajectory_artifact_path']}")
    if "result" in result:
        console.print(f"result: {result['result']}")
    return result


@app.command(help="Inspect a Root Agent or one descendant Agent without waiting for completion.")
def status(
    workflow_id: Annotated[str, typer.Argument(help="Root or descendant Agent ID to inspect.")],
    system_database_url: Annotated[
        str | None,
        typer.Option(
            "--system-database-url",
            help="DBOS system database URL. Defaults to DBOS_SYSTEM_DATABASE_URL.",
            show_default=False,
        ),
    ] = None,
) -> dict[str, Any]:
    result = dict(get_agent_workflow_status(workflow_id=workflow_id, system_database_url=system_database_url))
    console.print(result["output"], end="")
    raise typer.Exit(code=result["returncode"])


@app.command(help="Send one bash-shaped command to an Interactive Root Agent.")
def command(
    root_agent_id: Annotated[str, typer.Argument(help="Interactive Root Agent ID.")],
    command_text: Annotated[str, typer.Argument(help="One bash-shaped command to execute through the Root Agent.")],
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
    result_event = dict(
        send_root_command(
            root_agent_id=root_agent_id,
            command=command_text,
            result_timeout_seconds=result_timeout_seconds,
            system_database_url=system_database_url,
        )
    )
    command_result = result_event["result"]
    console.print(command_result.get("output", ""), end="")
    if command_result.get("returncode", 0) != 0:
        raise typer.Exit(code=command_result["returncode"])
    return result_event


@app.command(help="Wait for one Child Agent First Observable Event.")
def wait(
    workflow_id: Annotated[str, typer.Argument(help="Child Agent ID to wait for.")],
    timeout_seconds: Annotated[
        float | None,
        typer.Option("--timeout", help="Maximum seconds to wait for the First Observable Event.", show_default=False),
    ] = None,
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
        wait_for_agent_workflow(
            workflow_id=workflow_id,
            timeout_seconds=timeout_seconds,
            system_database_url=system_database_url,
        )
    )
    console.print(result["output"], end="")
    raise typer.Exit(code=result["returncode"])


@app.command("continue", help="Send a Continuation Signal to one waiting Child Agent.")
def continue_(
    workflow_id: Annotated[str, typer.Argument(help="Waiting Child Agent ID to continue.")],
    message: Annotated[str, typer.Argument(help="Continuation message to append to the child trajectory.")],
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
        continue_agent_workflow(
            workflow_id=workflow_id,
            message=message,
            system_database_url=system_database_url,
        )
    )
    console.print(result["output"], end="")
    if result["returncode"] != 0:
        raise typer.Exit(code=result["returncode"])
    return result


@app.command(help="Send a neutral Close Signal to one waiting Child Agent.")
def close(
    workflow_id: Annotated[str, typer.Argument(help="Waiting Child Agent ID to close.")],
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
        close_agent_workflow(
            workflow_id=workflow_id,
            system_database_url=system_database_url,
        )
    )
    console.print(result["output"], end="")
    if result["returncode"] != 0:
        raise typer.Exit(code=result["returncode"])
    return result


if __name__ == "__main__":
    app()
