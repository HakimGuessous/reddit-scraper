import json
import sys
import types
from datetime import date
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _raise_unexpected_call(*args, **kwargs):
    raise AssertionError("requests should not be invoked during unit tests")


requests_stub = types.SimpleNamespace(
    auth=types.SimpleNamespace(HTTPBasicAuth=lambda client_id, client_secret: (client_id, client_secret)),
    post=_raise_unexpected_call,
    request=_raise_unexpected_call,
)

sys.modules.setdefault("requests", requests_stub)

import pytest

from reddit_scraper.reddit_client import RedditClient, RedditCredentials
from reddit_scraper.scraper import (
    ScraperConfig,
    _extract_comments,
    _find_matching_post,
    _find_matching_posts,
    _flatten_comment,
    scrape_discussion_thread,
)
from reddit_scraper.formatter import iter_possible_titles


@pytest.fixture
def sample_posts():
    return [
        {"data": {"title": "Random thread"}},
        {"data": {"title": "Daily Discussion Thread for April 20, 2024", "id": "abc"}},
    ]


def test_find_matching_post_returns_first_match(sample_posts):
    candidate_titles = [
        "daily discussion thread for april 20, 2024",
        "Another title",
    ]

    match = _find_matching_post(sample_posts, candidate_titles)

    assert match == sample_posts[1]


def test_find_matching_post_returns_none_when_no_match(sample_posts):
    candidate_titles = ["Unrelated title"]

    match = _find_matching_post(sample_posts, candidate_titles)

    assert match is None


def test_find_matching_posts_returns_all_matches(sample_posts):
    posts = sample_posts + [
        {"data": {"title": "Weekend Discussion Thread for the Weekend of April 20, 2024", "id": "ghi"}},
        {"data": {"title": "Daily Discussion Thread for April 21, 2024", "id": "def"}},
    ]

    candidate_titles = [
        "Daily Discussion Thread for April 20, 2024",
        "Weekend Discussion Thread for the Weekend of April 20, 2024",
        "Daily Discussion Thread for April 21, 2024",
    ]

    matches = _find_matching_posts(posts, candidate_titles)

    assert [post["data"]["id"] for post in matches] == ["abc", "ghi", "def"]


def test_flatten_comment_recursively_processes_replies():
    comment = {
        "kind": "t1",
        "data": {
            "id": "c1",
            "author": "user1",
            "created_utc": 1,
            "body": "parent",
            "score": 10,
            "permalink": "/permalink1",
            "parent_id": "t3_post",
            "replies": {
                "data": {
                    "children": [
                        {
                            "kind": "t1",
                            "data": {
                                "id": "c2",
                                "author": "user2",
                                "created_utc": 2,
                                "body": "child",
                                "score": 5,
                                "permalink": "/permalink2",
                                "parent_id": "t1_c1",
                                "replies": ""
                            },
                        },
                        {"kind": "more", "data": {"id": "ignored"}},
                    ]
                }
            },
        },
    }

    flattened = _flatten_comment(comment)

    assert flattened["id"] == "c1"
    assert flattened["author"] == "user1"
    assert flattened["replies"] == [
        {
            "id": "c2",
            "author": "user2",
            "created_utc": 2,
            "body": "child",
            "score": 5,
            "permalink": "/permalink2",
            "parent_id": "t1_c1",
            "replies": [],
        }
    ]


def test_extract_comments_filters_non_comment_objects():
    tree = [
        {"kind": "t1", "data": {"id": "c1", "replies": ""}},
        {"kind": "more", "data": {"id": "ignored"}},
    ]

    comments = _extract_comments(tree)

    assert len(comments) == 1
    assert comments[0]["id"] == "c1"


def test_extract_comments_fetches_more_children():
    more_node = {"kind": "more", "data": {"children": ["c_more"]}}
    tree = [
        {
            "kind": "t1",
            "data": {
                "id": "c1",
                "author": "user1",
                "created_utc": 1,
                "body": "parent",
                "score": 10,
                "permalink": "/permalink1",
                "parent_id": "t3_post",
                "replies": {"data": {"children": [more_node]}},
            },
        }
    ]

    def fetch_more(more_item, link_fullname):
        assert link_fullname == "t3_post"
        assert more_item["data"]["children"] == ["c_more"]
        return [
            {
                "kind": "t1",
                "data": {
                    "id": "c_more",
                    "author": "user2",
                    "created_utc": 2,
                    "body": "child",
                    "score": 5,
                    "permalink": "/permalink2",
                    "parent_id": "t1_c1",
                    "replies": "",
                },
            }
        ]

    comments = _extract_comments(tree, fetch_more=fetch_more, link_fullname="t3_post")

    assert comments[0]["replies"] == [
        {
            "id": "c_more",
            "author": "user2",
            "created_utc": 2,
            "body": "child",
            "score": 5,
            "permalink": "/permalink2",
            "parent_id": "t1_c1",
            "replies": [],
        }
    ]


