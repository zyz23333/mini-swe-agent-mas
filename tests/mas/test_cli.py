from unittest.mock import Mock, call

import pytest
from typer.testing import CliRunner

from minisweagent.mas.cli import app


def test_plain_mini_mas_exits_on_eof_without_creating_interactive_root(monkeypatch):
    start_root = Mock(side_effect=AssertionError("EOF before effective input must not start a Root Agent"))
    send_root_command = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)

    cli_result = CliRunner().invoke(app, [], input="")

    assert cli_result.exit_code == 0
    assert cli_result.stdout == ""
    start_root.assert_not_called()
    send_root_command.assert_not_called()


@pytest.mark.parametrize("local_exit", ["exit", "quit"])
def test_plain_mini_mas_ignores_empty_input_then_exits_locally_before_root_creation(monkeypatch, local_exit):
    start_root = Mock(side_effect=AssertionError("local pre-root exit must not start a Root Agent"))
    send_root_command = Mock()
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(app, [], input=f"\n   \n{local_exit}\n")

    assert cli_result.exit_code == 0
    assert cli_result.stdout == ""
    start_root.assert_not_called()
    send_root_command.assert_not_called()
    release_attachment.assert_not_called()


def test_plain_mini_mas_lazily_creates_root_on_first_effective_command(monkeypatch):
    start_root = Mock(
        return_value={
            "agent_id": "mas-2222222222222222",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
        }
    )
    prepare_resume = Mock(
        return_value={
            "kind": "resume_ready",
            "root_agent_id": "mas-2222222222222222",
            "agent_id": "mas-2222222222222222",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
            "attachment_token": "att-1111111111111111",
            "returncode": 0,
        }
    )
    send_root_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-2222222222222222",
            "command": "echo hello",
            "result": {"output": "hello\n", "returncode": 0, "exception_info": "", "extra": {}},
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.prepare_resume_root_agent", prepare_resume)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(app, [], input="\n  \necho hello\n")

    assert cli_result.exit_code == 0
    assert cli_result.stdout.index("agent_id: mas-2222222222222222") < cli_result.stdout.index("hello\n")
    assert "lifecycle_state: waiting_for_command" in cli_result.stdout
    start_root.assert_called_once_with()
    prepare_resume.assert_called_once_with(root_agent_id="mas-2222222222222222")
    send_root_command.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        command="echo hello",
        result_timeout_seconds=60,
        attachment_token="att-1111111111111111",
    )
    release_attachment.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        attachment_token="att-1111111111111111",
    )


def test_plain_mini_mas_handles_pre_root_status_locally_then_stays_unbound(monkeypatch):
    start_root = Mock(side_effect=AssertionError("pre-root status must not create a Root Agent"))
    discover = Mock(
        return_value={
            "kind": "interactive_root_discovery",
            "roots": [],
            "output": "Interactive Root Agents\nNo Interactive Root Agents found.\n",
            "returncode": 0,
        }
    )
    send_root_command = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.discover_interactive_root_agents", discover)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)

    cli_result = CliRunner().invoke(app, [], input="  mini-mas status  \nquit\n")

    assert cli_result.exit_code == 0
    assert cli_result.stdout == "Interactive Root Agents\nNo Interactive Root Agents found.\n"
    discover.assert_called_once_with()
    start_root.assert_not_called()
    send_root_command.assert_not_called()


def test_plain_mini_mas_handles_pre_root_status_then_later_creates_root_for_work(monkeypatch):
    discover = Mock(
        return_value={
            "kind": "interactive_root_discovery",
            "roots": [],
            "output": "Interactive Root Agents\nNo Interactive Root Agents found.\n",
            "returncode": 0,
        }
    )
    start_root = Mock(
        return_value={
            "agent_id": "mas-2222222222222222",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
        }
    )
    monkeypatch.setattr(
        "minisweagent.mas.cli.prepare_resume_root_agent",
        Mock(
            return_value={
                "kind": "resume_ready",
                "root_agent_id": "mas-2222222222222222",
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
                "attachment_token": "att-1111111111111111",
                "returncode": 0,
            }
        ),
    )
    send_root_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-2222222222222222",
            "command": "  mini-mas status  ",
            "result": {"output": "inside-root status\n", "returncode": 0, "exception_info": "", "extra": {}},
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.discover_interactive_root_agents", discover)
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", Mock())

    cli_result = CliRunner().invoke(app, [], input="mini-mas status\necho hello\n")

    assert cli_result.exit_code == 0
    assert "Interactive Root Agents\nNo Interactive Root Agents found.\n" in cli_result.stdout
    assert "inside-root status\n" in cli_result.stdout
    discover.assert_called_once_with()
    start_root.assert_called_once_with()
    send_root_command.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        command="echo hello",
        result_timeout_seconds=60,
        attachment_token="att-1111111111111111",
    )


