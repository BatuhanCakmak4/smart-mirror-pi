"""Offline tests: the network is replaced with fake responses."""
import unittest
from unittest.mock import MagicMock, patch

import requests

from modules.cache import StaleCache
from modules.weather import OpenMeteoWeatherProvider, describe_weather_code

FAKE_FORECAST = {
    "current": {"temperature_2m": 17.6, "weather_code": 2, "is_day": 1},
    "daily": {"temperature_2m_max": [21.3], "temperature_2m_min": [11.8]},
}


def fake_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class WeatherCodeTests(unittest.TestCase):
    def test_known_codes(self):
        self.assertEqual(describe_weather_code(0, True), ("Clear", "clear"))
        self.assertEqual(describe_weather_code(63, True), ("Rain", "rain"))
        self.assertEqual(describe_weather_code(95, True), ("Thunderstorm", "storm"))

    def test_night_icons(self):
        self.assertEqual(describe_weather_code(0, False), ("Clear", "clear_night"))
        self.assertEqual(describe_weather_code(2, False), ("Partly cloudy", "cloudy"))

    def test_unknown_code(self):
        self.assertEqual(describe_weather_code(1234, True), ("Unknown", "unknown"))


class ProviderTests(unittest.TestCase):
    @patch("modules.weather.requests.get")
    def test_parses_open_meteo_response(self, get):
        get.return_value = fake_response(FAKE_FORECAST)
        report = OpenMeteoWeatherProvider("Weingarten", 47.81, 9.64).get_weather()
        self.assertEqual(report.city, "Weingarten")
        self.assertEqual(report.temperature_c, 17.6)
        self.assertEqual(report.condition, "Partly cloudy")
        self.assertEqual(report.icon, "partly_cloudy")
        self.assertEqual((report.high_c, report.low_c), (21.3, 11.8))

    @patch("modules.weather.requests.get")
    def test_geocodes_city_when_no_coordinates(self, get):
        geo = fake_response({"results": [{"latitude": 47.8, "longitude": 9.6, "admin1": "BW", "country": "Germany"}]})
        get.side_effect = [geo, fake_response(FAKE_FORECAST)]
        report = OpenMeteoWeatherProvider("Weingarten", None, None).get_weather()
        self.assertEqual(report.temperature_c, 17.6)
        self.assertEqual(get.call_count, 2)

    @patch("modules.weather.requests.get")
    def test_second_call_uses_cache(self, get):
        get.return_value = fake_response(FAKE_FORECAST)
        provider = OpenMeteoWeatherProvider("Weingarten", 47.81, 9.64)
        provider.get_weather()
        provider.get_weather()
        self.assertEqual(get.call_count, 1)

    @patch("modules.weather.requests.get")
    def test_fails_when_offline_and_nothing_cached(self, get):
        get.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(RuntimeError):
            OpenMeteoWeatherProvider("Weingarten", 47.81, 9.64).get_weather()


class StaleCacheTests(unittest.TestCase):
    def test_serves_stale_value_when_refresh_fails(self):
        cache = StaleCache("t", ttl_seconds=0, max_stale_seconds=3600, retry_after=0)
        self.assertEqual(cache.get(lambda: "fresh"), "fresh")

        def broken():
            raise ConnectionError("down")

        self.assertEqual(cache.get(broken), "fresh")

    def test_backoff_avoids_hammering_failing_source(self):
        cache = StaleCache("t", ttl_seconds=0, max_stale_seconds=3600, retry_after=60)
        cache.get(lambda: "fresh")
        calls = []

        def broken():
            calls.append(1)
            raise ConnectionError("down")

        cache.get(broken)
        cache.get(broken)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
