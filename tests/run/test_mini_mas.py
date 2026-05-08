import importlib
import json
import re
from unittest.mock import MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from minisweagent.mas.cli import app, run
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
    return getattr(workflow_func, "__wrapped__", workflow_func)(*args, **kwargs)


def test_mini_mas_run_initializes_launches_and_starts_root_workflow():
    """mini-mas run is the external path that activates DBOS for MAS work."""
    handle = Mock()
    handle.workflow_id = "mas-1111111111111111"
    handle.get_workflow_id.return_value = "mas-1111111111111111"
    handle.get_result.return_value = {
        "root_workflow_id": "mas-1111111111111111",
        "workflow_id": "mas-1111111111111111",
        "status": "started",
        "run_directory": ".mini-mas/runs/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
    }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow.return_value = handle

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
    dbos_module.DBOS.start_workflow.assert_called_once()

    workflow_func = dbos_module.DBOS.start_workflow.call_args.args[0]
    assert workflow_func.__name__ == "root_agent_workflow"
    assert dbos_module.DBOS.start_workflow.call_args.args[1] == "mas-1111111111111111"
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


def test_mini_mas_run_cli_outputs_artifact_locations():
    handle = Mock()
    handle.workflow_id = "mas-2222222222222222"
    handle.get_workflow_id.return_value = "mas-2222222222222222"
    handle.get_result.return_value = {
        "root_workflow_id": "mas-2222222222222222",
        "workflow_id": "mas-2222222222222222",
        "status": "started",
        "run_directory": ".mini-mas/runs/mas-2222222222222222",
        "trajectory_artifact_path": ".mini-mas/runs/mas-2222222222222222/trajectories/mas-2222222222222222.traj.json",
    }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow.return_value = handle

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


def test_root_agent_workflow_is_registered_as_dbos_workflow_when_module_loads():
    """The root workflow is defined inside the MAS subsystem boundary."""
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.workflows

        importlib.reload(minisweagent.mas.workflows)

    dbos_module.DBOS.workflow.assert_called()


def test_model_bash_and_trajectory_operations_are_registered_as_dbos_steps():
    """Model calls, ordinary bash execution, and trajectory persistence are checkpointed as DBOS steps."""
    dbos_module = _mock_recording_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.workflows

        importlib.reload(minisweagent.mas.workflows)

    assert "query_model_step" in dbos_module.registered_steps
    assert "execute_bash_step" in dbos_module.registered_steps
    assert "save_root_trajectory_artifact_step" in dbos_module.registered_steps


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

    message = make_output("dispatch", [{"command": "mini-mas status"}])
    env = Mock()
    model = DeterministicModel(outputs=[])

    observations = execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={})

    env.execute.assert_not_called()
    assert len(observations) == 1
    assert "MAS command accepted: status" in _observation_text(observations[0])


def test_workflow_action_execution_keeps_ordinary_bash_on_bash_path():
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    message = make_output("bash", [{"command": "echo hello"}])
    env = Mock()
    env.execute.return_value = {"output": "hello\n", "returncode": 0, "exception_info": ""}
    model = DeterministicModel(outputs=[])

    observations = execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={})

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

    observations = execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={})

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

    observations = execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={})

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
    assert "MAS command accepted: status" in _observation_text(artifact["messages"][3])
