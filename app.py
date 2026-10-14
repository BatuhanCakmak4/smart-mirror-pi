"""Flask application factory and routes."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request

from config.settings import REFRESH_SECONDS, settings
from modules.calendar_service import get_calendar_provider
from modules.sensors import get_sensor_provider
from modules.spotify import get_spotify_provider
from modules.spotify_auth import SpotifyAuth, SpotifyAuthError
from modules.weather import get_weather_provider


def _safe(app: Flask, name: str, producer) -> dict:
    """Run a provider; on any failure log it and return a harmless 'unavailable' payload."""
    try:
        return asdict(producer())
    except RuntimeError as exc:
        # Expected failure (e.g. no internet and nothing cached): one short line, no stack trace.
        app.logger.warning("%s unavailable: %s", name, exc)
        return {"available": False}
    except Exception:
        app.logger.exception("%s provider crashed", name)
        return {"available": False}


def create_app() -> Flask:
    app = Flask(__name__)

    spotify_auth = None
    if settings.spotify_source == "spotify":
        spotify_auth = SpotifyAuth(
            settings.spotify_client_id,
            settings.spotify_client_secret,
            settings.spotify_redirect_uri,
            settings.spotify_token_path,
        )

    weather = get_weather_provider(settings)
    calendar = get_calendar_provider(settings)
    spotify = get_spotify_provider(settings, spotify_auth)
    sensors = get_sensor_provider(settings)

    client_config = {
        "name": settings.mirror_name,
        "city": settings.city,
        "timezone": settings.timezone,
        "locale": settings.display_locale,
        "intervals": REFRESH_SECONDS,
    }

    @app.after_request
    def no_store(response):
        # API data must always be fresh; static files can use normal caching.
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            mirror_name=settings.mirror_name,
            hide_cursor=settings.hide_cursor,
            client_config=client_config,
        )

    # ---- Spotify login (one-time setup, opened by hand in a browser) ----------
    @app.get("/spotify/login")
    def spotify_login():
        if spotify_auth is None:
            return render_template(
                "message.html",
                message="Spotify is in mock mode. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env, then restart.",
            ), 400
        try:
            return redirect(spotify_auth.authorize_url())
        except SpotifyAuthError as exc:
            return render_template("message.html", message=str(exc)), 400

    @app.get("/spotify/callback")
    def spotify_callback():
        if spotify_auth is None:
            return render_template("message.html", message="Spotify is not enabled."), 404
        if request.args.get("error"):
            return render_template(
                "message.html", message=f"Spotify login was cancelled or failed ({request.args['error']})."
            ), 400
        try:
            spotify_auth.handle_callback(request.args.get("code", ""), request.args.get("state", ""))
        except SpotifyAuthError as exc:
            app.logger.warning("Spotify callback failed: %s", exc)
            return render_template(
                "message.html", message="Login failed. Open /spotify/login to try again."
            ), 400
        return render_template("message.html", message="Spotify connected. You can close this tab.")

    # ---- JSON API used by the dashboard ----------------------------------------
    @app.get("/api/weather")
    def api_weather():
        return jsonify(_safe(app, "weather", weather.get_weather))

    @app.get("/api/calendar")
    def api_calendar():
        return jsonify(_safe(app, "calendar", calendar.get_today))

    @app.get("/api/spotify")
    def api_spotify():
        return jsonify(_safe(app, "spotify", spotify.get_now_playing))

    @app.get("/api/sensors")
    def api_sensors():
        return jsonify(_safe(app, "sensors", sensors.read))

    @app.get("/api/dashboard")
    def api_dashboard():
        return jsonify(
            {
                "weather": _safe(app, "weather", weather.get_weather),
                "calendar": _safe(app, "calendar", calendar.get_today),
                "spotify": _safe(app, "spotify", spotify.get_now_playing),
                "sensors": _safe(app, "sensors", sensors.read),
            }
        )

    @app.get("/api/status")
    def api_status():
        return jsonify(
            {
                "ok": True,
                "environment": settings.environment,
                "hardware_mode": settings.hardware_mode,
                "spotify_source": settings.spotify_source,
                "spotify_connected": bool(spotify_auth and spotify_auth.is_authorized()),
                "server_time": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        )

    return app
