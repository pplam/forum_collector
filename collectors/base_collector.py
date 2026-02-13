
"""Base collector interface for all forum sources."""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import asyncio
import aiohttp
import backoff
import logging
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Post, CollectionResult, CollectionConfig, ForumSource


logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for all forum collectors."""
    
    def __init__(self, config: CollectionConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self._rate_limit_remaining = 0
        self._rate_limit_reset = None
    
    @property
    @abstractmethod
    def source(self) -> ForumSource:
        """Return the forum source type."""
        pass
    
    @property
    @abstractmethod
    def base_url(self) -> str:
        """Return the base URL for the API."""
        pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            headers=self._get_headers(),
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    def _get_headers(self) -> Dict[str, str]:
        """Get default headers for requests."""
        return {
            'User-Agent': 'ForumCollector/1.0 (Educational Research Bot)',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
    
    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=3,
        max_time=60
    )
    async def _make_request(
        self, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        method: str = 'GET'
    ) -> Optional[Dict[str, Any]]:
        """Make an HTTP request with retry logic."""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            async with self.session.request(method, url, params=params) as response:
                self._update_rate_limits(response)
                
                if response.status == 429:
                    # Rate limited - wait and retry
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limited. Waiting {retry_after} seconds.")
                    await asyncio.sleep(retry_after)
                    return await self._make_request(endpoint, params, method)
                
                if response.status == 404:
                    logger.warning(f"Resource not found: {url}")
                    return None
                
                response.raise_for_status()
                return await response.json()
                
        except aiohttp.ClientError as e:
            logger.error(f"Request failed for {url}: {e}")
            raise
    
    def _update_rate_limits(self, response: aiohttp.ClientResponse):
        """Update rate limit tracking from response headers."""
        # Override in subclasses for source-specific rate limiting
        pass
    
    @abstractmethod
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot posts from the forum.
        
        Args:
            limit: Maximum number of posts to collect (overrides config)
            
        Returns:
            CollectionResult with collected posts
        """
        pass
    
    @abstractmethod
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific post.
        
        Args:
            post_id: The unique identifier for the post
            
        Returns:
            Post object with full details including comments
        """
        pass
    
    @abstractmethod
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific post.
        
        Args:
            post_id: The unique identifier for the post
            limit: Maximum number of comments to retrieve
            
        Returns:
            List of comment dictionaries
        """
        pass
    
    async def search_posts(
        self, 
        query: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Search for posts matching a query.
        
        Args:
            query: Search query string
            limit: Maximum number of results
            
        Returns:
            CollectionResult with matching posts
        """
        # Default implementation - override in subclasses
        result = CollectionResult(
            source=self.source,
            posts=[],
            success=False,
            error_message="Search not implemented for this source"
        )
        return result
    
    def _filter_post(self, post: Post) -> bool:
        """Apply filters to determine if post should be included.
        
        Args:
            post: Post to evaluate
            
        Returns:
            True if post passes all filters
        """
        # Check minimum score
        if post.score < self.config.min_score:
            return False
        
        # Check time range
        if self.config.time_range_hours and post.created_at:
            hours_since = (datetime.now() - post.created_at).total_seconds() / 3600
            if hours_since > self.config.time_range_hours:
                return False
        
        # Check required tags (if specified, post must have at least one)
        if self.config.tags_filter:
            if not any(tag in post.tags for tag in self.config.tags_filter):
                return False
        
        # Check required keywords in title or content
        if self.config.keywords_filter:
            text = f"{post.title} {post.content or ''}".lower()
            if not any(kw.lower() in text for kw in self.config.keywords_filter):
                return False
        
        # Check excluded keywords
        if self.config.exclude_keywords:
            text = f"{post.title} {post.content or ''}".lower()
            if any(kw.lower() in text for kw in self.config.exclude_keywords):
                return False
        
        return True
    
    def _apply_filters(self, posts: List[Post]) -> List[Post]:
        """Apply all configured filters to a list of posts.
        
        Args:
            posts: List of posts to filter
            
        Returns:
            Filtered list of posts
        """
        return [post for post in posts if self._filter_post(post)]
