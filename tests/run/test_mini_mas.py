import importlib
from unittest.mock import MagicMock, Mock, patch

from typer.testing import CliRunner

from minisweagent.mas.cli import app, run


def _mock_dbos_module() -> MagicMock:
    dbos_module = MagicMock()
    dbos_module.DBOS.workflow.return_value = lambda func: func
    return dbos_module


def test_mini_mas_run_initializes_launches_and_starts_root_workflow():
    """mini-mas run is the external path that activates DBOS for MAS work."""
    handle = Mock()
    handle.workflow_id = "mas-test-root"
    handle.get_workflow_id.return_value = "mas-test-root"
    handle.get_result.return_value = {"workflow_id": "mas-test-root", "status": "started"}

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow.return_value = handle

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = run(workflow_id="mas-test-root", wait=True)

    dbos_module.DBOS.assert_called_once_with(
        config={
            "name": "mini-swe-agent-mas",
            "system_database_url": None,
        }
    )
    dbos_module.DBOS.launch.assert_called_once_with()
    dbos_module.SetWorkflowID.assert_called_once_with("mas-test-root")
    dbos_module.DBOS.start_workflow.assert_called_once()

    workflow_func = dbos_module.DBOS.start_workflow.call_args.args[0]
    assert workflow_func.__name__ == "root_agent_workflow"
    assert result == {"workflow_id": "mas-test-root", "result": {"workflow_id": "mas-test-root", "status": "started"}}


def test_mini_mas_run_cli_outputs_workflow_identifier():
    handle = Mock()
    handle.workflow_id = "mas-cli-root"
    handle.get_workflow_id.return_value = "mas-cli-root"

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow.return_value = handle

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        cli_result = CliRunner().invoke(app, ["run", "--workflow-id", "mas-cli-root"])

    assert cli_result.exit_code == 0
    assert "workflow_id: mas-cli-root" in cli_result.stdout


def test_root_agent_workflow_is_registered_as_dbos_workflow_when_module_loads():
    """The root workflow is defined inside the MAS subsystem boundary."""
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.workflows

        importlib.reload(minisweagent.mas.workflows)

    dbos_module.DBOS.workflow.assert_called()
