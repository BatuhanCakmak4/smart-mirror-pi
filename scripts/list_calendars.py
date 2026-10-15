"""Diagnostic tool.   Run from the project root:   python -m scripts.list_calendars

Checks your iCloud login, lists your calendars (use these names in CALENDAR_NAMES)
and prints what the mirror would show for today.
"""
import sys

from config.settings import settings
from modules.calendar_service import CalDAVCalendarProvider, CalDAVFetcher, resolve_timezone


def main() -> int:
    if not (settings.apple_username and settings.apple_app_password):
        print("Set APPLE_USERNAME and APPLE_APP_PASSWORD in .env first.")
        return 1

    try:
        import caldav

        with caldav.DAVClient(
            url=settings.caldav_url,
            username=settings.apple_username,
            password=settings.apple_app_password,
            timeout=15,
        ) as client:
            calendars = client.principal().calendars()
    except Exception as exc:
        print(f"Login failed: {exc.__class__.__name__}: {exc}")
        print("Check APPLE_USERNAME (Apple ID e-mail) and that APPLE_APP_PASSWORD is an app-specific password.")
        return 1

    print(f"Login OK. {len(calendars)} calendar(s) found:")
    for calendar in calendars:
        print(f"  - {calendar.name}")

    fetcher = CalDAVFetcher(
        settings.caldav_url, settings.apple_username, settings.apple_app_password, settings.calendar_names
    )
    try:
        schedule = CalDAVCalendarProvider(fetcher, resolve_timezone(settings.timezone)).get_today()
    except Exception as exc:
        print(f"Could not read events: {exc}")
        return 1

    print("\nToday on the mirror:")
    if not schedule.events:
        print("  (no events)")
    for ev in schedule.events:
        when = "All day" if ev.all_day else f"{ev.start}-{ev.end}"
        print(f"  {when:<12} {ev.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
