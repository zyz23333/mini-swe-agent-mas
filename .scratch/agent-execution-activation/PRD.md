# PRD: Explicit AI Agent Execution Activation

Status: needs-triage

## Problem Statement

The current MAS runtime design risks making ordinary `mini-mas` commands do more work than users expect. DBOS runtime launch can start recovery and queue consumption, so a command that appears to inspect or enter an Interactive Root Agent can accidentally resume autonomous AI Agent work. That is especially risky because autonomous Agents may call models, execute bash actions, and modify the Shared Workspace.

Users expect `mini-mas` to behave like `mini` in the MVP: work happens while the relevant foreground terminal process exists, and closing the terminal stops execution capacity without closing durable Agents. Users also need Interactive Agents to be available when they open `mini-mas`, while autonomous AI Agent execution must require a separate, explicit user action.

## Solution

Separate interactive command handling from autonomous AI Agent execution by using two DBOS queues and two foreground runtime modes.

Interactive Agents are queued on `mini_mas_interactive_workflows`. The default `mini-mas` runtime listens only to this interactive queue, so Interactive Agents can become available when the CLI is running. An Interactive Root Agent is the parentless Interactive Agent entered by the External MAS CLI, but interactivity is not Root-specific; future non-root Interactive Agents can use the same queue.

Autonomous AI Agents are queued on `mini_mas_ai_agent_workflows`. The default `mini-mas` runtime does not consume this queue. AI Agent Execution is activated only when the user runs:

```text
mini-mas agent activate
```

`mini-mas agent activate` starts a foreground execution capability for the active MAS Runtime State Store. It does not create, continue, close, or accept any Agent by itself. It remains active and waits for future queued AI Agent work even when no AI Agents are currently queued. It starts without a second confirmation prompt because invoking the command is already explicit execution authorization. It prints a startup notice that AI Agent work may call models, execute bash actions, and modify the Shared Workspace. Stopping the command deactivates AI Agent Execution without closing queued, running, or waiting Agents.

`mini-mas status` remains an External MAS CLI discovery command for Interactive Root Agents. It does not report queued AI Agent work and does not report whether AI Agent Execution is active. Activation is runtime state shown only as a startup notice by `mini-mas agent activate`; it is not an Agent lifecycle state, not a prompt indicator, and not a status concern.

## User Stories

