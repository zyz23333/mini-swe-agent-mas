#!/usr/bin/env python3

"""Run mini-mas on ProgramBench instances."""

from __future__ import annotations

import concurrent.futures
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.live import Live

from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.mas.action_environment import (
    MAS_DOCKER_LABEL_PREFIX,
    action_environment_namespace,
    docker_container_name,
)
from minisweagent.mas.artifacts import make_agent_id, make_trajectory_artifact_path
from minisweagent.mas.execution_config import (
    AGENT_EXECUTION_CONFIG_SCHEMA_VERSION,
    normalize_agent_execution_config,
    validate_agent_execution_config,
)
from minisweagent.mas.runtime import MAS_RUNTIME_STATE_STORE_ENV, MasRuntimeProfile, MasRuntimeSession
from minisweagent.run.benchmarks.utils.batch_progress import RunBatchProgressManager
from minisweagent.utils.log import add_file_handler, logger
from minisweagent.utils.serialize import UNSET, recursive_merge

PROGRAMBENCH_DOCKER_ORG = "programbench"
PROGRAMBENCH_IMAGE_TAG = "task_cleanroom"
PROGRAMBENCH_WORKSPACE = "/workspace"
PROGRAMBENCH_RESULTS_FILE = "programbench-mas-results.json"
PROGRAMBENCH_EVAL_COMMAND_TEMPLATE = "uv run --project references/ProgramBench programbench eval {run_dir}"
PROGRAMBENCH_ROOT_COMMAND_RESULT_TIMEOUT_MARGIN_SECONDS = 30.0
DEFAULT_CONFIG_FILE = builtin_config_dir / "benchmarks" / "programbench_mas.yaml"
DEFAULT_TASKS_DIR = Path("references") / "ProgramBench" / "src" / "programbench" / "data" / "tasks"
_OUTPUT_FILE_LOCK = threading.Lock()

app = typer.Typer(rich_markup_mode="rich", add_completion=False)


@dataclass(frozen=True)
class DockerProvisioningResult:
    """Concrete Docker Action Environment created for one ProgramBench instance."""

    action_environment_id: str
    container_name: str
    container_id: str
    image: str
    cwd: str


@dataclass(frozen=True)
class ProgramBenchRunResult:
    """Single-instance ProgramBench MAS runner result."""

    instance_id: str
    status: str
    root_agent_id: str
    action_environment_id: str
    container_name: str
    submission_path: str
    manifest_path: str
    eval_command: str


def programbench_image_name_from_instance_id(instance_id: str) -> str:
    """Return the official ProgramBench task_cleanroom image name for an instance."""
    return f"{PROGRAMBENCH_DOCKER_ORG}/{instance_id.replace('__', '_1776_')}:{PROGRAMBENCH_IMAGE_TAG}"


def make_programbench_action_environment_id(instance_id: str, root_agent_id: str) -> str:
    """Derive a path-safe Action Environment ID that is unique for one fresh instance run."""
    compact_instance = re.sub(r"[^A-Za-z0-9_.-]+", "-", instance_id.replace("__", "-")).strip(".-")
    suffix = root_agent_id.removeprefix("mas-")[:8]
    base = compact_instance[:42].strip(".-") or "instance"
    return f"programbench-{base}-{suffix}"


def load_programbench_instances(tasks_dir: Path = DEFAULT_TASKS_DIR, *, include_tests: bool = False) -> list[dict[str, Any]]:
    """Load ProgramBench task metadata from local task directories."""
    task_dirs = sorted(path for path in tasks_dir.iterdir() if path.is_dir() and (path / "task.yaml").exists())
    return [_load_programbench_instance(path, include_tests=include_tests) for path in task_dirs]


def filter_programbench_instances(
    instances: list[dict[str, Any]],
    *,
    instance_id: str = "",
    filter_spec: str = "",
    slice_spec: str = "",
    shuffle: bool = False,
) -> list[dict[str, Any]]:
    """Filter, optionally shuffle, and slice ProgramBench instances."""
    selected = list(instances)
    if instance_id:
        selected = [instance for instance in selected if instance["instance_id"] == instance_id]
    if shuffle:
        selected = sorted(selected, key=lambda instance: instance["instance_id"])
        random.seed(42)
        random.shuffle(selected)
    if filter_spec:
        selected = [instance for instance in selected if re.match(filter_spec, instance["instance_id"])]
    if slice_spec:
        values = [int(value) if value else None for value in slice_spec.split(":")]
        selected = selected[slice(*values)]
    return selected


