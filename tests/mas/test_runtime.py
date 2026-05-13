from unittest.mock import AsyncMock, Mock, call, patch

import pytest

from minisweagent.mas.queues import AI_AGENT_WORKFLOW_QUEUE_NAME, INTERACTIVE_WORKFLOW_QUEUE_NAME
from minisweagent.mas.runtime import (
    activate_ai_agent_execution,
    discover_interactive_root_agents,
    launch_interactive_runtime,
    make_standalone_spawn_command,
    one_shot_spawn_through_interactive_root,
    prepare_resume_root_agent,
    release_root_attachment,
    send_root_command,
    start_interactive_root_agent_workflow,
)

from .helpers import (
    AsyncMockHandle,
    _mock_dbos_module,
    _workflow_status_record,
)

DEFAULT_RUNTIME_DBOS_CONFIG = {
    "name": "mini-swe-agent-mas",
    "system_database_url": "sqlite:///.mini-mas/runtime/mini_mas_dbos.sqlite",
}


class DurableWorkflowQueue:
    def __init__(self, name):
        self.name = name
        self.pending = []
        self.executed = []
        self.agent_states = {
            "mas-3333333333333333": "running",
            "mas-4444444444444444": "waiting_for_child",
            "mas-5555555555555555": "recovery_required",
        }
        self.artifacts = {
            ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json": "{}",
            ".mini-mas/agents/mas-3333333333333333/trajectory.traj.json": '{"status": "running"}',
            ".mini-mas/agents/mas-4444444444444444/trajectory.traj.json": '{"status": "waiting"}',
            ".mini-mas/agents/mas-5555555555555555/trajectory.traj.json": '{"status": "recovery"}',
        }
        self.listening_queues = set()

    async def enqueue_async(self, workflow_func, *args, **kwargs):
        work = {"workflow_func": workflow_func, "args": args, "kwargs": kwargs}
        self.pending.append(work)
        await self.drain_queue(self.name)
        return AsyncMockHandle(args[0] if args else "mas-unknown")

    async def drain_queue(self, queue_name):
        if queue_name not in self.listening_queues:
            return
        runnable = list(self.pending)
        self.pending.clear()
        for work in runnable:
            self.executed.append(work["args"][0])
            await work["workflow_func"](*work["args"], **work["kwargs"])

    def activate_queue(self, queue_name):
        self.listening_queues.add(queue_name)
        if queue_name == self.name:
            import asyncio

            asyncio.run(self.drain_queue(queue_name))

    def deactivate_all(self, **_kwargs):
        self.listening_queues.clear()


@pytest.fixture(autouse=True)
def _isolate_runtime_state_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_plain_mini_mas_runtime_starts_interactive_root_workflow_and_waits_for_idle_metadata(tmp_path):
    handle = AsyncMockHandle("mas-1111111111111111")

    async def enqueue_workflow_async(*_args, **_kwargs):
        return handle

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.enqueue_workflow_async = Mock(side_effect=enqueue_workflow_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)
    dbos_module.DBOS.register_queue_async = AsyncMock()
    dbos_module.DBOS.register_queue = Mock(side_effect=AssertionError("Async runtime must use register_queue_async"))
    dbos_module.DBOS.start_workflow.side_effect = AssertionError("MAS runtime must use queued startup")
    dbos_module.DBOS.start_workflow_async.side_effect = AssertionError("MAS runtime must use queued startup")

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = start_interactive_root_agent_workflow(workflow_id="mas-1111111111111111")

    dbos_module.DBOS.assert_called_once_with(config=DEFAULT_RUNTIME_DBOS_CONFIG)
    assert (tmp_path / ".mini-mas" / "runtime").is_dir()
    assert not (tmp_path / ".gitignore").exists()
    dbos_module.DBOS.listen_queues.assert_called_once_with([INTERACTIVE_WORKFLOW_QUEUE_NAME])
    dbos_module.DBOS.launch.assert_called_once_with()
    dbos_module.SetWorkflowID.assert_called_once_with("mas-1111111111111111")
    dbos_module.DBOS.start_workflow.assert_not_called()
    dbos_module.DBOS.start_workflow_async.assert_not_called()
    dbos_module.DBOS.enqueue_workflow_async.assert_called_once()

    assert dbos_module.DBOS.enqueue_workflow_async.call_args.args[0] == INTERACTIVE_WORKFLOW_QUEUE_NAME
    workflow_func = dbos_module.DBOS.enqueue_workflow_async.call_args.args[1]
    assert workflow_func.__name__ == "interactive_root_agent_workflow"
    assert dbos_module.DBOS.enqueue_workflow_async.call_args.args[2] == "mas-1111111111111111"
    assert dbos_module.DBOS.enqueue_workflow_async.call_args.kwargs == {"max_commands": None}
    dbos_module.DBOS.get_event_async.assert_called_once_with("mas-1111111111111111", "mini_mas_status", 60)
    assert result == {
        "agent_id": "mas-1111111111111111",
        "lifecycle_state": "waiting_for_command",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
    }


