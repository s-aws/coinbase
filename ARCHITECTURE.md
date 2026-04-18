# Architecture and Refactoring Guide

## Current Project Structure

### Files Overview

```
e:\coinbase\
├── DOCUMENTATION.md                    # Main documentation (you are here)
├── TESTS_AND_EXAMPLES.md              # Test cases and examples
├── API_REFERENCE.md                   # Detailed API reference
├── ARCHITECTURE.md                    # This file
│
├── configuration.py                   # ~600 lines: Config, utils, OrderBook
├── main.py                            # ~800 lines: OrderEngine orchestration
├── order.py                           # ~200 lines: Order placement utilities
│
├── database/
│   ├── database.py                    # ~150 lines: PostgreSQL connection
│   └── order.py                       # ~300 lines: Order CRUD operations
│
├── websocket/
│   ├── ticker.py                      # Event handlers (minimal)
│   └── on_message/
│       └── user.py                    # Event handlers (minimal)
│
├── cli_create_all_tables.py          # Database initialization
├── cli_delete_all_tables.py          # Database reset
├── cli_list_all_orders.py            # Order listing utility
├── main_place_order.py               # Order placement example
│
└── api_reference/                     # JSON schema examples
    └── (various endpoint references)
```

---

## Current Architecture Analysis

### Responsibility Map

| File | Responsibilities | Lines |
|------|------------------|-------|
| **configuration.py** | API initialization, type conversion, product/order resolution, REST wrappers, order calculation, OrderBook class, Subscription | ~600 |
| **main.py** | OrderEngine class, threading, event processing, follow-up creation, state management, logging | ~800 |
| **order.py** | Order placement, price/size formatting, retry logic | ~200 |
| **database/database.py** | PostgreSQL connection, transaction management | ~150 |
| **database/order.py** | Parent/child order schema, CRUD operations | ~300 |
| **CLI scripts** | Database setup, utility scripts | ~150 |
| **Total** | | **~2,200** |

---

### Dependency Graph

```
┌─────────────────────────────────────┐
│     main.py (OrderEngine)           │
├─────────────────────────────────────┤
│ Imports from:                       │
│  - configuration (REST, utils)      │
│  - database.order (persistence)     │
│  - order (order placement)          │
│  - coinbase SDK                     │
└────────────────┬────────────────────┘
                 │
        ┌────────┴─────────┬──────────────┐
        │                  │              │
        ▼                  ▼              ▼
    order.py         configuration.py  database/order.py
        │                  │              │
        │         ┌────────┴──────┐      │
        │         │               │      │
        │         ▼               ▼      ▼
        │    REST_CLIENT    database/database.py
        │         │               │
        └─────────┼───────────────┴──────┐
                  │                       │
                  ▼                       ▼
            coinbase SDK          psycopg2 (PostgreSQL)
```

---

## Current Design Issues

### 1. **Mixed Concerns in configuration.py**
- ✗ API client initialization (REST_CLIENT)
- ✗ Configuration constants (ORDER_SIDE_SWITCH, etc.)
- ✗ Utility functions (safe_float, quantize_to_increment)
- ✗ REST wrappers (rest_get_products, rest_get_account_wallets)
- ✗ Calculation logic (calculate_new_order_move_from_snapshot)
- ✗ State container (OrderBook class)
- ✗ Subscription config (Subscription class)

**Impact**: Hard to test, change, or reuse individual components

### 2. **Large OrderEngine Class**
- ✗ 800+ lines in single class
- ✗ Threading logic mixed with business logic
- ✗ Deduplication logic embedded
- ✗ Event processing tightly coupled
- ✗ Too many methods (50+) at varying abstraction levels

**Impact**: Difficult to maintain, test, extend

### 3. **Tight Coupling Between Layers**
- ✗ REST client imported directly in configuration
- ✗ OrderBook directly imports REST client
- ✗ OrderEngine assumes specific order calculation logic
- ✗ Database operations tightly bound to order model

**Impact**: Difficult to mock, test, or swap implementations

### 4. **State Management Issues**
- ✗ OrderBook is global instance (ORDERBOOK)
- ✗ Multiple dictionaries for tracking (filled, cancelled, active)
- ✗ Deduplication state (seen_events buckets)
- ✗ Locking strategy not documented
- ✗ No clear ownership of state mutations

**Impact**: Thread safety bugs, race conditions, hard to debug

### 5. **Inconsistent Error Handling**
- ✗ Some functions return None on error
- ✗ Some raise exceptions
- ✗ Some return error dicts
- ✗ No standard error types

