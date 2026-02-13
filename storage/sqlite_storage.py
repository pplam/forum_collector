
"""SQLite storage implementation for forum collector."""

import sqlite3
import os
import json
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


class SQLiteStorage(BaseStorage):
    """SQLite database storage backend.
    
    Provides efficient storage and querying of posts using SQLite.
    """
    
    def __init__(self, storage_path: str = "./data/forum_collector.db"):
        """Initialize SQLite storage.
        
        Args:
            storage_path: Path to SQLite database file
        """
        self.storage_path = Path(storage_path)
        self.db_path = str(self.storage_path)
        self._lock = asyncio.Lock()
        
        # Ensure directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._initialize_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _initialize_db(self):
        """Initialize database tables."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Posts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                author_username TEXT,
                author_profile_url TEXT,
                author_avatar_url TEXT,
                content TEXT,
                summary TEXT,
                created_at TIMESTAMP,
                fetched_at TIMESTAMP,
                upvotes INTEGER DEFAULT 0,
                downvotes INTEGER DEFAULT 0,
                comments_count INTEGER DEFAULT 0,
                views INTEGER DEFAULT 0,
                shares INTEGER DEFAULT 0,
                tags TEXT,
                category TEXT,
                language TEXT,
                metadata TEXT,
                score REAL
            )
        ''')
        
        # Collection history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collection_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                success INTEGER NOT NULL,
                error_message TEXT,
                collected_at TIMESTAMP,
                total_count INTEGER,
                filtered_count INTEGER,
                post_count INTEGER
            )
        ''')
        
        # Hot posts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hot_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                rank INTEGER,
                trending_score REAL,
                viral_potential REAL,
                sentiment TEXT,
                key_topics TEXT,
                analyzed_at TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            )
        ''')
        
        # Create indexes for faster queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_score ON posts(score)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_fetched_at ON posts(fetched_at)')
        
        conn.commit()
        conn.close()
    
    def _post_to_row(self, post: Post) -> tuple:
        """Convert Post object to database row."""
        return (
            post.id,
            post.title,
            post.source.value,
            post.url,
            post.author.username if post.author else None,
            post.author.profile_url if post.author else None,
            post.author.avatar_url if post.author else None,
            post.content,
            post.summary,
            post.created_at.isoformat() if post.created_at else None,
            post.fetched_at.isoformat() if post.fetched_at else None,
            post.upvotes,
            post.downvotes,
            post.comments_count,
            post.views,
            post.shares,
            json.dumps(post.tags) if post.tags else '[]',
            post.category,
            post.language,
            json.dumps(post.metadata) if post.metadata else '{}',
            post.score
        )
    
    def _row_to_post(self, row: sqlite3.Row) -> Post:
        """Convert database row to Post object."""
        author = None
        if row['author_username']:
            author = Author(
                username=row['author_username'],
                profile_url=row['author_profile_url'],
                avatar_url=row['author_avatar_url']
            )
        
        created_at = None
        if row['created_at']:
            try:
                created_at = datetime.fromisoformat(row['created_at'])
            except ValueError:
                pass
        
        fetched_at = datetime.now()
        if row['fetched_at']:
            try:
                fetched_at = datetime.fromisoformat(row['fetched_at'])
            except ValueError:
                pass
        
        tags = []
        if row['tags']:
            try:
                tags = json.loads(row['tags'])
            except json.JSONDecodeError:
                pass
        
        metadata = {}
        if row['metadata']:
            try:
                metadata = json.loads(row['metadata'])
            except json.JSONDecodeError:
                pass
        
        return Post(
            id=row['id'],
            title=row['title'],
            source=ForumSource(row['source']),
            url=row['url'],
            author=author,
            content=row['content'],
            summary=row['summary'],
            created_at=created_at,
            fetched_at=fetched_at,
            upvotes=row['upvotes'] or 0,
            downvotes=row['downvotes'] or 0,
            comments_count=row['comments_count'] or 0,
            views=row['views'] or 0,
            shares=row['shares'] or 0,
            tags=tags,
            category=row['category'],
            language=row['language'],
            metadata=metadata
        )
    
    async def save_posts(self, posts: List[Post], source: str) -> bool:
        """Save posts to SQLite storage."""
        def _save():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            new_count = 0
            for post in posts:
                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO posts VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                    ''', self._post_to_row(post))
                    new_count += 1
                except sqlite3.Error as e:
                    logger.error(f"Error saving post {post.id}: {e}")
            
            conn.commit()
            conn.close()
            return new_count
        
        loop = asyncio.get_event_loop()
        new_count = await loop.run_in_executor(None, _save)
        
        logger.info(f"Saved {new_count} posts from {source}")
        return new_count > 0
    
    async def get_posts(
        self,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = 'created_at',
        descending: bool = True
    ) -> List[Post]:
        """Retrieve posts from SQLite storage."""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Build query
            order_direction = 'DESC' if descending else 'ASC'
            valid_order_fields = ['created_at', 'score', 'upvotes', 'fetched_at']
            if order_by not in valid_order_fields:
                order_by = 'created_at'
            
            if source:
                query = f'''
                    SELECT * FROM posts 
                    WHERE source = ? 
                    ORDER BY {order_by} {order_direction}
                    LIMIT ? OFFSET ?
                '''
                cursor.execute(query, (source, limit, offset))
            else:
                query = f'''
                    SELECT * FROM posts 
                    ORDER BY {order_by} {order_direction}
                    LIMIT ? OFFSET ?
                '''
                cursor.execute(query, (limit, offset))
            
            rows = cursor.fetchall()
            conn.close()
            return rows
        
        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(None, _get)
        
        return [self._row_to_post(row) for row in rows]
    
    async def get_post(self, post_id: str) -> Optional[Post]:
        """Get a specific post by ID."""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
            row = cursor.fetchone()
            conn.close()
            return row
        
        loop = asyncio.get_event_loop()
        row = await loop.run_in_executor(None, _get)
        
        if row:
            return self._row_to_post(row)
        return None
    
    async def delete_post(self, post_id: str) -> bool:
        """Delete a post from storage."""
        def _delete():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM posts WHERE id = ?', (post_id,))
            deleted = cursor.rowcount > 0
            
            conn.commit()
            conn.close()
            return deleted
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _delete)
    
    async def save_collection_result(self, result: CollectionResult) -> bool:
        """Save collection result metadata."""
        def _save():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO collection_history 
                (source, success, error_message, collected_at, total_count, filtered_count, post_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                result.source.value,
                1 if result.success else 0,
                result.error_message,
                result.collected_at.isoformat(),
                result.total_count,
                result.filtered_count,
                len(result.posts)
            ))
            
            conn.commit()
            conn.close()
            return True
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)
    
    async def get_collection_history(
        self,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get collection history."""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if source:
                cursor.execute('''
                    SELECT * FROM collection_history 
                    WHERE source = ? 
                    ORDER BY collected_at DESC 
                    LIMIT ?
                ''', (source, limit))
            else:
                cursor.execute('''
                    SELECT * FROM collection_history 
                    ORDER BY collected_at DESC 
                    LIMIT ?
                ''', (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            return rows
        
        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(None, _get)
        
        return [dict(row) for row in rows]
    
    async def save_hot_posts(self, hot_posts: List[HotPost]) -> bool:
        """Save hot posts with analysis data."""
        def _save():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            for hp in hot_posts:
                cursor.execute('''
                    INSERT INTO hot_posts 
                    (post_id, rank, trending_score, viral_potential, sentiment, key_topics, analyzed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    hp.post.id,
                    hp.rank,
                    hp.trending_score,
                    hp.viral_potential,
                    hp.sentiment,
                    json.dumps(hp.key_topics),
                    datetime.now().isoformat()
                ))
            
            conn.commit()
            conn.close()
            return True
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _save)
    
    async def search_posts(
        self,
        query: str,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Post]:
        """Search for posts matching a query."""
        def _search():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            search_pattern = f'%{query}%'
            
            if source:
                cursor.execute('''
                    SELECT * FROM posts 
                    WHERE (title LIKE ? OR content LIKE ?) AND source = ?
                    ORDER BY score DESC
                    LIMIT ?
                ''', (search_pattern, search_pattern, source, limit))
            else:
                cursor.execute('''
                    SELECT * FROM posts 
                    WHERE title LIKE ? OR content LIKE ?
                    ORDER BY score DESC
                    LIMIT ?
                ''', (search_pattern, search_pattern, limit))
            
            rows = cursor.fetchall()
            conn.close()
            return rows
        
        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(None, _search)
        
        return [self._row_to_post(row) for row in rows]
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        def _get():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Total posts
            cursor.execute('SELECT COUNT(*) FROM posts')
            total_posts = cursor.fetchone()[0]
            
            # Posts by source
            cursor.execute('SELECT source, COUNT(*) as count FROM posts GROUP BY source')
            source_counts = {row['source']: row['count'] for row in cursor.fetchall()}
            
            # Total hot posts
            cursor.execute('SELECT COUNT(*) FROM hot_posts')
            total_hot_posts = cursor.fetchone()[0]
            
            # Collection history count
            cursor.execute('SELECT COUNT(*) FROM collection_history')
            history_count = cursor.fetchone()[0]
            
            conn.close()
            return {
                'total_posts': total_posts,
                'posts_by_source': source_counts,
                'total_hot_posts': total_hot_posts,
                'collection_history_count': history_count,
                'storage_type': 'sqlite',
                'storage_path': self.db_path
            }
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get)
    
    async def clear_old_posts(self, days: int = 30) -> int:
        """Clear posts older than specified days."""
        def _clear():
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cutoff = datetime.now()
            from datetime import timedelta
            cutoff = cutoff - timedelta(days=days)
            
            cursor.execute(
                'DELETE FROM posts WHERE fetched_at < ?',
                (cutoff.isoformat(),)
            )
            deleted = cursor.rowcount
            
            conn.commit()
            conn.close()
            return deleted
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _clear)
    
    async def close(self) -> None:
        """Close the storage connection."""
        # SQLite connections are closed after each operation
        pass
