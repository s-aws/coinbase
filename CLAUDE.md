# CLAUDE.md

## Project

Trading bot for Coinbase derivatives/spot markets. Python 3.12, pytest for testing.

## Testing

- Regression tests live in `tests/regression/`
- Run with: `python3 -m pytest tests/regression/ -v --tb=short`
- Test file naming: `tests/regression/test_<feature>.py`
- New tests for bug fixes should be regression tests in `tests/regression/`

## Conventions

- No comments unless the why is non-obvious
- Prefer editing existing files over creating new ones
- No premature abstractions — three similar lines beats a helper
- `tools/check_ownership.py` must pass before committing

Context discipline:
- Avoid reading large files unless the task requires it.
- Use rg/grep first, then read only targeted line ranges.
- Spawn subagents for parallel, independent research tasks.
- After every major investigation, write a compact summary and discard raw tool output.
- Do not repeat file reads unless the file changed.
- For code review, inspect files by symbol/function, not whole-file ingestion.
- Keep working context under 35k tokens.

CRITICAL: You are not done when tests pass. You must prove compatibility at the known runtime call sites.

## Compatibility-First Change Protocol

Before editing, identify the public compatibility contract of every symbol you change or replace.

A public contract includes:
- imports: `from module import symbol`, `import module; module.symbol`
- calls: `symbol(...)`, `symbol.method(...)`
- attribute reads: `symbol.attr`
- attribute writes: `symbol.attr = value`
- item access: `symbol[key]`, `symbol[key] = value`
- truthiness/type/identity checks
- monkeypatch/patch patterns in tests
- thread-safety expectations
- import-time side effects

You must search for actual call-site operations, not just symbol names.

For each changed public symbol:
1. List existing call-site operation types.
2. State whether the old operation still works unchanged.
3. Add or run a direct probe for each important operation using the old import style.
4. Add regression tests for every reviewed bug or compatibility gap.
5. Do not claim success based only on new helper APIs or internal state checks.
6. Do not remove exported names unless every importer is migrated in the same patch.
7. If introducing a proxy/wrapper, it must emulate all old operations or callers must be updated.

Required probes for compatibility refactors:
- `python -c "import main"` where applicable
- `python -c "from <module> import <changed_symbol>"`
- one direct probe per old operation type
- `python tools/check_ownership.py`
- `pytest tests/regression/ -v --tb=short`

Test quality rules:
- A singleton test must use a factory that returns a fresh object each call and assert factory call count is 1.
- An import-time side-effect test must patch the dependency before importing the module under test, or assert via `sys.modules`/observable side effects.
- A thread-safety test must force concurrent first access with a barrier.
- Tests must exercise production import paths, not only new helper functions.
- If a reviewer finds a bug, add a regression test that fails on the buggy version.

Review checklist before final response:
- Did I test the old public API?
- Did I test direct runtime entrypoints?
- Did I test writes as well as reads/calls?
- Did I preserve exported names?
- Did I avoid broad formatting, line-ending churn, and unrelated edits?
- Did ownership checks pass?

Coinbase repo-specific:
- `configuration.py` is a compatibility module. Treat `REST_CLIENT`, `ORDERBOOK`, `API_KEY`, `API_SECRET`, `Subscription`, and product helpers as exported public names.
- `ORDERBOOK` is mutable runtime state. Existing callers may read and write attributes.
- Any non-agent-file change must pass `pytest tests/regression/ -v --tb=short`.
- Use surgical patches only; do not normalize line endings or run broad formatters.

CRITICAL:
- `genai_data\AGENT_ARCHITECT.md` must be read to understand when and where edits can be made.

CRITICAL: Do not invent behavior. If a behavior is missing, raise it to the user as a request to create a plan.