def test_plain_mini_mas_handles_successful_pre_root_resume_without_creating_new_root(monkeypatch):
    start_root = Mock(side_effect=AssertionError("pre-root resume must not create a new Root Agent"))
    prepare_resume = Mock(
        return_value={
            "kind": "resume_ready",
            "root_agent_id": "mas-2222222222222222",
            "agent_id": "mas-2222222222222222",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
            "attachment_token": "att-1111111111111111",
            "returncode": 0,
        }
    )
    send_root_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-2222222222222222",
            "command": "echo resumed",
            "result": {"output": "resumed\n", "returncode": 0, "exception_info": "", "extra": {}},
        }
    )
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.prepare_resume_root_agent", prepare_resume)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(app, [], input="mini-mas resume mas-2222222222222222\necho resumed\n")

    assert cli_result.exit_code == 0
    assert cli_result.stdout.index("agent_id: mas-2222222222222222") < cli_result.stdout.index("resumed\n")
    prepare_resume.assert_called_once_with(root_agent_id="mas-2222222222222222")
    start_root.assert_not_called()
    send_root_command.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        command="echo resumed",
        result_timeout_seconds=60,
        attachment_token="att-1111111111111111",
    )
    release_attachment.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        attachment_token="att-1111111111111111",
    )


def test_plain_mini_mas_handles_failed_pre_root_resume_then_stays_unbound(monkeypatch):
    start_root = Mock(
        return_value={
            "agent_id": "mas-3333333333333333",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-3333333333333333",
            "trajectory_artifact_path": ".mini-mas/agents/mas-3333333333333333/trajectory.traj.json",
        }
    )
    prepare_resume = Mock(
        side_effect=[
            {
                "kind": "resume_unavailable",
                "root_agent_id": "mas-2222222222222222",
                "output": (
                    "Unknown Root Agent ID: mas-2222222222222222\n"
                    "root_agent_id: mas-2222222222222222\n"
                    "lifecycle_state: unknown\n"
                    "Use mini-mas status to inspect Root Agents, then retry "
                    "mini-mas resume mas-2222222222222222 later.\n"
                ),
                "returncode": 2,
                "exception_info": "unknown_root_agent_id",
                "extra": {"mas_command_error": "unknown_root_agent_id"},
            },
            {
                "kind": "resume_ready",
                "root_agent_id": "mas-3333333333333333",
                "agent_id": "mas-3333333333333333",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-3333333333333333",
                "trajectory_artifact_path": ".mini-mas/agents/mas-3333333333333333/trajectory.traj.json",
                "attachment_token": "att-3333333333333333",
                "returncode": 0,
            },
        ]
    )
    send_root_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-3333333333333333",
            "command": "echo after failed resume",
            "result": {"output": "after failed resume\n", "returncode": 0, "exception_info": "", "extra": {}},
        }
    )
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.prepare_resume_root_agent", prepare_resume)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(
        app,
        [],
        input="mini-mas resume mas-2222222222222222\necho after failed resume\n",
    )

    assert cli_result.exit_code == 0
    assert "Unknown Root Agent ID: mas-2222222222222222" in cli_result.stdout
    assert "after failed resume\n" in cli_result.stdout
    start_root.assert_called_once_with()
    assert prepare_resume.call_args_list == [
        call(root_agent_id="mas-2222222222222222"),
        call(root_agent_id="mas-3333333333333333"),
    ]
    send_root_command.assert_called_once_with(
        root_agent_id="mas-3333333333333333",
        command="echo after failed resume",
        result_timeout_seconds=60,
        attachment_token="att-3333333333333333",
    )
    release_attachment.assert_called_once_with(
        root_agent_id="mas-3333333333333333",
        attachment_token="att-3333333333333333",
    )


