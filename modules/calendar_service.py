"""Today's schedule. Phase 1: mock only. Phase 4 adds an iCloud CalDAV provider."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CalendarEvent:
    start: str  # "HH:MM" in local time
    title: str


@dataclass
class TodaySchedule:
    events: list[CalendarEvent] = field(default_factory=list)
    available: bool = True


class CalendarProvider(ABC):
    @abstractmethod
    def get_today(self) -> TodaySchedule:
        """Return today's events sorted by start time."""


class MockCalendarProvider(CalendarProvider):
    def get_today(self) -> TodaySchedule:
        return TodaySchedule(
            events=[
                CalendarEvent("09:00", "Mathematics"),
                CalendarEvent("13:30", "Project Meeting"),
                CalendarEvent("17:00", "Gym"),
                CalendarEvent("20:00", "Dinner"),
            ]
        )


def get_calendar_provider(settings) -> CalendarProvider:
    return MockCalendarProvider()
