
"""Stack Overflow collector for gathering hot questions."""

import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import html

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Post, Comment, Author, CollectionResult, CollectionConfig, ForumSource
from collectors.base_collector import BaseCollector


logger = logging.getLogger(__name__)


class StackOverflowCollector(BaseCollector):
    """Collector for Stack Overflow questions and answers."""
    
    # Stack Exchange API
    BASE_URL = "https://api.stackexchange.com/2.3"
    
    def __init__(self, config: CollectionConfig, api_key: Optional[str] = None):
        super().__init__(config)
        self.api_key = api_key
        self._site = config.custom_params.get('site', 'stackoverflow')
        self._tags = config.custom_params.get('tags', [])
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.STACK_OVERFLOW
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        # Stack Exchange API requires these headers
        headers['Accept-Encoding'] = 'gzip'
        return headers
    
    def _get_default_params(self) -> Dict[str, str]:
        """Get default parameters for Stack Exchange API."""
        params = {
            'site': self._site,
            'filter': 'withbody',  # Include question body
        }
        if self.api_key:
            params['key'] = self.api_key
        return params
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot questions from Stack Overflow."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # Get hot questions
            endpoint = "/questions"
            params = {
                **self._get_default_params(),
                'order': 'desc',
                'sort': 'hot',
                'pagesize': min(limit, 100)
            }
            
            data = await self._make_request(endpoint, params)
            
            if not data or 'items' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No data returned from API"
                )
            
            for item in data['items']:
                post = self._parse_question(item)
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
            logger.error(f"Error collecting Stack Overflow posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    def _parse_question(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Stack Overflow question data into Post object."""
        try:
            author = None
            if data.get('owner'):
                owner = data['owner']
                author = Author(
                    username=owner.get('display_name', 'Unknown'),
                    profile_url=owner.get('link'),
                    reputation=owner.get('reputation'),
                    avatar_url=owner.get('profile_image')
                )
            
            created_at = datetime.fromtimestamp(data.get('creation_date', 0))
            
            # Clean HTML from content
            content = data.get('body', '')
            if content:
                content = html.unescape(content)
            
            post = Post(
                id=str(data['question_id']),
                title=html.unescape(data.get('title', '')),
                source=self.source,
                url=data.get('link', f"https://stackoverflow.com/questions/{data['question_id']}"),
                author=author,
                content=content,
                created_at=created_at,
                upvotes=data.get('score', 0),
                comments_count=data.get('answer_count', 0),
                views=data.get('view_count', 0),
                tags=data.get('tags', []),
                metadata={
                    'is_answered': data.get('is_answered', False),
                    'accepted_answer_id': data.get('accepted_answer_id'),
                    'answer_count': data.get('answer_count', 0),
                    'bounty_amount': data.get('bounty_amount'),
                    'closed_reason': data.get('closed_reason'),
                    'last_activity_date': datetime.fromtimestamp(data['last_activity_date']) if data.get('last_activity_date') else None
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Stack Overflow question: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific question."""
        endpoint = f"/questions/{post_id}"
        params = {
            **self._get_default_params(),
            'filter': 'withbody'
        }
        
        data = await self._make_request(endpoint, params)
        
        if not data or 'items' not in data or not data['items']:
            return None
        
        post = self._parse_question(data['items'][0])
        
        if post:
            # Fetch answers
            answers = await self._fetch_answers(post_id)
            post.comments = answers  # Store answers as comments for consistency
        
        return post
    
    async def _fetch_answers(self, question_id: str, limit: Optional[int] = None) -> List[Comment]:
        """Fetch answers for a question."""
        limit = limit or self.config.max_comments_per_post
        
        endpoint = f"/questions/{question_id}/answers"
        params = {
            **self._get_default_params(),
            'order': 'desc',
            'sort': 'votes',
            'pagesize': min(limit, 100)
        }
        
        data = await self._make_request(endpoint, params)
        
        if not data or 'items' not in data:
            return []
        
        answers = []
        for item in data['items']:
            author = None
            if item.get('owner'):
                owner = item['owner']
                author = Author(
                    username=owner.get('display_name', 'Unknown'),
                    profile_url=owner.get('link'),
                    reputation=owner.get('reputation'),
                    avatar_url=owner.get('profile_image')
                )
            
            answer = Comment(
                id=str(item['answer_id']),
                author=author,
                content=html.unescape(item.get('body', '')),
                created_at=datetime.fromtimestamp(item.get('creation_date', 0)),
                upvotes=item.get('score', 0),
                parent_id=question_id,
                url=item.get('link', '')
            )
            
            # Check if this is the accepted answer
            if item.get('is_accepted'):
                answer.metadata = {'is_accepted': True}
            
            answers.append(answer)
        
        return answers
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific question."""
        limit = limit or self.config.max_comments_per_post
        
        endpoint = f"/questions/{post_id}/comments"
        params = {
            **self._get_default_params(),
            'order': 'desc',
            'sort': 'votes',
            'pagesize': min(limit, 100)
        }
        
        data = await self._make_request(endpoint, params)
        
        if not data or 'items' not in data:
            return []
        
        comments = []
        for item in data['items']:
            author = None
            if item.get('owner'):
                owner = item['owner']
                author = Author(
                    username=owner.get('display_name', 'Unknown'),
                    profile_url=owner.get('link'),
                    reputation=owner.get('reputation')
                )
            
            comment = Comment(
                id=str(item['comment_id']),
                author=author,
                content=html.unescape(item.get('body', '')),
                created_at=datetime.fromtimestamp(item.get('creation_date', 0)),
                upvotes=item.get('score', 0),
                parent_id=post_id
            )
            comments.append(comment)
        
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
            'is_accepted': comment.metadata.get('is_accepted', False) if comment.metadata else False
        }
    
    async def search_posts(
        self, 
        query: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Search for questions on Stack Overflow."""
        limit = limit or self.config.max_posts
        
        endpoint = "/search/advanced"
        params = {
            **self._get_default_params(),
            'q': query,
            'order': 'desc',
            'sort': 'relevance',
            'pagesize': min(limit, 100)
        }
        
        # Add tag filter if configured
        if self._tags:
            params['tagged'] = ';'.join(self._tags)
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data or 'items' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No search results found"
                )
            
            posts = []
            for item in data['items']:
                post = self._parse_question(item)
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
            logger.error(f"Error searching Stack Overflow: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def collect_by_tags(
        self, 
        tags: List[str], 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Collect questions by specific tags."""
        limit = limit or self.config.max_posts
        
        endpoint = "/questions"
        params = {
            **self._get_default_params(),
            'order': 'desc',
            'sort': 'hot',
            'tagged': ';'.join(tags),
            'pagesize': min(limit, 100)
        }
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data or 'items' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No questions found for tags"
                )
            
            posts = []
            for item in data['items']:
                post = self._parse_question(item)
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
            logger.error(f"Error collecting by tags: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
