import asyncio
import importlib
import inspect
import json
from unittest.mock import MagicMock, Mock, patch

from minisweagent.mas import status_events as mas_status_events
from minisweagent.mas.queues import AI_AGENT_WORKFLOW_QUEUE_NAME
from minisweagent.mas.signals import (
    PARENT_DIRECTION_TOPIC,
    PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS,
)
from minisweagent.models.test_models import (
    DeterministicModel,
    make_output,
)

from .helpers import (
    _agent_execution_config,
    _call_root_agent_workflow,
    _mock_dbos_module,
    _mock_recording_dbos_module,
    _observation_text,
    _recording_workflow_queue,
)


def test_root_agent_workflow_writes_trajectory_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows

    result = _call_root_agent_workflow(workflows.root_agent_workflow, "mas-0123456789abcdef")

    assert result == {
        "agent_id": "mas-0123456789abcdef",
        "status": "started",
        "terminal_state": "started",
        "agent_artifact_directory": ".mini-mas/agents/mas-0123456789abcdef",
        "trajectory_artifact_path": ".mini-mas/agents/mas-0123456789abcdef/trajectory.traj.json",
    }
    trajectory_path = tmp_path / result["trajectory_artifact_path"]
    assert trajectory_path.exists()
    artifact = json.loads(trajectory_path.read_text())
    assert artifact["info"]["agent_id"] == "mas-0123456789abcdef"
    assert "workflow_id" not in artifact["info"]
    assert artifact["info"]["agent_artifact_directory"] == ".mini-mas/agents/mas-0123456789abcdef"


def test_interactive_root_agent_workflow_publishes_waiting_for_command_and_writes_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows

    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(key, value):
        published.append((key, value))

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))

    result = _call_root_agent_workflow(workflows.interactive_root_agent_workflow, "mas-0123456789abcdef")

    assert result == {
        "agent_id": "mas-0123456789abcdef",
        "status": "waiting_for_command",
        "terminal_state": "waiting_for_command",
        "lifecycle_state": "waiting_for_command",
        "agent_artifact_directory": ".mini-mas/agents/mas-0123456789abcdef",
        "trajectory_artifact_path": ".mini-mas/agents/mas-0123456789abcdef/trajectory.traj.json",
    }
    assert published == [
        (
            mas_status_events.STATUS_EVENT_KEY,
            {
                "agent_id": "mas-0123456789abcdef",
                "lifecycle_state": "waiting_for_command",
                "agent_artifact_directory": ".mini-mas/agents/mas-0123456789abcdef",
                "trajectory_artifact_path": ".mini-mas/agents/mas-0123456789abcdef/trajectory.traj.json",
            },
        )
    ]

    trajectory_path = tmp_path / result["trajectory_artifact_path"]
    artifact = json.loads(trajectory_path.read_text())
    assert artifact["info"]["agent_id"] == "mas-0123456789abcdef"
    assert artifact["info"]["exit_status"] == "waiting_for_command"
    assert artifact["info"]["agent_artifact_directory"] == ".mini-mas/agents/mas-0123456789abcdef"
    assert artifact["info"]["trajectory_artifact_path"] == result["trajectory_artifact_path"]
    assert "parent_agent_id" not in artifact["info"]
    assert "is_root" not in artifact["info"]
    assert "interaction_mode" not in artifact["info"]


