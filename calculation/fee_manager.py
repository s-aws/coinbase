"""Fee Manager - Dynamic fee rate fetching with market-regime adaptation.

Maintains independent Coinbase maker/taker schedules for spot and expiring
FCM futures, then applies the product's validation cushion. Market-regime
signals may widen fee protection and may independently adapt follow-up spacing:

- futures margin window state (intraday vs overnight)
- rolling volume regime (short-term vs long-term)

CRITICAL: Fee Charging Model
============================

Coinbase taker fees are charged on **every fill** — both the open
(parent) and the close (follow-up). The ``ProfitValidator`` formula
therefore computes round-trip percentage fees as
``(open_price + close_price) × size × effective_fee_rate``.

Pre-2026-05-01 the formula computed only the close-side fee and the
FeeManager carried a hidden 2.0 multiplier to compensate. That coupling
broke when the multiplier was tuned and silently halved real fee
accounting on futures. The two pieces are now decoupled: validator
formula is honest about both sides, multiplier is honest about cushion.

Mandatory contract fee
----------------------
Coinbase Derivatives charges fixed costs **per contract per side**. The
settlement-reconciled default is $0.12 all-in; the existing $0.27 full-size
BTI/ETI/SLC/XRL assumption remains explicitly unchanged pending independent
reconciliation. ``profit_validator.is_profitable()`` resolves the appropriate
all-in value through ``core.constants.get_derivatives_per_side_fee`` and
multiplies it by both contract count and two sides.

Base model:
- Base fee source: filtered Coinbase transaction-summary maker/taker rate
- Default multiplier: 1.0 for futures, 1.1 for spot (cushion only)
- Default effective fee (no regime factor): base × multiplier

Regime adaptation:
- Overnight/low-volume regimes may reduce target spacing
- Fee validation never discounts the selected exchange maker/taker rate
- High-volume regimes may widen both spacing and the validation cushion

Architecture:
- Fetches maker/taker rates from filtered transaction-summary REST calls
- Caches immutable per-product-type state with timestamp/error provenance
- Tracks rolling volume EWMA per product from ticker updates
- Tracks overnight margin state from futures balance summary updates
- Returns adaptive fee and spacing multipliers for existing order logic
- Refreshes base fee hourly in a background thread
- Thread-safe access via RLock
"""

import math
import threading
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Dict, Optional

from calculation.formatter import safe_float
from core.enums import (
    ContractExpiryType,
    FeeScheduleSource,
    LiquidityAssumption,
    ProductType,
    ProductVenue,
)


@dataclass(frozen=True)
class FeeScheduleSnapshot:
    """One immutable exchange fee schedule and its refresh provenance."""

    product_type: ProductType
    product_venue: ProductVenue
    contract_expiry_type: Optional[ContractExpiryType]
    maker_fee_rate: float
    taker_fee_rate: float
    pricing_tier: Optional[str]
    has_cost_plus_commission: Optional[bool]
    has_promo_fee: Optional[bool]
    source: FeeScheduleSource
    last_attempt_at: Optional[datetime]
    last_success_at: Optional[datetime]
    consecutive_errors: int
    last_error: Optional[str]


@dataclass(frozen=True)
class FeeQuote:
    """Atomic fee inputs used by one profitability decision."""

    product_id: Optional[str]
    product_type: ProductType
    liquidity_assumption: LiquidityAssumption
    exchange_fee_rate: float
    validation_fee_rate: float
    product_multiplier: float
    raw_fee_regime_factor: float
    applied_fee_regime_factor: float
    pricing_tier: Optional[str]
    has_cost_plus_commission: Optional[bool]
    has_promo_fee: Optional[bool]
    source: FeeScheduleSource
    last_success_at: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        """Return JSON-safe quote telemetry without weakening immutability."""
        return {
            "product_id": self.product_id,
            "product_type": self.product_type.value,
            "liquidity_assumption": self.liquidity_assumption.value,
            "exchange_fee_rate": self.exchange_fee_rate,
            "validation_fee_rate": self.validation_fee_rate,
            "product_multiplier": self.product_multiplier,
            "raw_fee_regime_factor": self.raw_fee_regime_factor,
            "applied_fee_regime_factor": self.applied_fee_regime_factor,
            "pricing_tier": self.pricing_tier,
            "has_cost_plus_commission": self.has_cost_plus_commission,
            "has_promo_fee": self.has_promo_fee,
            "source": self.source.value,
            "last_success_at": (
                self.last_success_at.isoformat() if self.last_success_at else None
            ),
        }


