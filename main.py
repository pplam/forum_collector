
#!/usr/bin/env python3
"""Main entry point for the Forum Collector application."""

import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime
from typing import List, Optional, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Post, CollectionResult, HotPost, ForumSource
from collectors import (
    BaseCollector,
    RedditCollector,
    HackerNewsCollector,
    StackOverflowCollector,
    GitHubDiscussionsCollector,
    DevToCollector,
    ProductHuntCollector,
    V2EXCollector,
    ZhihuCollector,
    LobstersCollector,
    DoubanCollector
)
from config import load_config, save_config, get_default_config, Settings, CollectorConfig
from storage import StorageManager
from utils import setup_logging, get_logger, calculate_trending_score, calculate_viral_potential


logger = get_logger(__name__)


class ForumCollectorApp:
    """Main application class for Forum Collector."""
    
    def __init__(self, config: Settings):
        """Initialize the application.
        
        Args:
            config: Application settings
        """
        self.config = config
        self.storage = StorageManager(
            storage_type=config.storage_type,
            storage_path=config.storage_path
        )
        self._collectors: Dict[str, BaseCollector] = {}
    
    def _get_collector(self, name: str, collector_config: CollectorConfig) -> Optional[BaseCollector]:
        """Get or create a collector instance.
        
        Args:
            name: Collector name
            collector_config: Collector configuration
            
        Returns:
            Collector instance or None if unsupported
        """
        collection_config = collector_config.to_collection_config()
        
        if collector_config.source == ForumSource.HACKER_NEWS:
            return HackerNewsCollector(collection_config)
        elif collector_config.source == ForumSource.REDDIT:
            return RedditCollector(
                collection_config,
                client_id=collector_config.api_key,
                client_secret=collector_config.api_secret
            )
        elif collector_config.source == ForumSource.STACK_OVERFLOW:
            return StackOverflowCollector(collection_config)
        elif collector_config.source == ForumSource.GITHUB_DISCUSSIONS:
            return GitHubDiscussionsCollector(
                collection_config,
                token=collector_config.access_token
            )
        elif collector_config.source == ForumSource.DEV_TO:
            return DevToCollector(collection_config)
        elif collector_config.source == ForumSource.PRODUCT_HUNT:
            return ProductHuntCollector(
                collection_config,
                api_key=collector_config.api_key
            )
        elif collector_config.source == ForumSource.V2EX:
            return V2EXCollector(collection_config, token=collector_config.access_token)
        elif collector_config.source == ForumSource.ZHIHU:
            return ZhihuCollector(collection_config, token=collector_config.access_token)
        elif collector_config.source == ForumSource.LOBSTERS:
            return LobstersCollector(collection_config)
        elif collector_config.source == ForumSource.DOUBAN:
            return DoubanCollector(collection_config, cookie=collector_config.cookie)
        else:
            logger.warning(f"Unsupported source: {collector_config.source}")
            return None
    
    async def collect_from_source(
        self, 
        source_name: str, 
        limit: Optional[int] = None
    ) -> CollectionResult:
        """Collect posts from a specific source.
        
        Args:
            source_name: Name of the source to collect from
            limit: Maximum number of posts to collect
            
        Returns:
            CollectionResult with collected posts
        """
        if source_name not in self.config.collectors:
            return CollectionResult(
                source=ForumSource.HACKER_NEWS,  # Default
                posts=[],
                success=False,
                error_message=f"Unknown source: {source_name}"
            )
        
        collector_config = self.config.collectors[source_name]
        
        if not collector_config.enabled:
            logger.info(f"Source '{source_name}' is disabled")
            return CollectionResult(
                source=collector_config.source,
                posts=[],
                success=False,
                error_message="Source is disabled"
            )
        
        collector = self._get_collector(source_name, collector_config)
        
        if not collector:
            return CollectionResult(
                source=collector_config.source,
                posts=[],
                success=False,
                error_message=f"Could not create collector for {source_name}"
            )
        
        async with collector:
            result = await collector.collect_hot_posts(limit)
            
            # Save to storage
            if result.posts:
                await self.storage.save_posts(result.posts, source_name)
            
            # Save collection result
            await self.storage.save_collection_result(result)
            
            logger.info(
                f"Collected {len(result.posts)} posts from {source_name} "
                f"(total: {result.total_count}, filtered: {result.filtered_count})"
            )
            
            return result
    
    async def collect_all(self, limit_per_source: Optional[int] = None) -> Dict[str, CollectionResult]:
        """Collect posts from all enabled sources.
        
        Args:
            limit_per_source: Maximum posts per source
            
        Returns:
            Dictionary mapping source names to results
        """
        results = {}
        
        for name, collector_config in self.config.collectors.items():
            if collector_config.enabled:
                try:
                    result = await self.collect_from_source(name, limit_per_source)
                    results[name] = result
                except Exception as e:
                    logger.error(f"Error collecting from {name}: {e}")
                    results[name] = CollectionResult(
                        source=collector_config.source,
                        posts=[],
                        success=False,
                        error_message=str(e)
                    )
        
        return results
    
    async def analyze_hot_posts(self, posts: List[Post]) -> List[HotPost]:
        """Analyze posts and calculate trending scores.
        
        Args:
            posts: Posts to analyze
            
        Returns:
            List of HotPost objects with analysis
        """
        hot_posts = []
        
        for i, post in enumerate(posts):
            trending_score = calculate_trending_score(
                post.upvotes,
                post.comments_count,
                post.views,
                post.created_at or datetime.now()
            )
            
            viral_potential = calculate_viral_potential(
                post.upvotes,
                post.comments_count,
                post.shares,
                post.views,
                post.created_at or datetime.now()
            )
            
            hot_post = HotPost(
                post=post,
                rank=i + 1,
                trending_score=trending_score,
                viral_potential=viral_potential,
                sentiment=None,
                key_topics=[]
            )
            
            hot_posts.append(hot_post)
        
        # Sort by trending score
        hot_posts.sort(key=lambda hp: hp.trending_score, reverse=True)
        
        # Update ranks
        for i, hp in enumerate(hot_posts):
            hp.rank = i + 1
        
        return hot_posts
    
    async def get_hot_posts(
        self, 
        source: Optional[str] = None, 
        limit: int = 20
    ) -> List[HotPost]:
        """Get hot posts from storage.
        
        Args:
            source: Filter by source (optional)
            limit: Maximum number of posts
            
        Returns:
            List of HotPost objects
        """
        posts = await self.storage.get_posts(
            source=source,
            limit=limit * 2,  # Get more for analysis
            order_by='score',
            descending=True
        )
        
        return await self.analyze_hot_posts(posts[:limit])
    
    async def search_posts(self, query: str, limit: int = 50) -> List[Post]:
        """Search for posts matching a query.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching posts
        """
        return await self.storage.search_posts(query, limit=limit)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics.
        
        Returns:
            Statistics dictionary
        """
        return await self.storage.get_stats()
    
    async def cleanup(self, days: int = 30) -> int:
        """Clean up old posts.
        
        Args:
            days: Delete posts older than this many days
            
        Returns:
            Number of deleted posts
        """
        return await self.storage.clear_old_posts(days)
    
    async def close(self):
        """Close the application."""
        await self.storage.close()


async def run_interactive(app: ForumCollectorApp):
    """Run interactive CLI mode."""
    print("\n" + "=" * 60)
    print("  Forum Collector - Interactive Mode")
    print("=" * 60)
    
    while True:
        print("\nOptions:")
        print("  1. Collect from all sources")
        print("  2. Collect from specific source")
        print("  3. View hot posts")
        print("  4. Search posts")
        print("  5. View statistics")
        print("  6. Cleanup old posts")
        print("  0. Exit")
        
        choice = input("\nEnter choice: ").strip()
        
        if choice == '0':
            print("Goodbye!")
            break
        
        elif choice == '1':
            print("\nCollecting from all sources...")
            results = await app.collect_all()
            
            total_posts = sum(len(r.posts) for r in results.values())
            success_count = sum(1 for r in results.values() if r.success)
            
            print(f"\nCollected {total_posts} posts from {success_count}/{len(results)} sources")
            
            for name, result in results.items():
                status = "✓" if result.success else "✗"
                print(f"  {status} {name}: {len(result.posts)} posts")
        
        elif choice == '2':
            sources = list(app.config.collectors.keys())
            print("\nAvailable sources:")
            for i, source in enumerate(sources, 1):
                config = app.config.collectors[source]
                status = "enabled" if config.enabled else "disabled"
                print(f"  {i}. {source} ({status})")
            
            try:
                idx = int(input("\nSelect source: ").strip()) - 1
                if 0 <= idx < len(sources):
                    source_name = sources[idx]
                    print(f"\nCollecting from {source_name}...")
                    result = await app.collect_from_source(source_name)
                    
                    if result.success:
                        print(f"Collected {len(result.posts)} posts")
                    else:
                        print(f"Error: {result.error_message}")
                else:
                    print("Invalid selection")
            except ValueError:
                print("Invalid input")
        
        elif choice == '3':
            limit = 10
            hot_posts = await app.get_hot_posts(limit=limit)
            
            print(f"\nTop {len(hot_posts)} Hot Posts:")
            print("-" * 80)
            
            for hp in hot_posts:
                print(f"\n{hp.rank}. [{hp.post.source.value}] {hp.post.title}")
                print(f"   Score: {hp.post.score:.1f} | Trending: {hp.trending_score:.2f} | "
                      f"Viral: {hp.viral_potential:.2f}")
                print(f"   URL: {hp.post.url}")
        
        elif choice == '4':
            query = input("\nEnter search query: ").strip()
            if query:
                posts = await app.search_posts(query)
                print(f"\nFound {len(posts)} matching posts:")
                
                for i, post in enumerate(posts[:10], 1):
                    print(f"\n{i}. [{post.source.value}] {post.title}")
                    print(f"   Score: {post.score:.1f} | URL: {post.url}")
        
        elif choice == '5':
            stats = await app.get_stats()
            
            print("\nStorage Statistics:")
            print("-" * 40)
            print(f"Total posts: {stats.get('total_posts', 0)}")
            print(f"Storage type: {stats.get('storage_type', 'unknown')}")
            
            print("\nPosts by source:")
            for source, count in stats.get('posts_by_source', {}).items():
                print(f"  {source}: {count}")
        
        elif choice == '6':
            days = 30
            try:
                days = int(input("\nDelete posts older than (days) [30]: ").strip() or 30)
            except ValueError:
                days = 30
            
            deleted = await app.cleanup(days)
            print(f"Deleted {deleted} old posts")
        
        else:
            print("Invalid choice")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Forum Collector - Collect hot posts from various forums")
    
    parser.add_argument(
        '-c', '--config',
        help='Path to configuration file'
    )
    parser.add_argument(
        '-s', '--source',
        help='Collect from a specific source only'
    )
    parser.add_argument(
        '-l', '--limit',
        type=int,
        default=100,
        help='Maximum posts to collect per source (default: 100)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Collect from all sources'
    )
    parser.add_argument(
        '--hot',
        type=int,
        default=20,
        help='Number of hot posts to display (default: 20)'
    )
    parser.add_argument(
        '--search',
        help='Search for posts matching a query'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show storage statistics'
    )
    parser.add_argument(
        '--cleanup',
        type=int,
        help='Delete posts older than specified days'
    )
    parser.add_argument(
        '-i', '--interactive',
        action='store_true',
        help='Run in interactive mode'
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Log level (default: INFO)'
    )
    parser.add_argument(
        '--generate-config',
        help='Generate default configuration file'
    )
    
    args = parser.parse_args()
    
    # Generate default config if requested
    if args.generate_config:
        default_config = get_default_config()
        save_config(default_config, args.generate_config)
        print(f"Generated default configuration: {args.generate_config}")
        return
    
    # Set up logging
    setup_logging(
        level=args.log_level,
        log_file="forum_collector.log",
        log_dir="./logs"
    )
    
    # Load configuration
    config = load_config(args.config)
    
    # Create application
    app = ForumCollectorApp(config)
    
    try:
        if args.interactive:
            await run_interactive(app)
        
        elif args.stats:
            stats = await app.get_stats()
            print("\nStorage Statistics:")
            print("-" * 40)
            print(f"Total posts: {stats.get('total_posts', 0)}")
            print(f"Storage type: {stats.get('storage_type', 'unknown')}")
            print("\nPosts by source:")
            for source, count in stats.get('posts_by_source', {}).items():
                print(f"  {source}: {count}")
        
        elif args.search:
            posts = await app.search_posts(args.search)
            print(f"\nFound {len(posts)} matching posts:")
            for i, post in enumerate(posts[:20], 1):
                print(f"\n{i}. [{post.source.value}] {post.title}")
                print(f"   Score: {post.score:.1f} | URL: {post.url}")
        
        elif args.cleanup:
            deleted = await app.cleanup(args.cleanup)
            print(f"Deleted {deleted} old posts")
        
        elif args.source:
            print(f"Collecting from {args.source}...")
            result = await app.collect_from_source(args.source, args.limit)
            
            if result.success:
                print(f"Collected {len(result.posts)} posts")
                
                # Show top posts
                hot_posts = await app.analyze_hot_posts(result.posts[:args.hot])
                print(f"\nTop {len(hot_posts)} posts:")
                for hp in hot_posts:
                    print(f"  {hp.rank}. {hp.post.title}")
                    print(f"     Score: {hp.post.score:.1f} | Trending: {hp.trending_score:.2f}")
            else:
                print(f"Error: {result.error_message}")
        
        elif args.all:
            print("Collecting from all sources...")
            results = await app.collect_all(args.limit)
            
            total_posts = sum(len(r.posts) for r in results.values())
            success_count = sum(1 for r in results.values() if r.success)
            
            print(f"\nCollected {total_posts} posts from {success_count}/{len(results)} sources")
            
            for name, result in results.items():
                status = "✓" if result.success else "✗"
                print(f"  {status} {name}: {len(result.posts)} posts")
        
        else:
            # Default: show hot posts
            hot_posts = await app.get_hot_posts(limit=args.hot)
            
            print(f"\nTop {len(hot_posts)} Hot Posts:")
            print("-" * 80)
            
            for hp in hot_posts:
                print(f"\n{hp.rank}. [{hp.post.source.value}] {hp.post.title}")
                print(f"   Score: {hp.post.score:.1f} | Trending: {hp.trending_score:.2f} | "
                      f"Viral: {hp.viral_potential:.2f}")
                print(f"   URL: {hp.post.url}")
    
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
