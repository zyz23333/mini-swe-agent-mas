# DBOS Workflow Agent Protocol

## Overview

This document defines the durable workflow protocol between the DBOS workflow and
the `mini-dbos` CLI.

The protocol has four DBOS communication channels:

- workflow input for frozen run configuration
- status event for the current state snapshot
- timeline stream for ordered run events
- workflow receive/send for pending request responses

The status event is optimized for `--check`, `--approve`, and `--deny`.
The timeline stream is optimized for `--watch`.

## Agent Status

The first version uses these agent-level statuses:

```text
starting
running
pending_approval
pending_exit
completed
failed
cancelled
```

### `starting`

The workflow has started and is initializing state, templates, and the first
messages.

### `running`

The workflow is actively progressing. It may be querying the model or executing
local actions. It is not waiting for user input.

### `pending_approval`

The workflow is waiting for the user to approve or deny model-proposed commands.

### `pending_exit`

The agent has attempted to submit or finish. The workflow is waiting for the user
to approve exit or deny exit with additional feedback.

### `completed`

The workflow finished successfully.

### `failed`

The workflow failed because of an exception or approval timeout.

### `cancelled`

The workflow was cancelled through the control plane.

## Status Event

The workflow writes a current state snapshot to the configured status event key.
The default key is:

```text
agent_status
```

The event shape is conceptually:

```json
{
  "workflow_id": "01J...",
  "status": "pending_approval",
  "dbos_status": "PENDING",
  "step": 3,
  "cost": 0.42,
  "n_calls": 3,
  "task": "fix this bug",
  "pending_request": {
    "request_id": "step-3-actions",
    "kind": "approve_actions",
    "step": 3,
    "commands": ["pytest tests/test_x.py"],
    "question": "Execute 1 action(s)?"
  },
  "last_message": "short display text",
  "exit_status": null,
  "submission": null,
  "error": null
}
```

The exact serialized model can evolve, but the first version should keep stable
fields for:

- `workflow_id`
- `status`
- `step`
- `cost`
- `n_calls`
- `pending_request`
- `exit_status`
- `submission`
- `error`

Verbose check output may include implementation details, such as:

- timeline stream key
- status event key
- internal trajectory path
- frozen config summary

## Pending Request

The first version supports two pending request kinds:

```text
approve_actions
approve_exit
```

No other pending request kinds are supported in the first version.

### `approve_actions`

An action approval request asks whether the workflow may execute proposed shell
commands.

Example:

```json
{
  "request_id": "step-3-actions",
  "kind": "approve_actions",
  "step": 3,
  "commands": [
    "pytest tests/test_x.py"
  ],
  "question": "Execute 1 action(s)?"
}
```

If approved, the workflow executes the actions.

If denied, the workflow does not execute the actions. It appends user feedback to
the message history and continues the agent loop.

### `approve_exit`

An exit approval request asks whether the workflow may accept the agent's
submission and finish.

Example:

```json
{
  "request_id": "step-7-exit",
  "kind": "approve_exit",
  "step": 7,
  "commands": [],
  "question": "Agent wants to finish. Approve exit?",
  "submission": "..."
}
```

If approved, the workflow appends the submitted exit message and completes.

If denied, the workflow does not finish. It appends user feedback to the message
history and continues the agent loop.

## Approval Response

The CLI sends responses to the workflow using DBOS send.

Approval response:

```json
{
  "kind": "approve",
  "request_id": "step-3-actions"
}
```

Denial response:

```json
{
  "kind": "deny",
  "request_id": "step-3-actions",
  "reason": "Don't run git commit"
}
```

If a denial reason is omitted at the CLI level, it is normalized before sending:

```text
Denied by user
```

The workflow should always receive a non-empty denial reason.

## Request ID Validation

Every pending request has a request id. Every approval or denial response must
include the request id it is responding to.

The CLI normally hides this from the user:

```bash
mini-dbos --approve <workflow_id>
```

The CLI reads the current status event, extracts the current pending request id,
and sends it in the response.

The workflow must still validate the request id because multiple watchers or
control commands can race.

If the workflow receives a response with a stale or mismatched request id:

- ignore the response
- keep waiting for the current request
- write a timeline event noting that the stale response was ignored

