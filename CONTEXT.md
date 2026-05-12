# mini-swe-agent MAS

This context describes the proposed multi-agent extension for mini-swe-agent, where durable agents are organised by MAS governance rules while preserving the existing bash-first agent interface.

## Language

**MAS Governance**:
The organizational rules that define Agent relationships, responsibilities, and allowed cross-Agent actions.
_Avoid_: MAS Coordination, orchestration, scheduler

**Agent Interaction**:
A concrete cross-Agent action allowed by **MAS Governance**, such as starting, observing, waiting for, continuing, closing, or messaging another **Agent**.
_Avoid_: Tool call, environment action

**Agent**:
A durable mini-swe-agent invocation that participates in **MAS Governance**.
_Avoid_: Agent Workflow, DBOS workflow, agent process

**Parent Agent**:
An **Agent** that delegates work to one or more **Child Agents**.
_Avoid_: Master agent, orchestrator process

**Root Agent**:
The top-level **Parent Agent** through which the **External MAS CLI** submits user-requested **Agent Interactions**.
_Avoid_: Operator Agent, CLI Parent Agent, main process, root process

**Interactive Root Agent**:
A **Root Agent** that receives commands from the **External MAS CLI** and remains available as the parent authority context for its direct **Child Agents**.
_Avoid_: ordinary root agent, terminal superuser, session process

**Child Agent**:
An **Agent** started by a **Parent Agent** to work on a delegated task.
_Avoid_: Worker process, subagent process

**Descendant Agent**:
An **Agent** recursively started below a **Root Agent**.
_Avoid_: Nested process, recursive worker

**Agent Tree**:
The recursive parent-child structure formed by **Agents** below one **Root Agent**.
_Avoid_: Process tree

**Agent ID**:
A durable opaque identifier for one **Agent**.
_Avoid_: Workflow Tree ID, path, tree position

**Agent Metadata**:
Self-describing identity and artifact information for one **Agent**.
_Avoid_: Root index, role flags, mode flags

**MAS Command**:
A bash command beginning with `mini-mas` that an agent emits to request a MAS-governed **Agent Interaction**.
_Avoid_: Tool call, DBOS command

**Standalone MAS Command**:
A **MAS Command** that occupies the entire agent action command without shell operators, environment assignments, loops, pipes, or redirections.
_Avoid_: Embedded mini-mas command, shell fragment

**MAS Command Interception**:
The in-process handling of a **MAS Command** by a DBOS-aware environment instead of executing it as a normal subprocess.
_Avoid_: Shell plugin, subprocess hook

**External MAS CLI**:
The real `mini-mas` command used outside an **Agent** to submit or inspect multi-agent work.
_Avoid_: Internal mini-mas

**Resume**:
An **External MAS CLI** action that re-enters an existing **Interactive Root Agent**.
_Avoid_: Attach, open, shell, connect

**Remote Interactive Agent**:
A **Child Agent** whose post-submission continuation is controlled by its **Parent Agent** instead of a local terminal user.
_Avoid_: TTY agent, long-running worker

**Continuation Signal**:
A parent-to-child message that asks a **Remote Interactive Agent** to continue working from its existing trajectory.
_Avoid_: New task command, resume event

**Root Command Signal**:
An external-to-Root message carrying one bash-shaped command for an **Interactive Root Agent** to execute.
_Avoid_: Parent direction signal, direct CLI execution

**Root Command Result**:
A command-id-scoped DBOS event containing the result of one **Root Command Signal**.
_Avoid_: Reply signal, terminal stdout buffer

**Close Signal**:
A parent-to-child message that tells a **Remote Interactive Agent** that no further work is requested.
_Avoid_: Accept signal, abort signal

**Child Status Event**:
A lightweight DBOS event that exposes a **Child Agent** lifecycle state to its parent.
_Avoid_: Full telemetry, trajectory event

**Waiting for Command**:
An **Interactive Root Agent** lifecycle state meaning the Agent is idle and available for future **Resume**.
_Avoid_: Closed, finished, waiting for parent

**First Observable Event**:
A lightweight DBOS event set by a **Child Agent** when it first reaches a parent-actionable state.
_Avoid_: Child result, workflow result, parent message

**Trajectory Artifact**:
A JSON file containing the message history and metadata for one **Agent**.
_Avoid_: DBOS event log, mini-mas history

**Agent Artifact Directory**:
The artifact directory scoped to one **Agent**.
_Avoid_: Run Directory, root-scoped history directory, global history directory

