
"""Logging configuration for forum collector."""

import os
import sys
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: str = "./logs",
    format_string: Optional[str] = None
) -> logging.Logger:
    """Set up logging configuration.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file name
        log_dir: Directory for log files
        format_string: Custom format string
        
    Returns:
        Configured logger
    """
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Default format
    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    formatter = logging.Formatter(format_string)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        file_path = log_path / log_file
        file_handler = logging.FileHandler(file_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Reduce noise from third-party libraries
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class ColoredFormatter(logging.Formatter):
    """Colored log formatter for console output."""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # Add color to level name
        if record.levelname in self.COLORS:
            record.levelname = (
                f"{self.COLORS[record.levelname]}{record.levelname}{self.RESET}"
            )
        
        return super().format(record)


def setup_colored_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: str = "./logs"
) -> logging.Logger:
    """Set up colored logging for console output.
    
    Args:
        level: Log level
        log_file: Optional log file name
        log_dir: Directory for log files
        
    Returns:
        Configured logger
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    root_logger.handlers.clear()
    
    # Colored console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ColoredFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    root_logger.addHandler(console_handler)
    
    # File handler (without colors)
    if log_file:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        file_path = log_path / log_file
        file_handler = logging.FileHandler(file_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        root_logger.addHandler(file_handler)
    
    return root_logger


class LogContext:
    """Context manager for temporary logging level changes."""
    
    def __init__(self, logger: logging.Logger, level: str):
        """Initialize context manager.
        
        Args:
            logger: Logger to modify
            level: Temporary log level
        """
        self.logger = logger
        self.temporary_level = getattr(logging, level.upper())
        self.original_level = logger.level
    
    def __enter__(self):
        self.logger.setLevel(self.temporary_level)
        return self.logger
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.setLevel(self.original_level)
        return False


def log_execution_time(logger: logging.Logger, message: str = "Execution time"):
    """Decorator to log function execution time.
    
    Args:
        logger: Logger to use
        message: Message prefix
        
    Returns:
        Decorator function
    """
    import functools
    import time
    
    def decorator(func):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"{message}: {func.__name__} took {elapsed:.2f}s")
            return result
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            result = await func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"{message}: {func.__name__} took {elapsed:.2f}s")
            return result
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
