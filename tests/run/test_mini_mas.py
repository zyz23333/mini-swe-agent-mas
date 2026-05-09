import asyncio
import importlib
import inspect
import json
import re
from unittest.mock import MagicMock, Mock, patch

import pytest
from typer.testing import CliRunner

from minisweagent.mas.cli import app, run
from minisweagent.mas.runtime import close_agent_workflow, make_root_workflow_id
from minisweagent.models.test_models import (
    DeterministicModel,
    DeterministicResponseAPIToolcallModel,
    DeterministicToolcallModel,
    make_output,
    make_response_api_output,
    make_toolcall_output,
)


def _mock_dbos_module() -> MagicMock:
    dbos_module = MagicMock()
    dbos_module.DBOS.workflow.return_value = lambda func: func
    dbos_module.DBOS.step.return_value = lambda func: func
    return dbos_module


def _mock_recording_dbos_module() -> MagicMock:
    dbos_module = MagicMock()
    dbos_module.registered_steps = []
    dbos_module.DBOS.workflow.return_value = lambda func: func

    def record_step(func):
        dbos_module.registered_steps.append(func.__name__)
        return func

    dbos_module.DBOS.step.return_value = record_step
    return dbos_module


def _observation_text(message: dict) -> str:
    if message.get("type") == "function_call_output":
        return message["output"]
    content = message.get("content", "")
    if isinstance(content, list):
        return content[0]["text"]
    return content


def _call_root_agent_workflow(workflow_func, *args, **kwargs):
    while hasattr(workflow_func, "__wrapped__"):
        workflow_func = workflow_func.__wrapped__
    return asyncio.run(workflow_func(*args, **kwargs))


def _recording_child_queue():
    class RecordingChildQueue:
        def __init__(self):
            self.enqueued = []

        async def enqueue_async(self, workflow_func, *args, **kwargs):
            handle = Mock()
            handle.workflow_id = args[1]
            handle.get_workflow_id.return_value = args[1]
            self.enqueued.append(
                {
                    "workflow_func": workflow_func,
                    "args": args,
                    "kwargs": kwargs,
                    "handle": handle,
                }
            )
            return handle

    return RecordingChildQueue()


def _workflow_status_record(workflow_id: str, parent_workflow_id: str | None = None) -> Mock:
    status = Mock()
    status.workflow_id = workflow_id
    status.parent_workflow_id = parent_workflow_id
    return status


def _set_agent_workflow_context(monkeypatch, workflows, workflow_id: str | None) -> None:
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", workflow_id)


