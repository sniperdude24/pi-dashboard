// Weather page: radar loop, current conditions, alerts, hourly and 7-day.

// Weather Service icon codes -> our icon names.
function weatherIcon(ic) {
  if (!ic) return "cloud";
  const c = ic.code, day = ic.day;
  if (c === "skc" || c === "few") return day ? "sun" : "moon-stars";
  if (c === "sct") return day ? "cloud-sun" : "cloud-moon";
  if (c === "bkn" || c === "ovc") return "cloud";
  if (c.startsWith("wind") || c === "hurricane" || c === "tropical_storm") return "wind";
  if (c.startsWith("tsra")) return "cloud-storm";
  if (c.startsWith("rain_showers") || c === "rain") return "cloud-rain";
  if (c === "snow" || c === "blizzard") return "snowflake";
  if (/snow|sleet|fzra/.test(c)) return "cloud-snow";
  if (c === "tornado") return "tornado";
  if (c === "fog") return "cloud-fog";
  if (c === "dust" || c === "smoke" || c === "haze") return "haze";
  if (c === "hot") return "temperature-sun";
  if (c === "cold") return "temperature";
  return "cloud";
}

let W = null; // latest weather summary

// ---------- Current conditions + alerts ----------

function alertClass(event) {
  if (/warning|emergency/i.test(event)) return "sev-warning";
  if (/watch/i.test(event)) return "sev-watch";
  return "sev-advisory";
}

function renderAlerts() {
  const box = document.getElementById("alert");
  const alerts = W.alerts || [];
  if (!alerts.length) {
    box.hidden = true;
    return;
  }
  const a = alerts[0];
  const more = alerts.length > 1 ? ` · +${alerts.length - 1} more` : "";
  const sameDay = a.ends && new Date(a.ends).toDateString() === new Date().toDateString();
  const until = a.ends ? `Until ${fmtTime(a.ends, sameDay ? {} : { weekday: "short" })}` : "In effect";
  box.className = alertClass(a.event);
  box.innerHTML = `${icon("alert-triangle")}<div><div class="alert-event">${escapeHTML(a.event)}</div>
    <div class="alert-sub">${until}${more} · tap for details</div></div>`;
  box.hidden = false;
}

function openAlerts() {
  const alerts = W.alerts || [];
  const sections = [];
  for (const a of alerts) {
    sections.push({ title: a.headline || a.event, text: a.description });
    if (a.instruction) sections.push({ title: "What to do", text: a.instruction });
  }
  showOverlay(alerts.length > 1 ? `${alerts.length} weather alerts` : alerts[0].event, sections);
}

function renderNow() {
  const c = W.current;
  if (!c) return;
  document.getElementById("now-label").textContent = `Now in ${W.location.name}`;
  document.getElementById("now-icon").innerHTML = icon(weatherIcon(c.icon));
  document.getElementById("now-temp").textContent = `${c.temp}°`;
  document.getElementById("now-text").textContent = c.text || "";

  const today = (W.daily || [])[0] || {};
  document.getElementById("now-forecast").textContent = today.detail || today.night || "";
  const pop = ((W.hourly || [])[0] || {}).pop ?? 0;
  const wind = c.wind_mph ? `${c.wind_dir || ""} ${c.wind_mph} mph` : "Calm";
  const gust = c.gust_mph ? `<span>gusts ${c.gust_mph}</span>` : "";
  const now = Date.now();
  const nextSun = (W.sun || []).find((e) => new Date(e.time).getTime() > now);
  const hiLo = `${today.high ?? "--"}° / ${today.low ?? "--"}°`;
  const cells = [
    ["Feels like", `${c.feels}°`],
    ["Wind", wind],
    ["Humidity", `${c.humidity}%`],
    ["Rain chance", `${pop}%`],
    ["High / low", hiLo],
    nextSun ? [nextSun.type === "sunset" ? "Sunset" : "Sunrise", fmtTime(nextSun.time)] : ["", ""],
  ];
  document.getElementById("now-grid").innerHTML = cells
    .map(([k, v]) => `<div><span>${k}</span>${v}</div>`)
    .join("");

  // Footer: where/when measured, or a warning if the data is old.
  const foot = document.getElementById("now-foot");
  const updated = W.updated && W.updated.current;
  const ageMin = updated ? (now - new Date(updated).getTime()) / 60000 : Infinity;
  if (ageMin > 30) {
    foot.className = "stale";
    foot.innerHTML = `${icon("wifi-off")} Can't reach the Weather Service · last update ${updated ? fmtTime(updated) : "never"}`;
  } else {
    foot.className = "";
    foot.textContent = `Measured at ${c.station_name || c.station} · ${fmtTime(c.time)}`;
  }
}

