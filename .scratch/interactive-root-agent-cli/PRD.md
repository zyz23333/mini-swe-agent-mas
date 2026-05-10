# PRD: Interactive Root Agent CLI Redesign

Status: needs-triage

## Problem Statement

The current MAS CLI still carries earlier `run`-oriented assumptions: Root Agent identity, Agent Tree position, artifact grouping, and CLI entrypoint behavior are coupled through Agent ID shape and root-scoped artifact paths. This makes the CLI harder to reason about and creates hidden dependencies where changing Agent ID encoding would affect artifact layout, authority boundaries, and user-facing output.

The user wants `mini-mas` to be a simple spawn-first interface backed by durable Interactive Root Agents. The External MAS CLI should create or resume Interactive Root Agents, submit bash-shaped commands through them, and preserve the Direct Child Authority Policy without inventing a global root, root index, run identifier, or CLI superuser path.

## Solution

Redesign the External MAS CLI around Interactive Root Agents.

`mini-mas` without a subcommand creates a new Interactive Root Agent and enters its terminal. `mini-mas spawn ...` is a one-shot convenience form: it creates an Interactive Root Agent, submits the initial `mini-mas spawn ...` command through that Root Agent, returns the spawned Child Agent metadata, and leaves the Root Agent available for later resume. `mini-mas status` is an external discovery command that lists parentless Interactive Root Agents only. `mini-mas resume <root-agent-id>` re-enters an existing Interactive Root Agent when it is Waiting for Command.

All CLI-submitted governance commands enter MAS Governance through an Interactive Root Agent. The CLI process itself is not an Agent, is not a Parent Agent, and does not directly execute Root Agent actions. The CLI sends Root Command Signals to the Interactive Root Agent, and the Root Agent executes the same bash-shaped action flow used by existing human interactive behavior: standalone `mini-mas ...` commands are intercepted as MAS Commands, while ordinary bash commands execute as bash actions. The Root Agent publishes a command-id-scoped Root Command Result event for the CLI to wait on.

Agent IDs remain `mas-<random-hex>` but become opaque durable Agent IDs. They do not encode root identity, parent identity, sibling order, or tree position. Root identity is structural: a Root Agent has no Parent Agent. External root discovery uses parentless Interactive Root Agent workflows, not an `is_root` flag, interaction-mode flag, separate root index, or single global root. Multi-spawn command result ordering may be used for immediate display, but sibling order is not durable Agent metadata.

Artifacts are scoped per Agent. Each Agent owns an Agent Artifact Directory and a Trajectory Artifact. Artifacts are not grouped under Root Agents, runs, or encoded Agent Tree paths. The Root Agent's Trajectory Artifact is the durable command history for Root terminal input, including ordinary bash actions and MAS command observations. The Interactive Root terminal does not create or reuse a separate prompt-history file.

The first version supports detach and resume, not Root Agent closure or cleanup. Exiting a terminal detaches from the Interactive Root Agent and leaves it Waiting for Command. Only one active terminal attachment is supported per Interactive Root Agent. One-shot external commands occupy that attachment while their submitted command is running and detach after returning.

## User Stories

