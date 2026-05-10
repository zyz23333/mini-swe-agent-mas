import importlib
import inspect
import json
from unittest.mock import Mock, patch

from minisweagent.mas import status_events as mas_status_events
from minisweagent.mas.signals import (
    PARENT_DIRECTION_TOPIC,
    PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS,
)
from minisweagent.models.test_models import (
    DeterministicModel,
    make_output,
)

from .helpers import (
    _call_root_agent_workflow,
    _mock_dbos_module,
    _mock_recording_dbos_module,
    _observation_text,
)


def test_root_agent_workflow_writes_trajectory_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows

    result = _call_root_agent_workflow(workflows.root_agent_workflow, "mas-0123456789abcdef")

    assert result == {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef",
        "status": "started",
        "terminal_state": "started",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef.traj.json",
    }
    trajectory_path = tmp_path / result["trajectory_artifact_path"]
    assert trajectory_path.exists()
    artifact = json.loads(trajectory_path.read_text())
    assert artifact["info"]["workflow_id"] == "mas-0123456789abcdef"
    assert artifact["info"]["run_directory"] == ".mini-mas/runs/mas-0123456789abcdef"

def test_child_agent_workflow_writes_artifact_under_root_run_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.mas_agent as workflows

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "inspect api",
    )

    assert result == {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef-c001",
        "status": "started",
        "terminal_state": "started",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json",
    }
    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["root_workflow_id"] == "mas-0123456789abcdef"
    assert artifact["info"]["workflow_id"] == "mas-0123456789abcdef-c001"
    assert artifact["info"]["run_directory"] == ".mini-mas/runs/mas-0123456789abcdef"

def test_root_agent_workflow_is_registered_as_dbos_workflow_when_module_loads():
    """The root workflow is defined inside the MAS subsystem boundary."""
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.mas_agent

        importlib.reload(minisweagent.mas.mas_agent)

    dbos_module.DBOS.workflow.assert_called()

def test_agent_workflows_are_async_dbos_workflows():
    import minisweagent.mas.mas_agent as workflows

    assert inspect.iscoroutinefunction(getattr(workflows.root_agent_workflow, "__wrapped__", workflows.root_agent_workflow))
    assert inspect.iscoroutinefunction(
        getattr(workflows.child_agent_workflow, "__wrapped__", workflows.child_agent_workflow)
    )

