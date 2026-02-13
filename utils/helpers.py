
"""Helper utility functions for forum collector."""

import re
import html
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
import functools
import logging


logger = logging.getLogger(__name__)


def format_timestamp(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format a datetime object to string.
    
    Args:
        dt: Datetime object to format
        format_str: Format string
        
    Returns:
        Formatted string
    """
    return dt.strftime(format_str)


def parse_timestamp(
    timestamp_str: str, 
    format_str: Optional[str] = None
) -> Optional[datetime]:
    """Parse a timestamp string to datetime.
    
    Args:
        timestamp_str: Timestamp string to parse
        format_str: Expected format (optional)
        
    Returns:
        Datetime object or None if parsing fails
    """
    if not timestamp_str:
        return None
    
    # Common formats to try
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %Z",  # RFC 2822
    ]
    
    if format_str:
        formats.insert(0, format_str)
    
    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue
    
    # Try ISO format
    try:
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except ValueError:
        pass
    
    return None


def clean_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities.
    
    Args:
        text: Text containing HTML
        
    Returns:
        Clean text without HTML tags
    """
    if not text:
        return ""
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def truncate_text(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """Truncate text to a maximum length.
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated
        
    Returns:
        Truncated text
    """
    if not text:
        return ""
    
    if len(text) <= max_length:
        return text
    
    # Find a good break point
    break_points = ['.', '!', '?', '\n', ' ']
    break_idx = max_length
    
    for bp in break_points:
        idx = text.rfind(bp, 0, max_length)
        if idx > max_length // 2:
            break_idx = idx + 1
            break
    
    return text[:break_idx].strip() + suffix


def calculate_trending_score(
    upvotes: int,
    comments_count: int,
    views: int,
    created_at: datetime,
    current_time: Optional[datetime] = None
) -> float:
    """Calculate a trending score for a post.
    
    Uses a time-decay algorithm similar to Hacker News.
    
    Args:
        upvotes: Number of upvotes
        comments_count: Number of comments
        views: Number of views
        created_at: Post creation time
        current_time: Current time (defaults to now)
        
    Returns:
        Trending score
    """
    if current_time is None:
        current_time = datetime.now()
    
    # Calculate engagement score
    engagement = upvotes * 1.0 + comments_count * 2.0 + views * 0.001
    
    # Time decay factor (using HN-like algorithm)
    hours_since = (current_time - created_at).total_seconds() / 3600
    
    # Gravity factor (higher = faster decay)
    gravity = 1.8
    
    # Score = engagement / (hours + 2)^gravity
    score = engagement / ((hours_since + 2) ** gravity)
    
    return round(score, 2)


def calculate_viral_potential(
    upvotes: int,
    comments_count: int,
    shares: int,
    views: int,
    created_at: datetime,
    current_time: Optional[datetime] = None
) -> float:
    """Calculate viral potential score (0-1).
    
    Higher scores indicate higher viral potential.
    
    Args:
        upvotes: Number of upvotes
        comments_count: Number of comments
        shares: Number of shares
        views: Number of views
        created_at: Post creation time
        current_time: Current time (defaults to now)
        
    Returns:
        Viral potential score (0-1)
    """
    if current_time is None:
        current_time = datetime.now()
    
    hours_since = (current_time - created_at).total_seconds() / 3600
    
    if hours_since <= 0:
        hours_since = 0.1
    
    # Calculate engagement rates
    upvote_rate = upvotes / hours_since if upvotes > 0 else 0
    comment_rate = comments_count / hours_since if comments_count > 0 else 0
    share_rate = shares / hours_since if shares > 0 else 0
    
    # View to engagement ratio
    if views > 0:
        engagement_ratio = (upvotes + comments_count) / views
    else:
        engagement_ratio = 0
    
    # Calculate viral score components
    # Normalize each component
    upvote_score = min(upvote_rate / 10, 0.25)  # Max 0.25
    comment_score = min(comment_rate / 5, 0.25)  # Max 0.25
    share_score = min(share_rate / 2, 0.25)  # Max 0.25
    ratio_score = min(engagement_ratio * 2, 0.25)  # Max 0.25
    
    total_score = upvote_score + comment_score + share_score + ratio_score
    
    return round(min(total_score, 1.0), 2)


def extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
    """Extract keywords from text.
    
    Simple keyword extraction based on word frequency.
    For production use, consider using NLP libraries.
    
    Args:
        text: Text to extract keywords from
        max_keywords: Maximum number of keywords to return
        
    Returns:
        List of keywords
    """
    if not text:
        return []
    
    # Common stop words
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
        'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
        'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we',
        'they', 'what', 'which', 'who', 'when', 'where', 'why', 'how', 'all',
        'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such',
        'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very',
        'just', 'also', 'now', 'here', 'there', 'then', 'if', 'as', 'about',
        'into', 'through', 'during', 'before', 'after', 'above', 'below',
        # Chinese stop words
        '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一',
        '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着',
        '没有', '看', '好', '自己', '这', '那', '什么', '他', '她', '它'
    }
    
    # Tokenize text
    words = re.findall(r'\b\w+\b', text.lower())
    
    # Count word frequencies
    word_freq: Dict[str, int] = {}
    for word in words:
        if word not in stop_words and len(word) > 2:
            word_freq[word] = word_freq.get(word, 0) + 1
    
    # Sort by frequency and return top keywords
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    
    return [word for word, freq in sorted_words[:max_keywords]]


def analyze_sentiment(text: str) -> str:
    """Analyze sentiment of text.
    
    Simple sentiment analysis based on keyword matching.
    For production use, consider using NLP libraries.
    
    Args:
        text: Text to analyze
        
    Returns:
        Sentiment string: 'positive', 'negative', or 'neutral'
    """
    if not text:
        return 'neutral'
    
    text_lower = text.lower()
    
    # Positive words
    positive_words = {
        'great', 'awesome', 'excellent', 'amazing', 'good', 'love', 'best',
        'fantastic', 'wonderful', 'brilliant', 'perfect', 'happy', 'glad',
        'excited', 'impressive', 'outstanding', 'superb', 'remarkable',
        # Chinese positive words
        '好', '很好', '太棒', '优秀', '出色', '喜欢', '爱', '精彩', '完美',
        '开心', '高兴', '推荐', '值得', '厉害', '强大'
    }
    
    # Negative words
    negative_words = {
        'bad', 'terrible', 'awful', 'horrible', 'hate', 'worst', 'poor',
        'disappointing', 'frustrating', 'annoying', 'sad', 'angry', 'ugly',
        'useless', 'broken', 'fail', 'failure', 'problem', 'issue', 'bug',
        # Chinese negative words
        '差', '糟糕', '不好', '失望', '讨厌', '问题', '错误', '失败', '坑',
        '垃圾', '烂', '差劲', '难用', '后悔', '无语', '坑爹'
    }
    
    # Count sentiment words
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)
    
    # Determine sentiment
    if positive_count > negative_count + 1:
        return 'positive'
    elif negative_count > positive_count + 1:
        return 'negative'
    else:
        return 'neutral'


