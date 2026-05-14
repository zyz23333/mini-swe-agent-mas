# Support ProgramBench Docker execution for mini-mas

Status: needs-triage
Type: HITL

## What to build

Add ProgramBench support for mini-mas in two connected pieces:

1. A mini-mas Docker action environment capability that lets autonomous Agents execute bash actions inside a persistent Docker container while model calls, provider credentials, MAS Runtime State Store access, and DBOS workflow execution remain in the host Runtime Process Environment.
2. A mini-mas ProgramBench benchmark runner, similar in spirit to `swebench.py` but using MAS Agent execution, that runs one or more ProgramBench instances in their official `task_cleanroom` Docker images and writes ProgramBench-compatible `submission.tar.gz` outputs.

The runner must exercise mini-mas rather than bypassing it with the ordinary mini `DefaultAgent` loop. It should establish ProgramBench instance loading, Docker image naming, no-network inference containers, MAS trajectory saving, workspace export, and `programbench eval` handoff through the same Docker action environment path used by autonomous MAS Agents.

The MAS path must preserve the current MAS Governance vocabulary and constraints: a spawned Child Agent receives a frozen Agent Execution Config, model provider credentials remain outside durable workflow input, and Docker support must not silently weaken ProgramBench's cleanroom requirement by giving shell actions internet access.

## Acceptance criteria

- [ ] A mini-mas `programbench.py` benchmark runner can run a selected ProgramBench instance using the official `programbench/<instance-id-with-_1776_>:task_cleanroom` image.
- [ ] The runner drives the task through MAS Agent execution rather than constructing and running a regular `DefaultAgent` directly.
- [ ] The runner executes model calls from the host process while bash actions run inside the ProgramBench Docker container.
- [ ] The runner can pass Docker run arguments that disable container networking during inference, such as `--network none`.
- [ ] The runner writes outputs in ProgramBench eval format: `<run-dir>/<instance_id>/submission.tar.gz`.
- [ ] The runner saves or links MAS Trajectory Artifacts next to the ProgramBench submission output for diagnosis.
- [ ] The runner can hand the output directory to `uv run --project references/ProgramBench programbench eval ...` or documents the exact follow-up command.
- [ ] ProgramBench image naming is covered by tests, including the `__` to `_1776_` conversion.
- [ ] Submission archive creation is covered by tests and excludes runner/MAS artifacts such as `.mini-mas/`, trajectories, caches, and temporary files.
- [ ] mini-mas Agent Execution Config validation explicitly represents whether an autonomous Agent uses a Local Agent Environment or a Docker action environment.
- [ ] A Docker-backed autonomous Agent reuses one persistent container for all bash actions in that Agent run; it must not create a fresh container for each action.
- [ ] MAS Docker support has explicit lifecycle and recovery behavior for DBOS workflow interruption or process restart, even if the first implementation chooses "fail and require rerun" instead of recovery.
- [ ] MAS Docker support keeps model queries in host Runtime Process Environment steps and does not store provider credentials in Agent Execution Config, Child Status Events, or Trajectory Artifacts.
- [ ] Documentation explains the difference between running mini/mini-mas on the host with Docker action execution and installing mini-mas inside a ProgramBench task container.
- [ ] Tests cover local-only MAS behavior so existing Shared Workspace semantics do not regress.
- [ ] Tests cover Docker action execution behavior without requiring real ProgramBench images in the default test suite, using a small local or mocked Docker environment.

## Blocked by

- Human design review of the MAS Docker action environment lifecycle and DBOS recovery contract.

## Suggested vertical slices

1. **MAS Docker action environment design** - HITL, blocked by none.
   Decide the durable contract for Docker-backed Agents: container identity storage, recovery behavior, cleanup, network policy, artifact export, and how this extends Agent Execution Config beyond the current Local Agent Environment MVP.

2. **MAS Docker action environment tracer bullet** - AFK after slice 1.
   Implement the narrowest Docker-backed autonomous Agent path that reuses one container per Agent run and preserves existing model-query, trajectory, and MAS Command Interception boundaries.

3. **ProgramBench single-instance mini-mas runner** - AFK after slice 2.
   Build the mini-mas ProgramBench tracer bullet: load one instance, configure a Docker-backed MAS Agent against `task_cleanroom`, run it to completion, export `submission.tar.gz`, and document the `programbench eval` command.

4. **ProgramBench runner batch and smoke coverage** - AFK after slice 3.
   Add filtering/slicing, multiple workers if consistent with existing benchmark utilities, and tests around image naming, MAS trajectory linking, and archive layout. Keep real Docker/ProgramBench image pulls out of default tests.

5. **ProgramBench eval handoff for mini-mas outputs** - AFK after slice 3.
   Provide a documented or automated handoff from mini-mas ProgramBench run directories to `programbench eval`, including local smoke coverage using a small fixture or mocked ProgramBench layout.

## Notes

- Current MAS Agent Execution Config version 1 intentionally supports only Local Agent Environment. Extending it for Docker action execution should update ADR-0010 or add a new ADR because it changes a documented MVP boundary.
- Do not implement the workaround where the entire mini-mas runtime is installed inside the ProgramBench task container as the primary path. That approach makes model API networking and ProgramBench no-network shell execution harder to separate.
- Do not satisfy this issue with a regular mini `DefaultAgent` ProgramBench runner. The runner in scope is a mini-mas runner and should exercise MAS Agent execution.
- ProgramBench official inference uses `task_cleanroom` images. ProgramBench evaluation uses `task` images through the ProgramBench CLI.
- The local calculator smoke fixture under `references/ProgramBench` is useful for eval-pipeline tests, but it is not an official public ProgramBench Docker image.

## Comments

> *This was generated by AI during issue creation.*
>
> Conversation context: the local ProgramBench eval smoke test succeeded after creating a temporary `.scratch/programbench-smoke` calculator fixture and local Docker image. The smoke test verified the eval side of the contract: `submission.tar.gz` is unpacked, `compile.sh` runs, `executable` is produced, tests are injected from a blob, and ProgramBench writes an eval JSON with three passing tests.
>
> The remaining product gap is inference: mini-mas must generate `submission.tar.gz` from official ProgramBench `task_cleanroom` images. Ordinary mini already has a persistent `DockerEnvironment`, but that is not the target of this issue. mini-mas currently normalizes autonomous Agent Execution Config to Local Agent Environment and needs a deliberate Docker action environment design before a mini-mas `programbench.py` runner can execute ProgramBench cleanroom commands correctly.
