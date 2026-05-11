import inspect
from unittest.mock import Mock, call, patch

import pytest

from minisweagent.mas.cli import run
from minisweagent.mas.runtime import (
    close_agent_workflow,
    continue_agent_workflow,
    discover_interactive_root_agents,
    get_agent_workflow_status,
    make_standalone_spawn_command,
    one_shot_spawn_through_interactive_root,
    prepare_resume_root_agent,
    release_root_attachment,
    send_root_command,
    start_interactive_root_agent_workflow,
    wait_for_agent_workflow,
)

from .helpers import (
    AsyncMockHandle,
    _mock_dbos_module,
    _workflow_status_record,
)


def test_mini_mas_run_initializes_launches_and_starts_root_workflow():
    """mini-mas run is the external path that activates DBOS for MAS work."""
    handle = AsyncMockHandle(
        "mas-1111111111111111",
        {
            "agent_id": "mas-1111111111111111",
            "status": "started",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        },
    )

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)
    dbos_module.DBOS.start_workflow.side_effect = AssertionError("MAS runtime must use start_workflow_async")

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = run(workflow_id="mas-1111111111111111", wait=True)

    dbos_module.DBOS.assert_called_once_with(
        config={
            "name": "mini-swe-agent-mas",
            "system_database_url": None,
        }
    )
    dbos_module.DBOS.launch.assert_called_once_with()
    dbos_module.SetWorkflowID.assert_called_once_with("mas-1111111111111111")
    dbos_module.DBOS.start_workflow.assert_not_called()
    dbos_module.DBOS.start_workflow_async.assert_called_once()

    workflow_func = dbos_module.DBOS.start_workflow_async.call_args.args[0]
    assert inspect.iscoroutinefunction(workflow_func)
    assert workflow_func.__name__ == "root_agent_workflow"
    assert dbos_module.DBOS.start_workflow_async.call_args.args[1] == "mas-1111111111111111"
    assert result == {
        "agent_id": "mas-1111111111111111",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        "result": {
            "agent_id": "mas-1111111111111111",
            "status": "started",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        },
    }

def test_mini_mas_run_returns_detached_metadata_without_waiting_for_result():
    handle = AsyncMockHandle(
        "mas-1111111111111111",
        {
            "agent_id": "mas-1111111111111111",
            "status": "started",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        },
    )

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = run(workflow_id="mas-1111111111111111", wait=False)

    dbos_module.DBOS.start_workflow_async.assert_called_once()
    assert result == {
        "agent_id": "mas-1111111111111111",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
    }


def test_plain_mini_mas_runtime_starts_interactive_root_workflow_and_waits_for_idle_metadata():
    handle = AsyncMockHandle("mas-1111111111111111")

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)
    dbos_module.DBOS.start_workflow.side_effect = AssertionError("MAS runtime must use start_workflow_async")

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = start_interactive_root_agent_workflow(workflow_id="mas-1111111111111111")

    dbos_module.DBOS.assert_called_once_with(
        config={
            "name": "mini-swe-agent-mas",
            "system_database_url": None,
        }
    )
    dbos_module.DBOS.launch.assert_called_once_with()
    dbos_module.SetWorkflowID.assert_called_once_with("mas-1111111111111111")
    dbos_module.DBOS.start_workflow.assert_not_called()
    dbos_module.DBOS.start_workflow_async.assert_called_once()

    workflow_func = dbos_module.DBOS.start_workflow_async.call_args.args[0]
    assert inspect.iscoroutinefunction(workflow_func)
    assert workflow_func.__name__ == "interactive_root_agent_workflow"
    assert dbos_module.DBOS.start_workflow_async.call_args.args[1] == "mas-1111111111111111"
    assert dbos_module.DBOS.start_workflow_async.call_args.kwargs == {"max_commands": None}
    dbos_module.DBOS.get_event_async.assert_called_once_with("mas-1111111111111111", "mini_mas_status", 60)
    assert result == {
        "agent_id": "mas-1111111111111111",
        "lifecycle_state": "waiting_for_command",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
    }


