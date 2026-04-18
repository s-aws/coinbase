"""Stealth order condition evaluators for flexible reveal triggers.

Provides evaluators for different condition types that determine when hidden
orders should be revealed to the market.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
from collections import defaultdict


class ConditionEvaluator(ABC):
    """Base class for all reveal condition evaluators."""
    
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
        threshold = condition_config.get("price_threshold", 0)
        direction = condition_config.get("direction", "below")
        hold_duration = condition_config.get("hold_duration_seconds", 0)
        
        current_price = market_data.get("price", 0)
        condition_first_met = order_data.get("condition_first_met_at")
        
        # Check if threshold crossed
        if direction == "below":
            threshold_crossed = current_price < threshold
        else:  # "above"
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
        product_id = condition_config.get("product_id")
        price_level = condition_config.get("price_level", 0)
        volume_threshold = condition_config.get("volume_threshold", 0)
        lookback_seconds = condition_config.get("lookback_seconds", 30)
        
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
        delay = condition_config.get("delay_seconds", 0)
        jitter = condition_config.get("jitter_seconds", 0)
        
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
        max_spread = condition_config.get("max_spread", 999999)
        hold_duration = condition_config.get("hold_duration_seconds", 0)
        
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
        price_a = market_data.get("price_a", 0)
        price_b = market_data.get("price_b", 0)
        threshold = condition_config.get("ratio_threshold", 0)
        direction = condition_config.get("direction", "below")
        
        if price_a <= 0 or price_b <= 0:
            return False, "Price data for one/both products missing"
        
        ratio = price_a / price_b
        
        if direction == "below":
            threshold_met = ratio < threshold
        else:  # "above"
            threshold_met = ratio > threshold
        
        if threshold_met:
            reason = f"Ratio {ratio:.6f} {direction} threshold {threshold:.6f}"
            return True, reason
        
        return False, f"Ratio {ratio:.6f} not {direction} {threshold:.6f}"


class CompositeEvaluator(ConditionEvaluator):
    """Evaluates multiple conditions with AND/OR logic."""
    
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
        operator = condition_config.get("operator", "AND")
        conditions = condition_config.get("conditions", [])
        
        evaluators = {
            "price": PriceThresholdEvaluator(),
            "cumulative_volume": CumulativeVolumeEvaluator(),
            "time_delay": TimeDelayEvaluator(),
            "spread": SpreadEvaluator(),
            "product_ratio": ProductRatioEvaluator(),
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
    """Factory function to get appropriate evaluator for condition type."""
    evaluators = {
        "price": PriceThresholdEvaluator,
        "cumulative_volume": CumulativeVolumeEvaluator,
        "time_delay": TimeDelayEvaluator,
        "spread": SpreadEvaluator,
        "product_ratio": ProductRatioEvaluator,
        "composite": CompositeEvaluator,
    }
    
    evaluator_class = evaluators.get(condition_type.lower(), TimeDelayEvaluator)
    return evaluator_class()