def existing_programbench_results(output_dir: Path) -> dict[str, Any]:
    """Read the run-level ProgramBench MAS results file when it exists."""
    results_path = output_dir / PROGRAMBENCH_RESULTS_FILE
    if not results_path.exists():
        return {}
    return json.loads(results_path.read_text())


def select_instances_for_run(
    instances: list[dict[str, Any]],
    *,
    output_dir: Path,
    instance_id: str = "",
    filter_spec: str = "",
    slice_spec: str = "",
    shuffle: bool = False,
    redo_existing: bool = False,
) -> list[dict[str, Any]]:
    """Apply ProgramBench runner selection and skip/redo policy."""
    selected = filter_programbench_instances(
        instances,
        instance_id=instance_id,
        filter_spec=filter_spec,
        slice_spec=slice_spec,
        shuffle=shuffle,
    )
    if redo_existing:
        return selected
    existing = existing_programbench_results(output_dir)
    return [instance for instance in selected if instance["instance_id"] not in existing]


class ProgramBenchDockerProvisioner:
    """Runner-side lifecycle owner for one ProgramBench Docker Action Environment."""

    def __init__(
        self,
        *,
        executable: str = "docker",
        namespace: str | None = None,
        run_timeout: int = 300,
    ) -> None:
        self.executable = executable
        self.namespace = namespace or action_environment_namespace()
        self.run_timeout = run_timeout

    def provision(
        self,
        *,
        image: str,
        action_environment_id: str,
        root_agent_id: str,
        cwd: str = PROGRAMBENCH_WORKSPACE,
        run_args: Sequence[str] = (),
    ) -> DockerProvisioningResult:
        """Create and verify the cleanroom container expected by MAS Docker execution."""
        run_args = _validated_programbench_run_args(list(run_args))
        container_name = docker_container_name(
            namespace=self.namespace,
            action_environment_id=action_environment_id,
        )
        labels = {
            f"{MAS_DOCKER_LABEL_PREFIX}.namespace": self.namespace,
            f"{MAS_DOCKER_LABEL_PREFIX}.root_agent_id": root_agent_id,
            f"{MAS_DOCKER_LABEL_PREFIX}.action_environment_id": action_environment_id,
            f"{MAS_DOCKER_LABEL_PREFIX}.binding_kind": "docker/shared",
        }
        label_args = [item for key, value in labels.items() for item in ("--label", f"{key}={value}")]
        cmd = [
            self.executable,
            "run",
            "-d",
            "--init",
            "--name",
            container_name,
            "-w",
            cwd,
            *label_args,
            *run_args,
            "--network",
            "none",
            image,
            "sleep",
            "2h",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.run_timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to provision ProgramBench container: {result.stderr.strip() or result.stdout.strip()}")
        container_id = result.stdout.strip()
        self.verify(container_name=container_name, action_environment_id=action_environment_id)
        return DockerProvisioningResult(
            action_environment_id=action_environment_id,
            container_name=container_name,
            container_id=container_id,
            image=image,
            cwd=cwd,
        )

    def verify(self, *, container_name: str, action_environment_id: str) -> None:
        """Verify the provisioned container is running and has no network access."""
        inspect = self.inspect(container_name)
        if not inspect.get("State", {}).get("Running"):
            raise RuntimeError(f"ProgramBench container is not running: {container_name}")
        labels = inspect.get("Config", {}).get("Labels") or {}
        expected = {
            f"{MAS_DOCKER_LABEL_PREFIX}.namespace": self.namespace,
            f"{MAS_DOCKER_LABEL_PREFIX}.action_environment_id": action_environment_id,
            f"{MAS_DOCKER_LABEL_PREFIX}.binding_kind": "docker/shared",
        }
        mismatched = [key for key, value in expected.items() if labels.get(key) != value]
        if mismatched:
            raise RuntimeError(f"ProgramBench container label mismatch: {', '.join(mismatched)}")
        networks = inspect.get("NetworkSettings", {}).get("Networks") or {}
        if set(networks) != {"none"}:
            raise RuntimeError(f"ProgramBench container must run with --network none, got: {sorted(networks)}")

    def inspect(self, container_name: str) -> dict[str, Any]:
        result = subprocess.run(
            [self.executable, "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker inspect failed for {container_name}: {result.stderr.strip() or result.stdout.strip()}")
        payload = json.loads(result.stdout)
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"docker inspect returned no container for {container_name}")
        return payload[0]

    def cleanup(self, container_name: str) -> None:
        """Best-effort cleanup for a provisioned ProgramBench container."""
        subprocess.run(
            [self.executable, "rm", "-f", container_name],
            capture_output=True,
            timeout=30,
        )


def build_programbench_agent_execution_config(
    *,
    config_specs: Sequence[str],
    model_name: str | None,
    model_class: str | None,
    action_environment_id: str,
    image: str,
    cwd: str = PROGRAMBENCH_WORKSPACE,
    env: Mapping[str, str] | None = None,
    timeout: int = 30,
    run_args: Sequence[str] = (),
    interpreter: Sequence[str] = ("bash", "-lc"),
) -> dict[str, Any]:
    """Build the Configured Interactive Root Agent Execution Config for ProgramBench."""
    specs = list(config_specs) or [str(DEFAULT_CONFIG_FILE)]
    configs = [get_config_from_spec(spec) for spec in specs]
    configs.append(
        {
            "model": {
                "model_name": model_name or os.getenv("MSWEA_MODEL_NAME") or UNSET,
                "model_class": model_class or UNSET,
            }
        }
    )
    merged = recursive_merge(*configs)
    normalized = normalize_agent_execution_config(merged, shared_workspace=Path.cwd())
    normalized["environment"] = {
        "default_action_environment_id": action_environment_id,
        "action_environments": {
            action_environment_id: {
                "kind": "docker",
                "scope": "shared",
                "image": image,
                "cwd": cwd,
                "env": dict(env or {}),
                "timeout": timeout,
                "run_args": list(run_args),
                "interpreter": list(interpreter),
            }
        },
    }
    normalized["schema_version"] = AGENT_EXECUTION_CONFIG_SCHEMA_VERSION
    return validate_agent_execution_config(normalized, preflight_credentials=False)


def export_programbench_workspace_from_container(
    *,
    container_name: str,
    cwd: str,
    output_dir: Path,
    instance_id: str,
    executable: str = "docker",
) -> Path:
    """Export one ProgramBench Docker workspace to `<run-dir>/<instance_id>/submission.tar.gz`."""
    instance_dir = output_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    submission_path = instance_dir / "submission.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        raw_tar = Path(tmp) / "workspace.tar"
        with raw_tar.open("wb") as stream:
            result = subprocess.run(
                [executable, "exec", container_name, "tar", "-C", cwd, "-cf", "-", "."],
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=300,
            )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr)
            raise RuntimeError(f"docker workspace export failed: {stderr.strip()}")
        filter_workspace_tar_to_submission(raw_tar, submission_path)
    return submission_path