def test_runtime_sends_root_command_signal_and_waits_for_matching_command_result(tmp_path, monkeypatch):
    monkeypatch.setenv("MINI_MAS_ATTACHMENT_LEASE_DIR", str(tmp_path))
    sent = []

    async def send_async(destination_id, message, topic=None):
        sent.append((destination_id, message, topic))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        if key == "mini_mas_status":
            return {
                "agent_id": workflow_id,
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
            }
        return {
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": workflow_id,
            "command": "echo hello",
            "result": {
                "output": "hello\n",
                "returncode": 0,
                "exception_info": "",
                "extra": {},
            },
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.send_async = Mock(side_effect=send_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        patch("minisweagent.mas.runtime.make_command_id", return_value="cmd-1111111111111111"),
    ):
        result = send_root_command(
            root_agent_id="mas-1111111111111111",
            command="echo hello",
            result_timeout_seconds=3,
        )

    from minisweagent.mas.signals import ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX, ROOT_COMMAND_TOPIC

    dbos_module.DBOS.assert_called_once_with(
        config={
            "name": "mini-swe-agent-mas",
            "system_database_url": None,
        }
    )
    dbos_module.DBOS.launch.assert_called_once_with()
    assert sent == [
        (
            "mas-1111111111111111",
            {
                "kind": "root_command",
                "command_id": "cmd-1111111111111111",
                "root_agent_id": "mas-1111111111111111",
                "command": "echo hello",
                "source": "external_cli",
            },
            ROOT_COMMAND_TOPIC,
        )
    ]
    assert dbos_module.DBOS.get_event_async.call_args_list[-1] == call(
        "mas-1111111111111111",
        f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-1111111111111111",
        3,
    )
    assert result == {
        "kind": "root_command_result",
        "command_id": "cmd-1111111111111111",
        "root_agent_id": "mas-1111111111111111",
        "command": "echo hello",
        "result": {
            "output": "hello\n",
            "returncode": 0,
            "exception_info": "",
            "extra": {},
        },
    }


def test_one_shot_spawn_creates_interactive_root_then_sends_standalone_spawn_command(monkeypatch):
    start_root = Mock(
        return_value={
            "agent_id": "mas-1111111111111111",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }
    )
    send_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-1111111111111111",
            "command": "mini-mas spawn 'task A'",
            "result": {
                "output": "Detached spawn started\n",
                "returncode": 0,
                "exception_info": "",
                "extra": {
                    "child_agent_id": "mas-2222222222222222",
                    "parent_agent_id": "mas-1111111111111111",
                },
            },
        }
    )
    monkeypatch.setattr("minisweagent.mas.runtime.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.runtime.send_root_command", send_command)

    result = one_shot_spawn_through_interactive_root(
        spawn_arguments=["task A"],
        result_timeout_seconds=7,
        system_database_url="postgres://db",
    )

    start_root.assert_called_once_with(system_database_url="postgres://db")
    send_command.assert_called_once_with(
        root_agent_id="mas-1111111111111111",
        command="mini-mas spawn 'task A'",
        result_timeout_seconds=7,
        system_database_url="postgres://db",
    )
    assert result["kind"] == "one_shot_spawn"
    assert result["root_agent_id"] == "mas-1111111111111111"
    assert result["command"] == "mini-mas spawn 'task A'"
    assert result["returncode"] == 0
    assert result["result"]["extra"]["parent_agent_id"] == "mas-1111111111111111"


def test_one_shot_spawn_uses_root_command_signal_result_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("MINI_MAS_ATTACHMENT_LEASE_DIR", str(tmp_path))
    sent = []
    handle = AsyncMockHandle("mas-1111111111111111")

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    async def send_async(destination_id, message, topic=None):
        sent.append((destination_id, message, topic))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        if key == "mini_mas_status":
            return {
                "agent_id": workflow_id,
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
            }
        assert key == "mini_mas_root_command_result:cmd-1111111111111111"
        return {
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": workflow_id,
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
                    "child_agent_id": "mas-2222222222222222",
                    "parent_agent_id": "mas-1111111111111111",
                },
            },
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)
    dbos_module.DBOS.send_async = Mock(side_effect=send_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        patch("minisweagent.mas.runtime.make_agent_id", return_value="mas-1111111111111111"),
        patch("minisweagent.mas.runtime.make_command_id", return_value="cmd-1111111111111111"),
    ):
        result = one_shot_spawn_through_interactive_root(spawn_arguments=["task A"], result_timeout_seconds=5)

    from minisweagent.mas.signals import ROOT_COMMAND_TOPIC

    workflow_func = dbos_module.DBOS.start_workflow_async.call_args.args[0]
    assert workflow_func.__name__ == "interactive_root_agent_workflow"
    assert dbos_module.DBOS.get_event_async.call_args_list[0] == call("mas-1111111111111111", "mini_mas_status", 60)
    assert sent == [
        (
            "mas-1111111111111111",
            {
                "kind": "root_command",
                "command_id": "cmd-1111111111111111",
                "root_agent_id": "mas-1111111111111111",
                "command": "mini-mas spawn 'task A'",
                "source": "external_cli",
            },
            ROOT_COMMAND_TOPIC,
        )
    ]
    assert result["root_agent_id"] == "mas-1111111111111111"
    assert result["result"]["extra"]["child_agent_id"] == "mas-2222222222222222"
    assert result["result"]["extra"]["parent_agent_id"] == "mas-1111111111111111"


