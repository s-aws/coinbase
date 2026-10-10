# Exception Handling Guide

Reconciled on 2026-10-09. `core/exceptions.py` owns the exception hierarchy.
Import directly from that module and inspect the constructor signature before
passing context: subclasses have different explicit fields; generic order
errors support extra keyword context.

## Current hierarchy

| Exception | Base | Intent |
| --- | --- | --- |
| `CoinbaseEngineError` | `Exception` | Base exception for all Coinbase engine errors. |
| `OrderProcessingError` | `CoinbaseEngineError` | Base for order creation, calculation, and lifecycle errors. |
| `OrderCalculationError` | `OrderProcessingError` | Order calculation failed (follow-up pricing, sizing, fees). |
| `OrderCreationError` | `OrderProcessingError` | Order creation in orderbook or database failed. |
| `OrderCancellationError` | `OrderProcessingError` | Order cancellation failed. |
| `FollowUpOrderError` | `OrderProcessingError` | Follow-up order generation failed after parent fill. |
| `StealthOrderError` | `CoinbaseEngineError` | Base for stealth (hidden) order errors. |
| `StealthOrderNotFoundError` | `StealthOrderError` | Stealth order not found in system. |
| `RevealConditionEvaluationError` | `StealthOrderError` | Reveal condition evaluation failed. |
| `RevealPricingError` | `StealthOrderError` | Reveal limit price resolution failed. |
| `RevealOrderSliceError` | `StealthOrderError` | Order reveal slice failed (converting stealth to exchange order). |
| `StealthMoveError` | `StealthOrderError` | Move of a REVEALED stealth order failed. |
| `StealthOrderPersistenceError` | `StealthOrderError` | Stealth order database persistence failed. |
| `DatabaseError` | `CoinbaseEngineError` | Base for database persistence and connectivity errors. |
| `OrderPersistenceError` | `DatabaseError` | Order persistence to database failed. |
| `DatabaseConnectionError` | `DatabaseError` | Database connection lost or failed. |
| `DatabaseTransactionError` | `DatabaseError` | Database transaction failed or rolled back. |
| `WebSocketError` | `CoinbaseEngineError` | Base for WebSocket connection and message handling errors. |
| `WebSocketConnectionError` | `WebSocketError` | WebSocket connection failed or was lost. |
| `WebSocketMessageError` | `WebSocketError` | WebSocket message parsing or validation failed. |
| `DuplicateEventError` | `WebSocketError` | Duplicate event detected and skipped. |
| `APIError` | `CoinbaseEngineError` | Base for Coinbase REST/WebSocket API errors. |
| `CoinbaseAPIError` | `APIError` | Coinbase API request failed. |
| `StateManagementError` | `CoinbaseEngineError` | Base for thread-safety and state consistency errors. |
| `ThreadLockTimeoutError` | `StateManagementError` | Lock acquisition timed out (thread safety issue). |
| `StateInconsistencyError` | `StateManagementError` | In-memory state is inconsistent. |
| `AnchorRepricingError` | `StealthOrderError` | Anchor repricing operation failed. |
| `AnchorRepricingGuardrailError` | `AnchorRepricingError` | Repricing guardrails prevented order placement. |

## Handling rules

Raise the narrow domain exception at an existing boundary and preserve the
cause with `raise ... from exc`. Use internal `client_order_id` in ownership
context; exchange IDs are supplemental API/reconciliation evidence.

Persistence failures for condition/intent commitment must not publish success
or continue reveal. Scheduler integrity and unavailable startup reconciliation
are fail-closed readiness boundaries. Existing fail-soft telemetry paths may
log and degrade, but do not apply that policy to every exception.

A REST transport exception leaves acceptance indeterminate. Classify placement
with `business/placement_response.py::classify_placement_response`; a
non-raising response is not acceptance, and a proven accepted order must never
be resubmitted just because local finalization failed. Cancellation likewise
needs exact terminal evidence before HIDDEN or closure can be claimed.

Dashboard handlers normally return structured failure/result payloads for
handled errors. Intentional Cancel may persist the local stop and still report
unsafe withdrawal identity; preserve that durable state and reconciliation
context rather than rolling it back as if no stop occurred.

Tests live in `tests/test_exceptions.py` and
`tests/regression/test_exception_kwargs_signature.py`, alongside the domain's
failure-boundary regressions. Run the complete gate in `TESTING_STRATEGY.md`.
