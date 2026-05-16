import json
import stat
import subprocess
import tarfile

import pytest


def test_programbench_image_name_replaces_double_underscore():
    from minisweagent.run.benchmarks.programbench_mas import programbench_image_name_from_instance_id

    assert (
        programbench_image_name_from_instance_id("ffmpeg__ffmpeg.360a402")
        == "programbench/ffmpeg_1776_ffmpeg.360a402:task_cleanroom"
    )


def test_programbench_root_spawn_command_propagates_wait_timeout():
    from minisweagent.run.benchmarks.programbench_mas import make_programbench_root_spawn_command

    command = make_programbench_root_spawn_command(
        {
            "instance_id": "xorg62__tty-clock.f2f847c",
            "repository": "xorg62/tty-clock",
            "language": "c",
        },
        wait_timeout_seconds=1800,
    )

    assert command.startswith("mini-mas spawn --wait --timeout 1800 ")
    assert "xorg62__tty-clock.f2f847c" in command


def test_programbench_mas_uses_programbench_specific_default_config():
    from minisweagent.config import get_config_from_spec
    from minisweagent.run.benchmarks.programbench_mas import (
        DEFAULT_CONFIG_FILE,
        build_programbench_agent_execution_config,
    )

    assert DEFAULT_CONFIG_FILE.name == "programbench_mas.yaml"
    config = get_config_from_spec(DEFAULT_CONFIG_FILE)
    instance_template = config["agent"]["instance_template"]

    assert "ProgramBench Submission Contract" in instance_template
    assert "chmod +x ./compile.sh && ./compile.sh" in instance_template
    assert "`compile.sh` MUST build or create the candidate program as `./executable`" in instance_template

    execution_config = build_programbench_agent_execution_config(
        config_specs=[],
        model_name="deterministic",
        model_class=None,
        action_environment_id="programbench-test",
        image="programbench/test:task_cleanroom",
    )
    assert "ProgramBench Submission Contract" in execution_config["agent"]["instance_template"]


def test_programbench_mas_runtime_state_store_is_run_scoped(tmp_path):
    from minisweagent.run.benchmarks.programbench_mas import make_programbench_mas_runtime_state_store

    first = make_programbench_mas_runtime_state_store(tmp_path / "run")
    second = make_programbench_mas_runtime_state_store(tmp_path / "run")

    assert first != second
    assert first.name == "mini_mas_dbos.sqlite"
    assert first.parent.parent == tmp_path / "run" / ".mini-mas" / "runtime"


def test_load_and_select_programbench_instances(tmp_path):
    from minisweagent.run.benchmarks.programbench_mas import (
        filter_programbench_instances,
        load_programbench_instances,
        select_instances_for_run,
        update_programbench_results_file,
    )

    for instance_id in ["alpha__tool.1111111", "beta__tool.2222222", "alpha__other.3333333"]:
        task_dir = tmp_path / "tasks" / instance_id
        task_dir.mkdir(parents=True)
        (task_dir / "task.yaml").write_text("repository: example/repo\nlanguage: python\n")

    instances = load_programbench_instances(tmp_path / "tasks")

    assert [instance["instance_id"] for instance in instances] == [
        "alpha__other.3333333",
        "alpha__tool.1111111",
        "beta__tool.2222222",
    ]
    assert filter_programbench_instances(instances, filter_spec=r"alpha__.*", slice_spec="1:") == [
        instances[1],
    ]

    output_dir = tmp_path / "run"
    update_programbench_results_file(output_dir, "alpha__tool.1111111", {"status": "submitted"})
    selected = select_instances_for_run(instances, output_dir=output_dir, filter_spec=r"alpha__.*")
    redo_selected = select_instances_for_run(
        instances,
        output_dir=output_dir,
        filter_spec=r"alpha__.*",
        redo_existing=True,
    )

    assert [instance["instance_id"] for instance in selected] == ["alpha__other.3333333"]
    assert [instance["instance_id"] for instance in redo_selected] == ["alpha__other.3333333", "alpha__tool.1111111"]


