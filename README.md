# Reddit Daily Discussion Scraper

This project downloads the r/wallstreetbets daily (and weekend) discussion threads using the official Reddit API and saves the thread metadata and comments to JSON files.

## Features

* Built on top of [PRAW](https://praw.readthedocs.io/) for resilient access to the official Reddit API.
* Script-only OAuth flow using your Reddit application credentials.
* Automatically searches for daily and weekend discussion thread titles matching the supplied date.
* Recursively fetches the full comment tree and stores it alongside metadata such as scores, authors and timestamps.

## Requirements

* Python 3.10+
* A Reddit application with `client_credentials` access. Create one at <https://www.reddit.com/prefs/apps>.

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Provide your Reddit API credentials via environment variables or CLI options and run the scraper for the desired date:

```bash
export REDDIT_CLIENT_ID="your_client_id"
export REDDIT_CLIENT_SECRET="your_client_secret"
export REDDIT_USER_AGENT="wsb-scraper/0.1 by yourusername"

python -m reddit_scraper --date 2024-04-17
```

By default the JSON output is written to `data/<date>.json`. Use `--output` to choose a custom path and `--subreddit` to target another subreddit.

## Output format

The generated JSON file contains the thread metadata, all comments (with nested replies) and the timestamp when the data was fetched. Example structure:

```json
{
  "thread": {
    "id": "abc123",
    "title": "Daily Discussion Thread for April 17, 2024",
    "author": "AutoModerator",
    "created_utc": 1713331200.0,
    "permalink": "/r/wallstreetbets/comments/abc123/daily_discussion_thread_for_april_17_2024/",
    "num_comments": 1234,
    "score": 100,
    "upvote_ratio": 0.95,
    "selftext": "..."
  },
  "comments": [
    {
      "id": "cmt1",
      "author": "user",
      "created_utc": 1713331300.0,
      "body": "Comment text",
      "score": 10,
      "permalink": "/r/wallstreetbets/comments/abc123/daily_discussion_thread_for_april_17_2024/cmt1/",
      "parent_id": "t3_abc123",
      "replies": [
        {
          "id": "cmt2",
          "author": "user2",
          "created_utc": 1713331400.0,
          "body": "Reply text",
          "score": 5,
          "permalink": "/r/wallstreetbets/comments/abc123/daily_discussion_thread_for_april_17_2024/cmt2/",
          "parent_id": "t1_cmt1",
          "replies": []
        }
      ]
    }
  ],
  "fetched_at": "2024-04-18T12:34:56Z"
}
```

## Notes

* Reddit enforces rate limits. The script currently performs a single API call per run, so it should comfortably remain within the limits for personal use.
* The search query includes a three-day window of possible titles to accommodate weekend thread naming conventions.
