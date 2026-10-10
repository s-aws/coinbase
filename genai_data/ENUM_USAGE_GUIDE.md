# Enum Usage Guide

Reconciled on 2026-10-09 from `core/enums.py`. Import directly from that module;
`core/__init__.py` re-exports only a subset. Use enum members inside domain code
and `.value` for persisted/wire values. UI JSON uses the same wire values.

`OrderStatus` is exchange-placement lifecycle. `WebSocketEventType` is envelope
kind (`snapshot`, `update`, `patch`), and `UserFeedPhase` is connection bootstrap
state. Synthetic legacy `OrderStatus.UPDATE`/`SNAPSHOT` are not canonical live
order statuses. Logical `StealthOrderStatus.CANCELLED` may precede confirmed
withdrawal: preserve tracked exposure and operator-stop intent.

`ProductType` contains SPOT and FUTURE; perpetual/expiring classification is
separate in `ContractExpiryType`. Use the shared `normalize_product_type` helper in `calculation/resolver.py` rather than guessing
expiry month strings.

## Current enum inventory

| Enum | Members and wire values |
| --- | --- |
| `OrderSide` | `BUY=BUY`, `SELL=SELL` |
| `OrderStatus` | `PENDING=PENDING`, `OPEN=OPEN`, `FILLED=FILLED`, `CANCELLED=CANCELLED`, `EXPIRED=EXPIRED`, `FAILED=FAILED`, `QUEUED=QUEUED`, `CANCEL_QUEUED=CANCEL_QUEUED`, `EDIT_QUEUED=EDIT_QUEUED`, `UPDATE=UPDATE`, `SNAPSHOT=SNAPSHOT` |
| `OrderPlacementOutcome` | `ACCEPTED=ACCEPTED`, `REJECTED=REJECTED`, `INDETERMINATE=INDETERMINATE` |
| `StealthOrderStatus` | `HIDDEN=HIDDEN`, `PENDING=PENDING`, `TRIGGERED=TRIGGERED`, `REVEALED=REVEALED`, `ERROR=ERROR`, `EXECUTED=EXECUTED`, `CANCELLED=CANCELLED` |
| `OrderType` | `LIMIT=LIMIT`, `MARKET=MARKET`, `STOP_LIMIT=STOP_LIMIT` |
| `TimeInForce` | `GOOD_UNTIL_CANCELLED=GOOD_UNTIL_CANCELLED`, `IMMEDIATE_OR_CANCEL=IMMEDIATE_OR_CANCEL`, `FILL_OR_KILL=FILL_OR_KILL`, `GOOD_UNTIL_DATE_TIME=GOOD_UNTIL_DATE_TIME`, `GTC=GOOD_UNTIL_CANCELLED`, `IOC=IMMEDIATE_OR_CANCEL`, `FOK=FILL_OR_KILL`, `GTD=GOOD_UNTIL_DATE_TIME` |
| `TriggerStatus` | `UNKNOWN_TRIGGER_STATUS=UNKNOWN_TRIGGER_STATUS`, `INVALID_ORDER_TYPE=INVALID_ORDER_TYPE`, `STOP_PENDING=STOP_PENDING`, `STOP_TRIGGERED=STOP_TRIGGERED` |
| `ProductType` | `SPOT=SPOT`, `FUTURE=FUTURE` |
| `ProductStatus` | `OPEN=OPEN`, `CLOSED=CLOSED`, `POST_ONLY=POST_ONLY`, `LIMIT_ONLY=LIMIT_ONLY` |
| `ContractExpiryType` | `PERPETUAL=PERPETUAL`, `EXPIRING=EXPIRING`, `UNKNOWN_CONTRACT_EXPIRY_TYPE=UNKNOWN_CONTRACT_EXPIRY_TYPE` |
| `ProductVenue` | `CBE=CBE`, `FCM=FCM` |
| `FeeScheduleSource` | `DEFAULT=default`, `COINBASE=coinbase` |
| `LiquidityAssumption` | `MAKER=maker`, `TAKER=taker` |
| `Direction` | `ABOVE=above`, `BELOW=below` |
| `RoundingDirection` | `UP=up`, `DOWN=down`, `NEAREST=nearest` |
| `PriceRoundingPolicy` | `SIDE_CONSERVATIVE=side_conservative`, `NEAREST=nearest`, `UP=up`, `DOWN=down` |
| `FollowUpRevealDirection` | `SAME=same`, `OPPOSITE=opposite` |
| `FollowUpKind` | `FILLED=filled`, `CANCELLED=cancelled` |
| `StealthMutationKind` | `MOVE=move`, `REPRICE=reprice`, `REHIDE=rehide` |
| `StealthMoveReason` | `MANUAL_USER_MOVE=manual_user_move`, `OPERATOR_REPRICE=operator_reprice` |
| `RevealPricingPolicy` | `CONFIGURED_LIMIT=configured_limit`, `TOP_OF_BOOK=top_of_book`, `MIDPOINT=midpoint` |
| `RevealPriceSource` | `CONFIGURED_LIMIT=configured_limit`, `TICKER_BEST_BID=ticker_best_bid`, `TICKER_BEST_ASK=ticker_best_ask`, `TICKER_MIDPOINT=ticker_midpoint`, `UNAVAILABLE=unavailable` |
| `RevealConditionType` | `PRICE_THRESHOLD=price`, `CUMULATIVE_VOLUME=cumulative_volume`, `TIME_DELAY=time_delay`, `SPREAD=spread`, `PRODUCT_RATIO=product_ratio`, `COMPOSITE=composite` |
| `StealthWakePurpose` | `CONDITION_HOLD=condition_hold`, `TIME_DELAY=time_delay`, `ADMISSION_RETRY=admission_retry`, `ANCHOR_REPRICE=anchor_reprice`, `COMPATIBILITY_RECHECK=compatibility_recheck` |
| `MarketEventMode` | `NORMAL=normal`, `STALE_INVALIDATION=stale_invalidation` |
| `TickerPublicationDisposition` | `ACCEPTED=accepted`, `STALE_INVALIDATION=stale_invalidation` |
| `RepricingReferenceSource` | `LAST_TRADE=last_trade`, `MIDPOINT=midpoint`, `TOP_OF_BOOK=top_of_book` |
| `RepricingDistanceType` | `PERCENT=P`, `ABSOLUTE=A` |
| `RepricingUpdateMode` | `ADAPTIVE=adaptive`, `FIXED=fixed` |
| `WebSocketEventType` | `SNAPSHOT=snapshot`, `UPDATE=update`, `PATCH=patch` |
| `UserFeedPhase` | `AWAITING_SNAPSHOT=awaiting_snapshot`, `BOOTSTRAPPING=bootstrapping`, `LIVE=live`, `DESYNCHRONIZED=desynchronized` |
| `EventTriggerType` | `STEALTH_CONDITION=stealth_condition`, `FOLLOW_UP=follow_up` |
| `EventSourceChannel` | `PLACEMENT_PRE_HOOK=placement_pre_hook`, `WS_USER=ws_user`, `FILL_HOOK=fill_hook`, `REST_SUBMIT=rest_submit`, `PLACEMENT_POST_HOOK=placement_post_hook`, `ORDER_STATE_HOOK=order_state_hook`, `STEALTH_LIFECYCLE_HOOK=stealth_lifecycle_hook`, `ORDER_ENGINE_OPEN=order_engine_open_handler`, `ORDER_ENGINE_TERMINAL=order_engine_terminal_handler` |
| `EventStreamType` | `STEALTH_CONDITION_MET=stealth_condition_met`, `FILL_RECORDED=fill_recorded`, `ORDER_SUBMITTED=order_submitted`, `STEALTH_REVEALED=stealth_revealed`, `STEALTH_FOLLOW_UP_CREATED=stealth_follow_up_created`, `INVENTORY_OPENED=inventory_opened`, `INVENTORY_CLOSED=inventory_closed`, `PARTIAL_FILL_DETECTED=partial_fill_detected`, `PARTIAL_FILL_PROGRESS_UPDATED=partial_fill_progress_updated`, `PARTIAL_FILL_FOLLOW_UP_QUEUED=partial_fill_follow_up_queued`, `PARTIAL_FILL_BELOW_MIN=partial_fill_below_min_accumulated`, `PARTIAL_FILL_FINALIZED=partial_fill_finalized` |
| `ChannelType` | `TICKER=ticker`, `LEVEL2=level2`, `MARKET_TRADES=market_trades`, `CANDLES=candles`, `HEARTBEATS=heartbeats`, `STATUS=status`, `TICKER_BATCH=ticker_batch`, `USER=user`, `FUTURES_BALANCE_SUMMARY=futures_balance_summary`, `SUBSCRIPTIONS=subscriptions` |
| `RiskManagementType` | `MANAGED_BY_FCM=MANAGED_BY_FCM`, `MANAGED_BY_VENUE=MANAGED_BY_VENUE`, `UNKNOWN_RISK_MANAGEMENT_TYPE=UNKNOWN_RISK_MANAGEMENT_TYPE` |
| `OrderStateEvent` | `OPENED=OPENED`, `FILLED=FILLED`, `CANCELLED=CANCELLED`, `EXPIRED=EXPIRED` |
| `StealthLifecycleEvent` | `CREATED=CREATED`, `CONDITION_WATCHING=CONDITION_WATCHING`, `CONDITION_RESET=CONDITION_RESET`, `CONDITION_MET=CONDITION_MET`, `REVEAL_ATTEMPTED=REVEAL_ATTEMPTED`, `PLACEMENT_BLOCKED=PLACEMENT_BLOCKED`, `REVEAL_FAILED=REVEAL_FAILED`, `REVEAL_SUCCEEDED=REVEAL_SUCCEEDED`, `FILL_RECEIVED=FILL_RECEIVED`, `EXECUTED=EXECUTED`, `CANCELLED=CANCELLED` |
| `TargetMovementType` | `PERCENTAGE=P`, `ABSOLUTE=A` |
| `EngineState` | `STARTING=STARTING`, `RUNNING=RUNNING`, `PAUSING=PAUSING`, `PAUSED=PAUSED`, `DRAINING=DRAINING`, `STOPPED=STOPPED` |
| `HotpointPlacementPolicy` | `WINDOW_CENTER=WINDOW_CENTER`, `LAST_FILL=LAST_FILL`, `MEAN_OF_FILLS=MEAN_OF_FILLS` |
| `HotpointFillSource` | `OWN_ORDERS=OWN_ORDERS`, `TAPE=TAPE` |

## Example

```python
from core.enums import OrderSide, OrderStatus, TargetMovementType

side = OrderSide.BUY
status = OrderStatus.OPEN
parent_payload = {
    "client_order_id": client_order_id,
    "side": side.value,
    "status": status.value,
    "target_movement_type": TargetMovementType.PERCENTAGE.value,
}
```

Validate incoming strings with the relevant enum at existing boundaries. Do not
add a parallel normalizer or new status without reviewing the persistence,
dashboard, lifecycle, and regression contracts. Internal ownership always uses
`client_order_id`; see `ORDER_ID_HANDLING.md`.
