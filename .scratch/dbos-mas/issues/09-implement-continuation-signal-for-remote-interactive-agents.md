# Implement Continuation Signal for Remote Interactive Agents

Status: needs-triage
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Implement `mini-mas continue <workflow-id> "message"` so a Parent Agent Workflow can ask a waiting Child Agent Workflow to keep working from its existing trajectory. The Continuation Signal should become a normal user message in the child trajectory, with metadata identifying it as a MAS continuation.

This slice should prove that a Remote Interactive Agent can produce a submission, wait for parent direction, continue with the same linear message history, and produce a later observable result.

## Acceptance criteria

- [ ] `mini-mas continue <workflow-id> "message"` sends a Continuation Signal to a waiting Child Agent Workflow.
- [ ] The Continuation Signal is injected into the child trajectory as a normal user message.
- [ ] Continuation metadata identifies the message as MAS continuation without changing model adapter action parsing.
- [ ] The child resumes from its existing message history rather than starting a new workflow.
- [ ] The resumed child can produce a second submission or terminal status visible through status/wait.
- [ ] Tests cover first submission, waiting state, continuation, trajectory message injection, second submission, and observation formatting.

## Blocked by

- .scratch/dbos-mas/issues/07-make-child-workflows-wait-after-first-submission.md

