# ProgramBench eval handoff

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Provide a clear handoff from mini-mas ProgramBench outputs to `programbench eval`, including documentation or runner output and local smoke coverage where practical.

## Acceptance criteria

- [ ] The runner prints the follow-up command `uv run --project references/ProgramBench programbench eval <run-dir>` or documentation includes it.
- [ ] The documented eval handoff points at the run directory containing per-instance `submission.tar.gz` files.
- [ ] Default tests do not require official ProgramBench image pulls.
- [ ] Local fixture coverage verifies the generated output directory shape is suitable for the ProgramBench eval path where practical.

## Blocked by

- .scratch/programbench-docker-support/issues/11-programbench-mas-single-instance-runner.md

