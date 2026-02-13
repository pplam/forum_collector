
"""Storage manager for forum collector."""

import os
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Post, CollectionResult, HotPost
from .base_storage import BaseStorage
from .json_storage import JSONStorage
from .sqlite_storage import SQLiteStorage


logger = logging.getLogger(__name__)


class StorageManager:
    """Manager for storage backends.
    
    Provides a unified interface for different storage backends.
    """
    
    def __init__(self, storage_type: str = "json", storage_path: str = "./data"):
        """Initialize storage manager.
        
        Args:
            storage_type: Type of storage backend ('json' or 'sqlite')
            storage_path: Path for storage files
        """
        self.storage_type = storage_type
        self.storage_path = storage_path
        self._storage: Optional[BaseStorage] = None
    
    @property
    def storage(self) -> BaseStorage:
        """Get the storage backend instance."""
        if self._storage is None:
            if self.storage_type == "sqlite":
                self._storage = SQLiteStorage(f"{self.storage_path}/forum_collector.db")
            else:
                self._storage = JSONStorage(self.storage_path)
        return self._storage
    
    async def save_posts(self, posts: List[Post], source: str) -> bool:
        """Save posts to storage."""
        return await self.storage.save_posts(posts, source)
    
    async def get_posts(
        self,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = 'created_at',
        descending: bool = True
    ) -> List[Post]:
        """Retrieve posts from storage."""
        return await self.storage.get_posts(source, limit, offset, order_by, descending)
    
    async def get_post(self, post_id: str) -> Optional[Post]:
        """Get a specific post by ID."""
        return await self.storage.get_post(post_id)
    
    async def delete_post(self, post_id: str) -> bool:
        """Delete a post from storage."""
        return await self.storage.delete_post(post_id)
    
    async def save_collection_result(self, result: CollectionResult) -> bool:
        """Save collection result metadata."""
        return await self.storage.save_collection_result(result)
    
    async def get_collection_history(
        self,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get collection history."""
        return await self.storage.get_collection_history(source, limit)
    
    async def save_hot_posts(self, hot_posts: List[HotPost]) -> bool:
        """Save hot posts with analysis data."""
        return await self.storage.save_hot_posts(hot_posts)
    
    async def search_posts(
        self,
        query: str,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Post]:
        """Search for posts matching a query."""
        return await self.storage.search_posts(query, source, limit)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        return await self.storage.get_stats()
    
    async def clear_old_posts(self, days: int = 30) -> int:
        """Clear posts older than specified days."""
        return await self.storage.clear_old_posts(days)
    
    async def close(self) -> None:
        """Close the storage connection."""
        if self._storage:
            await self._storage.close()
    
    async def get_posts_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        source: Optional[str] = None,
        limit: int = 100
    ) -> List[Post]:
        """Get posts within a date range.
        
        Args:
            start_date: Start of date range
            end_date: End of date range
            source: Filter by source (optional)
            limit: Maximum number of results
            
        Returns:
            List of Post objects within the date range
        """
        # Get all posts and filter by date
        all_posts = await self.get_posts(source=source, limit=10000)
        
        filtered_posts = []
        for post in all_posts:
            if post.created_at:
                if start_date <= post.created_at <= end_date:
                    filtered_posts.append(post)
            if len(filtered_posts) >= limit:
                break
        
        return filtered_posts
    
    async def get_top_posts(
        self,
        source: Optional[str] = None,
        limit: int = 10,
        by: str = 'score'
    ) -> List[Post]:
        """Get top posts by metric.
        
        Args:
            source: Filter by source (optional)
            limit: Maximum number of results
            by: Metric to sort by ('score', 'upvotes', 'comments')
            
        Returns:
            List of top Post objects
        """
        order_by_map = {
            'score': 'score',
            'upvotes': 'upvotes',
            'comments': 'comments_count'
        }
        
        order_by = order_by_map.get(by, 'score')
        
        return await self.get_posts(
            source=source,
            limit=limit,
            order_by=order_by,
            descending=True
        )
    
    async def get_unique_sources(self) -> List[str]:
        """Get list of unique sources in storage.
        
        Returns:
            List of source names
        """
        stats = await self.get_stats()
        return list(stats.get('posts_by_source', {}).keys())
    
    async def export_posts(
        self,
        output_path: str,
        source: Optional[str] = None,
        format: str = 'json'
    ) -> bool:
        """Export posts to a file.
        
        Args:
            output_path: Path to export file
            source: Filter by source (optional)
            format: Export format ('json' or 'csv')
            
        Returns:
            True if successful, False otherwise
        """
        import json
        import csv
        
        posts = await self.get_posts(source=source, limit=100000)
        
        try:
            if format == 'json':
                posts_data = []
                for post in posts:
                    posts_data.append({
                        'id': post.id,
                        'title': post.title,
                        'source': post.source.value,
                        'url': post.url,
                        'author': post.author.username if post.author else None,
                        'content': post.content,
                        'created_at': post.created_at.isoformat() if post.created_at else None,
                        'upvotes': post.upvotes,
                        'comments_count': post.comments_count,
                        'tags': post.tags,
                        'category': post.category,
                        'score': post.score
                    })
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(posts_data, f, indent=2, ensure_ascii=False)
            
            elif format == 'csv':
                with open(output_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'id', 'title', 'source', 'url', 'author', 
                        'created_at', 'upvotes', 'comments_count', 'score'
                    ])
                    
                    for post in posts:
                        writer.writerow([
                            post.id,
                            post.title,
                            post.source.value,
                            post.url,
                            post.author.username if post.author else '',
                            post.created_at.isoformat() if post.created_at else '',
                            post.upvotes,
                            post.comments_count,
                            post.score
                        ])
            
            logger.info(f"Exported {len(posts)} posts to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting posts: {e}")
            return False
    
    async def import_posts(
        self,
        input_path: str,
        format: str = 'json'
    ) -> int:
        """Import posts from a file.
        
        Args:
            input_path: Path to import file
            format: Import format ('json')
            
        Returns:
            Number of posts imported
        """
        import json
        
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            posts = []
            for item in data:
                post = Post(
                    id=item['id'],
                    title=item['title'],
                    source=ForumSource(item['source']),
                    url=item['url'],
                    content=item.get('content'),
                    upvotes=item.get('upvotes', 0),
                    comments_count=item.get('comments_count', 0),
                    tags=item.get('tags', []),
                    category=item.get('category')
                )
                posts.append(post)
            
            # Save imported posts
            if posts:
                await self.save_posts(posts, 'import')
            
            logger.info(f"Imported {len(posts)} posts from {input_path}")
            return len(posts)
            
        except Exception as e:
            logger.error(f"Error importing posts: {e}")
            return 0


# Import ForumSource for export_posts
from models import ForumSource
