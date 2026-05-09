# Use Direct Child Authority for MAS Coordination

The MAS MVP uses a **Direct Child Authority Policy**: a **Parent Agent Workflow** can observe, wait for, continue, and close only its direct **Child Agent Workflows** by default. The **Root Agent Workflow** has no special tree-wide **Coordination Authority** under this policy, so a grandchild workflow is visible or controllable only to its direct parent unless a future **Coordination Authority Model** introduces explicit broader **Authority Grants**.

Workflow-layer MAS Commands derive their current authority identity from DBOS-managed workflow context, specifically `DBOS.workflow_id`. They do not accept `root_workflow_id`, a caller-supplied current workflow ID, a DBOS API object, or an external operator identity as authority inputs. Direct-child scope is resolved from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`; Workflow Tree ID prefixes and Root Agent Workflow IDs are naming and artifact-path data, not authorization sources.

**Considered Options**

- Treat the Root Agent Workflow as a tree-wide coordinator with implicit authority over every descendant.
- Allow every Parent Agent Workflow to coordinate its full descendant subtree.
- Preserve naked external/operator status, wait, continue, and close APIs that inspect or control workflows outside an Agent Workflow.
- Use direct-child coordination for the MVP and defer broader subtree-wide or tree-wide authority to a later **Coordination Authority Model**.

**Consequences**

The current behavior resembles subinfeudation: the child agent of my child agent is not my child agent. `mini-mas status`, `mini-mas wait`, `mini-mas continue`, and `mini-mas close` therefore resolve scope from the current **Agent Workflow**'s direct children rather than the full **Agent Workflow Tree**. `mini-mas status <workflow-id>` and `mini-mas wait <workflow-id>` keep their explicit target form, but the explicit workflow ID is only a target identifier; it is not a scope override and must be authorized as a direct child of `DBOS.workflow_id`.

An **Agent Workflow** may publish `waiting_for_child` as its latest lightweight lifecycle state while it is executing `mini-mas wait` or the wait phase of `mini-mas spawn --wait`. This state is only a local coordination-state signal for the waiting workflow. It is not a First Observable Event, does not make the workflow parent-actionable, and does not grant a parent permission to `continue` or `close` it. Parent-direction commands remain authorized only for direct children whose latest status is `waiting_for_parent`.

This keeps recursive delegation local and leaves future multi-level inspection or control as an explicit authority design instead of an accidental Root Agent Workflow privilege. Naked external/operator `status`, `wait`, `continue`, and `close` APIs are not maintained as coordination authority paths while the Interactive Root Agent Workflow terminal model is deferred.
