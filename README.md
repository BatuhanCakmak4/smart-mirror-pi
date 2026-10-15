# Smart Mirror

A lightweight Raspberry Pi smart mirror dashboard built with Flask and plain HTML/CSS/JS.

## Quick start (macOS)

    python3 -m venv venv && source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    python run.py

Open http://127.0.0.1:5050

## Status
- Phase 1: dashboard UI, clock, greeting, mock data
- Phase 2: real weather via Open-Meteo (free, no API key), with caching and offline fallback
- Phase 3: Spotify now playing via the Web API (OAuth handled by the backend)
- Phase 4: Apple/iCloud Calendar via CalDAV (app-specific password)

## Configuration
Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Meaning |
|---|---|
| `SMART_MIRROR_NAME` | Name shown in the greeting |
| `CITY`, `LATITUDE`, `LONGITUDE` | Weather location (coordinates recommended) |
| `WEATHER_SOURCE` | `openmeteo` (real) or `mock` |
| `SPOTIFY_SOURCE` | `auto`, `spotify` or `mock` |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | From the Spotify developer dashboard (secret stays in `.env`) |
| `SPOTIFY_REDIRECT_URI` | Must match the dashboard exactly; use `127.0.0.1`, not `localhost` |
| `CALENDAR_SOURCE` | `auto`, `icloud` or `mock` |
| `APPLE_USERNAME`, `APPLE_APP_PASSWORD` | Apple ID e-mail and an *app-specific* password |
| `CALENDAR_NAMES` | Optional comma-separated calendar filter |
| `TIMEZONE` | IANA name, empty = system timezone |
| `HARDWARE_MODE` | `mock` on Mac, `raspberrypi` on the Pi |

## Tests
    python -m unittest discover -v

## Screenshots
_Coming soon._

## Spotify setup
1. Create an app at https://developer.spotify.com/dashboard (the owning account needs Spotify Premium).
2. Add the redirect URI `http://127.0.0.1:5050/spotify/callback` and enable the Web API.
3. Put the Client ID and Client Secret in `.env`, restart the app.
4. Open http://127.0.0.1:5050/spotify/login once and approve access.
The refresh token is stored in `.cache/spotify_token.json` (git-ignored).

## Calendar setup
1. Create an app-specific password at https://account.apple.com (Sign-In and Security).
2. Put your Apple ID e-mail and that password in `.env`.
3. Check it: `python -m scripts.list_calendars` (lists calendars and today's events).
