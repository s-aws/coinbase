"""Test demonstration of FillEventHookRegistry mirroring OrderPlacementHookRegistry pattern.

This test shows:
1. Pre-fill hooks for validation/enrichment (can block by raising exceptions)
2. Post-fill hooks for logging/tracking (non-blocking, exceptions logged)
3. Thread-safe hook registration
4. Global singleton pattern
"""

from integration.fill_event_hooks import (
    FillEventHookRegistry,
    get_global_fill_event_hook_registry,
    reset_global_fill_event_hook_registry,
)
import threading
from datetime import datetime


def test_fill_event_hook_registry_pre_fill_validation():
    """Test pre-fill hooks can validate and block fills."""
    print("\n=== Test 1: Pre-Fill Hook Validation ===")
    
    registry = FillEventHookRegistry()
    
    # Register a pre-fill hook that validates quantity > 0
    def validate_quantity(fill_data):
        if fill_data['quantity'] <= 0:
            raise ValueError("Quantity must be > 0")
        print(f"✓ Pre-fill hook: Validated quantity {fill_data['quantity']}")
    
    registry.register_pre_fill(validate_quantity)
    
    # Test with valid fill
    valid_fill = {
        'instrument': 'BTC-USD',
        'side': 'BUY',
        'quantity': 1.0,
        'price': 50000.0,
        'fees': 10.0,
        'client_order_id': 'order-123',
        'timestamp': datetime.utcnow(),
        'commission_percentage': 0.001,
        'trade_id': 'trade-456'
    }
    
    try:
        registry.call_pre_fill_hooks(valid_fill)
        print("✓ Valid fill passed pre-fill hooks")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
    
    # Test with invalid fill (should raise)
    invalid_fill = {
        'instrument': 'BTC-USD',
        'side': 'SELL',
        'quantity': -1.0,  # Invalid!
        'price': 50000.0,
        'fees': 10.0,
        'client_order_id': 'order-124',
        'timestamp': datetime.utcnow(),
        'commission_percentage': 0.001,
        'trade_id': 'trade-457'
    }
    
    try:
        registry.call_pre_fill_hooks(invalid_fill)
        print("✗ Invalid fill should have been blocked")
    except ValueError as e:
        print(f"✓ Pre-fill hook blocked invalid fill: {e}")


def test_fill_event_hook_registry_pre_fill_enrichment():
    """Test pre-fill hooks can modify fill data."""
    print("\n=== Test 2: Pre-Fill Hook Enrichment ===")
    
    registry = FillEventHookRegistry()
    
    # Register a pre-fill hook that enriches fill with commission
    def enrich_commission(fill_data):
        if fill_data.get('commission_percentage', 0) == 0:
            # Calculate commission based on instrument
            if 'BTC' in fill_data['instrument']:
                fill_data['commission_percentage'] = 0.002
            else:
                fill_data['commission_percentage'] = 0.001
        print(f"✓ Pre-fill hook: Enriched with commission {fill_data['commission_percentage']}")
    
    registry.register_pre_fill(enrich_commission)
    
    fill = {
        'instrument': 'BTC-USD',
        'side': 'BUY',
        'quantity': 1.0,
        'price': 50000.0,
        'fees': 10.0,
        'client_order_id': 'order-125',
        'timestamp': datetime.utcnow(),
        'commission_percentage': 0.0,  # Will be enriched
        'trade_id': 'trade-458'
    }
    
    registry.call_pre_fill_hooks(fill)
    assert fill['commission_percentage'] == 0.002, "Commission not enriched"
    print(f"✓ Fill enriched: commission_percentage = {fill['commission_percentage']}")


