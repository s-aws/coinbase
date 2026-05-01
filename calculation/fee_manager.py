"""Fee Manager - Dynamic fee rate fetching with market-regime adaptation.

Maintains the current taker fee rate from Coinbase and applies a configurable
multiplier for profitability checks. The effective rate is adapted by market
regime so follow-up spacing and fee sensitivity can react to:

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
Coinbase Derivatives charges a per-contract commission **per side**
(both open and close fills) under the schedule effective March 2, 2026.
Rates: $0.20/side for full-size BTI/ETI/SLC/XRL, $0.10/side for nano /
perp-style and everything else. Round-trip fee on a single contract is
therefore 2 × per-side. ``profit_validator.is_profitable()`` resolves
the per-side rate via ``core.constants.get_derivatives_per_side_fee``
and multiplies by 2.

Base model:
- Base fee source: Coinbase transaction summary taker fee rate
- Default multiplier: 1.0 for futures, 1.1 for spot (cushion only)
- Default effective fee (no regime factor): base × multiplier

Regime adaptation:
- Overnight/low-volume regimes reduce spacing and effective fee factor
- High-volume regimes widen spacing and increase effective fee factor

Architecture:
- Fetches taker_fee_rate from REST API (transaction_summary)
- Caches fee state with timestamp tracking
- Tracks rolling volume EWMA per product from ticker updates
- Tracks overnight margin state from futures balance summary updates
- Returns adaptive fee and spacing multipliers for existing order logic
- Refreshes base fee hourly in a background thread
- Thread-safe access via RLock
"""

import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from calculation.formatter import safe_float


