"""Example WebSocket Hook Extensions.

This module demonstrates practical use cases for the WebSocket hook system.
Copy and adapt these examples for your own extensions.
"""

import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)


# ============================================================================
# NORMALIZERS: Handle Coinbase Field Variations
# ============================================================================

class SpotOrderNormalizer:
    """Normalize spot order fields from Coinbase format."""

    def normalize_spot_order(self, order: dict) -> None:
        """Normalize spot-specific fields.

        Coinbase sends different fields for spot vs futures orders.
        This normalizer coerces them to a consistent format.
        """
        try:
            # Spot orders use 'limit_price', normalize to 'start_price'
            if 'limit_price' in order and 'start_price' not in order:
                order['start_price'] = float(order['limit_price'])

            # Spot orders use 'order_side', normalize to uppercase
            if 'order_side' in order:
                order['order_side'] = order['order_side'].upper()

            # Ensure numeric fields are float
            numeric_fields = ['avg_price', 'total_fees', 'filled_value']
            for field in numeric_fields:
                if field in order and order[field]:
                    try:
                        order[field] = float(order[field])
                    except (ValueError, TypeError):
                        logger.warning(f"Could not convert {field} to float")

        except Exception as e:
            logger.error(f"Spot order normalization failed: {e}")


# Usage:
# normalizer = SpotOrderNormalizer()
# hooks.register_order_normalizer(normalizer.normalize_spot_order)


class FuturesOrderNormalizer:
    """Normalize futures order fields from Coinbase format."""

    def normalize_futures_order(self, order: dict) -> None:
        """Normalize futures-specific fields."""
        try:
            # Detect if this is a futures order
            contract_expiry = order.get('contract_expiry_type')
            if not contract_expiry:
                return  # Not a futures order

            # Add computed field: is this an expiring futures contract?
            order['_is_expiring'] = contract_expiry == 'EXPIRING'
            order['_is_perpetual'] = contract_expiry == 'PERPETUAL'

            # Normalize trigger_status
            trigger_status = order.get('trigger_status', '')
            order['_is_triggered'] = trigger_status == 'STOP_TRIGGERED'

            logger.debug(f"Futures order {order.get('client_order_id')}: "
                        f"expiring={order['_is_expiring']}, triggered={order['_is_triggered']}")

        except Exception as e:
            logger.error(f"Futures order normalization failed: {e}")


# Usage:
# normalizer = FuturesOrderNormalizer()
# hooks.register_order_normalizer(normalizer.normalize_futures_order)


class PositionNormalizer:
    """Normalize position snapshot with computed fields."""

    def enrich_positions(self, snapshot: dict) -> None:
        """Add computed fields to positions."""
        try:
            positions_dict = snapshot.get('positions', {})
            perpetual_positions = positions_dict.get('perpetual_futures_positions', [])

            for pos in perpetual_positions:
                try:
                    # Compute notional value
                    net_size = float(pos.get('net_size', 0))
                    mark_price = float(pos.get('mark_price', 0))
                    pos['_notional_value'] = net_size * mark_price

                    # Compute leverage exposure
                    position_notional = float(pos.get('position_notional', 0))
                    if position_notional != 0:
                        leverage = float(pos.get('leverage', 1))
                        pos['_leverage_exposure'] = position_notional * leverage

                    # Flag risky positions
                    unrealized_pnl = float(pos.get('unrealized_pnl', 0))
                    pos['_is_losing'] = unrealized_pnl < 0

                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not compute position fields: {e}")

        except Exception as e:
            logger.error(f"Position normalization failed: {e}")


# Usage:
# normalizer = PositionNormalizer()
# hooks.register_snapshot_normalizer(normalizer.enrich_positions)


# ============================================================================
# EXAMPLE 1: Real-Time Fill Notifications
# ============================================================================

class FillNotifier:
    """Send notifications when orders fill."""

    def __init__(self, notification_service):
        self.notification_service = notification_service

    def on_order_filled(self, order: dict) -> None:
        """Post-hook: Notify external system of fills."""
        client_order_id = order.get('client_order_id')
        product_id = order.get('product_id')
        quantity = float(order.get('cumulative_quantity', 0))
        price = float(order.get('avg_price', 0))
        total_fees = float(order.get('total_fees', 0))

        message = (
            f"Order {client_order_id}: {quantity} {product_id} filled at {price} "
            f"(fees: {total_fees})"
        )

        try:
            self.notification_service.send(message)
            logger.info(f"Notification sent: {message}")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")


# Usage:
# notifier = FillNotifier(slack_service)
# hooks.register_post_order_status('FILLED', notifier.on_order_filled)


# ============================================================================
# EXAMPLE 2: Order Size Validation
# ============================================================================

