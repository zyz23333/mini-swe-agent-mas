import asyncio
from unittest.mock import Mock

import pytest

from minisweagent.mas.signals import (
    PARENT_DIRECTION_TOPIC,
)
from minisweagent.models.test_models import (
    DeterministicModel,
    make_output,
)

from .helpers import (
    _mock_direct_child_status_events,
    _mock_single_direct_child_status,
    _observation_text,
    _set_agent_workflow_context,
)


def test_workflow_continue_sends_parent_to_child_continuation_signal(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_single_direct_child_status(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {
            "workflow_id": "mas-0123456789abcdef-c001",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "waiting_for_parent",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
            "latest_submission": "first answer",
        },
    )

    sent = []

    async def send_async(destination_id, message, topic=None):
        sent.append((destination_id, message, topic))

    monkeypatch.setattr(workflows._dbos.DBOS, "send_async", Mock(side_effect=send_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send",
        Mock(side_effect=AssertionError("Continuation must use send_async outside DBOS steps")),
        raising=False,
    )

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output(
                "continue child",
                [{"command": 'mini-mas continue mas-0123456789abcdef-c001 "please revise"'}],
            ),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    assert sent == [
        (
            "mas-0123456789abcdef-c001",
            {
                "type": "continuation",
                "signal_type": "mas_continuation",
                "content": "please revise",
                "source_workflow_id": "mas-0123456789abcdef",
                "target_workflow_id": "mas-0123456789abcdef-c001",
            },
            PARENT_DIRECTION_TOPIC,
        )
    ]
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Continuation signal sent" in text
    assert "agent_id: mas-0123456789abcdef-c001" in text

def test_workflow_close_sends_parent_to_child_neutral_close_signal(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_single_direct_child_status(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {
            "workflow_id": "mas-0123456789abcdef-c001",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "waiting_for_parent",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
            "latest_submission": "first answer",
        },
    )

    sent = []

    async def send_async(destination_id, message, topic=None):
        sent.append((destination_id, message, topic))

    monkeypatch.setattr(workflows._dbos.DBOS, "send_async", Mock(side_effect=send_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send",
        Mock(side_effect=AssertionError("Close must use send_async outside DBOS steps")),
        raising=False,
    )

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("close child", [{"command": "mini-mas close mas-0123456789abcdef-c001"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    assert sent == [
        (
            "mas-0123456789abcdef-c001",
            {
                "type": "close",
                "signal_type": "mas_close",
                "source_workflow_id": "mas-0123456789abcdef",
                "target_workflow_id": "mas-0123456789abcdef-c001",
            },
            PARENT_DIRECTION_TOPIC,
        )
    ]
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Close signal sent" in text
    assert "agent_id: mas-0123456789abcdef-c001" in text
    assert "lifecycle_state: waiting_for_parent" in text
    assert "accepted" not in text.lower()
    assert "rejected" not in text.lower()
    assert "aborted" not in text.lower()
    assert "cancel" not in text.lower()

@pytest.mark.parametrize(
    ("command", "expected_error"),
    [
        ("mini-mas continue mas-0123456789abcdef root", "Cannot continue the current Agent"),
        (
            "mini-mas continue mas-fedcba9876543210-c001 no",
            "Agent is not a direct Child Agent of mas-0123456789abcdef",
        ),
        (
            "mini-mas continue mas-0123456789abcdef-c002 no",
            "Agent is not a direct Child Agent of mas-0123456789abcdef",
        ),
    ],
)
def test_workflow_continue_rejects_root_outside_tree_and_missing_children(monkeypatch, command, expected_error):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_direct_child_status_events(monkeypatch, workflows, "mas-0123456789abcdef", {})
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send_async",
        Mock(side_effect=AssertionError("Invalid continuation must not send a DBOS message")),
    )

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("bad continue", [{"command": command}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>1</returncode>" in text
    assert expected_error in text

def test_workflow_continue_rejects_sibling_from_child_workflow(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef-c001")
    _mock_direct_child_status_events(monkeypatch, workflows, "mas-0123456789abcdef-c001", {})
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send_async",
        Mock(side_effect=AssertionError("Sibling continuation must not send a DBOS message")),
    )

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("bad continue", [{"command": "mini-mas continue mas-0123456789abcdef-c002 no"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef-c001",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>1</returncode>" in text
    assert "Agent is not a direct Child Agent of mas-0123456789abcdef-c001: mas-0123456789abcdef-c002" in text

@pytest.mark.parametrize(
    ("command", "expected_error"),
    [
        ("mini-mas close mas-0123456789abcdef", "Cannot close the current Agent"),
        (
            "mini-mas close mas-fedcba9876543210-c001",
            "Agent is not a direct Child Agent of mas-0123456789abcdef",
        ),
        (
            "mini-mas close mas-0123456789abcdef-c002",
            "Agent is not a direct Child Agent of mas-0123456789abcdef",
        ),
    ],
)
def test_workflow_close_rejects_root_outside_tree_and_missing_children(monkeypatch, command, expected_error):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_direct_child_status_events(monkeypatch, workflows, "mas-0123456789abcdef", {})
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send_async",
        Mock(side_effect=AssertionError("Invalid close must not send a DBOS message")),
    )

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("bad close", [{"command": command}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>1</returncode>" in text
    assert expected_error in text

def test_workflow_close_rejects_sibling_from_child_workflow(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef-c001")
    _mock_direct_child_status_events(monkeypatch, workflows, "mas-0123456789abcdef-c001", {})
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send_async",
        Mock(side_effect=AssertionError("Sibling close must not send a DBOS message")),
    )

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("bad close", [{"command": "mini-mas close mas-0123456789abcdef-c002"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef-c001",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>1</returncode>" in text
    assert "Agent is not a direct Child Agent of mas-0123456789abcdef-c001: mas-0123456789abcdef-c002" in text

@pytest.mark.parametrize("lifecycle_state", ["closed", "failed", "limits_exceeded", "running", "waiting_for_child"])
def test_workflow_close_rejects_not_waiting_or_terminal_workflows(monkeypatch, lifecycle_state):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_single_direct_child_status(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {
            "workflow_id": "mas-0123456789abcdef-c001",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": lifecycle_state,
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        },
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send_async",
        Mock(side_effect=AssertionError("Not-waiting close must not send a DBOS message")),
    )

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("close", [{"command": "mini-mas close mas-0123456789abcdef-c001"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>1</returncode>" in text
    assert "Agent is not waiting for parent direction: mas-0123456789abcdef-c001" in text

def test_workflow_continue_and_close_reject_waiting_for_child_status(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_single_direct_child_status(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {
            "workflow_id": "mas-0123456789abcdef-c001",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "waiting_for_child",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        },
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send_async",
        Mock(side_effect=AssertionError("waiting_for_child must not authorize parent-direction messages")),
    )

    model = DeterministicModel(outputs=[])
    template_vars = {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef",
    }
    continued = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("continue", [{"command": 'mini-mas continue mas-0123456789abcdef-c001 "go"'}]),
            model=model,
            env=Mock(),
            template_vars=template_vars,
        )
    )
    closed = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("close", [{"command": "mini-mas close mas-0123456789abcdef-c001"}]),
            model=model,
            env=Mock(),
            template_vars=template_vars,
        )
    )

    for observations in (continued, closed):
        text = _observation_text(observations[0])
        assert "<returncode>1</returncode>" in text
        assert "Agent is not waiting for parent direction: mas-0123456789abcdef-c001" in text