def test_programbench_docker_provisioner_creates_no_network_container(monkeypatch, tmp_path):
    from minisweagent.mas.action_environment import docker_container_name
    from minisweagent.run.benchmarks.programbench_mas import ProgramBenchDockerProvisioner

    calls = []
    namespace = tmp_path.as_posix()
    expected_name = docker_container_name(namespace=namespace, action_environment_id="programbench-test")

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="container-id\n", stderr="")
        if cmd[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    [
                        {
                            "State": {"Running": True},
                            "Config": {
                                "Labels": {
                                    "minisweagent.mas.namespace": namespace,
                                    "minisweagent.mas.root_agent_id": "mas-0123456789abcdef",
                                    "minisweagent.mas.action_environment_id": "programbench-test",
                                    "minisweagent.mas.binding_kind": "docker/shared",
                                }
                            },
                            "NetworkSettings": {"Networks": {"none": {}}},
                        }
                    ]
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected docker command: {cmd}")

    monkeypatch.setattr("minisweagent.run.benchmarks.programbench_mas.subprocess.run", run)

    provisioner = ProgramBenchDockerProvisioner(namespace=namespace)
    result = provisioner.provision(
        image="programbench/example:task_cleanroom",
        action_environment_id="programbench-test",
        root_agent_id="mas-0123456789abcdef",
        cwd="/workspace",
        run_args=["--cpus", "2"],
    )

    assert result.container_name == expected_name
    run_cmd = calls[0]
    assert run_cmd[:2] == ["docker", "run"]
    assert "--network" in run_cmd
    assert run_cmd[run_cmd.index("--network") + 1] == "none"
    assert "--label" in run_cmd
    assert "programbench/example:task_cleanroom" in run_cmd
    assert calls[1] == ["docker", "inspect", expected_name]


@pytest.mark.parametrize("run_args", [["--network", "host"], ["--network=bridge"], ["--net", "container:abc"]])
def test_programbench_docker_provisioner_rejects_non_none_network(run_args):
    from minisweagent.run.benchmarks.programbench_mas import ProgramBenchDockerProvisioner

    provisioner = ProgramBenchDockerProvisioner(namespace="/workspace")

    with pytest.raises(ValueError, match="--network none"):
        provisioner.provision(
            image="programbench/example:task_cleanroom",
            action_environment_id="programbench-test",
            root_agent_id="mas-0123456789abcdef",
            run_args=run_args,
        )


def test_export_workspace_tree_to_tar_excludes_metadata_and_preserves_executable(tmp_path):
    from minisweagent.run.benchmarks.programbench_mas import export_workspace_tree_to_tar

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mini-mas").mkdir()
    (workspace / ".mini-mas" / "state").write_text("secret")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "HEAD").write_text("ref")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "mod.pyc").write_text("cache")
    (workspace / "node_modules" / ".cache").mkdir(parents=True)
    (workspace / "node_modules" / ".cache" / "x").write_text("cache")
    (workspace / "build").mkdir()
    (workspace / "build" / "artifact").write_text("keep")
    script = workspace / "run.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    archive = export_workspace_tree_to_tar(workspace, tmp_path / "submission.tar.gz")

    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
        script_info = tar.getmember("run.sh")

    assert ".mini-mas/state" not in names
    assert ".git/HEAD" not in names
    assert "__pycache__/mod.pyc" not in names
    assert "node_modules/.cache/x" not in names
    assert "build/artifact" in names
    assert script_info.mode & stat.S_IXUSR


def test_filter_workspace_tar_to_submission_rejects_unsafe_members(tmp_path):
    from minisweagent.run.benchmarks.programbench_mas import filter_workspace_tar_to_submission

    raw_tar = tmp_path / "raw.tar"
    safe_file = tmp_path / "safe.txt"
    safe_file.write_text("safe")
    excluded_file = tmp_path / "cache.txt"
    excluded_file.write_text("cache")
    with tarfile.open(raw_tar, "w") as tar:
        tar.add(safe_file, arcname="./safe.txt")
        tar.add(excluded_file, arcname="./.mini-mas/state")
        tar.add(safe_file, arcname="../escape.txt")

    submission = filter_workspace_tar_to_submission(raw_tar, tmp_path / "submission.tar.gz")

    with tarfile.open(submission, "r:gz") as tar:
        names = set(tar.getnames())

    assert names == {"safe.txt"}


def test_manifest_and_trajectory_copy(tmp_path, monkeypatch):
    from minisweagent.mas.artifacts import make_trajectory_artifact_path
    from minisweagent.run.benchmarks.programbench_mas import copy_mas_trajectories, write_instance_manifest

    monkeypatch.chdir(tmp_path)
    root_id = "mas-0123456789abcdef"
    child_id = "mas-1111111111111111"
    for agent_id in [root_id, child_id]:
        path = make_trajectory_artifact_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"info": {"agent_id": agent_id}}))

    instance_dir = tmp_path / "run" / "testorg__calculator.abc1234"
    copied = copy_mas_trajectories(agent_ids=[root_id, child_id], instance_dir=instance_dir)
    manifest = write_instance_manifest(
        output_dir=tmp_path / "run",
        instance_id="testorg__calculator.abc1234",
        root_agent_id=root_id,
        action_environment_id="programbench-test",
        container_name="container",
        agent_ids=[root_id, child_id],
        trajectory_paths=copied,
        status="submitted",
        export_status="exported",
        submission_path=tmp_path / "run" / "testorg__calculator.abc1234" / "submission.tar.gz",
    )

    assert copied == ["trajectories/mas-0123456789abcdef.traj.json", "trajectories/mas-1111111111111111.traj.json"]
    assert (instance_dir / copied[0]).exists()
    data = json.loads(manifest.read_text())
    assert data["instance_id"] == "testorg__calculator.abc1234"
    assert data["root_agent_id"] == root_id
    assert data["agent_ids"] == [root_id, child_id]
    assert data["submission_path"] == "testorg__calculator.abc1234/submission.tar.gz"


