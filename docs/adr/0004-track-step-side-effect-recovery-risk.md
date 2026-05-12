# Track Step Side Effect Recovery Risk

DBOS MAS must treat model calls and bash execution as external side effects whose results are checkpointed only after the step completes. Existing mini-swe-agent already has a crash-after-side-effect-before-trajectory-save window, but DBOS recovery makes that window more significant because an uncheckpointed step may be executed again during recovery.

**Consequences**

`retries_allowed=False` prevents automatic retry within a failed step attempt, but it does not provide exactly-once semantics for model calls or arbitrary bash commands. If a process crashes after an external side effect happens but before DBOS records the step result, recovery may repeat that side effect unless MAS adds another guard.

**Candidate Mitigation**

An Operation Ledger is a candidate mitigation for model and bash operations. It would give each logical operation a stable operation identifier and record whether that operation was started or completed before deciding whether recovery should reuse a recorded result, retry, or fail closed. The exact storage, schema, and recovery policy are intentionally left undecided.

**MVP Recovery Policy**

The MVP should fail closed against automatic replay when a ledgered external side effect is in an uncertain state. Failing closed means the Agent enters `recovery_required` instead of silently repeating the model call, bash action, or spawn operation. A parent or external user may later make an explicit recovery decision, but the MAS runtime must not treat the Agent's own inference as proof that the uncertain side effect completed safely.

`recovery_required` is distinct from `waiting_for_parent`. `waiting_for_parent` means a Remote Interactive Agent submitted work and is waiting for ordinary parent direction. `recovery_required` means automatic advancement is blocked because recovery found an uncertain side effect. Ordinary `mini-mas continue` should remain valid only for `waiting_for_parent`; the MVP recovery unblock path should use an explicit command shape such as `mini-mas continue --recovery <agent-id> "message"`, which sends a recovery-specific continuation signal rather than an ordinary Continuation Signal.

**Spawn Recovery Remains Undecided**

Replay after a crash could duplicate child creation unless spawn operations become ledgered. The current design does not assign durable sibling-order metadata and intentionally defers exactly-once spawn recovery semantics to the broader recovery design.

Future investigation should cover DBOS transactions and direct database-backed enqueue paths for MAS commands such as spawn. The goal is to determine whether child workflow creation, operation ledger writes, and enqueue records can share a safer atomic boundary than the current workflow-layer command execution.