1. As a CLI user, I want `mini-mas` with no subcommand to create an Interactive Root Agent, so that I can enter a durable MAS command terminal.
2. As a CLI user, I want `mini-mas` to print the new Root Agent metadata before the first prompt, so that I can record the Root Agent ID and artifact path.
3. As a CLI user, I want `mini-mas spawn "task"` to create an Interactive Root Agent and submit the first spawn command through it, so that I can start work with one command.
4. As a CLI user, I want `mini-mas spawn "task"` to return the spawned Child Agent metadata, so that I can inspect or wait on the work later.
5. As a CLI user, I want one-shot spawn output to include `root_agent_id`, so that I can resume the Root Agent later.
6. As a CLI user, I want one-shot spawn output to emphasize Child Agent artifacts, so that the work Agent is the obvious thing to inspect.
7. As a CLI user, I do not want one-shot spawn to print Root Agent artifact paths by default, so that the output stays focused on the spawned Child Agent.
8. As a CLI user, I want `mini-mas spawn "task A" "task B"` to create one Interactive Root Agent and multiple direct Child Agents, so that related one-shot work shares a parent authority context.
9. As a CLI user, I want multi-spawn output to include one Root Agent ID and one entry per Child Agent, so that the relationship is explicit.
10. As a CLI user, I want each spawned Child Agent entry to include parent Agent ID, Agent Artifact Directory, and Trajectory Artifact path, so that I can understand and inspect each child.
11. As a CLI user, I want one-shot `mini-mas spawn --wait` to use the same Waited Spawn behavior as workflow-layer `mini-mas spawn --wait`, so that external and internal semantics match.
12. As a CLI user, I want one-shot `mini-mas spawn --wait --all` to wait for all started children to become observable, so that I can synchronize related work.
13. As a CLI user, I want one-shot `mini-mas spawn --wait --timeout <seconds>` to bound only the wait phase, so that children keep running after timeout.
14. As a CLI user, I want `mini-mas spawn --timeout <seconds>` without `--wait` to remain invalid, so that Detached Spawn does not gain a meaningless timeout.
15. As a CLI user, I want `mini-mas status` to list Interactive Root Agents, so that I can discover resumable entrypoints.
16. As a CLI user, I want external `mini-mas status` to list parentless Interactive Root Agents only, so that it remains a discovery view rather than a governance command.
17. As a CLI user, I want external `mini-mas status` to include Root Agent lifecycle state, so that I can see whether a Root Agent is Waiting for Command, running, waiting for child, failed, or otherwise unavailable.
18. As a CLI user, I want external `mini-mas status` to list failed Root Agents too, so that Root Agents do not disappear from discovery just because they are not currently resumable.
19. As a CLI user, I do not want external `mini-mas status` to show Child Agent counts, so that discovery stays lightweight.
20. As a CLI user, I do not want external `mini-mas status` to show Child Agent status, so that child inspection remains inside a Root Agent authority context.
21. As a CLI user, I do not want external `mini-mas status` to summarize command history, so that durable history remains in Trajectory Artifacts.
22. As a CLI user, I want `mini-mas resume <root-agent-id>` to re-enter an existing Interactive Root Agent, so that I can continue managing its direct children.
23. As a CLI user, I want `resume` to print Root Agent metadata once before prompting, so that I can verify the Root Agent I entered.
24. As a CLI user, I want `resume` to work only when the Root Agent is Waiting for Command, so that I do not attach to an Agent that is already running a command.
25. As a CLI user, I want terminal exit to detach from the Interactive Root Agent, so that I can leave and resume later without closing it.
26. As a CLI user, I want Root Agent closure to be out of the first version, so that `close` remains unambiguously parent-to-child.
27. As a CLI user, I want at most one active terminal attachment per Interactive Root Agent, so that commands do not race.
28. As a CLI user, I want one-shot `spawn --wait` to occupy the Root Agent attachment while waiting, so that another terminal cannot concurrently resume and issue commands.
29. As a CLI user, I want Interactive Root terminal input to accept full standalone `mini-mas ...` commands, so that the same MAS Command syntax works inside and outside model actions.
30. As a CLI user, I do not want prefix-free shorthand such as `status` in the first version, so that parsing remains simple.
31. As a CLI user, I want ordinary bash commands to execute inside an Interactive Root Agent, so that the Root terminal follows the existing human interactive flow.
32. As a CLI user, I want ordinary bash actions in the Root terminal to be recorded in the Root Agent's Trajectory Artifact, so that artifact history is complete.
33. As a CLI user, I do not want the Interactive Root terminal to create or reuse prompt-history files, so that durable history has one source of truth.
34. As a Root Agent, I want to receive user commands through Root Command Signals, so that the CLI does not execute my actions outside the workflow.
35. As a Root Agent, I want to publish Root Command Results as command-id-scoped events, so that the CLI can wait for the result of the command it submitted.
36. As a Root Agent, I want Root Command Results to use the existing MAS Agent command result shape, so that the first version does not invent a premature CLI protocol schema.
37. As a Root Agent, I want to publish Waiting for Command when idle, so that `resume` can safely attach only when I am ready.
38. As a Root Agent, I want to be `running` while executing ordinary bash or detached MAS commands, so that external discovery reflects that I am busy.
39. As a Root Agent, I want to be `waiting_for_child` while executing `mini-mas wait` or `mini-mas spawn --wait`, so that wait state is distinguishable from ordinary command execution.
40. As a Parent Agent, I want Direct Child Authority to remain unchanged, so that a Root Agent controls only its direct children.
41. As a Child Agent, I want my Agent ID to be opaque, so that identity does not reveal Root Agent, parent Agent, sibling order, or tree position.
42. As a Child Agent, I want my artifact path to be scoped to my Agent ID, so that artifact layout does not depend on encoded tree position.
43. As a Parent Agent, I want multi-spawn output order to be preserved in the current command result, so that immediate display can match the submitted task order.
44. As a Parent Agent, I do not want sibling order to become durable Agent metadata, so that order does not become identity or authority.
45. As a developer, I want Root Agent discovery to use parentless Interactive Root Agent workflows, so that no global root Agent or root index is needed.
46. As a developer, I want Agent Metadata to avoid `is_root` and interaction-mode flags, so that query flags do not pollute per-Agent metadata.
47. As a developer, I want Interactive Root Agent workflow type/name to distinguish root terminal workflows, so that external status can filter root workflows without extra metadata flags.
48. As a developer, I want DBOS workflow ID to equal Agent ID, so that workflow status and Agent identity remain aligned.
49. As a developer, I want parent-child relations to come from DBOS parent workflow metadata, so that authority is structural rather than encoded in IDs.
50. As a developer, I want per-Agent artifact paths, so that changing Agent ID generation does not change root/run grouping semantics.
51. As a developer, I want Root Agent artifact paths to be available through metadata and status, so that users can inspect Root command history when needed.
52. As a developer, I want one-shot spawn to leave an Interactive Root Agent available after returning, so that future commands can enter through the same parent authority context.
53. As a developer, I want naked external `wait`, `continue`, and `close` to remain out of the first version, so that governance commands do not bypass Root Agent context.
54. As a developer, I want external `status` to be discovery rather than Agent Interaction, so that it can safely run outside Agent context.
55. As a developer, I want Root Agent cleanup to be deferred, so that close semantics do not expand the first version.
56. As a developer, I want spawn recovery semantics deferred to recovery design, so that the first version does not imply exactly-once spawn behavior.
57. As a maintainer, I want the PRD to align with the domain glossary and ADRs, so that future implementation issues can be split without re-opening terminology.

