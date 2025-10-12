"""Scraper for r/wallstreetbets daily discussion threads."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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


def _author_name(entity: Any) -> Optional[str]:
    if entity is None:
        return None
    name = getattr(entity, "name", None)
    if name is not None:
        return name
    return str(entity)


def _find_matching_post(posts: Iterable[Any], candidate_titles: Iterable[str]) -> Optional[Any]:
    """Return the first post whose title matches any of the candidates."""

    matches = _find_matching_posts(posts, candidate_titles)
    return matches[0] if matches else None


def _find_matching_posts(posts: Iterable[Any], candidate_titles: Iterable[str]) -> List[Any]:
    """Return all posts whose titles match the candidate titles."""

    normalized = {title.casefold(): title for title in candidate_titles}
    matches: List[Any] = []
    seen_titles = set()
    for post in posts:
        title = getattr(post, "title", "")
        normalized_title = title.casefold()
        if normalized_title in normalized and normalized_title not in seen_titles:
            LOGGER.info("Matched thread '%s'", title)
            matches.append(post)
            seen_titles.add(normalized_title)

    if not matches:
        LOGGER.warning("Failed to match any posts by expected titles")

    return matches


def _flatten_comment(comment: Any) -> Dict[str, Any]:
    replies = getattr(comment, "replies", None) or []
    return {
        "id": getattr(comment, "id", None),
        "author": _author_name(getattr(comment, "author", None)),
        "created_utc": getattr(comment, "created_utc", None),
        "body": getattr(comment, "body", None),
        "score": getattr(comment, "score", None),
        "permalink": getattr(comment, "permalink", None),
        "parent_id": getattr(comment, "parent_id", None),
        "replies": _extract_comments(replies),
    }


def _is_comment(obj: Any) -> bool:
    return hasattr(obj, "body") and hasattr(obj, "id")


def _extract_comments(tree: Iterable[Any]) -> List[Dict[str, Any]]:
    comments: List[Dict[str, Any]] = []
    for item in tree:
        if _is_comment(item):
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
    matched_posts = _find_matching_posts(search_results, candidate_titles)
    if not matched_posts:
        raise RuntimeError("Could not find a matching discussion thread")

    payload_threads: List[Dict[str, Any]] = []
    for post in matched_posts:
        LOGGER.info("Fetching comments for post %s", getattr(post, "id", "<unknown>"))
        submission = client.get_submission(post.id)
        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload_threads.append(
            {
                "thread": {
                    "id": submission.id,
                    "title": submission.title,
                    "author": _author_name(submission.author),
                    "created_utc": getattr(submission, "created_utc", None),
                    "permalink": submission.permalink,
                    "num_comments": getattr(submission, "num_comments", None),
                    "score": getattr(submission, "score", None),
                    "upvote_ratio": getattr(submission, "upvote_ratio", None),
                    "selftext": getattr(submission, "selftext", None),
                },
                "comments": _extract_comments(submission.comments),
                "fetched_at": fetched_at,
            }
        )

    payload = {
        "threads": payload_threads,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    LOGGER.info("Saved thread data to %s", output_path)
    return output_path
