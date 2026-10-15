"""Calendar tests. The pure logic runs offline; iCalendar parsing tests need the `icalendar` package."""
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from modules.calendar_service import (
    CalDAVCalendarProvider, RawEvent, normalize_events, parse_ical, resolve_timezone,
)

TZ = ZoneInfo("Europe/Istanbul")  # UTC+3, no DST
DAY_START = datetime(2026, 10, 14, 0, 0, tzinfo=TZ)
DAY_END = DAY_START + timedelta(days=1)


def norm(*raw):
    return normalize_events(list(raw), DAY_START, DAY_END, TZ)


def at(h, m=0, day=14):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


class NormalizeTests(unittest.TestCase):
    def test_utc_event_is_shown_in_local_time(self):
        utc = lambda h: datetime(2026, 10, 14, h, 0, tzinfo=timezone.utc)
        (ev,) = norm(RawEvent(utc(6), utc(7), "Mathematics"))
        self.assertEqual((ev.start, ev.end, ev.all_day), ("09:00", "10:00", False))

    def test_floating_time_means_local_time(self):
        (ev,) = norm(RawEvent(datetime(2026, 10, 14, 13, 30), datetime(2026, 10, 14, 14, 30), "Meeting"))
        self.assertEqual((ev.start, ev.end), ("13:30", "14:30"))

    def test_sorted_by_start_time(self):
        a, b = norm(RawEvent(at(17), at(18), "Gym"), RawEvent(at(9), at(10), "Math"))
        self.assertEqual((a.title, b.title), ("Math", "Gym"))

    def test_other_days_are_excluded(self):
        self.assertEqual(norm(RawEvent(at(9, day=13), at(10, day=13), "Yesterday")), [])
        self.assertEqual(norm(RawEvent(at(9, day=15), at(10, day=15), "Tomorrow")), [])

    def test_event_ending_exactly_at_midnight_does_not_leak_into_today(self):
        self.assertEqual(norm(RawEvent(at(22, day=13), at(0), "Late")), [])

    def test_overnight_event_is_clipped_to_today(self):
        (ev,) = norm(RawEvent(at(22, day=13), at(1), "Party"))
        self.assertEqual((ev.start, ev.end), ("00:00", "01:00"))

    def test_event_running_past_midnight_is_clipped(self):
        (ev,) = norm(RawEvent(at(23), at(2, day=15), "Night shift"))
        self.assertEqual((ev.start, ev.end), ("23:00", "23:59"))

    def test_all_day_event_comes_first(self):
        a, b = norm(RawEvent(at(9), at(10), "Math"), RawEvent(date(2026, 10, 14), date(2026, 10, 15), "Holiday"))
        self.assertTrue(a.all_day)
        self.assertEqual((a.title, b.title), ("Holiday", "Math"))

    def test_all_day_end_is_exclusive(self):
        self.assertEqual(norm(RawEvent(date(2026, 10, 13), date(2026, 10, 14), "Ended yesterday")), [])
        self.assertEqual(len(norm(RawEvent(date(2026, 10, 12), date(2026, 10, 16), "Trip"))), 1)

    def test_all_day_without_end_lasts_one_day(self):
        self.assertEqual(len(norm(RawEvent(date(2026, 10, 14), None, "Birthday"))), 1)
        self.assertEqual(norm(RawEvent(date(2026, 10, 13), None, "Birthday")), [])

    def test_cancelled_events_are_hidden(self):
        self.assertEqual(norm(RawEvent(at(9), at(10), "Math", cancelled=True)), [])

    def test_duplicates_from_shared_calendars_are_merged(self):
        self.assertEqual(len(norm(RawEvent(at(9), at(10), "Math"), RawEvent(at(9), at(10), "Math"))), 1)

    def test_missing_title_and_end(self):
        (ev,) = norm(RawEvent(at(9), None, ""))
        self.assertEqual((ev.title, ev.start, ev.end), ("(no title)", "09:00", "09:00"))