// ---------- Forecasts ----------

function renderHourly() {
  // Skip hours that have already ended (the saved forecast may be a few minutes old).
  const now = Date.now();
  const hours = (W.hourly || []).filter((h) => new Date(h.time).getTime() + 3600e3 > now).slice(0, 12);
  document.getElementById("hourly").innerHTML = hours
    .map(
      (h) => `<div class="hour"><div class="h">${fmtHour(h.time)}</div>${icon(weatherIcon(h.icon))}
        <div>${h.temp}°</div><div class="pop">${h.pop >= 20 ? h.pop + "%" : ""}</div></div>`,
    )
    .join("");
}

function dayName(d, i) {
  if (i === 0) return d.high === null ? "Tonight" : "Today";
  return new Date(d.date + "T12:00:00").toLocaleDateString([], { weekday: "short" });
}

function renderDaily() {
  const days = W.daily || [];
  const temps = days.flatMap((d) => [d.high, d.low]).filter((t) => t !== null);
  const min = Math.min(...temps), max = Math.max(...temps), span = Math.max(1, max - min);
  document.getElementById("daily").innerHTML = days
    .map((d, i) => {
      const lo = d.low ?? d.high, hi = d.high ?? d.low;
      const left = ((lo - min) / span) * 100, width = Math.max(4, ((hi - lo) / span) * 100);
      return `<div class="day" data-i="${i}">
        <div class="name">${dayName(d, i)}</div>${icon(weatherIcon(d.icon))}
        <div class="pop">${d.pop >= 20 ? d.pop + "%" : ""}</div>
        <div class="lo">${d.low ?? ""}${d.low !== null ? "°" : ""}</div>
        <div class="bar"><div style="left:${left}%;width:${width}%"></div></div>
        <div class="hi">${d.high ?? ""}${d.high !== null ? "°" : ""}</div></div>`;
    })
    .join("");
}

function openDay(i) {
  const d = W.daily[i];
  showOverlay(d.name, [
    { title: d.detail ? "Day" : "", text: d.detail },
    { title: "Night", text: d.night },
  ]);
}

async function loadWeather() {
  try {
    W = await getJSON("/api/weather");
  } catch (e) {
    return; // keep showing what we have
  }
  if (!W.current && !W.daily) return;
  renderAlerts();
  renderNow();
  renderHourly();
  renderDaily();
}

// ---------- Radar ----------

const radar = {
  map: null,
  layers: [],
  frames: [],
  index: 0,
  playing: true,
  timer: null,
  key: "",
};

function initRadarMap() {
  const loc = CONFIG.location;
  const map = L.map("radar-map", {
    center: [loc.latitude, loc.longitude],
    zoom: CONFIG.weather.radar_zoom,
    minZoom: 8, // the radar pictures cover zoom 8 and closer
    maxZoom: 10,
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    touchZoom: false,
    doubleClickZoom: false,
    scrollWheelZoom: false,
    boxZoom: false,
    keyboard: false,
    zoomSnap: 1,
  });
  // ?v= makes the browser re-ask after a restart, in case the map source changed.
  const v = encodeURIComponent(CONFIG.version);
  L.tileLayer(`/tiles/base/{z}/{x}/{y}.png?v=${v}`, { maxZoom: 10 }).addTo(map);
  map.createPane("labels").style.zIndex = 450;
  map.getPane("labels").style.pointerEvents = "none";
  // Labels drawn at double size so town names are readable on a small screen.
  L.tileLayer(`/tiles/labels/{z}/{x}/{y}.png?v=${v}`, {
    pane: "labels",
    maxZoom: 10,
    tileSize: 512,
    zoomOffset: -1,
  }).addTo(map);
  L.marker([loc.latitude, loc.longitude], {
    icon: L.divIcon({ className: "home-dot", iconSize: [22, 22] }),
    interactive: false,
    pane: "labels",
  }).addTo(map);
  radar.map = map;
}

