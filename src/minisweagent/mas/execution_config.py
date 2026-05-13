"""Agent Execution Config construction and validation for MAS."""

from __future__ import annotations

import copy
import os
import platform
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.utils.serialize import UNSET, recursive_merge

AGENT_EXECUTION_CONFIG_SCHEMA_VERSION = 1
REDACTED_ENV_VALUE = "<redacted>"

ERROR_MISSING_AGENT_EXECUTION_CONFIG = "missing_agent_execution_config"
ERROR_UNSUPPORTED_AGENT_EXECUTION_CONFIG_VERSION = "unsupported_agent_execution_config_version"
ERROR_INVALID_AGENT_EXECUTION_CONFIG = "invalid_agent_execution_config"
ERROR_UNSUPPORTED_AGENT_ENVIRONMENT = "unsupported_agent_environment"
ERROR_UNSUPPORTED_AGENT_ENVIRONMENT_CWD_OVERRIDE = "unsupported_agent_environment_cwd_override"
ERROR_AGENT_EXECUTION_CONFIG_SECRET_KEY = "agent_execution_config_secret_key"
ERROR_MISSING_MODEL_PROVIDER_CREDENTIAL = "missing_model_provider_credential"
ERROR_AGENT_EXECUTION_CONFIG_RESOLUTION_FAILED = "agent_execution_config_resolution_failed"
ERROR_AGENT_EXECUTION_RUNTIME_FAILED = "agent_execution_runtime_failed"

_EXCLUDED_AGENT_FIELDS = frozenset({"agent_class", "mode", "confirm_exit", "whitelist_actions", "output_path"})
_EXCLUDED_TOP_LEVEL_FIELDS = frozenset({"run"})
_SECRET_TOKENS = frozenset({"key", "token", "secret", "password", "credential", "authorization"})
_SECRET_COMPOUND_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "bearer_token",
        "auth_token",
        "client_secret",
        "private_key",
    }
)
_ENV_SECRET_RE = re.compile(r"(^AUTHORIZATION$|.*_(API_KEY|TOKEN|SECRET|PASSWORD)$)")
_LOCAL_ENVIRONMENT_CLASSES = frozenset(
    {
        "",
        "local",
        "minisweagent.environments.local.LocalEnvironment",
    }
)


@dataclass
class AgentExecutionConfigError(Exception):
    """Structured Agent Execution Config failure."""

    code: str
    message: str
    path: str = ""

    def __str__(self) -> str:
        if self.path:
            return f"{self.message} ({self.path})"
        return self.message


@dataclass(frozen=True)
class AgentExecutionConfigBuildRequest:
    """Inputs used to build one Child Agent Execution Config."""

    shared_workspace: Path
    config_specs: Sequence[str] = ()
    model_name: str | None = None
    base_agent_execution_config: Mapping[str, Any] | None = None


def default_mini_config_spec() -> str:
    """Return the mini-compatible default config spec for Spawn-time config building."""
    return str(Path(os.getenv("MSWEA_MINI_CONFIG_PATH", builtin_config_dir / "mini.yaml")))


def build_agent_execution_config(request: AgentExecutionConfigBuildRequest) -> dict[str, Any]:
    """Build, normalize, and validate a Child Agent Execution Config."""
    shared_workspace = request.shared_workspace.resolve()
    explicit_overrides = _load_explicit_overrides(request.config_specs, request.model_name)
    _reject_explicit_excluded_overrides(explicit_overrides)

    if request.base_agent_execution_config is not None:
        base_config = _strip_schema(copy.deepcopy(dict(request.base_agent_execution_config)))
        merged_config = recursive_merge(base_config, explicit_overrides)
    else:
        specs = list(request.config_specs) or [default_mini_config_spec()]
        try:
            configs = [get_config_from_spec(spec) for spec in specs]
        except Exception as exc:
            raise AgentExecutionConfigError(
                ERROR_AGENT_EXECUTION_CONFIG_RESOLUTION_FAILED,
                f"Could not resolve Agent Execution Config: {exc}",
            ) from exc
        configs.append(_model_override_config(request.model_name))
        merged_config = recursive_merge(*configs)
        _apply_spawn_time_default_model_name(merged_config)

    normalized = normalize_agent_execution_config(merged_config, shared_workspace=shared_workspace)
    validate_agent_execution_config(normalized, preflight_credentials=True)
    return normalized


def normalize_agent_execution_config(config: Mapping[str, Any], *, shared_workspace: Path) -> dict[str, Any]:
    """Normalize a mini-compatible config into Agent Execution Config schema v1."""
    if not isinstance(config, Mapping):
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, "Agent Execution Config must be a mapping")

    cleaned = copy.deepcopy(dict(config))
    for field in _EXCLUDED_TOP_LEVEL_FIELDS:
        cleaned.pop(field, None)

    agent = _mapping_section(cleaned.get("agent", {}), "agent")
    model = _mapping_section(cleaned.get("model", {}), "model")
    environment = _mapping_section(cleaned.get("environment", {}), "environment")

    for field in _EXCLUDED_AGENT_FIELDS:
        agent.pop(field, None)

    environment["environment_class"] = "local"
    environment["cwd"] = shared_workspace.resolve().as_posix()

    normalized = {
        "schema_version": AGENT_EXECUTION_CONFIG_SCHEMA_VERSION,
        "agent": agent,
        "model": model,
        "environment": environment,
    }
    validate_agent_execution_config(normalized, preflight_credentials=False)
    return normalized