def test_interactive_root_agent_executes_root_command_signal_and_publishes_scoped_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows
    from minisweagent.mas.signals import ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX, ROOT_COMMAND_TOPIC

    published = []
    received = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        received.append((topic, timeout_seconds))
        return {
            "kind": "root_command",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-0123456789abcdef",
            "command": "echo hello",
            "source": "external_cli",
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.return_value = {"output": "hello\n", "returncode": 0, "exception_info": "", "extra": {}}

    result = _call_root_agent_workflow(
        workflows.interactive_root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        step_limit=0,
        max_commands=1,
    )

    assert received == [(ROOT_COMMAND_TOPIC, workflows.ROOT_COMMAND_WAIT_TIMEOUT_SECONDS)]
    assert result["status"] == "waiting_for_command"
    assert result["lifecycle_state"] == "waiting_for_command"
    assert env.execute.call_args.args[0] == {"command": "echo hello"}

    result_events = [
        value
        for key, value in published
        if key == f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-1111111111111111"
    ]
    assert len(result_events) == 1
    event = result_events[0]
    assert event["kind"] == "root_command_result"
    assert event["command_id"] == "cmd-1111111111111111"
    assert event["root_agent_id"] == "mas-0123456789abcdef"
    assert event["command"] == "echo hello"
    assert set(event["result"]) == {"output", "returncode", "exception_info", "extra"}
    assert event["result"]["returncode"] == 0
    assert "hello" in event["result"]["output"]

    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == [
        "waiting_for_command",
        "running",
        "waiting_for_command",
    ]


def test_interactive_root_agent_rejects_mismatched_root_command_signal_without_execution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows
    from minisweagent.mas.signals import ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX, ROOT_COMMAND_TOPIC

    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        assert topic == ROOT_COMMAND_TOPIC
        return {
            "kind": "root_command",
            "command_id": "cmd-mismatch",
            "root_agent_id": "mas-9999999999999999",
            "command": "echo should-not-run",
            "source": "external_cli",
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}

    result = _call_root_agent_workflow(
        workflows.interactive_root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        step_limit=0,
        max_commands=1,
    )

    env.execute.assert_not_called()
    assert result["lifecycle_state"] == "waiting_for_command"
    result_events = [
        value
        for key, value in published
        if key == f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-mismatch"
    ]
    assert len(result_events) == 1
    event = result_events[0]
    assert event["command_id"] == "cmd-mismatch"
    assert event["root_agent_id"] == "mas-0123456789abcdef"
    assert event["command"] == "echo should-not-run"
    assert event["result"]["returncode"] == 2
    assert "target mismatch" in event["result"]["exception_info"]

    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == [
        "waiting_for_command",
        "waiting_for_command",
    ]


def test_interactive_root_agent_publishes_each_result_under_its_own_command_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows
    from minisweagent.mas.signals import ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX

    published = []
    signals = iter(
        [
            {
                "kind": "root_command",
                "command_id": "cmd-first",
                "root_agent_id": "mas-0123456789abcdef",
                "command": "echo first",
                "source": "external_cli",
            },
            {
                "kind": "root_command",
                "command_id": "cmd-second",
                "root_agent_id": "mas-0123456789abcdef",
                "command": "echo second",
                "source": "external_cli",
            },
        ]
    )
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        return next(signals)

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = [
        {"output": "first\n", "returncode": 0, "exception_info": "", "extra": {}},
        {"output": "second\n", "returncode": 0, "exception_info": "", "extra": {}},
    ]

    _call_root_agent_workflow(
        workflows.interactive_root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        step_limit=0,
        max_commands=2,
    )

    events_by_key = {key: value for key, value in published if key.startswith(ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX)}
    assert set(events_by_key) == {
        f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-first",
        f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-second",
    }
    assert events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-first"]["command_id"] == "cmd-first"
    assert "first" in events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-first"]["result"]["output"]
    assert events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-second"]["command_id"] == "cmd-second"
    assert "second" in events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-second"]["result"]["output"]


def test_interactive_root_agent_routes_standalone_mas_commands_and_rejects_composed_mas_commands(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows
    from minisweagent.mas.signals import ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX

    published = []
    signals = iter(
        [
            {
                "kind": "root_command",
                "command_id": "cmd-status",
                "root_agent_id": "mas-0123456789abcdef",
                "command": "mini-mas status",
                "source": "external_cli",
            },
            {
                "kind": "root_command",
                "command_id": "cmd-composed",
                "root_agent_id": "mas-0123456789abcdef",
                "command": "mini-mas status && echo done",
                "source": "external_cli",
            },
        ]
    )
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        return next(signals)

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}

    _call_root_agent_workflow(
        workflows.interactive_root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        step_limit=0,
        max_commands=2,
    )

    env.execute.assert_not_called()
    events_by_key = {key: value for key, value in published if key.startswith(ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX)}
    status_result = events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-status"]["result"]
    assert "Direct Child Agents for: mas-0123456789abcdef" in status_result["output"]
    assert status_result["returncode"] == 0

    composed_result = events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-composed"]["result"]
    assert composed_result["returncode"] == 2
    assert "mini-mas must be issued as a standalone command" in composed_result["output"]


def test_interactive_root_agent_waited_spawn_result_uses_existing_waited_shape_and_lifecycle(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MSWEA_MODEL_NAME", "deterministic")

    import minisweagent.mas.mas_agent as workflows
    from minisweagent.mas.signals import ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX, ROOT_COMMAND_TOPIC

    published = []
    ai_agent_queue = _recording_workflow_queue()
    monkeypatch.setattr(workflows, "ai_agent_workflow_queue", ai_agent_queue)
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")
    monkeypatch.setattr(workflows.agent_interactions, "make_agent_id", lambda: "mas-1111111111111111")
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        assert topic == ROOT_COMMAND_TOPIC
        return {
            "kind": "root_command",
            "command_id": "cmd-waited-spawn",
            "root_agent_id": "mas-0123456789abcdef",
            "command": 'mini-mas spawn --wait --timeout 0.01 "task A"',
            "source": "external_cli",
        }

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-1111111111111111"
        assert key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY
        assert timeout_seconds == 0.01
        await asyncio.sleep(10)

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}

    result = _call_root_agent_workflow(
        workflows.interactive_root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        step_limit=0,
        max_commands=1,
    )

    assert result["lifecycle_state"] == "waiting_for_command"
    env.execute.assert_not_called()
    assert [call["args"][0] for call in ai_agent_queue.enqueued] == ["mas-1111111111111111"]

    events_by_key = {key: value for key, value in published if key.startswith(ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX)}
    event = events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-waited-spawn"]
    assert event["command"] == 'mini-mas spawn --wait --timeout 0.01 "task A"'
    command_result = event["result"]
    assert command_result["returncode"] == 0
    assert "Waited spawn timed out" in command_result["output"]
    assert "wait_mode: any" in command_result["output"]
    assert "ready_child_count: 0" in command_result["output"]
    assert "still_running_child_agent_ids: mas-1111111111111111" in command_result["output"]

    extra = command_result["extra"]
    assert extra["waited"] is True
    assert extra["wait_mode"] == "any"
    assert extra["timed_out"] is True
    assert extra["ready_children"] == []
    assert extra["still_running_child_agent_ids"] == ["mas-1111111111111111"]

    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == [
        "waiting_for_command",
        "running",
        "waiting_for_child",
        "running",
        "waiting_for_command",
    ]


def test_interactive_root_agent_publishes_result_and_stays_alive_after_recoverable_command_error(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows
    from minisweagent.mas.signals import ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX

    published = []
    signals = iter(
        [
            {
                "kind": "root_command",
                "command_id": "cmd-error",
                "root_agent_id": "mas-0123456789abcdef",
                "command": "explode",
                "source": "external_cli",
            },
            {
                "kind": "root_command",
                "command_id": "cmd-after-error",
                "root_agent_id": "mas-0123456789abcdef",
                "command": "echo after",
                "source": "external_cli",
            },
        ]
    )
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        return next(signals)

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = [
        RuntimeError("boom"),
        {"output": "after\n", "returncode": 0, "exception_info": "", "extra": {}},
    ]

    result = _call_root_agent_workflow(
        workflows.interactive_root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        step_limit=0,
        max_commands=2,
    )

    assert result["lifecycle_state"] == "waiting_for_command"
    events_by_key = {key: value for key, value in published if key.startswith(ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX)}
    error_result = events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-error"]["result"]
    assert error_result["returncode"] == 1
    assert "boom" in error_result["output"]
    assert "boom" in error_result["exception_info"]

    after_result = events_by_key[f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}cmd-after-error"]["result"]
    assert after_result["returncode"] == 0
    assert "after" in after_result["output"]

    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert status_events[-1]["lifecycle_state"] == "waiting_for_command"

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["exit_status"] == "waiting_for_command"
    assert any("boom" in _observation_text(message) for message in artifact["messages"])


def test_waiting_for_command_lifecycle_is_owned_by_mas_interactive_agent():
    import minisweagent.mas.mas_agent as workflows

    assert hasattr(workflows, "MasInteractiveAgent")
    assert not issubclass(workflows.MasInteractiveAgent, workflows.MasAgent)
    assert not hasattr(workflows.MasAgent, "record_waiting_for_command")
    assert callable(workflows.MasInteractiveAgent.run_until_idle)


def test_child_agent_workflow_without_execution_config_fails_with_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "inspect api",
        parent_agent_id="mas-0123456789abcdef",
    )

    assert result["agent_id"] == "mas-1111111111111111"
    assert result["parent_agent_id"] == "mas-0123456789abcdef"
    assert result["status"] == "failed"
    assert result["terminal_state"] == "failed"
    assert result["mas_error"]["code"] == "missing_agent_execution_config"
    assert result["agent_artifact_directory"] == ".mini-mas/agents/mas-1111111111111111"
    assert result["trajectory_artifact_path"] == ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["parent_agent_id"] == "mas-0123456789abcdef"
    assert artifact["info"]["agent_id"] == "mas-1111111111111111"
    assert "workflow_id" not in artifact["info"]
    assert artifact["info"]["agent_artifact_directory"] == ".mini-mas/agents/mas-1111111111111111"


def test_child_agent_trajectory_redacts_agent_execution_config_env_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows

    config = {
        "schema_version": 1,
        "agent": {
            "system_template": "System",
            "instance_template": "Task {{task}}",
            "step_limit": 0,
            "cost_limit": 3.0,
        },
        "model": {
            "model_class": "deterministic",
            "model_name": "deterministic",
            "outputs": [
                {
                    "role": "exit",
                    "content": "done",
                    "extra": {"exit_status": "failed", "submission": ""},
                }
            ],
            "observation_template": "{{output.output}}",
            "format_error_template": "{{error}}",
        },
        "environment": {
            "environment_class": "local",
            "cwd": tmp_path.as_posix(),
            "env": {"PAGER": "cat"},
            "timeout": 30,
        },
    }

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "hit limit",
        parent_agent_id="mas-0123456789abcdef",
        agent_execution_config=config,
    )

    assert result["terminal_state"] == "failed"
    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    recorded_config = artifact["info"]["agent_execution_config"]
    assert recorded_config["environment"]["env"] == {"PAGER": "<redacted>"}
    assert config["environment"]["env"] == {"PAGER": "cat"}


