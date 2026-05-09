# Align MAS module names with the refactor map

Status: needs-triage
Category: enhancement
Type: AFK

## Parent

.scratch/dbos-mas/PRD.md

## Refactor map reference

This issue must follow `.scratch/dbos-mas/issues/16-record-mas-deep-module-refactor-map.md` and `.scratch/dbos-mas/mas-deep-module-refactor-map.md`. Preserve the module boundaries, DBOS step/workflow-control boundaries, and out-of-scope constraints recorded there; do not invent alternate MAS module names, authority models, DBOS behavior, or command fallbacks.

## What to build

Finish the MAS structural rename that was intentionally left incomplete after the deep module refactor slices. The canonical Agent Workflow module should be `minisweagent.mas.mas_agent`, not `minisweagent.mas.workflows`.

Move the plain `MasAgent`, module-level DBOS workflow entrypoints, module-level DBOS step wrappers, and top-level Agent Workflow orchestration into `src/minisweagent/mas/mas_agent.py`. Update production imports and tests to import the canonical `mas_agent` module directly.

Do not keep `workflows.py` as a compatibility re-export shim. If no production or test import needs `workflows.py`, remove it. If a temporary file remains for some unavoidable reason, it must not re-export `MasAgent`, workflow entrypoints, step wrappers, or other `mas_agent` symbols.

Also finish the adjacent module-name alignment from the refactor map:

- Rename the current status-event responsibilities from `status.py` to `status_events.py`.
- Extract parent-direction signal payload/topic helpers from `remote_lifecycle.py` into `signals.py`.
- Keep `remote_lifecycle.py` focused on Remote Interactive Agent lifecycle behavior.

Because the project is still early and there are no external MAS users to preserve, remove old-design compatibility code and compatibility tests instead of carrying them forward. Do not preserve old import paths, old module names, old metadata strings, old tests that prove compatibility, or placeholder shims for a previous MAS structure.

This is a behavior-preserving structure cleanup. It should not change MAS command semantics, Direct Child Authority Policy, Child Status Events, First Observable Events, Continuation Signals, Close Signals, DBOS workflow IDs, artifact paths, or external CLI behavior.

## Acceptance criteria

- [ ] `src/minisweagent/mas/mas_agent.py` is the canonical module for `MasAgent`, `root_agent_workflow`, `child_agent_workflow`, `query_model_step`, `execute_bash_step`, and trajectory persistence step wrappers.
- [ ] No production code imports `minisweagent.mas.workflows`.
- [ ] No tests import `minisweagent.mas.workflows`; tests use `minisweagent.mas.mas_agent` directly.
- [ ] `workflows.py` is not used as a compatibility re-export shim. It is either removed or contains no re-exported `mas_agent` API surface.
- [ ] No compatibility test asserts that `minisweagent.mas.workflows` can still be imported, reloaded, or used as an API surface.
- [ ] Runtime startup imports `root_agent_workflow` from `minisweagent.mas.mas_agent`, not from `minisweagent.mas.workflows`.
- [ ] MAS artifact metadata no longer records `minisweagent.mas.workflows.agent_workflow`; it uses the new canonical Agent Workflow identifier.
- [ ] `status_events.py` owns `LifecycleState`, `AgentStatusSnapshot`, `STATUS_EVENT_KEY`, `FIRST_OBSERVABLE_EVENT_KEY`, Child Status Event helpers, First Observable Event helpers, and status snapshot formatting.
- [ ] No production code imports the renamed status-event API from `minisweagent.mas.status`.
- [ ] No tests import the renamed status-event API from `minisweagent.mas.status`; tests use `minisweagent.mas.status_events` directly.
- [ ] `status.py` is not kept as a compatibility re-export module.
- [ ] `signals.py` owns `PARENT_DIRECTION_TOPIC`, Continuation Signal payload construction and recognition, Close Signal payload construction and recognition, and continuation user-message metadata shape.
- [ ] `remote_lifecycle.py` remains focused on Remote Interactive Agent lifecycle behavior and imports parent-direction signal helpers from `signals.py`.
- [ ] Tests import signal constants and helpers from `minisweagent.mas.signals`, not indirectly from `mas_agent` or `remote_lifecycle`.
- [ ] No compatibility layer preserves old MAS module names or old import paths solely for backward compatibility.
- [ ] `rg "minisweagent\\.mas\\.workflows|from minisweagent\\.mas\\.status|import minisweagent\\.mas\\.status|compatibility re-export|backward compatibility" src tests` returns no MAS structural-compatibility leftovers, except unrelated non-MAS compatibility text.
- [ ] DBOS workflows and steps remain module-level functions; `MasAgent` remains a plain Python orchestration object and is not DBOS-registered.
- [ ] `DBOSCoordinationAdapter` calls remain in the async Agent Workflow path and are not passed into or called from DBOS step wrappers.
- [ ] Standalone MAS Command classification still happens once in `commands.py`; invalid shell compositions still do not enter `execute_bash_step`.
- [ ] Existing MAS workflow, command, authority, coordination, status-event, signal, runtime, and CLI behavior tests pass without weakening assertions.