def validate_agent_execution_config(
    config: Mapping[str, Any] | None,
    *,
    preflight_credentials: bool = False,
) -> dict[str, Any]:
    """Validate Agent Execution Config and return a plain dict copy."""
    if config is None:
        raise AgentExecutionConfigError(
            ERROR_MISSING_AGENT_EXECUTION_CONFIG,
            "Child Agent workflow did not receive Agent Execution Config",
        )
    if not isinstance(config, Mapping):
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, "Agent Execution Config must be a mapping")

    config_dict = copy.deepcopy(dict(config))
    schema_version = config_dict.get("schema_version")
    if schema_version != AGENT_EXECUTION_CONFIG_SCHEMA_VERSION:
        raise AgentExecutionConfigError(
            ERROR_UNSUPPORTED_AGENT_EXECUTION_CONFIG_VERSION,
            f"Unsupported Agent Execution Config schema version: {schema_version!r}",
            "schema_version",
        )

    agent = _mapping_section(config_dict.get("agent"), "agent")
    model = _mapping_section(config_dict.get("model"), "model")
    environment = _mapping_section(config_dict.get("environment"), "environment")

    _required_string(agent, "agent.system_template")
    _required_string(agent, "agent.instance_template")
    _optional_nonnegative_int(agent, "step_limit", "agent.step_limit")
    _optional_nonnegative_number(agent, "cost_limit", "agent.cost_limit")

    _required_string(model, "model.model_name")
    if "model_class" in model and model["model_class"] is not None and not isinstance(model["model_class"], str):
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, "model.model_class must be a string", "model.model_class")
    if "model_kwargs" in model and not isinstance(model["model_kwargs"], Mapping):
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, "model.model_kwargs must be a mapping", "model.model_kwargs")

    environment_class = str(environment.get("environment_class", "local") or "local")
    if environment_class not in _LOCAL_ENVIRONMENT_CLASSES:
        raise AgentExecutionConfigError(
            ERROR_UNSUPPORTED_AGENT_ENVIRONMENT,
            f"Unsupported Agent Execution Config environment: {environment_class}",
            "environment.environment_class",
        )
    _required_string(environment, "environment.cwd")
    if "env" in environment and not _is_string_mapping(environment["env"]):
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, "environment.env must be a string mapping", "environment.env")
    _optional_nonnegative_int(environment, "timeout", "environment.timeout")

    _reject_secret_keys(config_dict)

    if preflight_credentials:
        _preflight_model_credentials(model)

    return config_dict


