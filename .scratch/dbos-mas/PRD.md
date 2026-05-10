# PRD: DBOS-backed mini-swe-agent MAS

Status: needs-triage

## Problem Statement

mini-swe-agent is intentionally small and bash-first, which makes it easy to understand and extend, but it currently runs as a single agent invocation without durable multi-agent governance. A user who wants one agent to delegate work to other agents needs a way to start, observe, wait for, and continue child work without abandoning mini-swe-agent's existing action parsing model.

The user wants to use DBOS durable workflows, queues, events, and communication primitives to build a recursive multi-agent system where a **Parent Agent** can create **Child Agents**, children can become observable through submissions, failures, or limits, and children can wait for further parent direction. All of this remains visible to the model as bash-shaped `mini-mas` commands.

## Solution

Add a DBOS-backed MAS subsystem as a parallel extension to mini-swe-agent. The existing `mini` command and core agent classes remain operationally unchanged. A new `mini-mas` entrypoint launches DBOS and starts **Root Agents**. Agent Interaction commands such as `status`, `wait`, `continue`, and `close` are intended to execute inside an **Agent** through MAS Command Interception; naked external/operator query or control paths are not part of the maintained design while the Interactive Root Agent model is deferred.

Inside an **Agent**, a model still emits bash-shaped actions. If the action is a **Standalone MAS Command**, the MAS workflow layer intercepts it and handles Agent Interactions directly in-process. If the action is ordinary bash, the command is executed through a DBOS step. This preserves the existing model adapter contract while allowing DBOS to retain parent-child workflow relationships.

The MVP supports recursive delegation through an **Agent Tree**. **Agent IDs** use readable, deterministic IDs such as `mas-a7f3c9d4e8b11234-c001-c002`. Every **Agent** writes a **Trajectory Artifact** under the current **Run Directory**, and MAS commands return exact artifact paths so parent agents can inspect history with ordinary shell tools.

The MVP uses a **Direct Child Authority Policy** for MAS Governance. A **Parent Agent** can perform Agent Interactions only on its direct **Child Agents** by default. The child agent of my child agent is not my child agent: a grandchild is part of the same **Agent Tree**, but it is not controlled by the grandparent unless a future **Authority Model** introduces broader **Authority Grants**. The **Root Agent** has no special tree-wide authority under the MVP policy.