def test_plain_mini_mas_runtime_listens_only_to_interactive_workflows_before_launch():
    handle = AsyncMockHandle("mas-1111111111111111")

    async def enqueue_workflow_async(*_args, **_kwargs):
        return handle

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.enqueue_workflow_async = Mock(side_effect=enqueue_workflow_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        start_interactive_root_agent_workflow(workflow_id="mas-1111111111111111")

    assert dbos_module.DBOS.listen_queues.call_args == call([INTERACTIVE_WORKFLOW_QUEUE_NAME])
    assert AI_AGENT_WORKFLOW_QUEUE_NAME not in dbos_module.DBOS.listen_queues.call_args.args[0]
    assert dbos_module.DBOS.mock_calls.index(call.listen_queues([INTERACTIVE_WORKFLOW_QUEUE_NAME])) < (
        dbos_module.DBOS.mock_calls.index(call.launch())
    )
    dbos_module.DBOS.register_queue.assert_not_called()
    dbos_module.DBOS.register_queue_async.assert_called_once_with(INTERACTIVE_WORKFLOW_QUEUE_NAME)
    assert dbos_module.DBOS.mock_calls.index(call.launch()) < (
        dbos_module.DBOS.mock_calls.index(call.register_queue_async(INTERACTIVE_WORKFLOW_QUEUE_NAME))
    )


def test_interactive_root_startup_is_queued_on_interactive_workflow_queue():
    handle = AsyncMockHandle("mas-1111111111111111")

    async def enqueue_workflow_async(*_args, **_kwargs):
        return handle

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.enqueue_workflow_async = Mock(side_effect=enqueue_workflow_async)
    dbos_module.DBOS.start_workflow_async = Mock(
        side_effect=AssertionError("Interactive Root Agent startup must go through the interactive queue")
    )
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        start_interactive_root_agent_workflow(workflow_id="mas-1111111111111111")

    dbos_module.DBOS.start_workflow_async.assert_not_called()
    dbos_module.DBOS.enqueue_workflow_async.assert_called_once()
    assert dbos_module.DBOS.enqueue_workflow_async.call_args.args[0] == INTERACTIVE_WORKFLOW_QUEUE_NAME
    workflow_func = dbos_module.DBOS.enqueue_workflow_async.call_args.args[1]
    assert workflow_func.__name__ == "interactive_root_agent_workflow"
    assert dbos_module.DBOS.enqueue_workflow_async.call_args.args[2] == "mas-1111111111111111"
    assert dbos_module.DBOS.enqueue_workflow_async.call_args.kwargs == {"max_commands": None}


def test_ordinary_runtime_entrypoints_apply_interactive_queue_policy_before_launch(monkeypatch, tmp_path):
    monkeypatch.setenv("MINI_MAS_ATTACHMENT_LEASE_DIR", str(tmp_path))
    root_status = _workflow_status_record("mas-1111111111111111")
    root_status.name = "interactive_root_agent_workflow"

    async def list_workflows_async(**_kwargs):
        return [root_status]

    async def get_workflow_status_async(_workflow_id):
        return root_status

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        if key == "mini_mas_root_command_result:cmd-1111111111111111":
            return {
                "kind": "root_command_result",
                "command_id": "cmd-1111111111111111",
                "root_agent_id": workflow_id,
                "command": "echo hello",
                "result": {"output": "hello\n", "returncode": 0, "exception_info": "", "extra": {}},
            }
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }

    async def send_async(_destination_id, _message, topic=None):
        return None

    for run_entrypoint in [
        lambda: send_root_command(
            root_agent_id="mas-1111111111111111",
            command="echo hello",
            command_id="cmd-1111111111111111",
        ),
        lambda: discover_interactive_root_agents(),
        lambda: prepare_resume_root_agent(root_agent_id="mas-1111111111111111"),
    ]:
        dbos_module = _mock_dbos_module()
        dbos_module.DBOS.list_workflows_async = Mock(side_effect=list_workflows_async)
        dbos_module.DBOS.get_workflow_status_async = Mock(side_effect=get_workflow_status_async)
        dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)
        dbos_module.DBOS.send_async = Mock(side_effect=send_async)

        with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
            run_entrypoint()

        assert dbos_module.DBOS.listen_queues.call_args == call([INTERACTIVE_WORKFLOW_QUEUE_NAME])
        assert AI_AGENT_WORKFLOW_QUEUE_NAME not in dbos_module.DBOS.listen_queues.call_args.args[0]
        assert dbos_module.DBOS.mock_calls.index(call.listen_queues([INTERACTIVE_WORKFLOW_QUEUE_NAME])) < (
            dbos_module.DBOS.mock_calls.index(call.launch())
        )


