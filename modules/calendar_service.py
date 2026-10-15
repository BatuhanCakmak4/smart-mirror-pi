"""Today's schedule: iCloud (CalDAV) provider plus a mock for development.

Layers, so the tricky logic can be tested without a network:
  CalDAVFetcher      talks to iCloud, returns RawEvent objects      (needs `caldav`)
  normalize_events   filters to today, fixes timezones, sorts       (pure Python)
  CalDAVCalendarProvider  adds caching around the two
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.cache import StaleCache

log = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    start: str            # "HH:MM" local time ("" for all-day events)
    title: str
    end: str = ""         # "HH:MM", clipped to the end of today
    all_day: bool = False


@dataclass
class TodaySchedule:
    events: list[CalendarEvent] = field(default_factory=list)
    available: bool = True


class CalendarProvider(ABC):
    @abstractmethod
    def get_today(self) -> TodaySchedule:
        """Return today's events: all-day first, then by start time."""


# ------------------------------------------------------------------ time zone
def resolve_timezone(name: str) -> tzinfo:
    """TIMEZONE from .env if set, otherwise the operating system's timezone."""
    if name:
        return ZoneInfo(name)
    try:
        target = os.path.realpath("/etc/localtime")  # symlink into the zoneinfo database
        if "zoneinfo/" in target:
            return ZoneInfo(target.split("zoneinfo/", 1)[1])
    except (OSError, ValueError, ZoneInfoNotFoundError):
        pass
    return datetime.now().astimezone().tzinfo  # fixed-offset fallback


# ------------------------------------------------------------- normalization
@dataclass
class RawEvent:
    start: date | datetime
    end: date | datetime | None
    title: str
    cancelled: bool = False


def _is_all_day(value) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _localize(value: datetime, tz: tzinfo) -> datetime:
    # A "floating" time (no timezone in the file) means local time.
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


def normalize_events(raw: list[RawEvent], day_start: datetime, day_end: datetime, tz: tzinfo) -> list[CalendarEvent]:
    today = day_start.date()
    all_day: list[CalendarEvent] = []
    timed: list[tuple[datetime, CalendarEvent]] = []
    seen: set[tuple] = set()

    for r in raw:
        if r.cancelled:
            continue
        title = r.title or "(no title)"

        if _is_all_day(r.start):
            # iCalendar all-day DTEND is exclusive: a one-day event ends the next day.
            end = r.end if _is_all_day(r.end) else r.start + timedelta(days=1)
            key = ("all-day", title)
            if r.start <= today < end and key not in seen:
                seen.add(key)
                all_day.append(CalendarEvent(start="", title=title, all_day=True))
            continue

        start = _localize(r.start, tz)
        end = _localize(r.end, tz) if isinstance(r.end, datetime) else start
        if end > start:
            overlaps = start < day_end and end > day_start
        else:  # zero-length event: it counts if it starts today
            overlaps = day_start <= start < day_end
        key = (start, title)
        if not overlaps or key in seen:
            continue
        seen.add(key)

        shown_start = max(start, day_start)
        shown_end = shown_start if end <= start else min(end, day_end - timedelta(minutes=1))
        timed.append(
            (shown_start, CalendarEvent(shown_start.strftime("%H:%M"), title, shown_end.strftime("%H:%M")))
        )

    timed.sort(key=lambda item: (item[0], item[1].title))
    return sorted(all_day, key=lambda e: e.title) + [event for _, event in timed]


# ---------------------------------------------------------------- iCloud I/O
def parse_ical(data) -> list[RawEvent]:
    """Turn one iCalendar text blob into RawEvents (needs the `icalendar` package)."""
    from icalendar import Calendar

    events = []
    for comp in Calendar.from_ical(data).walk("VEVENT"):
        dtstart = comp.get("dtstart")
        if dtstart is None:
            continue
        start = dtstart.dt
        dtend, duration = comp.get("dtend"), comp.get("duration")
        if dtend is not None:
            end = dtend.dt
        elif duration is not None:
            end = start + duration.dt
        else:
            end = None
        events.append(
            RawEvent(
                start=start,
                end=end,
                title=str(comp.get("summary", "")).strip(),
                cancelled=str(comp.get("status", "")).upper() == "CANCELLED",
            )
        )
    return events


class CalDAVFetcher:
    def __init__(self, url: str, username: str, password: str, calendar_names: tuple[str, ...] = ()):
        self._url = url
        self._username = username
        self._password = password
        self._wanted = {n.lower() for n in calendar_names}

    def fetch(self, start: datetime, end: datetime) -> list[RawEvent]:
        try:
            import caldav
        except ImportError as exc:
            raise RuntimeError("the 'caldav' package is missing; run: pip install -r requirements.txt") from exc

        raw: list[RawEvent] = []
        tried = failed = 0
        with caldav.DAVClient(
            url=self._url, username=self._username, password=self._password, timeout=15
        ) as client:
            for calendar in client.principal().calendars():
                name = (calendar.name or "").strip()
                if self._wanted and name.lower() not in self._wanted:
                    continue
                tried += 1
                try:
                    # expand=True turns "every Monday" into the concrete occurrences in this range
                    found = calendar.search(start=start, end=end, event=True, expand=True)
                except Exception as exc:  # one broken calendar (e.g. a reminders list) must not hide the rest
                    failed += 1
                    log.warning("calendar %r skipped: %s", name, exc)
                    continue
                for item in found:
                    raw.extend(parse_ical(item.data))

        if self._wanted and tried == 0:
            raise RuntimeError("none of CALENDAR_NAMES matched; run: python -m scripts.list_calendars")
        if tried and failed == tried:
            raise RuntimeError("no calendar could be read")
        return raw


# ------------------------------------------------------------------ providers
class CalDAVCalendarProvider(CalendarProvider):
    def __init__(self, fetcher, tz: tzinfo):
        self._fetcher = fetcher
        self._tz = tz
        self._cache_day: date | None = None
        self._cache: StaleCache[TodaySchedule] | None = None

    def get_today(self) -> TodaySchedule:
        today = datetime.now(self._tz).date()
        if self._cache_day != today:
            # New day = new cache, so yesterday's schedule is never shown as stale data.
            self._cache = StaleCache("calendar", ttl_seconds=240, max_stale_seconds=12 * 3600, retry_after=60)
            self._cache_day = today
        return self._cache.get(lambda: self._load(today))

    def _load(self, today: date) -> TodaySchedule:
        day_start = datetime.combine(today, time.min, tzinfo=self._tz)
        day_end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=self._tz)
        raw = self._fetcher.fetch(day_start, day_end)
        return TodaySchedule(events=normalize_events(raw, day_start, day_end, self._tz))


class MockCalendarProvider(CalendarProvider):
    def get_today(self) -> TodaySchedule:
        return TodaySchedule(
            events=[
                CalendarEvent("09:00", "Mathematics", "10:30"),
                CalendarEvent("13:30", "Project Meeting", "14:30"),
                CalendarEvent("17:00", "Gym", "18:00"),
                CalendarEvent("20:00", "Dinner", "21:30"),
            ]
        )


def get_calendar_provider(settings) -> CalendarProvider:
    if settings.calendar_source == "icloud":
        fetcher = CalDAVFetcher(
            settings.caldav_url, settings.apple_username, settings.apple_app_password, settings.calendar_names
        )
        return CalDAVCalendarProvider(fetcher, resolve_timezone(settings.timezone))
    return MockCalendarProvider()