def test_get_more_children_batches_requests():
    class CapturingClient(RedditClient):
        def __init__(self) -> None:
            super().__init__(
                RedditCredentials(client_id="id", client_secret="secret", user_agent="ua")
            )
            self.calls: List[Dict[str, Any]] = []

        def get(self, path: str, **kwargs: Any) -> Dict[str, Any]:  # type: ignore[override]
            self.calls.append({"path": path, "params": kwargs.get("params", {})})
            children = kwargs["params"]["children"].split(",")
            return {"json": {"data": {"things": [{"name": c} for c in children]}}}

    client = CapturingClient()
    children = [f"t1_child_{i}" for i in range(205)]

    things = client.get_more_children("t3_post", children)

    assert len(client.calls) == 3
    sizes = [len(call["params"]["children"].split(",")) for call in client.calls]
    assert sizes == [100, 100, 5]
    assert [item["name"] for item in things] == children


class FakeRedditClient:
    def __init__(self, _creds):
        self.search_calls = []
        self.comment_calls = []
        self.more_calls = []

    def search_subreddit(self, subreddit, query, **params):
        self.search_calls.append((subreddit, query, params))
        return {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "post123",
                            "title": "Daily Discussion Thread for April 20, 2024",
                            "author": "AutoModerator",
                            "created_utc": 1000,
                            "permalink": "/r/test/post123",
                            "num_comments": 42,
                            "score": 100,
                            "upvote_ratio": 0.95,
                        }
                    }
                ]
            }
        }

    def get_post_comments(self, subreddit, post_id, **params):
        self.comment_calls.append((subreddit, post_id, params))
        return [
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "selftext": "Thread body"
                            }
                        }
                    ]
                }
            },
            {
                "data": {
                    "children": [
                        {
                            "kind": "t1",
                            "data": {
                                "id": "c1",
                                "author": "commenter",
                                "created_utc": 1010,
                                "body": "Comment",
                                "score": 1,
                                "permalink": "/r/test/comments/post123/c1/",
                                "parent_id": "t3_post123",
                                "replies": "",
                            },
                        }
                    ]
                }
            },
        ]

    def get_more_children(self, link_fullname, children, **params):
        self.more_calls.append((link_fullname, tuple(children), params))
        return []


def test_scrape_discussion_thread_writes_expected_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "reddit_scraper.scraper.iter_possible_titles",
        lambda target_date: ["Daily Discussion Thread for April 20, 2024"],
    )
    monkeypatch.setattr("reddit_scraper.scraper.RedditClient", FakeRedditClient)

    config = ScraperConfig(client_id="id", client_secret="secret", user_agent="agent")
    target_date = date(2024, 4, 20)
    output_path = tmp_path / "output.json"

    result = scrape_discussion_thread(config, target_date, output_path)

    assert result == output_path
    assert output_path.exists()

    payload = json.loads(output_path.read_text())
    assert len(payload["threads"]) == 1
    thread_payload = payload["threads"][0]
    assert thread_payload["thread"]["id"] == "post123"
    assert thread_payload["thread"]["selftext"] == "Thread body"
    assert thread_payload["comments"] == [
        {
            "id": "c1",
            "author": "commenter",
            "created_utc": 1010,
            "body": "Comment",
            "score": 1,
            "permalink": "/r/test/comments/post123/c1/",
            "parent_id": "t3_post123",
            "replies": [],
        }
    ]
    assert "fetched_at" in payload
    assert "fetched_at" in thread_payload


def test_scrape_discussion_thread_raises_when_no_match(monkeypatch, tmp_path):
    class EmptyClient(FakeRedditClient):
        def search_subreddit(self, subreddit, query, **params):
            return {"data": {"children": []}}

    monkeypatch.setattr(
        "reddit_scraper.scraper.iter_possible_titles",
        lambda target_date: ["Daily Discussion Thread for April 20, 2024"],
    )
    monkeypatch.setattr("reddit_scraper.scraper.RedditClient", EmptyClient)

    config = ScraperConfig(client_id="id", client_secret="secret", user_agent="agent")
    target_date = date(2024, 4, 20)

    with pytest.raises(RuntimeError):
        scrape_discussion_thread(config, target_date, tmp_path / "output.json")


