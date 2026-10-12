// Pi-hole page: totals, blocking status, 24-hour chart, top blocked and devices.

function $(id) {
  return document.getElementById(id);
}

function num(n) {
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  return Math.round(n).toLocaleString();
}

function renderStatus(d) {
  const box = $("status");
  let cls = "unknown", text = "Status unknown", sub = "Pi-hole · mini PC";
  if (d.error && !d.updated) {
    text = "Not connected";
  } else if (d.error) {
    text = "Can't reach Pi-hole";
    sub = `Last seen ${fmtTime(new Date(d.updated * 1000))}`;
  } else if (d.blocking === "enabled") {
    cls = "on";
    text = "Blocking on";
  } else if (d.blocking === "disabled") {
    cls = "off";
    text = "Blocking OFF";
    sub = d.blocking_timer ? `Back on in ${Math.ceil(d.blocking_timer / 60)} min` : "Ads aren't being blocked";
  }
  box.className = `tile status ${cls}`;
  $("status-text").textContent = text;
  $("status-sub").textContent = sub;
}

function renderChart(history) {
  const max = Math.max(1, ...history.map((h) => h.total));
  $("bars").innerHTML = history
    .map((h) => {
      const blocked = Math.min(h.blocked, h.total);
      return `<div class="bar"><div class="a" style="height:${((h.total - blocked) / max) * 100}%"></div>` +
        `<div class="b" style="height:${(blocked / max) * 100}%"></div></div>`;
    })
    .join("");
  // Seven time labels spread along the bottom, the last one "Now".
  const labels = [];
  for (let i = 0; i < 7; i++) {
    const h = history[Math.min(history.length - 1, Math.round((i / 6) * (history.length - 1)))];
    labels.push(i === 6 ? "Now" : h ? fmtTime(new Date(h.time * 1000), { minute: undefined }) : "");
  }
  $("axis").innerHTML = labels.map((l) => `<span>${l}</span>`).join("");
}

function renderList(id, rows) {
  $(id).innerHTML = rows
    .map((r) => `<div class="row"><span>${escapeHTML(r.name)}</span><span>${num(r.count)}</span></div>`)
    .join("");
}

async function load() {
  let d;
  try {
    d = await getJSON("/api/pihole");
  } catch (e) {
    return;
  }
  renderStatus(d);
  const msg = d.updated ? "" : d.error || "Connecting to Pi-hole…";
  $("msg").textContent = msg;
  $("msg").hidden = !msg;
  if (!d.updated) return;
  $("total").textContent = num(d.total);
  $("blocked").textContent = num(d.blocked);
  $("percent").textContent = `${d.percent_blocked.toFixed(1)}%`;
  $("listsize").textContent = num(d.blocklist_size);
  renderChart(d.history);
  renderList("top-blocked", d.top_blocked);
  renderList("top-clients", d.top_clients);
}

async function start() {
  await watchVersion();
  await load();
  setInterval(load, 15 * 1000);
  setInterval(watchVersion, 60 * 1000);
}

start();
