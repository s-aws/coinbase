"""
Custom exceptions for the Coinbase trading engine.

This module defines domain-specific exception classes organized by system layer:
- OrderProcessingError: Order creation, calculation, and lifecycle errors
- StealthOrderError: Hidden order reveal, condition evaluation, pricing
- DatabaseError: Persistence and transaction failures
- WebSocketError: Connection, message handling, deduplication
- APIError: Coinbase REST/WebSocket API failures
- StateManagementError: Thread safety, locking, state consistency

Usage:
    try:
        reveal_stealth_order(stealth_order_id, market_data)
    except RevealConditionEvaluationError as e:
        logger.error("Condition evaluation failed", extra={"reason": str(e)})
        # Retry or escalate as needed
    except RevealPricingError as e:
        logger.error("Pricing failed during reveal", extra={"fallback_used": e.fallback_used})
        # Use fallback pricing or reject reveal
    except StealthOrderError as e:
        logger.error("Stealth order error", exc_info=True)
        # Critical failure - investigate

Exception hierarchy is designed to:
1. Enable precise error handling at each layer
2. Support structured logging with context
3. Allow recovery strategies based on error type
4. Make multithreaded debugging easier
"""

from typing import Optional, Dict, Any


def _format_error_message(message: str, **context) -> str:
    """Format an exception message with optional structured context.

    Used by all engine exception subclasses for consistent string output.
    None values are dropped so optional fields don't pollute the message.
    """
    parts = []
    if message:
        parts.append(str(message))
    ctx_pairs = [f"{k}={v}" for k, v in context.items() if v is not None]
    if ctx_pairs:
        parts.append("[" + ", ".join(ctx_pairs) + "]")
    return " ".join(parts) if parts else ""


class CoinbaseEngineError(Exception):
    """
    Base exception for all Coinbase engine errors.
    
    Use this to catch any engine-specific exception at the top level.
    """
    pass


# ============================================================================
# ORDER PROCESSING ERRORS
# ============================================================================

class OrderProcessingError(CoinbaseEngineError):
    """Base for order creation, calculation, and lifecycle errors."""
    
    def __init__(self, message: str, client_order_id: Optional[str] = None, **context):
        """
        Args:
            message: Human-readable error description
            client_order_id: Order ID for correlation
            **context: Additional error context (product_id, side, size, etc.)
        """
        self.message = message
        self.client_order_id = client_order_id
        self.context = context
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        msg = self.message
        if self.client_order_id:
            msg = f"{msg} [client_order_id={self.client_order_id}]"
        return msg


class OrderCalculationError(OrderProcessingError):
    """
    Order calculation failed (follow-up pricing, sizing, fees).
    
    Raised when:
    - Follow-up price calculation fails
    - Size calculation has invalid input
    - Fee estimation encounters bad data
    - Target movement calculation fails
    
    Recovery: Check input data, retry with adjusted parameters.
    """
    pass


class OrderCreationError(OrderProcessingError):
    """
    Order creation in orderbook or database failed.
    
    Raised when:
    - Unable to create order object
    - Database insert fails
    - Parent-child linkage fails
    - Order already exists (duplicate)
    
    Recovery: Check database connectivity, verify parent/child IDs exist.
    """
    pass


class OrderCancellationError(OrderProcessingError):
    """
    Order cancellation failed.
    
    Raised when:
    - Cancel request to exchange fails
    - Order state prevents cancellation
    - Database update fails
    
    Recovery: Check order state, retry cancel, or escalate to manual review.
    """
    pass


class FollowUpOrderError(OrderProcessingError):
    """
    Follow-up order generation failed after parent fill.
    
    Raised when:
    - Cannot create follow-up from parent fill
    - Child order linkage fails
    - Target movement metadata missing
    
    Recovery: Verify parent order has required metadata (target_movement, follow_up_direction).
    """
    pass


# ============================================================================
# STEALTH ORDER ERRORS
# ============================================================================

class StealthOrderError(CoinbaseEngineError):
    """Base for stealth (hidden) order errors."""
    pass


