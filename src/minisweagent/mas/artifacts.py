"""Deterministic artifact paths for MAS workflow runs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from minisweagent import __version__

RUNS_ROOT = Path(".mini-mas") / "runs"
ROOT_WORKFLOW_ID_RE = re.compile(r"mas-[0-9a-f]{16}\Z")
WORKFLOW_TREE_ID_RE = re.compile(r"mas-[0-9a-f]{16}(?:-c[0-9]{3})*\Z")


def validate_root_workflow_id(root_workflow_id: str) -> str:
    """Return a root Workflow Tree ID after validating its path-safe shape."""
    if not ROOT_WORKFLOW_ID_RE.fullmatch(root_workflow_id):
        raise ValueError("Root Workflow Tree ID must match mas-<16 lowercase hex characters>")
    return root_workflow_id


def validate_workflow_id(workflow_id: str) -> str:
    """Return an Agent Workflow ID after validating its path-safe tree shape."""
    if not WORKFLOW_TREE_ID_RE.fullmatch(workflow_id):
        raise ValueError("Agent Workflow ID must match mas-<16hex> with optional -cNNN child segments")
    return workflow_id


def make_run_directory(root_workflow_id: str) -> Path:
    """Build the Run Directory for one Root Agent Workflow."""
    root_workflow_id = validate_root_workflow_id(root_workflow_id)
    return RUNS_ROOT / root_workflow_id


def make_trajectory_artifact_path(run_directory: Path, workflow_id: str) -> Path:
    """Build the deterministic Trajectory Artifact path for one Agent Workflow."""
    workflow_id = validate_workflow_id(workflow_id)
    return run_directory / "trajectories" / f"{workflow_id}.traj.json"


def make_artifact_metadata(*, root_workflow_id: str, workflow_id: str) -> dict[str, str]:
    """Return the user-visible artifact metadata for an Agent Workflow."""
    run_directory = make_run_directory(root_workflow_id)
    trajectory_path = make_trajectory_artifact_path(run_directory, workflow_id)
    return {
        "root_workflow_id": root_workflow_id,
        "workflow_id": workflow_id,
        "run_directory": run_directory.as_posix(),
        "trajectory_artifact_path": trajectory_path.as_posix(),
    }


def build_trajectory_artifact(*, root_workflow_id: str, workflow_id: str, status: str) -> dict:
    """Build a minimal mini-swe-agent-compatible trajectory artifact."""
    metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)
    return {
        "info": {
            **metadata,
            "model_stats": {
                "instance_cost": 0.0,
                "api_calls": 0,
            },
            "config": {
                "agent_type": "minisweagent.mas.workflows.root_agent_workflow",
            },
            "mini_version": __version__,
            "exit_status": status,
            "submission": "",
        },
        "messages": [
            {
                "role": "exit",
                "content": status,
                "extra": {
                    "exit_status": status,
                    "submission": "",
                },
            }
        ],
        "trajectory_format": "mini-swe-agent-1.1",
    }


def save_trajectory_artifact(*, root_workflow_id: str, workflow_id: str, status: str) -> Path:
    """Persist a Trajectory Artifact, creating parents and overwriting the same path safely."""
    metadata = make_artifact_metadata(root_workflow_id=root_workflow_id, workflow_id=workflow_id)
    trajectory_path = Path(metadata["trajectory_artifact_path"])
    artifact = build_trajectory_artifact(
        root_workflow_id=root_workflow_id,
        workflow_id=workflow_id,
        status=status,
    )
    trajectory_path.parent.mkdir(parents=True, exist_ok=True)
    trajectory_path.write_text(json.dumps(artifact, indent=2))
    return trajectory_path
