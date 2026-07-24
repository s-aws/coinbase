"""
Order insertion and status management functions for parent and child order tables.

This module handles all database operations for parent and child orders,
including creation, insertion, batch operations, duplicate detection,
replacement tracking, and status updates.
It manages the parent-child order relationship for the trading engine.
"""

import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from logging_service import get_logger
from database.database import PostgresDB
from database.fill_ledger_lock import fill_ledger_product_lock_key
from database.order_follow_up_intent import (
    FOLLOW_UP_INTENT_DURABLE_SLOT_REQUIRED,
    complete_automatic_order_follow_up_claim,
    create_order_follow_up_intent_tables,
    mark_order_follow_up_positive_fill_activity,
    install_order_follow_up_lineage_lock_trigger,
    install_order_follow_up_source_lock_trigger,
    operator_follow_up_intent_slot_applies,
    release_automatic_order_follow_up_claim,
    try_claim_automatic_order_follow_up,
)
from database.operator_fill_triggered_follow_up_activation import (
    create_operator_fill_triggered_follow_up_activation_tables,
    get_default_operator_fill_triggered_follow_up_activation_repository,
)
from typing import Dict, List, Any, NoReturn, Optional
from core.action_condition_guard import SPOT_STANDING_MARKET_SOURCES
from core.constants import get_local_now
from core.enums import (
    OrderOwnershipProvenance,
    OrderSide,
    OrderStatus,
    RevealConditionType,
    StealthOrderStatus,
)
from core.exceptions import DatabaseConnectionError, OrderPersistenceError, DatabaseTransactionError
from configuration import DEFAULT_MAX_ORDER_REPLACEMENT

logger = get_logger("OrderDB")
DB_CLIENT: PostgresDB = PostgresDB()
FOLLOW_UP_INTENT_DURABLE_SLOT_APPLIES = operator_follow_up_intent_slot_applies


def dispatch_operator_fill_triggered_follow_up(
    *,
    source_client_order_id: str,
    trigger_evidence_sha256: str,
) -> dict[str, object]:
    """Dispatch one local attached intent; return fixed sanitized evidence."""

    repository = (
        get_default_operator_fill_triggered_follow_up_activation_repository()
    )
    if not repository.has_attached_intent(source_client_order_id):
        return {"managed": False}
    from application.admin_api.operator_fill_triggered_follow_up_activation import (
        get_default_fill_triggered_follow_up_activation_service,
    )

    record = (
        get_default_fill_triggered_follow_up_activation_service()
        .dispatch_authoritative_full_fill(
            source_client_order_id=source_client_order_id,
            trigger_evidence_sha256=trigger_evidence_sha256,
        )
    )
    return {
        "managed": True,
        "control_state": record.control_state.value,
        "trigger_state": record.trigger_state.value,
        "diagnostic_code": record.diagnostic_code,
    }


_CONTROLLED_ADMIN_CHILD_MAX_MARKET_AGE_SECONDS = Decimal("30")

# One narrowly scoped recovery authorization for the v8 child whose durable
# preparation committed before the HTTP request failed, while Coinbase SDK
# placement was independently proven not to have started.  This is deliberately
# backend-owned rather than a generic client-provided compare-and-swap token.
_SEALED_V8_CONTROLLED_CHILD_RECOVERY_SHA256 = (
    "af16bf8f7867c3f8a385b0d0cef31371d4381289cc1fd7a58e81c29102d783a9"
)
_SEALED_V8_CONTROLLED_CHILD_RECOVERY_BINDING = {
    "authority_id": "d67b89be-549b-4778-9061-e6decb20f550",
    "approval_snapshot_id": "bb1d8b0b-a32f-5acd-be46-a91af74ef701",
    "admission_audit_id": "6d2dd88a-e974-4c55-88a8-e869ae6ce492",
    "cap_guard_decision_id": (
        "cap-v8-slot-2-child-reveal-f88967db-5156-4a8a-b121-dd56dd5a24a3"
    ),
    "reconciliation_plan_id": (
        "reconciliation-v8-slot-2-child-reveal-ee4daeb4-7ab6-4f86-973f-977e502c6653"
    ),
    "batch_id": "4b4322db-64c6-57fc-8e2b-0890b64507e6",
    "batch_slot": 2,
    "root_client_order_id": "12a52c06-e368-5c39-bfa0-6eb5880f3c64",
    "stealth_order_id": "252b6389-d544-58db-a796-e9bc258f794f",
    "portfolio_id": "62f28f44-8e72-4fe0-ace7-d71a01f54883",
    "root_exchange_order_id": "2ed7d436-b16e-4a7e-b0af-cb8f8bb86e68",
}


def _controlled_admin_child_persistence_error(
    message: str,
    *,
    client_order_id: str,
    error_type: str = "ControlledAdminChildPreparationRejected",
) -> OrderPersistenceError:
    """Build one structured fail-closed preparation error."""

    return OrderPersistenceError(
        error_type=error_type,
        message=message,
        operation="update",
        table="order_parent,stealth_orders",
        client_order_id=client_order_id,
        stealth_order_id=client_order_id,
    )


def _finite_positive_decimal(
    value: Any,
    *,
    field_name: str,
    client_order_id: str,
) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _controlled_admin_child_persistence_error(
            f"{field_name} must be finite and positive",
            client_order_id=client_order_id,
        ) from exc
    if not normalized.is_finite() or normalized <= 0:
        raise _controlled_admin_child_persistence_error(
            f"{field_name} must be finite and positive",
            client_order_id=client_order_id,
        )
    return normalized


def _json_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return [None]
        return list(parsed) if isinstance(parsed, list) else [None]
    return [] if value is None else [None]


