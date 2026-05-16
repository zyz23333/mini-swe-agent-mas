# ProgramBench MAS Runner

!!! warning "Experimental MAS benchmark runner"

    The ProgramBench runner is currently implemented as a mini-mas benchmark runner. It is intended for local research and diagnosis on this branch, not as a stable public CLI surface.

## Overview

The ProgramBench MAS runner runs mini-mas against [ProgramBench](https://github.com/SWE-bench/ProgramBench) cleanroom tasks.

For each selected ProgramBench instance, the runner:

1. Starts the official `programbench/<instance-id-with-_1776_>:task_cleanroom` Docker image.
2. Creates a configured Interactive Root Agent whose bash actions run inside that Docker container.
3. Sends a root command that spawns one child Agent to solve the ProgramBench task.
4. Waits for the child Agent to submit.
5. Exports the Docker workspace to ProgramBench's expected `<run-dir>/<instance_id>/submission.tar.gz` layout.
6. Copies MAS trajectories and writes per-instance diagnostics next to the submission.

Model calls run from the host process. Bash actions run inside the ProgramBench Docker container. The runner provisions inference containers with `--network none` to preserve ProgramBench's cleanroom requirement.

## Prerequisites

You need:

- A local checkout of ProgramBench at `references/ProgramBench`, or pass `--tasks-dir` pointing at ProgramBench's `src/programbench/data/tasks` directory.
- Docker available on the host.
- A Linux x86_64 host for official ProgramBench Docker images. ProgramBench images are built for `linux/amd64`.
- Model credentials configured for mini-swe-agent, for example through `MSWEA_MODEL_NAME` and provider-specific environment variables.

Example model configuration:

```bash
export MSWEA_MODEL_NAME="deepseek/deepseek-v4-pro"
```

You can also pass the model explicitly with `--model`.

## Running One Instance

Run the module directly:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m minisweagent.run.benchmarks.programbench_mas \
  --instance xorg62__tty-clock.f2f847c \
  --output .scratch/programbench-runs/tty-clock-pro \
  --workers 1 \
  --result-timeout 5400
```

Useful flags:

- `-i`, `--instance` - Run one ProgramBench instance ID.
- `-o`, `--output` - Output run directory.
- `-m`, `--model` - Override the model for this run.
- `-c`, `--config` - Override or extend the runner config. The default is `src/minisweagent/config/benchmarks/programbench_mas.yaml`.
- `--result-timeout` - How long the runner waits for the child Agent to become ready or submit. ProgramBench reverse-engineering tasks can need much longer than the default.
- `--docker-executable` - Docker executable name or path.

The command prints the follow-up ProgramBench eval command when it finishes.

## Running A Batch

Use filters, slices, and worker concurrency for batch runs:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m minisweagent.run.benchmarks.programbench_mas \
  --filter 'xorg62|bootandy' \
  --slice 0:5 \
  --output .scratch/programbench-runs/sample \
  --workers 2 \
  --result-timeout 5400
```

Data selection flags:

- `--filter` - Regex over ProgramBench instance IDs.
- `--slice` - Python-like slice over the selected instance list, such as `0:10`.
- `--shuffle` - Shuffle selected instances deterministically before slicing.
- `--redo-existing` - Re-run instances already recorded in `programbench-mas-results.json`.
- `--tasks-dir` - ProgramBench task metadata directory. Defaults to `references/ProgramBench/src/programbench/data/tasks`.

Each selected instance gets a fresh Root Agent, Docker container, trajectories, and submission output by default.

## Evaluating Outputs

The runner writes ProgramBench-compatible submissions under the output directory:

```text
<run-dir>/
├── programbench-mas-results.json
└── <instance_id>/
    ├── submission.tar.gz
    ├── mas-run.json
    └── trajectories/
        ├── <root-agent-id>.traj.json
        └── <child-agent-id>.traj.json
```

Evaluate the run with ProgramBench:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --project references/ProgramBench programbench eval \
  .scratch/programbench-runs/sample \
  --docker-cpus 4
```

Show the summary again later:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --project references/ProgramBench programbench info \
  .scratch/programbench-runs/sample
```

ProgramBench writes `<instance_id>.eval.json` files into each instance directory.

## Submission Contract

ProgramBench's evaluator expects every `submission.tar.gz` to contain a workspace that can build `./executable`.

The default ProgramBench MAS prompt tells the Agent this contract explicitly:

```text
The final workspace must include compile.sh.
ProgramBench evaluation runs: chmod +x ./compile.sh && ./compile.sh.
compile.sh must build or create ./executable in the workspace root.
Hidden tests execute ./executable.
```

This matters because model self-validation can pass with another binary name, such as `./tty-clock`, while ProgramBench still reports `compile_failed` if `compile.sh` is missing or does not produce `./executable`.

For example, a C task might produce:

```bash
#!/usr/bin/env bash
set -euo pipefail

gcc -Wall -Wextra -I. -o executable tty-clock.c -l:libncurses.so.6 -l:libtinfo.so.6 -lm
```

## Diagnostics

Use `mas-run.json` first to inspect one instance:

```bash
jq . .scratch/programbench-runs/sample/<instance_id>/mas-run.json
```

Important fields:

- `status` - Runner status, such as `submitted`, `failed`, `limits_exceeded`, or `not_submitted`.
- `root_agent_id` - The configured Interactive Root Agent.
- `agent_ids` - Agents involved in this ProgramBench instance.
- `action_environment_id` and `docker_container_name` - Docker action environment identity.
- `submission_path` - Relative path to `submission.tar.gz`.
- `trajectory_paths` - Copied MAS trajectories for debugging.

If ProgramBench eval reports `compile_failed`, inspect the eval JSON:

```bash
jq '{error_code, error_details, log}' \
  .scratch/programbench-runs/sample/<instance_id>/<instance_id>.eval.json
```

Common causes:

- `compile.sh` is missing from the submitted workspace.
- `compile.sh` succeeds but does not create `./executable`.
- The Agent built a correctly named local binary during self-test but did not encode that build in `compile.sh`.
- The evaluator removed the original black-box `./executable` before running `compile.sh`, so the submission relied on a file that is not present during evaluation.

## Runtime Model

The ProgramBench MAS runner starts a supervised MAS runtime session for the benchmark process. This is different from using `mini-mas agent activate` for an ordinary external Interactive Root Agent.

In a normal run, the topology is:

```text
ProgramBench runner process
└── Configured Interactive Root Agent
    └── Child Agent solving the ProgramBench task
```

The Root exists to own the configured Docker Action Environment Binding and to submit the child spawn command. The child Agent does the actual ProgramBench reverse-engineering work. If the child Agent calls `mini-mas spawn` itself, that creates additional direct children in the same shared Docker workspace.

The runner owns Docker lifecycle for ProgramBench:

- It starts the cleanroom container before MAS execution.
- MAS bash execution resolves the configured Docker binding.
- The executor does not start missing ProgramBench containers on demand.
- The runner exports the workspace and cleans up the container after execution.

## Implementation

??? note "Default ProgramBench MAS config"

    ```yaml
    --8<-- "src/minisweagent/config/benchmarks/programbench_mas.yaml"
    ```

??? note "`programbench_mas.py` run script"

    ```python
    --8<-- "src/minisweagent/run/benchmarks/programbench_mas.py"
    ```

