from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from minisweagent.mas.cli import app

from .helpers import (
    AsyncMockHandle,
    _mock_dbos_module,
)


def test_mini_mas_run_cli_outputs_artifact_locations():
    handle = AsyncMockHandle(
        "mas-2222222222222222",
        {
            "agent_id": "mas-2222222222222222",
            "status": "started",
            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
        },
    )

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        cli_result = CliRunner().invoke(app, ["run", "--workflow-id", "mas-2222222222222222"])

    assert cli_result.exit_code == 0
    assert "agent_id: mas-2222222222222222" in cli_result.stdout
    assert "agent_artifact_directory: .mini-mas/agents/mas-2222222222222222" in cli_result.stdout
    assert (
        "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json"
        in cli_result.stdout
    )

def test_mini_mas_status_cli_reports_external_agent_interaction_unsupported(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.get_agent_workflow_status",
        Mock(
            return_value={
                "kind": "unsupported",
                "workflow_id": "mas-2222222222222222",
                "output": "External mini-mas status, wait, continue, and close are unsupported.\n",
                "returncode": 2,
                "exception_info": "external_agent_interaction_unsupported",
                "extra": {"mas_command_error": "external_agent_interaction_unsupported"},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["status", "mas-2222222222222222"])
    assert cli_result.exit_code == 2
    assert "unsupported" in cli_result.stdout

def test_mini_mas_status_cli_does_not_support_missing_descendant_lookup(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.get_agent_workflow_status",
        Mock(
            return_value={
                "kind": "unsupported",
                "workflow_id": "mas-9999999999999999",
                "output": "External mini-mas status, wait, continue, and close are unsupported.\n",
                "returncode": 2,
                "exception_info": "external_agent_interaction_unsupported",
                "extra": {"mas_command_error": "external_agent_interaction_unsupported"},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["status", "mas-9999999999999999"])

    assert cli_result.exit_code == 2
    assert "unsupported" in cli_result.stdout

def test_mini_mas_wait_cli_outputs_first_observable_event(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.wait_for_agent_workflow",
        Mock(
            return_value={
                "workflow_id": "mas-3333333333333333",
                "output": "External mini-mas status, wait, continue, and close are unsupported.\n",
                "returncode": 2,
                "exception_info": "external_agent_interaction_unsupported",
                "extra": {"mas_command_error": "external_agent_interaction_unsupported"},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["wait", "mas-3333333333333333", "--timeout", "0.01"])

    assert cli_result.exit_code == 2
    assert "unsupported" in cli_result.stdout

def test_mini_mas_wait_cli_outputs_closed_event_neutrally(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.wait_for_agent_workflow",
        Mock(
            return_value={
                "workflow_id": "mas-3333333333333333",
                "output": "External mini-mas status, wait, continue, and close are unsupported.\n",
                "returncode": 2,
                "exception_info": "external_agent_interaction_unsupported",
                "extra": {"mas_command_error": "external_agent_interaction_unsupported"},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["wait", "mas-3333333333333333"])

    assert cli_result.exit_code == 2
    assert "unsupported" in cli_result.stdout
    assert "accepted" not in cli_result.stdout.lower()
    assert "rejected" not in cli_result.stdout.lower()
    assert "aborted" not in cli_result.stdout.lower()
    assert "cancel" not in cli_result.stdout.lower()

def test_mini_mas_continue_cli_outputs_continuation_dispatch(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.continue_agent_workflow",
        Mock(
            return_value={
                "ok": True,
                "output": (
                    "Continuation signal sent\n"
                    "agent_id: mas-3333333333333333\n"
                    "lifecycle_state: waiting_for_parent\n"
                    "message: go on\n"
                    "agent_artifact_directory: .mini-mas/agents/mas-3333333333333333\n"
                    "trajectory_artifact_path: .mini-mas/agents/mas-3333333333333333/trajectory.traj.json\n"
                ),
                "returncode": 0,
                "exception_info": "",
                "extra": {},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["continue", "mas-3333333333333333", "go on"])

    assert cli_result.exit_code == 0
    assert "Continuation signal sent" in cli_result.stdout
    assert "agent_id: mas-3333333333333333" in cli_result.stdout
    assert "message: go on" in cli_result.stdout

def test_mini_mas_close_cli_outputs_neutral_close_dispatch(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.close_agent_workflow",
        Mock(
            return_value={
                "ok": True,
                "output": (
                    "Close signal sent\n"
                    "agent_id: mas-3333333333333333\n"
                    "lifecycle_state: waiting_for_parent\n"
                    "latest_submission: ready\n"
                    "agent_artifact_directory: .mini-mas/agents/mas-3333333333333333\n"
                    "trajectory_artifact_path: .mini-mas/agents/mas-3333333333333333/trajectory.traj.json\n"
                ),
                "returncode": 0,
                "exception_info": "",
                "extra": {},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["close", "mas-3333333333333333"])

    assert cli_result.exit_code == 0
    assert "Close signal sent" in cli_result.stdout
    assert "agent_id: mas-3333333333333333" in cli_result.stdout
    assert "latest_submission: ready" in cli_result.stdout
    assert "accepted" not in cli_result.stdout.lower()
    assert "rejected" not in cli_result.stdout.lower()
    assert "aborted" not in cli_result.stdout.lower()
    assert "cancel" not in cli_result.stdout.lower()

@pytest.mark.parametrize("command", ["history", "logs", "grep"])
def test_mini_mas_does_not_add_dedicated_history_or_log_commands(command):
    cli_result = CliRunner().invoke(app, [command])

    assert cli_result.exit_code != 0
