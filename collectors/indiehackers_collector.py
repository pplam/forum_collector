
"""Indie Hackers collector for gathering posts from the Indie Hackers community."""

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


class IndieHackersCollector(BaseCollector):
    """Collector for Indie Hackers posts and discussions."""
    
    BASE_URL = "https://indiehackers.com/api"
    
    def __init__(self, config: CollectionConfig):
        super().__init__(config)
        self._categories = config.custom_params.get('categories', [])
        self._include_ama = config.custom_params.get('include_ama', True)
        self._include_milestones = config.custom_params.get('include_milestones', True)
        self._include_products = config.custom_params.get('include_products', False)
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.INDIE_HACKERS
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot posts from Indie Hackers."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # Collect from different feed types
            feed_types = ['top', 'new', 'featured']
            
            for feed_type in feed_types:
                if len(all_posts) >= limit * 2:  # Get extra for filtering
                    break
                    
                posts = await self._fetch_feed(feed_type, min(limit, 50))
                all_posts.extend(posts)
                
                # Small delay between requests
                await asyncio.sleep(0.5)
            
            # Remove duplicates based on post ID
            seen_ids = set()
            unique_posts = []
            for post in all_posts:
                if post.id not in seen_ids:
                    seen_ids.add(post.id)
                    unique_posts.append(post)
            
            # Apply filters
            filtered_posts = self._apply_filters(unique_posts)
            
            # Sort by engagement (upvotes + comments)
            filtered_posts.sort(
                key=lambda p: (p.upvotes or 0) + (p.comments_count or 0) * 2,
                reverse=True
            )
            
            return CollectionResult(
                source=self.source,
                posts=filtered_posts[:limit],
                success=True,
                total_count=len(unique_posts),
                filtered_count=len(filtered_posts)
            )
            
        except Exception as e:
            logger.error(f"Error collecting Indie Hackers posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def _fetch_feed(self, feed_type: str, limit: int) -> List[Post]:
        """Fetch posts from a specific feed."""
        # Indie Hackers uses a GraphQL-like API
        # We'll use their public feed endpoint
        endpoint = "/feed"
        params = {
            'type': feed_type,
            'limit': limit
        }
        
        # Add category filter if specified
        if self._categories:
            params['category'] = self._categories[0]
        
        data = await self._make_request(endpoint, params)
        
        if not data or not isinstance(data, dict):
            return []
        
        posts = []
        items = data.get('posts', []) or data.get('data', []) or []
        
        for item in items:
            post = self._parse_post(item)
            if post:
                posts.append(post)
        
        return posts
    
    def _parse_post(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Indie Hackers post data into Post object."""
        try:
            if not data:
                return None
            
            # Handle different data structures
            post_data = data.get('post', data)
            
            # Skip if deleted or not published
            if post_data.get('deleted') or not post_data.get('published'):
                return None
            
            # Parse author
            author = None
            author_data = post_data.get('user') or post_data.get('author')
            if author_data:
                if isinstance(author_data, dict):
                    author = Author(
                        username=author_data.get('username', 'Unknown'),
                        name=author_data.get('name') or author_data.get('displayName'),
                        profile_url=f"https://indiehackers.com/user/{author_data.get('username', '')}",
                        avatar_url=author_data.get('avatarUrl') or author_data.get('avatar')
                    )
                elif isinstance(author_data, str):
                    author = Author(
                        username=author_data,
                        profile_url=f"https://indiehackers.com/user/{author_data}"
                    )
            
            # Parse dates
            created_at = None
            created_str = post_data.get('createdAt') or post_data.get('created_at')
            if created_str:
                try:
                    # Handle ISO format
                    created_at = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    try:
                        # Handle timestamp
                        created_at = datetime.fromtimestamp(int(created_str))
                    except (ValueError, TypeError):
                        pass
            
            # Get post URL
            post_id = str(post_data.get('id', ''))
            slug = post_data.get('slug', '')
            url = post_data.get('url')
            if not url:
                if slug:
                    url = f"https://indiehackers.com/post/{slug}"
                else:
                    url = f"https://indiehackers.com/post/{post_id}"
            
            # Determine category/type
            category = post_data.get('category') or post_data.get('type', 'post')
            if post_data.get('isAma'):
                category = 'ama'
            elif post_data.get('isMilestone'):
                category = 'milestone'
            
            # Build tags list
            tags = []
            if category:
                tags.append(category)
            if post_data.get('tags'):
                post_tags = post_data['tags']
                if isinstance(post_tags, list):
                    tags.extend(post_tags)
                elif isinstance(post_tags, str):
                    tags.extend([t.strip() for t in post_tags.split(',')])
            
            post = Post(
                id=post_id,
                title=post_data.get('title', ''),
                source=self.source,
                url=url,
                author=author,
                content=post_data.get('body') or post_data.get('content') or post_data.get('description'),
                summary=post_data.get('description') or post_data.get('excerpt'),
                created_at=created_at,
                upvotes=post_data.get('upvotes') or post_data.get('votes') or post_data.get('reactions', 0),
                comments_count=post_data.get('commentsCount') or post_data.get('commentCount', 0),
                views=post_data.get('views') or post_data.get('viewCount', 0),
                tags=tags,
                category=category,
                metadata={
                    'post_id': post_id,
                    'slug': slug,
                    'is_ama': post_data.get('isAma', False),
                    'is_milestone': post_data.get('isMilestone', False),
                    'is_featured': post_data.get('featured', False),
                    'category': category
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Indie Hackers post: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific post."""
        endpoint = f"/posts/{post_id}"
        
        data = await self._make_request(endpoint)
        
        if not data:
            return None
        
        post = self._parse_post(data)
        
        if post:
            # Fetch comments
            comments = await self._fetch_comments(post_id)
            post.comments = comments
        
        return post
    
    async def _fetch_comments(self, post_id: str, limit: Optional[int] = None) -> List[Comment]:
        """Fetch comments for a post."""
        limit = limit or self.config.max_comments_per_post
        
        endpoint = f"/posts/{post_id}/comments"
        params = {'limit': limit}
        
        data = await self._make_request(endpoint, params)
        
        if not data:
            return []
        
        comments = []
        items = data.get('comments', []) or data.get('data', []) or []
        
        for item in items[:limit]:
            comment = self._parse_comment(item)
            if comment:
                comments.append(comment)
        
        return comments
    
    def _parse_comment(self, data: Dict[str, Any]) -> Optional[Comment]:
        """Parse Indie Hackers comment data."""
        try:
            if not data:
                return None
            
            # Handle nested structure
            comment_data = data.get('comment', data)
            
            # Skip deleted comments
            if comment_data.get('deleted'):
                return None
            
            # Parse author
            author = None
            author_data = comment_data.get('user') or comment_data.get('author')
            if author_data:
                if isinstance(author_data, dict):
                    author = Author(
                        username=author_data.get('username', 'Unknown'),
                        name=author_data.get('name') or author_data.get('displayName'),
                        profile_url=f"https://indiehackers.com/user/{author_data.get('username', '')}",
                        avatar_url=author_data.get('avatarUrl') or author_data.get('avatar')
                    )
                elif isinstance(author_data, str):
                    author = Author(
                        username=author_data,
                        profile_url=f"https://indiehackers.com/user/{author_data}"
                    )
            
            # Parse date
            created_at = None
            created_str = comment_data.get('createdAt') or comment_data.get('created_at')
            if created_str:
                try:
                    created_at = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    try:
                        created_at = datetime.fromtimestamp(int(created_str))
                    except (ValueError, TypeError):
                        pass
            
            comment_id = str(comment_data.get('id', ''))
            
            comment = Comment(
                id=comment_id,
                author=author,
                content=comment_data.get('body') or comment_data.get('content', ''),
                created_at=created_at,
                upvotes=comment_data.get('upvotes') or comment_data.get('votes', 0),
                parent_id=str(comment_data.get('parentId')) if comment_data.get('parentId') else None,
                url=f"https://indiehackers.com/comment/{comment_id}"
            )
            
            # Parse replies recursively
            replies_data = comment_data.get('replies') or comment_data.get('children', [])
            if replies_data:
                for reply_data in replies_data:
                    reply = self._parse_comment(reply_data)
                    if reply:
                        reply.parent_id = comment_id
                        comment.replies.append(reply)
            
            return comment
            
        except Exception as e:
            logger.error(f"Error parsing Indie Hackers comment: {e}")
            return None
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific post."""
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
        """Search for posts on Indie Hackers."""
        limit = limit or self.config.max_posts
        
        endpoint = "/search"
        params = {
            'q': query,
            'type': 'posts',
            'limit': min(limit, 50)
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
            items = data.get('posts', []) or data.get('results', []) or data.get('data', []) or []
            
            for item in items:
                post = self._parse_post(item)
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
            logger.error(f"Error searching Indie Hackers: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def collect_by_category(
        self, 
        category: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Collect posts by specific category."""
        limit = limit or self.config.max_posts
        
        endpoint = "/feed"
        params = {
            'category': category,
            'limit': min(limit, 50)
        }
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message=f"No posts found for category: {category}"
                )
            
            posts = []
            items = data.get('posts', []) or data.get('data', []) or []
            
            for item in items:
                post = self._parse_post(item)
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
            logger.error(f"Error collecting by category: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