## Implementation Decisions

- Replace the existing `run`-first external MAS CLI mental model with a spawn-first Interactive Root Agent model.
- `mini-mas` with no subcommand creates a new Interactive Root Agent and enters its terminal.
- `mini-mas spawn` creates a new Interactive Root Agent, sends the first spawn command to it, waits for the Root Command Result, prints spawned Child Agent metadata, and detaches.
- `mini-mas spawn` supports repeated task arguments and creates multiple direct Child Agents under one new Interactive Root Agent.
- `mini-mas spawn` supports the same Detached Spawn and Waited Spawn options as workflow-layer `mini-mas spawn`.
- `mini-mas status` is external discovery for Interactive Root Agents and is not a MAS-governed Child Agent status command.
- External `mini-mas status` lists all parentless Interactive Root Agent workflows, including failed or otherwise non-resumable roots.
- External `mini-mas status` does not show child counts, child status, latest command, or history summary.
- `mini-mas resume <root-agent-id>` attaches to an existing Interactive Root Agent only when it is Waiting for Command.
- `mini-mas resume` prints Root Agent metadata once before entering the command prompt.
- Exiting the terminal detaches from the Interactive Root Agent and does not close it.
- Explicit Root Agent closure and cleanup are deferred; the first version does not add `close-root`.
- Each Interactive Root Agent supports at most one active terminal attachment in the first version.
- One-shot external commands occupy the Interactive Root Agent attachment while running and detach after returning.
- Interactive Root terminal input follows the existing bash-shaped human command flow.
- Interactive Root terminal input uses full standalone `mini-mas ...` commands for MAS interactions; prefix-free shorthand is not part of the first version.
- Ordinary bash commands are allowed in the Interactive Root terminal.
- Ordinary bash command actions and observations are recorded in the Root Agent's Trajectory Artifact.
- The Interactive Root terminal does not maintain or reuse a prompt-history file; durable command history is the Root Agent Trajectory Artifact.
- The External MAS CLI sends commands to the Interactive Root Agent through Root Command Signals.
- The CLI does not directly execute Root Agent actions.
- The Interactive Root Agent publishes Root Command Results as command-id-scoped DBOS events.
- Root Command Results use the existing MAS Agent command result shape unless a future CLI protocol design narrows it.
- Agent IDs use the `mas-<random-hex>` shape as opaque durable identifiers.
- Agent IDs do not encode root identity, parent identity, sibling order, or tree position.
- DBOS workflow ID equals Agent ID.
- Root Agent identity is structural: a Root Agent has no Parent Agent.
- Root discovery uses parentless Interactive Root Agent workflow records, not a root index, global root, `is_root` flag, or interaction-mode flag.
- The implementation may distinguish Interactive Root Agents from other parentless workflows by workflow type/name.
- Agent Metadata records stable identity and artifact description only: Agent ID, optional Parent Agent ID, Agent Artifact Directory, and Trajectory Artifact path.
- Multi-spawn command result ordering may be used for immediate display.
- Sibling order is not durable Agent metadata and is not identity, authority, tree position, or part of the Agent ID.
- Agent Artifacts are scoped per Agent.
- Trajectory Artifacts live under Agent Artifact Directories keyed by Agent ID.
- Root Agent artifacts and Child Agent artifacts use the same per-Agent artifact model.
- One-shot spawn output includes Root Agent ID for later resume but does not show Root Agent artifact paths by default.
- One-shot spawn output emphasizes spawned Child Agent metadata.
- Direct Child Authority Policy remains in force.
- A Root Agent does not gain tree-wide Authority.
- Root terminal commands enter MAS Governance through the Root Agent and follow the same Authority Model as any other Parent Agent.
- Workflow-layer `mini-mas status`, `wait`, `continue`, and `close` remain scoped to direct children of the current Parent Agent.
- External `wait`, `continue`, and `close` are not introduced as naked operator commands in the first version.
- `waiting_for_command` is added as an Interactive Root Agent lifecycle state.
- An Interactive Root Agent is Waiting for Command when idle and available for resume.
- An Interactive Root Agent is `running` while executing ordinary bash or detached MAS commands.
- An Interactive Root Agent is `waiting_for_child` while executing `mini-mas wait` or `mini-mas spawn --wait`.
- `resume` is rejected for Root Agents that are not Waiting for Command.
- Prompt format remains undecided in this PRD because the user redirected to PRD creation before resolving full-ID versus short-ID prompt display.
- Spawn recovery remains undecided and is tracked in the recovery ADR; this PRD does not define exactly-once spawn semantics.

