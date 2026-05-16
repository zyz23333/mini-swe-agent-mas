"""Action Environment Binding execution for MAS ordinary bash actions."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import subprocess
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minisweagent.environments.local import LocalEnvironment
from minisweagent.exceptions import Submitted
from minisweagent.mas.execution_config import (
    ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
    default_action_environment_binding,
)

ACTION_ENVIRONMENT_LOCK_DIR = Path(".mini-mas") / "runtime" / "action-environment-locks"
MAS_DOCKER_LABEL_PREFIX = "minisweagent.mas"
DEFAULT_DOCKER_EXECUTABLE = "docker"
DEFAULT_DOCKER_INTERPRETER = ("bash", "-lc")

_PROCESS_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


@dataclass
class ActionEnvironmentUnavailableError(Exception):
    """Runtime dependency failure that should block, not terminally fail, an Agent."""

    code: str
    message: str
    action_environment_id: str = ""

    def __str__(self) -> str:
        if self.action_environment_id:
            return f"{self.message} (action_environment_id={self.action_environment_id})"
        return self.message


def action_environment_namespace() -> str:
    """Return the workspace/runtime namespace used for Docker names and lock identity."""
    return Path.cwd().resolve().as_posix()


def docker_container_name(*, namespace: str, action_environment_id: str) -> str:
    """Derive the deterministic Docker container name for one Action Environment Binding."""
    namespace_hash = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
    sanitized_id = "".join(char if char.isalnum() or char in "_.-" else "-" for char in action_environment_id)
    return f"mini-mas-{namespace_hash}-{sanitized_id}"


@contextlib.contextmanager
def acquire_action_environment_lock(
    *,
    namespace: str,
    action_environment_id: str,
    lock_dir: Path = ACTION_ENVIRONMENT_LOCK_DIR,
) -> Iterator[None]:
    """Serialize ordinary bash actions for one Action Environment Binding."""
    key = (namespace, action_environment_id)
    try:
        process_lock = _process_lock(key)
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"{_lock_file_stem(namespace, action_environment_id)}.lock"
        with process_lock:
            with lock_path.open("a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise ActionEnvironmentUnavailableError(
            ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
            f"Could not acquire Action Environment Lock: {exc}",
            action_environment_id,
        ) from exc


def execute_action_from_environment_config(environment_config: Mapping[str, Any], action: dict) -> dict[str, Any]:
    """Execute one ordinary bash action through the default Action Environment Binding."""
    action_environment_id, binding = default_action_environment_binding(environment_config)
    namespace = action_environment_namespace()
    with acquire_action_environment_lock(namespace=namespace, action_environment_id=action_environment_id):
        if binding["kind"] == "local":
            return _execute_local(binding, action)
        if binding["kind"] == "docker":
            return _execute_docker(
                action_environment_id=action_environment_id,
                namespace=namespace,
                binding=binding,
                action=action,
            )
    raise ActionEnvironmentUnavailableError(
        ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
        f"Unsupported Action Environment Binding kind: {binding['kind']}",
        action_environment_id,
    )


def _process_lock(key: tuple[str, str]) -> threading.Lock:
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PROCESS_LOCKS[key] = lock
        return lock


def _lock_file_stem(namespace: str, action_environment_id: str) -> str:
    namespace_hash = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
    return f"{namespace_hash}-{action_environment_id}"


def _execute_local(binding: Mapping[str, Any], action: dict) -> dict[str, Any]:
    env = LocalEnvironment(
        cwd=str(binding.get("cwd") or ""),
        env=dict(binding.get("env") or {}),
        timeout=int(binding.get("timeout", 30)),
    )
    return env.execute(action)


def _execute_docker(
    *,
    action_environment_id: str,
    namespace: str,
    binding: Mapping[str, Any],
    action: dict,
) -> dict[str, Any]:
    executable = str(binding.get("executable") or os.getenv("MSWEA_DOCKER_EXECUTABLE", DEFAULT_DOCKER_EXECUTABLE))
    container_name = docker_container_name(namespace=namespace, action_environment_id=action_environment_id)
    container = _resolve_docker_container(
        executable=executable,
        container_name=container_name,
        namespace=namespace,
        action_environment_id=action_environment_id,
    )
    cmd = _docker_exec_command(
        executable=executable,
        container_name=container["name"],
        binding=binding,
        command=str(action.get("command", "")),
    )
    try:
        result = subprocess.run(
            cmd,
            text=True,
            timeout=int(binding.get("timeout", 30)),
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output = {"output": result.stdout, "returncode": result.returncode, "exception_info": ""}
    except Exception as exc:
        raw_output = getattr(exc, "output", None)
        raw_output = raw_output.decode("utf-8", errors="replace") if isinstance(raw_output, bytes) else (raw_output or "")
        output = {
            "output": raw_output,
            "returncode": -1,
            "exception_info": f"An error occurred while executing the command: {exc}",
            "extra": {"exception_type": type(exc).__name__, "exception": str(exc)},
        }
    _check_finished(output)
    return output


def _resolve_docker_container(
    *,
    executable: str,
    container_name: str,
    namespace: str,
    action_environment_id: str,
) -> dict[str, str]:
    inspect = _docker_inspect(executable=executable, container_name=container_name, action_environment_id=action_environment_id)
    state = inspect.get("State", {})
    if not state.get("Running"):
        raise ActionEnvironmentUnavailableError(
            ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
            f"Docker Action Environment container is not running: {container_name}",
            action_environment_id,
        )
    labels = inspect.get("Config", {}).get("Labels") or {}
    expected = {
        f"{MAS_DOCKER_LABEL_PREFIX}.namespace": namespace,
        f"{MAS_DOCKER_LABEL_PREFIX}.action_environment_id": action_environment_id,
    }
    mismatches = [key for key, value in expected.items() if labels.get(key) != value]
    if mismatches:
        raise ActionEnvironmentUnavailableError(
            ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
            f"Docker Action Environment labels do not match: {', '.join(mismatches)}",
            action_environment_id,
        )
    return {"name": container_name}


def _docker_inspect(*, executable: str, container_name: str, action_environment_id: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [executable, "inspect", container_name],
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        raise ActionEnvironmentUnavailableError(
            ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
            f"Could not inspect Docker Action Environment container: {exc}",
            action_environment_id,
        ) from exc
    if result.returncode != 0:
        raise ActionEnvironmentUnavailableError(
            ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
            f"Docker Action Environment container not found: {container_name}",
            action_environment_id,
        )
    import json

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ActionEnvironmentUnavailableError(
            ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
            f"Could not parse Docker inspect output for {container_name}: {exc}",
            action_environment_id,
        ) from exc
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ActionEnvironmentUnavailableError(
            ERROR_ACTION_ENVIRONMENT_UNAVAILABLE,
            f"Unexpected Docker inspect output for {container_name}",
            action_environment_id,
        )
    return payload[0]


def _docker_exec_command(
    *,
    executable: str,
    container_name: str,
    binding: Mapping[str, Any],
    command: str,
) -> list[str]:
    interpreter = _string_sequence(binding.get("interpreter"), default=DEFAULT_DOCKER_INTERPRETER)
    cmd = [executable, "exec", "-w", str(binding["cwd"])]
    for key, value in dict(binding.get("env") or {}).items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([container_name, *interpreter, command])
    return cmd


def _string_sequence(value: Any, *, default: Sequence[str]) -> list[str]:
    if value is None:
        return list(default)
    return [str(item) for item in value]


def _check_finished(output: dict[str, Any]) -> None:
    lines = output.get("output", "").lstrip().splitlines(keepends=True)
    if lines and lines[0].strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" and output["returncode"] == 0:
        submission = "".join(lines[1:])
        raise Submitted(
            {
                "role": "exit",
                "content": submission,
                "extra": {"exit_status": "Submitted", "submission": submission},
            }
        )
