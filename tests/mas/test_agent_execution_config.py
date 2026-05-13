import pytest


def _base_config(tmp_path):
    return {
        "agent": {
            "system_template": "System {{system}}",
            "instance_template": "Task {{task}} in {{cwd}}",
            "step_limit": 0,
            "cost_limit": 3.0,
            "mode": "confirm",
            "output_path": "ignored.traj.json",
        },
        "model": {
            "model_class": "deterministic",
            "model_name": "deterministic",
            "model_kwargs": {"drop_params": True},
            "observation_template": "{{output.output}}",
            "format_error_template": "{{error}}",
        },
        "environment": {
            "environment_class": "local",
            "cwd": "/should/not/survive",
            "env": {"PAGER": "cat"},
            "timeout": 30,
        },
        "run": {"task": "not config"},
    }


def test_normalize_agent_execution_config_drops_base_only_fields_and_fixes_workspace(tmp_path):
    from minisweagent.mas.execution_config import normalize_agent_execution_config

    config = normalize_agent_execution_config(_base_config(tmp_path), shared_workspace=tmp_path)

    assert config["schema_version"] == 1
    assert set(config) == {"schema_version", "agent", "model", "environment"}
    assert "mode" not in config["agent"]
    assert "output_path" not in config["agent"]
    assert config["environment"]["environment_class"] == "local"
    assert config["environment"]["cwd"] == tmp_path.resolve().as_posix()
    assert config["environment"]["env"] == {"PAGER": "cat"}
    assert config["model"]["model_kwargs"] == {"drop_params": True}


def test_build_agent_execution_config_rejects_explicit_excluded_override(tmp_path):
    from minisweagent.mas.execution_config import (
        AgentExecutionConfigBuildRequest,
        AgentExecutionConfigError,
        build_agent_execution_config,
    )

    with pytest.raises(AgentExecutionConfigError) as exc_info:
        build_agent_execution_config(
            AgentExecutionConfigBuildRequest(
                shared_workspace=tmp_path,
                base_agent_execution_config=_base_config(tmp_path),
                config_specs=["agent.mode=yolo"],
            )
        )

    assert exc_info.value.code == "invalid_agent_execution_config"
    assert exc_info.value.path == "agent.mode"


def test_build_agent_execution_config_rejects_explicit_cwd_override(tmp_path):
    from minisweagent.mas.execution_config import (
        AgentExecutionConfigBuildRequest,
        AgentExecutionConfigError,
        build_agent_execution_config,
    )

    with pytest.raises(AgentExecutionConfigError) as exc_info:
        build_agent_execution_config(
            AgentExecutionConfigBuildRequest(
                shared_workspace=tmp_path,
                base_agent_execution_config=_base_config(tmp_path),
                config_specs=["environment.cwd=/tmp/other"],
            )
        )

    assert exc_info.value.code == "unsupported_agent_environment_cwd_override"
    assert exc_info.value.path == "environment.cwd"


def test_validate_agent_execution_config_rejects_secret_like_keys(tmp_path):
    from minisweagent.mas.execution_config import (
        AgentExecutionConfigError,
        normalize_agent_execution_config,
    )

    raw = _base_config(tmp_path)
    raw["environment"]["env"]["OPENAI_API_KEY"] = "not allowed"
    with pytest.raises(AgentExecutionConfigError) as exc_info:
        normalize_agent_execution_config(raw, shared_workspace=tmp_path)

    assert exc_info.value.code == "agent_execution_config_secret_key"
    assert exc_info.value.path == "environment.env.OPENAI_API_KEY"


def test_redact_agent_execution_config_redacts_only_environment_values(tmp_path):
    from minisweagent.mas.execution_config import normalize_agent_execution_config, redact_agent_execution_config

    config = normalize_agent_execution_config(_base_config(tmp_path), shared_workspace=tmp_path)
    redacted = redact_agent_execution_config(config)

    assert redacted["environment"]["env"] == {"PAGER": "<redacted>"}
    assert config["environment"]["env"] == {"PAGER": "cat"}
    assert redacted["model"]["model_kwargs"] == {"drop_params": True}


def test_default_mini_config_spec_uses_mas_prompt_by_default(monkeypatch):
    from minisweagent.config import builtin_config_dir
    from minisweagent.mas.execution_config import default_mini_config_spec

    monkeypatch.delenv("MSWEA_MINI_CONFIG_PATH", raising=False)

    assert default_mini_config_spec() == str(builtin_config_dir / "mini-mas.yaml")


def test_default_mini_config_spec_respects_existing_env_override(monkeypatch, tmp_path):
    from minisweagent.mas.execution_config import default_mini_config_spec

    custom_config = tmp_path / "custom.yaml"
    monkeypatch.setenv("MSWEA_MINI_CONFIG_PATH", str(custom_config))

    assert default_mini_config_spec() == str(custom_config)


def test_build_agent_execution_config_without_specs_uses_mini_mas_default(monkeypatch, tmp_path):
    from minisweagent.config import builtin_config_dir
    from minisweagent.mas.execution_config import AgentExecutionConfigBuildRequest, build_agent_execution_config

    expected_spec = str(builtin_config_dir / "mini-mas.yaml")
    seen_specs = []

    def fake_get_config_from_spec(spec):
        seen_specs.append(spec)
        return _base_config(tmp_path)

    monkeypatch.delenv("MSWEA_MINI_CONFIG_PATH", raising=False)
    monkeypatch.setattr("minisweagent.mas.execution_config.get_config_from_spec", fake_get_config_from_spec)

    config = build_agent_execution_config(AgentExecutionConfigBuildRequest(shared_workspace=tmp_path))

    assert seen_specs == [expected_spec]
    assert config["environment"]["cwd"] == tmp_path.resolve().as_posix()


def test_safe_prompt_template_vars_are_from_config_not_process_env(tmp_path, monkeypatch):
    from minisweagent.mas.execution_config import normalize_agent_execution_config, safe_prompt_template_vars

    monkeypatch.setenv("PAGER", "less")
    config = normalize_agent_execution_config(_base_config(tmp_path), shared_workspace=tmp_path)

    vars_ = safe_prompt_template_vars(
        agent_execution_config=config,
        task="fix bug",
        agent_id="mas-0123456789abcdef",
        parent_agent_id="mas-fedcba9876543210",
        n_model_calls=2,
        model_cost=1.25,
    )

    assert vars_["task"] == "fix bug"
    assert vars_["agent_id"] == "mas-0123456789abcdef"
    assert vars_["parent_agent_id"] == "mas-fedcba9876543210"
    assert vars_["cwd"] == tmp_path.resolve().as_posix()
    assert vars_["env"] == {"PAGER": "cat"}
    assert vars_["model_name"] == "deterministic"
    assert vars_["n_model_calls"] == 2
    assert vars_["model_cost"] == 1.25
    assert "model_kwargs" not in vars_
    assert "agent_execution_config" not in vars_


def test_litellm_obvious_provider_preflight_requires_credential(tmp_path, monkeypatch):
    from minisweagent.mas.execution_config import (
        AgentExecutionConfigError,
        normalize_agent_execution_config,
        validate_agent_execution_config,
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    raw = _base_config(tmp_path)
    raw["model"]["model_class"] = "litellm"
    raw["model"]["model_name"] = "openai/gpt-4.1"
    config = normalize_agent_execution_config(raw, shared_workspace=tmp_path)

    with pytest.raises(AgentExecutionConfigError) as exc_info:
        validate_agent_execution_config(config, preflight_credentials=True)

    assert exc_info.value.code == "missing_model_provider_credential"
    assert "OPENAI_API_KEY" in exc_info.value.message
