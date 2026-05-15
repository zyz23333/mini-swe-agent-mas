# Runner-side Docker provisioning utility

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Add a runner-side Docker provisioning utility that creates, verifies, and cleans up the already-provisioned Docker container expected by MAS `docker/shared` Action Environment Bindings.

## Acceptance criteria

- [ ] The provisioner derives the same deterministic container name used by the Docker binding resolver.
- [ ] The provisioner applies MAS diagnostic labels for workspace/runtime namespace, Root Agent ID when available, Action Environment ID, and binding kind.
- [ ] The provisioner creates ProgramBench containers with `--network none`.
- [ ] User-supplied Docker run arguments that request a different network mode are rejected for ProgramBench inference.
- [ ] The provisioner verifies the container network mode with Docker inspect before MAS execution.
- [ ] The provisioner verifies the created container is running.
- [ ] Cleanup removes the provisioned container.
- [ ] Default tests do not pull official ProgramBench images.

## Blocked by

- .scratch/programbench-docker-support/issues/06-docker-action-environment-executor-resolver.md