def filter_workspace_tar_to_submission(raw_tar: Path, submission_path: Path) -> Path:
    """Filter a Docker workspace tar stream into a ProgramBench submission archive."""
    submission_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(raw_tar) as source, tarfile.open(submission_path, "w:gz") as target:
        for member in source:
            relative = _safe_tar_member_path(member.name)
            if relative is None or _excluded_export_path(relative):
                continue
            member.name = relative.as_posix()
            fileobj = source.extractfile(member) if member.isfile() else None
            target.addfile(member, fileobj)
            if fileobj is not None:
                fileobj.close()
    return submission_path


def export_workspace_tree_to_tar(source_dir: Path, submission_path: Path) -> Path:
    """Create a ProgramBench submission archive from a local workspace tree."""
    submission_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(submission_path, "w:gz") as tar:
        for path in sorted(source_dir.rglob("*")):
            relative = path.relative_to(source_dir)
            if _excluded_export_path(relative):
                continue
            tar.add(path, arcname=relative.as_posix(), recursive=False)
    return submission_path


def copy_mas_trajectories(*, agent_ids: Sequence[str], instance_dir: Path) -> list[str]:
    """Copy relevant MAS trajectory artifacts into the ProgramBench instance output directory."""
    trajectories_dir = instance_dir / "trajectories"
    copied: list[str] = []
    seen: set[str] = set()
    for agent_id in agent_ids:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        source = make_trajectory_artifact_path(agent_id)
        if not source.exists():
            continue
        trajectories_dir.mkdir(parents=True, exist_ok=True)
        destination = trajectories_dir / f"{agent_id}.traj.json"
        shutil.copy2(source, destination)
        copied.append(destination.relative_to(instance_dir).as_posix())
    return copied


