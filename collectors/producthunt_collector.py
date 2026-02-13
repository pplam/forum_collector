
"""Product Hunt collector for gathering trending products and discussions."""

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


class ProductHuntCollector(BaseCollector):
    """Collector for Product Hunt posts and discussions."""
    
    BASE_URL = "https://api.producthunt.com/v2/api/graphql"
    
    def __init__(self, config: CollectionConfig, api_key: Optional[str] = None):
        super().__init__(config)
        self.api_key = api_key
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.PRODUCT_HUNT
    
    @property
    def base_url(self) -> str:
        return "https://api.producthunt.com/v1"  # REST API base
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        if self.api_key:
            headers['Authorization'] = f"Bearer {self.api_key}"
        return headers
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect trending products from Product Hunt."""
        limit = limit or self.config.max_posts
        
        if not self.api_key:
            logger.warning("Product Hunt API key required")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message="API key required for Product Hunt"
            )
        
        try:
            # Use GraphQL API for better data
            query = """
            query($first: Int!) {
                posts(order: RANKING, first: $first) {
                    edges {
                        node {
                            id
                            name
                            tagline
                            description
                            url
                            website
                            createdAt
                            votesCount
                            commentsCount
                            topics(first: 5) {
                                edges {
                                    node {
                                        name
                                    }
                                }
                            }
                            makers {
                                id
                                username
                                name
                                headline
                                avatar
                            }
                            thumbnail {
                                url
                            }
                        }
                    }
                }
            }
            """
            
            variables = {'first': min(limit, 100)}
            
            data = await self._graphql_request(query, variables)
            
            if not data or 'posts' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No data returned from API"
                )
            
            posts = []
            for edge in data['posts']['edges']:
                post = self._parse_product(edge['node'])
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
            logger.error(f"Error collecting Product Hunt posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def _graphql_request(
        self, 
        query: str, 
        variables: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Make a GraphQL request to Product Hunt API."""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        try:
            async with self.session.post(
                self.BASE_URL,
                json={'query': query, 'variables': variables}
            ) as response:
                if response.status == 401:
                    logger.error("Product Hunt authentication failed")
                    return None
                
                response.raise_for_status()
                data = await response.json()
                return data.get('data')
                
        except Exception as e:
            logger.error(f"GraphQL request failed: {e}")
            return None
    
    def _parse_product(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Product Hunt product data into Post object."""
        try:
            # Get first maker as author
            author = None
            if data.get('makers') and len(data['makers']) > 0:
                maker = data['makers'][0]
                author = Author(
                    username=maker.get('username', 'Unknown'),
                    name=maker.get('name'),
                    bio=maker.get('headline'),
                    avatar_url=maker.get('avatar')
                )
            
            created_at = datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00')) if data.get('createdAt') else None
            
            tags = []
            if data.get('topics'):
                tags = [edge['node']['name'] for edge in data['topics']['edges']]
            
            post = Post(
                id=str(data['id']),
                title=data.get('name', ''),
                source=self.source,
                url=data.get('url', ''),
                author=author,
                content=data.get('description'),
                summary=data.get('tagline'),
                created_at=created_at,
                upvotes=data.get('votesCount', 0),
                comments_count=data.get('commentsCount', 0),
                tags=tags,
                metadata={
                    'website': data.get('website'),
                    'thumbnail': data['thumbnail']['url'] if data.get('thumbnail') else None,
                    'makers_count': len(data.get('makers', [])),
                    'product_name': data.get('name')
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Product Hunt product: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific product."""
        query = """
        query($id: ID!) {
            post(id: $id) {
                id
                name
                tagline
                description
                url
                website
                createdAt
                votesCount
                commentsCount
                topics(first: 5) {
                    edges {
                        node {
                            name
                        }
                    }
                }
                makers {
                    id
                    username
                    name
                    headline
                    avatar
                }
                comments(first: 50) {
                    edges {
                        node {
                            id
                            body
                            createdAt
                            user {
                                id
                                username
                                name
                                avatar
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {'id': post_id}
        
        data = await self._graphql_request(query, variables)
        
        if not data or 'post' not in data:
            return None
        
        post = self._parse_product(data['post'])
        
        if post and data['post'].get('comments'):
            post.comments = self._parse_comments(data['post']['comments']['edges'])
        
        return post
    
    def _parse_comments(self, comments_edges: List[Dict[str, Any]]) -> List[Comment]:
        """Parse Product Hunt comments."""
        comments = []
        
        for edge in comments_edges:
            data = edge['node']
            
            author = None
            if data.get('user'):
                user = data['user']
                author = Author(
                    username=user.get('username', 'Unknown'),
                    name=user.get('name'),
                    avatar_url=user.get('avatar')
                )
            
            comment = Comment(
                id=str(data['id']),
                author=author,
                content=data.get('body', ''),
                created_at=datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00')) if data.get('createdAt') else None
            )
            
            comments.append(comment)
        
        return comments
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific product."""
        post = await self.get_post_details(post_id)
        
        if not post:
            return []
        
        return [self._comment_to_dict(c) for c in post.comments[:limit or self.config.max_comments_per_post]]
    
    def _comment_to_dict(self, comment: Comment) -> Dict[str, Any]:
        """Convert Comment object to dictionary."""
        return {
            'id': comment.id,
            'author': comment.author.username if comment.author else None,
            'content': comment.content,
            'created_at': comment.created_at.isoformat() if comment.created_at else None
        }
    
    async def search_posts(
        self, 
        query: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Search for products on Product Hunt."""
        limit = limit or self.config.max_posts
        
        search_query = """
        query($query: String!, $first: Int!) {
            search(query: $query, first: $first, type: POSTS) {
                edges {
                    node {
                        ... on Post {
                            id
                            name
                            tagline
                            url
                            votesCount
                            commentsCount
                            topics(first: 5) {
                                edges {
                                    node {
                                        name
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            'query': query,
            'first': min(limit, 100)
        }
        
        try:
            data = await self._graphql_request(search_query, variables)
            
            if not data or 'search' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No search results found"
                )
            
            posts = []
            for edge in data['search']['edges']:
                post = self._parse_product(edge['node'])
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
            logger.error(f"Error searching Product Hunt: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