def validate_order_size(order: dict) -> None:
    """Pre-hook: Reject orders that exceed maximum size."""
    MAX_ORDER_SIZE = 100.0  # Example: 100 BTC

    try:
        quantity = float(order.get('order_quantity') or order.get('leaves_quantity', 0))
        client_order_id = order.get('client_order_id')

        if quantity > MAX_ORDER_SIZE:
            logger.warning(
                f"Order {client_order_id} exceeds max size: {quantity} > {MAX_ORDER_SIZE}"
            )
            # Could trigger alert, manual review, cancellation, etc.
    except (ValueError, TypeError) as e:
        logger.error(f"Failed to validate order size: {e}")


# Usage:
# hooks.register_pre_order_status('OPEN', validate_order_size)


# ============================================================================
# EXAMPLE 3: Audit Trail Logging
# ============================================================================

class AuditLogger:
    """Log all order events to an audit trail."""

    def __init__(self, database):
        self.database = database

    def log_order_event(self, event_type: str, order: dict) -> None:
        """Record order event to audit log."""
        try:
            client_order_id = order.get('client_order_id')
            status = order.get('status')
            product_id = order.get('product_id')
            quantity = float(order.get('cumulative_quantity', 0))
            price = float(order.get('avg_price', 0))

            audit_entry = {
                'event_type': event_type,
                'client_order_id': client_order_id,
                'status': status,
                'product_id': product_id,
                'quantity': quantity,
                'price': price,
                'timestamp': datetime.utcnow().isoformat(),
            }

            self.database.insert('audit_log', audit_entry)
            logger.debug(f"Audit log entry: {audit_entry}")

        except Exception as e:
            logger.error(f"Failed to log audit entry: {e}")


# Usage:
# audit_logger = AuditLogger(database)
# hooks.register_post_order_status('FILLED', lambda o: audit_logger.log_order_event('FILLED', o))
# hooks.register_post_order_status('CANCELLED', lambda o: audit_logger.log_order_event('CANCELLED', o))


# ============================================================================
# EXAMPLE 4: PnL Calculation on Fills
# ============================================================================

class PnLTracker:
    """Track profit and loss for filled orders."""

    def __init__(self, database):
        self.database = database
        self.open_positions: Dict[str, Any] = {}

    def on_order_filled(self, order: dict) -> None:
        """Post-hook: Calculate and track PnL."""
        try:
            client_order_id = order.get('client_order_id')
            product_id = order.get('product_id')
            side = order.get('order_side', '').upper()
            quantity = float(order.get('cumulative_quantity', 0))
            price = float(order.get('avg_price', 0))
            fees = float(order.get('total_fees', 0))
            filled_value = float(order.get('filled_value', 0))

            # Track open positions and calculate PnL
            position_key = product_id

            if position_key in self.open_positions:
                # Closing a position - calculate PnL
                prev_price = self.open_positions[position_key]['price']
                prev_quantity = self.open_positions[position_key]['quantity']
                prev_side = self.open_positions[position_key]['side']

                if side != prev_side:  # Opposite side closes position
                    pnl = (price - prev_price) * prev_quantity - fees
                    if prev_side == 'SELL':
                        pnl = (prev_price - price) * prev_quantity - fees

                    logger.info(f"Position closed for {product_id}: PnL = {pnl}")
                    del self.open_positions[position_key]
                else:
                    # Same side adds to position
                    avg_price = ((prev_price * prev_quantity) + (price * quantity)) / (prev_quantity + quantity)
                    self.open_positions[position_key] = {
                        'price': avg_price,
                        'quantity': prev_quantity + quantity,
                        'side': side,
                    }
            else:
                # Opening new position
                self.open_positions[position_key] = {
                    'price': price,
                    'quantity': quantity,
                    'side': side,
                }
                logger.info(f"Position opened for {product_id}: {quantity} @ {price}")

        except Exception as e:
            logger.error(f"Failed to track PnL: {e}")


# Usage:
# pnl_tracker = PnLTracker(database)
# hooks.register_post_order_status('FILLED', pnl_tracker.on_order_filled)


# ============================================================================
# EXAMPLE 5: Position Reconciliation
# ============================================================================

def reconcile_positions_after_snapshot(snapshot: dict) -> None:
    """Post-hook: Verify positions match expectations after snapshot."""
    try:
        positions_dict = snapshot.get('positions', {})
        perpetual_positions = positions_dict.get('perpetual_futures_positions', [])

        total_position_notional = 0.0

        for pos in perpetual_positions:
            product_id = pos.get('product_id')
            net_size = float(pos.get('net_size', 0))
            mark_price = float(pos.get('mark_price', 0))

            notional = net_size * mark_price
            total_position_notional += notional

            if net_size != 0:
                logger.info(f"Position: {product_id} {net_size} @ {mark_price} (notional: {notional})")

        logger.info(f"Total position notional value: {total_position_notional}")

        # Could compare against limits, trigger alerts, etc.
        MAX_NOTIONAL = 1000000  # Example: $1M limit
        if total_position_notional > MAX_NOTIONAL:
            logger.warning(f"Position notional {total_position_notional} exceeds limit {MAX_NOTIONAL}")

    except Exception as e:
        logger.error(f"Failed to reconcile positions: {e}")


