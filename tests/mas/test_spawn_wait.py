import asyncio
import json
import re
from unittest.mock import Mock, patch

import pytest

from minisweagent.mas import status_events as mas_status_events
from minisweagent.models.test_models import (
    DeterministicModel,
    make_output,
)

from .helpers import (
    _call_root_agent_workflow,
    _mock_direct_child_status_events,
    _observation_text,
    _recording_child_queue,
    _set_agent_workflow_context,
)


def _patch_agent_ids(
    monkeypatch,
    workflows,
    ids=("mas-1111111111111111", "mas-2222222222222222", "mas-3333333333333333", "mas-4444444444444444"),
):
    iterator = iter(ids)
    monkeypatch.setattr(workflows.agent_interactions, "make_agent_id", lambda: next(iterator))


def test_detached_spawn_returns_child_metadata_and_uses_child_queue(tmp_path, monkeypatch):
    import minisweagent.mas.mas_agent as workflows

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

    assert len(set_workflow_ids) == 1
    child_agent_id = set_workflow_ids[0]
    assert re.fullmatch(r"mas-[0-9a-f]{16}", child_agent_id)
    assert child_agent_id != "mas-0123456789abcdef"
    assert not re.search(r"-c[0-9]{3}(?:\\Z|-)", child_agent_id)
    assert len(child_queue.enqueued) == 1
    child_call = child_queue.enqueued[0]
    assert child_call["workflow_func"].__name__ == "child_agent_workflow"
    assert child_call["args"][:2] == (
        child_agent_id,
        "inspect api",
    )
    assert child_call["kwargs"] == {"parent_agent_id": "mas-0123456789abcdef"}
    assert result["terminal_state"] == "limits_exceeded"

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    observation = _observation_text(artifact["messages"][3])
    assert "Detached spawn started" in observation
    assert f"agent_id: {child_agent_id}" in observation
    assert "parent_agent_id: mas-0123456789abcdef" in observation
    assert f"agent_artifact_directory: .mini-mas/agents/{child_agent_id}" in observation
    assert f"trajectory_artifact_path: .mini-mas/agents/{child_agent_id}/trajectory.traj.json" in observation
    assert "run_directory" not in observation

def test_detached_spawn_allocates_opaque_child_ids_without_duplicate_enqueue(tmp_path, monkeypatch):
    import minisweagent.mas.mas_agent as workflows

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
    child_agent_ids = [call["args"][0] for call in child_queue.enqueued]
    assert len(child_agent_ids) == 2
    assert len(set(child_agent_ids)) == 2
    assert all(re.fullmatch(r"mas-[0-9a-f]{16}", agent_id) for agent_id in child_agent_ids)
    assert all(not re.search(r"-c[0-9]{3}(?:\\Z|-)", agent_id) for agent_id in child_agent_ids)

    replay_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", replay_queue)
    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    replay_observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=first_message,
            model=model,
            env=env,
            template_vars={"agent_id": "mas-0123456789abcdef"},
        )
    )

    replay_child_agent_ids = [call["args"][0] for call in replay_queue.enqueued]
    assert len(replay_child_agent_ids) == 1
    assert re.fullmatch(r"mas-[0-9a-f]{16}", replay_child_agent_ids[0])
    assert not re.search(r"-c[0-9]{3}(?:\\Z|-)", replay_child_agent_ids[0])
    assert f"agent_id: {replay_child_agent_ids[0]}" in _observation_text(replay_observations[0])

