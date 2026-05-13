# Freeze Agent Execution Config at Spawn

## Status

Accepted for MVP design.

## Context

The MAS MVP runs autonomous **Child Agents** durably through DBOS workflows. Unlike the original one-shot `mini` process, queued Child Agent work may be created by one `mini-mas` process and later consumed by another `mini-mas agent activate` process.

If the later activation process decides the model, prompt, limits, environment, or config file at execution time, the queued Agent can drift from the Spawn-time intent. It can also fail in ambiguous ways when model configuration or provider credentials are missing. The observed stale `running` problem came from Child workflows being queued without model/environment configuration and then recording a non-terminal `started` trajectory state.

The MVP needs a durable, explicit, secret-free execution contract for autonomous Child Agents, while still preserving mini-compatible configuration ergonomics at Spawn time.

## Decision

The MAS MVP freezes a secret-free **Agent Execution Config** when an autonomous Child Agent is spawned and passes that config directly as DBOS workflow input.

`mini-mas agent activate` consumes queued autonomous Agent work but does not choose or mutate the Agent Execution Config. A queued Agent's model, prompt, limits, and MVP Local Agent Environment settings are determined by the frozen config, not by whichever activation process later consumes the queue.

Spawn fails before creating a Child Agent when mini-mas cannot build a valid Agent Execution Config. That validation failure is reported as a MAS Command error and does not fail the Parent Agent.

Existing or externally queued Child workflows without a valid config fail explicitly instead of remaining `running`.

## Considered Options

- Freeze the Agent Execution Config at Spawn time and pass it directly as DBOS workflow input.
- Let `mini-mas agent activate` read the current mini config and decide how queued Agents run.
- Store the config as an Agent Artifact and pass only an artifact reference plus hash as workflow input.
- Let the Child workflow read the current config in a DBOS step without a frozen config input.

## Agent Execution Config V1

Schema version 1 keeps mini-compatible top-level `agent`, `model`, and `environment` sections, but includes only fields suitable for autonomous Child execution and durable workflow input.

The config includes `schema_version: 1`.

The `agent` section includes:

- `system_template`
- `instance_template`
- `step_limit`
- `cost_limit`

The `model` section includes model construction and formatting fields:

- `model_class`
- `model_name`
- `observation_template`
- `format_error_template`
- `model_kwargs`

`model.model_kwargs` is preserved as-is in Agent Execution Config V1. The MVP does not project it through a provider-specific allowlist because that would require reimplementing part of the model provider schema. Secret-key scanning rejects obvious secret carrier keys before the config is frozen, prompt rendering does not expose `model_kwargs`, and model construction steps may pass it to the model factory.

The `environment` section includes Local Agent Environment fields:

- `environment_class`
- `cwd`
- `env`
- `timeout`

Schema version 1 excludes `run.task` because delegated work remains Child workflow input rather than execution config.

Schema version 1 excludes `agent.output_path` because MAS trajectory paths come from Agent Metadata and Agent Artifact Directory.

Schema version 1 excludes interactive-only fields such as `agent.mode`, `agent.confirm_exit`, and `agent.whitelist_actions`.

Schema version 1 does not let `agent.agent_class` choose the autonomous Child implementation. Autonomous Child Agents use the MAS agent implementation; the `agent` section only configures prompt and limits.

## Spawn-Time Config Resolution

External and workflow-layer Detached Spawn and Waited Spawn may build a Child Agent Execution Config from mini-compatible `-c/--config` and `-m/--model` options during the MVP.

Explicit `-c/--config` options are resolved using mini-compatible config resolution:

- YAML file paths are supported.
- Bare config names may resolve to `.yaml`.
- Inline `key=value` config specs are supported.
- Multiple config specs are recursively merged.

If Spawn has no explicit `-c/--config`, it uses mini-compatible default config resolution: `MSWEA_MINI_CONFIG_PATH` from the current Runtime Process Environment if present, otherwise the built-in `mini.yaml`.

`MSWEA_CONFIG_DIR` from the current Runtime Process Environment may participate in mini-compatible `-c/--config` file lookup at Spawn time.

Runtime Process Environment variables that participate in Spawn config resolution affect only the newly frozen Agent Execution Config. They are not stored as runtime variables and are not consulted later by AI Agent Execution.

External Spawn resolves the current Shared Workspace from the External MAS CLI working directory.

Workflow-layer Spawn from an Interactive Root Agent resolves the current Shared Workspace from that Root Agent's recorded MAS workspace.

Workflow-layer Spawn from an autonomous Agent resolves the current Shared Workspace from that Agent's Agent Execution Config.

A workflow-layer Spawn from an autonomous Agent without config overrides inherits the current Agent's Agent Execution Config and does not re-read config files or config-resolution environment variables.