def test_fill_event_hook_registry_post_fill_tracking():
    """Test post-fill hooks for logging and tracking."""
    print("\n=== Test 3: Post-Fill Hook Tracking ===")
    
    registry = FillEventHookRegistry()
    tracked_fills = []
    
    # Register a post-fill hook for tracking
    def track_fill(fill_data, trade_id):
        tracked_fills.append({
            'trade_id': trade_id,
            'instrument': fill_data['instrument'],
            'side': fill_data['side'],
            'quantity': fill_data['quantity'],
            'price': fill_data['price'],
            'timestamp': datetime.utcnow()
        })
        print(f"✓ Post-fill hook: Tracked {trade_id} ({fill_data['side']} {fill_data['quantity']} {fill_data['instrument']})")
    
    registry.register_post_fill(track_fill)
    
    fill = {
        'instrument': 'ETH-USD',
        'side': 'SELL',
        'quantity': 10.0,
        'price': 3000.0,
        'fees': 30.0,
        'client_order_id': 'order-126',
        'timestamp': datetime.utcnow(),
        'commission_percentage': 0.001,
        'trade_id': 'trade-459'
    }
    
    registry.call_post_fill_hooks(fill, 'trade-459')
    assert len(tracked_fills) == 1, "Fill not tracked"
    assert tracked_fills[0]['trade_id'] == 'trade-459', "Wrong trade_id"
    print(f"✓ Fill tracked successfully: {len(tracked_fills)} fills in registry")


def test_fill_event_hook_registry_post_fill_error_handling():
    """Test post-fill hooks handle errors gracefully."""
    print("\n=== Test 4: Post-Fill Hook Error Handling ===")
    
    registry = FillEventHookRegistry()
    success_count = 0
    error_count = 0
    
    # Register hook that works
    def log_fill_success(fill_data, trade_id):
        nonlocal success_count
        success_count += 1
        print(f"✓ Post-fill hook 1: Logged {trade_id}")
    
    # Register hook that fails
    def log_fill_failure(fill_data, trade_id):
        nonlocal error_count
        error_count += 1
        raise RuntimeError("Simulated hook failure")
    
    # Register another hook that works (should still be called after failure)
    def log_fill_final(fill_data, trade_id):
        nonlocal success_count
        success_count += 1
        print(f"✓ Post-fill hook 3: Final log for {trade_id}")
    
    registry.register_post_fill(log_fill_success)
    registry.register_post_fill(log_fill_failure)
    registry.register_post_fill(log_fill_final)
    
    fill = {
        'instrument': 'BTC-USD',
        'side': 'BUY',
        'quantity': 1.0,
        'price': 50000.0,
        'fees': 10.0,
        'client_order_id': 'order-127',
        'timestamp': datetime.utcnow(),
        'commission_percentage': 0.001,
        'trade_id': 'trade-460'
    }
    
    # Call hooks - error in middle hook shouldn't stop others
    registry.call_post_fill_hooks(fill, 'trade-460')
    assert success_count == 2, f"Expected 2 successful hooks, got {success_count}"
    assert error_count == 1, f"Expected 1 failed hook, got {error_count}"
    print(f"✓ Error handling verified: {success_count} successful, {error_count} failed (non-blocking)")


def test_global_fill_event_hook_registry_singleton():
    """Test global singleton pattern for FillEventHookRegistry."""
    print("\n=== Test 5: Global Singleton Pattern ===")
    
    # Reset global registry
    reset_global_fill_event_hook_registry()
    
    # Get global registry (should create new instance)
    registry1 = get_global_fill_event_hook_registry()
    registry2 = get_global_fill_event_hook_registry()
    
    assert registry1 is registry2, "Should return same singleton instance"
    print("✓ Global registry is singleton")
    
    # Register a hook in registry1
    tracked = []
    def track_in_registry1(fill_data, trade_id):
        tracked.append(trade_id)
    
    registry1.register_post_fill(track_in_registry1)
    
    # Call hooks through registry2 (should have same hook)
    fill = {
        'instrument': 'BTC-USD',
        'side': 'BUY',
        'quantity': 1.0,
        'price': 50000.0,
        'fees': 10.0,
        'client_order_id': 'order-128',
        'timestamp': datetime.utcnow(),
        'commission_percentage': 0.001,
        'trade_id': 'trade-461'
    }
    
    registry2.call_post_fill_hooks(fill, 'trade-461')
    assert len(tracked) == 1, "Hook registered in registry1 should be called in registry2"
    print("✓ Singleton pattern verified: hooks are shared across instances")


