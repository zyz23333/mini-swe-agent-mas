# Agent Execution Config Implementation Plan

Status: draft

## Parent Context

- `.scratch/dbos-mas/PRD.md`
- `CONTEXT.md`
- `docs/adr/0010-freeze-agent-execution-config-at-spawn.md`

## Problem

Autonomous Child Agents can currently be queued without the model and environment configuration needed to run. When AI Agent Execution later consumes that work, the Child workflow can publish `running`, save a non-terminal `started` trajectory state, and return successfully from DBOS without ever reaching a terminal MAS lifecycle state.

This is a root-cause mismatch between original `mini` execution and durable `mini-mas` execution:

- `mini` is a one-shot process. If config, model, or environment construction fails before `agent.run()`, the process exits and no agent lifecycle remains behind.
- `mini-mas` queues durable Child workflows. Once a Child workflow exists, invalid or missing execution config must produce terminal Child state and diagnosable artifacts instead of stale `running`.

## Goal

Implement **Agent Execution Config** as the durable, secret-free Child Agent execution contract frozen at Spawn time and passed directly as DBOS workflow input.

The implementation must:

- Fail Spawn before creating a Child Agent when config cannot be built or validated.
- Pass a validated `agent_execution_config` into `child_agent_workflow`.
- Treat missing or invalid config inside an already-created Child workflow as `failed`.
- Keep `mini-mas agent activate` from choosing or mutating queued Child execution config.
- Preserve mini-compatible config ergonomics for Spawn.
- Keep secrets out of workflow input, status events, and trajectory artifacts.

## Non-Goals

- Do not introduce secret references.
- Do not implement durable external sandbox lifecycle.
- Do not implement Workspace Isolation.
- Do not replicate the full LiteLLM provider credential registry.
- Do not add a daemon or implicit background AI Agent Execution.
- Do not broaden Direct Child Authority Policy or add Authority Grants.
- Do not change ordinary `mini` behavior.

## Design Source of Truth

ADR 0010 is the detailed implementation contract for:

- Agent Execution Config V1 shape.
- Spawn-time config resolution.
- Local Agent Environment scope.
- Action Environment Variables.
- secret-key scanning.
- credential preflight.
- DBOS workflow/step boundaries.
- prompt rendering variables.
- failure codes.
- status and trajectory behavior.

`CONTEXT.md` keeps only the domain-level terminology and relationships. If implementation details conflict, update ADR 0010 rather than expanding `CONTEXT.md`.

## Proposed Modules

### `src/minisweagent/mas/execution_config.py`

Owns Agent Execution Config construction, normalization, validation, redaction, and prompt-template variable preparation.

Responsibilities:

- Define the schema-version constant.
- Build config from mini-compatible config specs and Spawn overrides.
- Build Child config by inheriting an autonomous Parent Agent's config.
- Normalize MAS-owned fields:
  - `schema_version: 1`
  - `environment.environment_class: local`
  - absolute Shared Workspace `environment.cwd`
  - dropped base-config-only excluded fields
- Detect explicit override of excluded fields.
- Detect explicit override of `environment.cwd`.
- Reject unsupported environment classes.
- Perform recursive secret-key scan over the final normalized config.
- Perform lightweight credential preflight.
- Redact Agent Execution Config for trajectory persistence.
- Produce the safe prompt template variable set.

Non-responsibilities:

- Do not enqueue workflows.
- Do not publish Child Status Events.
- Do not construct live model or environment objects in workflow bodies.
- Do not read DBOS workflow metadata.

### `src/minisweagent/mas/commands.py`

Extends Spawn argument parsing and command dispatch.

Responsibilities:

- Parse `mini-mas spawn` options:
  - repeated task arguments
  - existing wait options
  - `-c/--config`
  - `-m/--model`
- Preserve current invalid-argument behavior for existing Spawn options.
- Invoke Spawn config-building before Child creation.
- Return MAS Command errors when config building or validation fails.

### `src/minisweagent/mas/agent_interactions.py`

Passes validated config into Child workflow enqueueing.

Responsibilities:

- Add `agent_execution_config` to `enqueue_child_agent_workflow`.
- Add per-child Agent Execution Config to `spawn_children`.
- Keep Child workflow enqueueing outside DBOS steps.

### `src/minisweagent/mas/mas_agent.py`

Consumes Agent Execution Config in Child workflows.

Responsibilities:

- Update `child_agent_workflow` signature to require `agent_execution_config`.
- Defensive-validate the config at workflow start.
- Remove `model=None` / `env=None` as a valid Child startup path.
- Publish `failed` and save a minimal trajectory when an already-created Child workflow receives missing or invalid config.
- Construct live model and environment objects only inside DBOS steps.
- Render initial prompts from the safe MAS prompt variable set.
- Preserve existing MAS loop behavior after initialization:
  - model query through DBOS step
  - bash execution through DBOS step
  - MAS Command Interception at the Agent layer
  - trajectory persistence through DBOS step

