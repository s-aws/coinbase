"""Test WebSocket Hook System.

Quick validation that the hook registry system works correctly.
Run with: pytest genai_tools/test_websocket_hooks.py -v
or: python -m pytest genai_tools/test_websocket_hooks.py -v
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from integration.websocket_hooks import WebSocketHookRegistry, get_global_hook_registry

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_hook_registry():
    """Test basic hook registration and execution."""
    print("\n" + "="*70)
    print("TEST 1: Hook Registry Creation and Registration")
    print("="*70)

    registry = WebSocketHookRegistry()
    assert registry is not None
    assert registry.get_hook_count() == 0
    print("✓ Hook registry created successfully")

    # Register some test hooks
    call_log = []

    def pre_hook(order):
        call_log.append(('pre', order.get('client_order_id')))
        print(f"  PRE-hook called for {order.get('client_order_id')}")

    def post_hook(order):
        call_log.append(('post', order.get('client_order_id')))
        print(f"  POST-hook called for {order.get('client_order_id')}")

    registry.register_pre_order_status('FILLED', pre_hook)
    registry.register_post_order_status('FILLED', post_hook)

    assert registry.get_hook_count('FILLED') == 2
    print(f"✓ Registered 2 hooks for FILLED status")

    # Call hooks
    test_order = {
        'client_order_id': 'test-123',
        'status': 'FILLED',
        'cumulative_quantity': '1.0',
    }

    print("\nCalling pre-hook...")
    registry.call_pre_order_status('FILLED', test_order)

    print("Calling post-hook...")
    registry.call_post_order_status('FILLED', test_order)

    assert len(call_log) == 2
    assert call_log[0] == ('pre', 'test-123')
    assert call_log[1] == ('post', 'test-123')
    print(f"✓ Both hooks were called in correct order")


def test_multiple_hooks():
    """Test multiple hooks for same status."""
    print("\n" + "="*70)
    print("TEST 2: Multiple Hooks for Same Status")
    print("="*70)

    registry = WebSocketHookRegistry()
    execution_order = []

    def hook_a(order):
        execution_order.append('A')
        print("  Hook A executed")

    def hook_b(order):
        execution_order.append('B')
        print("  Hook B executed")

    def hook_c(order):
        execution_order.append('C')
        print("  Hook C executed")

    registry.register_post_order_status('OPEN', hook_a)
    registry.register_post_order_status('OPEN', hook_b)
    registry.register_post_order_status('OPEN', hook_c)

    test_order = {'client_order_id': 'test-multi', 'status': 'OPEN'}
    registry.call_post_order_status('OPEN', test_order)

    assert execution_order == ['A', 'B', 'C']
    print("✓ Multiple hooks executed in registration order")


def test_snapshot_hooks():
    """Test snapshot (position) hooks."""
    print("\n" + "="*70)
    print("TEST 3: Snapshot Hooks")
    print("="*70)

    registry = WebSocketHookRegistry()
    snapshot_calls = []

    def pre_snapshot(snapshot):
        snapshot_calls.append(('pre', len(snapshot.get('positions', {}))))
        print(f"  PRE-snapshot hook called")

    def post_snapshot(snapshot):
        snapshot_calls.append(('post', len(snapshot.get('positions', {}))))
        print(f"  POST-snapshot hook called")

    registry.register_pre_snapshot(pre_snapshot)
    registry.register_post_snapshot(post_snapshot)

    test_snapshot = {
        'type': 'snapshot',
        'positions': {
            'perpetual_futures_positions': [
                {'product_id': 'BTC-PERP', 'net_size': '1.5'},
            ]
        }
    }

    print("\nCalling snapshot hooks...")
    registry.call_pre_snapshot(test_snapshot)
    registry.call_post_snapshot(test_snapshot)

    assert len(snapshot_calls) == 2
    assert snapshot_calls[0][0] == 'pre'
    assert snapshot_calls[1][0] == 'post'
    print("✓ Snapshot hooks executed correctly")


def test_error_handling():
    """Test that exceptions in hooks don't break execution."""
    print("\n" + "="*70)
    print("TEST 4: Error Handling")
    print("="*70)

    registry = WebSocketHookRegistry()
    safe_calls = []

    def failing_hook(order):
        print("  Failing hook: raising exception...")
        raise RuntimeError("Intentional test error")

    def safe_hook(order):
        safe_calls.append('success')
        print("  Safe hook: executed successfully")

    registry.register_post_order_status('FILLED', failing_hook)
    registry.register_post_order_status('FILLED', safe_hook)

    test_order = {'client_order_id': 'test-error', 'status': 'FILLED'}

    print("\nCalling hooks (one will fail)...")
    registry.call_post_order_status('FILLED', test_order)

    # The exception should be logged but safe_hook should still run
    assert len(safe_calls) == 1
    print("✓ Exception in hook was handled, other hooks still ran")