Workflow-layer MAS Commands derive the current **Parent Agent** identity from DBOS-managed workflow context, specifically `DBOS.workflow_id`. They do not accept or maintain `root_workflow_id`, a caller-supplied current Agent ID, a DBOS API object, or an external operator identity as authority inputs. Direct-child scope is resolved from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`. Agent ID prefixes and root Agent IDs are naming, display, and artifact-path data only; they are not authorization sources.

`mini-mas spawn` accepts repeated task arguments such as `mini-mas spawn "task A" "task B"` and starts one Child Agent per task. `mini-mas spawn --wait` defaults to waiting for any started child to publish a First Observable Event; `mini-mas spawn --wait --all` waits for all started children to become observable. `mini-mas spawn --wait --timeout <seconds>` bounds only the waiting phase and does not cancel, close, fail, or retry started children.

Wait operations use direct child Agent IDs to wait for First Observable Events, not final DBOS workflow results. `mini-mas wait` waits over the current Parent Agent's direct children; `mini-mas wait <agent-id>` waits for one explicit target only after validating that the target is a direct Child Agent of the current Parent Agent. Child-to-parent observable state is published through DBOS events keyed by child Agent IDs; parent-to-child Continuation Signals and Close Signals are delivered as DBOS workflow messages only across a direct parent-child boundary.

During `mini-mas wait` and the wait phase of `mini-mas spawn --wait`, the waiting Agent may publish `waiting_for_child` as its latest lightweight lifecycle state. This state means the Agent is waiting for direct Child Agent First Observable Events. It is not itself a First Observable Event, does not make the Agent parent-actionable, and does not authorize parent-direction signals.

## User Stories

1. As a developer, I want to run `mini-mas` as a separate command, so that I can use MAS features without changing the ordinary `mini` workflow.
2. As a developer, I want DBOS to be installed as a default dependency on this branch, so that MAS works without an optional extra.
3. As a developer, I want the existing `mini` command to avoid DBOS initialization, so that single-agent usage remains operationally simple.
4. As a Parent Agent, I want to emit `mini-mas spawn "task"` as a bash action, so that I can delegate work while preserving the bash-first interface.
5. As a Parent Agent, I want to emit `mini-mas spawn "task A" "task B"` as a bash action, so that I can start multiple Child Agents in one command.
6. As a Parent Agent, I want `mini-mas spawn` to return child Agent IDs, Run Directory, and Trajectory Artifact paths immediately, so that I can decide when to synchronize and inspect child history.
7. As a Parent Agent, I want `mini-mas spawn --wait` to wait for the first observable child by default, so that I can react quickly to whichever child becomes actionable first.
8. As a Parent Agent, I want `mini-mas spawn --wait --all`, so that I can start several children and wait until all of them become observable.
9. As a Parent Agent, I want `mini-mas spawn --wait --timeout <seconds>`, so that I can bound the waited-spawn wait phase without stopping the children.
10. As a Parent Agent, I want `mini-mas wait --all`, so that I can gather First Observable Events from my direct Child Agents.
11. As a Parent Agent, I want `mini-mas wait --any`, so that I can react to whichever direct Child Agent becomes observable first.
12. As a Parent Agent, I want `mini-mas wait <agent-id>`, so that I can wait for one specific direct Child Agent.
13. As a Parent Agent, I want `mini-mas wait --timeout <seconds>`, so that I can use bounded waiting and regain control when no direct Child Agent becomes observable before the timeout.
14. As a Parent Agent, I want `mini-mas status`, so that I can inspect my direct Child Agents without blocking.
15. As a Parent Agent, I want `mini-mas status <agent-id>`, so that I can inspect a specific direct Child Agent.
16. As a Parent Agent, I want `mini-mas continue <agent-id> "message"`, so that I can ask a direct Remote Interactive Agent to keep working from its existing trajectory.
17. As a Parent Agent, I want `mini-mas close <agent-id>`, so that I can end a direct Remote Interactive Agent without implying acceptance or rejection.
17. As a Child Agent, I want to enter `waiting_for_parent` after producing a submission, so that my parent can decide whether I should continue or close.
18. As a Child Agent, I want a Continuation Signal to become a normal user message in my trajectory, so that I can continue with the same linear message history model.
19. As a Child Agent, I want a Close Signal to end my workflow, so that I do not keep waiting indefinitely once no further work is requested.
20. As a Descendant Agent, I want to spawn and perform Agent Interactions with my own direct Child Agents, so that MAS supports recursive delegation without granting transitive control.
21. As a developer, I want Agent IDs to encode tree position, so that recursive relationships are readable in logs and CLI output.
22. As a developer, I want all artifacts for one Root Agent under one Run Directory, so that history search is scoped and not polluted by unrelated MAS runs.
23. As a Parent Agent, I want status and wait results to include exact Trajectory Artifact paths, so that I can inspect full child history using ordinary bash tools.
24. As a Parent Agent, I want `mini-mas` to avoid dedicated history, grep, or logs commands, so that MAS Governance stays separate from shell-based text inspection.
25. As a developer, I want MAS command parsing to require Standalone MAS Commands, so that command interception is predictable and safe.
26. As a developer, I want complex shell combinations containing `mini-mas` to return a clear error, so that agents can correct their next action.
27. As a developer, I want model adapters to continue producing bash-shaped actions, so that MAS does not introduce another model tool schema.
28. As a developer, I want MAS to preserve model-specific observation formatting, so that toolcall, Responses API, and text-based models continue to receive observations correctly.
29. As a developer, I want MAS command dispatch to happen at the workflow layer, so that DBOS workflow-control APIs are not called from steps.
30. As a developer, I want ordinary model calls to be checkpointed as DBOS steps, so that successful model responses can be replayed during workflow recovery.
31. As a developer, I want ordinary bash execution to be checkpointed as DBOS steps, so that successful command outputs can be replayed during workflow recovery.
32. As a developer, I want trajectory saving to use deterministic artifact paths, so that repeated saves are safe and easy to find.
33. As a developer, I want child workflow startup to use deterministic Agent IDs, so that DBOS recovery does not create duplicate descendants.
34. As a developer, I want a DBOS queue for Child Agents, so that global Child Agent concurrency can be controlled.
35. As a developer, I want MAS to expose lightweight Child Status Events, so that parents can make Agent Interaction decisions without reading full trajectories.
36. As a developer, I want MAS to expose `latest_submission` and `latest_error`, so that parent workflows can make fast decisions.
37. As a developer, I want `limits_exceeded` to be a terminal MVP state, so that dynamic child limit changes do not expand the initial scope.
38. As a developer, I want DBOS step side-effect recovery risks documented, so that implementation does not imply exactly-once semantics for arbitrary bash.
39. As a developer, I want Operation Ledger to remain a candidate mitigation, so that recovery policy can be designed deliberately before implementation.
40. As a developer, I want Shared Workspace risks documented, so that MVP users understand that Workspace Isolation is deferred.
41. As a developer, I want MAS to avoid treating bash serialization as Workspace Isolation, so that file-level governance is not falsely considered solved.
42. As a tester, I want deterministic model and environment doubles, so that MAS workflow behavior can be tested without real LLM calls.
43. As a maintainer, I want the new subsystem separated from the core agent loop, so that future upstream changes to mini-swe-agent remain easier to adopt.

## Implementation Decisions

- MAS is introduced as a parallel DBOS-backed subsystem rather than converting the existing default or interactive agent classes in place.
- `mini-mas` is a separate command entrypoint responsible for DBOS configuration, launch, queue registration, and starting top-level MAS work.
- External `mini-mas status`, `mini-mas wait`, `mini-mas continue`, and `mini-mas close` are not maintained as naked operator query/control APIs. They may be unsupported until terminal commands are routed through an Interactive Root Agent.
- DBOS is a default dependency for this branch, but runtime activation is scoped to `mini-mas`.
- The existing `mini` path does not configure or launch DBOS during ordinary single-agent usage.
- Model adapters keep the existing action parsing contract: all model actions are still bash-shaped actions with a command string.
- MAS does not add a separate `mini-mas` model tool.
- MAS does not modify model-side action parsers.
- MAS does not put workflow-layer Agent Interactions inside environment implementations.
- MAS command dispatch happens at the Agent layer.
- Ordinary bash execution enters an `execute_bash_step`; Standalone MAS Commands enter the workflow-layer MAS dispatcher.
- Model calls, bash execution, and trajectory persistence are DBOS steps.
- Workflow control operations such as spawn, wait, send, receive, and child workflow creation stay outside DBOS steps.
- The Agent layer uses async DBOS workflows and async DBOS workflow-control APIs for MAS Governance.
- `root_agent_workflow`, `child_agent_workflow`, MAS command dispatch, spawn, wait, continue, and close are implemented with `async def` / `await` rather than blocking workflow-control calls.
- Blocking model, environment, and filesystem operations remain behind DBOS step boundaries; they may be synchronous steps or async steps as long as the Agent layer awaits them through DBOS-supported APIs.
- The MVP command set is limited to `run`, `spawn`, `status`, `wait`, `continue`, and `close`.
- The MVP uses the Direct Child Authority Policy: a Parent Agent can observe, wait for, continue, and close only its direct Child Agents by default.
- The Root Agent does not have special tree-wide Authority in the MVP.
- Broader subtree-wide or tree-wide control is deferred to a future Authority Model and explicit Authority Grants.
- Workflow-layer MAS dispatch must derive the current Parent Agent identity from `DBOS.workflow_id`.
- Workflow-layer MAS dispatch must fail with a clear model-visible error when `DBOS.workflow_id` is absent.
- Workflow-layer MAS dispatch must not accept a DBOS API object, `root_workflow_id`, caller-supplied current Agent ID, or external operator identity as an authority input.
- Direct-child scope must be resolved from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`.
- Agent ID prefix scans, Root Agent IDs, and Agent ID ancestry are not authorization sources.
- `root_workflow_id`, when needed for Run Directory or Trajectory Artifact paths, is derived from the relevant Agent ID rather than maintained as status, wait, or control scope.
- `mini-mas spawn` accepts one or more repeated task arguments and starts one Child Agent per task.
- `mini-mas spawn` defaults to Detached Spawn.
- `mini-mas spawn --wait` requests Waited Spawn and defaults to wait-any behavior.
- `mini-mas spawn --wait --all` requests Waited Spawn that waits until all started children first become observable.
- `mini-mas spawn --wait --timeout <seconds>` bounds the Waited Spawn wait phase and defaults to wait-any behavior unless `--all` is present.
- A Waited Spawn timeout returns started child metadata, any ready First Observable Events, and still-running child Agent IDs without cancelling, closing, failing, or retrying child workflows.
- `mini-mas spawn --timeout <seconds>` without `--wait` is invalid because Detached Spawn has no wait phase.
- Waited Spawn and `mini-mas wait` wait for First Observable Events, not final DBOS workflow results.
- An Agent may publish `waiting_for_child` as its latest lightweight status while executing `mini-mas wait` or the wait phase of `mini-mas spawn --wait`.
- `waiting_for_child` is a local Agent Interaction state of the waiting Agent, not a parent-actionable Child Agent state.
- A First Observable Event is set when a Child Agent first reaches a parent-actionable state: `waiting_for_parent`, `failed`, or `limits_exceeded`.
- Child-to-parent observable state uses DBOS events keyed by child Agent IDs; parent-to-child Continuation Signals and Close Signals use DBOS workflow messages.
- `mini-mas wait` supports waiting for direct Child Agents with wait-any, wait-all, one direct child, and bounded timeout-based waiting.
- `mini-mas status` without a Agent ID reports direct Child Agents only; it does not include the parent itself or deeper descendants.
- `mini-mas status <agent-id>`, `mini-mas wait <agent-id>`, `mini-mas continue <agent-id>`, and `mini-mas close <agent-id>` must validate that the target is a direct Child Agent of the current Parent Agent.
- Remote Interactive Agents wait for either a Continuation Signal or a Close Signal after producing a submission.
- A Continuation Signal is injected into the child trajectory as a normal user message with metadata identifying MAS continuation.
- A Close Signal ends a Remote Interactive Agent and does not mean accepted or aborted.
- Child Status Events are lightweight and include coarse states such as `running`, `waiting_for_child`, `waiting_for_parent`, `closed`, `failed`, and `limits_exceeded`.
- Child Status Events may be updated repeatedly and represent the latest lightweight state.
- A First Observable Event is set once per Child Agent and is the synchronization target for Waited Spawn and `mini-mas wait`.
- `waiting_for_child` must not be written to the First Observable Event key.
- `mini-mas continue` and `mini-mas close` must continue to authorize only targets whose latest status is `waiting_for_parent`, not `waiting_for_child`.
- The MVP exposes lightweight status, latest submission, and latest error data through DBOS events read by workflow-layer MAS Commands.
- Full history remains in Trajectory Artifacts, not DBOS events.
- `status`, `wait`, and `spawn` outputs include exact Trajectory Artifact paths and the Run Directory.
- Full history search uses ordinary bash tools against Trajectory Artifacts.
- No dedicated `mini-mas history`, `mini-mas logs`, or `mini-mas grep` commands are included in the MVP.
- Standalone MAS Commands must occupy the whole action command.
- Shell operators, environment assignments, loops, pipes, redirections, or embedded `mini-mas` fragments are rejected for MAS interception in the MVP.
- Recursive spawn is supported through an Agent Tree.
- Root Agent IDs use `mas-<16hex>`.
- Descendant Agent IDs append `-cNNN` segments to the parent Agent ID.
- Recursive Agent Interactions remain local at each layer: a child may perform Agent Interactions with its own children, but a grandparent does not control grandchildren under the Direct Child Authority Policy.
- All Agents in one tree share one Run Directory.
- Trajectory Artifacts live under a trajectories area scoped by the Root Agent.
- Shared Workspace is allowed for the MVP, but it is a known correctness risk.
- Workspace Isolation is deferred beyond the MVP.
- Global bash command serialization is not considered Workspace Isolation.
- Child Agent queueing is used for global Child Agent concurrency control.
- The MVP does not queue every model or bash step separately for concurrency control.
- Step automatic retries should not be used to mask arbitrary bash side-effect failures.
- `retries_allowed=False` prevents automatic retry within a failed step attempt but does not provide exactly-once semantics.
- DBOS recovery may repeat uncheckpointed model calls or bash commands if the process crashes after an external side effect but before DBOS records the step result.
- Operation Ledger is a candidate mitigation for model and bash operation recovery, but its storage, schema, and recovery policy are not decided by this PRD.