## Blocked by

- .scratch/dbos-mas/issues/17-extract-mas-command-handling.md
- .scratch/dbos-mas/issues/18-centralize-direct-child-authority-policy.md
- .scratch/dbos-mas/issues/19-introduce-dbos-coordination-adapter.md
- .scratch/dbos-mas/issues/20-move-child-spawn-and-wait-coordination.md
- .scratch/dbos-mas/issues/21-restore-mini-shaped-agent-workflow-loop.md
- .scratch/dbos-mas/issues/22-isolate-remote-interactive-agent-lifecycle.md
- .scratch/dbos-mas/issues/23-consolidate-mas-command-result-formatting.md
- .scratch/dbos-mas/issues/24-collapse-unsupported-external-coordination-runtime-paths.md

## Comments

> *This was generated by AI during triage.*
>
> ## Agent Brief
>
> **Category:** enhancement
> **Summary:** Complete the MAS module-name alignment from the deep refactor map without adding a compatibility re-export layer.
>
> **Current behavior:**
> The behavior-oriented MAS refactor slices have separated command classification, command dispatch, result formatting, authority validation, child coordination, DBOS coordination adaptation, and remote interactive lifecycle behavior. However, the canonical module names still diverge from the agreed refactor map:
>
> - `MasAgent`, DBOS workflow entrypoints, DBOS step wrappers, and Agent Workflow orchestration still live in `src/minisweagent/mas/workflows.py`.
> - Status-event concepts still live in `src/minisweagent/mas/status.py`.
> - Parent-direction signal topic and payload helpers still live in `src/minisweagent/mas/remote_lifecycle.py`.
> - `src/minisweagent/mas/runtime.py` still imports `root_agent_workflow` from `minisweagent.mas.workflows`.
> - MAS artifact metadata still records `minisweagent.mas.workflows.agent_workflow`.
> - MAS tests still import `minisweagent.mas.workflows` and `minisweagent.mas.status`, which would keep the old design alive as a tested API surface.
>
> Issue 16 and the design note identify `mas_agent.py`, `status_events.py`, and `signals.py` as the intended module names. The previous note allowed `workflows.py` to temporarily remain as a compatibility shim, but the current decision is stricter: do not create or keep a re-export shim. New and existing code should import the canonical module names directly.
>
> **Desired behavior:**
> `minisweagent.mas.mas_agent` should be the canonical Agent Workflow module. It should own the plain mini-shaped `MasAgent`, the module-level DBOS workflow entrypoints, the module-level DBOS step wrappers, and top-level Agent Workflow orchestration. Production code and tests should import this module directly.
>
> `status_events.py` should own lightweight MAS observable state: lifecycle states, status snapshots, status event keys, first observable event keys, Child Status Event helpers, First Observable Event helpers, and simple status snapshot formatting.
>
> `signals.py` should own parent-direction message concepts: the topic, Continuation Signal payloads, Close Signal payloads, recognition helpers, and continuation user-message metadata shape. `remote_lifecycle.py` should keep only the Remote Interactive Agent lifecycle policy and call into `signals.py`.
>
> **Hard constraint:**
> Do not keep `workflows.py` as a re-export compatibility shim. Avoid preserving the old import path as a supported API surface because it would undercut the structural rename and allow future agents to continue implementing against the wrong module.
>
> The same rule applies to `status.py` and signal helpers exposed from the wrong modules. Since MAS is still early and has no external compatibility contract, delete old-design compatibility implementations and tests instead of preserving them.
>
> **Key interfaces:**
> - `minisweagent.mas.mas_agent.MasAgent`
> - `minisweagent.mas.mas_agent.root_agent_workflow`
> - `minisweagent.mas.mas_agent.child_agent_workflow`
> - `minisweagent.mas.mas_agent.query_model_step`
> - `minisweagent.mas.mas_agent.execute_bash_step`
> - `minisweagent.mas.status_events`
> - `minisweagent.mas.signals`
> - `RemoteInteractiveAgentLifecycle`
> - `DBOSCoordinationAdapter`
>
> **Out of scope:**
> - Changing MAS command syntax or command semantics.
> - Changing Direct Child Authority Policy or adding broader authority models.
> - Changing DBOS workflow IDs, queue names, event keys, message topic values, artifact paths, or trajectory persistence semantics.
> - Moving model query, ordinary bash execution, or trajectory persistence out of DBOS step wrappers.
> - Passing `DBOSCoordinationAdapter` into DBOS step wrappers.
> - Adding external/operator coordination authority.
> - Adding compatibility re-export modules for old names.
> - Keeping compatibility tests for `workflows.py`, `status.py`, or other previous MAS module names.