## Testing Decisions

- Tests should validate external behavior: CLI output, lifecycle states, metadata, artifacts, Root Command Signal/Result behavior, authority boundaries, and trajectory contents.
- Tests should not assert incidental implementation details such as private helper names or exact DBOS internal function IDs.
- CLI tests should cover `mini-mas` with no subcommand creating an Interactive Root Agent and printing Root metadata before prompt.
- CLI tests should cover `mini-mas spawn "task"` creating one Interactive Root Agent and one direct Child Agent.
- CLI tests should cover one-shot multi-spawn creating one Interactive Root Agent and multiple direct Child Agents.
- CLI tests should cover one-shot `spawn --wait`, `--all`, and `--timeout` mapping to existing Waited Spawn semantics.
- CLI tests should cover one-shot spawn output showing Root Agent ID and Child Agent artifact metadata while omitting Root Agent artifact paths.
- CLI tests should cover external `mini-mas status` listing parentless Interactive Root Agents only.
- CLI tests should cover external `mini-mas status` omitting child count, child status, latest commands, and history summary.
- CLI tests should cover `mini-mas resume <root-agent-id>` accepting a Root Agent only when it is Waiting for Command.
- CLI tests should cover resume printing Root Agent metadata once before accepting command input.
- CLI tests should cover terminal detach leaving the Interactive Root Agent Waiting for Command and resumable.
- CLI tests should cover rejection of concurrent attachment when an attachment is already active or when one-shot spawn is still running.
- Workflow tests should cover Root Command Signal delivery into the Interactive Root Agent.
- Workflow tests should cover command-id-scoped Root Command Result events.
- Workflow tests should cover ordinary bash commands executing through the existing bash-shaped action flow inside an Interactive Root Agent.
- Workflow tests should cover ordinary bash actions and observations being persisted in the Root Agent Trajectory Artifact.
- Workflow tests should cover standalone `mini-mas ...` commands being intercepted as MAS Commands inside an Interactive Root Agent.
- Workflow tests should cover composed `mini-mas ... && ...` commands remaining invalid for MAS interception.
- Artifact tests should cover per-Agent artifact directories for Root Agents and Child Agents.
- Artifact tests should cover Agent Metadata shape with Agent ID, optional Parent Agent ID, Agent Artifact Directory, and Trajectory Artifact path.
- Identity tests should cover opaque `mas-<random-hex>` Agent IDs for Root Agents and Child Agents.
- Identity tests should prove Child Agent IDs do not encode Parent Agent ID or sibling order.
- Authority tests should continue to prove direct-child-only status, wait, continue, and close.
- Authority tests should prove Root Agent status inside the terminal lists direct children only and does not grant grandchild control.
- Discovery tests should cover parentless Interactive Root Agent workflow filtering.
- Discovery tests should avoid relying on `is_root`, interaction-mode, root index, or global root data.
- Lifecycle tests should cover `waiting_for_command`, `running`, and `waiting_for_child` transitions for Interactive Root Agents.
- Prior art exists in existing MAS CLI tests for external command output and return codes.
- Prior art exists in existing MAS spawn/wait tests for Detached Spawn, Waited Spawn, First Observable Events, and timeouts.
- Prior art exists in existing MAS authority tests for direct-child governance.
- Prior art exists in existing interactive agent tests for human-mode bash command wrapping.
- Prior art exists in existing artifact tests for deterministic artifact metadata and trajectory persistence.
- Good tests should exercise behavior through public CLI/runtime/workflow boundaries rather than private implementation details.

