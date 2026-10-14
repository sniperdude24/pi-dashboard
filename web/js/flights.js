// Flight page: live map of planes around home and a list of the closest ones.

const PLANE_SVG =
  '<svg viewBox="-22 -22 44 44"><path d="M0-20 L5-5 L20 4 L20 8 L5 4 L3 14 L9 18 L9 21 L0 18 L-9 21 L-9 18 L-3 14 L-5 4 L-20 8 L-20 4 L-5-5Z"/></svg>';
const MILES_TO_M = 1609.344;

const F = {
  map: null,
  markers: {}, // plane id -> Leaflet marker
  planes: [],
};

function altClass(p) {
  if (p.emergency) return "emergency";
  if (p.on_ground) return "ground";
  if (p.altitude_ft == null || p.altitude_ft < 10000) return "low";
  if (p.altitude_ft < 25000) return "mid";
  return "high";
}

function fmtFeet(ft) {
  return ft == null ? "--" : `${ft.toLocaleString()} ft`;
}

// "BOEING 737-800" -> "Boeing 737-800" (model codes like CRJ-700 stay as they are).
function tidyName(s) {
  return s ? s.replace(/\b[A-Z]{4,}\b/g, (w) => w[0] + w.slice(1).toLowerCase()) : s;
}

function routeText(r) {
  return r ? `${r.from.code} → ${r.to.code}` : "";
}

// ---------- Map ----------

function niceRings(range) {
  const round = (v) => Math.max(5, Math.round(v / 5) * 5);
  return [...new Set([round(range * 0.2), round(range * 0.5), range])];
}

// How far out the map shows. Normally range_miles; when fewer planes than fill
// the list are that close, it widens in steps (up to expand_to_miles) until
// they fit. It widens at once but only narrows again after 30 s, so it
// doesn't jump back and forth as planes come and go.
const NARROW_AFTER_MS = 30 * 1000;

function wantedRange(planes) {
  const base = CONFIG.flights.range_miles;
  const max = Math.max(base, CONFIG.flights.expand_to_miles);
  const need = CONFIG.flights.list_count;
  if (planes.filter((p) => p.distance_mi <= base).length >= need) return base;
  const nth = planes[need - 1]; // planes come sorted, closest first
  if (!nth) return max;
  const steps = [base, 75, 100, 150, 200, 250].filter((s) => s >= base && s < max).concat(max);
  return steps.find((s) => s >= nth.distance_mi) || max;
}

function updateRange() {
  const want = wantedRange(F.planes);
  if (want > F.range) {
    setRange(want);
  } else if (want < F.range) {
    F.narrowSince = F.narrowSince || Date.now();
    if (Date.now() - F.narrowSince >= NARROW_AFTER_MS) setRange(want);
  } else {
    F.narrowSince = null;
  }
}

function setRange(range) {
  F.range = range;
  F.narrowSince = null;
  const loc = CONFIG.location;
  const home = L.latLng(loc.latitude, loc.longitude);
  F.rings.clearLayers();
  for (const r of niceRings(range)) {
    L.circle(home, { radius: r * MILES_TO_M, color: "#6b8091", weight: 2, dashArray: "10 10", fill: false, interactive: false }).addTo(F.rings);
    const top = L.latLng(home.lat + (r * MILES_TO_M) / 111320, home.lng);
    L.marker(top, {
      icon: L.divIcon({ className: "ring-label", html: `${r} mi`, iconSize: [80, 24], iconAnchor: [-8, 12] }),
      interactive: false,
    }).addTo(F.rings);
  }
  F.map.fitBounds(home.toBounds(range * 2 * MILES_TO_M), { padding: [10, 10] });
}

function initMap() {
  const loc = CONFIG.location;
  const home = L.latLng(loc.latitude, loc.longitude);
  const map = L.map("map", {
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    touchZoom: false,
    doubleClickZoom: false,
    scrollWheelZoom: false,
    boxZoom: false,
    keyboard: false,
    zoomSnap: 0.5,
    minZoom: 5,
    maxZoom: 12,
  });
  const v = encodeURIComponent(CONFIG.version);
  L.tileLayer(`/tiles/base/{z}/{x}/{y}.png?v=${v}`, { maxZoom: 12 }).addTo(map);
  L.tileLayer(`/tiles/labels/{z}/{x}/{y}.png?v=${v}`, { maxZoom: 12, tileSize: 512, zoomOffset: -1, opacity: 0.7 }).addTo(map);
  L.marker(home, { icon: L.divIcon({ className: "home-dot", iconSize: [22, 22] }), interactive: false }).addTo(map);
  F.map = map;
  F.rings = L.layerGroup().addTo(map);
  setRange(CONFIG.flights.range_miles);
}

function shown() {
  return F.planes.filter((p) => p.distance_mi <= F.range);
}

