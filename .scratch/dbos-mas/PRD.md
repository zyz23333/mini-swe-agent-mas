# PRD: DBOS-backed mini-swe-agent MAS

Status: needs-triage

## Problem Statement

mini-swe-agent is intentionally small and bash-first, which makes it easy to understand and extend, but it currently runs as a single agent invocation without durable multi-agent coordination. A user who wants one agent to delegate work to other agents needs a way to start, observe, wait for, and continue child work without abandoning mini-swe-agent's existing action parsing model.

The user wants to use DBOS durable workflows, queues, and communication primitives to build a recursive multi-agent system where a **Parent Agent Workflow** can create **Child Agent Workflows**, children can produce submissions and wait for further parent direction, and all of this remains visible to the model as bash-shaped `mini-mas` commands.

## Solution

Add a DBOS-backed MAS subsystem as a parallel extension to mini-swe-agent. The existing `mini` command and core agent classes remain operationally unchanged. A new `mini-mas` entrypoint launches DBOS, starts **Root Agent Workflows**, and provides the external CLI surface for MAS work.

Inside an **Agent Workflow**, a model still emits bash-shaped actions. If the action is a **Standalone MAS Command**, the MAS workflow layer intercepts it and handles coordination directly in-process. If the action is ordinary bash, the command is executed through a DBOS step. This preserves the existing model adapter contract while allowing DBOS to retain parent-child workflow relationships.

The MVP supports recursive delegation through an **Agent Workflow Tree**. **Workflow Tree IDs** use readable, deterministic IDs such as `mas-a7f3c9d4e8b11234-c001-c002`. Every **Agent Workflow** writes a **Trajectory Artifact** under the current **Run Directory**, and MAS commands return exact artifact paths so parent agents can inspect history with ordinary shell tools.

## User Stories

1. As a developer, I want to run `mini-mas` as a separate command, so that I can use MAS features without changing the ordinary `mini` workflow.
2. As a developer, I want DBOS to be installed as a default dependency on this branch, so that MAS works without an optional extra.
3. As a developer, I want the existing `mini` command to avoid DBOS initialization, so that single-agent usage remains operationally simple.
4. As a Parent Agent Workflow, I want to emit `mini-mas spawn "task"` as a bash action, so that I can delegate work while preserving the bash-first interface.
5. As a Parent Agent Workflow, I want `mini-mas spawn` to return child workflow identifiers immediately, so that I can decide when to synchronize.
6. As a Parent Agent Workflow, I want `mini-mas spawn --wait` to wait for first child submissions, so that I can do simple fan-out/fan-in delegation in one action.
7. As a Parent Agent Workflow, I want `mini-mas wait --all`, so that I can gather all currently relevant child submissions.
8. As a Parent Agent Workflow, I want `mini-mas wait --any`, so that I can react to whichever child produces a result first.
9. As a Parent Agent Workflow, I want `mini-mas wait --timeout <seconds>`, so that I can use bounded waiting and regain control if children are still running.
10. As a Parent Agent Workflow, I want `mini-mas status`, so that I can inspect the current Agent Workflow Tree without blocking.
11. As a Parent Agent Workflow, I want `mini-mas status <workflow-id>`, so that I can inspect a specific descendant.
12. As a Parent Agent Workflow, I want `mini-mas continue <workflow-id> "message"`, so that I can ask a Remote Interactive Agent to keep working from its existing trajectory.
13. As a Parent Agent Workflow, I want `mini-mas close <workflow-id>`, so that I can end a Remote Interactive Agent without implying acceptance or rejection.
14. As a Child Agent Workflow, I want to enter `waiting_for_parent` after producing a submission, so that my parent can decide whether I should continue or close.
15. As a Child Agent Workflow, I want a Continuation Signal to become a normal user message in my trajectory, so that I can continue with the same linear message history model.
16. As a Child Agent Workflow, I want a Close Signal to end my workflow, so that I do not keep waiting indefinitely once no further work is requested.
17. As a Descendant Agent Workflow, I want to spawn my own child workflows, so that MAS supports recursive delegation.
18. As a developer, I want workflow IDs to encode tree position, so that recursive relationships are readable in logs and CLI output.
19. As a developer, I want all artifacts for one Root Agent Workflow under one Run Directory, so that history search is scoped and not polluted by unrelated MAS runs.
20. As a Parent Agent Workflow, I want status and wait results to include exact Trajectory Artifact paths, so that I can inspect full child history using ordinary bash tools.
21. As a Parent Agent Workflow, I want `mini-mas` to avoid dedicated history, grep, or logs commands, so that MAS coordination stays separate from shell-based text inspection.
22. As a developer, I want MAS command parsing to require Standalone MAS Commands, so that command interception is predictable and safe.
23. As a developer, I want complex shell combinations containing `mini-mas` to return a clear error, so that agents can correct their next action.
24. As a developer, I want model adapters to continue producing bash-shaped actions, so that MAS does not introduce another model tool schema.
25. As a developer, I want MAS to preserve model-specific observation formatting, so that toolcall, Responses API, and text-based models continue to receive observations correctly.
26. As a developer, I want MAS command dispatch to happen at the workflow layer, so that DBOS workflow-control APIs are not called from steps.
27. As a developer, I want ordinary model calls to be checkpointed as DBOS steps, so that successful model responses can be replayed during workflow recovery.
28. As a developer, I want ordinary bash execution to be checkpointed as DBOS steps, so that successful command outputs can be replayed during workflow recovery.
29. As a developer, I want trajectory saving to use deterministic artifact paths, so that repeated saves are safe and easy to find.
30. As a developer, I want child workflow startup to use deterministic Workflow Tree IDs, so that DBOS recovery does not create duplicate descendants.
31. As a developer, I want a DBOS queue for Child Agent Workflows, so that global child-agent concurrency can be controlled.
32. As a developer, I want MAS to expose lightweight Child Status Events, so that parents can make coordination decisions without reading full trajectories.
33. As a developer, I want MAS to expose `latest_submission` and `latest_error`, so that parent workflows can make fast decisions.
34. As a developer, I want `limits_exceeded` to be a terminal MVP state, so that dynamic child limit changes do not expand the initial scope.
35. As a developer, I want DBOS step side-effect recovery risks documented, so that implementation does not imply exactly-once semantics for arbitrary bash.
36. As a developer, I want Operation Ledger to remain a candidate mitigation, so that recovery policy can be designed deliberately before implementation.
37. As a developer, I want Shared Workspace risks documented, so that MVP users understand that Workspace Isolation is deferred.
38. As a developer, I want MAS to avoid treating bash serialization as Workspace Isolation, so that file-level coordination is not falsely considered solved.
39. As a tester, I want deterministic model and environment doubles, so that MAS workflow behavior can be tested without real LLM calls.
40. As a maintainer, I want the new subsystem separated from the core agent loop, so that future upstream changes to mini-swe-agent remain easier to adopt.

