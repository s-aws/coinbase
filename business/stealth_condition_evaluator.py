"""Stealth Order Condition Evaluators - Flexible Reveal Triggers.

This module provides evaluators for different condition types that determine when
hidden stealth orders should be revealed (placed) on the exchange. Each evaluator
implements logic to detect specific market conditions.

Supported Condition Types:
    - PRICE_THRESHOLD: Reveal when price crosses a target price level
    - CUMULATIVE_VOLUME: Reveal when trading volume accumulates at a price level
    - TIME_DELAY: Reveal after a time delay with optional jitter
    - SPREAD: Reveal when bid-ask spread narrows below a threshold
    - PRODUCT_RATIO: Reveal when ratio between two products meets threshold
    - COMPOSITE: Reveal when multiple conditions combine with AND/OR logic

All evaluators inherit from ConditionEvaluator base class and implement the
evaluate() method which returns (condition_met: bool, reason: Optional[str]).

Factory Pattern:
    Use get_evaluator(condition_type) to instantiate appropriate evaluator for
    a given condition type. Returns TimeDelayEvaluator as default fallback.

Usage:
    >>> from business.stealth_condition_evaluator import get_evaluator
    >>> from core.enums import RevealConditionType
    >>> 
    >>> evaluator = get_evaluator(RevealConditionType.PRICE_THRESHOLD.value)
    >>> condition_config = {
    ...     "price_threshold": 41000.00,
    ...     "direction": "below",
    ...     "hold_duration_seconds": 2,
    ... }
    >>> market_data = {"price": 40900.00}
    >>> order_data = {"condition_first_met_at": None}
    >>> met, reason = evaluator.evaluate(market_data, condition_config, order_data)
    >>> met
    False
    >>> reason
    'Price 40900.0 crossed below 41000.0, watching hold time...'
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Dict, Any, Tuple, Optional
from collections import defaultdict
from core.enums import RevealConditionType, Direction
from core.exceptions import RevealConditionEvaluationError


@dataclass(frozen=True)
class StableDeadlineResult:
    """Read-only resolution of a condition's deterministic UTC deadline.

    ``supported`` means this evaluator has a deterministic deadline model.
    ``stable`` means the order currently contains enough durable state to
    calculate that deadline.  For example, a price hold is supported but is
    not stable until ``condition_first_met_at`` has been recorded.

    Evaluators whose result depends on mutable internal buckets, random jitter,
    multiple products, or child conditions deliberately report
    ``supported=False``.  The scheduler must keep those conditions on an
    event/evaluation path instead of inventing a deadline.
    """

    deadline_utc: Optional[datetime]
    supported: bool
    stable: bool
    reason: str
    valid: bool = True

    @property
    def available(self) -> bool:
        """Return whether a concrete, stable deadline is available."""

        return self.supported and self.stable and self.deadline_utc is not None


@dataclass(frozen=True)
class ConditionTruthResult:
    """Read-only instantaneous truth used to validate a due deadline.

    ``truth=None`` means the evaluator supports a read-only truth check but
    required market/order data is unavailable.  ``supported=False`` means the
    condition cannot be reduced to this stateless helper without changing its
    existing semantics.
    """

    truth: Optional[bool]
    supported: bool
    reason: str

    @property
    def known(self) -> bool:
        """Return whether ``truth`` contains a usable Boolean result."""

        return self.supported and self.truth is not None


def _deadline_from_order_timestamp(
    order_data: Dict[str, Any],
    condition_config: Dict[str, Any],
    *,
    timestamp_field: str,
    seconds_field: str,
) -> StableDeadlineResult:
    """Resolve ``order timestamp + configured seconds`` without mutation."""

    try:
        seconds = float(condition_config.get(seconds_field, 0))
    except (TypeError, ValueError):
        return StableDeadlineResult(
            deadline_utc=None,
            supported=True,
            stable=False,
            reason=f"Invalid numeric condition field '{seconds_field}'",
            valid=False,
        )
    if not math.isfinite(seconds):
        return StableDeadlineResult(
            deadline_utc=None,
            supported=True,
            stable=False,
            reason=f"Non-finite condition field '{seconds_field}'",
            valid=False,
        )

    timestamp = order_data.get(timestamp_field)
    if not isinstance(timestamp, datetime):
        return StableDeadlineResult(
            deadline_utc=None,
            supported=True,
            stable=False,
            reason=f"Waiting for datetime order field '{timestamp_field}'",
        )

    return StableDeadlineResult(
        deadline_utc=timestamp + timedelta(seconds=seconds),
        supported=True,
        stable=True,
        reason=f"Stable deadline from {timestamp_field} + {seconds_field}",
    )


def _now_matching(reference: datetime, now_utc: Optional[datetime]) -> datetime:
    """Return an injected/default UTC ``now`` comparable with ``reference``.

    Existing persisted timestamps are normally naive UTC.  Tests and future
    scheduler callers may use timezone-aware UTC values, so the helper aligns
    awareness without altering either input.
    """

    current = now_utc if now_utc is not None else datetime.utcnow()
    if not isinstance(current, datetime):
        raise TypeError("now_utc must be a datetime or None")

    reference_is_aware = reference.utcoffset() is not None
    current_is_aware = current.utcoffset() is not None
    if reference_is_aware and not current_is_aware:
        return current.replace(tzinfo=timezone.utc).astimezone(reference.tzinfo)
    if not reference_is_aware and current_is_aware:
        return current.astimezone(timezone.utc).replace(tzinfo=None)
    return current


class ConditionEvaluator(ABC):
    """Base class for all reveal condition evaluators."""

    def resolve_stable_deadline(
        self,
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> StableDeadlineResult:
        """Describe whether this condition has a deterministic deadline.

        The default is intentionally unsupported.  Subclasses opt in only
        when the deadline can be derived without random sampling, mutable
        evaluator state, external product assembly, or child evaluation.
        """

        return StableDeadlineResult(
            deadline_utc=None,
            supported=False,
            stable=False,
            reason=f"{type(self).__name__} has no stable standalone deadline",
        )

    def evaluate_truth(
        self,
        market_data: Dict[str, Any],
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
        *,
        now_utc: Optional[datetime] = None,
    ) -> ConditionTruthResult:
        """Read instantaneous truth without mutating evaluator/order state."""

        return ConditionTruthResult(
            truth=None,
            supported=False,
            reason=f"{type(self).__name__} has no stateless truth helper",
        )
    
    @abstractmethod
    def evaluate(self, 
                market_data: Dict[str, Any],
                condition_config: Dict[str, Any],
                order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Evaluate if reveal condition is met.
        
        Args:
            market_data: Current market state (prices, volumes, spreads)
            condition_config: Condition parameters from stealth_orders table
            order_data: Current order state
            
        Returns:
            Tuple of (condition_met: bool, reason: Optional[str])
        """
        pass


