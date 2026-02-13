
"""Storage module for forum collector."""

from .base_storage import BaseStorage
from .json_storage import JSONStorage
from .sqlite_storage import SQLiteStorage
from .storage_manager import StorageManager

__all__ = [
    'BaseStorage',
    'JSONStorage',
    'SQLiteStorage',
    'StorageManager'
]
