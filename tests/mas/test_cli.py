from unittest.mock import Mock, call, patch

import pytest
from typer.testing import CliRunner

from minisweagent.mas.cli import app

from .helpers import (
    AsyncMockHandle,
    _mock_dbos_module,
)


def test_plain_mini_mas_creates_interactive_root_and_prints_metadata_banner():
    handle = AsyncMockHandle("mas-2222222222222222")

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        patch("minisweagent.mas.runtime.make_agent_id", return_value="mas-2222222222222222"),
    ):
        cli_result = CliRunner().invoke(app, [])

    assert cli_result.exit_code == 0
    assert "agent_id: mas-2222222222222222" in cli_result.stdout
    assert "lifecycle_state: waiting_for_command" in cli_result.stdout
    assert "agent_artifact_directory: .mini-mas/agents/mas-2222222222222222" in cli_result.stdout
    assert (
        "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json"
        in cli_result.stdout
    )

    workflow_func = dbos_module.DBOS.start_workflow_async.call_args.args[0]
    assert workflow_func.__name__ == "interactive_root_agent_workflow"
    assert dbos_module.DBOS.start_workflow_async.call_args.args[1] == "mas-2222222222222222"
    assert dbos_module.DBOS.start_workflow_async.call_args.kwargs == {"max_commands": None}


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
    discover.assert_called_once_with(system_database_url=None)


def test_mini_mas_status_cli_with_agent_id_keeps_external_agent_interaction_unsupported(monkeypatch):
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


def test_mini_mas_command_cli_sends_root_command_and_prints_result(monkeypatch):
    root_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-2222222222222222",
            "command": "echo hello",
            "result": {
                "output": "hello\n",
                "returncode": 0,
                "exception_info": "",
                "extra": {},
            },
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", root_command)

    cli_result = CliRunner().invoke(app, ["command", "mas-2222222222222222", "echo hello"])

    assert cli_result.exit_code == 0
    assert cli_result.stdout == "hello\n"
    root_command.assert_called_once_with(
        root_agent_id="mas-2222222222222222",
        command="echo hello",
        result_timeout_seconds=60,
        system_database_url=None,
    )


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
                            "trajectory_artifact_path": (
                                ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json"
                            ),
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
    assert (
        "trajectory_artifact_path: .mini-mas/agents/mas-2222222222222222/trajectory.traj.json"
        in cli_result.stdout
    )
    assert ".mini-mas/agents/mas-1111111111111111" not in cli_result.stdout
    one_shot_spawn.assert_called_once_with(
        spawn_arguments=["task A"],
        result_timeout_seconds=60,
        system_database_url=None,
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
        system_database_url=None,
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
        system_database_url=None,
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
        system_database_url=None,
    )


def test_mini_mas_spawn_timeout_without_wait_remains_invalid_through_root_command(monkeypatch):
    one_shot_spawn = Mock(
        return_value={
            "kind": "one_shot_spawn",
            "root_agent_id": "mas-1111111111111111",
            "command": "mini-mas spawn --timeout 1 task",
            "result": {
                "output": "mini-mas spawn --timeout requires --wait because Detached Spawn has no wait phase\n",
                "returncode": 2,
                "exception_info": "invalid_mas_command",
                "extra": {"mas_command_error": "invalid_mas_command"},
            },
            "returncode": 2,
        }
    )
    monkeypatch.setattr("minisweagent.mas.cli.one_shot_spawn_through_interactive_root", one_shot_spawn)

    cli_result = CliRunner().invoke(app, ["spawn", "--timeout", "1", "task"])

    assert cli_result.exit_code == 2
    assert "Detached Spawn has no wait phase" in cli_result.stdout
    one_shot_spawn.assert_called_once_with(
        spawn_arguments=["--timeout", "1", "task"],
        result_timeout_seconds=60,
        system_database_url=None,
    )


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
    prepare_resume.assert_called_once_with(root_agent_id="mas-2222222222222222", system_database_url=None)
    assert send_root_command.call_args_list == [
        call(
            root_agent_id="mas-2222222222222222",
            command="echo hello",
            result_timeout_seconds=60,
            system_database_url=None,
            attachment_token="att-1111111111111111",
        ),
        call(
            root_agent_id="mas-2222222222222222",
            command="mini-mas status",
            result_timeout_seconds=60,
            system_database_url=None,
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
        system_database_url=None,
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