class FeeManager:
    """Manages dynamic fee rates from Coinbase API with caching and auto-refresh.
    
    Features:
    - Fetches separate SPOT/CBE and FUTURE/EXPIRING/FCM fee schedules
    - Selects maker only for post-only orders; all other orders use taker
    - Adapts fee and spacing factors from margin-window + volume regime
    - Auto-refreshes hourly in background thread
    - Thread-safe access with RLock
    - Fallback to conservative default if API unavailable
    - Structured logging for fee and regime state changes
    
    Example:
        >>> manager = FeeManager(rest_client, log_callback=engine.log_message)
        >>> manager.start()  # Starts hourly REST fee refresh
        >>>
        >>> # Feed real-time market regime signals from websocket handlers
        >>> manager.update_volume_signal("BTC-USDC", volume_24h=1450000.0)
        >>> manager.update_margin_window_type("FCM_MARGIN_WINDOW_TYPE_OVERNIGHT")
        >>>
        >>> # Consume adaptive multipliers in existing follow-up/validation path
        >>> target_multiplier = manager.get_target_movement_multiplier("BTC-USDC")
        >>> effective_fee = manager.get_profit_validation_fee_rate("BTC-USDC")
        >>> info = manager.get_fee_info("BTC-USDC")
        >>> print(target_multiplier, effective_fee, info["volume_ratio"])
    """
    
    # Conservative pre-fetch defaults. They are held independently for each
    # product type and are replaced only by a fully validated filtered API
    # response. A failed refresh never destroys a last-known-good snapshot.
    DEFAULT_TAKER_FEE_RATE = 0.0010  # 10 bps
    DEFAULT_MAKER_FEE_RATE = 0.0005  # 5 bps
    # Product-type-aware fee cushions over the live taker fee.
    # FUTURES: 1.0 (no cushion). The per-contract mandatory fee provides a floor,
    #   and a 100% cushion makes any reasonable target_movement infeasible.
    # SPOT: 1.1 (10% cushion). Spot fees are higher (~60 bps) so a small
    #   cushion absorbs tier-slip between hourly refreshes without
    #   structurally blocking targets the way 2x does on futures.
    # Single legacy constant retained as the SPOT default for back-compat
    #   with callers/tests that didn't pass a product_id.
    FUTURES_FEE_MULTIPLIER = 1.0
    SPOT_FEE_MULTIPLIER = 1.1
    DEFAULT_MULTIPLIER = SPOT_FEE_MULTIPLIER  # back-compat alias
    REFRESH_INTERVAL_SECONDS = 3600  # 1 hour

    # Volume regime smoothing constants
    VOLUME_FAST_ALPHA = 0.20
    VOLUME_SLOW_ALPHA = 0.03

    # Safety clamps for adaptive factors
    TARGET_MOVEMENT_MIN_FACTOR = 0.75
    TARGET_MOVEMENT_MAX_FACTOR = 1.40
    FEE_REGIME_MIN_FACTOR = 0.80
    FEE_REGIME_MAX_FACTOR = 1.40
    
    def __init__(self, rest_client, log_callback=None, orderbook=None):
        """Initialize FeeManager.
        
        Args:
            rest_client: Initialized CoinbaseRestClient instance
            log_callback: Optional logging callback (log_type, message)
            orderbook: Optional orderbook reference. When provided, the
                effective-fee multiplier is resolved per product type
                (FUTURES vs SPOT) instead of using a single global value.
                Mirrors the convention used by ProfitValidator.
        """
        self.rest_client = rest_client
        self.log_callback = log_callback or self._default_log
        self.orderbook = orderbook
        
        # State reads are short and atomic. REST calls are serialized by a
        # separate mutex and occur outside this lock.
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._fee_schedules = {
            ProductType.SPOT: self._build_default_snapshot(ProductType.SPOT),
            ProductType.FUTURE: self._build_default_snapshot(ProductType.FUTURE),
        }
        self._refresh_thread = None
        self._running = False
        # The manager is owned by the one-shot OrderEngine lifecycle. Start
        # and stop publication are serialized, and a stop request is sticky so
        # a late startup path can never clear the event and revive the worker.
        self._lifecycle_lock = threading.Lock()
        self._compat_start_lock = threading.Lock()
        self._stop_requested = False
        # Drives interruptible sleeps in the refresh loop so stop()
        # collapses near-instantly instead of waiting out the hourly
        # refresh interval.
        self._shutdown_event = threading.Event()

        # Adaptive market regime state (updated from websocket data).
        self._current_margin_window_type = None
        self._overnight_margin_active = False
        self._volume_ewma = {}  # product_id -> {fast, slow, ratio, volume_1m, timestamp}

    def _build_default_snapshot(
        self,
        product_type: ProductType,
    ) -> FeeScheduleSnapshot:
        """Create the conservative pre-fetch snapshot for one product type."""
        is_future = product_type == ProductType.FUTURE
        return FeeScheduleSnapshot(
            product_type=product_type,
            product_venue=ProductVenue.FCM if is_future else ProductVenue.CBE,
            contract_expiry_type=(ContractExpiryType.EXPIRING if is_future else None),
            maker_fee_rate=self.DEFAULT_MAKER_FEE_RATE,
            taker_fee_rate=self.DEFAULT_TAKER_FEE_RATE,
            pricing_tier=None,
            has_cost_plus_commission=None,
            has_promo_fee=None,
            source=FeeScheduleSource.DEFAULT,
            last_attempt_at=None,
            last_success_at=None,
            consecutive_errors=0,
            last_error=None,
        )
    
    def _default_log(self, log_type: str, message: str):
        """Fallback logging if no callback provided."""
        print(f"[{log_type.upper()}] {message}")
    
    def start_periodic_refresh(self) -> bool:
        """Publish the hourly refresh worker without performing REST I/O.

        The publication is bounded and serialized with :meth:`stop`. Returns
        ``False`` when stop has already won; that stop intent is deliberately
        one-shot and is never cleared by a late start.
        """

        with self._lifecycle_lock:
            if self._running:
                return True
            if self._stop_requested:
                return False

            self._shutdown_event.clear()
            self._running = True
            refresh_thread = threading.Thread(
                target=self._refresh_loop,
                daemon=True,
                name="FeeManager-Refresher",
            )
            self._refresh_thread = refresh_thread
            try:
                refresh_thread.start()
            except Exception:
                self._running = False
                self._shutdown_event.set()
                self._refresh_thread = None
                raise

        self.log_callback("info", "Fee manager started (hourly refresh)")
        return True

    def refresh_now(self) -> bool:
        """Synchronously refresh both fee schedules through the canonical path."""

        return self._refresh_fee_rate()

    def start(self) -> bool:
        """Start hourly refresh and perform the historical immediate refresh.

        Kept as the compatibility entry point. OrderEngine uses the split
        methods so its lifecycle lock never spans Coinbase REST calls.
        """

        with self._compat_start_lock:
            with self._lifecycle_lock:
                if self._running:
                    return True
            if not self.start_periodic_refresh():
                return False
            self.refresh_now()
            with self._lifecycle_lock:
                return self._running and not self._stop_requested
    
    def stop(self):
        """Stop background refresh thread.

        Idempotent. Sets the shared shutdown event so the refresh loop
        wakes immediately rather than waiting out the hourly interval.
        """
        with self._lifecycle_lock:
            already_stopped = self._stop_requested
            was_active = self._running or self._refresh_thread is not None
            self._stop_requested = True
            self._running = False
            self._shutdown_event.set()
            refresh_thread = self._refresh_thread

        if (
            refresh_thread is not None
            and refresh_thread is not threading.current_thread()
        ):
            refresh_thread.join(timeout=5)
        if was_active and not already_stopped:
            self.log_callback("info", "Fee manager stopped")

    def _refresh_loop(self):
        """Background loop that refreshes fee rates hourly."""
        while self._running:
            try:
                # Interruptible sleep: stop() wakes us immediately.
                if self._shutdown_event.wait(timeout=self.REFRESH_INTERVAL_SECONDS):
                    break
                if self._running:  # Check again after sleep
                    self._refresh_fee_rate()
            except Exception as e:
                self.log_callback("error", f"Fee refresh loop error: {e}")
                if self._shutdown_event.wait(timeout=5):
                    break
    
    def _refresh_fee_rate(self) -> bool:
        """Refresh both filtered schedules without cross-product pollution.

        The compatibility name is retained because startup and existing
        diagnostics already call it. ``True`` means both filtered requests
        succeeded; a partial success updates only its own schedule.
        """
        with self._refresh_lock:
            outcomes = []
            for product_type in (ProductType.SPOT, ProductType.FUTURE):
                # Stop cannot cancel a Coinbase request that is already in
                # progress, but it must prevent the second request (or a
                # queued refresh) from beginning afterward.  Never hold the
                # lifecycle lock across REST I/O.
                with self._lifecycle_lock:
                    if self._stop_requested:
                        return False
                outcomes.append(self._refresh_fee_schedule(product_type))
        return all(outcomes)

    @staticmethod
    def _parse_fee_rate(raw_value: Any, field_name: str) -> float:
        """Parse one required, finite, non-negative decimal fee rate."""
        if raw_value is None or isinstance(raw_value, bool):
            raise ValueError(f"missing or invalid {field_name}")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {field_name}: {raw_value!r}") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid {field_name}: {raw_value!r}")
        return value

    @staticmethod
    def _optional_bool(payload: Dict[str, Any], field_name: str) -> Optional[bool]:
        """Read an optional API boolean without treating strings as truthy."""
        if field_name not in payload:
            return None
        value = payload[field_name]
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError(f"invalid {field_name}: expected boolean")
        return value

    def _refresh_fee_schedule(self, product_type: ProductType) -> bool:
        """Fetch and atomically replace one filtered fee schedule."""
        attempt_at = datetime.utcnow()
        is_future = product_type == ProductType.FUTURE
        request_filters = {
            "product_type": product_type,
            "product_venue": ProductVenue.FCM if is_future else ProductVenue.CBE,
        }
        if is_future:
            request_filters["contract_expiry_type"] = ContractExpiryType.EXPIRING

        try:
            summary = self.rest_client.get_transaction_summary(**request_filters)
            if not isinstance(summary, dict):
                raise ValueError("transaction summary was not an object")
            fee_tier = summary.get("fee_tier")
            if not isinstance(fee_tier, dict):
                raise ValueError("transaction summary omitted fee_tier")

            maker_fee = self._parse_fee_rate(
                fee_tier.get("maker_fee_rate"), "maker_fee_rate"
            )
            taker_fee = self._parse_fee_rate(
                fee_tier.get("taker_fee_rate"), "taker_fee_rate"
            )
            if maker_fee > taker_fee:
                raise ValueError(
                    "maker_fee_rate exceeds taker_fee_rate; refusing malformed snapshot"
                )

            has_cost_plus_commission = self._optional_bool(
                summary, "has_cost_plus_commission"
            )
            if is_future and has_cost_plus_commission is not True:
                raise ValueError(
                    "filtered FCM summary did not confirm cost-plus commission pricing"
                )
            has_promo_fee = self._optional_bool(summary, "has_promo_fee")
            pricing_tier_raw = fee_tier.get("pricing_tier")
            pricing_tier = (
                str(pricing_tier_raw).strip() if pricing_tier_raw is not None else None
            ) or None

            with self._lock:
                previous = self._fee_schedules[product_type]
                snapshot = FeeScheduleSnapshot(
                    product_type=product_type,
                    product_venue=request_filters["product_venue"],
                    contract_expiry_type=request_filters.get("contract_expiry_type"),
                    maker_fee_rate=maker_fee,
                    taker_fee_rate=taker_fee,
                    pricing_tier=pricing_tier,
                    has_cost_plus_commission=has_cost_plus_commission,
                    has_promo_fee=has_promo_fee,
                    source=FeeScheduleSource.COINBASE,
                    last_attempt_at=attempt_at,
                    last_success_at=attempt_at,
                    consecutive_errors=0,
                    last_error=None,
                )
                self._fee_schedules[product_type] = snapshot

            rates_changed = (
                previous.maker_fee_rate != maker_fee
                or previous.taker_fee_rate != taker_fee
                or previous.pricing_tier != pricing_tier
                or previous.source != FeeScheduleSource.COINBASE
            )
            self.log_callback("info" if rates_changed else "debug", {
                "event": (
                    "fee_schedule_updated" if rates_changed else "fee_schedule_refreshed"
                ),
                "product_type": product_type.value,
                "product_venue": snapshot.product_venue.value,
                "contract_expiry_type": (
                    snapshot.contract_expiry_type.value
                    if snapshot.contract_expiry_type else None
                ),
                "maker_fee_rate": maker_fee,
                "taker_fee_rate": taker_fee,
                "pricing_tier": pricing_tier,
                "has_cost_plus_commission": has_cost_plus_commission,
                "timestamp": attempt_at.isoformat(),
            })
            return True
        except Exception as exc:
            with self._lock:
                previous = self._fee_schedules[product_type]
                failed = replace(
                    previous,
                    last_attempt_at=attempt_at,
                    consecutive_errors=previous.consecutive_errors + 1,
                    last_error=str(exc),
                )
                self._fee_schedules[product_type] = failed

            self.log_callback("warning", {
                "event": "fee_schedule_fetch_failed",
                "product_type": product_type.value,
                "product_venue": failed.product_venue.value,
                "contract_expiry_type": (
                    failed.contract_expiry_type.value
                    if failed.contract_expiry_type else None
                ),
                "error": str(exc),
                "error_count": failed.consecutive_errors,
                "retained_source": failed.source.value,
                "retained_maker_fee_rate": failed.maker_fee_rate,
                "retained_taker_fee_rate": failed.taker_fee_rate,
                "note": "Retaining last-known-good schedule",
            })
            return False

    def get_fee_schedule_snapshot(
        self,
        product_id: Optional[str] = None,
    ) -> FeeScheduleSnapshot:
        """Return the immutable schedule selected for ``product_id``."""
        with self._lock:
            product_type = self._resolve_product_type_unlocked(product_id)
            return self._fee_schedules[product_type]

    def is_stale(
        self,
        max_age_seconds: int = REFRESH_INTERVAL_SECONDS * 2,
        product_id: Optional[str] = None,
    ) -> bool:
        """Check if cached fee rate is stale.
        
        Args:
            max_age_seconds: How old the data can be before considered stale (default: 2 hours)
        
        Returns:
            True if never updated or too old, False if recent
        """
        with self._lock:
            product_type = self._resolve_product_type_unlocked(product_id)
            last_success_at = self._fee_schedules[product_type].last_success_at
            if not last_success_at:
                return True

            age = (datetime.utcnow() - last_success_at).total_seconds()
            return age > max_age_seconds

    def get_taker_fee_rate(self, product_id: Optional[str] = None) -> float:
        """Get base taker fee rate from Coinbase (not multiplied).
        
        Returns:
            Fee rate as decimal (e.g., 0.0060 for 0.6%)
        """
        with self._lock:
            product_type = self._resolve_product_type_unlocked(product_id)
            return self._fee_schedules[product_type].taker_fee_rate

    def get_maker_fee_rate(self, product_id: Optional[str] = None) -> float:
        """Get base maker fee rate from Coinbase (not multiplied).

        The pre-trade model uses maker only when ``post_only=True``.
        Coinbase exposes the rate alongside the taker rate in
        ``transaction_summary.fee_tier.maker_fee_rate``.

        Returns:
            Fee rate as decimal (e.g., 0.0040 for 0.4%)
        """
        with self._lock:
            product_type = self._resolve_product_type_unlocked(product_id)
            return self._fee_schedules[product_type].maker_fee_rate

    @staticmethod
    def _clamp(value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(max_value, value))

    def _resolve_volume_ratio_unlocked(self, product_id: Optional[str]) -> float:
        if product_id and product_id in self._volume_ewma:
            return self._volume_ewma[product_id].get("ratio", 1.0)

        if self._volume_ewma:
            ratios = [state.get("ratio", 1.0) for state in self._volume_ewma.values()]
            return sum(ratios) / len(ratios)

        return 1.0

    def _resolve_product_type_unlocked(
        self,
        product_id: Optional[str],
        product_type_hint: Optional[Any] = None,
    ) -> ProductType:
        """Resolve the schedule key using the canonical product resolver.

        A valid explicit hint wins, followed by configured product metadata and
        the canonical suffix fallback. Unknown products without a valid hint
        deliberately fall back to SPOT. Caller holds ``_lock``.
        """
        try:
            from configuration import normalize_product_type as _normalize_product_type

            order_for_normalize = {}
            if product_id:
                order_for_normalize["product_id"] = product_id
            if product_type_hint is not None:
                order_for_normalize["product_type"] = getattr(
                    product_type_hint,
                    "value",
                    product_type_hint,
                )
            products = self.orderbook.product if self.orderbook else None
            normalized = _normalize_product_type(order_for_normalize, products=products)
            if normalized == ProductType.FUTURE.value:
                return ProductType.FUTURE
        except Exception:
            pass
        return ProductType.SPOT

    def _resolve_multiplier_unlocked(
        self,
        product_id: Optional[str],
        product_type_hint: Optional[Any] = None,
    ) -> float:
        """Return the fee cushion for the resolved product type.

        FUTURES products use ``FUTURES_FEE_MULTIPLIER`` (1.0 by default);
        SPOT products and unknown/unresolvable cases use
        ``SPOT_FEE_MULTIPLIER`` (1.1 by default — slightly conservative
        cushion for tier-slip on the higher spot fee schedule).

        Resolution mirrors ``ProfitValidator._resolve_product_context``:
        consults the orderbook's product metadata when available, falls
        back to the ``-CDE`` suffix heuristic, and finally to SPOT.

        A valid explicit product-type hint wins. Without one, unresolved
        products use the SPOT multiplier. Caller already holds ``self._lock``.
        """
        product_type = self._resolve_product_type_unlocked(
            product_id,
            product_type_hint,
        )
        if product_type == ProductType.FUTURE:
            return self.FUTURES_FEE_MULTIPLIER
        return self.SPOT_FEE_MULTIPLIER

    def _derive_regime_factors_unlocked(self, product_id: Optional[str] = None) -> Dict[str, float]:
        """Compute adaptive multipliers from margin + volume regime."""
        volume_ratio = self._resolve_volume_ratio_unlocked(product_id)

        target_factor = 0.85 if self._overnight_margin_active else 1.0
        fee_factor = 0.90 if self._overnight_margin_active else 1.0

        # Low liquidity: keep follow-ups closer and use a lighter effective fee.
        if volume_ratio < 0.85:
            target_factor *= 0.90
            fee_factor *= 0.92
        # High liquidity/activity: widen spacing and charge higher effective fee.
        elif volume_ratio > 1.15:
            high_volume_strength = volume_ratio - 1.15
            target_factor *= min(1.25, 1.0 + (high_volume_strength * 0.35))
            fee_factor *= min(1.30, 1.0 + (high_volume_strength * 0.50))

        target_factor = self._clamp(
            target_factor,
            self.TARGET_MOVEMENT_MIN_FACTOR,
            self.TARGET_MOVEMENT_MAX_FACTOR,
        )
        fee_factor = self._clamp(
            fee_factor,
            self.FEE_REGIME_MIN_FACTOR,
            self.FEE_REGIME_MAX_FACTOR,
        )

        return {
            "target_movement_factor": target_factor,
            "fee_factor": fee_factor,
            "volume_ratio": volume_ratio,
            "overnight_margin_active": self._overnight_margin_active,
            "margin_window_type": self._current_margin_window_type,
        }

    def update_volume_signal(self, product_id: str, volume_24h: float) -> None:
        """Update rolling volume regime for a product from ticker volume_24_h."""
        if not product_id:
            return

        volume_24h_float = safe_float(volume_24h, default=0.0)
        if volume_24h_float <= 0:
            return

        volume_1m = volume_24h_float / 1440.0

        with self._lock:
            state = self._volume_ewma.get(product_id)
            if not state:
                fast = volume_1m
                slow = volume_1m
            else:
                prev_fast = state.get("fast", volume_1m)
                prev_slow = state.get("slow", volume_1m)
                fast = (self.VOLUME_FAST_ALPHA * volume_1m) + ((1.0 - self.VOLUME_FAST_ALPHA) * prev_fast)
                slow = (self.VOLUME_SLOW_ALPHA * volume_1m) + ((1.0 - self.VOLUME_SLOW_ALPHA) * prev_slow)

            ratio = fast / slow if slow > 0 else 1.0
            ratio = self._clamp(ratio, 0.50, 2.00)

            self._volume_ewma[product_id] = {
                "fast": fast,
                "slow": slow,
                "ratio": ratio,
                "volume_1m": volume_1m,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def update_margin_window_type(self, margin_window_type: Optional[str]) -> bool:
        """Update margin window regime state from futures balance summary feed."""
        if not margin_window_type:
            return False

        normalized = str(margin_window_type).upper()
        overnight_active = "OVERNIGHT" in normalized
        log_payload = None

        with self._lock:
            changed = (
                self._current_margin_window_type != normalized
                or self._overnight_margin_active != overnight_active
            )

            self._current_margin_window_type = normalized
            self._overnight_margin_active = overnight_active

            if changed:
                log_payload = {
                    "event": "margin_window_regime_updated",
                    "margin_window_type": self._current_margin_window_type,
                    "overnight_margin_active": self._overnight_margin_active,
                    "timestamp": datetime.utcnow().isoformat(),
                }

        if log_payload is not None:
            self.log_callback("info", log_payload)

        return changed

    def update_margin_window_from_summary(self, fcm_balance_summary: dict) -> bool:
        """Best-effort extractor for active margin window type from summary payload."""
        if not isinstance(fcm_balance_summary, dict):
            return False

        # Prefer explicit active/current signals first. Some payloads include
        # "margin_window_type" as a generic fallback, but the nested measure
        # objects describe available windows rather than the currently active one.
        candidates = (
            fcm_balance_summary.get("active_margin_window_type"),
            fcm_balance_summary.get("current_margin_window_type"),
            fcm_balance_summary.get("active_margin_window_measure", {}).get("margin_window_type") if isinstance(fcm_balance_summary.get("active_margin_window_measure"), dict) else None,
            fcm_balance_summary.get("margin_window_type"),
        )

        for candidate in candidates:
            if candidate:
                return self.update_margin_window_type(candidate)

        return False

    def get_target_movement_multiplier(self, product_id: Optional[str] = None) -> float:
        """Get adaptive multiplier for follow-up target movement percentages."""
        with self._lock:
            factors = self._derive_regime_factors_unlocked(product_id)
            return factors["target_movement_factor"]
    
    def get_profit_validation_fee_rate(
        self,
        product_id: Optional[str] = None,
        post_only: bool = False,
        product_type: Optional[Any] = None,
    ) -> float:
        """Return the validation rate from one immutable fee quote."""
        return self.get_profit_validation_fee_quote(
            product_id=product_id,
            post_only=post_only,
            product_type=product_type,
        ).validation_fee_rate

    def _build_fee_quote_unlocked(
        self,
        product_id: Optional[str],
        post_only: bool,
        product_type_hint: Optional[Any] = None,
    ) -> FeeQuote:
        product_type = self._resolve_product_type_unlocked(
            product_id,
            product_type_hint,
        )
        snapshot = self._fee_schedules[product_type]
        liquidity = (
            LiquidityAssumption.MAKER if post_only else LiquidityAssumption.TAKER
        )
        exchange_rate = (
            snapshot.maker_fee_rate
            if liquidity == LiquidityAssumption.MAKER
            else snapshot.taker_fee_rate
        )
        multiplier = self._resolve_multiplier_unlocked(
            product_id,
            product_type,
        )
        factors = self._derive_regime_factors_unlocked(product_id)
        raw_regime_factor = factors["fee_factor"]
        # Regime signals may widen fee protection, but may never discount a
        # known exchange rate. Target-movement adaptation remains unchanged.
        applied_regime_factor = max(1.0, raw_regime_factor)
        validation_rate = exchange_rate * multiplier * applied_regime_factor
        return FeeQuote(
            product_id=product_id,
            product_type=product_type,
            liquidity_assumption=liquidity,
            exchange_fee_rate=exchange_rate,
            validation_fee_rate=validation_rate,
            product_multiplier=multiplier,
            raw_fee_regime_factor=raw_regime_factor,
            applied_fee_regime_factor=applied_regime_factor,
            pricing_tier=snapshot.pricing_tier,
            has_cost_plus_commission=snapshot.has_cost_plus_commission,
            has_promo_fee=snapshot.has_promo_fee,
            source=snapshot.source,
            last_success_at=snapshot.last_success_at,
        )

    def get_profit_validation_fee_quote(
        self,
        product_id: Optional[str] = None,
        post_only: bool = False,
        product_type: Optional[Any] = None,
    ) -> FeeQuote:
        """Atomically sample every fee input for one profitability decision.

        ``post_only=True`` is the sole maker assumption. Any order that is not
        post-only is costed as taker even if its current limit price appears
        non-marketable.
        """
        with self._lock:
            return self._build_fee_quote_unlocked(
                product_id,
                post_only,
                product_type,
            )

    def get_fee_info(self, product_id: Optional[str] = None) -> Dict[str, Any]:
        """Get comprehensive fee information.

        Returns:
            Dict with both maker- and taker-based effective rates so
            callers can preview either liquidity model.
        """
        with self._lock:
            product_type = self._resolve_product_type_unlocked(product_id)
            snapshot = self._fee_schedules[product_type]
            taker_quote = self._build_fee_quote_unlocked(product_id, False)
            maker_quote = self._build_fee_quote_unlocked(product_id, True)
            factors = self._derive_regime_factors_unlocked(product_id)

            # Example: Cost for 1 BTC at $50,000 (round-trip, taker model)
            example_btc_price = 50000.0
            example_cost_base = example_btc_price * snapshot.taker_fee_rate * 2
            example_cost_effective = (
                example_btc_price * taker_quote.validation_fee_rate * 2
            )
            last_success_at = snapshot.last_success_at
            is_stale = (
                last_success_at is None
                or (datetime.utcnow() - last_success_at).total_seconds()
                > self.REFRESH_INTERVAL_SECONDS * 2
            )

            return {
                "product_type": product_type.value,
                "product_venue": snapshot.product_venue.value,
                "contract_expiry_type": (
                    snapshot.contract_expiry_type.value
                    if snapshot.contract_expiry_type else None
                ),
                "taker_fee_rate": snapshot.taker_fee_rate,
                "maker_fee_rate": snapshot.maker_fee_rate,
                "profit_validation_fee_rate": taker_quote.validation_fee_rate,
                "profit_validation_fee_rate_taker": taker_quote.validation_fee_rate,
                "profit_validation_fee_rate_maker": maker_quote.validation_fee_rate,
                "multiplier": taker_quote.product_multiplier,
                "target_movement_factor": factors["target_movement_factor"],
                "fee_regime_factor": factors["fee_factor"],
                "fee_validation_factor": taker_quote.applied_fee_regime_factor,
                "volume_ratio": factors["volume_ratio"],
                "overnight_margin_active": factors["overnight_margin_active"],
                "margin_window_type": factors["margin_window_type"],
                "pricing_tier": snapshot.pricing_tier,
                "has_cost_plus_commission": snapshot.has_cost_plus_commission,
                "has_promo_fee": snapshot.has_promo_fee,
                "fee_schedule_source": snapshot.source.value,
                "last_attempt_at": (
                    snapshot.last_attempt_at.isoformat()
                    if snapshot.last_attempt_at else None
                ),
                "last_updated": (
                    last_success_at.isoformat() if last_success_at else None
                ),
                "consecutive_errors": snapshot.consecutive_errors,
                "last_error": snapshot.last_error,
                "is_stale": is_stale,
                "fee_per_trade_1btc_base": example_cost_base,
                "fee_per_trade_1btc_effective": example_cost_effective,
                "note": "Maker is used only for post_only=True; otherwise taker. "
                        "Regime adaptation cannot discount the selected exchange rate."
            }

    def validate_fee_freshness(
        self,
        max_age_seconds: int = 7200,
        product_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate that fee data is fresh and provide remediation if stale.
        
        Args:
            max_age_seconds: How old data can be before considered stale (default: 2 hours)
        
        Returns:
            Dict with keys:
            - is_fresh: Whether data is acceptably fresh
            - age_seconds: How old the data is
            - last_updated: Timestamp of last update
            - remediation: Suggested action if stale
        """
        with self._lock:
            product_type = self._resolve_product_type_unlocked(product_id)
            snapshot = self._fee_schedules[product_type]
            if not snapshot.last_success_at:
                return {
                    "is_fresh": False,
                    "age_seconds": None,
                    "last_updated": None,
                    "product_type": product_type.value,
                    "source": snapshot.source.value,
                    "last_error": snapshot.last_error,
                    "remediation": "Never fetched - refresh filtered fee schedules"
                }

            age = (datetime.utcnow() - snapshot.last_success_at).total_seconds()
            is_fresh = age <= max_age_seconds

            return {
                "is_fresh": is_fresh,
                "age_seconds": age,
                "last_updated": snapshot.last_success_at.isoformat(),
                "product_type": product_type.value,
                "source": snapshot.source.value,
                "last_error": snapshot.last_error,
                "remediation": None if is_fresh else "Refresh filtered fee schedules"
            }

    def explain_fee_multiplier(self, product_id: Optional[str] = None) -> Dict[str, Any]:
        """Explain fee and regime factor calculation for verification/debugging."""
        with self._lock:
            quote = self._build_fee_quote_unlocked(product_id, False)
            factors = self._derive_regime_factors_unlocked(product_id)

            # Example: BUY @ $50,000 (open), SELL @ $52,500 (close)
            example_open_price = 50000.0
            example_close_price = 52500.0
            example_size = 1.0
            fee_on_open = (
                example_open_price * example_size * quote.validation_fee_rate
            )
            fee_on_close = (
                example_close_price * example_size * quote.validation_fee_rate
            )
            total_example = fee_on_open + fee_on_close
            gross_profit = example_close_price - example_open_price
            net_profit = gross_profit * example_size - total_example

            return {
                "product_type": quote.product_type.value,
                "liquidity_assumption": quote.liquidity_assumption.value,
                "base_fee_from_coinbase": quote.exchange_fee_rate,
                "multiplier_applied": quote.product_multiplier,
                "fee_regime_factor": quote.raw_fee_regime_factor,
                "fee_validation_factor": quote.applied_fee_regime_factor,
                "target_movement_factor": factors["target_movement_factor"],
                "volume_ratio": factors["volume_ratio"],
                "overnight_margin_active": factors["overnight_margin_active"],
                "margin_window_type": factors["margin_window_type"],
                "effective_fee_rate": quote.validation_fee_rate,
                "pricing_tier": quote.pricing_tier,
                "source": quote.source.value,
                "calculation_method": (
                    "effective = exchange rate x product cushion x "
                    "max(1, regime factor), applied on both fills"
                ),
                "example": {
                    "open_price": example_open_price,
                    "close_price": example_close_price,
                    "size": example_size,
                    "fee_on_open": fee_on_open,
                    "fee_on_close": fee_on_close,
                    "gross_profit": gross_profit * example_size,
                    "net_profit": net_profit,
                    "total_fees_for_round_trip": total_example,
                    "note": "Percentage fees are modeled on both open and close fills"
                },
                "note": "Fixed per-contract futures costs are modeled separately."
            }
