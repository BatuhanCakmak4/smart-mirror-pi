"""Spotify OAuth (Authorization Code flow), handled entirely by the backend.

The browser never sees the client secret or any token. Tokens are stored in
.cache/spotify_token.json (git-ignored, owner-readable only).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
# Least privilege: this is the only scope GET /me/player needs.
SCOPES = "user-read-playback-state"
HTTP_TIMEOUT = 8
STATE_TTL = 600  # seconds a login attempt stays valid
REFRESH_MARGIN = 60  # refresh the access token this many seconds before it expires


class SpotifyAuthError(RuntimeError):
    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent  # True = the stored login is dead, user must reconnect


class SpotifyAuth:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, token_path: Path):
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._token_path = Path(token_path)
        self._lock = threading.Lock()
        self._states: dict[str, float] = {}
        self._tokens: dict | None = self._load()

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret and self._redirect_uri)

    def is_authorized(self) -> bool:
        return self._tokens is not None

    # ---- login flow -------------------------------------------------------
    def authorize_url(self) -> str:
        if not self.configured:
            raise SpotifyAuthError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set in .env")
        state = secrets.token_urlsafe(16)
        now = time.monotonic()
        with self._lock:
            self._states = {s: t for s, t in self._states.items() if now - t < STATE_TTL}
            self._states[state] = now
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "scope": SCOPES,
                "redirect_uri": self._redirect_uri,
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    def handle_callback(self, code: str, state: str) -> None:
        with self._lock:
            created = self._states.pop(state, None)
        if created is None or time.monotonic() - created > STATE_TTL:
            raise SpotifyAuthError("Invalid or expired login attempt (state mismatch)")
        if not code:
            raise SpotifyAuthError("Spotify did not send an authorization code")
        payload = self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": self._redirect_uri}
        )
        with self._lock:
            self._store(payload, previous_refresh=None)
        log.info("Spotify connected")

    # ---- tokens -----------------------------------------------------------
    def get_access_token(self) -> str:
        with self._lock:
            if self._tokens is None:
                raise SpotifyAuthError("Spotify is not connected")
            if time.time() >= self._tokens["expires_at"] - REFRESH_MARGIN:
                self._refresh_locked()
            return self._tokens["access_token"]

    def _refresh_locked(self) -> None:
        try:
            payload = self._token_request(
                {"grant_type": "refresh_token", "refresh_token": self._tokens["refresh_token"]}
            )
        except SpotifyAuthError as exc:
            if exc.permanent:
                log.warning("Spotify login was revoked or expired; open /spotify/login to reconnect")
                self._tokens = None
                self._token_path.unlink(missing_ok=True)
            raise
        self._store(payload, previous_refresh=self._tokens["refresh_token"])

    def _token_request(self, data: dict) -> dict:
        try:
            resp = requests.post(
                TOKEN_URL, data=data, auth=(self._client_id, self._client_secret), timeout=HTTP_TIMEOUT
            )
        except requests.RequestException as exc:
            raise SpotifyAuthError(f"token request failed: {exc.__class__.__name__}") from exc
        if resp.status_code != 200:
            try:
                error = resp.json().get("error", "")
            except ValueError:
                error = ""
            raise SpotifyAuthError(
                f"token request rejected (HTTP {resp.status_code} {error})".strip(),
                permanent=(error == "invalid_grant"),
            )
        return resp.json()

    def _store(self, payload: dict, previous_refresh: str | None) -> None:
        # Spotify only sometimes returns a new refresh token; keep the old one otherwise.
        refresh = payload.get("refresh_token") or previous_refresh
        if not refresh:
            raise SpotifyAuthError("Spotify did not return a refresh token")
        self._tokens = {
            "access_token": payload["access_token"],
            "refresh_token": refresh,
            "expires_at": time.time() + int(payload.get("expires_in", 3600)),
            "scope": payload.get("scope", ""),
        }
        self._save()

    # ---- persistence ------------------------------------------------------
    def _load(self) -> dict | None:
        try:
            data = json.loads(self._token_path.read_text())
            if all(k in data for k in ("access_token", "refresh_token", "expires_at")):
                return data
        except (OSError, ValueError):
            pass
        return None

    def _save(self) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._token_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner-only
        with os.fdopen(fd, "w") as fh:
            json.dump(self._tokens, fh)
        os.replace(tmp, self._token_path)  # atomic: a power cut never leaves a half-written file
