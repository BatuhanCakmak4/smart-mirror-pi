// Thin line weather icons (24x24 grid). Names match modules/weather.py ICONS.
(() => {
  "use strict";

  const CLOUD = "M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z";
  const SUN_FULL =
    '<circle cx="12" cy="12" r="4"/>' +
    '<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>';

  const icons = {
    clear: SUN_FULL,
    clear_night: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    cloudy: `<path d="${CLOUD}"/>`,
    partly_cloudy:
      '<circle cx="8" cy="8" r="3"/>' +
      '<path d="M8 1.5v1.5M1.5 8H3M3.4 3.4l1 1M12.6 3.4l-1 1"/>' +
      `<path transform="translate(5 5) scale(.7)" fill="#000" d="${CLOUD}"/>`,
    rain:
      '<path d="M16 13v8M8 13v8M12 15v8M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25"/>',
    snow:
      '<path d="M20 17.58A5 5 0 0 0 18 8h-1.26A8 8 0 1 0 4 16.25M8 16h.01M8 20h.01M12 18h.01M12 22h.01M16 16h.01M16 20h.01"/>',
    storm:
      '<path d="M19 16.9A5 5 0 0 0 18 7h-1.26a8 8 0 1 0-11.62 9M13 11l-4 6h6l-4 6"/>',
    fog: '<path d="M4 8h16M2 12h20M5 16h14"/>',
    unknown: '<path d="M8 12h8"/>',
  };

  window.WeatherIcons = {
    svg(name) {
      const body = icons[name] || icons.unknown;
      return `<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
    },
  };
})();