def test_plain_mini_mas_routes_status_and_resume_through_root_after_lazy_attachment(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.start_interactive_root_agent_workflow",
        Mock(
            return_value={
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
            }
        ),
    )
    monkeypatch.setattr(
        "minisweagent.mas.cli.prepare_resume_root_agent",
        Mock(
            return_value={
                "kind": "resume_ready",
                "root_agent_id": "mas-2222222222222222",
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
                "attachment_token": "att-1111111111111111",
                "returncode": 0,
            }
        ),
    )
    discover = Mock(side_effect=AssertionError("attached status must not run local discovery"))
    send_root_command = Mock(
        side_effect=[
            {
                "kind": "root_command_result",
                "command_id": "cmd-1111111111111111",
                "root_agent_id": "mas-2222222222222222",
                "command": "echo attach",
                "result": {"output": "attached\n", "returncode": 0, "exception_info": "", "extra": {}},
            },
            {
                "kind": "root_command_result",
                "command_id": "cmd-2222222222222222",
                "root_agent_id": "mas-2222222222222222",
                "command": "mini-mas status",
                "result": {"output": "root status\n", "returncode": 0, "exception_info": "", "extra": {}},
            },
            {
                "kind": "root_command_result",
                "command_id": "cmd-3333333333333333",
                "root_agent_id": "mas-2222222222222222",
                "command": "mini-mas resume mas-3333333333333333",
                "result": {"output": "root resume\n", "returncode": 0, "exception_info": "", "extra": {}},
            },
        ]
    )
    monkeypatch.setattr("minisweagent.mas.cli.discover_interactive_root_agents", discover)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", Mock())

    cli_result = CliRunner().invoke(
        app,
        [],
        input="echo attach\nmini-mas status\nmini-mas resume mas-3333333333333333\n",
    )

    assert cli_result.exit_code == 0
    assert "attached\n" in cli_result.stdout
    assert "root status\n" in cli_result.stdout
    assert "root resume\n" in cli_result.stdout
    assert [command_call.kwargs["command"] for command_call in send_root_command.call_args_list] == [
        "echo attach",
        "mini-mas status",
        "mini-mas resume mas-3333333333333333",
    ]


def test_plain_mini_mas_detaches_locally_on_exit_after_lazy_root_without_sending_exit(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.start_interactive_root_agent_workflow",
        Mock(
            return_value={
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
            }
        ),
    )
    monkeypatch.setattr(
        "minisweagent.mas.cli.prepare_resume_root_agent",
        Mock(
            return_value={
                "kind": "resume_ready",
                "root_agent_id": "mas-2222222222222222",
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
                "attachment_token": "att-1111111111111111",
                "returncode": 0,
            }
        ),
    )
    send_root_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-2222222222222222",
            "command": "echo hello",
            "result": {"output": "hello\n", "returncode": 0, "exception_info": "", "extra": {}},
        }
    )
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(app, [], input="echo hello\nexit\n")

    assert cli_result.exit_code == 0
    assert "hello\n" in cli_result.stdout
    send_root_command.assert_called_once()
    release_attachment.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        attachment_token="att-1111111111111111",
    )


def test_plain_mini_mas_keeps_attached_after_nonzero_result_and_exits_with_last_returncode(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.start_interactive_root_agent_workflow",
        Mock(
            return_value={
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
            }
        ),
    )
    monkeypatch.setattr(
        "minisweagent.mas.cli.prepare_resume_root_agent",
        Mock(
            return_value={
                "kind": "resume_ready",
                "root_agent_id": "mas-2222222222222222",
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
                "attachment_token": "att-1111111111111111",
                "returncode": 0,
            }
        ),
    )
    send_root_command = Mock(
        side_effect=[
            {
                "kind": "root_command_result",
                "command_id": "cmd-1111111111111111",
                "root_agent_id": "mas-2222222222222222",
                "command": "false",
                "result": {"output": "failed\n", "returncode": 7, "exception_info": "failed", "extra": {}},
            },
            {
                "kind": "root_command_result",
                "command_id": "cmd-2222222222222222",
                "root_agent_id": "mas-2222222222222222",
                "command": "echo after",
                "result": {"output": "after\n", "returncode": 3, "exception_info": "after", "extra": {}},
            },
        ]
    )
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", Mock())

    cli_result = CliRunner().invoke(app, [], input="false\necho after\n")

    assert cli_result.exit_code == 3
    assert "failed\n" in cli_result.stdout
    assert "after\n" in cli_result.stdout
    assert send_root_command.call_count == 2


def test_plain_mini_mas_lazy_root_creation_failure_exits_visibly(monkeypatch):
    start_root = Mock(side_effect=RuntimeError("database unavailable"))
    send_root_command = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)

    cli_result = CliRunner().invoke(app, [], input="echo hello\n")

    assert cli_result.exit_code == 1
    assert "Failed to create Interactive Root Agent" in cli_result.stdout
    assert "database unavailable" in cli_result.stdout
    send_root_command.assert_not_called()


