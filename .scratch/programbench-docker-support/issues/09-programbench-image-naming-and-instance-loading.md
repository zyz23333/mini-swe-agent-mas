# ProgramBench image naming and instance loading

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Add the ProgramBench benchmark runner skeleton for selecting ProgramBench instances and mapping instance IDs to official `task_cleanroom` Docker image names.

## Acceptance criteria

- [ ] A helper maps `ffmpeg__ffmpeg.360a402` to `programbench/ffmpeg_1776_ffmpeg.360a402:task_cleanroom`.
- [ ] Tests cover `__` to `_1776_` conversion.
- [ ] The runner can select one ProgramBench instance by ID or filter.
- [ ] Default tests do not require Docker image pulls.
- [ ] The runner module follows existing benchmark CLI conventions where practical without reusing SWE-bench-specific output schema.

## Blocked by

None - can start immediately

