
"""GitHub Discussions collector for gathering hot discussions from GitHub repositories."""

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


class GitHubDiscussionsCollector(BaseCollector):
    """Collector for GitHub Discussions."""
    
    BASE_GRAPHQL_URL = "https://api.github.com/graphql"
    BASE_REST_URL = "https://api.github.com"
    
    def __init__(self, config: CollectionConfig, token: Optional[str] = None):
        super().__init__(config)
        self.token = token
        self._repositories = config.custom_params.get('repositories', [])
        # Format: ['owner/repo', 'owner2/repo2']
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.GITHUB_DISCUSSIONS
    
    @property
    def base_url(self) -> str:
        return self.BASE_REST_URL
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        if self.token:
            headers['Authorization'] = f"Bearer {self.token}"
        return headers
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot discussions from configured repositories."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        if not self._repositories:
            logger.warning("No repositories configured for GitHub Discussions")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message="No repositories configured"
            )
        
        if not self.token:
            logger.warning("GitHub token required for Discussions API")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message="GitHub token required"
            )
        
        for repo in self._repositories:
            try:
                posts = await self._collect_repo_discussions(repo, limit // len(self._repositories))
                all_posts.extend(posts)
            except Exception as e:
                logger.error(f"Error collecting from {repo}: {e}")
        
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
    
    async def _collect_repo_discussions(self, repo: str, limit: int) -> List[Post]:
        """Collect discussions from a specific repository."""
        owner, name = repo.split('/')
        
        query = """
        query($owner: String!, $name: String!, $first: Int!) {
            repository(owner: $owner, name: $name) {
                discussions(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
                    nodes {
                        id
                        number
                        title
                        body
                        url
                        createdAt
                        updatedAt
                        author {
                            login
                            url
                            avatarUrl
                        }
                        upvoteCount
                        comments(first: 10) {
                            totalCount
                        }
                        labels(first: 5) {
                            nodes {
                                name
                            }
                        }
                        category {
                            name
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            'owner': owner,
            'name': name,
            'first': min(limit, 100)
        }
        
        data = await self._graphql_request(query, variables)
        
        if not data or 'repository' not in data or 'discussions' not in data['repository']:
            return []
        
        posts = []
        for node in data['repository']['discussions']['nodes']:
            post = self._parse_discussion(node, repo)
            if post:
                posts.append(post)
        
        return posts
    
    async def _graphql_request(
        self, 
        query: str, 
        variables: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Make a GraphQL request to GitHub API."""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        try:
            async with self.session.post(
                self.BASE_GRAPHQL_URL,
                json={'query': query, 'variables': variables}
            ) as response:
                if response.status == 401:
                    logger.error("GitHub authentication failed")
                    return None
                
                response.raise_for_status()
                data = await response.json()
                return data.get('data')
                
        except Exception as e:
            logger.error(f"GraphQL request failed: {e}")
            return None
    
    def _parse_discussion(self, data: Dict[str, Any], repo: str) -> Optional[Post]:
        """Parse GitHub discussion data into Post object."""
        try:
            author = None
            if data.get('author'):
                author_data = data['author']
                author = Author(
                    username=author_data.get('login', 'Unknown'),
                    profile_url=author_data.get('url'),
                    avatar_url=author_data.get('avatarUrl')
                )
            
            created_at = datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00'))
            
            tags = []
            if data.get('labels'):
                tags = [label['name'] for label in data['labels']['nodes']]
            
            post = Post(
                id=data['id'],
                title=data.get('title', ''),
                source=self.source,
                url=data.get('url', ''),
                author=author,
                content=data.get('body'),
                created_at=created_at,
                upvotes=data.get('upvoteCount', 0),
                comments_count=data['comments']['totalCount'] if data.get('comments') else 0,
                tags=tags,
                category=data['category']['name'] if data.get('category') else None,
                metadata={
                    'number': data.get('number'),
                    'repository': repo,
                    'updated_at': data.get('updatedAt')
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing GitHub discussion: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific discussion."""
        query = """
        query($discussionId: ID!) {
            node(id: $discussionId) {
                ... on Discussion {
                    id
                    number
                    title
                    body
                    url
                    createdAt
                    author {
                        login
                        url
                        avatarUrl
                    }
                    upvoteCount
                    comments(first: 50) {
                        totalCount
                        nodes {
                            id
                            body
                            createdAt
                            author {
                                login
                                url
                                avatarUrl
                            }
                            upvoteCount
                            replies(first: 10) {
                                nodes {
                                    id
                                    body
                                    createdAt
                                    author {
                                        login
                                        url
                                    }
                                }
                            }
                        }
                    }
                    labels(first: 5) {
                        nodes {
                            name
                        }
                    }
                    category {
                        name
                    }
                }
            }
        }
        """
        
        variables = {'discussionId': post_id}
        
        data = await self._graphql_request(query, variables)
        
        if not data or 'node' not in data:
            return None
        
        discussion = data['node']
        post = self._parse_discussion(discussion, '')
        
        if post and discussion.get('comments'):
            post.comments = self._parse_comments(discussion['comments']['nodes'])
        
        return post
    
    def _parse_comments(self, comments_data: List[Dict[str, Any]]) -> List[Comment]:
        """Parse GitHub discussion comments."""
        comments = []
        
        for comment_data in comments_data:
            author = None
            if comment_data.get('author'):
                author_data = comment_data['author']
                author = Author(
                    username=author_data.get('login', 'Unknown'),
                    profile_url=author_data.get('url'),
                    avatar_url=author_data.get('avatarUrl')
                )
            
            comment = Comment(
                id=comment_data['id'],
                author=author,
                content=comment_data.get('body', ''),
                created_at=datetime.fromisoformat(comment_data['createdAt'].replace('Z', '+00:00')),
                upvotes=comment_data.get('upvoteCount', 0)
            )
            
            # Parse replies
            if comment_data.get('replies'):
                for reply_data in comment_data['replies']['nodes']:
                    reply_author = None
                    if reply_data.get('author'):
                        reply_author = Author(
                            username=reply_data['author'].get('login', 'Unknown'),
                            profile_url=reply_data['author'].get('url')
                        )
                    
                    reply = Comment(
                        id=reply_data['id'],
                        author=reply_author,
                        content=reply_data.get('body', ''),
                        created_at=datetime.fromisoformat(reply_data['createdAt'].replace('Z', '+00:00')),
                        parent_id=comment_data['id']
                    )
                    comment.replies.append(reply)
            
            comments.append(comment)
        
        return comments
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific discussion."""
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
        """Search for discussions across configured repositories."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        for repo in self._repositories:
            try:
                posts = await self._search_repo_discussions(repo, query, limit // len(self._repositories))
                all_posts.extend(posts)
            except Exception as e:
                logger.error(f"Error searching in {repo}: {e}")
        
        filtered_posts = self._apply_filters(all_posts)
        
        return CollectionResult(
            source=self.source,
            posts=filtered_posts[:limit],
            success=True,
            total_count=len(all_posts),
            filtered_count=len(filtered_posts)
        )
    
    async def _search_repo_discussions(
        self, 
        repo: str, 
        query: str, 
        limit: int
    ) -> List[Post]:
        """Search discussions in a specific repository."""
        owner, name = repo.split('/')
        
        search_query = f"{query} repo:{repo} type:discussion"
        
        # Note: GitHub's search API doesn't directly support discussions
        # This is a workaround using the GraphQL API
        gql_query = """
        query($owner: String!, $name: String!, $first: Int!, $searchQuery: String!) {
            repository(owner: $owner, name: $name) {
                discussions(first: $first) {
                    nodes {
                        id
                        number
                        title
                        body
                        url
                        createdAt
                        author {
                            login
                            url
                        }
                        upvoteCount
                        comments {
                            totalCount
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            'owner': owner,
            'name': name,
            'first': min(limit, 100),
            'searchQuery': search_query
        }
        
        data = await self._graphql_request(gql_query, variables)
        
        if not data or 'repository' not in data:
            return []
        
        posts = []
        for node in data['repository']['discussions']['nodes']:
            # Filter by query in title or body
            if query.lower() in node.get('title', '').lower() or query.lower() in node.get('body', '').lower():
                post = self._parse_discussion(node, repo)
                if post:
                    posts.append(post)
        
        return posts