class StealthOrderNotFoundError(StealthOrderError):
    """
    Stealth order not found in system.
    
    Raised when:
    - Lookup by stealth_order_id returns None
    - Lookup by client_order_id returns None
    - Order was deleted or never created
    
    Recovery: Verify order ID is correct, check database for orphaned orders.
    """
    
    def __init__(self, lookup_type: str, lookup_value: str):
        """
        Args:
            lookup_type: "stealth_order_id", "client_order_id", "placed_order_id"
            lookup_value: The ID that was searched for
        """
        self.lookup_type = lookup_type
        self.lookup_value = lookup_value
        super().__init__(
            f"Stealth order not found by {lookup_type}={lookup_value}"
        )


class RevealConditionEvaluationError(StealthOrderError):
    """
    Reveal condition evaluation failed.
    
    Raised when:
    - Condition evaluator raises error
    - Market data unavailable during evaluation
    - Condition type unsupported
    - Timeout during evaluation
    
    Recovery: Check market data availability, retry evaluation, verify condition type.
    """
    
    def __init__(
        self,
        message: str,
        condition_type: Optional[str] = None,
        stealth_order_id: Optional[str] = None
    ):
        self.condition_type = condition_type
        self.stealth_order_id = stealth_order_id
        super().__init__(message)


class RevealPricingError(StealthOrderError):
    """
    Reveal limit price resolution failed.
    
    Raised when:
    - Configured limit price invalid
    - Market data missing for pricing policy (top_of_book, midpoint)
    - Price validation fails
    - Profitability check fails on submitted price
    
    Includes fallback_used flag to indicate if fallback to configured price was used.
    
    Recovery: Check market data, adjust pricing policy, or reject reveal if profitability invalid.
    """
    
    def __init__(
        self,
        message: str,
        configured_price: Optional[float] = None,
        fallback_used: bool = False,
        stealth_order_id: Optional[str] = None
    ):
        """
        Args:
            message: Error description
            configured_price: Original configured limit price (for fallback info)
            fallback_used: Whether fallback to configured_price was used
            stealth_order_id: Order ID for correlation
        """
        self.configured_price = configured_price
        self.fallback_used = fallback_used
        self.stealth_order_id = stealth_order_id
        super().__init__(message)


class RevealOrderSliceError(StealthOrderError):
    """
    Order reveal slice failed (converting stealth to exchange order).
    
    Raised when:
    - Cannot extract client_order_id from stealth order
    - Cannot slice order by size
    - Database update to REVEALED status fails
    - REST API submission fails after reveal
    
    Recovery: Check order structure, verify slice parameters, retry REST submission.
    """
    pass


class StealthOrderPersistenceError(StealthOrderError):
    """
    Stealth order database persistence failed.
    
    Raised when:
    - Insert to stealth_orders table fails
    - Update status fails
    - Delete fails
    - Transaction rollback needed
    
    Recovery: Check database connectivity, verify required fields, retry transaction.
    """
    pass


# ============================================================================
# DATABASE ERRORS
# ============================================================================

class DatabaseError(CoinbaseEngineError):
    """Base for database persistence and connectivity errors."""
    pass


class OrderPersistenceError(DatabaseError):
    """
    Order persistence to database failed.
    
    Raised when:
    - Insert order_parent fails
    - Insert order_child fails
    - Update order status fails
    - Delete order fails
    - Parent-child linkage insert fails
    
    Recovery: Check database connectivity, verify schema, check for constraint violations.
    """

    def __init__(
        self,
        message: str = "",
        operation: Optional[str] = None,  # "insert", "update", "delete"
        table: Optional[str] = None,      # "order_parent", "order_child", etc.
        client_order_id: Optional[str] = None,
        *,
        error_type: Optional[str] = None,
        stealth_order_id: Optional[str] = None,
        **context,
    ):
        self.operation = operation
        self.table = table
        self.client_order_id = client_order_id
        self.error_type = error_type
        self.stealth_order_id = stealth_order_id
        self.context = {k: v for k, v in context.items() if v is not None}
        super().__init__(
            _format_error_message(
                message,
                error_type=error_type,
                operation=operation,
                table=table,
                client_order_id=client_order_id,
                stealth_order_id=stealth_order_id,
                **self.context,
            )
        )


