# Use Action Environment Bindings for MAS Docker Execution

## Status

Accepted for ProgramBench Docker support design.

## Context

ProgramBench requires mini-mas to keep model calls, provider credentials, DBOS workflows, and MAS Runtime State Store access in the host Runtime Process Environment while bash actions run inside a no-network `task_cleanroom` Docker container. The original MAS Agent Execution Config MVP supported only Local Agent Environment execution and treated runtime model or environment failures as terminal `failed` states.

MAS is intended to let multiple Agents collaborate on one external task, not only to run one independent task per Agent. A ProgramBench instance therefore needs a shared task workspace that can be observed and modified by the configured Interactive Root Agent and its Child Agents.

## Decision

MAS Docker execution is modeled through **Action Environment Bindings** carried in Agent Execution Config rather than through per-Agent private Docker containers or a separate run-level durable environment record.

The first implementation supports one effective default binding per Agent. ProgramBench uses one shared Docker binding, identified by a stable **Action Environment ID** such as `programbench-cleanroom`, and all Agents in the Collaborative Task Run inherit that default binding. Future multi-Docker collaboration can extend the same model to multiple named bindings without changing the ownership vocabulary.

Configured Interactive Root Agents may carry an Agent Execution Config. ProgramBench creates a Configured Interactive Root Agent whose ordinary bash actions and spawned Child Agents use the same inherited default Action Environment Binding. Ordinary CLI Interactive Root Agents may remain unconfigured and keep host-local behavior.

A Configured Interactive Root Agent may carry model configuration as the base for spawned autonomous Child Agents, but Root command execution does not query that model. Creating a Configured Interactive Root Agent validates config shape and Action Environment Binding shape, but does not preflight model provider credentials. Credential availability is checked or blocked when autonomous Child execution needs the model.

The Agent Execution Config uses a canonical binding map rather than flat Docker environment fields:

```yaml
environment:
  default_action_environment_id: programbench-cleanroom
  action_environments:
    programbench-cleanroom:
      kind: docker
      scope: shared
      image: programbench/ffmpeg_1776_ffmpeg.360a402:task_cleanroom
      cwd: /workspace
      env: {}
      timeout: 30
      run_args:
        - --network
        - none
      interpreter:
        - bash
        - -lc
```

The project does not preserve a flat Docker compatibility shape because no existing users depend on one. Local execution is represented through the same binding map with a `local` binding kind.