def test_interactive_runtime_launch_reuses_existing_interactive_policy_and_rejects_mismatched_policy():
    from minisweagent.mas.runtime import launch_dbos_with_queue_policy

    dbos_module = _mock_dbos_module()

    launch_interactive_runtime(dbos_module)
    launch_interactive_runtime(dbos_module)

    dbos_module.DBOS.listen_queues.assert_called_once_with([INTERACTIVE_WORKFLOW_QUEUE_NAME])
    assert dbos_module.DBOS.launch.call_count == 2

    with pytest.raises(RuntimeError, match="non-interactive MAS queue policy"):
        launch_dbos_with_queue_policy(dbos_module, [AI_AGENT_WORKFLOW_QUEUE_NAME])


def test_ai_agent_activation_runtime_listens_only_to_ai_workflows_before_launch():
    dbos_module = _mock_dbos_module()
    stop_event = Mock()
    stop_event.wait.return_value = True
    activation_order = []
    register_workflows = Mock(side_effect=lambda: activation_order.append("register_workflows"))
    dbos_module.DBOS.listen_queues.side_effect = lambda _queue_names: activation_order.append("listen")
    dbos_module.DBOS.launch.side_effect = lambda: activation_order.append("launch")

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        patch("minisweagent.mas.runtime.register_mas_agent_workflows", register_workflows),
    ):
        result = activate_ai_agent_execution(stop_event=stop_event, wait_interval_seconds=0.01)

    dbos_module.DBOS.assert_called_once_with(config=DEFAULT_RUNTIME_DBOS_CONFIG)
    register_workflows.assert_called_once_with()
    assert activation_order.index("register_workflows") < activation_order.index("launch")
    assert activation_order.index("listen") < activation_order.index("launch")
    assert dbos_module.DBOS.listen_queues.call_args == call([AI_AGENT_WORKFLOW_QUEUE_NAME])
    assert INTERACTIVE_WORKFLOW_QUEUE_NAME not in dbos_module.DBOS.listen_queues.call_args.args[0]
    assert dbos_module.DBOS.mock_calls.index(call.listen_queues([AI_AGENT_WORKFLOW_QUEUE_NAME])) < (
        dbos_module.DBOS.mock_calls.index(call.launch())
    )
    dbos_module.DBOS.register_queue.assert_called_once_with(AI_AGENT_WORKFLOW_QUEUE_NAME)
    dbos_module.DBOS.register_queue_async.assert_not_called()
    stop_event.wait.assert_called_once_with(0.01)
    assert result == {
        "kind": "ai_agent_execution_deactivated",
        "queue_name": AI_AGENT_WORKFLOW_QUEUE_NAME,
    }


def test_ai_agent_activation_remains_foreground_when_no_work_is_queued():
    dbos_module = _mock_dbos_module()
    stop_event = Mock()
    stop_event.wait.side_effect = [False, False, True]

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        activate_ai_agent_execution(stop_event=stop_event, wait_interval_seconds=0.01)

    assert stop_event.wait.call_args_list == [call(0.01), call(0.01), call(0.01)]
    dbos_module.DBOS.enqueue_workflow.assert_not_called()
    dbos_module.DBOS.enqueue_workflow_async.assert_not_called()
    dbos_module.DBOS.start_workflow.assert_not_called()
    dbos_module.DBOS.start_workflow_async.assert_not_called()


