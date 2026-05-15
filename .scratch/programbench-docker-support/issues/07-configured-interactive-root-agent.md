# Configured Interactive Root Agent support

Status: needs-triage
Type: AFK

## Parent

.scratch/programbench-docker-support/issues/01-support-programbench-docker-execution.md

## What to build

Allow Interactive Root Agents to carry an optional Agent Execution Config so ProgramBench can create a configured Root whose ordinary bash actions and spawned Child Agents share the same default Action Environment Binding.

## Acceptance criteria

- [ ] Interactive Root workflow input can include an optional Agent Execution Config.
- [ ] Unconfigured CLI Interactive Root behavior remains unchanged.
- [ ] Configured Root ordinary bash uses its default Action Environment Binding.
- [ ] Configured Root creation validates config shape and Action Environment Binding shape.
- [ ] Configured Root creation does not preflight model provider credentials.
- [ ] Configured Root Spawn uses the Root Agent Execution Config as the Child base config.
- [ ] Child Spawn inherits Action Environment Bindings from the configured Root.
- [ ] Child Spawn may override model or Agent behavior settings where existing spawn override semantics allow it.
- [ ] Child Spawn may not override inherited Action Environment Bindings.

## Blocked by

- .scratch/programbench-docker-support/issues/03-action-environment-binding-schema-local-compatibility.md
- .scratch/programbench-docker-support/issues/04-execution-blocked-lifecycle-state.md
- .scratch/programbench-docker-support/issues/06-docker-action-environment-executor-resolver.md

