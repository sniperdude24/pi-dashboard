// Settings page: every change is saved right away.

const SECTIONS = [
  { id: "pages", title: "Pages and timing", icon: "layout-grid" },
  { id: "weather", title: "Weather", icon: "cloud" },
  { id: "flights", title: "Flights", icon: "plane" },
  { id: "screen", title: "Screen", icon: "device-desktop" },
  { id: "about", title: "About", icon: "info-circle" },
];

let INFO = null;
let current = "pages";

function $(id) {
  return document.getElementById(id);
}

// ---------- Showing values in plain words ----------

function fmtDuration(sec) {
  if (sec < 60) return `${sec} sec`;
  const m = Math.floor(sec / 60), s = sec % 60;
  return s ? `${m} min ${s} sec` : `${m} min`;
}

function fmtClock(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date(2000, 0, 1, h, m);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: CONFIG.clock !== "24h" });
}

function fmtValue(f, v) {
  if (f.kind === "time") return fmtClock(v);
  switch (f.unit) {
    case "sec": return fmtDuration(v);
    case "ft": return v === 0 ? "Show all" : `${v.toLocaleString()} ft`;
    case "zoom": return { 8: "Region", 9: "Area", 10: "Close" }[v] || v;
    case "min": {
      if (v < 60) return `${v} min`;
      const h = Math.floor(v / 60), m = v % 60;
      return (h === 1 ? "1 hour" : `${h} hours`) + (m ? ` ${m} min` : "");
    }
    case "%": return `${v}%`;
    case "": return String(v);
    default: return `${v} ${f.unit}`;
  }
}

// ---------- Saving ----------

let statusTimer = null;

function setStatus(text, cls) {
  const s = $("status");
  s.textContent = text;
  s.className = cls || "";
  clearTimeout(statusTimer);
  if (cls === "saved") statusTimer = setTimeout(() => (s.textContent = ""), 2500);
}

async function save(key, value) {
  try {
    const r = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.status);
    setStatus("Saved", "saved");
    return true;
  } catch (e) {
    setStatus(`Couldn't save: ${e.message}`, "error");
    return false;
  }
}

async function changeField(f, value) {
  const old = f.value;
  f.value = value;
  render();
  if (!(await save(f.key, value))) {
    f.value = old;
    render();
  }
}

async function changePages(pages) {
  const old = INFO.pages;
  INFO.pages = pages;
  render();
  const plain = pages.map((p) => ({ name: p.name, enabled: p.enabled, seconds: p.seconds }));
  if (!(await save("pages.list", plain))) {
    INFO.pages = old;
    render();
  }
}

// ---------- Controls ----------

function stepperHTML(id, text) {
  return `<div class="stepper">
    <button class="btn" data-act="down" data-id="${id}" aria-label="Less">−</button>
    <div class="value">${escapeHTML(text)}</div>
    <button class="btn" data-act="up" data-id="${id}" aria-label="More">+</button></div>`;
}

function toggleHTML(id, on) {
  return `<button class="toggle${on ? " on" : ""}" data-act="toggle" data-id="${id}" aria-label="On or off"></button>`;
}

function fieldHTML(f) {
  const control = f.kind === "bool" ? toggleHTML(f.key, f.value) : stepperHTML(f.key, fmtValue(f, f.value));
  return `<div class="field"><div class="name">${escapeHTML(f.label)}</div>${control}</div>`;
}

