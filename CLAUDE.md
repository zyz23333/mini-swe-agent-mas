# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Principle Priority

Security = Correctness > Minimal Changes > Readability > Consistency

## Language and Communication

- Use Chinese when having a conversation.
- Use English when writing code,document and annotation.
- Add comments inside relatively complex functions and implementations; for other code, add comments appropriately as well.
- Stay cautious and work from the original requirements and problem statement.
- When you hit a blocker (unclear motivation, invalid prerequisite assumptions, insufficient information, or conflicts in the proposed approach), stop immediately and report it; do not continue based on guesswork.

## Development and Modification

- Before execution, assess task complexity and briefly explain your approach. For complex tasks, first sort out the fundamental goals and constraints, confirm the plan, and only then start implementation.
- When proposing a modification or refactoring plan:
  - Make a solution decision:
    - If the issue is a structural defect (such as architectural coupling, duplicated code, or accumulated technical debt) -> choose a root-cause solution.
    - If the issue is a localized defect (such as missing boundary handling or incorrect condition checks in specific cases) -> make the minimum necessary. change
    - When a root-cause fix has a large change surface or involves interface changes, you must pause and ask for confirmation.
    - Do not expand the scope on your own (for example, by adding extra fallbacks). If you discover security, data, or performance risks, report them separately after completing the main request.
  - Perform a static logic check on the plan: walk through entry -> core logic -> boundary/exception paths -> exit, and confirm that the data flow is intact.
- When maintaining the project/code, keep the architecture clear and readable. Do not change the established directory structure or architectural layering without explanation.
- Prefer existing project dependencies or the standard library. Do not introduce new third-party dependencies without approval; if one is truly needed, explain why and get confirmation first.
- Logging strategy: log key areas such as inputs, branch decisions, and exceptions; do not log inside loops or other high-frequency call paths.
- Error handling strategy: handle recoverable errors nearby and log them; for unrecoverable errors, fail fast and raise them upward. Do not swallow errors silently.
- If you find that canonical documentation is clearly outdated, update it after the implementation.
- For high-risk operations such as deleting files, pushing to remote, or changing environments/CI/DB, verify the syntax and obtain a second confirmation before proceeding; do not execute them on your own.

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
- Tests that read text content to perform string assertions (if such tests were written during development to follow the Red-Green testing cycle, they should be removed once the code and documentation are complete)

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