class PriceThresholdEvaluator(ConditionEvaluator):
    """Reveals when price crosses threshold and holds for minimum duration."""

    def resolve_stable_deadline(
        self,
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> StableDeadlineResult:
        try:
            threshold = float(condition_config["price_threshold"])
        except (KeyError, TypeError, ValueError):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=True,
                stable=False,
                reason="Invalid or missing price_threshold",
                valid=False,
            )
        if not math.isfinite(threshold):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=True,
                stable=False,
                reason="Non-finite price_threshold",
                valid=False,
            )
        direction = condition_config.get("direction", Direction.BELOW.value)
        if direction not in {Direction.BELOW.value, Direction.ABOVE.value}:
            return StableDeadlineResult(
                deadline_utc=None,
                supported=True,
                stable=False,
                reason=f"Invalid price direction: {direction!r}",
                valid=False,
            )
        return _deadline_from_order_timestamp(
            order_data,
            condition_config,
            timestamp_field="condition_first_met_at",
            seconds_field="hold_duration_seconds",
        )

    def evaluate_truth(
        self,
        market_data: Dict[str, Any],
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
        *,
        now_utc: Optional[datetime] = None,
    ) -> ConditionTruthResult:
        if "price_threshold" not in condition_config or condition_config.get("price_threshold") is None:
            raise RevealConditionEvaluationError(
                message="PriceThresholdEvaluator requires 'price_threshold' in condition config",
                condition_type="PRICE_THRESHOLD",
            )

        current_price = market_data.get("price", 0)
        if current_price == 0:
            return ConditionTruthResult(
                truth=None,
                supported=True,
                reason="Price market data is unavailable",
            )

        threshold = float(condition_config.get("price_threshold", 0))
        direction = condition_config.get("direction", Direction.BELOW.value)
        truth = (
            current_price < threshold
            if direction == Direction.BELOW.value
            else current_price > threshold
        )
        return ConditionTruthResult(
            truth=truth,
            supported=True,
            reason=f"Price threshold currently {'met' if truth else 'not met'}",
        )
    
    def evaluate(self, market_data: Dict[str, Any], condition_config: Dict[str, Any], 
                 order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Check if price crossed threshold and held.
        
        Condition config:
        {
            "price_threshold": 41000.00,
            "direction": "below",  # "below" or "above"
            "hold_duration_seconds": 2,
        }
        """
        # Validate required configuration fields
        
        if "price_threshold" not in condition_config or condition_config.get("price_threshold") is None:
            raise RevealConditionEvaluationError(
                message="PriceThresholdEvaluator requires 'price_threshold' in condition config",
                condition_type="PRICE_THRESHOLD"
            )
        threshold = float(condition_config.get("price_threshold", 0))
        direction = condition_config.get("direction", Direction.BELOW.value)
        hold_duration = float(condition_config.get("hold_duration_seconds", 0))
        
        current_price = market_data.get("price", 0)
        condition_first_met = order_data.get("condition_first_met_at")
        
        # Guard: Don't evaluate if market data not available (price = 0)
        if current_price == 0:
            return False, f"Waiting for market data for {condition_config.get('price_threshold', 'unknown')}"
        
        # Check if threshold crossed
        if direction == Direction.BELOW.value:
            threshold_crossed = current_price < threshold
        else:  # Direction.ABOVE
            threshold_crossed = current_price > threshold
        
        if not threshold_crossed:
            return False, None
        
        # First time threshold crossed
        if not condition_first_met:
            return False, f"Price {current_price} crossed {direction} {threshold}, watching hold time..."
        
        # Check if held long enough
        time_held = datetime.utcnow() - condition_first_met
        if time_held >= timedelta(seconds=hold_duration):
            reason = f"Price {current_price} held {direction} {threshold} for {hold_duration}s"
            return True, reason
        
        return False, f"Price held for {time_held.total_seconds():.1f}s, need {hold_duration}s"


class CumulativeVolumeEvaluator(ConditionEvaluator):
    """Reveals when cumulative volume at price level is reached."""
    
    def __init__(self):
        # Track: product_id -> price_level -> accumulated_volume
        self.volume_buckets = defaultdict(lambda: defaultdict(float))
        self.bucket_start_time = defaultdict(lambda: defaultdict(lambda: datetime.utcnow()))

    def resolve_stable_deadline(
        self,
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> StableDeadlineResult:
        del order_data
        if (
            "product_id" not in condition_config
            or condition_config.get("product_id") is None
        ):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=False,
                stable=False,
                reason="Invalid or missing cumulative-volume product_id",
                valid=False,
            )
        for field, default in (
            ("price_level", None),
            ("volume_threshold", None),
            ("lookback_seconds", 30),
        ):
            value = condition_config.get(field, default)
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                parsed = math.nan
            if not math.isfinite(parsed):
                return StableDeadlineResult(
                    deadline_utc=None,
                    supported=False,
                    stable=False,
                    reason=f"Invalid cumulative-volume field '{field}'",
                    valid=False,
                )
        return super().resolve_stable_deadline(condition_config, {})
    
    def evaluate(self, market_data: Dict[str, Any], condition_config: Dict[str, Any],
                 order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Check if cumulative volume at price level met.
        
        Condition config:
        {
            "product_id": "BTC-USDC",
            "price_level": 42000.00,
            "volume_threshold": 10.0,
            "lookback_seconds": 30,
        }
        """
        # Validate required configuration fields
        
        required_fields = ["product_id", "price_level", "volume_threshold"]
        for field in required_fields:
            if field not in condition_config or condition_config.get(field) is None:
                raise RevealConditionEvaluationError(
                    message=f"CumulativeVolumeEvaluator requires '{field}' in condition config",
                    condition_type="CUMULATIVE_VOLUME"
                )
        product_id = condition_config.get("product_id")
        price_level = float(condition_config.get("price_level", 0))
        volume_threshold = float(condition_config.get("volume_threshold", 0))
        lookback_seconds = float(condition_config.get("lookback_seconds", 30))
        
        current_price = market_data.get("price", 0)
        trade_volume = market_data.get("trade_volume", 0)  # Volume of recent trade
        
        # Only count trades near the target price level (±0.5%)
        price_tolerance = price_level * 0.005
        if abs(current_price - price_level) > price_tolerance:
            return False, f"Price {current_price} not near {price_level}"
        
        # Accumulate volume in bucket
        bucket_key = f"{product_id}_{price_level}"
        self.volume_buckets[bucket_key][price_level] += trade_volume
        
        # Reset bucket if lookback window expired
        if (datetime.utcnow() - self.bucket_start_time[bucket_key][price_level]).total_seconds() > lookback_seconds:
            self.volume_buckets[bucket_key][price_level] = trade_volume
            self.bucket_start_time[bucket_key][price_level] = datetime.utcnow()
        
        accumulated = self.volume_buckets[bucket_key][price_level]
        
        if accumulated >= volume_threshold:
            reason = f"Volume {accumulated:.2f} reached threshold {volume_threshold} at ${price_level}"
            return True, reason
        
        return False, f"Volume {accumulated:.2f}/{volume_threshold} at ${price_level}"


class TimeDelayEvaluator(ConditionEvaluator):
    """Reveals after specified delay with random jitter."""

    def resolve_stable_deadline(
        self,
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> StableDeadlineResult:
        created_at = order_data.get("created_at")
        if not isinstance(created_at, datetime):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=True,
                stable=False,
                reason="Time-delay order requires datetime created_at",
                valid=False,
            )
        try:
            delay_seconds = float(condition_config.get("delay_seconds", 0))
            jitter = float(condition_config.get("jitter_seconds", 0))
        except (TypeError, ValueError):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=False,
                stable=False,
                reason="Time-delay delay/jitter must be numeric",
                valid=False,
            )
        if not math.isfinite(delay_seconds) or not math.isfinite(jitter):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=False,
                stable=False,
                reason="Time-delay delay/jitter must be finite",
                valid=False,
            )

        if jitter != 0:
            return StableDeadlineResult(
                deadline_utc=None,
                supported=False,
                stable=False,
                reason=(
                    "Time-delay jitter is sampled on each existing evaluate() "
                    "call, so no stable deadline exists"
                ),
            )

        return _deadline_from_order_timestamp(
            order_data,
            condition_config,
            timestamp_field="created_at",
            seconds_field="delay_seconds",
        )

    def evaluate_truth(
        self,
        market_data: Dict[str, Any],
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
        *,
        now_utc: Optional[datetime] = None,
    ) -> ConditionTruthResult:
        deadline = self.resolve_stable_deadline(condition_config, order_data)
        if not deadline.supported:
            return ConditionTruthResult(
                truth=None,
                supported=False,
                reason=deadline.reason,
            )
        if not deadline.available:
            return ConditionTruthResult(
                truth=None,
                supported=True,
                reason=deadline.reason,
            )

        current = _now_matching(deadline.deadline_utc, now_utc)
        truth = current >= deadline.deadline_utc
        return ConditionTruthResult(
            truth=truth,
            supported=True,
            reason=f"Time deadline currently {'met' if truth else 'not met'}",
        )
    
    def evaluate(self, market_data: Dict[str, Any], condition_config: Dict[str, Any],
                 order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Check if minimum time delay passed.
        
        Condition config:
        {
            "delay_seconds": 60,
            "jitter_seconds": 30,  # Random ± 30 seconds
        }
        """
        import random
        
        created_at = order_data.get("created_at")
        # Keep runtime evaluation consistent with activation validation, which
        # deliberately accepts JSON numeric strings as finite numbers.
        delay = float(condition_config.get("delay_seconds", 0))
        jitter = float(condition_config.get("jitter_seconds", 0))
        
        if not created_at:
            return False, "Order creation time not set"
        
        # Calculate random delay between (delay - jitter) and (delay + jitter)
        random_delay = delay + random.uniform(-jitter, jitter)
        time_elapsed = (datetime.utcnow() - created_at).total_seconds()
        
        if time_elapsed >= random_delay:
            reason = f"Time delay {random_delay:.1f}s elapsed ({time_elapsed:.1f}s actual)"
            return True, reason
        
        return False, f"Waiting {random_delay - time_elapsed:.1f}s more ({delay}±{jitter}s)"


class SpreadEvaluator(ConditionEvaluator):
    """Reveals when bid-ask spread narrows below threshold."""

    def resolve_stable_deadline(
        self,
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> StableDeadlineResult:
        try:
            max_spread = float(condition_config["max_spread"])
        except (KeyError, TypeError, ValueError):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=True,
                stable=False,
                reason="Invalid or missing max_spread",
                valid=False,
            )
        if not math.isfinite(max_spread):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=True,
                stable=False,
                reason="Non-finite max_spread",
                valid=False,
            )
        return _deadline_from_order_timestamp(
            order_data,
            condition_config,
            timestamp_field="condition_first_met_at",
            seconds_field="hold_duration_seconds",
        )

    def evaluate_truth(
        self,
        market_data: Dict[str, Any],
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
        *,
        now_utc: Optional[datetime] = None,
    ) -> ConditionTruthResult:
        if "max_spread" not in condition_config or condition_config.get("max_spread") is None:
            raise RevealConditionEvaluationError(
                message="SpreadEvaluator requires 'max_spread' in condition config",
                condition_type="SPREAD",
            )

        bid = market_data.get("bid", 0)
        ask = market_data.get("ask", 0)
        if bid <= 0 or ask <= 0:
            return ConditionTruthResult(
                truth=None,
                supported=True,
                reason="Bid/ask market data is unavailable",
            )

        max_spread = float(condition_config.get("max_spread", 999999))
        truth = (ask - bid) <= max_spread
        return ConditionTruthResult(
            truth=truth,
            supported=True,
            reason=f"Spread threshold currently {'met' if truth else 'not met'}",
        )
    
    def evaluate(self, market_data: Dict[str, Any], condition_config: Dict[str, Any],
                 order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Check if spread narrowed enough.
        
        Condition config:
        {
            "product_id": "BIT-24APR26-CDE",
            "max_spread": 2.00,
            "hold_duration_seconds": 1,
        }
        """
        # Validate required configuration fields
        
        if "max_spread" not in condition_config or condition_config.get("max_spread") is None:
            raise RevealConditionEvaluationError(
                message="SpreadEvaluator requires 'max_spread' in condition config",
                condition_type="SPREAD"
            )
        max_spread = float(condition_config.get("max_spread", 999999))
        hold_duration = float(condition_config.get("hold_duration_seconds", 0))
        
        bid = market_data.get("bid", 0)
        ask = market_data.get("ask", 0)
        
        if bid <= 0 or ask <= 0:
            return False, "Bid/ask data not available"
        
        current_spread = ask - bid
        condition_first_met = order_data.get("condition_first_met_at")
        
        if current_spread > max_spread:
            return False, f"Spread ${current_spread:.2f} > ${max_spread:.2f}"
        
        # First time spread is tight enough
        if not condition_first_met:
            return False, f"Spread ${current_spread:.2f} tightened, watching hold time..."
        
        # Check if held tight long enough
        time_held = datetime.utcnow() - condition_first_met
        if time_held >= timedelta(seconds=hold_duration):
            reason = f"Spread ${current_spread:.2f} held < ${max_spread:.2f} for {hold_duration}s"
            return True, reason
        
        return False, f"Spread held for {time_held.total_seconds():.1f}s, need {hold_duration}s"


class ProductRatioEvaluator(ConditionEvaluator):
    """Reveals when price ratio between two products meets threshold."""

    def resolve_stable_deadline(
        self,
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> StableDeadlineResult:
        del order_data
        for field in ("product_a", "product_b"):
            if field not in condition_config or condition_config.get(field) is None:
                return StableDeadlineResult(
                    deadline_utc=None,
                    supported=False,
                    stable=False,
                    reason=f"Invalid or missing product-ratio field '{field}'",
                    valid=False,
                )
        try:
            threshold = float(condition_config.get("ratio_threshold"))
        except (TypeError, ValueError):
            threshold = math.nan
        if not math.isfinite(threshold):
            return StableDeadlineResult(
                deadline_utc=None,
                supported=False,
                stable=False,
                reason="Invalid product-ratio field 'ratio_threshold'",
                valid=False,
            )
        return super().resolve_stable_deadline(condition_config, {})
    
    def evaluate(self, market_data: Dict[str, Any], condition_config: Dict[str, Any],
                 order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Check if product ratio triggered.
        
        Condition config:
        {
            "product_a": "BIT-24APR26-CDE",
            "product_b": "BIP-20DEC30-CDE",
            "ratio_threshold": 0.99,  # BIT/BIP
            "direction": "below",      # Trigger when ratio falls below threshold
        }
        """
        # Validate required configuration fields
        
        required_fields = ["product_a", "product_b", "ratio_threshold"]
        for field in required_fields:
            if field not in condition_config or condition_config.get(field) is None:
                raise RevealConditionEvaluationError(
                    message=f"ProductRatioEvaluator requires '{field}' in condition config",
                    condition_type="PRODUCT_RATIO"
                )
        price_a = market_data.get("price_a", 0)
        price_b = market_data.get("price_b", 0)
        threshold = float(condition_config.get("ratio_threshold", 0))
        direction = condition_config.get("direction", Direction.BELOW.value)
        
        if price_a <= 0 or price_b <= 0:
            return False, "Price data for one/both products missing"
        
        ratio = price_a / price_b
        
        if direction == Direction.BELOW.value:
            threshold_met = ratio < threshold
        else:  # Direction.ABOVE
            threshold_met = ratio > threshold
        
        if threshold_met:
            reason = f"Ratio {ratio:.6f} {direction} threshold {threshold:.6f}"
            return True, reason
        
        return False, f"Ratio {ratio:.6f} not {direction} {threshold:.6f}"


class CompositeEvaluator(ConditionEvaluator):
    """Evaluates multiple conditions with AND/OR logic."""

    def resolve_stable_deadline(
        self,
        condition_config: Dict[str, Any],
        order_data: Dict[str, Any],
    ) -> StableDeadlineResult:
        conditions = condition_config.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            return StableDeadlineResult(
                deadline_utc=None,
                supported=False,
                stable=False,
                reason="Composite condition requires a non-empty conditions list",
                valid=False,
            )

        evaluator_types = {
            RevealConditionType.PRICE_THRESHOLD.value,
            RevealConditionType.CUMULATIVE_VOLUME.value,
            RevealConditionType.TIME_DELAY.value,
            RevealConditionType.SPREAD.value,
            RevealConditionType.PRODUCT_RATIO.value,
        }
        for index, child in enumerate(conditions):
            if not isinstance(child, dict):
                return StableDeadlineResult(
                    deadline_utc=None,
                    supported=False,
                    stable=False,
                    reason=f"Composite child {index} must be an object",
                    valid=False,
                )
            child_type = child.get("type", "")
            if not isinstance(child_type, str):
                return StableDeadlineResult(
                    deadline_utc=None,
                    supported=False,
                    stable=False,
                    reason=f"Composite child {index} type must be a string",
                    valid=False,
                )
            if child_type.lower() not in evaluator_types:
                # Preserve the compatibility evaluator's historical behavior:
                # unknown child names are ignored, and an empty result set
                # simply remains unmet.
                continue
            child_result = get_evaluator(child_type.lower()).resolve_stable_deadline(
                child,
                order_data,
            )
            if not child_result.valid:
                return StableDeadlineResult(
                    deadline_utc=None,
                    supported=False,
                    stable=False,
                    reason=f"Invalid composite child {index}: {child_result.reason}",
                    valid=False,
                )

        return super().resolve_stable_deadline(condition_config, order_data)
    
    def evaluate(self, market_data: Dict[str, Any], condition_config: Dict[str, Any],
                 order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Check multiple conditions.
        
        Condition config:
        {
            "operator": "AND",  # or "OR"
            "conditions": [
                {"type": "price", ...},
                {"type": "spread", ...},
            ]
        }
        """
        # Validate required configuration fields
        
        if "conditions" not in condition_config or not condition_config.get("conditions"):
            raise RevealConditionEvaluationError(
                message="CompositeEvaluator requires 'conditions' list in condition config",
                condition_type="COMPOSITE"
            )
        operator = condition_config.get("operator", "AND")
        conditions = condition_config.get("conditions", [])
        
        evaluators = {
            RevealConditionType.PRICE_THRESHOLD.value: PriceThresholdEvaluator(),
            RevealConditionType.CUMULATIVE_VOLUME.value: CumulativeVolumeEvaluator(),
            RevealConditionType.TIME_DELAY.value: TimeDelayEvaluator(),
            RevealConditionType.SPREAD.value: SpreadEvaluator(),
            RevealConditionType.PRODUCT_RATIO.value: ProductRatioEvaluator(),
        }
        
        results = []
        reasons = []
        
        for cond in conditions:
            cond_type = cond.get("type", "").lower()
            evaluator = evaluators.get(cond_type)
            
            if not evaluator:
                continue
            
            met, reason = evaluator.evaluate(market_data, cond, order_data)
            results.append(met)
            if reason:
                reasons.append(f"{cond_type}: {reason}")
        
        if not results:
            return False, "No conditions to evaluate"
        
        if operator == "AND":
            final_result = all(results)
        else:  # OR
            final_result = any(results)
        
        reason = " | ".join(reasons) if reasons else None
        return final_result, reason


def get_evaluator(condition_type: str) -> ConditionEvaluator:
    """Get appropriate evaluator instance for the specified condition type.
    
    Factory function that instantiates the correct evaluator class based on
    the condition type. Acts as a registry for all available evaluators.
    
    Args:
        condition_type: Type of condition (e.g., 'price', 'spread', 'time_delay').
                       Should match RevealConditionType enum values.
    
    Returns:
        Instantiated evaluator (ConditionEvaluator subclass).
        If condition_type not recognized, returns TimeDelayEvaluator as fallback.
    
    Raises:
        No exceptions - always returns valid evaluator (uses default fallback).
    
    Example:
        >>> evaluator = get_evaluator('price')
        >>> type(evaluator).__name__
        'PriceThresholdEvaluator'
        
        >>> evaluator = get_evaluator('unknown_type')
        >>> type(evaluator).__name__  # Fallback
        'TimeDelayEvaluator'
        
        >>> from core.enums import RevealConditionType
        >>> evaluator = get_evaluator(RevealConditionType.SPREAD.value)
        >>> type(evaluator).__name__
        'SpreadEvaluator'
    """
    evaluators = {
        RevealConditionType.PRICE_THRESHOLD.value: PriceThresholdEvaluator,
        RevealConditionType.CUMULATIVE_VOLUME.value: CumulativeVolumeEvaluator,
        RevealConditionType.TIME_DELAY.value: TimeDelayEvaluator,
        RevealConditionType.SPREAD.value: SpreadEvaluator,
        RevealConditionType.PRODUCT_RATIO.value: ProductRatioEvaluator,
        RevealConditionType.COMPOSITE.value: CompositeEvaluator,
    }
    
    evaluator_class = evaluators.get(condition_type.lower(), TimeDelayEvaluator)
    return evaluator_class()
