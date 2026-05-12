

"""Douban Group collector for gathering hot posts from Douban Groups."""

import asyncio
import re
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import logging
import html
import json
import aiohttp
import backoff

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
    # Default groups as fallback if hot groups discovery fails
    DEFAULT_GROUPS = [
        'ai',           # AI人工智能 - this one works!
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
        # Track if we should use proxy (we don't want to for Douban)
        self._use_proxy = False
    
    async def __aenter__(self):
        """Async context manager entry - override to use proxy for Douban."""
        self.session = aiohttp.ClientSession(
            headers=self._get_headers(),
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    @property
    def source(self) -> ForumSource:
        return ForumSource.DOUBAN
    
    @property
    def base_url(self) -> str:
        return self.BASE_URL
    
    def _get_headers(self) -> Dict[str, str]:
        # Minimal headers to avoid being blocked
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        if self.cookie:
            headers['Cookie'] = self.cookie
        return headers
    
    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=3,
        max_time=30
    )
    async def _make_request(
        self, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        method: str = 'GET',
        allow_redirects: bool = True
    ) -> Optional[str]:
        """Make an HTTP request for HTML content."""
        import time
        
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Get proxy from environment for Douban (since IP is blocked)
        proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
        
        start_time = time.time()
        
        # Log request details at DEBUG level
        log_params = f" params={params}" if params else ""
        logger.debug(f"[HTTP Request] {method} {url}{log_params}")
        
        try:
            async with self.session.request(
                method, url, 
                params=params, 
                proxy=proxy,
                allow_redirects=False  # Don't auto-follow redirects to handle them manually
            ) as response:
                elapsed = time.time() - start_time
                
                # Log response at INFO level
                status_emoji = "✓" if response.status < 400 else "✗"
                logger.info(f"[HTTP] {status_emoji} {method} {url} -> {response.status} ({elapsed:.2f}s)")
                
                # Handle redirects manually
                if response.status in (301, 302, 303, 307, 308):
                    redirect_url = response.headers.get('Location')
                    if redirect_url:
                        # Handle relative redirects
                        if redirect_url.startswith('/'):
                            redirect_url = f"{self.base_url}{redirect_url}"
                        logger.debug(f"[HTTP Redirect] {url} -> {redirect_url}")
                        # Make request to redirect URL without proxy
                        async with self.session.request(
                            method, redirect_url, 
                            params=params,
                            allow_redirects=False
                        ) as redirect_response:
                            redirect_elapsed = time.time() - start_time
                            status_emoji2 = "✓" if redirect_response.status < 400 else "✗"
                            logger.info(f"[HTTP] {status_emoji2} {method} {redirect_url} -> {redirect_response.status} ({redirect_elapsed:.2f}s)")
                            # Check for another redirect
                            if redirect_response.status in (301, 302, 303, 307, 308):
                                # Handle second redirect
                                redirect_url2 = redirect_response.headers.get('Location')
                                if redirect_url2:
                                    if redirect_url2.startswith('/'):
                                        redirect_url2 = f"{self.base_url}{redirect_url2}"
                                    logger.debug(f"[HTTP Redirect] {redirect_url} -> {redirect_url2}")
                                    async with self.session.request(
                                        method, redirect_url2, 
                                        params=params,
                                        allow_redirects=False
                                    ) as redirect_response2:
                                        final_elapsed = time.time() - start_time
                                        status_emoji3 = "✓" if redirect_response2.status < 400 else "✗"
                                        logger.info(f"[HTTP] {status_emoji3} {method} {redirect_url2} -> {redirect_response2.status} ({final_elapsed:.2f}s)")
                                        if redirect_response2.status == 200:
                                            return await redirect_response2.text()
                                        elif redirect_response2.status == 403:
                                            logger.warning(f"[HTTP Forbidden] Access denied to {redirect_url2}")
                                            return None
                                        redirect_response2.raise_for_status()
                                        return await redirect_response2.text()
                            
                            if redirect_response.status == 200:
                                return await redirect_response.text()
                            elif redirect_response.status == 403:
                                logger.warning(f"[HTTP Forbidden] Access denied to {redirect_url}")
                                return None
                            redirect_response.raise_for_status()
                            return await redirect_response.text()
                
                if response.status == 429:
                    # Rate limited - wait and retry
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"[HTTP Rate Limited] {url} - waiting {retry_after}s before retry")
                    await asyncio.sleep(retry_after)
                    return await self._make_request(endpoint, params, method, allow_redirects)
                
                if response.status == 404:
                    logger.warning(f"[HTTP Not Found] {url}")
                    return None
                
                if response.status == 400:
                    logger.warning(f"[HTTP Bad Request] {url}")
                    return None
                
                if response.status == 403:
                    logger.warning(f"[HTTP Forbidden] Access denied to {url}")
                    return None
                
                response.raise_for_status()
                
                # Return text content (HTML) instead of JSON
                try:
                    return await response.text()
                except Exception as e:
                    # Handle brotli decoding errors
                    if 'brotli' in str(e).lower() or 'content-encoding' in str(e).lower():
                        logger.warning(f"[HTTP Decode Error] Content decoding error for {url}, trying raw read")
                        # Try reading raw content
                        return await response.read()
                    raise
                
        except aiohttp.ClientError as e:
            elapsed = time.time() - start_time
            logger.error(f"[HTTP Error] {method} {url} failed after {elapsed:.2f}s: {e}")
            raise
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"[HTTP Timeout] {method} {url} timed out after {elapsed:.2f}s")
            raise
    
    async def collect_hot_posts(self, limit: Optional[int] = None) -> CollectionResult:
        """Collect hot posts from Douban groups."""
        limit = limit or self.config.max_posts
        all_posts = []
        
        try:
            # First, try to discover hot groups
            groups_to_collect = await self._discover_hot_groups()
            
            if not groups_to_collect:
                # Fall back to configured groups if discovery fails
                logger.warning("Using default groups as fallback")
                groups_to_collect = self._groups
            
            # Collect from each group
            for group_name in groups_to_collect:
                try:
                    posts = await self._collect_group_hot(group_name, limit // len(groups_to_collect) + 1)
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
        
        # For numeric group IDs (new style), just use the base URL
        # For text-based group names (old style), try different patterns
        if group_name.isdigit():
            urls_to_try = [
                f"/group/{group_name}/",
            ]
        else:
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
                        created_at=datetime.now(timezone.utc),  # Would need more parsing for actual time
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
                    created_at = datetime.now(timezone.utc)
            
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
                    created_at = datetime.now(timezone.utc)
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
                    created_at=datetime.now(timezone.utc),
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
    
    async def _discover_hot_groups(self) -> List[str]:
        """Discover hot groups from Douban's hot groups page."""
        url = f"{self.BASE_URL}/group/explore/hot_groups"
        
        try:
            html_content = await self._make_request("/group/explore/hot_groups")
            
            if not html_content:
                logger.warning("Failed to fetch hot groups page")
                return []
            
            # Parse group links from the hot groups page
            # Pattern for group links: https://www.douban.com/group/xxxxx/
            # Groups have numeric IDs or short names
            group_pattern = r'href="https://www\.douban\.com/group/([a-zA-Z0-9]+)/"'
            matches = re.findall(group_pattern, html_content)
            
            # Filter to get valid group names (alphanumeric, not too long)
            groups = [m for m in matches if len(m) < 20 and m.isalnum()]
            
            # Remove duplicates while preserving order
            seen = set()
            unique_groups = []
            for g in groups:
                if g not in seen:
                    seen.add(g)
                    unique_groups.append(g)
            
            logger.info(f"Discovered {len(unique_groups)} hot groups")
            return unique_groups[:10]  # Limit to top 10 groups
            
        except Exception as e:
            logger.error(f"Error discovering hot groups: {e}")
            return []
