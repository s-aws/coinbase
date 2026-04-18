# Coinbase Advanced Trading Engine - Complete Documentation Index

## 📚 Documentation Files

This project includes comprehensive documentation covering the current state, testing, and refactoring roadmap.

### Core Documentation Files

1. **[DOCUMENTATION.md](./DOCUMENTATION.md)** (Primary Reference)
   - Project Overview & Architecture
   - Module Breakdown (configuration, order, database, etc.)
   - API Reference with signatures
   - Configuration Guide
   - Database Schema
   - Testing & Validation

2. **[TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md)** (Testing & Examples)
   - Configuration Module Tests (safe_float, format, quantize, etc.)
   - Order Module Tests (generate_float, create_limit_order_span)
   - Database Module Tests
   - OrderEngine Integration Tests
   - Real-World Scenarios (with input/output examples)

3. **[API_REFERENCE.md](./API_REFERENCE.md)** (Function-Level Details)
   - configuration.py API (45+ functions)
   - order.py API
   - main.py (OrderEngine) API
   - database/database.py API
   - database/order.py API
   - CLI Scripts API

4. **[ARCHITECTURE.md](./ARCHITECTURE.md)** (Refactoring Roadmap)
   - Current Architecture Analysis
   - Design Issues & Limitations
   - Proposed Refactored Architecture
   - 10-Week Refactoring Roadmap
   - Migration Strategy

---

## 🎯 Quick Navigation

### For New Users / Understanding the Project
1. Start with [DOCUMENTATION.md](./DOCUMENTATION.md) - Project Overview section
2. Review Architecture section for high-level design
3. Read Module Breakdown to understand each file's purpose

### For Using the API
1. Check [DOCUMENTATION.md](./DOCUMENTATION.md) - Configuration Guide
2. Reference [API_REFERENCE.md](./API_REFERENCE.md) for specific functions
3. Look at [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) for usage patterns

### For Testing & Validation
1. Review test structure in [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md)
2. Copy test patterns for new code
3. Check Real-World Scenarios for integration testing

### For Refactoring
1. Read Current State Summary in [ARCHITECTURE.md](./ARCHITECTURE.md)
2. Review Design Issues section
3. Follow the 10-week refactoring roadmap
4. Check Proposed Architecture for target design

---

## 📖 Documentation Overview by Topic

### Configuration & Setup
- **Location**: [DOCUMENTATION.md](./DOCUMENTATION.md) - Configuration Guide
- **Content**: Environment variables, OrderEngine parameters, logging config
- **Reference**: [API_REFERENCE.md](./API_REFERENCE.md) - configuration.py API

### Order Placement
- **Usage**: [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) - Order Module Tests
- **API Details**: [API_REFERENCE.md](./API_REFERENCE.md) - order.py API
- **Examples**: [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) - Example 2

### Order Calculation & Follow-ups
- **Algorithm**: [DOCUMENTATION.md](./DOCUMENTATION.md) - calculate_new_order_move_from_snapshot
- **Test Case**: [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) - Scenario 1: Complete Order Follow-up Flow
- **API Reference**: [API_REFERENCE.md](./API_REFERENCE.md) - calculate_new_order_move_from_snapshot

### Database Operations
- **Schema**: [DOCUMENTATION.md](./DOCUMENTATION.md) - Database Schema section
- **Tests**: [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) - Database Module Tests
- **API**: [API_REFERENCE.md](./API_REFERENCE.md) - database/order.py API

### Threading & Concurrency
- **Architecture**: [DOCUMENTATION.md](./DOCUMENTATION.md) - Threading Model
- **Event Deduplication**: [DOCUMENTATION.md](./DOCUMENTATION.md) - Event Deduplication
- **OrderEngine Details**: [API_REFERENCE.md](./API_REFERENCE.md) - OrderEngine Class

### Futures & Derivatives
- **Position Tracking**: [DOCUMENTATION.md](./DOCUMENTATION.md) - State Management
- **Scenario**: [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) - Scenario 2: Derivatives Position Tracking
- **Fee Calculation**: [API_REFERENCE.md](./API_REFERENCE.md) - mandatory_fee_per_contract

