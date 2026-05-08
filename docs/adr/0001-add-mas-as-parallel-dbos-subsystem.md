# Add MAS as a Parallel DBOS Subsystem

mini-swe-agent MAS will be introduced as a parallel DBOS-backed subsystem instead of converting `DefaultAgent` or `InteractiveAgent` in place. This preserves the existing minimal agent core and CLI behavior while allowing MAS-specific workflow, signal, queue, and command-interception semantics to evolve under a dedicated boundary.

**Considered Options**

- Convert the existing agent classes directly into DBOS workflows.
- Add a separate MAS subsystem that reuses configuration, model, and environment concepts without modifying the core agent loop.

**Consequences**

MAS may initially duplicate some control-loop logic, but that duplication keeps DBOS workflow constraints and Remote Interactive Agent behavior out of the existing `mini` path.
