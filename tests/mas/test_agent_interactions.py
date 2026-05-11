import asyncio
from unittest.mock import Mock

from minisweagent.mas import status_events as mas_status_events
from minisweagent.mas.signals import (
    PARENT_DIRECTION_TOPIC,
)
from minisweagent.models.test_models import (
    DeterministicModel,
    make_output,
)

from .helpers import (
    _mock_direct_child_status_events,
    _observation_text,
    _set_agent_workflow_context,
)


def test_agent_interactions_module_owns_status_first_observable_wait_and_messages(monkeypatch):
    import minisweagent.mas.agent_interactions as agent_interactions

    dbos_api = Mock()
    published = []
    received = []
    sent = []

    async def set_event_async(key, value):
        published.append((key, value))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-1111111111111111"
        assert key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY
        assert timeout_seconds == 0.25
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_parent",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": (
                ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
            ),
        }

    async def recv_async(topic=None, timeout_seconds=60):
        received.append((topic, timeout_seconds))
        return {"type": "close"}

    async def send_async(destination_id, message, topic=None):
        sent.append((destination_id, message, topic))

    dbos_api.workflow_id = "mas-0123456789abcdef"
    dbos_api.set_event_async = Mock(side_effect=set_event_async)
    dbos_api.get_event_async = Mock(side_effect=get_event_async)
    dbos_api.asyncio_wait = Mock(wraps=asyncio.wait)
    dbos_api.recv_async = Mock(side_effect=recv_async)
    dbos_api.send_async = Mock(side_effect=send_async)
    dbos_api.set_event = Mock(side_effect=AssertionError("Adapter must use async status/event publication"))
    dbos_api.recv = Mock(side_effect=AssertionError("Adapter must use async message receive"))
    dbos_api.send = Mock(side_effect=AssertionError("Adapter must use async message send"))

    monkeypatch.setattr(agent_interactions._dbos, "DBOS", dbos_api)

    assert agent_interactions.current_workflow_id() == "mas-0123456789abcdef"
    asyncio.run(
        agent_interactions.publish_status(
            agent_id="mas-0123456789abcdef",
            lifecycle_state="waiting_for_child",
        )
    )
    asyncio.run(
        agent_interactions.publish_first_observable(
            agent_id="mas-1111111111111111",
            parent_agent_id="mas-0123456789abcdef",
            lifecycle_state="waiting_for_parent",
        )
    )
    ready, still_running, timed_out = asyncio.run(
        agent_interactions.wait_for_first_observable_events(
            child_agent_ids=["mas-1111111111111111"],
            wait_all=False,
            timeout_seconds=0.25,
        )
    )
    signal = asyncio.run(agent_interactions.receive_parent_direction(topic=PARENT_DIRECTION_TOPIC, timeout_seconds=3))
    asyncio.run(
        agent_interactions.send_parent_direction(
            target_workflow_id="mas-1111111111111111",
            signal={"type": "close"},
            topic=PARENT_DIRECTION_TOPIC,
        )
    )

    assert [(key, value["lifecycle_state"]) for key, value in published] == [
        (mas_status_events.STATUS_EVENT_KEY, "waiting_for_child"),
        (mas_status_events.FIRST_OBSERVABLE_EVENT_KEY, "waiting_for_parent"),
    ]
    assert ready[0]["agent_id"] == "mas-1111111111111111"
    assert still_running == []
    assert timed_out is False
    assert signal == {"type": "close"}
    assert received == [(PARENT_DIRECTION_TOPIC, 3)]
    assert sent == [("mas-1111111111111111", {"type": "close"}, PARENT_DIRECTION_TOPIC)]