# Usage:
# hooks.register_post_snapshot(reconcile_positions_after_snapshot)


# ============================================================================
# EXAMPLE 6: Order Status Transitions
# ============================================================================

class OrderStateTracker:
    """Track order state transitions over time."""

    def __init__(self):
        self.order_history: Dict[str, list] = {}

    def track_status_change(self, order: dict) -> None:
        """Post-hook: Record order status change."""
        try:
            client_order_id = order.get('client_order_id')
            status = order.get('status')
            timestamp = datetime.utcnow().isoformat()

            if client_order_id not in self.order_history:
                self.order_history[client_order_id] = []

            self.order_history[client_order_id].append({
                'status': status,
                'timestamp': timestamp,
                'quantity': order.get('cumulative_quantity'),
                'price': order.get('avg_price'),
            })

            logger.debug(f"Order {client_order_id} → {status}")

        except Exception as e:
            logger.error(f"Failed to track status change: {e}")

    def get_order_timeline(self, client_order_id: str) -> list:
        """Get the complete state history for an order."""
        return self.order_history.get(client_order_id, [])


# Usage:
# tracker = OrderStateTracker()
# for status in ['OPEN', 'FILLED', 'CANCELLED', 'PENDING']:
#     hooks.register_post_order_status(status, tracker.track_status_change)


# ============================================================================
# EXAMPLE 7: Conditional Extensions Based on Product
# ============================================================================

class ProductSpecificHandler:
    """Apply different logic based on product type."""

    def handle_order(self, order: dict) -> None:
        """Post-hook: Handle order based on product."""
        try:
            product_id = order.get('product_id', '')

            if product_id.endswith('-PERP'):
                # Futures specific logic
                self._handle_futures(order)
            elif product_id.endswith('-USD') or product_id.endswith('-USDC'):
                # Spot specific logic
                self._handle_spot(order)
            else:
                logger.warning(f"Unknown product type: {product_id}")

        except Exception as e:
            logger.error(f"Failed to handle order: {e}")

    def _handle_futures(self, order: dict) -> None:
        """Handle futures order fill."""
        logger.info(f"Futures order: {order.get('client_order_id')}")
        # Futures-specific business logic

    def _handle_spot(self, order: dict) -> None:
        """Handle spot order fill."""
        logger.info(f"Spot order: {order.get('client_order_id')}")
        # Spot-specific business logic


# Usage:
# handler = ProductSpecificHandler()
# hooks.register_post_order_status('FILLED', handler.handle_order)


# ============================================================================
# EXAMPLE 8: Multiple Hooks for Complex Workflows
# ============================================================================

def setup_complete_fill_workflow(hooks, services):
    """Register multiple hooks for a complete fill workflow."""

    # Step 1: Validate the fill early
    def validate_fill(order: dict) -> None:
        quantity = float(order.get('cumulative_quantity', 0))
        if quantity <= 0:
            logger.error("Invalid fill quantity")

    # Step 2: Record to audit log
    def audit_fill(order: dict) -> None:
        logger.info(f"Audit: Order {order.get('client_order_id')} filled")

    # Step 3: Calculate PnL
    def calculate_pnl(order: dict) -> None:
        logger.info(f"Calculating PnL for {order.get('client_order_id')}")

    # Step 4: Notify external systems
    def notify_external(order: dict) -> None:
        logger.info(f"Notifying: Order {order.get('client_order_id')} filled")

    # Register in order of execution
    hooks.register_pre_order_status('FILLED', validate_fill)
    hooks.register_post_order_status('FILLED', audit_fill)
    hooks.register_post_order_status('FILLED', calculate_pnl)
    hooks.register_post_order_status('FILLED', notify_external)


# Usage:
# from integration.websocket_hooks import get_global_hook_registry
# hooks = get_global_hook_registry()
# setup_complete_fill_workflow(hooks, services)


if __name__ == '__main__':
    # Example of testing a hook in isolation
    import logging
    logging.basicConfig(level=logging.DEBUG)

    # Test the order size validator
    test_order = {
        'client_order_id': 'test-123',
        'order_quantity': '50.0',
        'product_id': 'BTC-USD',
    }

    print("Testing validate_order_size...")
    validate_order_size(test_order)

    print("\nTesting with oversized order...")
    large_order = {
        'client_order_id': 'test-456',
        'order_quantity': '150.0',
        'product_id': 'BTC-USD',
    }
    validate_order_size(large_order)
