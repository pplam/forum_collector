
"""Zhihu collector for gathering hot questions and answers from Zhihu."""

import asyncio
import re
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


class ZhihuCollector(BaseCollector):
    """Collector for Zhihu questions and answers."""
    
    BASE_URL = "https://www.zhihu.com/api/v3"
    
    def __init__(self, config: CollectionConfig, token: Optional[str] = None):
        super().__init__(config)
        self.token = token
        self._topics = config.custom_params.get('topics', [])
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.ZHIHU
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        headers['x-requested-with'] = 'fetch'
        if self.token:
            headers['authorization'] = f"Bearer {self.token}"
        return headers
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot questions from Zhihu."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # Get hot questions
            endpoint = "/feed/topstory/hot-lists/total"
            params = {
                'limit': min(limit, 50),
                'desktop': 'true'
            }
            
            data = await self._make_request(endpoint, params)
            
            if not data or 'data' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No data returned from API"
                )
            
            for item in data['data']:
                post = self._parse_hot_item(item)
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
            logger.error(f"Error collecting Zhihu posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    def _parse_hot_item(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Zhihu hot list item into Post object."""
        try:
            target = data.get('target', {})
            question_data = target.get('type') == 'question' and target or target.get('question', target)
            
            author = None
            if target.get('author'):
                author_data = target['author']
                author = Author(
                    username=author_data.get('name', '匿名用户'),
                    profile_url=f"https://www.zhihu.com/people/{author_data.get('url_token', '')}",
                    avatar_url=author_data.get('avatar_url'),
                    bio=author_data.get('headline')
                )
            
            created_at = None
            if question_data.get('created'):
                created_at = datetime.fromtimestamp(question_data['created'])
            
            # Clean HTML from title
            title = question_data.get('title', '')
            title = re.sub(r'<[^>]+>', '', title)
            title = html.unescape(title)
            
            # Extract excerpt
            excerpt = target.get('excerpt', '') or question_data.get('excerpt', '')
            
            post = Post(
                id=str(question_data.get('id', '')),
                title=title,
                source=self.source,
                url=f"https://www.zhihu.com/question/{question_data.get('id')}",
                author=author,
                content=excerpt,
                summary=excerpt,
                created_at=created_at,
                upvotes=target.get('voteup_count', 0),
                comments_count=target.get('comment_count', 0),
                views=data.get('detail_text', ''),  # Hot list shows view count as text
                metadata={
                    'hot_value': data.get('hot_value', 0),
                    'hot_value_desc': data.get('hot_value_desc', ''),
                    'question_type': question_data.get('type'),
                    'answer_count': question_data.get('answer_count', 0),
                    'follower_count': question_data.get('follower_count', 0)
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Zhihu hot item: {e}")
            return None
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific question."""
        endpoint = f"/questions/{post_id}"
        params = {'include': 'detail,excerpt'}
        
        data = await self._make_request(endpoint, params)
        
        if not data:
            return None
        
        post = self._parse_question(data)
        
        if post:
            # Fetch answers
            answers = await self._fetch_answers(post_id)
            post.comments = answers  # Store answers as comments
        
        return post
    
    def _parse_question(self, data: Dict[str, Any]) -> Optional[Post]:
        """Parse Zhihu question data."""
        try:
            author = None
            if data.get('author'):
                author_data = data['author']
                author = Author(
                    username=author_data.get('name', '匿名用户'),
                    profile_url=f"https://www.zhihu.com/people/{author_data.get('url_token', '')}",
                    avatar_url=author_data.get('avatar_url'),
                    bio=author_data.get('headline')
                )
            
            created_at = datetime.fromtimestamp(data['created']) if data.get('created') else None
            
            title = data.get('title', '')
            title = re.sub(r'<[^>]+>', '', title)
            title = html.unescape(title)
            
            tags = []
            if data.get('topics'):
                tags = [t.get('name', '') for t in data['topics']]
            
            post = Post(
                id=str(data['id']),
                title=title,
                source=self.source,
                url=f"https://www.zhihu.com/question/{data['id']}",
                author=author,
                content=data.get('detail'),
                summary=data.get('excerpt'),
                created_at=created_at,
                upvotes=0,  # Questions don't have votes
                comments_count=data.get('answer_count', 0),
                tags=tags,
                metadata={
                    'answer_count': data.get('answer_count', 0),
                    'follower_count': data.get('follower_count', 0),
                    'comment_count': data.get('comment_count', 0),
                    'visit_count': data.get('visit_count', 0)
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Zhihu question: {e}")
            return None
    
    async def _fetch_answers(
        self, 
        question_id: str, 
        limit: Optional[int] = None
    ) -> List[Comment]:
        """Fetch answers for a question."""
        limit = limit or self.config.max_comments_per_post
        
        endpoint = f"/questions/{question_id}/answers"
        params = {
            'limit': min(limit, 20),
            'sort_by': 'default',  # Can be 'default', 'updated', 'created'
            'include': 'content,excerpt,voteup_count,comment_count,author'
        }
        
        data = await self._make_request(endpoint, params)
        
        if not data or 'data' not in data:
            return []
        
        answers = []
        for item in data['data']:
            answer = self._parse_answer(item)
            if answer:
                answers.append(answer)
        
        return answers
    
    def _parse_answer(self, data: Dict[str, Any]) -> Optional[Comment]:
        """Parse Zhihu answer data."""
        try:
            author = None
            if data.get('author'):
                author_data = data['author']
                author = Author(
                    username=author_data.get('name', '匿名用户'),
                    profile_url=f"https://www.zhihu.com/people/{author_data.get('url_token', '')}",
                    avatar_url=author_data.get('avatar_url'),
                    bio=author_data.get('headline')
                )
            
            content = data.get('content', '')
            # Clean HTML
            content = re.sub(r'<[^>]+>', '', content)
            content = html.unescape(content)
            
            comment = Comment(
                id=str(data['id']),
                author=author,
                content=content[:2000] if content else '',  # Limit content length
                created_at=datetime.fromtimestamp(data['created_time']) if data.get('created_time') else None,
                upvotes=data.get('voteup_count', 0),
                parent_id=str(data.get('question_id')),
                url=f"https://www.zhihu.com/question/{data.get('question_id')}/answer/{data['id']}"
            )
            
            return comment
            
        except Exception as e:
            logger.error(f"Error parsing Zhihu answer: {e}")
            return None
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get answers for a specific question."""
        answers = await self._fetch_answers(post_id, limit)
        return [self._comment_to_dict(a) for a in answers]
    
    def _comment_to_dict(self, comment: Comment) -> Dict[str, Any]:
        """Convert Comment object to dictionary."""
        return {
            'id': comment.id,
            'author': comment.author.username if comment.author else None,
            'content': comment.content[:500] if comment.content else '',  # Truncate for display
            'created_at': comment.created_at.isoformat() if comment.created_at else None,
            'upvotes': comment.upvotes,
            'parent_id': comment.parent_id,
            'url': comment.url
        }
    
    async def search_posts(
        self, 
        query: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Search for questions on Zhihu."""
        limit = limit or self.config.max_posts
        
        endpoint = "/search"
        params = {
            'q': query,
            'type': 'question',
            'limit': min(limit, 20),
            'correct': 1
        }
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data or 'data' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No search results found"
                )
            
            posts = []
            for item in data['data']:
                if item.get('type') == 'question':
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
            logger.error(f"Error searching Zhihu: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def collect_by_topic(
        self, 
        topic_id: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Collect hot questions from a specific topic."""
        limit = limit or self.config.max_posts
        
        endpoint = f"/topics/{topic_id}/feeds/essence"
        params = {
            'limit': min(limit, 20),
            'desktop': 'true'
        }
        
        try:
            data = await self._make_request(endpoint, params)
            
            if not data or 'data' not in data:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message=f"No questions found for topic: {topic_id}"
                )
            
            posts = []
            for item in data['data']:
                if item.get('target'):
                    post = self._parse_hot_item(item)
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
            logger.error(f"Error collecting from topic {topic_id}: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