def write_instance_manifest(
    *,
    output_dir: Path,
    instance_id: str,
    root_agent_id: str,
    action_environment_id: str,
    container_name: str,
    agent_ids: Sequence[str],
    trajectory_paths: Sequence[str],
    status: str,
    export_status: str,
    submission_path: Path | None,
    error: str = "",
) -> Path:
    """Write `<run-dir>/<instance_id>/mas-run.json`."""
    instance_dir = output_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = instance_dir / "mas-run.json"
    data = {
        "instance_id": instance_id,
        "root_agent_id": root_agent_id,
        "action_environment_id": action_environment_id,
        "docker_container_name": container_name,
        "agent_ids": list(dict.fromkeys(agent_ids)),
        "trajectory_paths": list(trajectory_paths),
        "status": status,
        "export_status": export_status,
        "submission_path": _relative_or_empty(submission_path, output_dir),
        "error": error,
    }
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True))
    return manifest_path


def update_programbench_results_file(output_dir: Path, instance_id: str, result: Mapping[str, Any]) -> None:
    """Update the run-level ProgramBench MAS summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / PROGRAMBENCH_RESULTS_FILE
    with _OUTPUT_FILE_LOCK:
        data = json.loads(results_path.read_text()) if results_path.exists() else {}
        data[instance_id] = dict(result)
        results_path.write_text(json.dumps(data, indent=2, sort_keys=True))


async def run_programbench_instance_async(
    instance: Mapping[str, Any],
    *,
    output_dir: Path,
    config_specs: Sequence[str],
    model_name: str | None = None,
    model_class: str | None = None,
    result_timeout_seconds: float = 60,
    docker_executable: str = "docker",
    docker_run_args: Sequence[str] = (),
    cleanup_container: bool = True,
    session_factory: Callable[..., Any] = MasRuntimeSession,
    provisioner: ProgramBenchDockerProvisioner | None = None,
    export_workspace: Callable[..., Path] = export_programbench_workspace_from_container,
) -> ProgramBenchRunResult:
    """Run one ProgramBench instance through a Configured Interactive Root Agent."""
    instance_id = str(instance["instance_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    instance_dir = output_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)

    root_agent_id = make_agent_id()
    action_environment_id = make_programbench_action_environment_id(instance_id, root_agent_id)
    image = str(instance.get("image_name") or programbench_image_name_from_instance_id(instance_id))
    if ":" not in image.rsplit("/", 1)[-1]:
        image = f"{image}:{PROGRAMBENCH_IMAGE_TAG}"
    provisioner = provisioner or ProgramBenchDockerProvisioner(executable=docker_executable)
    provisioned: DockerProvisioningResult | None = None
    status = "error"
    export_status = "not_exported"
    submission_path: Path | None = None
    manifest_path = instance_dir / "mas-run.json"
    error = ""
    agent_ids = [root_agent_id]
    try:
        provisioned = provisioner.provision(
            image=image,
            action_environment_id=action_environment_id,
            root_agent_id=root_agent_id,
            cwd=PROGRAMBENCH_WORKSPACE,
            run_args=docker_run_args,
        )
        agent_execution_config = build_programbench_agent_execution_config(
            config_specs=config_specs,
            model_name=model_name,
            model_class=model_class,
            action_environment_id=action_environment_id,
            image=image,
            cwd=PROGRAMBENCH_WORKSPACE,
            run_args=docker_run_args,
        )
        command = make_programbench_root_spawn_command(instance, wait_timeout_seconds=result_timeout_seconds)
        root_command_timeout_seconds = result_timeout_seconds + PROGRAMBENCH_ROOT_COMMAND_RESULT_TIMEOUT_MARGIN_SECONDS
        async with session_factory(profile=MasRuntimeProfile.SUPERVISED_INTERACTIVE_AND_AI) as session:
            await session.start_interactive_root_agent_workflow(
                workflow_id=root_agent_id,
                agent_execution_config=agent_execution_config,
            )
            result_event = await session.send_root_command(
                root_agent_id=root_agent_id,
                command=command,
                result_timeout_seconds=root_command_timeout_seconds,
            )
            command_result = dict(result_event.get("result", {}))
            extra = dict(command_result.get("extra", {}))
            agent_ids.extend(str(agent_id) for agent_id in extra.get("child_agent_ids", []))
            ready_children = list(extra.get("ready_children", []))
            ready_child = _submitted_ready_child(ready_children)
            if ready_child is None:
                status = _status_from_root_command_result(command_result, ready_children)
                error = command_result.get("exception_info", "") or command_result.get("output", "")
            else:
                child_agent_id = str(ready_child["agent_id"])
                agent_ids.append(child_agent_id)
                await session.send_root_command(
                    root_agent_id=root_agent_id,
                    command=f"mini-mas close {child_agent_id}",
                    result_timeout_seconds=root_command_timeout_seconds,
                )
                submission_path = export_workspace(
                    container_name=provisioned.container_name,
                    cwd=provisioned.cwd,
                    output_dir=output_dir,
                    instance_id=instance_id,
                    executable=docker_executable,
                )
                status = "submitted"
                export_status = "exported"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.error("Error processing ProgramBench instance %s: %s", instance_id, exc, exc_info=True)
    finally:
        if provisioned is not None and cleanup_container:
            provisioner.cleanup(provisioned.container_name)
        trajectory_paths = copy_mas_trajectories(agent_ids=agent_ids, instance_dir=instance_dir)
        container_name = provisioned.container_name if provisioned is not None else ""
        manifest_path = write_instance_manifest(
            output_dir=output_dir,
            instance_id=instance_id,
            root_agent_id=root_agent_id,
            action_environment_id=action_environment_id,
            container_name=container_name,
            agent_ids=agent_ids,
            trajectory_paths=trajectory_paths,
            status=status,
            export_status=export_status,
            submission_path=submission_path,
            error=error,
        )
        result_payload = {
            "status": status,
            "root_agent_id": root_agent_id,
            "action_environment_id": action_environment_id,
            "submission_path": _relative_or_empty(submission_path, output_dir),
            "manifest_path": manifest_path.relative_to(output_dir).as_posix(),
        }
        update_programbench_results_file(output_dir, instance_id, result_payload)
    return ProgramBenchRunResult(
        instance_id=instance_id,
        status=status,
        root_agent_id=root_agent_id,
        action_environment_id=action_environment_id,
        container_name=provisioned.container_name if provisioned is not None else "",
        submission_path=_relative_or_empty(submission_path, output_dir),
        manifest_path=manifest_path.relative_to(output_dir).as_posix(),
        eval_command=PROGRAMBENCH_EVAL_COMMAND_TEMPLATE.format(run_dir=output_dir.as_posix()),
    )


def run_programbench_instance(instance: Mapping[str, Any], **kwargs: Any) -> ProgramBenchRunResult:
    """Synchronous wrapper for one ProgramBench MAS instance."""
    import asyncio

    return asyncio.run(run_programbench_instance_async(instance, **kwargs))


def process_instance(
    instance: Mapping[str, Any],
    *,
    output_dir: Path,
    config_specs: Sequence[str],
    progress_manager: RunBatchProgressManager | None = None,
    **kwargs: Any,
) -> ProgramBenchRunResult:
    """Process one ProgramBench instance and update progress."""
    instance_id = str(instance["instance_id"])
    if progress_manager is not None:
        progress_manager.on_instance_start(instance_id)
        progress_manager.update_instance_status(instance_id, "Starting MAS run")
    result = run_programbench_instance(
        instance,
        output_dir=output_dir,
        config_specs=config_specs,
        **kwargs,
    )
    if progress_manager is not None:
        progress_manager.on_instance_end(instance_id, result.status)
    return result


def make_programbench_root_spawn_command(instance: Mapping[str, Any], *, wait_timeout_seconds: float) -> str:
    """Build the Root command submitted by the ProgramBench runner."""
    task = make_programbench_task_prompt(instance)
    import shlex

    if wait_timeout_seconds < 0:
        msg = "ProgramBench spawn wait timeout must be non-negative"
        raise ValueError(msg)
    return " ".join(
        [
            "mini-mas",
            "spawn",
            "--wait",
            "--timeout",
            f"{wait_timeout_seconds:g}",
            shlex.quote(task),
        ]
    )


def make_programbench_task_prompt(instance: Mapping[str, Any]) -> str:
    """Build a generic black-box ProgramBench task prompt."""
    instance_id = str(instance["instance_id"])
    repository = str(instance.get("repository", "unknown"))
    language = str(instance.get("language", "unknown"))
    return (
        f"ProgramBench instance: {instance_id}\n"
        f"Repository: {repository}\n"
        f"Language: {language}\n\n"
        "Reverse-engineer and implement the program behavior needed for the hidden ProgramBench tests. "
        "Work inside the provided cleanroom workspace. When ready, submit by running "
        "`echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` as a standalone command."
    )


def print_eval_handoff(output_dir: Path) -> str:
    """Return and print the ProgramBench eval handoff command."""
    command = PROGRAMBENCH_EVAL_COMMAND_TEMPLATE.format(run_dir=output_dir.as_posix())
    typer.echo(f"ProgramBench eval command: {command}")
    return command


def make_programbench_mas_runtime_state_store(output_dir: Path) -> Path:
    """Create a fresh run-scoped MAS DBOS state store path for one benchmark invocation."""
    return output_dir / ".mini-mas" / "runtime" / f"run-{secrets.token_hex(8)}" / "mini_mas_dbos.sqlite"


# fmt: off
@app.command()
def main(
    tasks_dir: Path = typer.Option(DEFAULT_TASKS_DIR, "--tasks-dir", help="ProgramBench tasks directory", rich_help_panel="Data selection"),
    instance_id: str = typer.Option("", "-i", "--instance", help="Run one ProgramBench instance ID", rich_help_panel="Data selection"),
    filter_spec: str = typer.Option("", "--filter", help="Filter instance IDs by regex", rich_help_panel="Data selection"),
    slice_spec: str = typer.Option("", "--slice", help="Slice specification such as 0:5", rich_help_panel="Data selection"),
    shuffle: bool = typer.Option(False, "--shuffle", help="Shuffle instances deterministically", rich_help_panel="Data selection"),
    output: Path = typer.Option(Path("programbench-mas-run"), "-o", "--output", help="Output run directory", rich_help_panel="Basic"),
    workers: int = typer.Option(1, "-w", "--workers", help="Number of instances to run concurrently", rich_help_panel="Basic"),
    redo_existing: bool = typer.Option(False, "--redo-existing", help="Redo instances already in programbench-mas-results.json", rich_help_panel="Data selection"),
    model: str | None = typer.Option(None, "-m", "--model", help="Model to use", rich_help_panel="Basic"),
    model_class: str | None = typer.Option(None, "--model-class", help="Model class to use", rich_help_panel="Advanced"),
    config_spec: list[str] = typer.Option([str(DEFAULT_CONFIG_FILE)], "-c", "--config", help="Config specs", rich_help_panel="Basic"),
    docker_executable: str = typer.Option("docker", "--docker-executable", help="Docker executable", rich_help_panel="Advanced"),
    result_timeout_seconds: float = typer.Option(
        60,
        "--result-timeout",
        help="Child spawn wait timeout; Root command result wait includes a small finalization margin",
        rich_help_panel="Advanced",
    ),
) -> None:
    # fmt: on
    """Run mini-mas on ProgramBench instances."""
    output.mkdir(parents=True, exist_ok=True)
    os.environ[MAS_RUNTIME_STATE_STORE_ENV] = make_programbench_mas_runtime_state_store(output).as_posix()
    add_file_handler(output / "minisweagent-programbench-mas.log")
    instances = load_programbench_instances(tasks_dir, include_tests=False)
    selected = select_instances_for_run(
        instances,
        output_dir=output,
        instance_id=instance_id,
        filter_spec=filter_spec,
        slice_spec=slice_spec,
        shuffle=shuffle,
        redo_existing=redo_existing,
    )
    logger.info("Running ProgramBench MAS on %s instances", len(selected))
    progress_manager = RunBatchProgressManager(len(selected), output / f"exit_statuses_{time.time()}.yaml")

    def submit(executor: concurrent.futures.ThreadPoolExecutor) -> dict[concurrent.futures.Future, str]:
        return {
            executor.submit(
                process_instance,
                instance,
                output_dir=output,
                config_specs=config_spec,
                model_name=model,
                model_class=model_class,
                docker_executable=docker_executable,
                result_timeout_seconds=result_timeout_seconds,
                progress_manager=progress_manager,
            ): str(instance["instance_id"])
            for instance in selected
        }

    with Live(progress_manager.render_group, refresh_per_second=4):
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = submit(executor)
            for future in concurrent.futures.as_completed(futures):
                instance = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    logger.error("Uncaught ProgramBench MAS error for %s: %s", instance, exc, exc_info=True)
                    progress_manager.on_uncaught_exception(instance, exc)
    print_eval_handoff(output)


def _load_programbench_instance(task_dir: Path, *, include_tests: bool) -> dict[str, Any]:
    data = yaml.safe_load((task_dir / "task.yaml").read_text()) or {}
    instance = dict(data)
    instance["instance_id"] = task_dir.name
    instance["image_name"] = programbench_image_name_from_instance_id(task_dir.name)
    if include_tests and (task_dir / "tests.json").exists():
        instance.update(json.loads((task_dir / "tests.json").read_text()))
    return instance


def _validated_programbench_run_args(run_args: list[str]) -> list[str]:
    index = 0
    while index < len(run_args):
        argument = run_args[index]
        if argument in {"--network", "--net"}:
            if index + 1 >= len(run_args):
                raise ValueError(f"{argument} requires a value")
            if run_args[index + 1] != "none":
                raise ValueError("ProgramBench inference requires Docker --network none")
            index += 2
            continue
        if argument.startswith("--network=") or argument.startswith("--net="):
            value = argument.split("=", 1)[1]
            if value != "none":
                raise ValueError("ProgramBench inference requires Docker --network none")
        index += 1
    return list(run_args)


def _excluded_export_path(relative: Path) -> bool:
    parts = relative.parts
    name = relative.name
    if name == ".DS_Store":
        return True
    if any(part in {".mini-mas", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache"} for part in parts):
        return True
    return len(parts) >= 3 and parts[-2:] == ("node_modules", ".cache")


def _safe_tar_member_path(name: str) -> Path | None:
    clean = name.removeprefix("./")
    if not clean or clean == ".":
        return None
    path = Path(clean)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def _submitted_ready_child(ready_children: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for child in ready_children:
        if child.get("lifecycle_state") == "waiting_for_parent":
            return child
    return None


def _status_from_root_command_result(command_result: Mapping[str, Any], ready_children: Sequence[Mapping[str, Any]]) -> str:
    for child in ready_children:
        state = child.get("lifecycle_state")
        if state in {"execution_blocked", "failed", "limits_exceeded"}:
            return str(state)
    if command_result.get("returncode", 0) != 0:
        return "root_command_failed"
    if ready_children:
        return str(ready_children[0].get("lifecycle_state") or "not_submitted")
    return "not_submitted"


def _relative_or_empty(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    app()