### `src/minisweagent/mas/artifacts.py`

Extends trajectory persistence metadata.

Responsibilities:

- Allow minimal failure artifacts before normal messages exist.
- Allow trajectory metadata to include redacted Agent Execution Config.
- Do not include unredacted Action Environment Variable values in trajectory config snapshots.

## DBOS Boundary Plan

### Spawn Config Build Step

Add a DBOS step for Spawn-time config building because it may read:

- config files
- `MSWEA_MINI_CONFIG_PATH`
- `MSWEA_CONFIG_DIR`
- Runtime Process Environment credential variables for preflight

The step returns only a serializable, secret-free Agent Execution Config or a structured MAS Command error.

### Child Workflow Body

The Child workflow body may:

- validate `agent_execution_config`
- drive lifecycle transitions
- orchestrate DBOS steps
- publish status events
- save trajectory artifacts

The Child workflow body must not:

- read config files
- read `os.environ`
- call `get_model()`
- call `get_environment()`
- accept live model or environment objects as normal workflow input
- call `LocalEnvironment.get_template_vars()`

### Runtime Steps

DBOS steps may:

- construct model objects from `agent_execution_config.model`
- construct Local Agent Environment objects from `agent_execution_config.environment`
- read Runtime Process Environment indirectly through model provider libraries
- execute bash commands
- persist trajectory artifacts

Runtime construction failures after Child creation map to Child `failed`.

## Implementation Phases

### Phase 1: Config Schema and Pure Validation

Add `execution_config.py` with pure helpers and unit tests.

Build:

- schema-version constants
- excluded-field detection
- cwd override detection
- local-environment validation
- recursive secret-key scan
- config redaction
- safe prompt vars builder
- credential requirement inference

Verify:

- valid mini-compatible config normalizes to schema v1
- excluded base fields are dropped
- excluded explicit override fields fail
- explicit `environment.cwd` override fails
- non-local environment fails
- secret-like keys fail
- `environment.env` values redact for trajectory
- prompt vars do not include Runtime Process Environment, full config, or `model_kwargs`

### Phase 2: Mini-Compatible Config Builder

Implement Spawn-time config building.

Build:

- default config resolution from `MSWEA_MINI_CONFIG_PATH` or built-in `mini.yaml`
- `MSWEA_CONFIG_DIR` participation in config file lookup
- repeated `-c/--config` recursive merge
- inline `key=value` config specs
- `-m/--model` as `model.model_name`
- External / Interactive Root base config path
- autonomous Agent base config inheritance path

Verify:

- no explicit `-c` uses mini default config
- explicit `-c` supports file, bare name, and inline override
- autonomous no-override spawn inherits current config without reading runtime config env
- autonomous override spawn overlays current config rather than rebuilding from default config
- build failures return structured errors without creating Child metadata

### Phase 3: Spawn Parser and Command Errors

Extend `mini-mas spawn` parsing.

Build:

- `SpawnCommandRequest.config_specs`
- `SpawnCommandRequest.model_name`
- `-c/--config`
- `-m/--model`
- shared validation for external and workflow-layer Spawn
- MAS Command error formatting for Agent Execution Config failures

Verify:

- existing Spawn wait/detach parser tests still pass
- `-c` and `-m` parse in any supported order
- invalid config arguments are model-visible MAS Command errors
- config validation errors do not fail Parent Agent lifecycle

### Phase 4: Enqueue Agent Execution Config

Pass config through Child workflow enqueueing.

Build:

- `spawn_children(..., agent_execution_config=...)` or per-child config equivalent
- `enqueue_child_agent_workflow(..., agent_execution_config=...)`
- queue call into `child_agent_workflow(..., agent_execution_config=...)`

Verify:

- DBOS workflow input includes Agent Execution Config
- Child Agent metadata is created only after config build succeeds
- multi-spawn uses the same validated config for each child unless later design adds per-task config

### Phase 5: Child Workflow Defensive Failure

Make Child workflow failures terminal and diagnosable.

Build:

- `missing_agent_execution_config` handling
- unsupported schema version handling
- invalid shape handling
- failed Child Status Event publication
- minimal Trajectory Artifact save for existing Child workflows
- First Observable Event publication for failed Child workflows

Verify:

- calling `child_agent_workflow` without config reaches `failed`
- invalid config reaches `failed`
- status does not remain `running`
- trajectory status is terminal and includes diagnosis
- Spawn-time failures still do not write Child trajectory because no Child exists

### Phase 6: Runtime Model and Environment Steps

Move live object construction behind DBOS steps for autonomous Child execution.

Build:

- model construction step from `agent_execution_config.model`
- Local Agent Environment construction step from `agent_execution_config.environment`
- model query step that uses constructed model behavior without workflow body calling model factory
- bash execution step that applies Local Agent Environment config

Verify:

- Runtime Process Environment credentials are read only inside model/runtime steps
- model construction failure maps to Child `failed`
- environment construction failure maps to Child `failed`
- ordinary model query and bash execution still use DBOS checkpoints

