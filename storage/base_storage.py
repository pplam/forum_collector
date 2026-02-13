
"""Base storage interface for forum collector."""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Post, CollectionResult, HotPost


class BaseStorage(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    async def save_posts(self, posts: List[Post], source: str) -> bool:
        """Save a list of posts to storage.
        
        Args:
            posts: List of Post objects to save
            source: Source identifier
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def get_posts(
        self, 
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = 'created_at',
        descending: bool = True
    ) -> List[Post]:
        """Retrieve posts from storage.
        
        Args:
            source: Filter by source (optional)
            limit: Maximum number of posts to return
            offset: Number of posts to skip
            order_by: Field to order by
            descending: Sort in descending order
            
        Returns:
            List of Post objects
        """
        pass
    
    @abstractmethod
    async def get_post(self, post_id: str) -> Optional[Post]:
        """Get a specific post by ID.
        
        Args:
            post_id: The post identifier
            
        Returns:
            Post object if found, None otherwise
        """
        pass
    
    @abstractmethod
    async def delete_post(self, post_id: str) -> bool:
        """Delete a post from storage.
        
        Args:
            post_id: The post identifier
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def save_collection_result(self, result: CollectionResult) -> bool:
        """Save a collection result with metadata.
        
        Args:
            result: CollectionResult to save
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def get_collection_history(
        self,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get history of collection operations.
        
        Args:
            source: Filter by source (optional)
            limit: Maximum number of results
            
        Returns:
            List of collection result metadata
        """
        pass
    
    @abstractmethod
    async def save_hot_posts(self, hot_posts: List[HotPost]) -> bool:
        """Save hot posts with analysis data.
        
        Args:
            hot_posts: List of HotPost objects to save
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def search_posts(
        self,
        query: str,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Post]:
        """Search for posts matching a query.
        
        Args:
            query: Search query string
            source: Filter by source (optional)
            limit: Maximum number of results
            
        Returns:
            List of matching Post objects
        """
        pass
    
    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics.
        
        Returns:
            Dictionary with storage statistics
        """
        pass
    
    @abstractmethod
    async def clear_old_posts(self, days: int = 30) -> int:
        """Clear posts older than specified days.
        
        Args:
            days: Number of days to keep
            
        Returns:
            Number of posts deleted
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close the storage connection."""
        pass
