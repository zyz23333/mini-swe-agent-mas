"""External CLI for DBOS-backed MAS commands."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.console import Console

from minisweagent.mas.runtime import get_agent_workflow_status, start_root_agent_workflow, wait_for_agent_workflow
from minisweagent.mas.status import format_specific_status, format_status_tree
from minisweagent.mas.workflows import _format_wait_summary_output

app = typer.Typer(rich_markup_mode="rich", help="Run DBOS-backed mini-SWE-agent MAS commands.")
console = Console(highlight=False, soft_wrap=True)


@app.callback()
def main() -> None:
    """External MAS CLI entrypoint."""


@app.command(help="Start a minimal Root Agent Workflow through DBOS.")
def run(
    workflow_id: Annotated[
        str | None,
        typer.Option("--workflow-id", help="Explicit Root Agent Workflow ID. Defaults to a generated mas-<16hex> ID."),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option("--wait", help="Wait for the minimal Root Agent Workflow result before returning."),
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
    console.print(f"root_workflow_id: {result['root_workflow_id']}")
    console.print(f"workflow_id: {result['workflow_id']}")
    console.print(f"run_directory: {result['run_directory']}")
    console.print(f"trajectory_artifact_path: {result['trajectory_artifact_path']}")
    if "result" in result:
        console.print(f"result: {result['result']}")
    return result


@app.command(help="Inspect a Root Agent Workflow tree or one descendant without waiting for completion.")
def status(
    workflow_id: Annotated[str, typer.Argument(help="Root or descendant Workflow Tree ID to inspect.")],
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
    if result["kind"] == "tree":
        console.print(
            format_status_tree(
                result["snapshots"],
                root_workflow_id=result["root_workflow_id"],
            ),
            end="",
        )
        return result
    if result["kind"] == "single":
        console.print(format_specific_status(result["snapshot"]), end="")
        return result

    console.print(f"Workflow not found in current Agent Workflow Tree: {result['workflow_id']}")
    raise typer.Exit(code=1)


@app.command(help="Wait for one Child Agent Workflow First Observable Event.")
def wait(
    workflow_id: Annotated[str, typer.Argument(help="Child Workflow Tree ID to wait for.")],
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
    console.print(
        _format_wait_summary_output(
            command_name="mini-mas wait",
            wait_all=True,
            timed_out=result["timed_out"],
            children=result["children"],
            ready_snapshots=result["ready_children"],
            still_running_ids=result["still_running_child_workflow_ids"],
        ).replace("wait_mode: all", "wait_mode: one", 1),
        end="",
    )
    if result["timed_out"]:
        raise typer.Exit(code=1)
    return result


if __name__ == "__main__":
    app()
