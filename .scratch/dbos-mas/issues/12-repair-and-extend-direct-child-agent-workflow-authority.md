# Repair and extend direct-child Agent Workflow authority

Status: ready-for-agent
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Repair the existing first-level MAS coordination implementation so workflow-layer authority is derived from DBOS workflow context, then extend the same **Direct Child Authority Policy** to recursive Child Agent Workflows.

This issue is not only an additive recursive-spawn feature. It must first harden the existing `status`, `wait`, `continue`, and `close` behavior so current Parent Agent Workflow authority comes from `DBOS.workflow_id` and direct-child relationships come from DBOS workflow metadata. Existing paths that rely on manually threaded template variables, `root_workflow_id`, Workflow Tree ID prefixes, broad root-tree scans, DBOS API object parameters, or naked external/operator query/control APIs must be repaired or made explicitly unsupported.

After that repair, allow a Child Agent Workflow to act as a Parent Agent Workflow for its own direct children. Recursive delegation should preserve the Agent Workflow Tree, deterministic Workflow Tree IDs, shared Root Run Directory, and the same status, wait, continue, and close coordination semantics used for first-level children, but only across direct parent-child boundaries.

This slice should demonstrate a root, child, and grandchild workflow coordinated through MAS commands without granting the root direct control over the grandchild.

## Design constraints

