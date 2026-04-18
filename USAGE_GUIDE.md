"""Usage Guide: Coinbase Advanced Trading Engine - Complete API Reference

This guide covers how to use the refactored Coinbase Advanced Trading Engine
with Phase 1-4 modules. It provides practical examples for all major components.

## Quick Start

### Option 1: Original Engine (No Changes Required)
```python
from main import OrderEngine
from configuration import ORDERBOOK, ORDER_POST_ONLY, Subscription, API_KEY, API_SECRET
import database.order as DB_CLIENT

engine = OrderEngine(
    orderbook=ORDERBOOK,
    db_client=DB_CLIENT,
    subscription=Subscription,
    api_key=API_KEY,
    api_secret=API_SECRET,
    order_post_only=ORDER_POST_ONLY,
)
engine.run_forever()
```

### Option 2: Integrated Engine (With Phase 3 Modules)
```python
from main import OrderEngine
from integration.engine_integration import OrderEngineIntegration
from configuration import ORDERBOOK, ORDER_POST_ONLY, Subscription, API_KEY, API_SECRET
import database.order as DB_CLIENT

engine = OrderEngine(...)
integrated = OrderEngineIntegration(engine)
integrated.run_forever()  # Identical to original
```

### Option 3: Use Bridges Independently
```python
from integration.calculator_bridge import CalculatorBridge
from integration.processor_bridge import ProcessorBridge
from integration.event_bridge import EventBridge

calc_bridge = CalculatorBridge()
proc_bridge = ProcessorBridge()
evt_bridge = EventBridge()
```

## Table of Contents

1. Core Modules (Phase 1)
2. Dependency Injection (Phase 2)
3. Business Logic (Phase 3)
4. Integration (Phase 4)
5. Advanced Usage Patterns
6. Testing and Validation
"""

# This is just a marker file. Full documentation will follow in separate files.
