
"""Forum collectors package."""

from .base_collector import BaseCollector
from .reddit_collector import RedditCollector
from .hackernews_collector import HackerNewsCollector
from .stackoverflow_collector import StackOverflowCollector
from .github_collector import GitHubDiscussionsCollector
from .devto_collector import DevToCollector
from .producthunt_collector import ProductHuntCollector
from .v2ex_collector import V2EXCollector
from .zhihu_collector import ZhihuCollector
from .lobsters_collector import LobstersCollector
from .douban_collector import DoubanCollector

__all__ = [
    'BaseCollector',
    'RedditCollector',
    'HackerNewsCollector',
    'StackOverflowCollector',
    'GitHubDiscussionsCollector',
    'DevToCollector',
    'ProductHuntCollector',
    'V2EXCollector',
    'ZhihuCollector',
    'LobstersCollector',
    'DoubanCollector'
]