- A Parent Agent Workflow coordinates only its direct Child Agent Workflows by default.
- The Root Agent Workflow has no special tree-wide Coordination Authority.
- The child agent of my child agent is not my child agent.
- Broader subtree-wide or tree-wide control is out of scope for this slice and belongs to a future Coordination Authority Model with explicit Authority Grants.
- Workflow-layer MAS dispatch must use `DBOS.workflow_id` as the authoritative current Parent Agent Workflow identity.
- Workflow-layer MAS dispatch must fail with a clear model-visible error when `DBOS.workflow_id` is absent.
- Workflow-layer MAS dispatch must not accept or maintain `root_workflow_id`, a caller-supplied current workflow ID, a DBOS API object, or an external operator identity as an authority input.
- Direct-child scope must be resolved from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`.
- Workflow Tree ID prefixes, Root Agent Workflow IDs, and broad root-tree scans must not be used as authorization sources.
- `root_workflow_id`, when needed for Run Directory or Trajectory Artifact paths, should be derived from the relevant Workflow Tree ID rather than maintained as coordination scope.
- Naked external/operator `status`, `wait`, `continue`, and `close` paths are not part of this slice; they may be unsupported until terminal commands are routed through an Interactive Root Agent Workflow.

## Acceptance criteria

- [ ] Existing first-level `status`, `wait`, `continue`, and `close` behavior is migrated to the `DBOS.workflow_id` plus `parent_workflow_id == DBOS.workflow_id` authority model before recursive behavior is added.
- [ ] Existing workflow-layer MAS dispatch no longer relies on manually threaded template variables, `root_workflow_id`, DBOS API object parameters, or Workflow Tree ID prefix scans to establish current coordination authority.
- [ ] Existing naked external/operator `status`, `wait`, `continue`, and `close` paths are removed from the maintained path or return explicit unsupported results until the Interactive Root Agent Workflow terminal model exists.
- [ ] A Child Agent Workflow can issue `mini-mas spawn "task"` as a Standalone MAS Command and start a grandchild Agent Workflow.
- [ ] A Child Agent Workflow can issue `mini-mas spawn "task A" "task B"` as a Standalone MAS Command and start one grandchild Agent Workflow per task.
- [ ] Grandchild Workflow Tree IDs append another deterministic `-cNNN` segment to their direct parent ID, for example `mas-<16hex>-c001-c001`.
- [ ] Sibling grandchildren under the same Child Agent Workflow receive stable IDs such as `-c001` and `-c002`.
- [ ] Grandchildren under different Child Agent Workflows do not collide with each other or with root-level Child Agent Workflow IDs.
- [ ] Descendant Agent Workflows share the Root Agent Workflow's Run Directory.
- [ ] Descendant Trajectory Artifacts use deterministic paths under the Root Agent Workflow's Run Directory and include the full descendant Workflow Tree ID.
- [ ] `mini-mas status` from a Parent Agent Workflow reports that parent's direct Child Agent Workflows only, excluding the parent itself, grandchildren, siblings, ancestors, and workflows outside the tree.
- [ ] `mini-mas status <workflow-id>` from a Parent Agent Workflow succeeds only when the target is that parent's direct Child Agent Workflow.
- [ ] `mini-mas wait --any`, `mini-mas wait --all`, and bounded wait from a Parent Agent Workflow wait only for that parent's direct Child Agent Workflows.
- [ ] `mini-mas wait <workflow-id>` from a Parent Agent Workflow succeeds only when the target is that parent's direct Child Agent Workflow.
- [ ] Waited Spawn and `mini-mas wait` for recursive direct children synchronize through First Observable Events keyed by child workflow identifiers, not through `WorkflowHandle.get_result()` or final DBOS workflow completion.
- [ ] `mini-mas continue <workflow-id> "message"` succeeds only when the target is a waiting direct Child Agent Workflow.
- [ ] `mini-mas close <workflow-id>` succeeds only when the target is a waiting direct Child Agent Workflow.
- [ ] Root Agent Workflow attempts to status, wait for, continue, or close a grandchild directly return clear model-visible errors and do not send DBOS messages.
- [ ] Child Agent Workflow attempts to status, wait for, continue, or close siblings, ancestors, root, unknown workflows, or workflows outside the tree return clear model-visible errors and do not send DBOS messages.
- [ ] Recursive direct-child coordination uses the same async Agent Workflow layer and awaited DBOS workflow-control APIs as first-level child coordination.
- [ ] Workflow-layer `status`, `wait`, `continue`, and `close` derive current authority from `DBOS.workflow_id` and do not use caller-supplied current workflow IDs, `root_workflow_id`, DBOS API object parameters, or Workflow Tree ID prefix scans for authorization.
- [ ] External CLI `status`, `wait`, `continue`, and `close` are either removed from the maintained path or return an explicit unsupported message until the Interactive Root Agent Workflow terminal model exists.
- [ ] Tests cover root-child-grandchild spawning, repeated-task grandchild spawning, sibling ID generation, descendant artifact paths, direct-child status/wait behavior, and invalid transitive-control attempts.

## Blocked by

- .scratch/dbos-mas/issues/05-support-detached-spawn-with-deterministic-child-ids.md
- .scratch/dbos-mas/issues/09-implement-waited-spawn-and-mini-mas-wait.md
- .scratch/dbos-mas/issues/10-implement-continuation-signal-for-remote-interactive-agents.md
- .scratch/dbos-mas/issues/11-implement-neutral-close-signal-for-remote-interactive-agents.md

## Comments

> *This was generated by AI during triage.*

## Agent Brief

**Category:** enhancement
**Summary:** Repair MAS coordination authority for existing first-level commands and extend the same direct-child policy to recursive Child Agent Workflows.

**Current behavior:**
The MAS subsystem supports Root Agent Workflows, first-level Child Agent Workflow spawning, repeated-task Detached Spawn, Waited Spawn, `mini-mas wait`, `mini-mas status`, Continuation Signals, and neutral Close Signals. Child Agent Workflows reuse the same Agent Workflow loop as roots, and Workflow Tree IDs already allow additional `-cNNN` descendant segments.

The MAS domain model now uses the **Direct Child Authority Policy**. A Parent Agent Workflow coordinates only its direct Child Agent Workflows by default. The Root Agent Workflow has no special tree-wide Coordination Authority, so the child agent of my child agent is not my child agent.

The existing first-level implementation must be treated as part of this issue, not as a correct base to extend blindly. Workflow-layer coordination currently needs to be hardened so `status`, `wait`, `continue`, and `close` derive current authority from DBOS workflow context and validate targets through DBOS parent workflow metadata rather than through caller-provided state or Workflow Tree ID ancestry.

The explicit blockers for this slice are complete:

- Detached Spawn with deterministic Child Agent Workflow IDs is done.
- Waited Spawn and `mini-mas wait` synchronization are done.
- Continuation Signals for Remote Interactive Agents are done.
- Neutral Close Signals for Remote Interactive Agents are done.

The remaining gap is repairing existing first-level authority handling and then proving recursive coordination under that direct-child policy. A Child Agent Workflow must be able to issue Standalone MAS Commands that create and coordinate its own direct Child Agent Workflows while preserving the Root Agent Workflow's Run Directory, deterministic Workflow Tree IDs, and existing async DBOS coordination semantics. The implementation must avoid treating the full Root Agent Workflow Tree as the current parent's coordination scope.

**Desired behavior:**
Existing first-level `status`, `wait`, `continue`, and `close` behavior should be migrated to the same authority model required for recursive coordination: the current Parent Agent Workflow is `DBOS.workflow_id`, and direct-child scope is `parent_workflow_id == DBOS.workflow_id`. This repair should happen before adding or validating recursive child coordination so the recursive feature is not built on the old authority assumptions.

A Child Agent Workflow should be able to emit `mini-mas spawn "task"` and `mini-mas spawn "task A" "task B"` as Standalone MAS Commands. These commands should start grandchild Agent Workflows through the same async Agent Workflow coordination layer and child workflow queue used for first-level children.

Grandchild Workflow Tree IDs should encode their recursive position by appending another `-cNNN` segment to the direct parent Child Agent Workflow ID. For example, if the root is `mas-<16hex>` and its first child is `mas-<16hex>-c001`, that child's first child should be `mas-<16hex>-c001-c001`. Sibling numbering should remain deterministic within each Parent Agent Workflow, so sibling grandchildren under the same child use `-c001`, `-c002`, and so on without colliding with root-level children or descendants under other parents.

All Descendant Agent Workflows in one Agent Workflow Tree should share the Root Agent Workflow's Run Directory. Their Trajectory Artifacts should live under that same Run Directory and use deterministic paths based on their full Workflow Tree IDs.

`mini-mas status` without a workflow ID should report the current Parent Agent Workflow's direct Child Agent Workflows only. It should not include the parent itself, grandchildren, siblings, ancestors, or workflows outside the current tree. `mini-mas status <workflow-id>` should inspect exactly one direct Child Agent Workflow and should return a clear model-visible error for a grandchild, sibling, ancestor, root, unknown workflow, or workflow outside the current tree.

`mini-mas wait --any`, `mini-mas wait --all`, and bounded wait should wait only for the current Parent Agent Workflow's direct Child Agent Workflows. `mini-mas wait <workflow-id>` should be supported like `mini-mas status <workflow-id>`: the explicit workflow ID is a target identifier, not a scope override, and the command should succeed only when that target is a direct Child Agent Workflow of the current Parent Agent Workflow. All wait behavior must synchronize on First Observable Events keyed by child workflow identifiers, not on final DBOS workflow results.

`mini-mas continue <workflow-id> "message"` and `mini-mas close <workflow-id>` should succeed only when the target is a waiting direct Child Agent Workflow of the current Parent Agent Workflow. Invalid attempts to continue or close grandchildren, siblings, ancestors, root, unknown workflows, workflows outside the tree, or workflows that are not waiting for parent direction should return clear model-visible errors and must not send DBOS messages.

Recursive coordination must preserve the architectural boundary from the PRD and ADRs: Standalone MAS Commands are intercepted at the Agent Workflow layer, workflow-control operations are awaited through async DBOS APIs, and ordinary model calls, bash execution, and Trajectory Artifact persistence remain behind DBOS step boundaries.

Workflow-layer MAS dispatch must use `DBOS.workflow_id` as the authoritative current workflow identity. A Standalone MAS Command that requires Agent Workflow authority must return a clear model-visible error when `DBOS.workflow_id` is absent. Dispatch must not accept or maintain `root_workflow_id`, a caller-supplied current workflow ID, a DBOS API object, or an external operator identity as an authority input.

Direct-child scope must be resolved from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`. Explicit workflow IDs in `status <workflow-id>`, `wait <workflow-id>`, `continue <workflow-id>`, and `close <workflow-id>` are target identifiers only; each target must be authorized against the current `DBOS.workflow_id` before use. Workflow Tree ID prefixes, Root Agent Workflow IDs, and broad root-tree scans must not be used as authorization sources. `root_workflow_id`, when needed for Run Directory or Trajectory Artifact paths, should be derived from the relevant Workflow Tree ID rather than maintained as status, wait, or control scope.

