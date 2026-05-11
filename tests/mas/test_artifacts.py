import json

import pytest


def test_agent_artifact_and_trajectory_paths_are_agent_scoped():
    from minisweagent.mas.artifacts import make_agent_artifact_directory, make_trajectory_artifact_path

    artifact_directory = make_agent_artifact_directory("mas-0123456789abcdef")
    trajectory_path = make_trajectory_artifact_path("mas-0123456789abcdef")

    assert artifact_directory.as_posix() == ".mini-mas/agents/mas-0123456789abcdef"
    assert trajectory_path.as_posix() == ".mini-mas/agents/mas-0123456789abcdef/trajectory.traj.json"


def test_agent_id_validation_rejects_tree_encoded_child_ids():
    from minisweagent.mas.artifacts import validate_agent_id

    assert validate_agent_id("mas-0123456789abcdef") == "mas-0123456789abcdef"
    with pytest.raises(ValueError, match="Agent ID must match mas-<16 lowercase hex characters>"):
        validate_agent_id("mas-0123456789abcdef-c001")

def test_trajectory_artifact_save_overwrites_same_workflow_path(tmp_path, monkeypatch):
    from minisweagent.mas.artifacts import (
        make_agent_artifact_directory,
        make_trajectory_artifact_path,
        save_trajectory_artifact,
    )

    monkeypatch.chdir(tmp_path)
    artifact_directory = make_agent_artifact_directory("mas-0123456789abcdef")
    trajectory_path = make_trajectory_artifact_path("mas-0123456789abcdef")

    first_path = save_trajectory_artifact(
        agent_id="mas-0123456789abcdef",
        status="started",
    )
    second_path = save_trajectory_artifact(
        agent_id="mas-0123456789abcdef",
        status="complete",
    )

    assert first_path == trajectory_path
    assert second_path == trajectory_path
    assert list(artifact_directory.rglob("*.traj.json")) == [trajectory_path]
    assert json.loads(trajectory_path.read_text())["info"]["exit_status"] == "complete"
    assert json.loads(trajectory_path.read_text())["info"]["agent_artifact_directory"] == artifact_directory.as_posix()
