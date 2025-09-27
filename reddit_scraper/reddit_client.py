"""Simple Reddit API client for authenticated requests."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests

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
    """Thin wrapper around the Reddit REST API."""

    _TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    _BASE_URL = "https://oauth.reddit.com"

    def __init__(self, credentials: RedditCredentials) -> None:
        self._creds = credentials
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0

    def _authenticate(self) -> None:
        """Fetches a new access token if the current one is missing or expired."""

        if self._access_token and time.time() < self._token_expiry:
            return

        LOGGER.debug("Requesting new Reddit access token")
        auth = requests.auth.HTTPBasicAuth(self._creds.client_id, self._creds.client_secret)
        data = {"grant_type": "client_credentials"}
        headers = {"User-Agent": self._creds.user_agent}

        response = requests.post(self._TOKEN_URL, auth=auth, data=data, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RedditAPIError(
                f"Failed to authenticate with Reddit API: {response.status_code} {response.text}"
            )

        token_data = response.json()
        self._access_token = token_data["access_token"]
        self._token_expiry = time.time() + float(token_data.get("expires_in", 3600)) - 60  # safety margin
        LOGGER.debug("Obtained new Reddit access token expiring at %s", self._token_expiry)

    def request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Performs an authenticated request against the Reddit API."""

        self._authenticate()
        headers = kwargs.pop("headers", {})
        headers.setdefault("Authorization", f"bearer {self._access_token}")
        headers.setdefault("User-Agent", self._creds.user_agent)

        url = f"{self._BASE_URL}{path}"
        LOGGER.debug("Sending %s request to %s", method, url)
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if response.status_code >= 400:
            raise RedditAPIError(
                f"Reddit API request failed: {response.status_code} {response.text}"
            )
        return response.json()

    def get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        return self.request("GET", path, **kwargs)

    def search_subreddit(self, subreddit: str, query: str, **params: Any) -> Dict[str, Any]:
        """Performs a search request within a subreddit."""

        params.setdefault("q", query)
        params.setdefault("restrict_sr", "true")
        params.setdefault("sort", "new")
        params.setdefault("limit", 25)
        return self.get(f"/r/{subreddit}/search", params=params)

    def get_post_comments(self, subreddit: str, post_id: str, **params: Any) -> Dict[str, Any]:
        params.setdefault("depth", 10)
        params.setdefault("limit", 500)
        return self.get(f"/r/{subreddit}/comments/{post_id}", params=params)

    _MAX_CHILDREN_PER_REQUEST = 100

    def get_more_children(
        self, link_fullname: str, children: Iterable[str], **params: Any
    ) -> List[Dict[str, Any]]:
        """Fetch additional comment objects referenced by a ``more`` placeholder."""

        children_list = [child for child in children if child]
        if not children_list:
            return []

        base_params: Dict[str, Any] = dict(params)
        base_params.setdefault("link_id", link_fullname)
        base_params.setdefault("api_type", "json")
        base_params.setdefault("limit_children", "false")

        things: List[Dict[str, Any]] = []
        for start in range(0, len(children_list), self._MAX_CHILDREN_PER_REQUEST):
            chunk = children_list[start : start + self._MAX_CHILDREN_PER_REQUEST]
            chunk_params = dict(base_params)
            chunk_params["children"] = ",".join(chunk)

            LOGGER.debug(
                "Fetching %d additional children for %s (offset %d)",
                len(chunk),
                link_fullname,
                start,
            )

            response = self.get("/api/morechildren", params=chunk_params)
            chunk_things = response.get("json", {}).get("data", {}).get("things", [])
            things.extend(chunk_things)

        return things
