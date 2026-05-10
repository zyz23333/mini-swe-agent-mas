# Migrate remaining MAS governance naming

Status: needs-triage
Category: refactor
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## What to build

Complete the remaining behavior-preserving naming migration after the MAS glossary and ADRs moved from workflow/coordination language to **MAS Governance**, **Agent Interaction**, **Agent**, **Agent ID**, **Authority Model**, and **Delegated Non-Transitive Authority**.

This slice should update stale terminology in code comments, docstrings, CLI/help text, model-visible messages, result payload keys, tests, and local planning documents so readers see one coherent vocabulary. This project has no external users yet, so the slice may make breaking naming changes to user-visible MAS fields, command output keys, internal function names, test names, and error codes when doing so makes the MAS vocabulary coherent.

Keep DBOS implementation terms only at the DBOS boundary, where they name real DBOS APIs or metadata such as `DBOS.workflow_id` and `parent_workflow_id`. MAS-facing code and output should prefer **Agent ID** language, even if the underlying Agent ID is still stored in DBOS as a workflow ID.

The migration should be behavior-preserving but not API-name-preserving: improve naming consistency without changing MAS behavior, authority semantics, artifact path structure, command parsing rules, or DBOS workflow metadata usage. Any intentionally changed output shape or error code must be covered by updated tests.

Known areas to review:

- MAS source docstrings and help text in `src/minisweagent/mas/artifacts.py`, `status_events.py`, `cli.py`, `mas_agent.py`, `runtime.py`, `signals.py`, `commands.py`, and `agent_interactions.py`.
- User-visible output strings, result payload keys, exception info strings, command argument help, and tests that still say `Agent Workflow`, `Child Agent Workflow`, `Root Agent Workflow`, `Workflow Tree ID`, `workflow_id`, or `coordination` where the new domain term should be used.
- MAS-facing names such as `validate_workflow_id`, `make_root_workflow_id`, `child_workflow_ids`, `still_running_child_workflow_ids`, `continued_workflow_id`, `closed_workflow_id`, and related output keys. Rename these to **Agent ID** terminology unless the name is directly bound to a DBOS API.
- `.scratch/dbos-mas/PRD.md` and `.scratch/dbos-mas/mas-deep-module-refactor-map.md`, which still describe the MAS design with pre-governance terminology.
- Existing completed issue files under `.scratch/dbos-mas/issues/` only when they are used as current planning/reference material; avoid rewriting historical execution comments unless they actively mislead future agents.
- External unsupported-runtime names such as `external_coordination_unsupported`; these may be renamed because compatibility is not required, but the replacement should use the new vocabulary, for example external **Agent Interaction** wording, and tests must assert the new result shape.

## Acceptance criteria

- [ ] Source docstrings and CLI/help text use **Agent**, **Agent ID**, **Agent Tree**, **MAS Governance**, **Agent Interaction**, **Authority Model**, and **Delegated Non-Transitive Authority** where those are domain concepts.
- [ ] DBOS terms remain only where they describe actual DBOS APIs, metadata, or entrypoint implementation details, such as `DBOS.workflow_id`, DBOS `parent_workflow_id` metadata, and DBOS workflow decorators.
- [ ] MAS-facing names and output keys prefer **Agent ID** terminology over `workflow_id`, including command outputs, result `extra` payloads, CLI help, tests, and local docs.
- [ ] Model-visible and CLI-visible wording no longer says `Agent Workflow`, `Workflow Tree ID`, `MAS Coordination`, or `workflow_id` unless the text is explicitly explaining the DBOS implementation boundary.
- [ ] Tests are updated to assert the new wording and result keys for intentionally changed user-visible messages and payloads.
- [ ] Compatibility-sensitive identifiers such as `external_coordination_unsupported` are renamed where appropriate, with tests updated to assert the new error code and result shape.
- [ ] `.scratch/dbos-mas/PRD.md` and `.scratch/dbos-mas/mas-deep-module-refactor-map.md` are synchronized with the current `CONTEXT.md` glossary and ADR terminology.
- [ ] No MAS behavior changes: Direct Child Authority Policy still implements **Delegated Non-Transitive Authority**, Agent Interactions still require the same authority checks, and `uv run pytest tests/mas` passes.

## Blocked by

None - can start immediately
