import asyncio
from unittest.mock import MagicMock, Mock


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

def _child_metadata(workflow_id: str, task: str = "task") -> dict[str, str]:
    return {
        "task": task,
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": workflow_id,
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": f".mini-mas/runs/mas-0123456789abcdef/trajectories/{workflow_id}.traj.json",
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
