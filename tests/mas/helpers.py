import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

from minisweagent.mas.queues import AI_AGENT_WORKFLOW_QUEUE_NAME


def _mock_dbos_module() -> MagicMock:
    dbos_module = MagicMock()
    dbos_module.DBOS.register_queue_async = AsyncMock()
    dbos_module.DBOS.workflow.return_value = lambda func: func
    dbos_module.DBOS.step.return_value = lambda func: func

    control_plane = MagicMock()

    async def list_workflows_async(**kwargs):
        workflow_ids = kwargs.get("workflow_ids")
        if workflow_ids is not None and dbos_module.DBOS.get_workflow_status_async.side_effect is not None:
            statuses = []
            for workflow_id in workflow_ids:
                status = await dbos_module.DBOS.get_workflow_status_async(workflow_id)
                if status is not None:
                    statuses.append(status)
            return statuses
        return await dbos_module.DBOS.list_workflows_async(**kwargs)

    async def get_event_async(workflow_id, key, timeout_seconds=60):
        return await dbos_module.DBOS.get_event_async(workflow_id, key, timeout_seconds)

    control_plane.list_workflows_async = Mock(side_effect=list_workflows_async)
    control_plane.get_event_async = Mock(side_effect=get_event_async)
    control_plane.destroy = Mock()
    dbos_module.DBOSClient.return_value = control_plane
    return dbos_module

def _mock_recording_dbos_module() -> MagicMock:
    dbos_module = MagicMock()
    dbos_module.DBOS.register_queue_async = AsyncMock()
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

def _recording_workflow_queue(name: str = AI_AGENT_WORKFLOW_QUEUE_NAME):
    class RecordingWorkflowQueue:
        def __init__(self):
            self.name = name
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

    return RecordingWorkflowQueue()

def _child_metadata(workflow_id: str, task: str = "task") -> dict[str, str]:
    return {
        "task": task,
        "agent_id": workflow_id,
        "parent_agent_id": "mas-0123456789abcdef",
        "agent_artifact_directory": f".mini-mas/agents/{workflow_id}",
        "trajectory_artifact_path": f".mini-mas/agents/{workflow_id}/trajectory.traj.json",
    }

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
        {snapshot["agent_id"]: {"mini_mas_status": snapshot}},
    )

class AsyncMockHandle:
    def __init__(self, workflow_id, result=None):
        self.workflow_id = workflow_id
        self._result = result

    def get_workflow_id(self):
        return self.workflow_id

    async def get_result(self):
        return self._result