def test_detached_multi_spawn_returns_all_child_metadata_without_waiting(tmp_path, monkeypatch):
    import minisweagent.mas.mas_agent as workflows

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
    _patch_agent_ids(monkeypatch, workflows, ("mas-3333333333333333", "mas-4444444444444444"))
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
    enqueued_args = [call["args"][:2] for call in child_queue.enqueued]
    child_agent_ids = [args[0] for args in enqueued_args]
    assert enqueued_args == [
        ("mas-3333333333333333", "task A"),
        ("mas-4444444444444444", "task B"),
    ]
    assert len(set(child_agent_ids)) == 2
    assert all(re.fullmatch(r"mas-[0-9a-f]{16}", agent_id) for agent_id in child_agent_ids)
    assert all(not re.search(r"-c[0-9]{3}(?:\\Z|-)", agent_id) for agent_id in child_agent_ids)

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    observation = _observation_text(artifact["messages"][3])
    assert "Detached spawn started" in observation
    assert f"agent_id: {child_agent_ids[0]}" in observation
    assert f"agent_id: {child_agent_ids[1]}" in observation
    assert f"trajectory_artifact_path: .mini-mas/agents/{child_agent_ids[0]}/trajectory.traj.json" in observation
    assert f"trajectory_artifact_path: .mini-mas/agents/{child_agent_ids[1]}/trajectory.traj.json" in observation
    assert "sibling" not in observation.lower()

def test_child_agent_workflow_can_spawn_grandchildren_with_parent_relative_ids(tmp_path, monkeypatch):
    import minisweagent.mas.mas_agent as workflows

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
    _patch_agent_ids(monkeypatch, workflows, ("mas-3333333333333333", "mas-4444444444444444"))
    model = DeterministicModel(
        outputs=[make_output("delegate to grandchildren", [{"command": 'mini-mas spawn "task A" "task B"'}], cost=0.1)]
    )
    env = Mock()
    env.get_template_vars.return_value = {}

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-1111111111111111",
        "delegate recursively",
        parent_agent_id="mas-0123456789abcdef",
        model=model,
        env=env,
        step_limit=1,
    )

    assert result["terminal_state"] == "limits_exceeded"
    assert [call["args"][:2] for call in child_queue.enqueued] == [
        ("mas-3333333333333333", "task A"),
        ("mas-4444444444444444", "task B"),
    ]
    observation = _observation_text(json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())["messages"][3])
    assert "agent_id: mas-3333333333333333" in observation
    assert "agent_id: mas-4444444444444444" in observation
    assert "parent_agent_id: mas-1111111111111111" in observation
    assert (
        "trajectory_artifact_path: "
        ".mini-mas/agents/mas-3333333333333333/trajectory.traj.json"
        in observation
    )