class DatabaseConnectionError(DatabaseError):
    """
    Database connection lost or failed.
    
    Raised when:
    - Cannot connect to PostgreSQL
    - Connection timeout
    - Connection pool exhausted
    
    Recovery: Check database service, verify credentials, increase pool size.
    """

    def __init__(
        self,
        message: str = "",
        *,
        error_type: Optional[str] = None,
        client_order_id: Optional[str] = None,
        stealth_order_id: Optional[str] = None,
        **context,
    ):
        self.error_type = error_type
        self.client_order_id = client_order_id
        self.stealth_order_id = stealth_order_id
        self.context = {k: v for k, v in context.items() if v is not None}
        super().__init__(
            _format_error_message(
                message,
                error_type=error_type,
                client_order_id=client_order_id,
                stealth_order_id=stealth_order_id,
                **self.context,
            )
        )


class DatabaseTransactionError(DatabaseError):
    """
    Database transaction failed or rolled back.
    
    Raised when:
    - Multi-statement transaction fails
    - Constraint violation prevents insert
    - Deadlock detected and rolled back
    
    Recovery: Retry transaction, resolve constraint violations, reduce contention.
    """

    def __init__(
        self,
        message: str = "",
        rollback_reason: Optional[str] = None,
        *,
        error_type: Optional[str] = None,
        client_order_id: Optional[str] = None,
        stealth_order_id: Optional[str] = None,
        **context,
    ):
        self.rollback_reason = rollback_reason
        self.error_type = error_type
        self.client_order_id = client_order_id
        self.stealth_order_id = stealth_order_id
        self.context = {k: v for k, v in context.items() if v is not None}
        super().__init__(
            _format_error_message(
                message,
                error_type=error_type,
                rollback_reason=rollback_reason,
                client_order_id=client_order_id,
                stealth_order_id=stealth_order_id,
                **self.context,
            )
        )


# ============================================================================
# WEBSOCKET ERRORS
# ============================================================================

class WebSocketError(CoinbaseEngineError):
    """Base for WebSocket connection and message handling errors."""
    pass


class WebSocketConnectionError(WebSocketError):
    """
    WebSocket connection failed or was lost.
    
    Raised when:
    - Connection handshake fails
    - Connection drops unexpectedly
    - Reconnection attempts exhausted
    
    Recovery: Reconnect with backoff, verify WebSocket endpoint, check network.
    """
    
    def __init__(self, message: str, retry_count: Optional[int] = None):
        self.retry_count = retry_count
        super().__init__(message)


class WebSocketMessageError(WebSocketError):
    """
    WebSocket message parsing or validation failed.
    
    Raised when:
    - JSON parsing fails
    - Required fields missing
    - Message schema invalid
    - Event type unrecognized
    
    Recovery: Log malformed message, skip processing, continue with next message.
    """

    def __init__(
        self,
        message: str = "",
        raw_data: Optional[str] = None,
        *,
        error_type: Optional[str] = None,
        **context,
    ):
        self.raw_data = raw_data
        self.error_type = error_type
        self.context = {k: v for k, v in context.items() if v is not None}
        super().__init__(_format_error_message(message, error_type=error_type, **self.context))


class DuplicateEventError(WebSocketError):
    """
    Duplicate event detected and skipped.
    
    Raised when:
    - Event hash matches known event within dedup window
    - Event sequence ID already processed
    - Double-processing would cause state corruption
    
    Recovery: Skip processing (expected behavior), continue with next event.
    """
    
    def __init__(
        self,
        message: str,
        event_hash: Optional[str] = None,
        window_seconds: int = 60
    ):
        self.event_hash = event_hash
        self.window_seconds = window_seconds
        super().__init__(message)


# ============================================================================
# API ERRORS
# ============================================================================

class APIError(CoinbaseEngineError):
    """Base for Coinbase REST/WebSocket API errors."""
    pass


