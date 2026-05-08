import importlib
import json
import re
from unittest.mock import MagicMock, Mock, patch

from typer.testing import CliRunner

from minisweagent.mas.cli import app, run
from minisweagent.mas.runtime import make_root_workflow_id


def _mock_dbos_module() -> MagicMock:
    dbos_module = MagicMock()
    dbos_module.DBOS.workflow.return_value = lambda func: func
    dbos_module.DBOS.step.return_value = lambda func: func
    return dbos_module


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

    result = workflows.root_agent_workflow("mas-0123456789abcdef")

    assert result == {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef",
        "status": "started",
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