A workflow-layer Spawn from an autonomous Agent with `-c/--config` or `-m/--model` overrides resolves those overrides at Spawn time and freezes the resulting Child Agent Execution Config.

During the MVP, `-c/--config` and `-m/--model` Spawn overrides do not require an additional Authority Grant or confirmation.

Spawn builds Child Agent Execution Config through one pipeline:

1. Choose a base config.
2. Apply mini-compatible overrides.
3. Normalize MAS-owned fields.
4. Validate the result.

External Spawn and Interactive Root Agent Spawn use mini-compatible config resolution as their base config.

Autonomous Agent Spawn uses the current Agent's Agent Execution Config as its base config, including when `-c/--config` or `-m/--model` overrides are supplied. This prevents autonomous Child configuration from drifting back to whatever mini default config is visible to the current Runtime Process Environment.

`-m/--model` is equivalent to overriding `model.model_name`.

Spawn normalization sets `schema_version: 1`, fixes `environment.cwd` to the current Shared Workspace, normalizes the environment as Local Agent Environment, and drops fields excluded from Agent Execution Config schema version 1.

Fields excluded from Agent Execution Config schema version 1 may be silently dropped when they come from the base mini config for compatibility.

Fields excluded from Agent Execution Config schema version 1 cause Spawn to fail when they are supplied as explicit Spawn overrides. This prevents users from believing an override such as `agent.mode`, `agent.output_path`, or `run.task` affected autonomous Child execution when it was actually ignored.

An explicit Spawn override of `environment.cwd` fails with `unsupported_agent_environment_cwd_override`.

## Environment Scope

The MVP Agent Execution Config describes mini-equivalent agent, model, and Local Agent Environment settings only.

Spawn rejects an Agent Execution Config whose environment is not a Local Agent Environment.

Spawn rejects attempts to override the Local Agent Environment working directory. The effective `environment.cwd` is the absolute Shared Workspace path fixed when the Child Agent is spawned.

Action Environment Variables may be stored in the Agent Execution Config and passed to bash execution steps. Schema version 1 keeps the mini-compatible field name `environment.env`.

Action Environment Variables come only from resolved mini environment configuration, not from copying the Runtime Process Environment.

`environment.env` values are stored in Agent Execution Config workflow input as non-secret values so bash execution steps can apply them.

`environment.env` values are redacted only when the Agent Execution Config is copied into a Trajectory Artifact.

Secrets must not be passed through Action Environment Variables during the MVP.

Spawn rejects resolved Action Environment Variables whose names look like obvious secret carriers.

The final normalized Agent Execution Config is scanned recursively by key name for obvious secret carriers, regardless of whether those keys came from the base config or an explicit Spawn override. The scan checks key names only, not values.

Secret-key scanning uses case-insensitive key-name tokens and common secret compound names instead of arbitrary substring matching. It rejects key-name tokens `key`, `token`, `secret`, `password`, `credential`, and `authorization`.

It also rejects common compound names such as `api_key`, `apikey`, `access_token`, `refresh_token`, `bearer_token`, `auth_token`, `client_secret`, and `private_key`.