class FeeManager:
    """Manages dynamic fee rates from Coinbase API with caching and auto-refresh.
    
    Features:
    - Fetches taker fees from Coinbase transaction_summary endpoint
    - Applies base multiplier (default 2x) for profit validation
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
    
    # Conservative defaults (from a sample CDE Non-Professional fee tier)
    DEFAULT_TAKER_FEE_RATE = 0.0060  # 0.6% — used as conservative pre-fetch baseline
    DEFAULT_MAKER_FEE_RATE = 0.0040  # 0.4% — maker is always <= taker
    # Product-type-aware fee cushions over the live taker fee.
    # FUTURES: 1.0 (no cushion). Coinbase futures fees are already small
    #   (5-6 bps), the per-contract mandatory fee provides its own floor,
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
        
        # Thread-safe access to fee rates
        self._lock = threading.RLock()
        
        # Fee rate data with tracking. Both maker and taker rates are
        # refreshed together from a single ``transaction_summary`` call.
        # ProfitValidator selects between them based on whether the order
        # will rest as a maker (``post_only=True``) or cross as a taker.
        self._taker_fee_rate = self.DEFAULT_TAKER_FEE_RATE
        self._maker_fee_rate = self.DEFAULT_MAKER_FEE_RATE
        self._last_updated = None
        self._refresh_thread = None
        self._running = False
        # Drives interruptible sleeps in the refresh loop so stop()
        # collapses near-instantly instead of waiting out the hourly
        # refresh interval.
        self._shutdown_event = threading.Event()
        self._fetch_error_count = 0
        self._max_consecutive_errors = 3  # Fall back to default after 3 errors

        # Adaptive market regime state (updated from websocket data).
        self._current_margin_window_type = None
        self._overnight_margin_active = False
        self._volume_ewma = {}  # product_id -> {fast, slow, ratio, volume_1m, timestamp}
    
    def _default_log(self, log_type: str, message: str):
        """Fallback logging if no callback provided."""
        print(f"[{log_type.upper()}] {message}")
    
    def start(self):
        """Start background refresh thread.
        
        Spawns daemon thread that refreshes fee rates every hour.
        Safe to call multiple times (no-op if already running).
        """
        if self._running:
            return

        self._shutdown_event.clear()
        self._running = True
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            daemon=True,
            name="FeeManager-Refresher"
        )
        self._refresh_thread.start()
        
        self.log_callback("info", "Fee manager started (hourly refresh)")
        
        # Fetch immediately on startup
        self._refresh_fee_rate()
    
    def stop(self):
        """Stop background refresh thread.

        Idempotent. Sets the shared shutdown event so the refresh loop
        wakes immediately rather than waiting out the hourly interval.
        """
        if not self._running and not self._shutdown_event.is_set():
            return
        self._running = False
        self._shutdown_event.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)
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
        """Fetch latest maker/taker fee rates from Coinbase API.

        Returns:
            True if successfully fetched, False if API call failed
        """
        try:
            summary = self.rest_client.get_transaction_summary()

            # Extract maker_fee_rate and taker_fee_rate - nested in fee_tier.
            # See ``api_reference/fees/get_fees_response.json`` for shape.
            taker_fee_str = None
            maker_fee_str = None
            if isinstance(summary, dict):
                fee_tier = summary.get("fee_tier", {})
                if isinstance(fee_tier, dict):
                    taker_fee_str = fee_tier.get("taker_fee_rate")
                    maker_fee_str = fee_tier.get("maker_fee_rate")

            # Fallback to defaults if not found
            if not taker_fee_str:
                taker_fee_str = str(self.DEFAULT_TAKER_FEE_RATE)
            if not maker_fee_str:
                maker_fee_str = str(self.DEFAULT_MAKER_FEE_RATE)

            # API returns fees as decimals (e.g., "0.00035" = 0.035%).
            taker_fee = safe_float(taker_fee_str, default=self.DEFAULT_TAKER_FEE_RATE)
            maker_fee = safe_float(maker_fee_str, default=self.DEFAULT_MAKER_FEE_RATE)

            # Sanity guard: maker rate should never exceed taker. If the
            # API returns something pathological, prefer the safer (higher)
            # taker rate for both rather than under-charging.
            if maker_fee > taker_fee:
                self.log_callback("warning", {
                    "event": "maker_fee_exceeds_taker",
                    "maker_fee": maker_fee,
                    "taker_fee": taker_fee,
                    "action": "clamping maker_fee to taker_fee",
                })
                maker_fee = taker_fee

            with self._lock:
                old_taker = self._taker_fee_rate
                old_maker = self._maker_fee_rate
                self._taker_fee_rate = taker_fee
                self._maker_fee_rate = maker_fee
                self._last_updated = datetime.utcnow()
                self._fetch_error_count = 0  # Reset error counter on success

            # Log update if either rate changed materially
            if abs(old_taker - taker_fee) > 0.00001 or abs(old_maker - maker_fee) > 0.00001:
                self.log_callback("info", {
                    "event": "fee_rates_updated",
                    "old_taker": old_taker,
                    "new_taker": taker_fee,
                    "old_maker": old_maker,
                    "new_maker": maker_fee,
                    "effective_profit_fee_futures_taker": taker_fee * self.FUTURES_FEE_MULTIPLIER,
                    "effective_profit_fee_spot_taker": taker_fee * self.SPOT_FEE_MULTIPLIER,
                    "timestamp": self._last_updated.isoformat()
                })
            else:
                self.log_callback("debug", {
                    "event": "fee_rates_refreshed",
                    "taker_fee_rate": taker_fee,
                    "maker_fee_rate": maker_fee,
                    "timestamp": self._last_updated.isoformat()
                })

            return True

        except Exception as e:
            with self._lock:
                self._fetch_error_count += 1

                # If too many consecutive errors, use defaults
                if self._fetch_error_count >= self._max_consecutive_errors:
                    self._taker_fee_rate = self.DEFAULT_TAKER_FEE_RATE
                    self._maker_fee_rate = self.DEFAULT_MAKER_FEE_RATE
                    self._last_updated = datetime.utcnow()

            self.log_callback("warning", {
                "event": "fee_rate_fetch_failed",
                "error": str(e),
                "error_count": self._fetch_error_count,
                "fallback_taker": self._taker_fee_rate if self._fetch_error_count >= self._max_consecutive_errors else "previous",
                "fallback_maker": self._maker_fee_rate if self._fetch_error_count >= self._max_consecutive_errors else "previous",
                "note": "Using default conservative rates" if self._fetch_error_count >= self._max_consecutive_errors else "Will retry next hour"
            })

            return False
    
    def is_stale(self, max_age_seconds: int = REFRESH_INTERVAL_SECONDS * 2) -> bool:
        """Check if cached fee rate is stale.
        
        Args:
            max_age_seconds: How old the data can be before considered stale (default: 2 hours)
        
        Returns:
            True if never updated or too old, False if recent
        """
        with self._lock:
            if not self._last_updated:
                return True
            
            age = (datetime.utcnow() - self._last_updated).total_seconds()
            return age > max_age_seconds
    
    def get_taker_fee_rate(self) -> float:
        """Get base taker fee rate from Coinbase (not multiplied).
        
        Returns:
            Fee rate as decimal (e.g., 0.0060 for 0.6%)
        """
        with self._lock:
            return self._taker_fee_rate

    def get_maker_fee_rate(self) -> float:
        """Get base maker fee rate from Coinbase (not multiplied).

        Maker fees apply when an order rests on the book before filling
        (i.e. ``post_only=True`` orders, or any non-marketable limit).
        Coinbase exposes this alongside the taker rate in
        ``transaction_summary.fee_tier.maker_fee_rate``.

        Returns:
            Fee rate as decimal (e.g., 0.0040 for 0.4%)
        """
        with self._lock:
            return self._maker_fee_rate

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

    def _resolve_multiplier_unlocked(self, product_id: Optional[str]) -> float:
        """Return the fee multiplier for a given product.

        FUTURES products use ``FUTURES_FEE_MULTIPLIER`` (1.0 by default);
        SPOT products and unknown/unresolvable cases use
        ``SPOT_FEE_MULTIPLIER`` (1.1 by default — slightly conservative
        cushion for tier-slip on the higher spot fee schedule).

        Resolution mirrors ``ProfitValidator._resolve_product_context``:
        consults the orderbook's product metadata when available, falls
        back to the ``-CDE`` suffix heuristic, and finally to SPOT.

        Returns SPOT multiplier when ``product_id`` is None, when no
        orderbook was injected, or when any resolution step raises.
        Caller already holds ``self._lock``.
        """
        if not product_id:
            return self.SPOT_FEE_MULTIPLIER
        try:
            from configuration import normalize_product_type as _normalize_product_type
            from core.enums import ProductType

            order_for_normalize = {"product_id": product_id}
            products = self.orderbook.product if self.orderbook else None
            product_type = _normalize_product_type(order_for_normalize, products=products)
            if product_type == ProductType.FUTURE.value:
                return self.FUTURES_FEE_MULTIPLIER
            return self.SPOT_FEE_MULTIPLIER
        except Exception:
            # Resolver is best-effort. Never let a metadata gap raise
            # into the fee path: fall back to the SPOT cushion (the
            # safer of the two options for an unknown product).
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
    ) -> float:
        """Get adaptive effective fee rate for profit validation.

        Effective fee = base fee × product-type multiplier × regime fee factor.

        Args:
            product_id: Optional product hint for multiplier resolution.
            post_only: When ``True``, base the calculation on the maker
                fee rate (the order will rest as a maker if it doesn't
                cross). When ``False`` (default), use the taker rate —
                this matches the behavior of ``CONFIGURED_LIMIT`` reveals
                where the user-supplied price may cross the spread.

        Picking the right base rate matters: a TOP_OF_BOOK reveal that
        succeeds with ``post_only=True`` is charged the maker rate by
        Coinbase, so validating against the taker rate over-rejects
        feasibility at low target_movements.
        """
        with self._lock:
            base_rate = self._maker_fee_rate if post_only else self._taker_fee_rate
            multiplier = self._resolve_multiplier_unlocked(product_id)
            base_effective_fee = base_rate * multiplier
            regime_factors = self._derive_regime_factors_unlocked(product_id)
            return base_effective_fee * regime_factors["fee_factor"]
    
    def get_fee_info(self, product_id: Optional[str] = None) -> Dict[str, Any]:
        """Get comprehensive fee information.

        Returns:
            Dict with both maker- and taker-based effective rates so
            callers can preview either liquidity model.
        """
        with self._lock:
            taker_base = self._taker_fee_rate
            maker_base = self._maker_fee_rate
            multiplier = self._resolve_multiplier_unlocked(product_id)
            factors = self._derive_regime_factors_unlocked(product_id)
            taker_effective = (taker_base * multiplier) * factors["fee_factor"]
            maker_effective = (maker_base * multiplier) * factors["fee_factor"]

            # Example: Cost for 1 BTC at $50,000 (round-trip, taker model)
            example_btc_price = 50000.0
            example_cost_base = example_btc_price * taker_base * 2
            example_cost_effective = example_btc_price * taker_effective * 2

            return {
                "taker_fee_rate": taker_base,
                "maker_fee_rate": maker_base,
                "profit_validation_fee_rate": taker_effective,            # default: taker
                "profit_validation_fee_rate_taker": taker_effective,
                "profit_validation_fee_rate_maker": maker_effective,
                "multiplier": multiplier,
                "target_movement_factor": factors["target_movement_factor"],
                "fee_regime_factor": factors["fee_factor"],
                "volume_ratio": factors["volume_ratio"],
                "overnight_margin_active": factors["overnight_margin_active"],
                "margin_window_type": factors["margin_window_type"],
                "last_updated": self._last_updated.isoformat() if self._last_updated else None,
                "is_stale": self.is_stale(),
                "fee_per_trade_1btc_base": example_cost_base,
                "fee_per_trade_1btc_effective": example_cost_effective,
                "note": "Effective fees use base × product-type multiplier × regime fee factor. "
                        "Maker rate applies when the order rests as a maker (post_only=True)."
            }
    
    def validate_fee_freshness(self, max_age_seconds: int = 7200) -> Dict[str, Any]:
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
            if not self._last_updated:
                return {
                    "is_fresh": False,
                    "age_seconds": None,
                    "last_updated": None,
                    "remediation": "Never fetched - call refresh_fee_rate() immediately"
                }
            
            age = (datetime.utcnow() - self._last_updated).total_seconds()
            is_fresh = age <= max_age_seconds
            
            return {
                "is_fresh": is_fresh,
                "age_seconds": age,
                "last_updated": self._last_updated.isoformat(),
                "remediation": None if is_fresh else "Call refresh_fee_rate() to update"
            }
    
    def explain_fee_multiplier(self, product_id: Optional[str] = None) -> Dict[str, Any]:
        """Explain fee and regime factor calculation for verification/debugging."""
        with self._lock:
            base_fee = self._taker_fee_rate
            multiplier = self._resolve_multiplier_unlocked(product_id)
            factors = self._derive_regime_factors_unlocked(product_id)
            effective_fee = (base_fee * multiplier) * factors["fee_factor"]
            
            # Example: BUY @ $50,000 (open), SELL @ $52,500 (close)
            example_open_price = 50000.0
            example_close_price = 52500.0
            example_size = 1.0
            
            # OPEN order: NO FEE
            fee_on_open = 0.0
            
            # CLOSE order: FEE CHARGED
            fee_on_close = example_close_price * example_size * effective_fee
            
            total_example = fee_on_open + fee_on_close
            gross_profit = example_close_price - example_open_price
            net_profit = gross_profit * example_size - fee_on_close
            
            return {
                "base_fee_from_coinbase": base_fee,
                "multiplier_applied": multiplier,
                "fee_regime_factor": factors["fee_factor"],
                "target_movement_factor": factors["target_movement_factor"],
                "volume_ratio": factors["volume_ratio"],
                "overnight_margin_active": factors["overnight_margin_active"],
                "margin_window_type": factors["margin_window_type"],
                "effective_fee_rate": effective_fee,
                "calculation_method": "effective = base x base_multiplier x regime_factor, applied on close",
                "example": {
                    "open_price": example_open_price,
                    "close_price": example_close_price,
                    "size": example_size,
                    "fee_on_open": fee_on_open,
                    "fee_on_close": fee_on_close,
                    "gross_profit": gross_profit * example_size,
                    "net_profit": net_profit,
                    "total_fees_for_round_trip": total_example,
                    "note": "Fee is charged ONLY when the position is closed, not when opened"
                },
                "warning": "If you see fees on both open and close orders, behavior is incorrect. Only close is charged."
            }
