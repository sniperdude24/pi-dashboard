// The rotating screen: shows each page in turn, with a control bar on touch.

const BAR_SECONDS = 8;

const shell = {
  pages: [],      // enabled pages from settings, in order
  frames: [],     // one <iframe> per page, all kept loaded
  index: 0,
  shownAt: 0,     // when the current page appeared
  lastTouch: 0,
  paused: false,  // the pause button (not saved; resets on restart)
  barTimer: null,
  settingsOpen: false,
};

function $(id) {
  return document.getElementById(id);
}

// ---------- Pages ----------

function buildPages() {
  shell.pages = CONFIG.pages.filter((p) => p.enabled);
  const box = $("pages");
  box.innerHTML = "";
  shell.frames = shell.pages.map((p) => {
    const f = document.createElement("iframe");
    f.src = `/${p.name}${KIOSK ? "?kiosk" : ""}`;
    f.title = p.title;
    f.addEventListener("load", () => watchTouches(f.contentDocument));
    box.appendChild(f);
    return f;
  });
  $("bar-dots").innerHTML = shell.pages.map(() => "<span></span>").join("");
  show(0);
}

function show(i) {
  const n = shell.pages.length;
  shell.index = ((i % n) + n) % n;
  shell.frames.forEach((f, j) => f.classList.toggle("active", j === shell.index));
  [...$("bar-dots").children].forEach((d, j) => d.classList.toggle("on", j === shell.index));
  shell.shownAt = Date.now();
}

// Called every second: move on when this page's time is up and nobody has
// touched the screen recently.
function tick() {
  if (shell.settingsOpen || shell.paused || shell.pages.length < 2) return;
  const now = Date.now();
  const page = shell.pages[shell.index];
  const due = Math.max(shell.shownAt + page.seconds * 1000, shell.lastTouch + CONFIG.resume_after_touch_seconds * 1000);
  if (now >= due) show(shell.index + 1);
}

// ---------- Touch, swipe and the control bar ----------

let down = null;

// Things on the pages that do something when tapped. Tapping one of these never
// brings up the control bar, so the bar can't end up covering it.
const TAPPABLE = "button, a, input, select, [data-act], [data-id], [data-i], #alert, .leaflet-marker-icon, .overlay";

function watchTouches(doc) {
  doc.addEventListener("pointerdown", (e) => {
    touched(e.target);
    down = { x: e.screenX, y: e.screenY, t: Date.now() };
  }, true);
  doc.addEventListener("pointerup", (e) => {
    if (!down) return;
    const dx = e.screenX - down.x, dy = e.screenY - down.y;
    if (Math.abs(dx) > 150 && Math.abs(dy) < 100 && Date.now() - down.t < 800) {
      show(shell.index + (dx < 0 ? 1 : -1));
    }
    down = null;
  }, true);
}

function touched(target) {
  shell.lastTouch = Date.now();
  updateDim();
  const bar = $("bar");
  if (bar.contains(target)) showBar(); // using the bar: keep it up
  else if (!bar.classList.contains("hidden")) hideBar(); // a tap anywhere else closes it
  else if (!(target.closest && target.closest(TAPPABLE))) showBar(); // empty space opens it
}

function showBar() {
  $("bar").classList.remove("hidden");
  clearTimeout(shell.barTimer);
  shell.barTimer = setTimeout(hideBar, BAR_SECONDS * 1000);
}

function hideBar() {
  clearTimeout(shell.barTimer);
  $("bar").classList.add("hidden");
}

function setPaused(on) {
  shell.paused = on;
  $("bar-pause").innerHTML = icon(on ? "player-play" : "player-pause");
  $("paused-badge").hidden = !on;
  if (!on) shell.shownAt = Date.now();
}

// ---------- Night dimming ----------

function minutesOf(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

function isNight() {
  const s = CONFIG.screen;
  if (!s.night_dim) return false;
  const d = new Date(), now = d.getHours() * 60 + d.getMinutes();
  const start = minutesOf(s.night_start), end = minutesOf(s.night_end);
  return start <= end ? now >= start && now < end : now >= start || now < end;
}

function updateDim() {
  // A touch brightens the screen until the page rotation would resume.
  const recentlyTouched = Date.now() - shell.lastTouch < CONFIG.resume_after_touch_seconds * 1000;
  const dark = isNight() && !recentlyTouched && !shell.settingsOpen;
  $("dim").style.opacity = dark ? 1 - CONFIG.screen.night_brightness / 100 : 0;
}

// ---------- Settings ----------

function openSettings() {
  shell.settingsOpen = true;
  updateDim();
  hideBar();
  const layer = $("settings-layer");
  layer.innerHTML = `<iframe src="/settings${KIOSK ? "?kiosk" : ""}" title="Settings"></iframe>`;
  layer.hidden = false;
}

async function closeSettings() {
  const layer = $("settings-layer");
  layer.hidden = true;
  layer.innerHTML = "";
  shell.settingsOpen = false;
  shell.lastTouch = Date.now();
  await checkForChanges();
}

window.addEventListener("message", (e) => {
  if (e.origin === location.origin && e.data && e.data.type === "close-settings") closeSettings();
});

// After an update or a settings change, start fresh so everything picks it up.
async function checkForChanges() {
  if (shell.settingsOpen) return;
  try {
    const cfg = await getJSON("/api/config");
    if (cfg.version !== CONFIG.version || cfg.settings_rev !== CONFIG.settings_rev) location.reload();
  } catch (e) {
    /* server restarting; try again later */
  }
}

// ---------- Start ----------

async function start() {
  CONFIG = await getJSON("/api/config");
  $("bar-prev").innerHTML = icon("chevron-left");
  $("bar-next").innerHTML = icon("chevron-right");
  $("bar-settings").innerHTML = icon("settings");
  $("paused-badge").innerHTML = `${icon("player-pause")} Paused`;
  setPaused(false);

  $("bar-prev").onclick = () => show(shell.index - 1);
  $("bar-next").onclick = () => show(shell.index + 1);
  $("bar-pause").onclick = () => setPaused(!shell.paused);
  $("bar-settings").onclick = openSettings;
  watchTouches(document);
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") show(shell.index + 1);
    if (e.key === "ArrowLeft") show(shell.index - 1);
  });

  buildPages();
  setInterval(tick, 1000);
  setInterval(updateDim, 30 * 1000);
  setInterval(checkForChanges, 15 * 1000);
  updateDim();
}

start();
