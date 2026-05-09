import asyncio
import importlib
import inspect
import json
import re
from unittest.mock import MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from minisweagent.mas.cli import app, run, status
from minisweagent.mas.runtime import make_root_workflow_id
from minisweagent.models.test_models import (
    DeterministicModel,
    DeterministicResponseAPIToolcallModel,
    DeterministicToolcallModel,
    make_output,
    make_response_api_output,
    make_toolcall_output,
)


def _mock_dbos_module() -> MagicMock:
    dbos_module = MagicMock()
    dbos_module.DBOS.workflow.return_value = lambda func: func
    dbos_module.DBOS.step.return_value = lambda func: func
    return dbos_module


def _mock_recording_dbos_module() -> MagicMock:
    dbos_module = MagicMock()
    dbos_module.registered_steps = []
    dbos_module.DBOS.workflow.return_value = lambda func: func

    def record_step(func):
        dbos_module.registered_steps.append(func.__name__)
        return func

    dbos_module.DBOS.step.return_value = record_step
    return dbos_module


def _observation_text(message: dict) -> str:
    if message.get("type") == "function_call_output":
        return message["output"]
    content = message.get("content", "")
    if isinstance(content, list):
        return content[0]["text"]
    return content


def _call_root_agent_workflow(workflow_func, *args, **kwargs):
    while hasattr(workflow_func, "__wrapped__"):
        workflow_func = workflow_func.__wrapped__
    return asyncio.run(workflow_func(*args, **kwargs))


def _recording_child_queue():
    class RecordingChildQueue:
        def __init__(self):
            self.enqueued = []

        async def enqueue_async(self, workflow_func, *args, **kwargs):
            handle = Mock()
            handle.workflow_id = args[1]
            handle.get_workflow_id.return_value = args[1]
            self.enqueued.append(
                {
                    "workflow_func": workflow_func,
                    "args": args,
                    "kwargs": kwargs,
                    "handle": handle,
                }
            )
            return handle

    return RecordingChildQueue()


class AsyncMockHandle:
    def __init__(self, workflow_id, result=None):
        self.workflow_id = workflow_id
        self._result = result

    def get_workflow_id(self):
        return self.workflow_id

    async def get_result(self):
        return self._result


