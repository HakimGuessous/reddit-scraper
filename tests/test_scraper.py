import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, List, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reddit_scraper.scraper import (
    ScraperConfig,
    _extract_comments,
    _find_matching_post,
    _find_matching_posts,
    _flatten_comment,
    scrape_discussion_thread,
)


class StubAuthor:
    def __init__(self, name: str) -> None:
        self.name = name


class StubComment:
    def __init__(
        self,
        comment_id: str,
        author: str | None,
        created_utc: float,
        body: str,
        score: int,
        permalink: str,
        parent_id: str,
        replies: Sequence["StubComment"] | None = None,
    ) -> None:
        self.id = comment_id
        self.author = StubAuthor(author) if author is not None else None
        self.created_utc = created_utc
        self.body = body
        self.score = score
        self.permalink = permalink
        self.parent_id = parent_id
        self.replies = list(replies or [])


class StubSubmission:
    def __init__(
        self,
        submission_id: str,
        title: str,
        author: str,
        created_utc: float,
        permalink: str,
        num_comments: int,
        score: int,
        upvote_ratio: float,
        selftext: str,
        comments: Sequence[StubComment] | None = None,
    ) -> None:
        self.id = submission_id
        self.title = title
        self.author = StubAuthor(author)
        self.created_utc = created_utc
        self.permalink = permalink
        self.num_comments = num_comments
        self.score = score
        self.upvote_ratio = upvote_ratio
        self.selftext = selftext
        self.comments = list(comments or [])


@pytest.fixture
def sample_posts() -> List[StubSubmission]:
    return [
        StubSubmission(
            "ignored",
            "Random thread",
            author="User",
            created_utc=0.0,
            permalink="/r/test/ignored",
            num_comments=0,
            score=0,
            upvote_ratio=0.0,
            selftext="",
        ),
        StubSubmission(
            "abc",
            "Daily Discussion Thread for April 20, 2024",
            author="AutoModerator",
            created_utc=1.0,
            permalink="/r/test/abc",
            num_comments=10,
            score=1,
            upvote_ratio=0.9,
            selftext="",
        ),
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
        StubSubmission(
            "ghi",
            "Weekend Discussion Thread for the Weekend of April 20, 2024",
            author="AutoModerator",
            created_utc=2.0,
            permalink="/r/test/ghi",
            num_comments=5,
            score=2,
            upvote_ratio=0.8,
            selftext="",
        ),
        StubSubmission(
            "def",
            "Daily Discussion Thread for April 21, 2024",
            author="AutoModerator",
            created_utc=3.0,
            permalink="/r/test/def",
            num_comments=7,
            score=3,
            upvote_ratio=0.85,
            selftext="",
        ),
    ]

    candidate_titles = [
        "Daily Discussion Thread for April 20, 2024",
        "Weekend Discussion Thread for the Weekend of April 20, 2024",
        "Daily Discussion Thread for April 21, 2024",
    ]

    matches = _find_matching_posts(posts, candidate_titles)

    assert [post.id for post in matches] == ["abc", "ghi", "def"]


def test_flatten_comment_recursively_processes_replies():
    child = StubComment(
        "c2",
        author="user2",
        created_utc=2,
        body="child",
        score=5,
        permalink="/permalink2",
        parent_id="t1_c1",
        replies=None,
    )
    comment = StubComment(
        "c1",
        author="user1",
        created_utc=1,
        body="parent",
        score=10,
        permalink="/permalink1",
        parent_id="t3_post",
        replies=[child],
    )

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
        StubComment(
            "c1",
            author="user",
            created_utc=0,
            body="body",
            score=0,
            permalink="/permalink",
            parent_id="t3_post",
        ),
        object(),
    ]

    comments = _extract_comments(tree)

    assert len(comments) == 1
    assert comments[0]["id"] == "c1"


