# Test Suite Documentation

External test operations runbook: `docs/EXTERNAL_TESTING_RUNBOOK.md`

Comprehensive regression testing suite for the Coinbase Advanced Trading Platform. This test structure follows enterprise standards (Google, Meta) for safe deployments across all project components.

**Current Focus:** Stealth order management (foundation for other features)  
**Scope:** Entire project - covers order management, conditions, portfolio, dashboard, and Coinbase API integration

## Test Structure

```
tests/
├── unit/           - Isolated component tests (no external deps)
├── integration/    - Multi-component tests (in-process)
├── e2e/           - End-to-end tests (full system)
├── external/      - Coinbase API/WebSocket tests (ISOLATED)
├── fixtures/      - Test data and mocks
└── regression/    - Critical path tests (milestone/release closeout gate)
```

## Running Tests

## Current Regression Policy

Use focused tests and validators for ordinary phase work. The full
`tests/regression/` gate is reserved for durable milestone closeout,
public/release-candidate handoff, deployment approval, or explicit user
request.

When the full regression gate is required, prefer the process-parallel helper:

```bash
python tools/run_parallel_regression.py --workers 4
```

The helper runs tests marked `serial` in a separate sequential lane and runs
the remaining regression tests with pytest-xdist process workers. Do not use
Python threads to parallelize this suite.

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test Category
```bash
pytest tests/unit/ -v              # Unit tests only
pytest tests/integration/ -v       # Integration tests
python tools/run_parallel_regression.py --workers 4  # Full milestone/release regression gate
pytest tests/external/ -v          # Coinbase API tests (requires API key)
```

### Run with Coverage
```bash
pytest tests/ --cov=. --cov-report=html
```

### Run Regression For Milestone Closeout Or Release Candidate
```bash
python tools/run_parallel_regression.py --workers 4
# Must pass before closing a durable milestone or releasing/deploying changes
```

Use `pytest tests/regression/ -v --tb=short` only as an intentional sequential
fallback when `pytest-xdist` is unavailable.

## Test Categories

### 1. Unit Tests (`tests/unit/`)
**Purpose:** Test individual components in isolation with mocks.

**When to use:**
- Testing business logic (StealthOrderManager, OrderCalculator, OrderProcessor, evaluators)
- Testing individual functions with mocked dependencies
- Fast, deterministic, no I/O

**Examples (existing and future):**
- `test_stealth_order_manager.py` - Stealth order creation, state transitions, reveals
- `test_order_calculator.py` - Order math, spread calculations, sizing
- `test_condition_evaluators.py` - All reveal condition types (price, time, volume, spread, etc)
- `test_database.py` - DB operations with mocked connections
- `test_event_processor.py` - Event handling and routing

**Characteristics:**
- No network calls
- No real database
- Mocked external dependencies
- Run in < 1 second per test

### 2. Integration Tests (`tests/integration/`)
**Purpose:** Test multiple components working together (but not external APIs).

**When to use:**
- Testing workflow across components (order creation through execution)
- Testing database persistence
- Testing event/hook systems
- Testing condition evaluation with real market data

**Examples (existing and future):**
- `test_stealth_order_workflow.py` - Stealth order creation → reveal → execution
- `test_order_calculator_integration.py` - Calculator with conditions and market data
- `test_event_flow.py` - Events propagating through system
- `test_bridge_orchestration.py` - Multiple threads/components working together
- `test_portfolio_management.py` - Portfolio updates and tracking

**Characteristics:**
- Use real in-memory database (SQLite)
- Can use real components
- No Coinbase API calls (use mocks)
- May be slower (1-10 seconds per test)

### 3. End-to-End Tests (`tests/e2e/`)
**Purpose:** Test complete user workflows through full system.

**When to use:**
- Testing complete order lifecycle (from create through execution)
- Testing dashboard integration and WebSocket updates
- Testing multiple simultaneous orders
- Validating system under realistic conditions

**Examples (existing and future):**
- `test_full_order_lifecycle.py` - Stealth order: create → monitor → reveal → execute
- `test_dashboard_updates.py` - Orders appear, stats update, conditions evaluate
- `test_cli_order_placement.py` - CLI to order execution
- `test_portfolio_dashboard.py` - Portfolio view updates in real-time
- `test_concurrent_orders.py` - Multiple orders processing simultaneously

**Characteristics:**
- Real application state
- May use test database
- No real Coinbase API (use mocks)
- Slower (5-30 seconds per test)

### 4. External Tests (`tests/external/`)
**Purpose:** Test actual Coinbase API integration. ISOLATED from other tests.

