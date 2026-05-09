# Consolidate MAS command result formatting

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Create a result formatting **Module** for model-visible MAS command results. `status`, `spawn`, `wait`, `continue`, and `close` should return consistent `output`, `returncode`, `exception_info`, and `extra` shapes without each command branch manually constructing strings and dictionaries in place.

The formatting **Module** should preserve existing output compatibility while making the output shape a single testable **Interface**.

## Acceptance criteria

- [ ] `status` output still includes direct child workflow ID, lifecycle state, latest submission or error when present, run directory, and trajectory artifact path.
- [ ] `spawn` output still includes started child metadata and waited-spawn summaries.
- [ ] `wait` output still includes wait mode, ready children, still-running child workflow IDs, run directory, and trajectory artifact paths.
- [ ] `continue` and `close` outputs still include target workflow metadata and signal result details.
- [ ] Error results still include stable return code, exception info, and `mas_command_error` extras.
- [ ] Existing CLI and workflow command output tests pass.

## Blocked by

- .scratch/dbos-mas/issues/17-extract-mas-command-handling.md
- .scratch/dbos-mas/issues/20-move-child-spawn-and-wait-coordination.md
