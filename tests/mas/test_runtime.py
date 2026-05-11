import inspect
from unittest.mock import Mock, patch

import pytest

from minisweagent.mas.cli import run
from minisweagent.mas.runtime import (
    close_agent_workflow,
    continue_agent_workflow,
    get_agent_workflow_status,
    start_interactive_root_agent_workflow,
    wait_for_agent_workflow,
)

from .helpers import (
    AsyncMockHandle,
    _mock_dbos_module,
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
    handle = AsyncMockHandle(
        "mas-1111111111111111",
        {
            "agent_id": "mas-1111111111111111",
            "status": "waiting_for_command",
            "terminal_state": "waiting_for_command",
            "lifecycle_state": "waiting_for_command",
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
    assert result == {
        "agent_id": "mas-1111111111111111",
        "lifecycle_state": "waiting_for_command",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
    }


@pytest.mark.parametrize(
    ("runtime_func", "kwargs"),
    [
        (get_agent_workflow_status, {"workflow_id": "mas-2222222222222222"}),
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