class CoinbaseAPIError(APIError):
    """
    Coinbase API request failed.
    
    Raised when:
    - REST API returns error status
    - Rate limit exceeded
    - Authentication failed
    - Request validation failed
    
    Recovery: Check API credentials, reduce request rate, verify request format.
    """
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        api_error_code: Optional[str] = None,
        rate_limit_remaining: Optional[int] = None
    ):
        """
        Args:
            message: Error description from API or client
            status_code: HTTP status code
            api_error_code: Coinbase error code (e.g., "invalid_order")
            rate_limit_remaining: Requests remaining before rate limit
        """
        self.status_code = status_code
        self.api_error_code = api_error_code
        self.rate_limit_remaining = rate_limit_remaining
        super().__init__(message)


# ============================================================================
# STATE MANAGEMENT ERRORS
# ============================================================================

class StateManagementError(CoinbaseEngineError):
    """Base for thread-safety and state consistency errors."""
    pass


class ThreadLockTimeoutError(StateManagementError):
    """
    Lock acquisition timed out (thread safety issue).
    
    Raised when:
    - RLock.acquire() times out
    - Cannot acquire state lock for mutation
    - Potential deadlock detected
    
    Recovery: Increase timeout, check for deadlocks, reduce critical section.
    """
    
    def __init__(self, message: str, lock_name: str, timeout_seconds: float):
        self.lock_name = lock_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"{message} [lock={lock_name}, timeout={timeout_seconds}s]"
        )


class StateInconsistencyError(StateManagementError):
    """
    In-memory state is inconsistent.
    
    Raised when:
    - Parent order missing but child references it
    - Order count doesn't match
    - Position state invalid
    
    Recovery: Check database for source of truth, rebuild in-memory state.
    """
    
    def __init__(self, message: str, expected: Any, actual: Any):
        self.expected = expected
        self.actual = actual
        super().__init__(f"{message} [expected={expected}, actual={actual}]")


# ============================================================================
# TYPE ALIASES FOR COMMON PATTERNS
# ============================================================================

class AnchorRepricingError(StealthOrderError):
    """Anchor repricing operation failed.
    
    Raised when:
    - Market data invalid or unavailable for repricing
    - Reference price cannot be determined
    - Repricing guardrails block placement
    - Post-only enforcement fails
    
    Recovery: Check market data, review policy constraints, retry or escalate.
    """
    
    def __init__(
        self,
        message: str,
        stealth_order_id: Optional[str] = None,
        reference_price: Optional[float] = None,
        policy: Optional[str] = None
    ):
        """
        Args:
            message: Error description
            stealth_order_id: Order ID for correlation
            reference_price: Reference price that was attempted (for debugging)
            policy: Repricing policy name (e.g., 'midpoint', 'last_trade')
        """
        self.stealth_order_id = stealth_order_id
        self.reference_price = reference_price
        self.policy = policy
        super().__init__(message)


class AnchorRepricingGuardrailError(AnchorRepricingError):
    """Repricing guardrails prevented order placement.
    
    Raised when repricing logic determines placement would violate constraints:
    - Post-only price check failed (would cross bid/ask)
    - Price would exceed max boundary
    - Not enough time elapsed since last reprice
    - Hourly reprice limit exceeded
    
    Recovery: Adjust policy constraints or wait for next repricing window.
    """
    
    def __init__(
        self,
        message: str,
        guardrail_type: str,  # "post_only", "max_boundary", "cooldown", "rate_limit"
        stealth_order_id: Optional[str] = None
    ):
        self.guardrail_type = guardrail_type
        super().__init__(message, stealth_order_id=stealth_order_id)


# ============================================================================
# TYPE ALIASES FOR COMMON PATTERNS
# ============================================================================

# Use these for type hints on functions that may raise specific exceptions
OrderRelatedError = (
    OrderProcessingError | StealthOrderError | DatabaseError | StateManagementError
)

RevealRelatedError = (
    RevealConditionEvaluationError | RevealPricingError | RevealOrderSliceError
)

RepricingRelatedError = (
    AnchorRepricingError | AnchorRepricingGuardrailError
)

APIRelatedError = APIError | WebSocketError
