
"""Data models for the forum collection service."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from enum import Enum


class ForumSource(Enum):
    """Supported forum/community sources."""
    REDDIT = "reddit"
    HACKER_NEWS = "hacker_news"
    STACK_OVERFLOW = "stack_overflow"
    GITHUB_DISCUSSIONS = "github_discussions"
    PRODUCT_HUNT = "product_hunt"
    INDIE_HACKERS = "indie_hackers"
    DEV_TO = "dev_to"
    MEDIUM = "medium"
    TWITTER = "twitter"
    LOBSTERS = "lobsters"
    V2EX = "v2ex"
    ZHIHU = "zhihu"
    DOUBAN = "douban"


@dataclass
class Author:
    """Author information."""
    username: str
    name: Optional[str] = None
    profile_url: Optional[str] = None
    avatar_url: Optional[str] = None
    reputation: Optional[int] = None
    bio: Optional[str] = None


@dataclass
class Comment:
    """Comment on a post."""
    id: str
    author: Optional[Author]
    content: str
    created_at: datetime
    upvotes: int = 0
    downvotes: int = 0
    parent_id: Optional[str] = None
    replies: List['Comment'] = field(default_factory=list)
    url: Optional[str] = None


@dataclass
class Post:
    """Represents a post from a forum or community."""
    id: str
    title: str
    source: ForumSource
    url: str
    author: Optional[Author] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    created_at: Optional[datetime] = None
    fetched_at: datetime = field(default_factory=datetime.now)
    
    # Engagement metrics
    upvotes: int = 0
    downvotes: int = 0
    comments_count: int = 0
    views: int = 0
    shares: int = 0
    
    # Content metadata
    tags: List[str] = field(default_factory=list)
    category: Optional[str] = None
    language: Optional[str] = None
    
    # Comments and discussions
    comments: List[Comment] = field(default_factory=list)
    
    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def score(self) -> float:
        """Calculate a hotness score based on engagement metrics."""
        # Simple scoring algorithm - can be customized
        # Ensure all values are numbers
        upvotes = int(self.upvotes or 0)
        downvotes = int(self.downvotes or 0)
        comments_count = int(self.comments_count or 0)
        views = int(self.views or 0)
        
        engagement = upvotes - downvotes + (comments_count * 2) + (views * 0.01)
        
        # Time decay factor (posts lose hotness over time)
        if self.created_at:
            # Ensure created_at is timezone-aware
            created_at = self.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            hours_since_post = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
            time_decay = 1 / (1 + hours_since_post ** 0.5)
            return engagement * time_decay
        
        return engagement


@dataclass
class CollectionResult:
    """Result of a collection operation."""
    source: ForumSource
    posts: List[Post]
    success: bool
    error_message: Optional[str] = None
    collected_at: datetime = field(default_factory=datetime.now)
    total_count: int = 0
    filtered_count: int = 0


@dataclass
class CollectionConfig:
    """Configuration for collection."""
    source: ForumSource
    enabled: bool = True
    max_posts: int = 100
    max_comments_per_post: int = 50
    min_score: int = 0
    tags_filter: List[str] = field(default_factory=list)
    keywords_filter: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    time_range_hours: Optional[int] = None  # None means no time limit
    custom_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HotPost:
    """A hot post with additional analysis."""
    post: Post
    rank: int
    trending_score: float
    viral_potential: float  # 0-1 score indicating viral potential
    sentiment: Optional[str] = None  # positive, negative, neutral
    key_topics: List[str] = field(default_factory=list)
