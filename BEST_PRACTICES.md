"""Best Practices Guide - Coinbase Advanced Trading Engine Refactoring

This guide provides best practices for using, extending, and maintaining
the refactored Coinbase Advanced Trading Engine.

## Table of Contents

1. Code Organization
2. Module Usage
3. Testing Practices
4. Performance Optimization
5. Error Handling
6. Thread Safety
7. Debugging
8. Extension Points

## 1. Code Organization

### Do's ✅

1. **Keep phases separated**
   ```python
   # Good: Use phase-specific imports
   from core.models import Order, Position
   from business.order_calculator import OrderCalculator
   from integration.calculator_bridge import CalculatorBridge
   ```

2. **Use bridges for OrderEngine integration**
   ```python
   # Good: Use bridge pattern
   from integration.engine_integration import OrderEngineIntegration
   engine = OrderEngine(...)
   integrated = OrderEngineIntegration(engine)
   ```

3. **Follow single responsibility principle**
   ```python
   # Good: Each class has single responsibility
   calc = OrderCalculator()        # Only calculations
   proc = OrderProcessor()         # Only validation/enrichment
   evt = EventProcessor()          # Only deduplication/routing
   ```

4. **Use type hints for clarity**
   ```python
   # Good: Clear types
   def calculate_follow_up_price(
       self,
       parent_order: dict,
       follow_up_side: str,
       profit_pct: float,
   ) -> float:
       pass
   ```

### Don'ts ❌

1. **Don't mix concerns**
   ```python
   # Bad: Calculator does both calculation and validation
   result = calculator.calculate_and_validate_price(order)
   ```

2. **Don't bypass bridges**
   ```python
   # Bad: Directly using Phase 3 modules in OrderEngine
   from business.order_calculator import OrderCalculator
   OrderCalculator().calculate_follow_up_price(...)  # Skip bridge
   ```

3. **Don't modify OrderEngine for new features**
   ```python
   # Bad: Adding logic to OrderEngine
   class OrderEngine:
       def new_business_logic(self):
           pass
   
   # Good: Create bridge or new business module
   class NewBusinessLogic:
       def process(self):
           pass
   ```

4. **Don't skip error handling**
   ```python
   # Bad: No error handling
   price = bridge.calculate_follow_up_price(order, side, pct)
   
   # Good: Check for errors
   try:
       price = bridge.calculate_follow_up_price(order, side, pct)
   except (ValueError, TypeError) as e:
       logger.error(f"Price calculation failed: {e}")
       return None
   ```

## 2. Module Usage

### Phase 1: Core Modules (Always Safe)

Use whenever you need fundamental types or utilities:

```python
from core.models import Order, Position, Product
from core.enums import OrderSide, OrderStatus
from core.constants import ORDER_SIDE_SWITCH

# Safe to use directly - no dependencies on other phases
side = ORDER_SIDE_SWITCH['BUY']  # 'SELL'
```

### Phase 2: External Integration (For Testing/Flexibility)

Use when you need to mock external services:

```python
from external.coinbase_client import CoinbaseRESTClient
from data.state_manager import StateManager
from data.repositories.postgres_order_repository import PostgresOrderRepository

# Create for testing or standalone usage
client = CoinbaseRESTClient(api_key, api_secret)
state = StateManager()
repo = PostgresOrderRepository(db_connection)
```

### Phase 3: Business Logic (Recommended Approach)

Use through bridges in OrderEngine, or standalone for calculations:

```python
from business.order_calculator import OrderCalculator
from business.order_processor import OrderProcessor
from business.event_processor import EventProcessor

# Standalone usage
calc = OrderCalculator()
price = calc.calculate_follow_up_price(parent_order, side, profit)

# Through bridges (recommended with OrderEngine)
bridge = CalculatorBridge()
price = bridge.calculate_follow_up_price(parent_order, side, profit)
```

### Phase 4: Integration (For OrderEngine Enhancement)

Use when integrating Phase 3 modules into OrderEngine:

```python
from integration.engine_integration import OrderEngineIntegration

# Wrap existing engine
engine = OrderEngine(...)
integrated = OrderEngineIntegration(engine)

# Access bridges if needed
calc_bridge = integrated.get_calculator_bridge()
proc_bridge = integrated.get_processor_bridge()
evt_bridge = integrated.get_event_bridge()
```

## 3. Testing Practices

### Unit Testing

```python
# Test individual modules in isolation
import pytest
from business.order_calculator import OrderCalculator

class TestOrderCalculator:
    def setup_method(self):
        self.calculator = OrderCalculator()
    
    def test_calculate_follow_up_price_buy_to_sell(self):
        """Test specific scenario"""
        parent = {'order_side': 'BUY', 'avg_price': '100.00'}
        result = self.calculator.calculate_follow_up_price(parent, 'SELL', 0.01)
        assert result['price'] == 101.0
```

### Integration Testing

```python
# Test module interactions
from integration.calculator_bridge import CalculatorBridge
from integration.processor_bridge import ProcessorBridge

def test_order_calculation_and_validation():
    calc_bridge = CalculatorBridge()
    proc_bridge = ProcessorBridge()
    
    parent_order = {
        'order_id': '123',
        'product_id': 'BTC-USDC',
        'order_side': 'BUY',
        'avg_price': '100.00',
    }
    
    # Validate order
    is_valid, missing = proc_bridge.validate_order_fields(parent_order)
    assert is_valid
    
    # Calculate follow-up
    price = calc_bridge.calculate_follow_up_price(parent_order, 'SELL', 0.01)
    assert price == 101.0
```

### Testing Best Practices

1. **Use fixtures for common data**
   ```python
   @pytest.fixture
   def sample_order():
       return {
           'order_id': '123',
           'product_id': 'BTC-USDC',
           'status': 'FILLED',
           'filled_size': '1.0',
           'limit_price': '100.00',
       }
   ```

2. **Test edge cases**
   ```python
   def test_calculate_price_zero_profit():
       """Test with zero profit target"""
       result = calc.calculate_follow_up_price(order, side, 0.0)
       assert result['price'] == float(order['avg_price'])
   
   def test_calculate_price_zero_initial_price():
       """Test with zero initial price"""
       order = {'order_side': 'BUY', 'avg_price': '0.00'}
       with pytest.raises(ValueError):
           calc.calculate_follow_up_price(order, 'SELL', 0.01)
   ```

3. **Mock external dependencies**
   ```python
   from unittest.mock import Mock, patch
   
   @patch('database.order.update_order')
   def test_record_follow_up_with_db_failure(mock_db):
       mock_db.side_effect = DatabaseError("Connection failed")
       # Test error handling
   ```

4. **Use parametrized tests**
   ```python
   @pytest.mark.parametrize("side,expected_ratio", [
       ('BUY', 1.01),  # Price increases
       ('SELL', 0.99), # Price decreases
   ])
   def test_follow_up_price_by_side(side, expected_ratio):
       result = calc.calculate_follow_up_price(order, side, 0.01)
       assert result == float(order['avg_price']) * expected_ratio
   ```

## 4. Performance Optimization

### Identify Bottlenecks

```python
import time

class PerformanceMonitor:
    def __init__(self):
        self.timings = {}
    
    def measure(self, name):
        def decorator(func):
            def wrapper(*args, **kwargs):
                start = time.time()
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                self.timings.setdefault(name, []).append(elapsed)
                return result
            return wrapper
        return decorator

monitor = PerformanceMonitor()

@monitor.measure('order_calculation')
def process_order(order):
    return calc.calculate_follow_up_price(order, 'SELL', 0.01)

# Analyze: print(monitor.timings)
```

### Caching

```python
from functools import lru_cache

class CachedCalculator:
    @lru_cache(maxsize=1000)
    def get_profit_target(self, product_id: str) -> float:
        """Cache profit targets per product"""
        # Expensive lookup
        return orderbook.profit.get(product_id, 0.01)
```

### Batch Processing

```python
# Instead of processing events one-by-one
for event in events:
    process_user_event(event)

# Process in batches
def process_events_batch(events, batch_size=100):
    for i in range(0, len(events), batch_size):
        batch = events[i:i+batch_size]
        # Process batch atomically
        with orderbook_lock:
            for event in batch:
                process_user_event(event)
```

### Connection Pooling

```python
from connection_pool import DBConnectionPool

class PooledOrderRepository:
    def __init__(self, pool_size=5):
        self.pool = DBConnectionPool(
            connection_string="...",
            pool_size=pool_size
        )
    
    def save_order(self, order):
        with self.pool.get_connection() as conn:
            # Use connection from pool
            conn.execute(insert_query, order)
```

## 5. Error Handling

### Defensive Programming

```python
# Good: Validate inputs
def calculate_follow_up_price(parent_order, side, profit_pct):
    if not isinstance(parent_order, dict):
        raise TypeError("parent_order must be dict")
    
    if side not in ('BUY', 'SELL'):
        raise ValueError(f"Invalid side: {side}")
    
    if profit_pct < 0:
        raise ValueError(f"Profit must be >= 0, got {profit_pct}")
    
    # Proceed with calculation
    return ...
```

### Exception Handling Strategy

```python
# Specific exceptions (better)
try:
    price = bridge.calculate_follow_up_price(order, side, pct)
except ValueError as e:
    logger.error(f"Invalid input: {e}")
    return None
except TypeError as e:
    logger.error(f"Type error: {e}")
    return None

# Avoid broad exception handling
try:
    price = bridge.calculate_follow_up_price(order, side, pct)
except Exception as e:  # Too broad!
    logger.error(f"Error: {e}")
```

### Context Management

```python
# Good: Use context managers
with orderbook_lock:
    try:
        order = orderbook.order[client_order_id]
        # Process order
    except KeyError:
        logger.warning(f"Order {client_order_id} not found")
        return False
    finally:
        # Lock is released automatically
        pass
```

## 6. Thread Safety

### Protected Operations

```python
# Always acquire lock before modifying shared state
with orderbook_lock:
    self.orderbook.order[client_order_id] = updated_order
    self.orderbook.positions['FUTURE'][product_id] = position

# Multiple operations in one critical section
with orderbook_lock:
    parent_entry = self.orderbook.parent_order_ids.get(parent_id)
    if parent_entry:
        parent_entry['current_order_replacement'] += 1
        self.orderbook.parent_order_ids[parent_id] = parent_entry
```

### Avoiding Deadlocks

```python
# Bad: Nested locks (can cause deadlock)
with lock_a:
    with lock_b:
        # Deadlock risk if another thread acquired locks in opposite order
        pass

# Good: Single lock or consistent ordering
with orderbook_lock:
    # All orderbook operations
    pass

with seen_events_lock:
    # All dedup operations
    pass
```

### Thread-Safe Data Structures

```python
from queue import Queue
from threading import Lock
from collections import defaultdict

# Use thread-safe Queue
event_queue = Queue(maxsize=10000)
event = event_queue.get(timeout=1)

# Use Lock for dict operations
order_lock = Lock()
orders = {}

with order_lock:
    orders[order_id] = order_data
```

## 7. Debugging

### Logging Strategy

```python
import logging

logger = logging.getLogger(__name__)

# Different log levels
logger.debug("Detailed information for debugging")
logger.info("General informational message")
logger.warning("Warning condition")
logger.error("Error condition")
logger.critical("Critical condition")
```

### Structured Logging

```python
# Good: Structured logging with context
logger.info("Order processed", extra={
    'order_id': order['order_id'],
    'product_id': order['product_id'],
    'side': order['side'],
    'status': order['status'],
    'filled_size': order.get('filled_size'),
})

# Bad: Unstructured string
logger.info(f"Order {order['order_id']} processed")
```

### Debugging Techniques

```python
# 1. Add checkpoints
def process_order(order):
    logger.debug("Start processing order")
    
    result = validate(order)
    logger.debug(f"Validation result: {result}")
    
    if not result:
        logger.warning("Validation failed, returning")
        return None
    
    calculated = calculate(order)
    logger.debug(f"Calculation result: {calculated}")
    
    logger.debug("Finish processing order")
    return calculated

# 2. Add assertions
def calculate_price(order):
    assert order is not None, "Order cannot be None"
    assert 'avg_price' in order, "Order missing avg_price"
    # Proceed with calculation

# 3. Use pdb for interactive debugging
import pdb; pdb.set_trace()  # Breakpoint
```

## 8. Extension Points

### Adding New Business Logic

```python
# Create in business/ directory
# business/custom_validator.py

from core.models import Order

class CustomValidator:
    """Custom validation logic for orders"""
    
    def validate_position_limits(self, order: dict, position: dict) -> bool:
        """Check if order respects position limits"""
        max_position = 10.0
        new_size = float(order.get('filled_size', 0))
        current_size = float(position.get('net_size', 0))
        
        return (current_size + new_size) <= max_position
    
    def validate_order_frequency(self, product_id: str, orders: list) -> bool:
        """Check if order frequency is within limits"""
        # Implementation
        pass

# Use in OrderEngine
validator = CustomValidator()
if not validator.validate_position_limits(order, position):
    logger.warning("Position limit exceeded")
    return
```

### Adding New Bridges

```python
# Create in integration/ directory
# integration/custom_bridge.py

from business.custom_validator import CustomValidator

class CustomValidatorBridge:
    """Bridge for CustomValidator to OrderEngine"""
    
    def __init__(self):
        self.validator = CustomValidator()
    
    def validate_position_limits(self, order: dict, position: dict) -> bool:
        return self.validator.validate_position_limits(order, position)
    
    def validate_order_frequency(self, product_id: str, orders: list) -> bool:
        return self.validator.validate_order_frequency(product_id, orders)

# Update OrderEngineIntegration to include new bridge
class OrderEngineIntegration:
    def __init__(self, engine):
        # ... existing bridges ...
        self.custom_validator_bridge = CustomValidatorBridge()
    
    def get_custom_validator_bridge(self) -> CustomValidatorBridge:
        return self.custom_validator_bridge
```

### Plugin System (Advanced)

```python
# Register custom business logic
class PluginRegistry:
    def __init__(self):
        self.plugins = {}
    
    def register(self, name: str, plugin):
        """Register a plugin"""
        self.plugins[name] = plugin
    
    def get(self, name: str):
        """Retrieve a plugin"""
        return self.plugins.get(name)

# Usage
registry = PluginRegistry()
registry.register('custom_validator', CustomValidator())

# In OrderEngine
validator = registry.get('custom_validator')
if validator:
    result = validator.validate_position_limits(order, position)
```

## Code Quality Checklist

Before committing code:

- [ ] Code follows PEP 8 style guide
- [ ] All imports are organized (stdlib, third-party, local)
- [ ] Type hints added to function signatures
- [ ] Docstrings added to all classes and public methods
- [ ] Error handling implemented for all edge cases
- [ ] Thread safety verified for shared state
- [ ] Tests written for new functionality
- [ ] Tests pass locally: `pytest tests/ -v`
- [ ] No print statements (use logging instead)
- [ ] No hardcoded values (use constants or configuration)
- [ ] Code reviewed by team member

## Performance Optimization Checklist

Before deploying:

- [ ] Profile code to identify bottlenecks
- [ ] Add caching for expensive operations
- [ ] Use batch processing where applicable
- [ ] Implement connection pooling
- [ ] Minimize lock contention
- [ ] Monitor memory usage
- [ ] Test under load
- [ ] Document performance characteristics

## Documentation Checklist

For each module:

- [ ] Module docstring explains purpose
- [ ] Class docstrings explain responsibility
- [ ] Method docstrings with Args, Returns, Examples
- [ ] Complex logic commented
- [ ] Edge cases documented
- [ ] Thread safety notes added
- [ ] Performance characteristics noted
- [ ] Usage examples provided

---

**Document Version**: 1.0
**Last Updated**: April 2026
**Status**: Phase 4 Complete
