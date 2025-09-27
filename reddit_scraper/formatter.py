"""Utilities for generating expected Reddit discussion thread titles."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


@dataclass(frozen=True)
class ThreadTitleFormat:
    """Represents a discussion thread title template."""

    name: str
    template: str

    def render(self, target_date: date) -> str:
        human_date = target_date.strftime("%B %d, %Y").replace(" 0", " ")
        return self.template.format(date=human_date)


DAILY_THREAD = ThreadTitleFormat(
    name="daily",
    template="Daily Discussion Thread for {date}",
)

WEEKEND_THREAD = ThreadTitleFormat(
    name="weekend",
    template="Weekend Discussion Thread for the Weekend of {date}",
)


def iter_possible_titles(target_date: date) -> Iterable[str]:
    """Yield expected thread titles for the given date.

    Weekdays are served by the standard daily discussion thread. On Fridays
    both a daily and a weekend discussion thread are expected, with the
    weekend thread also using the Friday date. For Saturday and Sunday the
    search should only consider the weekend thread that references the Friday
    starting that weekend.
    """

    weekday = target_date.weekday()

    if weekday < 4:  # Monday through Thursday
        yield DAILY_THREAD.render(target_date)
        return

    if weekday == 4:  # Friday
        yield DAILY_THREAD.render(target_date)
        yield WEEKEND_THREAD.render(target_date)
        return

    # Saturday or Sunday: look for the weekend thread referencing Friday
    days_since_friday = weekday - 4
    friday_date = target_date - timedelta(days=days_since_friday)
    yield WEEKEND_THREAD.render(friday_date)
