"""Deterministic artifact paths for MAS Agents."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

from minisweagent import __version__

AGENTS_ROOT = Path(".mini-mas") / "agents"
AGENT_ID_RE = re.compile(r"mas-[0-9a-f]{16}\Z")


def make_agent_id() -> str:
    """Return an opaque MAS Agent ID."""
    return f"mas-{secrets.token_hex(8)}"


def validate_agent_id(agent_id: str) -> str:
    """Return an opaque Agent ID after validating its path-safe shape."""
    if not AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError("Agent ID must match mas-<16 lowercase hex characters>")
    return agent_id


def make_agent_artifact_directory(agent_id: str) -> Path:
    """Build the Agent Artifact Directory for one Agent."""
    agent_id = validate_agent_id(agent_id)
    return AGENTS_ROOT / agent_id


def make_trajectory_artifact_path(agent_id: str) -> Path:
    """Build the deterministic Trajectory Artifact path for one Agent."""
    return make_agent_artifact_directory(agent_id) / "trajectory.traj.json"


def make_artifact_metadata(
    *,
    agent_id: str,
    parent_agent_id: str | None = None,
) -> dict[str, str]:
    """Return artifact metadata for one Agent backed by DBOS workflow identifiers."""
    resolved_agent_id = validate_agent_id(agent_id)
    if parent_agent_id is not None:
        parent_agent_id = validate_agent_id(parent_agent_id)
    artifact_directory = make_agent_artifact_directory(resolved_agent_id)
    trajectory_path = make_trajectory_artifact_path(resolved_agent_id)
    metadata = {
        "agent_id": resolved_agent_id,
        "agent_artifact_directory": artifact_directory.as_posix(),
        "trajectory_artifact_path": trajectory_path.as_posix(),
    }
    if parent_agent_id is not None:
        metadata["parent_agent_id"] = parent_agent_id
    return metadata


def build_trajectory_artifact(
    *,
    agent_id: str,
    parent_agent_id: str | None = None,
    status: str,
    messages: list[dict] | None = None,
    model_stats: dict | None = None,
    submission: str = "",
    extra_info: dict | None = None,
) -> dict:
    """Build a mini-swe-agent-compatible trajectory artifact."""
    metadata = make_artifact_metadata(
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
    )
    messages = messages or [
        {
            "role": "exit",
            "content": status,
            "extra": {
                "exit_status": status,
                "submission": submission,
            },
        }
    ]
    return {
        "info": {
            **metadata,
            "model_stats": model_stats or {
                "instance_cost": 0.0,
                "api_calls": 0,
            },
            "config": {
                "agent_type": "minisweagent.mas.mas_agent.agent_workflow",
            },
            "mini_version": __version__,
            "exit_status": status,
            "terminal_state": status,
            "submission": submission,
            **(extra_info or {}),
        },
        "messages": messages,
        "trajectory_format": "mini-swe-agent-1.1",
    }


def save_trajectory_artifact(
    *,
    agent_id: str,
    parent_agent_id: str | None = None,
    status: str,
    messages: list[dict] | None = None,
    model_stats: dict | None = None,
    submission: str = "",
    extra_info: dict | None = None,
) -> Path:
    """Persist a Trajectory Artifact, creating parents and overwriting the same path safely."""
    metadata = make_artifact_metadata(
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
    )
    trajectory_path = Path(metadata["trajectory_artifact_path"])
    artifact = build_trajectory_artifact(
        agent_id=metadata["agent_id"],
        parent_agent_id=parent_agent_id,
        status=status,
        messages=messages,
        model_stats=model_stats,
        submission=submission,
        extra_info=extra_info,
    )
    trajectory_path.parent.mkdir(parents=True, exist_ok=True)
    trajectory_path.write_text(json.dumps(artifact, indent=2))
    return trajectory_path
