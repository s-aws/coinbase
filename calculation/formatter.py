"""Calculation utilities - Formatting and quantization functions."""

from typing import Union
from core.enums import RoundingDirection


def safe_float(value: Union[str, int, float, None], default: float = 0.0) -> float:
    """Safely convert a value to float, returning default on error.
    
    Handles None, empty strings, and invalid types gracefully.
    
    Args:
        value: The value to convert (str, int, float, None, etc.)
        default: The default value to return if conversion fails (default: 0.0)
    
    Returns:
        The converted float value, or default if conversion fails
    
    Examples:
        >>> safe_float('123.45')
        123.45
        >>> safe_float(None)
        0.0
        >>> safe_float('invalid', 10.0)
        10.0
    """
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def format_based_on_reference(value_to_format: float, reference_float: str) -> str:
    """Format a float to match the number of decimal places of a reference float.
    
    Extracts the number of decimal places from a reference string and formats
    the input value to match. Useful for matching price/size precision to
    exchange-specific increments.
    
    Args:
        value_to_format: The numeric value to format (float or convertible)
        reference_float: A reference string (e.g., '0.01', '1') representing target precision
    
    Returns:
        A formatted string representation with matching decimal places
    
    Examples:
        >>> format_based_on_reference(123.456, '0.01')
        '123.46'
        >>> format_based_on_reference(123.456, '0.001')
        '123.456'
        >>> format_based_on_reference(123.456, '1')
        '123'
    """
    decimal_places = len(str(reference_float).rsplit('.', maxsplit=1)[-1]) if '.' in str(reference_float) else 0
    return f"{value_to_format:.{decimal_places}f}"


def quantize_to_increment(
    value: float,
    increment: str,
    direction: str = "nearest"
) -> float:
    """Quantize a value to the nearest valid increment.
    
    Rounds, floors, or ceils a numeric value to match a specified price/size increment.
    Essential for ensuring orders comply with exchange minimum price/size requirements.
    
    Args:
        value: The value to quantize (e.g., a price or size)
        increment: The increment step as a string (e.g., "0.01" for cent precision)
        direction: Rounding direction:
                   - "down": floor to lower increment (conservative for price)
                   - "up": ceil to higher increment (conservative for sell price)
                   - "nearest": round to nearest increment (default)
    
    Returns:
        The quantized value as a float
    
    Raises:
        ValueError: If increment <= 0 or direction not in {"up", "down", "nearest"}
    
    Examples:
        >>> quantize_to_increment(100.126, "0.01")
        100.13
        >>> quantize_to_increment(100.124, "0.01", direction="down")
        100.12
        >>> quantize_to_increment(100.126, "0.01", direction="up")
        100.13
    """
    increment_float = float(increment)
    if increment_float <= 0:
        raise ValueError("increment must be greater than 0")
    
    if direction not in {RoundingDirection.UP.value, RoundingDirection.DOWN.value, RoundingDirection.NEAREST.value}:
        raise ValueError(f"Unsupported direction: {direction}")
    
    remainder = value % increment_float
    
    if remainder == 0:
        return value
    
    if direction == RoundingDirection.DOWN.value:
        return value - remainder
    
    if direction == RoundingDirection.UP.value:
        return value + (increment_float - remainder)
    
    # nearest
    down_value = value - remainder
    up_value = value + (increment_float - remainder)
    return down_value if remainder < (increment_float / 2) else up_value