1. As a CLI user, I want ordinary `mini-mas` startup to make Interactive Agents available, so that I can enter or resume command-handling Agents without enabling autonomous AI work.
2. As a CLI user, I want `mini-mas` to avoid consuming autonomous AI Agent work by default, so that opening the MAS CLI does not unexpectedly call models or modify files.
3. As a CLI user, I want to explicitly run `mini-mas agent activate`, so that I can decide when queued AI Agents are allowed to execute.
4. As a CLI user, I want `mini-mas agent activate` to remain active when no AI Agents are currently queued, so that I can start it before spawning work.
5. As a CLI user, I want `mini-mas agent activate` to run in the foreground, so that I can stop AI Agent Execution with normal terminal controls.
6. As a CLI user, I want stopping `mini-mas agent activate` to deactivate execution capacity without closing Agents, so that durable MAS state remains available for later work.
7. As a CLI user, I want `mini-mas agent activate` to print a startup notice, so that I understand it may call models, execute bash actions, and modify the Shared Workspace.
8. As a CLI user, I do not want `mini-mas agent activate` to ask for a second confirmation prompt, so that activation stays ergonomic when I run it after opening a terminal.
9. As a CLI user, I want `mini-mas agent activate` to avoid creating a new Agent, so that activation is clearly execution capacity rather than task creation.
10. As a CLI user, I want `mini-mas agent activate` to avoid continuing, closing, or accepting Agents, so that it does not imply a governance decision.
11. As a CLI user, I want `mini-mas spawn "task"` to create or queue AI Agent work without requiring immediate execution, so that I can stage work before activating execution.
12. As a CLI user, I want AI Agent work spawned before activation to remain durable, so that I can activate execution later from a foreground terminal.
13. As a CLI user, I want Interactive Root Agents to remain usable even when AI Agent Execution is inactive, so that I can inspect, coordinate, or issue MAS commands without enabling autonomous AI execution.
14. As a CLI user, I want `mini-mas status` to remain a lightweight Interactive Root Agent discovery command, so that it does not become a runtime dashboard.
15. As a CLI user, I do not want `mini-mas status` to report whether AI Agent Execution is active, so that status stays focused on MAS governance and Agent discovery.
16. As a CLI user, I do not want `mini-mas status` to report queued AI Agent work, so that queue state does not become an Agent lifecycle concept.
17. As a CLI user, I do not want the interactive prompt to show a persistent AI Agent Execution indicator, so that the prompt stays simple.
18. As a CLI user, I want activation state to be communicated only at activation startup, so that I receive a clear warning without ongoing prompt noise.
19. As a CLI user, I want closing a `mini-mas` terminal to stop the local runtime process without closing the Interactive Root Agent, so that I can resume later.
20. As a CLI user, I want closing the `mini-mas agent activate` terminal to stop AI Agent Execution without deleting queued work, so that I can safely pause execution capacity.
21. As a user concerned about model cost, I want autonomous AI Agent execution to require explicit activation, so that model calls do not happen just because I checked status or resumed a Root.
22. As a user concerned about workspace modifications, I want autonomous bash execution to require explicit activation, so that files do not change unexpectedly after a harmless-looking command.
23. As a Parent Agent, I want spawned Child Agents to be independent of whether execution is currently active, so that delegation and execution capacity are separate concerns.
24. As an Interactive Agent, I want to wait for external or parent-supplied commands instead of autonomously advancing through model calls, so that the interactive queue can be consumed safely by the default runtime.
25. As an Interactive Root Agent, I want to remain the External MAS CLI entrypoint, so that the existing parent authority context remains intact.
26. As a future non-root Interactive Agent, I want interactivity to be a general Agent capability, so that the design does not treat interactive behavior as Root-only.
27. As an autonomous AI Agent, I want to advance only when AI Agent Execution is active, so that execution follows explicit user authorization.
28. As a maintainer, I want interactive command handling and autonomous AI Agent execution to use separate DBOS queues, so that DBOS queue listening controls the category of work a process may execute.
29. As a maintainer, I want to avoid direct DBOS workflow startup for Interactive Agents, so that queue listening can control recovery and execution boundaries consistently.
30. As a maintainer, I want to avoid putting all MAS workflows on one queue, so that runtime authorization does not depend on fragile workflow-name filtering.
31. As a maintainer, I want ordinary `mini-mas` runtime activation to listen only to the interactive queue, so that AI Agent execution is not accidentally enabled.
32. As a maintainer, I want `mini-mas agent activate` to listen only to the AI Agent queue, so that the activation command has a clear execution scope.
33. As a maintainer, I want inspection paths to avoid launching a DBOS executor when they only need metadata, so that status and resume validation do not trigger recovery or queue consumption.
34. As a maintainer, I want any DBOS launch path to declare its queue listening policy before launch, so that default DBOS behavior does not silently consume database-backed queues.
35. As a maintainer, I want lifecycle states to remain Agent-owned semantic states, so that queue placement does not become Agent lifecycle.
36. As a maintainer, I want activation state to remain runtime state, so that Agent metadata and status events do not depend on local process liveness.
37. As a maintainer, I want startup notices to be tested through CLI behavior, so that users get risk information without interactive confirmation prompts.
38. As a tester, I want deterministic tests for queue-listening policy, so that ordinary `mini-mas` cannot regress into consuming AI Agent work.
39. As a tester, I want deterministic tests for `mini-mas agent activate`, so that it runs foreground activation behavior without creating Agents or requiring queued work.
40. As a tester, I want status tests to prove activation and queued AI work are absent from status output, so that the runtime boundary remains visible.
41. As a developer, I want the implementation to align with ADR 0009, so that future queue and runtime changes preserve explicit execution authorization.
42. As a developer, I want this feature to preserve the Direct Child Authority Policy, so that execution activation does not grant broader control over Agents.
43. As a developer, I want this feature to preserve the existing External MAS CLI entry model, so that CLI-submitted governance commands still enter through Interactive Root Agents.
44. As a developer, I want this feature to avoid claiming exactly-once side-effect recovery, so that DBOS recovery risks from model calls, bash actions, and spawn remain explicit.
45. As a developer, I want this feature to avoid solving Workspace Isolation, so that activation does not imply safe concurrent file modifications.