Action Environment IDs must match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`. `default_action_environment_id` must name an existing entry in `action_environments`.

The first implementation supports only these binding combinations:

- `kind: local`, `scope: private`
- `kind: docker`, `scope: shared`

Other combinations such as `docker/private` and `local/shared` are reserved for future design and rejected by validation.

`cwd` has binding-specific meaning. For `local/private`, MAS fixes `cwd` to the absolute host Shared Workspace path. For `docker/shared`, `cwd` is an absolute container-internal workspace path such as `/workspace`, supplied by the binding config or runner. MAS must not overwrite Docker `cwd` with the host Shared Workspace path.

`env` contains non-secret action-time environment variables. For Docker bindings these variables are applied to `docker exec`, not to `docker run`. Runner-internal provisioning environment variables are outside the Agent Execution Config for the first implementation.

## Provisioning Boundary

Action Environment Binding describes execution intent; it does not automatically create Docker containers.

Docker container lifecycle is controlled by the runner or an explicit provisioner. The MAS executor resolves a Docker binding to an already-provisioned live container, serializes bash action execution for that binding, and runs `docker exec`. If the live container cannot be resolved, execution becomes blocked; the executor does not run `docker run`.

Fresh ProgramBench runs provision the cleanroom Docker container before creating the Configured Interactive Root Agent. By default, a fresh run creates a new Root, new container, new trajectories, and a new submission output. Reusing an existing Root or container is an explicit recovery or diagnosis mode, not default benchmark behavior.

Docker container names are derived by MAS from a workspace/runtime namespace and the Action Environment ID. Users configure the Action Environment ID, not the raw Docker container name. Containers should also carry diagnostic labels for workspace, root, and action-environment identity.

For ProgramBench inference, no-network execution is a runner-enforced policy rather than a user option. The runner must provision the Docker container with `--network none`, reject user-supplied Docker run arguments that request a different network mode, and verify the provisioned container's network mode with Docker inspect before MAS execution begins.

The Docker binding resolver uses the deterministic container name as the primary lookup key. Labels are used for verification, diagnosis, and cleanup, not as a first-implementation fallback that silently adopts any matching container. If the named container is missing, stopped, or has mismatched MAS labels, execution becomes blocked rather than falling back to a label-only match.

## Shared Execution

A shared Docker Action Environment is shared by Agents in the same Collaborative Task Run. It is not private to one Child Agent.

The first implementation serializes ordinary bash actions per shared Action Environment Binding. Model calls may still run concurrently in the host Runtime Process Environment. This serialization covers one bash action at a time; it does not provide full read-reason-write transaction isolation across multiple Agent turns.

Per-binding serialization is implemented with an Action Environment Lock. The first implementation uses both a process-local lock keyed by workspace/runtime namespace and Action Environment ID, and a POSIX file lock under `.mini-mas/runtime/action-environment-locks/`. The process-local lock covers concurrent workflows or threads inside one Python process; the file lock covers multiple `mini-mas` processes using the same MAS Runtime State Store.

The Action Environment Lock is held only while one ordinary bash action is executing. It is not a TTL lease and does not use a DBOS dynamic queue. If the process crashes, the OS releases the file lock; any uncertainty about whether the external side effect completed remains a future operation-ledger concern and is not solved by the lock. If lock acquisition fails because the runtime lock cannot be created or opened, the Agent enters `execution_blocked`.

Child Spawn inherits the current default Action Environment Binding. The first implementation does not let Child Spawn choose among multiple bindings or mutate the inherited Docker binding. Model and Agent behavior overrides may still be allowed for spawned Child Agents. This keeps ProgramBench cleanroom image, working directory, and no-network policy stable across cooperating Agents while allowing Child Agents to use different model settings.

## Lifecycle States

Agent lifecycle is separated from runtime model and action-environment availability. A durable Agent does not become terminal merely because the current Runtime Process Environment lacks credentials, the model provider is temporarily unavailable, or an expected Docker Action Environment is not currently provisioned.

Runtime dependency unavailability after an Agent exists makes the Agent enter `execution_blocked`. Repairing the missing dependency does not automatically advance the Agent; a Parent Agent, External MAS CLI, or runner must explicitly continue or retry it.

`recovery_required` remains reserved for uncertain external side effects and replay decisions, especially once bash execution and model calls are protected by an operation ledger. Invalid durable Agent Execution Config remains terminal `failed` because the frozen execution contract itself is invalid.

## Considered Options

- Put Docker lifecycle directly inside MAS bash execution and start missing containers on demand. Rejected because ordinary execution lacks the ProgramBench instance and security context needed to safely choose image, network policy, export path, and cleanup behavior.
- Give each Child Agent a private persistent Docker container. Rejected because MAS is intended for multiple Agents collaborating on the same external task workspace.
- Add a separate run-level durable Action Environment record. Rejected for the first implementation because duplicated inherited Agent Execution Config can carry the binding intent without adding a new durable state model.
- Bind container identity directly to Agent ID. Rejected because shared environments belong to the collaborative action environment binding, not to one Child Agent.
- Treat missing Docker containers or model credentials as terminal `failed`. Rejected because durable Agent lifecycle should remain separable from runtime dependency availability.

## Consequences

ADR 0010's Local Agent Environment-only boundary must be extended for Docker Action Environment support, and its runtime-failure language should be narrowed so runtime dependency unavailability maps to `execution_blocked` rather than terminal `failed`.

ProgramBench support must include a runner-side provisioning path before MAS execution begins, plus export and cleanup behavior after MAS execution ends.

The MAS executor needs a binding resolver and a per-binding bash-action serialization mechanism, but it must not silently weaken ProgramBench cleanroom requirements by provisioning containers itself.

The first ProgramBench runner should not hard-code a multi-Agent topology. It should create a Configured Interactive Root Agent and submit a Root command such as `mini-mas spawn --wait "<task>"`; any further Child Agents are created through normal MAS Commands from autonomous Agents.

For the happy path, the runner treats a Child Agent in `waiting_for_parent` with a submission as ready for workspace export. The runner should close that Child Agent through the Root authority path, then export the shared Docker workspace to `submission.tar.gz`. If the Child reaches `execution_blocked`, `failed`, or `limits_exceeded`, the runner records that status instead of assuming the workspace is a valid submission.

ProgramBench workspace export should exclude MAS/runtime metadata and generic development caches, including `.mini-mas/`, `.git/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.cache/`, nested `node_modules/.cache/`, and `.DS_Store`. It should not broadly exclude project output directories such as `build/`, `dist/`, or `target/` in the first implementation because those names may contain task-relevant files.

ProgramBench runner outputs should follow mini's SWE-bench precedent of keeping diagnostic artifacts inside the per-instance output directory. Because MAS may involve multiple Agents, the ProgramBench runner should copy relevant MAS Trajectory Artifacts into `<run-dir>/<instance_id>/trajectories/` and write a `mas-run.json` manifest that records the instance ID, Root Agent ID, Action Environment ID, Docker container identity, involved Agent IDs, relative trajectory paths, and final export status.

The ProgramBench runner should write a run-level `programbench-mas-results.json` summary instead of reusing SWE-bench's `preds.json` name. The summary maps instance IDs to status, Root Agent ID, Action Environment ID, submission path, and manifest path; the ProgramBench-compatible artifact remains each instance's `submission.tar.gz`.

Future multi-Docker collaboration should add explicit action-to-binding selection semantics. Until then, ordinary bash actions use the one effective default Action Environment Binding.
