

"""Douban Group collector for gathering hot posts from Douban Groups."""

import asyncio
import re
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import html
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Post, Comment, Author, CollectionResult, CollectionConfig, ForumSource
from collectors.base_collector import BaseCollector


logger = logging.getLogger(__name__)


class DoubanCollector(BaseCollector):
    """Collector for Douban Group posts and discussions.
    
    Douban Groups are discussion forums on Douban, a Chinese social networking
    service. This collector scrapes hot topics from various Douban groups.
    
    Note: Douban doesn't provide an official public API for groups,
    so this collector uses web scraping techniques.
    """
    
    BASE_URL = "https://www.douban.com"
    API_BASE_URL = "https://douban.com/j"
    
    # Popular Douban groups for tech/lifestyle content
    DEFAULT_GROUPS = [
        'gossip',       # 吃瓜贴
        'tech',         # 技术
        'programmer',   # 程序员
        'python',       # Python
        'ai',           # AI人工智能
        'startup',      # 创业
        'remote',       # 远程工作
        'book',         # 书籍
        'movie',        # 电影
        'travel',       # 旅行
    ]
    
    def __init__(self, config: CollectionConfig, cookie: Optional[str] = None):
        super().__init__(config)
        self.cookie = cookie
        self._groups = config.custom_params.get('groups', self.DEFAULT_GROUPS)
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.DOUBAN
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    def _get_headers(self) -> Dict[str, str]:
        headers = super()._get_headers()
        headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache',
            'Referer': 'https://www.douban.com/',
        })
        if self.cookie:
            headers['Cookie'] = self.cookie
        return headers
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot posts from Douban groups."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # Collect from each configured group
            for group_name in self._groups:
                try:
                    posts = await self._collect_group_hot(group_name, limit // len(self._groups) + 1)
                    all_posts.extend(posts)
                except Exception as e:
                    logger.error(f"Error collecting from Douban group '{group_name}': {e}")
                    continue
            
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
            logger.error(f"Error collecting Douban posts: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def _collect_group_hot(self, group_name: str, limit: int) -> List[Post]:
        """Collect hot posts from a specific Douban group."""
        posts = []
        
        # Try different URL patterns for Douban groups
        urls_to_try = [
            f"/group/{group_name}/",
            f"/group/{group_name}/hot",
            f"/group/{group_name}?sort=hot",
        ]
        
        for endpoint in urls_to_try:
            try:
                data = await self._make_request(endpoint)
                
                if data:
                    # Parse HTML response (Douban returns HTML, not JSON)
                    parsed_posts = await self._parse_group_page(data, group_name)
                    if parsed_posts:
                        posts.extend(parsed_posts)
                        break
                        
            except Exception as e:
                logger.debug(f"Failed to fetch from {endpoint}: {e}")
                continue
        
        return posts[:limit]
    
    async def _parse_group_page(self, html_content: str, group_name: str) -> List[Post]:
        """Parse Douban group page HTML to extract posts."""
        posts = []
        
        try:
            # Use regex to extract topic information from HTML
            # This is a simplified parser - in production, consider using BeautifulSoup
            
            # Pattern for topic list items
            topic_pattern = r'<a[^>]+href="https://www\.douban\.com/group/topic/(\d+)/"[^>]*>([^<]+)</a>'
            author_pattern = r'<a[^>]+class="[^"]*author[^"]*"[^>]*>([^<]+)</a>'
            reply_pattern = r'(\d+)\s*回应'
            time_pattern = r'(\d{4}-\d{2}-\d{2}|\d+小时前|\d+分钟前|昨天|今天)'
            
            topics = re.findall(topic_pattern, html_content)
            replies = re.findall(reply_pattern, html_content)
            
            for i, (topic_id, title) in enumerate(topics):
                try:
                    # Clean title
                    title = html.unescape(title.strip())
                    
                    # Get reply count if available
                    comments_count = 0
                    if i < len(replies):
                        comments_count = int(replies[i])
                    
                    post = Post(
                        id=topic_id,
                        title=title,
                        source=self.source,
                        url=f"https://www.douban.com/group/topic/{topic_id}",
                        created_at=datetime.now(),  # Would need more parsing for actual time
                        comments_count=comments_count,
                        tags=[group_name],
                        category=group_name,
                        metadata={
                            'group': group_name,
                            'group_url': f"https://www.douban.com/group/{group_name}/"
                        }
                    )
                    posts.append(post)
                    
                except Exception as e:
                    logger.error(f"Error parsing topic {topic_id}: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Error parsing Douban group page: {e}")
        
        return posts
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        """Get detailed information about a specific Douban topic."""
        endpoint = f"/group/topic/{post_id}/"
        
        try:
            html_content = await self._make_request(endpoint)
            
            if not html_content:
                return None
            
            post = await self._parse_topic_page(html_content, post_id)
            
            if post:
                # Fetch comments
                comments = await self._fetch_comments(post_id)
                post.comments = comments
            
            return post
            
        except Exception as e:
            logger.error(f"Error fetching Douban topic {post_id}: {e}")
            return None
    
    async def _parse_topic_page(self, html_content: str, post_id: str) -> Optional[Post]:
        """Parse a Douban topic page to extract post details."""
        try:
            # Extract title
            title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html_content)
            title = html.unescape(title_match.group(1).strip()) if title_match else f"Topic {post_id}"
            
            # Extract author
            author_match = re.search(r'<a[^>]+class="[^"]*from-app[^"]*"[^>]*>([^<]+)</a>', html_content)
            author_name = author_match.group(1).strip() if author_match else "匿名用户"
            
            author = Author(
                username=author_name,
                profile_url=f"https://www.douban.com/people/{author_name}/"
            )
            
            # Extract content
            content_match = re.search(r'<div[^>]+class="[^"]*topic-content[^"]*"[^>]*>(.*?)</div>', 
                                     html_content, re.DOTALL)
            content = ""
            if content_match:
                content = re.sub(r'<[^>]+>', '', content_match.group(1))
                content = html.unescape(content.strip())
            
            # Extract group name
            group_match = re.search(r'douban\.com/group/([^/]+)/', html_content)
            group_name = group_match.group(1) if group_match else "unknown"
            
            # Extract time
            time_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', html_content)
            created_at = None
            if time_match:
                try:
                    created_at = datetime.strptime(time_match.group(1), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    created_at = datetime.now()
            
            # Extract reply count
            reply_match = re.search(r'(\d+)\s*回应', html_content)
            comments_count = int(reply_match.group(1)) if reply_match else 0
            
            post = Post(
                id=post_id,
                title=title,
                source=self.source,
                url=f"https://www.douban.com/group/topic/{post_id}",
                author=author,
                content=content[:5000] if content else None,  # Limit content length
                created_at=created_at,
                comments_count=comments_count,
                tags=[group_name],
                category=group_name,
                metadata={
                    'group': group_name,
                    'group_url': f"https://www.douban.com/group/{group_name}/"
                }
            )
            
            return post
            
        except Exception as e:
            logger.error(f"Error parsing Douban topic page: {e}")
            return None
    
    async def _fetch_comments(self, topic_id: str, limit: Optional[int] = None) -> List[Comment]:
        """Fetch comments for a Douban topic."""
        limit = limit or self.config.max_comments_per_post
        comments = []
        
        # Douban uses pagination for comments
        page = 0
        while len(comments) < limit:
            endpoint = f"/group/topic/{topic_id}/?start={page * 100}"
            
            try:
                html_content = await self._make_request(endpoint)
                
                if not html_content:
                    break
                
                page_comments = await self._parse_comments_page(html_content, topic_id)
                
                if not page_comments:
                    break
                
                comments.extend(page_comments)
                page += 1
                
                if len(page_comments) < 100:
                    break
                    
            except Exception as e:
                logger.error(f"Error fetching comments page {page}: {e}")
                break
        
        return comments[:limit]
    
    async def _parse_comments_page(self, html_content: str, topic_id: str) -> List[Comment]:
        """Parse comments from a Douban topic page."""
        comments = []
        
        try:
            # Pattern for comment items
            comment_pattern = r'<div[^>]+class="[^"]*reply-item[^"]*"[^>]*data-cid="(\d+)"[^>]*>(.*?)</div>'
            author_pattern = r'<a[^>]+class="[^"]*reply-author[^"]*"[^>]*>([^<]+)</a>'
            content_pattern = r'<p[^>]+class="[^"]*reply-content[^"]*"[^>]*>(.*?)</p>'
            time_pattern = r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'
            
            comment_blocks = re.findall(comment_pattern, html_content, re.DOTALL)
            
            for comment_id, block in comment_blocks:
                try:
                    # Extract author
                    author_match = re.search(author_pattern, block)
                    author_name = author_match.group(1).strip() if author_match else "匿名用户"
                    
                    author = Author(
                        username=author_name,
                        profile_url=f"https://www.douban.com/people/{author_name}/"
                    )
                    
                    # Extract content
                    content_match = re.search(content_pattern, block, re.DOTALL)
                    content = ""
                    if content_match:
                        content = re.sub(r'<[^>]+>', '', content_match.group(1))
                        content = html.unescape(content.strip())
                    
                    # Extract time
                    time_match = re.search(time_pattern, block)
                    created_at = datetime.now()
                    if time_match:
                        try:
                            created_at = datetime.strptime(time_match.group(1), "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass
                    
                    comment = Comment(
                        id=comment_id,
                        author=author,
                        content=content[:2000] if content else '',
                        created_at=created_at,
                        parent_id=topic_id,
                        url=f"https://www.douban.com/group/topic/{topic_id}/#reply_{comment_id}"
                    )
                    
                    comments.append(comment)
                    
                except Exception as e:
                    logger.error(f"Error parsing comment: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Error parsing comments page: {e}")
        
        return comments
    
    async def get_post_comments(
        self, 
        post_id: str, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get comments for a specific Douban topic."""
        comments = await self._fetch_comments(post_id, limit)
        return [self._comment_to_dict(c) for c in comments]
    
    def _comment_to_dict(self, comment: Comment) -> Dict[str, Any]:
        """Convert Comment object to dictionary."""
        return {
            'id': comment.id,
            'author': comment.author.username if comment.author else None,
            'content': comment.content[:500] if comment.content else '',
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
        """Search for posts across Douban groups."""
        limit = limit or self.config.max_posts
        
        endpoint = "/search"
        params = {
            'q': query,
            'cat': '1013',  # Group category
            'start': 0,
            'limit': min(limit, 50)
        }
        
        try:
            html_content = await self._make_request(endpoint, params)
            
            if not html_content:
                return CollectionResult(
                    source=self.source,
                    posts=[],
                    success=False,
                    error_message="No search results found"
                )
            
            posts = await self._parse_search_results(html_content)
            
            filtered_posts = self._apply_filters(posts)
            
            return CollectionResult(
                source=self.source,
                posts=filtered_posts[:limit],
                success=True,
                total_count=len(posts),
                filtered_count=len(filtered_posts)
            )
            
        except Exception as e:
            logger.error(f"Error searching Douban: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def _parse_search_results(self, html_content: str) -> List[Post]:
        """Parse Douban search results."""
        posts = []
        
        try:
            # Pattern for search result items
            result_pattern = r'<a[^>]+href="https://www\.douban\.com/group/topic/(\d+)/"[^>]*class="[^"]*result-title[^"]*"[^>]*>([^<]+)</a>'
            
            results = re.findall(result_pattern, html_content)
            
            for topic_id, title in results:
                title = html.unescape(title.strip())
                
                post = Post(
                    id=topic_id,
                    title=title,
                    source=self.source,
                    url=f"https://www.douban.com/group/topic/{topic_id}",
                    created_at=datetime.now(),
                    metadata={
                        'source': 'search'
                    }
                )
                posts.append(post)
            
        except Exception as e:
            logger.error(f"Error parsing search results: {e}")
        
        return posts
    
    async def collect_by_group(
        self, 
        group_name: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Collect posts from a specific Douban group."""
        limit = limit or self.config.max_posts
        
        try:
            posts = await self._collect_group_hot(group_name, limit)
            
            filtered_posts = self._apply_filters(posts)
            
            return CollectionResult(
                source=self.source,
                posts=filtered_posts[:limit],
                success=True,
                total_count=len(posts),
                filtered_count=len(filtered_posts)
            )
            
        except Exception as e:
            logger.error(f"Error collecting from group {group_name}: {e}")
            return CollectionResult(
                source=self.source,
                posts=[],
                success=False,
                error_message=str(e)
            )
    
    async def get_trending_groups(self) -> List[Dict[str, Any]]:
        """Get a list of trending/hot Douban groups."""
        endpoint = "/group/explore"
        
        try:
            html_content = await self._make_request(endpoint)
            
            if not html_content:
                return []
            
            groups = []
            # Parse group listings
            group_pattern = r'<a[^>]+href="https://www\.douban\.com/group/([^/]+)/"[^>]*>([^<]+)</a>'
            
            matches = re.findall(group_pattern, html_content)
            
            for group_id, group_name in matches:
                groups.append({
                    'id': group_id,
                    'name': html.unescape(group_name.strip()),
                    'url': f"https://www.douban.com/group/{group_id}/"
                })
            
            return groups
            
        except Exception as e:
            logger.error(f"Error getting trending groups: {e}")
            return []
