# ProgramBench MAS single-instance runner

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Wire the single-instance ProgramBench runner end to end through MAS: provision the cleanroom Docker Action Environment Binding, create a Configured Interactive Root, submit a Root spawn command, wait for the Child result, close the submitted Child, export the workspace, and clean up.

## Acceptance criteria

- [ ] The runner drives execution through a Configured Interactive Root Agent rather than constructing a regular `DefaultAgent`.
- [ ] The runner submits a Root command such as `mini-mas spawn --wait "<task>"`.
- [ ] Model calls remain in the host Runtime Process Environment.
- [ ] Ordinary bash actions execute through the `docker/shared` Action Environment Binding.
- [ ] A Child in `waiting_for_parent` with a submission is treated as ready for workspace export.
- [ ] The runner closes the submitted Child through the Root authority path before or as part of finalization.
- [ ] `execution_blocked`, `failed`, and `limits_exceeded` are recorded instead of being treated as valid submissions.
- [ ] The runner exports `submission.tar.gz` in the ProgramBench eval format.
- [ ] Default tests use deterministic models and mocked or tiny local Docker fixtures.

## Blocked by

- .scratch/programbench-docker-support/issues/07-configured-interactive-root-agent.md
- .scratch/programbench-docker-support/issues/08-runner-side-docker-provisioning.md
- .scratch/programbench-docker-support/issues/09-programbench-image-naming-and-instance-loading.md
- .scratch/programbench-docker-support/issues/10-programbench-workspace-export.md

