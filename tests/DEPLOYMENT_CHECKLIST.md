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

## Phase 3: Focused Post-Change Testing

- [ ] Run focused tests and validators that cover the changed behavior
  ```bash
  pytest tests/regression/<focused_test_file>.py -v --tb=short
  ```
  - If failures: debug, fix, and rerun the focused gate
  - Do not run the full regression suite for ordinary phase work unless explicitly requested

## Phase 4: Full Regression Closeout

- [ ] Run full regression before durable milestone closeout, public/release-candidate handoff, deployment approval/closeout, release-hardening closeout, Admin API/backend association closeout, or explicit user request
  ```bash
  python tools/run_parallel_regression.py --workers 4
  ```
  - Requires pytest-xdist for the process-parallel lane; if pytest-xdist is
    unavailable, install the test dependencies or deliberately run the
    sequential closeout fallback: `pytest tests/regression/ -v --tb=short`
  - The runner validates serial-lane classification before pytest. Regression
    files touching shared DB cursors, fixed service ports, process-global
    state, or process-shared resources must use `pytest.mark.serial`; false
    positives require a documented `parallel-regression: serial-safe` comment.
  - Optional fast preflight: `python tools/run_parallel_regression.py --check-serial-classification-only`
  - Must pass before the milestone/release/deployment is considered complete

## Phase 5: Full Test Suite

- [ ] Run complete test suite when the change is broad enough to require it
  ```bash
  pytest tests/ -v --tb=short --cov=. > full_test_results.txt
  ```
  - Compare to baseline results
  - Investigate any new failures
  - Update tests if behavior intentionally changed

## Phase 6: External API Testing

- [ ] Run external Coinbase tests (if API integration changed)
  ```bash
  export COINBASE_API_KEY=your_key
  export COINBASE_API_SECRET=your_secret
  export COINBASE_USE_SANDBOX=true
  pytest tests/external/ -v -m external
  ```

## Phase 7: Code Review

- [ ] Architecture changes approved by team
- [ ] Code follows project patterns
- [ ] Test coverage adequate (> 80%)
- [ ] Documentation updated

## Phase 8: Deployment

- [ ] Full regression closeout gate passed when this is a durable milestone, release, or deployment closeout: `python tools/run_parallel_regression.py --workers 4`
- [ ] All unit tests pass ✓
- [ ] All integration tests pass ✓
- [ ] External tests pass (if applicable) ✓
- [ ] Code review approved ✓
- [ ] Documentation updated ✓
- [ ] Commit message references test results
- [ ] Tag release with test results

## Phase 9: Post-Deployment Monitoring

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

### Check focused tests after ordinary changes
```bash
pytest tests/regression/<focused_test_file>.py -v --tb=short
```

### Check full regression at closeout/release
```bash
python tools/run_parallel_regression.py --workers 4
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
# Run full regression closeout gate
python tools/run_parallel_regression.py --workers 4
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "REGRESSION TESTS FAILED - DO NOT DEPLOY"
    exit 1
fi

echo "Full regression closeout gate passed - safe to deploy"
exit 0
```

## Why This Matters

When refactoring the engine architecture (adding hooks, events, middleware, etc.):

1. **Regression tests catch regressions** - If architecture changes broke core functionality, tests fail immediately
2. **Tests document behavior** - Future developers understand what the system should do
3. **Tests enable confidence** - You can refactor knowing nothing broke
4. **Tests catch edge cases** - Handle scenarios developers might overlook

The more comprehensive the test suite, the safer the refactoring.