## Implementation Decisions

- MAS is introduced as a parallel DBOS-backed subsystem rather than converting the existing default or interactive agent classes in place.
- `mini-mas` is a separate command entrypoint responsible for DBOS configuration, launch, queue registration, and top-level MAS operations.
- DBOS is a default dependency for this branch, but runtime activation is scoped to `mini-mas`.
- The existing `mini` path does not configure or launch DBOS during ordinary single-agent usage.
- Model adapters keep the existing action parsing contract: all model actions are still bash-shaped actions with a command string.
- MAS does not add a separate `mini-mas` model tool.
- MAS does not modify model-side action parsers.
- MAS does not put workflow coordination inside environment implementations.
- MAS command dispatch happens at the Agent Workflow layer.
- Ordinary bash execution enters an `execute_bash_step`; Standalone MAS Commands enter the workflow-layer MAS dispatcher.
- Model calls, bash execution, and trajectory persistence are DBOS steps.
- Workflow control operations such as spawn, wait, send, receive, and child workflow creation stay outside DBOS steps.
- The MVP command set is limited to `run`, `spawn`, `status`, `wait`, `continue`, and `close`.
- `mini-mas spawn` defaults to Detached Spawn.
- `mini-mas spawn --wait` requests Waited Spawn and waits for first observable submissions, not final workflow completion.
- `mini-mas wait` supports waiting for one workflow, all workflows, any workflow, and bounded timeout-based waiting.
- Remote Interactive Agents wait for either a Continuation Signal or a Close Signal after producing a submission.
- A Continuation Signal is injected into the child trajectory as a normal user message with metadata identifying MAS continuation.
- A Close Signal ends a Remote Interactive Agent and does not mean accepted or aborted.
- Child Status Events are lightweight and include coarse states such as `running`, `waiting_for_parent`, `closed`, `failed`, and `limits_exceeded`.
- The MVP exposes lightweight status, latest submission, and latest error data through DBOS events or status APIs.
- Full history remains in Trajectory Artifacts, not DBOS events.
- `status`, `wait`, and `spawn` outputs include exact Trajectory Artifact paths and the Run Directory.
- Full history search uses ordinary bash tools against Trajectory Artifacts.
- No dedicated `mini-mas history`, `mini-mas logs`, or `mini-mas grep` commands are included in the MVP.
- Standalone MAS Commands must occupy the whole action command.
- Shell operators, environment assignments, loops, pipes, redirections, or embedded `mini-mas` fragments are rejected for MAS interception in the MVP.
- Recursive spawn is supported through an Agent Workflow Tree.
- Root Workflow Tree IDs use `mas-<16hex>`.
- Descendant Workflow Tree IDs append `-cNNN` segments to the parent workflow ID.
- All Agent Workflows in one tree share one Run Directory.
- Trajectory Artifacts live under a trajectories area scoped by the Root Agent Workflow.
- Shared Workspace is allowed for the MVP, but it is a known correctness risk.
- Workspace Isolation is deferred beyond the MVP.
- Global bash command serialization is not considered Workspace Isolation.
- Child Agent Workflow queueing is used for global child-agent concurrency control.
- The MVP does not queue every model or bash step separately for concurrency control.
- Step automatic retries should not be used to mask arbitrary bash side-effect failures.
- `retries_allowed=False` prevents automatic retry within a failed step attempt but does not provide exactly-once semantics.
- DBOS recovery may repeat uncheckpointed model calls or bash commands if the process crashes after an external side effect but before DBOS records the step result.
- Operation Ledger is a candidate mitigation for model and bash operation recovery, but its storage, schema, and recovery policy are not decided by this PRD.

