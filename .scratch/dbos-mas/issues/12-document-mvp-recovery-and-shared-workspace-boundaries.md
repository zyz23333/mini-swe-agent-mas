# Document MVP recovery and Shared Workspace boundaries

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Document the MVP boundaries that must remain visible to users and implementers: `mini-mas` does not include dedicated history, logs, grep, diff, or inspector commands; DBOS step checkpointing does not provide exactly-once semantics for arbitrary bash; Operation Ledger remains only a candidate mitigation; and Shared Workspace is not Workspace Isolation.

This slice should update canonical documentation and CLI help text where appropriate so MAS does not imply stronger correctness guarantees than it actually provides.

## Acceptance criteria

- [ ] Documentation states that full history inspection uses ordinary shell tools against exact Trajectory Artifact paths.
- [ ] Documentation and CLI help do not advertise dedicated `mini-mas history`, `mini-mas logs`, `mini-mas grep`, `mini-mas diff`, or inspector commands.
- [ ] Documentation explains that `retries_allowed=False` does not provide exactly-once semantics for arbitrary bash side effects.
- [ ] Documentation keeps Operation Ledger as a candidate mitigation, not a finalized schema or recovery policy.
- [ ] Documentation explains that Shared Workspace is allowed for the MVP but does not provide Workspace Isolation.
- [ ] Tests or documentation checks cover the relevant CLI help text when such help text exists.

## Blocked by

- .scratch/dbos-mas/issues/04-execute-model-and-bash-steps-through-dbos-checkpoints.md
- .scratch/dbos-mas/issues/05-support-detached-spawn-with-deterministic-child-ids.md

