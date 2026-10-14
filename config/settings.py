"""Central configuration: reads .env once and exposes an immutable Settings object."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

log = logging.getLogger(__name__)

# How often (seconds) the browser asks the backend for each widget.
REFRESH_SECONDS = {
    "sensors": 5,
    "spotify": 5,
    "weather": 900,   # 15 minutes
    "calendar": 300,  # 5 minutes
}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    return _env(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        log.warning("Invalid integer for %s, using %s", name, default)
        return default


def _env_float(name: str) -> float | None:
    raw = _env(name)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid number for %s, ignoring it", name)
        return None


def _valid_timezone(name: str) -> str:
    if not name:
        return ""
    try:
        ZoneInfo(name)
        return name
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("Unknown TIMEZONE %r, falling back to system timezone", name)
        return ""


@dataclass(frozen=True)
class Settings:
    environment: str
    debug: bool
    host: str
    port: int
    mirror_name: str
    city: str
    latitude: float | None
    longitude: float | None
    timezone: str
    display_locale: str
    hide_cursor: bool
    hardware_mode: str
    weather_source: str
    mock_spotify_state: str
    spotify_source: str
    spotify_client_id: str
    spotify_client_secret: str = field(repr=False)  # keep the secret out of logs
    spotify_redirect_uri: str
    spotify_token_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        environment = _env("FLASK_ENV", "development")

        hardware_mode = _env("HARDWARE_MODE", "mock").lower()
        if hardware_mode not in {"mock", "raspberrypi"}:
            log.warning("Unknown HARDWARE_MODE %r, using 'mock'", hardware_mode)
            hardware_mode = "mock"

        weather_source = _env("WEATHER_SOURCE", "openmeteo").lower()
        if weather_source not in {"openmeteo", "mock"}:
            log.warning("Unknown WEATHER_SOURCE %r, using 'openmeteo'", weather_source)
            weather_source = "openmeteo"

        spotify_state = _env("MOCK_SPOTIFY_STATE", "playing").lower()
        if spotify_state not in {"playing", "idle"}:
            spotify_state = "playing"

        port = _env_int("PORT", 5050)
        client_id = _env("SPOTIFY_CLIENT_ID")
        client_secret = _env("SPOTIFY_CLIENT_SECRET")

        spotify_source = _env("SPOTIFY_SOURCE", "auto").lower()
        if spotify_source not in {"auto", "spotify", "mock"}:
            log.warning("Unknown SPOTIFY_SOURCE %r, using 'auto'", spotify_source)
            spotify_source = "auto"
        if spotify_source == "auto":
            spotify_source = "spotify" if client_id and client_secret else "mock"

        # Spotify only accepts HTTPS or a loopback IP; "localhost" is rejected.
        redirect_uri = _env("SPOTIFY_REDIRECT_URI") or f"http://127.0.0.1:{port}/spotify/callback"
        if "//localhost" in redirect_uri:
            log.warning("SPOTIFY_REDIRECT_URI uses 'localhost'; Spotify requires 127.0.0.1 instead")

        return cls(
            environment=environment,
            debug=environment == "development",
            host=_env("HOST", "127.0.0.1"),
            port=port,
            mirror_name=_env("SMART_MIRROR_NAME", "Mirror"),
            city=_env("CITY", "Weingarten"),
            latitude=_env_float("LATITUDE"),
            longitude=_env_float("LONGITUDE"),
            timezone=_valid_timezone(_env("TIMEZONE")),
            display_locale=_env("DISPLAY_LOCALE", "en-GB"),
            hide_cursor=_env_bool("HIDE_CURSOR", False),
            hardware_mode=hardware_mode,
            weather_source=weather_source,
            mock_spotify_state=spotify_state,
            spotify_source=spotify_source,
            spotify_client_id=client_id,
            spotify_client_secret=client_secret,
            spotify_redirect_uri=redirect_uri,
            spotify_token_path=BASE_DIR / ".cache" / "spotify_token.json",
        )


settings = Settings.from_env()