def test_agent_workflow_entrypoints_delegate_to_plain_mas_agent(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    mas_agent_class = workflows.MasAgent
    created_agents = []
    run_calls = []

    class RecordingMasAgent:
        def __init__(self, *, root_workflow_id, workflow_id, model, env, step_limit):
            self.root_workflow_id = root_workflow_id
            self.workflow_id = workflow_id
            self.model = model
            self.env = env
            self.step_limit = step_limit
            created_agents.append(self)

        async def run(self, *, task="", initial_messages=None):
            run_calls.append((self.workflow_id, task, initial_messages))
            return {
                "status": "recorded",
                "terminal_state": "recorded",
                "root_workflow_id": self.root_workflow_id,
                "workflow_id": self.workflow_id,
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
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef",
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
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "child task",
        model=Mock(),
        env=Mock(),
        step_limit=5,
    )

    assert child_result["root_workflow_id"] == "mas-0123456789abcdef"
    assert child_result["workflow_id"] == "mas-0123456789abcdef-c001"
    assert child_result["task"] == "child task"
    assert len(created_agents) == 2
    assert created_agents[1].step_limit == 5
    assert run_calls[-1] == ("mas-0123456789abcdef-c001", "child task", None)
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
    assert "save_root_trajectory_artifact_step" in dbos_module.registered_steps
    assert "save_child_trajectory_artifact_step" in dbos_module.registered_steps

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
        Mock(side_effect=AssertionError("Agent Workflow status publishing must use set_event_async")),
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
    assert published[0][1]["workflow_tree_id"] == "mas-0123456789abcdef"
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
        Mock(side_effect=AssertionError("Agent Workflow status publishing must use set_event_async")),
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
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

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

    model = DeterministicModel(outputs=[make_output("submit", [{"command": "submit"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = Submitted(
        {
            "role": "exit",
            "content": "child done",
            "extra": {"exit_status": "Submitted", "submission": "child done"},
        }
    )

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "submit once",
        model=model,
        env=env,
        step_limit=3,
    )

    assert result["terminal_state"] == "waiting_for_parent"
    assert result["latest_submission"] == "child done"
    assert received == [(PARENT_DIRECTION_TOPIC, PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS)]
    status_events = [value for key, value in published if key == mas_status_events.STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == ["running", "waiting_for_parent"]
    waiting_event = status_events[-1]
    assert waiting_event["workflow_id"] == "mas-0123456789abcdef-c001"
    assert waiting_event["latest_submission"] == "child done"
    assert (
        waiting_event["trajectory_artifact_path"]
        == ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
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
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        assert topic == PARENT_DIRECTION_TOPIC
        assert timeout_seconds == PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS
        return {
            "type": "close",
            "signal_type": "mas_close",
            "source_workflow_id": "mas-0123456789abcdef",
            "target_workflow_id": "mas-0123456789abcdef-c001",
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv",
        Mock(side_effect=AssertionError("Child close waiting must use recv_async")),
    )

    model = DeterministicModel(outputs=[make_output("submit", [{"command": "submit"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = Submitted(
        {
            "role": "exit",
            "content": "child done",
            "extra": {"exit_status": "Submitted", "submission": "child done"},
        }
    )

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "submit once",
        model=model,
        env=env,
        step_limit=3,
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
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

    async def set_event_async(key, value):
        published.append((key, value))

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv_async",
        Mock(side_effect=AssertionError("Failed or limited child should not wait for parent direction")),
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
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "fail",
        model=model,
        env=env,
        step_limit=3,
    )

    first_observable = [value for key, value in published if key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable == [
        {
            "root_workflow_id": "mas-0123456789abcdef",
            "workflow_id": "mas-0123456789abcdef-c001",
            "workflow_tree_id": "mas-0123456789abcdef-c001",
            "lifecycle_state": "failed",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
            "latest_error": "model failed",
        }
    ]

    published.clear()

    async def replay_model_response(_model, _messages):
        return make_output("work", [{"command": "echo hi"}], cost=0.1)

    monkeypatch.setattr(workflows, "query_model_step", replay_model_response)
    monkeypatch.setattr(
        workflows,
        "execute_bash_step",
        lambda _env, _action: {"output": "hi\n", "returncode": 0, "exception_info": ""},
    )

    _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c002",
        "hit limit",
        model=model,
        env=env,
        step_limit=1,
    )

    first_observable = [value for key, value in published if key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable[-1]["workflow_id"] == "mas-0123456789abcdef-c002"
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
    assert "Direct Child Agent Workflows for: mas-0123456789abcdef" in _observation_text(artifact["messages"][3])

def test_child_workflow_injects_continuation_and_resumes_existing_trajectory(monkeypatch, tmp_path):
    import minisweagent.mas.mas_agent as workflows
    from minisweagent.exceptions import Submitted

    monkeypatch.chdir(tmp_path)
    published = []
    received = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

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
                "target_workflow_id": "mas-0123456789abcdef-c001",
            }
        return {"type": "test_stop_waiting"}

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv",
        Mock(side_effect=AssertionError("Child continuation waiting must use recv_async")),
    )

    model = DeterministicModel(
        outputs=[
            make_output("first", [{"command": "submit first"}], cost=0.1),
            make_output("second", [{"command": "submit second"}], cost=0.1),
        ]
    )
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = [
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

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "submit once",
        model=model,
        env=env,
        step_limit=4,
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
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

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
            "target_workflow_id": "mas-0123456789abcdef-c001",
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))

    model = DeterministicModel(outputs=[make_output("first", [{"command": "submit first"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = Submitted(
        {
            "role": "exit",
            "content": "first submission",
            "extra": {"exit_status": "Submitted", "submission": "first submission"},
        }
    )

    async def query_model_step(_model, messages):
        if any(message.get("extra", {}).get("mas", {}).get("signal_type") == "mas_continuation" for message in messages):
            raise InterruptAgentFlow(
                {
                    "role": "exit",
                    "content": "model failed after continuation",
                    "extra": {"exit_status": "failed", "submission": ""},
                }
            )
        return _model.query(messages)

    monkeypatch.setattr(workflows, "query_model_step", query_model_step)

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "submit once",
        model=model,
        env=env,
        step_limit=4,
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
