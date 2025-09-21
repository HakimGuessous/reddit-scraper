"""Utilities for generating expected Reddit discussion thread titles."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List


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
    """Yield likely thread titles around the given date.

    Weekend discussion threads often cover the entire weekend and may use the
    Friday, Saturday or Sunday date. To increase the chance of finding a match
    we generate titles for a three day window around the provided date.
    """

    templates: List[ThreadTitleFormat] = [DAILY_THREAD, WEEKEND_THREAD]
    for delta in range(-1, 2):
        shifted = target_date + timedelta(days=delta)
        for template in templates:
            yield template.render(shifted)
