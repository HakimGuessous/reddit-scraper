"""Command line interface for the Reddit scraper."""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime
from pathlib import Path

from .scraper import ScraperConfig, scrape_discussion_thread

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape r/wallstreetbets discussion threads")
    parser.add_argument(
        "--client-id",
        default=os.environ.get("REDDIT_CLIENT_ID"),
        help="Reddit API client id (default: REDDIT_CLIENT_ID env var)",
    )
    parser.add_argument(
        "--client-secret",
        default=os.environ.get("REDDIT_CLIENT_SECRET"),
        help="Reddit API client secret (default: REDDIT_CLIENT_SECRET env var)",
    )
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("REDDIT_USER_AGENT"),
        help="User agent to send with Reddit requests (default: REDDIT_USER_AGENT env var)",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Target date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: ./data/<date>.json)",
    )
    parser.add_argument(
        "--subreddit",
        default="wallstreetbets",
        help="Subreddit to scrape (default: wallstreetbets)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.client_id or not args.client_secret or not args.user_agent:
        raise SystemExit("client id, secret and user agent must be provided")

    try:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"Invalid date: {exc}")

    output = Path(args.output) if args.output else Path("data") / f"{target_date.isoformat()}.json"
    config = ScraperConfig(
        client_id=args.client_id,
        client_secret=args.client_secret,
        user_agent=args.user_agent,
        subreddit=args.subreddit,
    )
    scrape_discussion_thread(config, target_date, output)


if __name__ == "__main__":
    main()