def test_mini_mas_run_initializes_launches_and_starts_root_workflow():
    """mini-mas run is the external path that activates DBOS for MAS work."""
    handle = AsyncMockHandle(
        "mas-1111111111111111",
        {
            "root_workflow_id": "mas-1111111111111111",
            "workflow_id": "mas-1111111111111111",
            "status": "started",
            "run_directory": ".mini-mas/runs/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
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
        "root_workflow_id": "mas-1111111111111111",
        "workflow_id": "mas-1111111111111111",
        "run_directory": ".mini-mas/runs/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
        "result": {
            "root_workflow_id": "mas-1111111111111111",
            "workflow_id": "mas-1111111111111111",
            "status": "started",
            "run_directory": ".mini-mas/runs/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
        },
    }


def test_mini_mas_run_returns_detached_metadata_without_waiting_for_result():
    handle = AsyncMockHandle(
        "mas-1111111111111111",
        {
            "root_workflow_id": "mas-1111111111111111",
            "workflow_id": "mas-1111111111111111",
            "status": "started",
            "run_directory": ".mini-mas/runs/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
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
        "root_workflow_id": "mas-1111111111111111",
        "workflow_id": "mas-1111111111111111",
        "run_directory": ".mini-mas/runs/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
    }


def test_mini_mas_run_cli_outputs_artifact_locations():
    handle = AsyncMockHandle(
        "mas-2222222222222222",
        {
            "root_workflow_id": "mas-2222222222222222",
            "workflow_id": "mas-2222222222222222",
            "status": "started",
            "run_directory": ".mini-mas/runs/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/runs/mas-2222222222222222/trajectories/mas-2222222222222222.traj.json",
        },
    )

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        cli_result = CliRunner().invoke(app, ["run", "--workflow-id", "mas-2222222222222222"])

    assert cli_result.exit_code == 0
    assert "root_workflow_id: mas-2222222222222222" in cli_result.stdout
    assert "workflow_id: mas-2222222222222222" in cli_result.stdout
    assert "run_directory: .mini-mas/runs/mas-2222222222222222" in cli_result.stdout
    assert (
        "trajectory_artifact_path: .mini-mas/runs/mas-2222222222222222/trajectories/mas-2222222222222222.traj.json"
        in cli_result.stdout
    )


def test_mini_mas_status_cli_outputs_root_tree(monkeypatch):
    tree = [
        {
            "workflow_id": "mas-2222222222222222",
            "root_workflow_id": "mas-2222222222222222",
            "lifecycle_state": "running",
            "run_directory": ".mini-mas/runs/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/runs/mas-2222222222222222/trajectories/mas-2222222222222222.traj.json",
        },
        {
            "workflow_id": "mas-2222222222222222-c001",
            "root_workflow_id": "mas-2222222222222222",
            "lifecycle_state": "closed",
            "latest_submission": "child done",
            "run_directory": ".mini-mas/runs/mas-2222222222222222",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-2222222222222222/trajectories/mas-2222222222222222-c001.traj.json"
            ),
        },
    ]
    monkeypatch.setattr(
        "minisweagent.mas.cli.get_agent_workflow_status",
        Mock(
            return_value={
                "kind": "tree",
                "root_workflow_id": "mas-2222222222222222",
                "snapshots": tree,
            }
        ),
    )

    result = status("mas-2222222222222222")

    assert result["kind"] == "tree"
    cli_result = CliRunner().invoke(app, ["status", "mas-2222222222222222"])
    assert cli_result.exit_code == 0
    assert "Agent Workflow Tree: mas-2222222222222222" in cli_result.stdout
    assert "workflow_id: mas-2222222222222222-c001" in cli_result.stdout
    assert "latest_submission: child done" in cli_result.stdout


def test_mini_mas_status_cli_reports_missing_descendant(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.get_agent_workflow_status",
        Mock(
            return_value={
                "kind": "missing",
                "root_workflow_id": "mas-2222222222222222",
                "workflow_id": "mas-2222222222222222-c999",
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["status", "mas-2222222222222222-c999"])

    assert cli_result.exit_code == 1
    assert "Workflow not found in current Agent Workflow Tree: mas-2222222222222222-c999" in cli_result.stdout


def test_root_workflow_ids_use_mas_16_hex_shape():
    generated_ids = [make_root_workflow_id() for _ in range(20)]

    assert all(re.fullmatch(r"mas-[0-9a-f]{16}", workflow_id) for workflow_id in generated_ids)


def test_run_and_trajectory_artifact_paths_are_deterministic():
    from minisweagent.mas.artifacts import make_run_directory, make_trajectory_artifact_path

    run_directory = make_run_directory("mas-0123456789abcdef")
    trajectory_path = make_trajectory_artifact_path(run_directory, "mas-0123456789abcdef")

    assert run_directory.as_posix() == ".mini-mas/runs/mas-0123456789abcdef"
    assert (
        trajectory_path.as_posix()
        == ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef.traj.json"
    )


def test_trajectory_artifact_save_overwrites_same_workflow_path(tmp_path, monkeypatch):
    from minisweagent.mas.artifacts import (
        make_run_directory,
        make_trajectory_artifact_path,
        save_trajectory_artifact,
    )

    monkeypatch.chdir(tmp_path)
    run_directory = make_run_directory("mas-0123456789abcdef")
    trajectory_path = make_trajectory_artifact_path(run_directory, "mas-0123456789abcdef")

    first_path = save_trajectory_artifact(
        root_workflow_id="mas-0123456789abcdef",
        workflow_id="mas-0123456789abcdef",
        status="started",
    )
    second_path = save_trajectory_artifact(
        root_workflow_id="mas-0123456789abcdef",
        workflow_id="mas-0123456789abcdef",
        status="complete",
    )

    assert first_path == trajectory_path
    assert second_path == trajectory_path
    assert list(run_directory.rglob("*.traj.json")) == [trajectory_path]
    assert json.loads(trajectory_path.read_text())["info"]["exit_status"] == "complete"


def test_root_agent_workflow_writes_trajectory_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.workflows as workflows

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

    import minisweagent.mas.workflows as workflows

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
        import minisweagent.mas.workflows

        importlib.reload(minisweagent.mas.workflows)

    dbos_module.DBOS.workflow.assert_called()


def test_agent_workflows_are_async_dbos_workflows():
    import minisweagent.mas.workflows as workflows

    assert inspect.iscoroutinefunction(getattr(workflows.root_agent_workflow, "__wrapped__", workflows.root_agent_workflow))
    assert inspect.iscoroutinefunction(
        getattr(workflows.child_agent_workflow, "__wrapped__", workflows.child_agent_workflow)
    )


def test_model_bash_and_trajectory_operations_are_registered_as_dbos_steps():
    """Model calls, ordinary bash execution, and trajectory persistence are checkpointed as DBOS steps."""
    dbos_module = _mock_recording_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.workflows

        importlib.reload(minisweagent.mas.workflows)

    assert "query_model_step" in dbos_module.registered_steps
    assert "execute_bash_step" in dbos_module.registered_steps
    assert "save_root_trajectory_artifact_step" in dbos_module.registered_steps
    assert "save_child_trajectory_artifact_step" in dbos_module.registered_steps


@pytest.mark.parametrize(
    ("command", "expected_arguments"),
    [
        ("mini-mas status", ["status"]),
        (" mini-mas spawn 'check parser' ", ["spawn", "check parser"]),
        ("mini-mas wait --any", ["wait", "--any"]),
    ],
)
def test_standalone_mas_commands_are_detected(command, expected_arguments):
    from minisweagent.mas.commands import MasCommandKind, classify_mas_command

    parsed = classify_mas_command(command)

    assert parsed.kind == MasCommandKind.STANDALONE
    assert parsed.arguments == expected_arguments


@pytest.mark.parametrize(
    "command",
    [
        "echo mini-mas status",
        "mini-mas status && echo done",
        "mini-mas status | cat",
        "mini-mas status > out.txt",
        "DEBUG=1 mini-mas status",
        "for x in 1; do mini-mas status; done",
        "$(mini-mas status)",
    ],
)
def test_shell_compositions_containing_mini_mas_are_rejected_for_interception(command):
    from minisweagent.mas.commands import MasCommandKind, classify_mas_command

    parsed = classify_mas_command(command)

    assert parsed.kind == MasCommandKind.INVALID
    assert "standalone command" in parsed.error


@pytest.mark.parametrize("command", ["echo hello", "python -c 'print(42)'"])
def test_ordinary_bash_without_mini_mas_is_not_intercepted(command):
    from minisweagent.mas.commands import MasCommandKind, classify_mas_command

    parsed = classify_mas_command(command)

    assert parsed.kind == MasCommandKind.ORDINARY_BASH


def test_workflow_action_execution_dispatches_standalone_mas_commands():
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    message = make_output("dispatch", [{"command": "mini-mas wait --any"}])
    env = Mock()
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    assert len(observations) == 1
    assert "mini-mas wait requires Agent Workflow context" in _observation_text(observations[0])


def test_workflow_status_reports_current_tree_without_blocking(monkeypatch):
    import minisweagent.mas.workflows as workflows

    events_by_workflow = {
        "mas-0123456789abcdef": {
            "mini_mas_status": {
                "workflow_id": "mas-0123456789abcdef",
                "root_workflow_id": "mas-0123456789abcdef",
                "lifecycle_state": "running",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef.traj.json"
                ),
            }
        },
        "mas-0123456789abcdef-c001": {
            "mini_mas_status": {
                "workflow_id": "mas-0123456789abcdef-c001",
                "root_workflow_id": "mas-0123456789abcdef",
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "ready for review",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
                ),
            }
        },
    }
    async def list_workflows_async(**_kwargs):
        return [Mock(workflow_id=workflow_id) for workflow_id in events_by_workflow]

    async def get_all_events_async(workflow_id):
        return events_by_workflow[workflow_id]

    monkeypatch.setattr(workflows._dbos.DBOS, "list_workflows_async", Mock(side_effect=list_workflows_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "get_all_events_async", Mock(side_effect=get_all_events_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "list_workflows",
        Mock(side_effect=AssertionError("Agent Workflow status dispatch must use list_workflows_async")),
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_all_events",
        Mock(side_effect=AssertionError("Agent Workflow status dispatch must use get_all_events_async")),
    )

    message = make_output("status", [{"command": "mini-mas status"}])
    model = DeterministicModel(outputs=[])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=model,
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    workflows._dbos.DBOS.list_workflows_async.assert_called_once_with(
        workflow_id_prefix="mas-0123456789abcdef",
        load_input=False,
        load_output=False,
    )
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Agent Workflow Tree" in text
    assert "workflow_id: mas-0123456789abcdef" in text
    assert "lifecycle_state: running" in text
    assert "workflow_id: mas-0123456789abcdef-c001" in text
    assert "lifecycle_state: waiting_for_parent" in text
    assert "latest_submission: ready for review" in text
    assert "trajectory_artifact_path: .mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json" in text


def test_workflow_status_reports_specific_descendant_and_missing_workflow(monkeypatch):
    import minisweagent.mas.workflows as workflows

    child_status = {
        "workflow_id": "mas-0123456789abcdef-c001",
        "root_workflow_id": "mas-0123456789abcdef",
        "lifecycle_state": "failed",
        "latest_error": "model failed",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        ),
    }
    async def get_all_events_async(_workflow_id):
        return {"mini_mas_status": child_status}

    get_all_events_mock = Mock(side_effect=get_all_events_async)
    monkeypatch.setattr(workflows._dbos.DBOS, "get_all_events_async", get_all_events_mock)
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_all_events",
        Mock(side_effect=AssertionError("Agent Workflow status dispatch must use get_all_events_async")),
    )

    model = DeterministicModel(outputs=[])
    found = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("status child", [{"command": "mini-mas status mas-0123456789abcdef-c001"}]),
            model=model,
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    found_text = _observation_text(found[0])
    assert "<returncode>0</returncode>" in found_text
    assert "workflow_id: mas-0123456789abcdef-c001" in found_text
    assert "lifecycle_state: failed" in found_text
    assert "latest_error: model failed" in found_text

    async def no_events_async(_workflow_id):
        return {}

    get_all_events_mock.side_effect = no_events_async
    missing = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("missing child", [{"command": "mini-mas status mas-0123456789abcdef-c999"}]),
            model=model,
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    missing_text = _observation_text(missing[0])
    assert "<returncode>1</returncode>" in missing_text
    assert "Workflow not found in current Agent Workflow Tree: mas-0123456789abcdef-c999" in missing_text


def test_agent_workflow_publishes_running_submission_and_limits_status(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
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
    import minisweagent.mas.workflows as workflows
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
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import Submitted
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY, STATUS_EVENT_KEY

    monkeypatch.chdir(tmp_path)
    published = []
    received = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        received.append((topic, timeout_seconds))
        return {"type": "close"}

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
    assert received == [(workflows.PARENT_DIRECTION_TOPIC, workflows.PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS)]
    status_events = [value for key, value in published if key == STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == ["running", "waiting_for_parent"]
    waiting_event = status_events[-1]
    assert waiting_event["workflow_id"] == "mas-0123456789abcdef-c001"
    assert waiting_event["latest_submission"] == "child done"
    assert (
        waiting_event["trajectory_artifact_path"]
        == ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
    )
    first_observable_events = [value for key, value in published if key == FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable_events == [waiting_event]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["exit_status"] == "waiting_for_parent"
    assert artifact["info"]["submission"] == "child done"
    assert artifact["messages"][-1]["extra"] == {"exit_status": "Submitted", "submission": "child done"}


def test_child_workflow_sets_first_observable_event_for_failure_and_limits(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import InterruptAgentFlow
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY

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

    first_observable = [value for key, value in published if key == FIRST_OBSERVABLE_EVENT_KEY]
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

    first_observable = [value for key, value in published if key == FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable[-1]["workflow_id"] == "mas-0123456789abcdef-c002"
    assert first_observable[-1]["lifecycle_state"] == "limits_exceeded"


def test_workflow_action_execution_keeps_ordinary_bash_on_bash_path():
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    message = make_output("bash", [{"command": "echo hello"}])
    env = Mock()
    env.execute.return_value = {"output": "hello\n", "returncode": 0, "exception_info": ""}
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_called_once_with({"command": "echo hello"})
    assert "<returncode>0</returncode>" in _observation_text(observations[0])
    assert "hello" in _observation_text(observations[0])


@pytest.mark.parametrize(
    "command",
    [
        "echo before && mini-mas status",
        "mini-mas status | cat",
        "DEBUG=1 mini-mas status",
        "for x in 1; do mini-mas status; done",
    ],
)
def test_workflow_action_execution_rejects_shell_compositions_without_executing_bash(command):
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    message = make_output("reject", [{"command": command}])
    env = Mock()
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    text = _observation_text(observations[0])
    assert "<returncode>2</returncode>" in text
    assert "mini-mas must be issued as a standalone command" in text


@pytest.mark.parametrize(
    ("model", "message", "expected_marker"),
    [
        (
            DeterministicModel(outputs=[]),
            make_output("text", [{"command": "mini-mas status && echo no"}]),
            "role",
        ),
        (
            DeterministicToolcallModel(outputs=[]),
            make_toolcall_output(
                "tool",
                [
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command": "mini-mas status && echo no"}'},
                    }
                ],
                [{"command": "mini-mas status && echo no", "tool_call_id": "call_0"}],
            ),
            "tool_call_id",
        ),
        (
            DeterministicResponseAPIToolcallModel(outputs=[]),
            make_response_api_output(
                "responses",
                [{"command": "mini-mas status && echo no", "tool_call_id": "call_resp_0"}],
            ),
            "call_id",
        ),
    ],
)
def test_mas_rejections_use_existing_model_specific_observation_formatters(model, message, expected_marker):
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    env = Mock()

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    assert expected_marker in observations[0]
    assert "mini-mas must be issued as a standalone command" in _observation_text(observations[0])


def test_root_agent_workflow_runs_model_and_bash_path_and_saves_trajectory(tmp_path, monkeypatch):
    from minisweagent.exceptions import Submitted
    from minisweagent.mas.workflows import root_agent_workflow

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
    import minisweagent.mas.workflows as workflows

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
    import minisweagent.mas.workflows as workflows

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
    assert "Agent Workflow Tree: mas-0123456789abcdef" in _observation_text(artifact["messages"][3])


def test_detached_spawn_returns_child_metadata_and_uses_child_queue(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

    monkeypatch.chdir(tmp_path)
    child_queue = _recording_child_queue()
    set_workflow_ids = []

    class RecordingSetWorkflowID:
        def __init__(self, workflow_id):
            self.workflow_id = workflow_id

        def __enter__(self):
            set_workflow_ids.append(self.workflow_id)
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", RecordingSetWorkflowID)
    child_queue.enqueue = Mock(side_effect=AssertionError("Detached spawn must use enqueue_async"))

    model = DeterministicModel(outputs=[make_output("delegate", [{"command": 'mini-mas spawn "inspect api"'}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}

    result = _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="delegate once",
        step_limit=1,
    )

    assert set_workflow_ids == ["mas-0123456789abcdef-c001"]
    assert len(child_queue.enqueued) == 1
    child_call = child_queue.enqueued[0]
    assert child_call["workflow_func"].__name__ == "child_agent_workflow"
    assert child_call["args"][:3] == (
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "inspect api",
    )
    assert child_call["kwargs"] == {}
    assert result["terminal_state"] == "limits_exceeded"

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    observation = _observation_text(artifact["messages"][3])
    assert "Detached spawn started" in observation
    assert "workflow_id: mas-0123456789abcdef-c001" in observation
    assert "run_directory: .mini-mas/runs/mas-0123456789abcdef" in observation
    assert (
        "trajectory_artifact_path: "
        ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        in observation
    )


def test_detached_spawn_allocates_stable_sibling_child_ids_without_duplicate_enqueue(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

    monkeypatch.chdir(tmp_path)
    child_queue = _recording_child_queue()

    class NoopSetWorkflowID:
        def __init__(self, workflow_id):
            self.workflow_id = workflow_id

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", NoopSetWorkflowID)
    child_queue.enqueue = Mock(side_effect=AssertionError("Detached spawn must use enqueue_async"))

    first_message = make_output("delegate first", [{"command": 'mini-mas spawn "first task"'}], cost=0.1)
    second_message = make_output("delegate second", [{"command": 'mini-mas spawn "second task"'}], cost=0.1)
    model = DeterministicModel(outputs=[first_message, second_message])
    env = Mock()
    env.get_template_vars.return_value = {}

    result = _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="delegate twice",
        step_limit=2,
    )

    assert result["terminal_state"] == "limits_exceeded"
    assert [call["args"][1] for call in child_queue.enqueued] == [
        "mas-0123456789abcdef-c001",
        "mas-0123456789abcdef-c002",
    ]

    replay_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", replay_queue)
    replay_observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=first_message,
            model=model,
            env=env,
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
                "spawn_index": 0,
                "existing_child_workflow_ids": ["mas-0123456789abcdef-c001"],
            },
        )
    )

    assert replay_queue.enqueued == []
    assert "workflow_id: mas-0123456789abcdef-c001" in _observation_text(replay_observations[0])


def test_detached_multi_spawn_returns_all_child_metadata_without_waiting(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

    monkeypatch.chdir(tmp_path)
    child_queue = _recording_child_queue()

    class NoopSetWorkflowID:
        def __init__(self, workflow_id):
            self.workflow_id = workflow_id

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", NoopSetWorkflowID)
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_event_async",
        Mock(side_effect=AssertionError("Detached multi-spawn must not wait for First Observable Events")),
    )

    model = DeterministicModel(
        outputs=[make_output("delegate many", [{"command": 'mini-mas spawn "task A" "task B"'}], cost=0.1)]
    )
    env = Mock()
    env.get_template_vars.return_value = {}

    result = _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="delegate twice in one command",
        step_limit=1,
    )

    assert result["terminal_state"] == "limits_exceeded"
    assert [call["args"][:3] for call in child_queue.enqueued] == [
        ("mas-0123456789abcdef", "mas-0123456789abcdef-c001", "task A"),
        ("mas-0123456789abcdef", "mas-0123456789abcdef-c002", "task B"),
    ]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    observation = _observation_text(artifact["messages"][3])
    assert "Detached spawn started" in observation
    assert "workflow_id: mas-0123456789abcdef-c001" in observation
    assert "workflow_id: mas-0123456789abcdef-c002" in observation
    assert "trajectory_artifact_path: .mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json" in observation
    assert "trajectory_artifact_path: .mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c002.traj.json" in observation


def test_waited_spawn_defaults_to_wait_any_first_observable_event(monkeypatch):
    import minisweagent.mas.workflows as workflows

    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _workflow_id: patch("builtins.id"))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "asyncio_wait",
        Mock(wraps=asyncio.wait),
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_result",
        Mock(side_effect=AssertionError("Waited Spawn must not wait on final workflow results")),
        raising=False,
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 60
        if workflow_id.endswith("-c001"):
            return {
                "workflow_id": workflow_id,
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "A ready",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
                ),
            }
        await asyncio.sleep(10)
        return None

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))

    message = make_output("delegate", [{"command": 'mini-mas spawn --wait "task A" "task B"'}])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    assert [call["args"][1] for call in child_queue.enqueued] == [
        "mas-0123456789abcdef-c001",
        "mas-0123456789abcdef-c002",
    ]
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Waited spawn completed" in text
    assert "wait_mode: any" in text
    assert "ready_child_count: 1" in text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c002" in text
    assert "latest_submission: A ready" in text


