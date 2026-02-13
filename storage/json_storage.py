
"""JSON file storage implementation for forum collector."""

import json
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import asyncio
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Post, CollectionResult, HotPost, Comment, Author, ForumSource
from .base_storage import BaseStorage


logger = logging.getLogger(__name__)


class JSONStorage(BaseStorage):
    """JSON file-based storage backend.
    
    Stores posts and collection results in JSON files organized by date and source.
    """
    
    def __init__(self, storage_path: str = "./data"):
        """Initialize JSON storage.
        
        Args:
            storage_path: Base directory for storing JSON files
        """
        self.storage_path = Path(storage_path)
        self.posts_file = self.storage_path / "posts.json"
        self.history_file = self.storage_path / "history.json"
        self.hot_posts_file = self.storage_path / "hot_posts.json"
        self._lock = asyncio.Lock()
        
        # Ensure directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize files if they don't exist
        self._initialize_files()
    
    def _initialize_files(self):
        """Initialize storage files if they don't exist."""
        if not self.posts_file.exists():
            self._write_json(self.posts_file, {"posts": []})
        
        if not self.history_file.exists():
            self._write_json(self.history_file, {"history": []})
        
        if not self.hot_posts_file.exists():
            self._write_json(self.hot_posts_file, {"hot_posts": []})
    
    def _read_json(self, filepath: Path) -> Dict[str, Any]:
        """Read JSON file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.error(f"Error reading {filepath}: {e}")
            return {}
    
    def _write_json(self, filepath: Path, data: Dict[str, Any]) -> bool:
        """Write JSON file."""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            return True
        except Exception as e:
            logger.error(f"Error writing {filepath}: {e}")
            return False
    
    def _post_to_dict(self, post: Post) -> Dict[str, Any]:
        """Convert Post object to dictionary."""
        return {
            'id': post.id,
            'title': post.title,
            'source': post.source.value,
            'url': post.url,
            'author': {
                'username': post.author.username if post.author else None,
                'profile_url': post.author.profile_url if post.author else None,
                'avatar_url': post.author.avatar_url if post.author else None,
            } if post.author else None,
            'content': post.content,
            'summary': post.summary,
            'created_at': post.created_at.isoformat() if post.created_at else None,
            'fetched_at': post.fetched_at.isoformat() if post.fetched_at else None,
            'upvotes': post.upvotes,
            'downvotes': post.downvotes,
            'comments_count': post.comments_count,
            'views': post.views,
            'shares': post.shares,
            'tags': post.tags,
            'category': post.category,
            'language': post.language,
            'metadata': post.metadata,
            'score': post.score
        }
    
    def _dict_to_post(self, data: Dict[str, Any]) -> Post:
        """Convert dictionary to Post object."""
        author = None
        if data.get('author'):
            author = Author(
                username=data['author'].get('username', 'Unknown'),
                profile_url=data['author'].get('profile_url'),
                avatar_url=data['author'].get('avatar_url')
            )
        
        created_at = None
        if data.get('created_at'):
            try:
                created_at = datetime.fromisoformat(data['created_at'])
            except ValueError:
                pass
        
        fetched_at = datetime.now()
        if data.get('fetched_at'):
            try:
                fetched_at = datetime.fromisoformat(data['fetched_at'])
            except ValueError:
                pass
        
        return Post(
            id=data['id'],
            title=data['title'],
            source=ForumSource(data['source']),
            url=data['url'],
            author=author,
            content=data.get('content'),
            summary=data.get('summary'),
            created_at=created_at,
            fetched_at=fetched_at,
            upvotes=data.get('upvotes', 0),
            downvotes=data.get('downvotes', 0),
            comments_count=data.get('comments_count', 0),
            views=data.get('views', 0),
            shares=data.get('shares', 0),
            tags=data.get('tags', []),
            category=data.get('category'),
            language=data.get('language'),
            metadata=data.get('metadata', {})
        )
    
    async def save_posts(self, posts: List[Post], source: str) -> bool:
        """Save posts to JSON storage."""
        async with self._lock:
            data = self._read_json(self.posts_file)
            existing_posts = data.get('posts', [])
            
            # Create a set of existing post IDs for quick lookup
            existing_ids = {p['id'] for p in existing_posts}
            
            # Add new posts (avoid duplicates)
            new_count = 0
            for post in posts:
                if post.id not in existing_ids:
                    existing_posts.append(self._post_to_dict(post))
                    existing_ids.add(post.id)
                    new_count += 1
            
            data['posts'] = existing_posts
            success = self._write_json(self.posts_file, data)
            
            if success:
                logger.info(f"Saved {new_count} new posts from {source}")
            
            return success
    
    async def get_posts(
        self,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = 'created_at',
        descending: bool = True
    ) -> List[Post]:
        """Retrieve posts from JSON storage."""
        data = self._read_json(self.posts_file)
        posts = data.get('posts', [])
        
        # Filter by source if provided
        if source:
            posts = [p for p in posts if p.get('source') == source]
        
        # Sort posts
        reverse_order = descending
        if order_by == 'created_at':
            posts.sort(key=lambda p: p.get('created_at') or '', reverse=reverse_order)
        elif order_by == 'score':
            posts.sort(key=lambda p: p.get('score', 0), reverse=reverse_order)
        elif order_by == 'upvotes':
            posts.sort(key=lambda p: p.get('upvotes', 0), reverse=reverse_order)
        
        # Apply offset and limit
        posts = posts[offset:offset + limit]
        
        return [self._dict_to_post(p) for p in posts]
    
    async def get_post(self, post_id: str) -> Optional[Post]:
        """Get a specific post by ID."""
        data = self._read_json(self.posts_file)
        posts = data.get('posts', [])
        
        for post_data in posts:
            if post_data.get('id') == post_id:
                return self._dict_to_post(post_data)
        
        return None
    
    async def delete_post(self, post_id: str) -> bool:
        """Delete a post from storage."""
        async with self._lock:
            data = self._read_json(self.posts_file)
            posts = data.get('posts', [])
            
            original_count = len(posts)
            posts = [p for p in posts if p.get('id') != post_id]
            
            if len(posts) < original_count:
                data['posts'] = posts
                return self._write_json(self.posts_file, data)
            
            return False
    
    async def save_collection_result(self, result: CollectionResult) -> bool:
        """Save collection result metadata."""
        async with self._lock:
            data = self._read_json(self.history_file)
            history = data.get('history', [])
            
            history_entry = {
                'source': result.source.value,
                'success': result.success,
                'error_message': result.error_message,
                'collected_at': result.collected_at.isoformat(),
                'total_count': result.total_count,
                'filtered_count': result.filtered_count,
                'post_count': len(result.posts)
            }
            
            history.append(history_entry)
            
            # Keep only last 1000 entries
            if len(history) > 1000:
                history = history[-1000:]
            
            data['history'] = history
            return self._write_json(self.history_file, data)
    
    async def get_collection_history(
        self,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get collection history."""
        data = self._read_json(self.history_file)
        history = data.get('history', [])
        
        if source:
            history = [h for h in history if h.get('source') == source]
        
        return history[-limit:]
    
    async def save_hot_posts(self, hot_posts: List[HotPost]) -> bool:
        """Save hot posts with analysis data."""
        async with self._lock:
            data = self._read_json(self.hot_posts_file)
            existing = data.get('hot_posts', [])
            
            for hp in hot_posts:
                entry = {
                    'post': self._post_to_dict(hp.post),
                    'rank': hp.rank,
                    'trending_score': hp.trending_score,
                    'viral_potential': hp.viral_potential,
                    'sentiment': hp.sentiment,
                    'key_topics': hp.key_topics,
                    'analyzed_at': datetime.now().isoformat()
                }
                existing.append(entry)
            
            # Keep only last 500 entries
            if len(existing) > 500:
                existing = existing[-500:]
            
            data['hot_posts'] = existing
            return self._write_json(self.hot_posts_file, data)
    
    async def search_posts(
        self,
        query: str,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Post]:
        """Search for posts matching a query."""
        data = self._read_json(self.posts_file)
        posts = data.get('posts', [])
        
        query_lower = query.lower()
        matching_posts = []
        
        for post_data in posts:
            # Search in title and content
            title = post_data.get('title', '').lower()
            content = (post_data.get('content') or '').lower()
            
            if query_lower in title or query_lower in content:
                if source is None or post_data.get('source') == source:
                    matching_posts.append(post_data)
        
        return [self._dict_to_post(p) for p in matching_posts[:limit]]
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        data = self._read_json(self.posts_file)
        posts = data.get('posts', [])
        
        # Calculate stats
        source_counts = {}
        for post in posts:
            source = post.get('source', 'unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
        
        return {
            'total_posts': len(posts),
            'posts_by_source': source_counts,
            'storage_type': 'json',
            'storage_path': str(self.storage_path)
        }
    
    async def clear_old_posts(self, days: int = 30) -> int:
        """Clear posts older than specified days."""
        async with self._lock:
            data = self._read_json(self.posts_file)
            posts = data.get('posts', [])
            
            cutoff = datetime.now()
            from datetime import timedelta
            cutoff = cutoff - timedelta(days=days)
            
            original_count = len(posts)
            posts = [
                p for p in posts
                if p.get('fetched_at') and datetime.fromisoformat(p['fetched_at']) > cutoff
            ]
            
            deleted_count = original_count - len(posts)
            
            if deleted_count > 0:
                data['posts'] = posts
                self._write_json(self.posts_file, data)
            
            return deleted_count
    
    async def close(self) -> None:
        """Close the storage connection."""
        # No connection to close for JSON storage
        pass
