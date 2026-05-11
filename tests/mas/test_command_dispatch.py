import asyncio
from unittest.mock import Mock


def test_mas_command_handler_accepts_classified_standalone_command():
    from minisweagent.mas.commands import MasCommandHandler, classify_mas_command

    handler = MasCommandHandler()

    result = asyncio.run(
        handler.execute(
            classify_mas_command("mini-mas wait --any"),
        )
    )

    assert result == {
        "output": "mini-mas wait requires Agent context.\n",
        "returncode": 2,
        "exception_info": "missing_agent_context",
        "extra": {"mas_command_error": "missing_agent_context"},
    }

def test_mas_command_handler_uses_agent_interaction_functions_for_spawn(monkeypatch):
    import minisweagent.mas.commands as commands
    from minisweagent.mas.agent_interactions import ChildWaitResult, SpawnChildrenResult
    from minisweagent.mas.commands import MasCommandHandler, classify_mas_command

    calls = []

    async def spawn_children(*, parent_workflow_id, tasks):
        calls.append(("spawn", parent_workflow_id, tuple(tasks)))
        child_ids = ["mas-1111111111111111", "mas-2222222222222222"] if len(tasks) > 1 else ["mas-3333333333333333"]
        return SpawnChildrenResult(
            children=[
                {
                    "task": task,
                    "agent_id": child_id,
                    "parent_agent_id": parent_workflow_id,
                    "agent_artifact_directory": f".mini-mas/agents/{child_id}",
                    "trajectory_artifact_path": f".mini-mas/agents/{child_id}/trajectory.traj.json",
                }
                for task, child_id in zip(tasks, child_ids)
            ]
        )

    async def wait_for_children(*, parent_workflow_id, children, wait_all, timeout_seconds, wait_mode):
        calls.append(
            (
                "wait_children",
                parent_workflow_id,
                tuple(child["agent_id"] for child in children),
                wait_all,
                timeout_seconds,
                wait_mode,
            )
        )
        return ChildWaitResult(
            children=list(children),
            ready_snapshots=[
                {
                    "agent_id": children[0]["agent_id"],
                    "lifecycle_state": "waiting_for_parent",
                    "latest_submission": "ready",
                    "agent_artifact_directory": children[0]["agent_artifact_directory"],
                    "trajectory_artifact_path": children[0]["trajectory_artifact_path"],
                }
            ],
            still_running_ids=[children[1]["agent_id"]],
            timed_out=True,
            wait_mode="all",
        )

    monkeypatch.setattr(commands.agent_interactions, "current_workflow_id", lambda: "mas-0123456789abcdef")
    monkeypatch.setattr(commands.agent_interactions, "spawn_children", spawn_children)
    monkeypatch.setattr(commands.agent_interactions, "wait_for_children", wait_for_children)
    handler = MasCommandHandler()

    result = asyncio.run(
        handler.execute(
            classify_mas_command('mini-mas spawn --wait --all --timeout 0.5 "task A" "task B"'),
        )
    )
    second_result = asyncio.run(handler.execute(classify_mas_command('mini-mas spawn "task C"')))

    assert calls == [
        (
            "spawn",
            "mas-0123456789abcdef",
            ("task A", "task B"),
        ),
        (
            "wait_children",
            "mas-0123456789abcdef",
            ("mas-1111111111111111", "mas-2222222222222222"),
            True,
            0.5,
            "all",
        ),
        (
            "spawn",
            "mas-0123456789abcdef",
            ("task C",),
        ),
    ]
    assert result["extra"]["waited"] is True
    assert result["extra"]["wait_mode"] == "all"
    assert result["extra"]["timed_out"] is True
    assert result["extra"]["still_running_child_agent_ids"] == ["mas-2222222222222222"]
    assert "Waited spawn timed out" in result["output"]
    assert "agent_id: mas-3333333333333333" in second_result["output"]

def test_explicit_parent_direction_commands_share_authority_policy_path(monkeypatch):
    import minisweagent.mas.commands as commands
    from minisweagent.mas.agent_interactions import ChildWaitResult
    from minisweagent.mas.commands import MasCommandHandler, classify_mas_command

    calls = []
    child_snapshot = {
        "agent_id": "mas-1111111111111111",
        "parent_agent_id": "mas-0123456789abcdef",
        "lifecycle_state": "waiting_for_parent",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": (
            ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
        ),
    }

    async def wait_for_children(*, parent_workflow_id, children, wait_all, timeout_seconds, wait_mode):
        assert parent_workflow_id == "mas-0123456789abcdef"
        assert [child["agent_id"] for child in children] == ["mas-1111111111111111"]
        assert wait_all is True
        assert timeout_seconds is None
        assert wait_mode == "one"
        return ChildWaitResult(
            children=list(children),
            ready_snapshots=[],
            still_running_ids=["mas-1111111111111111"],
            timed_out=True,
            wait_mode=wait_mode,
        )

    async def send_parent_direction(*, target_workflow_id, signal, topic):
        calls.append(("send", target_workflow_id, signal["type"], topic))

    class RecordingAuthorityPolicy:
        async def list_observable_children(self, *, parent_workflow_id):
            raise AssertionError("target commands should not list children")

        async def require_observable_child(self, *, parent_workflow_id, target_workflow_id, command_name):
            calls.append(("observable", parent_workflow_id, target_workflow_id, command_name))
            return child_snapshot

        async def require_waiting_child(self, *, parent_workflow_id, target_workflow_id, command_name):
            calls.append(("waiting", parent_workflow_id, target_workflow_id, command_name))
            return child_snapshot

    monkeypatch.setattr(commands.agent_interactions, "current_workflow_id", lambda: "mas-0123456789abcdef")
    monkeypatch.setattr(commands.agent_interactions, "wait_for_children", wait_for_children)
    monkeypatch.setattr(commands.agent_interactions, "send_parent_direction", send_parent_direction)

    handler = MasCommandHandler(authority=RecordingAuthorityPolicy())

    for command in [
        "mini-mas status mas-1111111111111111",
        "mini-mas wait mas-1111111111111111",
        'mini-mas continue mas-1111111111111111 "go"',
        "mini-mas close mas-1111111111111111",
    ]:
        result = asyncio.run(handler.execute(classify_mas_command(command)))
        assert result["returncode"] == 0

    assert calls[:3] == [
        ("observable", "mas-0123456789abcdef", "mas-1111111111111111", "status"),
        ("observable", "mas-0123456789abcdef", "mas-1111111111111111", "wait"),
        ("waiting", "mas-0123456789abcdef", "mas-1111111111111111", "continue"),
    ]
    assert calls[3][0] == "send"
    assert calls[4] == ("waiting", "mas-0123456789abcdef", "mas-1111111111111111", "close")
    assert calls[5][0] == "send"