def test_grandchildren_under_different_child_workflows_do_not_collide(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    first_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", first_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _agent_id: patch("builtins.id"))
    _patch_agent_ids(monkeypatch, workflows, ("mas-3333333333333333", "mas-4444444444444444"))

    for parent_workflow_id, queue in [
        ("mas-1111111111111111", first_queue),
        ("mas-2222222222222222", _recording_child_queue()),
    ]:
        monkeypatch.setattr(workflows, "child_agent_queue", queue)
        _set_agent_workflow_context(monkeypatch, workflows, parent_workflow_id)
        asyncio.run(
            workflows.execute_agent_workflow_actions(
                message=make_output("delegate", [{"command": 'mini-mas spawn "task"'}]),
                model=DeterministicModel(outputs=[]),
                env=Mock(),
            )
        )

    assert [call["args"][0] for call in first_queue.enqueued] == ["mas-3333333333333333"]
    assert [call["args"][0] for call in queue.enqueued] == ["mas-4444444444444444"]

def test_waited_spawn_defaults_to_wait_any_first_observable_event(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _agent_id: patch("builtins.id"))
    _patch_agent_ids(monkeypatch, workflows)
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
        if workflow_id == "mas-1111111111111111":
            return {
                "agent_id": workflow_id,
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "A ready",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": (
                    ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
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
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    assert [call["args"][0] for call in child_queue.enqueued] == [
        "mas-1111111111111111",
        "mas-2222222222222222",
    ]
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Waited spawn completed" in text
    assert "wait_mode: any" in text
    assert "ready_child_count: 1" in text
    assert "still_running_child_agent_ids: mas-2222222222222222" in text
    assert "latest_submission: A ready" in text

def test_waited_spawn_all_and_partial_timeout(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _agent_id: patch("builtins.id"))
    _patch_agent_ids(monkeypatch, workflows)
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "asyncio_wait",
        Mock(wraps=asyncio.wait),
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 0.01
        if workflow_id == "mas-1111111111111111":
            return {
                "agent_id": workflow_id,
                "lifecycle_state": "failed",
                "latest_error": "boom",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": (
                    ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
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
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Waited spawn timed out" in text
    assert "wait_mode: all" in text
    assert "ready_child_count: 1" in text
    assert "still_running_child_agent_ids: mas-2222222222222222" in text
    assert "latest_error: boom" in text

def test_waited_spawn_wait_any_timeout_returns_running_children(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _agent_id: patch("builtins.id"))
    _patch_agent_ids(monkeypatch, workflows)
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id in {"mas-1111111111111111", "mas-2222222222222222"}
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
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "Waited spawn timed out" in text
    assert "wait_mode: any" in text
    assert "ready_child_count: 0" in text
    assert "still_running_child_agent_ids: mas-1111111111111111, mas-2222222222222222" in text
    assert [call["args"][0] for call in child_queue.enqueued] == [
        "mas-1111111111111111",
        "mas-2222222222222222",
    ]

def test_waited_spawn_publishes_waiting_for_child_status_and_restores_running_on_timeout(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_queue = _recording_child_queue()
    published = []
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _agent_id: patch("builtins.id"))
    _patch_agent_ids(monkeypatch, workflows)

    async def set_event_async(key, value):
        published.append((key, value))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id in {"mas-1111111111111111", "mas-2222222222222222"}
        assert key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY
        assert timeout_seconds == 0.01
        await asyncio.sleep(10)

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("delegate", [{"command": 'mini-mas spawn --wait --timeout 0.01 "task A" "task B"'}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    assert "Waited spawn timed out" in _observation_text(observations[0])
    assert [(key, value["lifecycle_state"]) for key, value in published] == [
        (mas_status_events.STATUS_EVENT_KEY, "waiting_for_child"),
        (mas_status_events.STATUS_EVENT_KEY, "running"),
    ]
    assert all(key != mas_status_events.FIRST_OBSERVABLE_EVENT_KEY for key, _value in published)

def test_spawn_timeout_without_wait_is_invalid(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    message = make_output("invalid", [{"command": 'mini-mas spawn --timeout 1 "task"'}])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>2</returncode>" in text
    assert "Detached Spawn has no wait phase" in text

def test_invalid_wait_and_waited_spawn_commands_do_not_publish_waiting_for_child(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_direct_child_status_events(monkeypatch, workflows, "mas-0123456789abcdef", {})
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "set_event_async",
        Mock(side_effect=AssertionError("Invalid wait commands must not publish waiting_for_child")),
    )

    model = DeterministicModel(outputs=[])
    template_vars = {
        "parent_agent_id": "mas-0123456789abcdef",
        "agent_id": "mas-0123456789abcdef",
    }

    invalid_wait = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("bad wait", [{"command": "mini-mas wait --timeout 0.01"}]),
            model=model,
            env=Mock(),
            template_vars=template_vars,
        )
    )
    invalid_spawn = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("bad spawn", [{"command": 'mini-mas spawn --timeout 1 "task"'}]),
            model=model,
            env=Mock(),
            template_vars=template_vars,
        )
    )

    assert "No current child workflows found" in _observation_text(invalid_wait[0])
    assert "Detached Spawn has no wait phase" in _observation_text(invalid_spawn[0])

def test_workflow_wait_for_specific_child_uses_first_observable_event(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "agent_id": "mas-1111111111111111",
        "parent_agent_id": "mas-0123456789abcdef",
        "lifecycle_state": "running",
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
        "asyncio_wait",
        Mock(wraps=asyncio.wait),
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-1111111111111111"
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 60
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_parent",
            "latest_submission": "ready",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": (
                ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
            ),
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))

    message = make_output("wait", [{"command": "mini-mas wait mas-1111111111111111"}])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "mini-mas wait completed" in text
    assert "wait_mode: one" in text
    assert "ready_child_count: 1" in text
    assert "latest_submission: ready" in text

