"""DBOS workflows for the MAS subsystem boundary."""

from __future__ import annotations

import asyncio
from inspect import isawaitable
from typing import Any

from minisweagent.exceptions import InterruptAgentFlow
from minisweagent.mas.artifacts import (
    make_artifact_metadata,
    save_trajectory_artifact,
    validate_root_workflow_id,
    validate_workflow_id,
)
from minisweagent.mas.authority import DirectChildAuthorityPolicy
from minisweagent.mas.command_dispatch import MasCommandHandler
from minisweagent.mas.command_results import MasCommandResultFormatter
from minisweagent.mas.commands import MasCommandClassification, MasCommandKind, classify_mas_command
from minisweagent.mas.coordination import ChildCoordinator, DBOSCoordinationAdapter
from minisweagent.mas.remote_lifecycle import (
    PARENT_DIRECTION_TOPIC,
    PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS,
    RemoteInteractiveAgentLifecycle,
    continuation_user_message,
    is_close_signal,
    is_continuation_signal,
    make_close_signal,
    make_continuation_signal,
)
from minisweagent.mas.runtime import load_dbos
from minisweagent.mas.status import LifecycleState

_dbos = load_dbos()
child_agent_queue = _dbos.Queue("mini_mas_child_agent_workflows")


async def _maybe_await(value):
    return await value if isawaitable(value) else value


def _current_agent_workflow_id() -> str | None:
    return _coordination_adapter().current_agent_workflow_id()


def _coordination_adapter() -> DBOSCoordinationAdapter:
    return DBOSCoordinationAdapter(
        dbos_api=_dbos.DBOS,
        child_agent_queue=child_agent_queue,
        set_workflow_id=_dbos.SetWorkflowID,
        child_agent_workflow=child_agent_workflow,
    )


def _child_coordinator() -> ChildCoordinator:
    return ChildCoordinator(adapter=_coordination_adapter())


