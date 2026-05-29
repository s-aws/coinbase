# Test Suite Documentation

This document serves as the index and primary documentation for the test suite in this repository.

## Test Structure

```
tests/
├── unit/           - Isolated component tests (no external deps)
├── integration/    - Multi-component tests (in-process)
├── e2e/           - End-to-end tests (full system)
├── external/      - Coinbase API/WebSocket tests (ISOLATED)
├── fixtures/      - Test data and mocks
└── regression/    - Critical path tests (runs before deploy)
```

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

### 5. Regression Tests (`tests/regression/`)
**Purpose:** Critical path tests that must pass before deployment.

**When to use:**
- Before any major refactor (like adding hooks/events)
- Before production deployment
- After architectural changes
- After merging major features

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
- Must pass 100% before deploy
- Fast (run in < 30 seconds total)
- No external API calls (all mocked)
- Cover high-value functionality that users depend on

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

## Running Tests

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test Category
```bash
pytest tests/unit/ -v              # Unit tests only
pytest tests/integration/ -v       # Integration tests
pytest tests/regression/ -v        # Regression tests (critical)
pytest tests/external/ -v          # Coinbase API tests (requires API key)
```

### Run with Coverage
```bash
pytest tests/ --cov=. --cov-report=html
```

### Run Regression Before Deploy
```bash
pytest tests/regression/ -v --tb=short
# Must pass 100% before deploying changes
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
    - pytest tests/regression/ -v
    
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

## Project Components Covered by Tests

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

## External Test Operations Runbook

For detailed external testing procedures, see: [External Testing Runbook](../docs/EXTERNAL_TESTING_RUNBOOK.md)
