# Constrain ordinary `mini-mas` to the Interactive Agent queue

Status: needs-triage

## What to build

Make ordinary `mini-mas` runtime activation consume only Interactive Agent work. The default External MAS CLI path should launch DBOS with an explicit queue-listening policy for `mini_mas_interactive_workflows`, start Interactive Root Agents through that queue instead of direct workflow startup, and avoid consuming autonomous AI Agent work.

## Acceptance criteria

- [ ] MAS queue names are centralized so `mini_mas_interactive_workflows` and `mini_mas_ai_agent_workflows` are not duplicated ad hoc across runtime code.
- [ ] Ordinary `mini-mas` runtime activation declares a queue-listening policy before DBOS launch and listens only to `mini_mas_interactive_workflows`.
- [ ] Interactive Root Agent startup uses queued startup through `mini_mas_interactive_workflows` rather than direct DBOS workflow startup.
- [ ] Existing Interactive Root Agent availability still works for plain `mini-mas`, `mini-mas resume <root-agent-id>`, and one-shot command entry paths.
- [ ] Tests prove ordinary `mini-mas` does not listen to or consume `mini_mas_ai_agent_workflows`.
- [ ] Tests avoid depending on private DBOS implementation details such as internal thread names.

## Blocked by

None - can start immediately
