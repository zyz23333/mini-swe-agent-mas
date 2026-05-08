# Make DBOS a Default Dependency for the MAS Branch

This MAS branch makes DBOS a default project dependency because durable workflows, queues, and workflow communication are core to the branch goal. DBOS runtime activation remains scoped to the `mini-mas` entrypoint, so the existing `mini` command does not configure or launch DBOS during normal single-agent use.

**Considered Options**

- Keep DBOS behind an optional `mas` extra to preserve the upstream minimal dependency surface.
- Make DBOS a default dependency for this branch while keeping runtime initialization out of the existing `mini` path.

**Consequences**

Installing this branch always installs DBOS, but ordinary `mini` invocations remain operationally non-DBOS unless they explicitly enter the MAS command path.