The workflow must not treat a stale approval as approval for the current request.
The workflow must not treat a stale denial as normal user feedback.

Example stale-response timeline event:

```json
{
  "type": "stale_response_ignored",
  "expected_request_id": "step-4-actions",
  "received_request_id": "step-3-actions"
}
```

## Approval Timeout

Approval waits use an explicit timeout. The default timeout is seven days:

```text
604800 seconds
```

This is configured under the DBOS configuration section:

```yaml
dbos:
  approval_timeout_seconds: 604800
```

DBOS `recv` defaults are not used implicitly because the SDK default timeout is
too short for human approval workflows.

If no valid response is received before the timeout:

- the workflow raises an approval timeout error
- DBOS workflow state becomes an error state
- agent status becomes `failed`
- `exit_status` becomes `ApprovalTimeout`
- the timeline records an `approval_timeout` event

Timeouts are not treated as approval.
Timeouts are not treated as denial feedback.
Timeouts do not let the agent continue running.

Example timeout event:

```json
{
  "type": "approval_timeout",
  "request_id": "step-3-actions",
  "kind": "approve_actions"
}
```

## Timeline Stream

The workflow writes ordered timeline events to the configured stream key. The
default key is:

```text
timeline
```

The first version writes full assistant messages and full action outputs to the
stream. This makes the watcher self-contained and simple.

Example event types:

```text
workflow_started
status_changed
assistant_message
actions_proposed
approval_requested
approval_received
approval_denied
stale_response_ignored
action_started
action_output
observation_message
exit_requested
approval_timeout
workflow_completed
workflow_failed
workflow_cancelled
```

The exact event schema can evolve, but each event should include enough metadata
to render a useful watch view:

- event type
- workflow id
- agent step
- relevant request id
- relevant action index
- message or output payload
- timestamp if available

## Stream and Status Responsibilities

Use the status event for current state:

- current agent status
- current step and cost
- pending request details
- final exit status
- final submission
- error summary

Use the timeline stream for history:

- full assistant messages
- proposed commands
- approvals and denials
- full command outputs
- observations
- final events

Do not derive `--approve` or `--deny` state from the stream. Those commands must
read the status event so they respond to the current pending request.

## Submitted Handling

The existing mini-SWE-agent environment layer uses the `Submitted` exception as
normal control flow when an action indicates task completion.

The DBOS version preserves this semantic but must not allow `Submitted` to turn a
DBOS step into an error.

Action execution steps should convert `Submitted` into a normal step return:

```json
{
  "kind": "submitted",
  "messages": [
    {
      "role": "exit",
      "content": "...",
      "extra": {
        "exit_status": "Submitted",
        "submission": "..."
      }
    }
  ]
}
```

The workflow then creates an `approve_exit` pending request if exit confirmation
is enabled.

If exit is approved, the workflow appends the stored exit message and completes.

If exit is denied, the workflow does not append the exit message. It appends user
feedback and continues.

## Limits and Failures

Step limits and cost limits keep their existing semantic. If a limit is exceeded,
the workflow should finish with an appropriate exit status rather than waiting
for approval.

Unexpected exceptions should:

- update the status event to `failed`
- write a failure event to the timeline stream when possible
- preserve error details in the final status event
- allow DBOS to record the workflow as errored

Approval timeout is a specific failure case with `exit_status` set to
`ApprovalTimeout`.

## Cancellation

Cancellation is a control-plane operation.

The first version directly calls DBOS workflow cancellation. It does not send a
conversation message to the workflow and does not attempt graceful agent-level
cancellation.

`--check` should display cancelled workflows as:

```text
Agent status: cancelled
```

even if the last status event was written before cancellation.

## Configuration Snapshot

The workflow input includes a frozen non-secret configuration snapshot.

The snapshot is used for:

- prompts
- model class and model name
- model kwargs
- environment configuration
- agent limits
- mode
- DBOS agent settings

Secrets are not frozen into the workflow input. Provider code continues to read
API keys from the environment at runtime.

## Local Environment Scope

Only the local environment is supported in the first version.

Action execution steps rebuild the local environment from the frozen environment
configuration. Local filesystem side effects persist naturally through the shared
working tree.

Container and remote environments are deferred because they require durable
environment identity, reconnection, cleanup, and recovery semantics.
