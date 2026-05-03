# Pre-Deployment Checklist

Before deploying any changes to the platform (architectural changes, new features, bug fixes), follow this checklist:

## Phase 1: Establish Baseline (✓ Do This First)

- [ ] Run full test suite to establish baseline
  ```bash
  pytest tests/ -v --tb=short > baseline_test_results.txt
  ```
  - Record number of passing tests
  - Note any pre-existing failures
  - Get baseline code coverage %

## Phase 2: Make Your Changes

- [ ] Review suggested architectural changes
- [ ] Create feature branch
- [ ] Implement changes incrementally
- [ ] Add inline code comments for complex logic
- [ ] Update documentation in genai_data/

## Phase 3: Immediate Regression Testing

- [ ] Run regression tests immediately after changes
  ```bash
  pytest tests/regression/ -v --tb=short
  ```
  - **Must pass 100%** or roll back changes
  - If failures: revert, debug, try again

## Phase 4: Full Test Suite

- [ ] Run complete test suite
  ```bash
  pytest tests/ -v --tb=short --cov=. > full_test_results.txt
  ```
  - Compare to baseline results
  - Investigate any new failures
  - Update tests if behavior intentionally changed

## Phase 5: External API Testing

- [ ] Run external Coinbase tests (if API integration changed)
  ```bash
  export COINBASE_API_KEY=your_key
  export COINBASE_API_SECRET=your_secret
  export COINBASE_USE_SANDBOX=true
  pytest tests/external/ -v -m external
  ```

## Phase 6: Code Review

- [ ] Architecture changes approved by team
- [ ] Code follows project patterns
- [ ] Test coverage adequate (> 80%)
- [ ] Documentation updated

## Phase 7: Deployment

- [ ] All regression tests pass ✓
- [ ] All unit tests pass ✓
- [ ] All integration tests pass ✓
- [ ] External tests pass (if applicable) ✓
- [ ] Code review approved ✓
- [ ] Documentation updated ✓
- [ ] Commit message references test results
- [ ] Tag release with test results

## Phase 8: Post-Deployment Monitoring

- [ ] Monitor error logs for new issues
- [ ] Verify order creation/reveal in production
- [ ] Check WebSocket connections stable
- [ ] Monitor database performance
- [ ] Ready to rollback if needed

---

## Quick Reference: Common Commands

### Establish baseline before changes
```bash
pytest tests/ -v --tb=short > baseline.log
pytest tests/ --cov=. --cov-report=term-missing > baseline_coverage.log
```

### Check regression tests (immediate)
```bash
pytest tests/regression/ -v --tb=short
```

### Full test suite after changes
```bash
pytest tests/ -v --tb=short > after_changes.log
diff baseline.log after_changes.log  # Compare results
```

### Run with coverage
```bash
pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html  # View coverage report
```

### External API tests (sandbox only)
```bash
export COINBASE_USE_SANDBOX=true
pytest tests/external/ -v -m external --tb=short
```

### Skip external tests for faster development
```bash
pytest tests/ -v -m "not external"
```

---

## Exit Codes

Use these to validate test status in CI/CD:

```bash
# Run regression tests
pytest tests/regression/ -v
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "REGRESSION TESTS FAILED - DO NOT DEPLOY"
    exit 1
fi

echo "All regression tests passed - safe to deploy"
exit 0
```

## Why This Matters

When refactoring the engine architecture (adding hooks, events, middleware, etc.):

1. **Regression tests catch regressions** - If architecture changes broke core functionality, tests fail immediately
2. **Tests document behavior** - Future developers understand what the system should do
3. **Tests enable confidence** - You can refactor knowing nothing broke
4. **Tests catch edge cases** - Handle scenarios developers might overlook

The more comprehensive the test suite, the safer the refactoring.
