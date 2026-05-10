import asyncio
from unittest.mock import Mock

from minisweagent.models.test_models import (
    DeterministicModel,
    make_output,
)

from .helpers import (
    _mock_single_direct_child_status,
    _observation_text,
    _set_agent_workflow_context,
)


def test_direct_child_authority_policy_uses_coordination_lookup(monkeypatch):
    import minisweagent.mas.authority as authority
    from minisweagent.mas.authority import DirectChildAuthorityPolicy

    calls = []

    async def query_direct_child_status(*, parent_workflow_id, child_workflow_id):
        calls.append((parent_workflow_id, child_workflow_id))
        return {
            "root_workflow_id": "mas-0123456789abcdef",
            "workflow_id": "mas-0123456789abcdef-c001",
            "lifecycle_state": "waiting_for_parent",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        }

    monkeypatch.setattr(authority.coordination, "query_direct_child_status", query_direct_child_status)

    result = asyncio.run(
        DirectChildAuthorityPolicy().require_observable_child(
            parent_workflow_id="mas-0123456789abcdef",
            target_workflow_id="mas-0123456789abcdef-c001",
            command_name="status",
        )
    )

    assert result["workflow_id"] == "mas-0123456789abcdef-c001"
    assert calls == [("mas-0123456789abcdef", "mas-0123456789abcdef-c001")]

def test_direct_child_authority_policy_success_and_rejection_paths(monkeypatch):
    import minisweagent.mas.authority as authority
    from minisweagent.mas.authority import AuthorityCommandError, DirectChildAuthorityPolicy

    snapshots = {
        "mas-0123456789abcdef-c001": {
            "root_workflow_id": "mas-0123456789abcdef",
            "workflow_id": "mas-0123456789abcdef-c001",
            "lifecycle_state": "waiting_for_parent",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        },
        "mas-0123456789abcdef-c002": {
            "root_workflow_id": "mas-0123456789abcdef",
            "workflow_id": "mas-0123456789abcdef-c002",
            "lifecycle_state": "waiting_for_child",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c002.traj.json"
            ),
        },
    }

    async def query_direct_child_status(*, parent_workflow_id, child_workflow_id):
        assert parent_workflow_id == "mas-0123456789abcdef"
        return snapshots.get(child_workflow_id)

    monkeypatch.setattr(authority.coordination, "query_direct_child_status", query_direct_child_status)
    policy = DirectChildAuthorityPolicy()

    authorized = asyncio.run(
        policy.require_observable_child(
            parent_workflow_id="mas-0123456789abcdef",
            target_workflow_id="mas-0123456789abcdef-c001",
            command_name="status",
        )
    )
    not_direct = asyncio.run(
        policy.require_observable_child(
            parent_workflow_id="mas-0123456789abcdef",
            target_workflow_id="mas-0123456789abcdef-c001-c001",
            command_name="status",
        )
    )
    not_waiting = asyncio.run(
        policy.require_waiting_child(
            parent_workflow_id="mas-0123456789abcdef",
            target_workflow_id="mas-0123456789abcdef-c002",
            command_name="continue",
        )
    )

    assert authorized["workflow_id"] == "mas-0123456789abcdef-c001"
    assert authorized["trajectory_artifact_path"].endswith("mas-0123456789abcdef-c001.traj.json")
    assert isinstance(not_direct, AuthorityCommandError)
    assert not_direct.exception_info == "workflow_not_direct_child"
    assert isinstance(not_waiting, AuthorityCommandError)
    assert not_waiting.exception_info == "workflow_not_waiting_for_parent"

def test_root_cannot_status_or_wait_for_grandchild_through_transitive_authority(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_single_direct_child_status(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {
            "workflow_id": "mas-0123456789abcdef-c001",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        },
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_event_async",
        Mock(side_effect=AssertionError("Transitive wait must not wait on a grandchild event")),
    )

    status_result = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("bad status", [{"command": "mini-mas status mas-0123456789abcdef-c001-c001"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={},
        )
    )
    wait_result = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("bad wait", [{"command": "mini-mas wait mas-0123456789abcdef-c001-c001"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={},
        )
    )

    for observations in (status_result, wait_result):
        text = _observation_text(observations[0])
        assert "<returncode>1</returncode>" in text
        assert (
            "Workflow is not a direct Child Agent Workflow of mas-0123456789abcdef: "
            "mas-0123456789abcdef-c001-c001"
        ) in text