function stepValue(f, dir) {
  if (f.kind === "time") {
    const [h, m] = f.value.split(":").map(Number);
    const mins = (h * 60 + m + dir * f.step + 1440) % 1440;
    return `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
  }
  return Math.min(f.max, Math.max(f.min, f.value + dir * f.step));
}

// ---------- Sections ----------

function renderPages() {
  const n = INFO.pages.length;
  const rows = INFO.pages
    .map((p, i) => `<div class="page-row${p.enabled ? "" : " off"}">
      ${icon(p.icon)}<div class="name">${escapeHTML(p.title)}</div>
      <button class="btn${i === 0 ? " dim" : ""}" data-act="page-up" data-i="${i}" aria-label="Move up">${icon("arrow-up")}</button>
      <button class="btn${i === n - 1 ? " dim" : ""}" data-act="page-down" data-i="${i}" aria-label="Move down">${icon("arrow-down")}</button>
      <div class="gap"></div>
      ${stepperHTML(`page-${i}`, fmtDuration(p.seconds))}
      <div class="gap"></div>
      ${toggleHTML(`page-${i}`, p.enabled)}</div>`)
    .join("");
  const resume = INFO.fields.find((f) => f.key === "pages.resume_after_touch_seconds");
  return rows + `<div class="push-down">${fieldHTML(resume)}</div>`;
}

function renderFields(section) {
  const fields = INFO.fields.filter((f) => f.section === section);
  return `<div class="grid">${fields.map(fieldHTML).join("")}</div>`;
}

function renderAbout() {
  const a = INFO.about;
  const rows = [
    ["Version", a.version],
    ["Open from a computer", a.address],
    ["Location", `${a.location.name} (${a.location.latitude}, ${a.location.longitude})`],
    ["Weather updated", a.weather_updated ? fmtTime(a.weather_updated) : "Not yet"],
    ["Plane feed", `<span class="${a.flight_feed_ok ? "ok" : "bad"}">${a.flight_feed_ok ? "Working" : "Not reachable"}</span> · ${escapeHTML(a.flight_feed)}`],
    ["Settings file", a.settings_file],
    ["To update", "~/pi-dashboard/update.sh"],
  ];
  return `<dl class="about">${rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${k === "Plane feed" ? v : escapeHTML(v)}</dd>`)
    .join("")}</dl>`;
}

function render() {
  $("sections").innerHTML = SECTIONS.map(
    (s) => `<button class="section-btn${s.id === current ? " on" : ""}" data-section="${s.id}">${icon(s.icon)}${s.title}</button>`,
  ).join("");
  $("section-title").textContent = SECTIONS.find((s) => s.id === current).title;
  const html = current === "pages" ? renderPages() : current === "about" ? renderAbout() : renderFields(current);
  $("content").innerHTML = html;
}

// ---------- Taps ----------

function onTap(e) {
  const sec = e.target.closest("[data-section]");
  if (sec) {
    current = sec.dataset.section;
    render();
    return;
  }
  const el = e.target.closest("[data-act]");
  if (!el || !INFO.can_edit) return;
  const act = el.dataset.act, id = el.dataset.id;

  if (act.startsWith("page-")) {
    const i = +el.dataset.i, j = act === "page-up" ? i - 1 : i + 1;
    if (j < 0 || j >= INFO.pages.length) return;
    const pages = [...INFO.pages];
    [pages[i], pages[j]] = [pages[j], pages[i]];
    changePages(pages);
    return;
  }
  if (id.startsWith("page-")) {
    const i = +id.slice(5);
    const pages = INFO.pages.map((p) => ({ ...p }));
    const lim = INFO.page_seconds;
    if (act === "toggle") {
      pages[i].enabled = !pages[i].enabled;
      if (!pages.some((p) => p.enabled)) {
        setStatus("At least one page has to stay on", "error");
        return;
      }
    } else {
      const dir = act === "up" ? 1 : -1;
      const next = Math.min(lim.max, Math.max(lim.min, pages[i].seconds + dir * lim.step));
      if (next === pages[i].seconds) return;
      pages[i].seconds = next;
    }
    changePages(pages);
    return;
  }
  const f = INFO.fields.find((x) => x.key === id);
  if (act === "toggle") changeField(f, !f.value);
  else {
    const next = stepValue(f, act === "up" ? 1 : -1);
    if (next !== f.value) changeField(f, next);
  }
}

function goBack() {
  if (EMBEDDED) parent.postMessage({ type: "close-settings" }, location.origin);
  else location.href = "/";
}

async function start() {
  await watchVersion();
  INFO = await getJSON("/api/settings");
  $("back").innerHTML = icon("arrow-left");
  $("back").onclick = goBack;
  if (!INFO.can_edit) {
    $("view-only").innerHTML = `${icon("lock")} View only. Settings can be changed on the touchscreen.`;
    $("view-only").hidden = false;
    document.body.classList.add("readonly");
  }
  document.addEventListener("click", onTap);
  render();
}

start();