def test_workflow_wait_for_specific_child_publishes_waiting_for_child_status_and_restores_running(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "agent_id": "mas-1111111111111111",
        "parent_agent_id": "mas-0123456789abcdef",
        "lifecycle_state": "running",
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
    published = []

    async def set_event_async(key, value):
        published.append((key, value))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-1111111111111111"
        assert key == mas_status_events.FIRST_OBSERVABLE_EVENT_KEY
        return {
            "agent_id": workflow_id,
            "lifecycle_state": "waiting_for_parent",
            "latest_submission": "ready",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": (
                ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
            ),
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("wait", [{"command": "mini-mas wait mas-1111111111111111"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "mini-mas wait completed" in text
    assert [(key, value["lifecycle_state"]) for key, value in published] == [
        (mas_status_events.STATUS_EVENT_KEY, "waiting_for_child"),
        (mas_status_events.STATUS_EVENT_KEY, "running"),
    ]
    assert all(key != mas_status_events.FIRST_OBSERVABLE_EVENT_KEY for key, _value in published)

def test_workflow_wait_restores_running_when_first_observable_wait_raises(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "agent_id": "mas-1111111111111111",
        "parent_agent_id": "mas-0123456789abcdef",
        "lifecycle_state": "running",
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
    published = []

    async def set_event_async(key, value):
        published.append((key, value))

    async def get_event_async(_workflow_id, _key, timeout_seconds=60):
        raise RuntimeError("dbos wait failed")

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    with pytest.raises(RuntimeError, match="dbos wait failed"):
        asyncio.run(
            workflows.execute_agent_workflow_actions(
                message=make_output("wait", [{"command": "mini-mas wait mas-1111111111111111"}]),
                model=DeterministicModel(outputs=[]),
                env=Mock(),
                template_vars={
                    "parent_agent_id": "mas-0123456789abcdef",
                    "agent_id": "mas-0123456789abcdef",
                },
            )
        )

    assert [(key, value["lifecycle_state"]) for key, value in published] == [
        (mas_status_events.STATUS_EVENT_KEY, "waiting_for_child"),
        (mas_status_events.STATUS_EVENT_KEY, "running"),
    ]

def test_workflow_wait_any_all_and_timeout_use_current_child_statuses(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    statuses = {
        "mas-1111111111111111": {
            "agent_id": "mas-1111111111111111",
            "parent_agent_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": (
                ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
            ),
        },
        "mas-2222222222222222": {
            "agent_id": "mas-2222222222222222",
            "parent_agent_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": (
                ".mini-mas/agents/mas-2222222222222222/trajectory.traj.json"
            ),
        },
    }
    _mock_direct_child_status_events(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {workflow_id: {"mini_mas_status": snapshot} for workflow_id, snapshot in statuses.items()},
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 0.01
        if workflow_id == "mas-1111111111111111":
            return {
                "agent_id": workflow_id,
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "ready",
                "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
                "trajectory_artifact_path": (
                    ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
                ),
            }
        await asyncio.sleep(10)
        return None

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    model = DeterministicModel(outputs=[])
    template_vars = {
        "parent_agent_id": "mas-0123456789abcdef",
        "agent_id": "mas-0123456789abcdef",
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
    assert "still_running_child_agent_ids: mas-2222222222222222" in all_text

def test_workflow_wait_timeout_returns_running_children_when_none_are_ready(monkeypatch):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "agent_id": "mas-1111111111111111",
        "parent_agent_id": "mas-0123456789abcdef",
        "lifecycle_state": "running",
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

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-1111111111111111"
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 0.01
        await asyncio.sleep(10)

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("wait timeout", [{"command": "mini-mas wait --timeout 0.01"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "mini-mas wait timed out" in text
    assert "ready_child_count: 0" in text
    assert "still_running_child_agent_ids: mas-1111111111111111" in text
