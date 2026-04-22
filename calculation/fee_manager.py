"""Fee Manager - Dynamic fee rate fetching from Coinbase API with hourly refresh.

Maintains current taker fee rates from the Coinbase API and applies 4x multiplier
to ensure we capture enough revenue to cover costs and profit.

CRITICAL: Fee Charging Model
=============================

Fees are charged ONLY when orders close (fill on exchange):
1. Parent order closes → Coinbase charges base fee on that order
2. Follow-up order closes → Coinbase charges base fee on that order
3. Total: 2 fees (one per order close), NOT 4 fees

We apply 4x multiplier to the BASE fee rate, not separately on each side:
- Base fee (from Coinbase): 0.6% (0.0060)
- Our markup: 4x multiplier
- Effective fee for validation: 0.6% × 4 = 2.4% (0.024)
- Total cost for round trip: 2 × 0.024 = 4.8% (NOT 2×2×!)

Example of WRONG calculation (AVOID):
  ❌ Fee on buy = price × size × base × 2
  ❌ Fee on sell = price × size × base × 2
  ❌ Total = price × size × base × 4  (WRONG!)

Example of CORRECT calculation (CURRENT):
  ✓ Effective fee = base × 4 = 0.024
  ✓ Fee on buy = price × size × 0.024 (once, not twice)
  ✓ Fee on sell = price × size × 0.024 (once, not twice)
  ✓ Total = 2 × (price × size × 0.024) = correct!

Architecture:
- Fetches taker_fee_rate from REST API (via transaction_summary)
- Caches the base rate with timestamp tracking
- Returns (base_rate × 4) for profit validation
- Refreshes hourly in background thread
- Thread-safe access via lock
- Fallback to conservative default if API fails
"""

import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from time import sleep

from calculation.formatter import safe_float


