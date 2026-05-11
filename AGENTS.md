
## Subagent Spawn Rule

If there is no explicit prompt from the user or SKILL to enable a subagent for the task, please default to handling it on your own.

<!-- MANUAL ADDITIONS START -->
## Principle Priority

Security = Correctness > Minimal Changes > Readability > Consistency

## Language and Communication

- Use Chinese when having a conversation.
- Use English when writing code,document and annotation.
- Add comments inside relatively complex functions and implementations; for other code, add comments appropriately as well.
- Stay cautious and work from the original requirements and problem statement.
- When you hit a blocker (unclear motivation, invalid prerequisite assumptions, insufficient information, or conflicts in the proposed approach), stop immediately and report it; do not continue based on guesswork.

## Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Commit Guidelines

- Create commits only when the user explicitly asks for a commit or when an active workflow/skill requires one.
- Before committing, inspect `git status` and include only files that belong to the current task. Do not include unrelated user changes.
- Keep commits atomic: one logical change per commit. Separate code changes, tests, documentation, and mechanical formatting when they are independent.
- Prefer Conventional Commits format: `<type>(<scope>): <summary>`.
- Common types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `build`, `perf`, `style`.
- Use a short, imperative English summary, for example `fix(api): validate workflow inputs`.
- Add a commit body when the change has non-obvious motivation, risk, migration notes, or verification details.
- Do not commit secrets, local environment files, generated caches, dependency vendor directories, or temporary scratch artifacts unless they are explicitly part of the requested change.
- Do not commit broken tests, skipped verification, or known regressions without clearly documenting the reason and getting explicit user approval.
- Never push to a remote unless the user explicitly asks for it.

## Testing Guidelines

Use reasonable judgment to decide whether tests are needed. The criteria are as follows:

Tests that are needed:

- Core business logic (input -> expected output).
- Boundary cases and error paths that are prone to regression.
- External integrations (with minimized mocking).

Tests that are not needed:

- Tests that chase coverage numbers while ignoring logic.
- Duplicate or redundant tests.
- Tests that verify implementation details rather than behavior (such as specific color values or class names).
- Tests written for deprecated functionality.
- Over-mocked or over-stubbed tests that distort reality.
- Trivial tests that do not validate business value.

## Dependency Investigation Guidance

Dependency investigation approach: the `references/` directory usually contains source code or mirrored copies of upstream open-source libraries used by this project. Whenever you need to understand implementation details, API behavior, configuration patterns, data structures, constraints, or version differences for these libraries, default to investigating the corresponding library source directly instead of relying on memory or assumptions first.

Recommended order:

1. First inspect the relevant dependency source, docs, examples, and configuration files under `references/` in this repository.
2. If the local copy is insufficient, use the `Context7` MCP service to look up official documentation, API usage, or version notes.
3. If uncertainty still remains, use `web search` to gather additional external references, prioritizing official repositories, official documentation, and other primary sources.

Default principles for dependency investigation:

- Prefer the local source of truth whenever the answer can be confirmed from local source code.
- For implementation details, edge-case behavior, or implicit conventions, do not guess from experience; support conclusions with source evidence.
- If the copy under `references/` differs from online documentation, explicitly call out the difference and prioritize judgment based on the version actually used by this project.
- Treat `Context7` and `web search` as supplementary and cross-validation tools, not as replacements for local source investigation.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default canonical label strings. See `docs/agents/triage-labels.md`.

### Domain docs

This repo uses a single-context domain documentation layout. See `docs/agents/domain.md`.
<!-- MANUAL ADDITIONS END -->


