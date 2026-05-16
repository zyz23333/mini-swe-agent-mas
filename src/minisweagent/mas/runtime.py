"""Runtime wiring for the DBOS-backed MAS command path."""

from __future__ import annotations

import asyncio
import os
import secrets
import shlex
import threading
import time
import weakref
from collections.abc import Awaitable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from minisweagent.mas.artifacts import make_agent_id, make_artifact_metadata, validate_agent_id
from minisweagent.mas.queues import AI_AGENT_WORKFLOW_QUEUE_NAME, INTERACTIVE_WORKFLOW_QUEUE_NAME
from minisweagent.mas.signals import (
    ROOT_COMMAND_TOPIC,
    make_root_command_signal,
    root_command_result_event_key,
)
from minisweagent.mas.status_events import STATUS_EVENT_KEY, normalize_agent_snapshot

MAS_APP_NAME = "mini-swe-agent-mas"
MAS_RUNTIME_STATE_STORE_PATH = Path(".mini-mas") / "runtime" / "mini_mas_dbos.sqlite"
MAS_RUNTIME_STATE_STORE_ENV = "MINI_MAS_RUNTIME_STATE_STORE"
ATTACHMENT_LEASE_TOKEN_PREFIX = "att-"
ATTACHMENT_LEASE_DEFAULT_TTL_SECONDS = 300.0
_DECLARED_DBOS_QUEUE_POLICIES: weakref.WeakKeyDictionary[Any, tuple[str, ...]] = weakref.WeakKeyDictionary()
_SYNC_ASYNC_LOOP_LOCK = threading.Lock()
_SYNC_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None


class MasRuntimeProfile(str, Enum):
    """Process-level MAS runtime activation profiles."""

    INTERACTIVE_ONLY = "interactive_only"
    SUPERVISED_INTERACTIVE_AND_AI = "supervised_interactive_and_ai"


def load_dbos():
    """Import DBOS only inside the MAS path."""
    import dbos

    return dbos