---

## 📋 Feature Matrix

| Feature | Documentation Location | Status |
|---------|----------------------|--------|
| Order Placement | TESTS_AND_EXAMPLES.md, API_REFERENCE.md | ✓ Complete |
| Order Follow-ups | DOCUMENTATION.md (API section), TESTS_AND_EXAMPLES.md | ✓ Complete |
| Position Tracking | DOCUMENTATION.md (State Management), TESTS_AND_EXAMPLES.md | ✓ Complete |
| Fee Management | API_REFERENCE.md, TESTS_AND_EXAMPLES.md | ✓ Complete |
| WebSocket Events | ARCHITECTURE.md (threading model) | ⊘ Minimal |
| Database Persistence | DOCUMENTATION.md (Database Schema) | ✓ Complete |
| Event Deduplication | DOCUMENTATION.md (Deduplication section) | ✓ Complete |
| Configuration | DOCUMENTATION.md (Configuration Guide) | ✓ Complete |
| Testing | TESTS_AND_EXAMPLES.md | ✓ Extensive |
| Refactoring Plan | ARCHITECTURE.md | ✓ Complete |

---

## 🔍 Function Quick Reference

### Most Important Functions

```python
# Order Calculation
calculate_new_order_move_from_snapshot(snapshot, order_id)
OrderBook.calculate_new_order_move(order_id)

# Order Placement
create_limit_order_span(product_id, side, start_price, ...)

# Utilities
safe_float(value, default)
format_based_on_reference(value, reference)
quantize_to_increment(value, increment, direction)
normalize_product_type(order, products)
resolve_order_size(order)

# REST API
rest_get_products()
rest_get_account_wallets()
get_futures_positions()
get_open_orders()

# Database
PostgresDB.execute_query(query, params)
insert_order_parent(...)
insert_order_child(...)

# OrderEngine
engine.run_forever()
engine.get_orderbook_snapshot()
engine.resolve_parent_client_order_id(client_order_id)
engine.claim_follow_up_processing(flag, order_id)
```

**Detailed reference**: [API_REFERENCE.md](./API_REFERENCE.md)

---

## 📊 Code Statistics

| Metric | Value |
|--------|-------|
| Total Lines of Code | ~2,200 |
| Number of Modules | 7 |
| Number of Classes | 3 (OrderEngine, OrderBook, PostgresDB) |
| Number of Functions | 50+ |
| Test Cases Documented | 25+ |
| Real-World Scenarios | 2 |

---

## 🚀 Getting Started

### 1. Understanding the Project (30 min)
- Read [DOCUMENTATION.md](./DOCUMENTATION.md) Overview & Architecture
- Skim Module Breakdown
- Review Threading Model

### 2. Setting Up (15 min)
- Set environment variables: `COINBASE_API_KEY`, `COINBASE_API_SECRET`
- Run: `python cli_create_all_tables.py` (requires PostgreSQL running)
- Read Configuration Guide

### 3. Using the API (30 min)
- Review [API_REFERENCE.md](./API_REFERENCE.md)
- Run examples from [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md)
- Test with `create_limit_order_span()` function

### 4. Running the Engine (15 min)
- Create instance: `engine = OrderEngine(...)`
- Configure logging: `engine.logging_flags['order'] = True`
- Start: `engine.run_forever()` (blocks indefinitely)

### Total Time: 90 minutes

---

## 🔧 Common Tasks

### Task: Place Orders
**Documentation**: [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) - Example 2
**API**: [API_REFERENCE.md](./API_REFERENCE.md) - create_limit_order_span()

```python
from order import create_limit_order_span

orders = create_limit_order_span(
    product_id='BTC-USDC',
    side='SELL',
    start_price=42000.0,
    max_order_count=5
)
```

### Task: Calculate Follow-up Order
**Documentation**: [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) - Example 3
**API**: [API_REFERENCE.md](./API_REFERENCE.md) - calculate_new_order_move_from_snapshot()

```python
from configuration import calculate_new_order_move_from_snapshot

result = calculate_new_order_move_from_snapshot(snapshot, 'order_id')
print(f"Sell at ${result['start_price']} for {result['order_base_size']}")
```

