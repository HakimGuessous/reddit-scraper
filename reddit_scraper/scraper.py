"""Scraper for r/wallstreetbets daily discussion threads."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .formatter import iter_possible_titles
from .reddit_client import RedditClient, RedditCredentials

LOGGER = logging.getLogger(__name__)
DEFAULT_SUBREDDIT = "wallstreetbets"


@dataclass
class ScraperConfig:
    client_id: str
    client_secret: str
    user_agent: str
    subreddit: str = DEFAULT_SUBREDDIT


def _find_matching_post(posts: Iterable[Dict], candidate_titles: Iterable[str]) -> Optional[Dict]:
    """Return the first post whose title matches any of the candidates."""

    normalized = {title.casefold(): title for title in candidate_titles}
    for post in posts:
        title = post.get("data", {}).get("title", "")
        if title.casefold() in normalized:
            LOGGER.info("Matched thread '%s'", title)
            return post
    LOGGER.warning("Failed to match any posts by expected titles")
    return None


def _flatten_comment(comment: Dict) -> Dict:
    data = comment.get("data", {})
    replies = data.get("replies")
    children: List[Dict] = []
    if isinstance(replies, dict):
        children = replies.get("data", {}).get("children", [])

    return {
        "id": data.get("id"),
        "author": data.get("author"),
        "created_utc": data.get("created_utc"),
        "body": data.get("body"),
        "score": data.get("score"),
        "permalink": data.get("permalink"),
        "parent_id": data.get("parent_id"),
        "replies": [
            _flatten_comment(reply)
            for reply in children
            if reply.get("kind") == "t1"
        ],
    }


def _extract_comments(tree: List[Dict]) -> List[Dict]:
    comments = []
    for item in tree:
        if item.get("kind") != "t1":
            continue
        comments.append(_flatten_comment(item))
    return comments


def scrape_discussion_thread(
    config: ScraperConfig,
    target_date: date,
    output_path: Path,
) -> Path:
    """Scrape the discussion thread for the given date and save to JSON."""

    creds = RedditCredentials(
        client_id=config.client_id,
        client_secret=config.client_secret,
        user_agent=config.user_agent,
    )
    client = RedditClient(creds)
    candidate_titles = list(iter_possible_titles(target_date))
    LOGGER.info("Searching for discussion threads matching any of: %s", candidate_titles)

    search_results = client.search_subreddit(
        config.subreddit,
        query=" OR ".join(f'title:"{title}"' for title in candidate_titles),
        sort="new",
        limit=50,
    )
    posts = search_results.get("data", {}).get("children", [])
    post = _find_matching_post(posts, candidate_titles)
    if not post:
        raise RuntimeError("Could not find a matching discussion thread")

    post_data = post["data"]
    post_id = post_data["id"]
    LOGGER.info("Fetching comments for post %s", post_id)
    comments_response = client.get_post_comments(config.subreddit, post_id)
    if not isinstance(comments_response, list) or len(comments_response) < 2:
        raise RuntimeError("Unexpected comments response format")

    listing = comments_response[0]
    comments_listing = comments_response[1]
    submission_children = listing.get("data", {}).get("children", [])
    if not submission_children:
        raise RuntimeError("Submission data missing from comments response")

    submission = submission_children[0].get("data", {})
    comments_tree = comments_listing.get("data", {}).get("children", [])

    payload = {
        "thread": {
            "id": post_id,
            "title": post_data.get("title"),
            "author": post_data.get("author"),
            "created_utc": post_data.get("created_utc"),
            "permalink": post_data.get("permalink"),
            "num_comments": post_data.get("num_comments"),
            "score": post_data.get("score"),
            "upvote_ratio": post_data.get("upvote_ratio"),
            "selftext": submission.get("selftext"),
        },
        "comments": _extract_comments(comments_tree),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    LOGGER.info("Saved thread data to %s", output_path)
    return output_path