**MAS Workspace State Directory**:
The `.mini-mas/` directory that contains workspace-local MAS artifacts and runtime state.
_Avoid_: global config directory, DBOS data directory, run directory

**MAS Runtime State Store**:
The workspace-scoped durable store that backs MAS workflow, event, queue, and Root discovery state.
_Avoid_: system database, user database, agent artifact store, global history database

**Detached Spawn**:
A **MAS Command** that starts one or more **Child Agents** from repeated task arguments and immediately returns their identifiers.
_Avoid_: Background subprocess, fire-and-forget shell

**Waited Spawn**:
A **MAS Command** that starts one or more **Child Agents** from repeated task arguments and waits for **First Observable Events** before returning.
_Avoid_: Synchronous spawn, blocking spawn

**Shared Workspace**:
A working directory that can be accessed by multiple **Agents** during a MAS run.
_Avoid_: Safe workspace, isolated worktree

**Workspace Isolation**:
The separation of child agent file changes into independent worktrees or directories before parent-level reconciliation.
_Avoid_: Bash serialization, command locking

**Authority Model**:
The **MAS Governance** rules that determine which **Agent Interactions** a requester is allowed to perform on which **Agents**.
_Avoid_: Role system, permission hack

**Authority**:
Permission to perform one or more **Agent Interactions** on **Agents** within an **Authority Scope**.
_Avoid_: Ownership, dominance

**Delegated Non-Transitive Authority**:
An **Authority Model** where **Authority** is delegated through parent-child relationships but does not extend from an **Agent** to its descendants.
_Avoid_: Feudal authority, transitive authority, tree-wide authority, supervision boundary

**Authority Scope**:
The set of **Agents** covered by an **Authority**.
_Avoid_: Reach, visibility radius

**Direct Child Authority Policy**:
The current MVP policy implementing **Delegated Non-Transitive Authority** where a **Parent Agent** can perform parent-child **Agent Interactions** only on its direct **Child Agents** by default.
_Avoid_: Full-tree authority, transitive authority

**Authority Grant**:
An explicit assignment of **Authority** that can differ from the default **Direct Child Authority Policy**.
_Avoid_: Special case, bypass

## Relationships