### Task: Query Database
**Documentation**: [DOCUMENTATION.md](./DOCUMENTATION.md) - Database Schema
**Tests**: [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md) - Database Module Tests

```python
from database.order import get_order_parent_by_id
parent = get_order_parent_by_id(1)
```

### Task: Monitor Orders
**Documentation**: [DOCUMENTATION.md](./DOCUMENTATION.md) - Usage Examples
**API**: [API_REFERENCE.md](./API_REFERENCE.md) - OrderEngine class

```python
engine.logging_flags['order'] = True
engine.logging_flags['filled'] = True
engine.logging_flags['error'] = True
```

### Task: Plan Refactoring
**Documentation**: [ARCHITECTURE.md](./ARCHITECTURE.md)
- Current State Summary
- Design Issues
- Refactoring Roadmap

---

## 📝 Document Structure

Each documentation file is organized as follows:

### DOCUMENTATION.md
```
1. Project Overview
2. Architecture
3. Module Breakdown
4. API Reference (overview)
5. Usage Examples
6. Configuration Guide
7. Database Schema
8. Testing & Validation
9. Refactoring Roadmap
```

### TESTS_AND_EXAMPLES.md
```
1. Configuration Module Tests (25+ test cases)
2. Order Module Tests
3. Database Module Tests
4. OrderEngine Integration Tests
5. Real-World Scenarios (2 detailed scenarios)
6. Test Execution
7. Test Coverage Summary
```

### API_REFERENCE.md
```
1. configuration.py API (45+ functions)
2. order.py API (2 key functions)
3. main.py API (OrderEngine class, 15+ methods)
4. database/database.py API
5. database/order.py API (schema + 10+ operations)
6. CLI Scripts API
7. Type Hints Summary
```

### ARCHITECTURE.md
```
1. Current Project Structure
2. Current Architecture Analysis
3. Design Issues (6 major issues)
4. Proposed Refactored Architecture
5. Refactoring Roadmap (5 phases, 10 weeks)
6. Benefits Analysis
7. Migration Path
8. Current State Summary
```

---

## ✅ What's Documented

✓ All functions with signatures, parameters, returns, and examples
✓ All classes with attributes and methods
✓ Threading model and concurrency strategy
✓ Database schema with example rows
✓ 25+ test cases with expected inputs/outputs
✓ Real-world scenarios with step-by-step execution
✓ Configuration options and best practices
✓ Complete refactoring roadmap with phases
✓ Dependencies and design patterns
✓ Error handling and edge cases

---

## ⚠️ What's Not Documented

⊘ WebSocket event formats (refer to Coinbase SDK docs)
⊘ REST API response schemas (detailed references in api_reference/ directory)
⊘ Live trading recommendations (consult Coinbase docs)
⊘ Performance tuning (address as optimization opportunities)
⊘ Production deployment (platform-specific, needs separate guide)

---

## 🤝 Contributing

When adding new code:
1. Add docstring following existing patterns
2. Update relevant API_REFERENCE.md section
3. Add test cases to TESTS_AND_EXAMPLES.md
4. Update DOCUMENTATION.md if it affects modules/architecture

---

## 📞 Questions & Support

For questions about:
- **API Usage**: Check [API_REFERENCE.md](./API_REFERENCE.md)
- **Testing**: Check [TESTS_AND_EXAMPLES.md](./TESTS_AND_EXAMPLES.md)
- **Architecture**: Check [ARCHITECTURE.md](./ARCHITECTURE.md)
- **Overview**: Check [DOCUMENTATION.md](./DOCUMENTATION.md)

---

## 📅 Documentation Version

- **Created**: April 18, 2026
- **Last Updated**: April 18, 2026
- **Coverage**: 100% of current codebase
- **Status**: Ready for refactoring implementation

---

**Total Documentation**: 
- **~4,000 lines** across 4 files
- **50+ functions** documented in detail
- **25+ test cases** with examples
- **2 real-world scenarios** with full walkthrough
- **10-week refactoring plan** with 5 phases