def test_root_agent_workflow_is_registered_as_dbos_workflow_when_module_loads():
    """The root workflow is defined inside the MAS subsystem boundary."""
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.mas_agent

        importlib.reload(minisweagent.mas.mas_agent)

    dbos_module.DBOS.workflow.assert_called()

def test_ai_agent_workflow_queue_is_registered_for_child_agent_startup_when_module_loads():
    """Spawned autonomous Child Agents are queued on the AI Agent workflow queue."""
    dbos_module = _mock_dbos_module()
    queue = MagicMock()
    dbos_module.Queue.return_value = queue

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.mas_agent

        importlib.reload(minisweagent.mas.mas_agent)

    assert dbos_module.Queue.call_args_list
    assert {call.args[0] for call in dbos_module.Queue.call_args_list} == {AI_AGENT_WORKFLOW_QUEUE_NAME}
    assert minisweagent.mas.mas_agent.ai_agent_workflow_queue is queue

def test_agent_workflows_are_async_dbos_workflows():
    import minisweagent.mas.mas_agent as workflows

    assert inspect.iscoroutinefunction(getattr(workflows.root_agent_workflow, "__wrapped__", workflows.root_agent_workflow))
    assert inspect.iscoroutinefunction(
        getattr(workflows.child_agent_workflow, "__wrapped__", workflows.child_agent_workflow)
    )