def test_one_shot_multi_spawn_preserves_child_result_order_without_order_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("MINI_MAS_ATTACHMENT_LEASE_DIR", str(tmp_path))
    sent = []
    handle = AsyncMockHandle("mas-1111111111111111")

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    async def send_async(destination_id, message, topic=None):
        sent.append((destination_id, message, topic))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        if key == "mini_mas_status":
            return {
                "agent_id": workflow_id,
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
            }
        assert key == "mini_mas_root_command_result:cmd-1111111111111111"
        return {
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": workflow_id,
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
                "extra": {
                    "mas_command": ["spawn", "task A", "task B"],
                    "spawned_child_count": 2,
                    "child_agent_ids": ["mas-2222222222222222", "mas-3333333333333333"],
                    "children": [
                        {
                            "task": "task A",
                            "agent_id": "mas-2222222222222222",
                            "parent_agent_id": "mas-1111111111111111",
                            "agent_artifact_directory": ".mini-mas/agents/mas-2222222222222222",
                            "trajectory_artifact_path": (
                                ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json"
                            ),
                        },
                        {
                            "task": "task B",
                            "agent_id": "mas-3333333333333333",
                            "parent_agent_id": "mas-1111111111111111",
                            "agent_artifact_directory": ".mini-mas/agents/mas-3333333333333333",
                            "trajectory_artifact_path": (
                                ".mini-mas/agents/mas-3333333333333333/trajectory.traj.json"
                            ),
                        },
                    ],
                    "waited": False,
                    "ready_children": [],
                    "still_running_child_agent_ids": [],
                },
            },
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)
    dbos_module.DBOS.send_async = Mock(side_effect=send_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        patch("minisweagent.mas.runtime.make_agent_id", return_value="mas-1111111111111111"),
        patch("minisweagent.mas.runtime.make_command_id", return_value="cmd-1111111111111111"),
    ):
        result = one_shot_spawn_through_interactive_root(
            spawn_arguments=["task A", "task B"],
            result_timeout_seconds=5,
        )

    assert result["kind"] == "one_shot_spawn"
    assert result["root_agent_id"] == "mas-1111111111111111"
    assert result["command"] == "mini-mas spawn 'task A' 'task B'"
    dbos_module.DBOS.start_workflow_async.assert_called_once()
    assert sent[0][1]["command"] == "mini-mas spawn 'task A' 'task B'"

    extra = result["result"]["extra"]
    assert extra["child_agent_ids"] == ["mas-2222222222222222", "mas-3333333333333333"]
    assert [child["task"] for child in extra["children"]] == ["task A", "task B"]
    assert [child["agent_id"] for child in extra["children"]] == [
        "mas-2222222222222222",
        "mas-3333333333333333",
    ]
    assert {child["parent_agent_id"] for child in extra["children"]} == {"mas-1111111111111111"}
    assert all("mas-1111111111111111" not in child["agent_id"] for child in extra["children"])

    durable_order_fields = {"spawn_index", "sibling_index", "task_position", "result_order"}
    for child in extra["children"]:
        assert durable_order_fields.isdisjoint(child)
    assert durable_order_fields.isdisjoint(extra)


def test_standalone_spawn_command_preserves_external_multi_spawn_arguments():
    assert make_standalone_spawn_command(["--wait", "--all", "--timeout", "0.5", "task A", "task B"]) == (
        "mini-mas spawn --wait --all --timeout 0.5 'task A' 'task B'"
    )


