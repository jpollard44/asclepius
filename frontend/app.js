"use strict";

const $ = (sel) => document.querySelector(sel);
const api = async (path, opts) => {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
};

let metricsMeta = [];
let metricChart = null;
let sleepChart = null;
const chatHistory = []; // [{role, content}]

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
init();

async function init() {
  try {
    const status = await api("/api/status");
    if (status.has_data) {
      enterApp(status);
    } else {
      showUpload();
    }
  } catch (e) {
    showUpload();
  }
  wireUpload();
  wireTabs();
  wireExplore();
  wireChat();
}

function showUpload() {
  $("#uploadView").classList.remove("hidden");
  $("#appView").classList.add("hidden");
  $("#rangeBadge").classList.add("hidden");
  $("#uploadStatus").textContent = "";
}

async function enterApp(status) {
  $("#uploadView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  metricsMeta = status.metrics || [];
  const r = status.date_range || {};
  const badge = $("#rangeBadge");
  if (r.start && r.end) {
    badge.textContent = `${r.start} → ${r.end}`;
    badge.classList.remove("hidden");
  }
  populateMetricSelect();
  await loadOverview();
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------
function wireUpload() {
  const dz = $("#dropzone");
  const input = $("#fileInput");
  input.addEventListener("change", () => input.files[0] && uploadFile(input.files[0]));
  ["dragover", "dragenter"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
  $("#reloadBtn").addEventListener("click", showUpload);
}

async function uploadFile(file) {
  const status = $("#uploadStatus");
  status.className = "upload-status";
  status.textContent = `Parsing ${file.name}… this can take a moment for large exports.`;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await api("/api/upload", { method: "POST", body: fd });
    status.className = "upload-status ok";
    status.textContent = `Loaded ${res.metrics_found} metrics (${res.counts.daily_rows} daily records).`;
    const st = await api("/api/status");
    enterApp(st);
  } catch (e) {
    status.className = "upload-status error";
    status.textContent = e.message;
  }
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
function wireTabs() {
  document.querySelectorAll(".tab[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab[data-tab]").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`#tab-${btn.dataset.tab}`).classList.add("active");
      if (btn.dataset.tab === "explore") loadMetric();
    });
  });
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadOverview() {
  const data = await api("/api/overview");
  renderCards(data.headline);
  renderSleep(data.sleep);
  renderWorkouts(data.workouts);
}

function fmt(n) {
  if (n === null || n === undefined) return "–";
  return Math.abs(n) >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 })
                             : n.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function trendHtml(trend) {
  if (!trend) return "";
  const arrow = trend.direction === "up" ? "▲" : trend.direction === "down" ? "▼" : "→";
  const sign = trend.pct_change > 0 ? "+" : "";
  return `<div class="trend ${trend.direction}">${arrow} ${sign}${trend.pct_change}% vs earlier</div>`;
}

function renderCards(cards) {
  $("#cards").innerHTML = cards.map((c) => `
    <div class="card">
      <div class="label">${c.label}</div>
      <div class="value">${fmt(c.latest)} <small>${c.unit || ""}</small></div>
      <div class="label">30d avg ${fmt(c.average)}</div>
      ${trendHtml(c.trend)}
    </div>`).join("");
}

function renderSleep(s) {
  const stats = $("#sleepStats");
  if (!s || !s.available) { stats.innerHTML = '<span class="muted">No sleep data recorded.</span>'; return; }
  stats.innerHTML = `
    <div class="stat"><div class="n">${s.avg_asleep_hours}h</div><div class="k">avg asleep</div></div>
    <div class="stat"><div class="n">${s.avg_deep_hours ?? "–"}h</div><div class="k">deep</div></div>
    <div class="stat"><div class="n">${s.avg_rem_hours ?? "–"}h</div><div class="k">REM</div></div>
    <div class="stat"><div class="n">±${s.consistency_std_hours}h</div><div class="k">consistency</div></div>`;
  api(`/api/sleep?days=60`).then((d) => {
    const rows = d.series.filter((r) => r.asleep_hours > 0);
    drawLine("sleepChart", (c) => sleepChart = c, rows.map((r) => r.date),
      rows.map((r) => r.asleep_hours), "Hours asleep", "#0f8f86",
      () => sleepChart, (v) => sleepChart = v);
  });
}

