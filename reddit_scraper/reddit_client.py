"""Reddit client built on top of PRAW."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import praw
from prawcore import PrawcoreException

LOGGER = logging.getLogger(__name__)


class RedditAPIError(RuntimeError):
    """Raised when the Reddit API returns an error response."""


@dataclass
class RedditCredentials:
    """Holds the credentials required for script-only Reddit API access."""

    client_id: str
    client_secret: str
    user_agent: str


class RedditClient:
    """Wrapper around :mod:`praw` for scraping subreddit content."""

    def __init__(self, credentials: RedditCredentials, reddit: Optional[praw.Reddit] = None) -> None:
        self._creds = credentials
        try:
            self._reddit = reddit or praw.Reddit(
                client_id=credentials.client_id,
                client_secret=credentials.client_secret,
                user_agent=credentials.user_agent,
                check_for_async=False,
            )
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise RedditAPIError("Failed to initialise Reddit client") from exc

    def search_subreddit(self, subreddit: str, query: str, **params: Any) -> List[praw.models.Submission]:
        """Search for submissions within a subreddit.

        Parameters mirror :meth:`praw.models.Subreddit.search` with sensible defaults.
        """

        search_params: Dict[str, Any] = dict(params)
        limit = int(search_params.pop("limit", 25))
        sort = search_params.pop("sort", "new")
        time_filter = search_params.pop("time_filter", "all")
        syntax = search_params.pop("syntax", None)
        search_params.setdefault("restrict_sr", True)

        try:
            subreddit_ref = self._reddit.subreddit(subreddit)
            LOGGER.debug(
                "Searching subreddit %s with query %s (sort=%s, limit=%d)",
                subreddit,
                query,
                sort,
                limit,
            )
            submissions = subreddit_ref.search(
                query=query,
                sort=sort,
                syntax=syntax,
                time_filter=time_filter,
                limit=limit,
                params=search_params or None,
            )
            return list(submissions)
        except PrawcoreException as exc:
            raise RedditAPIError(f"Reddit search failed: {exc}") from exc

    def get_submission(self, submission_id: str) -> praw.models.Submission:
        """Return a submission with its full comment tree loaded."""

        try:
            submission = self._reddit.submission(id=submission_id)
            LOGGER.debug("Fetching submission %s", submission_id)
            # ``Submission`` objects lazily load their data when accessed, so
            # calling ``load`` is unnecessary and, with newer versions of PRAW,
            # raises ``AttributeError``. Access the comment tree directly and
            # ensure it is fully expanded instead.
            submission.comments.replace_more(limit=None)
            return submission
        except PrawcoreException as exc:
            raise RedditAPIError(f"Failed to fetch submission {submission_id}: {exc}") from exc

