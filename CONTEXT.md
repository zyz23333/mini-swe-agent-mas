# mini-swe-agent MAS

This context describes the proposed multi-agent extension for mini-swe-agent, where DBOS durable workflows coordinate parent and child agent runs while preserving the existing bash-first agent interface.

## Language

**Agent Workflow**:
A DBOS workflow that runs one mini-swe-agent agent invocation.
_Avoid_: Agent process, agent thread

**Parent Agent Workflow**:
An **Agent Workflow** that delegates work to one or more **Child Agent Workflows**.
_Avoid_: Master agent, orchestrator process

**Root Agent Workflow**:
The top-level **Agent Workflow** for a MAS run.
_Avoid_: Main process, root process

**Child Agent Workflow**:
An **Agent Workflow** started by a **Parent Agent Workflow** to work on a delegated task.
_Avoid_: Worker process, subagent process

**Descendant Agent Workflow**:
An **Agent Workflow** recursively started below a **Root Agent Workflow**.
_Avoid_: Nested process, recursive worker

**Agent Workflow Tree**:
The recursive parent-child structure formed by **Agent Workflows** in one MAS run.
_Avoid_: Process tree

**Workflow Tree ID**:
A readable DBOS workflow identifier that encodes an **Agent Workflow** position in its **Agent Workflow Tree**, such as `mas-a7f3c9d4e8b11234-c001-c002`.
_Avoid_: Random UUID, path

**MAS Command**:
A bash command beginning with `mini-mas` that an agent emits to request multi-agent coordination.
_Avoid_: Tool call, DBOS command

**Standalone MAS Command**:
A **MAS Command** that occupies the entire agent action command without shell operators, environment assignments, loops, pipes, or redirections.
_Avoid_: Embedded mini-mas command, shell fragment

**MAS Command Interception**:
The in-process handling of a **MAS Command** by a DBOS-aware environment instead of executing it as a normal subprocess.
_Avoid_: Shell plugin, subprocess hook

**External MAS CLI**:
The real `mini-mas` command used outside an **Agent Workflow** to submit or inspect multi-agent work.
_Avoid_: Internal mini-mas

**Remote Interactive Agent**:
A child agent whose post-submission continuation is controlled by its **Parent Agent Workflow** instead of a local terminal user.
_Avoid_: TTY agent, long-running worker

**Continuation Signal**:
A parent-to-child message that asks a **Remote Interactive Agent** to continue working from its existing trajectory.
_Avoid_: New task command, resume event

**Close Signal**:
A parent-to-child message that tells a **Remote Interactive Agent** that no further work is requested.
_Avoid_: Accept signal, abort signal

**Child Status Event**:
A lightweight DBOS event that exposes a **Child Agent Workflow** lifecycle state to its parent.
_Avoid_: Full telemetry, trajectory event

**First Observable Event**:
A lightweight DBOS event set by a **Child Agent Workflow** when it first reaches a parent-actionable state.
_Avoid_: Child result, workflow result, parent message

**Trajectory Artifact**:
A JSON file containing the message history and run metadata for an **Agent Workflow**.
_Avoid_: DBOS event log, mini-mas history

**Run Directory**:
The artifact directory scoped to one **Root Agent Workflow**.
_Avoid_: Global history directory, log folder

**Detached Spawn**:
A **MAS Command** that starts one or more **Child Agent Workflows** from repeated task arguments and immediately returns their identifiers.
_Avoid_: Background subprocess, fire-and-forget shell

**Waited Spawn**:
A **MAS Command** that starts one or more **Child Agent Workflows** from repeated task arguments and waits for **First Observable Events** before returning.
_Avoid_: Synchronous spawn, blocking spawn

**Shared Workspace**:
A working directory that can be accessed by multiple **Agent Workflows** during a MAS run.
_Avoid_: Safe workspace, isolated worktree

**Workspace Isolation**:
The separation of child agent file changes into independent worktrees or directories before parent-level reconciliation.
_Avoid_: Bash serialization, command locking

## Relationships