Naked external/operator `status`, `wait`, `continue`, and `close` paths should not be preserved as maintained query/control APIs in this slice. They may return explicit unsupported results until the Interactive Root Agent Workflow terminal design routes terminal commands through a workflow.

**Key interfaces:**
- Standalone MAS Command dispatch - should work from both Root Agent Workflows and Child Agent Workflows without changing model adapter action parsing.
- Current workflow identity - must come from `DBOS.workflow_id` when dispatching in-workflow MAS Commands.
- Child Agent Workflow startup - should accept a recursive parent Workflow Tree ID and create one direct child per task using deterministic descendant IDs.
- Workflow Tree ID allocation - should allocate sibling `-cNNN` segments relative to the current Parent Agent Workflow, not globally across the Root Agent Workflow.
- Direct-child status lookup - should report only direct Child Agent Workflows for `mini-mas status` without a target by querying DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`.
- Direct-child wait lookup - should wait only direct Child Agent Workflows for `mini-mas wait` without a target by querying DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`.
- Direct-child target validation - should ensure explicit `status`, `wait`, `continue`, and `close` targets are direct Child Agent Workflows of the current Parent Agent Workflow by checking DBOS parent workflow metadata, not Workflow Tree ID prefixes.
- First Observable Event waiting - should keep using child-keyed DBOS events for Waited Spawn and `mini-mas wait`.
- Parent-to-child signaling - should deliver Continuation Signals and Close Signals only across a direct parent-child boundary through async DBOS messages, outside DBOS steps.
- Trajectory Artifact metadata - should preserve one shared Root Run Directory while using each descendant's full Workflow Tree ID for deterministic artifact paths.

