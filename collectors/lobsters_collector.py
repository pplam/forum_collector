
"""Lobsters collector for gathering hot posts from Lobsters community."""

import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Post, Comment, Author, CollectionResult, CollectionConfig, ForumSource
from collectors.base_collector import BaseCollector


logger = logging.getLogger(__name__)


class LobstersCollector(BaseCollector):
    """Collector for Lobsters posts and discussions."""
    
    BASE_URL = "https://lobste.rs"
    
    def __init__(self, config: CollectionConfig, api_key: Optional[str] = None):
        super().__init__(config)
        self.api_key = api_key
        self._tags = config.custom_params.get('tags', [])
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.LOBSTERS
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        if self.api_key:
            headers['Authorization'] = f"Bearer {self.api_key}"
        return headers
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot stories from Lobsters."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # Get hottest stories
            endpoint = "/hottest.json"
            params = {}
            
            if self._tags:
                params['tag'] = ','.join(self._tags)
            
            data = await self._make_request(endpoint, params)
            
            if not data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No data returned from API"
                )
            
            for item in data[:limit]:
                post = self._parse_story(item)
                if post:
                    all_posts.append(post)
            
            # Apply filters
            filtered_posts = self._apply_filters(all_posts)
            
            return CollectionResult(
                source=self.source,
                posts=filtered_posts[:limit],
                success=True,
                total_count=len(all_posts),
                filtered_count=len(filtered_posts)
            )
            
        except Exception as e:
            logger.error(f"Error collecting Lobsters posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    def _parse_story(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Lobsters story data into Post object."""
        try:
            author = None
            submitter_user = data.get('submitter_user')
            if submitter_user:
                # submitter_user can be a string (username) or a dict with user info
                if isinstance(submitter_user, str):
                    username = submitter_user
                    avatar_url = None
                    bio = None
                else:
                    username = submitter_user.get('username', 'Unknown')
                    avatar_url = submitter_user.get('avatar_url')
                    bio = submitter_user.get('about')
                
                author = Author(
                    username=username,
                    profile_url=f"https://lobste.rs/u/{username}",
                    avatar_url=avatar_url,
                    bio=bio
                )
            
            created_at = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00')) if data.get('created_at') else None
            
            # Handle tags - can be list of strings or list of dicts
            tags = []
            raw_tags = data.get('tags', [])
            if raw_tags:
                # Check if tags are strings or dicts
                if isinstance(raw_tags[0], str):
                    tags = raw_tags  # Already strings
                else:
                    tags = [tag.get('tag', '') for tag in raw_tags]
            
            # Extract category (first tag)
            category = None
            if raw_tags:
                if isinstance(raw_tags[0], str):
                    category = raw_tags[0] if raw_tags else None
                else:
                    category = raw_tags[0].get('tag') if raw_tags else None
            
            # Determine URL
            url = data.get('url')
            if not url:
                url = f"https://lobste.rs/s/{data.get('short_id')}"
            
            post = Post(
                id=data.get('short_id', ''),
                title=data.get('title', ''),
                source=self.source,
                url=url,
                author=author,
                content=data.get('description'),
                created_at=created_at,
                upvotes=data.get('score', 0),
                comments_count=data.get('comment_count', 0),
                tags=tags,
                category=category,
                metadata={
                    'short_id': data.get('short_id'),
                    'short_id_url': data.get('short_id_url'),
                    'is_story': data.get('is_story', True),
                    'is_expired': data.get('is_expired', False),
                    'is_moderated': data.get('is_moderated', False),
                    'is_own': data.get('is_own', False)
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Lobsters story: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific story."""
        endpoint = f"/s/{post_id}.json"
        
        data = await self._make_request(endpoint)
        
        if not data:
            return None
        
        post = self._parse_story(data)
        
        if post:
            # Fetch comments
            comments = await self._fetch_comments(post_id)
            post.comments = comments
        
        return post
    
    async def _fetch_comments(self, story_id: str, limit: Optional[int] = None) -> List[Comment]:
        """Fetch comments for a story."""
        limit = limit or self.config.max_comments_per_post
        
        endpoint = f"/s/{story_id}.json"
        
        data = await self._make_request(endpoint)
        
        if not data or 'comments' not in data:
            return []
        
        comments = []
        for item in data['comments'][:limit]:
            comment = self._parse_comment(item)
            if comment:
                comments.append(comment)
        
        return comments
    
    def _parse_comment(self, data: Dict[str, Any]) -> Optional[Comment]:
        """Parse Lobsters comment data."""
        try:
            author = None
            if data.get('commenting_user'):
                user = data['commenting_user']
                author = Author(
                    username=user.get('username', 'Unknown'),
                    profile_url=f"https://lobste.rs/u/{user.get('username')}",
                    avatar_url=user.get('avatar_url')
                )
            
            created_at = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00')) if data.get('created_at') else None
            
            comment = Comment(
                id=data.get('short_id', ''),
                author=author,
                content=data.get('comment', ''),
                created_at=created_at,
                upvotes=data.get('score', 0),
                parent_id=data.get('parent_comment'),
                url=f"https://lobste.rs/s/{data.get('story_short_id')}#c_{data.get('short_id')}"
            )
            
            # Parse child comments
            if data.get('comments'):
                for child in data['comments']:
                    child_comment = self._parse_comment(child)
                    if child_comment:
                        comment.replies.append(child_comment)
            
            return comment
            
        except Exception as e:
            logger.error(f"Error parsing Lobsters comment: {e}")
            return None
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific story."""
        comments = await self._fetch_comments(post_id, limit)
        return [self._comment_to_dict(c) for c in comments]
    
    def _comment_to_dict(self, comment: Comment) -> Dict[str, Any]:
        """Convert Comment object to dictionary."""
        return {
            'id': comment.id,
            'author': comment.author.username if comment.author else None,
            'content': comment.content,
            'created_at': comment.created_at.isoformat() if comment.created_at else None,
            'upvotes': comment.upvotes,
            'parent_id': comment.parent_id,
            'replies': [self._comment_to_dict(r) for r in comment.replies]
        }
    
    async def search_posts(
        self, 
        query: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Search for stories on Lobsters."""
        limit = limit or self.config.max_posts
        
        endpoint = "/search.json"
        params = {
            'q': query,
            'what': 'stories',
            'order': 'newest'
        }
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No search results found"
                )
            
            posts = []
            for item in data[:limit]:
                post = self._parse_story(item)
                if post:
                    posts.append(post)
            
            filtered_posts = self._apply_filters(posts)
            
            return CollectionResult(
                source=self.source,
                posts=filtered_posts[:limit],
                success=True,
                total_count=len(posts),
                filtered_count=len(filtered_posts)
            )
            
        except Exception as e:
            logger.error(f"Error searching Lobsters: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def collect_newest(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect newest stories from Lobsters."""
        limit = limit or self.config.max_posts
        
        endpoint = "/newest.json"
        params = {}
        
        if self._tags:
            params['tag'] = ','.join(self._tags)
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No newest stories found"
                )
            
            posts = []
            for item in data[:limit]:
                post = self._parse_story(item)
                if post:
                    posts.append(post)
            
            filtered_posts = self._apply_filters(posts)
            
            return CollectionResult(
                source=self.source,
                posts=filtered_posts[:limit],
                success=True,
                total_count=len(posts),
                filtered_count=len(filtered_posts)
            )
            
        except Exception as e:
            logger.error(f"Error collecting newest Lobsters posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def collect_by_tag(
        self, 
        tag: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Collect stories by specific tag."""
        limit = limit or self.config.max_posts
        
        endpoint = "/t/{tag}.json"
        params = {}
        
        try:
            data = await self._make_request(endpoint.format(tag=tag), params)
            
            if not data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message=f"No stories found for tag: {tag}"
                )
            
            posts = []
            for item in data[:limit]:
                post = self._parse_story(item)
                if post:
                    posts.append(post)
            
            filtered_posts = self._apply_filters(posts)
            
            return CollectionResult(
                source=self.source,
                posts=filtered_posts[:limit],
                success=True,
                total_count=len(posts),
                filtered_count=len(filtered_posts)
            )
            
        except Exception as e:
            logger.error(f"Error collecting by tag {tag}: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