def test_single_instance_runner_uses_configured_root_closes_child_and_exports(tmp_path, monkeypatch):
    from minisweagent.mas.artifacts import make_trajectory_artifact_path
    from minisweagent.mas.runtime import MasRuntimeProfile
    from minisweagent.run.benchmarks.programbench_mas import (
        DockerProvisioningResult,
        run_programbench_instance,
    )

    monkeypatch.chdir(tmp_path)
    calls = []

    class FakeProvisioner:
        def provision(self, *, image, action_environment_id, root_agent_id, cwd, run_args):
            calls.append(("provision", image, action_environment_id, root_agent_id, cwd, tuple(run_args)))
            return DockerProvisioningResult(
                action_environment_id=action_environment_id,
                container_name="container",
                container_id="container-id",
                image=image,
                cwd=cwd,
            )

        def cleanup(self, container_name):
            calls.append(("cleanup", container_name))

    class FakeSession:
        def __init__(self, **kwargs):
            calls.append(("session", kwargs["profile"]))
            self.root_agent_id = ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def start_interactive_root_agent_workflow(self, *, workflow_id, agent_execution_config):
            self.root_agent_id = workflow_id
            calls.append(("start_root", workflow_id, agent_execution_config["environment"]["default_action_environment_id"]))
            path = make_trajectory_artifact_path(workflow_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"info": {"agent_id": workflow_id}}))
            return {"agent_id": workflow_id, "lifecycle_state": "waiting_for_command"}

        async def send_root_command(self, *, root_agent_id, command, result_timeout_seconds):
            calls.append(("root_command", command, result_timeout_seconds))
            child_id = "mas-1111111111111111"
            path = make_trajectory_artifact_path(child_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"info": {"agent_id": child_id}}))
            if command.startswith("mini-mas close"):
                return {"result": {"returncode": 0, "extra": {}}}
            return {
                "result": {
                    "returncode": 0,
                    "extra": {
                        "child_agent_ids": [child_id],
                        "ready_children": [
                            {
                                "agent_id": child_id,
                                "lifecycle_state": "waiting_for_parent",
                                "latest_submission": "",
                            }
                        ],
                    },
                }
            }

    def fake_export(**kwargs):
        calls.append(("export", kwargs["container_name"], kwargs["cwd"], kwargs["instance_id"]))
        path = kwargs["output_dir"] / kwargs["instance_id"] / "submission.tar.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"archive")
        return path

    result = run_programbench_instance(
        {
            "instance_id": "testorg__calculator.abc1234",
            "repository": "testorg/calculator",
            "language": "bash",
        },
        output_dir=tmp_path / "run",
        config_specs=[],
        model_name="deterministic",
        session_factory=FakeSession,
        provisioner=FakeProvisioner(),
        export_workspace=fake_export,
    )

    assert result.status == "submitted"
    assert result.submission_path == "testorg__calculator.abc1234/submission.tar.gz"
    assert ("session", MasRuntimeProfile.SUPERVISED_INTERACTIVE_AND_AI) in calls
    assert ("export", "container", "/workspace", "testorg__calculator.abc1234") in calls
    assert any(
        call[0] == "root_command" and call[1].startswith("mini-mas spawn --wait --timeout 60 ") for call in calls
    )
    assert any(call == ("root_command", "mini-mas close mas-1111111111111111", 90.0) for call in calls)
    assert calls[-1] == ("cleanup", "container")
    manifest = json.loads((tmp_path / "run" / "testorg__calculator.abc1234" / "mas-run.json").read_text())
    summary = json.loads((tmp_path / "run" / "programbench-mas-results.json").read_text())
    assert manifest["status"] == "submitted"
    assert manifest["export_status"] == "exported"
    assert manifest["trajectory_paths"]
    assert summary["testorg__calculator.abc1234"]["status"] == "submitted"