def redact_agent_execution_config(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a trajectory-safe config snapshot with Action Environment Variable values redacted."""
    if config is None:
        return None
    redacted = copy.deepcopy(dict(config))
    environment = redacted.get("environment")
    if isinstance(environment, dict) and isinstance(environment.get("env"), dict):
        environment["env"] = {str(key): REDACTED_ENV_VALUE for key in environment["env"]}
    return redacted


def safe_prompt_template_vars(
    *,
    agent_execution_config: Mapping[str, Any],
    task: str,
    agent_id: str,
    parent_agent_id: str | None,
    n_model_calls: int,
    model_cost: float,
) -> dict[str, Any]:
    """Build autonomous MAS Child prompt template vars without process environment leakage."""
    config = validate_agent_execution_config(agent_execution_config, preflight_credentials=False)
    environment = config["environment"]
    model = config["model"]
    uname = platform.uname()
    return {
        "task": task,
        "agent_id": agent_id,
        "parent_agent_id": parent_agent_id or "",
        "cwd": environment.get("cwd", ""),
        "env": copy.deepcopy(environment.get("env", {})),
        "timeout": environment.get("timeout", 30),
        "model_name": model.get("model_name", ""),
        "n_model_calls": n_model_calls,
        "model_cost": model_cost,
        "system": uname.system,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
    }


def _load_explicit_overrides(config_specs: Sequence[str], model_name: str | None) -> dict[str, Any]:
    configs = []
    try:
        configs = [get_config_from_spec(spec) for spec in config_specs]
    except Exception as exc:
        raise AgentExecutionConfigError(
            ERROR_AGENT_EXECUTION_CONFIG_RESOLUTION_FAILED,
            f"Could not resolve Agent Execution Config override: {exc}",
        ) from exc
    configs.append(_model_override_config(model_name))
    return recursive_merge(*configs) if configs else {}


def _model_override_config(model_name: str | None) -> dict[str, Any]:
    return {"model": {"model_name": model_name or UNSET}}


def _apply_spawn_time_default_model_name(config: dict[str, Any]) -> None:
    model = config.setdefault("model", {})
    if not isinstance(model, dict) or model.get("model_name"):
        return
    if default_model_name := os.getenv("MSWEA_MODEL_NAME"):
        model["model_name"] = default_model_name


def _strip_schema(config: dict[str, Any]) -> dict[str, Any]:
    config.pop("schema_version", None)
    return config


def _reject_explicit_excluded_overrides(overrides: Mapping[str, Any]) -> None:
    if not overrides:
        return
    if "run" in overrides:
        raise AgentExecutionConfigError(
            ERROR_INVALID_AGENT_EXECUTION_CONFIG,
            "run.* is not part of Agent Execution Config schema version 1",
            "run",
        )
    agent = overrides.get("agent")
    if isinstance(agent, Mapping):
        for field in _EXCLUDED_AGENT_FIELDS:
            if field in agent:
                raise AgentExecutionConfigError(
                    ERROR_INVALID_AGENT_EXECUTION_CONFIG,
                    f"agent.{field} is not part of Agent Execution Config schema version 1",
                    f"agent.{field}",
                )
    environment = overrides.get("environment")
    if isinstance(environment, Mapping) and "cwd" in environment:
        raise AgentExecutionConfigError(
            ERROR_UNSUPPORTED_AGENT_ENVIRONMENT_CWD_OVERRIDE,
            "Spawn config overrides cannot change Local Agent Environment working directory",
            "environment.cwd",
        )


def _mapping_section(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, f"{path} section is required", path)
    if not isinstance(value, Mapping):
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, f"{path} section must be a mapping", path)
    return copy.deepcopy(dict(value))


def _required_string(section: Mapping[str, Any], path: str) -> None:
    key = path.rsplit(".", 1)[-1]
    if not isinstance(section.get(key), str) or not section.get(key):
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, f"{path} must be a non-empty string", path)


def _optional_nonnegative_int(section: Mapping[str, Any], key: str, path: str) -> None:
    if key not in section:
        return
    value = section[key]
    if not isinstance(value, int) or value < 0:
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, f"{path} must be a non-negative integer", path)


def _optional_nonnegative_number(section: Mapping[str, Any], key: str, path: str) -> None:
    if key not in section:
        return
    value = section[key]
    if not isinstance(value, int | float) or value < 0:
        raise AgentExecutionConfigError(ERROR_INVALID_AGENT_EXECUTION_CONFIG, f"{path} must be a non-negative number", path)


def _is_string_mapping(value: Any) -> bool:
    return isinstance(value, Mapping) and all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())


def _reject_secret_keys(config: Mapping[str, Any]) -> None:
    for path, key in _walk_keys(config):
        if _is_secret_key_name(str(key), environment_name=path.startswith("environment.env.")):
            raise AgentExecutionConfigError(
                ERROR_AGENT_EXECUTION_CONFIG_SECRET_KEY,
                f"Agent Execution Config contains secret-like key: {key}",
                path,
            )


def _walk_keys(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    found = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_str = str(key)
            path = f"{prefix}.{key_str}" if prefix else key_str
            found.append((path, key_str))
            found.extend(_walk_keys(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_walk_keys(item, f"{prefix}[{index}]"))
    return found


def _is_secret_key_name(key: str, *, environment_name: bool = False) -> bool:
    normalized = key.lower()
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    if normalized in _SECRET_COMPOUND_KEYS or compact in _SECRET_COMPOUND_KEYS:
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if token]
    if any(token in _SECRET_TOKENS for token in tokens):
        return True
    if environment_name and _ENV_SECRET_RE.fullmatch(key.upper()):
        return True
    return False


def _preflight_model_credentials(model: Mapping[str, Any]) -> None:
    required_groups = _required_credential_env_name_groups(model)
    missing_groups = [group for group in required_groups if not any(os.getenv(name) for name in group)]
    if missing_groups:
        missing = [" or ".join(group) for group in missing_groups]
        raise AgentExecutionConfigError(
            ERROR_MISSING_MODEL_PROVIDER_CREDENTIAL,
            f"Missing model provider credential: {', '.join(missing)}",
            "model",
        )


def _required_credential_env_name_groups(model: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    model_class = str(model.get("model_class") or "")
    model_name = str(model.get("model_name") or "").lower()
    model_class_key = model_class.rsplit(".", 1)[-1].lower()
    model_class_alias = model_class.lower()

    if "deterministic" in model_class_alias or model_name == "deterministic":
        return ()
    if "openrouter" in model_class_alias or model_class_key.startswith("openrouter"):
        return (("OPENROUTER_API_KEY",),)
    if "portkey" in model_class_alias or model_class_key.startswith("portkey"):
        return (("PORTKEY_API_KEY",),)
    if "requesty" in model_class_alias or model_class_key.startswith("requesty"):
        return (("REQUESTY_API_KEY",),)
    if not model_class or "litellm" in model_class_alias:
        if model_name.startswith("openai/"):
            return (("OPENAI_API_KEY",),)
        if model_name.startswith("anthropic/") or any(token in model_name for token in ("claude", "sonnet", "opus")):
            return (("ANTHROPIC_API_KEY",),)
        if model_name.startswith(("gemini/", "google/")):
            return (("GEMINI_API_KEY", "GOOGLE_API_KEY"),)
    return ()