**Impact**: Unpredictable error handling, hard to integrate

### 6. **Difficulty Testing**
- ✗ Hard to mock external API (REST_CLIENT is global)
- ✗ Hard to test without real database
- ✗ Hard to test threading logic (run_forever blocks)
- ✗ Hard to test event processing (queue/thread based)

**Impact**: Limited test coverage, risky changes

---

## Proposed Refactored Architecture

### Layer-Based Design

```
┌─────────────────────────────────────────────────────┐
│              Application Layer                      │
│  (main.py - Orchestration & CLI)                   │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│           Business Logic Layer                      │
│  ├─ trading_engine.py (OrderEngine refactored)     │
│  ├─ order_processor.py (Follow-up logic)           │
│  ├─ position_tracker.py (Position updates)         │
│  └─ event_processor.py (WebSocket events)          │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│            Calculator/Logic Layer                   │
│  ├─ order_calculator.py (calculate_new_order_move) │
│  ├─ formatter.py (quantize, format_based_on_ref)   │
│  ├─ resolver.py (resolve_order_size, normalize)    │
│  └─ validators.py (validate orders, positions)     │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│            Data Access Layer (Repository)          │
│  ├─ order_repository.py                           │
│  ├─ position_repository.py                        │
│  ├─ product_repository.py                         │
│  └─ database_connection.py                        │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│            External Services Layer                  │
│  ├─ coinbase_client.py (REST API wrapper)          │
│  ├─ websocket_client.py (WebSocket wrapper)        │
│  └─ postgresql_client.py                          │
└─────────────────────────────────────────────────────┘
```

### New Module Structure

```
coinbase/
├── application/
│   ├── __init__.py
│   ├── cli.py                       # Entry points, CLI
│   └── main_app.py                  # Application orchestration
│
├── core/
│   ├── __init__.py
│   ├── models.py                    # Order, Position, Product dataclasses
│   ├── config.py                    # Configuration classes
│   ├── enums.py                     # OrderSide, OrderStatus, etc.
│   ├── exceptions.py                # Custom exception types
│   └── constants.py                 # Constants (SPOT_PRODUCTS, etc.)
│
├── business/
│   ├── __init__.py
│   ├── trading_engine.py            # Main OrderEngine (refactored)
│   ├── order_processor.py           # Follow-up order creation
│   ├── position_tracker.py          # Position update logic
│   ├── event_processor.py           # WebSocket event handling
│   ├── deduplicator.py              # Event deduplication
│   └── reconciler.py                # Database reconciliation
│
├── calculation/
│   ├── __init__.py
│   ├── order_calculator.py          # calculate_new_order_move
│   ├── formatter.py                 # Format and quantize functions
│   ├── resolver.py                  # resolve_order_size, etc.
│   └── validators.py                # Validation logic
│
├── data/
│   ├── __init__.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── order_repository.py
│   │   ├── position_repository.py
│   │   ├── product_repository.py
│   │   └── wallet_repository.py
│   │
│   ├── database.py                  # PostgreSQL connection (unchanged)
│   └── cache.py                     # In-memory caching strategy
│
├── external/
│   ├── __init__.py
│   ├── coinbase_client.py           # REST API wrapper
│   ├── websocket_client.py          # WebSocket wrapper
│   └── postgresql.py                # PostgreSQL client
│
├── utils/
│   ├── __init__.py
│   ├── logger.py                    # Logging utilities
│   ├── threading_utils.py           # Thread helpers
│   ├── decorators.py                # Common decorators
│   └── validators.py                # Generic validators
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── DOCUMENTATION.md
├── API_REFERENCE.md
├── TESTS_AND_EXAMPLES.md
└── REFACTORING_STATUS.md
```

---

## Refactoring Roadmap

### Phase 1: Extraction & Isolation (Weeks 1-2)

**Goal**: Move code into separate modules with minimal logic changes

#### Step 1.1: Extract Core Models
- Create `core/models.py` with dataclasses:
  - `Order` (client_order_id, product_id, side, status, ...)
  - `Position` (product_id, side, number_of_contracts, ...)
  - `Product` (product_id, price_increment, base_increment, ...)
  - `Wallet` (currency, available_balance, total_balance, ...)

- Create `core/enums.py`:
  - `OrderSide` (BUY, SELL)
  - `OrderStatus` (OPEN, FILLED, CANCELLED, PENDING)
  - `ProductType` (SPOT, FUTURE)
  - `TargetMovementType` (PERCENTAGE, ABSOLUTE)