def test_one_shot_spawn_result_timeout_reports_resumable_root_without_cleanup(monkeypatch):
    start_root = Mock(
        return_value={
            "agent_id": "mas-1111111111111111",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }
    )
    send_command = Mock(
        return_value={
            "kind": "root_command_result_timeout",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-1111111111111111",
            "command": "mini-mas spawn 'task A'",
            "result": {
                "output": "Timed out waiting for Root Command Result.\n",
                "returncode": 1,
                "exception_info": "root_command_result_timeout",
                "extra": {"mas_command_error": "root_command_result_timeout"},
            },
        }
    )
    monkeypatch.setattr("minisweagent.mas.runtime.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.runtime.send_root_command", send_command)

    result = one_shot_spawn_through_interactive_root(
        spawn_arguments=["task A"],
        result_timeout_seconds=0.01,
    )

    start_root.assert_called_once_with(system_database_url=None)
    send_command.assert_called_once_with(
        root_agent_id="mas-1111111111111111",
        command="mini-mas spawn 'task A'",
        result_timeout_seconds=0.01,
        system_database_url=None,
    )
    assert result["kind"] == "one_shot_spawn_result_timeout"
    assert result["returncode"] == 1
    assert "may still be running" in result["output"]
    assert "root_agent_id: mas-1111111111111111" in result["output"]
    assert "mini-mas status" in result["output"]
    assert "mini-mas resume mas-1111111111111111" in result["output"]
    assert "cancel" not in result["output"].lower()
    assert "failed" not in result["output"].lower()


def test_resume_preparation_validates_agent_id_before_querying_dbos():
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = prepare_resume_root_agent(root_agent_id="not-an-agent-id")

    dbos_module.DBOS.assert_not_called()
    dbos_module.DBOS.launch.assert_not_called()
    assert result["returncode"] == 2
    assert "Invalid Agent ID" in result["output"]
    assert "mas-<16 lowercase hex characters>" in result["output"]


