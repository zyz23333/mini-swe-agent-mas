# ProgramBench MAS output diagnostics

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Make ProgramBench MAS runner outputs diagnosable and self-contained by copying relevant MAS trajectories into each instance directory and writing per-instance and run-level manifests.

## Acceptance criteria

- [ ] Relevant MAS Trajectory Artifacts are copied into `<run-dir>/<instance_id>/trajectories/`.
- [ ] Trajectory output is not symlink-only.
- [ ] `<run-dir>/<instance_id>/mas-run.json` records instance ID, Root Agent ID, Action Environment ID, Docker container identity, involved Agent IDs, relative trajectory paths, and final export status.
- [ ] `<run-dir>/programbench-mas-results.json` maps instance IDs to status, Root Agent ID, Action Environment ID, submission path, and manifest path.
- [ ] The ProgramBench-compatible artifact remains `<run-dir>/<instance_id>/submission.tar.gz`.
- [ ] Tests cover manifest shape and trajectory copy behavior.

## Blocked by

- .scratch/programbench-docker-support/issues/11-programbench-mas-single-instance-runner.md

