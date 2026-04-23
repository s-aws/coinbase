"""
Lot-Based Profit Configuration.

Configuration settings for the lot tracking and profit-aware execution system.
"""

# ============================================================================
# LOT TRACKING AND PROFIT CONFIGURATION
# ============================================================================

# Default profit margin for new lots (percentage)
# Example: 0.5 = 0.5% profit target
DEFAULT_PROFIT_MARGIN_PCT = 0.5

# Lot selection strategy when exiting positions
# Options: 'FIFO' (default), 'LIFO', 'BEST_PROFIT'
LOT_EXIT_STRATEGY = 'FIFO'

# Conditional execution mode
# Options: 'ADVISORY' (log warnings but allow), 'ENFORCING' (block unprofitable)
CONDITIONAL_EXECUTION_MODE = 'ADVISORY'

# Enable lot-based profit awareness
ENABLE_LOT_TRACKING = True

# Enable conditional execution wrapper
ENABLE_CONDITIONAL_EXECUTION = True

# Maximum conditional orders in memory
MAX_CONDITIONAL_ORDERS = 1000

# Conditional order evaluation frequency (milliseconds)
CONDITIONAL_ORDER_EVALUATION_INTERVAL_MS = 100

# Fee estimation for new lots (if actual fees unavailable)
# This is used when creating hypothetical lots before actual fills
ESTIMATED_MAKER_FEE_PCT = 0.04  # 0.04% typical Coinbase maker fee
ESTIMATED_TAKER_FEE_PCT = 0.06  # 0.06% typical Coinbase taker fee

# ============================================================================
# PROFIT TARGET CUSTOMIZATION
# ============================================================================

# Product-specific profit targets (override DEFAULT_PROFIT_MARGIN_PCT)
PRODUCT_PROFIT_TARGETS = {
    'BTC-USDC': 0.5,      # 0.5% for Bitcoin
    'ETH-USDC': 0.75,     # 0.75% for Ethereum
    'SOL-USDC': 1.0,      # 1.0% for Solana
}

# Strategy-specific profit targets
# Example: Different targets for day trading vs swing trading
STRATEGY_PROFIT_TARGETS = {
    'scalp': 0.1,         # 0.1% for scalping
    'day_trade': 0.5,     # 0.5% for day trading
    'swing_trade': 2.0,   # 2.0% for swing trading
}

# ============================================================================
# FILL LEDGER CONFIGURATION
# ============================================================================

# Automatically append fills to ledger (requires post-fill hook in order engine)
AUTO_LEDGER_FILLS = True

# Retention policy for fills (days, None = keep forever)
FILL_LEDGER_RETENTION_DAYS = None

# ============================================================================
# FUNCTIONS FOR PROFIT CONFIGURATION
# ============================================================================

def get_profit_target_for_product(product_id: str) -> float:
    """Get configured profit target for a product.
    
    Args:
        product_id: Product ID (e.g., 'BTC-USDC')
    
    Returns:
        Profit margin as percentage
    """
    return PRODUCT_PROFIT_TARGETS.get(product_id, DEFAULT_PROFIT_MARGIN_PCT)


def get_profit_target_for_strategy(strategy_name: str) -> float:
    """Get configured profit target for a strategy.
    
    Args:
        strategy_name: Strategy name (e.g., 'scalp', 'day_trade')
    
    Returns:
        Profit margin as percentage
    """
    return STRATEGY_PROFIT_TARGETS.get(strategy_name.lower(), DEFAULT_PROFIT_MARGIN_PCT)


def configure_custom_profit_target(product_id: str, profit_pct: float) -> None:
    """Configure custom profit target for a product.
    
    Args:
        product_id: Product to configure
        profit_pct: Profit target as percentage
    """
    PRODUCT_PROFIT_TARGETS[product_id] = profit_pct