def _json_default_for_db(value: Any):
    """Serialize common Python runtime types for JSONB database writes."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        from decimal import Decimal

        if isinstance(value, Decimal):
            return float(value)
    except Exception:
        pass
    return str(value)


def _is_uuid_text(value: Any) -> bool:
    """Return True when value is valid UUID text."""
    if value is None:
        return False
    try:
        uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _require_uuid_text(value: Any, field_name: str, client_order_id: Optional[str] = None) -> None:
    """Reject parent-order identifiers that cannot participate in UUID joins."""
    if not _is_uuid_text(value):
        raise OrderPersistenceError(
            error_type="ValidationError",
            message=f"{field_name} must be a valid UUID, got {value!r}",
            client_order_id=client_order_id or str(value),
        )


def _normalize_ownership_provenance(
    value: Optional[OrderOwnershipProvenance | str],
    *,
    client_order_id: Optional[str] = None,
) -> Optional[str]:
    """Return canonical ownership provenance or reject an unknown value."""

    if value is None:
        return None
    try:
        if isinstance(value, OrderOwnershipProvenance):
            return value.value
        return OrderOwnershipProvenance(str(value)).value
    except ValueError as exc:
        raise OrderPersistenceError(
            error_type="OwnershipProvenanceValidationError",
            message=f"Unknown order ownership provenance: {value!r}",
            client_order_id=client_order_id,
        ) from exc


def create_order_parent_table() -> None:
    """Create the order_parent table if it doesn't exist.
    
    Creates parent order table to track the initial orders placed in the system.
    Parent orders can have multiple child orders created when they fill or are cancelled.
    
    Table Schema:
        - id: Auto-incrementing primary key
        - target_movement: Profit target as decimal value
        - target_movement_type: 'P' for percentage or 'A' for absolute amount
        - max_order_replacement: Maximum number of follow-up orders allowed
        - current_order_replacement: Count of follow-up orders created so far
        - client_order_id: UUID generated by application (unique)
        - product_id: Trading product (e.g., 'BTC-USDC')
        - side: 'BUY' or 'SELL'
        - size: Order size in base currency
        - price: Limit price for the order
        - status: Order status ('PENDING', 'OPEN', 'FILLED', 'CANCELLED', etc.)
        - parent_order_id: UUID of parent if this is a follow-up order
        - created_at: Timestamp when record was inserted
    
    Returns:
        None. Creates table as side effect.
    
    Raises:
        No exceptions - uses IF NOT EXISTS to prevent errors if table already exists.
    
    Example:
        >>> create_order_parent_table()
        order_parent table done.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS order_parent (
        id SERIAL PRIMARY KEY,
        target_movement NUMERIC,
        target_movement_type VARCHAR(1),
        max_order_replacement INTEGER NOT NULL DEFAULT 0,
        current_order_replacement INTEGER NOT NULL DEFAULT 0,
        client_order_id VARCHAR(40) UNIQUE NOT NULL,
        product_id VARCHAR(255) NOT NULL,
        side VARCHAR(10) NOT NULL,
        size NUMERIC NOT NULL,
        price NUMERIC NOT NULL,
        status VARCHAR(20) NOT NULL,
        parent_order_id VARCHAR(40),
        ownership_provenance VARCHAR(64),
        retail_portfolio_id UUID,
        correlation_id VARCHAR(255),
        audit_id VARCHAR(255),
        exchange_order_id VARCHAR(64),
        allow_partial_fills BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        cursor.execute(
            "ALTER TABLE order_parent ADD COLUMN IF NOT EXISTS "
            "allow_partial_fills BOOLEAN NOT NULL DEFAULT FALSE"
        )
        cursor.execute(
            "ALTER TABLE order_parent ADD COLUMN IF NOT EXISTS "
            "ownership_provenance VARCHAR(64)"
        )
        cursor.execute(
            "ALTER TABLE order_parent ADD COLUMN IF NOT EXISTS "
            "retail_portfolio_id UUID"
        )
        cursor.execute(
            "ALTER TABLE order_parent ADD COLUMN IF NOT EXISTS "
            "correlation_id VARCHAR(255)"
        )
        cursor.execute(
            "ALTER TABLE order_parent ADD COLUMN IF NOT EXISTS "
            "audit_id VARCHAR(255)"
        )
        cursor.execute(
            "ALTER TABLE order_parent ADD COLUMN IF NOT EXISTS exchange_order_id VARCHAR(64)"
        )
        # Hotpoint Auto-Replicate (per-order opt-in; provenance marker).
        # `enable_hotpoint_replication=TRUE` opts a parent's fills into the
        # hotpoint detector. `auto_placed_by_hotpoint=TRUE` marks rows this
        # feature created â€” used by the rate-limiter restart rebuild and the
        # decay sweeper. Auto-placed rows always carry
        # enable_hotpoint_replication=FALSE so they cannot cascade.
        cursor.execute(
            "ALTER TABLE order_parent ADD COLUMN IF NOT EXISTS "
            "enable_hotpoint_replication BOOLEAN NOT NULL DEFAULT FALSE"
        )
        cursor.execute(
            "ALTER TABLE order_parent ADD COLUMN IF NOT EXISTS "
            "auto_placed_by_hotpoint BOOLEAN NOT NULL DEFAULT FALSE"
        )
        print("order_parent table done.")
    install_order_follow_up_lineage_lock_trigger()


def create_stealth_orders_table() -> None:
    """Create the stealth_orders table if it doesn't exist.
    
    Main table for hidden order tracking with reveal conditions and execution state.
    Stores the complete lifecycle of stealth (hidden) orders from creation through
    reveal conditions being met to final execution.
    
    Table Schema:
        - id: Auto-incrementing primary key
        - created_at, updated_at: Timestamps for creation and last update
        - stealth_order_id: UUID unique identifier for the stealth order
        - parent_order_id: Optional UUID linking to parent stealth order if this is a follow-up
        - product_id: Trading product (e.g., 'BTC-USDC')
        - side: Order side ('BUY' or 'SELL')
        - total_size: Total quantity to eventually place
        - revealed_size: Quantity that has been placed on exchange
        - remaining_size: Quantity still hidden (total - revealed)
        - executed_size: Quantity that has been filled
        - limit_price: Limit price for orders
        - status: Order status (HIDDEN, PENDING, TRIGGERED, REVEALED, EXECUTED, CANCELLED)
        - visibility_score: Calculated market visibility metric (0.0-1.0)
        - reveal_condition_type: Type of condition (price, time_delay, spread, etc.)
        - reveal_condition_json: JSONB configuration for the reveal condition
        - condition_first_met_at: Timestamp when condition was first detected
        - condition_confirmed_at: Timestamp when condition was fully confirmed
        - sizing_strategy_json: JSONB configuration for reveal sizing
        - revealed_orders: JSONB array of order IDs placed on exchange
        - last_placement_at: Timestamp of most recent reveal/placement
        - target_movement: Profit target value
        - target_movement_type: 'P' for percentage or 'A' for absolute amount
        - cancel_reentry_policy_json: Optional cancel/re-entry policy config
        - cancel_reentry_state_json: Runtime state for policy-cancelled placements
        - post_fill_retreat_policy_json: Optional same-side hidden-order retreat policy
        - reason: Reason for creation (e.g., 'follow_up', 'user_created')
        - notes: Optional additional details
    
    Returns:
        None. Creates table as side effect.
    
    Raises:
        No exceptions - uses IF NOT EXISTS to prevent errors if table already exists.
    
    Example:
        >>> create_stealth_orders_table()
        stealth_orders table done.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS stealth_orders (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        stealth_order_id UUID UNIQUE NOT NULL,
        parent_order_id UUID,
        product_id VARCHAR(32) NOT NULL,
        side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
        
        total_size DECIMAL(16, 8) NOT NULL,
        revealed_size DECIMAL(16, 8) DEFAULT 0,
        remaining_size DECIMAL(16, 8) NOT NULL,
        executed_size DECIMAL(16, 8) DEFAULT 0,
        
        limit_price DECIMAL(16, 2) NOT NULL,
        
        status VARCHAR(32) NOT NULL DEFAULT 'HIDDEN',
        visibility_score FLOAT DEFAULT 0.0,
        
        reveal_condition_type VARCHAR(32) NOT NULL,
        reveal_condition_json JSONB NOT NULL,
        condition_first_met_at TIMESTAMP,
        condition_confirmed_at TIMESTAMP,
        
        sizing_strategy_json JSONB,
        
        revealed_orders JSONB DEFAULT '[]'::jsonb,
        last_placement_at TIMESTAMP,
        
        target_movement NUMERIC,
        target_movement_type VARCHAR(1),
        cancel_reentry_policy_json JSONB DEFAULT '{}'::jsonb,
        cancel_reentry_state_json JSONB DEFAULT '{}'::jsonb,
        post_fill_retreat_policy_json JSONB DEFAULT '{"enabled": false}'::jsonb,
        
        reason VARCHAR(255),
        notes TEXT,

        -- Lifecycle inventory tracking (OrderInventory / StealthLifecycleHookRegistry)
        last_lifecycle_event VARCHAR(64),
        failure_reason       VARCHAR(512)
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        cursor.execute(
            "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS anchor_repricing_policy_json JSONB DEFAULT '{}'::jsonb"
        )
        cursor.execute(
            "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS anchor_repricing_state_json JSONB DEFAULT '{}'::jsonb"
        )
        cursor.execute(
            "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS cancel_reentry_policy_json JSONB DEFAULT '{}'::jsonb"
        )
        cursor.execute(
            "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS cancel_reentry_state_json JSONB DEFAULT '{}'::jsonb"
        )
        cursor.execute(
            """ALTER TABLE stealth_orders
               ADD COLUMN IF NOT EXISTS post_fill_retreat_policy_json
               JSONB DEFAULT '{"enabled": false}'::jsonb"""
        )
        cursor.execute(
            "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS "
            "last_lifecycle_event VARCHAR(64)"
        )
        cursor.execute(
            "ALTER TABLE stealth_orders ADD COLUMN IF NOT EXISTS "
            "failure_reason VARCHAR(512)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS "
            "idx_stealth_orders_last_lifecycle_event "
            "ON stealth_orders (last_lifecycle_event)"
        )
        print("stealth_orders table done.")


def update_stealth_order_target_movement(stealth_order_id: str, target_movement: Optional[float], target_movement_type: str = "P") -> bool:
    """DEPRECATED: writes to ``stealth_orders.target_movement`` were silently
    ignored by the engine, which reads ``target_movement`` exclusively from
    ``order_parent`` (see ``StealthOrderManager._resolve_target_movement_for_plan``).

    Retained as a thin shim that delegates to the canonical writer
    ``update_parent_order_target_movement`` so any external script still
    importing this name keeps working AND its updates actually take effect.

    New code MUST call ``update_parent_order_target_movement`` directly.

    Removed in: TBD (after ``stealth_orders.target_movement`` /
    ``target_movement_type`` columns are dropped from the schema).
    """
    return update_parent_order_target_movement(
        parent_order_id=stealth_order_id,
        target_movement=target_movement,
        target_movement_type=target_movement_type,
    )


def update_stealth_order_price_threshold(stealth_order_id: str, price_threshold: float, hold_duration_seconds: Optional[int] = None) -> bool:
    """Update price_threshold and optional hold_duration_seconds for a price-based stealth order.

    Args:
        stealth_order_id: UUID of the stealth order.
        price_threshold: New price threshold value.
        hold_duration_seconds: Optional hold duration seconds to persist in reveal_condition_json.

    Returns:
        True if update successful, False otherwise.
    """
    try:
        if hold_duration_seconds is not None:
            query = """
            UPDATE stealth_orders
            SET reveal_condition_json = jsonb_set(
                    jsonb_set(
                        COALESCE(reveal_condition_json, '{}'::jsonb),
                        '{price_threshold}',
                        to_jsonb(%s::numeric),
                        true
                    ),
                    '{hold_duration_seconds}',
                    to_jsonb(%s::int),
                    true
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE stealth_order_id = %s
              AND reveal_condition_type = 'price'
            """

            rows_affected = DB_CLIENT.execute_update(
                query,
                (price_threshold, hold_duration_seconds, stealth_order_id)
            )
        else:
            query = """
            UPDATE stealth_orders
            SET reveal_condition_json = jsonb_set(
                    COALESCE(reveal_condition_json, '{}'::jsonb),
                    '{price_threshold}',
                    to_jsonb(%s::numeric),
                    true
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE stealth_order_id = %s
              AND reveal_condition_type = 'price'
            """

            rows_affected = DB_CLIENT.execute_update(
                query,
                (price_threshold, stealth_order_id)
            )

        return rows_affected > 0
    except Exception as e:
        logger.error(f"âœ— Error updating stealth order threshold {stealth_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Update params - price_threshold: {price_threshold}, hold_duration_seconds: {hold_duration_seconds}")
        return False


def get_stealth_order_by_id(stealth_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a stealth order by its ID.
    
    Args:
        stealth_order_id: UUID of the stealth order
    
    Returns:
        Dictionary with stealth order data or None if not found
    
    Raises:
        DatabaseConnectionError: If database connection fails.
        OrderPersistenceError: If query execution fails.
    """
    try:
        query = """
        SELECT * FROM stealth_orders
        WHERE stealth_order_id = %s
        """
        
        results = DB_CLIENT.execute_query(query, (stealth_order_id,))
        return results[0] if results else None
    except Exception as e:
        error_msg = str(e).lower()
        if "connection" in error_msg or "timeout" in error_msg:
            raise DatabaseConnectionError(
                error_type="ConnectionError",
                message=f"Failed to connect to database while fetching stealth order",
                stealth_order_id=stealth_order_id,
            )
        else:
            raise OrderPersistenceError(
                error_type="PersistenceQueryError",
                message=f"Failed to fetch stealth order {stealth_order_id}: {str(e)}",
                stealth_order_id=stealth_order_id,
            )


def create_stealth_order_snapshots_table() -> None:
    """Create the stealth_order_snapshots table if it doesn't exist.
    
    Historical snapshots of stealth order state for auditing and analysis.
    Records periodic snapshots of order state along with market conditions at that moment,
    enabling analysis of execution quality and order lifecycle.
    
    Table Schema:
        - id: Auto-incrementing primary key
        - created_at: Timestamp when snapshot was recorded
        - stealth_order_id: UUID reference to stealth_orders table
        - status: Order status at snapshot time
        - revealed_size: Size revealed at snapshot time
        - remaining_size: Size still hidden at snapshot time
        - executed_size: Size filled at snapshot time
        - condition_met: Whether reveal condition was met at this snapshot
        - condition_first_met_at: When condition was first detected
        - market_price: Current market price for product
        - market_bid: Bid price
        - market_ask: Ask price
        - market_spread: Bid-ask spread
        - market_volume_1m: Trading volume in 1-minute window
        - Foreign key to stealth_orders.stealth_order_id (cascading delete)
    
    Purpose:
        - Audit trail of order execution quality
        - Market condition analysis (was spread narrow when revealed?)
        - Performance metrics (correlation with market conditions)
        - Debugging (replay order lifecycle with market state)
    
    Returns:
        None. Creates table as side effect.
    
    Raises:
        No exceptions - uses IF NOT EXISTS to prevent errors if table already exists.
    
    Example:
        >>> create_stealth_order_snapshots_table()
        stealth_order_snapshots table done.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS stealth_order_snapshots (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        stealth_order_id UUID NOT NULL,
        status VARCHAR(32),
        revealed_size DECIMAL(16, 8),
        remaining_size DECIMAL(16, 8),
        executed_size DECIMAL(16, 8),
        condition_met BOOLEAN,
        condition_first_met_at TIMESTAMP,
        
        market_price DECIMAL(16, 2),
        market_bid DECIMAL(16, 2),
        market_ask DECIMAL(16, 2),
        market_spread DECIMAL(16, 2),
        market_volume_1m DECIMAL(16, 8),
        
        FOREIGN KEY (stealth_order_id) REFERENCES stealth_orders(stealth_order_id) ON DELETE CASCADE
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("stealth_order_snapshots table done.")


def insert_stealth_order_snapshot(
    stealth_order_id: str,
    lifecycle_event: str,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Insert an event-scoped stealth snapshot for audit replay.

    Snapshots are intentionally written only at lifecycle milestones through the
    existing lifecycle hook path to avoid adding parallel trigger paths.
    """
    context = dict(context or {})
    try:
        status = context.get("status")
        if not status:
            status_map = {
                "CREATED": "HIDDEN",
                "CONDITION_WATCHING": "PENDING",
                "CONDITION_MET": "TRIGGERED",
                "REVEAL_SUCCEEDED": "REVEALED",
                "FILL_RECEIVED": "REVEALED",
                "EXECUTED": "EXECUTED",
                "CANCELLED": "CANCELLED",
            }
            status = status_map.get(lifecycle_event)

        market_price = context.get("market_price")
        market_bid = context.get("market_bid")
        market_ask = context.get("market_ask")
        market_spread = context.get("market_spread")
        if market_spread is None and market_bid is not None and market_ask is not None:
            try:
                market_spread = float(market_ask) - float(market_bid)
            except (TypeError, ValueError):
                market_spread = None

        if market_price is None:
            reveal_condition = context.get("reveal_condition") or {}
            if isinstance(reveal_condition, dict):
                market_price = reveal_condition.get("current_price")

        condition_met = lifecycle_event in {"CONDITION_MET", "REVEAL_SUCCEEDED", "FILL_RECEIVED", "EXECUTED"}

        query = """
        INSERT INTO stealth_order_snapshots (
            stealth_order_id,
            status,
            revealed_size,
            remaining_size,
            executed_size,
            condition_met,
            condition_first_met_at,
            market_price,
            market_bid,
            market_ask,
            market_spread,
            market_volume_1m
        )
        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """
        params = (
            stealth_order_id,
            status,
            context.get("size"),
            context.get("remaining_size"),
            context.get("executed_size"),
            condition_met,
            context.get("condition_first_met_at"),
            market_price,
            market_bid,
            market_ask,
            market_spread,
            context.get("market_volume_1m"),
        )
        rows = DB_CLIENT.execute_query(query, params)
        return rows[0]["id"] if rows else None
    except Exception as exc:
        logger.warning(
            f"insert_stealth_order_snapshot failed for {stealth_order_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None


def create_stealth_order_reveal_history_table() -> None:
    """Create the stealth_order_reveal_history table if it doesn't exist.
    
    Detailed history of each reveal event with market conditions and trigger reasons.
    Logs every reveal (order placement) event including the trigger reason and market
    state, enabling analysis of when and why orders were revealed.
    
    Table Schema:
        - id: Auto-incrementing primary key
        - created_at: Timestamp when reveal event was recorded
        - stealth_order_id: UUID reference to stealth_orders table
        - reveal_number: Sequence number of reveal event (1st, 2nd, 3rd, etc.)
        - revealed_size: Size placed in this reveal event
        - placement_price: Price at which order was placed
        - placed_order_id: UUID of the actual order placed on exchange
        - exchange_order_id: External Coinbase order UUID for audit/reference only
        - market_price: Market price when reveal occurred
        - market_bid: Bid price when reveal occurred
        - market_ask: Ask price when reveal occurred
        - market_spread: Bid-ask spread when reveal occurred
        - market_volume_1m: Trading volume in 1-minute window when reveal occurred
        - reveal_trigger_reason: Human-readable reason condition was triggered
        - reveal_trigger_data: JSONB with detailed trigger data (threshold, values, etc.)
        - Foreign key to stealth_orders.stealth_order_id (cascading delete)
        - UNIQUE constraint on (stealth_order_id, reveal_number) to prevent duplicates
    
    Purpose:
        - Detailed reveal audit trail (why and when)
        - Market analysis (price/spread when reveals occurred)
        - Timing analysis (how many reveals per order, spacing)
        - Condition evaluation debugging (what triggered reveal?)
    
    Returns:
        None. Creates table as side effect.
    
    Raises:
        No exceptions - uses IF NOT EXISTS to prevent errors if table already exists.
    
    Example:
        >>> create_stealth_order_reveal_history_table()
        stealth_order_reveal_history table done.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS stealth_order_reveal_history (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        stealth_order_id UUID NOT NULL,
        reveal_number INT NOT NULL,
        revealed_size DECIMAL(16, 8) NOT NULL,
        placement_price DECIMAL(16, 2),
        placed_order_id UUID,
        exchange_order_id VARCHAR(64),
        
        market_price DECIMAL(16, 2),
        market_bid DECIMAL(16, 2),
        market_ask DECIMAL(16, 2),
        market_spread DECIMAL(16, 2),
        market_volume_1m DECIMAL(16, 8),
        
        reveal_trigger_reason VARCHAR(255),
        reveal_trigger_data JSONB,
        
        FOREIGN KEY (stealth_order_id) REFERENCES stealth_orders(stealth_order_id) ON DELETE CASCADE,
        UNIQUE (stealth_order_id, reveal_number)
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        cursor.execute(
            "ALTER TABLE stealth_order_reveal_history ADD COLUMN IF NOT EXISTS exchange_order_id VARCHAR(64)"
        )
        # Reprice / placement audit columns. Added so anchor-repricing events
        # captured via _record_reveal_event preserve the full execution context
        # (placement uuid, success/cancel state, reprice reason, anchor target,
        # reference price source). Backwards-compatible: all nullable.
        reprice_audit_cols = [
            "placement_client_order_id UUID",
            "placement_status VARCHAR(32)",
            "placement_success BOOLEAN",
            "cancelled_for_reprice BOOLEAN",
            "reprice_reason VARCHAR(64)",
            "reveal_event_type VARCHAR(32)",
            "anchor_target_price DECIMAL(16, 2)",
            "anchor_max_price DECIMAL(16, 2)",
            "reference_price_source VARCHAR(64)",
            "reference_price DECIMAL(16, 2)",
            "reference_bid DECIMAL(16, 2)",
            "reference_ask DECIMAL(16, 2)",
            "market_source VARCHAR(32)",
        ]
        for col_def in reprice_audit_cols:
            col_name = col_def.split()[0]
            cursor.execute(
                f"ALTER TABLE stealth_order_reveal_history "
                f"ADD COLUMN IF NOT EXISTS {col_def}"
            )
        print("stealth_order_reveal_history table done.")


def create_stealth_order_lifecycle_history_table() -> None:
    """Create the stealth_order_lifecycle_history table if it doesn't exist.

    Stores one immutable row per stealth lifecycle transition so state changes can
    be audited without reconstructing them from mixed event sources.

    Table Schema:
        - stealth_order_id: UUID reference to the stealth order
        - lifecycle_event: StealthLifecycleEvent value (e.g. CONDITION_MET)
        - previous_lifecycle_event: Previously persisted event, if any
        - status_from / status_to: Derived stealth order statuses for the transition
        - event_time: UTC timestamp supplied by the lifecycle hook context
        - product_id / side / size / total_size / limit_price: event facts
        - reason / parent_order_id / placed_order_id / exchange_order_id / failure_reason: context
        - context_json: full event context payload for later inspection
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS stealth_order_lifecycle_history (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        stealth_order_id UUID NOT NULL,
        lifecycle_event VARCHAR(64) NOT NULL,
        previous_lifecycle_event VARCHAR(64),
        status_from VARCHAR(32),
        status_to VARCHAR(32),
        event_time TIMESTAMP,

        product_id VARCHAR(32),
        side VARCHAR(10),
        size DECIMAL(18, 8),
        total_size DECIMAL(18, 8),
        limit_price DECIMAL(18, 8),

        reason VARCHAR(255),
        parent_order_id UUID,
        placed_order_id UUID,
        exchange_order_id VARCHAR(64),
        failure_reason VARCHAR(512),
        context_json JSONB NOT NULL DEFAULT '{}'::jsonb,

        FOREIGN KEY (stealth_order_id) REFERENCES stealth_orders(stealth_order_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_stealth_lifecycle_history_order_id
        ON stealth_order_lifecycle_history (stealth_order_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_stealth_lifecycle_history_event
        ON stealth_order_lifecycle_history (lifecycle_event);
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        cursor.execute(
            "ALTER TABLE stealth_order_lifecycle_history ADD COLUMN IF NOT EXISTS exchange_order_id VARCHAR(64)"
        )
        print("stealth_order_lifecycle_history table done.")


def insert_order_parent(
    client_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
    target_movement: float,
    target_movement_type: str = "P",
    max_order_replacement: int = 0,
    current_order_replacement: int = 0,
    status: str = "pending",
    parent_order_id: Optional[str] = None,
    allow_partial_fills: bool = False,
    enable_hotpoint_replication: bool = False,
    auto_placed_by_hotpoint: bool = False,
    retail_portfolio_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    audit_id: Optional[str] = None,
    ownership_provenance: Optional[OrderOwnershipProvenance | str] = None,
) -> Optional[int]:
    """Insert a parent order into the order_parent table.
    
    Creates a new parent order entry with tracking for follow-up order replacement count.
    This operation is idempotent - if the parent order already exists, it returns the existing ID.
    
    Args:
        client_order_id: Unique client-assigned order ID.
        product_id: Product ID (e.g., 'BTC-USDC').
        side: Order side ('BUY' or 'SELL').
        size: Order size/quantity.
        price: Order price.
        target_movement: Target profit/movement percentage.
        target_movement_type: Type of target ('P' for percentage, 'A' for absolute, default 'P').
        max_order_replacement: Maximum number of follow-up orders allowed (default 0).
        current_order_replacement: Current count of replacements created (default 0).
        status: Order status (default 'pending').
        parent_order_id: Optional parent order UUID (for child/follow-up orders).
    
    Returns:
        The inserted order's database ID if successful, None if failed.
    
    Raises:
        OrderPersistenceError: If database insertion fails.
    """
    _require_uuid_text(client_order_id, "client_order_id", client_order_id=client_order_id)
    if parent_order_id is not None:
        _require_uuid_text(parent_order_id, "parent_order_id", client_order_id=client_order_id)
    if retail_portfolio_id is not None:
        _require_uuid_text(
            retail_portfolio_id,
            "retail_portfolio_id",
            client_order_id=client_order_id,
        )
    normalized_provenance = _normalize_ownership_provenance(
        ownership_provenance,
        client_order_id=client_order_id,
    )

    # Check if parent order already exists (handles race condition with multiple threads)
    existing_parent = get_parent_order(client_order_id)
    if existing_parent:
        existing_provenance_raw = existing_parent.get("ownership_provenance")
        strict_immutable_reuse = (
            normalized_provenance is not None
            or existing_provenance_raw is not None
        )
        if strict_immutable_reuse:
            try:
                existing_provenance = _normalize_ownership_provenance(
                    existing_provenance_raw,
                    client_order_id=client_order_id,
                )
            except OrderPersistenceError:
                existing_provenance = None

            def numeric_equal(left: Any, right: Any) -> bool:
                try:
                    return Decimal(str(left)) == Decimal(str(right))
                except (InvalidOperation, TypeError, ValueError):
                    return False

            immutable_facts_match = all(
                (
                    str(existing_parent.get("product_id") or "")
                    == str(product_id),
                    str(existing_parent.get("side") or "").upper()
                    == str(side).upper(),
                    numeric_equal(existing_parent.get("size"), size),
                    numeric_equal(existing_parent.get("price"), price),
                    (
                        str(existing_parent.get("parent_order_id"))
                        if existing_parent.get("parent_order_id")
                        else None
                    )
                    == (str(parent_order_id) if parent_order_id else None),
                    existing_provenance == normalized_provenance,
                    (
                        str(existing_parent.get("retail_portfolio_id"))
                        if existing_parent.get("retail_portfolio_id")
                        else None
                    )
                    == (str(retail_portfolio_id) if retail_portfolio_id else None),
                    (
                        str(existing_parent.get("correlation_id"))
                        if existing_parent.get("correlation_id")
                        else None
                    )
                    == (str(correlation_id) if correlation_id else None),
                    (
                        str(existing_parent.get("audit_id"))
                        if existing_parent.get("audit_id")
                        else None
                    )
                    == (str(audit_id) if audit_id else None),
                )
            )
            if not immutable_facts_match:
                raise OrderPersistenceError(
                    error_type="OrderParentIdentityConflict",
                    message=(
                        "Existing order_parent immutable facts conflict with "
                        f"requested identity for {client_order_id}"
                    ),
                    client_order_id=client_order_id,
                )
        if retail_portfolio_id is not None and str(
            existing_parent.get("retail_portfolio_id") or ""
        ) != str(retail_portfolio_id):
            raise OrderPersistenceError(
                error_type="PortfolioScopeConflict",
                message=(
                    "Existing order_parent portfolio scope conflicts with "
                    f"requested scope for {client_order_id}"
                ),
                client_order_id=client_order_id,
            )
        logger.info(f"âœ“ Parent order already exists: {client_order_id} (DB ID: {existing_parent['id']})")
        return existing_parent['id']
    
    query = """
    INSERT INTO order_parent (
        client_order_id,
        product_id,
        side,
        size,
        price,
        status,
        target_movement,
        target_movement_type,
        max_order_replacement,
        current_order_replacement,
        parent_order_id,
        allow_partial_fills,
        enable_hotpoint_replication,
        auto_placed_by_hotpoint,
        retail_portfolio_id,
        correlation_id,
        audit_id,
        ownership_provenance
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """
    params = (
        client_order_id,
        product_id,
        side,
        size,
        price,
        status,
        target_movement,
        target_movement_type,
        int(max_order_replacement),
        int(current_order_replacement),
        parent_order_id,
        bool(allow_partial_fills),
        bool(enable_hotpoint_replication),
        bool(auto_placed_by_hotpoint),
        retail_portfolio_id,
        correlation_id,
        audit_id,
        normalized_provenance,
    )

    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]["id"]
            row_kind = "Child" if parent_order_id else "Root parent"
            logger.info(
                f"âœ“ {row_kind} order inserted: {client_order_id} (DB ID: {inserted_id}, "
                f"product: {product_id}, {side} {size} @ {price}"
                + (f", parent: {parent_order_id})" if parent_order_id else ")")
            )
            return inserted_id

        logger.warning(f"Failed to retrieve inserted order ID for: {client_order_id} - query executed but no result returned")
        return None
    except Exception as e:
        error_msg = str(e).lower()
        if "connection" in error_msg or "timeout" in error_msg:
            raise DatabaseConnectionError(
                error_type="ConnectionError",
                message=f"Failed to connect to database while inserting parent order",
                client_order_id=client_order_id,
            )
        else:
            raise OrderPersistenceError(
                error_type="InsertionError",
                message=f"Failed to insert parent order {client_order_id}: {str(e)}",
                client_order_id=client_order_id,
            )


def persist_operator_stealth_root_atomic(
    *,
    order: Dict[str, Any],
    target_movement: float,
    target_movement_type: str,
    portfolio_id: str,
    correlation_id: str,
    audit_id: str,
    definition_revision: int,
    definition_sha256: str,
) -> tuple[int, bool]:
    """Atomically persist one claimed operator definition as a stealth root.

    The operator reveal repository installs a trigger that permits the
    reserved definition identity only while its exact revision/hash is in the
    durable ``MATERIALIZING`` state.  This writer supplies the canonical
    ``order_parent`` ownership row and ``stealth_orders`` row in one database
    transaction; it performs no Coinbase call.
    """

    client_order_id = str(order.get("stealth_order_id") or "")
    _require_uuid_text(
        client_order_id,
        "stealth_order_id",
        client_order_id=client_order_id,
    )
    if order.get("parent_order_id") is not None:
        raise OrderPersistenceError(
            error_type="OperatorStealthRootNested",
            message="Operator stealth materialization requires a root order",
            client_order_id=client_order_id,
        )
    if (
        not isinstance(definition_revision, int)
        or isinstance(definition_revision, bool)
        or definition_revision < 1
        or not isinstance(definition_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", definition_sha256) is None
    ):
        raise OrderPersistenceError(
            error_type="OperatorStealthDefinitionBindingInvalid",
            message="Operator stealth definition binding is invalid",
            client_order_id=client_order_id,
        )
    _require_uuid_text(
        portfolio_id,
        "portfolio_id",
        client_order_id=client_order_id,
    )
    if not str(correlation_id or "").strip() or not str(audit_id or "").strip():
        raise OrderPersistenceError(
            error_type="OperatorStealthAuditBindingInvalid",
            message="Operator stealth audit binding is invalid",
            client_order_id=client_order_id,
        )

    product_id = str(order.get("product_id") or "")
    side = str(order.get("side") or "").upper()
    total_size = order.get("total_size")
    limit_price = order.get("limit_price")

    def row_dict(cursor: Any, row: Any) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        return dict(
            zip(
                [description[0] for description in cursor.description],
                row,
            )
        )

    def numeric_equal(left: Any, right: Any) -> bool:
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except (InvalidOperation, TypeError, ValueError):
            return False

    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (31873, client_order_id),
        )
        cursor.execute(
            """SELECT id, product_id, side, size, price, parent_order_id,
                      ownership_provenance, retail_portfolio_id,
                      correlation_id, audit_id
               FROM order_parent WHERE client_order_id = %s""",
            (client_order_id,),
        )
        parent_row = row_dict(cursor, cursor.fetchone())
        cursor.execute(
            """SELECT product_id, side, total_size, limit_price,
                      parent_order_id, reveal_condition_json
               FROM stealth_orders WHERE stealth_order_id = %s""",
            (client_order_id,),
        )
        stealth_row = row_dict(cursor, cursor.fetchone())

        if parent_row and not all(
            (
                str(parent_row.get("product_id") or "") == product_id,
                str(parent_row.get("side") or "").upper() == side,
                numeric_equal(parent_row.get("size"), total_size),
                numeric_equal(parent_row.get("price"), limit_price),
                parent_row.get("parent_order_id") is None,
                str(parent_row.get("ownership_provenance") or "")
                == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value,
                str(parent_row.get("retail_portfolio_id") or "")
                == portfolio_id,
                str(parent_row.get("correlation_id") or "")
                == correlation_id,
                str(parent_row.get("audit_id") or "") == audit_id,
            )
        ):
            raise OrderPersistenceError(
                error_type="OperatorStealthParentIdentityConflict",
                message="Existing operator stealth parent identity conflicts",
                client_order_id=client_order_id,
            )
        if stealth_row and not all(
            (
                str(stealth_row.get("product_id") or "") == product_id,
                str(stealth_row.get("side") or "").upper() == side,
                numeric_equal(stealth_row.get("total_size"), total_size),
                numeric_equal(stealth_row.get("limit_price"), limit_price),
                stealth_row.get("parent_order_id") is None,
                bool(
                    (stealth_row.get("reveal_condition_json") or {}).get(
                        "operator_manual_reveal_required"
                    )
                ),
            )
        ):
            raise OrderPersistenceError(
                error_type="OperatorStealthRuntimeIdentityConflict",
                message="Existing operator stealth runtime identity conflicts",
                client_order_id=client_order_id,
            )

        if parent_row:
            parent_row_id = int(parent_row["id"])
        else:
            cursor.execute(
                """INSERT INTO order_parent (
                       client_order_id, product_id, side, size, price, status,
                       target_movement, target_movement_type,
                       max_order_replacement, current_order_replacement,
                       parent_order_id, allow_partial_fills,
                       enable_hotpoint_replication, auto_placed_by_hotpoint,
                       ownership_provenance, retail_portfolio_id,
                       correlation_id, audit_id
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, 0, NULL, %s, FALSE, FALSE, %s, %s, %s, %s
                   ) RETURNING id""",
                (
                    client_order_id,
                    product_id,
                    side,
                    total_size,
                    limit_price,
                    OrderStatus.PENDING.value,
                    target_movement,
                    target_movement_type,
                    int(order.get("max_order_replacements") or 0),
                    bool(order.get("allow_partial_fills", False)),
                    OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value,
                    portfolio_id,
                    correlation_id,
                    audit_id,
                ),
            )
            inserted_parent = cursor.fetchone()
            if not inserted_parent:
                raise OrderPersistenceError(
                    error_type="OperatorStealthParentInsertMissing",
                    message="Operator stealth parent insert returned no id",
                    client_order_id=client_order_id,
                )
            parent_row_id = int(inserted_parent[0])

        stealth_row_created = stealth_row is None
        if stealth_row_created:
            cursor.execute(
                """INSERT INTO stealth_orders (
                       stealth_order_id, product_id, side, total_size,
                       remaining_size, limit_price, status,
                       reveal_condition_type, reveal_condition_json,
                       sizing_strategy_json, reason, notes, parent_order_id,
                       anchor_repricing_policy_json,
                       anchor_repricing_state_json,
                       cancel_reentry_policy_json,
                       cancel_reentry_state_json,
                       post_fill_retreat_policy_json
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, NULL, %s, %s, %s, %s, %s
                   )""",
                (
                    client_order_id,
                    product_id,
                    side,
                    total_size,
                    order.get("remaining_size"),
                    limit_price,
                    order.get("status", StealthOrderStatus.HIDDEN.value),
                    order.get("reveal_condition_type", "time_delay"),
                    json.dumps(
                        order.get("reveal_condition_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get("sizing_strategy_json", {}),
                        default=_json_default_for_db,
                    ),
                    order.get("reason", ""),
                    order.get("notes", ""),
                    json.dumps(
                        order.get("anchor_repricing_policy_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get("anchor_repricing_state_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get("cancel_reentry_policy_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get("cancel_reentry_state_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get(
                            "post_fill_retreat_policy_json",
                            {"enabled": False},
                        ),
                        default=_json_default_for_db,
                    ),
                ),
            )
    return parent_row_id, stealth_row_created


def persist_filled_follow_up_atomic(
    *,
    order: Dict[str, Any],
    target_movement: float,
    target_movement_type: str = "P",
) -> tuple[int, bool]:
    """Atomically persist both durable rows for one FILLED follow-up.

    The deterministic ``stealth_order_id`` is also the child
    ``client_order_id``. Replays with the same identity are idempotent; an
    existing row with conflicting immutable linkage fails closed.

    Returns:
        ``(order_parent_id, stealth_row_created)``.
    """

    client_order_id = str(order.get("stealth_order_id") or "")
    parent_order_id = str(order.get("parent_order_id") or "")
    _require_uuid_text(
        client_order_id,
        "stealth_order_id",
        client_order_id=client_order_id,
    )
    _require_uuid_text(
        parent_order_id,
        "parent_order_id",
        client_order_id=client_order_id,
    )

    product_id = str(order.get("product_id") or "")
    side = str(order.get("side") or "").upper()
    total_size = order.get("total_size")
    limit_price = order.get("limit_price")

    def row_dict(cursor, row) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))

    def numeric_equal(left: Any, right: Any) -> bool:
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except (InvalidOperation, TypeError, ValueError):
            return False

    def raise_conflict(source: str) -> None:
        raise OrderPersistenceError(
            error_type="FilledFollowUpIdentityConflict",
            message=(
                f"Existing {source} row conflicts with deterministic FILLED "
                f"follow-up {client_order_id}"
            ),
            client_order_id=client_order_id,
        )

    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(
            """SELECT product_id, parent_order_id, ownership_provenance,
                      retail_portfolio_id, correlation_id, audit_id
               FROM order_parent WHERE client_order_id = %s""",
            (parent_order_id,),
        )
        root_parent_row = row_dict(cursor, cursor.fetchone())
        if root_parent_row is None:
            raise OrderPersistenceError(
                error_type="FilledFollowUpRootMissing",
                message=(
                    "Atomic FILLED follow-up root order_parent row is missing "
                    f"for {parent_order_id}"
                ),
                client_order_id=client_order_id,
            )
        if root_parent_row.get("parent_order_id"):
            raise OrderPersistenceError(
                error_type="FilledFollowUpNestedRoot",
                message=(
                    "Atomic FILLED follow-up rejected nested root "
                    f"{parent_order_id}"
                ),
                client_order_id=client_order_id,
            )
        if str(root_parent_row.get("product_id") or "") != product_id:
            raise OrderPersistenceError(
                error_type="FilledFollowUpProductConflict",
                message=(
                    "Atomic FILLED follow-up product conflicts with root "
                    f"{parent_order_id}"
                ),
                client_order_id=client_order_id,
            )
        root_provenance = _normalize_ownership_provenance(
            root_parent_row.get("ownership_provenance"),
            client_order_id=client_order_id,
        )
        if root_provenance == OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value:
            raise OrderPersistenceError(
                error_type="FilledFollowUpExternalRoot",
                message=(
                    "Atomic FILLED follow-up rejected external root "
                    f"{parent_order_id}"
                ),
                client_order_id=client_order_id,
            )
        root_portfolio_id = (
            str(root_parent_row.get("retail_portfolio_id"))
            if root_parent_row and root_parent_row.get("retail_portfolio_id")
            else None
        )
        root_correlation_id = (
            str(root_parent_row.get("correlation_id"))
            if root_parent_row and root_parent_row.get("correlation_id")
            else None
        )
        root_audit_id = (
            str(root_parent_row.get("audit_id"))
            if root_parent_row and root_parent_row.get("audit_id")
            else None
        )
        if root_provenance == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value:
            if root_portfolio_id is None:
                raise OrderPersistenceError(
                    error_type="FilledFollowUpPortfolioScopeMissing",
                    message="Admin root portfolio scope is required",
                    client_order_id=client_order_id,
                )
            if root_correlation_id is None:
                raise OrderPersistenceError(
                    error_type="FilledFollowUpCorrelationMissing",
                    message="Admin root correlation_id is required",
                    client_order_id=client_order_id,
                )
            if root_audit_id is None:
                raise OrderPersistenceError(
                    error_type="FilledFollowUpAuditMissing",
                    message="Admin root audit_id is required",
                    client_order_id=client_order_id,
                )
        child_provenance = (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
            if root_provenance
            == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            else root_provenance
        )

        cursor.execute(
            """SELECT id, product_id, side, size, price, parent_order_id,
                      ownership_provenance, retail_portfolio_id,
                      correlation_id, audit_id
               FROM order_parent WHERE client_order_id = %s""",
            (client_order_id,),
        )
        parent_row = row_dict(cursor, cursor.fetchone())

        cursor.execute(
            """SELECT product_id, side, total_size, limit_price,
                      parent_order_id
               FROM stealth_orders WHERE stealth_order_id = %s""",
            (client_order_id,),
        )
        stealth_row = row_dict(cursor, cursor.fetchone())

        if parent_row and not all(
            (
                str(parent_row.get("product_id") or "") == product_id,
                str(parent_row.get("side") or "").upper() == side,
                numeric_equal(parent_row.get("size"), total_size),
                numeric_equal(parent_row.get("price"), limit_price),
                str(parent_row.get("parent_order_id") or "")
                == parent_order_id,
                (
                    str(parent_row.get("ownership_provenance"))
                    if parent_row.get("ownership_provenance")
                    else None
                )
                == child_provenance,
                (
                    str(parent_row.get("retail_portfolio_id"))
                    if parent_row.get("retail_portfolio_id")
                    else None
                )
                == root_portfolio_id,
                (
                    str(parent_row.get("correlation_id"))
                    if parent_row.get("correlation_id")
                    else None
                )
                == root_correlation_id,
                (
                    str(parent_row.get("audit_id"))
                    if parent_row.get("audit_id")
                    else None
                )
                == root_audit_id,
            )
        ):
            raise_conflict("order_parent")

        if stealth_row and not all(
            (
                str(stealth_row.get("product_id") or "") == product_id,
                str(stealth_row.get("side") or "").upper() == side,
                numeric_equal(stealth_row.get("total_size"), total_size),
                numeric_equal(stealth_row.get("limit_price"), limit_price),
                str(stealth_row.get("parent_order_id") or "")
                == parent_order_id,
            )
        ):
            raise_conflict("stealth_orders")

        if parent_row:
            parent_row_id = int(parent_row["id"])
        else:
            cursor.execute(
                """INSERT INTO order_parent (
                       client_order_id, product_id, side, size, price, status,
                       target_movement, target_movement_type,
                       max_order_replacement, current_order_replacement,
                       parent_order_id, allow_partial_fills,
                       enable_hotpoint_replication, auto_placed_by_hotpoint,
                       ownership_provenance, retail_portfolio_id,
                       correlation_id, audit_id
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s,
                       0, 0, %s, FALSE, FALSE, FALSE, %s, %s, %s, %s
                   ) RETURNING id""",
                (
                    client_order_id,
                    product_id,
                    side,
                    total_size,
                    limit_price,
                    OrderStatus.PENDING.value,
                    target_movement,
                    target_movement_type,
                    parent_order_id,
                    child_provenance,
                    root_portfolio_id,
                    root_correlation_id,
                    root_audit_id,
                ),
            )
            inserted_parent = cursor.fetchone()
            if not inserted_parent:
                raise OrderPersistenceError(
                    error_type="FilledFollowUpParentInsertMissing",
                    message="Atomic FILLED follow-up parent insert returned no id",
                    client_order_id=client_order_id,
                )
            parent_row_id = int(inserted_parent[0])

        stealth_row_created = stealth_row is None
        if stealth_row_created:
            cursor.execute(
                """INSERT INTO stealth_orders (
                       stealth_order_id, product_id, side, total_size,
                       remaining_size, limit_price, status,
                       reveal_condition_type, reveal_condition_json,
                       sizing_strategy_json, reason, notes, parent_order_id,
                       anchor_repricing_policy_json,
                       anchor_repricing_state_json,
                       cancel_reentry_policy_json,
                       cancel_reentry_state_json,
                       post_fill_retreat_policy_json
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    client_order_id,
                    product_id,
                    side,
                    total_size,
                    order.get("remaining_size"),
                    limit_price,
                    order.get("status", "HIDDEN"),
                    order.get("reveal_condition_type", "time_delay"),
                    json.dumps(
                        order.get("reveal_condition_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get("sizing_strategy_json", {}),
                        default=_json_default_for_db,
                    ),
                    order.get("reason", ""),
                    order.get("notes", ""),
                    parent_order_id,
                    json.dumps(
                        order.get("anchor_repricing_policy_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get("anchor_repricing_state_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get("cancel_reentry_policy_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get("cancel_reentry_state_json", {}),
                        default=_json_default_for_db,
                    ),
                    json.dumps(
                        order.get(
                            "post_fill_retreat_policy_json",
                            {"enabled": False},
                        ),
                        default=_json_default_for_db,
                    ),
                ),
            )

    return parent_row_id, stealth_row_created


def prepare_controlled_admin_first_child_reveal_atomic(
    *,
    stealth_order_id: str,
    expected_root_client_order_id: str,
    expected_portfolio_id: str,
    submitted_limit_price: float,
    quote_increment: str,
    max_notional_usdc: float,
    market_bid: Any,
    market_source: str,
    market_observed_at: datetime,
    approval_snapshot_id: str,
    admission_audit_id: str,
    cap_guard_decision_id: str,
    reconciliation_plan_id: str,
    batch_id: str,
    batch_slot: int,
    authority_id: str,
    expected_prior_preparation_sha256: Optional[str] = None,
    controlled_plan_sha256: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Atomically prepare one owned first-generation Admin child for reveal.

    This is deliberately narrower than a general stealth reprice. It accepts
    only the restart-stable first child of one FILLED ``ADMIN_MANUAL_ROOT`` on
    the exact Test portfolio and records the original prices plus the complete
    controlled-live admission evidence before changing either durable row.
    Nothing in this function places or reveals an exchange order.
    """

    child_id = str(stealth_order_id or "").strip()
    root_id = str(expected_root_client_order_id or "").strip()
    portfolio_id = str(expected_portfolio_id or "").strip()
    _require_uuid_text(child_id, "stealth_order_id", client_order_id=child_id)
    _require_uuid_text(root_id, "expected_root_client_order_id", client_order_id=child_id)
    _require_uuid_text(portfolio_id, "expected_portfolio_id", client_order_id=child_id)

    if controlled_plan_sha256 is not None and (
        not isinstance(controlled_plan_sha256, str)
        or len(controlled_plan_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in controlled_plan_sha256
        )
    ):
        raise _controlled_admin_child_persistence_error(
            "controlled_plan_sha256 must be exactly 64 lowercase hexadecimal characters",
            client_order_id=child_id,
        )

    evidence_ids = {
        "approval_snapshot_id": approval_snapshot_id,
        "admission_audit_id": admission_audit_id,
        "cap_guard_decision_id": cap_guard_decision_id,
        "reconciliation_plan_id": reconciliation_plan_id,
        "batch_id": batch_id,
        "authority_id": authority_id,
    }
    missing_evidence = sorted(
        key for key, value in evidence_ids.items() if not str(value or "").strip()
    )
    if missing_evidence:
        raise _controlled_admin_child_persistence_error(
            "controlled reveal audit evidence is incomplete: "
            + ",".join(missing_evidence),
            client_order_id=child_id,
        )
    if (
        not isinstance(batch_slot, int)
        or isinstance(batch_slot, bool)
        or batch_slot < 1
        or batch_slot > 10
    ):
        raise _controlled_admin_child_persistence_error(
            "batch_slot must be an integer from 1 through 10",
            client_order_id=child_id,
        )

    requested_price = _finite_positive_decimal(
        submitted_limit_price,
        field_name="submitted_limit_price",
        client_order_id=child_id,
    )
    increment = _finite_positive_decimal(
        quote_increment,
        field_name="quote_increment",
        client_order_id=child_id,
    )
    bid = _finite_positive_decimal(
        market_bid,
        field_name="market_bid",
        client_order_id=child_id,
    )
    normalized_market_source = str(market_source or "").strip().lower()
    if normalized_market_source not in SPOT_STANDING_MARKET_SOURCES:
        raise _controlled_admin_child_persistence_error(
            "controlled reveal market source is not canonical standing evidence",
            client_order_id=child_id,
        )
    hard_cap = _finite_positive_decimal(
        max_notional_usdc,
        field_name="max_notional_usdc",
        client_order_id=child_id,
    )
    prepared_price = (
        (requested_price / increment).to_integral_value(rounding=ROUND_CEILING)
        * increment
    )
    minimum_standing_price = bid * Decimal("1.5")
    if prepared_price < minimum_standing_price:
        raise _controlled_admin_child_persistence_error(
            "submitted SELL limit must be at least 150% of the fresh bid",
            client_order_id=child_id,
        )

    if (
        not isinstance(market_observed_at, datetime)
        or market_observed_at.tzinfo is None
        or market_observed_at.utcoffset() is None
    ):
        raise _controlled_admin_child_persistence_error(
            "market_observed_at must be timezone-aware fresh bid evidence",
            client_order_id=child_id,
        )
    observed_at_utc = market_observed_at.astimezone(timezone.utc)
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    market_age = Decimal(str((now_utc - observed_at_utc).total_seconds()))
    if market_age < 0 or market_age > _CONTROLLED_ADMIN_CHILD_MAX_MARKET_AGE_SECONDS:
        raise _controlled_admin_child_persistence_error(
            "controlled reveal requires fresh, non-future bid evidence",
            client_order_id=child_id,
        )

    expected_child_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"coinbase://filled-follow-up/{root_id}/{root_id}",
        )
    )
    if child_id != expected_child_id:
        raise _controlled_admin_child_persistence_error(
            "child is not the deterministic first ADMIN_FILL_FOLLOW_UP for the root",
            client_order_id=child_id,
        )

    def row_dict(cursor, row) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))

    def row_dicts(cursor, rows) -> List[Dict[str, Any]]:
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    def reject(message: str) -> NoReturn:
        raise _controlled_admin_child_persistence_error(
            message,
            client_order_id=child_id,
        )

    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM order_parent WHERE client_order_id = %s FOR UPDATE",
            (root_id,),
        )
        root_row = row_dict(cursor, cursor.fetchone())
        cursor.execute(
            "SELECT * FROM order_parent WHERE client_order_id = %s FOR UPDATE",
            (child_id,),
        )
        child_row = row_dict(cursor, cursor.fetchone())
        cursor.execute(
            "SELECT * FROM stealth_orders WHERE stealth_order_id = %s FOR UPDATE",
            (child_id,),
        )
        stealth_row = row_dict(cursor, cursor.fetchone())
        cursor.execute(
            """SELECT client_order_id
                 FROM order_parent
                WHERE parent_order_id = %s
                  AND ownership_provenance = %s
                FOR UPDATE""",
            (root_id, OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value),
        )
        admin_children = row_dicts(cursor, cursor.fetchall())

        if child_row is None or root_row is None or stealth_row is None:
            reject("controlled reveal requires existing root, child, and stealth rows")
        if str(child_row.get("client_order_id") or "") != child_id:
            reject("child is not the deterministic current row")
        if len(admin_children) != 1 or str(
            admin_children[0].get("client_order_id") or ""
        ) != child_id:
            reject("root must have exactly one current ADMIN_FILL_FOLLOW_UP child")

        if str(root_row.get("client_order_id") or "") != root_id:
            reject("root ownership row mismatch")
        if root_row.get("parent_order_id"):
            reject("controlled reveal root must be flat and non-nested")
        if str(root_row.get("ownership_provenance") or "") != (
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
        ):
            reject("root ownership provenance is not ADMIN_MANUAL_ROOT")
        if str(root_row.get("status") or "").upper() != OrderStatus.FILLED.value:
            reject("controlled reveal root must be FILLED")
        if str(root_row.get("side") or "").upper() != OrderSide.BUY.value:
            reject("controlled reveal root must be BUY")
        if not str(root_row.get("exchange_order_id") or "").strip():
            reject("controlled reveal root exchange fill evidence is missing")

        if str(child_row.get("parent_order_id") or "") != root_id:
            reject("controlled reveal child does not link flat to the expected root")
        if str(child_row.get("ownership_provenance") or "") != (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
        ):
            reject("child ownership provenance is not ADMIN_FILL_FOLLOW_UP")
        if str(child_row.get("status") or "").upper() != OrderStatus.PENDING.value:
            reject("controlled reveal child tracking row must be PENDING")
        if child_row.get("exchange_order_id"):
            reject("controlled reveal child must be unsubmitted")

        rows = (root_row, child_row, stealth_row)
        if any(str(row.get("product_id") or "") != "BTC-USDC" for row in rows):
            reject("controlled reveal is scoped only to BTC-USDC")
        if str(child_row.get("side") or "").upper() != OrderSide.SELL.value or str(
            stealth_row.get("side") or ""
        ).upper() != OrderSide.SELL.value:
            reject("controlled reveal child must be SELL")
        if str(stealth_row.get("parent_order_id") or "") != root_id:
            reject("stealth child does not link flat to the expected root")
        if str(stealth_row.get("stealth_order_id") or "") != child_id:
            reject("stealth child identity mismatch")

        scoped_portfolios = {
            str(root_row.get("retail_portfolio_id") or ""),
            str(child_row.get("retail_portfolio_id") or ""),
        }
        if scoped_portfolios != {portfolio_id}:
            reject("root/child portfolio does not match the exact Test portfolio")
        root_correlation_id = str(root_row.get("correlation_id") or "").strip()
        root_audit_id = str(root_row.get("audit_id") or "").strip()
        if (
            not root_correlation_id
            or str(child_row.get("correlation_id") or "").strip()
            != root_correlation_id
        ):
            reject("root/child correlation trace mismatch")
        if (
            not root_audit_id
            or str(child_row.get("audit_id") or "").strip() != root_audit_id
        ):
            reject("root/child audit trace mismatch")

        original_stealth_status = str(
            stealth_row.get("status") or ""
        ).upper()
        if original_stealth_status not in {
            StealthOrderStatus.HIDDEN.value,
            StealthOrderStatus.PENDING.value,
            StealthOrderStatus.TRIGGERED.value,
        }:
            reject(
                "controlled reveal stealth child must remain in an "
                "unsubmitted pre-exchange condition state"
            )
        revealed_orders = _json_list(stealth_row.get("revealed_orders"))
        try:
            total_size = Decimal(str(stealth_row.get("total_size")))
            remaining_size = Decimal(str(stealth_row.get("remaining_size")))
            revealed_size = Decimal(str(stealth_row.get("revealed_size") or 0))
            executed_size = Decimal(str(stealth_row.get("executed_size") or 0))
            tracked_size = Decimal(str(child_row.get("size")))
            root_size = Decimal(str(root_row.get("size")))
        except (InvalidOperation, TypeError, ValueError):
            reject("controlled reveal child size evidence is invalid")
        if (
            not total_size.is_finite()
            or total_size <= 0
            or total_size != remaining_size
            or total_size != tracked_size
            or total_size != root_size
            or revealed_size != 0
            or executed_size != 0
            or revealed_orders
            or stealth_row.get("last_placement_at") is not None
        ):
            reject("controlled reveal child must be wholly hidden and unsubmitted")

        condition = _json_mapping(stealth_row.get("reveal_condition_json"))
        if (
            str(stealth_row.get("reveal_condition_type") or "")
            != RevealConditionType.PRICE_THRESHOLD.value
            or str(condition.get("type") or "")
            != RevealConditionType.PRICE_THRESHOLD.value
            or str(condition.get("direction") or "").lower() != "above"
            or str(condition.get("standing_price_limit_policy") or "")
            != "admin_test_profile"
            or str(stealth_row.get("reason") or "") != "follow_up_replacement"
        ):
            reject("controlled reveal child policy evidence is invalid")

        state = _json_mapping(stealth_row.get("anchor_repricing_state_json"))
        prior_preparation_value = state.get(
            "controlled_admin_first_child_reveal_preparation"
        )
        expected_prior_hash = str(
            expected_prior_preparation_sha256 or ""
        ).strip()
        supersession_record: Optional[Dict[str, Any]] = None
        sealed_prior_preparation: Optional[Dict[str, Any]] = None
        if prior_preparation_value:
            if not expected_prior_hash:
                reject("controlled reveal child was already prepared")
            if len(expected_prior_hash) != 64 or any(
                character not in "0123456789abcdef"
                for character in expected_prior_hash
            ):
                reject("controlled reveal prior preparation hash is invalid")
            if not secrets.compare_digest(
                expected_prior_hash,
                _SEALED_V8_CONTROLLED_CHILD_RECOVERY_SHA256,
            ):
                reject(
                    "controlled reveal prior preparation hash is not authorized "
                    "for the sealed v8 recovery"
                )
            prior_preparation = _json_mapping(prior_preparation_value)
            if not prior_preparation:
                reject("controlled reveal prior preparation is malformed")
            prior_encoded = json.dumps(
                prior_preparation,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
            observed_prior_hash = hashlib.sha256(prior_encoded).hexdigest()
            if not secrets.compare_digest(
                observed_prior_hash,
                expected_prior_hash,
            ):
                reject("controlled reveal prior preparation hash mismatch")
            if any(
                prior_preparation.get(field_name) != expected_value
                for field_name, expected_value in (
                    _SEALED_V8_CONTROLLED_CHILD_RECOVERY_BINDING.items()
                )
            ):
                reject("controlled reveal prior preparation is not the sealed v8 recovery")
            sealed_prior_preparation = prior_preparation
            required_prior_values = {
                "authority_id": prior_preparation.get("authority_id"),
                "approval_snapshot_id": prior_preparation.get(
                    "approval_snapshot_id"
                ),
                "admission_audit_id": prior_preparation.get(
                    "admission_audit_id"
                ),
                "cap_guard_decision_id": prior_preparation.get(
                    "cap_guard_decision_id"
                ),
                "reconciliation_plan_id": prior_preparation.get(
                    "reconciliation_plan_id"
                ),
                "batch_id": prior_preparation.get("batch_id"),
                "root_exchange_order_id": prior_preparation.get(
                    "root_exchange_order_id"
                ),
            }
            if any(
                not str(value or "").strip()
                for value in required_prior_values.values()
            ):
                reject("controlled reveal prior preparation evidence is incomplete")
            if (
                str(prior_preparation.get("root_client_order_id") or "")
                != root_id
                or str(prior_preparation.get("stealth_order_id") or "")
                != child_id
                or str(prior_preparation.get("portfolio_id") or "")
                != portfolio_id
                or prior_preparation.get("batch_slot") != batch_slot
                or str(prior_preparation.get("root_exchange_order_id") or "")
                != str(root_row.get("exchange_order_id") or "")
            ):
                reject("controlled reveal prior preparation scope mismatch")
            if (
                str(prior_preparation.get("batch_id") or "") == str(batch_id)
                or str(prior_preparation.get("authority_id") or "")
                == str(authority_id)
                or str(prior_preparation.get("approval_snapshot_id") or "")
                == str(approval_snapshot_id)
                or str(prior_preparation.get("admission_audit_id") or "")
                == str(admission_audit_id)
                or str(prior_preparation.get("cap_guard_decision_id") or "")
                == str(cap_guard_decision_id)
                or str(prior_preparation.get("reconciliation_plan_id") or "")
                == str(reconciliation_plan_id)
            ):
                reject("controlled reveal supersession must use fresh authority")
            history_value = state.get(
                "controlled_admin_first_child_reveal_preparation_history"
            )
            if history_value is None:
                history: List[Dict[str, Any]] = []
            elif isinstance(history_value, list) and all(
                isinstance(item, dict) for item in history_value
            ):
                history = [dict(item) for item in history_value]
            else:
                reject("controlled reveal prior preparation history is malformed")
            if history:
                reject("controlled reveal prior preparation history is not empty")
            supersession_record = {
                "preparation": prior_preparation,
                "preparation_sha256": observed_prior_hash,
                "superseded_at": now_utc.isoformat(),
                "superseded_by_batch_id": str(batch_id),
                "superseded_by_authority_id": str(authority_id),
            }
            history.append(supersession_record)
            state[
                "controlled_admin_first_child_reveal_preparation_history"
            ] = history
        elif expected_prior_hash:
            reject("controlled reveal prior preparation is missing")
        if (
            state.get("active_placement_client_order_id")
            or state.get("active_exchange_order_id")
        ):
            reject("controlled reveal child has active placement evidence")

        reference_notional = total_size * prepared_price
        if not reference_notional.is_finite() or reference_notional >= hard_cap:
            reject("controlled reveal child reference notional is not under the hard cap")

        try:
            original_parent_price = Decimal(str(child_row.get("price")))
            original_stealth_price = Decimal(str(stealth_row.get("limit_price")))
            original_threshold = Decimal(str(condition.get("price_threshold")))
        except (InvalidOperation, TypeError, ValueError):
            reject("controlled reveal original child price evidence is invalid")
        if (
            not original_parent_price.is_finite()
            or not original_stealth_price.is_finite()
            or not original_threshold.is_finite()
            or original_parent_price != original_stealth_price
        ):
            reject("controlled reveal original child price evidence is inconsistent")
        if sealed_prior_preparation is not None:
            try:
                sealed_prepared_price = Decimal(
                    str(sealed_prior_preparation.get("prepared_limit_price"))
                )
                sealed_reference_notional = Decimal(
                    str(
                        sealed_prior_preparation.get(
                            "reference_notional_usdc"
                        )
                    )
                )
                sealed_total_size = (
                    sealed_reference_notional / sealed_prepared_price
                )
            except (ArithmeticError, InvalidOperation, TypeError, ValueError):
                reject("controlled reveal sealed v8 numeric evidence is invalid")
            if (
                not sealed_prepared_price.is_finite()
                or sealed_prepared_price <= 0
                or not sealed_reference_notional.is_finite()
                or sealed_reference_notional <= 0
                or not sealed_total_size.is_finite()
                or sealed_total_size <= 0
                or sealed_total_size * sealed_prepared_price
                != sealed_reference_notional
                or total_size != sealed_total_size
                or original_parent_price != sealed_prepared_price
                or original_stealth_price != sealed_prepared_price
                or original_threshold != sealed_prepared_price
                or root_correlation_id
                != str(sealed_prior_preparation.get("correlation_id") or "")
                or root_audit_id
                != str(sealed_prior_preparation.get("root_audit_id") or "")
                or original_stealth_status != StealthOrderStatus.HIDDEN.value
                or stealth_row.get("condition_first_met_at") is not None
                or stealth_row.get("condition_confirmed_at") is not None
            ):
                reject(
                    "controlled reveal rows do not match the sealed v8 "
                    "materialized state"
                )

        preparation_evidence = {
            "authority_id": str(authority_id),
            "approval_snapshot_id": str(approval_snapshot_id),
            "admission_audit_id": str(admission_audit_id),
            "cap_guard_decision_id": str(cap_guard_decision_id),
            "reconciliation_plan_id": str(reconciliation_plan_id),
            "batch_id": str(batch_id),
            "batch_slot": batch_slot,
            "prepared_at": now_utc.isoformat(),
            "market_observed_at": observed_at_utc.isoformat(),
            "market_age_seconds": float(market_age),
            "market_bid": format(bid, "f"),
            "market_source": normalized_market_source,
            "minimum_standing_price": float(minimum_standing_price),
            "requested_limit_price": float(requested_price),
            "prepared_limit_price": float(prepared_price),
            "quote_increment": str(increment),
            "reference_notional_usdc": float(reference_notional),
            "max_notional_usdc": float(hard_cap),
            "original_order_parent_price": float(original_parent_price),
            "original_stealth_limit_price": float(original_stealth_price),
            "original_price_threshold": float(original_threshold),
            "original_stealth_status": original_stealth_status,
            "original_condition_first_met_at": stealth_row.get(
                "condition_first_met_at"
            ),
            "original_condition_confirmed_at": stealth_row.get(
                "condition_confirmed_at"
            ),
            "root_client_order_id": root_id,
            "stealth_order_id": child_id,
            "portfolio_id": portfolio_id,
            "correlation_id": root_correlation_id,
            "root_audit_id": root_audit_id,
            "root_exchange_order_id": str(root_row.get("exchange_order_id")),
        }
        if controlled_plan_sha256 is not None:
            preparation_evidence["controlled_plan_sha256"] = (
                controlled_plan_sha256
            )
        if supersession_record is not None:
            preparation_evidence["supersedes_preparation_sha256"] = (
                supersession_record["preparation_sha256"]
            )
            preparation_evidence["supersedes_batch_id"] = str(
                supersession_record["preparation"].get("batch_id") or ""
            )
        state["controlled_admin_first_child_reveal_preparation"] = preparation_evidence
        condition["price_threshold"] = float(prepared_price)

        cursor.execute(
            "UPDATE order_parent SET price = %s WHERE client_order_id = %s",
            (prepared_price, child_id),
        )
        if cursor.rowcount != 1:
            reject("controlled reveal order_parent update did not affect exactly one row")
        cursor.execute(
            """UPDATE stealth_orders
                  SET limit_price = %s,
                      status = %s,
                      reveal_condition_json = %s,
                      anchor_repricing_state_json = %s,
                      condition_first_met_at = NULL,
                      condition_confirmed_at = NULL,
                      updated_at = CURRENT_TIMESTAMP
                WHERE stealth_order_id = %s""",
            (
                prepared_price,
                StealthOrderStatus.HIDDEN.value,
                json.dumps(condition, default=_json_default_for_db),
                json.dumps(state, default=_json_default_for_db),
                child_id,
            ),
        )
        if cursor.rowcount != 1:
            reject("controlled reveal stealth update did not affect exactly one row")

        return {
            "stealth_order_id": child_id,
            "root_client_order_id": root_id,
            "portfolio_id": portfolio_id,
            "correlation_id": root_correlation_id,
            "root_audit_id": root_audit_id,
            "prepared_limit_price": prepared_price,
            "reference_notional_usdc": reference_notional,
            "market_bid": format(bid, "f"),
            "market_source": normalized_market_source,
            "market_observed_at": observed_at_utc,
            "controlled_plan_sha256": controlled_plan_sha256,
            "reveal_condition_json": condition,
            "anchor_repricing_state_json": state,
        }


def insert_order_parent_batch(
    orders: List[Dict[str, Any]],
) -> List[Optional[int]]:
    """Insert multiple parent orders in batch.
    
    Processes a list of parent order dicts and inserts each one, returning
    the list of inserted IDs (None for failed entries).
    
    Args:
        orders: List of parent order dicts with keys: client_order_id, product_id,
                side, size, price, target_movement, and optional: target_movement_type,
                max_order_replacement, current_order_replacement, status.
    
    Returns:
        List of inserted database IDs, with None for any orders that failed validation
        or insertion.
    """
    inserted_ids: List[Optional[int]] = []
    
    logger.info(f"Starting batch insert of {len(orders)} parent orders")

    for idx, order in enumerate(orders, start=1):
        client_order_id = order.get("client_order_id")
        product_id = order.get("product_id")
        side = order.get("side")
        size = order.get("size")
        price = order.get("price")
        status = order.get("status", "pending")
        target_movement = order.get("target_movement")
        target_movement_type = order.get("target_movement_type", "P")
        max_order_replacement = int(order.get("max_order_replacement", DEFAULT_MAX_ORDER_REPLACEMENT))
        current_order_replacement = int(order.get("current_order_replacement", 0))

        if any(value is None for value in (
            client_order_id,
            product_id,
            side,
            size,
            price,
            target_movement,
        )):
            logger.warning(f"  [{idx}/{len(orders)}] Skipping invalid order - missing required fields: {order}")
            inserted_ids.append(None)
            continue

        result = insert_order_parent(
            client_order_id=client_order_id,
            product_id=product_id,
            side=side,
            size=size,
            price=price,
            target_movement=target_movement,
            target_movement_type=target_movement_type,
            max_order_replacement=max_order_replacement,
            current_order_replacement=current_order_replacement,
            status=status,
        )
        inserted_ids.append(result)

    success_count = sum(1 for x in inserted_ids if x is not None)
    logger.info(f"Batch insert complete: {success_count}/{len(orders)} parent orders inserted successfully")
    
    return inserted_ids


def get_parent_orders() -> List[Dict[str, Any]]:
    """Retrieve all parent orders from the database.
    
    Args:
        None
    
    Returns:
        List of all parent order dicts, or empty list if none exist.
    """
    query = "SELECT * FROM order_parent"
    return DB_CLIENT.execute_query(query)


def get_parent_orders_page(
    *,
    product_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    """Return one deterministic, filtered order page and its total count.

    This is the lightweight operator-list read path.  It intentionally selects
    only fields exposed by the ordinary Admin order summary instead of loading
    every ``order_parent`` column and paginating in application memory.
    """

    normalized_limit = max(1, min(int(limit), 500))
    normalized_offset = max(0, int(offset))
    clauses: List[str] = []
    params: List[Any] = []
    if product_id:
        clauses.append("product_id = %s")
        params.append(str(product_id))
    if status:
        clauses.append("status = %s")
        params.append(str(status).upper())
    where_clause = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    count_query = (
        "SELECT COUNT(*) AS total_matching_count FROM order_parent"
        f"{where_clause}"
    )
    count_rows = DB_CLIENT.execute_query(count_query, tuple(params)) or []
    total_matching_count = (
        int(count_rows[0].get("total_matching_count") or 0)
        if count_rows
        else 0
    )

    page_query = f"""
    SELECT
        client_order_id,
        product_id,
        side,
        status,
        size,
        price,
        parent_order_id,
        ownership_provenance,
        created_at,
        exchange_order_id,
        correlation_id,
        audit_id
    FROM order_parent{where_clause}
    ORDER BY created_at DESC, id DESC
    LIMIT %s OFFSET %s
    """
    page_params = tuple([*params, normalized_limit, normalized_offset])
    rows = DB_CLIENT.execute_query(page_query, page_params) or []
    return rows, total_matching_count


def get_parent_order_summary(client_order_id: str) -> Optional[Dict[str, Any]]:
    """Return the lightweight operator-facing fields for one parent order."""

    query = """
    SELECT
        client_order_id,
        product_id,
        side,
        status,
        size,
        price,
        parent_order_id,
        ownership_provenance,
        created_at,
        exchange_order_id,
        correlation_id,
        audit_id
    FROM order_parent
    WHERE client_order_id = %s
    """
    results = DB_CLIENT.execute_query(query, (client_order_id,)) or []
    return results[0] if results else None


def get_parent_order(client_order_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single parent order by client_order_id.
    
    Args:
        client_order_id: The client_order_id to look up.
    
    Returns:
        Parent order dict if found, None otherwise.
    
    Raises:
        DatabaseConnectionError: If database connection fails.
        OrderPersistenceError: If query execution fails unexpectedly.
    """
    try:
        query = "SELECT * FROM order_parent WHERE client_order_id = %s"
        results = DB_CLIENT.execute_query(query, (client_order_id,))
        return results[0] if results else None
    except Exception as e:
        error_msg = str(e).lower()
        if "connection" in error_msg or "timeout" in error_msg:
            raise DatabaseConnectionError(
                error_type="ConnectionError",
                message=f"Failed to connect to database while fetching parent order",
                client_order_id=client_order_id,
            )
        else:
            raise OrderPersistenceError(
                error_type="PersistenceQueryError",
                message=f"Failed to retrieve parent order {client_order_id}: {str(e)}",
                client_order_id=client_order_id,
            )


def get_unresolved_admin_manual_root_submissions(
    retail_portfolio_id: str,
) -> List[Dict[str, Any]]:
    """Return nonterminal Admin manual roots for one portfolio.

    This is the durable restart/single-flight admission source. Unknown and
    newly introduced nonterminal statuses fail closed because the query
    excludes only the explicit terminal exchange states.
    """

    _require_uuid_text(
        retail_portfolio_id,
        "retail_portfolio_id",
        client_order_id=retail_portfolio_id,
    )
    terminal_statuses = (
        OrderStatus.FILLED.value,
        OrderStatus.CANCELLED.value,
        OrderStatus.EXPIRED.value,
        OrderStatus.FAILED.value,
    )
    query = """
    SELECT client_order_id, product_id, side, size, price, status,
           ownership_provenance, retail_portfolio_id,
           correlation_id, audit_id, created_at
    FROM order_parent
    WHERE retail_portfolio_id = %s
      AND ownership_provenance = %s
      AND parent_order_id IS NULL
      AND UPPER(status) NOT IN (%s, %s, %s, %s)
    ORDER BY created_at ASC, id ASC
    """
    return DB_CLIENT.execute_query(
        query,
        (
            retail_portfolio_id,
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value,
            *terminal_statuses,
        ),
    )


def get_unresolved_admin_spot_root_submissions(
    retail_portfolio_id: str,
) -> List[Dict[str, Any]]:
    """Return every nonterminal Admin-owned direct Spot root for a portfolio."""

    _require_uuid_text(
        retail_portfolio_id,
        "retail_portfolio_id",
        client_order_id=retail_portfolio_id,
    )
    terminal_statuses = (
        OrderStatus.FILLED.value,
        OrderStatus.CANCELLED.value,
        OrderStatus.EXPIRED.value,
        OrderStatus.FAILED.value,
    )
    query = """
    SELECT client_order_id, product_id, side, size, price, status,
           ownership_provenance, retail_portfolio_id,
           correlation_id, audit_id, created_at
    FROM order_parent
    WHERE retail_portfolio_id = %s
      AND ownership_provenance IN (%s, %s)
      AND parent_order_id IS NULL
      AND UPPER(status) NOT IN (%s, %s, %s, %s)
    ORDER BY created_at ASC, id ASC
    """
    return DB_CLIENT.execute_query(
        query,
        (
            retail_portfolio_id,
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value,
            OrderOwnershipProvenance.ADMIN_AUTOMATION_ROOT.value,
            *terminal_statuses,
        ),
    )


def has_unresolved_admin_manual_root_submission(
    retail_portfolio_id: str,
) -> bool:
    """Return whether durable Admin root state blocks another submission."""

    return bool(
        get_unresolved_admin_manual_root_submissions(retail_portfolio_id)
    )


def update_parent_order_target_movement(parent_order_id: str, target_movement: Optional[float], target_movement_type: str = "P") -> bool:
    """Update the target_movement and target_movement_type for a parent order.
    
    Args:
        parent_order_id: UUID of the parent order
        target_movement: Profit target value (float) or None to clear
        target_movement_type: "P" for percentage (default) or "A" for absolute amount
    
    Returns:
        True if update successful, False otherwise
    
    Raises:
        DatabaseTransactionError: If update transaction fails.
        DatabaseConnectionError: If database connection fails.
    
    Example:
        >>> update_parent_order_target_movement(
        ...     parent_order_id="550e8400-e29b-41d4-a716-446655440000",
        ...     target_movement=0.002,
        ...     target_movement_type="P"
        ... )
        True
    """
    try:
        query = """
        UPDATE order_parent
        SET target_movement = %s,
            target_movement_type = %s
        WHERE client_order_id = %s
        """
        
        rows_affected = DB_CLIENT.execute_update(
            query,
            (target_movement, target_movement_type if target_movement else None, parent_order_id)
        )
        
        return rows_affected > 0
    except Exception as e:
        error_msg = str(e).lower()
        if "connection" in error_msg or "timeout" in error_msg:
            raise DatabaseConnectionError(
                error_type="ConnectionError",
                message=f"Failed to connect to database while updating parent order",
                client_order_id=parent_order_id,
            )
        else:
            raise DatabaseTransactionError(
                error_type="UpdateTransactionError",
                message=f"Failed to update parent order target_movement: {str(e)}",
                client_order_id=parent_order_id,
            )


def get_stealth_children_for_parent(parent_order_id: str) -> List[Dict[str, Any]]:
    """Retrieve all children (follow-ups) for a parent stealth order.
    
    Since all orders are stealth orders, all children are stealth children
    stored in the stealth_orders table with parent_order_id pointing to the parent.
    
    Args:
        parent_order_id: The UUID of the parent stealth order (matches stealth_order_id).
    
    Returns:
        List of stealth child order dicts (with stealth_order_id as the child identifier),
        or empty list if none exist.
    """
    query = """
    SELECT stealth_order_id as client_order_id, 
           product_id, 
           side, 
           total_size as size, 
           limit_price as price,
           parent_order_id,
           status as stealth_status,
           last_lifecycle_event,
           failure_reason
    FROM stealth_orders 
    WHERE parent_order_id = %s
    """
    return DB_CLIENT.execute_query(query, (parent_order_id,))


def get_order_parent_replacement_count(client_order_id: str) -> Optional[int]:
    """Retrieve the current replacement count for a parent order.
    
    Args:
        client_order_id: The client-specified parent order ID.
    
    Returns:
        The current replacement count, or None if parent not found.
    """
    query = "SELECT current_order_replacement FROM order_parent WHERE client_order_id = %s"
    results = DB_CLIENT.execute_query(query, (client_order_id,))
    return int(results[0]["current_order_replacement"]) if results else None


def update_order_parent_status(
    client_order_id: str,
    status: str,
    exchange_order_id: Optional[str] = None,
) -> int:
    """Update parent status and optionally bind authoritative exchange evidence.
    
    Args:
        client_order_id: The client-specified parent order ID.
        status: New status value.
        exchange_order_id: Exact Coinbase order ID proven by authoritative
            readback.  Status-only calls leave any existing ID unchanged.
    
    Returns:
        Number of rows updated (0 or 1).
    """
    if exchange_order_id is None:
        query = "UPDATE order_parent SET status = %s WHERE client_order_id = %s"
        params = (status, client_order_id)
    else:
        normalized_exchange_order_id = str(exchange_order_id).strip()
        if not normalized_exchange_order_id or len(normalized_exchange_order_id) > 64:
            raise ValueError("exchange_order_id must be 1-64 characters")
        query = (
            "UPDATE order_parent SET status = %s, exchange_order_id = %s "
            "WHERE client_order_id = %s "
            "AND (exchange_order_id IS NULL OR exchange_order_id = %s)"
        )
        params = (
            status,
            normalized_exchange_order_id,
            client_order_id,
            normalized_exchange_order_id,
        )

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        logger.info(
            "Parent order status updated: %s -> %s%s",
            client_order_id,
            status,
            (
                f" (exchange_order_id={exchange_order_id})"
                if exchange_order_id is not None
                else ""
            ),
        )
    else:
        logger.warning(f"No parent order found to update status: {client_order_id}")
    return result


def update_order_parent_replacement_count(
    client_order_id: str,
    current_order_replacement: int
) -> int:
    """Update the current replacement count for a parent order.
    
    Args:
        client_order_id: The client-specified parent order ID.
        current_order_replacement: New replacement count value.
    
    Returns:
        Number of rows updated (0 or 1).
    """
    query = """
    UPDATE order_parent
    SET current_order_replacement = %s
    WHERE client_order_id = %s
    """
    params = (int(current_order_replacement), client_order_id)

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        logger.info(
            f"Parent order replacement count updated: "
            f"{client_order_id} -> {current_order_replacement}"
        )
    else:
        logger.warning(f"No parent order found to update replacement count: {client_order_id}")
    return result


def increment_order_parent_replacement_count(client_order_id: str) -> Optional[int]:
    """Increment the current replacement count for a parent order.
    
    Adds 1 to the existing replacement count in a single atomic operation.
    
    Args:
        client_order_id: The client-specified parent order ID.
    
    Returns:
        The new replacement count after incrementing, or None if parent not found.
    """
    query = """
    UPDATE order_parent
    SET current_order_replacement = current_order_replacement + 1
    WHERE client_order_id = %s
    RETURNING current_order_replacement
    """
    results = DB_CLIENT.execute_query(query, (client_order_id,))

    if results:
        new_count = int(results[0]["current_order_replacement"])
        logger.info(f"Parent order replacement count incremented: {client_order_id} -> {new_count}")
        return new_count

    logger.warning(f"No parent order found to increment replacement count: {client_order_id}")
    return None


def update_order_parent_replacement_config(
    client_order_id: str,
    max_order_replacement: int,
    current_order_replacement: Optional[int] = None,
) -> int:
    """Update replacement configuration for a parent order.
    
    Updates max and/or current replacement counts. If current_order_replacement
    is None, only updates max. If provided, updates both.
    
    Args:
        client_order_id: The client-specified parent order ID.
        max_order_replacement: New maximum replacement count.
        current_order_replacement: Optional new current replacement count (default None).
    
    Returns:
        Number of rows updated (0 or 1).
    """
    if current_order_replacement is None:
        query = """
        UPDATE order_parent
        SET max_order_replacement = %s
        WHERE client_order_id = %s
        """
        params = (int(max_order_replacement), client_order_id)
    else:
        query = """
        UPDATE order_parent
        SET max_order_replacement = %s,
            current_order_replacement = %s
        WHERE client_order_id = %s
        """
        params = (
            int(max_order_replacement),
            int(current_order_replacement),
            client_order_id,
        )

    result = DB_CLIENT.execute_update(query, params)
    if result > 0:
        print(
            f"Parent order replacement config updated: {client_order_id} "
            f"-> max={int(max_order_replacement)}"
            + (
                f", current={int(current_order_replacement)}"
                if current_order_replacement is not None else ""
            )
        )
    else:
        logger.warning(f"No parent order found to update replacement config: {client_order_id}")
    return result


def update_order_parent_status_batch(
    status_updates: List[Dict[str, str]]
) -> int:
    """Update status for multiple parent orders in batch.
    
    Processes a list of status updates and applies each one.
    
    Args:
        status_updates: List of dicts with 'client_order_id' and 'status' keys.
    
    Returns:
        Total count of rows successfully updated.
    """
    total_updated: int = 0

    for update in status_updates:
        client_order_id = update.get("client_order_id")
        status = update.get("status")

        if not all([client_order_id, status]):
            logger.warning(f"Skipping invalid parent order status update: {update}")
            continue

        result = update_order_parent_status(client_order_id, status)
        total_updated += result

    return total_updated


def adopt_child_to_parent(
    child_client_order_id: str,
    new_parent_client_order_id: str,
    keep_adoption_history: bool = True
) -> bool:
    """
    Reassign a child order to a new parent order (adoption).
    
    Updates the parent-child relationship in the database. Optionally tracks
    the original parent for audit history.
    
    Args:
        child_client_order_id: The UUID of the child order to adopt.
        new_parent_client_order_id: The UUID of the new parent order.
        keep_adoption_history: If True, stores the old parent in previous_parent_client_order_id
                               and timestamp in adopted_at. If False, old parent is lost.
    
    Returns:
        True if adoption was successful, False otherwise.
    
    Raises:
        Exception: If database update fails.
    
    Examples:
        >>> # Adopt child to new parent, keeping history
        >>> result = adopt_child_to_parent(
        ...     child_client_order_id="child-uuid-123",
        ...     new_parent_client_order_id="parent-uuid-456",
        ...     keep_adoption_history=True
        ... )
        >>> if result:
        ...     print("Child adopted successfully")
        
        >>> # Adopt without keeping history
        >>> result = adopt_child_to_parent(
        ...     child_client_order_id="child-uuid-123",
        ...     new_parent_client_order_id="parent-uuid-456",
        ...     keep_adoption_history=False
        ... )
    
    Notes:
        - Validates that both parent and child exist before updating
        - When keep_adoption_history=True, stores old parent ID for audit trail
        - The timestamp adopted_at records when the adoption occurred
        - Old parent-child relationship is broken by updating the FK
    """
    # First, validate that child exists
    validate_child_query = (
        "SELECT parent_client_order_id FROM order_child WHERE client_order_id = %s"
    )
    try:
        child_result = DB_CLIENT.execute_query(validate_child_query, (child_client_order_id,))
        if not child_result:
            logger.error(f"Adoption failed: Child order not found: {child_client_order_id}")
            return False
        
        old_parent = child_result[0].get("parent_client_order_id")
    except Exception as e:
        logger.error(f"Error validating child order {child_client_order_id}: {type(e).__name__}: {e}")
        return False
    
    # Validate that new parent exists
    validate_parent_query = (
        "SELECT client_order_id FROM order_parent WHERE client_order_id = %s"
    )
    try:
        parent_result = DB_CLIENT.execute_query(validate_parent_query, (new_parent_client_order_id,))
        if not parent_result:
            logger.error(f"Adoption failed: Parent order not found: {new_parent_client_order_id}")
            return False
    except Exception as e:
        logger.error(f"Error validating parent order {new_parent_client_order_id}: {type(e).__name__}: {e}")
        return False
    
    # Perform the adoption
    if keep_adoption_history:
        # Preserve old parent and add adoption timestamp
        update_query = """
        UPDATE order_child 
        SET parent_client_order_id = %s,
            previous_parent_client_order_id = %s,
            adopted_at = CURRENT_TIMESTAMP
        WHERE client_order_id = %s
        """
        params = (new_parent_client_order_id, old_parent, child_client_order_id)
    else:
        # Just update the parent, no history
        update_query = """
        UPDATE order_child 
        SET parent_client_order_id = %s
        WHERE client_order_id = %s
        """
        params = (new_parent_client_order_id, child_client_order_id)
    
    try:
        result = DB_CLIENT.execute_update(update_query, params)
        if result > 0:
            history_note = (
                f" (previous parent: {old_parent})"
                if keep_adoption_history else ""
            )
            logger.info(
                f"âœ“ Child order adopted: {child_client_order_id} "
                f"{old_parent} â†’ {new_parent_client_order_id}{history_note}"
            )
            return True
        else:
            logger.error(f"âœ— Adoption failed: No child order found: {child_client_order_id}")
            return False
    except Exception as e:
        logger.error(f"âœ— Error adopting child order {child_client_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Adoption details - new_parent: {new_parent_client_order_id}, keep_history: {keep_adoption_history}")
        return False


def find_compatible_parents(
    child_order: Dict[str, Any],
    parent_orders: List[Dict[str, Any]],
    price_tolerance_pct: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Find parent orders compatible for adopting a child order.
    
    Compatibility criteria:
    - Same product_id
    - Same side
    - Price difference < price_tolerance_pct% of parent price
    
    Args:
        child_order: Child order dict with product_id, side, price keys.
        parent_orders: List of parent order dicts to search.
        price_tolerance_pct: Maximum price difference as % of parent price (default 0.5%).
    
    Returns:
        List of compatible parent orders, sorted by price difference (closest first).
    """
    compatible = []
    child_product = child_order.get("product_id")
    child_side = child_order.get("side")
    child_price = float(child_order.get("price", 0))
    
    for parent in parent_orders:
        parent_product = parent.get("product_id")
        parent_side = parent.get("side")
        parent_price = float(parent.get("price", 0))
        
        # Check product and side match
        if parent_product != child_product or parent_side != child_side:
            continue
        
        # Skip if parent price is invalid
        if parent_price <= 0:
            continue
        
        # Check price difference
        price_diff_pct = abs(child_price - parent_price) / parent_price * 100
        if price_diff_pct < price_tolerance_pct:
            compatible.append({
                "parent": parent,
                "price_diff_pct": price_diff_pct
            })
    
    # Sort by price difference (closest first)
    compatible.sort(key=lambda x: x["price_diff_pct"])
    return compatible


def adopt_orphaned_orders(
    price_tolerance_pct: float = 0.5,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Find and adopt orphaned child orders to compatible parents.
    
    Searches for child orders without a matching parent and attempts to find
    compatible parents based on product_id, side, and price similarity.
    
    Args:
        price_tolerance_pct: Maximum price difference as % of parent price (default 0.5%).
        dry_run: If True, only report what would be adopted without making changes.
    
    Returns:
        Dict with adoption results:
        {
            "total_children": int,
            "orphaned_found": int,
            "adoptions_completed": int,
            "adoptions_skipped": int,
            "details": List[Dict with adoption details]
        }
    
    Examples:
        >>> # Find and adopt orphaned orders
        >>> result = adopt_orphaned_orders(price_tolerance_pct=0.5)
        >>> print(f"Adopted {result['adoptions_completed']} orders")
        
        >>> # Dry run to see what would be adopted
        >>> result = adopt_orphaned_orders(dry_run=True)
        >>> for detail in result['details']:
        ...     print(f"Would adopt {detail['child_id']} to {detail['parent_id']}")
    """
    try:
        # Get all parents and children
        all_parents = get_parent_orders()
        all_children = []
        orphaned_children = []
        
        # Collect all children and find orphaned ones
        if all_parents:
            all_parent_ids = {p["client_order_id"] for p in all_parents}
            
            for parent in all_parents:
                children = get_child_orders(parent["client_order_id"])
                all_children.extend(children)
        else:
            all_parent_ids = set()
        
        # Find orphaned children (parent doesn't exist)
        for child in all_children:
            if child.get("parent_client_order_id") not in all_parent_ids:
                orphaned_children.append(child)
        
        result = {
            "total_children": len(all_children),
            "orphaned_found": len(orphaned_children),
            "adoptions_completed": 0,
            "adoptions_skipped": 0,
            "details": []
        }
        
        if not orphaned_children:
            print(f"âœ… No orphaned children found")
            return result
        
        print(f"\nðŸ“ Found {len(orphaned_children)} orphaned child orders")
        print(f"   Searching for compatible parents (tolerance: {price_tolerance_pct}%)...")
        
        # Try to adopt each orphaned child
        for orphan in orphaned_children:
            # Find compatible parents
            compatible = find_compatible_parents(
                orphan,
                all_parents,
                price_tolerance_pct=price_tolerance_pct
            )
            
            if not compatible:
                result["adoptions_skipped"] += 1
                result["details"].append({
                    "child_id": orphan.get("client_order_id"),
                    "status": "SKIPPED_NO_COMPATIBLE_PARENT",
                    "product_id": orphan.get("product_id"),
                    "side": orphan.get("side"),
                    "price": orphan.get("price"),
                    "reason": f"No compatible parents found (tolerance: {price_tolerance_pct}%)"
                })
                continue
            
            # Adopt to the closest parent
            best_parent = compatible[0]["parent"]
            parent_id = best_parent.get("client_order_id")
            price_diff = compatible[0]["price_diff_pct"]
            
            if dry_run:
                result["adoptions_completed"] += 1
                result["details"].append({
                    "child_id": orphan.get("client_order_id"),
                    "status": "DRY_RUN_WOULD_ADOPT",
                    "product_id": orphan.get("product_id"),
                    "side": orphan.get("side"),
                    "child_price": orphan.get("price"),
                    "parent_id": parent_id,
                    "parent_price": best_parent.get("price"),
                    "price_diff_pct": price_diff
                })
            else:
                success = adopt_child_to_parent(
                    child_client_order_id=orphan.get("client_order_id"),
                    new_parent_client_order_id=parent_id,
                    keep_adoption_history=True
                )
                
                if success:
                    result["adoptions_completed"] += 1
                    result["details"].append({
                        "child_id": orphan.get("client_order_id"),
                        "status": "ADOPTED",
                        "product_id": orphan.get("product_id"),
                        "side": orphan.get("side"),
                        "child_price": orphan.get("price"),
                        "parent_id": parent_id,
                        "parent_price": best_parent.get("price"),
                        "price_diff_pct": price_diff
                    })
                else:
                    result["adoptions_skipped"] += 1
                    result["details"].append({
                        "child_id": orphan.get("client_order_id"),
                        "status": "ADOPTION_FAILED",
                        "product_id": orphan.get("product_id"),
                        "side": orphan.get("side"),
                        "parent_id": parent_id,
                        "reason": "Database adoption failed - check logs"
                    })
        
        # Print summary
        mode = "[DRY RUN] " if dry_run else ""
        print(f"\nâœ… {mode}Adoption Summary:")
        print(f"   Total children: {result['total_children']}")
        print(f"   Orphaned found: {result['orphaned_found']}")
        print(f"   Adoptions completed: {result['adoptions_completed']}")
        print(f"   Adoptions skipped: {result['adoptions_skipped']}")
        
        return result
        
    except Exception as e:
        print(f"âŒ Error during adoption process: {e}")
        return {
            "total_children": 0,
            "orphaned_found": 0,
            "adoptions_completed": 0,
            "adoptions_skipped": 0,
            "details": [],
            "error": str(e)
        }


def find_compatible_stealth_parents(
    orphaned_stealth: Dict[str, Any],
    all_parent_orders: List[Dict[str, Any]],
    price_tolerance_pct: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Find parent orders compatible for adopting an orphaned stealth order.
    
    Compatibility criteria:
    - Same product_id
    - Same side
    - Price difference < price_tolerance_pct% of parent price
    
    Args:
        orphaned_stealth: Orphaned stealth order dict with product_id, side, limit_price keys.
        all_parent_orders: List of parent order dicts from order_parent table to search.
        price_tolerance_pct: Maximum price difference as % of parent price (default 0.5%).
    
    Returns:
        List of compatible parent orders, sorted by price difference (closest first).
    """
    compatible = []
    child_product = orphaned_stealth.get("product_id")
    child_side = orphaned_stealth.get("side")
    child_price = float(orphaned_stealth.get("limit_price", 0))
    
    for parent in all_parent_orders:
        parent_product = parent.get("product_id")
        parent_side = parent.get("side")
        parent_price = float(parent.get("price", 0))
        
        # Check product and side match
        if parent_product != child_product or parent_side != child_side:
            continue
        
        # Skip if parent price is invalid
        if parent_price <= 0:
            continue
        
        # Check price difference
        price_diff_pct = abs(child_price - parent_price) / parent_price * 100
        if price_diff_pct <= price_tolerance_pct:
            compatible.append({
                "parent": parent,
                "price_diff_pct": price_diff_pct
            })
    
    # Sort by price difference (closest first)
    compatible.sort(key=lambda x: x["price_diff_pct"])
    return compatible


def adopt_stealth_order_to_parent(
    stealth_order_id: str,
    new_parent_order_id: str
) -> bool:
    """
    Reassign a stealth order to a new parent order (adoption).
    
    Updates the parent reference in the stealth_orders table to a valid order_parent.
    
    Args:
        stealth_order_id: The UUID of the stealth order to adopt.
        new_parent_order_id: The UUID of the new parent order (client_order_id from order_parent).
    
    Returns:
        True if adoption was successful, False otherwise.
    """
    # First, validate that stealth order exists
    validate_stealth_query = (
        "SELECT parent_order_id FROM stealth_orders WHERE stealth_order_id = %s"
    )
    try:
        stealth_result = DB_CLIENT.execute_query(validate_stealth_query, (stealth_order_id,))
        if not stealth_result:
            logger.error(f"Adoption failed: Stealth order not found: {stealth_order_id}")
            return False
        
        old_parent = stealth_result[0].get("parent_order_id")
    except Exception as e:
        logger.error(f"Error validating stealth order {stealth_order_id}: {type(e).__name__}: {e}")
        return False
    
    # Validate that new parent exists in order_parent table
    validate_parent_query = (
        "SELECT client_order_id FROM order_parent WHERE client_order_id = %s"
    )
    try:
        parent_result = DB_CLIENT.execute_query(validate_parent_query, (new_parent_order_id,))
        if not parent_result:
            logger.error(f"Adoption failed: Parent order not found: {new_parent_order_id}")
            return False
    except Exception as e:
        logger.error(f"Error validating parent order {new_parent_order_id}: {type(e).__name__}: {e}")
        return False
    
    # Perform the adoption
    update_query = """
    UPDATE stealth_orders
    SET parent_order_id = %s,
        updated_at = CURRENT_TIMESTAMP
    WHERE stealth_order_id = %s
    """
    params = (new_parent_order_id, stealth_order_id)
    
    try:
        result = DB_CLIENT.execute_update(update_query, params)
        if result > 0:
            logger.info(
                f"Stealth order adopted: {stealth_order_id} "
                f"from {old_parent} -> {new_parent_order_id}"
            )
            return True
        else:
            logger.error(f"Adoption failed: No stealth order found: {stealth_order_id}")
            return False
    except Exception as e:
        logger.error(f"Error adopting stealth order {stealth_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Adoption details - new_parent: {new_parent_order_id}")
        return False


def adopt_orphaned_stealth_orders(
    price_tolerance_pct: float = 0.5,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Find and adopt orphaned stealth orders to compatible stealth parents.
    
    Searches for stealth orders without a matching parent and attempts to find
    compatible stealth parents based on product_id, side, and price similarity.
    
    Args:
        price_tolerance_pct: Maximum price difference as % of parent price (default 0.5%).
        dry_run: If True, only report what would be adopted without making changes.
    
    Returns:
        Dict with adoption results:
        {
            "total_stealth_orders": int,
            "orphaned_found": int,
            "stealth_parents": int,
            "adoptions_completed": int,
            "adoptions_skipped": int,
            "details": List[Dict with adoption details]
        }
    
    Examples:
        >>> # Find and adopt orphaned stealth orders
        >>> result = adopt_orphaned_stealth_orders(price_tolerance_pct=0.5)
        >>> print(f"Adopted {result['adoptions_completed']} stealth orders")
        
        >>> # Dry run to see what would be adopted
        >>> result = adopt_orphaned_stealth_orders(dry_run=True)
        >>> for detail in result['details']:
        ...     print(f"Would adopt {detail['stealth_id']} to {detail['parent_id']}")
    """
    try:
        # Get all orphaned stealth orders (those with parent_order_id NULL)
        orphaned_query = (
            "SELECT * FROM stealth_orders WHERE parent_order_id IS NULL ORDER BY created_at DESC"
        )
        orphaned_stealth = DB_CLIENT.execute_query(orphaned_query)
        
        # Get all parent orders from order_parent table
        parents_query = (
            "SELECT client_order_id, product_id, side, price FROM order_parent ORDER BY created_at DESC"
        )
        all_parent_orders = DB_CLIENT.execute_query(parents_query)
        
        # Count total stealth orders
        total_stealth_query = "SELECT COUNT(*) as count FROM stealth_orders"
        total_stealth_result = DB_CLIENT.execute_query(total_stealth_query)
        total_stealth_count = total_stealth_result[0]["count"] if total_stealth_result else 0
        
        result = {
            "total_stealth_orders": total_stealth_count,
            "orphaned_found": len(orphaned_stealth),
            "parent_orders_available": len(all_parent_orders),
            "adoptions_completed": 0,
            "adoptions_skipped": 0,
            "details": []
        }
        
        if not orphaned_stealth:
            print(f"âœ… No orphaned stealth orders found")
            return result
        
        print(f"\nðŸ“ Found {len(orphaned_stealth)} orphaned stealth orders")
        print(f"   Found {len(all_parent_orders)} parent orders")
        print(f"   Searching for compatible parents (tolerance: {price_tolerance_pct}%)...")
        
        # Try to adopt each orphaned stealth order
        for orphan in orphaned_stealth:
            # Find compatible parent orders
            compatible = find_compatible_stealth_parents(
                orphan,
                all_parent_orders,
                price_tolerance_pct=price_tolerance_pct
            )
            
            if not compatible:
                result["adoptions_skipped"] += 1
                result["details"].append({
                    "stealth_id": orphan.get("stealth_order_id"),
                    "status": "SKIPPED_NO_COMPATIBLE_PARENT",
                    "product_id": orphan.get("product_id"),
                    "side": orphan.get("side"),
                    "price": orphan.get("limit_price"),
                    "reason": f"No compatible stealth parents found (tolerance: {price_tolerance_pct}%)"
                })
                continue
            
            # Adopt to the closest parent
            best_parent = compatible[0]["parent"]
            parent_id = best_parent.get("client_order_id")
            price_diff = compatible[0]["price_diff_pct"]
            
            if dry_run:
                result["adoptions_completed"] += 1
                result["details"].append({
                    "stealth_id": orphan.get("stealth_order_id"),
                    "status": "DRY_RUN_WOULD_ADOPT",
                    "product_id": orphan.get("product_id"),
                    "side": orphan.get("side"),
                    "child_price": orphan.get("limit_price"),
                    "parent_id": parent_id,
                    "parent_price": best_parent.get("price"),
                    "price_diff_pct": price_diff
                })
            else:
                success = adopt_stealth_order_to_parent(
                    stealth_order_id=orphan.get("stealth_order_id"),
                    new_parent_order_id=parent_id
                )
                
                if success:
                    result["adoptions_completed"] += 1
                    result["details"].append({
                        "stealth_id": orphan.get("stealth_order_id"),
                        "status": "ADOPTED",
                        "product_id": orphan.get("product_id"),
                        "side": orphan.get("side"),
                        "child_price": orphan.get("limit_price"),
                        "parent_id": parent_id,
                        "parent_price": best_parent.get("price"),
                        "price_diff_pct": price_diff
                    })
                else:
                    result["adoptions_skipped"] += 1
                    result["details"].append({
                        "stealth_id": orphan.get("stealth_order_id"),
                        "status": "ADOPTION_FAILED",
                        "product_id": orphan.get("product_id"),
                        "side": orphan.get("side"),
                        "parent_id": parent_id,
                        "reason": "Database adoption failed - check logs"
                    })
        
        # Print summary
        mode = "[DRY RUN] " if dry_run else ""
        print(f"\nâœ… {mode}Stealth Adoption Summary:")
        print(f"   Total stealth orders: {result['total_stealth_orders']}")
        print(f"   Orphaned found: {result['orphaned_found']}")
        print(f"   Parent orders available: {result['parent_orders_available']}")
        print(f"   Adoptions completed: {result['adoptions_completed']}")
        print(f"   Adoptions skipped: {result['adoptions_skipped']}")
        
        return result
        
    except Exception as e:
        print(f"âŒ Error during stealth adoption process: {e}")
        return {
            "total_stealth_orders": 0,
            "orphaned_found": 0,
            "parent_orders_available": 0,
            "adoptions_completed": 0,
            "adoptions_skipped": 0,
            "details": [],
            "error": str(e)
        }

def clear_all_stealth_orders() -> Dict[str, Any]:
    """
    Clears all stealth orders from the database.
    
    Deletes all records from the stealth_orders table. Due to cascading delete
    constraints, related records in stealth_order_snapshots and 
    stealth_order_reveal_history tables are automatically deleted.
    
    Returns:
        Dict with clear operation result:
        {
            "success": bool,
            "rows_deleted": int,
            "message": str,
            "error": str (if operation failed)
        }
    
    Examples:
        >>> # Clear all stealth orders
        >>> result = clear_all_stealth_orders()
        >>> if result["success"]:
        ...     print(f"Cleared {result['rows_deleted']} stealth orders")
        >>> else:
        ...     print(f"Error: {result['error']}")
    """
    try:
        # Get count before deletion for reporting
        count_query = "SELECT COUNT(*) as count FROM stealth_orders"
        count_result = DB_CLIENT.execute_query(count_query)
        count_before = count_result[0]["count"] if count_result else 0
        
        # Execute DELETE query for all stealth orders
        delete_query = "DELETE FROM stealth_orders"
        rows_deleted = DB_CLIENT.execute_update(delete_query)
        
        result = {
            "success": True,
            "rows_deleted": rows_deleted,
            "message": f"Successfully cleared {rows_deleted} stealth orders"
        }
        
        print(f"? {result['message']}")
        if count_before > 0:
            print(f"   (Cascaded: snapshots and reveal history also deleted)")
        
        return result
        
    except Exception as e:
        error_msg = f"Failed to clear stealth orders: {str(e)}"
        print(f"? {error_msg}")
        return {
            "success": False,
            "rows_deleted": 0,
            "error": error_msg
        }


def create_order_moves_table() -> None:
    """
    Create the order_moves table to track when cancelled orders are "moved" to new replacement orders.
    
    An order "move" occurs when a cancelled order is replaced with a new order that takes
    its place as the parent order, rather than becoming a child order. This tracks the
    relationship between the cancelled order and its replacement.
    
    Table columns:
    - id: Unique identifier for the move record
    - original_parent_client_order_id: The client_order_id of the cancelled parent order
    - new_parent_client_order_id: The client_order_id of the new replacement parent order (NULL if pre-marked)
    - move_on_cancel: If True, execute move automatically when order cancels (for automation)
    - moved_at: Timestamp when the move occurred (NULL until actual move happens)
    - reason: Optional reason for the move (e.g., "user_move", "auto_move")
    - notes: Optional additional details about the move
    - created_at: Timestamp when the move record was created
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS order_moves (
        id SERIAL PRIMARY KEY,
        original_parent_client_order_id VARCHAR(40) NOT NULL,
        new_parent_client_order_id VARCHAR(40),
        move_on_cancel BOOLEAN DEFAULT FALSE,
        moved_at TIMESTAMP,
        reason VARCHAR(50) DEFAULT 'auto_move',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (original_parent_client_order_id) REFERENCES order_parent(client_order_id) ON DELETE CASCADE,
        FOREIGN KEY (new_parent_client_order_id) REFERENCES order_parent(client_order_id) ON DELETE CASCADE
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("order_moves table done.")


def insert_order_move(
    original_parent_client_order_id: str,
    new_parent_client_order_id: str = None,
    reason: str = "auto_move",
    notes: str = None,
    move_on_cancel: bool = False
) -> Optional[int]:
    """
    Record a move when a cancelled parent order is replaced with a new parent order.
    
    Can be used in two ways:
    1. Record completed move: new_parent_client_order_id is set, moved_at is set
    2. Pre-mark for automation: new_parent_client_order_id is None, move_on_cancel=True
       (will be set when order cancels)
    
    Args:
        original_parent_client_order_id: The client_order_id of the cancelled parent order.
        new_parent_client_order_id: The client_order_id of the new replacement parent order.
                                  If None, this is a pre-marked move.
        reason: Reason for the move (default 'auto_move'). Other values: 'user_move', etc.
        notes: Optional additional details about the move.
        move_on_cancel: If True, execute move automatically when order cancels (for automation).
    
    Returns:
        The inserted move record's database ID if successful, None if failed.
    
    Raises:
        Exception: If database insertion fails.
        
    Example - Completed move:
        >>> move_id = insert_order_move(
        ...     original_parent_client_order_id="old_parent_uuid",
        ...     new_parent_client_order_id="new_parent_uuid",
        ...     reason="cancelled_order_moved",
        ...     notes="Cancelled due to user request"
        ... )
    
    Example - Pre-marked move (for automation):
        >>> move_id = insert_order_move(
        ...     original_parent_client_order_id="parent_uuid",
        ...     reason="auto_move_scheduled",
        ...     notes="Will move to strategy B if cancelled",
        ...     move_on_cancel=True
        ... )
    """
    query = """
    INSERT INTO order_moves (
        original_parent_client_order_id,
        new_parent_client_order_id,
        reason,
        notes,
        move_on_cancel,
        moved_at
    )
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id
    """
    params = (
        original_parent_client_order_id,
        new_parent_client_order_id,
        reason,
        notes,
        move_on_cancel,
        get_local_now() if new_parent_client_order_id else None  # Only set if completed move
    )

    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]["id"]
            if new_parent_client_order_id:
                logger.info(
                    f"âœ“ Order move recorded: {original_parent_client_order_id} "
                    f"â†’ {new_parent_client_order_id} (DB ID: {inserted_id}, reason: {reason})"
                )
            else:
                logger.info(
                    f"âœ“ Order move pre-marked: {original_parent_client_order_id} "
                    f"(DB ID: {inserted_id}, move_on_cancel={move_on_cancel}, reason: {reason})"
                )
            return inserted_id

        logger.warning(f"Failed to retrieve inserted move record ID for: {original_parent_client_order_id}")
        return None
    except Exception as e:
        logger.error(f"âœ— Error inserting order move ({original_parent_client_order_id}): {type(e).__name__}: {e}")
        logger.debug(f"  Move details - new_parent: {new_parent_client_order_id}, reason: {reason}, move_on_cancel: {move_on_cancel}")
        return None


# ============================================================================
# STEALTH ORDER MOVES (move REVEALED stealth order audit)
# ============================================================================
#
# A "stealth move" is the cancel-and-replace of a REVEALED stealth order's
# *exchange placement* while the same internal stealth_order_id is preserved.
# This is distinct from order_moves, which records the creation of a brand
# new parent_order on cancel. Each row here captures one move event so the
# history of price changes against a single stealth order is queryable.
#
# Schema rationale:
# - keyed on stealth_order_id (not parent_client_order_id) because the
#   move mutates the same stealth row in place.
# - old/new placement client_order_ids and exchange_order_ids are stored
#   for forensics: the "before" placement is gone from the exchange post-cancel
#   and the order_parent FK guard insert is the only on-disk record of the
#   "after" placement at the time of the move.
# - reason is a free-form string (intended to hold StealthMoveReason values)
#   to match the order_moves convention.
# - status field captures the result: "completed" | "cancel_failed" |
#   "place_failed_after_cancel" | "persist_failed". Failed-after-cancel rows
#   are critical for operator recovery (the stealth order is left CANCELLED).


def create_stealth_order_moves_table() -> None:
    """Create the stealth_order_moves table if it doesn't exist.

    Records every "move REVEALED stealth order" event executed via
    ``StealthOrderManager.execute_stealth_move``. Mirrors the
    ``order_moves`` audit pattern but keyed on ``stealth_order_id`` so a
    single stealth order's price-change history is one query away.

    Columns:
        - id: surrogate key
        - stealth_order_id: which stealth order was moved
        - old_placement_client_order_id: previous exchange placement uuid
        - old_exchange_order_id: previous Coinbase order id (cancelled)
        - old_submitted_price: previous limit price (audit snapshot)
        - new_placement_client_order_id: new exchange placement uuid
        - new_exchange_order_id: new Coinbase order id (NULL on failure)
        - new_submitted_price: new limit price
        - reason: StealthMoveReason value
        - notes: free-form operator note
        - status: "completed" | "cancel_failed" | "place_failed_after_cancel"
                  | "persist_failed"
        - error_message: populated when status != "completed"
        - market_bid: bid at move execution time (audit snapshot)
        - market_ask: ask at move execution time (audit snapshot)
        - moved_at: server timestamp when the move row was inserted

    No FK on stealth_order_id (audit rows must survive deletion of the
    parent stealth_orders row, mirroring order_moves' pattern of allowing
    orphaned audit history).
    """

    create_table_query = """
    CREATE TABLE IF NOT EXISTS stealth_order_moves (
        id SERIAL PRIMARY KEY,
        stealth_order_id VARCHAR(64) NOT NULL,
        old_placement_client_order_id VARCHAR(40),
        old_exchange_order_id VARCHAR(64),
        old_submitted_price NUMERIC,
        new_placement_client_order_id VARCHAR(40),
        new_exchange_order_id VARCHAR(64),
        new_submitted_price NUMERIC,
        reason VARCHAR(50) DEFAULT 'manual_user_move',
        notes TEXT,
        status VARCHAR(40) NOT NULL DEFAULT 'completed',
        error_message TEXT,
        market_bid NUMERIC,
        market_ask NUMERIC,
        moved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    index_query = """
    CREATE INDEX IF NOT EXISTS idx_stealth_order_moves_sid
        ON stealth_order_moves (stealth_order_id, moved_at DESC);
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        cursor.execute(index_query)
        print("stealth_order_moves table done.")


def insert_stealth_order_move(
    stealth_order_id: str,
    *,
    old_placement_client_order_id: Optional[str] = None,
    old_exchange_order_id: Optional[str] = None,
    old_submitted_price: Optional[float] = None,
    new_placement_client_order_id: Optional[str] = None,
    new_exchange_order_id: Optional[str] = None,
    new_submitted_price: Optional[float] = None,
    reason: str = "manual_user_move",
    notes: Optional[str] = None,
    status: str = "completed",
    error_message: Optional[str] = None,
    market_bid: Optional[float] = None,
    market_ask: Optional[float] = None,
) -> Optional[int]:
    """Insert one stealth-move audit row. Returns the new row id, or None on failure.

    Best-effort: failures are logged and swallowed (audit insertion must
    never break the move's own success path or its already-failing
    failure path).
    """

    query = """
    INSERT INTO stealth_order_moves (
        stealth_order_id,
        old_placement_client_order_id,
        old_exchange_order_id,
        old_submitted_price,
        new_placement_client_order_id,
        new_exchange_order_id,
        new_submitted_price,
        reason,
        notes,
        status,
        error_message,
        market_bid,
        market_ask
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """
    params = (
        stealth_order_id,
        old_placement_client_order_id,
        old_exchange_order_id,
        old_submitted_price,
        new_placement_client_order_id,
        new_exchange_order_id,
        new_submitted_price,
        reason,
        notes,
        status,
        error_message,
        market_bid,
        market_ask,
    )
    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            return results[0]["id"]
        return None
    except Exception as exc:
        logger.error(
            f"âœ— Error inserting stealth_order_move ({stealth_order_id}, "
            f"status={status}): {type(exc).__name__}: {exc}"
        )
        return None


def get_stealth_order_moves(
    stealth_order_id: str,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return move audit rows for one stealth order, newest first."""

    query = """
    SELECT * FROM stealth_order_moves
    WHERE stealth_order_id = %s
    ORDER BY moved_at DESC
    LIMIT %s
    """
    try:
        return DB_CLIENT.execute_query(query, (stealth_order_id, limit)) or []
    except Exception as exc:
        logger.error(
            f"âœ— Error fetching stealth_order_moves for {stealth_order_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return []


def get_order_move(original_parent_client_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a move record by the original parent order ID.
    
    Args:
        original_parent_client_order_id: The client_order_id of the original (cancelled) parent order.
    
    Returns:
        Move record dict if found, None if not found.
        
    Example:
        >>> move = get_order_move("old_parent_uuid")
        >>> if move:
        ...     print(f"Order was moved to: {move['new_parent_client_order_id']}")
    """
    query = """
    SELECT * FROM order_moves 
    WHERE original_parent_client_order_id = %s
    ORDER BY moved_at DESC
    LIMIT 1
    """
    results = DB_CLIENT.execute_query(query, (original_parent_client_order_id,))
    return results[0] if results else None


def get_order_moves_by_original_parent(original_parent_client_order_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all move records for a given original parent order ID.
    
    Useful for tracking the full history of moves for a parent order.
    
    Args:
        original_parent_client_order_id: The client_order_id of the original parent order.
    
    Returns:
        List of move record dicts, ordered by moved_at timestamp (newest first).
        
    Example:
        >>> moves = get_order_moves_by_original_parent("old_parent_uuid")
        >>> for move in moves:
        ...     print(f"Moved to {move['new_parent_client_order_id']} on {move['moved_at']}")
    """
    query = """
    SELECT * FROM order_moves 
    WHERE original_parent_client_order_id = %s
    ORDER BY moved_at DESC
    """
    return DB_CLIENT.execute_query(query, (original_parent_client_order_id,))


def get_order_moves_by_new_parent(new_parent_client_order_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all move records where a given order ID is the new parent.
    
    Useful for finding all orders that resulted from a move.
    
    Args:
        new_parent_client_order_id: The client_order_id of the new parent order.
    
    Returns:
        List of move record dicts, ordered by moved_at timestamp (newest first).
        
    Example:
        >>> moves = get_order_moves_by_new_parent("new_parent_uuid")
        >>> for move in moves:
        ...     print(f"Replaced {move['original_parent_client_order_id']} on {move['moved_at']}")
    """
    query = """
    SELECT * FROM order_moves 
    WHERE new_parent_client_order_id = %s
    ORDER BY moved_at DESC
    """
    return DB_CLIENT.execute_query(query, (new_parent_client_order_id,))


def has_order_moved(client_order_id: str) -> bool:
    """
    Check if an order has been moved (replaced).
    
    Args:
        client_order_id: The client_order_id to check (could be original or new parent).
    
    Returns:
        True if the order was involved in a move (either as original or new parent), False otherwise.
        
    Example:
        >>> if has_order_moved("parent_uuid"):
        ...     print("This order has been moved or is a replacement")
    """
    query = """
    SELECT 1 FROM order_moves 
    WHERE original_parent_client_order_id = %s 
       OR new_parent_client_order_id = %s
    LIMIT 1
    """
    results = DB_CLIENT.execute_query(query, (client_order_id, client_order_id))
    return bool(results)


def get_pending_move(original_parent_client_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a pre-marked (pending) move for an order that hasn't been executed yet.
    
    Pre-marked moves have:
    - move_on_cancel = True (should execute automatically on cancel)
    - new_parent_client_order_id = None (not yet set)
    - moved_at = NULL (not yet executed)
    
    Args:
        original_parent_client_order_id: The client_order_id of the parent to check.
    
    Returns:
        Pending move record dict if found, None if no pending move.
        
    Example:
        >>> pending = get_pending_move("parent_uuid")
        >>> if pending:
        ...     print(f"This order is pre-marked for move: {pending['reason']}")
    """
    query = """
    SELECT * FROM order_moves 
    WHERE original_parent_client_order_id = %s 
      AND move_on_cancel = TRUE
      AND new_parent_client_order_id IS NULL
    LIMIT 1
    """
    results = DB_CLIENT.execute_query(query, (original_parent_client_order_id,))
    return results[0] if results else None


def has_pending_move(original_parent_client_order_id: str) -> bool:
    """
    Check if an order has a pre-marked move waiting to be executed on cancel.
    
    Args:
        original_parent_client_order_id: The client_order_id of the parent to check.
    
    Returns:
        True if a pending move exists, False otherwise.
        
    Example:
        >>> if has_pending_move("parent_uuid"):
        ...     print("Order is pre-marked for automatic move on cancel")
    """
    return get_pending_move(original_parent_client_order_id) is not None


def create_pending_move(
    original_parent_client_order_id: str,
    new_order_details: Dict[str, Any],
    reason: str = "auto_move_scheduled",
    notes: str = None
) -> Optional[int]:
    """
    Pre-mark an order for automatic move when it cancels.
    
    Creates a move record with move_on_cancel=True and no new parent yet.
    When the order cancels, the new parent will be created and move executed.
    
    Args:
        original_parent_client_order_id: The client_order_id to pre-mark.
        new_order_details: Dict with new parent configuration (same as move_order):
            - product_id, side, size, price, target_movement, target_movement_type, max_order_replacement
        reason: Reason for the pending move (default 'auto_move_scheduled').
        notes: Optional additional context.
    
    Returns:
        The move record ID if successful, None if failed.
        
    Example:
        >>> move_id = create_pending_move(
        ...     original_parent_client_order_id="parent_uuid",
        ...     new_order_details={
        ...         "product_id": "BTC-USDC",
        ...         "side": "SELL",
        ...         "size": 0.5,
        ...         "price": 43000.0,
        ...         "target_movement": 0.01,
        ...         "max_order_replacement": 5
        ...     },
        ...     reason="scheduled_reversal",
        ...     notes="Switch to sell if cancelled after 1 hour"
        ... )
        >>> if move_id:
        ...     print(f"Pending move created: {move_id}")
    """
    # Store the new order details as JSON in notes if not provided
    import json
    if notes is None:
        notes = f"Pending move config: {json.dumps(new_order_details)}"
    else:
        notes = f"{notes}\n\nPending move config: {json.dumps(new_order_details)}"
    
    query = """
    INSERT INTO order_moves (
        original_parent_client_order_id,
        move_on_cancel,
        reason,
        notes
    )
    VALUES (%s, %s, %s, %s)
    RETURNING id
    """
    params = (original_parent_client_order_id, True, reason, notes)
    
    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            move_id = results[0]["id"]
            logger.info(
                f"Pending move created: {original_parent_client_order_id} "
                f"(DB ID: {move_id}, reason: {reason})"
            )
            return move_id
        return None
    except Exception as e:
        logger.error(f"Error creating pending move {original_parent_client_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Move details - new_parent: {new_parent_client_order_id}, reason: {reason}")
        return None


def execute_pending_move(
    original_parent_client_order_id: str,
    new_parent_client_order_id: str
) -> int:
    """
    Execute a pending move by setting the new parent and marking as executed.
    
    Called when a pre-marked order cancels and the new parent has been created.
    Sets new_parent_client_order_id, moved_at timestamp, and move_on_cancel to FALSE.
    
    Args:
        original_parent_client_order_id: The original parent being moved.
        new_parent_client_order_id: The new parent that was created.
    
    Returns:
        Number of rows updated (0 or 1).
        
    Example:
        >>> result = execute_pending_move(
        ...     original_parent_client_order_id="0_parent_uuid",
        ...     new_parent_client_order_id="new_parent_uuid"
        ... )
        >>> if result > 0:
        ...     print("Pending move executed")
    """
    query = """
    UPDATE order_moves
    SET new_parent_client_order_id = %s,
        moved_at = CURRENT_TIMESTAMP,
        move_on_cancel = FALSE
    WHERE original_parent_client_order_id = %s
      AND move_on_cancel = TRUE
      AND new_parent_client_order_id IS NULL
    """
    params = (new_parent_client_order_id, original_parent_client_order_id)
    
    try:
        result = DB_CLIENT.execute_update(query, params)
        if result > 0:
            logger.info(
                f"Pending move executed: {original_parent_client_order_id} "
                f"-> {new_parent_client_order_id}"
            )
        return result
    except Exception as e:
        logger.error(f"Error executing pending move for {original_parent_client_order_id}: {type(e).__name__}: {e}")
        return 0


def create_fill_ledger_table() -> None:
    """
    Create the fill_ledger table for lot-based profit tracking.

    Immutable append-only ledger of all fills (both partial and complete),
    derived from per-match cumulative-counter deltas on the WebSocket user channel.

    Naming distinction (deliberate):
        derived_trade_key   â€“ synthetic, deterministic UUID5 keyed on
                              (client_order_id, cumulative_quantity).
                              Always present. Idempotency / dedup key.
        exchange_trade_id   â€“ authoritative trade id from REST historical/fills.
                              NULL until reconciliation populates it.

    Reconciliation lifecycle (``reconciliation_status``):
        WS_DERIVED  â€“ just inserted from WS counters; not yet checked against REST.
        RECONCILED  â€“ matched 1:1 with a REST historical/fills row.
        MISMATCH    â€“ REST disagrees with WS-derived rows; operator review needed.

    Migration: idempotent ALTERs run after CREATE so existing deployments pick
    up the rename + new columns without manual intervention.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS fill_ledger (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        derived_trade_key UUID UNIQUE NOT NULL,
        exchange_trade_id TEXT,
        exchange_entry_id VARCHAR(80),
        exchange_fill_identity_sha256 CHAR(64),
        operator_import_batch_id UUID,
        instrument VARCHAR(32) NOT NULL,
        side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity DECIMAL(16, 8) NOT NULL,
        price DECIMAL(24, 12) NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        fees DECIMAL(16, 8) DEFAULT 0,
        commission_percentage DECIMAL(5, 4) DEFAULT 0,
        client_order_id VARCHAR(128),
        reconciliation_status VARCHAR(16) NOT NULL DEFAULT 'WS_DERIVED'
            CHECK (reconciliation_status IN ('WS_DERIVED','RECONCILED','MISMATCH')),
        reconciled_at TIMESTAMP
    );
    -- Forward-migration for deployments that predate this schema.
    ALTER TABLE fill_ledger RENAME COLUMN trade_id TO derived_trade_key;
    """
    # The RENAME is wrapped in its own try/except below because PostgreSQL has no
    # ALTER ... RENAME ... IF EXISTS for columns. Also handle the additive
    # columns idempotently with ADD COLUMN IF NOT EXISTS.
    additive_migrations = """
    ALTER TABLE fill_ledger ADD COLUMN IF NOT EXISTS exchange_trade_id TEXT;
    ALTER TABLE fill_ledger ADD COLUMN IF NOT EXISTS exchange_entry_id VARCHAR(80);
    ALTER TABLE fill_ledger ADD COLUMN IF NOT EXISTS
        exchange_fill_identity_sha256 CHAR(64);
    ALTER TABLE fill_ledger ADD COLUMN IF NOT EXISTS operator_import_batch_id UUID;
    ALTER TABLE fill_ledger ADD COLUMN IF NOT EXISTS reconciliation_status VARCHAR(16)
        NOT NULL DEFAULT 'WS_DERIVED';
    ALTER TABLE fill_ledger ADD COLUMN IF NOT EXISTS reconciled_at TIMESTAMP;
    ALTER TABLE fill_ledger ALTER COLUMN client_order_id TYPE VARCHAR(128);
    ALTER TABLE fill_ledger ALTER COLUMN price TYPE DECIMAL(24, 12);
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'fill_ledger'
               AND column_name = 'exchange_trade_id'
               AND data_type <> 'text'
        ) THEN
            ALTER TABLE fill_ledger
                ALTER COLUMN exchange_trade_id TYPE TEXT
                USING exchange_trade_id::text;
        END IF;
    END $$;
    DO $$
    BEGIN
        ALTER TABLE fill_ledger
            ADD CONSTRAINT fill_ledger_reconciliation_status_check
            CHECK (reconciliation_status IN ('WS_DERIVED','RECONCILED','MISMATCH'));
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END $$;
    CREATE INDEX IF NOT EXISTS idx_fill_ledger_instrument ON fill_ledger(instrument);
    CREATE INDEX IF NOT EXISTS idx_fill_ledger_timestamp ON fill_ledger(timestamp);
    CREATE INDEX IF NOT EXISTS idx_fill_ledger_client_order_id ON fill_ledger(client_order_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_fill_ledger_exchange_trade_id
        ON fill_ledger(exchange_trade_id) WHERE exchange_trade_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_fill_ledger_reconciliation_status
        ON fill_ledger(reconciliation_status);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_fill_ledger_exchange_fill_identity_sha256
        ON fill_ledger(exchange_fill_identity_sha256)
        WHERE exchange_fill_identity_sha256 IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_fill_ledger_operator_import_batch
        ON fill_ledger(operator_import_batch_id)
        WHERE operator_import_batch_id IS NOT NULL;
    """
    create_only = """
    CREATE TABLE IF NOT EXISTS fill_ledger (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        derived_trade_key UUID UNIQUE NOT NULL,
        exchange_trade_id TEXT,
        exchange_entry_id VARCHAR(80),
        exchange_fill_identity_sha256 CHAR(64),
        operator_import_batch_id UUID,
        instrument VARCHAR(32) NOT NULL,
        side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity DECIMAL(16, 8) NOT NULL,
        price DECIMAL(24, 12) NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        fees DECIMAL(16, 8) DEFAULT 0,
        commission_percentage DECIMAL(5, 4) DEFAULT 0,
        client_order_id VARCHAR(128),
        reconciliation_status VARCHAR(16) NOT NULL DEFAULT 'WS_DERIVED'
            CHECK (reconciliation_status IN ('WS_DERIVED','RECONCILED','MISMATCH')),
        reconciled_at TIMESTAMP
    );
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_only)
        # Forward-migrate legacy column name only if it still exists.
        # We pre-check via information_schema rather than wrapping ALTER ...
        # RENAME in try/except, because a failed ALTER inside an open
        # transaction aborts every subsequent statement.
        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'fill_ledger'
               AND column_name = 'trade_id'
            """
        )
        if cursor.fetchone() is not None:
            cursor.execute(
                "ALTER TABLE fill_ledger RENAME COLUMN trade_id TO derived_trade_key;"
            )
        cursor.execute(additive_migrations)
        print("fill_ledger table done.")
    install_order_follow_up_source_lock_trigger("fill_ledger")


def create_order_match_audit_table() -> None:
    """Create append-only ``order_match_audit`` for full WS-snapshot history per order.

    Every WS snapshot we process for a ``client_order_id`` is logged here in
    ``snapshot_seq`` order with the absolute counters, the deltas we computed,
    and the raw payload. Lets us reconstruct any past order's full WS history
    end-to-end and is the audit substrate for the reconciliation job.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS order_match_audit (
        id BIGSERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        client_order_id VARCHAR(40) NOT NULL,
        snapshot_seq INTEGER NOT NULL,
        cumulative_quantity DECIMAL(18, 8) NOT NULL,
        filled_value DECIMAL(20, 8) NOT NULL,
        total_fees DECIMAL(16, 8) NOT NULL,
        number_of_fills INTEGER NOT NULL,
        leaves_quantity DECIMAL(18, 8) NOT NULL,
        outstanding_hold_amount DECIMAL(20, 8) NOT NULL,
        status VARCHAR(20) NOT NULL,
        derived_size_delta DECIMAL(18, 8) NOT NULL,
        derived_value_delta DECIMAL(20, 8) NOT NULL,
        derived_fee_delta DECIMAL(16, 8) NOT NULL,
        derived_price DECIMAL(20, 8),
        derived_trade_key UUID,
        emitted_fill_ledger_row BOOLEAN NOT NULL DEFAULT FALSE,
        raw_payload_json JSONB NOT NULL,
        UNIQUE (client_order_id, snapshot_seq)
    );
    CREATE INDEX IF NOT EXISTS idx_order_match_audit_client_order
        ON order_match_audit (client_order_id);
    CREATE INDEX IF NOT EXISTS idx_order_match_audit_derived_trade_key
        ON order_match_audit (derived_trade_key)
        WHERE derived_trade_key IS NOT NULL;
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("order_match_audit table done.")
    install_order_follow_up_source_lock_trigger("order_match_audit")


def insert_order_match_audit(
    client_order_id: str,
    snapshot_seq: int,
    cumulative_quantity: float,
    filled_value: float,
    total_fees: float,
    number_of_fills: int,
    leaves_quantity: float,
    outstanding_hold_amount: float,
    status: str,
    derived_size_delta: float,
    derived_value_delta: float,
    derived_fee_delta: float,
    derived_price: Optional[float],
    derived_trade_key: Optional[str],
    emitted_fill_ledger_row: bool,
    raw_payload_json: str,
) -> Optional[int]:
    """Insert one row into ``order_match_audit``. Idempotent on (client_order_id, snapshot_seq)."""
    query = """
    INSERT INTO order_match_audit (
        client_order_id, snapshot_seq,
        cumulative_quantity, filled_value, total_fees, number_of_fills,
        leaves_quantity, outstanding_hold_amount, status,
        derived_size_delta, derived_value_delta, derived_fee_delta,
        derived_price, derived_trade_key, emitted_fill_ledger_row,
        raw_payload_json
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
    )
    ON CONFLICT (client_order_id, snapshot_seq) DO NOTHING
    RETURNING id
    """
    params = (
        client_order_id, snapshot_seq,
        cumulative_quantity, filled_value, total_fees, number_of_fills,
        leaves_quantity, outstanding_hold_amount, status,
        derived_size_delta, derived_value_delta, derived_fee_delta,
        derived_price, derived_trade_key, emitted_fill_ledger_row,
        raw_payload_json,
    )
    try:
        results = DB_CLIENT.execute_query(query, params)
        return results[0]["id"] if results else None
    except Exception as e:
        logger.error(
            f"âœ— Error inserting order_match_audit row for {client_order_id} "
            f"seq={snapshot_seq}: {type(e).__name__}: {e}"
        )
        return None


def create_order_event_stream_table() -> None:
    """Create append-only order_event_stream table for timeline reconstruction.

    This table captures a normalized event timeline across order submission,
    status transitions, stealth reveal triggers, and fill persistence hooks.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS order_event_stream (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        event_id UUID UNIQUE NOT NULL,
        event_time_exchange TIMESTAMP,
        event_time_ingested TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        product_id VARCHAR(32),
        client_order_id VARCHAR(64),
        order_id VARCHAR(64),
        parent_client_order_id VARCHAR(64),
        stealth_order_id VARCHAR(64),
        event_type VARCHAR(64) NOT NULL,
        event_status_from VARCHAR(32),
        event_status_to VARCHAR(32),
        side VARCHAR(10),
        price DECIMAL(18, 8),
        size DECIMAL(18, 8),
        cumulative_filled_size DECIMAL(18, 8),
        leaves_size DECIMAL(18, 8),
        fee DECIMAL(18, 8),
        fee_currency VARCHAR(16),
        trigger_type VARCHAR(64),
        trigger_payload_json JSONB,
        source_channel VARCHAR(64),
        raw_payload_json JSONB,
        idempotency_key VARCHAR(200) UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_order_event_stream_event_time_exchange ON order_event_stream(event_time_exchange);
    CREATE INDEX IF NOT EXISTS idx_order_event_stream_client_order_id ON order_event_stream(client_order_id);
    CREATE INDEX IF NOT EXISTS idx_order_event_stream_event_type ON order_event_stream(event_type);
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("order_event_stream table done.")
    install_order_follow_up_source_lock_trigger("order_event_stream")


def insert_order_event(
    event_id: str,
    event_type: str,
    source_channel: str,
    event_time_exchange=None,
    product_id: str = None,
    client_order_id: str = None,
    order_id: str = None,
    parent_client_order_id: str = None,
    stealth_order_id: str = None,
    event_status_from: str = None,
    event_status_to: str = None,
    side: str = None,
    price: float = None,
    size: float = None,
    cumulative_filled_size: float = None,
    leaves_size: float = None,
    fee: float = None,
    fee_currency: str = None,
    trigger_type: str = None,
    trigger_payload_json: Dict[str, Any] = None,
    raw_payload_json: Dict[str, Any] = None,
    idempotency_key: str = None,
) -> Optional[int]:
    """Insert one immutable event record into order_event_stream.

    Returns inserted row id, or None when conflict/no-op/error.
    """
    query = """
    INSERT INTO order_event_stream (
        event_id,
        event_time_exchange,
        product_id,
        client_order_id,
        order_id,
        parent_client_order_id,
        stealth_order_id,
        event_type,
        event_status_from,
        event_status_to,
        side,
        price,
        size,
        cumulative_filled_size,
        leaves_size,
        fee,
        fee_currency,
        trigger_type,
        trigger_payload_json,
        source_channel,
        raw_payload_json,
        idempotency_key
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s::jsonb, %s,
        %s::jsonb, %s
    )
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id
    """

    params = (
        event_id,
        event_time_exchange,
        product_id,
        client_order_id,
        order_id,
        parent_client_order_id,
        stealth_order_id,
        event_type,
        event_status_from,
        event_status_to,
        side,
        price,
        size,
        cumulative_filled_size,
        leaves_size,
        fee,
        fee_currency,
        trigger_type,
        json.dumps(trigger_payload_json or {}, default=_json_default_for_db),
        source_channel,
        json.dumps(raw_payload_json or {}, default=_json_default_for_db),
        idempotency_key,
    )

    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            return results[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Error inserting order event {event_type} ({event_id}): {type(e).__name__}: {e}")
        return None


def insert_fill_record(
    derived_trade_key: str,
    instrument: str,
    side: str,
    quantity: float,
    price: float,
    timestamp,
    fees: float = 0.0,
    commission_percentage: float = 0.0,
    client_order_id: str = None,
    exchange_trade_id: Optional[str] = None,
    exchange_entry_id: Optional[str] = None,
) -> Optional[int]:
    """
    Insert a fill record into the fill_ledger table.

    Append-only record of one derived match (a per-match cumulative-counter
    delta on the WS user channel). Idempotent on ``derived_trade_key``: a
    duplicate insert silently no-ops via the UNIQUE constraint.

    Args:
        derived_trade_key: Synthetic UUID derived from
            (client_order_id, cumulative_quantity). Always required.
        instrument: Product ID (e.g., 'BTC-USDC')
        side: 'BUY' or 'SELL'
        quantity: Amount filled in this match
        price: Fill price for this match
        timestamp: When the fill occurred
        fees: Fees attributable to this match
        commission_percentage: Commission rate as decimal
        client_order_id: Originating order's client_order_id
        exchange_trade_id: REST-confirmed exchange trade id (set by reconciler)
        exchange_entry_id: REST-confirmed entry id (set by reconciler)

    Returns:
        The inserted row id on success, ``None`` on duplicate or error.
    """
    query = """
    WITH product_lock AS MATERIALIZED (
        SELECT pg_advisory_xact_lock(hashtext(%s))
    )
    INSERT INTO fill_ledger (
        derived_trade_key,
        exchange_trade_id,
        exchange_entry_id,
        instrument,
        side,
        quantity,
        price,
        timestamp,
        fees,
        commission_percentage,
        client_order_id
    )
    SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    FROM product_lock
    ON CONFLICT (derived_trade_key) DO NOTHING
    RETURNING id
    """
    params = (
        fill_ledger_product_lock_key(instrument),
        derived_trade_key,
        exchange_trade_id,
        exchange_entry_id,
        instrument,
        side,
        quantity,
        price,
        timestamp,
        fees,
        commission_percentage,
        client_order_id,
    )

    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]["id"]
            logger.info(
                f"âœ“ Fill recorded: {derived_trade_key} ({instrument} {side} {quantity} @ {price}, "
                f"fees: {fees}, commission: {commission_percentage})"
            )
            return inserted_id
        return None
    except Exception as e:
        logger.error(
            f"âœ— Error inserting fill record {derived_trade_key}: {type(e).__name__}: {e}"
        )
        logger.debug(
            f"  Fill details - instrument: {instrument}, side: {side}, "
            f"quantity: {quantity}, price: {price}"
        )
        return None


def get_fills_by_instrument(instrument: str) -> List[Dict[str, Any]]:
    """
    Retrieve all fills for a given instrument.
    
    Args:
        instrument: Product ID (e.g., 'BTC-USDC')
    
    Returns:
        List of fill records for the instrument, ordered by timestamp.
    """
    query = """
    SELECT * FROM fill_ledger 
    WHERE instrument = %s 
    ORDER BY timestamp ASC
    """
    return DB_CLIENT.execute_query(query, (instrument,))


def get_fills_by_order(client_order_id: str) -> List[Dict[str, Any]]:
    """
    Retrieve all fills for a specific order.
    
    Args:
        client_order_id: The client_order_id to look up
    
    Returns:
        List of fill records for the order, ordered by timestamp.
    """
    query = """
    SELECT * FROM fill_ledger 
    WHERE client_order_id = %s 
    ORDER BY timestamp ASC
    """
    return DB_CLIENT.execute_query(query, (client_order_id,))


def get_fills_since(instrument: str, since_timestamp) -> List[Dict[str, Any]]:
    """
    Retrieve fills for an instrument since a given timestamp.
    
    Useful for incremental updates and reporting.
    
    Args:
        instrument: Product ID (e.g., 'BTC-USDC')
        since_timestamp: Start time for the range query
    
    Returns:
        List of fill records since the timestamp, ordered by timestamp.
    """
    query = """
    SELECT * FROM fill_ledger 
    WHERE instrument = %s AND timestamp >= %s 
    ORDER BY timestamp ASC
    """
    return DB_CLIENT.execute_query(query, (instrument, since_timestamp))


def create_conditional_orders_table() -> None:
    """
    Create the conditional_orders table for persistent conditional order storage.
    
    Stores conditional orders that must survive engine restarts.
    Conditional orders wait for market conditions before submission.
    
    Table columns:
    - id: Auto-increment primary key
    - conditional_order_id: Unique UUID for the conditional order
    - base_order_id: Reference to order_parent.client_order_id (FK, on delete cascade)
    - product_id: Product ID (e.g., 'BTC-USDC')
    - side: Order side ('BUY' or 'SELL')
    - size: Order size/quantity (DECIMAL(16,8))
    - price: Order price (DECIMAL(16,2))
    - min_profitable_price: Minimum profitable exit price (DECIMAL(16,2))
    - status: ConditionalOrderStatus enum as VARCHAR
    - created_at: When the conditional order was created
    - submitted_at: When submitted to exchange (NULL until submitted)
    - filled_at: When fully filled (NULL until filled)
    - execution_price: Actual execution price (NULL until filled)
    - notes: Optional additional details
    
    Indexes for query performance:
    - product_id: Fast lookup by product
    - status: Query awaiting orders for evaluation
    - conditional_order_id: UNIQUE for PK
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS conditional_orders (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        conditional_order_id UUID UNIQUE NOT NULL,
        base_order_id VARCHAR(40) NOT NULL,
        product_id VARCHAR(32) NOT NULL,
        side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
        size DECIMAL(16, 8) NOT NULL,
        price DECIMAL(16, 2) NOT NULL,
        min_profitable_price DECIMAL(16, 2) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'AWAITING_CONDITION',
        submitted_at TIMESTAMP,
        filled_at TIMESTAMP,
        execution_price DECIMAL(16, 2),
        notes TEXT,
        FOREIGN KEY (base_order_id) REFERENCES order_parent(client_order_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_conditional_orders_product_id ON conditional_orders(product_id);
    CREATE INDEX IF NOT EXISTS idx_conditional_orders_status ON conditional_orders(status);
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("conditional_orders table done.")


def insert_conditional_order(
    conditional_order_id: str,
    base_order_id: str,
    product_id: str,
    side: str,
    size: float,
    price: float,
    min_profitable_price: float,
    notes: str = None
) -> Optional[int]:
    """
    Insert a conditional order into persistent storage.
    
    Args:
        conditional_order_id: Unique UUID for this conditional order
        base_order_id: Reference to order_parent.client_order_id
        product_id: Product ID (e.g., 'BTC-USDC')
        side: 'BUY' or 'SELL'
        size: Order size (float)
        price: Order price (float)
        min_profitable_price: Minimum profitable exit price (float)
        notes: Optional additional context
    
    Returns:
        The inserted conditional order's database ID if successful, None if failed.
    """
    query = """
    INSERT INTO conditional_orders (
        conditional_order_id,
        base_order_id,
        product_id,
        side,
        size,
        price,
        min_profitable_price,
        notes,
        status
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'AWAITING_CONDITION')
    RETURNING id
    """
    params = (
        conditional_order_id,
        base_order_id,
        product_id,
        side,
        size,
        price,
        min_profitable_price,
        notes
    )
    
    try:
        results = DB_CLIENT.execute_query(query, params)
        if results:
            inserted_id = results[0]["id"]
            logger.info(
                f"âœ“ Conditional order inserted: {conditional_order_id} "
                f"({product_id} {side} {size} @ {price}, min_profit: {min_profitable_price})"
            )
            return inserted_id
        return None
    except Exception as e:
        logger.error(f"âœ— Error inserting conditional order {conditional_order_id}: {type(e).__name__}: {e}")
        logger.debug(f"  Conditional order details - product: {product_id}, side: {side}, size: {size}, price: {price}")
        return None


def update_stealth_order_lifecycle_event(
    stealth_order_id: str,
    lifecycle_event: str,
    failure_reason: Optional[str] = None,
) -> bool:
    """Persist the most recent StealthLifecycleEvent for a stealth order.

    Called by StealthOrderManager (via the stealth lifecycle hook dispatcher)
    after each transition so the database reflects the current lifecycle state.
    This enables OrderInventory.rebuild_from_database() to restore the
    ``last_event`` and ``failure_reason`` fields after a restart.

    Args:
        stealth_order_id: UUID of the stealth order.
        lifecycle_event:  StealthLifecycleEvent value string (e.g. 'REVEAL_FAILED').
        failure_reason:   Human-readable failure reason for PLACEMENT_BLOCKED /
                          REVEAL_FAILED events.  Pass None to leave existing value.

    Returns:
        True if the row was updated, False otherwise.

    Example:
        >>> update_stealth_order_lifecycle_event(
        ...     stealth_order_id="550e8400-...",
        ...     lifecycle_event="REVEAL_FAILED",
        ...     failure_reason="Connection timeout to Coinbase REST API",
        ... )
        True
    """
    try:
        if failure_reason is not None:
            query = """
            UPDATE stealth_orders
            SET    last_lifecycle_event = %s,
                   failure_reason       = %s,
                   updated_at           = CURRENT_TIMESTAMP
            WHERE  stealth_order_id = %s
            """
            params = (lifecycle_event, failure_reason, stealth_order_id)
        else:
            query = """
            UPDATE stealth_orders
            SET    last_lifecycle_event = %s,
                   updated_at           = CURRENT_TIMESTAMP
            WHERE  stealth_order_id = %s
            """
            params = (lifecycle_event, stealth_order_id)

        rows = DB_CLIENT.execute_update(query, params)
        return rows > 0
    except Exception as exc:
        logger.error(
            f"update_stealth_order_lifecycle_event failed for {stealth_order_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def insert_stealth_order_lifecycle_event(
    stealth_order_id: str,
    lifecycle_event: str,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Insert one immutable lifecycle transition row for a stealth order.

    The previous lifecycle event is read from the current stealth_orders row so the
    audit history preserves transition direction without relying on in-memory state.
    """
    context = dict(context or {})

    status_map = {
        "CREATED": "HIDDEN",
        "CONDITION_WATCHING": "PENDING",
        "CONDITION_MET": "TRIGGERED",
        "REVEAL_ATTEMPTED": "TRIGGERED",
        "PLACEMENT_BLOCKED": "TRIGGERED",
        "REVEAL_FAILED": "TRIGGERED",
        "REVEAL_SUCCEEDED": "REVEALED",
        "FILL_RECEIVED": "REVEALED",
        "EXECUTED": "EXECUTED",
        "CANCELLED": "CANCELLED",
    }

    try:
        existing_rows = DB_CLIENT.execute_query(
            """
            SELECT last_lifecycle_event
            FROM stealth_orders
            WHERE stealth_order_id = %s
            """,
            (stealth_order_id,),
        )
        previous_event = existing_rows[0].get("last_lifecycle_event") if existing_rows else None
        status_from = status_map.get(previous_event) if previous_event else None
        status_to = context.get("status") or status_map.get(lifecycle_event)

        query = """
        INSERT INTO stealth_order_lifecycle_history (
            stealth_order_id,
            lifecycle_event,
            previous_lifecycle_event,
            status_from,
            status_to,
            event_time,
            product_id,
            side,
            size,
            total_size,
            limit_price,
            reason,
            parent_order_id,
            placed_order_id,
            exchange_order_id,
            failure_reason,
            context_json
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
        )
        RETURNING id
        """

        params = (
            stealth_order_id,
            lifecycle_event,
            previous_event,
            status_from,
            status_to,
            context.get("timestamp"),
            context.get("product_id"),
            context.get("side"),
            context.get("size"),
            context.get("total_size"),
            context.get("limit_price"),
            context.get("reason"),
            context.get("parent_order_id"),
            context.get("placed_order_id"),
            context.get("exchange_order_id"),
            context.get("failure_reason"),
            json.dumps(context, default=str),
        )

        with DB_CLIENT.get_cursor() as cursor:
            cursor.execute(query, params)
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception as exc:
        logger.error(
            f"insert_stealth_order_lifecycle_event failed for {stealth_order_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None


def update_stealth_audit_exchange_order_id(
    stealth_order_id: str,
    placed_order_id: str,
    exchange_order_id: str,
) -> bool:
    """Backfill audit-only exchange_order_id onto stealth history rows.

    Internal orchestration continues to use client_order_id/placed_order_id.
    This helper only enriches audit surfaces once Coinbase later provides the
    external exchange order UUID via websocket events.
    """
    if not stealth_order_id or not placed_order_id or not exchange_order_id:
        return False

    try:
        column_rows = DB_CLIENT.execute_query(
            """
            SELECT table_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name = 'exchange_order_id'
              AND table_name IN ('stealth_order_lifecycle_history', 'stealth_order_reveal_history')
            """
        )
        tables_with_column = {row["table_name"] for row in column_rows}

        updated = False
        if "stealth_order_lifecycle_history" in tables_with_column:
            lifecycle_rows = DB_CLIENT.execute_update(
                """
                UPDATE stealth_order_lifecycle_history
                SET exchange_order_id = %s
                WHERE stealth_order_id = %s
                  AND placed_order_id = %s
                  AND COALESCE(exchange_order_id, '') = ''
                """,
                (exchange_order_id, stealth_order_id, placed_order_id),
            )
            updated = updated or lifecycle_rows > 0

        if "stealth_order_reveal_history" in tables_with_column:
            reveal_rows = DB_CLIENT.execute_update(
                """
                UPDATE stealth_order_reveal_history
                SET exchange_order_id = %s
                WHERE stealth_order_id = %s
                  AND placed_order_id = %s
                  AND COALESCE(exchange_order_id, '') = ''
                """,
                (exchange_order_id, stealth_order_id, placed_order_id),
            )
            updated = updated or reveal_rows > 0

        return updated
    except Exception as exc:
        logger.error(
            f"update_stealth_audit_exchange_order_id failed for {stealth_order_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def get_stealth_order_lifecycle_history(
    stealth_order_id: str,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return lifecycle transition history for a stealth order, newest first."""
    query = """
    SELECT *
    FROM stealth_order_lifecycle_history
    WHERE stealth_order_id = %s
    ORDER BY created_at DESC, id DESC
    LIMIT %s
    """
    return DB_CLIENT.execute_query(query, (stealth_order_id, limit))


def get_conditional_order(conditional_order_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a conditional order by ID.
    
    Args:
        conditional_order_id: The UUID of the conditional order
    
    Returns:
        Conditional order dict if found, None otherwise.
    """
    query = """
    SELECT * FROM conditional_orders 
    WHERE conditional_order_id = %s
    """
    results = DB_CLIENT.execute_query(query, (conditional_order_id,))
    return results[0] if results else None


def get_awaiting_conditional_orders(product_id: str = None) -> List[Dict[str, Any]]:
    """
    Retrieve all conditional orders awaiting condition evaluation.
    
    Args:
        product_id: Optional filter by product ID. If None, returns all awaiting orders.
    
    Returns:
        List of conditional orders with status='AWAITING_CONDITION'.
    """
    if product_id:
        query = """
        SELECT * FROM conditional_orders 
        WHERE status = 'AWAITING_CONDITION' AND product_id = %s 
        ORDER BY created_at ASC
        """
        return DB_CLIENT.execute_query(query, (product_id,))
    else:
        query = """
        SELECT * FROM conditional_orders 
        WHERE status = 'AWAITING_CONDITION' 
        ORDER BY created_at ASC
        """
        return DB_CLIENT.execute_query(query)


def update_conditional_order_status(
    conditional_order_id: str,
    status: str
) -> int:
    """
    Update the status of a conditional order.
    
    Args:
        conditional_order_id: The UUID of the conditional order
        status: New status value (e.g., 'CONDITION_MET', 'SUBMITTED', 'FILLED')
    
    Returns:
        Number of rows updated (0 or 1).
    """
    query = """
    UPDATE conditional_orders 
    SET status = %s 
    WHERE conditional_order_id = %s
    """
    result = DB_CLIENT.execute_update(query, (status, conditional_order_id))
    if result > 0:
        logger.info(f"Conditional order status updated: {conditional_order_id} -> {status}")
    return result


def mark_conditional_submitted(conditional_order_id: str) -> int:
    """
    Mark a conditional order as submitted to the exchange.
    
    Sets status='SUBMITTED' and submitted_at=CURRENT_TIMESTAMP.
    
    Args:
        conditional_order_id: The UUID of the conditional order
    
    Returns:
        Number of rows updated (0 or 1).
    """
    query = """
    UPDATE conditional_orders 
    SET status = 'SUBMITTED', 
        submitted_at = CURRENT_TIMESTAMP
    WHERE conditional_order_id = %s
    """
    result = DB_CLIENT.execute_update(query, (conditional_order_id,))
    if result > 0:
        logger.info(f"Conditional order marked submitted: {conditional_order_id}")
    return result


def mark_conditional_filled(
    conditional_order_id: str,
    execution_price: float
) -> int:
    """
    Mark a conditional order as filled.
    
    Sets status='FILLED', filled_at=CURRENT_TIMESTAMP, and execution_price.
    
    Args:
        conditional_order_id: The UUID of the conditional order
        execution_price: The actual execution price (float)
    
    Returns:
        Number of rows updated (0 or 1).
    """
    query = """
    UPDATE conditional_orders 
    SET status = 'FILLED', 
        filled_at = CURRENT_TIMESTAMP,
        execution_price = %s
    WHERE conditional_order_id = %s
    """
    result = DB_CLIENT.execute_update(query, (execution_price, conditional_order_id))
    if result > 0:
        logger.info(f"Conditional order marked filled: {conditional_order_id} @ {execution_price}")
    return result


def cancel_conditional_order(conditional_order_id: str) -> int:
    """
    Cancel a conditional order.
    
    Sets status='CANCELLED'.
    
    Args:
        conditional_order_id: The UUID of the conditional order
    
    Returns:
        Number of rows updated (0 or 1).
    """
    query = """
    UPDATE conditional_orders 
    SET status = 'CANCELLED' 
    WHERE conditional_order_id = %s
    """
    result = DB_CLIENT.execute_update(query, (conditional_order_id,))
    if result > 0:
        logger.info(f"Conditional order cancelled: {conditional_order_id}")
    return result


# ---------------------------------------------------------------------------
# partial_fill_progress table â€“ restart-resilient partial fill watermarks
# ---------------------------------------------------------------------------

def create_partial_fill_progress_table() -> None:
    """Create the partial_fill_progress table for restart-resilient partial fill tracking.

    Each row holds the high-watermark state for one active order that has been
    enabled for partial-fill follow-up creation.  The row is upserted on every
    OPEN/UPDATE event that advances the cumulative fill and cleared (status set
    to FINALIZED or CANCELLED) when the order reaches a terminal state.

    Table columns:
        client_order_id               â€“ FK to order_parent; also the natural PK
        parent_client_order_id        â€“ root parent for flat hierarchy linking
        product_id                    â€“ trading pair (informational)
        side                          â€“ BUY / SELL
        original_order_size           â€“ total size of the placed child order
        min_order_size                â€“ minimum base increment for the product
        last_cumulative_qty_processed â€“ highest cumulative_quantity seen and acted on
        carry_remainder_qty           â€“ sub-minimum accumulator carried forward
        last_number_of_fills_seen     â€“ dedup helper; mirrors number_of_fills field
        last_completion_pct_seen      â€“ completion_percentage watermark (0-100)
        partial_follow_ups_created    â€“ count of follow-up orders spawned so far
        status                        â€“ ACTIVE | FINALIZED | CANCELLED
        created_at / updated_at       â€“ timestamps
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS partial_fill_progress (
        id SERIAL PRIMARY KEY,
        client_order_id VARCHAR(40) NOT NULL UNIQUE,
        parent_client_order_id VARCHAR(40),
        product_id VARCHAR(32),
        side VARCHAR(10),
        original_order_size NUMERIC(18, 8) NOT NULL DEFAULT 0,
        min_order_size NUMERIC(18, 8) NOT NULL DEFAULT 0,
        last_cumulative_qty_processed NUMERIC(18, 8) NOT NULL DEFAULT 0,
        carry_remainder_qty NUMERIC(18, 8) NOT NULL DEFAULT 0,
        last_number_of_fills_seen INTEGER NOT NULL DEFAULT 0,
        last_completion_pct_seen NUMERIC(7, 4) NOT NULL DEFAULT 0,
        partial_follow_ups_created INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (client_order_id) REFERENCES order_parent(client_order_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_partial_fill_progress_status
        ON partial_fill_progress (status);
    CREATE INDEX IF NOT EXISTS idx_partial_fill_progress_parent
        ON partial_fill_progress (parent_client_order_id);
    """
    with DB_CLIENT.get_cursor() as cursor:
        cursor.execute(create_table_query)
        print("partial_fill_progress table done.")
    install_order_follow_up_source_lock_trigger("partial_fill_progress")


def upsert_partial_fill_progress(
    client_order_id: str,
    parent_client_order_id: Optional[str],
    product_id: Optional[str],
    side: Optional[str],
    original_order_size: float,
    min_order_size: float,
    last_cumulative_qty_processed: float,
    carry_remainder_qty: float,
    last_number_of_fills_seen: int,
    last_completion_pct_seen: float,
    partial_follow_ups_created: int,
) -> bool:
    """Insert or update the partial-fill watermark for a single child order.

    Uses INSERT â€¦ ON CONFLICT (client_order_id) DO UPDATE so both the initial
    row creation and every subsequent watermark advance are handled atomically.

    Returns:
        True on success, False on error.
    """
    query = """
    INSERT INTO partial_fill_progress (
        client_order_id,
        parent_client_order_id,
        product_id,
        side,
        original_order_size,
        min_order_size,
        last_cumulative_qty_processed,
        carry_remainder_qty,
        last_number_of_fills_seen,
        last_completion_pct_seen,
        partial_follow_ups_created,
        status,
        updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', CURRENT_TIMESTAMP)
    ON CONFLICT (client_order_id) DO UPDATE SET
        last_cumulative_qty_processed = EXCLUDED.last_cumulative_qty_processed,
        carry_remainder_qty           = EXCLUDED.carry_remainder_qty,
        last_number_of_fills_seen     = EXCLUDED.last_number_of_fills_seen,
        last_completion_pct_seen      = EXCLUDED.last_completion_pct_seen,
        partial_follow_ups_created    = EXCLUDED.partial_follow_ups_created,
        original_order_size           = EXCLUDED.original_order_size,
        min_order_size                = EXCLUDED.min_order_size,
        status                        = 'ACTIVE',
        updated_at                    = CURRENT_TIMESTAMP
    """
    params = (
        client_order_id,
        parent_client_order_id,
        product_id,
        side,
        original_order_size,
        min_order_size,
        last_cumulative_qty_processed,
        carry_remainder_qty,
        last_number_of_fills_seen,
        last_completion_pct_seen,
        partial_follow_ups_created,
    )
    try:
        DB_CLIENT.execute_update(query, params)
        logger.debug(
            f"[PARTIAL-FILL] Progress upserted: {client_order_id} "
            f"cumulative={last_cumulative_qty_processed} carry={carry_remainder_qty}"
        )
        return True
    except Exception as e:
        logger.error(f"[PARTIAL-FILL] upsert_partial_fill_progress failed for {client_order_id}: {type(e).__name__}: {e}")
        return False


def get_partial_fill_progress(client_order_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the current partial-fill watermark row for a single child order.

    Returns:
        Dict of column values, or None if no row exists.
    """
    query = """
    SELECT * FROM partial_fill_progress
    WHERE client_order_id = %s
    LIMIT 1
    """
    try:
        results = DB_CLIENT.execute_query(query, (client_order_id,))
        return results[0] if results else None
    except Exception as e:
        logger.error(f"[PARTIAL-FILL] get_partial_fill_progress failed for {client_order_id}: {type(e).__name__}: {e}")
        return None


def get_all_active_partial_fill_progress(
    *,
    raise_on_error: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve all ACTIVE partial-fill watermark rows for engine restart hydration.

    Returns:
        List of dicts; empty list on error or when no active rows exist.
    """
    query = """
    SELECT * FROM partial_fill_progress
    WHERE status = 'ACTIVE'
    ORDER BY created_at ASC
    """
    try:
        return DB_CLIENT.execute_query(query) or []
    except Exception as e:
        logger.error(f"[PARTIAL-FILL] get_all_active_partial_fill_progress failed: {type(e).__name__}: {e}")
        if raise_on_error:
            raise
        return []


def finalize_partial_fill_progress(client_order_id: str, status: str) -> bool:
    """Mark a partial-fill progress row as terminal (FINALIZED or CANCELLED).

    Called when the originating order reaches a terminal exchange status so the
    engine no longer needs to track it across restarts.

    Args:
        client_order_id: The child order whose progress row to close.
        status:          Terminal status string â€“ 'FINALIZED' or 'CANCELLED'.

    Returns:
        True if a row was updated, False otherwise.
    """
    query = """
    UPDATE partial_fill_progress
    SET status = %s,
        updated_at = CURRENT_TIMESTAMP
    WHERE client_order_id = %s
      AND status = 'ACTIVE'
    """
    try:
        rows = DB_CLIENT.execute_update(query, (status, client_order_id))
        if rows > 0:
            logger.info(f"[PARTIAL-FILL] Progress finalized: {client_order_id} -> {status}")
        return rows > 0
    except Exception as e:
        logger.error(f"[PARTIAL-FILL] finalize_partial_fill_progress failed for {client_order_id}: {type(e).__name__}: {e}")
        return False


# ============================================================================
# Hotpoint Auto-Replicate — query helpers
# ============================================================================

def get_recent_auto_placed_hotpoint_rows(window_seconds: int) -> List[Dict[str, Any]]:
    """Return rows auto-placed by hotpoint within the last ``window_seconds``.

    Used by ``HotpointRateLimiter`` at engine startup to rebuild the
    sliding-window counter from persisted state. Returns the columns the
    limiter needs to compute the bucket id (price + product) and an
    ``epoch_seconds`` timestamp.

    Returns:
        List of dicts with keys: ``client_order_id``, ``product_id``,
        ``side``, ``price``, ``epoch_seconds``.
    """
    query = """
    SELECT client_order_id,
           product_id,
           side,
           price,
           EXTRACT(EPOCH FROM created_at)::float8 AS epoch_seconds
      FROM order_parent
     WHERE auto_placed_by_hotpoint = TRUE
       AND created_at > NOW() - make_interval(secs => %s)
    """
    try:
        rows = DB_CLIENT.execute_query(query, (int(window_seconds),)) or []
        return list(rows)
    except Exception as e:
        logger.error(
            f"\u2717 get_recent_auto_placed_hotpoint_rows failed: {type(e).__name__}: {e}"
        )
        return []


def get_open_auto_placed_hotpoint_rows() -> List[Dict[str, Any]]:
    """Return currently-resting auto-placed hotpoint rows.

    Used by the decay sweeper to find candidates for cancellation when
    their bucket has cooled.

    Returns:
        List of dicts with keys: ``client_order_id``, ``product_id``,
        ``side``, ``price``.
    """
    query = """
    SELECT client_order_id,
           product_id,
           side,
           price
      FROM order_parent
     WHERE auto_placed_by_hotpoint = TRUE
       AND status IN ('OPEN', 'PENDING', 'pending', 'open')
    """
    try:
        rows = DB_CLIENT.execute_query(query) or []
        return list(rows)
    except Exception as e:
        logger.error(
            f"\u2717 get_open_auto_placed_hotpoint_rows failed: {type(e).__name__}: {e}"
        )
        return []
