// Helpers shared by every page.

// Scale the 1920x720 stage to fill whatever window it's shown in.
function fitStage() {
  const stage = document.getElementById("stage");
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 720);
  stage.style.transform = `scale(${scale})`;
}
window.addEventListener("resize", fitStage);
document.addEventListener("DOMContentLoaded", fitStage);

function icon(name) {
  return `<span class="icon">${ICONS[name] || ICONS.cloud}</span>`;
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

let CONFIG = { clock: "12h" };

function fmtTime(iso, opts = {}) {
  return new Date(iso).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    hour12: CONFIG.clock !== "24h",
    ...opts,
  });
}

function fmtHour(iso) {
  const d = new Date(iso);
  if (CONFIG.clock === "24h") return String(d.getHours()).padStart(2, "0");
  const h = d.getHours() % 12 || 12;
  return `${h}${d.getHours() < 12 ? "a" : "p"}`;
}

function escapeHTML(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

// Pop-up for longer text. sections: [{title, text}]
function showOverlay(title, sections) {
  const o = document.getElementById("overlay");
  o.querySelector(".overlay-title").textContent = title;
  o.querySelector(".overlay-body").innerHTML = sections
    .filter((s) => s.text)
    .map((s) => (s.title ? `<h3>${escapeHTML(s.title)}</h3>` : "") + `<div>${escapeHTML(s.text)}</div>`)
    .join("");
  o.querySelector(".overlay-body").scrollTop = 0;
  o.hidden = false;
}

function hideOverlay() {
  document.getElementById("overlay").hidden = true;
}

// Same as showOverlay, but with ready-made HTML for the body.
function showOverlayHTML(title, html) {
  const o = document.getElementById("overlay");
  o.querySelector(".overlay-title").textContent = title;
  o.querySelector(".overlay-body").innerHTML = html;
  o.querySelector(".overlay-body").scrollTop = 0;
  o.hidden = false;
}

const EMBEDDED = window.top !== window; // running inside the rotating screen

// Load page settings, and reload the page by itself after an update or a
// settings change. Inside the rotating screen, the screen does the reloading.
async function watchVersion() {
  if (EMBEDDED && CONFIG.version) return;
  try {
    const cfg = await getJSON("/api/config");
    const changed = cfg.version !== CONFIG.version || cfg.settings_rev !== CONFIG.settings_rev;
    if (CONFIG.version && changed) location.reload();
    CONFIG = cfg;
  } catch (e) {
    /* server restarting; try again later */
  }
}