def test_mini_mas_help_presents_first_version_root_cli_surface_without_legacy_commands():
    cli_result = CliRunner().invoke(app, ["--help"])

    assert cli_result.exit_code == 0
    assert "Interactive Root Agent" in cli_result.stdout
    assert "mini-mas" in cli_result.stdout
    assert "spawn" in cli_result.stdout
    assert "status" in cli_result.stdout
    assert "resume" in cli_result.stdout
    assert "run" not in cli_result.stdout
    assert "command" not in cli_result.stdout
    assert "wait" not in cli_result.stdout
    assert "continue" not in cli_result.stdout
    assert "close" not in cli_result.stdout
    assert "close-root" not in cli_result.stdout
    assert "run ID" not in cli_result.stdout
    assert "cleanup" not in cli_result.stdout.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["status", "--help"],
        ["spawn", "--help"],
        ["resume", "--help"],
    ],
)
def test_mini_mas_help_does_not_expose_system_database_configuration(argv):
    cli_result = CliRunner().invoke(app, argv)

    assert cli_result.exit_code == 0
    assert "--system-database-url" not in cli_result.stdout
    assert "system_database_url" not in cli_result.stdout
    assert "DBOS_SYSTEM_DATABASE_URL" not in cli_result.stdout
    assert "database URL" not in cli_result.stdout
    assert "connection string" not in cli_result.stdout


@pytest.mark.parametrize(
    "argv",
    [
        ["--system-database-url", "postgres://db"],
        ["status", "--system-database-url", "postgres://db"],
        ["spawn", "--system-database-url", "postgres://db", "task A"],
        ["resume", "mas-2222222222222222", "--system-database-url", "postgres://db"],
    ],
)
def test_mini_mas_does_not_accept_system_database_url_as_user_facing_option(argv, monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.start_interactive_root_agent_workflow",
        Mock(side_effect=AssertionError("removed database options must fail before runtime calls")),
    )
    monkeypatch.setattr(
        "minisweagent.mas.cli.discover_interactive_root_agents",
        Mock(side_effect=AssertionError("removed database options must fail before runtime calls")),
    )
    monkeypatch.setattr(
        "minisweagent.mas.cli.one_shot_spawn_through_interactive_root",
        Mock(side_effect=AssertionError("removed database options must fail before runtime calls")),
    )
    monkeypatch.setattr(
        "minisweagent.mas.cli.prepare_resume_root_agent",
        Mock(side_effect=AssertionError("removed database options must fail before runtime calls")),
    )

    cli_result = CliRunner().invoke(app, argv, input="")

    assert cli_result.exit_code != 0