## Implementation Decisions

- Use two distinct DBOS queues for MAS runtime execution categories.
- Use `mini_mas_interactive_workflows` for Interactive Agents that wait for external or parent-supplied commands.
- Use `mini_mas_ai_agent_workflows` for autonomous Agents that advance through model calls and bash actions.
- Treat Interactive Root Agent as the parentless Interactive Agent entered by the External MAS CLI.
- Keep interactivity as a general Agent capability so future non-root Interactive Agents can use the interactive queue.
- Replace direct startup of Interactive Agent workflows with queued startup through the interactive queue.
- Ensure default `mini-mas` runtime activation listens only to the interactive queue.
- Ensure default `mini-mas` runtime activation does not consume the AI Agent queue.
- Add `mini-mas agent activate` as the explicit command for AI Agent Execution.
- Make `mini-mas agent activate` listen to the AI Agent queue while the command is running.
- Make `mini-mas agent activate` run in the foreground and wait for future queued AI Agent work.
- Do not require queued AI Agent work to exist before `mini-mas agent activate` starts.
- Do not add a second confirmation prompt to `mini-mas agent activate`.
- Print a startup notice from `mini-mas agent activate` explaining that queued AI Agent work may call models, execute bash actions, and modify the Shared Workspace.
- Stopping `mini-mas agent activate` deactivates AI Agent Execution without closing, continuing, accepting, deleting, or cancelling Agents.
- Do not add an Agent lifecycle state for queued work.
- Do not make Agents aware of their queue placement.
- Do not make `mini-mas status` report queued AI Agent work.
- Do not make `mini-mas status` report whether AI Agent Execution is active.
- Do not add a persistent prompt indicator for AI Agent Execution.
- Treat activation liveness as runtime state, not Agent metadata, Agent lifecycle, Child Status Event data, or External MAS CLI status output.
- Preserve existing Root discovery semantics for `mini-mas status`: status lists Interactive Root Agents, not runtime activation state.
- Use read-only control-plane access for discovery and resume validation where possible, so status-like commands do not need a DBOS executor.
- Any DBOS executor launch path must set an explicit queue listening policy before launch.
- Avoid relying on DBOS default database-backed queue discovery for MAS runtime entrypoints.
- Avoid using queue concurrency or workflow-name filtering as the primary mechanism for execution authorization.
- Preserve Direct Child Authority Policy; activation enables execution capacity but does not grant new governance authority.
- Preserve the existing Root Command Signal and Root Command Result model for Interactive Agents.
- Keep ordinary bash command execution inside Interactive Agents as explicit user command handling, not autonomous AI Agent Execution.
- Keep autonomous model calls and bash actions behind the AI Agent Execution activation boundary.
- Keep DBOS step side-effect recovery risk visible; this feature does not solve model call, bash action, or spawn exactly-once semantics.
- Keep Shared Workspace risk visible; this feature does not implement Workspace Isolation.
- The main deep module opportunity is a runtime activation policy that maps command intent to DBOS queue listening policy through a small, testable interface.
- Another deep module opportunity is a queue catalog that centralizes MAS queue names and prevents ad hoc string duplication.
- Another deep module opportunity is a startup notice formatter that can be tested independently from DBOS execution.
- Another deep module opportunity is a control-plane DBOS client adapter for status and resume validation paths that must not launch execution.

## Testing Decisions

