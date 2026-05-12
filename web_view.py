import os
import sys
import asyncio
import logging
from typing import Optional, Dict, Any

import flask
from flask import Flask, render_template_string, request, jsonify

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import StorageManager
from models import ForumSource

logger = logging.getLogger(__name__)

app = Flask(__name__)

storage: Optional[StorageManager] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def get_loop() -> asyncio.AbstractEventLoop:
    """Get or create event loop for running async code."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_async(coro):
    """Run async coroutine in existing event loop."""
    loop = get_loop()
    return loop.run_until_complete(coro)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Forum Collector - Post Explorer</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body { background-color: #f8f9fa; }
        .post-card { transition: transform 0.2s, box-shadow 0.2s; }
        .post-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        .source-badge { font-size: 0.75rem; }
        .score-badge { min-width: 60px; }
        .search-box { max-width: 500px; }
        .post-content { max-height: 200px; overflow: hidden; text-overflow: ellipsis; }
        .post-content.expanded { max-height: none; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="/"><i class="bi bi-collection"></i> Forum Collector</a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="/"><i class="bi bi-house"></i> Home</a>
                <a class="nav-link" href="/stats"><i class="bi bi-graph-up"></i> Stats</a>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        <div class="row mb-4">
            <div class="col-md-8">
                <form class="d-flex search-box" method="get" action="/">
                    <input class="form-control me-2" type="search" name="q" placeholder="Search posts..." value="{{ request.args.get('q', '') }}">
                    <button class="btn btn-primary" type="submit"><i class="bi bi-search"></i></button>
                </form>
            </div>
            <div class="col-md-4 text-end">
                <span class="badge bg-secondary fs-6">Total: {{ total_posts }} posts</span>
            </div>
        </div>

        <div class="row mb-3">
            <div class="col">
                <div class="btn-group flex-wrap" role="group">
                    <a href="/" class="btn btn-sm {{ 'btn-primary' if not request.args.get('source') else 'btn-outline-primary' }}">All</a>
                    {% for src in sources %}
                    <a href="/?source={{ src }}" class="btn btn-sm {{ 'btn-primary' if request.args.get('source') == src else 'btn-outline-primary' }}">{{ src|replace('_', ' ')|title }}</a>
                    {% endfor %}
                </div>
            </div>
        </div>

        <div class="row mb-3">
            <div class="col">
                <div class="btn-group" role="group">
                    <a href="?{{ dict(request.args, sort='created_at', order='desc') | urlencode }}" class="btn btn-sm {{ 'btn-dark' if request.args.get('sort') != 'score' else 'btn-outline-dark' }}">Latest</a>
                    <a href="?{{ dict(request.args, sort='score', order='desc') | urlencode }}" class="btn btn-sm {{ 'btn-dark' if request.args.get('sort') == 'score' else 'btn-outline-dark' }}">Top</a>
                </div>
            </div>
            <div class="col text-end">
                <span class="text-muted">Showing {{ posts|length }} posts</span>
            </div>
        </div>

        <div class="row">
            {% for post in posts %}
            <div class="col-12 mb-3">
                <div class="card post-card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <div>
                                <span class="badge bg-primary source-badge me-2">{{ post.source }}</span>
                                {% if post.category %}
                                <span class="badge bg-info source-badge me-2">{{ post.category }}</span>
                                {% endif %}
                                {% for tag in post.tags[:3] %}
                                <span class="badge bg-light text-dark source-badge me-1">{{ tag }}</span>
                                {% endfor %}
                            </div>
                            <div class="text-end">
                                <span class="badge bg-success score-badge">
                                    <i class="bi bi-arrow-up"></i> {{ post.upvotes or 0 }}
                                </span>
                                <span class="badge bg-secondary score-badge">
                                    <i class="bi bi-chat"></i> {{ post.comments_count or 0 }}
                                </span>
                            </div>
                        </div>
                        <h5 class="card-title">
                            <a href="{{ post.url }}" target="_blank" class="text-decoration-none">{{ post.title }}</a>
                        </h5>
                        {% if post.content %}
                        <p class="card-text text-muted post-content" id="content-{{ post.id }}">{{ post.content[:500] }}</p>
                        {% endif %}
                        <div class="d-flex justify-content-between align-items-center">
                            <div class="text-muted small">
                                {% if post.author and post.author.username %}
                                <span class="me-3"><i class="bi bi-person"></i> {{ post.author.username }}</span>
                                {% endif %}
                                <span class="me-3"><i class="bi bi-clock"></i> {{ post.created_at.strftime('%Y-%m-%d %H:%M') if post.created_at else 'N/A' }}</span>
                            </div>
                            <a href="/post/{{ post.id }}" class="btn btn-sm btn-outline-primary">View Details</a>
                        </div>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="col-12">
                <div class="alert alert-info">No posts found. Try collecting some posts first!</div>
            </div>
            {% endfor %}
        </div>

        {% if total_pages > 1 %}
        <nav>
            <ul class="pagination justify-content-center">
                {% if page > 1 %}
                <li class="page-item"><a class="page-link" href="?{{ dict(request.args, page=page-1) | urlencode }}">Previous</a></li>
                {% endif %}
                {% for p in range(1, total_pages + 1) %}
                <li class="page-item {{ 'active' if p == page else '' }}"><a class="page-link" href="?{{ dict(request.args, page=p) | urlencode }}">{{ p }}</a></li>
                {% endfor %}
                {% if page < total_pages %}
                <li class="page-item"><a class="page-link" href="?{{ dict(request.args, page=page+1) | urlencode }}">Next</a></li>
                {% endif %}
            </ul>
        </nav>
        {% endif %}
    </div>

    <footer class="mt-5 py-3 bg-light text-center">
        <div class="container">
            <p class="text-muted mb-0">Forum Collector - Post Explorer</p>
        </div>
    </footer>
</body>
</html>
"""