#### Step 1.2: Extract Configuration
- Create `core/config.py`:
  - `TradingConfig` dataclass
  - `WebSocketConfig` dataclass
  - `DatabaseConfig` dataclass
  - `OrderConfig` dataclass (post_only settings, etc.)

- Create `core/constants.py`:
  - SPOT_PRODUCT_IDS, DERIVATIVES_PRODUCT_IDS
  - ORDER_SIDE_SWITCH, ORDER_POSITION_SIDE, ORDER_DIRECTION
  - DERIVATIVES_MANDATORY_FEE_PER_CONTRACT

#### Step 1.3: Extract Utilities
- Create `calculation/formatter.py`:
  - `format_based_on_reference()`
  - `quantize_to_increment()`

- Create `calculation/resolver.py`:
  - `resolve_order_size()`
  - `normalize_product_type()`
  - `safe_float()`
  - `resolve_profit_move_pct()`

**Tests**: Unit tests for each extracted module

---

### Phase 2: Dependency Injection & Decoupling (Weeks 3-4)

**Goal**: Remove global singletons, enable testing and flexibility

#### Step 2.1: API Client Abstraction
- Create `external/coinbase_client.py`:
  ```python
  class CoinbaseRestClient:
      def get_products(self) -> Dict[str, Product]: ...
      def get_account_wallets(self) -> Dict[str, Wallet]: ...
      def get_futures_positions(self) -> Dict[str, Position]: ...
      def get_open_orders(self) -> Dict[str, Order]: ...
      def place_limit_order(self, ...) -> Order: ...
  ```

- Create `external/coinbase_websocket.py`:
  ```python
  class CoinbaseWebSocketClient:
      def connect(self, products: List[str], channels: List[str]) -> None: ...
      def on_message(self, callback: Callable) -> None: ...
      def disconnect(self) -> None: ...
  ```

#### Step 2.2: Data Layer Abstraction
- Create repository interfaces:
  ```python
  class OrderRepository(Protocol):
      def get(self, client_order_id: str) -> Order: ...
      def get_all(self) -> List[Order]: ...
      def save(self, order: Order) -> None: ...
      def save_parent(self, parent_order: ParentOrder) -> int: ...
      def save_child(self, child_order: ChildOrder) -> int: ...
  ```

- Create `data/repositories/postgres_order_repository.py`:
  - Implements OrderRepository using PostgreSQL
  - Wraps existing database.order functions

#### Step 2.3: OrderBook Refactoring
- Rename to `StateManager`:
  ```python
  class StateManager:
      def __init__(self, repo: OrderRepository):
          self.repo = repo
          self._orders = {}
          self._positions = {}
      
      def update_order(self, order: Order) -> None: ...
      def get_position(self, product_id: str) -> Position: ...
      def get_profit_config(self, product_id: str) -> Dict: ...
  ```

- No global instance; inject into OrderEngine

**Tests**: Unit tests with mock repositories

---

### Phase 3: Business Logic Extraction (Weeks 5-6)

**Goal**: Separate orchestration from computation

#### Step 3.1: Order Calculator
- Move to `calculation/order_calculator.py`:
  ```python
  class OrderCalculator:
      def calculate_follow_up(
          self,
          order: Order,
          position: Optional[Position],
          product: Product,
          profit_config: Dict,
          target_movement: Optional[Dict] = None
      ) -> FollowUpOrderTemplate: ...
  ```

#### Step 3.2: Order Processor
- Create `business/order_processor.py`:
  ```python
  class OrderProcessor:
      async def process_fill(
          self,
          order: Order,
          state: StateManager
      ) -> Optional[PlacedOrder]: ...
      
      async def process_cancellation(
          self,
          order: Order,
          state: StateManager
      ) -> Optional[PlacedOrder]: ...
  ```

#### Step 3.3: Event Processing
- Create `business/event_processor.py`:
  ```python
  class EventProcessor:
      async def process_snapshot(self, event: SnapshotEvent) -> None: ...
      async def process_open(self, event: OpenEvent) -> None: ...
      async def process_filled(self, event: FilledEvent) -> None: ...
      async def process_cancelled(self, event: CancelledEvent) -> None: ...
  ```

**Tests**: Unit tests with mock state and API client

---

### Phase 4: OrderEngine Refactoring (Weeks 7-8)

**Goal**: Reduce OrderEngine to pure orchestration