def test_scrape_discussion_thread_handles_multiple_matches(monkeypatch, tmp_path):
    class MultiPostClient(FakeRedditClient):
        def search_subreddit(self, subreddit, query, **params):
            self.search_calls.append((subreddit, query, params))
            return {
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "daily1",
                                "title": "Daily Discussion Thread for April 19, 2024",
                                "author": "AutoModerator",
                                "created_utc": 1000,
                                "permalink": "/r/test/daily1",
                                "num_comments": 10,
                                "score": 50,
                                "upvote_ratio": 0.9,
                            }
                        },
                        {
                            "data": {
                                "id": "weekend1",
                                "title": "Weekend Discussion Thread for the Weekend of April 19, 2024",
                                "author": "AutoModerator",
                                "created_utc": 900,
                                "permalink": "/r/test/weekend1",
                                "num_comments": 20,
                                "score": 80,
                                "upvote_ratio": 0.92,
                            }
                        },
                    ]
                }
            }

        def get_post_comments(self, subreddit, post_id, **params):
            self.comment_calls.append((subreddit, post_id, params))
            if post_id == "daily1":
                return [
                    {"data": {"children": [{"data": {"selftext": "Daily body"}}]}},
                    {
                        "data": {
                            "children": [
                                {
                                    "kind": "t1",
                                    "data": {
                                        "id": "c_daily",
                                        "author": "user_daily",
                                        "created_utc": 1010,
                                        "body": "Daily comment",
                                        "score": 5,
                                        "permalink": "/r/test/comments/daily1/c_daily/",
                                        "parent_id": "t3_daily1",
                                        "replies": "",
                                    },
                                }
                            ]
                        }
                    },
                ]
            if post_id == "weekend1":
                return [
                    {"data": {"children": [{"data": {"selftext": "Weekend body"}}]}},
                    {
                        "data": {
                            "children": [
                                {
                                    "kind": "t1",
                                    "data": {
                                        "id": "c_weekend",
                                        "author": "user_weekend",
                                        "created_utc": 1020,
                                        "body": "Weekend comment",
                                        "score": 7,
                                        "permalink": "/r/test/comments/weekend1/c_weekend/",
                                        "parent_id": "t3_weekend1",
                                        "replies": "",
                                    },
                                }
                            ]
                        }
                    },
                ]
            raise AssertionError(f"Unexpected post_id {post_id}")

    monkeypatch.setattr("reddit_scraper.scraper.RedditClient", MultiPostClient)

    config = ScraperConfig(client_id="id", client_secret="secret", user_agent="agent")
    target_date = date(2024, 4, 19)
    output_path = tmp_path / "output.json"

    scrape_discussion_thread(config, target_date, output_path)

    payload = json.loads(output_path.read_text())
    assert len(payload["threads"]) == 2
    ids = {entry["thread"]["id"] for entry in payload["threads"]}
    assert ids == {"daily1", "weekend1"}

    daily_entry = next(entry for entry in payload["threads"] if entry["thread"]["id"] == "daily1")
    weekend_entry = next(entry for entry in payload["threads"] if entry["thread"]["id"] == "weekend1")

    assert daily_entry["thread"]["selftext"] == "Daily body"
    assert daily_entry["comments"][0]["id"] == "c_daily"

    assert weekend_entry["thread"]["selftext"] == "Weekend body"
    assert weekend_entry["comments"][0]["id"] == "c_weekend"


def test_scrape_discussion_thread_fetches_more_comments(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "reddit_scraper.scraper.iter_possible_titles",
        lambda target_date: ["Daily Discussion Thread for April 20, 2024"],
    )

    class MoreClient(FakeRedditClient):
        def get_post_comments(self, subreddit, post_id, **params):
            self.comment_calls.append((subreddit, post_id, params))
            return [
                {"data": {"children": [{"data": {"selftext": "Body"}}]}},
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "id": "parent",
                                    "author": "u1",
                                    "created_utc": 1,
                                    "body": "Parent",
                                    "score": 0,
                                    "permalink": "/r/test/comments/post123/parent/",
                                    "parent_id": "t3_post123",
                                    "replies": {
                                        "data": {
                                            "children": [
                                                {
                                                    "kind": "more",
                                                    "data": {"children": ["child1"]},
                                                }
                                            ]
                                        }
                                    },
                                },
                            }
                        ]
                    }
                },
            ]

        def get_more_children(self, link_fullname, children, **params):
            self.more_calls.append((link_fullname, tuple(children), params))
            assert link_fullname == "t3_post123"
            assert tuple(children) == ("child1",)
            return [
                {
                    "kind": "t1",
                    "data": {
                        "id": "child1",
                        "author": "u2",
                        "created_utc": 2,
                        "body": "Child",
                        "score": 1,
                        "permalink": "/r/test/comments/post123/child1/",
                        "parent_id": "t1_parent",
                        "replies": "",
                    },
                }
            ]

    monkeypatch.setattr("reddit_scraper.scraper.RedditClient", MoreClient)

    config = ScraperConfig(client_id="id", client_secret="secret", user_agent="agent")
    target_date = date(2024, 4, 20)
    output_path = tmp_path / "output.json"

    scrape_discussion_thread(config, target_date, output_path)

    payload = json.loads(output_path.read_text())
    comments = payload["threads"][0]["comments"]
    assert comments[0]["replies"][0]["id"] == "child1"


def test_iter_possible_titles_weekday_only_daily():
    titles = list(iter_possible_titles(date(2024, 4, 17)))  # Wednesday

    assert titles == ["Daily Discussion Thread for April 17, 2024"]


def test_iter_possible_titles_friday_includes_weekend_thread():
    titles = list(iter_possible_titles(date(2024, 4, 19)))

    assert titles == [
        "Daily Discussion Thread for April 19, 2024",
        "Weekend Discussion Thread for the Weekend of April 19, 2024",
    ]


def test_iter_possible_titles_weekend_targets_friday_weekend_thread():
    titles = list(iter_possible_titles(date(2024, 4, 20)))  # Saturday

    assert titles == ["Weekend Discussion Thread for the Weekend of April 19, 2024"]
