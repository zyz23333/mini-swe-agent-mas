import asyncio
import json
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from minisweagent.mas.cli import app
from minisweagent.mas.queues import AI_AGENT_WORKFLOW_QUEUE_NAME

from .helpers import _mock_dbos_module, _workflow_status_record

ACTIVATION_STATE_KEYS = {
    "activation_state",
    "ai_agent_execution",
    "ai_agent_execution_active",
    "ai_agent_execution_state",
    "ai_agent_queue",
    "queued",
    "queue_name",
}


def assert_no_ai_agent_execution_activation_state(data):
    text = json.dumps(data, sort_keys=True).lower()
    for term in ACTIVATION_STATE_KEYS:
        assert term not in data
        assert term not in text
    assert "activation" not in text


def test_ai_agent_execution_activation_is_not_an_agent_lifecycle_state_or_agent_metadata():
    from minisweagent.mas.artifacts import build_trajectory_artifact, make_artifact_metadata
    from minisweagent.mas.status_events import LIFECYCLE_STATES, make_status_snapshot

    assert "queued" not in LIFECYCLE_STATES
    with pytest.raises(ValueError, match="Unsupported MAS lifecycle state: queued"):
        make_status_snapshot(
            agent_id="mas-1111111111111111",
            parent_agent_id="mas-0123456789abcdef",
            lifecycle_state="queued",
        )

    metadata = make_artifact_metadata(
        agent_id="mas-1111111111111111",
        parent_agent_id="mas-0123456789abcdef",
    )
    trajectory_artifact = build_trajectory_artifact(
        agent_id="mas-1111111111111111",
        parent_agent_id="mas-0123456789abcdef",
        status="running",
    )

    assert set(metadata) == {
        "agent_id",
        "parent_agent_id",
        "agent_artifact_directory",
        "trajectory_artifact_path",
    }
    assert_no_ai_agent_execution_activation_state(metadata)
    assert_no_ai_agent_execution_activation_state(trajectory_artifact["info"])


def test_child_status_event_and_agent_status_output_exclude_ai_agent_execution_activation_state():
    from minisweagent.mas.status_events import format_specific_status, make_status_snapshot

    snapshot = make_status_snapshot(
        agent_id="mas-1111111111111111",
        parent_agent_id="mas-0123456789abcdef",
        lifecycle_state="waiting_for_parent",
        latest_submission="ready for parent review",
    )
    child_status_event = snapshot.to_event()

    assert set(child_status_event) == {
        "agent_id",
        "parent_agent_id",
        "lifecycle_state",
        "latest_submission",
        "agent_artifact_directory",
        "trajectory_artifact_path",
    }
    assert child_status_event["lifecycle_state"] == "waiting_for_parent"
    assert_no_ai_agent_execution_activation_state(child_status_event)

    status_output = format_specific_status(
        {
            **child_status_event,
            "activation_state": "active",
            "ai_agent_execution_active": True,
            "queue_name": AI_AGENT_WORKFLOW_QUEUE_NAME,
        }
    )

    assert "agent_id: mas-1111111111111111" in status_output
    assert "lifecycle_state: waiting_for_parent" in status_output
    assert "latest_submission: ready for parent review" in status_output
    assert "activation" not in status_output.lower()
    assert "queue" not in status_output.lower()
    assert "queued" not in status_output.lower()
    assert "AI Agent Execution" not in status_output


def test_external_mas_cli_status_discovers_interactive_root_agents_without_activation_state(tmp_path, monkeypatch):
    from minisweagent.mas.runtime import discover_interactive_root_agents

    monkeypatch.chdir(tmp_path)
    root_status = _workflow_status_record("mas-1111111111111111")
    root_status.name = "interactive_root_agent_workflow"

    async def list_workflows_async(**kwargs):
        assert kwargs == {
            "name": "interactive_root_agent_workflow",
            "has_parent": False,
            "load_input": False,
            "load_output": False,
        }
        return [root_status]

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-1111111111111111"
        assert key == "mini_mas_status"
        assert timeout_seconds == 1
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
            "activation_state": "active",
            "ai_agent_execution_active": True,
            "queue_name": AI_AGENT_WORKFLOW_QUEUE_NAME,
        }

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.list_workflows_async = Mock(side_effect=list_workflows_async)
    dbos_module.DBOS.get_event_async = Mock(side_effect=get_event_async)

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = discover_interactive_root_agents()

    assert result["roots"] == [
        {
            "agent_id": "mas-1111111111111111",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }
    ]
    assert "Interactive Root Agents" in result["output"]
    assert "lifecycle_state: waiting_for_command" in result["output"]
    assert "AI Agent Execution" not in result["output"]
    assert "activation" not in result["output"].lower()
    assert "queue" not in result["output"].lower()
    assert "queued" not in result["output"].lower()
    assert_no_ai_agent_execution_activation_state(result["roots"][0])