- An **Agent** is backed by one DBOS workflow in the current implementation.
- A **Parent Agent** can start zero or more **Child Agents**.
- A **Child Agent** belongs to exactly one **Parent Agent** when started through **MAS Command Interception**.
- A **Parent Agent** directly controls only its direct **Child Agents**.
- A **Descendant Agent** that is not a direct child is not treated as the parent's **Child Agent** under **Delegated Non-Transitive Authority**.
- The current MVP uses the **Direct Child Authority Policy** and does not include broader **Authority Grants**.
- The **Root Agent** does not have special tree-wide **Authority** under the current **Direct Child Authority Policy**.
- Future **Authority Models** may add broader **Authority Scopes** such as subtree-wide, tree-wide, or peer-to-peer governance.
- A **Root Agent** owns one **Agent Tree** but does not have special tree-wide **Authority** beyond the current **Authority Model**.
- A **Root Agent** is identified by having no **Parent Agent**, not by an `is_root` flag, a global root, or an index entry.
- **Agent Artifacts** are scoped to individual **Agents**, not to **Root Agents** or runs.
- **Agent IDs** use the `mas-<random-hex>` shape and do not encode root identity, parent identity, sibling order, or tree position.
- **Agent Metadata** records stable Agent identity and artifact fields such as Agent ID, optional Parent Agent ID, Agent Artifact Directory, and Trajectory Artifact path.
- Multi-spawn command result ordering may be used for immediate display, but sibling order is not durable Agent metadata.
- A **Standalone MAS Command** issued inside an **Agent** is handled through **MAS Command Interception**.
- An **External MAS CLI** command is used outside an **Agent** and enters MAS governance through a **Root Agent**.
- Every **External MAS CLI** entrypoint creates or addresses an **Interactive Root Agent**; there is no separate non-interactive Root Agent mode for CLI-submitted work.
- `mini-mas` without a subcommand opens an **Interactive Root Agent** for terminal-driven commands.
- `mini-mas` without a subcommand prints the new Root Agent metadata once before entering the command prompt.
- `mini-mas spawn "task"` is a one-shot convenience form that creates an **Interactive Root Agent**, submits the initial spawn command through it, and returns the spawned **Child Agent** metadata.
- One-shot `mini-mas spawn "task A" "task B"` creates one **Interactive Root Agent** and multiple direct **Child Agents** under it.
- One-shot `mini-mas spawn` supports the same Detached Spawn and Waited Spawn options as workflow-layer `mini-mas spawn`.
- One-shot `mini-mas spawn` output emphasizes the spawned **Child Agent** metadata and includes the Root Agent ID for later **Resume**, but does not show Root Agent artifact paths by default.
- External `mini-mas status` discovers **Interactive Root Agents** by querying root workflows, not by reading an Agent-maintained index.
- External `mini-mas status` lists **Interactive Root Agents** only and does not include Child Agent counts or Child Agent status.
- External `mini-mas status` lists all parentless **Interactive Root Agents** in the first version rather than filtering to only active or resumable roots.
- External `mini-mas status` does not include latest commands or history summaries; durable command history is read from **Trajectory Artifacts**.
- `mini-mas resume <root-agent-id>` re-enters an existing **Interactive Root Agent**.
- `mini-mas resume <root-agent-id>` prints the Root Agent metadata once before entering the command prompt.
- `mini-mas resume <root-agent-id>` is allowed only when the **Interactive Root Agent** is **Waiting for Command** in the first version.
- The implementation may distinguish **Interactive Root Agents** from other root workflows by workflow type/name instead of storing an interaction-mode flag in **Agent Metadata**.
- Naked external/operator `status`, `wait`, `continue`, and `close` commands are not maintained as MAS governance authority paths in the current design.
- A **Remote Interactive Agent** waits for either a **Continuation Signal** or a **Close Signal** after producing a submission.
- An **Interactive Root Agent** remains available after one-shot spawn so later external commands can enter through the same parent authority context.
- An **Interactive Root Agent** receives terminal user commands as agent actions and still follows the current **Authority Model**.
- Detaching from an **Interactive Root Agent** terminal does not close the **Root Agent**; the **Root Agent** remains in **Waiting for Command** and can be resumed later.
- An **Interactive Root Agent** supports at most one active terminal attachment in the first version.
- A one-shot external command such as `mini-mas spawn` occupies the **Interactive Root Agent** attachment while its submitted command is running, then detaches after returning.
- An **Interactive Root Agent** is `running` while executing ordinary bash or detached MAS commands, and `waiting_for_child` while executing `mini-mas wait` or `mini-mas spawn --wait`.
- The **External MAS CLI** sends user commands to an **Interactive Root Agent** through **Root Command Signals**; the CLI does not execute the Root Agent's actions directly.
- An **Interactive Root Agent** publishes each **Root Command Result** as a command-id-scoped event that the **External MAS CLI** waits on.
- **Root Command Results** use the existing MAS Agent command result shape unless a future CLI protocol design introduces a narrower schema.
- Explicit **Root Agent** closure and cleanup are deferred; the first version supports detach and resume, not `close-root`.
- Terminal input inside an **Interactive Root Agent** follows the existing bash-shaped human command flow: standalone `mini-mas ...` commands are intercepted as **MAS Commands**, while ordinary bash commands execute as bash actions.
- Terminal input inside an **Interactive Root Agent** does not add prefix-free MAS shorthand; MAS interactions use full standalone `mini-mas ...` commands.
- Ordinary bash actions entered in an **Interactive Root Agent** are recorded in that Root Agent's **Trajectory Artifact**.
- Interactive Root terminal history is not stored in a separate prompt-history file and does not reuse the existing `mini` prompt history; the Root Agent's **Trajectory Artifact** is the durable command history.
- A **Close Signal** ends a **Remote Interactive Agent** without judging whether the child output was accepted or rejected.
- A **Child Status Event** reports coarse lifecycle states such as `running`, `waiting_for_parent`, `closed`, `failed`, and `limits_exceeded`.
- A **First Observable Event** is set when a **Child Agent** first reaches `waiting_for_parent`, `failed`, or `limits_exceeded`.
- The MVP exposes lightweight child events such as `status`, `latest_submission`, and `latest_error`; full trajectory data remains outside DBOS events.
- **Trajectory Artifacts** live under **Agent Artifact Directories** keyed by **Agent ID**.
- `mini-mas status` and `mini-mas wait` return the exact **Trajectory Artifact** path and **Agent Artifact Directory** for full history inspection.
- Workflow-layer `mini-mas status`, `mini-mas wait`, `mini-mas continue`, and `mini-mas close` derive the current **Parent Agent** from `DBOS.workflow_id`.
- Direct child scope is resolved from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`.
- Artifact paths are derived from **Agent IDs**, not from **Root Agents**, ancestor paths, or run identifiers.
- `mini-mas status` without an **Agent ID** reports the current **Parent Agent**'s direct **Child Agents**, not the parent itself and not deeper descendants.
- `mini-mas status <agent-id>` inspects one direct **Child Agent** and respects **Delegated Non-Transitive Authority**.
- `mini-mas wait <agent-id>` waits for one direct **Child Agent** and respects **Delegated Non-Transitive Authority**.
- Explicit **Agent IDs** in `status <agent-id>`, `wait <agent-id>`, `continue <agent-id>`, and `close <agent-id>` are target identifiers, not scope overrides.
- `mini-mas wait`, `mini-mas continue`, and `mini-mas close` respect **Delegated Non-Transitive Authority** in the current MVP.
- Full history search is performed with ordinary bash tools against **Trajectory Artifacts**, not with dedicated `mini-mas` history, logs, or grep commands.
- A **MAS Runtime State Store** is scoped to one **Shared Workspace** by default, not to the whole user account.
- The default **MAS Workspace State Directory** is `.mini-mas/` in the active **Shared Workspace**.
- The default **MAS Runtime State Store** is `.mini-mas/runtime/mini_mas_dbos.sqlite`, separate from **Agent Artifact Directories** under `.mini-mas/agents/`.
- The default **MAS Runtime State Store** is resolved relative to the current working directory; ordinary project-local MAS usage does not provide a separate state-root configuration.
- Runtime creation of the **MAS Workspace State Directory** does not modify user project version-control ignore files.
- `mini-mas status` discovers **Interactive Root Agents** from the active **MAS Runtime State Store**.
- Separate **Shared Workspaces** have separate default **MAS Runtime State Stores** and do not discover each other's **Interactive Root Agents** by default.
- `mini-mas spawn "task A" "task B"` starts one **Child Agent** per repeated task argument.
- `mini-mas spawn` defaults to **Detached Spawn**.
- `mini-mas spawn --wait` requests **Waited Spawn**.
- **Waited Spawn** defaults to wait-any behavior; a parent uses explicit all-waiting only when it needs all started children to become observable.
- `mini-mas spawn --wait --timeout <seconds>` bounds only the **Waited Spawn** wait phase.
- A **Waited Spawn** timeout does not cancel, close, fail, or retry started **Child Agents**.
- `mini-mas spawn --timeout <seconds>` without `--wait` is invalid because **Detached Spawn** has no wait phase.
- `mini-mas wait` waits on **First Observable Events** for child **Agent IDs**, not on final DBOS workflow results.
- **Child Agents** publish parent-observable state through DBOS events; **Continuation Signals** and **Close Signals** are parent-to-child DBOS messages.
- The MVP may allow multiple **Agents** to use a **Shared Workspace**.
- **Workspace Isolation** is deferred beyond the MVP and should not be replaced by global bash command serialization.

## Example Dialogue

> **Dev:** "When an agent runs `mini-mas spawn`, does that create a subprocess?"
> **Domain expert:** "Inside an Agent, no. It is a MAS Command handled by MAS Command Interception so DBOS can preserve the Parent Agent to Child Agent relationship."

> **Dev:** "When a child agent submits, is that the end of the child workflow?"
> **Domain expert:** "No. A Remote Interactive Agent waits for a Continuation Signal or a neutral Close Signal from its parent."

> **Dev:** "Can DBOS queue concurrency make several child agents safe to run in the same checkout?"
> **Domain expert:** "No. Queue concurrency limits capacity, while Workspace Isolation is the mechanism that would address file-level coordination."

> **Dev:** "Does `mini-mas spawn` wait for child results?"
> **Domain expert:** "No. Spawn is detached by default; use `mini-mas spawn --wait` or `mini-mas wait` to synchronize."

> **Dev:** "Does `mini-mas spawn --wait` wait for child workflows to finish?"
> **Domain expert:** "No. It waits for First Observable Events, so a child can submit and then keep waiting for a Continuation Signal or Close Signal."

> **Dev:** "Does external one-shot `mini-mas spawn --wait` have different wait semantics?"
> **Domain expert:** "No. It submits the same Waited Spawn through an Interactive Root Agent and keeps that Root Agent resumable afterward."

> **Dev:** "If `mini-mas spawn --wait --timeout 30` times out, are the children stopped?"
> **Domain expert:** "No. The timeout only ends the parent's current wait action; the started Child Agents keep running."

> **Dev:** "How does one command start several children?"
> **Domain expert:** "Use repeated task arguments, such as `mini-mas spawn \"inspect api\" \"write tests\"`; the command returns one Agent ID per child."

