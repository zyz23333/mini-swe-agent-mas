# Add `mini-mas run` as an isolated External MAS CLI

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Add a separate `mini-mas` External MAS CLI with a minimal `run` command that initializes DBOS only on the MAS path and starts a Root Agent Workflow. The existing `mini` command must remain operationally unchanged and must not configure or launch DBOS during ordinary single-agent use.

This slice should prove the new MAS subsystem boundary end to end: package dependency, script entrypoint, DBOS launch path, Root Agent Workflow startup, and regression coverage for the existing `mini` command.

## Acceptance criteria

- [ ] DBOS is installed as a default project dependency for this branch.
- [ ] `pyproject.toml` exposes a `mini-mas` script without changing the existing `mini`, `mini-swe-agent`, `mini-extra`, or `mini-e` scripts.
- [ ] `mini-mas run` starts a minimal Root Agent Workflow through DBOS and returns a clear workflow identifier or result.
- [ ] Existing `mini` CLI tests still pass and include coverage that ordinary `mini` invocation does not initialize or launch DBOS.
- [ ] The MAS implementation lives under a separate subsystem boundary and does not convert `DefaultAgent` or `InteractiveAgent` into DBOS workflows.

## Blocked by

None - can start immediately.