## Testing Decisions

- Tests should validate model-visible behavior: command results, lifecycle state transitions, emitted messages, returned artifact paths, and durable Agent Interaction behavior.
- Tests should avoid asserting incidental implementation details such as private method names or exact internal DBOS function IDs.
- MAS command parsing should be tested as a deep module with accepted standalone commands and rejected shell-composition cases.
- Agent ID generation should be tested as a deep module with root, child, grandchild, and sibling cases.
- Run Directory and Trajectory Artifact path generation should be tested as a deep module to ensure histories stay scoped to one Root Agent.
- MAS command dispatch should be tested with deterministic model outputs and fake ordinary bash execution.
- Remote Interactive Agent lifecycle should be tested for first submission, waiting for parent, continue, second submission, and close.
- Single-child and multi-child `spawn` behavior should be tested separately.
- `spawn` default detach behavior should be tested separately from `spawn --wait`.
- `spawn --wait` default wait-any behavior should be tested separately from `spawn --wait --all`.
- `spawn --wait --timeout` behavior should be tested for wait-any timeout, wait-all partial timeout, ready child snapshots, still-running child IDs, and preservation of running child workflows.
- `spawn --wait` and `mini-mas wait` should be tested to publish `waiting_for_child` before waiting and restore `running` after the wait finishes, including timeout paths.
- Tests should prove `waiting_for_child` is not published as a First Observable Event and does not authorize `continue` or `close`.
- `spawn --timeout` without `--wait` should be tested as an invalid command.
- `wait --any`, `wait --all`, one-direct-child waiting, and timeout behavior should be tested against First Observable Events using deterministic child workflows or DBOS test doubles.
- Tests should prove Waited Spawn and `mini-mas wait` synchronize through child DBOS events rather than child-to-parent send messages or final workflow results.
- Workflow-control tests should cover async MAS Governance behavior without asserting incidental internal DBOS function IDs.
- Status output should be tested to ensure it includes Agent ID, status, latest submission or error, trajectory path, and run directory for direct Child Agents.
- Tests should prove that a Parent Agent cannot status, wait for, continue, or close grandchildren, siblings, ancestors, or workflows outside its direct child boundary.
- Tests should prove workflow-layer `status`, `wait`, `continue`, and `close` derive current authority from `DBOS.workflow_id` and do not rely on caller-supplied current Agent IDs, `root_workflow_id`, DBOS API object parameters, or Agent ID prefix scans.
- External CLI tests for `status`, `wait`, `continue`, and `close` may assert that these commands are unsupported until the Interactive Root Agent terminal model exists.
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
- Tree-wide or subtree-wide Authority Grants.
- Naked external/operator `status`, `wait`, `continue`, or `close` APIs that inspect or control DBOS workflows outside an Agent.
- Guaranteeing that multiple Agents can safely mutate a Shared Workspace.

## Further Notes

This PRD intentionally preserves mini-swe-agent's core philosophy: the model still interacts through bash-shaped commands, and model adapters still parse and format messages through the existing abstraction. MAS adds durable Agent Interactions around that interface rather than replacing it.

The biggest unresolved correctness issue is side-effect recovery. Existing mini-swe-agent already has a crash-after-side-effect-before-save window. DBOS recovery makes the window more important because uncheckpointed steps may execute again. The Operation Ledger concept should be evaluated before MAS claims robust recovery for model and bash operations.

The second major unresolved correctness issue is Shared Workspace governance. DBOS queue concurrency controls capacity; it does not protect the full read-reason-write window across multiple agent turns. Workspace Isolation remains the likely root-cause fix, but it is deliberately outside the MVP.
