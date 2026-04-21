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


# This will be set by main.py to point to the dashboard's add_log_entry function
_add_log_entry_backend = None


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
    
    def info(self, msg: str, *args, **kwargs) -> None:
        """Log an info message.
        
        Args:
            msg: Message string
            args: Arguments to format into message
            extra: Dict with additional context
        """
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
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
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
        if kwargs.get('exc_info'):
            import traceback
            context['traceback'] = traceback.format_exc()
        if _add_log_entry_backend:
            _add_log_entry_backend("ERROR", formatted_msg, context)
    
    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log a warning message.
        
        Args:
            msg: Message string
            args: Arguments to format into message
            extra: Dict with additional context
        """
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
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
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
        if _add_log_entry_backend:
            _add_log_entry_backend("DEBUG", formatted_msg, context)
    
    def critical(self, msg: str, *args, **kwargs) -> None:
        """Log a critical message.
        
        Args:
            msg: Message string
            args: Arguments to format into message
            extra: Dict with additional context
        """
        formatted_msg, context = self._format_message(msg, *args, extra=kwargs.get('extra'))
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
