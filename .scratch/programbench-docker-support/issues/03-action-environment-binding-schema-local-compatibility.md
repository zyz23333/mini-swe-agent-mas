# Action Environment Binding schema and local compatibility

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Update MAS Agent Execution Config to represent action execution through the canonical `default_action_environment_id` plus `action_environments` binding map, while preserving existing local-only MAS behavior through a `local/private` binding.

## Acceptance criteria

- [ ] Agent Execution Config validation accepts the canonical binding map shape.
- [ ] Local config normalizes to one `local/private` Action Environment Binding.
- [ ] `default_action_environment_id` must reference an existing binding.
- [ ] Action Environment IDs must match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`.
- [ ] Only `kind: local, scope: private` and `kind: docker, scope: shared` are accepted by validation.
- [ ] Flat Docker environment config is not accepted as a compatibility shape.
- [ ] Existing local-only MAS tests continue to pass.
- [ ] Trajectory redaction still redacts Action Environment Variable values.

## Blocked by

None - can start immediately

