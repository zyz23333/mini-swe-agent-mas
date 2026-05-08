# DBOS Workflow Agent CLI Specification

## Entry Point

The DBOS-backed agent is exposed through a new command:

```bash
mini-dbos
```

The existing `mini` command remains unchanged and continues to run the current
local interactive agent.

## Command Categories

`mini-dbos` supports four categories of operations:

- start a new workflow
- watch an existing workflow
- inspect workflow status
- respond to or control an existing workflow

## Start

Start a new detached workflow:

```bash
mini-dbos -t "fix this bug"
```

Default behavior:

- create a new DBOS workflow
- print the workflow id
- print suggested next commands
- exit without watching

Example output:

```text
Started workflow: 01J...

Next:
  mini-dbos --watch 01J...
  mini-dbos --check 01J...
```

Start a new workflow and immediately watch it:

```bash
mini-dbos -t "fix this bug" --watch
```

This creates the workflow, then attaches the watcher in the same terminal.

## Workflow ID

Users may provide an explicit workflow id when starting:

```bash
mini-dbos -t "fix this bug" --workflow-id my-run-001
```

The explicit workflow id is only for creating a new workflow with a stable id.
It does not mean resume.

If the workflow id already exists, the command fails fast:

```text
Workflow id already exists: my-run-001
```

The command must not attach to the existing workflow, overwrite it, or generate a
new name automatically.

## Watch

Watch an existing workflow:

```bash
mini-dbos --watch <workflow_id>
```

Watch behavior:

- replay timeline stream entries from the beginning by default
- continue following new timeline entries
- observe the current status event
- if a pending request appears, prompt the terminal user
- send approval or denial back to the workflow
- exit when the workflow reaches a terminal state, unless the user detaches first

Watch without replaying history:

```bash
mini-dbos --watch <workflow_id> --tail
```

`--tail` behavior:

- show the current status snapshot
- do not replay the full historical timeline
- follow new timeline entries after attaching

The first version does not expose raw stream offsets as a CLI concept.

## Watch Detach

Stopping the watcher does not cancel the workflow.

The user can detach using:

- `q`
- `/q`
- `Ctrl+C`

Detach behavior:

- the local watcher exits
- the DBOS workflow continues running or waiting
- the user can later attach again with `mini-dbos --watch <workflow_id>`

Cancellation is a separate explicit operation.

## Pending Request Prompt

When `--watch` sees a pending request, it uses the existing mini confirmation
style subset:

```text
Enter -> approve
any non-empty text -> deny with that text as the reason
/h -> show help
q or /q -> detach watcher
```

The first version does not support `human` mode in the watcher.

The first version also does not require dynamic `/y` or `/c` mode switching
inside `--watch`. If added later, those commands must update durable workflow
state instead of local watcher state only.

## Check

Check the current status once:

```bash
mini-dbos --check <workflow_id>
```

Default output is human-readable and focused on the next action:

```text
Workflow: 01J...
DBOS status: PENDING
Agent status: pending_approval
Step: 3
Cost: $0.42

Pending request: approve_actions step-3-actions
Commands:
  pytest tests/test_x.py

Next:
  mini-dbos --approve 01J...
  mini-dbos --deny 01J... "reason"
  mini-dbos --watch 01J...
```

Machine-readable output:

```bash
mini-dbos --check <workflow_id> --json
```

Verbose human-readable output:

```bash
mini-dbos --check <workflow_id> --verbose
```

Verbose JSON output:

```bash
mini-dbos --check <workflow_id> --json --verbose
```

Default `--check` and default `--check --json` output expose stable product
fields only. Verbose output may include implementation details such as stream
keys, status event keys, and internal trajectory paths.

## Approve

Approve the current pending request:

```bash
mini-dbos --approve <workflow_id>
```

The command reads the current status event, extracts the pending request id, and
sends an approval response containing that request id.

The user does not need to pass the request id manually in normal use.

If there is no pending request, the CLI fails without sending a response.

If the workflow is already terminal, the CLI fails without sending a response.

## Deny

Deny the current pending request:

```bash
mini-dbos --deny <workflow_id>
```

With an explicit reason:

```bash
mini-dbos --deny <workflow_id> "Don't run git commit"
```

If the reason is omitted, the default reason is:

```text
Denied by user
```

The command reads the current status event, extracts the pending request id, and
sends a denial response containing that request id and reason.

For an action approval request, denial means:

- do not execute the proposed commands
- append the denial reason to the agent conversation as user feedback
- continue the agent loop

For an exit approval request, denial means:

- do not finish the workflow
- append the denial reason as additional user feedback
- continue the agent loop

## Cancel

Cancel a workflow:

```bash
mini-dbos --cancel <workflow_id>
```

Cancellation is explicit. Detaching a watcher does not cancel.

In an interactive terminal, cancellation prompts for confirmation:

```text
Cancel workflow 01J...? [y/N]
```

Non-interactive cancellation requires:

```bash
mini-dbos --cancel <workflow_id> --yes
```

Without `--yes`, non-interactive cancellation fails.

The first version directly calls DBOS workflow cancellation. It does not send a
graceful cancellation message into the agent conversation.

`--check` should map a DBOS cancelled workflow to the agent-level `cancelled`
status when displaying the state.

## Mode Flags

The first version supports confirm and yolo modes.

Confirm mode is the default:

```bash
mini-dbos -t "fix this bug"
```

Yolo mode:

```bash
mini-dbos -t "fix this bug" -y
```

In yolo mode, action approval requests are skipped and proposed commands are
executed directly. Human mode is not supported in the first DBOS version.

## Unsupported First-Version CLI Surface

The first version does not support:

- `-o` or `--output` for DBOS trajectory path selection
- `--resume`
- `human` mode
- arbitrary message injection while running
- web inbox commands
- raw stream offset controls

## Naming Decisions

The response command is called `--deny`, not `--comment`.

Reason: the operation rejects the current pending request and optionally gives
the agent a reason. It is not a general comment, post-run feedback, or log note.

If post-run feedback is added later, it should use a different command such as
`--feedback`.
