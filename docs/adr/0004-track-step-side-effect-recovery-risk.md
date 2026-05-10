# Track Step Side Effect Recovery Risk

DBOS MAS must treat model calls and bash execution as external side effects whose results are checkpointed only after the step completes. Existing mini-swe-agent already has a crash-after-side-effect-before-trajectory-save window, but DBOS recovery makes that window more significant because an uncheckpointed step may be executed again during recovery.

**Consequences**

`retries_allowed=False` prevents automatic retry within a failed step attempt, but it does not provide exactly-once semantics for model calls or arbitrary bash commands. If a process crashes after an external side effect happens but before DBOS records the step result, recovery may repeat that side effect unless MAS adds another guard.

**Candidate Mitigation**

An Operation Ledger is a candidate mitigation for model and bash operations. It would give each logical operation a stable operation identifier and record whether that operation was started or completed before deciding whether recovery should reuse a recorded result, retry, or fail closed. The exact storage, schema, and recovery policy are intentionally left undecided.

**Spawn Recovery Remains Undecided**

Parent-local Spawn Index metadata should be stable enough for display and audit, but replay after a crash could duplicate child creation or assign later indexes unless spawn operations become ledgered. The current design records Spawn Index as metadata and intentionally defers exactly-once spawn recovery semantics to the broader recovery design.