async def _publish_status_snapshot(
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> None:
    await _coordination_adapter().publish_status(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


async def _publish_first_observable_event(
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> dict[str, str]:
    return await _coordination_adapter().publish_first_observable(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


async def _publish_first_observable_event_once(
    agent: MasAgent,
    *,
    root_workflow_id: str,
    workflow_id: str,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> dict[str, str] | None:
    if agent.first_observable_published:
        return None
    agent.first_observable_published = True
    return await _publish_first_observable_event(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


async def _wait_for_parent_direction_signal() -> dict | str:
    """Keep the child workflow waiting until the parent sends an actual direction signal."""
    while True:
        signal = await _coordination_adapter().receive_parent_direction(
            topic=PARENT_DIRECTION_TOPIC,
            timeout_seconds=PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS,
        )
        if signal is not None:
            return signal


async def send_continuation_signal_async(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
    content: str,
    target_status: dict[str, Any],
) -> dict[str, Any]:
    """Send a continuation signal after Direct Child Authority Policy validation."""
    signal = make_continuation_signal(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        content=content,
    )
    await _coordination_adapter().send_parent_direction(
        target_workflow_id=target_workflow_id,
        signal=signal,
        topic=PARENT_DIRECTION_TOPIC,
    )
    result = MasCommandResultFormatter().continuation_sent(
        mas_command=["continue", target_workflow_id, content],
        target_workflow_id=target_workflow_id,
        content=content,
        target_status=target_status,
        signal=signal,
    )
    result["ok"] = True
    return result


async def send_close_signal_async(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
    target_status: dict[str, Any],
) -> dict[str, Any]:
    """Send a neutral close signal after Direct Child Authority Policy validation."""
    signal = make_close_signal(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
    )
    await _coordination_adapter().send_parent_direction(
        target_workflow_id=target_workflow_id,
        signal=signal,
        topic=PARENT_DIRECTION_TOPIC,
    )
    result = MasCommandResultFormatter().close_sent(
        mas_command=["close", target_workflow_id],
        target_workflow_id=target_workflow_id,
        target_status=target_status,
        signal=signal,
    )
    result["ok"] = True
    return result


async def _query_direct_child_statuses(parent_workflow_id: str) -> list[dict[str, Any]]:
    return await _coordination_adapter().query_direct_child_statuses(parent_workflow_id)


async def _query_direct_child_status(parent_workflow_id: str, child_workflow_id: str) -> dict[str, Any] | None:
    return await _coordination_adapter().query_direct_child_status(
        parent_workflow_id=parent_workflow_id,
        child_workflow_id=child_workflow_id,
    )


async def _send_continuation_signal_for_handler(
    source_workflow_id: str, target_workflow_id: str, content: str, target_status: dict[str, Any]
) -> dict[str, Any]:
    return await send_continuation_signal_async(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        content=content,
        target_status=target_status,
    )


async def _send_close_signal_for_handler(
    source_workflow_id: str, target_workflow_id: str, target_status: dict[str, Any]
) -> dict[str, Any]:
    return await send_close_signal_async(
        source_workflow_id=source_workflow_id,
        target_workflow_id=target_workflow_id,
        target_status=target_status,
    )


def _make_mas_command_handler() -> MasCommandHandler:
    authority_policy = DirectChildAuthorityPolicy(query_direct_child_status=_query_direct_child_status)
    return MasCommandHandler(
        current_workflow_id=_current_agent_workflow_id,
        query_direct_child_statuses=_query_direct_child_statuses,
        authority_policy=authority_policy,
        child_coordinator=_child_coordinator(),
        send_continuation_signal=_send_continuation_signal_for_handler,
        send_close_signal=_send_close_signal_for_handler,
    )


def _reject_mas_shell_composition(classification: MasCommandClassification) -> dict:
    return {
        "output": f"{classification.error}\n",
        "returncode": 2,
        "exception_info": classification.error,
        "extra": {"mas_command_error": "non_standalone_mas_command"},
    }


@_dbos.DBOS.step()
async def query_model_step(model, messages: list[dict]) -> dict:
    """Query the model through a DBOS checkpointed step."""
    return await asyncio.to_thread(model.query, messages)


@_dbos.DBOS.step()
async def execute_bash_step(env, action: dict) -> dict:
    """Execute ordinary bash through a DBOS checkpointed step."""
    return await asyncio.to_thread(env.execute, action)


async def _execute_agent_workflow_outputs(
    *,
    message: dict,
    env,
    spawn_index: int = 0,
    existing_child_workflow_ids: set[str] | None = None,
) -> list[dict]:
    """Execute bash-shaped Agent Workflow actions with workflow-layer MAS interception."""
    outputs = []
    existing_child_workflow_ids = existing_child_workflow_ids if existing_child_workflow_ids is not None else set()
    command_handler = _make_mas_command_handler()
    current_spawn_index = spawn_index
    for action in message.get("extra", {}).get("actions", []):
        classification = classify_mas_command(action.get("command", ""))
        if classification.kind == MasCommandKind.STANDALONE:
            output = await command_handler.execute(
                classification,
                spawn_index=current_spawn_index + 1,
                existing_child_workflow_ids=existing_child_workflow_ids,
            )
            outputs.append(output)
            current_spawn_index += output.get("extra", {}).get("spawned_child_count", 0)
        elif classification.kind == MasCommandKind.INVALID:
            outputs.append(_reject_mas_shell_composition(classification))
        else:
            outputs.append(await _maybe_await(execute_bash_step(env, action)))
    return outputs


async def execute_agent_workflow_actions(*, message: dict, model, env, template_vars: dict | None = None) -> list[dict]:
    """Execute one model message and return model-specific observation messages."""
    template_vars = template_vars or {}
    child_workflow_ids = template_vars.get("existing_child_workflow_ids", set())
    existing_ids = child_workflow_ids if isinstance(child_workflow_ids, set) else set(child_workflow_ids)
    outputs = await _execute_agent_workflow_outputs(
        message=message,
        env=env,
        spawn_index=template_vars.get("spawn_index", 0),
        existing_child_workflow_ids=existing_ids,
    )
    return model.format_observation_messages(message, outputs, template_vars)


def _terminal_result(*, root_workflow_id: str, workflow_id: str, terminal_message: dict, agent: MasAgent) -> dict:
    terminal_extra = terminal_message.get("extra", {})
    terminal_state = terminal_extra.get("exit_status", "unknown")
    submission = terminal_extra.get("submission", "")
    model_stats = {
        "instance_cost": agent.cost,
        "api_calls": agent.n_calls,
    }
    metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)
    return {
        "status": terminal_state,
        "terminal_state": terminal_state,
        "submission": submission,
        "model_stats": model_stats,
        **metadata,
    }


def _latest_error_for_terminal(terminal_state: str, terminal_message: dict) -> str:
    if _lifecycle_state_for_terminal(terminal_state) != "failed":
        return ""
    return terminal_message.get("content", "")


def _lifecycle_state_for_terminal(terminal_state: str) -> LifecycleState:
    if terminal_state == "limits_exceeded":
        return "limits_exceeded"
    if terminal_state in {"failed", "error", "Exception"}:
        return "failed"
    return "closed"


def _limits_exceeded_message(model) -> dict:
    return model.format_message(
        role="exit",
        content="limits_exceeded",
        extra={"exit_status": "limits_exceeded", "submission": ""},
    )


def _initial_messages(model, task: str) -> list[dict]:
    return [
        model.format_message(role="system", content="You are a mini-swe-agent MAS Root Agent Workflow."),
        model.format_message(role="user", content=task),
    ]


class MasAgent:
    """Plain per-workflow MAS agent loop; DBOS decorators stay on module-level functions."""

    def __init__(self, *, root_workflow_id: str, workflow_id: str, model, env, step_limit: int) -> None:
        self.root_workflow_id = root_workflow_id
        self.workflow_id = workflow_id
        self.model = model
        self.env = env
        self.step_limit = step_limit
        self.task = ""
        self.messages: list[dict] = []
        self.cost = 0.0
        self.n_calls = 0
        self.spawn_count = 0
        self.first_observable_published = False
        self.spawned_child_workflow_ids: set[str] = set()
        self.remote_lifecycle = RemoteInteractiveAgentLifecycle(
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            receive_parent_direction=_wait_for_parent_direction_signal,
        )

    async def run(self, *, task: str = "", initial_messages: list[dict] | None = None) -> dict:
        """Run the MAS Agent Workflow until a terminal state or parent direction wait."""
        self.task = task
        if self.model is None or self.env is None:
            return await self._record_started_workflow()

        self.messages = list(initial_messages) if initial_messages is not None else _initial_messages(self.model, task)
        while True:
            await self._publish_status("running")
            await self._run_until_terminal_message()
            result = _terminal_result(
                root_workflow_id=self.root_workflow_id,
                workflow_id=self.workflow_id,
                terminal_message=self.messages[-1],
                agent=self,
            )
            lifecycle_state = _lifecycle_state_for_terminal(result["terminal_state"])
            latest_error = _latest_error_for_terminal(result["terminal_state"], self.messages[-1])

            if self.remote_lifecycle.should_wait_for_parent(result):
                waiting_result = await self._wait_for_parent_after_submission(result)
                parent_direction_signal = waiting_result.get("parent_direction_signal")
                if self.remote_lifecycle.is_continuation_signal(parent_direction_signal):
                    self.add_messages(self.remote_lifecycle.continuation_user_message(self.model, parent_direction_signal))
                    self.first_observable_published = False
                    continue
                if self.remote_lifecycle.is_close_signal(parent_direction_signal):
                    return await self._close_after_parent_signal(waiting_result, result)
                return waiting_result

            await self._publish_status(
                lifecycle_state,
                latest_submission=result["submission"],
                latest_error=latest_error,
            )
            if self.workflow_id != self.root_workflow_id and lifecycle_state in {"failed", "limits_exceeded"}:
                await _publish_first_observable_event_once(
                    self,
                    root_workflow_id=self.root_workflow_id,
                    workflow_id=self.workflow_id,
                    lifecycle_state=lifecycle_state,
                    latest_submission=result["submission"],
                    latest_error=latest_error,
                )
            await self._save_trajectory(
                status=result["terminal_state"],
                model_stats=result["model_stats"],
                submission=result["submission"],
            )
            return result

    async def step(self) -> list[dict]:
        """Query the model, execute bash-shaped actions, and append observations."""
        return await self.execute_actions(await self.query())

    async def query(self) -> dict:
        """Query the model through the DBOS model step and append the model message."""
        self.n_calls += 1
        message = await _maybe_await(query_model_step(self.model, self.messages))
        self.cost += message.get("extra", {}).get("cost", 0.0)
        self.add_messages(message)
        return message

    async def execute_actions(self, message: dict) -> list[dict]:
        """Execute MAS-aware actions and append model-specific observation messages."""
        observations = await execute_agent_workflow_actions(
            message=message,
            model=self.model,
            env=self.env,
            template_vars=self.get_template_vars(),
        )
        self.add_messages(*observations)
        self.spawn_count += sum(
            observation.get("extra", {}).get("spawned_child_count", 0) for observation in observations
        )
        return observations

    def add_messages(self, *messages: dict) -> list[dict]:
        self.messages.extend(messages)
        return list(messages)

    def get_template_vars(self, **kwargs) -> dict:
        data = {}
        if hasattr(self.env, "get_template_vars"):
            data |= self.env.get_template_vars()
        if hasattr(self.model, "get_template_vars"):
            data |= self.model.get_template_vars()
        data |= {
            "task": self.task,
            "n_model_calls": self.n_calls,
            "model_cost": self.cost,
            "root_workflow_id": self.root_workflow_id,
            "workflow_id": self.workflow_id,
            "spawn_index": self.spawn_count,
            "existing_child_workflow_ids": self.spawned_child_workflow_ids,
        }
        data |= kwargs
        return data

    async def _run_until_terminal_message(self) -> None:
        while True:
            if 0 < self.step_limit <= self.n_calls:
                self.add_messages(_limits_exceeded_message(self.model))
                return
            try:
                await self.step()
            except InterruptAgentFlow as flow:
                self.add_messages(*flow.messages)
            if self.messages and self.messages[-1].get("role") == "exit":
                return

    async def _record_started_workflow(self) -> dict:
        await self._publish_status("running")
        metadata = await self._save_trajectory(status="started")
        return {"status": "started", "terminal_state": "started", **metadata}

    async def _publish_status(
        self,
        lifecycle_state: LifecycleState,
        *,
        latest_submission: str = "",
        latest_error: str = "",
    ) -> None:
        await _publish_status_snapshot(
            root_workflow_id=self.root_workflow_id,
            workflow_id=self.workflow_id,
            lifecycle_state=lifecycle_state,
            latest_submission=latest_submission,
            latest_error=latest_error,
        )

    async def _save_trajectory(
        self,
        *,
        status: str,
        model_stats: dict | None = None,
        submission: str = "",
    ) -> dict[str, str]:
        if self.workflow_id == self.root_workflow_id:
            return await _maybe_await(
                save_root_trajectory_artifact_step(
                    self.root_workflow_id,
                    status=status,
                    messages=self.messages or None,
                    model_stats=model_stats,
                    submission=submission,
                )
            )
        return await _maybe_await(
            save_child_trajectory_artifact_step(
                self.root_workflow_id,
                self.workflow_id,
                status=status,
                messages=self.messages or None,
                model_stats=model_stats,
                submission=submission,
            )
        )

    async def _wait_for_parent_after_submission(self, result: dict[str, Any]) -> dict[str, Any]:
        return await self.remote_lifecycle.wait_after_submission(
            result,
            publish_waiting_status=lambda lifecycle_state: self._publish_status(
                lifecycle_state,
                latest_submission=result["submission"],
            ),
            publish_first_observable=lambda lifecycle_state: _publish_first_observable_event_once(
                self,
                root_workflow_id=self.root_workflow_id,
                workflow_id=self.workflow_id,
                lifecycle_state=lifecycle_state,
                latest_submission=result["submission"],
            ),
            save_trajectory=lambda status: self._save_trajectory(
                status=status,
                model_stats=result["model_stats"],
                submission=result["submission"],
            ),
        )

    async def _close_after_parent_signal(self, waiting_result: dict[str, Any], submitted_result: dict[str, Any]) -> dict:
        return await self.remote_lifecycle.close_after_parent_signal(
            waiting_result,
            publish_closed_status=lambda lifecycle_state: self._publish_status(
                lifecycle_state,
                latest_submission=submitted_result["submission"],
            ),
            save_trajectory=lambda status: self._save_trajectory(
                status=status,
                model_stats=submitted_result["model_stats"],
                submission=submitted_result["submission"],
            ),
        )


_is_continuation_signal = is_continuation_signal
_is_close_signal = is_close_signal
_continuation_user_message = continuation_user_message


@_dbos.DBOS.step()
async def save_root_trajectory_artifact_step(
    root_workflow_id: str,
    *,
    status: str = "started",
    messages: list[dict] | None = None,
    model_stats: dict | None = None,
    submission: str = "",
) -> dict[str, str]:
    """Persist the Root Agent Workflow trajectory through a DBOS step."""
    await asyncio.to_thread(
        save_trajectory_artifact,
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        status=status,
        messages=messages,
        model_stats=model_stats,
        submission=submission,
    )
    return make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=root_workflow_id)


@_dbos.DBOS.step()
async def save_child_trajectory_artifact_step(
    root_workflow_id: str,
    workflow_id: str,
    *,
    status: str = "started",
    messages: list[dict] | None = None,
    model_stats: dict | None = None,
    submission: str = "",
) -> dict[str, str]:
    """Persist a Child Agent Workflow trajectory through a DBOS step."""
    await asyncio.to_thread(
        save_trajectory_artifact,
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        status=status,
        messages=messages,
        model_stats=model_stats,
        submission=submission,
    )
    return make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)


async def _run_agent_workflow(
    *,
    root_workflow_id: str,
    workflow_id: str,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None,
) -> dict:
    original_workflow_id = _current_agent_workflow_id()
    if original_workflow_id is None:
        _dbos.DBOS.workflow_id = workflow_id
    try:
        return await _run_agent_workflow_with_context(
            root_workflow_id=root_workflow_id,
            workflow_id=workflow_id,
            model=model,
            env=env,
            task=task,
            step_limit=step_limit,
            initial_messages=initial_messages,
        )
    finally:
        if original_workflow_id is None:
            _dbos.DBOS.workflow_id = original_workflow_id


async def _run_agent_workflow_with_context(
    *,
    root_workflow_id: str,
    workflow_id: str,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None,
) -> dict:
    agent = MasAgent(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        model=model,
        env=env,
        step_limit=step_limit,
    )
    return await agent.run(task=task, initial_messages=initial_messages)


@_dbos.DBOS.workflow()
async def root_agent_workflow(
    root_workflow_id: str,
    *,
    model=None,
    env=None,
    task: str = "",
    step_limit: int = 0,
    initial_messages: list[dict] | None = None,
) -> dict:
    """Root Agent Workflow for the ordinary non-child-coordination MAS path."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    return await _run_agent_workflow(
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        model=model,
        env=env,
        task=task,
        step_limit=step_limit,
        initial_messages=initial_messages,
    )


@_dbos.DBOS.workflow()
async def child_agent_workflow(
    root_workflow_id: str,
    workflow_id: str,
    task: str,
    *,
    model=None,
    env=None,
    step_limit: int = 0,
    initial_messages: list[dict] | None = None,
) -> dict:
    """Child Agent Workflow started by detached spawn through the child queue."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    workflow_id = validate_workflow_id(workflow_id)
    return await _run_agent_workflow(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        model=model,
        env=env,
        task=task,
        step_limit=step_limit,
        initial_messages=initial_messages,
    )