def test_ai_agent_work_queued_before_activation_executes_only_after_activation(monkeypatch):
    from minisweagent.mas import agent_interactions

    queued_work = DurableWorkflowQueue(AI_AGENT_WORKFLOW_QUEUE_NAME)

    async def child_agent_workflow(agent_id, task, *, parent_agent_id):
        queued_work.artifacts[f".mini-mas/agents/{agent_id}/trajectory.traj.json"] = task
        return {"agent_id": agent_id, "parent_agent_id": parent_agent_id, "status": "started"}

    spawn_dbos_module = _mock_dbos_module()
    ordinary_dbos_module = _mock_dbos_module()
    activation_dbos_module = _mock_dbos_module()
    ordinary_dbos_module.DBOS.register_queue.side_effect = queued_work.activate_queue
    activation_dbos_module.DBOS.register_queue.side_effect = queued_work.activate_queue

    monkeypatch.setattr(agent_interactions, "_dbos", spawn_dbos_module)
    monkeypatch.setattr(
        "minisweagent.mas.mas_agent.ai_agent_workflow_queue",
        queued_work,
    )
    monkeypatch.setattr(
        "minisweagent.mas.mas_agent.child_agent_workflow",
        child_agent_workflow,
    )

    import asyncio

    asyncio.run(
        agent_interactions.enqueue_child_agent_workflow(
            parent_agent_id="mas-1111111111111111",
            child_agent_id="mas-2222222222222222",
            task="inspect staged work",
        )
    )

    with patch("minisweagent.mas.runtime.load_dbos", return_value=ordinary_dbos_module):
        assert queued_work.executed == []
        assert [work["args"][0] for work in queued_work.pending] == ["mas-2222222222222222"]
        launch_interactive_runtime(ordinary_dbos_module)
        assert queued_work.executed == []
        assert [work["args"][0] for work in queued_work.pending] == ["mas-2222222222222222"]

    with patch("minisweagent.mas.runtime.load_dbos", return_value=activation_dbos_module):
        stop_event = Mock()
        stop_event.wait.return_value = True
        activate_ai_agent_execution(stop_event=stop_event, wait_interval_seconds=0.01)

    assert queued_work.executed == ["mas-2222222222222222"]
    assert queued_work.pending == []
    assert queued_work.artifacts[".mini-mas/agents/mas-2222222222222222/trajectory.traj.json"] == (
        "inspect staged work"
    )