async function loadRadar() {
  let data;
  try {
    data = await getJSON("/api/radar");
  } catch (e) {
    return;
  }
  const key = data.frames.map((f) => f.file).join(",");
  if (!data.frames.length || key === radar.key) {
    document.getElementById("radar-empty").hidden = !!radar.frames.length;
    return;
  }
  radar.key = key;
  // Swap in the new set of pictures (all loaded up front so the loop is smooth).
  const old = radar.layers;
  radar.layers = data.frames.map((f) =>
    L.imageOverlay(`/radar/${f.file}`, data.bounds, { opacity: 0, interactive: false }).addTo(radar.map),
  );
  old.forEach((l) => l.remove());
  radar.frames = data.frames;
  radar.index = radar.frames.length - 1;
  document.getElementById("radar-empty").hidden = true;
  showFrame();
}

function showFrame() {
  radar.layers.forEach((l, i) => l.setOpacity(i === radar.index ? 0.8 : 0));
  const n = radar.frames.length;
  document.getElementById("radar-progress").style.width = `${((radar.index + 1) / n) * 100}%`;
  document.getElementById("radar-time").textContent = fmtTime(radar.frames[radar.index].time);
}

function radarTick() {
  if (radar.playing && radar.frames.length) {
    radar.index = (radar.index + 1) % radar.frames.length;
    showFrame();
  }
  // Linger on the newest picture so "now" is easy to read.
  const last = radar.index === radar.frames.length - 1;
  radar.timer = setTimeout(radarTick, last ? 2000 : 450);
}

function setPlaying(on) {
  radar.playing = on;
  document.getElementById("radar-play").innerHTML = icon(on ? "player-pause" : "player-play");
  if (!on && radar.frames.length) {
    radar.index = radar.frames.length - 1; // pausing shows the latest picture
    showFrame();
  }
}

// ---------- Start ----------

function radarSpan() {
  const mins = CONFIG.weather.radar_loop_minutes;
  if (mins < 50) return `last ${mins} min`;
  const hours = Math.round(mins / 30) / 2;
  return hours === 1 ? "last hour" : `last ${hours} hours`;
}

// Hide the parts turned off in settings; the rest spreads out to fill the space.
function applyLayout() {
  const w = CONFIG.weather, page = document.getElementById("weather");
  page.classList.toggle("no-radar", !w.show_radar);
  page.classList.toggle("no-hourly", !w.show_hourly);
  page.classList.toggle("no-daily", !w.show_daily);
  page.classList.toggle("no-forecast-text", !w.show_forecast_text);
}

async function start() {
  await watchVersion();
  applyLayout();
  document.getElementById("radar-sub").textContent = `· ${radarSpan()}`;
  document.getElementById("radar-zoom-in").innerHTML = icon("zoom-in");
  document.getElementById("radar-zoom-out").innerHTML = icon("zoom-out");
  document.getElementById("overlay-close").innerHTML = icon("x");
  setPlaying(true);

  document.getElementById("radar-play").onclick = () => setPlaying(!radar.playing);
  document.getElementById("radar-zoom-in").onclick = () => radar.map.zoomIn();
  document.getElementById("radar-zoom-out").onclick = () => radar.map.zoomOut();
  document.getElementById("alert").onclick = openAlerts;
  document.getElementById("overlay-close").onclick = hideOverlay;
  document.getElementById("daily").onclick = (e) => {
    const row = e.target.closest(".day");
    if (row) openDay(+row.dataset.i);
  };

  if (CONFIG.weather.show_radar) {
    initRadarMap();
    await loadRadar();
    radarTick();
    setInterval(loadRadar, 2 * 60 * 1000);
  }
  await loadWeather();
  setInterval(loadWeather, 60 * 1000);
  setInterval(watchVersion, 60 * 1000);
  // Keep "measured at" ages and sunrise/sunset fresh between data updates.
  setInterval(() => W && renderNow(), 60 * 1000);
}

start();
