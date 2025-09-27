"""Scraper for r/wallstreetbets daily discussion threads."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set

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


MoreFetcher = Callable[[Dict, Optional[str]], List[Dict]]


def _find_matching_post(posts: Iterable[Dict], candidate_titles: Iterable[str]) -> Optional[Dict]:
    """Return the first post whose title matches any of the candidates."""

    matches = _find_matching_posts(posts, candidate_titles)
    return matches[0] if matches else None


def _find_matching_posts(posts: Iterable[Dict], candidate_titles: Iterable[str]) -> List[Dict]:
    """Return all posts whose titles match the candidate titles."""

    normalized = {title.casefold(): title for title in candidate_titles}
    matches: List[Dict] = []
    seen_titles = set()
    for post in posts:
        title = post.get("data", {}).get("title", "")
        normalized_title = title.casefold()
        if normalized_title in normalized and normalized_title not in seen_titles:
            LOGGER.info("Matched thread '%s'", title)
            matches.append(post)
            seen_titles.add(normalized_title)

    if not matches:
        LOGGER.warning("Failed to match any posts by expected titles")

    return matches


def _flatten_comment(
    comment: Dict,
    fetch_more: Optional[MoreFetcher] = None,
    link_fullname: Optional[str] = None,
    seen_more_ids: Optional[Set[str]] = None,
) -> Dict:
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
        "replies": _process_comment_children(
            children, fetch_more, link_fullname, seen_more_ids=seen_more_ids
        ),
    }


def _process_comment_children(
    children: Iterable[Dict],
    fetch_more: Optional[MoreFetcher],
    link_fullname: Optional[str],
    *,
    seen_more_ids: Optional[Set[str]] = None,
) -> List[Dict]:
    if seen_more_ids is None:
        seen_more_ids = set()
    replies: List[Dict] = []
    for child in children:
        kind = child.get("kind")
        if kind == "t1":
            replies.append(
                _flatten_comment(
                    child,
                    fetch_more,
                    link_fullname,
                    seen_more_ids=seen_more_ids,
                )
            )
        elif kind == "more" and fetch_more:
            more_id = child.get("data", {}).get("id")
            if more_id and more_id in seen_more_ids:
                continue
            if more_id:
                seen_more_ids.add(more_id)
            fetched = fetch_more(child, link_fullname)
            if fetched:
                replies.extend(
                    _extract_comments(
                        fetched,
                        fetch_more,
                        link_fullname,
                        seen_more_ids=seen_more_ids,
                    )
                )
    return replies


def _extract_comments(
    tree: List[Dict],
    fetch_more: Optional[MoreFetcher] = None,
    link_fullname: Optional[str] = None,
    *,
    seen_more_ids: Optional[Set[str]] = None,
) -> List[Dict]:
    if seen_more_ids is None:
        seen_more_ids = set()
    comments: List[Dict] = []
    for item in tree:
        kind = item.get("kind")
        if kind == "t1":
            comments.append(
                _flatten_comment(
                    item,
                    fetch_more,
                    link_fullname,
                    seen_more_ids=seen_more_ids,
                )
            )
        elif kind == "more" and fetch_more:
            more_id = item.get("data", {}).get("id")
            if more_id and more_id in seen_more_ids:
                continue
            if more_id:
                seen_more_ids.add(more_id)
            fetched = fetch_more(item, link_fullname)
            if fetched:
                comments.extend(
                    _extract_comments(
                        fetched,
                        fetch_more,
                        link_fullname,
                        seen_more_ids=seen_more_ids,
                    )
                )
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
    matched_posts = _find_matching_posts(posts, candidate_titles)
    if not matched_posts:
        raise RuntimeError("Could not find a matching discussion thread")

    payload_threads: List[Dict] = []
    for post in matched_posts:
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

        link_fullname = submission.get("name") or f"t3_{post_id}"

        def fetch_more_children(more_item: Dict, link_id: Optional[str] = link_fullname) -> List[Dict]:
            more_data = more_item.get("data", {})
            child_ids = more_data.get("children", []) or []
            return client.get_more_children(link_id, child_ids)

        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload_threads.append(
            {
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
                "comments": _extract_comments(
                    comments_tree, fetch_more=fetch_more_children, link_fullname=link_fullname
                ),
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
