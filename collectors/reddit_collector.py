
"""Reddit collector for gathering hot posts from Reddit."""

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


class RedditCollector(BaseCollector):
    """Collector for Reddit posts and comments."""
    
    def __init__(self, config: CollectionConfig, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        super().__init__(config)
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token = None
        self._subreddits = config.custom_params.get('subreddits', ['all'])
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.REDDIT
    
    @property
    def base_url(self) -> str:
        return "https://oauth.reddit.com"
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        if self._access_token:
            headers['Authorization'] = f"Bearer {self._access_token}"
        return headers
    
    async def _authenticate(self):
        """Authenticate with Reddit API using OAuth2."""
        if not self.client_id or not self.client_secret:
            logger.warning("No Reddit credentials provided. Using read-only access.")
            return
        
        auth_url = "https://www.reddit.com/api/v1/access_token"
        auth = aiohttp.BasicAuth(self.client_id, self.client_secret)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                auth_url,
                auth=auth,
                data={'grant_type': 'client_credentials'},
                headers={'User-Agent': 'ForumCollector/1.0'}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self._access_token = data.get('access_token')
                    logger.info("Successfully authenticated with Reddit API")
                else:
                    logger.warning("Failed to authenticate with Reddit API")
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot posts from configured subreddits."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        # Authenticate if credentials are available
        if self.client_id and self.client_secret:
            await self._authenticate()
        
        for subreddit in self._subreddits:
            try:
                posts = await self._collect_subreddit_hot(subreddit, limit // len(self._subreddits))
                all_posts.extend(posts)
            except Exception as e:
                logger.error(f"Error collecting from r/{subreddit}: {e}")
        
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
    
    async def _collect_subreddit_hot(self, subreddit: str, limit: int) -> List[Post]:
        """Collect hot posts from a specific subreddit."""
        endpoint = f"/r/{subreddit}/hot"
        params = {'limit': min(limit, 100)}
        
        data = await self._make_request(endpoint, params)
        
        if not data or 'data' not in data or 'children' not in data['data']:
            return []
        
        posts = []
        for child in data['data']['children']:
            post_data = child['data']
            post = self._parse_post(post_data)
            if post:
                posts.append(post)
        
        return posts
    
    def _parse_post(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Reddit post data into Post object."""
        try:
            author = Author(
                username=data.get('author', '[deleted]'),
                profile_url=f"https://reddit.com/u/{data.get('author', '')}",
                reputation=data.get('author_karma')
            )
            
            created_at = datetime.fromtimestamp(data.get('created_utc', 0))
            
            # Determine post URL
            permalink = data.get('permalink', '')
            url = f"https://reddit.com{permalink}"
            
            # Handle different post types
            content = None
            if data.get('selftext'):
                content = data.get('selftext')
            elif data.get('url') and not data.get('url', '').startswith('https://www.reddit.com'):
                content = f"[Link]({data.get('url')})"
            
            post = Post(
                id=data['id'],
                title=data.get('title', ''),
                source=self.source,
                url=url,
                author=author,
                content=content,
                created_at=created_at,
                upvotes=data.get('ups', 0),
                downvotes=data.get('downs', 0),
                comments_count=data.get('num_comments', 0),
                views=data.get('view_count', 0),
                tags=[data.get('subreddit', '')],
                category=data.get('link_flair_text'),
                metadata={
                    'subreddit': data.get('subreddit'),
                    'subreddit_subscribers': data.get('subreddit_subscribers'),
                    'over_18': data.get('over_18', False),
                    'spoiler': data.get('spoiler', False),
                    'stickied': data.get('stickied', False),
                    'domain': data.get('domain'),
                    'gilded': data.get('gilded', 0),
                    'awards': data.get('all_awardings', [])
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Reddit post: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific Reddit post."""
        endpoint = f"/comments/{post_id}"
        params = {'limit': self.config.max_comments_per_post}
        
        data = await self._make_request(endpoint, params)
        
        if not data or len(data) < 2:
            return None
        
        # First element is the post, second is comments
        post_data = data[0]['data']['children'][0]['data']
        comments_data = data[1]['data']['children']
        
        post = self._parse_post(post_data)
        if post:
            post.comments = await self._parse_comments(comments_data, post_id)
        
        return post
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific Reddit post."""
        limit = limit or self.config.max_comments_per_post
        endpoint = f"/comments/{post_id}"
        params = {'limit': limit}
        
        data = await self._make_request(endpoint, params)
        
        if not data or len(data) < 2:
            return []
        
        comments_data = data[1]['data']['children']
        comments = await self._parse_comments(comments_data, post_id, limit)
        
        return [self._comment_to_dict(c) for c in comments]
    
    async def _parse_comments(
        self, 
        comments_data: List[Dict[str, Any]], 
        post_id: str,
        limit: Optional[int] = None
    ) -> List[Comment]:
        """Parse Reddit comments into Comment objects."""
        comments = []
        limit = limit or self.config.max_comments_per_post
        
        async def parse_comment_tree(comment_data: Dict[str, Any], depth: int = 0) -> Optional[Comment]:
            if len(comments) >= limit:
                return None
            
            if comment_data.get('kind') == 'more':
                return None
            
            data = comment_data.get('data', {})
            
            if not data:
                return None
            
            author = Author(
                username=data.get('author', '[deleted]'),
                profile_url=f"https://reddit.com/u/{data.get('author', '')}"
            )
            
            comment = Comment(
                id=data.get('id', ''),
                author=author,
                content=data.get('body', ''),
                created_at=datetime.fromtimestamp(data.get('created_utc', 0)),
                upvotes=data.get('ups', 0),
                downvotes=data.get('downs', 0),
                parent_id=data.get('parent_id'),
                url=f"https://reddit.com{data.get('permalink', '')}"
            )
            
            # Parse replies recursively
            replies_data = data.get('replies', {})
            if isinstance(replies_data, dict) and 'data' in replies_data:
                for reply in replies_data['data'].get('children', []):
                    reply_comment = await parse_comment_tree(reply, depth + 1)
                    if reply_comment:
                        comment.replies.append(reply_comment)
            
            return comment
        
        for comment_data in comments_data:
            comment = await parse_comment_tree(comment_data)
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
            'downvotes': comment.downvotes,
            'parent_id': comment.parent_id,
            'replies': [self._comment_to_dict(r) for r in comment.replies]
        }
    
    async def search_posts(
        self, 
        query: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Search for posts on Reddit."""
        limit = limit or self.config.max_posts
        
        endpoint = "/search"
        params = {
            'q': query,
            'limit': min(limit, 100),
            'sort': 'relevance',
            'type': 'link'
        }
        
        data = await self._make_request(endpoint, params)
        
        if not data or 'data' not in data or 'children' not in data['data']:
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message="No search results found"
            )
        
        posts = []
        for child in data['data']['children']:
            post_data = child['data']
            post = self._parse_post(post_data)
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