## Out of Scope

- Prefix-free shorthand commands such as `status` inside the Interactive Root terminal.
- Naked external `wait`, `continue`, and `close` commands that bypass an Interactive Root Agent.
- External status showing Child Agent counts, Child Agent status, latest Root commands, or history summaries.
- Prompt-history files for the Interactive Root terminal.
- Root Agent close, delete, cleanup, garbage collection, or retention policy.
- Multiple simultaneous terminal attachments to one Interactive Root Agent.
- A global root Agent.
- A Root Agent index.
- A `run_id` or run-scoped artifact model.
- Root-scoped artifact directories.
- Agent IDs that encode root, parent, sibling order, or tree position.
- `is_root` or interaction-mode flags in Agent Metadata.
- A new Root Command Result payload schema.
- Exactly-once spawn recovery semantics.
- Operation Ledger design.
- Workspace Isolation.
- Tree-wide or subtree-wide Authority Grants.
- Direct external control of grandchildren.
- Prompt display decision for full Root Agent ID versus shortened Root Agent ID.

## Further Notes

The design deliberately separates discovery from governance. External `mini-mas status` can discover parentless Interactive Root Agents outside Agent context, but control commands still enter through an Interactive Root Agent and obey Direct Child Authority.

The design also separates identity from structure. Agent ID is opaque; parent-child structure comes from workflow parent metadata; sibling display order is limited to the current multi-spawn command result; artifact ownership comes from per-Agent artifact paths.

The first version intentionally avoids a global root because it would be an implementation convenience rather than a meaningful MAS Governance concept. If future requirements introduce a real system-level coordinator with scheduling, policy, leases, or cleanup responsibilities, that should be designed as its own concept rather than smuggled into the Agent Tree.

Spawn recovery remains a known unresolved area. Replay after a crash could duplicate child creation unless spawn operations become ledgered. This is tracked in the recovery ADR and should be handled with the broader Operation Ledger design.
