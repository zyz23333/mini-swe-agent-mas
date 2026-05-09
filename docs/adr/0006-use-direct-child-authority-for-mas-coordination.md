# Use Direct Child Authority for MAS Coordination

The MAS MVP uses a **Direct Child Authority Policy**: a **Parent Agent Workflow** can observe, wait for, continue, and close only its direct **Child Agent Workflows** by default. The **Root Agent Workflow** has no special tree-wide **Coordination Authority** under this policy, so a grandchild workflow is visible or controllable only to its direct parent unless a future **Coordination Authority Model** introduces explicit broader **Authority Grants**.

**Considered Options**

- Treat the Root Agent Workflow as a tree-wide coordinator with implicit authority over every descendant.
- Allow every Parent Agent Workflow to coordinate its full descendant subtree.
- Use direct-child coordination for the MVP and defer broader subtree-wide or tree-wide authority to a later **Coordination Authority Model**.

**Consequences**

The current behavior resembles subinfeudation: the child agent of my child agent is not my child agent. `mini-mas status`, `mini-mas wait`, `mini-mas continue`, and `mini-mas close` should therefore resolve their default scope from the current **Agent Workflow**'s direct children rather than the full **Agent Workflow Tree**. This keeps recursive delegation local and leaves future multi-level inspection or control as an explicit authority design instead of an accidental Root Agent Workflow privilege.
