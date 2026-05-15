# ProgramBench batch runner controls

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Add batch runner controls for processing multiple ProgramBench instances with filtering, slicing, redo/skip behavior, and worker concurrency while preserving one fresh Root/container/output directory per instance by default.

## Acceptance criteria

- [ ] The runner supports filtering instances.
- [ ] The runner supports slicing selected instances.
- [ ] The runner supports redo/skip behavior based on `programbench-mas-results.json`.
- [ ] Each fresh instance run creates a new Configured Interactive Root and provisioned Docker container by default.
- [ ] Worker concurrency does not share container names across instances.
- [ ] Progress or status output follows existing benchmark runner conventions where practical.
- [ ] Default tests cover selection and skip/redo behavior without official image pulls.

## Blocked by

- .scratch/programbench-docker-support/issues/11-programbench-mas-single-instance-runner.md
- .scratch/programbench-docker-support/issues/12-programbench-mas-output-diagnostics.md

