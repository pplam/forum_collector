
"""V2EX collector for gathering hot posts from V2EX community."""

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


class V2EXCollector(BaseCollector):
    """Collector for V2EX posts and discussions."""
    
    BASE_URL = "https://www.v2ex.com/api/v2"
    
    def __init__(self, config: CollectionConfig, token: Optional[str] = None):
        super().__init__(config)
        self.token = token
        self._nodes = config.custom_params.get('nodes', [])  # V2EX node names
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.V2EX
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        if self.token:
            headers['Authorization'] = f"Bearer {self.token}"
        return headers
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot topics from V2EX."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # Get hot topics
            endpoint = "/topics/hot.json"
            params = {'limit': min(limit, 100)}
            
            data = await self._make_request(endpoint, params)
            
            if not data or 'result' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No data returned from API"
                )
            
            for item in data['result']:
                post = self._parse_topic(item)
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
            logger.error(f"Error collecting V2EX posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    def _parse_topic(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse V2EX topic data into Post object."""
        try:
            author = None
            if data.get('member'):
                member = data['member']
                author = Author(
                    username=member.get('username', 'Unknown'),
                    profile_url=f"https://www.v2ex.com/member/{member.get('username')}",
                    avatar_url=member.get('avatar_large'),
                    bio=member.get('bio')
                )
            
            created_at = datetime.fromtimestamp(data.get('created', 0))
            
            node_name = None
            if data.get('node'):
                node_name = data['node'].get('name')
            
            post = Post(
                id=str(data['id']),
                title=data.get('title', ''),
                source=self.source,
                url=f"https://www.v2ex.com/t/{data['id']}",
                author=author,
                content=data.get('content'),
                summary=data.get('content_rendered'),
                created_at=created_at,
                upvotes=data.get('thanks', 0),
                comments_count=data.get('replies', 0),
                views=0,  # V2EX doesn't provide view count
                tags=[node_name] if node_name else [],
                category=node_name,
                metadata={
                    'node': node_name,
                    'node_title': data['node'].get('title') if data.get('node') else None,
                    'last_modified': datetime.fromtimestamp(data['last_modified']) if data.get('last_modified') else None,
                    'last_touched': datetime.fromtimestamp(data['last_touched']) if data.get('last_touched') else None
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing V2EX topic: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific topic."""
        endpoint = f"/topics/{post_id}.json"
        
        data = await self._make_request(endpoint)
        
        if not data or 'result' not in data:
            return None
        
        post = self._parse_topic(data['result'])
        
        if post:
            # Fetch replies
            replies = await self._fetch_replies(post_id)
            post.comments = replies
        
        return post
    
    async def _fetch_replies(self, topic_id: str, limit: Optional[int] = None) -> List[Comment]:
        """Fetch replies for a topic."""
        limit = limit or self.config.max_comments_per_post
        
        endpoint = f"/topics/{topic_id}/replies.json"
        params = {'limit': min(limit, 100)}
        
        data = await self._make_request(endpoint, params)
        
        if not data or 'result' not in data:
            return []
        
        comments = []
        for item in data['result']:
            comment = self._parse_reply(item)
            if comment:
                comments.append(comment)
        
        return comments
    
    def _parse_reply(self, data: Dict[str, Any]) -> Optional[Comment]:
        """Parse V2EX reply data."""
        try:
            author = None
            if data.get('member'):
                member = data['member']
                author = Author(
                    username=member.get('username', 'Unknown'),
                    profile_url=f"https://www.v2ex.com/member/{member.get('username')}",
                    avatar_url=member.get('avatar_large')
                )
            
            comment = Comment(
                id=str(data['id']),
                author=author,
                content=data.get('content', ''),
                created_at=datetime.fromtimestamp(data.get('created', 0)),
                upvotes=data.get('thanks', 0),
                parent_id=str(data.get('topic_id')),
                url=f"https://www.v2ex.com/t/{data.get('topic_id')}#r_{data['id']}"
            )
            
            return comment
            
        except Exception as e:
            logger.error(f"Error parsing V2EX reply: {e}")
            return None
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific topic."""
        comments = await self._fetch_replies(post_id, limit)
        return [self._comment_to_dict(c) for c in comments]
    
    def _comment_to_dict(self, comment: Comment) -> Dict[str, Any]:
        """Convert Comment object to dictionary."""
        return {
            'id': comment.id,
            'author': comment.author.username if comment.author else None,
            'content': comment.content,
            'created_at': comment.created_at.isoformat(),
            'upvotes': comment.upvotes,
            'parent_id': comment.parent_id,
            'url': comment.url
        }
    
    async def collect_by_node(
        self, 
        node_name: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Collect topics from a specific node."""
        limit = limit or self.config.max_posts
        
        endpoint = f"/nodes/{node_name}/topics.json"
        params = {'limit': min(limit, 100)}
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data or 'result' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message=f"No topics found for node: {node_name}"
                )
            
            posts = []
            for item in data['result']:
                post = self._parse_topic(item)
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
            logger.error(f"Error collecting from node {node_name}: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def get_latest_topics(self, limit: Optional[int] = None) -> CollectionResult:
        """Get latest topics from V2EX."""
        limit = limit or self.config.max_posts
        
        endpoint = "/topics/latest.json"
        params = {'limit': min(limit, 100)}
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data or 'result' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No latest topics found"
                )
            
            posts = []
            for item in data['result']:
                post = self._parse_topic(item)
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
            logger.error(f"Error collecting latest topics: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