def test_agent_workflow_entrypoints_delegate_to_plain_mas_agent(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows

    mas_agent_class = workflows.MasAgent
    created_agents = []
    run_calls = []

    class RecordingMasAgent:
        def __init__(
            self,
            *,
            agent_id,
            parent_agent_id=None,
            model,
            env,
            step_limit,
            agent_execution_config=None,
        ):
            self.agent_id = agent_id
            self.parent_agent_id = parent_agent_id
            self.model = model
            self.env = env
            self.step_limit = step_limit
            self.agent_execution_config = agent_execution_config
            created_agents.append(self)

        async def run(self, *, task="", initial_messages=None):
            run_calls.append((self.agent_id, task, initial_messages))
            return {
                "status": "recorded",
                "terminal_state": "recorded",
                "agent_id": self.agent_id,
                **({"parent_agent_id": self.parent_agent_id} if self.parent_agent_id else {}),
                "task": task,
                "initial_messages": initial_messages,
            }

    monkeypatch.setattr(workflows, "MasAgent", RecordingMasAgent)

    result = _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=Mock(),
        env=Mock(),
        task="delegate through agent",
        step_limit=7,
        initial_messages=[{"role": "user", "content": "seed"}],
    )

    assert result == {
        "status": "recorded",
        "terminal_state": "recorded",
        "agent_id": "mas-0123456789abcdef",
        "task": "delegate through agent",
        "initial_messages": [{"role": "user", "content": "seed"}],
    }
    assert len(created_agents) == 1
    assert created_agents[0].model is not None
    assert created_agents[0].env is not None
    assert created_agents[0].step_limit == 7
    assert run_calls == [
        ("mas-0123456789abcdef", "delegate through agent", [{"role": "user", "content": "seed"}])
    ]

    child_result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "child task",
        parent_agent_id="mas-0123456789abcdef",
        agent_execution_config=_agent_execution_config(tmp_path, step_limit=5),
    )

    assert child_result["agent_id"] == "mas-1111111111111111"
    assert child_result["parent_agent_id"] == "mas-0123456789abcdef"
    assert child_result["task"] == "child task"
    assert len(created_agents) == 2
    assert created_agents[1].model is None
    assert created_agents[1].env is None
    assert created_agents[1].step_limit == 0
    assert created_agents[1].agent_execution_config["model"]["model_name"] == "deterministic"
    assert created_agents[1].agent_execution_config["agent"]["step_limit"] == 5
    assert run_calls[-1] == ("mas-1111111111111111", "child task", None)
    assert not hasattr(mas_agent_class, "__dbos_class_info__")
    for method_name in ("run", "step", "query", "execute_actions", "add_messages", "get_template_vars"):
        assert callable(getattr(mas_agent_class, method_name))