function renderWorkouts(w) {
  const list = $("#workoutList");
  if (!w || !w.by_activity.length) {
    list.innerHTML = '<span class="muted">No workouts in the last 30 days.</span>';
    return;
  }
  list.innerHTML = w.by_activity.map((a) => `
    <div class="workout-row">
      <div><strong>${a.activity}</strong> <span class="meta">×${a.n}</span></div>
      <div class="meta">${a.total_min ?? 0} min${a.total_km ? ` · ${a.total_km} km` : ""}${a.total_kcal ? ` · ${fmt(a.total_kcal)} kcal` : ""}</div>
    </div>`).join("");
}

// ---------------------------------------------------------------------------
// Explore
// ---------------------------------------------------------------------------
function populateMetricSelect() {
  const sel = $("#metricSelect");
  const byArea = {};
  metricsMeta.forEach((m) => (byArea[m.area] = byArea[m.area] || []).push(m));
  const areaLabels = { activity: "Activity & fitness", heart: "Heart health",
    body: "Body & vitals", other: "Other" };
  sel.innerHTML = Object.keys(byArea).map((area) => `
    <optgroup label="${areaLabels[area] || area}">
      ${byArea[area].map((m) => `<option value="${m.key}">${m.label}</option>`).join("")}
    </optgroup>`).join("");
}

function wireExplore() {
  $("#metricSelect").addEventListener("change", loadMetric);
  $("#rangeSelect").addEventListener("change", loadMetric);
}

async function loadMetric() {
  const key = $("#metricSelect").value;
  if (!key) return;
  const days = $("#rangeSelect").value;
  const data = await api(`/api/metric/${key}?days=${days}`);
  const s = data.summary;
  $("#metricSummary").innerHTML = s.available ? `
    <div class="stat"><div class="n">${fmt(s.latest)} ${s.unit}</div><div class="k">latest (${s.latest_date})</div></div>
    <div class="stat"><div class="n">${fmt(s.average)}</div><div class="k">average</div></div>
    <div class="stat"><div class="n">${fmt(s.min)}–${fmt(s.max)}</div><div class="k">range</div></div>
    ${s.trend ? `<div class="stat"><div class="n trend ${s.trend.direction}">${s.trend.pct_change > 0 ? "+" : ""}${s.trend.pct_change}%</div><div class="k">trend</div></div>` : ""}`
    : '<span class="muted">No data for this metric in range.</span>';
  drawLine("metricChart", (c) => metricChart = c, data.series.map((r) => r.date),
    data.series.map((r) => r.value), s.label || key, "#0a6b64",
    () => metricChart, (v) => metricChart = v);
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------
function drawLine(canvasId, _set, labels, values, label, color, getChart, setChart) {
  const existing = getChart();
  if (existing) existing.destroy();
  const ctx = document.getElementById(canvasId);
  setChart(new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label, data: values, borderColor: color, backgroundColor: color + "22",
        fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 8, color: "#6c807d" }, grid: { display: false } },
        y: { ticks: { color: "#6c807d" }, grid: { color: "#eef3f2" } },
      },
    },
  }));
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
function wireChat() {
  $("#chatForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#chatInput").value.trim();
    if (text) sendChat(text);
  });
  $("#suggestions").addEventListener("click", (e) => {
    if (e.target.classList.contains("chip")) sendChat(e.target.textContent);
  });
}

function addMsg(role, text, cls = "") {
  const log = $("#chatLog");
  const el = document.createElement("div");
  el.className = `msg ${role} ${cls}`;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

async function sendChat(text) {
  $("#chatInput").value = "";
  $("#sendBtn").disabled = true;
  addMsg("user", text);
  chatHistory.push({ role: "user", content: text });
  const pending = addMsg("assistant", "Reading your data…", "thinking");
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: chatHistory }),
    });
    pending.classList.remove("thinking");
    pending.textContent = data.reply;
    chatHistory.push({ role: "assistant", content: data.reply });
  } catch (e) {
    pending.classList.remove("thinking");
    pending.classList.add("error");
    pending.textContent = "⚠ " + e.message;
    chatHistory.pop();
  } finally {
    $("#sendBtn").disabled = false;
    $("#chatInput").focus();
  }
}