def test_workflow_status_reports_current_tree_without_blocking(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    events_by_workflow = {
        "mas-1111111111111111": {
            "mini_mas_status": {
                "agent_id": "mas-1111111111111111",
                "parent_agent_id": "mas-0123456789abcdef",
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "ready for review",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": (
                    ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
                ),
            }
        },
    }
    _mock_direct_child_status_events(monkeypatch, workflows, "mas-0123456789abcdef", events_by_workflow)
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "list_workflows",
        Mock(side_effect=AssertionError("Agent status dispatch must use list_workflows_async")),
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_all_events",
        Mock(side_effect=AssertionError("Agent status dispatch must use get_all_events_async")),
    )

    message = make_output("status", [{"command": "mini-mas status"}])
    model = DeterministicModel(outputs=[])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=model,
            env=Mock(),
            template_vars={"agent_id": "mas-0123456789abcdef"},
        )
    )

    workflows._dbos.DBOS.list_workflows_async.assert_called_once_with(
        parent_workflow_id="mas-0123456789abcdef",
        load_input=False,
        load_output=False,
    )
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Direct Child Agents for: mas-0123456789abcdef" in text
    assert "agent_id: mas-0123456789abcdef\nlifecycle_state" not in text
    assert "agent_id: mas-1111111111111111" in text
    assert "lifecycle_state: waiting_for_parent" in text
    assert "latest_submission: ready for review" in text
    assert "trajectory_artifact_path: .mini-mas/agents/mas-1111111111111111/trajectory.traj.json" in text

def test_workflow_status_reports_specific_descendant_and_missing_workflow(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "agent_id": "mas-1111111111111111",
        "parent_agent_id": "mas-0123456789abcdef",
        "lifecycle_state": "failed",
        "latest_error": "model failed",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": (
            ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
        ),
    }
    _mock_direct_child_status_events(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {"mas-1111111111111111": {"mini_mas_status": child_status}},
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_all_events",
        Mock(side_effect=AssertionError("Agent status dispatch must use get_all_events_async")),
    )

    model = DeterministicModel(outputs=[])
    found = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("status child", [{"command": "mini-mas status mas-1111111111111111"}]),
            model=model,
            env=Mock(),
            template_vars={"agent_id": "mas-0123456789abcdef"},
        )
    )

    found_text = _observation_text(found[0])
    assert "<returncode>0</returncode>" in found_text
    assert "agent_id: mas-1111111111111111" in found_text
    assert "lifecycle_state: failed" in found_text
    assert "latest_error: model failed" in found_text

    missing = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("missing child", [{"command": "mini-mas status mas-9999999999999999"}]),
            model=model,
            env=Mock(),
            template_vars={"agent_id": "mas-0123456789abcdef"},
        )
    )

    missing_text = _observation_text(missing[0])
    assert "<returncode>1</returncode>" in missing_text
    assert "Agent is not a direct Child Agent of mas-0123456789abcdef: mas-9999999999999999" in missing_text

def test_status_snapshot_accepts_waiting_for_child_lifecycle_state():

    snapshot = mas_status_events.make_status_snapshot(
        agent_id="mas-1111111111111111",
        parent_agent_id="mas-0123456789abcdef",
        lifecycle_state="waiting_for_child",
    )

    assert snapshot.to_event()["lifecycle_state"] == "waiting_for_child"


def test_status_snapshot_normalization_rebuilds_canonical_agent_artifact_metadata():
    snapshot = mas_status_events.normalize_agent_snapshot(
        {
            "agent_id": "mas-1111111111111111",
            "parent_agent_id": "mas-0123456789abcdef",
            "lifecycle_state": "waiting_for_parent",
            "agent_artifact_directory": ".mini-mas/agents/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/agents/mas-0123456789abcdef/trajectories/"
                "mas-1111111111111111.traj.json"
            ),
        }
    )

    assert snapshot["agent_id"] == "mas-1111111111111111"
    assert "workflow_id" not in snapshot
    assert snapshot["parent_agent_id"] == "mas-0123456789abcdef"
    assert snapshot["agent_artifact_directory"] == ".mini-mas/agents/mas-1111111111111111"
    assert snapshot["trajectory_artifact_path"] == (
        ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
    )
