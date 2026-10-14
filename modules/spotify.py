"""Spotify now-playing: real Web API provider plus a mock for development."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from modules.cache import StaleCache
from modules.spotify_auth import SpotifyAuth

log = logging.getLogger(__name__)

PLAYER_URL = "https://api.spotify.com/v1/me/player"
HTTP_TIMEOUT = 8
ARTWORK_TARGET_WIDTH = 300  # px; plenty for a 9rem cover, small download on a Pi


@dataclass
class NowPlaying:
    available: bool = True
    is_playing: bool = False
    title: str = ""
    artist: str = ""
    artwork_url: str = ""
    progress_ms: int = 0
    duration_ms: int = 0


class SpotifyProvider(ABC):
    @abstractmethod
    def get_now_playing(self) -> NowPlaying:
        """Return the current playback state. Nothing playing is NOT an error."""


# ---------------------------------------------------------------- parsing
def _pick_image(images: list[dict]) -> str:
    """Choose the image whose width is closest to ARTWORK_TARGET_WIDTH."""
    if not images:
        return ""
    best = min(images, key=lambda i: abs((i.get("width") or ARTWORK_TARGET_WIDTH) - ARTWORK_TARGET_WIDTH))
    return best.get("url", "")


def parse_playback(data: dict) -> NowPlaying:
    """Convert a GET /me/player response into NowPlaying. Paused, ads and idle all become 'idle'."""
    item = data.get("item")
    if not data.get("is_playing") or not item:
        return NowPlaying()

    if item.get("type") == "episode":  # podcast
        show = item.get("show") or {}
        artist = show.get("name", "")
        images = item.get("images") or show.get("images") or []
    else:
        artist = ", ".join(a.get("name", "") for a in item.get("artists") or [])
        images = (item.get("album") or {}).get("images") or []

    return NowPlaying(
        is_playing=True,
        title=item.get("name", ""),
        artist=artist,
        artwork_url=_pick_image(images),
        progress_ms=int(data.get("progress_ms") or 0),
        duration_ms=int(item.get("duration_ms") or 0),
    )


# --------------------------------------------------------------- providers
class SpotifyWebProvider(SpotifyProvider):
    def __init__(self, auth: SpotifyAuth):
        self._auth = auth
        # Several browser windows or a quick refresh share one Spotify call per 3 s.
        # If Spotify is unreachable, the last state is shown for at most 20 s.
        self._cache: StaleCache[NowPlaying] = StaleCache(
            "spotify", ttl_seconds=3, max_stale_seconds=20, retry_after=15
        )
        self._blocked_until = 0.0
        self._warned = False

    def get_now_playing(self) -> NowPlaying:
        if not self._auth.is_authorized():
            if not self._warned:
                log.warning("Spotify is not connected yet. Open http://127.0.0.1:<PORT>/spotify/login once.")
                self._warned = True
            return NowPlaying(available=False)
        return self._cache.get(self._fetch)

    def _fetch(self) -> NowPlaying:
        if time.monotonic() < self._blocked_until:
            raise RuntimeError("waiting out a Spotify rate limit")

        resp = requests.get(
            PLAYER_URL,
            headers={"Authorization": f"Bearer {self._auth.get_access_token()}"},
            params={"additional_types": "track,episode"},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code == 204:  # no active device: nothing is playing anywhere
            return NowPlaying()
        if resp.status_code == 429:
            self._blocked_until = time.monotonic() + int(resp.headers.get("Retry-After", "30"))
            raise RuntimeError("rate limited by Spotify")
        resp.raise_for_status()
        return parse_playback(resp.json())


class MockSpotifyProvider(SpotifyProvider):
    DURATION_MS = 268_000  # 4:28

    def __init__(self, state: str = "playing"):
        self._state = state
        self._started = time.monotonic()
        self._start_offset_ms = 137_000  # begin at 2:17 like the design example

    def get_now_playing(self) -> NowPlaying:
        if self._state == "idle":
            return NowPlaying()
        elapsed_ms = int((time.monotonic() - self._started) * 1000)
        return NowPlaying(
            is_playing=True,
            title="Bir Derdim Var",
            artist="Mor ve Ötesi",
            artwork_url="/static/images/placeholder-cover.svg",
            progress_ms=(self._start_offset_ms + elapsed_ms) % self.DURATION_MS,
            duration_ms=self.DURATION_MS,
        )


def get_spotify_provider(settings, auth: SpotifyAuth | None = None) -> SpotifyProvider:
    if settings.spotify_source == "spotify" and auth is not None:
        return SpotifyWebProvider(auth)
    return MockSpotifyProvider(settings.mock_spotify_state)
