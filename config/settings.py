
"""Configuration settings for forum collector."""

import os
import json
import yaml
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import CollectionConfig, ForumSource


@dataclass
class CollectorConfig:
    """Configuration for a specific collector."""
    source: ForumSource
    enabled: bool = True
    max_posts: int = 100
    max_comments_per_post: int = 50
    min_score: int = 0
    tags_filter: List[str] = field(default_factory=list)
    keywords_filter: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    time_range_hours: Optional[int] = None
    custom_params: Dict[str, Any] = field(default_factory=dict)
    
    # Authentication
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    access_token: Optional[str] = None
    cookie: Optional[str] = None
    
    def to_collection_config(self) -> CollectionConfig:
        """Convert to CollectionConfig model."""
        return CollectionConfig(
            source=self.source,
            enabled=self.enabled,
            max_posts=self.max_posts,
            max_comments_per_post=self.max_comments_per_post,
            min_score=self.min_score,
            tags_filter=self.tags_filter,
            keywords_filter=self.keywords_filter,
            exclude_keywords=self.exclude_keywords,
            time_range_hours=self.time_range_hours,
            custom_params=self.custom_params
        )


@dataclass
class Settings:
    """Main settings for the forum collector application."""
    
    # General settings
    app_name: str = "Forum Collector"
    debug: bool = False
    log_level: str = "INFO"
    
    # Collection settings
    default_max_posts: int = 100
    default_max_comments: int = 50
    collection_interval_hours: int = 1
    
    # Storage settings
    storage_type: str = "json"  # json, sqlite, mongodb
    storage_path: str = "./data"
    database_url: Optional[str] = None
    
    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    api_enabled: bool = True
    
    # Collector configurations
    collectors: Dict[str, CollectorConfig] = field(default_factory=dict)
    
    # Proxy settings
    proxy_enabled: bool = False
    proxy_url: Optional[str] = None
    
    # Rate limiting
    rate_limit_enabled: bool = True
    requests_per_second: int = 2
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Settings':
        """Create Settings from a dictionary."""
        collectors = {}
        
        if 'collectors' in data:
            for name, config in data['collectors'].items():
                if isinstance(config, dict):
                    # Convert source string to ForumSource enum
                    if 'source' in config and isinstance(config['source'], str):
                        config['source'] = ForumSource(config['source'])
                    collectors[name] = CollectorConfig(**config)
        
        # Remove collectors from data before creating Settings
        data_copy = {k: v for k, v in data.items() if k != 'collectors'}
        data_copy['collectors'] = collectors
        
        return cls(**data_copy)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert Settings to a dictionary."""
        result = {
            'app_name': self.app_name,
            'debug': self.debug,
            'log_level': self.log_level,
            'default_max_posts': self.default_max_posts,
            'default_max_comments': self.default_max_comments,
            'collection_interval_hours': self.collection_interval_hours,
            'storage_type': self.storage_type,
            'storage_path': self.storage_path,
            'database_url': self.database_url,
            'api_host': self.api_host,
            'api_port': self.api_port,
            'api_enabled': self.api_enabled,
            'proxy_enabled': self.proxy_enabled,
            'proxy_url': self.proxy_url,
            'rate_limit_enabled': self.rate_limit_enabled,
            'requests_per_second': self.requests_per_second,
            'collectors': {}
        }
        
        for name, config in self.collectors.items():
            result['collectors'][name] = {
                'source': config.source.value,
                'enabled': config.enabled,
                'max_posts': config.max_posts,
                'max_comments_per_post': config.max_comments_per_post,
                'min_score': config.min_score,
                'tags_filter': config.tags_filter,
                'keywords_filter': config.keywords_filter,
                'exclude_keywords': config.exclude_keywords,
                'time_range_hours': config.time_range_hours,
                'custom_params': config.custom_params,
                'api_key': config.api_key,
                'api_secret': config.api_secret,
                'access_token': config.access_token,
                'cookie': config.cookie
            }
        
        return result


def get_default_config() -> Settings:
    """Get default configuration."""
    return Settings(
        collectors={
            'hacker_news': CollectorConfig(
                source=ForumSource.HACKER_NEWS,
                enabled=True,
                max_posts=50,
                custom_params={
                    'include_ask_hn': True,
                    'include_show_hn': True,
                    'include_jobs': False
                }
            ),
            'reddit': CollectorConfig(
                source=ForumSource.REDDIT,
                enabled=True,
                max_posts=50,
                custom_params={
                    'subreddits': ['programming', 'technology', 'python', 'javascript']
                }
            ),
            'v2ex': CollectorConfig(
                source=ForumSource.V2EX,
                enabled=True,
                max_posts=50,
                custom_params={
                    'nodes': ['python', 'programmer', 'share']
                }
            ),
            'zhihu': CollectorConfig(
                source=ForumSource.ZHIHU,
                enabled=True,
                max_posts=50,
                custom_params={
                    'topics': []
                }
            ),
            'douban': CollectorConfig(
                source=ForumSource.DOUBAN,
                enabled=True,
                max_posts=50,
                custom_params={
                    'groups': ['gossip', 'tech', 'programmer', 'python', 'ai']
                }
            ),
            'lobsters': CollectorConfig(
                source=ForumSource.LOBSTERS,
                enabled=True,
                max_posts=30
            ),
            'dev_to': CollectorConfig(
                source=ForumSource.DEV_TO,
                enabled=True,
                max_posts=50
            ),
            'product_hunt': CollectorConfig(
                source=ForumSource.PRODUCT_HUNT,
                enabled=True,
                max_posts=30
            ),
            'stack_overflow': CollectorConfig(
                source=ForumSource.STACK_OVERFLOW,
                enabled=True,
                max_posts=50,
                custom_params={
                    'tags': ['python', 'javascript', 'java', 'go']
                }
            ),
            'github': CollectorConfig(
                source=ForumSource.GITHUB_DISCUSSIONS,
                enabled=True,
                max_posts=30,
                custom_params={
                    'repositories': ['microsoft/vscode', 'facebook/react']
                }
            )
        }
    )


def load_config(config_path: Optional[str] = None) -> Settings:
    """Load configuration from file.
    
    Args:
        config_path: Path to configuration file. If None, looks for default locations.
        
    Returns:
        Settings object
    """
    # Default config file locations
    default_paths = [
        './config.yaml',
        './config.yml',
        './config.json',
        './forum_collector.yaml',
        './forum_collector.json',
        os.path.expanduser('~/.forum_collector/config.yaml'),
        os.path.expanduser('~/.forum_collector/config.json'),
    ]
    
    # Determine which config file to use
    if config_path:
        paths_to_try = [config_path]
    else:
        paths_to_try = default_paths
    
    for path in paths_to_try:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    if path.endswith('.yaml') or path.endswith('.yml'):
                        data = yaml.safe_load(f)
                    else:
                        data = json.load(f)
                
                print(f"Loaded configuration from {path}")
                return Settings.from_dict(data)
                
            except Exception as e:
                print(f"Error loading config from {path}: {e}")
                continue
    
    # Return default config if no file found
    print("No configuration file found, using defaults")
    return get_default_config()


def save_config(settings: Settings, config_path: str) -> bool:
    """Save configuration to file.
    
    Args:
        settings: Settings object to save
        config_path: Path to save configuration file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        data = settings.to_dict()
        
        with open(config_path, 'w', encoding='utf-8') as f:
            if config_path.endswith('.yaml') or config_path.endswith('.yml'):
                yaml.dump(data, f, default_flow_style=False)
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"Configuration saved to {config_path}")
        return True
        
    except Exception as e:
        print(f"Error saving config to {config_path}: {e}")
        return False
