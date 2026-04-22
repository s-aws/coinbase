"""Logging service using Python's industry-standard logging module.

This module wraps Python's built-in logging to provide:
- Industry-standard logging using Python's logging module
- Dashboard integration via custom handler
- Structured logging support via extra context
- Backward compatible API with the previous custom logger

The standard logging module is used for:
- Reliable log level filtering
- Multiple handler support
- Standard formatter patterns
- Exception tracking and traceback capture
- Thread-safe logging

Dashboard Backend:
- Logs are forwarded to the dashboard via set_backend()
- Custom handler captures all logs for real-time display
- Supports structured logging with context dictionaries

Usage:
    >>> from logging_service import get_logger
    >>> logger = get_logger("MyModule")
    >>> logger.info("Order created", extra={"order_id": "123"})
    >>> logger.error("Connection failed", exc_info=True)
    >>> logger.debug("Debug info", extra={"value": 42})
"""

import logging
import json
from typing import Dict, Any, Optional, Callable


# Console formatter with timestamp and level
_FORMATTER = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Global reference to dashboard backend function
_dashboard_backend: Optional[Callable] = None
_dashboard_handler: Optional['DashboardHandler'] = None


class DashboardHandler(logging.Handler):
    """Custom logging handler that forwards logs to the dashboard.
    
    This handler captures all logging records and sends them to the dashboard
    backend for real-time display and storage.
    """
    
    def __init__(self, backend_func: Callable):
        """Initialize the dashboard handler.
        
        Args:
            backend_func: Function with signature (level: str, message: str, context: Dict = None)
        """
        super().__init__()
        self.backend_func = backend_func
    
    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the dashboard.
        
        Args:
            record: The logging record to emit
        """
        try:
            # Extract level name
            level = record.levelname
            
            # Format the message
            message = record.getMessage()
            
            # Extract context from record
            context = {}
            
            # Include exception info if present
            if record.exc_info:
                import traceback
                context['traceback'] = ''.join(traceback.format_exception(*record.exc_info))
            
            # Include any extra fields from the record that are JSON-serializable
            # Standard logging fields to exclude
            standard_fields = {
                'name', 'msg', 'args', 'created', 'filename', 'funcName',
                'levelname', 'levelno', 'lineno', 'module', 'msecs', 'message',
                'pathname', 'process', 'processName', 'relativeCreated', 'thread',
                'threadName', 'exc_info', 'exc_text', 'stack_info', 'taskName'
            }
            
            for key, value in record.__dict__.items():
                if key not in standard_fields and not key.startswith('_'):
                    # Only include fields that are JSON-serializable
                    # This prevents non-serializable objects like WebSocketServerProtocol
                    # from being included in the dashboard logs
                    if self._is_serializable(value):
                        context[key] = value
            
            # Call backend
            self.backend_func(level, message, context)
            
        except Exception:
            # If dashboard logging fails, don't let it crash the application
            self.handleError(record)
    
    @staticmethod
    def _is_serializable(value: Any) -> bool:
        """Check if a value is JSON-serializable or convertible.
        
        This checks if a value can be serialized to JSON directly, or if it's
        a known type that can be converted by CustomJSONEncoder (Decimal, datetime).
        
        Args:
            value: The value to check
            
        Returns:
            True if the value can be serialized directly or converted via CustomJSONEncoder
        """
        # Import here to avoid circular imports
        from decimal import Decimal
        from datetime import (datetime, date, time)
        
        # Check for standard JSON-serializable types first
        if value is None or isinstance(value, (bool, int, float, str)):
            return True
        
        if isinstance(value, (list, tuple)):
            # Recursively check list/tuple contents
            return all(DashboardHandler._is_serializable(item) for item in value)
        
        if isinstance(value, dict):
            # Recursively check dict keys and values
            return all(
                isinstance(k, str) and DashboardHandler._is_serializable(v)
                for k, v in value.items()
            )
        
        # Check for types that CustomJSONEncoder can handle
        if isinstance(value, (Decimal, datetime, date, time)):
            return True
        
        # For anything else, try to serialize it
        try:
            json.dumps(value)
            return True
        except (TypeError, ValueError):
            return False


def set_backend(add_log_entry_func: Callable) -> None:
    """Set the backend logging function (called from main.py).
    
    This function sets up the dashboard handler to forward logs to the dashboard.
    
    Args:
        add_log_entry_func: Function with signature (level: str, message: str, context: Dict = None)
    
    Example:
        >>> from logging_service import set_backend
        >>> def dashboard_logger(level, message, context):
        ...     # Store in database or send to dashboard
        ...     print(f"[{level}] {message}")
        >>> set_backend(dashboard_logger)
    """
    global _dashboard_backend, _dashboard_handler
    
    _dashboard_backend = add_log_entry_func
    
    # Create and configure the dashboard handler if we have a backend
    if add_log_entry_func:
        _dashboard_handler = DashboardHandler(add_log_entry_func)
        # Use a simple formatter for dashboard handler
        dashboard_formatter = logging.Formatter('%(message)s')
        _dashboard_handler.setFormatter(dashboard_formatter)
        
        # Add handler to the root logger
        root_logger = logging.getLogger()
        
        # Remove any existing dashboard handlers to avoid duplicates
        for handler in root_logger.handlers[:]:
            if isinstance(handler, DashboardHandler):
                root_logger.removeHandler(handler)
        
        # Add the new dashboard handler
        root_logger.addHandler(_dashboard_handler)


def set_log_level(level: str) -> None:
    """Set the minimum logging level to display.
    
    Args:
        level: One of "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    
    Raises:
        ValueError: If level is not a valid log level
    
    Example:
        >>> from logging_service import set_log_level
        >>> set_log_level("DEBUG")
    """
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    
    if level.upper() not in valid_levels:
        raise ValueError(
            f"Invalid logging level: {level}. Must be one of {valid_levels}"
        )
    
    # Set level on root logger and all configured loggers
    logging.getLogger().setLevel(level.upper())
    print(f"Logging level set to {level.upper()}")


def get_log_level() -> str:
    """Get the current logging level.
    
    Returns:
        The current logging level as a string (e.g., "INFO", "DEBUG")
    
    Example:
        >>> from logging_service import get_log_level
        >>> level = get_log_level()
        >>> print(f"Current level: {level}")
    """
    return logging.getLevelName(logging.getLogger().level)



def get_logger(name: str) -> logging.Logger:
    """Get a logger instance using Python's standard logging module.
    
    This function returns a standard Python logger configured for your application.
    It uses the industry-standard logging module and supports:
    - Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - Structured logging via the 'extra' parameter
    - Exception tracking with exc_info=True
    - Dashboard integration via set_backend()
    
    Args:
        name: Logger name (e.g., 'PostgresDB', 'OrderDB')
    
    Returns:
        logging.Logger instance (standard Python logger)
    
    Example:
        >>> from logging_service import get_logger
        >>> logger = get_logger("MyModule")
        >>> logger.info("Starting module")
        >>> logger.error("Something failed", extra={"order_id": "123"})
        >>> logger.debug("Debug value: %s", value)
        >>> logger.error("Exception occurred", exc_info=True)
    
    Notes:
        - This returns the standard logging.Logger class
        - No code changes needed if you switch between this and standard logging
        - The returned logger has console output plus dashboard integration
        - Use set_backend() in main.py to enable dashboard logging
    """
    # Configure root logger if not already done
    root_logger = logging.getLogger()
    
    # Set a default level if not already set
    if root_logger.level == logging.NOTSET:
        root_logger.setLevel(logging.INFO)
    
    # Add a console handler if one doesn't exist
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, DashboardHandler) 
               for h in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(_FORMATTER)
        root_logger.addHandler(console_handler)
    
    # Return a logger with the given name
    return logging.getLogger(name)