Action Environment Variable names are rejected when they match secret-like environment variable shapes such as `*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, or `AUTHORIZATION`.

Strict false positives such as `cache_key` are acceptable during the MVP because secret-free workflow input takes priority.

During the MVP, local bash actions may still inherit the step process's Runtime Process Environment at execution time. This preserves the current mini LocalEnvironment behavior and is not treated as part of the durable config contract.

## Secrets and Credentials

Secrets are not stored in workflow input.

Spawn rejects Agent Execution Config keys that look like obvious secret carriers anywhere in the config. The MVP denylist includes obvious key-name fragments such as:

- `key`
- `token`
- `secret`
- `password`
- `credential`
- `authorization`

Model provider credentials are read from the Runtime Process Environment inside model query steps rather than represented as secret references in the Agent Execution Config.

Spawn performs a lightweight credential preflight against the current Runtime Process Environment when the model provider's required credential variable is obvious. The preflight checks only whether required environment variables are present and non-empty. It does not make network calls and does not validate credential correctness.

Credential preflight failure prevents Child Agent creation.

If the required credential variable is not obvious, Spawn skips preflight and leaves validation to runtime model steps.

MVP preflight requires:

- `OPENROUTER_API_KEY` for explicit OpenRouter model classes.
- `PORTKEY_API_KEY` for explicit Portkey model classes.
- `REQUESTY_API_KEY` for the explicit Requesty model class.

MVP preflight does not require `PORTKEY_VIRTUAL_KEY`.

Deterministic test models are treated as credential-free.

For LiteLLM-backed models, the MVP only checks obvious model names such as OpenAI, Anthropic/Claude, and Gemini/Google models. Less obvious providers are left to runtime model steps.

## DBOS Boundaries

Spawn command handling builds the Child Agent Execution Config in a DBOS step because config file reads and Runtime Process Environment reads are non-deterministic.

Child workflow bodies use the Agent Execution Config only for deterministic validation, lifecycle orchestration, and safe prompt rendering.

Child workflow bodies do not:

- Read config files.
- Read `os.environ`.
- Call mini object factories such as `get_model()` and `get_environment()`.
- Accept live model or environment objects as normal workflow input.

Model and environment objects are constructed and used inside DBOS steps.

The existing `model=None` or `env=None` Child workflow path becomes invalid config behavior rather than a normal `started` state.

Runtime model, credential, or environment construction failures after Spawn make the Child Agent reach `failed`, not `recovery_required`.

## Prompt Rendering

Autonomous MAS prompt rendering uses Agent Execution Config data and does not include the Runtime Process Environment.

Prompt rendering does not call `LocalEnvironment.get_template_vars()` because that helper merges `os.environ`.

If prompt rendering needs host information, it should read only safe, non-secret system information such as `platform.uname()` through an explicit step or helper, not through the LocalEnvironment template-vars merge.

During the MVP, autonomous MAS prompt rendering uses a dedicated safe template variable set:

- `task`
- `agent_id`
- `parent_agent_id`
- `cwd`
- `env`
- `timeout`
- `model_name`
- `n_model_calls`
- `model_cost`
- `system`
- `release`
- `version`
- `machine`

The `env` prompt template variable comes only from Action Environment Variables in the Agent Execution Config.

Prompt rendering does not expose `model_kwargs`, the full Agent Execution Config, provider credential variables, or arbitrary Runtime Process Environment variables.

## Failure Codes

Agent Execution Config failures use stable diagnosis codes during the MVP without a complex error hierarchy.

- `missing_agent_execution_config`: a Child workflow did not receive an Agent Execution Config.
- `unsupported_agent_execution_config_version`: the config schema version is missing or unsupported.
- `invalid_agent_execution_config`: the config shape, field type, required fields, prompt templates, or limits are invalid.
- `unsupported_agent_environment`: the resolved environment is not a supported Local Agent Environment.
- `unsupported_agent_environment_cwd_override`: a Spawn config override attempted to change the Local Agent Environment working directory.
- `agent_execution_config_secret_key`: the config contains a key that looks like an obvious secret carrier.
- `missing_model_provider_credential`: Spawn preflight found an obvious required provider credential missing from the current Runtime Process Environment.
- `agent_execution_config_resolution_failed`: Spawn could not resolve or merge mini-compatible config specs.
- `agent_execution_runtime_failed`: runtime model, credential, or environment construction failed after Spawn.

Spawn-time failures return MAS Command errors, do not create Child Agents, and do not fail Parent Agents.

Spawn-time failures that occur before a Child Agent is created do not write a Child Trajectory Artifact. This matches mini's behavior for failures before agent construction, such as missing config or missing default model.

Child workflow defensive-validation failures publish Child failed status and record diagnosis in a minimal Trajectory Artifact. Once a Child workflow exists, validation and runtime failures must produce a terminal Child status and diagnosable artifact rather than leaving a stale `running` state.

## Status and Trajectory

Child Status Event stays lightweight and does not include Agent Execution Config.

Trajectory Artifact may record the non-secret Agent Execution Config for diagnosis.

Trajectory Artifact redacts Action Environment Variables values when recording an Agent Execution Config.

Runtime Process Environment may provide secrets to DBOS steps, but it is not stored in Agent Execution Config, Child Status Event, or Trajectory Artifact.

## Consequences

The queued Child Agent contract becomes explicit and durable. Model, prompt, limit, and Local Agent Environment settings no longer drift based on which activation process consumes queued AI Agent work.

Spawn can fail early for common configuration errors, including missing default model configuration, unsupported environment configuration, obvious secret-bearing config keys, and obvious missing provider credentials.

Old or malformed queued Child workflows fail explicitly instead of recording a non-terminal `started` result while publishing `running`.

The MVP preserves mini-compatible config ergonomics at Spawn time, while keeping DBOS workflow inputs secret-free and serializable.

The implementation must introduce a config builder/validator path instead of treating missing live `model` or `env` objects as a valid Child workflow state.

## Deferred

The MVP intentionally defers:

- Durable external sandbox lifecycle semantics.
- Secret reference semantics.
- Strong environment isolation semantics.
- Full LiteLLM provider credential registry replication.
- Artifact reference plus hash storage for Agent Execution Config.
- Rich config override authority semantics.
