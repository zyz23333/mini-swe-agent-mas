# DBOS Workflow Agent Overview

## Purpose

This design captures the first version of a DBOS-backed mini-SWE-agent run mode.
The goal is to keep the familiar mini-SWE-agent programming model while adding
durable workflow execution, durable approval waits, and explicit control-plane
commands for checking, watching, approving, denying, and cancelling an agent run.

The new mode is intentionally separate from the existing `mini` command. The
existing local interactive agent remains unchanged. The DBOS-backed agent is
exposed through a new `mini-dbos` entry point.

## Problem

The current `mini` CLI runs as a synchronous local process. Its state lives in
memory during execution and is periodically saved to a trajectory file. User
confirmation is handled by blocking terminal prompts inside the agent process.

This makes the current design simple, but it has important limits:

- If the process dies, in-memory state and terminal prompts are lost.
- A model query or shell action can be repeated after a restart unless the caller
  manually reconstructs what happened.
- Confirmation waits are tied to a specific terminal process.
- There is no durable workflow id that external commands can inspect or respond
  to.

The DBOS-backed mode addresses these limits by making the agent loop a durable
workflow and by representing approval waits as durable workflow receive points.

## Goals

- Provide a DBOS-backed agent run mode through `mini-dbos`.
- Support strong recovery at the completed DBOS step boundary.
- Avoid repeating completed model calls after recovery.
- Avoid repeating completed shell actions after recovery.
- Support durable user waits for command approval and exit approval.
- Preserve the default start-detached workflow behavior.
- Provide CLI commands to watch, check, approve, deny, and cancel workflows.
- Keep `mini` unchanged.
- Use the existing `mini.yaml` configuration as the default configuration source.
- Add DBOS-specific defaults under a `dbos` section in `mini.yaml`.
- Support local environment execution in the first version.
- Continue writing an internal trajectory file for compatibility and debugging,
  but do not make trajectory files part of the user-facing control plane.

## Non-Goals

- Do not replace the existing `mini` implementation.
- Do not make `mini` automatically use DBOS.
- Do not support `human` mode in the first DBOS version.
- Do not support every existing environment backend in the first version.
- Do not rely on trajectory files as the recovery source.
- Do not expose `-o` or `--output` for DBOS trajectory paths in the first version.
- Do not build a web inbox UI in the first version.
- Do not make DBOS streams a replacement for trajectories.
- Do not provide arbitrary user message injection while the workflow is running.
- Do not guarantee exactly-once shell side effects across a crash that happens
  after a shell command mutates the outside world but before DBOS records the
  step result.

## Execution Model

The first version uses a workflow-native agent design instead of subclassing the
existing `InteractiveAgent` run loop.

The workflow owns serializable agent state:

- task
- messages
- cost
- model call count
- mode
- frozen non-secret configuration snapshot
- workflow id
- status metadata

External effects are executed inside DBOS steps:

- model calls
- local shell actions
- trajectory writes, if implemented as steps

The workflow itself coordinates deterministic control flow:

- initialize state
- call model step
- append assistant message
- request approval if needed
- wait for approval or denial
- execute action steps
- append observation messages
- handle submission
- publish status events
- publish timeline stream events
- finish or fail

## Recovery Semantics

The target recovery level is strong recovery at the DBOS step boundary.

If the workflow crashes after a model query step has completed and DBOS has
recorded the result, recovery must not call the model again for that same agent
step.

If the workflow crashes after an action execution step has completed and DBOS has
recorded the result, recovery must not execute that action again.

This is not a transactional guarantee for arbitrary shell side effects. A local
shell command can still mutate files or external systems before DBOS has recorded
the step result. If the process crashes in that narrow window, DBOS cannot know
the external side effect happened. The first version accepts this boundary and
uses approval gates for safety.

## User Interaction Model

The user-facing interaction is still terminal-first, but terminal input is not
read inside the workflow.

Instead:

- the workflow writes a pending request to its status event
- the workflow waits using DBOS receive
- the CLI reads status and timeline information
- the CLI prompts the terminal user when watching a pending workflow
- the CLI sends approval or denial messages back to the workflow

This keeps terminal interaction familiar while making the wait durable.

## Supported Modes

The first version supports:

- `confirm`
- `yolo`

The first version does not support:

- `human`

In `confirm` mode, the workflow creates pending requests before executing model
proposed actions and before accepting an agent submission.

In `yolo` mode, action approval is skipped. Exit approval behavior follows the
configured confirmation policy, but the first version should be explicit in the
CLI and status output about whether exit confirmation is enabled.

## Configuration

The DBOS-backed command uses the existing configuration system and default
`mini.yaml`.

DBOS-specific settings live in a top-level `dbos` section. Example:

```yaml
dbos:
  application_name: mini-dbos
  approval_timeout_seconds: 604800
  timeline_stream_key: timeline
  status_event_key: agent_status
```

Configuration is frozen at workflow start for non-secret behavior settings. This
includes model name, model class, model kwargs, environment config, prompts,
limits, mode, and DBOS agent settings.

Secrets such as API keys are not frozen into workflow inputs. They continue to be
read from the environment at runtime by the existing model/provider code.

## Dependency Decision

DBOS is a main dependency on this branch.

This branch is specifically intended to add DBOS workflow execution. Users who do
not want DBOS can use the upstream branch. Making DBOS a main dependency avoids
optional-extra installation branches and keeps the new command path direct.

## Environment Scope

The first version supports only the local environment.

This keeps the environment state model simple. Local shell side effects are
visible through the filesystem across DBOS steps because each step runs in the
same working tree.

Other environments require additional lifecycle design:

- stable container or sandbox identity
- provisioning
- reconnect on recovery
- cleanup on completion or cancellation
- failure behavior if the backing environment disappears

Those are deferred.

## Trajectory Decision

The first version still writes an internal trajectory file, but the control plane
does not depend on it.

The workflow recovery source is DBOS state, not the trajectory file. `--check`
and `--watch` read DBOS status events and DBOS timeline stream entries, not the
trajectory.

The trajectory remains useful for compatibility, inspector workflows, debugging,
and offline analysis. The path is internal and not configurable in the first
version. The default internal path is:

```text
<global_config_dir>/dbos-runs/<workflow_id>/<workflow_id>.traj.json
```

The default human-readable `--check` output does not show this path. Verbose
check output may include it as an implementation detail.

## Event and Stream Roles

The DBOS status event and timeline stream have separate roles.

The status event is the current state snapshot. It is used by `--check`,
`--approve`, `--deny`, and watcher logic.

The timeline stream is the append-only run history. It is used by `--watch` to
replay and follow workflow progress.

The first version writes full assistant messages and full action outputs to the
timeline stream. This is simple and makes watch output self-contained. It can
increase DBOS system database size. A later version may add truncation or external
large-output storage.

## Open Risks

- Stream storage can grow quickly because full model messages and full command
  outputs are written to DBOS.
- Local shell commands are not transactionally exactly-once across the narrow
  crash window before DBOS records a step result.
- Long-running shell commands may not be gracefully cancellable.
- Secrets are not frozen in workflow input, so recovery depends on the runtime
  environment still having the required API keys.
- The first version does not support remote or container environments.
- Multiple watchers can respond to the same pending workflow, so request id
  validation is required.
