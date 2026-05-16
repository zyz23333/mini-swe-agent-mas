import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def _docker_environment_config() -> dict:
    return {
        "default_action_environment_id": "programbench-cleanroom",
        "action_environments": {
            "programbench-cleanroom": {
                "kind": "docker",
                "scope": "shared",
                "image": "programbench/example:task_cleanroom",
                "cwd": "/workspace",
                "env": {"PAGER": "cat"},
                "timeout": 30,
                "interpreter": ["bash", "-lc"],
            }
        },
    }


def _inspect_payload(namespace: str, action_environment_id: str) -> str:
    return json.dumps(
        [
            {
                "State": {"Running": True},
                "Config": {
                    "Labels": {
                        "minisweagent.mas.namespace": namespace,
                        "minisweagent.mas.action_environment_id": action_environment_id,
                    }
                },
            }
        ]
    )


def test_action_environment_lock_serializes_same_binding_and_allows_different_bindings(tmp_path):
    from minisweagent.mas.action_environment import acquire_action_environment_lock

    lock_dir = tmp_path / "locks"
    events = []
    first_entered = threading.Event()
    release_first = threading.Event()

    def hold_first_binding():
        with acquire_action_environment_lock(namespace="workspace", action_environment_id="same", lock_dir=lock_dir):
            events.append("same-1-enter")
            first_entered.set()
            release_first.wait(timeout=5)
            events.append("same-1-exit")

    def wait_same_binding():
        first_entered.wait(timeout=5)
        with acquire_action_environment_lock(namespace="workspace", action_environment_id="same", lock_dir=lock_dir):
            events.append("same-2-enter")

    def enter_different_binding():
        first_entered.wait(timeout=5)
        with acquire_action_environment_lock(namespace="workspace", action_environment_id="other", lock_dir=lock_dir):
            events.append("other-enter")

    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(hold_first_binding)
        same = executor.submit(wait_same_binding)
        other = executor.submit(enter_different_binding)
        first_entered.wait(timeout=5)
        time.sleep(0.05)
        release_first.set()
        first.result(timeout=5)
        same.result(timeout=5)
        other.result(timeout=5)

    assert events.index("other-enter") < events.index("same-1-exit")
    assert events.index("same-1-exit") < events.index("same-2-enter")
    assert list(lock_dir.iterdir())


def test_docker_action_environment_executes_against_resolved_container(monkeypatch, tmp_path):
    from minisweagent.mas import action_environment
    from minisweagent.mas.action_environment import execute_action_from_environment_config

    monkeypatch.chdir(tmp_path)
    namespace = Path.cwd().resolve().as_posix()
    container_name = action_environment.docker_container_name(
        namespace=namespace,
        action_environment_id="programbench-cleanroom",
    )
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=_inspect_payload(namespace, "programbench-cleanroom"))
        if cmd[:2] == ["docker", "exec"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="hello\n")
        raise AssertionError(f"unexpected docker command: {cmd}")

    monkeypatch.setattr(action_environment.subprocess, "run", run)

    result = execute_action_from_environment_config(_docker_environment_config(), {"command": "echo hello"})

    assert result == {"output": "hello\n", "returncode": 0, "exception_info": ""}
    assert calls == [
        ["docker", "inspect", container_name],
        [
            "docker",
            "exec",
            "-w",
            "/workspace",
            "-e",
            "PAGER=cat",
            container_name,
            "bash",
            "-lc",
            "echo hello",
        ],
    ]
    assert all("run" not in call for call in calls)


def test_missing_docker_action_environment_raises_unavailable(monkeypatch, tmp_path):
    from minisweagent.mas import action_environment
    from minisweagent.mas.action_environment import (
        ActionEnvironmentUnavailableError,
        execute_action_from_environment_config,
    )

    monkeypatch.chdir(tmp_path)

    def run(cmd, **_kwargs):
        if cmd[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="not found\n")
        raise AssertionError(f"unexpected docker command: {cmd}")

    monkeypatch.setattr(action_environment.subprocess, "run", run)

    with pytest.raises(ActionEnvironmentUnavailableError) as exc_info:
        execute_action_from_environment_config(_docker_environment_config(), {"command": "echo hello"})

    assert exc_info.value.code == "action_environment_unavailable"
    assert exc_info.value.action_environment_id == "programbench-cleanroom"