POST_DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ post.title[:50] }}... - Forum Collector</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body { background-color: #f8f9fa; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="/"><i class="bi bi-collection"></i> Forum Collector</a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="/"><i class="bi bi-house"></i> Home</a>
                <a class="nav-link" href="/stats"><i class="bi bi-graph-up"></i> Stats</a>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
                <div>
                    <span class="badge bg-primary me-2">{{ post.source }}</span>
                    {% if post.category %}
                    <span class="badge bg-info me-2">{{ post.category }}</span>
                    {% endif %}
                </div>
                <div>
                    <span class="badge bg-success me-1"><i class="bi bi-arrow-up"></i> {{ post.upvotes or 0 }}</span>
                    <span class="badge bg-secondary me-1"><i class="bi bi-chat"></i> {{ post.comments_count or 0 }}</span>
                    {% if post.views %}
                    <span class="badge bg-info"><i class="bi bi-eye"></i> {{ post.views }}</span>
                    {% endif %}
                </div>
            </div>
            <div class="card-body">
                <h2 class="card-title mb-3">
                    <a href="{{ post.url }}" target="_blank" class="text-decoration-none">{{ post.title }}</a>
                </h2>
                
                <div class="mb-3">
                    {% if post.author %}
                    <span class="me-3">
                        <i class="bi bi-person"></i> 
                        {% if post.author.profile_url %}
                        <a href="{{ post.author.profile_url }}" target="_blank">{{ post.author.username }}</a>
                        {% else %}
                        {{ post.author.username }}
                        {% endif %}
                    </span>
                    {% endif %}
                    <span class="me-3">
                        <i class="bi bi-clock"></i> {{ post.created_at.strftime('%Y-%m-%d %H:%M:%S') if post.created_at else 'N/A' }}
                    </span>
                    <span class="me-3">
                        <i class="bi bi-download"></i> {{ post.fetched_at.strftime('%Y-%m-%d %H:%M:%S') if post.fetched_at else 'N/A' }}
                    </span>
                </div>

                {% if post.tags %}
                <div class="mb-3">
                    {% for tag in post.tags %}
                    <span class="badge bg-light text-dark me-1">{{ tag }}</span>
                    {% endfor %}
                </div>
                {% endif %}

                {% if post.content %}
                <div class="card bg-light mb-3">
                    <div class="card-body">
                        <pre style="white-space: pre-wrap; word-wrap: break-word; font-family: inherit;">{{ post.content }}</pre>
                    </div>
                </div>
                {% endif %}

                {% if post.summary %}
                <div class="alert alert-secondary">
                    <strong>Summary:</strong> {{ post.summary }}
                </div>
                {% endif %}

                <div class="mt-3">
                    <a href="{{ post.url }}" target="_blank" class="btn btn-primary"><i class="bi bi-box-arrow-up-right"></i> View Original</a>
                    <a href="/" class="btn btn-outline-secondary"><i class="bi bi-arrow-left"></i> Back</a>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""

STATS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Statistics - Forum Collector</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body { background-color: #f8f9fa; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="/"><i class="bi bi-collection"></i> Forum Collector</a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="/"><i class="bi bi-house"></i> Home</a>
                <a class="nav-link" href="/stats"><i class="bi bi-graph-up"></i> Stats</a>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        <h2 class="mb-4"><i class="bi bi-graph-up"></i> Storage Statistics</h2>
        
        <div class="row mb-4">
            <div class="col-md-4">
                <div class="card text-center">
                    <div class="card-body">
                        <h3 class="display-4">{{ stats.total_posts }}</h3>
                        <p class="text-muted mb-0">Total Posts</p>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card text-center">
                    <div class="card-body">
                        <h3 class="display-4">{{ stats.storage_type }}</h3>
                        <p class="text-muted mb-0">Storage Type</p>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card text-center">
                    <div class="card-body">
                        <h3 class="display-4">{{ stats.collection_history_count }}</h3>
                        <p class="text-muted mb-0">Collection Runs</p>
                    </div>
                </div>
            </div>
        </div>

        <h4 class="mb-3">Posts by Source</h4>
        <div class="card mb-4">
            <div class="card-body">
                {% if stats.posts_by_source %}
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>Source</th>
                            <th class="text-end">Posts</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for source, count in stats.posts_by_source.items() %}
                        <tr>
                            <td><a href="/?source={{ source }}">{{ source }}</a></td>
                            <td class="text-end">{{ count }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% else %}
                <p class="text-muted mb-0">No posts collected yet.</p>
                {% endif %}
            </div>
        </div>

        <a href="/" class="btn btn-primary"><i class="bi bi-arrow-left"></i> Back to Posts</a>
    </div>
</body>
</html>
"""


def serialize_post(post) -> Dict[str, Any]:
    """Serialize a Post object for template rendering."""
    return {
        "id": post.id,
        "title": post.title,
        "source": post.source.value,
        "url": post.url,
        "content": post.content,
        "summary": post.summary,
        "created_at": post.created_at,
        "fetched_at": post.fetched_at,
        "upvotes": post.upvotes,
        "downvotes": post.downvotes,
        "comments_count": post.comments_count,
        "views": post.views,
        "shares": post.shares,
        "tags": post.tags,
        "category": post.category,
        "author": {
            "username": post.author.username if post.author else None,
            "profile_url": post.author.profile_url if post.author else None,
            "avatar_url": post.author.avatar_url if post.author else None,
        }
        if post.author
        else None,
    }


@app.route("/")
def index():
    """List all posts with filtering and pagination."""
    source = request.args.get("source")
    query = request.args.get("q", "")
    sort = request.args.get("sort", "created_at")
    order = request.args.get("order", "desc")
    page = int(request.args.get("page", 1))
    per_page = 20

    try:
        if query:
            posts = run_async(
                storage.search_posts(query, source=source, limit=per_page * page)
            )
        else:
            posts = run_async(
                storage.get_posts(
                    source=source,
                    limit=per_page,
                    offset=(page - 1) * per_page,
                    order_by=sort,
                    descending=(order == "desc"),
                )
            )

        stats = run_async(storage.get_stats())
        total_posts = stats.get("total_posts", 0)
        total_pages = max(1, (total_posts + per_page - 1) // per_page)

        sources = [s.value for s in ForumSource]

        return render_template_string(
            HTML_TEMPLATE,
            posts=[serialize_post(p) for p in posts],
            sources=sources,
            total_posts=total_posts,
            total_pages=total_pages,
            page=page,
        )
    except Exception as e:
        logger.error(f"Error in index: {e}")
        return f"Error: {e}", 500


@app.route("/post/<post_id>")
def post_detail(post_id: str):
    """Show post detail."""
    try:
        post = run_async(storage.get_post(post_id))
        if not post:
            return "Post not found", 404

        return render_template_string(POST_DETAIL_TEMPLATE, post=serialize_post(post))
    except Exception as e:
        logger.error(f"Error in post_detail: {e}")
        return f"Error: {e}", 500


@app.route("/stats")
def stats():
    """Show storage statistics."""
    try:
        stats_data = run_async(storage.get_stats())
        return render_template_string(STATS_TEMPLATE, stats=stats_data)
    except Exception as e:
        logger.error(f"Error in stats: {e}")
        return f"Error: {e}", 500


@app.route("/api/posts")
def api_posts():
    """API endpoint for posts."""
    try:
        source = request.args.get("source")
        query = request.args.get("q", "")
        limit = int(request.args.get("limit", 50))

        if query:
            posts = run_async(storage.search_posts(query, source=source, limit=limit))
        else:
            posts = run_async(storage.get_posts(source=source, limit=limit))

        return jsonify([serialize_post(p) for p in posts])
    except Exception as e:
        logger.error(f"Error in api_posts: {e}")
        return jsonify({"error": str(e)}), 500


def run_web_view(
    storage_manager: StorageManager, host: str = "127.0.0.1", port: int = 5000
):
    """Run the Flask web server."""
    global storage
    storage = storage_manager

    print(f"\nStarting web server at http://{host}:{port}")
    print("Press Ctrl+C to stop the server\n")

    app.run(host=host, port=port, debug=False)
