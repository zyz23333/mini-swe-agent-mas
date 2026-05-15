# ProgramBench workspace export

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Export the shared Docker workspace for one ProgramBench instance into ProgramBench-compatible `<run-dir>/<instance_id>/submission.tar.gz`.

## Acceptance criteria

- [ ] Export reads from the `docker/shared` binding's container-internal `cwd`.
- [ ] The generated archive is written to `<run-dir>/<instance_id>/submission.tar.gz`.
- [ ] The archive root layout matches ProgramBench evaluation expectations.
- [ ] Export excludes `.mini-mas/`, `.git/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.cache/`, nested `node_modules/.cache/`, and `.DS_Store`.
- [ ] Export does not broadly exclude `build/`, `dist/`, or `target/`.
- [ ] Export preserves executable bits and useful file metadata.
- [ ] Tests use local fixtures and tar inspection.

## Blocked by

- .scratch/programbench-docker-support/issues/08-runner-side-docker-provisioning.md