**Acceptance criteria:**
- [ ] Existing first-level `status`, `wait`, `continue`, and `close` behavior is migrated to the `DBOS.workflow_id` plus `parent_workflow_id == DBOS.workflow_id` authority model before recursive behavior is added.
- [ ] Existing workflow-layer MAS dispatch no longer relies on manually threaded template variables, `root_workflow_id`, DBOS API object parameters, or Workflow Tree ID prefix scans to establish current coordination authority.
- [ ] Existing naked external/operator `status`, `wait`, `continue`, and `close` paths are removed from the maintained path or return explicit unsupported results until the Interactive Root Agent Workflow terminal model exists.
- [ ] A Child Agent Workflow can issue `mini-mas spawn "task"` as a Standalone MAS Command and start a grandchild Agent Workflow.
- [ ] A Child Agent Workflow can issue `mini-mas spawn "task A" "task B"` as a Standalone MAS Command and start one grandchild Agent Workflow per task.
- [ ] Grandchild Workflow Tree IDs append another deterministic `-cNNN` segment to their parent ID, for example `mas-<16hex>-c001-c001`.
- [ ] Sibling grandchildren under the same Child Agent Workflow receive stable IDs such as `-c001` and `-c002`.
- [ ] Grandchildren under different Child Agent Workflows do not collide with each other or with root-level Child Agent Workflow IDs.
- [ ] Descendant Agent Workflows share the Root Agent Workflow's Run Directory.
- [ ] Descendant Trajectory Artifacts use deterministic paths under the Root Agent Workflow's Run Directory and include the full descendant Workflow Tree ID.
- [ ] `mini-mas status` from a Parent Agent Workflow reports that parent's direct Child Agent Workflows only, excluding the parent itself, grandchildren, siblings, ancestors, and workflows outside the tree.
- [ ] `mini-mas status <workflow-id>` from a Parent Agent Workflow succeeds only when the target is that parent's direct Child Agent Workflow.
- [ ] `mini-mas wait --any`, `mini-mas wait --all`, and bounded wait from a Parent Agent Workflow wait only for that parent's direct Child Agent Workflows.
- [ ] `mini-mas wait <workflow-id>` from a Parent Agent Workflow succeeds only when the target is that parent's direct Child Agent Workflow.
- [ ] Waited Spawn and `mini-mas wait` for recursive direct children synchronize through First Observable Events keyed by child workflow identifiers, not through `WorkflowHandle.get_result()` or final DBOS workflow completion.
- [ ] `mini-mas continue <workflow-id> "message"` succeeds only when the target is a waiting direct Child Agent Workflow.
- [ ] `mini-mas close <workflow-id>` succeeds only when the target is a waiting direct Child Agent Workflow.
- [ ] Root Agent Workflow attempts to status, wait for, continue, or close a grandchild directly return clear model-visible errors and do not send DBOS messages.
- [ ] Child Agent Workflow attempts to status, wait for, continue, or close siblings, ancestors, root, unknown workflows, or workflows outside the tree return clear model-visible errors and do not send DBOS messages.
- [ ] Recursive direct-child coordination uses the same async Agent Workflow layer and awaited DBOS workflow-control APIs as first-level child coordination.
- [ ] Workflow-layer `status`, `wait`, `continue`, and `close` derive current authority from `DBOS.workflow_id` and do not use caller-supplied current workflow IDs, `root_workflow_id`, DBOS API object parameters, or Workflow Tree ID prefix scans for authorization.
- [ ] External CLI `status`, `wait`, `continue`, and `close` are either removed from the maintained path or return an explicit unsupported message until the Interactive Root Agent Workflow terminal model exists.
- [ ] Tests cover root-child-grandchild spawning, repeated-task grandchild spawning, sibling ID generation, descendant artifact paths, direct-child status/wait behavior, and invalid transitive-control attempts.

**Out of scope:**
- Changing the Standalone MAS Command syntax or adding a separate model tool schema.
- Changing ordinary `mini` behavior or initializing DBOS from the non-MAS command path.
- Adding subtree-wide, tree-wide, or operator-wide Authority Grants.
- Implementing the Interactive Root Agent Workflow terminal control model.
- Preserving naked external/operator `status`, `wait`, `continue`, or `close` query/control APIs.
- Adding dedicated history, logs, grep, diff, or inspector commands.
- Solving Shared Workspace isolation, parent-level patch reconciliation, or merge workflow.
- Adding cancel, kill, retry, fork, or queue mutation commands.
- Claiming exactly-once semantics for arbitrary model or bash side effects.