- A **Parent Agent Workflow** can start zero or more **Child Agent Workflows**.
- A **Child Agent Workflow** belongs to exactly one **Parent Agent Workflow** when started through **MAS Command Interception**.
- A **Root Agent Workflow** owns one **Agent Workflow Tree**.
- A **Descendant Agent Workflow** belongs to the same **Run Directory** as its **Root Agent Workflow**.
- **Workflow Tree IDs** use the form `mas-<16hex>` for roots and append `-cNNN` segments for descendants.
- A **Standalone MAS Command** issued inside an **Agent Workflow** is handled through **MAS Command Interception**.
- An **External MAS CLI** command is used outside an **Agent Workflow** and does not itself imply a parent-child workflow relationship.
- A **Remote Interactive Agent** waits for either a **Continuation Signal** or a **Close Signal** after producing a submission.
- A **Close Signal** ends a **Remote Interactive Agent** without judging whether the child output was accepted or rejected.
- A **Child Status Event** reports coarse lifecycle states such as `running`, `waiting_for_parent`, `closed`, `failed`, and `limits_exceeded`.
- A **First Observable Event** is set when a **Child Agent Workflow** first reaches `waiting_for_parent`, `failed`, or `limits_exceeded`.
- The MVP exposes lightweight child events such as `status`, `latest_submission`, and `latest_error`; full trajectory data remains outside DBOS events.
- **Trajectory Artifacts** live under `.mini-mas/runs/<root-workflow-id>/trajectories/<workflow-id>.traj.json`.
- `mini-mas status` and `mini-mas wait` return the exact **Trajectory Artifact** path and **Run Directory** for full history inspection.
- Full history search is performed with ordinary bash tools against **Trajectory Artifacts**, not with dedicated `mini-mas` history, logs, or grep commands.
- `mini-mas spawn "task A" "task B"` starts one **Child Agent Workflow** per repeated task argument.
- `mini-mas spawn` defaults to **Detached Spawn**.
- `mini-mas spawn --wait` requests **Waited Spawn**.
- **Waited Spawn** defaults to wait-any behavior; a parent uses explicit all-waiting only when it needs all started children to become observable.
- `mini-mas spawn --wait --timeout <seconds>` bounds only the **Waited Spawn** wait phase.
- A **Waited Spawn** timeout does not cancel, close, fail, or retry started **Child Agent Workflows**.
- `mini-mas spawn --timeout <seconds>` without `--wait` is invalid because **Detached Spawn** has no wait phase.
- `mini-mas wait` waits on **First Observable Events** for child workflow identifiers, not on final DBOS workflow results.
- **Child Agent Workflows** publish parent-observable state through DBOS events; **Continuation Signals** and **Close Signals** are parent-to-child DBOS messages.
- The MVP may allow multiple **Agent Workflows** to use a **Shared Workspace**.
- **Workspace Isolation** is deferred beyond the MVP and should not be replaced by global bash command serialization.

## Example Dialogue

> **Dev:** "When an agent runs `mini-mas spawn`, does that create a subprocess?"
> **Domain expert:** "Inside an Agent Workflow, no. It is a MAS Command handled by MAS Command Interception so DBOS can preserve the Parent Agent Workflow to Child Agent Workflow relationship."

> **Dev:** "When a child agent submits, is that the end of the child workflow?"
> **Domain expert:** "No. A Remote Interactive Agent waits for a Continuation Signal or a neutral Close Signal from its parent."

> **Dev:** "Can DBOS queue concurrency make several child agents safe to run in the same checkout?"
> **Domain expert:** "No. Queue concurrency limits capacity, while Workspace Isolation is the mechanism that would address file-level coordination."

> **Dev:** "Does `mini-mas spawn` wait for child results?"
> **Domain expert:** "No. Spawn is detached by default; use `mini-mas spawn --wait` or `mini-mas wait` to synchronize."

> **Dev:** "Does `mini-mas spawn --wait` wait for child workflows to finish?"
> **Domain expert:** "No. It waits for First Observable Events, so a child can submit and then keep waiting for a Continuation Signal or Close Signal."

> **Dev:** "If `mini-mas spawn --wait --timeout 30` times out, are the children stopped?"
> **Domain expert:** "No. The timeout only ends the parent's current wait action; the started Child Agent Workflows keep running."

> **Dev:** "How does one command start several children?"
> **Domain expert:** "Use repeated task arguments, such as `mini-mas spawn \"inspect api\" \"write tests\"`; the command returns one Workflow Tree ID per child."

> **Dev:** "Can an agent write `mini-mas spawn ... && echo done`?"
> **Domain expert:** "Not for the MVP. A MAS Command must be standalone to receive in-process interception."

> **Dev:** "Where should a parent agent search for child history?"
> **Domain expert:** "Use the exact Trajectory Artifact path returned by status or wait, scoped to the current Run Directory."

## Flagged Ambiguities

- "mini-mas command" can mean both an internal agent-issued command and the external shell command. Resolved: use **MAS Command** for the internal bash-level request and **External MAS CLI** for the real command run outside an **Agent Workflow**.
- "close" can sound like acceptance or cancellation. Resolved: **Close Signal** is neutral and only means no further work is requested.
- "serialize bash steps" can sound like **Workspace Isolation**. Resolved: global command serialization does not protect the full read-reason-write window across multiple agent turns.
- "wait for a child handle" can sound like waiting for the final DBOS workflow result. Resolved: `mini-mas wait` waits for a **First Observable Event** for a child workflow identifier.