def test_ai_agent_execution_activation_does_not_grant_authority_over_descendant_or_peer_agents(monkeypatch):
    import minisweagent.mas.authority as authority
    from minisweagent.mas.authority import AuthorityCommandError, DirectChildAuthorityPolicy
    from minisweagent.mas.runtime import activate_ai_agent_execution

    dbos_module = _mock_dbos_module()
    stop_event = Mock()
    stop_event.wait.return_value = True

    with (
        patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module),
        patch("minisweagent.mas.runtime.register_mas_agent_workflows", Mock()),
    ):
        activate_ai_agent_execution(stop_event=stop_event, wait_interval_seconds=0.01)

    async def query_direct_child_status(*, parent_workflow_id, child_workflow_id):
        assert parent_workflow_id == "mas-0123456789abcdef"
        if child_workflow_id == "mas-1111111111111111":
            return {
                "agent_id": "mas-1111111111111111",
                "parent_agent_id": "mas-0123456789abcdef",
                "lifecycle_state": "waiting_for_parent",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
            }
        return None

    monkeypatch.setattr(authority.agent_interactions, "query_direct_child_status", query_direct_child_status)
    policy = DirectChildAuthorityPolicy()

    direct_child = asyncio.run(
        policy.require_observable_child(
            parent_workflow_id="mas-0123456789abcdef",
            target_workflow_id="mas-1111111111111111",
            command_name="status",
        )
    )
    descendant = asyncio.run(
        policy.require_observable_child(
            parent_workflow_id="mas-0123456789abcdef",
            target_workflow_id="mas-2222222222222222",
            command_name="status",
        )
    )
    peer = asyncio.run(
        policy.require_waiting_child(
            parent_workflow_id="mas-0123456789abcdef",
            target_workflow_id="mas-3333333333333333",
            command_name="continue",
        )
    )

    assert direct_child["agent_id"] == "mas-1111111111111111"
    assert isinstance(descendant, AuthorityCommandError)
    assert descendant.exception_info == "agent_not_direct_child"
    assert isinstance(peer, AuthorityCommandError)
    assert peer.exception_info == "agent_not_direct_child"


def test_external_mas_cli_governance_command_enters_through_interactive_root_agent(monkeypatch):
    start_root = Mock(
        return_value={
            "agent_id": "mas-1111111111111111",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
        }
    )
    prepare_resume = Mock(
        return_value={
            "kind": "resume_ready",
            "root_agent_id": "mas-1111111111111111",
            "attachment_token": "att-1111111111111111",
            "agent_id": "mas-1111111111111111",
            "lifecycle_state": "waiting_for_command",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json",
            "returncode": 0,
        }
    )
    send_root_command = Mock(
        return_value={
            "kind": "root_command_result",
            "command_id": "cmd-1111111111111111",
            "root_agent_id": "mas-1111111111111111",
            "command": "mini-mas wait mas-2222222222222222",
            "result": {"output": "wait result\n", "returncode": 0, "exception_info": "", "extra": {}},
        }
    )
    release_attachment = Mock()
    monkeypatch.setattr("minisweagent.mas.cli.start_interactive_root_agent_workflow", start_root)
    monkeypatch.setattr("minisweagent.mas.cli.prepare_resume_root_agent", prepare_resume)
    monkeypatch.setattr("minisweagent.mas.cli.send_root_command", send_root_command)
    monkeypatch.setattr("minisweagent.mas.cli._refresh_attachment_until_stopped", Mock())
    monkeypatch.setattr("minisweagent.mas.cli.release_root_attachment", release_attachment)

    cli_result = CliRunner().invoke(app, [], input="mini-mas wait mas-2222222222222222\n")

    assert cli_result.exit_code == 0
    assert "agent_id: mas-1111111111111111" in cli_result.stdout
    assert "wait result\n" in cli_result.stdout
    start_root.assert_called_once_with()
    prepare_resume.assert_called_once_with(root_agent_id="mas-1111111111111111")
    send_root_command.assert_called_once_with(
        root_agent_id="mas-1111111111111111",
        command="mini-mas wait mas-2222222222222222",
        result_timeout_seconds=60,
        attachment_token="att-1111111111111111",
    )
    release_attachment.assert_called_once_with(
        root_agent_id="mas-1111111111111111",
        attachment_token="att-1111111111111111",
    )


def test_ai_agent_execution_activation_notice_does_not_claim_exactly_once_or_workspace_isolation(monkeypatch):
    activate = Mock(return_value={"kind": "ai_agent_execution_deactivated", "queue_name": AI_AGENT_WORKFLOW_QUEUE_NAME})
    monkeypatch.setattr("minisweagent.mas.cli.activate_ai_agent_execution", activate)
    monkeypatch.setattr("minisweagent.mas.cli.Path.cwd", Mock(return_value="/workspace/project"))

    cli_result = CliRunner().invoke(app, ["agent", "activate"])

    assert cli_result.exit_code == 0
    assert "AI Agent Execution activation" in cli_result.stdout
    assert "may call models, execute bash actions, and modify the Shared Workspace" in cli_result.stdout
    assert "exactly-once" not in cli_result.stdout.lower()
    assert "recovery" not in cli_result.stdout.lower()
    assert "Workspace Isolation" not in cli_result.stdout
    activate.assert_called_once_with()