def test_mini_mas_status_cli_lists_interactive_root_agents(monkeypatch):
    discover = Mock(
        return_value={
            "kind": "interactive_root_discovery",
            "roots": [
                {
                    "agent_id": "mas-2222222222222222",
                    "lifecycle_state": "waiting_for_command",
                    "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                    "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
                },
                {
                    "agent_id": "mas-3333333333333333",
                    "lifecycle_state": "failed",
                    "agent_artifact_directory": ".mini-mas/agents/mas-3333333333333333",
                    "trajectory_artifact_path": ".mini-mas/agents/mas-3333333333333333/trajectory.traj.json",
                },
            ],
            "output": (
                "Interactive Root Agents\n"
                "\n"
                "agent_id: mas-2222222222222222\n"
                "lifecycle_state: waiting_for_command\n"
                "agent_artifact_directory: .mini-mas/agents/mas-2222222222222222\n"
                "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json\n"
                "\n"
                "agent_id: mas-3333333333333333\n"
                "lifecycle_state: failed\n"
                "agent_artifact_directory: .mini-mas/agents/mas-3333333333333333\n"
                "trajectory_artifact_path: .mini-mas/agents/mas-3333333333333333/trajectory.traj.json\n"
            ),
            "returncode": 0,
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.discover_interactive_root_agents", discover)

    cli_result = CliRunner().invoke(app, ["status"])

    assert cli_result.exit_code == 0
    assert "Interactive Root Agents" in cli_result.stdout
    assert "agent_id: mas-2222222222222222" in cli_result.stdout
    assert "lifecycle_state: waiting_for_command" in cli_result.stdout
    assert "agent_id: mas-3333333333333333" in cli_result.stdout
    assert "lifecycle_state: failed" in cli_result.stdout
    assert "Child Agent" not in cli_result.stdout
    assert "latest_" not in cli_result.stdout
    discover.assert_called_once_with()


def test_mini_mas_status_with_agent_id_is_not_a_supported_external_lookup():
    cli_result = CliRunner().invoke(app, ["status", "mas-2222222222222222"])

    assert cli_result.exit_code != 0
    assert "Unsupported external MAS governance command" in cli_result.output
    assert "mini-mas status" in cli_result.output
    assert "mini-mas resume <root-agent-id>" in cli_result.output


def test_mini_mas_command_is_not_a_supported_external_bypass():
    cli_result = CliRunner().invoke(app, ["command", "mas-2222222222222222", "echo hello"])

    assert cli_result.exit_code != 0
    assert "Unsupported external MAS governance command" in cli_result.output
    assert "mini-mas status" in cli_result.output
    assert "mini-mas resume <root-agent-id>" in cli_result.output


def test_mini_mas_spawn_creates_root_sends_preserved_spawn_command_and_prints_child_metadata(monkeypatch):
    one_shot_spawn = Mock(
        return_value={
            "kind": "one_shot_spawn",
            "root_agent_id": "mas-1111111111111111",
            "command": "mini-mas spawn 'task A'",
            "result": {
                "output": (
                    "Detached spawn started\n"
                    "child_count: 1\n"
                    "task: task A\n"
                    "agent_id: mas-2222222222222222\n"
                    "parent_agent_id: mas-1111111111111111\n"
                    "agent_artifact_directory: .mini-mas/agents/mas-2222222222222222\n"
                    "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json\n"
                ),
                "returncode": 0,
                "exception_info": "",
                "extra": {
                    "children": [
                        {
                            "task": "task A",
                            "agent_id": "mas-2222222222222222",
                            "parent_agent_id": "mas-1111111111111111",
                            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                            "trajectory_artifact_path": (".mini-mas/agents/mas-2222222222222222/trajectory.traj.json"),
                        }
                    ],
                },
            },
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.one_shot_spawn_through_interactive_root", one_shot_spawn)

    cli_result = CliRunner().invoke(app, ["spawn", "task A"])

    assert cli_result.exit_code == 0
    assert "root_agent_id: mas-1111111111111111" in cli_result.stdout
    assert "agent_id: mas-2222222222222222" in cli_result.stdout
    assert "parent_agent_id: mas-1111111111111111" in cli_result.stdout
    assert "agent_artifact_directory: .mini-mas/agents/mas-2222222222222222" in cli_result.stdout
    assert "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json" in cli_result.stdout
    assert ".mini-mas/agents/mas-1111111111111111" not in cli_result.stdout
    one_shot_spawn.assert_called_once_with(
        spawn_arguments=["task A"],
        result_timeout_seconds=60,
    )


def test_mini_mas_multi_spawn_prints_one_root_id_and_each_child(monkeypatch):
    one_shot_spawn = Mock(
        return_value={
            "kind": "one_shot_spawn",
            "root_agent_id": "mas-1111111111111111",
            "command": "mini-mas spawn 'task A' 'task B'",
            "result": {
                "output": (
                    "Detached spawn started\n"
                    "child_count: 2\n"
                    "task: task A\n"
                    "agent_id: mas-2222222222222222\n"
                    "parent_agent_id: mas-1111111111111111\n"
                    "agent_artifact_directory: .mini-mas/agents/mas-2222222222222222\n"
                    "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json\n"
                    "\n"
                    "task: task B\n"
                    "agent_id: mas-3333333333333333\n"
                    "parent_agent_id: mas-1111111111111111\n"
                    "agent_artifact_directory: .mini-mas/agents/mas-3333333333333333\n"
                    "trajectory_artifact_path: .mini-mas/agents/mas-3333333333333333/trajectory.traj.json\n"
                ),
                "returncode": 0,
                "exception_info": "",
                "extra": {"child_agent_ids": ["mas-2222222222222222", "mas-3333333333333333"]},
            },
            "returncode": 0,
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.one_shot_spawn_through_interactive_root", one_shot_spawn)

    cli_result = CliRunner().invoke(app, ["spawn", "task A", "task B"])

    assert cli_result.exit_code == 0
    assert cli_result.stdout.count("root_agent_id: mas-1111111111111111") == 1
    assert "agent_id: mas-2222222222222222" in cli_result.stdout
    assert "agent_id: mas-3333333333333333" in cli_result.stdout
    assert cli_result.stdout.index("task: task A") < cli_result.stdout.index("task: task B")
    assert cli_result.stdout.index("agent_id: mas-2222222222222222") < cli_result.stdout.index(
        "agent_id: mas-3333333333333333"
    )
    assert cli_result.stdout.count("parent_agent_id: mas-1111111111111111") == 2
    assert "spawn_index" not in cli_result.stdout
    assert "sibling_index" not in cli_result.stdout
    assert "task_position" not in cli_result.stdout
    assert "result_order" not in cli_result.stdout
    one_shot_spawn.assert_called_once_with(
        spawn_arguments=["task A", "task B"],
        result_timeout_seconds=60,
    )


def test_mini_mas_spawn_wait_options_are_preserved_as_mas_wait_options(monkeypatch):
    one_shot_spawn = Mock(
        return_value={
            "kind": "one_shot_spawn",
            "root_agent_id": "mas-1111111111111111",
            "command": "mini-mas spawn --wait --all --timeout 0.5 'task A' 'task B'",
            "result": {
                "output": (
                    "Waited spawn timed out\n"
                    "wait_mode: all\n"
                    "child_count: 2\n"
                    "ready_child_count: 1\n"
                    "still_running_child_agent_ids: mas-3333333333333333\n"
                    "\n"
                    "started_children:\n"
                    "task: task A\n"
                    "agent_id: mas-2222222222222222\n"
                    "parent_agent_id: mas-1111111111111111\n"
                    "agent_artifact_directory: .mini-mas/agents/mas-2222222222222222\n"
                    "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json\n"
                    "\n"
                    "task: task B\n"
                    "agent_id: mas-3333333333333333\n"
                    "parent_agent_id: mas-1111111111111111\n"
                    "agent_artifact_directory: .mini-mas/agents/mas-3333333333333333\n"
                    "trajectory_artifact_path: .mini-mas/agents/mas-3333333333333333/trajectory.traj.json\n"
                    "\n"
                    "ready_children:\n"
                    "ready_agent_id: mas-2222222222222222\n"
                    "lifecycle_state: waiting_for_parent\n"
                    "latest_submission: ready\n"
                    "agent_artifact_directory: .mini-mas/agents/mas-2222222222222222\n"
                    "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json\n"
                ),
                "returncode": 0,
                "exception_info": "",
                "extra": {
                    "waited": True,
                    "wait_mode": "all",
                    "timed_out": True,
                    "ready_children": [{"agent_id": "mas-2222222222222222"}],
                    "still_running_child_agent_ids": ["mas-3333333333333333"],
                },
            },
            "returncode": 0,
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.one_shot_spawn_through_interactive_root", one_shot_spawn)

    cli_result = CliRunner().invoke(
        app,
        ["spawn", "--result-timeout", "7", "--wait", "--all", "--timeout", "0.5", "task A", "task B"],
    )

    assert cli_result.exit_code == 0
    assert "root_agent_id: mas-1111111111111111" in cli_result.stdout
    assert "Waited spawn timed out" in cli_result.stdout
    assert "wait_mode: all" in cli_result.stdout
    assert "ready_agent_id: mas-2222222222222222" in cli_result.stdout
    assert "still_running_child_agent_ids: mas-3333333333333333" in cli_result.stdout
    one_shot_spawn.assert_called_once_with(
        spawn_arguments=["--wait", "--all", "--timeout", "0.5", "task A", "task B"],
        result_timeout_seconds=7,
    )


def test_mini_mas_spawn_timeout_reports_resumable_root_without_canceling_children(monkeypatch):
    one_shot_spawn = Mock(
        return_value={
            "kind": "one_shot_spawn_result_timeout",
            "root_agent_id": "mas-1111111111111111",
            "command": "mini-mas spawn 'task A'",
            "output": (
                "Timed out waiting for Root Command Result. The spawn command may still be running.\n"
                "root_agent_id: mas-1111111111111111\n"
                "Use mini-mas status to inspect Root Agents, then resume this Root Agent with "
                "mini-mas resume mas-1111111111111111.\n"
            ),
            "returncode": 1,
            "exception_info": "root_command_result_timeout",
            "extra": {"mas_command_error": "root_command_result_timeout"},
            "result": {
                "output": "Timed out waiting for Root Command Result.\n",
                "returncode": 1,
                "exception_info": "root_command_result_timeout",
                "extra": {"mas_command_error": "root_command_result_timeout"},
            },
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.one_shot_spawn_through_interactive_root", one_shot_spawn)

    cli_result = CliRunner().invoke(app, ["spawn", "--result-timeout", "0.01", "task A"])

    assert cli_result.exit_code == 1
    assert "may still be running" in cli_result.stdout
    assert "root_agent_id: mas-1111111111111111" in cli_result.stdout
    assert "mini-mas status" in cli_result.stdout
    assert "mini-mas resume mas-1111111111111111" in cli_result.stdout
    assert "cancel" not in cli_result.stdout.lower()
    assert "mark" not in cli_result.stdout.lower()
    one_shot_spawn.assert_called_once_with(
        spawn_arguments=["task A"],
        result_timeout_seconds=0.01,
    )


def test_mini_mas_spawn_timeout_without_wait_fails_before_starting_root(monkeypatch):
    one_shot_spawn = Mock(side_effect=AssertionError("invalid external spawn arguments must not start a Root Agent"))
    monkeypatch.setattr("minisweagent.mas.cli.one_shot_spawn_through_interactive_root", one_shot_spawn)

    cli_result = CliRunner().invoke(app, ["spawn", "--timeout", "1", "task"])

    assert cli_result.exit_code == 2
    assert "Detached Spawn has no wait phase" in cli_result.stdout
    one_shot_spawn.assert_not_called()


def test_mini_mas_resume_prints_metadata_once_and_sends_each_input_line(monkeypatch):
    prepare_resume = Mock(
        return_value={
            "kind": "resume_ready",
            "root_agent_id": "mas-2222222222222222",
            "agent_id": "mas-2222222222222222",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
            "attachment_token": "att-1111111111111111",
            "returncode": 0,
        }
    )
    send_root_command = Mock(
        side_effect=[
            {
                "kind": "root_command_result",
                "command_id": "cmd-1111111111111111",
                "root_agent_id": "mas-2222222222222222",
                "command": "echo hello",
                "result": {"output": "hello\n", "returncode": 0, "exception_info": "", "extra": {}},
            },
            {
                "kind": "root_command_result",
                "command_id": "cmd-2222222222222222",
                "root_agent_id": "mas-2222222222222222",
                "command": "mini-mas status",
                "result": {"output": "status output\n", "returncode": 0, "exception_info": "", "extra": {}},
            },
        ]
    )
    monkeypatch.setattr("minisweagent.mas.cli.prepare_resume_root_agent", prepare_resume)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(
        app,
        ["resume", "mas-2222222222222222"],
        input="echo hello\nmini-mas status\n",
    )

    assert cli_result.exit_code == 0
    assert cli_result.stdout.count("agent_id: mas-2222222222222222") == 1
    assert "lifecycle_state: waiting_for_command" in cli_result.stdout
    assert "hello\n" in cli_result.stdout
    assert "status output\n" in cli_result.stdout
    prepare_resume.assert_called_once_with(root_agent_id="mas-2222222222222222")
    assert send_root_command.call_args_list == [
        call(
            root_agent_id="mas-2222222222222222",
            command="echo hello",
            result_timeout_seconds=60,
            attachment_token="att-1111111111111111",
        ),
        call(
            root_agent_id="mas-2222222222222222",
            command="mini-mas status",
            result_timeout_seconds=60,
            attachment_token="att-1111111111111111",
        ),
    ]
    release_attachment.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        attachment_token="att-1111111111111111",
    )


def test_mini_mas_resume_sends_prefix_free_input_as_ordinary_bash_without_rewriting(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.prepare_resume_root_agent",
        Mock(
            return_value={
                "kind": "resume_ready",
                "root_agent_id": "mas-2222222222222222",
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
                "attachment_token": "att-1111111111111111",
                "returncode": 0,
            }
        ),
    )
    send_root_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-2222222222222222",
            "command": "status",
            "result": {"output": "bash status output\n", "returncode": 0, "exception_info": "", "extra": {}},
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(app, ["resume", "mas-2222222222222222"], input="status\n")

    assert cli_result.exit_code == 0
    assert "bash status output\n" in cli_result.stdout
    send_root_command.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        command="status",
        result_timeout_seconds=60,
        attachment_token="att-1111111111111111",
    )
    release_attachment.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        attachment_token="att-1111111111111111",
    )


def test_mini_mas_resume_exits_with_last_command_returncode(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.prepare_resume_root_agent",
        Mock(
            return_value={
                "kind": "resume_ready",
                "root_agent_id": "mas-2222222222222222",
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
                "attachment_token": "att-1111111111111111",
                "returncode": 0,
            }
        ),
    )
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    monkeypatch.setattr(
        "minisweagent.mas.cli.send_root_command",
        Mock(
            return_value={
                "kind": "root_command_result",
                "command_id": "cmd-1111111111111111",
                "root_agent_id": "mas-2222222222222222",
                "command": "false",
                "result": {"output": "failed\n", "returncode": 7, "exception_info": "failed", "extra": {}},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["resume", "mas-2222222222222222"], input="false\n")

    assert cli_result.exit_code == 7
    assert "failed\n" in cli_result.stdout


def test_mini_mas_resume_keeps_terminal_attached_after_nonzero_command(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.prepare_resume_root_agent",
        Mock(
            return_value={
                "kind": "resume_ready",
                "root_agent_id": "mas-2222222222222222",
                "agent_id": "mas-2222222222222222",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
                "attachment_token": "att-1111111111111111",
                "returncode": 0,
            }
        ),
    )
    send_root_command = Mock(
        side_effect=[
            {
                "kind": "root_command_result",
                "command_id": "cmd-1111111111111111",
                "root_agent_id": "mas-2222222222222222",
                "command": "false",
                "result": {"output": "failed\n", "returncode": 7, "exception_info": "failed", "extra": {}},
            },
            {
                "kind": "root_command_result",
                "command_id": "cmd-2222222222222222",
                "root_agent_id": "mas-2222222222222222",
                "command": "echo recovered",
                "result": {"output": "recovered\n", "returncode": 0, "exception_info": "", "extra": {}},
            },
        ]
    )
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(
        app,
        ["resume", "mas-2222222222222222"],
        input="false\necho recovered\n",
    )

    assert cli_result.exit_code == 0
    assert "failed\n" in cli_result.stdout
    assert "recovered\n" in cli_result.stdout
    assert send_root_command.call_count == 2
    release_attachment.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        attachment_token="att-1111111111111111",
    )


def test_mini_mas_resume_prints_unavailable_error_without_entering_terminal(monkeypatch):
    prepare_resume = Mock(
        return_value={
            "kind": "resume_unavailable",
            "root_agent_id": "mas-2222222222222222",
            "output": (
                "Root Agent is not available for resume.\n"
                "root_agent_id: mas-2222222222222222\n"
                "lifecycle_state: running\n"
                "Use mini-mas status to inspect Root Agents, then retry "
                "mini-mas resume mas-2222222222222222 later when it is waiting_for_command.\n"
            ),
            "returncode": 2,
            "exception_info": "root_agent_not_waiting_for_command",
            "extra": {"mas_command_error": "root_agent_not_waiting_for_command"},
        }
    )
    send_root_command = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.prepare_resume_root_agent", prepare_resume)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)

    cli_result = CliRunner().invoke(app, ["resume", "mas-2222222222222222"], input="echo ignored\n")

    assert cli_result.exit_code == 2
    assert "root_agent_id: mas-2222222222222222" in cli_result.stdout
    assert "lifecycle_state: running" in cli_result.stdout
    assert "mini-mas status" in cli_result.stdout
    assert "mini-mas resume mas-2222222222222222" in cli_result.stdout
    send_root_command.assert_not_called()


def test_mini_mas_resume_detaches_on_eof_without_sending_close_or_using_prompt_history(monkeypatch):
    prepare_resume = Mock(
        return_value={
            "kind": "resume_ready",
            "root_agent_id": "mas-2222222222222222",
            "agent_id": "mas-2222222222222222",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
            "attachment_token": "att-1111111111111111",
            "returncode": 0,
        }
    )
    send_root_command = Mock()
    prompt_history_prompt = Mock(side_effect=AssertionError("resume must not use prompt history"))
    monkeypatch.setattr("minisweagent.mas.cli.prepare_resume_root_agent", prepare_resume)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)
    monkeypatch.setattr("minisweagent.agents.utils.prompt_user.prompt_session.prompt", prompt_history_prompt)

    cli_result = CliRunner().invoke(app, ["resume", "mas-2222222222222222"], input="")

    assert cli_result.exit_code == 0
    assert "agent_id: mas-2222222222222222" in cli_result.stdout
    send_root_command.assert_not_called()
    prompt_history_prompt.assert_not_called()
    release_attachment.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        attachment_token="att-1111111111111111",
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["run"],
        ["wait", "mas-3333333333333333"],
        ["continue", "mas-3333333333333333", "go on"],
        ["close", "mas-3333333333333333"],
    ],
)
def test_external_legacy_and_governance_commands_are_not_supported_bypasses(argv):
    cli_result = CliRunner().invoke(app, argv)

    assert cli_result.exit_code != 0
    assert "Unsupported external MAS" in cli_result.output
    assert "mini-mas status" in cli_result.output
    assert "mini-mas resume <root-agent-id>" in cli_result.output
    assert "Root Agent closure" not in cli_result.output
    assert "cleanup" not in cli_result.output.lower()
    assert "run ID" not in cli_result.output
    assert "Root index" not in cli_result.output


def test_mini_mas_does_not_add_close_root_command():
    cli_result = CliRunner().invoke(app, ["close-root", "mas-3333333333333333"])

    assert cli_result.exit_code != 0
    assert "No such command" in cli_result.output
    assert "Root Agent closure" not in cli_result.output
    assert "cleanup" not in cli_result.output.lower()
    assert "run ID" not in cli_result.output
    assert "Root index" not in cli_result.output


@pytest.mark.parametrize("command", ["history", "logs", "grep"])
def test_mini_mas_does_not_add_dedicated_history_or_log_commands(command):
    cli_result = CliRunner().invoke(app, [command])

    assert cli_result.exit_code != 0
