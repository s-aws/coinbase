#!/usr/bin/env python3
"""
Phase 4: Repricing loop performance profiler.

Profiles process_anchor_repricing_for_product() to identify bottlenecks:
- State dict parsing overhead
- Market cache lookups
- Enum comparisons
- Reprice history filtering
- Policy normalization

Usage:
    python genai_tools/profile_repricing_loop.py
"""

import sys
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any
import cProfile
import pstats
from io import StringIO
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.stealth_order_manager import StealthOrderManager
from core.enums import StealthOrderStatus


def create_test_orders(count: int = 1000) -> Dict[str, Any]:
    """Create test stealth orders for benchmarking."""
    orders = {}
    for i in range(count):
        order_id = str(uuid.uuid4())
        orders[order_id] = {
            "stealth_order_id": order_id,
            "product_id": "BTC-USD",
            "side": "BUY",
            "total_size": 0.5 + (i % 10) * 0.01,
            "remaining_size": 0.5 + (i % 10) * 0.01,
            "limit_price": 40000.0 + (i % 100),
            "status": [
                StealthOrderStatus.HIDDEN.value,
                StealthOrderStatus.PENDING.value,
                StealthOrderStatus.TRIGGERED.value,
                StealthOrderStatus.REVEALED.value,
            ][i % 4],
            "created_at": datetime.utcnow() - timedelta(hours=i % 24),
            "updated_at": datetime.utcnow(),
            "anchor_repricing_policy_json": {
                "enabled": i % 2 == 0,  # 50% have repricing
                "reference_price_source": ["last_trade", "midpoint", "top_of_book"][i % 3],
                "distance_type": "A",
                "target_distance": 10.0 + (i % 5),
                "max_distance": 20.0 + (i % 5),
                "min_price_change": 0.01,
                "hysteresis_bps": 5.0,
                "min_reprice_interval_seconds": 30,
                "max_reprices_per_hour": 20,
                "post_only_required": True,
                "volatility_sensitivity": 1.0,
                "max_reprice_window_seconds": 600,
                "require_minimum_volume": 0.0,
                "enable_spread_monitoring": False,
            },
            "anchor_repricing_state_json": {
                "reprice_history": [
                    (datetime.utcnow() - timedelta(seconds=j*300)).isoformat()
                    for j in range(i % 5)
                ],
            },
            "revealed_orders": [],
        }
    return orders


def benchmark_repricing_loop(order_count: int = 1000, iterations: int = 5):
    """Benchmark the repricing loop with specified order count."""
    print(f"\n📊 Repricing Loop Benchmarking")
    print(f"   Orders: {order_count:,} | Iterations: {iterations}")
    print(f"   Target: process_anchor_repricing_for_product()")
    print()

    # Create manager with test orders
    manager = StealthOrderManager(db_client=None, log_callback=lambda *args, **kw: None)
    manager._save_stealth_order_to_db = lambda *args, **kw: None
    manager._update_stealth_order = lambda *args, **kw: None

    test_orders = create_test_orders(order_count)
    manager.in_memory_orders.update(test_orders)

    # Set market cache with ticker data
    manager._market_cache["BTC-USD"] = {
        "bid": 40000.0,
        "ask": 40100.0,
        "price": 40050.0,
        "source": "ticker",
        "volume_1m": 500.0,
    }

    # Warm-up run (not counted)
    manager.process_anchor_repricing_for_product("BTC-USD")

    # Benchmark multiple iterations
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        processed = manager.process_anchor_repricing_for_product("BTC-USD")
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  Iteration {i+1}: {elapsed*1000:.2f}ms ({processed} reprices)")

    # Calculate statistics
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    total_time = sum(times)

    # Calculate rates
    orders_per_sec = order_count / avg_time
    ns_per_order = (avg_time * 1e9) / order_count

    print()
    print(f"  ⏱️  Average time: {avg_time*1000:.2f}ms")
    print(f"     Min: {min_time*1000:.2f}ms, Max: {max_time*1000:.2f}ms")
    print(f"     Total ({iterations}x): {total_time*1000:.2f}ms")
    print()
    print(f"  📈 Throughput: {orders_per_sec:,.0f} orders/sec")
    print(f"     Latency per order: {ns_per_order:.1f}ns")
    print(f"     For 10k orders: {(10000 / orders_per_sec)*1000:.0f}ms")
    print()

    return {
        "order_count": order_count,
        "iterations": iterations,
        "avg_time_ms": avg_time * 1000,
        "min_time_ms": min_time * 1000,
        "max_time_ms": max_time * 1000,
        "orders_per_sec": orders_per_sec,
        "ns_per_order": ns_per_order,
    }


def profile_repricing_loop(order_count: int = 1000):
    """Profile the repricing loop using cProfile."""
    print(f"\n🔍 Repricing Loop CPU Profile")
    print(f"   Orders: {order_count:,}")
    print()

    # Create manager with test orders
    manager = StealthOrderManager(db_client=None, log_callback=lambda *args, **kw: None)
    manager._save_stealth_order_to_db = lambda *args, **kw: None
    manager._update_stealth_order = lambda *args, **kw: None

    test_orders = create_test_orders(order_count)
    manager.in_memory_orders.update(test_orders)

    # Set market cache
    manager._market_cache["BTC-USD"] = {
        "bid": 40000.0,
        "ask": 40100.0,
        "price": 40050.0,
        "source": "ticker",
        "volume_1m": 500.0,
    }

    # Profile the repricing loop
    profiler = cProfile.Profile()
    profiler.enable()

    processed = manager.process_anchor_repricing_for_product("BTC-USD")

    profiler.disable()

    # Print statistics
    s = StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    ps.print_stats(15)  # Top 15 functions

    print(s.getvalue())
    print(f"  Total reprices processed: {processed}")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("REPRICING LOOP PERFORMANCE ANALYSIS")
    print("=" * 60)

    # Benchmark with different order counts
    results = []

    for order_count in [100, 500, 1000]:
        result = benchmark_repricing_loop(order_count=order_count, iterations=3)
        results.append(result)

    # Profiling on 1000 orders
    profile_repricing_loop(order_count=1000)

    # Summary table
    print("=" * 60)
    print("SUMMARY TABLE")
    print("=" * 60)
    print(f"{'Orders':<10} {'Avg (ms)':<12} {'Throughput':<15} {'Per-Order':<12}")
    print("-" * 60)
    for r in results:
        print(f"{r['order_count']:<10} {r['avg_time_ms']:<12.2f} {r['orders_per_sec']:<15,.0f} {r['ns_per_order']:<12.1f}ns")
    print()

    # Recommendations
    print("=" * 60)
    print("OPTIMIZATION RECOMMENDATIONS")
    print("=" * 60)
    print("""
1. If throughput < 5,000 orders/sec, profile shows bottlenecks in:
   - _normalize_anchor_repricing_policy() - dict copies for every order
   - _should_skip_anchor_reprice() - reprice_history filtering
   - State dict lookups - use caching for frequently accessed fields

2. Consider optimizations:
   - Cache normalized policies (they don't change frequently)
   - Use array-based reprice_history instead of list of ISO strings
   - Pre-compile enum comparisons to avoid string conversions
   - Batch market data updates instead of per-order lookups

3. For 10,000+ orders, consider:
   - Parallel repricing loops by product_id
   - Async market data fetching
   - In-memory indexes for status-based filtering
    """)
    print()