def test_waited_spawn_all_and_partial_timeout(monkeypatch):
    import minisweagent.mas.workflows as workflows

    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _workflow_id: patch("builtins.id"))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "asyncio_wait",
        Mock(wraps=asyncio.wait),
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 0.01
        if workflow_id.endswith("-c001"):
            return {
                "workflow_id": workflow_id,
                "lifecycle_state": "failed",
                "latest_error": "boom",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
                ),
            }
        await asyncio.sleep(10)
        return None

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))

    message = make_output("delegate", [{"command": 'mini-mas spawn --wait --all --timeout 0.01 "task A" "task B"'}])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Waited spawn timed out" in text
    assert "wait_mode: all" in text
    assert "ready_child_count: 1" in text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c002" in text
    assert "latest_error: boom" in text


def test_waited_spawn_wait_any_timeout_returns_running_children(monkeypatch):
    import minisweagent.mas.workflows as workflows

    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _workflow_id: patch("builtins.id"))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id in {"mas-0123456789abcdef-c001", "mas-0123456789abcdef-c002"}
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 0.01
        await asyncio.sleep(10)

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("delegate", [{"command": 'mini-mas spawn --wait --timeout 0.01 "task A" "task B"'}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "Waited spawn timed out" in text
    assert "wait_mode: any" in text
    assert "ready_child_count: 0" in text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c001, mas-0123456789abcdef-c002" in text
    assert [call["args"][1] for call in child_queue.enqueued] == [
        "mas-0123456789abcdef-c001",
        "mas-0123456789abcdef-c002",
    ]


def test_spawn_timeout_without_wait_is_invalid():
    import minisweagent.mas.workflows as workflows

    message = make_output("invalid", [{"command": 'mini-mas spawn --timeout 1 "task"'}])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>2</returncode>" in text
    assert "Detached Spawn has no wait phase" in text


def test_workflow_wait_for_specific_child_uses_first_observable_event(monkeypatch):
    import minisweagent.mas.workflows as workflows

    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "asyncio_wait",
        Mock(wraps=asyncio.wait),
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-0123456789abcdef-c001"
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 60
        return {
            "workflow_id": workflow_id,
            "lifecycle_state": "waiting_for_parent",
            "latest_submission": "ready",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))

    message = make_output("wait", [{"command": "mini-mas wait mas-0123456789abcdef-c001"}])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "mini-mas wait completed" in text
    assert "wait_mode: one" in text
    assert "ready_child_count: 1" in text
    assert "latest_submission: ready" in text


def test_workflow_wait_any_all_and_timeout_use_current_child_statuses(monkeypatch):
    import minisweagent.mas.workflows as workflows

    snapshots = [
        {
            "workflow_id": "mas-0123456789abcdef",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef.traj.json",
        },
        {
            "workflow_id": "mas-0123456789abcdef-c001",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        },
        {
            "workflow_id": "mas-0123456789abcdef-c002",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c002.traj.json"
            ),
        },
    ]

    async def query_status_tree_async(_dbos_api, _root_workflow_id):
        return snapshots

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 0.01
        if workflow_id.endswith("-c001"):
            return {
                "workflow_id": workflow_id,
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "ready",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
                ),
            }
        await asyncio.sleep(10)
        return None

    monkeypatch.setattr(workflows, "query_status_tree_async", query_status_tree_async)
    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    model = DeterministicModel(outputs=[])
    template_vars = {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef",
    }

    wait_any = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("wait any", [{"command": "mini-mas wait --any --timeout 0.01"}]),
            model=model,
            env=Mock(),
            template_vars=template_vars,
        )
    )
    assert "wait_mode: any" in _observation_text(wait_any[0])
    assert "mini-mas wait completed" in _observation_text(wait_any[0])

    wait_all = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("wait all", [{"command": "mini-mas wait --all --timeout 0.01"}]),
            model=model,
            env=Mock(),
            template_vars=template_vars,
        )
    )
    all_text = _observation_text(wait_all[0])
    assert "wait_mode: all" in all_text
    assert "mini-mas wait timed out" in all_text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c002" in all_text


