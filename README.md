
# Forum Collector

A Python application for collecting hot posts from various online forums and communities.

## Features

- **Multiple Sources**: Collect posts from various forums including:
  - Hacker News
  - Reddit
  - V2EX (Chinese tech community)
  - Zhihu (Chinese Q&A platform)
  - Douban Groups (Chinese interest groups)
  - Lobsters
  - Dev.to
  - Product Hunt
  - Stack Overflow
  - GitHub Discussions

- **Smart Filtering**: Filter posts by score, time range, tags, and keywords
- **Trending Analysis**: Calculate trending scores and viral potential
- **Multiple Storage Backends**: JSON or SQLite storage
- **CLI & Interactive Mode**: Use from command line or interactive menu

## Installation

```bash
# Clone or navigate to the forum_collector directory
cd forum_collector

# Install dependencies
pip install -r requirements.txt
```

## Quick Start

```bash
# Run with default settings (shows hot posts)
python main.py

# Collect from all sources
python main.py --all

# Collect from specific source
python main.py --source hacker_news --limit 50

# Search posts
python main.py --search "python"

# Show statistics
python main.py --stats

# Interactive mode
python main.py -i
```

## Configuration

1. Copy the sample configuration:
```bash
cp config.sample.yaml config.yaml
```

2. Edit `config.yaml` to customize sources and settings.

### API Keys

Some sources require authentication:

| Source | Required | How to Get |
|--------|----------|------------|
| Hacker News | No | - |
| Reddit | Optional | https://www.reddit.com/prefs/apps |
| V2EX | Optional | https://www.v2ex.com/settings/tokens |
| Zhihu | Optional | Login required |
| Douban | Optional | Login required for full access |
| Product Hunt | Yes | https://www.producthunt.com/v2/oauth/applications |
| GitHub | Optional | https://github.com/settings/tokens |
| Stack Overflow | Optional | https://stackapps.com |

## Usage Examples

### Interactive Mode

```bash
python main.py -i
```

This provides a menu-driven interface for:
- Collecting posts from all or specific sources
- Viewing hot posts
- Searching posts
- Viewing statistics
- Cleaning up old posts

### Command Line

```bash
# Collect from Hacker News
python main.py --source hacker_news --limit 30

# Collect from all enabled sources
python main.py --all --limit 50

# Search for posts
python main.py --search "machine learning"

# Show storage statistics
python main.py --stats

# Clean up posts older than 30 days
python main.py --cleanup 30

# Generate default config file
python main.py --generate-config my_config.yaml
```

### As a Library

```python
import asyncio
from config import load_config
from main import ForumCollectorApp

async def main():
    # Load configuration
    config = load_config('config.yaml')
    
    # Create app
    app = ForumCollectorApp(config)
    
    try:
        # Collect from all sources
        results = await app.collect_all(limit_per_source=50)
        
        # Get hot posts
        hot_posts = await app.get_hot_posts(limit=20)
        
        for hp in hot_posts:
            print(f"{hp.rank}. {hp.post.title}")
            print(f"   Trending: {hp.trending_score:.2f}")
        
        # Search posts
        posts = await app.search_posts("python")
        print(f"Found {len(posts)} posts")
        
    finally:
        await app.close()

asyncio.run(main())
```

## Project Structure

```
forum_collector/
├── main.py                 # Main entry point
├── requirements.txt        # Python dependencies
├── config.sample.yaml      # Sample configuration
├── collectors/             # Source collectors
│   ├── __init__.py
│   ├── base_collector.py   # Abstract base class
│   ├── hackernews_collector.py
│   ├── reddit_collector.py
│   ├── v2ex_collector.py
│   ├── zhihu_collector.py
│   ├── douban_collector.py
│   └── ...
├── models/                 # Data models
│   └── __init__.py
├── config/                 # Configuration management
│   ├── __init__.py
│   └── settings.py
├── storage/                # Storage backends
│   ├── __init__.py
│   ├── base_storage.py
│   ├── json_storage.py
│   ├── sqlite_storage.py
│   └── storage_manager.py
└── utils/                  # Utility functions
    ├── __init__.py
    ├── helpers.py
    └── logger.py
```

## Data Models

### Post
- `id`: Unique identifier
- `title`: Post title
- `source`: Forum source (enum)
- `url`: Post URL
- `author`: Author information
- `content`: Post content
- `created_at`: Creation timestamp
- `upvotes`, `downvotes`, `comments_count`, `views`: Engagement metrics
- `tags`: List of tags
- `score`: Calculated hotness score

### HotPost
- `post`: Post object
- `rank`: Ranking position
- `trending_score`: Trending calculation
- `viral_potential`: Viral potential score (0-1)
- `sentiment`: Sentiment analysis result
- `key_topics`: Extracted key topics

## Storage

### JSON Storage (default)
- Posts stored in `./data/posts.json`
- Collection history in `./data/history.json`
- Hot posts in `./data/hot_posts.json`

### SQLite Storage
- All data in `./data/forum_collector.db`
- Enable in config: `storage_type: "sqlite"`

## Rate Limiting

The application includes built-in rate limiting:
- Respects API rate limits
- Exponential backoff for retries
- Configurable requests per second

## Adding New Collectors

1. Create a new collector in `collectors/`:
```python
from collectors.base_collector import BaseCollector
from models import Post, CollectionResult, ForumSource

class MyCollector(BaseCollector):
    @property
    def source(self) -> ForumSource:
        return ForumSource.MY_SOURCE
    
    @property
    def base_url(self) -> str:
        return "https://api.example.com"
    
    async def collect_hot_posts(self, limit=None) -> CollectionResult:
        # Implement collection logic
        pass
    
    async def get_post_details(self, post_id: str) -> Optional[Post]:
        # Implement post details retrieval
        pass
    
    async def get_post_comments(self, post_id: str, limit=None) -> List[Dict]:
        # Implement comments retrieval
        pass
```

2. Add the source to `models/__init__.py`:
```python
class ForumSource(Enum):
    # ... existing sources
    MY_SOURCE = "my_source"
```

3. Register in `collectors/__init__.py`

4. Add configuration in `config/settings.py`

## License

MIT License