def rate_limit(calls_per_second: float = 2.0):
    """Decorator to rate limit async function calls.
    
    Args:
        calls_per_second: Maximum calls per second
        
    Returns:
        Decorated function
    """
    min_interval = 1.0 / calls_per_second
    
    def decorator(func: Callable):
        last_call_time: Dict[str, datetime] = {}
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Use function name as key
            key = func.__name__
            
            if key in last_call_time:
                elapsed = (datetime.now() - last_call_time[key]).total_seconds()
                if elapsed < min_interval:
                    await asyncio.sleep(min_interval - elapsed)
            
            last_call_time[key] = datetime.now()
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def normalize_url(url: str, base_url: Optional[str] = None) -> str:
    """Normalize a URL.
    
    Args:
        url: URL to normalize
        base_url: Base URL for relative URLs
        
    Returns:
        Normalized URL
    """
    if not url:
        return ""
    
    url = url.strip()
    
    # Handle relative URLs
    if url.startswith('/') and base_url:
        url = base_url.rstrip('/') + url
    
    # Ensure protocol
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    return url


def calculate_read_time(text: str, words_per_minute: int = 200) -> int:
    """Calculate estimated read time in minutes.
    
    Args:
        text: Text to calculate read time for
        words_per_minute: Average reading speed
        
    Returns:
        Estimated read time in minutes
    """
    if not text:
        return 0
    
    # Count words (including Chinese characters as words)
    word_count = len(re.findall(r'\b\w+\b', text))
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    
    total_words = word_count + chinese_chars
    
    return max(1, total_words // words_per_minute)


def format_number(num: int) -> str:
    """Format a number with K/M suffixes.
    
    Args:
        num: Number to format
        
    Returns:
        Formatted string
    """
    if num >= 1000000:
        return f"{num / 1000000:.1f}M"
    elif num >= 1000:
        return f"{num / 1000:.1f}K"
    else:
        return str(num)


def is_chinese_text(text: str) -> bool:
    """Check if text is primarily Chinese.
    
    Args:
        text: Text to check
        
    Returns:
        True if text is primarily Chinese
    """
    if not text:
        return False
    
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = len(text.replace(' ', ''))
    
    return chinese_chars / max(total_chars, 1) > 0.3