def test_resume_preparation_rejects_unknown_root_agent_id():
    async def get_workflow_status_async(_workflow_id):
        return None

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.get_workflow_status_async = Mock(side_effect=get_workflow_status_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = prepare_resume_root_agent(root_agent_id="mas-1111111111111111")

    dbos_module.DBOS.assert_called_once()
    dbos_module.DBOS.launch.assert_called_once_with()
    assert result["returncode"] == 2
    assert "Unknown Root Agent ID: mas-1111111111111111" in result["output"]


def test_resume_preparation_rejects_child_agent_ids():
    status = _workflow_status_record("mas-2222222222222222", parent_workflow_id="mas-1111111111111111")
    status.name = "child_agent_workflow"

    async def get_workflow_status_async(_workflow_id):
        return status

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.get_workflow_status_async = Mock(side_effect=get_workflow_status_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = prepare_resume_root_agent(root_agent_id="mas-2222222222222222")

    assert result["returncode"] == 2
    assert "not a parentless Interactive Root Agent" in result["output"]
    assert "parent_agent_id: mas-1111111111111111" in result["output"]


def test_resume_preparation_rejects_parentless_non_interactive_workflows():
    status = _workflow_status_record("mas-1111111111111111")
    status.name = "root_agent_workflow"

    async def get_workflow_status_async(_workflow_id):
        return status

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.get_workflow_status_async = Mock(side_effect=get_workflow_status_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = prepare_resume_root_agent(root_agent_id="mas-1111111111111111")

    assert result["returncode"] == 2
    assert "not an Interactive Root Agent workflow" in result["output"]


@pytest.mark.parametrize("lifecycle_state", ["running", "waiting_for_child", "failed", "closed", "limits_exceeded"])
def test_resume_preparation_rejects_unavailable_lifecycle_states(lifecycle_state):
    status = _workflow_status_record("mas-1111111111111111")
    status.name = "interactive_root_agent_workflow"

    async def get_workflow_status_async(_workflow_id):
        return status

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return {
            "agent_id": workflow_id,
            "lifecycle_state": lifecycle_state,
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.get_workflow_status_async = Mock(side_effect=get_workflow_status_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = prepare_resume_root_agent(root_agent_id="mas-1111111111111111")

    assert result["returncode"] == 2
    assert "mas-1111111111111111" in result["output"]
    assert f"lifecycle_state: {lifecycle_state}" in result["output"]
    assert "mini-mas status" in result["output"]
    assert "mini-mas resume mas-1111111111111111" in result["output"]


def test_resume_preparation_claims_single_active_attachment_for_waiting_interactive_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MINI_MAS_ATTACHMENT_LEASE_DIR", str(tmp_path))
    status = _workflow_status_record("mas-1111111111111111")
    status.name = "interactive_root_agent_workflow"

    async def get_workflow_status_async(_workflow_id):
        return status

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.get_workflow_status_async = Mock(side_effect=get_workflow_status_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        first = prepare_resume_root_agent(root_agent_id="mas-1111111111111111")
        second = prepare_resume_root_agent(root_agent_id="mas-1111111111111111")

    assert first | {"attachment_token": "<token>"} == {
        "kind": "resume_ready",
        "root_agent_id": "mas-1111111111111111",
        "agent_id": "mas-1111111111111111",
        "lifecycle_state": "waiting_for_command",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        "attachment_token": "<token>",
        "returncode": 0,
    }
    assert first["attachment_token"].startswith("att-")
    assert second["returncode"] == 2
    assert second["exception_info"] == "root_attachment_unavailable"
    assert "Root Agent attachment is already active" in second["output"]
    assert "root_agent_id: mas-1111111111111111" in second["output"]

    release_root_attachment(
        root_agent_id="mas-1111111111111111",
        attachment_token=first["attachment_token"],
    )
    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        third = prepare_resume_root_agent(root_agent_id="mas-1111111111111111")
    assert third["kind"] == "resume_ready"
    assert third["attachment_token"] != first["attachment_token"]
    release_root_attachment(
        root_agent_id="mas-1111111111111111",
        attachment_token=third["attachment_token"],
    )


@pytest.mark.parametrize("lifecycle_state", ["running", "waiting_for_child"])
def test_root_command_submission_rejects_unavailable_lifecycle_without_sending(
    lifecycle_state,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("MINI_MAS_ATTACHMENT_LEASE_DIR", str(tmp_path))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert key == "mini_mas_status"
        return {
            "agent_id": workflow_id,
            "lifecycle_state": lifecycle_state,
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)
    dbos_module.DBOS.send_async = Mock(side_effect=AssertionError("unavailable Root must not receive commands"))

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = send_root_command(
            root_agent_id="mas-1111111111111111",
            command="echo blocked",
        )

    assert result["kind"] == "root_command_attachment_unavailable"
    assert result["result"]["returncode"] == 2
    assert f"lifecycle_state: {lifecycle_state}" in result["result"]["output"]
    assert "mini-mas resume mas-1111111111111111" in result["result"]["output"]


def test_root_command_result_timeout_keeps_attachment_until_lease_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("MINI_MAS_ATTACHMENT_LEASE_DIR", str(tmp_path))

    async def send_async(_destination_id, _message, topic=None):
        return None

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        if key == "mini_mas_status":
            return {
                "agent_id": workflow_id,
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
            }
        return None

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.send_async = Mock(side_effect=send_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        patch("minisweagent.mas.runtime.make_command_id", return_value="cmd-1111111111111111"),
    ):
        first = send_root_command(
            root_agent_id="mas-1111111111111111",
            command="mini-mas spawn 'long task'",
            result_timeout_seconds=0.01,
        )
        second = send_root_command(
            root_agent_id="mas-1111111111111111",
            command="echo blocked",
        )

    assert first["kind"] == "root_command_result_timeout"
    assert second["kind"] == "root_command_attachment_unavailable"
    assert dbos_module.DBOS.send_async.call_count == 1


def test_external_status_discovers_parentless_interactive_root_agents_only():
    statuses = [
        _workflow_status_record("mas-1111111111111111"),
        _workflow_status_record("mas-2222222222222222", parent_workflow_id="mas-9999999999999999"),
        _workflow_status_record("mas-3333333333333333"),
    ]
    statuses[0].name = "interactive_root_agent_workflow"
    statuses[1].name = "interactive_root_agent_workflow"
    statuses[2].name = "root_agent_workflow"
    snapshots = {
        "mas-1111111111111111": {
            "agent_id": "mas-1111111111111111",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        },
    }

    async def list_workflows_async(**kwargs):
        assert kwargs == {
            "name": "interactive_root_agent_workflow",
            "has_parent": False,
            "load_input": False,
            "load_output": False,
        }
        return statuses

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return snapshots[workflow_id]

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.list_workflows_async = Mock(side_effect=list_workflows_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = discover_interactive_root_agents()

    dbos_module.DBOS.assert_called_once_with(
        config={
            "name": "mini-swe-agent-mas",
            "system_database_url": None,
        }
    )
    dbos_module.DBOS.launch.assert_called_once_with()
    dbos_module.DBOS.get_event_async.assert_called_once_with("mas-1111111111111111", "mini_mas_status", 1)
    assert result["kind"] == "interactive_root_discovery"
    assert result["returncode"] == 0
    assert result["roots"] == [
        {
            "agent_id": "mas-1111111111111111",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }
    ]
    assert "Interactive Root Agents" in result["output"]
    assert "agent_id: mas-1111111111111111" in result["output"]
    assert "lifecycle_state: waiting_for_command" in result["output"]
    assert "mas-2222222222222222" not in result["output"]
    assert "mas-3333333333333333" not in result["output"]
    assert "Child Agent" not in result["output"]
    assert "latest_" not in result["output"]


def test_external_status_lists_non_resumable_root_agents_with_lifecycle_state():
    running_status = _workflow_status_record("mas-1111111111111111")
    failed_status = _workflow_status_record("mas-2222222222222222")
    running_status.name = "interactive_root_agent_workflow"
    failed_status.name = "interactive_root_agent_workflow"

    async def list_workflows_async(**_kwargs):
        return [failed_status, running_status]

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "failed" if workflow_id == "mas-2222222222222222" else "running",
            "agent_artifact_directory": f".mini-mas/agents/{workflow_id}",
            "trajectory_artifact_path": f".mini-mas/agents/{workflow_id}/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.list_workflows_async = Mock(side_effect=list_workflows_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = discover_interactive_root_agents()

    assert "agent_id: mas-1111111111111111" in result["output"]
    assert "lifecycle_state: running" in result["output"]
    assert "agent_id: mas-2222222222222222" in result["output"]
    assert "lifecycle_state: failed" in result["output"]


def test_external_status_dbos_errors_propagate_visibly():
    async def list_workflows_async(**_kwargs):
        raise RuntimeError("dbos query failed")

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.list_workflows_async = Mock(side_effect=list_workflows_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module), pytest.raises(
        RuntimeError, match="dbos query failed"
    ):
        discover_interactive_root_agents()


def test_external_status_dbos_configuration_errors_propagate_visibly():
    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.side_effect = RuntimeError("dbos config failed")

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module), pytest.raises(
        RuntimeError, match="dbos config failed"
    ):
        discover_interactive_root_agents()


def test_external_status_snapshot_read_errors_propagate_visibly():
    status = _workflow_status_record("mas-1111111111111111")
    status.name = "interactive_root_agent_workflow"

    async def list_workflows_async(**_kwargs):
        return [status]

    async def get_event_async(_workflow_id, _key, timeout_seconds=60):
        raise RuntimeError("status event read failed")

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.list_workflows_async = Mock(side_effect=list_workflows_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module), pytest.raises(
        RuntimeError, match="status event read failed"
    ):
        discover_interactive_root_agents()


@pytest.mark.parametrize(
    ("runtime_func", "kwargs"),
    [
        (wait_for_agent_workflow, {"workflow_id": "mas-2222222222222222", "timeout_seconds": 1.0}),
        (
            continue_agent_workflow,
            {"workflow_id": "mas-2222222222222222", "message": "please continue"},
        ),
        (close_agent_workflow, {"workflow_id": "mas-2222222222222222"}),
    ],
)
def test_external_agent_interaction_runtimes_share_unsupported_response_without_dbos(runtime_func, kwargs):
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = runtime_func(**kwargs)

    dbos_module.DBOS.assert_not_called()
    dbos_module.DBOS.launch.assert_not_called()
    assert result == {
        "kind": "unsupported",
        "agent_id": "mas-2222222222222222",
        "output": (
            "External mini-mas status, wait, continue, and close are unsupported until terminal commands are routed "
            "through an Interactive Root Agent.\n"
        ),
        "returncode": 2,
        "exception_info": "external_agent_interaction_unsupported",
        "extra": {"mas_command_error": "external_agent_interaction_unsupported"},
    }
    assert "unsupported until terminal commands are routed through an Interactive Root Agent" in result["output"]


def test_external_status_with_agent_id_keeps_unsupported_external_agent_interaction_response():
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = get_agent_workflow_status(workflow_id="mas-2222222222222222")

    dbos_module.DBOS.assert_not_called()
    dbos_module.DBOS.launch.assert_not_called()
    assert result["kind"] == "unsupported"
    assert result["agent_id"] == "mas-2222222222222222"
    assert result["returncode"] == 2
