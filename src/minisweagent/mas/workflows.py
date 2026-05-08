"""DBOS workflows for the MAS subsystem boundary."""

from __future__ import annotations

from minisweagent.mas.artifacts import make_artifact_metadata, save_trajectory_artifact, validate_root_workflow_id
from minisweagent.mas.commands import MasCommandClassification, MasCommandKind, classify_mas_command
from minisweagent.mas.runtime import load_dbos

_dbos = load_dbos()


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


def execute_agent_workflow_actions(*, message: dict, model, env, template_vars: dict | None = None) -> list[dict]:
    """Execute bash-shaped Agent Workflow actions with workflow-layer MAS interception."""
    outputs = []
    for action in message.get("extra", {}).get("actions", []):
        classification = classify_mas_command(action.get("command", ""))
        if classification.kind == MasCommandKind.STANDALONE:
            outputs.append(_dispatch_mas_command(classification))
        elif classification.kind == MasCommandKind.INVALID:
            outputs.append(_reject_mas_shell_composition(classification))
        else:
            outputs.append(env.execute(action))
    return model.format_observation_messages(message, outputs, template_vars or {})


@_dbos.DBOS.step()
def save_root_trajectory_artifact_step(root_workflow_id: str) -> dict[str, str]:
    """Persist the Root Agent Workflow trajectory through a DBOS step."""
    save_trajectory_artifact(
        root_workflow_id=root_workflow_id,
        workflow_id=root_workflow_id,
        status="started",
    )
    return make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=root_workflow_id)


@_dbos.DBOS.workflow()
def root_agent_workflow(root_workflow_id: str) -> dict[str, str]:
    """Minimal Root Agent Workflow that writes its deterministic Trajectory Artifact."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    metadata = save_root_trajectory_artifact_step(root_workflow_id)
    return {"status": "started", **metadata}