> **Dev:** "Does external one-shot multi-spawn create multiple Root Agents?"
> **Domain expert:** "No. It creates one Interactive Root Agent and multiple direct Child Agents under it."

> **Dev:** "Can an agent write `mini-mas spawn ... && echo done`?"
> **Domain expert:** "Not for the MVP. A MAS Command must be standalone to receive in-process interception."

> **Dev:** "Where should a parent agent search for child history?"
> **Domain expert:** "Use the exact Trajectory Artifact path returned by status or wait; artifacts are scoped to Agents, not to Root Agents or runs."

> **Dev:** "Can a parent agent directly continue a grandchild agent?"
> **Domain expert:** "No. Under Delegated Non-Transitive Authority, the child agent of my child agent is not my child agent."

> **Dev:** "Can `mini-mas wait <agent-id>` wait for a grandchild if I know the ID?"
> **Domain expert:** "No. The explicit Agent ID is only a target. The scope still comes from the current DBOS workflow context, so the target must be a direct child."

> **Dev:** "Does opening the MAS terminal give the user tree-wide control?"
> **Domain expert:** "No. In the Interactive Root Agent model, terminal commands enter through the root agent, and the root agent follows the same Authority Model as any other Parent Agent."

> **Dev:** "Is `mini-mas spawn \"task\"` a different Root Agent type from `mini-mas`?"
> **Domain expert:** "No. Both enter through an Interactive Root Agent; one-shot spawn only submits the first spawn command automatically."

