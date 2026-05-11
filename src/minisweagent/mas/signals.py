"""Signal payload helpers for MAS Agent Interactions."""

from __future__ import annotations

from minisweagent.mas.artifacts import validate_agent_id

PARENT_DIRECTION_TOPIC = "mini_mas_parent_direction"
PARENT_DIRECTION_WAIT_TIMEOUT_SECONDS = 60 * 60 * 24 * 30
ROOT_COMMAND_TOPIC = "mini_mas_root_command"
ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX = "mini_mas_root_command_result:"


def root_command_result_event_key(command_id: str) -> str:
    """Build the DBOS event key for one Root Command Result."""
    if not command_id:
        raise ValueError("Root Command Result requires a command ID")
    return f"{ROOT_COMMAND_RESULT_EVENT_KEY_PREFIX}{command_id}"


def make_root_command_signal(
    *,
    command_id: str,
    root_agent_id: str,
    command: str,
    source: str = "external_cli",
) -> dict[str, str]:
    """Build the external-to-Root command payload."""
    if not command_id:
        raise ValueError("Root Command Signal requires a command ID")
    if not isinstance(command, str):
        raise ValueError("Root Command Signal command must be a string")
    return {
        "kind": "root_command",
        "command_id": command_id,
        "root_agent_id": validate_agent_id(root_agent_id),
        "command": command,
        "source": source,
    }


def validate_root_command_signal(signal: dict, *, target_root_agent_id: str) -> dict[str, str]:
    """Validate one Root Command Signal before the Root Agent executes it."""
    if not isinstance(signal, dict) or signal.get("kind") != "root_command":
        raise ValueError("Expected Root Command Signal")
    command_id = str(signal.get("command_id") or "")
    if not command_id:
        raise ValueError("Root Command Signal requires a command ID")
    root_agent_id = validate_agent_id(str(signal.get("root_agent_id") or ""))
    target_root_agent_id = validate_agent_id(target_root_agent_id)
    if root_agent_id != target_root_agent_id:
        raise ValueError(
            f"Root Command Signal target mismatch: expected {target_root_agent_id}, got {root_agent_id}"
        )
    command = signal.get("command")
    if not isinstance(command, str):
        raise ValueError("Root Command Signal command must be a string")
    return {
        "kind": "root_command",
        "command_id": command_id,
        "root_agent_id": root_agent_id,
        "command": command,
        "source": str(signal.get("source") or ""),
    }


def make_root_command_result_event(
    *,
    command_id: str,
    root_agent_id: str,
    command: str,
    result: dict,
) -> dict:
    """Wrap the existing MAS command result shape in a command-id-scoped event."""
    return {
        "kind": "root_command_result",
        "command_id": command_id,
        "root_agent_id": validate_agent_id(root_agent_id),
        "command": command,
        "result": result,
    }


def make_continuation_signal(
    *,
    source_workflow_id: str,
    target_workflow_id: str,
    content: str,
) -> dict[str, str]:
    """Build the parent-to-child message payload used for MAS continuation."""
    return {
        "type": "continuation",
        "signal_type": "mas_continuation",
        "content": content,
        "source_workflow_id": source_workflow_id,
        "target_workflow_id": target_workflow_id,
    }


def make_close_signal(*, source_workflow_id: str, target_workflow_id: str) -> dict[str, str]:
    """Build the neutral parent-to-child message payload used to close a waiting child."""
    return {
        "type": "close",
        "signal_type": "mas_close",
        "source_workflow_id": source_workflow_id,
        "target_workflow_id": target_workflow_id,
    }


def is_continuation_signal(signal: dict | str) -> bool:
    return isinstance(signal, dict) and (
        signal.get("type") == "continuation" or signal.get("signal_type") == "mas_continuation"
    )


def is_close_signal(signal: dict | str) -> bool:
    return isinstance(signal, dict) and (signal.get("type") == "close" or signal.get("signal_type") == "mas_close")


def continuation_user_message(model, signal: dict) -> dict:
    """Represent parent continuation as a normal model-facing user message."""
    return model.format_message(
        role="user",
        content=str(signal.get("content", "")),
        extra={
            "mas": {
                "signal_type": "mas_continuation",
                "source_workflow_id": str(signal.get("source_workflow_id", "")),
                "target_workflow_id": str(signal.get("target_workflow_id", "")),
            }
        },
    )