def _mock_direct_child_status_events(monkeypatch, workflows, parent_workflow_id: str, events_by_workflow: dict) -> None:
    async def list_workflows_async(**kwargs):
        assert kwargs.get("parent_workflow_id") == parent_workflow_id
        requested_ids = kwargs.get("workflow_ids")
        workflow_ids = requested_ids if requested_ids is not None else events_by_workflow.keys()
        return [
            _workflow_status_record(workflow_id, parent_workflow_id)
            for workflow_id in workflow_ids
            if workflow_id in events_by_workflow
        ]

    async def get_all_events_async(workflow_id):
        return events_by_workflow[workflow_id]

    monkeypatch.setattr(workflows._dbos.DBOS, "list_workflows_async", Mock(side_effect=list_workflows_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "get_all_events_async", Mock(side_effect=get_all_events_async))


def _mock_single_direct_child_status(monkeypatch, workflows, parent_workflow_id: str, snapshot: dict) -> None:
    _mock_direct_child_status_events(
        monkeypatch,
        workflows,
        parent_workflow_id,
        {snapshot["workflow_id"]: {"mini_mas_status": snapshot}},
    )


class AsyncMockHandle:
    def __init__(self, workflow_id, result=None):
        self.workflow_id = workflow_id
        self._result = result

    def get_workflow_id(self):
        return self.workflow_id

    async def get_result(self):
        return self._result


def test_mini_mas_run_initializes_launches_and_starts_root_workflow():
    """mini-mas run is the external path that activates DBOS for MAS work."""
    handle = AsyncMockHandle(
        "mas-1111111111111111",
        {
            "root_workflow_id": "mas-1111111111111111",
            "workflow_id": "mas-1111111111111111",
            "status": "started",
            "run_directory": ".mini-mas/runs/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
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


def test_mini_mas_run_returns_detached_metadata_without_waiting_for_result():
    handle = AsyncMockHandle(
        "mas-1111111111111111",
        {
            "root_workflow_id": "mas-1111111111111111",
            "workflow_id": "mas-1111111111111111",
            "status": "started",
            "run_directory": ".mini-mas/runs/mas-1111111111111111",
            "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
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
        "root_workflow_id": "mas-1111111111111111",
        "workflow_id": "mas-1111111111111111",
        "run_directory": ".mini-mas/runs/mas-1111111111111111",
        "trajectory_artifact_path": ".mini-mas/runs/mas-1111111111111111/trajectories/mas-1111111111111111.traj.json",
    }


def test_external_close_runtime_is_unsupported_until_interactive_root_terminal_exists(monkeypatch):
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        result = close_agent_workflow(workflow_id="mas-1111111111111111-c001")

    dbos_module.DBOS.assert_not_called()
    dbos_module.DBOS.launch.assert_not_called()
    assert result["returncode"] == 2
    assert result["exception_info"] == "external_coordination_unsupported"
    assert "unsupported until terminal commands are routed through an Interactive Root Agent Workflow" in result["output"]


def test_mini_mas_run_cli_outputs_artifact_locations():
    handle = AsyncMockHandle(
        "mas-2222222222222222",
        {
            "root_workflow_id": "mas-2222222222222222",
            "workflow_id": "mas-2222222222222222",
            "status": "started",
            "run_directory": ".mini-mas/runs/mas-2222222222222222",
            "trajectory_artifact_path": ".mini-mas/runs/mas-2222222222222222/trajectories/mas-2222222222222222.traj.json",
        },
    )

    async def start_workflow_async(*_args, **_kwargs):
        return handle

    dbos_module = _mock_dbos_module()
    dbos_module.DBOS.start_workflow_async = Mock(side_effect=start_workflow_async)

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


def test_mini_mas_status_cli_reports_external_coordination_unsupported(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.get_agent_workflow_status",
        Mock(
            return_value={
                "kind": "unsupported",
                "workflow_id": "mas-2222222222222222",
                "output": "External mini-mas status, wait, continue, and close are unsupported.\n",
                "returncode": 2,
                "exception_info": "external_coordination_unsupported",
                "extra": {"mas_command_error": "external_coordination_unsupported"},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["status", "mas-2222222222222222"])
    assert cli_result.exit_code == 2
    assert "unsupported" in cli_result.stdout


def test_mini_mas_status_cli_does_not_support_missing_descendant_lookup(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.get_agent_workflow_status",
        Mock(
            return_value={
                "kind": "unsupported",
                "workflow_id": "mas-2222222222222222-c999",
                "output": "External mini-mas status, wait, continue, and close are unsupported.\n",
                "returncode": 2,
                "exception_info": "external_coordination_unsupported",
                "extra": {"mas_command_error": "external_coordination_unsupported"},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["status", "mas-2222222222222222-c999"])

    assert cli_result.exit_code == 2
    assert "unsupported" in cli_result.stdout


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

    result = _call_root_agent_workflow(workflows.root_agent_workflow, "mas-0123456789abcdef")

    assert result == {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef",
        "status": "started",
        "terminal_state": "started",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef.traj.json",
    }
    trajectory_path = tmp_path / result["trajectory_artifact_path"]
    assert trajectory_path.exists()
    artifact = json.loads(trajectory_path.read_text())
    assert artifact["info"]["workflow_id"] == "mas-0123456789abcdef"
    assert artifact["info"]["run_directory"] == ".mini-mas/runs/mas-0123456789abcdef"


def test_child_agent_workflow_writes_artifact_under_root_run_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    import minisweagent.mas.workflows as workflows

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "inspect api",
    )

    assert result == {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef-c001",
        "status": "started",
        "terminal_state": "started",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json",
    }
    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["root_workflow_id"] == "mas-0123456789abcdef"
    assert artifact["info"]["workflow_id"] == "mas-0123456789abcdef-c001"
    assert artifact["info"]["run_directory"] == ".mini-mas/runs/mas-0123456789abcdef"


def test_root_agent_workflow_is_registered_as_dbos_workflow_when_module_loads():
    """The root workflow is defined inside the MAS subsystem boundary."""
    dbos_module = _mock_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.workflows

        importlib.reload(minisweagent.mas.workflows)

    dbos_module.DBOS.workflow.assert_called()


def test_agent_workflows_are_async_dbos_workflows():
    import minisweagent.mas.workflows as workflows

    assert inspect.iscoroutinefunction(getattr(workflows.root_agent_workflow, "__wrapped__", workflows.root_agent_workflow))
    assert inspect.iscoroutinefunction(
        getattr(workflows.child_agent_workflow, "__wrapped__", workflows.child_agent_workflow)
    )


def test_model_bash_and_trajectory_operations_are_registered_as_dbos_steps():
    """Model calls, ordinary bash execution, and trajectory persistence are checkpointed as DBOS steps."""
    dbos_module = _mock_recording_dbos_module()

    with patch("minisweagent.mas.runtime.load_dbos", return_value=dbos_module):
        import minisweagent.mas.workflows

        importlib.reload(minisweagent.mas.workflows)

    assert "query_model_step" in dbos_module.registered_steps
    assert "execute_bash_step" in dbos_module.registered_steps
    assert "save_root_trajectory_artifact_step" in dbos_module.registered_steps
    assert "save_child_trajectory_artifact_step" in dbos_module.registered_steps


@pytest.mark.parametrize(
    ("command", "expected_arguments"),
    [
        ("mini-mas status", ["status"]),
        (" mini-mas spawn 'check parser' ", ["spawn", "check parser"]),
        ("mini-mas wait --any", ["wait", "--any"]),
    ],
)
def test_standalone_mas_commands_are_detected(command, expected_arguments):
    from minisweagent.mas.commands import MasCommandKind, classify_mas_command

    parsed = classify_mas_command(command)

    assert parsed.kind == MasCommandKind.STANDALONE
    assert parsed.arguments == expected_arguments


@pytest.mark.parametrize(
    "command",
    [
        "echo mini-mas status",
        "mini-mas status && echo done",
        "mini-mas status | cat",
        "mini-mas status > out.txt",
        "DEBUG=1 mini-mas status",
        "for x in 1; do mini-mas status; done",
        "$(mini-mas status)",
    ],
)
def test_shell_compositions_containing_mini_mas_are_rejected_for_interception(command):
    from minisweagent.mas.commands import MasCommandKind, classify_mas_command

    parsed = classify_mas_command(command)

    assert parsed.kind == MasCommandKind.INVALID
    assert "standalone command" in parsed.error


@pytest.mark.parametrize("command", ["echo hello", "python -c 'print(42)'"])
def test_ordinary_bash_without_mini_mas_is_not_intercepted(command):
    from minisweagent.mas.commands import MasCommandKind, classify_mas_command

    parsed = classify_mas_command(command)

    assert parsed.kind == MasCommandKind.ORDINARY_BASH


def test_workflow_action_execution_dispatches_standalone_mas_commands():
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    message = make_output("dispatch", [{"command": "mini-mas wait --any"}])
    env = Mock()
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    assert len(observations) == 1
    assert "mini-mas wait requires Agent Workflow context" in _observation_text(observations[0])


def test_mas_command_handler_accepts_classified_standalone_command():
    from minisweagent.mas.command_dispatch import MasCommandHandler
    from minisweagent.mas.commands import classify_mas_command

    handler = MasCommandHandler(current_workflow_id=lambda: None)

    result = asyncio.run(
        handler.execute(
            classify_mas_command("mini-mas wait --any"),
            spawn_index=1,
            existing_child_workflow_ids=set(),
        )
    )

    assert result == {
        "output": "mini-mas wait requires Agent Workflow context.\n",
        "returncode": 2,
        "exception_info": "missing_agent_workflow_context",
        "extra": {"mas_command_error": "missing_agent_workflow_context"},
    }


def test_dbos_coordination_adapter_owns_status_first_observable_wait_and_messages(monkeypatch):
    import minisweagent.mas.workflows as workflows
    from minisweagent.mas.coordination import DBOSCoordinationAdapter
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY, STATUS_EVENT_KEY

    dbos_api = Mock()
    published = []
    received = []
    sent = []

    async def set_event_async(key, value):
        published.append((key, value))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-0123456789abcdef-c001"
        assert key == FIRST_OBSERVABLE_EVENT_KEY
        assert timeout_seconds == 0.25
        return {
            "workflow_id": workflow_id,
            "lifecycle_state": "waiting_for_parent",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
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

    adapter = DBOSCoordinationAdapter(
        dbos_api=dbos_api,
        child_agent_queue=Mock(),
        set_workflow_id=lambda _workflow_id: patch("builtins.id"),
        child_agent_workflow=workflows.child_agent_workflow,
    )

    assert adapter.current_agent_workflow_id() == "mas-0123456789abcdef"
    asyncio.run(
        adapter.publish_status(
            root_workflow_id="mas-0123456789abcdef",
            workflow_id="mas-0123456789abcdef",
            lifecycle_state="waiting_for_child",
        )
    )
    asyncio.run(
        adapter.publish_first_observable(
            root_workflow_id="mas-0123456789abcdef",
            workflow_id="mas-0123456789abcdef-c001",
            lifecycle_state="waiting_for_parent",
        )
    )
    ready, still_running, timed_out = asyncio.run(
        adapter.wait_for_first_observable_events(
            child_workflow_ids=["mas-0123456789abcdef-c001"],
            wait_all=False,
            timeout_seconds=0.25,
        )
    )
    signal = asyncio.run(adapter.receive_parent_direction(topic=workflows.PARENT_DIRECTION_TOPIC, timeout_seconds=3))
    asyncio.run(
        adapter.send_parent_direction(
            target_workflow_id="mas-0123456789abcdef-c001",
            signal={"type": "close"},
            topic=workflows.PARENT_DIRECTION_TOPIC,
        )
    )

    assert [(key, value["lifecycle_state"]) for key, value in published] == [
        (STATUS_EVENT_KEY, "waiting_for_child"),
        (FIRST_OBSERVABLE_EVENT_KEY, "waiting_for_parent"),
    ]
    assert ready[0]["workflow_id"] == "mas-0123456789abcdef-c001"
    assert still_running == []
    assert timed_out is False
    assert signal == {"type": "close"}
    assert received == [(workflows.PARENT_DIRECTION_TOPIC, 3)]
    assert sent == [("mas-0123456789abcdef-c001", {"type": "close"}, workflows.PARENT_DIRECTION_TOPIC)]


def test_child_coordinator_owns_spawn_and_wait_domain_behavior():
    from minisweagent.mas.command_dispatch import MasCommandHandler
    from minisweagent.mas.commands import classify_mas_command
    from minisweagent.mas.coordination import ChildCoordinator, ChildWaitResult, SpawnChildrenResult

    class RecordingCoordinator(ChildCoordinator):
        def __init__(self):
            super().__init__(adapter=Mock())
            self.calls = []

        async def spawn_children(
            self,
            *,
            root_workflow_id,
            parent_workflow_id,
            first_spawn_index,
            tasks,
            existing_child_workflow_ids,
        ):
            self.calls.append(
                (
                    "spawn",
                    root_workflow_id,
                    parent_workflow_id,
                    first_spawn_index,
                    tuple(tasks),
                    existing_child_workflow_ids,
                )
            )
            return SpawnChildrenResult(
                children=[
                    {
                        "task": "task A",
                        "root_workflow_id": root_workflow_id,
                        "workflow_id": f"{parent_workflow_id}-c001",
                        "run_directory": f".mini-mas/runs/{root_workflow_id}",
                        "trajectory_artifact_path": (
                            f".mini-mas/runs/{root_workflow_id}/trajectories/{parent_workflow_id}-c001.traj.json"
                        ),
                    },
                    {
                        "task": "task B",
                        "root_workflow_id": root_workflow_id,
                        "workflow_id": f"{parent_workflow_id}-c002",
                        "run_directory": f".mini-mas/runs/{root_workflow_id}",
                        "trajectory_artifact_path": (
                            f".mini-mas/runs/{root_workflow_id}/trajectories/{parent_workflow_id}-c002.traj.json"
                        ),
                    },
                ]
            )

        async def wait_for_spawned_children(self, *, parent_workflow_id, children, wait_all, timeout_seconds):
            self.calls.append(
                (
                    "wait_spawned",
                    parent_workflow_id,
                    tuple(child["workflow_id"] for child in children),
                    wait_all,
                    timeout_seconds,
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

    coordinator = RecordingCoordinator()
    handler = MasCommandHandler(
        current_workflow_id=lambda: "mas-0123456789abcdef",
        child_coordinator=coordinator,
    )

    result = asyncio.run(
        handler.execute(
            classify_mas_command('mini-mas spawn --wait --all --timeout 0.5 "task A" "task B"'),
            spawn_index=1,
            existing_child_workflow_ids=set(),
        )
    )

    assert coordinator.calls == [
        (
            "spawn",
            "mas-0123456789abcdef",
            "mas-0123456789abcdef",
            1,
            ("task A", "task B"),
            set(),
        ),
        (
            "wait_spawned",
            "mas-0123456789abcdef",
            ("mas-0123456789abcdef-c001", "mas-0123456789abcdef-c002"),
            True,
            0.5,
        ),
    ]
    assert result["extra"]["waited"] is True
    assert result["extra"]["wait_mode"] == "all"
    assert result["extra"]["timed_out"] is True
    assert result["extra"]["still_running_child_workflow_ids"] == ["mas-0123456789abcdef-c002"]
    assert "Waited spawn timed out" in result["output"]


def test_explicit_parent_direction_commands_share_authority_policy_path():
    from minisweagent.mas.command_dispatch import MasCommandHandler
    from minisweagent.mas.commands import classify_mas_command
    from minisweagent.mas.coordination import ChildCoordinator, ChildWaitResult

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

    class RecordingPolicy:
        async def require_direct_child(self, parent_workflow_id, target_workflow_id):
            calls.append(("direct", parent_workflow_id, target_workflow_id))
            return child_snapshot

        async def require_waiting_direct_child(self, parent_workflow_id, target_workflow_id, command_name):
            calls.append(("waiting", parent_workflow_id, target_workflow_id, command_name))
            return child_snapshot

    class RecordingCoordinator(ChildCoordinator):
        def __init__(self):
            super().__init__(adapter=Mock())

        async def wait_for_children(self, *, parent_workflow_id, children, wait_all, timeout_seconds, wait_mode):
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

    async def send_continuation_signal(_source_workflow_id, target_workflow_id, content, snapshot):
        return {
            "output": f"continued {target_workflow_id}: {content}\n",
            "returncode": 0,
            "exception_info": "",
            "extra": {"target_status": snapshot},
        }

    async def send_close_signal(_source_workflow_id, target_workflow_id, snapshot):
        return {
            "output": f"closed {target_workflow_id}\n",
            "returncode": 0,
            "exception_info": "",
            "extra": {"target_status": snapshot},
        }

    handler = MasCommandHandler(
        current_workflow_id=lambda: "mas-0123456789abcdef",
        authority_policy=RecordingPolicy(),
        child_coordinator=RecordingCoordinator(),
        send_continuation_signal=send_continuation_signal,
        send_close_signal=send_close_signal,
    )

    for command in [
        "mini-mas status mas-0123456789abcdef-c001",
        "mini-mas wait mas-0123456789abcdef-c001",
        'mini-mas continue mas-0123456789abcdef-c001 "go"',
        "mini-mas close mas-0123456789abcdef-c001",
    ]:
        result = asyncio.run(
            handler.execute(
                classify_mas_command(command),
                spawn_index=1,
                existing_child_workflow_ids=set(),
            )
        )
        assert result["returncode"] == 0

    assert calls == [
        ("direct", "mas-0123456789abcdef", "mas-0123456789abcdef-c001"),
        ("direct", "mas-0123456789abcdef", "mas-0123456789abcdef-c001"),
        ("waiting", "mas-0123456789abcdef", "mas-0123456789abcdef-c001", "continue"),
        ("waiting", "mas-0123456789abcdef", "mas-0123456789abcdef-c001", "close"),
    ]


def test_direct_child_authority_policy_success_and_rejection_paths():
    from minisweagent.mas.authority import AuthorityCommandError, AuthorizedChild, DirectChildAuthorityPolicy

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

    async def query_direct_child_status(parent_workflow_id, target_workflow_id):
        assert parent_workflow_id == "mas-0123456789abcdef"
        return snapshots.get(target_workflow_id)

    policy = DirectChildAuthorityPolicy(query_direct_child_status=query_direct_child_status)

    authorized = asyncio.run(
        policy.require_direct_child("mas-0123456789abcdef", "mas-0123456789abcdef-c001")
    )
    not_direct = asyncio.run(
        policy.require_direct_child("mas-0123456789abcdef", "mas-0123456789abcdef-c001-c001")
    )
    not_waiting = asyncio.run(
        policy.require_waiting_direct_child("mas-0123456789abcdef", "mas-0123456789abcdef-c002", "continue")
    )

    assert isinstance(authorized, AuthorizedChild)
    assert authorized.workflow_id == "mas-0123456789abcdef-c001"
    assert authorized.metadata()["trajectory_artifact_path"].endswith("mas-0123456789abcdef-c001.traj.json")
    assert isinstance(not_direct, AuthorityCommandError)
    assert not_direct.exception_info == "workflow_not_direct_child"
    assert isinstance(not_waiting, AuthorityCommandError)
    assert not_waiting.exception_info == "workflow_not_waiting_for_parent"


def test_workflow_status_reports_current_tree_without_blocking(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    events_by_workflow = {
        "mas-0123456789abcdef-c001": {
            "mini_mas_status": {
                "workflow_id": "mas-0123456789abcdef-c001",
                "root_workflow_id": "mas-0123456789abcdef",
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "ready for review",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
                ),
            }
        },
    }
    _mock_direct_child_status_events(monkeypatch, workflows, "mas-0123456789abcdef", events_by_workflow)
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "list_workflows",
        Mock(side_effect=AssertionError("Agent Workflow status dispatch must use list_workflows_async")),
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_all_events",
        Mock(side_effect=AssertionError("Agent Workflow status dispatch must use get_all_events_async")),
    )

    message = make_output("status", [{"command": "mini-mas status"}])
    model = DeterministicModel(outputs=[])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=model,
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    workflows._dbos.DBOS.list_workflows_async.assert_called_once_with(
        parent_workflow_id="mas-0123456789abcdef",
        load_input=False,
        load_output=False,
    )
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Direct Child Agent Workflows for: mas-0123456789abcdef" in text
    assert "workflow_id: mas-0123456789abcdef\n" not in text
    assert "workflow_id: mas-0123456789abcdef-c001" in text
    assert "lifecycle_state: waiting_for_parent" in text
    assert "latest_submission: ready for review" in text
    assert "trajectory_artifact_path: .mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json" in text


def test_workflow_status_reports_specific_descendant_and_missing_workflow(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "workflow_id": "mas-0123456789abcdef-c001",
        "root_workflow_id": "mas-0123456789abcdef",
        "lifecycle_state": "failed",
        "latest_error": "model failed",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        ),
    }
    _mock_direct_child_status_events(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {"mas-0123456789abcdef-c001": {"mini_mas_status": child_status}},
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "get_all_events",
        Mock(side_effect=AssertionError("Agent Workflow status dispatch must use get_all_events_async")),
    )

    model = DeterministicModel(outputs=[])
    found = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("status child", [{"command": "mini-mas status mas-0123456789abcdef-c001"}]),
            model=model,
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    found_text = _observation_text(found[0])
    assert "<returncode>0</returncode>" in found_text
    assert "workflow_id: mas-0123456789abcdef-c001" in found_text
    assert "lifecycle_state: failed" in found_text
    assert "latest_error: model failed" in found_text

    missing = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("missing child", [{"command": "mini-mas status mas-0123456789abcdef-c999"}]),
            model=model,
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    missing_text = _observation_text(missing[0])
    assert "<returncode>1</returncode>" in missing_text
    assert "Workflow is not a direct Child Agent Workflow of mas-0123456789abcdef: mas-0123456789abcdef-c999" in missing_text


def test_status_snapshot_accepts_waiting_for_child_lifecycle_state():
    from minisweagent.mas.status import make_status_snapshot

    snapshot = make_status_snapshot(
        root_workflow_id="mas-0123456789abcdef",
        workflow_id="mas-0123456789abcdef-c001",
        lifecycle_state="waiting_for_child",
    )

    assert snapshot.to_event()["lifecycle_state"] == "waiting_for_child"


def test_agent_workflow_publishes_running_submission_and_limits_status(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import Submitted

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(key, value):
        published.append((key, value))

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "set_event",
        Mock(side_effect=AssertionError("Agent Workflow status publishing must use set_event_async")),
    )

    model = DeterministicModel(outputs=[make_output("submit", [{"command": "submit"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = Submitted(
        {
            "role": "exit",
            "content": "done",
            "extra": {"exit_status": "Submitted", "submission": "done"},
        }
    )

    _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="submit once",
        step_limit=3,
    )

    assert [event[0] for event in published] == ["mini_mas_status", "mini_mas_status"]
    assert published[0][1]["lifecycle_state"] == "running"
    assert published[0][1]["workflow_tree_id"] == "mas-0123456789abcdef"
    assert published[1][1]["lifecycle_state"] == "closed"
    assert published[1][1]["latest_submission"] == "done"
    assert "messages" not in published[1][1]

    published.clear()
    limit_model = DeterministicModel(outputs=[make_output("work", [{"command": "echo hi"}], cost=0.1)])
    limit_env = Mock()
    limit_env.get_template_vars.return_value = {}
    limit_env.execute.return_value = {"output": "hi\n", "returncode": 0, "exception_info": ""}

    _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=limit_model,
        env=limit_env,
        task="hit limit",
        step_limit=1,
    )

    assert published[-1][1]["lifecycle_state"] == "limits_exceeded"


def test_agent_workflow_publishes_failed_status(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import InterruptAgentFlow

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef")

    async def set_event_async(_key, value):
        published.append(value)

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "set_event",
        Mock(side_effect=AssertionError("Agent Workflow status publishing must use set_event_async")),
    )

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}

    async def failing_model(_model, _messages):
        raise InterruptAgentFlow(
            {
                "role": "exit",
                "content": "model failed",
                "extra": {"exit_status": "failed", "submission": ""},
            }
        )

    monkeypatch.setattr(workflows, "query_model_step", failing_model)

    _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="fail",
        step_limit=3,
    )

    assert published[-1]["lifecycle_state"] == "failed"
    assert published[-1]["latest_error"] == "model failed"


def test_child_workflow_waits_after_first_submission_and_sets_first_observable_event(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import Submitted
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY, STATUS_EVENT_KEY

    monkeypatch.chdir(tmp_path)
    published = []
    received = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        received.append((topic, timeout_seconds))
        return {"type": "test_stop_waiting"}

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv",
        Mock(side_effect=AssertionError("Child waiting must use recv_async")),
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "send_async",
        Mock(side_effect=AssertionError("Child status must not use child-to-parent send")),
    )

    model = DeterministicModel(outputs=[make_output("submit", [{"command": "submit"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = Submitted(
        {
            "role": "exit",
            "content": "child done",
            "extra": {"exit_status": "Submitted", "submission": "child done"},
        }
    )

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "submit once",
        model=model,
        env=env,
        step_limit=3,
    )

    assert result["terminal_state"] == "waiting_for_parent"
    assert result["latest_submission"] == "child done"
    assert received == [(workflows.PARENT_DIRECTION_TOPIC, workflows.PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS)]
    status_events = [value for key, value in published if key == STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == ["running", "waiting_for_parent"]
    waiting_event = status_events[-1]
    assert waiting_event["workflow_id"] == "mas-0123456789abcdef-c001"
    assert waiting_event["latest_submission"] == "child done"
    assert (
        waiting_event["trajectory_artifact_path"]
        == ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
    )
    first_observable_events = [value for key, value in published if key == FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable_events == [waiting_event]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["exit_status"] == "waiting_for_parent"
    assert artifact["info"]["submission"] == "child done"
    assert artifact["messages"][-1]["extra"] == {"exit_status": "Submitted", "submission": "child done"}


def test_child_workflow_receives_close_and_publishes_closed_status(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import Submitted
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY, STATUS_EVENT_KEY

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        assert topic == workflows.PARENT_DIRECTION_TOPIC
        assert timeout_seconds == workflows.PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS
        return {
            "type": "close",
            "signal_type": "mas_close",
            "source_workflow_id": "mas-0123456789abcdef",
            "target_workflow_id": "mas-0123456789abcdef-c001",
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv",
        Mock(side_effect=AssertionError("Child close waiting must use recv_async")),
    )

    model = DeterministicModel(outputs=[make_output("submit", [{"command": "submit"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = Submitted(
        {
            "role": "exit",
            "content": "child done",
            "extra": {"exit_status": "Submitted", "submission": "child done"},
        }
    )

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "submit once",
        model=model,
        env=env,
        step_limit=3,
    )

    assert result["status"] == "closed"
    assert result["terminal_state"] == "closed"
    assert result["latest_submission"] == "child done"
    assert result["parent_direction_signal"]["signal_type"] == "mas_close"

    status_events = [value for key, value in published if key == STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == ["running", "waiting_for_parent", "closed"]
    closed_event = status_events[-1]
    assert closed_event["latest_submission"] == "child done"
    assert closed_event["trajectory_artifact_path"] == result["trajectory_artifact_path"]

    first_observable_events = [value for key, value in published if key == FIRST_OBSERVABLE_EVENT_KEY]
    assert [event["lifecycle_state"] for event in first_observable_events] == ["waiting_for_parent"]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["exit_status"] == "closed"
    assert artifact["info"]["submission"] == "child done"
    assert artifact["messages"][-1]["extra"] == {"exit_status": "Submitted", "submission": "child done"}


def test_child_workflow_sets_first_observable_event_for_failure_and_limits(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import InterruptAgentFlow
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

    async def set_event_async(key, value):
        published.append((key, value))

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv_async",
        Mock(side_effect=AssertionError("Failed or limited child should not wait for parent direction")),
    )

    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}

    async def failing_model(_model, _messages):
        raise InterruptAgentFlow(
            {
                "role": "exit",
                "content": "model failed",
                "extra": {"exit_status": "failed", "submission": ""},
            }
        )

    monkeypatch.setattr(workflows, "query_model_step", failing_model)

    _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "fail",
        model=model,
        env=env,
        step_limit=3,
    )

    first_observable = [value for key, value in published if key == FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable == [
        {
            "root_workflow_id": "mas-0123456789abcdef",
            "workflow_id": "mas-0123456789abcdef-c001",
            "workflow_tree_id": "mas-0123456789abcdef-c001",
            "lifecycle_state": "failed",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
            "latest_error": "model failed",
        }
    ]

    published.clear()

    async def replay_model_response(_model, _messages):
        return make_output("work", [{"command": "echo hi"}], cost=0.1)

    monkeypatch.setattr(workflows, "query_model_step", replay_model_response)
    monkeypatch.setattr(
        workflows,
        "execute_bash_step",
        lambda _env, _action: {"output": "hi\n", "returncode": 0, "exception_info": ""},
    )

    _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c002",
        "hit limit",
        model=model,
        env=env,
        step_limit=1,
    )

    first_observable = [value for key, value in published if key == FIRST_OBSERVABLE_EVENT_KEY]
    assert first_observable[-1]["workflow_id"] == "mas-0123456789abcdef-c002"
    assert first_observable[-1]["lifecycle_state"] == "limits_exceeded"


def test_workflow_action_execution_keeps_ordinary_bash_on_bash_path():
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    message = make_output("bash", [{"command": "echo hello"}])
    env = Mock()
    env.execute.return_value = {"output": "hello\n", "returncode": 0, "exception_info": ""}
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_called_once_with({"command": "echo hello"})
    assert "<returncode>0</returncode>" in _observation_text(observations[0])
    assert "hello" in _observation_text(observations[0])


@pytest.mark.parametrize(
    "command",
    [
        "echo before && mini-mas status",
        "mini-mas status | cat",
        "DEBUG=1 mini-mas status",
        "for x in 1; do mini-mas status; done",
    ],
)
def test_workflow_action_execution_rejects_shell_compositions_without_executing_bash(command):
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    message = make_output("reject", [{"command": command}])
    env = Mock()
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    text = _observation_text(observations[0])
    assert "<returncode>2</returncode>" in text
    assert "mini-mas must be issued as a standalone command" in text


@pytest.mark.parametrize(
    ("model", "message", "expected_marker"),
    [
        (
            DeterministicModel(outputs=[]),
            make_output("text", [{"command": "mini-mas status && echo no"}]),
            "role",
        ),
        (
            DeterministicToolcallModel(outputs=[]),
            make_toolcall_output(
                "tool",
                [
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command": "mini-mas status && echo no"}'},
                    }
                ],
                [{"command": "mini-mas status && echo no", "tool_call_id": "call_0"}],
            ),
            "tool_call_id",
        ),
        (
            DeterministicResponseAPIToolcallModel(outputs=[]),
            make_response_api_output(
                "responses",
                [{"command": "mini-mas status && echo no", "tool_call_id": "call_resp_0"}],
            ),
            "call_id",
        ),
    ],
)
def test_mas_rejections_use_existing_model_specific_observation_formatters(model, message, expected_marker):
    from minisweagent.mas.workflows import execute_agent_workflow_actions

    env = Mock()

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    assert expected_marker in observations[0]
    assert "mini-mas must be issued as a standalone command" in _observation_text(observations[0])


def test_root_agent_workflow_runs_model_and_bash_path_and_saves_trajectory(tmp_path, monkeypatch):
    from minisweagent.exceptions import Submitted
    from minisweagent.mas.workflows import root_agent_workflow

    monkeypatch.chdir(tmp_path)
    model = DeterministicModel(
        outputs=[
            make_output("inspect", [{"command": "echo hello"}], cost=0.25),
            make_output("submit", [{"command": "submit"}], cost=0.25),
        ],
        cost_per_call=0.25,
    )
    env = Mock()
    env.get_template_vars.return_value = {"cwd": tmp_path.as_posix()}
    env.serialize.return_value = {"info": {"config": {"environment_type": "deterministic-env"}}}
    env.execute.side_effect = [
        {"output": "hello\n", "returncode": 0, "exception_info": ""},
        Submitted(
            {
                "role": "exit",
                "content": "done",
                "extra": {"exit_status": "Submitted", "submission": "done"},
            }
        ),
    ]

    result = _call_root_agent_workflow(
        root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="exercise ordinary path",
        step_limit=3,
    )

    assert result["terminal_state"] == "Submitted"
    assert result["submission"] == "done"
    assert result["model_stats"] == {"instance_cost": 0.5, "api_calls": 2}
    trajectory_path = tmp_path / result["trajectory_artifact_path"]
    artifact = json.loads(trajectory_path.read_text())
    assert artifact["info"]["exit_status"] == "Submitted"
    assert artifact["info"]["submission"] == "done"
    assert artifact["info"]["model_stats"] == {"instance_cost": 0.5, "api_calls": 2}
    assert artifact["messages"][2]["content"] == "inspect"
    assert "hello" in _observation_text(artifact["messages"][3])
    assert artifact["messages"][-1]["extra"] == {"exit_status": "Submitted", "submission": "done"}


def test_root_agent_workflow_can_replay_successful_model_and_bash_step_results(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

    monkeypatch.chdir(tmp_path)
    model = DeterministicModel(outputs=[])
    env = Mock()
    env.get_template_vars.return_value = {}

    def replay_model_response(_model, _messages):
        return make_output("replayed model", [{"command": "echo replay"}], cost=0.1)

    def replay_bash_output(_env, _action):
        return {"output": "replayed output\n", "returncode": 0, "exception_info": ""}

    monkeypatch.setattr(workflows, "query_model_step", replay_model_response)
    monkeypatch.setattr(workflows, "execute_bash_step", replay_bash_output)

    result = _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="replay checkpoints",
        step_limit=1,
    )

    env.execute.assert_not_called()
    assert result["terminal_state"] == "limits_exceeded"
    trajectory_path = tmp_path / result["trajectory_artifact_path"]
    artifact = json.loads(trajectory_path.read_text())
    assert artifact["info"]["exit_status"] == "limits_exceeded"
    assert artifact["info"]["model_stats"] == {"instance_cost": 0.1, "api_calls": 1}
    assert artifact["messages"][2]["content"] == "replayed model"
    assert "replayed output" in _observation_text(artifact["messages"][3])
    assert artifact["messages"][-1]["extra"] == {"exit_status": "limits_exceeded", "submission": ""}


def test_root_agent_workflow_keeps_standalone_mas_commands_out_of_bash_step(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

    monkeypatch.chdir(tmp_path)
    model = DeterministicModel(outputs=[make_output("check status", [{"command": "mini-mas status"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    bash_step = Mock(side_effect=AssertionError("standalone MAS command entered bash step"))
    monkeypatch.setattr(workflows, "execute_bash_step", bash_step)

    result = _call_root_agent_workflow(
        workflows.root_agent_workflow,
        "mas-0123456789abcdef",
        model=model,
        env=env,
        task="route mas command",
        step_limit=1,
    )

    env.execute.assert_not_called()
    bash_step.assert_not_called()
    assert result["terminal_state"] == "limits_exceeded"
    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert "Direct Child Agent Workflows for: mas-0123456789abcdef" in _observation_text(artifact["messages"][3])


def test_detached_spawn_returns_child_metadata_and_uses_child_queue(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

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

    assert set_workflow_ids == ["mas-0123456789abcdef-c001"]
    assert len(child_queue.enqueued) == 1
    child_call = child_queue.enqueued[0]
    assert child_call["workflow_func"].__name__ == "child_agent_workflow"
    assert child_call["args"][:3] == (
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "inspect api",
    )
    assert child_call["kwargs"] == {}
    assert result["terminal_state"] == "limits_exceeded"

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    observation = _observation_text(artifact["messages"][3])
    assert "Detached spawn started" in observation
    assert "workflow_id: mas-0123456789abcdef-c001" in observation
    assert "run_directory: .mini-mas/runs/mas-0123456789abcdef" in observation
    assert (
        "trajectory_artifact_path: "
        ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        in observation
    )


def test_detached_spawn_allocates_stable_sibling_child_ids_without_duplicate_enqueue(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

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
    assert [call["args"][1] for call in child_queue.enqueued] == [
        "mas-0123456789abcdef-c001",
        "mas-0123456789abcdef-c002",
    ]

    replay_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", replay_queue)
    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    replay_observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=first_message,
            model=model,
            env=env,
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
                "spawn_index": 0,
                "existing_child_workflow_ids": ["mas-0123456789abcdef-c001"],
            },
        )
    )

    assert replay_queue.enqueued == []
    assert "workflow_id: mas-0123456789abcdef-c001" in _observation_text(replay_observations[0])


def test_detached_multi_spawn_returns_all_child_metadata_without_waiting(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

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
    assert [call["args"][:3] for call in child_queue.enqueued] == [
        ("mas-0123456789abcdef", "mas-0123456789abcdef-c001", "task A"),
        ("mas-0123456789abcdef", "mas-0123456789abcdef-c002", "task B"),
    ]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    observation = _observation_text(artifact["messages"][3])
    assert "Detached spawn started" in observation
    assert "workflow_id: mas-0123456789abcdef-c001" in observation
    assert "workflow_id: mas-0123456789abcdef-c002" in observation
    assert "trajectory_artifact_path: .mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json" in observation
    assert "trajectory_artifact_path: .mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c002.traj.json" in observation


def test_child_agent_workflow_can_spawn_grandchildren_with_parent_relative_ids(tmp_path, monkeypatch):
    import minisweagent.mas.workflows as workflows

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
    model = DeterministicModel(
        outputs=[make_output("delegate to grandchildren", [{"command": 'mini-mas spawn "task A" "task B"'}], cost=0.1)]
    )
    env = Mock()
    env.get_template_vars.return_value = {}

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "delegate recursively",
        model=model,
        env=env,
        step_limit=1,
    )

    assert result["terminal_state"] == "limits_exceeded"
    assert [call["args"][:3] for call in child_queue.enqueued] == [
        ("mas-0123456789abcdef", "mas-0123456789abcdef-c001-c001", "task A"),
        ("mas-0123456789abcdef", "mas-0123456789abcdef-c001-c002", "task B"),
    ]
    observation = _observation_text(json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())["messages"][3])
    assert "workflow_id: mas-0123456789abcdef-c001-c001" in observation
    assert "workflow_id: mas-0123456789abcdef-c001-c002" in observation
    assert "run_directory: .mini-mas/runs/mas-0123456789abcdef" in observation
    assert (
        "trajectory_artifact_path: "
        ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001-c001.traj.json"
        in observation
    )


def test_grandchildren_under_different_child_workflows_do_not_collide(monkeypatch):
    import minisweagent.mas.workflows as workflows

    first_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", first_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _workflow_id: patch("builtins.id"))

    for parent_workflow_id, queue in [
        ("mas-0123456789abcdef-c001", first_queue),
        ("mas-0123456789abcdef-c002", _recording_child_queue()),
    ]:
        monkeypatch.setattr(workflows, "child_agent_queue", queue)
        _set_agent_workflow_context(monkeypatch, workflows, parent_workflow_id)
        asyncio.run(
            workflows.execute_agent_workflow_actions(
                message=make_output("delegate", [{"command": 'mini-mas spawn "task"'}]),
                model=DeterministicModel(outputs=[]),
                env=Mock(),
                template_vars={"spawn_index": 0},
            )
        )

    assert [call["args"][1] for call in first_queue.enqueued] == ["mas-0123456789abcdef-c001-c001"]
    assert [call["args"][1] for call in queue.enqueued] == ["mas-0123456789abcdef-c002-c001"]


def test_root_cannot_status_or_wait_for_grandchild_through_transitive_authority(monkeypatch):
    import minisweagent.mas.workflows as workflows

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


def test_waited_spawn_defaults_to_wait_any_first_observable_event(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _workflow_id: patch("builtins.id"))
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
        if workflow_id.endswith("-c001"):
            return {
                "workflow_id": workflow_id,
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "A ready",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
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
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    assert [call["args"][1] for call in child_queue.enqueued] == [
        "mas-0123456789abcdef-c001",
        "mas-0123456789abcdef-c002",
    ]
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Waited spawn completed" in text
    assert "wait_mode: any" in text
    assert "ready_child_count: 1" in text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c002" in text
    assert "latest_submission: A ready" in text


def test_waited_spawn_all_and_partial_timeout(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _workflow_id: patch("builtins.id"))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "asyncio_wait",
        Mock(wraps=asyncio.wait),
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 0.01
        if workflow_id.endswith("-c001"):
            return {
                "workflow_id": workflow_id,
                "lifecycle_state": "failed",
                "latest_error": "boom",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
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
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Waited spawn timed out" in text
    assert "wait_mode: all" in text
    assert "ready_child_count: 1" in text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c002" in text
    assert "latest_error: boom" in text


def test_waited_spawn_wait_any_timeout_returns_running_children(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_queue = _recording_child_queue()
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _workflow_id: patch("builtins.id"))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id in {"mas-0123456789abcdef-c001", "mas-0123456789abcdef-c002"}
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
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "Waited spawn timed out" in text
    assert "wait_mode: any" in text
    assert "ready_child_count: 0" in text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c001, mas-0123456789abcdef-c002" in text
    assert [call["args"][1] for call in child_queue.enqueued] == [
        "mas-0123456789abcdef-c001",
        "mas-0123456789abcdef-c002",
    ]


def test_waited_spawn_publishes_waiting_for_child_status_and_restores_running_on_timeout(monkeypatch):
    import minisweagent.mas.workflows as workflows
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY, STATUS_EVENT_KEY

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_queue = _recording_child_queue()
    published = []
    monkeypatch.setattr(workflows, "child_agent_queue", child_queue)
    monkeypatch.setattr(workflows._dbos, "SetWorkflowID", lambda _workflow_id: patch("builtins.id"))

    async def set_event_async(key, value):
        published.append((key, value))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id in {"mas-0123456789abcdef-c001", "mas-0123456789abcdef-c002"}
        assert key == FIRST_OBSERVABLE_EVENT_KEY
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
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    assert "Waited spawn timed out" in _observation_text(observations[0])
    assert [(key, value["lifecycle_state"]) for key, value in published] == [
        (STATUS_EVENT_KEY, "waiting_for_child"),
        (STATUS_EVENT_KEY, "running"),
    ]
    assert all(key != FIRST_OBSERVABLE_EVENT_KEY for key, _value in published)


def test_spawn_timeout_without_wait_is_invalid(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    message = make_output("invalid", [{"command": 'mini-mas spawn --timeout 1 "task"'}])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "<returncode>2</returncode>" in text
    assert "Detached Spawn has no wait phase" in text


def test_invalid_wait_and_waited_spawn_commands_do_not_publish_waiting_for_child(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_direct_child_status_events(monkeypatch, workflows, "mas-0123456789abcdef", {})
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "set_event_async",
        Mock(side_effect=AssertionError("Invalid wait commands must not publish waiting_for_child")),
    )

    model = DeterministicModel(outputs=[])
    template_vars = {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef",
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
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "workflow_id": "mas-0123456789abcdef-c001",
        "root_workflow_id": "mas-0123456789abcdef",
        "lifecycle_state": "running",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        ),
    }
    _mock_direct_child_status_events(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {"mas-0123456789abcdef-c001": {"mini_mas_status": child_status}},
    )
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "asyncio_wait",
        Mock(wraps=asyncio.wait),
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-0123456789abcdef-c001"
        assert key == "mini_mas_first_observable"
        assert timeout_seconds == 60
        return {
            "workflow_id": workflow_id,
            "lifecycle_state": "waiting_for_parent",
            "latest_submission": "ready",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))

    message = make_output("wait", [{"command": "mini-mas wait mas-0123456789abcdef-c001"}])
    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
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
    import minisweagent.mas.workflows as workflows
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY, STATUS_EVENT_KEY

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "workflow_id": "mas-0123456789abcdef-c001",
        "root_workflow_id": "mas-0123456789abcdef",
        "lifecycle_state": "running",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        ),
    }
    _mock_direct_child_status_events(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {"mas-0123456789abcdef-c001": {"mini_mas_status": child_status}},
    )
    published = []

    async def set_event_async(key, value):
        published.append((key, value))

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-0123456789abcdef-c001"
        assert key == FIRST_OBSERVABLE_EVENT_KEY
        return {
            "workflow_id": workflow_id,
            "lifecycle_state": "waiting_for_parent",
            "latest_submission": "ready",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=make_output("wait", [{"command": "mini-mas wait mas-0123456789abcdef-c001"}]),
            model=DeterministicModel(outputs=[]),
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "mini-mas wait completed" in text
    assert [(key, value["lifecycle_state"]) for key, value in published] == [
        (STATUS_EVENT_KEY, "waiting_for_child"),
        (STATUS_EVENT_KEY, "running"),
    ]
    assert all(key != FIRST_OBSERVABLE_EVENT_KEY for key, _value in published)


def test_workflow_wait_restores_running_when_first_observable_wait_raises(monkeypatch):
    import minisweagent.mas.workflows as workflows
    from minisweagent.mas.status import STATUS_EVENT_KEY

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "workflow_id": "mas-0123456789abcdef-c001",
        "root_workflow_id": "mas-0123456789abcdef",
        "lifecycle_state": "running",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        ),
    }
    _mock_direct_child_status_events(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {"mas-0123456789abcdef-c001": {"mini_mas_status": child_status}},
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
                message=make_output("wait", [{"command": "mini-mas wait mas-0123456789abcdef-c001"}]),
                model=DeterministicModel(outputs=[]),
                env=Mock(),
                template_vars={
                    "root_workflow_id": "mas-0123456789abcdef",
                    "workflow_id": "mas-0123456789abcdef",
                },
            )
        )

    assert [(key, value["lifecycle_state"]) for key, value in published] == [
        (STATUS_EVENT_KEY, "waiting_for_child"),
        (STATUS_EVENT_KEY, "running"),
    ]


def test_workflow_wait_any_all_and_timeout_use_current_child_statuses(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    statuses = {
        "mas-0123456789abcdef-c001": {
            "workflow_id": "mas-0123456789abcdef-c001",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
            ),
        },
        "mas-0123456789abcdef-c002": {
            "workflow_id": "mas-0123456789abcdef-c002",
            "root_workflow_id": "mas-0123456789abcdef",
            "lifecycle_state": "running",
            "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
            "trajectory_artifact_path": (
                ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c002.traj.json"
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
        if workflow_id.endswith("-c001"):
            return {
                "workflow_id": workflow_id,
                "lifecycle_state": "waiting_for_parent",
                "latest_submission": "ready",
                "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
                "trajectory_artifact_path": (
                    ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
                ),
            }
        await asyncio.sleep(10)
        return None

    monkeypatch.setattr(workflows._dbos.DBOS, "get_event_async", Mock(side_effect=get_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "asyncio_wait", Mock(wraps=asyncio.wait))

    model = DeterministicModel(outputs=[])
    template_vars = {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef",
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
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c002" in all_text


def test_workflow_wait_timeout_returns_running_children_when_none_are_ready(monkeypatch):
    import minisweagent.mas.workflows as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    child_status = {
        "workflow_id": "mas-0123456789abcdef-c001",
        "root_workflow_id": "mas-0123456789abcdef",
        "lifecycle_state": "running",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        ),
    }
    _mock_direct_child_status_events(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {"mas-0123456789abcdef-c001": {"mini_mas_status": child_status}},
    )

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        assert workflow_id == "mas-0123456789abcdef-c001"
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
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    text = _observation_text(observations[0])
    assert "mini-mas wait timed out" in text
    assert "ready_child_count: 0" in text
    assert "still_running_child_workflow_ids: mas-0123456789abcdef-c001" in text


def test_workflow_continue_sends_parent_to_child_continuation_signal(monkeypatch):
    import minisweagent.mas.workflows as workflows

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
            workflows.PARENT_DIRECTION_TOPIC,
        )
    ]
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Continuation signal sent" in text
    assert "workflow_id: mas-0123456789abcdef-c001" in text


def test_workflow_close_sends_parent_to_child_neutral_close_signal(monkeypatch):
    import minisweagent.mas.workflows as workflows

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
            workflows.PARENT_DIRECTION_TOPIC,
        )
    ]
    text = _observation_text(observations[0])
    assert "<returncode>0</returncode>" in text
    assert "Close signal sent" in text
    assert "workflow_id: mas-0123456789abcdef-c001" in text
    assert "lifecycle_state: waiting_for_parent" in text
    assert "accepted" not in text.lower()
    assert "rejected" not in text.lower()
    assert "aborted" not in text.lower()
    assert "cancel" not in text.lower()


@pytest.mark.parametrize(
    ("command", "expected_error"),
    [
        ("mini-mas continue mas-0123456789abcdef root", "Cannot continue the current Agent Workflow"),
        (
            "mini-mas continue mas-fedcba9876543210-c001 no",
            "Workflow is not a direct Child Agent Workflow of mas-0123456789abcdef",
        ),
        (
            "mini-mas continue mas-0123456789abcdef-c002 no",
            "Workflow is not a direct Child Agent Workflow of mas-0123456789abcdef",
        ),
    ],
)
def test_workflow_continue_rejects_root_outside_tree_and_missing_children(monkeypatch, command, expected_error):
    import minisweagent.mas.workflows as workflows

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
    import minisweagent.mas.workflows as workflows

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
    assert "Workflow is not a direct Child Agent Workflow of mas-0123456789abcdef-c001: mas-0123456789abcdef-c002" in text


@pytest.mark.parametrize(
    ("command", "expected_error"),
    [
        ("mini-mas close mas-0123456789abcdef", "Cannot close the current Agent Workflow"),
        (
            "mini-mas close mas-fedcba9876543210-c001",
            "Workflow is not a direct Child Agent Workflow of mas-0123456789abcdef",
        ),
        (
            "mini-mas close mas-0123456789abcdef-c002",
            "Workflow is not a direct Child Agent Workflow of mas-0123456789abcdef",
        ),
    ],
)
def test_workflow_close_rejects_root_outside_tree_and_missing_children(monkeypatch, command, expected_error):
    import minisweagent.mas.workflows as workflows

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
    import minisweagent.mas.workflows as workflows

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
    assert "Workflow is not a direct Child Agent Workflow of mas-0123456789abcdef-c001: mas-0123456789abcdef-c002" in text


@pytest.mark.parametrize("lifecycle_state", ["closed", "failed", "limits_exceeded", "running", "waiting_for_child"])
def test_workflow_close_rejects_not_waiting_or_terminal_workflows(monkeypatch, lifecycle_state):
    import minisweagent.mas.workflows as workflows

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
    assert "Workflow is not waiting for parent direction: mas-0123456789abcdef-c001" in text


def test_workflow_continue_and_close_reject_waiting_for_child_status(monkeypatch):
    import minisweagent.mas.workflows as workflows

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
        assert "Workflow is not waiting for parent direction: mas-0123456789abcdef-c001" in text


@pytest.mark.parametrize(
    ("model", "message", "expected_marker"),
    [
        (
            DeterministicModel(outputs=[]),
            make_output("continue", [{"command": 'mini-mas continue mas-0123456789abcdef-c001 "go on"'}]),
            "role",
        ),
        (
            DeterministicToolcallModel(outputs=[]),
            make_toolcall_output(
                "tool",
                [
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": '{"command": "mini-mas continue mas-0123456789abcdef-c001 \\"go on\\""}',
                        },
                    }
                ],
                [{"command": 'mini-mas continue mas-0123456789abcdef-c001 "go on"', "tool_call_id": "call_0"}],
            ),
            "tool_call_id",
        ),
        (
            DeterministicResponseAPIToolcallModel(outputs=[]),
            make_response_api_output(
                "responses",
                [{"command": 'mini-mas continue mas-0123456789abcdef-c001 "go on"', "tool_call_id": "call_resp_0"}],
            ),
            "call_id",
        ),
    ],
)
def test_mas_continue_uses_existing_model_specific_observation_formatters(monkeypatch, model, message, expected_marker):
    import minisweagent.mas.workflows as workflows

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
        },
    )

    async def send_async(_destination_id, _message, topic=None):
        assert topic == workflows.PARENT_DIRECTION_TOPIC

    monkeypatch.setattr(workflows._dbos.DBOS, "send_async", Mock(side_effect=send_async))

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=model,
            env=Mock(),
            template_vars={
                "root_workflow_id": "mas-0123456789abcdef",
                "workflow_id": "mas-0123456789abcdef",
            },
        )
    )

    assert expected_marker in observations[0]
    assert "Continuation signal sent" in _observation_text(observations[0])


def test_child_workflow_injects_continuation_and_resumes_existing_trajectory(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import Submitted
    from minisweagent.mas.status import STATUS_EVENT_KEY

    monkeypatch.chdir(tmp_path)
    published = []
    received = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        received.append((topic, timeout_seconds))
        if len(received) == 1:
            return {
                "type": "continuation",
                "signal_type": "mas_continuation",
                "content": "please revise",
                "source_workflow_id": "mas-0123456789abcdef",
                "target_workflow_id": "mas-0123456789abcdef-c001",
            }
        return {"type": "test_stop_waiting"}

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))
    monkeypatch.setattr(
        workflows._dbos.DBOS,
        "recv",
        Mock(side_effect=AssertionError("Child continuation waiting must use recv_async")),
    )

    model = DeterministicModel(
        outputs=[
            make_output("first", [{"command": "submit first"}], cost=0.1),
            make_output("second", [{"command": "submit second"}], cost=0.1),
        ]
    )
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = [
        Submitted(
            {
                "role": "exit",
                "content": "first submission",
                "extra": {"exit_status": "Submitted", "submission": "first submission"},
            }
        ),
        Submitted(
            {
                "role": "exit",
                "content": "second submission",
                "extra": {"exit_status": "Submitted", "submission": "second submission"},
            }
        ),
    ]

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "submit once",
        model=model,
        env=env,
        step_limit=4,
    )

    assert result["terminal_state"] == "waiting_for_parent"
    assert result["latest_submission"] == "second submission"
    assert len(received) == 2
    status_events = [value for key, value in published if key == STATUS_EVENT_KEY]
    assert [event["lifecycle_state"] for event in status_events] == [
        "running",
        "waiting_for_parent",
        "running",
        "waiting_for_parent",
    ]
    assert status_events[-1]["latest_submission"] == "second submission"

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    messages = artifact["messages"]
    continuation_messages = [
        message
        for message in messages
        if message.get("role") == "user"
        and message.get("extra", {}).get("mas", {}).get("signal_type") == "mas_continuation"
    ]
    assert len(continuation_messages) == 1
    assert continuation_messages[0]["content"] == "please revise"
    assert continuation_messages[0]["extra"]["mas"]["source_workflow_id"] == "mas-0123456789abcdef"
    assert messages[-1]["extra"] == {"exit_status": "Submitted", "submission": "second submission"}
    assert artifact["info"]["exit_status"] == "waiting_for_parent"
    assert artifact["info"]["submission"] == "second submission"


def test_child_workflow_publishes_terminal_status_after_continuation(monkeypatch, tmp_path):
    import minisweagent.mas.workflows as workflows
    from minisweagent.exceptions import InterruptAgentFlow, Submitted
    from minisweagent.mas.status import FIRST_OBSERVABLE_EVENT_KEY, STATUS_EVENT_KEY

    monkeypatch.chdir(tmp_path)
    published = []
    monkeypatch.setattr(workflows._dbos.DBOS, "workflow_id", "mas-0123456789abcdef-c001")

    async def set_event_async(key, value):
        published.append((key, value))

    async def recv_async(topic=None, timeout_seconds=60):
        assert topic == workflows.PARENT_DIRECTION_TOPIC
        assert timeout_seconds == workflows.PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS
        return {
            "type": "continuation",
            "signal_type": "mas_continuation",
            "content": "try again",
            "source_workflow_id": "mas-0123456789abcdef",
            "target_workflow_id": "mas-0123456789abcdef-c001",
        }

    monkeypatch.setattr(workflows._dbos.DBOS, "set_event_async", Mock(side_effect=set_event_async))
    monkeypatch.setattr(workflows._dbos.DBOS, "recv_async", Mock(side_effect=recv_async))

    model = DeterministicModel(outputs=[make_output("first", [{"command": "submit first"}], cost=0.1)])
    env = Mock()
    env.get_template_vars.return_value = {}
    env.execute.side_effect = Submitted(
        {
            "role": "exit",
            "content": "first submission",
            "extra": {"exit_status": "Submitted", "submission": "first submission"},
        }
    )

    async def query_model_step(_model, messages):
        if any(message.get("extra", {}).get("mas", {}).get("signal_type") == "mas_continuation" for message in messages):
            raise InterruptAgentFlow(
                {
                    "role": "exit",
                    "content": "model failed after continuation",
                    "extra": {"exit_status": "failed", "submission": ""},
                }
            )
        return _model.query(messages)

    monkeypatch.setattr(workflows, "query_model_step", query_model_step)

    result = _call_root_agent_workflow(
        workflows.child_agent_workflow,
        "mas-0123456789abcdef",
        "mas-0123456789abcdef-c001",
        "submit once",
        model=model,
        env=env,
        step_limit=4,
    )

    assert result["terminal_state"] == "failed"
    assert result["status"] == "failed"
    status_events = [value for key, value in published if key == STATUS_EVENT_KEY]
    assert status_events[-1]["lifecycle_state"] == "failed"
    assert status_events[-1]["latest_error"] == "model failed after continuation"
    first_observable_events = [value for key, value in published if key == FIRST_OBSERVABLE_EVENT_KEY]
    assert [event["lifecycle_state"] for event in first_observable_events] == ["waiting_for_parent", "failed"]

    artifact = json.loads((tmp_path / result["trajectory_artifact_path"]).read_text())
    assert artifact["info"]["exit_status"] == "failed"
    assert artifact["messages"][-1]["content"] == "model failed after continuation"


def test_mini_mas_wait_cli_outputs_first_observable_event(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.wait_for_agent_workflow",
        Mock(
            return_value={
                "workflow_id": "mas-2222222222222222-c001",
                "output": "External mini-mas status, wait, continue, and close are unsupported.\n",
                "returncode": 2,
                "exception_info": "external_coordination_unsupported",
                "extra": {"mas_command_error": "external_coordination_unsupported"},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["wait", "mas-2222222222222222-c001", "--timeout", "0.01"])

    assert cli_result.exit_code == 2
    assert "unsupported" in cli_result.stdout


def test_mini_mas_wait_cli_outputs_closed_event_neutrally(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.wait_for_agent_workflow",
        Mock(
            return_value={
                "workflow_id": "mas-2222222222222222-c001",
                "output": "External mini-mas status, wait, continue, and close are unsupported.\n",
                "returncode": 2,
                "exception_info": "external_coordination_unsupported",
                "extra": {"mas_command_error": "external_coordination_unsupported"},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["wait", "mas-2222222222222222-c001"])

    assert cli_result.exit_code == 2
    assert "unsupported" in cli_result.stdout
    assert "accepted" not in cli_result.stdout.lower()
    assert "rejected" not in cli_result.stdout.lower()
    assert "aborted" not in cli_result.stdout.lower()
    assert "cancel" not in cli_result.stdout.lower()


def test_mini_mas_continue_cli_outputs_continuation_dispatch(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.continue_agent_workflow",
        Mock(
            return_value={
                "ok": True,
                "output": (
                    "Continuation signal sent\n"
                    "workflow_id: mas-2222222222222222-c001\n"
                    "lifecycle_state: waiting_for_parent\n"
                    "message: go on\n"
                    "run_directory: .mini-mas/runs/mas-2222222222222222\n"
                    "trajectory_artifact_path: .mini-mas/runs/mas-2222222222222222/trajectories/"
                    "mas-2222222222222222-c001.traj.json\n"
                ),
                "returncode": 0,
                "exception_info": "",
                "extra": {},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["continue", "mas-2222222222222222-c001", "go on"])

    assert cli_result.exit_code == 0
    assert "Continuation signal sent" in cli_result.stdout
    assert "workflow_id: mas-2222222222222222-c001" in cli_result.stdout
    assert "message: go on" in cli_result.stdout


def test_mini_mas_close_cli_outputs_neutral_close_dispatch(monkeypatch):
    monkeypatch.setattr(
        "minisweagent.mas.cli.close_agent_workflow",
        Mock(
            return_value={
                "ok": True,
                "output": (
                    "Close signal sent\n"
                    "workflow_id: mas-2222222222222222-c001\n"
                    "lifecycle_state: waiting_for_parent\n"
                    "latest_submission: ready\n"
                    "run_directory: .mini-mas/runs/mas-2222222222222222\n"
                    "trajectory_artifact_path: .mini-mas/runs/mas-2222222222222222/trajectories/"
                    "mas-2222222222222222-c001.traj.json\n"
                ),
                "returncode": 0,
                "exception_info": "",
                "extra": {},
            }
        ),
    )

    cli_result = CliRunner().invoke(app, ["close", "mas-2222222222222222-c001"])

    assert cli_result.exit_code == 0
    assert "Close signal sent" in cli_result.stdout
    assert "workflow_id: mas-2222222222222222-c001" in cli_result.stdout
    assert "latest_submission: ready" in cli_result.stdout
    assert "accepted" not in cli_result.stdout.lower()
    assert "rejected" not in cli_result.stdout.lower()
    assert "aborted" not in cli_result.stdout.lower()
    assert "cancel" not in cli_result.stdout.lower()


@pytest.mark.parametrize("command", ["history", "logs", "grep"])
def test_mini_mas_does_not_add_dedicated_history_or_log_commands(command):
    cli_result = CliRunner().invoke(app, [command])

    assert cli_result.exit_code != 0
