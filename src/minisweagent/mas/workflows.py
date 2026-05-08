"""DBOS workflows for the MAS subsystem boundary."""

from __future__ import annotations

from dataclasses import dataclass

from minisweagent.exceptions import InterruptAgentFlow
from minisweagent.mas.artifacts import make_artifact_metadata, save_trajectory_artifact, validate_root_workflow_id
from minisweagent.mas.commands import MasCommandClassification, MasCommandKind, classify_mas_command
from minisweagent.mas.runtime import load_dbos

_dbos = load_dbos()


@dataclass
class AgentWorkflowState:
    """Mutable state for one ordinary Agent Workflow loop."""

    messages: list[dict]
    cost: float = 0.0
    n_calls: int = 0


def _dispatch_mas_command(classification: MasCommandClassification) -> dict:
    """Placeholder workflow-layer MAS dispatcher for accepted standalone commands."""
    command_text = " ".join(classification.arguments)
    output = f"MAS command accepted: {command_text}\n"
    return {
        "output": output,
        "returncode": 0,
        "exception_info": "",
        "extra": {"mas_command": classification.arguments},
    }


def _reject_mas_shell_composition(classification: MasCommandClassification) -> dict:
    return {
        "output": f"{classification.error}\n",
        "returncode": 2,
        "exception_info": classification.error,
        "extra": {"mas_command_error": "non_standalone_mas_command"},
    }


@_dbos.DBOS.step()
def query_model_step(model, messages: list[dict]) -> dict:
    """Query the model through a DBOS checkpointed step."""
    return model.query(messages)


@_dbos.DBOS.step()
def execute_bash_step(env, action: dict) -> dict:
    """Execute ordinary bash through a DBOS checkpointed step."""
    return env.execute(action)


def _execute_agent_workflow_outputs(*, message: dict, env) -> list[dict]:
    """Execute bash-shaped Agent Workflow actions with workflow-layer MAS interception."""
    outputs = []
    for action in message.get("extra", {}).get("actions", []):
        classification = classify_mas_command(action.get("command", ""))
        if classification.kind == MasCommandKind.STANDALONE:
            outputs.append(_dispatch_mas_command(classification))
        elif classification.kind == MasCommandKind.INVALID:
            outputs.append(_reject_mas_shell_composition(classification))
        else:
            outputs.append(execute_bash_step(env, action))
    return outputs


def execute_agent_workflow_actions(*, message: dict, model, env, template_vars: dict | None = None) -> list[dict]:
    """Execute one model message and return model-specific observation messages."""
    outputs = _execute_agent_workflow_outputs(message=message, env=env)
    return model.format_observation_messages(message, outputs, template_vars or {})


def _template_vars(*, model, env, state: AgentWorkflowState, task: str) -> dict:
    data = {}
    if hasattr(env, "get_template_vars"):
        data |= env.get_template_vars()
    if hasattr(model, "get_template_vars"):
        data |= model.get_template_vars()
    data |= {
        "task": task,
        "n_model_calls": state.n_calls,
        "model_cost": state.cost,
    }
    return data


def _terminal_result(*, root_workflow_id: str, workflow_id: str, terminal_message: dict, state: AgentWorkflowState) -> dict:
    terminal_extra = terminal_message.get("extra", {})
    terminal_state = terminal_extra.get("exit_status", "unknown")
    submission = terminal_extra.get("submission", "")
    model_stats = {
        "instance_cost": state.cost,
        "api_calls": state.n_calls,
    }
    metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)
    return {
        "status": terminal_state,
        "terminal_state": terminal_state,
        "submission": submission,
        "model_stats": model_stats,
        **metadata,
    }


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


def _run_agent_workflow_loop(
    *,
    model,
    env,
    task: str,
    step_limit: int,
    initial_messages: list[dict] | None = None,
) -> AgentWorkflowState:
    state = AgentWorkflowState(messages=list(initial_messages) if initial_messages is not None else _initial_messages(model, task))
    while True:
        if 0 < step_limit <= state.n_calls:
            state.messages.append(_limits_exceeded_message(model))
            return state

        state.n_calls += 1
        try:
            message = query_model_step(model, state.messages)
            state.cost += message.get("extra", {}).get("cost", 0.0)
            state.messages.append(message)
            observations = execute_agent_workflow_actions(
                message=message,
                model=model,
                env=env,
                template_vars=_template_vars(model=model, env=env, state=state, task=task),
            )
            state.messages.extend(observations)
        except InterruptAgentFlow as flow:
            state.messages.extend(flow.messages)

        if state.messages and state.messages[-1].get("role") == "exit":
            return state


@_dbos.DBOS.step()
def save_root_trajectory_artifact_step(
    root_workflow_id: str,
    *,
    status: str = "started",
    messages: list[dict] | None = None,
    model_stats: dict | None = None,
    submission: str = "",
) -> dict[str, str]:
    """Persist the Root Agent Workflow trajectory through a DBOS step."""
    save_trajectory_artifact(
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        status=status,
        messages=messages,
        model_stats=model_stats,
        submission=submission,
    )
    return make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=root_workflow_id)


@_dbos.DBOS.workflow()
def root_agent_workflow(
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
    if model is None or env is None:
        metadata = save_root_trajectory_artifact_step(root_workflow_id)
        return {"status": "started", "terminal_state": "started", **metadata}

    state = _run_agent_workflow_loop(
        model=model,
        env=env,
        task=task,
        step_limit=step_limit,
        initial_messages=initial_messages,
    )
    result = _terminal_result(
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        terminal_message=state.messages[-1],
        state=state,
    )
    save_root_trajectory_artifact_step(
        root_workflow_id,
        status=result["terminal_state"],
        messages=state.messages,
        model_stats=result["model_stats"],
        submission=result["submission"],
    )
    return result
