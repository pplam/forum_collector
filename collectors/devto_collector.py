
"""Dev.to collector for gathering hot posts from Dev.to community."""

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


class DevToCollector(BaseCollector):
    """Collector for Dev.to articles and discussions."""
    
    BASE_URL = "https://dev.to/api"
    
    def __init__(self, config: CollectionConfig, api_key: Optional[str] = None):
        super().__init__(config)
        self.api_key = api_key
        self._tags = config.custom_params.get('tags', [])
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.DEV_TO
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        if self.api_key:
            headers['api-key'] = self.api_key
        return headers
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot articles from Dev.to."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # Get articles sorted by popularity
            endpoint = "/articles"
            params = {
                'per_page': min(limit, 100),
                'top': 7  # Articles from last 7 days
            }
            
            if self._tags:
                params['tag'] = self._tags[0]  # Dev.to API supports single tag
            
            data = await self._make_request(endpoint, params)
            
            if not data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No data returned from API"
                )
            
            for item in data:
                post = self._parse_article(item)
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
            logger.error(f"Error collecting Dev.to posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    def _parse_article(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Dev.to article data into Post object."""
        try:
            author = None
            if data.get('user'):
                user = data['user']
                # Handle case where user might be a string (username) or dict
                if isinstance(user, str):
                    author = Author(
                        username=user,
                        profile_url=f"https://dev.to/{user}"
                    )
                elif isinstance(user, dict):
                    author = Author(
                        username=user.get('username', 'Unknown'),
                        profile_url=f"https://dev.to/{user.get('username')}",
                        name=user.get('name'),
                        avatar_url=user.get('profile_image')
                    )
            
            created_at = datetime.fromisoformat(data.get('published_at', '').replace('Z', '+00:00')) if data.get('published_at') else None
            
            tags = []
            if data.get('tag_list'):
                tags = data['tag_list']
            elif data.get('tags'):
                tags = data['tags'].split(', ') if isinstance(data['tags'], str) else data['tags']
            
            post = Post(
                id=str(data['id']),
                title=data.get('title', ''),
                source=self.source,
                url=data.get('url', f"https://dev.to/{data.get('path', '')}"),
                author=author,
                content=data.get('body_markdown') or data.get('description'),
                summary=data.get('description'),
                created_at=created_at,
                upvotes=data.get('positive_reactions_count', 0),
                comments_count=data.get('comments_count', 0),
                views=data.get('page_views_count', 0),
                tags=tags,
                metadata={
                    'reading_time_minutes': data.get('reading_time_minutes'),
                    'published': data.get('published'),
                    'slug': data.get('slug'),
                    'path': data.get('path'),
                    'canonical_url': data.get('canonical_url'),
                    'cover_image': data.get('cover_image'),
                    'social_image': data.get('social_image'),
                    'type_of': data.get('type_of')
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Dev.to article: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific article."""
        endpoint = f"/articles/{post_id}"
        
        data = await self._make_request(endpoint)
        
        if not data:
            return None
        
        post = self._parse_article(data)
        
        if post:
            # Fetch comments
            comments = await self._fetch_comments(post_id)
            post.comments = comments
        
        return post
    
    async def _fetch_comments(self, article_id: str, limit: Optional[int] = None) -> List[Comment]:
        """Fetch comments for an article."""
        limit = limit or self.config.max_comments_per_post
        
        endpoint = f"/comments?a_id={article_id}"
        
        data = await self._make_request(endpoint)
        
        if not data:
            return []
        
        comments = []
        for item in data[:limit]:
            comment = self._parse_comment(item)
            if comment:
                comments.append(comment)
        
        return comments
    
    def _parse_comment(self, data: Dict[str, Any]) -> Optional[Comment]:
        """Parse Dev.to comment data."""
        try:
            author = None
            if data.get('user'):
                user = data['user']
                # Handle case where user might be a string (username) or dict
                if isinstance(user, str):
                    author = Author(
                        username=user,
                        profile_url=f"https://dev.to/{user}"
                    )
                elif isinstance(user, dict):
                    author = Author(
                        username=user.get('username', 'Unknown'),
                        profile_url=f"https://dev.to/{user.get('username')}",
                        name=user.get('name'),
                        avatar_url=user.get('profile_image')
                    )
            
            created_at = datetime.fromisoformat(data.get('created_at', '').replace('Z', '+00:00')) if data.get('created_at') else None
            
            comment = Comment(
                id=str(data.get('id_code', '')),
                author=author,
                content=data.get('body_markdown', ''),
                created_at=created_at,
                url=data.get('url', '')
            )
            
            # Parse child comments
            if data.get('children'):
                for child in data['children']:
                    child_comment = self._parse_comment(child)
                    if child_comment:
                        child_comment.parent_id = str(data.get('id_code', ''))
                        comment.replies.append(child_comment)
            
            return comment
            
        except Exception as e:
            logger.error(f"Error parsing Dev.to comment: {e}")
            return None
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific article."""
        comments = await self._fetch_comments(post_id, limit)
        return [self._comment_to_dict(c) for c in comments]
    
    def _comment_to_dict(self, comment: Comment) -> Dict[str, Any]:
        """Convert Comment object to dictionary."""
        return {
            'id': comment.id,
            'author': comment.author.username if comment.author else None,
            'content': comment.content,
            'created_at': comment.created_at.isoformat() if comment.created_at else None,
            'parent_id': comment.parent_id,
            'replies': [self._comment_to_dict(r) for r in comment.replies]
        }
    
    async def search_posts(
        self, 
        query: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Search for articles on Dev.to."""
        limit = limit or self.config.max_posts
        
        endpoint = "/articles"
        params = {
            'per_page': min(limit, 100)
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
            
            # Filter by query in title or description
            posts = []
            query_lower = query.lower()
            for item in data:
                title = item.get('title', '').lower()
                description = item.get('description', '').lower()
                
                if query_lower in title or query_lower in description:
                    post = self._parse_article(item)
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
            logger.error(f"Error searching Dev.to: {e}")
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
        """Collect articles by specific tag."""
        limit = limit or self.config.max_posts
        
        endpoint = "/articles"
        params = {
            'per_page': min(limit, 100),
            'tag': tag
        }
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message=f"No articles found for tag: {tag}"
                )
            
            posts = []
            for item in data:
                post = self._parse_article(item)
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
            logger.error(f"Error collecting by tag: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
