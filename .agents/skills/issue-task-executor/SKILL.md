---
name: issue-task-executor
description: Execute local markdown issues from `.scratch/` after they are triaged as ready for an agent, including feature PRD, related ADR/SPEC/PLAN docs, related issue, and code context collection. Use when the user asks to do, execute, implement, or work on a `.scratch` issue, especially issues marked `ready-for-agent`, `AFK`, `for-agent`, or "for agent".
---

# Issue Task Executor

Execute local `.scratch` issues strictly: triage readiness gate, context collection, issue-as-plan review, test-first implementation, evidence-based verification, then an explicit commit/keep/discard choice.

## Start

Announce: "I'm using the issue-task-executor skill to execute this local issue." Read `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, and the requested issue file under `.scratch/<feature-slug>/issues/`.

## Readiness Gate

Only implement when all are true: `Status: ready-for-agent`; the issue has an `Agent Brief` or equivalent actionable acceptance criteria; blockers and dependencies do not prevent execution. `Type: AFK`, `Type: for-agent`, and similar metadata support readiness but do not replace `Status: ready-for-agent`.

If the issue is not executable, stop and switch to triage behavior. Do not edit production code. If `Status:` is missing or state labels conflict, ask the maintainer to triage.

## Context Collection

Before planning or editing, collect enough context to understand the issue's local feature, neighboring work, and implementation surface.

Read the issue's parent feature PRD at `.scratch/<feature-slug>/PRD.md` when present. Also look across the repo for related decision, design, and planning docs such as `ADR*.md`, `SPEC*.md`, `PLAN*.md`, or equivalent files when they are referenced or clearly relevant; these files may live outside `.scratch/<feature-slug>/`. Note missing or stale context docs, and stop only when the gap makes behavior ambiguous.

Inspect related issues in `.scratch/<feature-slug>/issues/`: named dependencies/blockers, same affected area, nearby issue numbers, and completed issues defining behavior to preserve. Do not implement unrelated sibling issues.

Read necessary docs and code referenced by the issue, PRD, or related issues. Use focused `rg` searches for existing routes, services, models, components, tests, commands, and terminology. Prefer project docs and local dependency source under `references/` before external lookup.

After context collection, decide which other skills are relevant before Plan Review. Base the decision on collected evidence, not the issue title alone: affected language/framework, domain docs, testing strategy, auth/security surface, dependency investigation needs, UI stack, and whether the issue explicitly requests TDD, diagnosis, triage, architecture review, or documentation work.

Load only skills that materially change execution. If a relevant skill is available, read its `SKILL.md` before planning and merge its constraints into the plan. If no extra skill is needed, note that internally and continue with this skill only. Do not load skills speculatively.

Summarize internally: feature goal, issue role, prior decisions, affected files/modules, existing tests, constraints, unknowns, and selected supporting skills. Feed this into Plan Review. Stop if context reveals blockers, contradictions, or issue-exceeding scope.

## Plan Review

Treat the issue plus collected context and selected supporting skills as the implementation plan. Extract desired behavior, acceptance criteria, out-of-scope boundaries, affected surfaces, skill-specific constraints, and a verification method for each criterion.

Review critically before implementation. Stop if the issue is ambiguous, unsafe, blocked, requires human judgment, or would exceed scope.

## TDD Loop

For behavior changes, use vertical slices: write one public-interface behavior test, confirm it fails for the expected reason, implement the minimum to pass, confirm it passes, refactor only while green, then repeat for the next behavior.

Do not write all tests first. Do not write production code before a failing test unless the task is pure docs, static configuration, or mechanical wiring where no meaningful automated test exists. Record the exception and replacement verification command.

Tests should verify observable behavior through real code paths. Mock only unavoidable external systems, time, network, or nondeterministic dependencies.

## Implementation Rules

- Keep scope limited to the issue and out-of-scope section.
- Prefer existing project patterns, helpers, and dependencies.
- Do not add third-party dependencies without approval.
- If dependency behavior matters, inspect `references/` first.
- Preserve unrelated user changes.
- Stop on blockers instead of guessing.

## Verification Gate

Before claiming completion, re-read every acceptance criterion, run fresh verification commands, read full output and exit codes, and state only what the evidence supports.

Use repo commands first: `make lint`, `make test-backend`, `make test-frontend`, and specialized backend targets when contract, database migration, or integration boundaries are touched.

If verification fails, do not call the work complete. Report the failing command, relevant output, and next debugging step.

## Issue Update

After verified completion, check off completed acceptance criteria, set `Status: done` only when all criteria are met, append an execution note under `## Comments`, and prefix issue comments with `> *This was generated by AI during execution.*`

If verification is incomplete or failing, leave status unchanged and record the blocker.

## Result Summary And Review Choice

After implementation and verification, stop and present a review summary before committing or discarding.

Include issue path, final status, changed files, acceptance criteria evidence, verification command results, issue tracker updates, residual risks, and current `git status --short`.

If verification passed and the issue is complete, present exactly:

```text
Work is ready for review. What would you like to do?

1. Commit this work
2. Keep changes uncommitted for review
3. Discard this work
```

If verification failed, do not offer commit as ready. Present only safe options such as keeping changes for debugging or discarding after confirmation.

## Commit, Keep, Discard

Commit: inspect `git status --short`, stage only files related to this issue, never stage unrelated user changes, use a commit message referencing the issue number or slug, and report the commit hash.

Keep: leave the worktree unchanged and report current status. Do not clean up, commit, or discard.

Discard: list changed and untracked files that would be removed, explain permanence, and require the user to type `discard`. If issue-related changes cannot be separated from pre-existing user changes, do not discard automatically.

## Stop Conditions

Stop and report instead of implementing when status is not `ready-for-agent`, acceptance criteria are missing, labels conflict, human judgment is required, verification needs unavailable services, tests repeatedly fail for unclear reasons, scope would be exceeded, or commit/discard would affect unrelated user changes.