class FakeRedditClient:
    def __init__(self, _creds: Any) -> None:
        self.search_calls: List[Any] = []
        self.get_submission_calls: List[str] = []

    def search_subreddit(self, subreddit: str, query: str, **params: Any) -> List[StubSubmission]:
        self.search_calls.append((subreddit, query, params))
        return [
            StubSubmission(
                "post123",
                "Daily Discussion Thread for April 20, 2024",
                author="AutoModerator",
                created_utc=1000,
                permalink="/r/test/post123",
                num_comments=42,
                score=100,
                upvote_ratio=0.95,
                selftext="",
            )
        ]

    def get_submission(self, submission_id: str) -> StubSubmission:
        self.get_submission_calls.append(submission_id)
        return StubSubmission(
            submission_id,
            "Daily Discussion Thread for April 20, 2024",
            author="AutoModerator",
            created_utc=1000,
            permalink="/r/test/post123",
            num_comments=42,
            score=100,
            upvote_ratio=0.95,
            selftext="Thread body",
            comments=[
                StubComment(
                    "c1",
                    author="commenter",
                    created_utc=1010,
                    body="Comment",
                    score=1,
                    permalink="/r/test/comments/post123/c1/",
                    parent_id="t3_post123",
                )
            ],
        )


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
        def search_subreddit(self, subreddit: str, query: str, **params: Any) -> List[StubSubmission]:
            self.search_calls.append((subreddit, query, params))
            return []

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
        def search_subreddit(self, subreddit: str, query: str, **params: Any) -> List[StubSubmission]:
            self.search_calls.append((subreddit, query, params))
            return [
                StubSubmission(
                    "daily1",
                    "Daily Discussion Thread for April 19, 2024",
                    author="AutoModerator",
                    created_utc=1000,
                    permalink="/r/test/daily1",
                    num_comments=10,
                    score=50,
                    upvote_ratio=0.9,
                    selftext="",
                ),
                StubSubmission(
                    "weekend1",
                    "Weekend Discussion Thread for the Weekend of April 19, 2024",
                    author="AutoModerator",
                    created_utc=900,
                    permalink="/r/test/weekend1",
                    num_comments=20,
                    score=80,
                    upvote_ratio=0.92,
                    selftext="",
                ),
            ]

        def get_submission(self, submission_id: str) -> StubSubmission:
            self.get_submission_calls.append(submission_id)
            if submission_id == "daily1":
                return StubSubmission(
                    "daily1",
                    "Daily Discussion Thread for April 19, 2024",
                    author="AutoModerator",
                    created_utc=1000,
                    permalink="/r/test/daily1",
                    num_comments=10,
                    score=50,
                    upvote_ratio=0.9,
                    selftext="Daily body",
                    comments=[
                        StubComment(
                            "c_daily",
                            author="user_daily",
                            created_utc=1010,
                            body="Daily comment",
                            score=5,
                            permalink="/r/test/comments/daily1/c_daily/",
                            parent_id="t3_daily1",
                        )
                    ],
                )
            if submission_id == "weekend1":
                return StubSubmission(
                    "weekend1",
                    "Weekend Discussion Thread for the Weekend of April 19, 2024",
                    author="AutoModerator",
                    created_utc=900,
                    permalink="/r/test/weekend1",
                    num_comments=20,
                    score=80,
                    upvote_ratio=0.92,
                    selftext="Weekend body",
                    comments=[
                        StubComment(
                            "c_weekend",
                            author="user_weekend",
                            created_utc=1020,
                            body="Weekend comment",
                            score=7,
                            permalink="/r/test/comments/weekend1/c_weekend/",
                            parent_id="t3_weekend1",
                        )
                    ],
                )
            raise AssertionError(f"Unexpected post_id {submission_id}")

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


def test_scrape_discussion_thread_handles_nested_replies(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "reddit_scraper.scraper.iter_possible_titles",
        lambda target_date: ["Daily Discussion Thread for April 20, 2024"],
    )

    class NestedClient(FakeRedditClient):
        def get_submission(self, submission_id: str) -> StubSubmission:
            self.get_submission_calls.append(submission_id)
            return StubSubmission(
                submission_id,
                "Daily Discussion Thread for April 20, 2024",
                author="AutoModerator",
                created_utc=1000,
                permalink="/r/test/post123",
                num_comments=1,
                score=10,
                upvote_ratio=0.9,
                selftext="Body",
                comments=[
                    StubComment(
                        "parent",
                        author="u1",
                        created_utc=1,
                        body="Parent",
                        score=0,
                        permalink="/r/test/comments/post123/parent/",
                        parent_id="t3_post123",
                        replies=[
                            StubComment(
                                "child1",
                                author="u2",
                                created_utc=2,
                                body="Child",
                                score=1,
                                permalink="/r/test/comments/post123/child1/",
                                parent_id="t1_parent",
                            )
                        ],
                    )
                ],
            )

    monkeypatch.setattr("reddit_scraper.scraper.RedditClient", NestedClient)

    config = ScraperConfig(client_id="id", client_secret="secret", user_agent="agent")
    target_date = date(2024, 4, 20)
    output_path = tmp_path / "output.json"

    scrape_discussion_thread(config, target_date, output_path)

    payload = json.loads(output_path.read_text())
    comments = payload["threads"][0]["comments"]
    assert comments[0]["replies"][0]["id"] == "child1"


from reddit_scraper.formatter import iter_possible_titles


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