def test_workflow_wait_timeout_returns_running_children_when_none_are_ready(monkeypatch):
    import minisweagent.mas.workflows as workflows

    snapshots = [
        {
            "workflow_id": "mas-0123456789abcdef-c001",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        }
    ]

    async def query_status_tree_async(_dbos_api, _root_workflow_id):
        return snapshots

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-0123456789abcdef-c001"
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 0.01
        await asyncio.sleep(10)

    monkeypatch.setattr(workflows, "query_status_tree_async", query_status_tree_async)
    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("wait timeout", [{"command": "mini-mas wait --timeout 0.01"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "mini-mas wait timed out" in text
    assert "ready_child_count: 0" in text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c001" in text


def test_mini_mas_wait_cli_outputs_first_observable_event(monkeypatch):
    ready = {
        "workflow_id": "mas-2222222222222222-c001",
        "lifecycle_state": "waiting_for_parent",
        "latest_submission": "ready",
        "run_directory": ".mini-mas/runs/mas-2222222222222222",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-2222222222222222/trajectories/mas-2222222222222222-c001.traj.json"
        ),
    }
    monkeypatch.setattr(
        "minisweagent.mas.cli.wait_for_agent_workflow",
        Mock(
            return_value={
                "workflow_id": "mas-2222222222222222-c001",
                "root_workflow_id": "mas-2222222222222222",
                "wait_mode": "one",
                "timed_out": False,
                "ready_children": [ready],
                "still_running_child_workflow_ids": [],
                "children": [
                    {
                        "task": "",
                        "workflow_id": "mas-2222222222222222-c001",
                        "root_workflow_id": "mas-2222222222222222",
                        "run_directory": ".mini-mas/runs/mas-2222222222222222",
                        "trajectory_artifact_path": (
                            ".mini-mas/runs/mas-2222222222222222/trajectories/"
                            "mas-2222222222222222-c001.traj.json"
                        ),
                    }
                ],
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["wait", "mas-2222222222222222-c001", "--timeout", "0.01"])

    assert cli_result.exit_code == 0
    assert "mini-mas wait completed" in cli_result.stdout
    assert "wait_mode: one" in cli_result.stdout
    assert "workflow_id: mas-2222222222222222-c001" in cli_result.stdout
    assert "latest_submission: ready" in cli_result.stdout


@pytest.mark.parametrize("command", ["history", "logs", "grep"])
def test_mini_mas_does_not_add_dedicated_history_or_log_commands(command):
    cli_result = CliRunner().invoke(app, [command])

    assert cli_result.exit_code != 0