- Tests should validate external behavior and explicit runtime boundaries rather than private helper names.
- Tests should prove ordinary `mini-mas` runtime activation listens only to interactive work.
- Tests should prove ordinary `mini-mas` runtime activation does not listen to autonomous AI Agent work.
- Tests should prove `mini-mas agent activate` listens to autonomous AI Agent work.
- Tests should prove `mini-mas agent activate` remains running when no AI Agents are queued.
- Tests should prove `mini-mas agent activate` does not create an Agent by itself.
- Tests should prove `mini-mas agent activate` does not continue, close, accept, cancel, or delete Agents by itself.
- Tests should prove stopping activation does not close queued, running, or waiting Agents.
- Tests should prove `mini-mas agent activate` starts without a second confirmation prompt.
- Tests should prove `mini-mas agent activate` prints the required startup notice.
- Tests should prove the startup notice includes the active workspace, runtime state store, AI Agent queue, side-effect warning, and Ctrl-C deactivation guidance when those values are available.
- Tests should prove `mini-mas status` does not report queued AI Agent work.
- Tests should prove `mini-mas status` does not report whether AI Agent Execution is active.
- Tests should prove no new `queued` Agent lifecycle state is introduced.
- Tests should prove Agent status output remains based on Agent-published lifecycle states and existing metadata.
- Tests should prove Interactive Agent queue wiring supports Interactive Root Agent availability under the default runtime.
- Tests should prove future non-root Interactive Agent queue support is not blocked by Root-specific queue naming.
- Tests should prove AI Agent work queued before activation can be consumed after activation.
- Tests should prove activation can run before any AI Agent work is queued and then consume work queued later.
- Tests should prove the runtime activation policy chooses queue listening sets deterministically for ordinary `mini-mas`, `mini-mas agent activate`, and inspection-only commands.
- Tests should prove inspection-only commands use control-plane access without launching execution when feasible.
- Tests should prove DBOS launch wrappers apply queue listening policy before launch.
- Tests should avoid asserting internal DBOS recovery thread behavior directly unless using a stable adapter boundary.
- Tests should avoid checking private DBOS implementation details such as internal thread names.
- Existing MAS runtime tests provide prior art for DBOS launch assertions and workflow startup behavior.
- Existing MAS CLI tests provide prior art for command output, return codes, and terminal behavior.
- Existing MAS spawn/wait tests provide prior art for Child Agent enqueue behavior and wait semantics.
- Existing MAS status tests provide prior art for keeping external status focused on Interactive Root Agent discovery.
- Existing MAS authority tests provide prior art for proving activation does not change Direct Child Authority.
- Good tests should exercise public CLI/runtime boundaries and stable adapter interfaces.

## Out of Scope

- Implementing a background daemon or system service for AI Agent Execution.
- Adding a persistent prompt indicator for AI Agent Execution.
- Reporting AI Agent Execution activation in `mini-mas status`.
- Reporting queued AI Agent work in `mini-mas status`.
- Adding a `queued` Agent lifecycle state.
- Making Agents aware of queue placement.
- Adding `mini-mas agent deactivate` as a separate command for the MVP; foreground Ctrl-C is sufficient.
- Adding a second confirmation prompt to `mini-mas agent activate`.
- Changing Direct Child Authority Policy.
- Adding tree-wide, subtree-wide, or peer-to-peer Authority Grants.
- Solving Operation Ledger design or exactly-once side-effect recovery.
- Solving Workspace Isolation.
- Adding Root Agent cleanup, retention, or garbage collection behavior.
- Adding a runtime dashboard for queues or activation liveness.
- Adding external naked `wait`, `continue`, or `close` commands that bypass an Interactive Root Agent.
- Supporting multiple queue backends beyond the existing DBOS-backed MAS Runtime State Store.

## Further Notes

This PRD follows ADR 0009 and the current domain glossary. The core design principle is that queue listening is the execution authorization boundary: the default `mini-mas` runtime is authorized to run Interactive Agents, while `mini-mas agent activate` is the explicit authorization to run autonomous AI Agents.

This feature deliberately avoids making runtime activation part of Agent lifecycle. An Agent should not know whether it is queued or whether a local foreground activation process exists. That keeps Agent lifecycle focused on Agent-owned semantic states and keeps runtime liveness out of MAS Governance.

This feature also preserves the MVP's no-daemon posture. `mini-mas agent activate` is a foreground capability, not a background service. The command can be made service-like in a future feature, but the MVP should keep execution visible and easy to stop.