def test_ai_agent_activation_consumes_late_work_and_stops_execution_without_agent_cleanup(monkeypatch):
    from minisweagent.mas import agent_interactions

    queued_work = DurableWorkflowQueue(AI_AGENT_WORKFLOW_QUEUE_NAME)
    initial_agent_states = dict(queued_work.agent_states)
    initial_artifacts = dict(queued_work.artifacts)

    async def child_agent_workflow(agent_id, task, *, parent_agent_id):
        queued_work.agent_states[agent_id] = "started"
        queued_work.artifacts[f".mini-mas/agents/{agent_id}/trajectory.traj.json"] = task
        return {"agent_id": agent_id, "parent_agent_id": parent_agent_id, "status": "started"}

    spawn_dbos_module = _mock_dbos_module()
    activation_dbos_module = _mock_dbos_module()
    activation_dbos_module.DBOS.register_queue.side_effect = queued_work.activate_queue
    activation_dbos_module.DBOS.destroy.side_effect = queued_work.deactivate_all
    monkeypatch.setattr(agent_interactions, "_dbos", spawn_dbos_module)
    monkeypatch.setattr("minisweagent.mas.mas_agent.ai_agent_workflow_queue", queued_work)
    monkeypatch.setattr("minisweagent.mas.mas_agent.child_agent_workflow", child_agent_workflow)

    import asyncio

    def enqueue_late_work_then_stop(_wait_interval_seconds):
        asyncio.run(
            agent_interactions.enqueue_child_agent_workflow(
                parent_agent_id="mas-1111111111111111",
                child_agent_id="mas-6666666666666666",
                task="late work",
            )
        )
        return True

    stop_event = Mock()
    stop_event.wait.side_effect = enqueue_late_work_then_stop
    with patch("minisweagent.mas.runtime.load_dbos", return_value=activation_dbos_module):
        activate_ai_agent_execution(stop_event=stop_event, wait_interval_seconds=0.01)

    assert queued_work.executed == ["mas-6666666666666666"]
    assert queued_work.pending == []
    assert queued_work.agent_states == {
        **initial_agent_states,
        "mas-6666666666666666": "started",
    }
    assert queued_work.artifacts == {
        **initial_artifacts,
        ".mini-mas/agents/mas-6666666666666666/trajectory.traj.json": "late work",
    }

    asyncio.run(
        agent_interactions.enqueue_child_agent_workflow(
            parent_agent_id="mas-1111111111111111",
            child_agent_id="mas-7777777777777777",
            task="post-shutdown work",
        )
    )

    assert queued_work.executed == ["mas-6666666666666666"]
    assert [work["args"][0] for work in queued_work.pending] == ["mas-7777777777777777"]
    assert queued_work.agent_states == {
        **initial_agent_states,
        "mas-6666666666666666": "started",
    }
    assert queued_work.artifacts == {
        **initial_artifacts,
        ".mini-mas/agents/mas-6666666666666666/trajectory.traj.json": "late work",
    }
    activation_dbos_module.DBOS.destroy.assert_called_once_with(workflow_completion_timeout_sec=0)


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

    dbos_module.DBOS.assert_called_once_with(config=DEFAULT_RUNTIME_DBOS_CONFIG)
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
    )

    start_root.assert_called_once_with()
    send_command.assert_called_once_with(
        root_agent_id="mas-1111111111111111",
        command="mini-mas spawn 'task A'",
        result_timeout_seconds=7,
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

    async def enqueue_workflow_async(*_args, **_kwargs):
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
    dbos_module.DBOS.enqueue_workflow_async = Mock(side_effect=enqueue_workflow_async)
    dbos_module.DBOS.send_async = Mock(side_effect=send_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        patch("minisweagent.mas.runtime.make_agent_id", return_value="mas-1111111111111111"),
        patch("minisweagent.mas.runtime.make_command_id", return_value="cmd-1111111111111111"),
    ):
        result = one_shot_spawn_through_interactive_root(spawn_arguments=["task A"], result_timeout_seconds=5)

    from minisweagent.mas.signals import ROOT_COMMAND_TOPIC

    workflow_func = dbos_module.DBOS.enqueue_workflow_async.call_args.args[1]
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

    async def enqueue_workflow_async(*_args, **_kwargs):
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
                            "trajectory_artifact_path": (".mini-mas/agents/mas-2222222222222222/trajectory.traj.json"),
                        },
                        {
                            "task": "task B",
                            "agent_id": "mas-3333333333333333",
                            "parent_agent_id": "mas-1111111111111111",
                            "agent_artifact_directory": ".mini-mas/agents/mas-3333333333333333",
                            "trajectory_artifact_path": (".mini-mas/agents/mas-3333333333333333/trajectory.traj.json"),
                        },
                    ],
                    "waited": False,
                    "ready_children": [],
                    "still_running_child_agent_ids": [],
                },
            },
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.enqueue_workflow_async = Mock(side_effect=enqueue_workflow_async)
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
    dbos_module.DBOS.enqueue_workflow_async.assert_called_once()
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

    start_root.assert_called_once_with()
    send_command.assert_called_once_with(
        root_agent_id="mas-1111111111111111",
        command="mini-mas spawn 'task A'",
        result_timeout_seconds=0.01,
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
    assert "lifecycle_state: unknown" in result["output"]
    assert "mini-mas status" in result["output"]
    assert "mini-mas resume mas-1111111111111111" in result["output"]


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
    assert "may still be running" in first["result"]["output"]
    assert "root_agent_id: mas-1111111111111111" in first["result"]["output"]
    assert "mini-mas status" in first["result"]["output"]
    assert "mini-mas resume mas-1111111111111111" in first["result"]["output"]
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

    dbos_module.DBOS.assert_called_once_with(config=DEFAULT_RUNTIME_DBOS_CONFIG)
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

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        pytest.raises(RuntimeError, match="dbos query failed"),
    ):
        discover_interactive_root_agents()


def test_external_status_dbos_configuration_errors_propagate_visibly():
    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.side_effect = RuntimeError("dbos config failed")

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        pytest.raises(RuntimeError, match="dbos config failed"),
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

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        pytest.raises(RuntimeError, match="status event read failed"),
    ):
        discover_interactive_root_agents()
