// Backyard page: live picture (left) and the last-hour timelapse (right).
// Both only play while the page is on screen.

const SPEED = 60; // the timelapse plays an hour in a minute

const B = {
  visible: false,
  status: null,     // latest /api/backyard
  hourVersion: 0,   // version of last_hour.mp4 loaded in the player
  liveRetry: null,
  liveProgress: 0,  // last time the live picture moved
};

function $(id) {
  return document.getElementById(id);
}

function message(id, text) {
  $(id).textContent = text || "";
  $(id).hidden = !text;
}

// ---------- Live ----------

function startLive() {
  clearTimeout(B.liveRetry);
  const err = B.status && B.status.live.error;
  if (err && err.includes("settings.yaml")) {
    message("live-msg", err); // not set up yet: no point trying
    $("live-status").textContent = "Not set up";
    return;
  }
  const v = $("live");
  $("live-status").textContent = "Connecting…";
  B.liveProgress = Date.now();
  B.livePlaying = false;
  v.src = `/camera/live.mp4?t=${Date.now()}`;
  v.play().catch(() => {});
}

function stopLive() {
  clearTimeout(B.liveRetry);
  const v = $("live");
  v.removeAttribute("src");
  v.load(); // closes the connection, which stops the Pi pulling from the recorder
  $("live-dot").classList.remove("on");
}

function liveFailed() {
  $("live-dot").classList.remove("on");
  if (!B.visible) return;
  $("live-status").textContent = "Reconnecting…";
  loadStatus().then(() => {
    const err = B.status && B.status.live.error;
    if (err) message("live-msg", err);
  });
  B.liveRetry = setTimeout(startLive, 5000);
}

function watchLive() {
  const v = $("live");
  v.addEventListener("playing", () => {
    B.livePlaying = true;
    $("live-status").textContent = "Live";
    $("live-dot").classList.add("on");
    message("live-msg", "");
  });
  let lastTime = -1;
  v.addEventListener("timeupdate", () => {
    if (v.currentTime !== lastTime) B.liveProgress = Date.now(); // the picture moved
    lastTime = v.currentTime;
    // Stay near the newest picture by playing a little faster when behind.
    // (Never jump ahead: a live stream can't be skipped through, and trying
    // made the player snap back to the start over and over.)
    if (v.buffered.length) {
      const behind = v.buffered.end(v.buffered.length - 1) - v.currentTime;
      v.playbackRate = behind > 3 ? 1.25 : behind < 1 ? 1 : v.playbackRate;
    }
  });
  v.addEventListener("error", () => v.getAttribute("src") && liveFailed());
  v.addEventListener("ended", liveFailed);
  // Restart if the picture freezes (allowing longer for the first picture).
  setInterval(() => {
    const limit = B.livePlaying ? 12000 : 20000;
    if (B.visible && v.getAttribute("src") && Date.now() - B.liveProgress > limit) {
      stopLive();
      liveFailed();
    }
  }, 4000);
}

// ---------- Last hour ----------

function loadHour(version) {
  B.hourVersion = version;
  B.hourUpdated = B.status.timelapse.updated; // when this hour was fetched
  const v = $("hour");
  v.src = `/camera/last_hour.mp4?v=${version}`;
  if (B.visible) v.play().catch(() => {});
}

// When the player reaches the end: switch to a newer hour if there is one.
function hourEnded() {
  const latest = B.status ? B.status.timelapse.version : 0;
  if (latest > B.hourVersion) loadHour(latest);
  else {
    $("hour").currentTime = 0;
    if (B.visible) $("hour").play().catch(() => {});
  }
}

// The timeline: which real time of day is on screen right now, matching the
// camera's own clock stamp to within about a minute. Checked against the
// stamps on 2026-10-11: the newest frame is ~1.5 min older than the download,
// and the hour is built from whole 5-minute blocks (a few frames get skipped,
// so 58.7 s of video really spans 60 minutes).
const END_LAG_MS = 60 * 1000;
const BLOCK_MS = 5 * 60 * 1000;

function updateTimeline() {
  const v = $("hour");
  if (!B.hourUpdated || !v.duration) return;
  const end = B.hourUpdated * 1000 - END_LAG_MS;
  const span = Math.max(1, Math.round((v.duration * SPEED * 1000) / BLOCK_MS)) * BLOCK_MS;
  const start = end - span;
  const frac = Math.min(1, v.currentTime / v.duration);
  $("hour-span").textContent = `${fmtTime(new Date(start))} – ${fmtTime(new Date(end))}`;
  $("hour-start").textContent = fmtTime(new Date(start));
  $("hour-end").textContent = fmtTime(new Date(end));
  $("hour-fill").style.width = `${frac * 100}%`;
  $("hour-knob").style.left = `${frac * 100}%`;
  $("hour-knob").textContent = fmtTime(new Date(start + frac * (end - start)));
}

// ---------- Status from the Pi ----------

async function loadStatus() {
  try {
    B.status = await getJSON("/api/backyard");
  } catch (e) {
    return;
  }
  const t = B.status.timelapse;
  if (t.version && !B.hourVersion) loadHour(t.version); // first video
  message("hour-msg", t.version ? "" : t.error || "Waiting for the first timelapse…");
}

function setVisible(visible) {
  B.visible = visible;
  if (visible) {
    startLive();
    if ($("hour").getAttribute("src")) $("hour").play().catch(() => {});
  } else {
    stopLive();
    $("hour").pause();
  }
}

onPageVisible(setVisible);

async function start() {
  await watchVersion();
  watchLive();
  $("hour").addEventListener("ended", hourEnded);
  $("hour").addEventListener("timeupdate", updateTimeline);
  await loadStatus();
  if (B.visible) setVisible(true);
  setInterval(loadStatus, 30 * 1000);
  setInterval(watchVersion, 60 * 1000);
}

start();
