"""Offline Spotify tests: network calls are replaced with fakes."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from modules.spotify import NowPlaying, SpotifyWebProvider, parse_playback
from modules.spotify_auth import SCOPES, SpotifyAuth, SpotifyAuthError

TRACK = {
    "is_playing": True,
    "progress_ms": 137000,
    "item": {
        "type": "track",
        "name": "Bir Derdim Var",
        "duration_ms": 268000,
        "artists": [{"name": "Mor ve Ötesi"}],
        "album": {"images": [
            {"url": "big", "width": 640}, {"url": "mid", "width": 300}, {"url": "small", "width": 64},
        ]},
    },
}


def response(status=200, payload=None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    r.headers = headers or {}
    r.raise_for_status.return_value = None
    return r


class ParsePlaybackTests(unittest.TestCase):
    def test_track(self):
        np = parse_playback(TRACK)
        self.assertEqual((np.title, np.artist), ("Bir Derdim Var", "Mor ve Ötesi"))
        self.assertEqual((np.progress_ms, np.duration_ms), (137000, 268000))
        self.assertEqual(np.artwork_url, "mid")  # closest to 300px
        self.assertTrue(np.is_playing)

    def test_multiple_artists(self):
        data = json.loads(json.dumps(TRACK))
        data["item"]["artists"] = [{"name": "A"}, {"name": "B"}]
        self.assertEqual(parse_playback(data).artist, "A, B")

    def test_paused_is_idle(self):
        self.assertFalse(parse_playback({**TRACK, "is_playing": False}).is_playing)

    def test_ad_without_item_is_idle(self):
        self.assertEqual(parse_playback({"is_playing": True, "item": None}), NowPlaying())

    def test_podcast_episode(self):
        data = {"is_playing": True, "progress_ms": 5, "item": {
            "type": "episode", "name": "Ep 1", "duration_ms": 1000,
            "show": {"name": "My Show"}, "images": [{"url": "cover", "width": 300}]}}
        np = parse_playback(data)
        self.assertEqual((np.title, np.artist, np.artwork_url), ("Ep 1", "My Show", "cover"))

    def test_missing_images(self):
        data = json.loads(json.dumps(TRACK))
        data["item"]["album"] = {}
        self.assertEqual(parse_playback(data).artwork_url, "")


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "token.json"
        self.auth = SpotifyAuth("cid", "secret", "http://127.0.0.1:5050/spotify/callback", self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def _login(self, token_payload):
        state = parse_qs(urlparse(self.auth.authorize_url()).query)["state"][0]
        with patch("modules.spotify_auth.requests.post", return_value=response(200, token_payload)):
            self.auth.handle_callback("code123", state)

    def test_authorize_url(self):
        q = parse_qs(urlparse(self.auth.authorize_url()).query)
        self.assertEqual(q["client_id"], ["cid"])
        self.assertEqual(q["scope"], [SCOPES])
        self.assertEqual(q["redirect_uri"], ["http://127.0.0.1:5050/spotify/callback"])
        self.assertNotIn("client_secret", q)  # the secret never goes through the browser

    def test_callback_rejects_unknown_state(self):
        with self.assertRaises(SpotifyAuthError):
            self.auth.handle_callback("code", "forged-state")

    def test_login_saves_token_with_private_permissions(self):
        self._login({"access_token": "A", "refresh_token": "R", "expires_in": 3600})
        self.assertTrue(self.auth.is_authorized())
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "R")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_token_survives_restart(self):
        self._login({"access_token": "A", "refresh_token": "R", "expires_in": 3600})
        again = SpotifyAuth("cid", "secret", "uri", self.path)
        self.assertTrue(again.is_authorized())

    def test_refresh_keeps_old_refresh_token_when_none_returned(self):
        self._login({"access_token": "A", "refresh_token": "R", "expires_in": 1})  # expires immediately
        with patch("modules.spotify_auth.requests.post",
                   return_value=response(200, {"access_token": "B", "expires_in": 3600})) as post:
            self.assertEqual(self.auth.get_access_token(), "B")
            self.assertEqual(post.call_args.kwargs["data"]["refresh_token"], "R")
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "R")

    def test_revoked_login_is_forgotten(self):
        self._login({"access_token": "A", "refresh_token": "R", "expires_in": 1})
        with patch("modules.spotify_auth.requests.post",
                   return_value=response(400, {"error": "invalid_grant"})):
            with self.assertRaises(SpotifyAuthError):
                self.auth.get_access_token()
        self.assertFalse(self.auth.is_authorized())
        self.assertFalse(self.path.exists())

    def test_not_configured(self):
        empty = SpotifyAuth("", "", "", self.path)
        with self.assertRaises(SpotifyAuthError):
            empty.authorize_url()


class ProviderTests(unittest.TestCase):
    def make(self, authorized=True):
        auth = MagicMock()
        auth.is_authorized.return_value = authorized
        auth.get_access_token.return_value = "tok"
        return SpotifyWebProvider(auth)

    def test_not_connected_returns_unavailable(self):
        self.assertFalse(self.make(authorized=False).get_now_playing().available)

    @patch("modules.spotify.requests.get")
    def test_playing(self, get):
        get.return_value = response(200, TRACK)
        np = self.make().get_now_playing()
        self.assertTrue(np.is_playing)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

    @patch("modules.spotify.requests.get")
    def test_204_means_idle_not_error(self, get):
        get.return_value = response(204)
        np = self.make().get_now_playing()
        self.assertTrue(np.available)
        self.assertFalse(np.is_playing)

    @patch("modules.spotify.requests.get")
    def test_rate_limit_blocks_further_calls(self, get):
        get.return_value = response(429, headers={"Retry-After": "60"})
        provider = self.make()
        with self.assertRaises(RuntimeError):
            provider.get_now_playing()
        with self.assertRaises(RuntimeError):
            provider.get_now_playing()
        self.assertEqual(get.call_count, 1)  # second call never reached Spotify


if __name__ == "__main__":
    unittest.main()