⚠️ **IMPORTANT:** These tests require:
- Valid Coinbase API credentials
- Test account/sandbox
- Network access
- Run separately from other tests

**When to use:**
- Testing REST API integration (accounts, orders, products, conversions, fees)
- Testing WebSocket connections (ticker, user messages, done)
- Testing API response handling and error cases
- Regression testing after API changes

**Current external coverage in this repo:**
- Live REST contract checks in `tests/external/test_coinbase_api.py` for accounts/products/orders
- WebSocket reference contract checks using `websocket_reference/`
- Wrapper behavior checks for `external/coinbase_websocket.py` without network I/O
- Optional live WebSocket ticker smoke test (explicit opt-in)

**Examples (existing and future):**
- `test_rest_api.py` - Accounts, order placement, cancellation, product lookup, conversions
- `test_websocket.py` - Subscribe/unsubscribe, ticker updates, order fills
- `test_error_handling.py` - Rate limits, API errors, timeouts, reconnection
- `test_perpetuals_api.py` - Perpetual positions and orders (if applicable)

**Characteristics:**
- Requires credentials
- Makes real network calls
- Uses `api_reference/` and `websocket_reference/`
- Slow (depends on network)
- Run in CI/CD after unit/integration pass

**Run only external tests:**
```bash
pytest tests/external/ -v -m external
```

**Run websocket external tests only (default includes safe skips):**
```bash
pytest tests/external/test_coinbase_api.py -v -m websocket --tb=short
```

**Enable live websocket smoke test explicitly:**
```bash
export COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true
pytest tests/external/test_coinbase_api.py -v -m websocket --tb=short
```

**Skip external tests in normal development:**
```bash
pytest tests/ -v -m "not external"
```

### 5. Regression Tests (`tests/regression/`)
**Purpose:** Critical path tests for durable milestone closeout, public/release
candidate handoff, deployment approval, or explicit user request.

**When to use:**
- Before durable milestone closeout
- Before production deployment or release-candidate handoff
- After broad architectural changes when focused tests are insufficient
- When explicitly requested

**Content (project-wide critical paths):**
- Order creation and execution (all order types)
- Stealth order reveals and state management
- Condition evaluation accuracy
- Database persistence and recovery
- Portfolio calculations and updates
- Event routing and notifications
- WebSocket message handling
- Error handling and graceful degradation

**Current examples:**
- Core functionality: stealth order creation, reveal, execution
- State persistence: database operations
- Event flow: notifications and updates
- Error handling: edge cases and failures

**Characteristics:**
- Representative of actual user workflows
- Must pass 100% before milestone closeout or release/deployment handoff
- Fast (run in < 30 seconds total)
- No external API calls (all mocked)
- Cover high-value functionality that users depend on

**Run for milestone closeout or release/deployment handoff:**
```bash
python tools/run_parallel_regression.py --workers 4
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "REGRESSION TESTS FAILED - DO NOT CLOSE OUT OR DEPLOY"
    exit 1
fi
echo "Regression tests passed - closeout/deployment gate passed"
```

## Test Data & Fixtures (`tests/fixtures/`)

### Coinbase API Responses
Use `api_reference/` JSON examples to mock real API responses:

```python
# Load from api_reference
import json

@pytest.fixture
def sample_order_response():
    with open('api_reference/orders/create_order_response.json') as f:
        return json.load(f)

def test_order_creation(sample_order_response):
    # Use real Coinbase response format
    pass
```

### WebSocket Messages
Use `websocket_reference/` for realistic WebSocket testing:

```python
@pytest.fixture
def websocket_messages():
    with open('websocket_reference/authenticated/user_messages.json') as f:
        return json.load(f)
```

### Test Data Files
Store fixture data in `tests/fixtures/`:
- `coinbase_responses.json` - REST API responses
- `websocket_messages.json` - WebSocket message samples
- `order_samples.json` - Test order data
- `market_data.json` - Ticker/market data

## Workflow: Before Making Architectural Changes

1. **Run full test suite to establish baseline:**
   ```bash
   pytest tests/ -v --tb=short > test_baseline.log
   ```

2. **Make changes to core engine**

3. **Run focused tests immediately:**
   ```bash
   pytest tests/regression/<focused_test_file>.py -v --tb=short
   ```
   - Must pass for the changed behavior

4. **Run full test suite:**
   ```bash
   pytest tests/ -v --tb=short
   ```
   - Review any new failures
   - Update tests if behavior changed intentionally