def _run_mas_async(awaitable: Awaitable[Any]) -> Any:
    """Run a MAS async runtime operation without shutting down DBOS' default executor."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        msg = "MAS synchronous runtime APIs cannot be called from a running asyncio event loop"
        raise RuntimeError(msg)

    global _SYNC_ASYNC_LOOP
    with _SYNC_ASYNC_LOOP_LOCK:
        if _SYNC_ASYNC_LOOP is None or _SYNC_ASYNC_LOOP.is_closed():
            _SYNC_ASYNC_LOOP = asyncio.new_event_loop()
        return _SYNC_ASYNC_LOOP.run_until_complete(awaitable)


class RuntimeControlPlane:
    """Read MAS runtime metadata without launching a DBOS executor."""

    def __init__(self, dbos_module: Any):
        self._client = dbos_module.DBOSClient(system_database_url=make_dbos_config()["system_database_url"])

    async def list_interactive_root_workflows(self) -> list[Any]:
        return await self._client.list_workflows_async(
            name="interactive_root_agent_workflow",
            has_parent=False,
            load_input=False,
            load_output=False,
        )

    async def get_workflow_status(self, workflow_id: str) -> Any | None:
        workflow_statuses = await self._client.list_workflows_async(
            workflow_ids=[workflow_id],
            load_input=False,
            load_output=False,
        )
        return workflow_statuses[0] if workflow_statuses else None

    async def get_event(self, workflow_id: str, key: str, timeout_seconds: float) -> Any:
        return await self._client.get_event_async(workflow_id, key, timeout_seconds)

    def close(self) -> None:
        destroy = getattr(self._client, "destroy", None)
        if destroy is not None:
            destroy()


def open_runtime_control_plane() -> RuntimeControlPlane:
    return RuntimeControlPlane(load_dbos())


def get_mas_runtime_state_store_path() -> Path:
    """Return the configured DBOS state store path for this runtime process."""
    override = os.environ.get(MAS_RUNTIME_STATE_STORE_ENV)
    return Path(override) if override else MAS_RUNTIME_STATE_STORE_PATH


def make_dbos_config() -> dict[str, str]:
    """Build the minimal DBOS configuration for the external MAS CLI."""
    runtime_state_store_path = get_mas_runtime_state_store_path()
    runtime_state_store_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "name": MAS_APP_NAME,
        "system_database_url": f"sqlite:///{runtime_state_store_path.as_posix()}",
    }


def _declare_dbos_queue_policy(dbos_module: Any, queue_names: list[str]) -> tuple[str, ...]:
    dbos_instance = dbos_module.DBOS(config=make_dbos_config())
    queue_policy = tuple(queue_names)
    declared_policy = _DECLARED_DBOS_QUEUE_POLICIES.get(dbos_instance)
    if declared_policy is None:
        dbos_module.DBOS.listen_queues(list(queue_policy))
        _DECLARED_DBOS_QUEUE_POLICIES[dbos_instance] = queue_policy
    elif declared_policy != queue_policy:
        msg = "DBOS runtime is already configured for a non-interactive MAS queue policy"
        raise RuntimeError(msg)
    return queue_policy


def _queue_policy_for_runtime_profile(profile: MasRuntimeProfile) -> list[str]:
    """Map a named runtime authorization profile to concrete DBOS queues."""
    profile = MasRuntimeProfile(profile)
    if profile is MasRuntimeProfile.INTERACTIVE_ONLY:
        return [INTERACTIVE_WORKFLOW_QUEUE_NAME]
    if profile is MasRuntimeProfile.SUPERVISED_INTERACTIVE_AND_AI:
        return [INTERACTIVE_WORKFLOW_QUEUE_NAME, AI_AGENT_WORKFLOW_QUEUE_NAME]
    msg = f"Unsupported MAS runtime profile: {profile}"
    raise ValueError(msg)


def launch_dbos_with_queue_policy(dbos_module: Any, queue_names: list[str]) -> None:
    """Launch DBOS after applying the MAS queue-listening policy once per DBOS instance."""
    queue_policy = _declare_dbos_queue_policy(dbos_module, queue_names)
    dbos_module.DBOS.launch()
    for queue_name in queue_policy:
        dbos_module.DBOS.register_queue(queue_name)


def launch_interactive_runtime(dbos_module: Any) -> None:
    """Launch DBOS for ordinary mini-mas work with interactive-only queue authorization."""
    launch_dbos_with_queue_policy(dbos_module, [INTERACTIVE_WORKFLOW_QUEUE_NAME])


def launch_ai_agent_runtime(dbos_module: Any) -> None:
    """Launch DBOS for explicit AI Agent Execution with AI-agent-only queue authorization."""
    launch_dbos_with_queue_policy(dbos_module, [AI_AGENT_WORKFLOW_QUEUE_NAME])


def register_mas_agent_workflows() -> None:
    """Import MAS Agent workflow definitions so DBOS can run queued Agent work."""
    from minisweagent.mas import mas_agent as _mas_agent  # noqa: F401


class MasRuntimeSession:
    """Own one activated External MAS CLI runtime lifecycle."""

    def __init__(
        self,
        dbos_module: Any | None = None,
        *,
        profile: MasRuntimeProfile = MasRuntimeProfile.INTERACTIVE_ONLY,
    ):
        self._dbos_module = dbos_module or load_dbos()
        self._runtime_profile = MasRuntimeProfile(profile)
        self._queue_names = _queue_policy_for_runtime_profile(self._runtime_profile)
        self._launched = False

    async def __aenter__(self) -> MasRuntimeSession:
        await self.activate_interactive_runtime()
        return self

    async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        return None

    async def activate_interactive_runtime(self) -> None:
        """Launch DBOS once for this session's runtime authorization profile."""
        if self._launched:
            return
        register_mas_agent_workflows()
        await launch_dbos_with_queue_policy_async(self._dbos_module, self._queue_names)
        self._launched = True

    async def start_interactive_root_agent_workflow(
        self,
        *,
        workflow_id: str | None = None,
        agent_execution_config: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Start an Interactive Root Agent inside this runtime session."""
        from minisweagent.mas.mas_agent import interactive_root_agent_workflow

        await self.activate_interactive_runtime()

        assigned_workflow_id = validate_agent_id(workflow_id or make_agent_id())
        with self._dbos_module.SetWorkflowID(assigned_workflow_id):
            handle = await self._dbos_module.DBOS.enqueue_workflow_async(
                INTERACTIVE_WORKFLOW_QUEUE_NAME,
                interactive_root_agent_workflow,
                assigned_workflow_id,
                max_commands=None,
                agent_execution_config=dict(agent_execution_config) if agent_execution_config is not None else None,
            )

        started_workflow_id = _handle_workflow_id(handle)
        result = await self._dbos_module.DBOS.get_event_async(started_workflow_id, STATUS_EVENT_KEY, 60)
        return _format_interactive_root_result(agent_id=started_workflow_id, result=result)

    async def send_root_command(
        self,
        *,
        root_agent_id: str,
        command: str,
        command_id: str | None = None,
        result_timeout_seconds: float = 60,
        attachment_token: str | None = None,
    ) -> Mapping[str, Any]:
        """Submit one Root Command Signal and wait for its scoped result in this session."""
        await self.activate_interactive_runtime()

        root_agent_id = validate_agent_id(root_agent_id)
        command_id = command_id or make_command_id()
        claimed_token: str | None = None
        if attachment_token is None:
            snapshot = await self._dbos_module.DBOS.get_event_async(root_agent_id, STATUS_EVENT_KEY, 1)
            if not isinstance(snapshot, Mapping):
                return _attachment_unavailable_result(
                    root_agent_id=root_agent_id,
                    command=command,
                    lifecycle_state="unknown",
                    command_id=command_id,
                )
            lifecycle_state = str(normalize_agent_snapshot(dict(snapshot))["lifecycle_state"])
            if lifecycle_state != "waiting_for_command":
                return _attachment_unavailable_result(
                    root_agent_id=root_agent_id,
                    command=command,
                    lifecycle_state=lifecycle_state,
                    command_id=command_id,
                )
            lease = claim_root_attachment(
                root_agent_id=root_agent_id,
                ttl_seconds=max(result_timeout_seconds, 0.0) + ATTACHMENT_LEASE_DEFAULT_TTL_SECONDS,
            )
            if not lease["claimed"]:
                return _attachment_unavailable_result(
                    root_agent_id=root_agent_id,
                    command=command,
                    lifecycle_state=lifecycle_state,
                    command_id=command_id,
                )
            claimed_token = str(lease["attachment_token"])
        elif not _attachment_token_is_active(root_agent_id=root_agent_id, attachment_token=attachment_token):
            return _attachment_unavailable_result(
                root_agent_id=root_agent_id,
                command=command,
                lifecycle_state="unknown",
                command_id=command_id,
            )

        release_claimed_token = False
        try:
            signal = make_root_command_signal(
                command_id=command_id,
                root_agent_id=root_agent_id,
                command=command,
                source="external_cli",
            )
            await self._dbos_module.DBOS.send_async(root_agent_id, signal, ROOT_COMMAND_TOPIC)
            event = await self._dbos_module.DBOS.get_event_async(
                root_agent_id,
                root_command_result_event_key(command_id),
                result_timeout_seconds,
            )
            if not isinstance(event, Mapping):
                return {
                    "kind": "root_command_result_timeout",
                    "command_id": command_id,
                    "root_agent_id": root_agent_id,
                    "command": command,
                    "result": {
                        "output": _root_command_result_timeout_output(root_agent_id),
                        "returncode": 1,
                        "exception_info": "root_command_result_timeout",
                        "extra": {"mas_command_error": "root_command_result_timeout"},
                    },
                }
            release_claimed_token = True
            return event
        finally:
            if claimed_token is not None and release_claimed_token:
                release_root_attachment(root_agent_id=root_agent_id, attachment_token=claimed_token)

    async def prepare_resume_root_agent(
        self,
        *,
        root_agent_id: str,
    ) -> Mapping[str, Any]:
        """Validate and claim an Interactive Root Agent attachment for this session."""
        return await _prepare_resume_root_agent_async(root_agent_id=root_agent_id)

    async def one_shot_spawn_through_interactive_root(
        self,
        *,
        spawn_arguments: list[str],
        result_timeout_seconds: float = 60,
    ) -> Mapping[str, Any]:
        """Create an Interactive Root Agent and submit external spawn in this session."""
        root_result = await self.start_interactive_root_agent_workflow()
        root_agent_id = str(root_result["agent_id"])
        command = make_standalone_spawn_command(spawn_arguments)
        result_event = await self.send_root_command(
            root_agent_id=root_agent_id,
            command=command,
            result_timeout_seconds=result_timeout_seconds,
        )
        if result_event.get("kind") == "root_command_result_timeout":
            return _format_one_shot_spawn_result_timeout(
                root_agent_id=root_agent_id,
                command=command,
                result_event=result_event,
            )
        return {
            "kind": "one_shot_spawn",
            "root_agent_id": root_agent_id,
            "command": command,
            "result": result_event["result"],
            "returncode": result_event["result"].get("returncode", 0),
        }


async def launch_dbos_with_queue_policy_async(dbos_module: Any, queue_names: list[str]) -> None:
    """Async variant for MAS runtime paths already running on an event loop."""
    queue_policy = _declare_dbos_queue_policy(dbos_module, queue_names)
    dbos_module.DBOS.launch()
    for queue_name in queue_policy:
        await dbos_module.DBOS.register_queue_async(queue_name)


async def launch_interactive_runtime_async(dbos_module: Any) -> None:
    """Launch DBOS for ordinary async mini-mas work with interactive-only queue authorization."""
    await launch_dbos_with_queue_policy_async(dbos_module, [INTERACTIVE_WORKFLOW_QUEUE_NAME])


def activate_ai_agent_execution(
    *,
    stop_event: threading.Event | None = None,
    wait_interval_seconds: float = 1.0,
) -> Mapping[str, Any]:
    """Activate foreground AI Agent Execution until interrupted or stopped by the caller."""
    dbos_module = load_dbos()
    register_mas_agent_workflows()
    launch_ai_agent_runtime(dbos_module)

    stop_event = stop_event or threading.Event()
    try:
        while not stop_event.wait(wait_interval_seconds):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        dbos_module.DBOS.destroy(workflow_completion_timeout_sec=0)
    return {
        "kind": "ai_agent_execution_deactivated",
        "queue_name": AI_AGENT_WORKFLOW_QUEUE_NAME,
    }


def _handle_workflow_id(handle: Any) -> str:
    if hasattr(handle, "get_workflow_id"):
        return str(handle.get_workflow_id())
    return str(handle.workflow_id)


def make_command_id() -> str:
    """Generate an opaque Root command ID."""
    return f"cmd-{secrets.token_hex(8)}"


def make_attachment_token() -> str:
    """Generate an opaque Root attachment token."""
    return f"{ATTACHMENT_LEASE_TOKEN_PREFIX}{secrets.token_hex(8)}"


def _attachment_lease_directory() -> Path:
    configured = os.environ.get("MINI_MAS_ATTACHMENT_LEASE_DIR")
    if configured:
        return Path(configured)
    return Path(".mini-mas") / "attachments"


def _attachment_lease_path(root_agent_id: str) -> Path:
    return _attachment_lease_directory() / f"{root_agent_id}.lease"


def _parse_attachment_lease(raw: str) -> dict[str, Any]:
    token, expires_at = raw.strip().split("\n", 1)
    return {"token": token, "expires_at": float(expires_at)}


def _read_attachment_lease(path: Path) -> dict[str, Any] | None:
    try:
        return _parse_attachment_lease(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"token": "", "expires_at": float("inf")}


def _try_remove_stale_attachment_lease(path: Path, *, now: float) -> None:
    lease = _read_attachment_lease(path)
    if lease is None or lease["expires_at"] > now:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


def claim_root_attachment(
    *,
    root_agent_id: str,
    ttl_seconds: float = ATTACHMENT_LEASE_DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> dict[str, Any]:
    """Claim the single external attachment slot for one Interactive Root Agent."""
    root_agent_id = validate_agent_id(root_agent_id)
    now = time.monotonic() if now is None else now
    lease_path = _attachment_lease_path(root_agent_id)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    _try_remove_stale_attachment_lease(lease_path, now=now)

    token = make_attachment_token()
    expires_at = now + ttl_seconds
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(lease_path, flags, 0o600)
    except FileExistsError:
        return {
            "claimed": False,
            "root_agent_id": root_agent_id,
            "lease_path": str(lease_path),
        }
    with os.fdopen(fd, "w", encoding="utf-8") as lease_file:
        lease_file.write(f"{token}\n{expires_at}\n")
    return {
        "claimed": True,
        "root_agent_id": root_agent_id,
        "attachment_token": token,
        "expires_at": expires_at,
        "lease_path": str(lease_path),
    }


def release_root_attachment(*, root_agent_id: str, attachment_token: str | None) -> bool:
    """Release a Root attachment only when the caller still owns the lease token."""
    if not attachment_token:
        return False
    root_agent_id = validate_agent_id(root_agent_id)
    lease_path = _attachment_lease_path(root_agent_id)
    lease = _read_attachment_lease(lease_path)
    if lease is None or lease["token"] != attachment_token:
        return False
    try:
        lease_path.unlink()
    except FileNotFoundError:
        return False
    return True


def refresh_root_attachment(
    *,
    root_agent_id: str,
    attachment_token: str | None,
    ttl_seconds: float = ATTACHMENT_LEASE_DEFAULT_TTL_SECONDS,
) -> bool:
    """Extend a Root attachment lease while the caller still owns its token."""
    if not attachment_token:
        return False
    root_agent_id = validate_agent_id(root_agent_id)
    lease_path = _attachment_lease_path(root_agent_id)
    lease = _read_attachment_lease(lease_path)
    if lease is None or lease["token"] != attachment_token:
        return False
    expires_at = time.monotonic() + ttl_seconds
    try:
        lease_path.write_text(f"{attachment_token}\n{expires_at}\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _attachment_token_is_active(*, root_agent_id: str, attachment_token: str | None) -> bool:
    if not attachment_token:
        return False
    root_agent_id = validate_agent_id(root_agent_id)
    lease = _read_attachment_lease(_attachment_lease_path(root_agent_id))
    return lease is not None and lease["token"] == attachment_token and lease["expires_at"] > time.monotonic()


def _attachment_unavailable_result(
    *,
    root_agent_id: str,
    command: str | None = None,
    lifecycle_state: str | None = None,
    command_id: str | None = None,
) -> dict[str, Any]:
    output_lines = [
        "Root Agent attachment is already active or unavailable.",
        f"root_agent_id: {root_agent_id}",
    ]
    if lifecycle_state:
        output_lines.append(f"lifecycle_state: {lifecycle_state}")
    output_lines.append(
        f"Use mini-mas status to inspect Root Agents, then retry mini-mas resume {root_agent_id} later."
    )
    command_result = {
        "output": "\n".join(output_lines) + "\n",
        "returncode": 2,
        "exception_info": "root_attachment_unavailable",
        "extra": {"mas_command_error": "root_attachment_unavailable"},
    }
    result: dict[str, Any] = {
        "kind": "root_command_attachment_unavailable",
        "root_agent_id": root_agent_id,
        "result": command_result,
    }
    if command is not None:
        result["command"] = command
    if command_id is not None:
        result["command_id"] = command_id
    return result


def _root_command_result_timeout_output(root_agent_id: str) -> str:
    return (
        "Timed out waiting for Root Command Result. The command may still be running.\n"
        f"root_agent_id: {root_agent_id}\n"
        "Use mini-mas status to inspect Root Agents, then retry "
        f"mini-mas resume {root_agent_id} later.\n"
    )


def _format_interactive_root_result(*, agent_id: str, result: Mapping[str, Any] | None) -> dict[str, str]:
    data: dict[str, Any] = make_artifact_metadata(agent_id=agent_id)
    if result is not None and result.get("lifecycle_state"):
        data["lifecycle_state"] = result["lifecycle_state"]
    return data


async def _start_interactive_root_agent_workflow_async(
    *,
    workflow_id: str | None = None,
    agent_execution_config: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Async compatibility wrapper for starting an Interactive Root Agent."""
    async with MasRuntimeSession() as session:
        return await session.start_interactive_root_agent_workflow(
            workflow_id=workflow_id,
            agent_execution_config=agent_execution_config,
        )


def start_interactive_root_agent_workflow(
    *,
    workflow_id: str | None = None,
    agent_execution_config: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS and start the minimal Interactive Root Agent path."""
    return _run_mas_async(
        _start_interactive_root_agent_workflow_async(
            workflow_id=workflow_id,
            agent_execution_config=agent_execution_config,
        )
    )


async def _send_root_command_async(
    *,
    root_agent_id: str,
    command: str,
    command_id: str | None = None,
    result_timeout_seconds: float = 60,
    attachment_token: str | None = None,
) -> Mapping[str, Any]:
    """Async compatibility wrapper for submitting one Root Command Signal."""
    async with MasRuntimeSession() as session:
        return await session.send_root_command(
            root_agent_id=root_agent_id,
            command=command,
            command_id=command_id,
            result_timeout_seconds=result_timeout_seconds,
            attachment_token=attachment_token,
        )


def send_root_command(
    *,
    root_agent_id: str,
    command: str,
    command_id: str | None = None,
    result_timeout_seconds: float = 60,
    attachment_token: str | None = None,
) -> Mapping[str, Any]:
    """Initialize DBOS, send one Root command, and wait on the command-id-scoped result event."""
    return _run_mas_async(
        _send_root_command_async(
            root_agent_id=root_agent_id,
            command=command,
            command_id=command_id,
            result_timeout_seconds=result_timeout_seconds,
            attachment_token=attachment_token,
        )
    )


def make_standalone_spawn_command(spawn_arguments: list[str]) -> str:
    """Preserve an external spawn invocation as one standalone MAS command."""
    return " ".join(["mini-mas", "spawn", *(shlex.quote(argument) for argument in spawn_arguments)])


def _format_one_shot_spawn_result_timeout(
    *,
    root_agent_id: str,
    command: str,
    result_event: Mapping[str, Any],
) -> dict[str, Any]:
    command_result = result_event["result"]
    return {
        "kind": "one_shot_spawn_result_timeout",
        "root_agent_id": root_agent_id,
        "command": command,
        "output": (
            "Timed out waiting for Root Command Result. The spawn command may still be running.\n"
            f"root_agent_id: {root_agent_id}\n"
            "Use mini-mas status to inspect Root Agents, then resume this Root Agent with "
            f"mini-mas resume {root_agent_id}.\n"
        ),
        "returncode": command_result.get("returncode", 1),
        "exception_info": command_result.get("exception_info", "root_command_result_timeout"),
        "extra": command_result.get("extra", {"mas_command_error": "root_command_result_timeout"}),
        "result": command_result,
    }


def one_shot_spawn_through_interactive_root(
    *,
    spawn_arguments: list[str],
    result_timeout_seconds: float = 60,
) -> Mapping[str, Any]:
    """Compatibility wrapper for one-shot External MAS CLI spawn."""

    async def run_session() -> Mapping[str, Any]:
        async with MasRuntimeSession() as session:
            return await session.one_shot_spawn_through_interactive_root(
                spawn_arguments=spawn_arguments,
                result_timeout_seconds=result_timeout_seconds,
            )

    return _run_mas_async(run_session())


def _resume_invalid_agent_id_result(*, root_agent_id: str, error: ValueError) -> dict[str, Any]:
    return {
        "kind": "resume_unavailable",
        "root_agent_id": root_agent_id,
        "output": f"Invalid Agent ID for resume: {root_agent_id}\n{error}\n",
        "returncode": 2,
        "exception_info": "invalid_agent_id",
        "extra": {"mas_command_error": "invalid_agent_id"},
    }


def _resume_unavailable_result(
    *,
    root_agent_id: str,
    output: str,
    exception_info: str,
    lifecycle_state: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "resume_unavailable",
        "root_agent_id": root_agent_id,
        "output": output,
        "returncode": 2,
        "exception_info": exception_info,
        "extra": {"mas_command_error": exception_info},
    }
    if lifecycle_state:
        result["lifecycle_state"] = lifecycle_state
    return result


def _resume_unavailable_lifecycle_result(*, root_agent_id: str, lifecycle_state: str) -> dict[str, Any]:
    return _resume_unavailable_result(
        root_agent_id=root_agent_id,
        lifecycle_state=lifecycle_state,
        exception_info="root_agent_not_waiting_for_command",
        output=(
            "Root Agent is not available for resume.\n"
            f"root_agent_id: {root_agent_id}\n"
            f"lifecycle_state: {lifecycle_state}\n"
            "Use mini-mas status to inspect Root Agents, then retry "
            f"mini-mas resume {root_agent_id} later when it is waiting_for_command.\n"
        ),
    )


def _resume_retry_guidance(root_agent_id: str) -> str:
    return f"Use mini-mas status to inspect Root Agents, then retry mini-mas resume {root_agent_id} later.\n"


def _is_interactive_root_workflow(workflow_status: Any) -> bool:
    return getattr(workflow_status, "name", "") == "interactive_root_agent_workflow"


def _parent_workflow_id(workflow_status: Any) -> str | None:
    parent_workflow_id = getattr(workflow_status, "parent_workflow_id", None)
    return str(parent_workflow_id) if parent_workflow_id else None


def _root_discovery_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    metadata = normalize_agent_snapshot(dict(snapshot))
    return {
        "agent_id": metadata["agent_id"],
        "lifecycle_state": metadata["lifecycle_state"],
        "agent_artifact_directory": metadata["agent_artifact_directory"],
        "trajectory_artifact_path": metadata["trajectory_artifact_path"],
    }


def _format_root_discovery(snapshots: list[Mapping[str, Any]]) -> str:
    lines = ["Interactive Root Agents"]
    if not snapshots:
        lines.append("No Interactive Root Agents found.")
        return "\n".join(lines) + "\n"

    for index, snapshot in enumerate(snapshots):
        if index:
            lines.append("")
        lines.extend(
            [
                f"agent_id: {snapshot['agent_id']}",
                f"lifecycle_state: {snapshot['lifecycle_state']}",
                f"agent_artifact_directory: {snapshot['agent_artifact_directory']}",
                f"trajectory_artifact_path: {snapshot['trajectory_artifact_path']}",
            ]
        )
    return "\n".join(lines) + "\n"


async def _discover_interactive_root_agents_async() -> Mapping[str, Any]:
    """Async implementation for external Interactive Root Agent discovery."""
    control_plane = open_runtime_control_plane()
    try:
        workflow_statuses = await control_plane.list_interactive_root_workflows()

        snapshots: list[dict[str, Any]] = []
        for workflow_status in workflow_statuses:
            if _parent_workflow_id(workflow_status) is not None or not _is_interactive_root_workflow(workflow_status):
                continue
            workflow_id = validate_agent_id(str(getattr(workflow_status, "workflow_id", "")))
            snapshot = await control_plane.get_event(workflow_id, STATUS_EVENT_KEY, 1)
            if not isinstance(snapshot, Mapping):
                msg = f"Missing lifecycle status event for Interactive Root Agent: {workflow_id}"
                raise RuntimeError(msg)
            snapshots.append(_root_discovery_snapshot(snapshot))
    finally:
        control_plane.close()

    snapshots = sorted(snapshots, key=lambda snapshot: snapshot["agent_id"])
    return {
        "kind": "interactive_root_discovery",
        "roots": snapshots,
        "output": _format_root_discovery(snapshots),
        "returncode": 0,
    }


async def discover_interactive_root_agents_async() -> Mapping[str, Any]:
    """List parentless Interactive Root Agent workflows through the control plane."""
    return await _discover_interactive_root_agents_async()


def discover_interactive_root_agents() -> Mapping[str, Any]:
    """List parentless Interactive Root Agent workflows through the control plane."""
    return _run_mas_async(_discover_interactive_root_agents_async())


async def _prepare_resume_root_agent_async(
    *,
    root_agent_id: str,
) -> Mapping[str, Any]:
    """Async implementation for validating an Interactive Root Agent before resume."""
    try:
        root_agent_id = validate_agent_id(root_agent_id)
    except ValueError as exc:
        return _resume_invalid_agent_id_result(root_agent_id=root_agent_id, error=exc)

    workflow_status = None
    control_plane = open_runtime_control_plane()
    try:
        workflow_status = await control_plane.get_workflow_status(root_agent_id)
    finally:
        if workflow_status is None:
            control_plane.close()
    if workflow_status is None:
        return _resume_unavailable_result(
            root_agent_id=root_agent_id,
            lifecycle_state="unknown",
            exception_info="unknown_root_agent_id",
            output=(
                f"Unknown Root Agent ID: {root_agent_id}\n"
                f"root_agent_id: {root_agent_id}\n"
                "lifecycle_state: unknown\n"
                f"{_resume_retry_guidance(root_agent_id)}"
            ),
        )

    parent_workflow_id = _parent_workflow_id(workflow_status)
    if parent_workflow_id is not None:
        control_plane.close()
        return _resume_unavailable_result(
            root_agent_id=root_agent_id,
            lifecycle_state="unknown",
            exception_info="not_parentless_interactive_root_agent",
            output=(
                "Resume target is not a parentless Interactive Root Agent.\n"
                f"target_agent_id: {root_agent_id}\n"
                "lifecycle_state: unknown\n"
                f"parent_agent_id: {parent_workflow_id}\n"
                "Use mini-mas status to inspect Root Agents, then resume a listed Root Agent ID.\n"
            ),
        )

    if not _is_interactive_root_workflow(workflow_status):
        control_plane.close()
        return _resume_unavailable_result(
            root_agent_id=root_agent_id,
            lifecycle_state="unknown",
            exception_info="not_interactive_root_agent",
            output=(
                "Resume target is not an Interactive Root Agent workflow.\n"
                f"root_agent_id: {root_agent_id}\n"
                "lifecycle_state: unknown\n"
                f"workflow_name: {getattr(workflow_status, 'name', '')}\n"
                f"{_resume_retry_guidance(root_agent_id)}"
            ),
        )

    try:
        snapshot = await control_plane.get_event(root_agent_id, STATUS_EVENT_KEY, 1)
    finally:
        control_plane.close()
    if not isinstance(snapshot, Mapping):
        return _resume_unavailable_lifecycle_result(root_agent_id=root_agent_id, lifecycle_state="unknown")

    metadata = normalize_agent_snapshot(dict(snapshot))
    lifecycle_state = str(metadata["lifecycle_state"])
    if lifecycle_state != "waiting_for_command":
        return _resume_unavailable_lifecycle_result(root_agent_id=root_agent_id, lifecycle_state=lifecycle_state)

    lease = claim_root_attachment(root_agent_id=root_agent_id)
    if not lease["claimed"]:
        return _resume_unavailable_result(
            root_agent_id=root_agent_id,
            lifecycle_state=lifecycle_state,
            exception_info="root_attachment_unavailable",
            output=(
                "Root Agent attachment is already active or unavailable.\n"
                f"root_agent_id: {root_agent_id}\n"
                f"lifecycle_state: {lifecycle_state}\n"
                "Use mini-mas status to inspect Root Agents, then retry "
                f"mini-mas resume {root_agent_id} later.\n"
            ),
        )

    return {
        "kind": "resume_ready",
        "root_agent_id": root_agent_id,
        "attachment_token": lease["attachment_token"],
        **metadata,
        "returncode": 0,
    }


def prepare_resume_root_agent(
    *,
    root_agent_id: str,
) -> Mapping[str, Any]:
    """Validate an Interactive Root Agent before the resume terminal attaches."""
    return _run_mas_async(
        _prepare_resume_root_agent_async(
            root_agent_id=root_agent_id,
        )
    )