def test_model_bash_and_trajectory_operations_are_registered_as_dbos_steps():
    """Model calls, ordinary bash execution, and trajectory persistence are checkpointed as DBOS steps."""
    dbos_module = _mock_recording_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.mas_agent

        importlib.reload(minisweagent.mas.mas_agent)

    assert "query_model_step" in dbos_module.registered_steps
    assert "execute_bash_step" in dbos_module.registered_steps
    assert "save_trajectory_artifact_step" in dbos_module.registered_steps
    assert "save_root_trajectory_artifact_step" not in dbos_module.registered_steps
    assert "save_child_trajectory_artifact_step" not in dbos_module.registered_steps

def test_agent_workflow_publishes_running_submission_and_limits_status(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows
    from minisweagent.exceptions import Submitted

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(key, value):
        published.append((key, value))

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "set_event",
        Mock(side_effect=AssertionError("Agent status publishing must use set_event_async")),
    )

    model = DeterministicModel(outputs=[make_output("submit", [{"command": "submit"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = Submitted(
        {
            "role": "exit",
            "content": "done",
            "extra": {"exit_status": "Submitted", "submission": "done"},
        }
    )

    _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="submit once",
        step_limit=3,
    )

    assert [event[0] for event in published] == ["mini_mas_status", "mini_mas_status"]
    assert published[0][1]["lifecycle_state"] == "running"
    assert published[0][1]["agent_id"] == "mas-0123456789abcdef"
    assert published[1][1]["lifecycle_state"] == "closed"
    assert published[1][1]["latest_submission"] == "done"
    assert "messages" not in published[1][1]

    published.clear()
    limit_model = DeterministicModel(outputs=[make_output("work", [{"command": "echo hi"}], cost=0.1)])
    limit_env = Mock()
    limit_env.get_template_vars.return_value = {}
    limit_env.execute.return_value = {"output": "hi\n", "returncode": 0, "exception_info": ""}

    _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=limit_model,
        env=limit_env,
        task="hit limit",
        step_limit=1,
    )

    assert published[-1][1]["lifecycle_state"] == "limits_exceeded"

def test_agent_workflow_publishes_failed_status(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows
    from minisweagent.exceptions import InterruptAgentFlow

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(_key, value):
        published.append(value)

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "set_event",
        Mock(side_effect=AssertionError("Agent status publishing must use set_event_async")),
    )

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}

    async def failing_model(_model, _messages):
        raise InterruptAgentFlow(
            {
                "role": "exit",
                "content": "model failed",
                "extra": {"exit_status": "failed", "submission": ""},
            }
        )

    monkeypatch.setattr(workflows, "query_model_step", failing_model)

    _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="fail",
        step_limit=3,
    )

    assert published[-1]["lifecycle_state"] == "failed"
    assert published[-1]["latest_error"] == "model failed"

def test_child_workflow_waits_after_first_submission_and_sets_first_observable_event(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows
    from minisweagent.exceptions import Submitted

    monkeypatch.chdir(tmp_path)
    published = []
    received = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-1111111111111111")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        received.append((topic, timeout_seconds))
        return {"type": "test_stop_waiting"}

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv",
        Mock(side_effect=AssertionError("Child waiting must use recv_async")),
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send_async",
        Mock(side_effect=AssertionError("Child status must not use child-to-parent send")),
    )

    monkeypatch.setattr(
        workflows,
        "execute_bash_from_config_step",
        Mock(
            side_effect=Submitted(
                {
                    "role": "exit",
                    "content": "child done",
                    "extra": {"exit_status": "Submitted", "submission": "child done"},
                }
            )
        ),
    )
    config = _agent_execution_config(
        tmp_path,
        outputs=[make_output("submit", [{"command": "submit"}], cost=0.1)],
        step_limit=3,
    )

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "submit once",
        parent_agent_id="mas-0123456789abcdef",
        agent_execution_config=config,
    )

    assert result["terminal_state"] == "waiting_for_parent"
    assert result["latest_submission"] == "child done"
    assert received == [(PARENT_DIRECTION_TOPIC, PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS)]
    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == ["running", "waiting_for_parent"]
    waiting_event = status_events[-1]
    assert waiting_event["agent_id"] == "mas-1111111111111111"
    assert waiting_event["latest_submission"] == "child done"
    assert (
        waiting_event["trajectory_artifact_path"]
        == ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
    )
    first_observable_events = [value for key, value in published if key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable_events == [waiting_event]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["exit_status"] == "waiting_for_parent"
    assert artifact["info"]["submission"] == "child done"
    assert artifact["messages"][-1]["extra"] == {"exit_status": "Submitted", "submission": "child done"}

def test_child_workflow_receives_close_and_publishes_closed_status(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows
    from minisweagent.exceptions import Submitted

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-1111111111111111")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        assert topic == PARENT_DIRECTION_TOPIC
        assert timeout_seconds == PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS
        return {
            "type": "close",
            "signal_type": "mas_close",
            "source_workflow_id": "mas-0123456789abcdef",
            "target_workflow_id": "mas-1111111111111111",
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv",
        Mock(side_effect=AssertionError("Child close waiting must use recv_async")),
    )

    monkeypatch.setattr(
        workflows,
        "execute_bash_from_config_step",
        Mock(
            side_effect=Submitted(
                {
                    "role": "exit",
                    "content": "child done",
                    "extra": {"exit_status": "Submitted", "submission": "child done"},
                }
            )
        ),
    )
    config = _agent_execution_config(
        tmp_path,
        outputs=[make_output("submit", [{"command": "submit"}], cost=0.1)],
        step_limit=3,
    )

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "submit once",
        parent_agent_id="mas-0123456789abcdef",
        agent_execution_config=config,
    )

    assert result["status"] == "closed"
    assert result["terminal_state"] == "closed"
    assert result["latest_submission"] == "child done"
    assert result["parent_direction_signal"]["signal_type"] == "mas_close"

    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == ["running", "waiting_for_parent", "closed"]
    closed_event = status_events[-1]
    assert closed_event["latest_submission"] == "child done"
    assert closed_event["trajectory_artifact_path"] == result["trajectory_artifact_path"]

    first_observable_events = [value for key, value in published if key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY]
    assert [event["lifecycle_state"] for event in first_observable_events] == ["waiting_for_parent"]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["exit_status"] == "closed"
    assert artifact["info"]["submission"] == "child done"
    assert artifact["messages"][-1]["extra"] == {"exit_status": "Submitted", "submission": "child done"}

def test_child_workflow_sets_first_observable_event_for_failure_and_limits(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows
    from minisweagent.exceptions import InterruptAgentFlow

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-1111111111111111")

    async def set_event_async(key, value):
        published.append((key, value))

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv_async",
        Mock(side_effect=AssertionError("Failed or limited child should not wait for parent direction")),
    )

    async def failing_model(_model_config, _messages, _query_index):
        raise InterruptAgentFlow(
            {
                "role": "exit",
                "content": "model failed",
                "extra": {"exit_status": "failed", "submission": ""},
            }
        )

    monkeypatch.setattr(workflows, "query_model_from_config_step", failing_model)

    _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "fail",
        parent_agent_id="mas-0123456789abcdef",
        agent_execution_config=_agent_execution_config(tmp_path, step_limit=3),
    )

    first_observable = [value for key, value in published if key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable == [
        {
            "agent_id": "mas-1111111111111111",
            "parent_agent_id": "mas-0123456789abcdef",
            "lifecycle_state": "failed",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": (
                ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
            ),
            "latest_error": "model failed",
        }
    ]

    published.clear()

    async def replay_model_response(_model_config, _messages, _query_index):
        return make_output("work", [{"command": "echo hi"}], cost=0.1)

    monkeypatch.setattr(workflows, "query_model_from_config_step", replay_model_response)
    monkeypatch.setattr(
        workflows,
        "execute_bash_from_config_step",
        lambda _environment_config, _action: {"output": "hi\n", "returncode": 0, "exception_info": ""},
    )

    _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-2222222222222222",
        "hit limit",
        parent_agent_id="mas-0123456789abcdef",
        agent_execution_config=_agent_execution_config(tmp_path, step_limit=1),
    )

    first_observable = [value for key, value in published if key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable[-1]["agent_id"] == "mas-2222222222222222"
    assert first_observable[-1]["lifecycle_state"] == "limits_exceeded"

def test_root_agent_workflow_runs_model_and_bash_path_and_saves_trajectory(tmp_path, monkeypatch):
    from minisweagent.exceptions import Submitted
    from minisweagent.mas.mas_agent import root_agent_workflow

    monkeypatch.chdir(tmp_path)
    model = DeterministicModel(
        outputs=[
            make_output("inspect", [{"command": "echo hello"}], cost=0.25),
            make_output("submit", [{"command": "submit"}], cost=0.25),
        ],
        cost_per_call=0.25,
    )
    env = Mock()
    env.get_template_vars.return_value = {"cwd": tmp_path.as_posix()}
    env.serialize.return_value = {"info": {"config": {"environment_type": "deterministic-env"}}}
    env.execute.side_effect = [
        {"output": "hello\n", "returncode": 0, "exception_info": ""},
        Submitted(
            {
                "role": "exit",
                "content": "done",
                "extra": {"exit_status": "Submitted", "submission": "done"},
            }
        ),
    ]

    result = _call_root_agent_workflow(
        root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="exercise ordinary path",
        step_limit=3,
    )

    assert result["terminal_state"] == "Submitted"
    assert result["submission"] == "done"
    assert result["model_stats"] == {"instance_cost": 0.5, "api_calls": 2}
    trajectory_path = tmp_path / result["trajectory_artifact_path"]
    artifact = json.loads(trajectory_path.read_text())
    assert artifact["info"]["exit_status"] == "Submitted"
    assert artifact["info"]["submission"] == "done"
    assert artifact["info"]["model_stats"] == {"instance_cost": 0.5, "api_calls": 2}
    assert artifact["messages"][2]["content"] == "inspect"
    assert "hello" in _observation_text(artifact["messages"][3])
    assert artifact["messages"][-1]["extra"] == {"exit_status": "Submitted", "submission": "done"}

def test_root_agent_workflow_can_replay_successful_model_and_bash_step_results(tmp_path, monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    monkeypatch.chdir(tmp_path)
    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}

    def replay_model_response(_model, _messages):
        return make_output("replayed model", [{"command": "echo replay"}], cost=0.1)

    def replay_bash_output(_env, _action):
        return {"output": "replayed output\n", "returncode": 0, "exception_info": ""}

    monkeypatch.setattr(workflows, "query_model_step", replay_model_response)
    monkeypatch.setattr(workflows, "execute_bash_step", replay_bash_output)

    result = _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="replay checkpoints",
        step_limit=1,
    )

    env.execute.assert_not_called()
    assert result["terminal_state"] == "limits_exceeded"
    trajectory_path = tmp_path / result["trajectory_artifact_path"]
    artifact = json.loads(trajectory_path.read_text())
    assert artifact["info"]["exit_status"] == "limits_exceeded"
    assert artifact["info"]["model_stats"] == {"instance_cost": 0.1, "api_calls": 1}
    assert artifact["messages"][2]["content"] == "replayed model"
    assert "replayed output" in _observation_text(artifact["messages"][3])
    assert artifact["messages"][-1]["extra"] == {"exit_status": "limits_exceeded", "submission": ""}

