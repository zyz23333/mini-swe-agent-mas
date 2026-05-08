"""External CLI for DBOS-backed MAS commands."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.console import Console

from minisweagent.mas.runtime import start_root_agent_workflow

app = typer.Typer(rich_markup_mode="rich", help="Run DBOS-backed mini-SWE-agent MAS commands.")
console = Console(highlight=False)


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
    ] = False,
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
    console.print(f"workflow_id: {result['workflow_id']}")
    if "result" in result:
        console.print(f"result: {result['result']}")
    return result


if __name__ == "__main__":
    app()