> **Dev:** "What should plain `mini-mas` show before the first prompt?"
> **Domain expert:** "It prints the new Root Agent metadata once, matching the resume banner."

> **Dev:** "Inside an Interactive Root Agent, should the user type `status` or `mini-mas status`?"
> **Domain expert:** "Use full standalone `mini-mas ...` commands; prefix-free shorthand is not part of the first version."

> **Dev:** "Can an Interactive Root Agent run ordinary bash commands?"
> **Domain expert:** "Yes. It follows the existing human command flow: standalone `mini-mas ...` is intercepted by MAS, and ordinary bash is executed as bash."

> **Dev:** "Where is ordinary bash history from an Interactive Root Agent stored?"
> **Domain expert:** "In the Root Agent's Trajectory Artifact, just like other human-entered actions and observations."

> **Dev:** "Does the Interactive Root terminal keep a separate readline-style history file?"
> **Domain expert:** "No. It does not reuse or create prompt-history files; durable command history lives in the Root Agent's Trajectory Artifact."

> **Dev:** "How does external `mini-mas status` find roots?"
> **Domain expert:** "It queries workflows with no Parent Agent and the Interactive Root Agent workflow type; Root is structural, not a metadata flag."

> **Dev:** "Does external `mini-mas status` show child status?"
> **Domain expert:** "No. It only lists resumable Interactive Root Agents; enter one with `resume` and run status there for direct children."

> **Dev:** "Does external `mini-mas status` hide failed Root Agents?"
> **Domain expert:** "No. The first version lists all parentless Interactive Root Agents and shows their lifecycle state."

> **Dev:** "Does external `mini-mas status` summarize recent Root Agent commands?"
> **Domain expert:** "No. It stays a Root Agent discovery view; command history lives in Trajectory Artifacts."

> **Dev:** "How does a user get back to a Root Agent created by one-shot spawn?"
> **Domain expert:** "Use `mini-mas resume <root-agent-id>` to re-enter that Interactive Root Agent."

> **Dev:** "What should `resume` show before the prompt?"
> **Domain expert:** "It prints the Root Agent metadata once, then enters the command prompt."

> **Dev:** "Can a failed or currently-running Root Agent be resumed?"
> **Domain expert:** "No. The first version only resumes Root Agents that are Waiting for Command."

> **Dev:** "What state is a Root Agent in while running ordinary bash?"
> **Domain expert:** "`running`; `waiting_for_command` means idle and resumable, while `waiting_for_child` is reserved for MAS waits."

> **Dev:** "Does exiting the terminal close the Interactive Root Agent?"
> **Domain expert:** "No. Exiting detaches from the terminal; the Root Agent remains Waiting for Command until resumed."

> **Dev:** "Can two terminals resume the same Root Agent at once?"
> **Domain expert:** "No. The first version supports at most one active terminal attachment per Interactive Root Agent."