def test_no_target_status_and_wait_use_injected_authority_policy(monkeypatch):
    import minisweagent.mas.commands as commands
    from minisweagent.mas.agent_interactions import ChildWaitResult
    from minisweagent.mas.commands import MasCommandHandler, classify_mas_command

    calls = []
    child_snapshot = {
        "agent_id": "mas-1111111111111111",
        "parent_agent_id": "mas-0123456789abcdef",
        "lifecycle_state": "waiting_for_parent",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": (
            ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
        ),
    }

    class ListingAuthorityPolicy:
        async def list_observable_children(self, *, parent_workflow_id):
            calls.append(("list", parent_workflow_id))
            return [child_snapshot]

        async def require_observable_child(self, *, parent_workflow_id, target_workflow_id, command_name):
            raise AssertionError("no-target commands should list children")

        async def require_waiting_child(self, *, parent_workflow_id, target_workflow_id, command_name):
            raise AssertionError("no-target commands should list children")

    async def wait_for_children(*, parent_workflow_id, children, wait_all, timeout_seconds, wait_mode):
        calls.append(
            (
                "wait_children",
                parent_workflow_id,
                tuple(child["agent_id"] for child in children),
                wait_all,
                timeout_seconds,
                wait_mode,
            )
        )
        return ChildWaitResult(
            children=list(children),
            ready_snapshots=[child_snapshot],
            still_running_ids=[],
            timed_out=False,
            wait_mode=wait_mode,
        )

    async def forbidden_direct_statuses(parent_workflow_id):
        raise AssertionError("handler should use authority policy for no-target status")

    monkeypatch.setattr(commands.agent_interactions, "current_workflow_id", lambda: "mas-0123456789abcdef")
    monkeypatch.setattr(commands.agent_interactions, "query_direct_child_statuses", forbidden_direct_statuses)
    monkeypatch.setattr(commands.agent_interactions, "wait_for_children", wait_for_children)

    handler = MasCommandHandler(authority=ListingAuthorityPolicy())

    status_result = asyncio.run(handler.execute(classify_mas_command("mini-mas status")))
    wait_result = asyncio.run(handler.execute(classify_mas_command("mini-mas wait --all")))

    assert status_result["returncode"] == 0
    assert wait_result["returncode"] == 0
    assert calls == [
        ("list", "mas-0123456789abcdef"),
        ("list", "mas-0123456789abcdef"),
        (
            "wait_children",
            "mas-0123456789abcdef",
            ("mas-1111111111111111",),
            True,
            None,
            "all",
        ),
    ]

def test_each_mas_agent_owns_private_command_handler():
    from minisweagent.mas.commands import MasCommandHandler
    from minisweagent.mas.mas_agent import MasAgent

    first_agent = MasAgent(
        agent_id="mas-0123456789abcdef",
        model=Mock(),
        env=Mock(),
        step_limit=1,
    )
    second_agent = MasAgent(
        agent_id="mas-1111111111111111",
        parent_agent_id="mas-0123456789abcdef",
        model=Mock(),
        env=Mock(),
        step_limit=1,
    )

    assert isinstance(first_agent.command_handler, MasCommandHandler)
    assert isinstance(second_agent.command_handler, MasCommandHandler)
    assert first_agent.command_handler is not second_agent.command_handler

def test_mas_command_handler_execute_signature_has_no_caller_context_dependencies():
    import inspect

    from minisweagent.mas.authority import DirectChildAuthorityPolicy
    from minisweagent.mas.commands import MasCommandHandler

    assert list(inspect.signature(MasCommandHandler.execute).parameters) == ["self", "classification"]

    constructor_parameters = inspect.signature(MasCommandHandler).parameters
    assert "current_workflow_id" not in constructor_parameters
    assert "query_direct_child_statuses" not in constructor_parameters
    assert "authority_policy" not in constructor_parameters
    assert "child_coordinator" not in constructor_parameters
    assert "send_continuation_signal" not in constructor_parameters
    assert "send_close_signal" not in constructor_parameters
    handler = MasCommandHandler()
    assert isinstance(handler.authority, DirectChildAuthorityPolicy)

def test_mas_command_behavior_is_consolidated_in_commands_module():
    import minisweagent.mas.commands as commands

    assert commands.MasCommandHandler.__module__ == "minisweagent.mas.commands"
    assert commands.MasCommandResultFormatter.__module__ == "minisweagent.mas.commands"
