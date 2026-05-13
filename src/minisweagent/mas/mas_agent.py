"""MAS Agent orchestration and DBOS entrypoints."""

from __future__ import annotations

import asyncio
from inspect import isawaitable
from typing import Any

from minisweagent.exceptions import InterruptAgentFlow
from minisweagent.mas import agent_interactions
from minisweagent.mas.artifacts import (
    make_artifact_metadata,
    save_trajectory_artifact,
    validate_agent_id,
)
from minisweagent.mas.commands import (
    MasCommandClassification,
    MasCommandHandler,
    MasCommandKind,
    classify_mas_command,
)
from minisweagent.mas.queues import AI_AGENT_WORKFLOW_QUEUE_NAME
from minisweagent.mas.runtime import load_dbos
from minisweagent.mas.signals import (
    PARENT_DIRECTION_TOPIC,
    PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS,
    ROOT_COMMAND_TOPIC,
    continuation_user_message,
    is_close_signal,
    is_continuation_signal,
    make_root_command_result_event,
    root_command_result_event_key,
    validate_root_command_signal,
)
from minisweagent.models.utils.actions_text import format_observation_messages

from .status_events import LifecycleState

_dbos = load_dbos()
agent_interactions._dbos = _dbos
ai_agent_workflow_queue = _dbos.Queue(AI_AGENT_WORKFLOW_QUEUE_NAME)
ROOT_COMMAND_WAIT_TIMEOUT_SECONDS = 60 * 60 * 24 * 30


class RootCommandModel:
    """Minimal formatter for externally submitted Root terminal commands."""

    observation_template = (
        "{% if output.exception_info %}<exception>{{output.exception_info}}</exception>\n{% endif %}"
        "<returncode>{{output.returncode}}</returncode>\n<output>\n{{output.output}}</output>"
    )

    def format_message(self, **kwargs) -> dict:
        return kwargs

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]:
        return format_observation_messages(
            outputs,
            observation_template=self.observation_template,
            template_vars=template_vars,
            multimodal_regex="",
        )

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return kwargs

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "model_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                },
            },
        }


async def _maybe_await(value):
    return await value if isawaitable(value) else value


def _current_agent_workflow_id() -> str | None:
    return agent_interactions.current_workflow_id()


async def _publish_first_observable_event_once(
    agent: MasAgent,
    *,
    agent_id: str,
    parent_agent_id: str | None = None,
    lifecycle_state: LifecycleState,
    latest_submission: str = "",
    latest_error: str = "",
) -> dict[str, str] | None:
    if agent.first_observable_published:
        return None
    agent.first_observable_published = True
    return await agent_interactions.publish_first_observable(
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        lifecycle_state=lifecycle_state,
        latest_submission=latest_submission,
        latest_error=latest_error,
    )


async def _wait_for_parent_direction_signal() -> dict | str:
    """Keep the child workflow waiting until the parent sends an actual direction signal."""
    while True:
        signal = await agent_interactions.receive_parent_direction(
            topic=PARENT_DIRECTION_TOPIC,
            timeout_seconds=PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS,
        )
        if signal is not None:
            return signal


def _reject_mas_shell_composition(classification: MasCommandClassification) -> dict:
    return {
        "output": f"{classification.error}\n",
        "returncode": 2,
        "exception_info": classification.error,
        "extra": {"mas_command_error": "non_standalone_mas_command"},
    }


def _root_command_user_message(model, command: str) -> dict:
    return model.format_message(
        role="user",
        content=f"User command:\n```bash\n{command}\n```",
        extra={"actions": [{"command": command}]},
    )


def _command_result_from_outputs(outputs: list[dict]) -> dict:
    if not outputs:
        return {"output": "", "returncode": 0, "exception_info": "", "extra": {}}
    output = outputs[-1]
    return {
        "output": output.get("output", ""),
        "returncode": output.get("returncode", 0),
        "exception_info": output.get("exception_info", ""),
        "extra": output.get("extra", {}),
    }


def _recoverable_root_command_error_result(error: Exception, *, returncode: int = 1) -> dict:
    message = str(error)
    return {
        "output": f"{message}\n",
        "returncode": returncode,
        "exception_info": message,
        "extra": {"mas_command_error": "root_command_error"},
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
    command_handler: MasCommandHandler,
) -> list[dict]:
    """Execute bash-shaped Agent actions with workflow-layer MAS interception."""
    outputs = []
    for action in message.get("extra", {}).get("actions", []):
        classification = classify_mas_command(action.get("command", ""))
        if classification.kind == MasCommandKind.STANDALONE:
            output = await command_handler.execute(classification)
            outputs.append(output)
        elif classification.kind == MasCommandKind.INVALID:
            outputs.append(_reject_mas_shell_composition(classification))
        else:
            outputs.append(await _maybe_await(execute_bash_step(env, action)))
    return outputs


