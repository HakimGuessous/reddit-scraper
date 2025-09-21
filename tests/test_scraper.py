import json
import sys
import types
from datetime import date
from pathlib import Path


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

from reddit_scraper.scraper import (
    ScraperConfig,
    _extract_comments,
    _find_matching_post,
    _flatten_comment,
    scrape_discussion_thread,
)


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


class FakeRedditClient:
    def __init__(self, _creds):
        self.search_calls = []
        self.comment_calls = []

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
    assert payload["thread"]["id"] == "post123"
    assert payload["thread"]["selftext"] == "Thread body"
    assert payload["comments"] == [
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
