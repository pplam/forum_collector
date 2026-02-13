
"""Hacker News collector for gathering hot posts from HN."""

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


class HackerNewsCollector(BaseCollector):
    """Collector for Hacker News posts and comments."""
    
    # HN API is free and doesn't require authentication
    BASE_URL = "https://hacker-news.firebaseio.com/v0"
    
    def __init__(self, config: CollectionConfig):
        super().__init__(config)
        self._include_ask_hn = config.custom_params.get('include_ask_hn', True)
        self._include_show_hn = config.custom_params.get('include_show_hn', True)
        self._include_jobs = config.custom_params.get('include_jobs', False)
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.HACKER_NEWS
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot posts from Hacker News front page."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # Get top story IDs
            top_ids = await self._get_top_story_ids()
            
            # Fetch posts in batches
            batch_size = 30
            for i in range(0, min(len(top_ids), limit * 2), batch_size):
                batch_ids = top_ids[i:i + batch_size]
                tasks = [self._fetch_item(item_id) for item_id in batch_ids]
                items = await asyncio.gather(*tasks, return_exceptions=True)
                
                for item in items:
                    if isinstance(item, dict) and item.get('type') == 'story':
                        post = self._parse_post(item)
                        if post:
                            all_posts.append(post)
                
                if len(all_posts) >= limit:
                    break
            
            # Apply filters
            filtered_posts = self._apply_filters(all_posts)
            
            # Sort by score
            filtered_posts.sort(key=lambda p: p.score, reverse=True)
            
            return CollectionResult(
                source=self.source,
                posts=filtered_posts[:limit],
                success=True,
                total_count=len(all_posts),
                filtered_count=len(filtered_posts)
            )
            
        except Exception as e:
            logger.error(f"Error collecting Hacker News posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def _get_top_story_ids(self) -> List[int]:
        """Get list of top story IDs."""
        endpoint = "/topstories.json"
        data = await self._make_request(endpoint)
        
        if not data:
            return []
        
        return data
    
    async def _fetch_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single item by ID."""
        endpoint = f"/item/{item_id}.json"
        return await self._make_request(endpoint)
    
    def _parse_post(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Hacker News item data into Post object."""
        try:
            if not data or data.get('deleted') or data.get('dead'):
                return None
            
            author = None
            if data.get('by'):
                author = Author(
                    username=data['by'],
                    profile_url=f"https://news.ycombinator.com/user?id={data['by']}"
                )
            
            created_at = datetime.fromtimestamp(data.get('time', 0))
            
            # Determine URL
            url = data.get('url')
            if not url:
                # Ask HN, Show HN, etc. don't have external URLs
                url = f"https://news.ycombinator.com/item?id={data['id']}"
            
            # Determine category
            title = data.get('title', '')
            category = 'story'
            if title.lower().startswith('ask hn:'):
                category = 'ask_hn'
            elif title.lower().startswith('show hn:'):
                category = 'show_hn'
            elif data.get('type') == 'job':
                category = 'job'
            
            post = Post(
                id=str(data['id']),
                title=title,
                source=self.source,
                url=url,
                author=author,
                content=data.get('text'),
                created_at=created_at,
                upvotes=data.get('score', 0),
                comments_count=data.get('descendants', 0),
                tags=[category],
                category=category,
                metadata={
                    'hn_id': data['id'],
                    'type': data.get('type'),
                    'has_url': bool(data.get('url'))
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Hacker News post: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific HN post."""
        item = await self._fetch_item(int(post_id))
        
        if not item:
            return None
        
        post = self._parse_post(item)
        
        if post and item.get('kids'):
            # Fetch comments
            comments = await self._fetch_comments(item['kids'], self.config.max_comments_per_post)
            post.comments = comments
        
        return post
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific HN post."""
        limit = limit or self.config.max_comments_per_post
        
        item = await self._fetch_item(int(post_id))
        
        if not item or not item.get('kids'):
            return []
        
        comments = await self._fetch_comments(item['kids'], limit)
        
        return [self._comment_to_dict(c) for c in comments]
    
    async def _fetch_comments(
        self, 
        comment_ids: List[int], 
        limit: int
    ) -> List[Comment]:
        """Fetch comments recursively."""
        comments = []
        
        async def fetch_comment_tree(comment_id: int, depth: int = 0) -> Optional[Comment]:
            if len(comments) >= limit:
                return None
            
            item = await self._fetch_item(comment_id)
            
            if not item or item.get('deleted') or item.get('dead'):
                return None
            
            author = None
            if item.get('by'):
                author = Author(
                    username=item['by'],
                    profile_url=f"https://news.ycombinator.com/user?id={item['by']}"
                )
            
            comment = Comment(
                id=str(item['id']),
                author=author,
                content=item.get('text', ''),
                created_at=datetime.fromtimestamp(item.get('time', 0)),
                upvotes=0,  # HN doesn't show comment scores
                parent_id=str(item.get('parent')),
                url=f"https://news.ycombinator.com/item?id={item['id']}"
            )
            
            # Fetch replies recursively
            if item.get('kids') and depth < 5:  # Limit depth to avoid too many requests
                for kid_id in item['kids']:
                    reply = await fetch_comment_tree(kid_id, depth + 1)
                    if reply:
                        comment.replies.append(reply)
            
            return comment
        
        for comment_id in comment_ids[:limit]:
            comment = await fetch_comment_tree(comment_id)
            if comment:
                comments.append(comment)
        
        return comments
    
    def _comment_to_dict(self, comment: Comment) -> Dict[str, Any]:
        """Convert Comment object to dictionary."""
        return {
            'id': comment.id,
            'author': comment.author.username if comment.author else None,
            'content': comment.content,
            'created_at': comment.created_at.isoformat(),
            'upvotes': comment.upvotes,
            'parent_id': comment.parent_id,
            'replies': [self._comment_to_dict(r) for r in comment.replies]
        }
    
    async def search_posts(
        self, 
        query: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Search for posts on Hacker News using Algolia API."""
        limit = limit or self.config.max_posts
        
        # HN uses Algolia for search
        search_url = "https://hn.algolia.com/api/v1/search"
        params = {
            'query': query,
            'hitsPerPage': min(limit, 100),
            'tags': 'story'
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, params=params) as response:
                    if response.status != 200:
                        return CollectionResult(
                            source=self.source,
                            posts=[],
                            success=False,
                            error_message="Search request failed"
                        )
                    
                    data = await response.json()
                    
                    posts = []
                    for hit in data.get('hits', []):
                        post = Post(
                            id=str(hit.get('objectID', '')),
                            title=hit.get('title', ''),
                            source=self.source,
                            url=hit.get('url') or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                            author=Author(username=hit.get('author', '')),
                            created_at=datetime.fromtimestamp(hit.get('created_at_i', 0)),
                            upvotes=hit.get('points', 0),
                            comments_count=hit.get('num_comments', 0),
                            metadata={'relevance': hit.get('relevance', 0)}
                        )
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
            logger.error(f"Error searching Hacker News: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
