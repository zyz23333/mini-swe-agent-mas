# Scope MAS Runtime State to the Workspace

The MAS Runtime State Store is workspace-scoped by default rather than user-global or mandatory external infrastructure. Local `mini-mas` usage stores DBOS runtime state in `.mini-mas/runtime/mini_mas_dbos.sqlite`, resolved relative to the current working directory, so Root discovery and durable MAS workflow state stay tied to the current workspace without exposing DBOS database configuration as ordinary user-facing MAS configuration.

**Considered Options**

- Use a workspace-local SQLite store at `.mini-mas/runtime/mini_mas_dbos.sqlite` by default.
- Use one global SQLite store for the current user.
- Leave the DBOS-derived SQLite file in the workspace root.
- Require an explicit external database such as Postgres for all MAS usage.

**Consequences**

Root discovery is local to the active workspace by default, so separate repositories do not see each other's Interactive Root Agents. The workspace root is not polluted by a DBOS-derived SQLite filename; MAS artifacts and runtime state are grouped under `.mini-mas/`. Ordinary `mini-mas` help, errors, and usage documentation should not expose DBOS system database URLs as a user configuration surface.

Runtime creation of `.mini-mas/` does not modify user project version-control ignore files. This repository may ignore `.mini-mas/` for mini-swe-agent development, but installed `mini-mas` should not impose Git-specific policy on user projects.