function updateMarkers() {
  const seen = new Set();
  for (const p of shown()) {
    seen.add(p.id);
    let m = F.markers[p.id];
    if (!m) {
      m = L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: "", html: `<div class="plane">${PLANE_SVG}<span class="tag"></span></div>`, iconSize: [56, 56], iconAnchor: [28, 28] }),
        keyboard: false,
      }).addTo(F.map);
      m.on("click", () => openPlane(m.planeId));
      F.markers[p.id] = m;
    }
    m.planeId = p.id;
    m.setLatLng([p.lat, p.lon]);
    const el = m.getElement().querySelector(".plane");
    el.className = `plane ${altClass(p)}${CONFIG.flights.show_labels ? "" : " no-tag"}`;
    el.querySelector("svg").style.transform = `rotate(${p.track}deg)`;
    el.querySelector(".tag").textContent = p.callsign;
    m.setZIndexOffset(p.emergency ? 1000 : -Math.round(p.distance_mi));
  }
  for (const id of Object.keys(F.markers)) {
    if (!seen.has(id)) {
      F.markers[id].remove();
      delete F.markers[id];
    }
  }
}

// ---------- List ----------

function renderList(error) {
  const list = document.getElementById("list");
  const planes = shown();
  if (error && !planes.length) {
    list.innerHTML = `<div class="empty">${icon("wifi-off")}${escapeHTML(error)}</div>`;
    return;
  }
  if (!planes.length) {
    list.innerHTML = `<div class="empty">${icon("plane")}No planes within ${F.range} mi right now</div>`;
    return;
  }
  list.innerHTML = planes
    .slice(0, CONFIG.flights.list_count)
    .map((p) => {
      const badges =
        (p.emergency ? `<span class="badge emg">${escapeHTML(p.emergency)}</span>` : "") +
        (p.military ? '<span class="badge mil">Military</span>' : "");
      const what = [routeText(p.route), tidyName(p.model) || p.type].filter(Boolean).join(" · ");
      const alt = p.on_ground ? "On ground" : fmtFeet(p.altitude_ft);
      return `<div class="row" data-id="${p.id}">
        <div class="swatch" style="--c:var(--alt-${altClass(p)})"></div>
        <div class="who"><div class="cs">${escapeHTML(p.callsign)}${badges}</div><div class="what">${escapeHTML(what)}</div></div>
        <div class="alt">${alt}<small>${p.speed_mph == null ? "" : p.speed_mph + " mph"}</small></div>
        <div class="dist">${p.distance_mi} mi<small>${p.direction}</small></div></div>`;
    })
    .join("");
}

// ---------- Details pop-up ----------

function openPlane(id) {
  const p = F.planes.find((x) => x.id === id);
  if (!p) return;
  let html = "";
  if (p.route) {
    html += `<div class="detail-route">
      <div><div class="code">${escapeHTML(p.route.from.code)}</div><div class="city">${escapeHTML(p.route.from.city)}</div></div>
      ${icon("arrow-narrow-right")}
      <div><div class="code">${escapeHTML(p.route.to.code)}</div><div class="city">${escapeHTML(p.route.to.city)}</div></div></div>`;
  }
  const climb = p.climb_fpm == null || Math.abs(p.climb_fpm) < 300 ? "Level" : p.climb_fpm > 0 ? "Climbing" : "Descending";
  const cells = [
    ["Aircraft", tidyName(p.model) || p.type || "Unknown"],
    ["Operator", (p.route && p.route.airline) || tidyName(p.owner) || "Unknown"],
    ["Altitude", p.on_ground ? "On ground" : fmtFeet(p.altitude_ft)],
    ["Climb", p.on_ground ? "--" : climb],
    ["Speed", p.speed_mph == null ? "--" : `${p.speed_mph} mph`],
    ["From you", `${p.distance_mi} mi ${p.direction}`],
    ["Registration", p.registration || "--"],
    ["Built", p.year || "--"],
  ];
  if (p.military) cells.push(["Type", "Military"]);
  if (p.emergency) cells.push(["Squawking", p.emergency]);
  html += `<div class="detail-grid">${cells
    .map(([k, v]) => `<div><span>${k}</span>${escapeHTML(v)}</div>`)
    .join("")}</div>`;
  showOverlayHTML(p.callsign, html);
}

// ---------- Start ----------

async function loadFlights() {
  let data;
  try {
    data = await getJSON("/api/flights");
  } catch (e) {
    return;
  }
  F.planes = data.planes;
  updateRange();
  const widened = F.range > CONFIG.flights.range_miles ? " · widened" : "";
  document.getElementById("count").textContent = `· ${shown().length} within ${F.range} mi${widened}`;
  updateMarkers();
  renderList(data.error);
}

async function start() {
  await watchVersion();
  document.getElementById("zoom-in").innerHTML = icon("zoom-in");
  document.getElementById("zoom-out").innerHTML = icon("zoom-out");
  document.getElementById("overlay-close").innerHTML = icon("x");
  document.getElementById("zoom-in").onclick = () => F.map.zoomIn(1);
  document.getElementById("zoom-out").onclick = () => F.map.zoomOut(1);
  document.getElementById("overlay-close").onclick = hideOverlay;
  document.getElementById("list").onclick = (e) => {
    const row = e.target.closest(".row");
    if (row) openPlane(row.dataset.id);
  };
  initMap();
  await loadFlights();
  setInterval(loadFlights, 2000);
  setInterval(watchVersion, 60 * 1000);
}

start();
