"""Custom logging service that wraps the dashboard logging system.

Provides a logger interface compatible with Python's standard logging module
so it can be easily swapped out in the future.

Usage:
    >>> from logging_service import get_logger
    >>> logger = get_logger("MyModule")
    >>> logger.info("Order created", extra={"order_id": "123"})
    >>> logger.error("Connection failed", exc_info=True)
    >>> logger.debug("Debug info", extra={"value": 42})
"""

from typing import Dict, Any, Optional
from functools import partial


# Log level constants
LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

# Default logging level (set to INFO to hide DEBUG messages by default)
_current_log_level = LOG_LEVELS["INFO"]

# This will be set by main.py to point to the dashboard's add_log_entry function
_add_log_entry_backend = None


def set_log_level(level: str):
    """Set the minimum logging level to display.
    
    Args:
        level: One of "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    """
    global _current_log_level
    if level in LOG_LEVELS:
        _current_log_level = LOG_LEVELS[level]
        print(f"Logging level set to {level}")
    else:
        raise ValueError(f"Invalid logging level: {level}. Must be one of {list(LOG_LEVELS.keys())}")


def get_log_level() -> str:
    """Get the current logging level."""
    for level_name, level_value in LOG_LEVELS.items():
        if level_value == _current_log_level:
            return level_name
    return "INFO"


def set_backend(add_log_entry_func):
    """Set the backend logging function (called from main.py).
    
    Args:
        add_log_entry_func: Function with signature (level: str, message: str, context: Dict = None)
    """
    global _add_log_entry_backend
    _add_log_entry_backend = add_log_entry_func


class CustomLogger:
    """Custom logger that mimics Python's logging.Logger interface.
    
    Provides the same method signatures as standard logging.Logger:
    - info(msg, *args, **kwargs)
    - error(msg, *args, **kwargs)
    - warning(msg, *args, **kwargs)
    - debug(msg, *args, **kwargs)
    
    Can be swapped with standard logging.Logger without code changes.
    """
    
    def __init__(self, name: str):
        """Initialize logger with a name.
        
        Args:
            name: Logger name (e.g., 'PostgresDB', 'OrderDB')
        """
        self.name = name
    
    def _format_message(self, msg: str, *args, extra: Optional[Dict[str, Any]] = None) -> tuple:
        """Format message with args and extract extra context.
        
        Args:
            msg: Message string with optional %s placeholders
            args: Arguments to substitute into message
            extra: Extra context dict (from kwargs)
        
        Returns:
            Tuple of (formatted_message, context_dict)
        """
        # Format message with positional args if provided
        if args:
            try:
                formatted_msg = msg % args
            except (TypeError, ValueError):
                # If formatting fails, just concatenate
                formatted_msg = f"{msg} {args}"
        else:
            formatted_msg = msg
        
        # Extract context from extra kwarg
        context = {}
        if extra and isinstance(extra, dict):
            context = extra.copy()
        
        return formatted_msg, context
    
    def _should_log(self, level: str) -> bool:
        """Check if a message at this level should be logged.
        
        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            
        Returns:
            True if message should be printed/logged
        """
        return LOG_LEVELS.get(level, 20) >= _current_log_level
    
    def info(self, msg: str, *args, **kwargs) -> None:
        """Log an info message.
        
        Args:
            msg: Message string
            args: Arguments to format into message
            extra: Dict with additional context
        """
        if not self._should_log("INFO"):
            return
            
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
        # Print to console
        print(f"[INFO] {self.name}: {formatted_msg}")
        # Also send to backend if available
        if _add_log_entry_backend:
            _add_log_entry_backend("INFO", formatted_msg, context)
    
    def error(self, msg: str, *args, **kwargs) -> None:
        """Log an error message.
        
        Args:
            msg: Message string
            args: Arguments to format into message
            extra: Dict with additional context
            exc_info: If True, include exception information
        """
        if not self._should_log("ERROR"):
            return
            
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
        if kwargs.get('exc_info'):
            import traceback
            context['traceback'] = traceback.format_exc()
        # Print to console
        print(f"[ERROR] {self.name}: {formatted_msg}")
        # Also send to backend if available
        if _add_log_entry_backend:
            _add_log_entry_backend("ERROR", formatted_msg, context)
    
    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log a warning message.
        
        Args:
            msg: Message string
            args: Arguments to format into message
            extra: Dict with additional context
        """
        if not self._should_log("WARNING"):
            return
            
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
        # Print to console
        print(f"[WARNING] {self.name}: {formatted_msg}")
        # Also send to backend if available
        if _add_log_entry_backend:
            _add_log_entry_backend("WARNING", formatted_msg, context)
    
    def warn(self, msg: str, *args, **kwargs) -> None:
        """Alias for warning() for compatibility."""
        self.warning(msg, *args, **kwargs)
    
    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log a debug message.
        
        Args:
            msg: Message string
            args: Arguments to format into message
            extra: Dict with additional context
        """
        if not self._should_log("DEBUG"):
            return
            
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
        # Print to console
        print(f"[DEBUG] {self.name}: {formatted_msg}")
        # Also send to backend if available
        if _add_log_entry_backend:
            _add_log_entry_backend("DEBUG", formatted_msg, context)
    
    def critical(self, msg: str, *args, **kwargs) -> None:
        """Log a critical message.
        
        Args:
            msg: Message string
            args: Arguments to format into message
            extra: Dict with additional context
        """
        if not self._should_log("CRITICAL"):
            return
            
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
        # Print to console
        print(f"[CRITICAL] {self.name}: {formatted_msg}")
        # Also send to backend if available
        if _add_log_entry_backend:
            _add_log_entry_backend("CRITICAL", formatted_msg, context)


def get_logger(name: str) -> CustomLogger:
    """Get a logger instance with the given name.
    
    Mimics logging.getLogger() interface.
    
    Args:
        name: Logger name (e.g., 'PostgresDB', 'OrderDB')
    
    Returns:
        CustomLogger instance
    
    Example:
        >>> from logging_service import get_logger
        >>> logger = get_logger("MyModule")
        >>> logger.info("Starting module")
        >>> logger.error("Something failed", extra={"order_id": "123"})
    """
    return CustomLogger(name)