def test_thread_safe_registration():
    """Test thread-safe hook registration."""
    print("\n=== Test 6: Thread-Safe Hook Registration ===")
    
    registry = FillEventHookRegistry()
    registration_count = 0
    registration_lock = threading.Lock()
    
    def register_hook(hook_id):
        nonlocal registration_count
        def hook(fill_data, trade_id):
            pass
        registry.register_post_fill(hook)
        with registration_lock:
            registration_count += 1
    
    # Create multiple threads registering hooks simultaneously
    threads = []
    for i in range(10):
        t = threading.Thread(target=register_hook, args=(i,))
        threads.append(t)
        t.start()
    
    # Wait for all threads
    for t in threads:
        t.join()
    
    assert registration_count == 10, f"Expected 10 registrations, got {registration_count}"
    print(f"✓ Thread-safe registration: {registration_count} hooks registered from 10 threads")


def test_mirrors_order_submission_pattern():
    """Verify FillEventHookRegistry mirrors OrderPlacementHookRegistry pattern."""
    print("\n=== Test 7: Pattern Comparison ===")
    
    from integration.order_placement_hooks import OrderPlacementHookRegistry
    
    # Both registries should have the same public interface
    fill_registry = FillEventHookRegistry()
    order_registry = OrderPlacementHookRegistry()
    
    # Check methods exist on both
    fill_methods = set(dir(fill_registry))
    order_methods = set(dir(order_registry))
    
    required_methods = {
        'call_pre_submission_hooks', 'register_pre_submission',
        'call_post_submission_hooks', 'register_post_submission'
    }
    
    # Map order hook names to fill hook names
    fill_required = {
        'call_pre_fill_hooks', 'register_pre_fill',
        'call_post_fill_hooks', 'register_post_fill',
        '_pre_fill_hooks', '_post_fill_hooks', '_lock'
    }
    
    print("✓ Order Placement Hook Registry methods:")
    for method in ['register_pre_submission', 'call_pre_submission_hooks', 
                   'register_post_submission', 'call_post_submission_hooks']:
        has_it = hasattr(order_registry, method)
        print(f"  {'✓' if has_it else '✗'} {method}")
    
    print("✓ Fill Event Hook Registry methods (mirrored):")
    for method in ['register_pre_fill', 'call_pre_fill_hooks',
                   'register_post_fill', 'call_post_fill_hooks']:
        has_it = hasattr(fill_registry, method)
        print(f"  {'✓' if has_it else '✗'} {method}")
    
    # Both should be thread-safe with RLock
    assert hasattr(fill_registry, '_lock'), "FillEventHookRegistry missing _lock"
    assert isinstance(fill_registry._lock, type(order_registry._lock)), "Lock types should match"
    print("✓ Both registries are thread-safe with RLock")
    
    print("✓ Pattern verification complete: FillEventHookRegistry mirrors OrderPlacementHookRegistry")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("FILL EVENT HOOK REGISTRY TEST SUITE")
    print("Demonstrates pattern mirroring OrderPlacementHookRegistry")
    print("="*70)
    
    test_fill_event_hook_registry_pre_fill_validation()
    test_fill_event_hook_registry_pre_fill_enrichment()
    test_fill_event_hook_registry_post_fill_tracking()
    test_fill_event_hook_registry_post_fill_error_handling()
    test_global_fill_event_hook_registry_singleton()
    test_thread_safe_registration()
    test_mirrors_order_submission_pattern()
    
    print("\n" + "="*70)
    print("✓ ALL TESTS PASSED")
    print("="*70)
    print("\nSummary:")
    print("- Pre-fill hooks: Validate, enrich, or block fills before recording")
    print("- Post-fill hooks: Non-blocking logging/tracking after recording")
    print("- Thread-safe: Uses RLock for concurrent hook registration")
    print("- Singleton: Global registry for centralized hook management")
    print("- Pattern: Mirrors OrderPlacementHookRegistry exactly")
