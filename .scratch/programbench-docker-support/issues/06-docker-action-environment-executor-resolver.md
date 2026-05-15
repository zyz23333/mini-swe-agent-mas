# Docker Action Environment executor resolver

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Implement the `docker/shared` ordinary bash execution path for already-provisioned Docker containers, preserving MAS command interception and host-side model execution.

## Acceptance criteria

- [ ] The executor resolves Docker containers by deterministic container name derived from workspace/runtime namespace and Action Environment ID.
- [ ] The executor verifies MAS Docker labels before executing bash.
- [ ] The executor verifies the named container is running.
- [ ] The executor never calls `docker run` or provisions missing containers.
- [ ] Missing, stopped, or label-mismatched containers produce `execution_blocked`.
- [ ] `docker/shared` `cwd` is treated as a container-internal path.
- [ ] `docker/shared` `env` is passed to `docker exec` as action-time environment variables.
- [ ] Ordinary bash actions acquire the Action Environment Lock before `docker exec`.
- [ ] Standalone `mini-mas ...` commands are still intercepted in-process and are not sent to Docker.
- [ ] Default tests use mocked Docker or a tiny local fixture, not official ProgramBench images.

## Blocked by

- .scratch/programbench-docker-support/issues/03-action-environment-binding-schema-local-compatibility.md
- .scratch/programbench-docker-support/issues/04-execution-blocked-lifecycle-state.md
- .scratch/programbench-docker-support/issues/05-action-environment-lock.md

