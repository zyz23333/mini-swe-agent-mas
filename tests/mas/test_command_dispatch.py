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
        "output": "mini-mas wait requires Agent Workflow context.\n",
        "returncode": 2,
        "exception_info": "missing_agent_workflow_context",
        "extra": {"mas_command_error": "missing_agent_workflow_context"},
    }

def test_mas_command_handler_owns_spawn_cursor_and_uses_coordination_functions(monkeypatch):
    import minisweagent.mas.commands as commands
    from minisweagent.mas.commands import MasCommandHandler, classify_mas_command
    from minisweagent.mas.coordination import ChildWaitResult, SpawnChildrenResult

    calls = []

    async def spawn_children(*, root_workflow_id, parent_workflow_id, first_spawn_index, tasks):
        calls.append(("spawn", root_workflow_id, parent_workflow_id, first_spawn_index, tuple(tasks)))
        return SpawnChildrenResult(
            children=[
                {
                    "task": task,
                    "root_workflow_id": root_workflow_id,
                    "workflow_id": f"{parent_workflow_id}-c{first_spawn_index + offset:03d}",
                    "run_directory": f".mini-mas/runs/{root_workflow_id}",
                    "trajectory_artifact_path": (
                        f".mini-mas/runs/{root_workflow_id}/trajectories/"
                        f"{parent_workflow_id}-c{first_spawn_index + offset:03d}.traj.json"
                    ),
                }
                for offset, task in enumerate(tasks)
            ]
        )

    async def wait_for_children(*, parent_workflow_id, children, wait_all, timeout_seconds, wait_mode):
        calls.append(
            (
                "wait_children",
                parent_workflow_id,
                tuple(child["workflow_id"] for child in children),
                wait_all,
                timeout_seconds,
                wait_mode,
            )
        )
        return ChildWaitResult(
            children=list(children),
            ready_snapshots=[
                {
                    "workflow_id": children[0]["workflow_id"],
                    "lifecycle_state": "waiting_for_parent",
                    "latest_submission": "ready",
                    "run_directory": children[0]["run_directory"],
                    "trajectory_artifact_path": children[0]["trajectory_artifact_path"],
                }
            ],
            still_running_ids=[children[1]["workflow_id"]],
            timed_out=True,
            wait_mode="all",
        )

    monkeypatch.setattr(commands.coordination, "current_workflow_id", lambda: "mas-0123456789abcdef")
    monkeypatch.setattr(commands.coordination, "spawn_children", spawn_children)
    monkeypatch.setattr(commands.coordination, "wait_for_children", wait_for_children)
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
            "mas-0123456789abcdef",
            1,
            ("task A", "task B"),
        ),
        (
            "wait_children",
            "mas-0123456789abcdef",
            ("mas-0123456789abcdef-c001", "mas-0123456789abcdef-c002"),
            True,
            0.5,
            "all",
        ),
        (
            "spawn",
            "mas-0123456789abcdef",
            "mas-0123456789abcdef",
            3,
            ("task C",),
        ),
    ]
    assert handler.next_spawn_index == 4
    assert result["extra"]["waited"] is True
    assert result["extra"]["wait_mode"] == "all"
    assert result["extra"]["timed_out"] is True
    assert result["extra"]["still_running_child_workflow_ids"] == ["mas-0123456789abcdef-c002"]
    assert "Waited spawn timed out" in result["output"]
    assert "workflow_id: mas-0123456789abcdef-c003" in second_result["output"]

def test_explicit_parent_direction_commands_share_authority_policy_path(monkeypatch):
    import minisweagent.mas.commands as commands
    from minisweagent.mas.commands import MasCommandHandler, classify_mas_command
    from minisweagent.mas.coordination import ChildWaitResult

    calls = []
    child_snapshot = {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef-c001",
        "lifecycle_state": "waiting_for_parent",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        ),
    }

    async def wait_for_children(*, parent_workflow_id, children, wait_all, timeout_seconds, wait_mode):
        assert parent_workflow_id == "mas-0123456789abcdef"
        assert [child["workflow_id"] for child in children] == ["mas-0123456789abcdef-c001"]
        assert wait_all is True
        assert timeout_seconds is None
        assert wait_mode == "one"
        return ChildWaitResult(
            children=list(children),
            ready_snapshots=[],
            still_running_ids=["mas-0123456789abcdef-c001"],
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

    monkeypatch.setattr(commands.coordination, "current_workflow_id", lambda: "mas-0123456789abcdef")
    monkeypatch.setattr(commands.coordination, "wait_for_children", wait_for_children)
    monkeypatch.setattr(commands.coordination, "send_parent_direction", send_parent_direction)

    handler = MasCommandHandler(authority=RecordingAuthorityPolicy())

    for command in [
        "mini-mas status mas-0123456789abcdef-c001",
        "mini-mas wait mas-0123456789abcdef-c001",
        'mini-mas continue mas-0123456789abcdef-c001 "go"',
        "mini-mas close mas-0123456789abcdef-c001",
    ]:
        result = asyncio.run(handler.execute(classify_mas_command(command)))
        assert result["returncode"] == 0

    assert calls[:3] == [
        ("observable", "mas-0123456789abcdef", "mas-0123456789abcdef-c001", "status"),
        ("observable", "mas-0123456789abcdef", "mas-0123456789abcdef-c001", "wait"),
        ("waiting", "mas-0123456789abcdef", "mas-0123456789abcdef-c001", "continue"),
    ]
    assert calls[3][0] == "send"
    assert calls[4] == ("waiting", "mas-0123456789abcdef", "mas-0123456789abcdef-c001", "close")
    assert calls[5][0] == "send"

def test_no_target_status_and_wait_use_injected_authority_policy(monkeypatch):
    import minisweagent.mas.commands as commands
    from minisweagent.mas.commands import MasCommandHandler, classify_mas_command
    from minisweagent.mas.coordination import ChildWaitResult

    calls = []
    child_snapshot = {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef-c001",
        "lifecycle_state": "waiting_for_parent",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
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
                tuple(child["workflow_id"] for child in children),
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

    monkeypatch.setattr(commands.coordination, "current_workflow_id", lambda: "mas-0123456789abcdef")
    monkeypatch.setattr(commands.coordination, "query_direct_child_statuses", forbidden_direct_statuses)
    monkeypatch.setattr(commands.coordination, "wait_for_children", wait_for_children)

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
            ("mas-0123456789abcdef-c001",),
            True,
            None,
            "all",
        ),
    ]

def test_each_mas_agent_owns_private_command_handler():
    from minisweagent.mas.commands import MasCommandHandler
    from minisweagent.mas.mas_agent import MasAgent

    first_agent = MasAgent(
        root_workflow_id="mas-0123456789abcdef",
        workflow_id="mas-0123456789abcdef",
        model=Mock(),
        env=Mock(),
        step_limit=1,
    )
    second_agent = MasAgent(
        root_workflow_id="mas-0123456789abcdef",
        workflow_id="mas-0123456789abcdef-c001",
        model=Mock(),
        env=Mock(),
        step_limit=1,
    )

    assert isinstance(first_agent.command_handler, MasCommandHandler)
    assert isinstance(second_agent.command_handler, MasCommandHandler)
    assert first_agent.command_handler is not second_agent.command_handler
    assert first_agent.command_handler.next_spawn_index == 1
    assert second_agent.command_handler.next_spawn_index == 1

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