async def execute_agent_workflow_actions(
    *,
    message: dict,
    model,
    env,
    template_vars: dict | None = None,
    command_handler: MasCommandHandler | None = None,
) -> list[dict]:
    """Execute one model message and return model-specific observation messages."""
    template_vars = template_vars or {}
    outputs = await _execute_agent_workflow_outputs(
        message=message,
        env=env,
        command_handler=command_handler or MasCommandHandler(),
    )
    return model.format_observation_messages(message, outputs, template_vars)


def _terminal_result(*, agent_id: str, parent_agent_id: str | None, terminal_message: dict, agent: MasAgent) -> dict:
    terminal_extra = terminal_message.get("extra", {})
    terminal_state = terminal_extra.get("exit_status", "unknown")
    submission = terminal_extra.get("submission", "")
    model_stats = {
        "instance_cost": agent.cost,
        "api_calls": agent.n_calls,
    }
    metadata = make_artifact_metadata(
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
    )
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
        model.format_message(role="system", content="You are a mini-swe-agent MAS Root Agent."),
        model.format_message(role="user", content=task),
    ]


class MasAgent:
    """Plain per-workflow MAS agent loop; DBOS decorators stay on module-level functions."""

    def __init__(
        self,
        *,
        agent_id: str,
        parent_agent_id: str | None = None,
        model,
        env,
        step_limit: int,
    ) -> None:
        self.agent_id = agent_id
        self.workflow_id = agent_id
        self.parent_agent_id = parent_agent_id
        self.model = model
        self.env = env
        self.step_limit = step_limit
        self.task = ""
        self.messages: list[dict] = []
        self.cost = 0.0
        self.n_calls = 0
        self.first_observable_published = False
        self.command_handler = MasCommandHandler()

    async def run(self, *, task: str = "", initial_messages: list[dict] | None = None) -> dict:
        """Run the MAS Agent until a terminal state or parent direction wait."""
        self.task = task
        if self.model is None or self.env is None:
            return await self._record_started_workflow()

        self.messages = list(initial_messages) if initial_messages is not None else _initial_messages(self.model, task)
        while True:
            await self._publish_status("running")
            await self._run_until_terminal_message()
            result = _terminal_result(
                agent_id=self.agent_id,
                parent_agent_id=self.parent_agent_id,
                terminal_message=self.messages[-1],
                agent=self,
            )
            lifecycle_state = _lifecycle_state_for_terminal(result["terminal_state"])
            latest_error = _latest_error_for_terminal(result["terminal_state"], self.messages[-1])

            if self._should_wait_for_parent_after_submission(result):
                waiting_result = await self._wait_for_parent_after_submission(result)
                parent_direction_signal = waiting_result.get("parent_direction_signal")
                if is_continuation_signal(parent_direction_signal):
                    self.add_messages(continuation_user_message(self.model, parent_direction_signal))
                    self.first_observable_published = False
                    continue
                if is_close_signal(parent_direction_signal):
                    return await self._close_after_parent_signal(waiting_result, result)
                return waiting_result

            await self._publish_status(
                lifecycle_state,
                latest_submission=result["submission"],
                latest_error=latest_error,
            )
            if self.parent_agent_id is not None and lifecycle_state in {"failed", "limits_exceeded"}:
                await _publish_first_observable_event_once(
                    self,
                    agent_id=self.agent_id,
                    parent_agent_id=self.parent_agent_id,
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
            command_handler=self.command_handler,
        )
        self.add_messages(*observations)
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
            "agent_id": self.agent_id,
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
        await agent_interactions.publish_status(
            agent_id=self.workflow_id,
            parent_agent_id=self.parent_agent_id,
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
        return await _maybe_await(
            save_trajectory_artifact_step(
                self.agent_id,
                self.parent_agent_id,
                status=status,
                messages=self.messages or None,
                model_stats=model_stats,
                submission=submission,
            )
        )

    def _should_wait_for_parent_after_submission(self, result: dict[str, Any]) -> bool:
        return self.parent_agent_id is not None and result["terminal_state"] == "Submitted"

    async def _wait_for_parent_after_submission(self, result: dict[str, Any]) -> dict[str, Any]:
        waiting_result = {
            **result,
            "status": "waiting_for_parent",
            "terminal_state": "waiting_for_parent",
            "latest_submission": result["submission"],
        }
        await self._publish_status("waiting_for_parent", latest_submission=result["submission"])
        await _publish_first_observable_event_once(
            self,
            agent_id=self.agent_id,
            parent_agent_id=self.parent_agent_id,
            lifecycle_state="waiting_for_parent",
            latest_submission=result["submission"],
        )
        await self._save_trajectory(
            status="waiting_for_parent",
            model_stats=result["model_stats"],
            submission=result["submission"],
        )
        waiting_result["parent_direction_signal"] = await _wait_for_parent_direction_signal()
        return waiting_result

    async def _close_after_parent_signal(self, waiting_result: dict[str, Any], submitted_result: dict[str, Any]) -> dict:
        closed_result = {
            **waiting_result,
            "status": "closed",
            "terminal_state": "closed",
        }
        await self._publish_status("closed", latest_submission=submitted_result["submission"])
        await self._save_trajectory(
            status="closed",
            model_stats=submitted_result["model_stats"],
            submission=submitted_result["submission"],
        )
        return closed_result


class MasInteractiveAgent:
    """Interactive Root Agent lifecycle owner; DBOS decorators stay on module-level functions."""

    def __init__(
        self,
        *,
        agent_id: str,
        model=None,
        env=None,
        step_limit: int,
    ) -> None:
        self.agent_id = validate_agent_id(agent_id)
        self.workflow_id = self.agent_id
        self.parent_agent_id = None
        self.model = model or RootCommandModel()
        self.env = env or self._default_environment()
        self.step_limit = step_limit
        self.messages: list[dict] = []
        self.command_handler = MasCommandHandler()

    def _default_environment(self):
        from minisweagent.environments import get_environment

        return get_environment({}, default_type="local")

    async def run_until_idle(self) -> dict:
        """Record the minimal idle Interactive Root Agent state."""
        metadata = await self._save_trajectory(status="waiting_for_command")
        await self._publish_status("waiting_for_command")
        return {
            "status": "waiting_for_command",
            "terminal_state": "waiting_for_command",
            "lifecycle_state": "waiting_for_command",
            **metadata,
        }

    async def run_command_loop(self, *, max_commands: int | None = None) -> dict:
        """Receive Root commands, execute them through the Agent action flow, and stay idle afterward."""
        metadata = await self._save_trajectory(status="waiting_for_command")
        commands_completed = 0
        while max_commands is None or commands_completed < max_commands:
            await self._publish_status("waiting_for_command")
            signal = await _maybe_await(
                _dbos.DBOS.recv_async(ROOT_COMMAND_TOPIC, timeout_seconds=ROOT_COMMAND_WAIT_TIMEOUT_SECONDS)
            )
            if signal is None:
                continue
            try:
                command_signal = validate_root_command_signal(signal, target_root_agent_id=self.agent_id)
            except ValueError as exc:
                command_signal = self._recoverable_signal_context(signal)
                result = _recoverable_root_command_error_result(exc, returncode=2)
                await self._publish_root_command_result(command_signal, result)
                commands_completed += 1
                continue
            await self._publish_status("running")
            try:
                result = await self.execute_user_command(command_signal["command"])
            except Exception as exc:
                result = await self.record_recoverable_command_error(command_signal["command"], exc)
            await self._publish_root_command_result(command_signal, result)
            metadata = await self._save_trajectory(
                status="waiting_for_command",
                model_stats={"instance_cost": 0.0, "api_calls": 0},
            )
            commands_completed += 1
        await self._publish_status("waiting_for_command")
        return {
            "status": "waiting_for_command",
            "terminal_state": "waiting_for_command",
            "lifecycle_state": "waiting_for_command",
            **metadata,
        }

    async def execute_user_command(self, command: str) -> dict:
        """Execute one terminal command through the existing MAS-aware bash action path."""
        message = _root_command_user_message(self.model, command)
        self.messages.append(message)
        outputs = await _execute_agent_workflow_outputs(
            message=message,
            env=self.env,
            command_handler=self.command_handler,
        )
        observations = self.model.format_observation_messages(message, outputs, self.get_template_vars())
        self.messages.extend(observations)
        return _command_result_from_outputs(outputs)

    async def record_recoverable_command_error(self, command: str, error: Exception) -> dict:
        """Persist a recoverable command failure as a normal command observation."""
        result = _recoverable_root_command_error_result(error, returncode=1)
        if not self.messages or self.messages[-1].get("extra", {}).get("actions", [{}])[-1].get("command") != command:
            self.messages.append(_root_command_user_message(self.model, command))
        observations = self.model.format_observation_messages(self.messages[-1], [result], self.get_template_vars())
        self.messages.extend(observations)
        return result

    async def _publish_root_command_result(self, command_signal: dict[str, str], result: dict) -> None:
        event = make_root_command_result_event(
            command_id=command_signal["command_id"],
            root_agent_id=self.agent_id,
            command=command_signal["command"],
            result=result,
        )
        await _maybe_await(
            _dbos.DBOS.set_event_async(root_command_result_event_key(command_signal["command_id"]), event)
        )

    def _recoverable_signal_context(self, signal: Any) -> dict[str, str]:
        if isinstance(signal, dict):
            command_id = str(signal.get("command_id") or "invalid-root-command")
            command = str(signal.get("command") or "")
        else:
            command_id = "invalid-root-command"
            command = ""
        return {
            "kind": "root_command",
            "command_id": command_id,
            "root_agent_id": self.agent_id,
            "command": command,
            "source": "",
        }

    def get_template_vars(self) -> dict:
        data = {}
        if hasattr(self.env, "get_template_vars"):
            data |= self.env.get_template_vars()
        if hasattr(self.model, "get_template_vars"):
            data |= self.model.get_template_vars()
        data |= {
            "task": "",
            "n_model_calls": 0,
            "model_cost": 0.0,
            "agent_id": self.agent_id,
        }
        return data

    async def _publish_status(
        self,
        lifecycle_state: LifecycleState,
        *,
        latest_submission: str = "",
        latest_error: str = "",
    ) -> None:
        await agent_interactions.publish_status(
            agent_id=self.workflow_id,
            parent_agent_id=self.parent_agent_id,
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
        return await _maybe_await(
            save_trajectory_artifact_step(
                self.agent_id,
                self.parent_agent_id,
                status=status,
                messages=self.messages or None,
                model_stats=model_stats,
                submission=submission,
            )
        )


@_dbos.DBOS.step()
async def save_trajectory_artifact_step(
    agent_id: str,
    parent_agent_id: str | None = None,
    *,
    status: str = "started",
    messages: list[dict] | None = None,
    model_stats: dict | None = None,
    submission: str = "",
) -> dict[str, str]:
    """Persist any Agent trajectory through one DBOS checkpointed step."""
    await asyncio.to_thread(
        save_trajectory_artifact,
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        status=status,
        messages=messages,
        model_stats=model_stats,
        submission=submission,
    )
    return make_artifact_metadata(
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
    )


async def _run_agent_workflow(
    *,
    agent_id: str,
    parent_agent_id: str | None,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None,
) -> dict:
    original_workflow_id = _current_agent_workflow_id()
    if original_workflow_id is None:
        _dbos.DBOS.workflow_id = agent_id
    try:
        return await _run_agent_workflow_with_context(
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
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
    agent_id: str,
    parent_agent_id: str | None,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None,
) -> dict:
    agent = MasAgent(
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        model=model,
        env=env,
        step_limit=step_limit,
    )
    return await agent.run(task=task, initial_messages=initial_messages)


@_dbos.DBOS.workflow()
async def interactive_root_agent_workflow(
    agent_id: str,
    *,
    model=None,
    env=None,
    step_limit: int = 0,
    max_commands: int | None = 0,
) -> dict:
    """Interactive Root Agent DBOS workflow for idle startup and Root command execution."""
    agent_id = validate_agent_id(agent_id)
    original_workflow_id = _current_agent_workflow_id()
    if original_workflow_id is None:
        _dbos.DBOS.workflow_id = agent_id
    try:
        agent = MasInteractiveAgent(
            agent_id=agent_id,
            model=model,
            env=env,
            step_limit=step_limit,
        )
        if max_commands == 0:
            return await agent.run_until_idle()
        return await agent.run_command_loop(max_commands=max_commands)
    finally:
        if original_workflow_id is None:
            _dbos.DBOS.workflow_id = original_workflow_id


@_dbos.DBOS.workflow()
async def root_agent_workflow(
    agent_id: str,
    *,
    model=None,
    env=None,
    task: str = "",
    step_limit: int = 0,
    initial_messages: list[dict] | None = None,
) -> dict:
    """Root Agent DBOS workflow for the ordinary non-child-interaction MAS path."""
    agent_id = validate_agent_id(agent_id)
    return await _run_agent_workflow(
        agent_id=agent_id,
        parent_agent_id=None,
        model=model,
        env=env,
        task=task,
        step_limit=step_limit,
        initial_messages=initial_messages,
    )


@_dbos.DBOS.workflow()
async def child_agent_workflow(
    agent_id: str,
    task: str,
    *,
    parent_agent_id: str,
    model=None,
    env=None,
    step_limit: int = 0,
    initial_messages: list[dict] | None = None,
) -> dict:
    """Autonomous Child Agent DBOS workflow started through the AI Agent queue."""
    agent_id = validate_agent_id(agent_id)
    parent_agent_id = validate_agent_id(parent_agent_id)
    return await _run_agent_workflow(
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        model=model,
        env=env,
        task=task,
        step_limit=step_limit,
        initial_messages=initial_messages,
    )