#### Step 4.1: Threading Extraction
- Create `business/thread_coordinator.py`:
  ```python
  class ThreadCoordinator:
      def start_websocket_threads(self, count: int) -> None: ...
      def start_event_processors(self, count: int) -> None: ...
      def start_background_tasks(self) -> None: ...
      def shutdown_all(self) -> None: ...
  ```

#### Step 4.2: Deduplication Extraction
- Create `business/deduplicator.py`:
  ```python
  class EventDeduplicator:
      def should_process(self, event_dict: Dict) -> bool: ...
      def mark_processed(self, event_dict: Dict) -> None: ...
      def rotate_buckets(self) -> None: ...
  ```

#### Step 4.3: Clean OrderEngine
- Reduced to:
  ```python
  class OrderEngine:
      def __init__(
          self,
          state_manager: StateManager,
          order_processor: OrderProcessor,
          event_processor: EventProcessor,
          thread_coordinator: ThreadCoordinator,
          deduplicator: EventDeduplicator,
          config: TradingConfig
      ): ...
      
      async def run(self) -> None: ...
  ```

**Tests**: Integration tests with all components

---

### Phase 5: Testing & Documentation (Weeks 9-10)

**Goal**: Comprehensive test coverage and updated docs

#### Step 5.1: Test Suite
- Unit tests for each module (target: 80%+ coverage)
- Integration tests for workflows
- Mock external dependencies
- Performance benchmarks

#### Step 5.2: Documentation
- Update all docstrings
- Create architecture diagrams
- Document testing strategy
- Create migration guide

---

## Benefits of Refactored Architecture

### 1. **Testability**
```python
# Before: Hard to mock REST client (global)
def test_calculate_follow_up():
    # Can't test without real API

# After: Dependency injection enables mocking
def test_calculate_follow_up(mock_client):
    calculator = OrderCalculator(product_repo=mock_client)
    result = calculator.calculate_follow_up(...)
```

### 2. **Maintainability**
- Each module has single responsibility
- Clear dependencies
- Easy to understand code flow
- 200-300 line limit per class

### 3. **Reusability**
```python
# Can use OrderCalculator without full engine
calculator = OrderCalculator(formatter, resolver)
template = calculator.calculate_follow_up(order, ...)

# Can use OrderProcessor independently
processor = OrderProcessor(calculator, client, repo)
new_order = await processor.process_fill(filled_order, state)
```

### 4. **Extensibility**
```python
# Easy to add new order processors
class PercentageOrderProcessor(OrderProcessor):
    async def process_fill(self, order, state):
        # Custom logic
        pass

# Easy to add new calculators
class AdvancedOrderCalculator(OrderCalculator):
    async def calculate_follow_up(self, order, ...):
        # Advanced logic
        pass
```

### 5. **Thread Safety**
- Clear state ownership (StateManager)
- Explicit synchronization primitives
- Easy to audit concurrent access
- Testable without actual threads

### 6. **Error Handling**
```python
class OrderPlacementError(Exception): ...
class InsufficientFundsError(OrderPlacementError): ...
class NetworkError(Exception): ...

# Consistent error handling
try:
    order = await processor.place_order(template)
except InsufficientFundsError:
    logger.warn("Insufficient funds")
    retry_later()
```

---

## Migration Path

### For Existing Code
1. Run existing code alongside refactored components
2. Gradually swap implementations
3. Keep database schema unchanged
4. Provide adapter layer for compatibility

### Version Numbering
- **v1.x**: Current monolithic version
- **v2.0**: Refactored modular version
- **v2.x**: Stabilization and optimization

---

## Current State Summary

| Aspect | Status | Notes |
|--------|--------|-------|
| **Functionality** | ✓ Working | All core features implemented |
| **Code Quality** | ⚠ Moderate | Mixed concerns, tight coupling |
| **Testability** | ⚠ Limited | Hard to unit test, relies on API |
| **Documentation** | ✓ Created | Comprehensive docs provided |
| **Scalability** | ⚠ Fair | Thread-based, monolithic |
| **Maintainability** | ⚠ Fair | Large classes, implicit dependencies |

---

## Quick Start for Refactoring

1. **Start with Phase 1**: Extract models and constants (low risk)
2. **Move to Phase 2**: Create repository pattern (medium risk)
3. **Parallel Phase 3/4**: Extract business logic and clean OrderEngine
4. **Complete Phase 5**: Comprehensive testing

Each phase is independently testable and can be deployed separately.

