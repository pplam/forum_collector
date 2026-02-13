
"""Configuration module for forum collector."""

from .settings import Settings, CollectorConfig, load_config, save_config, get_default_config

__all__ = [
    'Settings',
    'CollectorConfig',
    'load_config',
    'save_config',
    'get_default_config'
]