def test_hook_unregistration():
    """Test unregistering hooks."""
    print("\n" + "="*70)
    print("TEST 5: Hook Unregistration")
    print("="*70)

    registry = WebSocketHookRegistry()

    def test_hook(order):
        pass

    registry.register_pre_order_status('CANCELLED', test_hook)
    assert registry.get_hook_count('CANCELLED') == 1
    print("✓ Hook registered")

    registry.unregister_pre_order_status('CANCELLED', test_hook)
    assert registry.get_hook_count('CANCELLED') == 0
    print("✓ Hook unregistered successfully")


def test_global_registry():
    """Test the global hook registry singleton."""
    print("\n" + "="*70)
    print("TEST 6: Global Hook Registry Singleton")
    print("="*70)

    global_hooks = get_global_hook_registry()
    assert global_hooks is not None
    print("✓ Global registry obtained")

    # Get it again - should be same instance
    global_hooks_2 = get_global_hook_registry()
    assert global_hooks is global_hooks_2
    print("✓ Same instance returned on subsequent calls (singleton)")


def test_clear_all():
    """Test clearing all hooks."""
    print("\n" + "="*70)
    print("TEST 7: Clear All Hooks")
    print("="*70)

    registry = WebSocketHookRegistry()

    def hook1(order): pass
    def hook2(order): pass
    def hook3(snapshot): pass

    registry.register_pre_order_status('FILLED', hook1)
    registry.register_post_order_status('CANCELLED', hook2)
    registry.register_pre_snapshot(hook3)

    assert registry.get_hook_count() == 3
    print(f"✓ Registered 3 hooks total")

    registry.clear_all()
    assert registry.get_hook_count() == 0
    print("✓ All hooks cleared successfully")


def test_different_statuses():
    """Test hooks for different order statuses."""
    print("\n" + "="*70)
    print("TEST 8: Different Order Statuses")
    print("="*70)

    registry = WebSocketHookRegistry()
    called_statuses = []

    def make_hook(status_name):
        def hook(order):
            called_statuses.append(status_name)
        return hook

    # Register hooks for multiple statuses
    for status in ['OPEN', 'FILLED', 'CANCELLED', 'PENDING']:
        registry.register_post_order_status(status, make_hook(status))

    print("Calling hooks for different statuses...")
    for status in ['OPEN', 'FILLED', 'CANCELLED', 'PENDING']:
        test_order = {'client_order_id': f'test-{status}', 'status': status}
        registry.call_post_order_status(status, test_order)
        print(f"  Called hook for {status}")

    assert called_statuses == ['OPEN', 'FILLED', 'CANCELLED', 'PENDING']
    print("✓ All status-specific hooks executed correctly")


def test_order_normalizers():
    """Test order normalization."""
    print("\n" + "="*70)
    print("TEST 9: Order Normalizers")
    print("="*70)

    registry = WebSocketHookRegistry()

    def normalize_spot_order(order):
        """Add computed field for spot orders."""
        if 'limit_price' in order:
            order['_normalized_price'] = float(order.get('limit_price', 0))
        print("  Spot normalizer executed")

    def normalize_futures_order(order):
        """Add computed field for futures orders."""
        if 'contract_expiry_type' in order:
            order['_is_expiring'] = order['contract_expiry_type'] == 'EXPIRING'
        print("  Futures normalizer executed")

    registry.register_order_normalizer(normalize_spot_order)
    registry.register_order_normalizer(normalize_futures_order)

    print("\nNormalizing spot order...")
    spot_order = {
        'client_order_id': 'spot-123',
        'limit_price': '50000.50',
    }
    registry.call_order_normalizers(spot_order)
    assert spot_order.get('_normalized_price') == 50000.50
    print("✓ Spot order normalized correctly")

    print("\nNormalizing futures order...")
    futures_order = {
        'client_order_id': 'futures-456',
        'contract_expiry_type': 'EXPIRING',
    }
    registry.call_order_normalizers(futures_order)
    assert futures_order.get('_is_expiring') == True
    print("✓ Futures order normalized correctly")


def test_snapshot_normalizers():
    """Test snapshot normalization."""
    print("\n" + "="*70)
    print("TEST 10: Snapshot Normalizers")
    print("="*70)

    registry = WebSocketHookRegistry()

    def compute_position_notional(snapshot):
        """Add notional value to positions."""
        perpetual_positions = snapshot.get('positions', {}).get('perpetual_futures_positions', [])
        for pos in perpetual_positions:
            net_size = float(pos.get('net_size', 0))
            mark_price = float(pos.get('mark_price', 0))
            pos['_notional_value'] = net_size * mark_price
        print("  Position notional computed")

    registry.register_snapshot_normalizer(compute_position_notional)

    test_snapshot = {
        'type': 'snapshot',
        'positions': {
            'perpetual_futures_positions': [
                {
                    'product_id': 'BTC-PERP',
                    'net_size': '2.5',
                    'mark_price': '50000',
                }
            ]
        }
    }

    print("\nNormalizing snapshot...")
    registry.call_snapshot_normalizers(test_snapshot)

    pos = test_snapshot['positions']['perpetual_futures_positions'][0]
    assert pos['_notional_value'] == 125000.0
    print("✓ Snapshot normalized correctly (notional = 2.5 * 50000 = 125000)")