## Testing Decisions

- Tests should validate external behavior: command results, workflow status transitions, emitted messages, returned artifact paths, and durable coordination behavior.
- Tests should avoid asserting incidental implementation details such as private method names or exact internal DBOS function IDs.
- MAS command parsing should be tested as a deep module with accepted standalone commands and rejected shell-composition cases.
- Workflow Tree ID generation should be tested as a deep module with root, child, grandchild, and sibling cases.
- Run Directory and Trajectory Artifact path generation should be tested as a deep module to ensure histories stay scoped to one Root Agent Workflow.
- MAS command dispatch should be tested with deterministic model outputs and fake ordinary bash execution.
- Remote Interactive Agent lifecycle should be tested for first submission, waiting for parent, continue, second submission, and close.
- `spawn` default detach behavior should be tested separately from `spawn --wait`.
- `wait --any`, `wait --all`, and timeout behavior should be tested using deterministic child workflows or DBOS test doubles.
- Status output should be tested to ensure it includes workflow ID, status, latest submission or error, trajectory path, and run directory.
- Observation formatting should be tested with existing model adapter patterns so MAS does not break toolcall, Responses API, or text-based observation handling.
- Existing tests for default and interactive agents provide prior art for deterministic model outputs, message history assertions, and command execution behavior.
- Existing model action parser tests provide prior art for preserving the bash-shaped action contract.
- Existing environment tests provide prior art for command execution outputs and submission detection.
- Existing run/CLI tests provide prior art for command entrypoint behavior.
- DBOS-specific tests should use local test configuration and deterministic workflows rather than real model providers.
- Recovery-risk behavior should be covered at the policy level once Operation Ledger is designed; this PRD only requires that the risk remain visible and not silently implied solved.

## Out of Scope

- Workspace Isolation with per-child worktrees or directories.
- Parent-level patch reconciliation or merge workflow.
- Dedicated history, logs, grep, diff, or inspector commands for `mini-mas`.
- Cancel, kill, retry, fork, and queue mutation commands.
- Dynamic adjustment of child step or cost limits after `limits_exceeded`.
- Full telemetry in DBOS events.
- Exactly-once semantics for arbitrary bash commands.
- A finalized Operation Ledger schema or recovery policy.
- A model-provider-specific idempotency key implementation.
- A separate `mini-mas` model tool schema.
- Direct DBOS conversion of the existing default or interactive agent classes.
- Guaranteeing that multiple Agent Workflows can safely mutate a Shared Workspace.

## Further Notes

This PRD intentionally preserves mini-swe-agent's core philosophy: the model still interacts through bash-shaped commands, and model adapters still parse and format messages through the existing abstraction. MAS adds durable coordination around that interface rather than replacing it.

The biggest unresolved correctness issue is side-effect recovery. Existing mini-swe-agent already has a crash-after-side-effect-before-save window. DBOS recovery makes the window more important because uncheckpointed steps may execute again. The Operation Ledger concept should be evaluated before MAS claims robust recovery for model and bash operations.

The second major unresolved correctness issue is Shared Workspace coordination. DBOS queue concurrency controls capacity; it does not protect the full read-reason-write window across multiple agent turns. Workspace Isolation remains the likely root-cause fix, but it is deliberately outside the MVP.
