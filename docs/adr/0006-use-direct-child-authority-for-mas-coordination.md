# Use Direct Child Authority for MAS Governance

The MAS MVP uses a **Direct Child Authority Policy** implementing **Delegated Non-Transitive Authority**: a **Parent Agent** can observe, wait for, continue, and close only its direct **Child Agents** by default. The **Root Agent** has no special tree-wide **Authority** under this policy, so a grandchild Agent is visible or controllable only to its direct parent unless a future **Authority Model** introduces explicit broader **Authority Grants**.

Workflow-layer MAS Commands derive their current authority identity from DBOS-managed workflow context, specifically `DBOS.workflow_id`. They do not accept `root_workflow_id`, a caller-supplied current Agent ID, a DBOS API object, or an external operator identity as authority inputs. Direct-child scope is resolved from DBOS workflow metadata where `parent_workflow_id == DBOS.workflow_id`; Agent ID prefixes and Root Agent IDs are naming and artifact-path data, not authorization sources.

**Considered Options**

- Treat the Root Agent as having implicit authority over every descendant.
- Allow every Parent Agent to have authority over its full descendant subtree.
- Preserve naked external/operator status, wait, continue, and close APIs that inspect or control Agents outside a MAS-governed Agent context.
- Use **Delegated Non-Transitive Authority** for the MVP and defer broader subtree-wide or tree-wide authority to a later **Authority Model**.

**Consequences**

The current behavior resembles subinfeudation: the child agent of my child agent is not my child agent. `mini-mas status`, `mini-mas wait`, `mini-mas continue`, and `mini-mas close` therefore resolve scope from the current **Agent**'s direct children rather than the full **Agent Tree**. `mini-mas status <agent-id>` and `mini-mas wait <agent-id>` keep their explicit target form, but the explicit Agent ID is only a target identifier; it is not a scope override and must be authorized as a direct child of `DBOS.workflow_id`.

An **Agent** may publish `waiting_for_child` as its latest lightweight lifecycle state while it is executing `mini-mas wait` or the wait phase of `mini-mas spawn --wait`. This state is only a local waiting-state signal for that Agent. It is not a First Observable Event, does not make the Agent parent-actionable, and does not grant a parent permission to `continue` or `close` it. Parent-direction commands remain authorized only for direct children whose latest status is `waiting_for_parent`.

This keeps recursive delegation local and leaves future multi-level inspection or control as an explicit Authority Model design instead of an accidental Root Agent privilege. Naked external/operator `status`, `wait`, `continue`, and `close` APIs are not maintained as MAS governance authority paths while the Interactive Root Agent terminal model is deferred.