def test_normalizer_error_handling():
    """Test that exceptions in normalizers don't break execution."""
    print("\n" + "="*70)
    print("TEST 11: Normalizer Error Handling")
    print("="*70)

    registry = WebSocketHookRegistry()
    called = []

    def failing_normalizer(order):
        print("  Failing normalizer: raising exception...")
        raise RuntimeError("Intentional test error")

    def safe_normalizer(order):
        called.append('success')
        print("  Safe normalizer executed successfully")

    registry.register_order_normalizer(failing_normalizer)
    registry.register_order_normalizer(safe_normalizer)

    test_order = {'client_order_id': 'test', 'status': 'OPEN'}

    print("\nCalling normalizers (one will fail)...")
    registry.call_order_normalizers(test_order)

    assert len(called) == 1
    print("✓ Exception handled, subsequent normalizer still ran")


def test_normalizer_unregistration():
    """Test unregistering normalizers."""
    print("\n" + "="*70)
    print("TEST 12: Normalizer Unregistration")
    print("="*70)

    registry = WebSocketHookRegistry()

    def test_normalizer(order):
        pass

    registry.register_order_normalizer(test_normalizer)
    assert registry.get_hook_count() >= 1
    print("✓ Normalizer registered")

    registry.unregister_order_normalizer(test_normalizer)
    print("✓ Normalizer unregistered successfully")


def test_complete_flow_with_normalizers():
    """Test complete flow: PRE-hook → Normalizer → POST-hook."""
    print("\n" + "="*70)
    print("TEST 13: Complete Flow (PRE → Normalize → POST)")
    print("="*70)

    registry = WebSocketHookRegistry()
    execution_log = []

    def pre_hook(order):
        execution_log.append(('pre', 'raw_fields' in order))
        print("  1. PRE-hook: sees raw fields")

    def normalizer(order):
        # Simulate normalizing a Coinbase field variation
        if 'limit_price' in order and 'start_price' not in order:
            order['start_price'] = float(order['limit_price'])
        execution_log.append(('normalizer', 'start_price' in order))
        print("  2. Normalizer: added start_price field")

    def post_hook(order):
        execution_log.append(('post', 'start_price' in order))
        print("  3. POST-hook: sees normalized fields")

    registry.register_pre_order_status('OPEN', pre_hook)
    registry.register_order_normalizer(normalizer)
    registry.register_post_order_status('OPEN', post_hook)

    test_order = {
        'client_order_id': 'test-flow',
        'status': 'OPEN',
        'raw_fields': True,
        'limit_price': '50000',
    }

    print("\nExecuting flow...")
    registry.call_pre_order_status('OPEN', test_order)
    registry.call_order_normalizers(test_order)
    registry.call_post_order_status('OPEN', test_order)

    # Verify execution order and state
    assert execution_log[0] == ('pre', True), "PRE hook should see raw_fields"
    assert execution_log[1] == ('normalizer', True), "Normalizer should add start_price"
    assert execution_log[2] == ('post', True), "POST hook should see normalized start_price"

    print("✓ Complete flow executed in correct order")


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print("WEBSOCKET HOOK SYSTEM TEST SUITE")
    print("="*70)

    try:
        test_hook_registry()
        test_multiple_hooks()
        test_snapshot_hooks()
        test_error_handling()
        test_hook_unregistration()
        test_global_registry()
        test_clear_all()
        test_different_statuses()
        test_order_normalizers()
        test_snapshot_normalizers()
        test_normalizer_error_handling()
        test_normalizer_unregistration()
        test_complete_flow_with_normalizers()

        print("\n" + "="*70)
        print("✓✓✓ ALL 13 TESTS PASSED ✓✓✓")
        print("="*70)
        print("\nWebSocket hook system with normalizers is working correctly!")
        print("\nNext steps:")
        print("1. Read genai_data/WEBSOCKET_HOOKS_EXTENSION.md for usage guide")
        print("2. See genai_tools/websocket_hook_examples.py for practical examples")
        print("3. Register your own hooks with: engine.websocket_hooks.register_*()")
        print("4. Register normalizers with: engine.websocket_hooks.register_*_normalizer()")
        return 0

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit_code = run_all_tests()
    sys.exit(exit_code)
