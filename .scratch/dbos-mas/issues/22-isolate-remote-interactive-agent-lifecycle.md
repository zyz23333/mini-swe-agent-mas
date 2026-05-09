# Isolate Remote Interactive Agent continuation lifecycle

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Move **Remote Interactive Agent** lifecycle behavior into a dedicated **Module** or clearly isolated **Interface**. A **Child Agent Workflow** that reaches first submission should publish `waiting_for_parent`, publish its **First Observable Event**, save its trajectory, wait for a parent-direction message, and then either inject a **Continuation Signal** as a normal user message or close neutrally on a **Close Signal**.

The main **Agent Workflow** loop should not inline this entire continuation lifecycle.

## Acceptance criteria

- [ ] A **Child Agent Workflow** enters `waiting_for_parent` after producing a submission.
- [ ] The first parent-actionable state publishes a **First Observable Event** exactly as before.
- [ ] A **Continuation Signal** becomes a normal user message in the existing trajectory.
- [ ] After continuation, the child resumes from the same message history and can produce a second submission.
- [ ] A **Close Signal** ends the **Remote Interactive Agent** neutrally without implying acceptance or rejection.
- [ ] Failed and limits-exceeded child terminal states still publish parent-observable events as currently specified.
- [ ] Existing continuation and close lifecycle tests pass.

## Blocked by

- .scratch/dbos-mas/issues/19-introduce-dbos-coordination-adapter.md
- .scratch/dbos-mas/issues/21-restore-mini-shaped-agent-workflow-loop.md