### Phase 7: Prompt Rendering

Replace autonomous MAS Child initial message rendering.

Build:

- safe template variable set:
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
- system-info helper or step using `platform.uname()`
- no `LocalEnvironment.get_template_vars()` in autonomous prompt rendering

Verify:

- mini default prompt renders system information
- `env` prompt variable comes only from Action Environment Variables
- Runtime Process Environment variables do not appear in prompt vars
- `model_kwargs` and full Agent Execution Config are not prompt vars
- missing template variable produces Child `failed` after workflow creation

### Phase 8: Trajectory Recording

Persist redacted config and minimal failure artifacts.

Build:

- redacted Agent Execution Config trajectory metadata
- redacted `environment.env` values
- failure-code metadata for validation/runtime failures
- no config in Child Status Event

Verify:

- trajectory config snapshot redacts Action Environment Variable values
- status events remain lightweight
- secret-key validation failures do not write raw offending config into trajectory
- normal completed / waiting-for-parent / failed / limits-exceeded trajectories still save

### Phase 9: Regression and Integration Coverage

Add focused MAS tests around the original stale-running class.

Verify:

- spawn with missing default model fails before Child creation
- spawn with obvious missing provider credential fails before Child creation
- old-style queued Child workflow without config reaches `failed`
- invalid queued Child config reaches `failed`
- `mini-mas status` never reports stale `running` for config validation failures
- `mini-mas agent activate` does not read current mini config to decide queued Child execution
- existing MAS runtime, command, authority, status, and interactive-root tests pass

## Suggested Test Files

Add or update:

- `tests/mas/test_agent_execution_config.py`
- `tests/mas/test_commands.py`
- `tests/mas/test_agent_interactions.py`
- `tests/mas/test_mas_agent.py`
- `tests/mas/test_artifacts.py`
- `tests/mas/test_runtime.py` only if existing runtime session behavior needs coverage

Prefer focused unit tests for config construction and validation, plus a small number of end-to-end-ish MAS tests for queued Child workflow behavior.

## Acceptance Criteria

- [ ] Spawn builds a valid Agent Execution Config before creating any autonomous Child Agent.
- [ ] Spawn validation failures return MAS Command errors and do not create Child Agents.
- [ ] Child workflow input includes `agent_execution_config`.
- [ ] A Child workflow without valid config reaches `failed`, publishes Child Status Event, publishes First Observable Event when applicable, and writes a minimal Trajectory Artifact.
- [ ] `model=None` or `env=None` is not a normal Child workflow startup state.
- [ ] `mini-mas agent activate` consumes queued work without choosing or mutating Agent Execution Config.
- [ ] Action Environment Variables come only from Agent Execution Config and are redacted in trajectory snapshots.
- [ ] Runtime Process Environment is not stored in Agent Execution Config, Child Status Event, or Trajectory Artifact.
- [ ] Autonomous prompt rendering uses the safe MAS template variable set and does not call `LocalEnvironment.get_template_vars()`.
- [ ] Model/environment live objects are constructed and used inside DBOS steps, not passed as workflow input.
- [ ] Existing MAS behavior for Detached Spawn, Waited Spawn, wait, status, continue, close, Interactive Root Agent, and AI Agent Execution activation remains intact.

## Verification Commands

Run targeted tests first:

```bash
uv run pytest tests/mas/test_agent_execution_config.py -q
uv run pytest tests/mas/test_commands.py tests/mas/test_agent_interactions.py tests/mas/test_mas_agent.py -q
```

Then run broader MAS coverage:

```bash
uv run pytest tests/mas tests/run/test_cli_integration.py -q
uv run ruff check src/minisweagent/mas tests/mas
git diff --check
```

## Risks

### DBOS replay and live objects

Constructing live model/environment objects in steps while keeping the Agent loop readable may require reshaping the current `MasAgent` implementation. Keep changes incremental and avoid introducing a generic backend abstraction.

### Credential preflight false negatives

LiteLLM supports many providers. MVP preflight intentionally catches only obvious cases. Less obvious providers must fail at runtime with Child `failed`, not stale `running`.

### Secret-key false positives

Strict key scanning can reject non-secret fields such as `cache_key`. This is acceptable during the MVP because secret-free workflow input has priority.

### Existing modified runtime files

At the time this plan was written, `src/minisweagent/mas/runtime.py` and `tests/mas/test_runtime.py` already had unrelated local modifications. Implementation should not revert or absorb those changes unless the task explicitly owns them.

## Open Questions Before Coding

- Should this be executed as one implementation issue or split into smaller `.scratch/dbos-mas/issues/32+` tickets?
- Should the config builder use Pydantic models immediately, or start with explicit dict validation to stay close to mini's current config style?
- Should failed Child trajectories include a dedicated `info.mas_error` object, or reuse existing `latest_error` / exit metadata shape?
