(() => {
  "use strict";

  const cfg = window.MIRROR_CONFIG;
  const tz = cfg.timezone || undefined; // undefined = browser/system timezone

  // All user-facing fallback texts in one place.
  const TEXT = {
    weatherUnavailable: "Weather unavailable",
    calendarUnavailable: "Calendar unavailable",
    calendarEmpty: "Bugün için plan yok",
    nothingPlaying: "Nothing playing",
  };

  const $ = (id) => document.getElementById(id);
  const setText = (id, value) => {
    const el = $(id);
    if (el.textContent !== value) el.textContent = value;
  };

  /* ---------- Networking ---------- */
  async function getJSON(url) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  // Chained timeouts (not setInterval) so a slow request can never overlap the next one.
  // A task returns false when it failed; then we retry sooner than the normal interval
  // (important at boot, when the Pi may start before Wi-Fi is up).
  function poll(task, seconds, retrySeconds = seconds) {
    const run = async () => {
      let ok = false;
      try { ok = (await task()) !== false; } catch (err) { console.warn(err); }
      setTimeout(run, (ok ? seconds : retrySeconds) * 1000);
    };
    run();
  }

  /* ---------- Clock, date, greeting (fully local, no network) ---------- */
  const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: tz });
  const hourFmt = new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: tz });
  const dateFmt = new Intl.DateTimeFormat(cfg.locale, { day: "numeric", month: "long", weekday: "long", timeZone: tz });

  let currentGreeting = null;
let lastGreetingChange = 0;
let currentPeriod = null;

