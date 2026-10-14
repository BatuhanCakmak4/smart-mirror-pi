"""Weather data. Open-Meteo (free, no API key) for real data, a mock for offline development."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from modules.cache import StaleCache

log = logging.getLogger(__name__)

# Icon names understood by static/js/icons.js
ICONS = {"clear", "clear_night", "partly_cloudy", "cloudy", "rain", "snow", "storm", "fog", "unknown"}

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
HTTP_TIMEOUT = 8  # seconds

# WMO weather codes used by Open-Meteo -> (text, icon)
_WEATHER_CODES = {
    0: ("Clear", "clear"),
    1: ("Mostly clear", "clear"),
    2: ("Partly cloudy", "partly_cloudy"),
    3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"),
    48: ("Fog", "fog"),
    51: ("Light drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"),
    57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Light showers", "rain"),
    81: ("Showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm with hail", "storm"),
    99: ("Thunderstorm with hail", "storm"),
}

# A sun icon at night looks wrong, so some icons change after dark.
_NIGHT_ICON = {"clear": "clear_night", "partly_cloudy": "cloudy"}


def describe_weather_code(code: int, is_day: bool) -> tuple[str, str]:
    text, icon = _WEATHER_CODES.get(code, ("Unknown", "unknown"))
    if not is_day:
        icon = _NIGHT_ICON.get(icon, icon)
    return text, icon


@dataclass
class WeatherReport:
    city: str
    temperature_c: float
    condition: str
    icon: str
    high_c: float | None = None
    low_c: float | None = None
    available: bool = True


class WeatherProvider(ABC):
    @abstractmethod
    def get_weather(self) -> WeatherReport:
        """Return the current weather. May raise; the API layer handles failures."""


class MockWeatherProvider(WeatherProvider):
    def __init__(self, city: str):
        self._city = city

    def get_weather(self) -> WeatherReport:
        return WeatherReport(
            city=self._city,
            temperature_c=18,
            condition="Partly cloudy",
            icon="partly_cloudy",
            high_c=21,
            low_c=12,
        )


class OpenMeteoWeatherProvider(WeatherProvider):
    def __init__(self, city: str, latitude: float | None, longitude: float | None):
        self._city = city
        self._lat = latitude
        self._lon = longitude
        # Fresh for 10 min; if Open-Meteo is unreachable keep showing the last value up to 6 h.
        self._cache: StaleCache[WeatherReport] = StaleCache(
            "weather", ttl_seconds=600, max_stale_seconds=6 * 3600, retry_after=30
        )

    def get_weather(self) -> WeatherReport:
        return self._cache.get(self._fetch)

    def _coordinates(self) -> tuple[float, float]:
        """Use LATITUDE/LONGITUDE if configured, otherwise look the city up once."""
        if self._lat is None or self._lon is None:
            resp = requests.get(
                GEOCODING_URL,
                params={"name": self._city, "count": 1, "language": "en"},
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
            if not results:
                raise RuntimeError(f"City not found: {self._city!r}")
            place = results[0]
            self._lat, self._lon = place["latitude"], place["longitude"]
            log.info(
                "Geocoded %r -> %s, %s (%.4f, %.4f). Set LATITUDE/LONGITUDE in .env if this is the wrong place.",
                self._city, place.get("admin1", "?"), place.get("country", "?"), self._lat, self._lon,
            )
        return self._lat, self._lon

    def _fetch(self) -> WeatherReport:
        lat, lon = self._coordinates()
        resp = requests.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,is_day",
                "daily": "temperature_2m_max,temperature_2m_min",
                "forecast_days": 1,
                "timezone": "auto",
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        current, daily = data["current"], data["daily"]
        text, icon = describe_weather_code(current["weather_code"], bool(current.get("is_day", 1)))
        return WeatherReport(
            city=self._city,
            temperature_c=current["temperature_2m"],
            condition=text,
            icon=icon,
            high_c=daily["temperature_2m_max"][0],
            low_c=daily["temperature_2m_min"][0],
        )


def get_weather_provider(settings) -> WeatherProvider:
    if settings.weather_source == "mock":
        return MockWeatherProvider(settings.city)
    return OpenMeteoWeatherProvider(settings.city, settings.latitude, settings.longitude)
