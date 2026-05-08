# Parse and reject non-standalone MAS Commands

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Teach the Agent Workflow execution path to distinguish Standalone MAS Commands from ordinary bash commands while preserving mini-swe-agent's existing bash-shaped model action contract. A command beginning with `mini-mas` should be intercepted only when the full action command is a valid Standalone MAS Command. Shell compositions that contain `mini-mas` must produce a clear corrective error instead of being partially intercepted or executed as ambiguous bash.

This slice should prove command parsing and observation formatting end to end with deterministic model outputs, without implementing the full coordination command set yet.

## Acceptance criteria

- [ ] Standalone MAS Commands are detected only when `mini-mas ...` occupies the whole action command.
- [ ] Ordinary bash commands that do not invoke `mini-mas` continue through ordinary bash execution.
- [ ] Shell operators, environment assignments, loops, pipes, redirections, and embedded `mini-mas` fragments are rejected for MAS interception with a clear error.
- [ ] Model adapters still produce bash-shaped actions with a `command` string; no separate `mini-mas` model tool schema is introduced.
- [ ] Observation formatting remains model-specific and uses existing text-based, toolcall, and Responses API patterns.
- [ ] Tests cover accepted standalone commands and rejected shell-composition cases.

## Blocked by

- .scratch/dbos-mas/issues/01-add-mini-mas-run-isolated-cli.md

