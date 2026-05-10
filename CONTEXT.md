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
The top-level **Agent** for a MAS run.
_Avoid_: Main process, root process

**Child Agent**:
An **Agent** started by a **Parent Agent** to work on a delegated task.
_Avoid_: Worker process, subagent process

**Descendant Agent**:
An **Agent** recursively started below a **Root Agent**.
_Avoid_: Nested process, recursive worker

**Agent Tree**:
The recursive parent-child structure formed by **Agents** in one MAS run.
_Avoid_: Process tree

**Agent ID**:
A readable identifier that encodes an **Agent** position in its **Agent Tree**, such as `mas-a7f3c9d4e8b11234-c001-c002`.
_Avoid_: Workflow Tree ID, random UUID, path

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

**Remote Interactive Agent**:
A **Child Agent** whose post-submission continuation is controlled by its **Parent Agent** instead of a local terminal user.
_Avoid_: TTY agent, long-running worker

**Interactive Root Agent**:
A **Root Agent** whose next action is supplied by an external terminal user through DBOS messages instead of by a model query.
_Avoid_: External shell controller, terminal superuser

**Continuation Signal**:
A parent-to-child message that asks a **Remote Interactive Agent** to continue working from its existing trajectory.
_Avoid_: New task command, resume event

**Close Signal**:
A parent-to-child message that tells a **Remote Interactive Agent** that no further work is requested.
_Avoid_: Accept signal, abort signal

**Child Status Event**:
A lightweight DBOS event that exposes a **Child Agent** lifecycle state to its parent.
_Avoid_: Full telemetry, trajectory event

**First Observable Event**:
A lightweight DBOS event set by a **Child Agent** when it first reaches a parent-actionable state.
_Avoid_: Child result, workflow result, parent message

**Trajectory Artifact**:
A JSON file containing the message history and run metadata for an **Agent**.
_Avoid_: DBOS event log, mini-mas history

**Run Directory**:
The artifact directory scoped to one **Root Agent**.
_Avoid_: Global history directory, log folder

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
- A **Root Agent** owns one **Agent Tree**.
- A **Descendant Agent** belongs to the same **Run Directory** as its **Root Agent**.
- **Agent IDs** use the form `mas-<16hex>` for roots and append `-cNNN` segments for descendants.
- A **Standalone MAS Command** issued inside an **Agent** is handled through **MAS Command Interception**.
- An **External MAS CLI** command is used outside an **Agent** and does not itself imply a parent-child relationship.
- Naked external/operator `status`, `wait`, `continue`, and `close` commands are not maintained as MAS governance authority paths in the current design.
- A **Remote Interactive Agent** waits for either a **Continuation Signal** or a **Close Signal** after producing a submission.
- An **Interactive Root Agent** receives terminal user commands as agent actions and still follows the current **Authority Model**.
- A **Close Signal** ends a **Remote Interactive Agent** without judging whether the child output was accepted or rejected.
- A **Child Status Event** reports coarse lifecycle states such as `running`, `waiting_for_parent`, `closed`, `failed`, and `limits_exceeded`.
- A **First Observable Event** is set when a **Child Agent** first reaches `waiting_for_parent`, `failed`, or `limits_exceeded`.
- The MVP exposes lightweight child events such as `status`, `latest_submission`, and `latest_error`; full trajectory data remains outside DBOS events.
- **Trajectory Artifacts** live under `.mini-mas/runs/<root-workflow-id>/trajectories/<workflow-id>.traj.json`.
- `mini-mas status` and `mini-mas wait` return the exact **Trajectory Artifact** path and **Run Directory** for full history inspection.
- Workflow-layer `mini-mas status`, `mini-mas wait`, `mini-mas continue`, and `mini-mas close` derive the current **Parent Agent** from `DBOS.workflow_id`.
- Direct child scope is resolved from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`.
- `root_workflow_id` is derived for artifact paths and display; it is not a status, wait, or control scope input.
- `mini-mas status` without an **Agent ID** reports the current **Parent Agent**'s direct **Child Agents**, not the parent itself and not deeper descendants.
- `mini-mas status <agent-id>` inspects one direct **Child Agent** and respects **Delegated Non-Transitive Authority**.
- `mini-mas wait <agent-id>` waits for one direct **Child Agent** and respects **Delegated Non-Transitive Authority**.
- Explicit **Agent IDs** in `status <agent-id>`, `wait <agent-id>`, `continue <agent-id>`, and `close <agent-id>` are target identifiers, not scope overrides.
- `mini-mas wait`, `mini-mas continue`, and `mini-mas close` respect **Delegated Non-Transitive Authority** in the current MVP.
- Full history search is performed with ordinary bash tools against **Trajectory Artifacts**, not with dedicated `mini-mas` history, logs, or grep commands.
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

> **Dev:** "If `mini-mas spawn --wait --timeout 30` times out, are the children stopped?"
> **Domain expert:** "No. The timeout only ends the parent's current wait action; the started Child Agents keep running."

> **Dev:** "How does one command start several children?"
> **Domain expert:** "Use repeated task arguments, such as `mini-mas spawn \"inspect api\" \"write tests\"`; the command returns one Agent ID per child."

> **Dev:** "Can an agent write `mini-mas spawn ... && echo done`?"
> **Domain expert:** "Not for the MVP. A MAS Command must be standalone to receive in-process interception."

> **Dev:** "Where should a parent agent search for child history?"
> **Domain expert:** "Use the exact Trajectory Artifact path returned by status or wait, scoped to the current Run Directory."

> **Dev:** "Can a parent agent directly continue a grandchild agent?"
> **Domain expert:** "No. Under Delegated Non-Transitive Authority, the child agent of my child agent is not my child agent."

> **Dev:** "Can `mini-mas wait <agent-id>` wait for a grandchild if I know the ID?"
> **Domain expert:** "No. The explicit Agent ID is only a target. The scope still comes from the current DBOS workflow context, so the target must be a direct child."

> **Dev:** "Does opening the MAS terminal give the user tree-wide control?"
> **Domain expert:** "No. In the Interactive Root Agent model, terminal commands enter through the root agent, and the root agent follows the same Authority Model as any other Parent Agent."

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