class FeeManager:
    """Manages dynamic fee rates from Coinbase API with caching and auto-refresh.
    
    Features:
    - Fetches actual taker fees from Coinbase transaction_summary endpoint
    - Multiplies base fee by 4x (2x each way) for profit validation
    - Auto-refreshes hourly in background thread
    - Thread-safe access with RWLock
    - Fallback to conservative default if API unavailable
    - Detailed logging of fee updates
    
    Example:
        >>> manager = FeeManager(rest_client, log_callback=engine.log_message)
        >>> manager.start()  # Start hourly refresh thread
        >>> 
        >>> # Get current effective fee for profit validation
        >>> effective_fee = manager.get_effective_fee_rate()
        >>> print(f"Effective fee (base * 4x): {effective_fee:.6f}")
        
        >>> # Get individual fees
        >>> base_fee = manager.get_taker_fee_rate()
        >>> profit_fee = manager.get_profit_validation_fee_rate()
    """
    
    # Conservative defaults (0.6% taker + 4x multiplier = 2.4%)
    DEFAULT_TAKER_FEE_RATE = 0.0060  # 0.6% from API documentation
    DEFAULT_MULTIPLIER = 4.0
    REFRESH_INTERVAL_SECONDS = 3600  # 1 hour
    
    def __init__(self, rest_client, log_callback=None):
        """Initialize FeeManager.
        
        Args:
            rest_client: Initialized CoinbaseRestClient instance
            log_callback: Optional logging callback (log_type, message)
        """
        self.rest_client = rest_client
        self.log_callback = log_callback or self._default_log
        
        # Thread-safe access to fee rates
        self._lock = threading.RLock()
        
        # Fee rate data with tracking
        self._taker_fee_rate = self.DEFAULT_TAKER_FEE_RATE
        self._last_updated = None
        self._refresh_thread = None
        self._running = False
        self._fetch_error_count = 0
        self._max_consecutive_errors = 3  # Fall back to default after 3 errors
    
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
        """Stop background refresh thread."""
        self._running = False
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)
        self.log_callback("info", "Fee manager stopped")
    
    def _refresh_loop(self):
        """Background loop that refreshes fee rates hourly."""
        while self._running:
            try:
                sleep(self.REFRESH_INTERVAL_SECONDS)
                if self._running:  # Check again after sleep
                    self._refresh_fee_rate()
            except Exception as e:
                self.log_callback("error", f"Fee refresh loop error: {e}")
                sleep(5)  # Backoff before retry
    
    def _refresh_fee_rate(self) -> bool:
        """Fetch latest taker fee rate from Coinbase API.
        
        Returns:
            True if successfully fetched, False if API call failed
        """
        try:
            summary = self.rest_client.get_transaction_summary()
            
            # Extract taker_fee_rate from response
            taker_fee_str = summary.get("taker_fee_rate", str(self.DEFAULT_TAKER_FEE_RATE))
            taker_fee = safe_float(taker_fee_str, default=self.DEFAULT_TAKER_FEE_RATE)
            
            with self._lock:
                old_rate = self._taker_fee_rate
                self._taker_fee_rate = taker_fee
                self._last_updated = datetime.utcnow()
                self._fetch_error_count = 0  # Reset error counter on success
            
            # Log update if rate changed
            if abs(old_rate - taker_fee) > 0.00001:  # More than rounding error
                self.log_callback("info", {
                    "event": "taker_fee_rate_updated",
                    "old_rate": old_rate,
                    "new_rate": taker_fee,
                    "effective_profit_fee": taker_fee * self.DEFAULT_MULTIPLIER,
                    "timestamp": self._last_updated.isoformat()
                })
            else:
                self.log_callback("debug", {
                    "event": "taker_fee_rate_refreshed",
                    "taker_fee_rate": taker_fee,
                    "timestamp": self._last_updated.isoformat()
                })
            
            return True
            
        except Exception as e:
            with self._lock:
                self._fetch_error_count += 1
                
                # If too many consecutive errors, use default
                if self._fetch_error_count >= self._max_consecutive_errors:
                    self._taker_fee_rate = self.DEFAULT_TAKER_FEE_RATE
                    self._last_updated = datetime.utcnow()
            
            self.log_callback("warning", {
                "event": "taker_fee_fetch_failed",
                "error": str(e),
                "error_count": self._fetch_error_count,
                "fallback_rate": self._taker_fee_rate if self._fetch_error_count >= self._max_consecutive_errors else "previous",
                "note": "Using default conservative rate" if self._fetch_error_count >= self._max_consecutive_errors else "Will retry next hour"
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
    
    def get_profit_validation_fee_rate(self) -> float:
        """Get effective fee rate for profit validation (base * 4x).
        
        This is the fee rate used by ProfitValidator to ensure we charge
        at least 4x the base taker fee (2x each way on buy + sell).
        
        Returns:
            Fee rate as decimal (e.g., 0.024 for 2.4% when base is 0.6%)
        """
        with self._lock:
            return self._taker_fee_rate * self.DEFAULT_MULTIPLIER
    
    def get_fee_info(self) -> Dict[str, Any]:
        """Get comprehensive fee information.
        
        Returns:
            Dict with keys:
            - taker_fee_rate: Base taker fee rate (e.g., 0.0060)
            - profit_validation_fee_rate: 4x multiplied rate (e.g., 0.024)
            - multiplier: Applied multiplier (4.0)
            - last_updated: Timestamp of last successful API call
            - is_stale: Whether data is considered stale
            - fee_per_trade_1btc: Example fee for 1 BTC at $50,000
        """
        with self._lock:
            base_fee = self._taker_fee_rate
            effective_fee = base_fee * self.DEFAULT_MULTIPLIER
            
            # Example: Cost for 1 BTC at $50,000
            example_btc_price = 50000.0
            example_cost_base = example_btc_price * base_fee * 2  # Buy + sell
            example_cost_effective = example_btc_price * effective_fee * 2  # Profit validation
            
            return {
                "taker_fee_rate": base_fee,
                "profit_validation_fee_rate": effective_fee,
                "multiplier": self.DEFAULT_MULTIPLIER,
                "last_updated": self._last_updated.isoformat() if self._last_updated else None,
                "is_stale": self.is_stale(),
                "fee_per_trade_1btc_base": example_cost_base,
                "fee_per_trade_1btc_effective": example_cost_effective,
                "note": "Effective fee is 4x base (2x each way) to ensure profitability"
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
    
    def explain_fee_multiplier(self) -> Dict[str, Any]:
        """Explain the fee multiplier calculation (for verification and debugging).
        
        Shows exactly how the 4x multiplier is applied to the CLOSE order only.
        
        Returns:
            Dict with detailed breakdown
        """
        with self._lock:
            base_fee = self._taker_fee_rate
            effective_fee = base_fee * self.DEFAULT_MULTIPLIER
            
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
                "multiplier_applied": self.DEFAULT_MULTIPLIER,
                "effective_fee_rate": effective_fee,
                "calculation_method": "effective = base × 4, applied ONCE on the close order",
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
                "warning": "If you see fees on BOTH the open and close order, that's incorrect. Only close order is charged."
            }