function greetingForHour(h) {
    const greetings = {
        morning: [
            "Good morning",
            "Rise and shine",
            "Morning,",
            "Ready for the day?",
            "Let's make today count",
            "A fresh day begins"
        ],

        afternoon: [
            "Good afternoon",
            "How's your day going?",
            "Keep it going",
            "Hope your day is going well",
            "Still going strong?",
            "Halfway through the day"
        ],

        evening: [
            "Good evening",
            "Welcome back",
            "Time to slow down",
            "How was your day?",
            "Evening, Batuhan",
            "Take it easy"
        ],

        night: [
            "Good night",
            "Time to rest",
            "You made it through the day",
            "Wind down",
            "See you tomorrow",
            "Sleep well"
        ]
    };

    let period;

    if (h >= 5 && h < 12) {
        period = "morning";
    } else if (h >= 12 && h < 18) {
        period = "afternoon";
    } else if (h >= 18 && h < 23) {
        period = "evening";
    } else {
        period = "night";
    }

    const now = Date.now();

    const periodChanged = period !== currentPeriod;
    const fifteenMinutesPassed =
        now - lastGreetingChange >= 15 * 60 * 1000;

    if (
        currentGreeting === null ||
        periodChanged ||
        fifteenMinutesPassed
    ) {
        const messages = greetings[period];

        currentGreeting =
            messages[Math.floor(Math.random() * messages.length)];

        currentPeriod = period;
        lastGreetingChange = now;
    }

    return currentGreeting;
}

  function formatDate(now) {
    const p = Object.fromEntries(dateFmt.formatToParts(now).map((x) => [x.type, x.value]));
    return `${p.day} ${p.month} ${p.weekday}`; // "14 October Wednesday"
  }

  // Dev helper: open /?hour=23 to preview a greeting without waiting for that time.
  const hourOverride = new URLSearchParams(location.search).get("hour");

  function tickClock() {
    const now = new Date();
    setText("clock", timeFmt.format(now));
    setText("date", formatDate(now));
    const hour = hourOverride !== null ? parseInt(hourOverride, 10) : parseInt(hourFmt.format(now), 10);
    setText("greeting-text", greetingForHour(hour));
  }

  /* ---------- Weather ---------- */
  let weatherLoaded = false;

  function showWeatherUnavailable() {
    $("weather-condition").textContent = TEXT.weatherUnavailable;
    $("weather-condition").classList.add("is-unavailable");
    $("weather-icon").innerHTML = "";
    setText("weather-temp", "--°C");
    setText("weather-range", "");
  }

  async function updateWeather() {
    try {
      const d = await getJSON("/api/weather");
      if (!d.available) throw new Error("weather unavailable");
      $("weather-condition").classList.remove("is-unavailable");
      setText("weather-city", d.city || cfg.city);
      setText("weather-temp", `${Math.round(d.temperature_c)}°C`);
      setText("weather-condition", d.condition);
      $("weather-icon").innerHTML = window.WeatherIcons.svg(d.icon);
      const hasRange = d.high_c !== null && d.low_c !== null;
      setText("weather-range", hasRange ? `H ${Math.round(d.high_c)}°  ·  L ${Math.round(d.low_c)}°` : "");
      weatherLoaded = true;
      return true;
    } catch (err) {
      console.warn("weather:", err.message);
      if (!weatherLoaded) showWeatherUnavailable(); // otherwise keep last good data on screen
      return false;
    }
  }

  /* ---------- Calendar ---------- */
  let calendarLoaded = false;

  function renderPlan(items) {
    $("plan-list").replaceChildren(...items);
  }

  function planMessage(text) {
    const li = document.createElement("li");
    li.className = "plan__empty";
    li.textContent = text;
    return li;
  }

  async function updateCalendar() {
    try {
      const d = await getJSON("/api/calendar");
      if (!d.available) throw new Error("calendar unavailable");
      if (d.events.length === 0) {
        renderPlan([planMessage(TEXT.calendarEmpty)]);
      } else {
        // textContent (not innerHTML): event titles come from the outside world.
        renderPlan(
          d.events.slice(0, 8).map((ev) => {
            const li = document.createElement("li");
            li.className = "plan__item";
            const time = document.createElement("span");
            time.className = "plan__time";
            time.textContent = ev.start;
            const title = document.createElement("span");
            title.textContent = ev.title;
            li.append(time, title);
            return li;
          })
        );
      }
      calendarLoaded = true;
      return true;
    } catch (err) {
      console.warn("calendar:", err.message);
      if (!calendarLoaded) renderPlan([planMessage(TEXT.calendarUnavailable)]);
      return false;
    }
  }

  /* ---------- Spotify ---------- */
  // Offline or blocked artwork: hide the image instead of showing a broken-image icon.
  $("music-art").addEventListener("error", (e) => {
    e.target.dataset.failed = "1";
    e.target.hidden = true;
  });

  const music = { playing: false, progressMs: 0, durationMs: 0, fetchedAt: 0 };

  const fmtMs = (ms) => {
    const total = Math.floor(ms / 1000);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  };

  function showIdle() {
    music.playing = false;
    $("music").classList.add("is-idle");
    setText("music-idle", TEXT.nothingPlaying);
  }

  function renderMusic(d) {
    if (!(d.available && d.is_playing && d.title)) return showIdle();

    $("music").classList.remove("is-idle");
    setText("music-title", d.title);
    setText("music-artist", d.artist);
    setText("music-total", fmtMs(d.duration_ms));

    const art = $("music-art");
    if (d.artwork_url && art.getAttribute("src") !== d.artwork_url) {
      art.src = d.artwork_url;
      delete art.dataset.failed;
    }
    art.hidden = !d.artwork_url || art.dataset.failed === "1";

    music.playing = true;
    music.progressMs = d.progress_ms;
    music.durationMs = d.duration_ms;
    music.fetchedAt = performance.now();
    tickMusic();
  }

  // The server is polled every few seconds; between polls we advance the bar locally.
  function tickMusic() {
    if (!music.playing || !music.durationMs) return;
    const current = Math.min(music.durationMs, music.progressMs + (performance.now() - music.fetchedAt));
    setText("music-elapsed", fmtMs(current));
    $("music-fill").style.width = `${(current / music.durationMs) * 100}%`;
  }

  async function updateSpotify() {
    try {
      renderMusic(await getJSON("/api/spotify"));
    } catch (err) {
      console.warn("spotify:", err.message);
      showIdle(); // an unreachable Spotify just looks like "nothing playing"
    }
  }

  /* ---------- Indoor sensors ---------- */
  async function updateSensors() {
    try {
      const d = await getJSON("/api/sensors");
      if (!d.available) throw new Error("sensor unavailable");
      setText("room-temp", `${d.temperature_c.toFixed(1)}°C`);
      setText("room-humidity", `${Math.round(d.humidity_pct)}% humidity`);
      $("room-temp").classList.remove("is-unavailable");
    } catch (err) {
      console.warn("sensors:", err.message);
      // Stale room data would be misleading, so show placeholders instead.
      setText("room-temp", "--.-°C");
      setText("room-humidity", "--% humidity");
      $("room-temp").classList.add("is-unavailable");
    }
  }

  /* ---------- Start ---------- */
  setText("weather-city", cfg.city);
  tickClock();
  setInterval(() => { tickClock(); tickMusic(); }, 1000);

  poll(updateSensors, cfg.intervals.sensors);
  poll(updateSpotify, cfg.intervals.spotify);
  poll(updateWeather, cfg.intervals.weather, 30);
  poll(updateCalendar, cfg.intervals.calendar, 30);
})();
