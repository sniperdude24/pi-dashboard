// Servers page: the mini PC (left) and this Pi (right), side by side.

const SIDES = {
  mini: { title: "daveserver", tempWarn: 80, tempBad: 90, box: appsBox },
  pi: { title: "raspberrypi", tempWarn: 70, tempBad: 80, box: powerBox },
};

// ---------- Formatting ----------

function size(bytes) {
  if (bytes == null) return "--";
  return bytes >= 1e12 ? `${(bytes / 1e12).toFixed(2)} TB` : `${Math.round(bytes / 1e9)} GB`;
}

function rate(bytesPerSecond) {
  if (bytesPerSecond == null) return "--";
  if (bytesPerSecond >= 1e6) return `${(bytesPerSecond / 1e6).toFixed(1)} MB/s`;
  return `${Math.round(bytesPerSecond / 1e3)} KB/s`;
}

function upFor(seconds) {
  if (seconds == null) return "";
  const days = Math.floor(seconds / 86400), hours = Math.floor(seconds / 3600), mins = Math.floor(seconds / 60);
  if (days >= 1) return `Up ${days} day${days > 1 ? "s" : ""}`;
  if (hours >= 1) return `Up ${hours} hour${hours > 1 ? "s" : ""}`;
  return `Up ${mins} min`;
}

// normal colour, then amber, then red as a value climbs past warn / bad
function level(value, warn, bad, normal) {
  if (value == null) return normal;
  return value >= bad ? "#e24b4a" : value >= warn ? "#e5a43a" : normal;
}

// ---------- Pieces ----------

function ring(percent, color, text, label) {
  const r = 60, c = 2 * Math.PI * r, p = Math.max(0, Math.min(1, (percent || 0) / 100));
  return `<div class="ring"><svg width="150" height="150" viewBox="0 0 150 150">
    <circle cx="75" cy="75" r="${r}" fill="none" stroke="#2f3e4b" stroke-width="14"/>
    <circle cx="75" cy="75" r="${r}" fill="none" stroke="${color}" stroke-width="14" stroke-linecap="round"
      stroke-dasharray="${c * p} ${c}" transform="rotate(-90 75 75)"/>
    <text x="75" y="86" text-anchor="middle" font-size="34" font-weight="600" fill="#eaeef2">${text}</text>
  </svg><div class="l">${label}</div></div>`;
}

function spark(points) {
  if (!points || points.length < 2) {
    return `<div class="spark"><span class="t">Processor · last hour</span><div class="wait">Collecting…</div></div>`;
  }
  const n = 120; // one hour at 30 s per point, filling in from the right
  const xy = points.map((v, i) => `${((n - points.length + i) / (n - 1)) * 600},${150 - 12 - (v / 100) * 110}`);
  return `<div class="spark"><span class="t">Processor · last hour</span>
    <svg width="100%" height="150" viewBox="0 0 600 150" preserveAspectRatio="none">
      <polyline points="${xy.join(" ")}" fill="none" stroke="#7fb2e8" stroke-width="3" vector-effect="non-scaling-stroke"/>
    </svg></div>`;
}

function bar(label, value, fraction, warnAt = 0.8, badAt = 0.9) {
  const cls = fraction == null ? "" : fraction >= badAt ? "bad" : fraction >= warnAt ? "warn" : "";
  const track = fraction == null ? "" :
    `<div class="track"><div class="fill ${cls}" style="width:${Math.min(100, fraction * 100)}%"></div></div>`;
  return `<div class="bar">${label}<b>${value}</b>${track}</div>`;
}

function appsBox(d) {
  if (!d.apps) return `<div class="t">Apps</div><div class="power">CasaOS isn't sharing its app list.</div>`;
  const running = d.apps.filter((a) => a.running).length;
  const stopped = d.apps.length - running;
  const head = `Apps · ${running} running${stopped ? ` · ${stopped} stopped` : ""}`;
  return `<div class="t">${head}</div><div class="apps">${d.apps
    .slice(0, 12)
    .map((a) => `<span class="${a.running ? "" : "off"}">${escapeHTML(a.name)}</span>`)
    .join("")}</div>`;
}

function powerBox(d) {
  const p = d.power || {};
  const volts = p.volts ? `${p.volts.toFixed(2)} volts at the board` : "Voltage not available";
  const supply = p.supply_amps ? ` · ${p.supply_amps} A supply` : "";
  const status = p.warnings && p.warnings.length
    ? `<span class="bad-text">${p.warnings.map(escapeHTML).join("<br>")}</span>`
    : `<span class="ok-text">No low-voltage warnings since start-up</span>`;
  return `<div class="t">Power</div><div class="power">${volts}${supply}<br>${status}</div>`;
}

// ---------- One half ----------

function render(id, d) {
  const side = SIDES[id], el = document.getElementById(id);
  const fresh = d && !d.error;
  const name = (d && d.name) || side.title;
  let html = `<div class="hd"><span class="dot ${fresh ? "ok" : d && d.updated ? "bad" : ""}"></span>
    <span class="n">${escapeHTML(name)}</span><span class="m">${escapeHTML((d && d.model) || "")}</span>
    <span class="u">${d && d.error && d.updated ? `Last seen ${fmtTime(new Date(d.updated * 1000))}` : upFor(d && d.uptime)}</span></div>`;

  if (d && d.cpu != null) {
    const temp = d.temp == null ? "--" : `${Math.round(d.temp)}°`;
    html += `<div class="top">
      ${ring(d.cpu, level(d.cpu, 70, 90, "#7fb2e8"), `${Math.round(d.cpu)}%`, "Processor")}
      ${ring(d.mem_percent, level(d.mem_percent, 80, 90, "#5dcaa5"), `${Math.round(d.mem_percent)}%`, "Memory")}
      ${ring(d.temp, level(d.temp, side.tempWarn, side.tempBad, "#b4a2e8"), temp, "Temperature")}
      ${spark(d.cpu_history)}</div>`;
    const rows = (d.disks || []).map((k) => bar(k.name, `${size(k.used)} of ${size(k.total)}`, k.total ? k.used / k.total : null));
    rows.push(bar("Network", `↓ ${rate(d.net_down)} · ↑ ${rate(d.net_up)}`, null));
    html += `<div class="rows">${rows.join("")}</div><div class="box">${side.box(d)}</div>`;
  }
  if (!d || (d.error && !d.updated && d.cpu == null)) {
    html += `<div class="msg">${escapeHTML((d && d.error) || "Connecting…")}</div>`;
  }
  el.innerHTML = html;
}

async function load() {
  try {
    const d = await getJSON("/api/servers");
    render("mini", d.mini);
    render("pi", d.pi);
  } catch (e) {
    /* keep showing the last numbers */
  }
}

async function start() {
  await watchVersion();
  await load();
  setInterval(load, 5000);
  setInterval(watchVersion, 60 * 1000);
}

start();