> **Dev:** "Can a user resume a Root Agent while one-shot spawn is still waiting?"
> **Domain expert:** "No. One-shot spawn occupies the Root Agent attachment until its submitted command returns or times out."

> **Dev:** "When a user types a command after resume, who executes it?"
> **Domain expert:** "The CLI sends a Root Command Signal, and the Interactive Root Agent executes the bash-shaped action flow itself."

> **Dev:** "How does the CLI receive the result of a Root command?"
> **Domain expert:** "It waits for the command-id-scoped Root Command Result event published by the Interactive Root Agent."

> **Dev:** "Does the Root Command Result define a new CLI payload schema?"
> **Domain expert:** "No. It follows the existing MAS Agent command result shape until a future protocol design needs more detail."

> **Dev:** "Can users close a Root Agent in the first version?"
> **Domain expert:** "No. Root closure and cleanup are deferred; `close` remains a parent-to-child command."

> **Dev:** "Does one-shot spawn print the Root Agent artifact path?"
> **Domain expert:** "No. It prints the spawned Child Agent artifact path and the Root Agent ID needed for resume."

> **Dev:** "How do we tell which sibling was returned first if Agent IDs are random?"
> **Domain expert:** "Use the current multi-spawn command result order for display; sibling order is not durable Agent metadata."

> **Dev:** "Does the Root Agent ID determine where child artifacts are stored?"
> **Domain expert:** "No. Root identifies the CLI entry Agent; each Agent owns its own artifact directory."

> **Dev:** "If I run `mini-mas status` in another repository, should I see Roots from this one?"
> **Domain expert:** "No. By default each Shared Workspace has its own MAS Runtime State Store, so Root discovery is workspace-local unless the runtime is explicitly pointed at a shared external store."

> **Dev:** "Is the DBOS SQLite file a repo-root file?"
> **Domain expert:** "No. The default MAS Runtime State Store is `.mini-mas/runtime/mini_mas_dbos.sqlite`, separate from Agent Artifact Directories."

> **Dev:** "Can I point normal `mini-mas` at a different local state root?"
> **Domain expert:** "No. Ordinary project-local MAS usage resolves the MAS Workspace State Directory from the current working directory."

> **Dev:** "Does `mini-mas` edit my project's `.gitignore` when it creates `.mini-mas/`?"
> **Domain expert:** "No. Version-control ignore policy belongs to the user project; MAS only creates its workspace state directory."

## Flagged Ambiguities

- "Agent" can mean both a MAS participant and the Python agent implementation class. Resolved: use **Agent** for the MAS participant, and say agent class, `DefaultAgent`, or agent implementation for Python code objects.
- "mini-mas command" can mean both an internal agent-issued command and the external shell command. Resolved: use **MAS Command** for the internal bash-level request and **External MAS CLI** for the real command run outside an **Agent**.
- "close" can sound like acceptance or cancellation. Resolved: **Close Signal** is neutral and only means no further work is requested.
- "serialize bash steps" can sound like **Workspace Isolation**. Resolved: global command serialization does not protect the full read-reason-write window across multiple agent turns.
- "wait for a child handle" can sound like waiting for the final DBOS workflow result. Resolved: `mini-mas wait` waits for a **First Observable Event** for a child **Agent ID**.
- "descendant" can sound like it grants transitive control. Resolved: the current MVP follows **Delegated Non-Transitive Authority**; broader multi-level control models are future design space.
- "role" can sound like a fixed RBAC role. Resolved: use **Authority Model**, **Authority**, **Authority Scope**, and **Authority Grant** for MAS governance permissions.
- "explicit Agent ID" can sound like a scope override. Resolved: explicit IDs in workflow-layer commands identify a target only; authority still comes from `DBOS.workflow_id` and DBOS `parent_workflow_id` metadata.
- "external CLI" can sound like operator superuser access. Resolved: naked external/operator query and control paths are not maintained in the current design; future terminal control should enter through an **Interactive Root Agent**.
- "root" can sound like artifact scope or tree-wide authority. Resolved: **Root Agent** is the top-level **Parent Agent** for CLI-submitted work, while artifacts are scoped per **Agent** and authority remains governed by the **Authority Model**.
- "Agent metadata" can sound like a place for query flags. Resolved: root discovery uses workflow parent structure and workflow type; **Agent Metadata** stays limited to identity and artifact description.
- "system database" can sound like a user-facing configuration concept or a global mini-swe-agent database. Resolved: use **MAS Runtime State Store** for the MAS durable workflow/event/queue store, and keep it workspace-scoped by default.