5. **Run external tests (if API integration changed):**
   ```bash
   pytest tests/external/ -v -m external
   ```

6. **Run full regression before milestone closeout or deployment approval:**
   ```bash
   python tools/run_parallel_regression.py --workers 4
   ```

7. **Deploy only if required gates pass**

## Continuous Integration

### GitHub Actions / GitLab CI Example

```yaml
test:
  script:
    # Unit tests (fast, no deps)
    - pytest tests/unit/ -v
    
    # Integration tests (medium speed)
    - pytest tests/integration/ -v
    
    # Regression tests (must pass)
    - python tools/run_parallel_regression.py --workers 4
    
  only:
    - merge_requests
    - main
```

```yaml
test:external:
  script:
    - pytest tests/external/ -v -m external
  only:
    - main  # Only run on main branch
  when: manual  # Requires approval
```

## Test Organization Best Practices

### File Naming
- Test files: `test_*.py`
- Test functions: `test_<component>_<behavior>()`
- Fixtures: `tests/fixtures/*.json` or conftest.py

### Test Naming Convention
```python
def test_stealth_order_manager_creates_order_with_valid_params():
    """Clear, descriptive names"""
    pass

def test_stealth_order_manager_raises_error_on_invalid_product():
    """Test error cases explicitly"""
    pass
```

### One Assertion Per Test (When Possible)
```python
# Good
def test_order_has_correct_total_size():
    order = create_order(total_size=10)
    assert order.total_size == 10

# Good - Multiple related assertions
def test_order_creation():
    order = create_order(total_size=10)
    assert order.total_size == 10
    assert order.status == 'HIDDEN'
    assert order.created_at is not None
```

## Test Dependencies

See `requirements.txt` for test-specific dependencies.

## Troubleshooting Tests

### External tests fail with "API key not found"
```bash
export COINBASE_API_KEY=your_key
export COINBASE_API_SECRET=your_secret
pytest tests/external/ -v
```

### Live websocket smoke test is skipped
By default, live websocket smoke tests are disabled for safety.

Enable them explicitly:
```bash
export COINBASE_ENABLE_WEBSOCKET_EXTERNAL=true
pytest tests/external/test_coinbase_api.py -v -m websocket --tb=short
```

If disabled, websocket tests still run deterministic contract/wrapper checks and skip only the live network scenarios.

### Database tests fail with "connection error"
Tests use SQLite in-memory database. Ensure `database.py` supports `":memory:"` mode.

### WebSocket tests timeout
Increase timeout in `tests/external/conftest.py`:
```python
WEBSOCKET_TIMEOUT = 10  # seconds
```

## Metrics to Track

After running tests, track:
- **Test Count:** Total unit, integration, regression
- **Coverage:** Code coverage % (aim for > 80%)
- **Regression Pass Rate:** Must be 100% before milestone closeout or release/deployment handoff
- **Test Execution Time:** Should complete in < 5 minutes

## Project Components (Ready for Test Coverage)

This test suite covers the entire platform. Key components include:

**Core Order Management:**
- `core/stealth_order_manager.py` - Stealth order lifecycle
- `business/order_calculator.py` - Order math and calculations
- `business/order_processor.py` - Order execution pipeline
- `core/order_engine.py` - Main order execution engine

**Condition Evaluation:**
- `business/stealth_condition_evaluator.py` - All condition types (price, time, volume, spread, etc)
- `calculation/resolver.py` - Condition resolution logic

**Event Processing:**
- `business/event_processor.py` - Event routing
- `bridges/event_bridge.py` - Event pub/sub

**Database & Persistence:**
- `database/database.py` - DB operations
- `data/repositories/` - Data access layer
- `data/state_manager.py` - In-memory state management

**API & WebSocket:**
- `external/coinbase_client.py` - REST API client
- `external/coinbase_websocket.py` - WebSocket client
- `websocket/ticker.py` - Market data handling

**Dashboard & UI:**
- `dashboard_server.py` - WebSocket server for UI
- `ui_stealth_orders_manager.html` - Stealth orders dashboard
- `ui_dashboard.html` - Main dashboard

**Portfolio & Accounts:**
- Account management operations
- Portfolio calculations and tracking

## Next Steps

1. ✓ Create test infrastructure (done)
2. ✓ Create example tests for stealth orders (done)
3. Add unit tests for OrderCalculator, ConditionEvaluators
4. Add integration tests for order workflows
5. Add E2E tests for dashboard and portfolio
6. Add external tests for Coinbase API integration
7. Run regression tests before architectural refactoring