class FakeFetcher:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result or [], error, 0

    def fetch(self, start, end):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class ProviderTests(unittest.TestCase):
    def provider(self, fetcher):
        return CalDAVCalendarProvider(fetcher, TZ)

    def test_events_for_today(self):
        now = datetime.now(TZ)
        noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
        fetcher = FakeFetcher([RawEvent(noon, noon + timedelta(hours=1), "Lunch")])
        schedule = self.provider(fetcher).get_today()
        self.assertEqual([e.title for e in schedule.events], ["Lunch"])

    def test_second_call_uses_cache(self):
        fetcher = FakeFetcher()
        p = self.provider(fetcher)
        p.get_today()
        p.get_today()
        self.assertEqual(fetcher.calls, 1)

    def test_offline_with_nothing_cached_raises_runtimeerror(self):
        with self.assertRaises(RuntimeError):
            self.provider(FakeFetcher(error=ConnectionError("offline"))).get_today()


class TimezoneTests(unittest.TestCase):
    def test_explicit_timezone(self):
        self.assertEqual(str(resolve_timezone("Europe/Berlin")), "Europe/Berlin")

    def test_system_timezone_fallback_returns_a_tzinfo(self):
        self.assertIsNotNone(resolve_timezone("").utcoffset(datetime.now()))


try:
    import icalendar  # noqa: F401
    HAVE_ICALENDAR = True
except ImportError:
    HAVE_ICALENDAR = False


def ics(body):
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n{body}END:VCALENDAR\r\n"


@unittest.skipUnless(HAVE_ICALENDAR, "icalendar not installed")
class ParseIcalTests(unittest.TestCase):
    def test_utc_event(self):
        (r,) = parse_ical(ics(
            "BEGIN:VEVENT\r\nUID:1\r\nDTSTAMP:20261014T000000Z\r\n"
            "DTSTART:20261014T060000Z\r\nDTEND:20261014T073000Z\r\nSUMMARY:Mathematics\r\nEND:VEVENT\r\n"))
        self.assertEqual(r.title, "Mathematics")
        (ev,) = normalize_events([r], DAY_START, DAY_END, TZ)
        self.assertEqual((ev.start, ev.end), ("09:00", "10:30"))

    def test_tzid_event(self):
        (r,) = parse_ical(ics(
            "BEGIN:VEVENT\r\nUID:2\r\nDTSTAMP:20261014T000000Z\r\n"
            "DTSTART;TZID=Europe/Istanbul:20261014T133000\r\n"
            "DTEND;TZID=Europe/Istanbul:20261014T143000\r\nSUMMARY:Meeting\r\nEND:VEVENT\r\n"))
        (ev,) = normalize_events([r], DAY_START, DAY_END, TZ)
        self.assertEqual((ev.start, ev.end), ("13:30", "14:30"))

    def test_all_day_event(self):
        (r,) = parse_ical(ics(
            "BEGIN:VEVENT\r\nUID:3\r\nDTSTAMP:20261014T000000Z\r\n"
            "DTSTART;VALUE=DATE:20261014\r\nDTEND;VALUE=DATE:20261015\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\n"))
        (ev,) = normalize_events([r], DAY_START, DAY_END, TZ)
        self.assertTrue(ev.all_day)

    def test_duration_instead_of_dtend(self):
        (r,) = parse_ical(ics(
            "BEGIN:VEVENT\r\nUID:4\r\nDTSTAMP:20261014T000000Z\r\n"
            "DTSTART:20261014T140000Z\r\nDURATION:PT1H\r\nSUMMARY:Call\r\nEND:VEVENT\r\n"))
        (ev,) = normalize_events([r], DAY_START, DAY_END, TZ)
        self.assertEqual((ev.start, ev.end), ("17:00", "18:00"))

    def test_cancelled_status(self):
        (r,) = parse_ical(ics(
            "BEGIN:VEVENT\r\nUID:5\r\nDTSTAMP:20261014T000000Z\r\n"
            "DTSTART:20261014T060000Z\r\nDTEND:20261014T070000Z\r\nSTATUS:CANCELLED\r\nSUMMARY:X\r\nEND:VEVENT\r\n"))
        self.assertTrue(r.cancelled)


if __name__ == "__main__":
    unittest.main()
