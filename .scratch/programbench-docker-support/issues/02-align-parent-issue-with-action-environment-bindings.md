# Align parent issue with Action Environment Binding design

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Update the parent ProgramBench Docker support issue so future implementers follow ADR 0011's Action Environment Binding design instead of the stale per-Agent private-container wording.

## Acceptance criteria

- [ ] The parent issue references ADR 0011 as the accepted Docker action environment design.
- [ ] The stale acceptance criterion about one persistent container per Agent run is replaced with one persistent provisioned container per `docker/shared` Action Environment Binding.
- [ ] The parent issue's design blocker is marked resolved or narrowed to implementation-ready follow-up work.
- [ ] The parent issue keeps ProgramBench cleanroom/no-network and MAS execution requirements intact.

## Blocked by

None - can start immediately