def test_root_agent_workflow_keeps_standalone_mas_commands_out_of_bash_step(tmp_path, monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    monkeypatch.chdir(tmp_path)
    model = DeterministicModel(outputs=[make_output("check status", [{"command": "mini-mas status"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    bash_step = Mock(side_effect=AssertionError("standalone MAS command entered bash step"))
    monkeypatch.setattr(workflows, "execute_bash_step", bash_step)

    result = _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="route mas command",
        step_limit=1,
    )

    env.execute.assert_not_called()
    bash_step.assert_not_called()
    assert result["terminal_state"] == "limits_exceeded"
    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert "Direct Child Agents for: mas-0123456789abcdef" in _observation_text(artifact["messages"][3])

def test_child_workflow_injects_continuation_and_resumes_existing_trajectory(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows
    from minisweagent.exceptions import Submitted

    monkeypatch.chdir(tmp_path)
    published = []
    received = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-1111111111111111")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        received.append((topic, timeout_seconds))
        if len(received) == 1:
            return {
                "type": "continuation",
                "signal_type": "mas_continuation",
                "content": "please revise",
                "source_workflow_id": "mas-0123456789abcdef",
                "target_workflow_id": "mas-1111111111111111",
            }
        return {"type": "test_stop_waiting"}

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv",
        Mock(side_effect=AssertionError("Child continuation waiting must use recv_async")),
    )

    bash_results = iter(
        [
            Submitted(
                {
                    "role": "exit",
                    "content": "first submission",
                    "extra": {"exit_status": "Submitted", "submission": "first submission"},
                }
            ),
            Submitted(
                {
                    "role": "exit",
                    "content": "second submission",
                    "extra": {"exit_status": "Submitted", "submission": "second submission"},
                }
            ),
        ]
    )
    monkeypatch.setattr(
        workflows,
        "execute_bash_from_config_step",
        Mock(side_effect=bash_results),
    )
    config = _agent_execution_config(
        tmp_path,
        outputs=[
            make_output("first", [{"command": "submit first"}], cost=0.1),
            make_output("second", [{"command": "submit second"}], cost=0.1),
        ],
        step_limit=4,
    )

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "submit once",
        parent_agent_id="mas-0123456789abcdef",
        agent_execution_config=config,
    )

    assert result["terminal_state"] == "waiting_for_parent"
    assert result["latest_submission"] == "second submission"
    assert len(received) == 2
    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == [
        "running",
        "waiting_for_parent",
        "running",
        "waiting_for_parent",
    ]
    assert status_events[-1]["latest_submission"] == "second submission"

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    messages = artifact["messages"]
    continuation_messages = [
        message
        for message in messages
        if message.get("role") == "user"
        and message.get("extra", {}).get("mas", {}).get("signal_type") == "mas_continuation"
    ]
    assert len(continuation_messages) == 1
    assert continuation_messages[0]["content"] == "please revise"
    assert continuation_messages[0]["extra"]["mas"]["source_workflow_id"] == "mas-0123456789abcdef"
    assert messages[-1]["extra"] == {"exit_status": "Submitted", "submission": "second submission"}
    assert artifact["info"]["exit_status"] == "waiting_for_parent"
    assert artifact["info"]["submission"] == "second submission"

def test_child_workflow_publishes_terminal_status_after_continuation(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows
    from minisweagent.exceptions import InterruptAgentFlow, Submitted

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-1111111111111111")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        assert topic == PARENT_DIRECTION_TOPIC
        assert timeout_seconds == PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS
        return {
            "type": "continuation",
            "signal_type": "mas_continuation",
            "content": "try again",
            "source_workflow_id": "mas-0123456789abcdef",
            "target_workflow_id": "mas-1111111111111111",
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))

    monkeypatch.setattr(
        workflows,
        "execute_bash_from_config_step",
        Mock(
            side_effect=[
                Submitted(
                    {
                        "role": "exit",
                        "content": "first submission",
                        "extra": {"exit_status": "Submitted", "submission": "first submission"},
                    }
                )
            ]
        ),
    )

    original_query_model_from_config_step = workflows.query_model_from_config_step

    async def query_model_step(model_config, messages, query_index):
        if any(message.get("extra", {}).get("mas", {}).get("signal_type") == "mas_continuation" for message in messages):
            raise InterruptAgentFlow(
                {
                    "role": "exit",
                    "content": "model failed after continuation",
                    "extra": {"exit_status": "failed", "submission": ""},
                }
            )
        return await original_query_model_from_config_step(model_config, messages, query_index)

    monkeypatch.setattr(workflows, "query_model_from_config_step", query_model_step)
    config = _agent_execution_config(
        tmp_path,
        outputs=[make_output("first", [{"command": "submit first"}], cost=0.1)],
        step_limit=4,
    )

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "submit once",
        parent_agent_id="mas-0123456789abcdef",
        agent_execution_config=config,
    )

    assert result["terminal_state"] == "failed"
    assert result["status"] == "failed"
    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert status_events[-1]["lifecycle_state"] == "failed"
    assert status_events[-1]["latest_error"] == "model failed after continuation"
    first_observable_events = [value for key, value in published if key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY]
    assert [event["lifecycle_state"] for event in first_observable_events] == ["waiting_for_parent", "failed"]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["exit_status"] == "failed"
    assert artifact["messages"][-1]["content"] == "model failed after continuation"
