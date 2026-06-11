"use strict";

/* ============================================================
   Tiny helpers
   ============================================================ */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}
const jpost = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const jput = (path, body) =>
  api(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const jdel = (path) => api(path, { method: "DELETE" });

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return node;
}
const escapeHtml = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const num = (v, d = 0) => (v == null || isNaN(v) ? d : Number(v));
const round = (v, p = 0) => { const m = 10 ** p; return Math.round(num(v) * m) / m; };
const fmt = (v, p = 0) => round(v, p).toLocaleString();
const todayISO = () => new Date().toISOString().slice(0, 10);

/* ============================================================
   Imperial / US-customary units
   ------------------------------------------------------------
   Everything is stored in metric (kg, km, cm, ml, °C) so the math and goal
   tracking stay consistent. We convert to US units only at the display edge,
   and convert entry back to metric before POSTing. Macros (grams) and energy
   (kcal) already match US nutrition labels, so they pass through unchanged.
   ============================================================ */
const UNIT_CONV = {
  kg:   { to: "lb",    f: (v) => v * 2.2046226, inv: (v) => v / 2.2046226, dp: 1 },
  cm:   { to: "in",    f: (v) => v / 2.54,      inv: (v) => v * 2.54,      dp: 1 },
  km:   { to: "mi",    f: (v) => v * 0.6213712, inv: (v) => v / 0.6213712, dp: 2 },
  degC: { to: "°F",    f: (v) => v * 9 / 5 + 32, inv: (v) => (v - 32) * 5 / 9, dp: 1 },
  ml:   { to: "fl oz", f: (v) => v * 0.0338140, inv: (v) => v / 0.0338140, dp: 0 },
};
// Stored metric value+unit -> display { value, unit, dp }.
function disp(value, unit) {
  const c = UNIT_CONV[unit];
  if (!c || value == null) return { value, unit, dp: 1 };
  return { value: c.f(num(value)), unit: c.to, dp: c.dp };
}
// The US label for a metric unit (e.g. "kg" -> "lb"), unchanged if not metric.
const dispUnit = (unit) => (UNIT_CONV[unit] ? UNIT_CONV[unit].to : unit);
// Convert a display value back to its canonical metric value for storage.
const toMetric = (value, unit) => (UNIT_CONV[unit] ? UNIT_CONV[unit].inv(num(value)) : num(value));
// Rewrite serving text like "100 g" / "250 ml" to US units for display.
function servingUS(s) {
  if (!s) return s;
  return String(s)
    .replace(/(\d+(?:\.\d+)?)\s*ml\b/gi, (_, n) => `${round(num(n) * 0.0338140, 1)} fl oz`)
    .replace(/(\d+(?:\.\d+)?)\s*g\b/gi, (_, n) => `${round(num(n) * 0.0352740, 1)} oz`);
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 2200);
}

/* ============================================================
   Global state
   ============================================================ */
const State = {
  status: null,
  config: { meals: [], workout_types: [], goal_categories: {}, manual_metrics: {} },
  advisorReady: true,
  tab: "dashboard",
  foodDate: todayISO(),
  goals: {},   // personalized daily targets, keyed by metric (see loadGoals)
};
const charts = {}; // id -> Chart instance

const MEAL_ICONS = { breakfast: "🍳", lunch: "🥗", dinner: "🍽", snack: "🍎" };
const WORKOUT_ICONS = { strength: "🏋", cardio: "🏃", other: "🤸" };

/* ============================================================
   Boot
   ============================================================ */
init();
async function init() {
  marked.setOptions({ breaks: true });
  setupChartDefaults();
  wireUpload();
  wireSheet();
  wireDetail();
  wireTabs();
  wireChrome();
  wireSettings();
  registerServiceWorker();   // PWA + push; safe no-op where unsupported
  try {
    const status = await api("/api/status");
    State.status = status;
    State.config = status.config || State.config;
    State.advisorReady = status.advisor_ready;
    await loadGoals();
    if (status.has_data) enterApp();
    else showUpload();
  } catch (e) {
    showUpload();
  }
}

function showUpload() {
  $("#uploadView").classList.remove("hidden");
  $("#appView").classList.add("hidden");
}
function enterApp() {
  $("#uploadView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  const r = State.status?.date_range;
  $("#topbarSub").textContent = State.advisorReady ? "Your health coach" : "Set ANTHROPIC_API_KEY for coaching";
  switchTab(State.tab);
  // appView was display:none until now, so the topbar/tabbar had no measurable
  // height; measure them now that they're laid out.
  syncChrome();
  maybePromptNotifications();   // gentle first-run nudge to turn on reminders
}

/* ------------------------------------------------------------
   Keep the coach (chat) layout pinned to the *real* app chrome.
   We measure the topbar + tabbar instead of trusting the hardcoded
   --topbar-h / --tabbar-h guesses (those drift with safe-area insets,
   dynamic type and iOS's collapsing toolbar under viewport-fit=cover),
   and track visualViewport so the composer rides above the software
   keyboard instead of being pushed behind the tabbar. styles.css reads
   --topbar-h / --tabbar-h / --app-h from here.
   ------------------------------------------------------------ */
function syncChrome() {
  const root = document.documentElement.style;
  const topbar = $(".topbar"), tabbar = $(".tabbar");
  if (topbar && topbar.offsetHeight) root.setProperty("--topbar-h", topbar.offsetHeight + "px");
  if (tabbar && tabbar.offsetHeight) root.setProperty("--tabbar-h", tabbar.offsetHeight + "px");
  const vv = window.visualViewport;
  root.setProperty("--app-h", Math.round(vv ? vv.height : window.innerHeight) + "px");
}
function wireChrome() {
  const sync = () => requestAnimationFrame(syncChrome);
  window.addEventListener("resize", sync);
  window.addEventListener("orientationchange", sync);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", sync);
    window.visualViewport.addEventListener("scroll", sync);
  }
}

/* ============================================================
   Upload
   ============================================================ */
function wireUpload() {
  const dz = $("#dropzone"), input = $("#fileInput");
  input.addEventListener("change", () => input.files[0] && uploadFile(input.files[0]));
  ["dragover", "dragenter"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) uploadFile(f); });
  $("#reloadBtn").addEventListener("click", showUpload);
  $("#skipImportBtn").addEventListener("click", async () => {
    // Let the user in with manual logging only; ensure status reflects it.
    try { State.status = await api("/api/status"); State.config = State.status.config; } catch {}
    enterApp();
  });
}
async function uploadFile(file) {
  const status = $("#uploadStatus");
  status.className = "upload-status";
  status.textContent = `Reading ${file.name}… large exports can take a moment.`;
  const fd = new FormData();
  fd.append("file", file);
  try {
    await api("/api/upload", { method: "POST", body: fd });
    State.status = await api("/api/status");
    State.config = State.status.config;
    State.advisorReady = State.status.advisor_ready;
    status.className = "upload-status ok";
    status.textContent = "Imported! Loading your dashboard…";
    enterApp();
  } catch (e) {
    status.className = "upload-status error";
    status.textContent = e.message;
  }
}

/* ============================================================
   Tabs / router
   ============================================================ */
const RENDERERS = {
  dashboard: renderDashboard,
  food: renderFood,
  workouts: renderWorkouts,
  body: renderBody,
  sleep: renderSleep,
  goals: renderGoals,
  coach: renderCoach,
};
function wireTabs() {
  $("#tabbar").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn) switchTab(btn.dataset.tab);
  });
}
function switchTab(tab) {
  State.tab = tab;
  $$("#tabbar .tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  destroyCharts();
  const screen = $("#screen");
  screen.innerHTML = "";
  screen.scrollTop = 0;
  screen.classList.toggle("coach-screen", tab === "coach");
  RENDERERS[tab]();
}
function loading(msg = "Loading…") { return el("div", { class: "empty" }, msg); }

/* ============================================================
   Charts
   ============================================================ */
function setupChartDefaults() {
  if (!window.Chart) return;
  Chart.defaults.color = "#8aa39e";
  Chart.defaults.font.family = "Inter, -apple-system, sans-serif";
  Chart.defaults.borderColor = "#243733";
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.maintainAspectRatio = false;
}
function destroyCharts() {
  for (const k of Object.keys(charts)) { charts[k].destroy(); delete charts[k]; }
}
function makeChart(canvas, config) {
  if (!window.Chart || !canvas) return;
  const c = new Chart(canvas, config);
  charts[canvas.id || Math.random()] = c;
  return c;
}
const TEAL = "#2dd4bf", CORAL = "#f47560", AMBER = "#f5b14c", BLUE = "#5eb3f6", VIOLET = "#a78bfa";
function lineDataset(label, data, color) {
  return { label, data, borderColor: color, backgroundColor: color + "22",
    tension: .35, fill: true, pointRadius: 0, borderWidth: 2 };
}
const AXES = {
  x: { grid: { display: false }, ticks: { maxTicksLimit: 6, autoSkip: true } },
  y: { grid: { color: "#1a2b28" }, ticks: { maxTicksLimit: 5 }, beginAtZero: false },
};
function chartCard(title, height = "") {
  const canvas = el("canvas", { id: "c_" + Math.random().toString(36).slice(2) });
  const box = el("div", { class: "chart-box " + height }, canvas);
  const card = el("div", { class: "card" },
    title ? el("div", { class: "card-head" }, el("h3", {}, title)) : null, box);
  return { card, canvas };
}

/* ============================================================
   Bottom sheet (modal)
   ============================================================ */
function wireSheet() {
  $("#sheetClose").addEventListener("click", closeSheet);
  $("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeSheet(); });
}
// Some sheets hold live resources (e.g. an open camera for barcode scanning).
// They register a teardown that runs whenever the sheet is replaced or closed.
let sheetCleanup = null;
function onSheetClose(fn) { sheetCleanup = fn; }
function runSheetCleanup() {
  if (!sheetCleanup) return;
  const fn = sheetCleanup; sheetCleanup = null;
  try { fn(); } catch {}
}
function openSheet(title, bodyNode) {
  runSheetCleanup();
  $("#sheetTitle").textContent = title;
  const body = $("#sheetBody");
  body.innerHTML = "";
  body.append(bodyNode);
  $("#sheet").classList.remove("hidden");
}
function closeSheet() { runSheetCleanup(); $("#sheet").classList.add("hidden"); }

/* ============================================================
   DASHBOARD
   ============================================================ */
async function renderDashboard() {
  const screen = $("#screen");
  screen.append(el("div", { class: "screen-head" },
    el("div", {}, el("h2", {}, greeting()),
      el("p", { class: "sub" }, new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })))));
  screen.append(loading());
  let d;
  try { d = await api("/api/dashboard"); }
  catch (e) { screen.lastChild.replaceWith(el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  screen.lastChild.remove();

  // Quick actions
  screen.append(el("div", { class: "quick-actions" },
    qa("🍎", "Log food", () => openFoodSearch("snack")),
    qa("💧", "Add water", () => quickWater()),
    qa("🏋", "Log workout", () => openWorkoutSheet())));

  // Stat grid
  const n = d.nutrition, w = d.water;
  const wTotal = disp(w.total_ml, "ml"), wGoal = disp(w.goal_ml, "ml");
  const weight = d.weight ? disp(d.weight.value, "kg") : null;
  const grid = el("div", { class: "stat-grid" });
  grid.append(
    statCard("🔥 Calories", n.kcal ? fmt(n.kcal) : "—", `of ${fmt(n.kcal_goal || State.goals.calories?.target)} kcal`,
      { goalKey: "calories", current: n.kcal, onclick: openCaloriesDetail }),
    statCard("💪 Protein", n.protein ? fmt(n.protein) + "g" : "—", `of ${fmt(n.protein_goal || State.goals.protein?.target)}g`,
      { goalKey: "protein", current: n.protein, onclick: openProteinDetail }),
    statCard("💧 Water", fmt(wTotal.value) + " fl oz", `of ${fmt(wGoal.value)} fl oz`,
      { goalKey: "water", current: w.total_ml, color: "blue", pctVal: w.pct, onclick: openWaterDetail }),
    statCard("👟 Steps", d.steps_today != null ? fmt(d.steps_today) : "—", goalSub("steps"),
      { goalKey: "steps", current: d.steps_today,
        onclick: () => openMetricDetail("steps", { label: "Steps", periods: [7, 30, 90, 365], default: 30 }) }),
    statCard("⚡ Active energy", d.active_energy_today != null ? fmt(d.active_energy_today) + " kcal" : "—", goalSub("active_energy"),
      { goalKey: "active_energy", current: d.active_energy_today,
        onclick: () => openMetricDetail("active_energy", { label: "Active Energy", periods: [7, 30, 90, 365], default: 30 }) }),
    statCard("⚖️ Weight", weight ? fmt(weight.value, 1) + " lb" : "—", d.weight ? d.weight.date : "no data",
      { onclick: openWeightDetail }),
    statCard("😴 Sleep", d.sleep_last ? round(d.sleep_last.asleep_hours, 1) + "h" : "—", d.sleep_last ? goalSub("sleep", "last night") : "no data",
      { goalKey: d.sleep_last ? "sleep" : null, current: d.sleep_last?.asleep_hours, onclick: openSleepDetail }),
    statCard("🏋 Workouts", d.workouts_week, "this week", { onclick: openWorkoutsDetail }));
  screen.append(grid);

  // Streaks
  const s = d.streaks;
  screen.append(el("div", { class: "card" },
    el("div", { class: "card-head" }, el("h3", {}, "Streaks")),
    el("div", { class: "streaks" },
      streakBox("🔥", s.food, "Food log", openCaloriesDetail),
      streakBox("⚡", s.workout, "Workouts", openWorkoutsDetail),
      streakBox("💧", s.water, "Water goal", openWaterDetail))));

  // Active goals
  if (d.goals?.length) {
    const card = el("div", { class: "card" },
      el("div", { class: "card-head" }, el("h3", {}, "Goals"),
        el("a", { class: "link text-btn", onclick: () => switchTab("goals") }, "Manage")));
    d.goals.slice(0, 4).forEach((g) => card.append(goalRow(g, true)));
    screen.append(card);
  }

  // Achievements strip
  try {
    const { achievements } = await api("/api/achievements");
    const unlocked = achievements.filter((a) => a.unlocked);
    if (achievements.length) {
      const strip = el("div", { class: "scroller badges" });
      achievements.forEach((a) => strip.append(
        el("div", { class: "badge " + (a.unlocked ? "on" : ""), title: a.desc },
          el("div", { class: "b-icon" }, a.unlocked ? a.icon : "🔒"),
          el("div", { class: "b-title" }, a.title))));
      screen.append(el("div", { class: "card" },
        el("div", { class: "card-head" }, el("h3", {}, "Achievements"),
          el("span", { class: "muted", style: "font-size:13px" }, `${unlocked.length}/${achievements.length}`)),
        strip));
    }
  } catch {}
}
function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
function qa(icon, lbl, onclick) {
  return el("div", { class: "qa", onclick },
    el("div", { class: "qa-icon" }, icon), el("div", { class: "qa-lbl" }, lbl));
}
// opts: { goalKey, current, pctVal, color, onclick }. When goalKey is given and
// State has that goal, the card shows a colour-coded bar + "· N%" against the
// personalized daily target; otherwise it falls back to pctVal/color.
function statCard(label, value, sub, opts = {}) {
  const { goalKey, current, color = "", onclick = null } = opts;
  let pctVal = opts.pctVal, tone = color, pctTxt = null;
  if (goalKey && State.goals[goalKey] && current != null) {
    const p = goalPct(goalKey, current);
    if (p != null) { pctVal = Math.min(100, p); tone = goalTone(goalKey, current); pctTxt = p + "%"; }
  }
  const subTxt = sub ? (pctTxt ? `${sub} · ${pctTxt}` : sub) : null;
  const node = el("div", { class: "stat" + (onclick ? " tappable" : ""), onclick },
    el("div", { class: "label" }, label),
    el("div", { class: "value", html: String(value) }),
    subTxt ? el("div", { class: "sub" }, subTxt) : null);
  if (pctVal != null) node.append(el("div", { class: "bar " + tone }, el("span", { style: `width:${Math.min(100, pctVal)}%` })));
  return node;
}
function streakBox(icon, n, lbl, onclick) {
  return el("div", { class: "streak" + (onclick ? " tappable" : ""), onclick },
    el("div", { class: "s-num" }, el("span", { class: "flame" }, n > 0 ? icon : "·"), " " + n),
    el("div", { class: "s-lbl" }, lbl));
}
const pct = (v, goal) => goal ? round((num(v) / goal) * 100) : 0;

/* ============================================================
   Personalized daily goals
   ------------------------------------------------------------
   State.goals holds the user's target for each metric (calories, protein,
   water, steps, …), loaded once at boot and refreshed when edited in Settings.
   Every card measures the current value against these to show "% of daily goal"
   and a colour-coded bar (green on track, amber close, coral off-track — and
   inverted for sugar/sodium, where staying *under* the number is the win).
   ============================================================ */
async function loadGoals() {
  try { State.goals = (await api("/api/daily-goals")).goals || {}; }
  catch { State.goals = State.goals || {}; }
  return State.goals;
}
// Percentage of the daily goal a value represents (null if no goal for the key).
function goalPct(key, value) {
  const g = State.goals[key];
  if (!g || !g.target || value == null) return null;
  return round((num(value) / g.target) * 100);
}
// HTML suffix showing what % of the daily goal a single value contributes,
// e.g. " · <span…>18% daily</span>". Returns "" when no goal exists for the key.
// A meaningful contribution (≥20% of the day in one item) is highlighted green;
// everything else stays muted — it's informational, not a pass/fail signal.
function dailyContribHtml(key, value) {
  const p = goalPct(key, value);
  if (p == null) return "";
  return ` · <span class="kv-pct${p >= 20 ? " good" : ""}">${p}% daily</span>`;
}
// Colour tone for a value vs its goal: "good" | "mid" | "low".
// Higher-is-better: ≥75% good, 50–75% mid, <50% low.
// Lower-is-better (sugar, sodium): ≤75% good, 75–100% mid, over budget low.
function goalTone(key, value) {
  const g = State.goals[key];
  if (!g || !g.target || value == null) return "";
  const p = (num(value) / g.target) * 100;
  if (g.lower_better) return p <= 75 ? "good" : p <= 100 ? "mid" : "low";
  return p >= 75 ? "good" : p >= 50 ? "mid" : "low";
}
// Sub-label for a card showing the goal, e.g. "of 10,000" or "of 500 kcal".
function goalSub(key, fallback = "today") {
  const g = State.goals[key];
  if (!g || !g.target) return fallback;
  const u = key === "calories" ? "kcal" : (g.unit || "");
  return `of ${fmt(g.target)}${u ? " " + u : ""}`;
}
// A labelled goal progress row (Daily-targets card on the Food tab).
function goalBarRow(key, value) {
  const g = State.goals[key];
  if (!g || !g.target) return null;
  const p = goalPct(key, value), tone = goalTone(key, value);
  // Water is stored in ml but shown in fl oz; the percentage is unit-agnostic.
  const isWater = g.unit === "ml";
  const dp = (key === "fiber" || key === "sugar") ? 1 : 0;
  const unit = key === "calories" ? "kcal" : (isWater ? "fl oz" : (g.unit || ""));
  const shownVal = isWater ? disp(value, "ml").value : value;
  const shownTgt = isWater ? disp(g.target, "ml").value : g.target;
  return el("div", { class: "tgt-row" },
    el("div", { class: "tgt-top" },
      el("span", { class: "tgt-name" }, g.label + (g.lower_better ? " (max)" : "")),
      el("span", { class: "tgt-val" + (g.lower_better && p > 100 ? " over" : "") },
        `${fmt(shownVal, dp)} / ${fmt(shownTgt)} ${unit} · ${p}%`)),
    el("div", { class: "bar " + tone }, el("span", { style: `width:${Math.min(100, p)}%` })));
}

/* ============================================================
   FOOD
   ============================================================ */
async function renderFood() {
  const screen = $("#screen");
  screen.append(el("div", { class: "screen-head" },
    el("div", {}, el("h2", {}, "Food"),
      el("p", { class: "sub" }, dateLabel(State.foodDate))),
    el("div", { class: "row" },
      el("button", { class: "ghost-btn", onclick: () => shiftFoodDate(-1) }, "‹"),
      el("button", { class: "ghost-btn", onclick: () => shiftFoodDate(1) }, "›"))));
  screen.append(loading());

  let log, nutrition, favs, water;
  try {
    [log, nutrition, favs, water] = await Promise.all([
      api("/api/food?date=" + State.foodDate),
      api("/api/nutrition?days=30"),
      api("/api/favorites"),
      api("/api/water?date=" + State.foodDate),
    ]);
  } catch (e) { screen.lastChild.replaceWith(el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  screen.lastChild.remove();

  // Quick Add — saved favorites logged with a single tap.
  screen.append(quickAddSection(favs.favorites || []));

  // Day totals including micros (list_food totals only carry the four macros).
  const t = log.totals;
  const tot = { kcal: t.kcal, protein: t.protein, carbs: t.carbs, fat: t.fat, fiber: 0, sugar: 0, sodium: 0, water: water.total_ml };
  (log.entries || []).forEach((e) => { tot.fiber += num(e.fiber); tot.sugar += num(e.sugar); tot.sodium += num(e.sodium); });

  // Totals card with macro split — tap to drill into calories
  const calGoal = State.goals.calories?.target;
  const calPct = goalPct("calories", t.kcal);
  screen.append(el("div", { class: "card d-tap", onclick: openCaloriesDetail },
    el("div", { class: "ring-wrap" },
      el("div", {}, el("div", { class: "value", style: "font-size:30px;font-weight:800" }, fmt(t.kcal)),
        el("div", { class: "muted", style: "font-size:13px" },
          calGoal ? `of ${fmt(calGoal)} kcal · ${calPct}% ›` : "calories today ›")),
      el("div", { class: "grow macros" },
        macroBox("p", "Protein", t.protein, "protein"),
        macroBox("c", "Carbs", t.carbs, "carbs"),
        macroBox("f", "Fat", t.fat, "fat")))));

  // Daily targets — every macro & micro against the personalized goal.
  if (Object.keys(State.goals).length) {
    const card = el("div", { class: "card" },
      el("div", { class: "card-head" }, el("h3", {}, "Daily targets"),
        el("a", { class: "link text-btn", onclick: openSettings }, "Edit")));
    [["calories", "kcal"], ["protein", "protein"], ["carbs", "carbs"], ["fat", "fat"],
     ["fiber", "fiber"], ["sugar", "sugar"], ["sodium", "sodium"], ["water", "water"]].forEach(([gk, vk]) => {
      const row = goalBarRow(gk, tot[vk]);
      if (row) card.append(row);
    });
    screen.append(card);
  }

  // Add buttons per meal
  State.config.meals.forEach((meal) => {
    const entries = log.by_meal[meal] || [];
    const kcal = entries.reduce((a, e) => a + num(e.kcal), 0);
    const block = el("div", { class: "meal-block" },
      el("div", { class: "meal-head" },
        el("span", { class: "m-name" }, `${MEAL_ICONS[meal] || ""} ${meal}`),
        el("div", { class: "row", style: "align-items:center;gap:10px" },
          el("span", { class: "m-kcal" }, kcal ? fmt(kcal) + " kcal" : ""),
          el("button", { class: "add-inline", onclick: () => openFoodSearch(meal) }, "+ Add"))));
    if (entries.length) {
      const list = el("div", { class: "card list", style: "margin-top:6px" });
      entries.forEach((e) => list.append(foodEntryRow(e)));
      block.append(list);
    }
    screen.append(block);
  });

  // Water — hydration is part of daily nutrition, so log & track it here too.
  screen.append(waterSection(water));

  // Nutrition trend
  if (nutrition.available) {
    const { card, canvas } = chartCard(`Calories — last 30 days (avg ${fmt(nutrition.avg_kcal)})`);
    screen.append(card);
    makeChart(canvas, {
      type: "line",
      data: { labels: nutrition.series.map((r) => r.date.slice(5)),
        datasets: [lineDataset("kcal", nutrition.series.map((r) => r.kcal), TEAL)] },
      options: { scales: AXES, plugins: { legend: { display: false } } },
    });
  }
}
function macroBox(cls, lbl, val, goalKey) {
  const p = goalKey ? goalPct(goalKey, val) : null;
  return el("div", { class: "macro " + cls },
    el("div", { class: "m-val" }, fmt(val) + "g"),
    el("div", { class: "m-lbl" }, lbl),
    p != null ? el("div", { class: "m-pct" }, p + "%") : null);
}

/* ---- Water section on the Food tab ---- */
// Common pours in fluid ounces (water is stored in ml).
const WATER_PRESETS = [["🥛 Glass", 8], ["🍶 Bottle", 16], ["🧴 Large", 24]];

function waterSection(water) {
  const goalMl = water.goal_ml, totMl = water.total_ml;
  const tt = disp(totMl, "ml"), g = disp(goalMl, "ml");
  const p = goalMl ? round(totMl / goalMl * 100) : 0;
  const card = el("div", { class: "card" },
    el("div", { class: "card-head" },
      el("h3", {}, "💧 Water"),
      el("a", { class: "link text-btn", onclick: openWaterDetail }, "Details ›")));
  // Today's total + progress bar
  card.append(el("div", { class: "water-total" },
    `${fmt(tt.value)} / ${fmt(g.value)} fl oz · ${p}%`));
  card.append(el("div", { class: "bar blue" },
    el("span", { style: `width:${Math.min(100, p)}%` })));
  // Quick-add buttons for common amounts + custom entry
  const row = el("div", { class: "row wrap", style: "margin-top:14px" });
  WATER_PRESETS.forEach(([lbl, oz]) =>
    row.append(el("button", { class: "pill", onclick: () => addFoodWater(oz) }, `${lbl} · ${oz} oz`)));
  row.append(el("button", { class: "pill", onclick: openCustomWater }, "＋ Custom"));
  card.append(row);
  // Today's entries with timestamps + delete
  if (water.entries && water.entries.length) {
    const list = el("div", { class: "list", style: "margin-top:8px" });
    water.entries.forEach((e) => {
      const oz = disp(e.amount_ml, "ml");
      list.append(el("div", { class: "lrow" },
        el("div", { class: "l-icon" }, "💧"),
        el("div", { class: "l-main" },
          el("div", { class: "l-title" }, fmt(oz.value) + " fl oz"),
          el("div", { class: "l-sub" }, timeOf(e.created_at))),
        el("button", { class: "del", onclick: async () => {
          await jdel("/api/water/" + e.id); toast("Removed"); switchTab("food");
        } }, "✕")));
    });
    card.append(list);
  } else {
    card.append(el("div", { class: "empty", style: "padding:18px 12px 4px" },
      "No water logged yet — tap a button above."));
  }
  return card;
}

async function addFoodWater(oz) {
  await jpost("/api/water", { amount_ml: toMetric(oz, "ml"), date: State.foodDate });
  toast(`+${oz} oz water`); switchTab("food");
}

function openCustomWater() {
  const input = el("input", { type: "number", placeholder: "Fluid ounces", inputmode: "decimal" });
  const body = el("div", {},
    el("p", { class: "muted", style: "margin-top:0" }, "Log a custom amount"),
    el("div", { class: "field" }, input),
    el("button", { class: "btn full", onclick: async () => {
      const v = num(input.value); if (!v) return;
      await jpost("/api/water", { amount_ml: toMetric(v, "ml"), date: State.foodDate });
      closeSheet(); toast("Water logged"); switchTab("food");
    } }, "Add water"));
  openSheet("Add water", body);
}

/* ---- Quick Add (favorites) ---- */
const FAV_ICONS = { breakfast: "🍳", lunch: "🥗", dinner: "🍽", snack: "🍎", drink: "🥤" };

function quickAddSection(favorites) {
  const wrap = el("div", { class: "qadd-wrap" });
  wrap.append(el("div", { class: "qadd-head" },
    el("span", { class: "qadd-title" }, "⚡ Quick Add"),
    el("button", { class: "qadd-edit", onclick: openManageFavorites }, "⚙ Edit")));
  if (!favorites.length) {
    wrap.append(el("div", { class: "qadd-empty", onclick: openManageFavorites },
      "Save your go-to meals for one-tap logging →"));
    return wrap;
  }
  const row = el("div", { class: "scroller qadd-scroller" });
  favorites.forEach((f) => row.append(quickAddCard(f)));
  wrap.append(row);
  return wrap;
}

function quickAddCard(fav) {
  const icon = FAV_ICONS[fav.category] || "🍎";
  const calPct = goalPct("calories", fav.calories), proPct = goalPct("protein", fav.protein_g);
  const card = el("div", { class: "qadd-card", title: favGoalSummary(fav) || fav.description || fav.name },
    el("div", { class: "qadd-emoji" }, icon),
    el("div", { class: "qadd-name" }, fav.name),
    el("div", { class: "qadd-kcal" }, fmt(fav.calories) + " kcal · " + fmt(fav.protein_g) + "P"),
    calPct != null ? el("div", { class: "qadd-pct" }, `${calPct}% cals · ${proPct}% protein`) : null,
    el("button", { class: "qadd-plus", "aria-label": "Log " + fav.name,
      onclick: (e) => { e.stopPropagation(); logFavorite(fav, card); } }, "+"));
  card.addEventListener("click", () => logFavorite(fav, card));
  return card;
}

// "20% of daily calories, 33% of daily protein" — what one serving contributes.
function favGoalSummary(fav) {
  const c = goalPct("calories", fav.calories), p = goalPct("protein", fav.protein_g);
  if (c == null) return "";
  return `${fav.name}: ${c}% of daily calories, ${p}% of daily protein`;
}

// Optimistic one-tap log: flash the card, toast immediately, then sync totals.
async function logFavorite(fav, card) {
  if (card) {
    if (card.dataset.busy) return;       // ignore double-taps mid-request
    card.dataset.busy = "1";
    card.classList.add("logged");
  }
  toast("Logged " + fav.name + " ✓");
  try {
    await jpost("/api/favorites/" + fav.id + "/log", { date: State.foodDate });
    if (State.tab === "food") switchTab("food");   // refresh totals & meal lists
  } catch (e) {
    toast("⚠ " + e.message);
    if (card) { card.classList.remove("logged"); delete card.dataset.busy; }
  }
}

/* ---- Manage favorites ---- */
async function openManageFavorites() {
  openSheet("Quick Add favorites", el("div", { class: "empty" }, loadingDots("Loading")));
  let favorites;
  try { favorites = (await api("/api/favorites")).favorites || []; }
  catch (e) { openSheet("Quick Add favorites", el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  renderManageFavorites(favorites);
}

function loadingDots(msg) { return el("div", { class: "thinking dots" }, msg); }

function renderManageFavorites(favorites) {
  const body = el("div", {});
  const list = el("div", { class: "fav-manage-list" });
  if (!favorites.length) {
    list.append(el("div", { class: "empty" }, "No favorites yet."));
  }
  favorites.forEach((f, i) => list.append(favManageRow(f, i, favorites)));
  body.append(list,
    el("button", { class: "btn full", style: "margin-top:14px",
      onclick: () => openFavoriteForm(null) }, "+ Add favorite"));
  openSheet("Quick Add favorites", body);
}

function favManageRow(fav, idx, favorites) {
  const icon = FAV_ICONS[fav.category] || "🍎";
  const reorder = el("div", { class: "fav-reorder" },
    el("button", { class: "fav-move", disabled: idx === 0, "aria-label": "Move up",
      onclick: () => moveFavorite(favorites, idx, -1) }, "▲"),
    el("button", { class: "fav-move", disabled: idx === favorites.length - 1, "aria-label": "Move down",
      onclick: () => moveFavorite(favorites, idx, 1) }, "▼"));
  return el("div", { class: "fav-mrow" },
    reorder,
    el("div", { class: "fav-mmain", onclick: () => openFavoriteForm(fav) },
      el("div", { class: "fav-mname" }, icon + " " + fav.name),
      el("div", { class: "fav-msub" },
        fmt(fav.calories) + " kcal · " + fmt(fav.protein_g) + "P "
        + fmt(fav.carbs_g) + "C " + fmt(fav.fat_g) + "F"),
      goalPct("calories", fav.calories) != null
        ? el("div", { class: "fav-mpct" },
            `${goalPct("calories", fav.calories)}% of daily calories · ${goalPct("protein", fav.protein_g)}% of daily protein`)
        : null),
    el("button", { class: "del", "aria-label": "Delete",
      onclick: async (e) => {
        e.stopPropagation();
        await jdel("/api/favorites/" + fav.id);
        renderManageFavorites(favorites.filter((x) => x.id !== fav.id));
        if (State.tab === "food") refreshQuickAdd();
      } }, "🗑"));
}

// Swap a favorite with its neighbour and persist both sort_orders.
async function moveFavorite(favorites, idx, dir) {
  const j = idx + dir;
  if (j < 0 || j >= favorites.length) return;
  const a = favorites[idx], b = favorites[j];
  [favorites[idx], favorites[j]] = [b, a];
  renderManageFavorites(favorites);          // optimistic reorder
  try {
    await Promise.all([
      jput("/api/favorites/" + a.id, { sort_order: j }),
      jput("/api/favorites/" + b.id, { sort_order: idx }),
    ]);
    a.sort_order = j; b.sort_order = idx;
    if (State.tab === "food") refreshQuickAdd();
  } catch (e) { toast("⚠ " + e.message); }
}

function openFavoriteForm(fav) {
  const editing = !!fav;
  const f = fav || { category: "snack" };
  const name = el("input", { placeholder: "e.g. Protein Matcha", value: f.name || "" });
  const desc = el("input", { placeholder: "ingredients / details (optional)", value: f.description || "" });
  const cats = ["breakfast", "lunch", "dinner", "snack", "drink"];
  const category = el("select", {}, ...cats.map((c) =>
    el("option", { value: c, selected: f.category === c }, (FAV_ICONS[c] || "") + " " + c)));
  const numIn = (k, ph) => el("input", { type: "number", step: "any", inputmode: "decimal",
    placeholder: ph, value: f[k] != null ? f[k] : "" });
  const calories = numIn("calories", "kcal"), protein = numIn("protein_g", "g");
  const carbs = numIn("carbs_g", "g"), fat = numIn("fat_g", "g");
  const fiber = numIn("fiber_g", "g"), sugar = numIn("sugar_g", "g"), sodium = numIn("sodium_mg", "mg");
  const field = (label, node) => el("div", { class: "field grow" }, el("label", {}, label), node);

  const body = el("div", {},
    field("Name", name),
    field("Description", desc),
    field("Category", category),
    el("div", { class: "row" }, field("Calories", calories), field("Protein (g)", protein)),
    el("div", { class: "row" }, field("Carbs (g)", carbs), field("Fat (g)", fat)),
    el("div", { class: "section-title", style: "margin-top:4px" }, "Optional micros"),
    el("div", { class: "row" }, field("Fiber (g)", fiber), field("Sugar (g)", sugar)),
    field("Sodium (mg)", sodium),
    el("button", { class: "btn full", style: "margin-top:10px", onclick: async () => {
      if (!name.value.trim()) return toast("Name required");
      const payload = {
        name: name.value.trim(), description: desc.value.trim(),
        category: category.value,
        calories: num(calories.value), protein_g: num(protein.value),
        carbs_g: num(carbs.value), fat_g: num(fat.value),
        fiber_g: fiber.value === "" ? null : num(fiber.value),
        sugar_g: sugar.value === "" ? null : num(sugar.value),
        sodium_mg: sodium.value === "" ? null : num(sodium.value),
      };
      try {
        if (editing) await jput("/api/favorites/" + f.id, payload);
        else await jpost("/api/favorites", payload);
      } catch (e) { return toast("⚠ " + e.message); }
      toast(editing ? "Saved" : "Favorite added");
      openManageFavorites();
      if (State.tab === "food") refreshQuickAdd();
    } }, editing ? "Save changes" : "Add favorite"));

  if (editing) {
    body.append(el("button", { class: "btn danger full", style: "margin-top:10px",
      onclick: async () => {
        await jdel("/api/favorites/" + f.id);
        toast("Deleted");
        openManageFavorites();
        if (State.tab === "food") refreshQuickAdd();
      } }, "Delete favorite"));
  }
  openSheet(editing ? "Edit favorite" : "New favorite", body);
}

// Re-fetch just the Quick Add row and swap it in, so managing favorites updates
// the Food tab behind the sheet without a full re-render.
async function refreshQuickAdd() {
  const existing = $(".qadd-wrap");
  if (!existing) return;
  try {
    const favs = (await api("/api/favorites")).favorites || [];
    existing.replaceWith(quickAddSection(favs));
  } catch {}
}
function foodEntryRow(e) {
  return el("div", { class: "lrow d-tap-row", onclick: () => openFoodEntryDetail(e) },
    el("div", { class: "l-main" },
      el("div", { class: "l-title" }, e.name + (e.qty !== 1 ? ` ×${round(e.qty, 2)}` : "")),
      el("div", { class: "l-sub" }, `${fmt(e.protein)}P · ${fmt(e.carbs)}C · ${fmt(e.fat)}F`)),
    el("div", { class: "l-val" }, fmt(e.kcal), el("small", {}, " kcal")),
    el("button", { class: "move", title: "Move to another meal",
      onclick: (ev) => { ev.stopPropagation(); openMoveFood(e); } }, "⇄"),
    el("button", { class: "del", onclick: async (ev) => { ev.stopPropagation(); await jdel("/api/food/" + e.id); switchTab("food"); } }, "✕"));
}

// Reassign a food entry to a different meal. `after` runs once the move lands
// (e.g. to refresh an open detail overlay); the Food tab is always re-rendered.
async function moveFood(e, meal, after) {
  if (meal === e.meal) return;
  try {
    await jput("/api/food/" + e.id + "/meal", { meal });
    e.meal = meal;
    toast(`Moved ${e.name} to ${meal}`);
    if (after) after();
    if (State.tab === "food") switchTab("food");
  } catch (err) {
    toast(err.message || "Couldn't move that entry");
  }
}

// Sheet of the four meals; tapping one moves the entry and closes the sheet.
function openMoveFood(e, after) {
  const body = el("div", {});
  State.config.meals.forEach((meal) => {
    body.append(el("button", {
      class: "btn full" + (meal === e.meal ? " secondary" : ""),
      style: "margin-top:10px",
      disabled: meal === e.meal || null,
      onclick: async () => { closeSheet(); await moveFood(e, meal, after); },
    }, `${MEAL_ICONS[meal] || ""} ${meal}` + (meal === e.meal ? " (current)" : "")));
  });
  openSheet(`Move ${e.name}`, body);
}
function dateLabel(iso) {
  if (iso === todayISO()) return "Today";
  return new Date(iso + "T00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}
function shiftFoodDate(delta) {
  const d = new Date(State.foodDate + "T00:00");
  d.setDate(d.getDate() + delta);
  const iso = d.toISOString().slice(0, 10);
  if (iso > todayISO()) return;
  State.foodDate = iso;
  switchTab("food");
}

// Food search sheet
async function openFoodSearch(meal) {
  const body = el("div", {});
  const search = el("input", { type: "search", placeholder: "Search foods…", autocomplete: "off" });
  const results = el("div", { class: "list" });
  // Photo logging: a hidden file input the camera button triggers. `capture`
  // hints the rear camera on phones; on desktop it falls back to a file picker.
  const photoInput = el("input", { type: "file", accept: "image/*", capture: "environment", style: "display:none" });
  photoInput.addEventListener("change", () => {
    const f = photoInput.files[0]; photoInput.value = "";
    if (f) analyzeFoodPhoto(f, meal);
  });
  const photoBtn = el("button", { class: "btn full", style: "margin-top:12px",
    onclick: () => photoInput.click() }, "📷 Snap a photo");
  const scanBtn = el("button", { class: "btn secondary full", style: "margin-top:10px",
    onclick: () => openBarcodeScanner(meal) }, "▦ Scan barcode");
  const customBtn = el("button", { class: "btn secondary full", style: "margin-top:10px",
    onclick: () => openCustomFood(meal) }, "+ Create custom food");
  body.append(el("div", { class: "field" }, search), results, photoInput, photoBtn, scanBtn, customBtn);
  openSheet(`Add to ${meal}`, body);

  const run = async (q) => {
    const { foods } = await api("/api/foods?q=" + encodeURIComponent(q));
    results.innerHTML = "";
    foods.forEach((f) => results.append(
      el("div", { class: "food-result", onclick: () => openFoodQty(f, meal) },
        el("div", { class: "fr-main" },
          el("div", { class: "fr-name" }, f.name),
          el("div", { class: "fr-sub" }, `${servingUS(f.serving) || "1 serving"} · ${fmt(f.protein)}P ${fmt(f.carbs)}C ${fmt(f.fat)}F`)),
        el("div", { class: "fr-kcal" }, fmt(f.kcal)))));
    if (!foods.length) results.append(el("div", { class: "empty" }, "No matches — snap a photo or create a custom food."));
  };
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => run(search.value), 180); });
  run("");
  setTimeout(() => search.focus(), 100);
}
// Quantity picker for a chosen food
function openFoodQty(food, meal) {
  const qty = el("input", { type: "number", step: "0.25", value: "1", inputmode: "decimal" });
  const out = el("div", { class: "muted", style: "font-size:13px;margin-top:6px" });
  const upd = () => { const q = num(qty.value, 1); out.textContent =
    `${fmt(food.kcal * q)} kcal · ${fmt(food.protein * q)}P ${fmt(food.carbs * q)}C ${fmt(food.fat * q)}F`; };
  qty.addEventListener("input", upd); upd();
  const body = el("div", {},
    el("p", { class: "muted", style: "margin-top:0" }, `${food.name} — ${servingUS(food.serving) || "per serving"}`),
    el("div", { class: "field" }, el("label", {}, "Servings"), qty), out,
    el("button", { class: "btn full", style: "margin-top:14px", onclick: async () => {
      await jpost("/api/food", { name: food.name, kcal: food.kcal, protein: food.protein,
        carbs: food.carbs, fat: food.fat, meal, qty: num(qty.value, 1), serving: food.serving,
        date: State.foodDate, food_id: food.id });
      closeSheet(); toast("Logged " + food.name); switchTab("food");
    } }, "Add"));
  openSheet("How much?", body);
}
function openCustomFood(meal) {
  const f = {};
  const inp = (k, label, ph = "") => { const i = el("input", { type: "number", step: "any", inputmode: "decimal", placeholder: ph });
    f[k] = i; return el("div", { class: "field grow" }, el("label", {}, label), i); };
  const name = el("input", { placeholder: "e.g. Mom's lasagna" });
  const serving = el("input", { placeholder: "1 serving" });
  const body = el("div", {},
    el("div", { class: "field" }, el("label", {}, "Name"), name),
    el("div", { class: "field" }, el("label", {}, "Serving"), serving),
    el("div", { class: "row" }, inp("kcal", "Calories"), inp("protein", "Protein (g)")),
    el("div", { class: "row" }, inp("carbs", "Carbs (g)"), inp("fat", "Fat (g)")),
    el("button", { class: "btn full", style: "margin-top:8px", onclick: async () => {
      if (!name.value.trim()) return toast("Name required");
      const payload = { name: name.value.trim(), serving: serving.value,
        kcal: num(f.kcal.value), protein: num(f.protein.value), carbs: num(f.carbs.value), fat: num(f.fat.value) };
      const saved = await jpost("/api/foods", payload);
      await jpost("/api/food", { ...payload, meal, qty: 1, date: State.foodDate, food_id: saved.id });
      closeSheet(); toast("Logged " + payload.name); switchTab("food");
    } }, "Save & log"));
  openSheet("Custom food", body);
}

// Photo logging: send the picked image to the AI, then open a prefilled review.
async function analyzeFoodPhoto(file, meal) {
  openSheet("Analyzing photo", el("div", { class: "empty" },
    el("div", { class: "thinking dots" }, "🔍 Estimating macros from your photo")));
  const fd = new FormData();
  fd.append("file", file);
  try {
    const { estimate } = await api("/api/food/analyze", { method: "POST", body: fd });
    openFoodReview(estimate, meal);
  } catch (e) {
    openSheet("Photo analysis", el("div", {},
      el("div", { class: "empty" }, "⚠ " + e.message),
      el("button", { class: "btn full", onclick: () => openFoodSearch(meal) }, "Back")));
  }
}
// Review/adjust an estimate (AI photo or scanned barcode) before logging it.
function openFoodReview(est, meal, opts = {}) {
  const title = opts.title || "Review estimate";
  const intro = opts.intro || "AI estimate from your photo — review and adjust, then save.";
  const f = {};
  const numField = (k, label, val) => {
    const i = el("input", { type: "number", step: "any", inputmode: "decimal",
      value: val != null ? round(val, 1) : "" });
    f[k] = i;
    return el("div", { class: "field grow" }, el("label", {}, label), i);
  };
  const name = el("input", { value: est.name || "" });
  const serving = el("input", { value: est.serving || "", placeholder: "e.g. 6 oz" });
  const body = el("div", {},
    el("p", { class: "muted", style: "margin-top:0" }, intro),
    est.notes ? el("p", { class: "muted", style: "font-size:13px" }, "📝 " + est.notes) : null,
    el("div", { class: "field" }, el("label", {}, "Food"), name),
    el("div", { class: "field" }, el("label", {}, "Serving"), serving),
    el("div", { class: "row" }, numField("kcal", "Calories"), numField("protein", "Protein (g)")),
    el("div", { class: "row" }, numField("carbs", "Carbs (g)"), numField("fat", "Fat (g)")),
    el("div", { class: "row" }, numField("fiber", "Fiber (g)"), numField("sugar", "Sugar (g)")),
    el("div", { class: "row" }, numField("sodium", "Sodium (mg)")),
    el("button", { class: "btn full", style: "margin-top:8px", onclick: async () => {
      if (!name.value.trim()) return toast("Name required");
      await jpost("/api/food", {
        name: name.value.trim(), serving: serving.value, meal, qty: 1, date: State.foodDate,
        kcal: num(f.kcal.value), protein: num(f.protein.value),
        carbs: num(f.carbs.value), fat: num(f.fat.value),
        fiber: num(f.fiber.value), sugar: num(f.sugar.value), sodium: num(f.sodium.value),
      });
      closeSheet(); toast("Logged " + name.value.trim()); switchTab("food");
    } }, "Log food"));
  // Seed the inputs with the estimate (after build so refs exist).
  f.kcal.value = est.kcal != null ? round(est.kcal, 1) : "";
  f.protein.value = est.protein != null ? round(est.protein, 1) : "";
  f.carbs.value = est.carbs != null ? round(est.carbs, 1) : "";
  f.fat.value = est.fat != null ? round(est.fat, 1) : "";
  f.fiber.value = est.fiber != null ? round(est.fiber, 1) : "";
  f.sugar.value = est.sugar != null ? round(est.sugar, 1) : "";
  f.sodium.value = est.sodium != null ? round(est.sodium, 0) : "";
  openSheet(title, body);
}

/* ------------------------------------------------------------
   Barcode scanning (Food tab)
   ------------------------------------------------------------
   Live-camera UPC/EAN scan via QuaggaJS, then a free, key-less
   nutrition lookup against Open Food Facts (public CORS API, so the
   request stays client-side — no backend proxy needed). On a confirmed
   read we map the response into the same `est` shape the photo flow
   uses and hand off to openFoodReview so the user reviews and adjusts.
   ------------------------------------------------------------ */
async function openBarcodeScanner(meal) {
  if (!window.Quagga) { toast("Scanner not available"); return openFoodSearch(meal); }
  const viewport = el("div", { class: "scanner-view", id: "scannerView" });
  const status = el("div", { class: "muted", style: "text-align:center;margin-top:10px" },
    "Point your camera at a barcode");
  // Manual fallback for damaged labels or when the camera is unavailable.
  const manual = el("input", { type: "text", inputmode: "numeric", autocomplete: "off",
    placeholder: "or type the barcode number" });
  const manualBtn = el("button", { class: "btn secondary full", style: "margin-top:10px",
    onclick: () => { const code = manual.value.replace(/\D/g, ""); if (code.length >= 8) lookupBarcode(code, meal);
      else toast("Enter a valid barcode"); } }, "Look up");
  const body = el("div", {}, viewport, status,
    el("div", { class: "field", style: "margin-top:14px" }, manual), manualBtn);
  openSheet("Scan barcode", body);

  let done = false;          // guard so we only act on the first solid read
  let lastCode = null;       // require two consecutive matching reads to confirm
  const onDetected = (result) => {
    const code = result?.codeResult?.code;
    if (!code || done) return;
    if (code === lastCode) {
      done = true;
      runSheetCleanup();     // stop the camera before we navigate on
      lookupBarcode(code, meal);
    } else {
      lastCode = code;
      status.textContent = "Reading…";
    }
  };
  const teardown = () => {
    try { Quagga.offDetected(onDetected); } catch {}
    try { Quagga.stop(); } catch {}
  };
  onSheetClose(teardown);

  Quagga.init({
    inputStream: {
      name: "Live", type: "LiveStream", target: viewport,
      constraints: { facingMode: "environment" },
    },
    locator: { patchSize: "medium", halfSample: true },
    decoder: { readers: ["ean_reader", "ean_8_reader", "upc_reader", "upc_e_reader"] },
  }, (err) => {
    if (err) {
      onSheetClose(null);
      const denied = /permission|denied|notallowed/i.test(String(err.name || err.message || err));
      status.className = "empty";
      status.textContent = denied
        ? "⚠ Camera access was blocked. Allow camera access, or type the barcode below."
        : "⚠ Couldn't start the camera. Type the barcode below instead.";
      return;
    }
    Quagga.start();
  });
  Quagga.onDetected(onDetected);
}

// Look up a UPC/EAN against Open Food Facts and pre-fill the review form.
async function lookupBarcode(code, meal) {
  openSheet("Looking up…", el("div", { class: "empty" },
    el("div", { class: "thinking dots" }, `🔎 Looking up barcode ${code}`)));
  try {
    const fields = "code,product_name,product_name_en,generic_name,brands,serving_size,nutriments";
    const res = await fetch(
      `https://world.openfoodfacts.org/api/v2/product/${encodeURIComponent(code)}.json?fields=${fields}`);
    const data = await res.json().catch(() => ({}));
    const product = data.product;
    const found = product && (data.status === 1 || data.status === "success" ||
      product.product_name || product.nutriments);
    if (!found) return barcodeNotFound(code, meal);
    const est = offToEstimate(product, code);
    openFoodReview(est, meal, {
      title: "Review scan",
      intro: "Pulled from Open Food Facts — review and adjust, then save.",
    });
  } catch (e) {
    barcodeNotFound(code, meal, "Couldn't reach Open Food Facts.");
  }
}

// Map an Open Food Facts product to the `est` shape openFoodReview expects.
// Macros are grams/kcal (already US-label units); sodium is mg. Open Food
// Facts stores values per-100g and (often) per-serving — we prefer per-serving
// when present so the logged entry matches one serving off the package.
function offToEstimate(product, code) {
  const n = product.nutriments || {};
  const perServing = n["energy-kcal_serving"] != null;
  const suffix = perServing ? "_serving" : "_100g";
  const g = (base) => { const v = n[base + suffix]; return v != null ? Number(v) : null; };
  const kcal = g("energy-kcal");
  // Open Food Facts reports sodium (and salt) in grams; the form wants mg.
  let sodiumG = g("sodium");
  if (sodiumG == null && g("salt") != null) sodiumG = g("salt") / 2.5; // salt → sodium
  const servingText = perServing ? (product.serving_size || "1 serving") : "100 g";
  const name = product.product_name || product.product_name_en || product.generic_name || "Scanned item";
  const brand = product.brands ? String(product.brands).split(",")[0].trim() : "";
  // Prefix the brand for context, unless the product name already carries it.
  const displayName = brand && !name.toLowerCase().includes(brand.toLowerCase())
    ? `${brand} ${name}` : name;
  return {
    name: displayName,
    serving: servingUS(servingText),
    kcal,
    protein: g("proteins"),
    carbs: g("carbohydrates"),
    fat: g("fat"),
    fiber: g("fiber"),
    sugar: g("sugars"),
    sodium: sodiumG != null ? sodiumG * 1000 : null,
  };
}

// No match (or lookup failed): let the user retry, type it, or fall back.
function barcodeNotFound(code, meal, msg) {
  const body = el("div", {},
    el("div", { class: "empty" }, msg
      ? `⚠ ${msg}`
      : `No product found for barcode ${code}. It may not be in the Open Food Facts database yet.`),
    el("button", { class: "btn full", style: "margin-top:8px",
      onclick: () => openBarcodeScanner(meal) }, "▦ Scan again"),
    el("button", { class: "btn secondary full", style: "margin-top:10px",
      onclick: () => openCustomFood(meal) }, "+ Enter it manually"),
    el("button", { class: "btn secondary full", style: "margin-top:10px",
      onclick: () => openFoodSearch(meal) }, "Back to search"));
  openSheet("Barcode", body);
}

async function quickWater() {
  const body = el("div", {});
  const row = el("div", { class: "row wrap" });
  // Common amounts in fluid ounces; water is stored in ml.
  [8, 12, 16, 20, 32].forEach((oz) =>
    row.append(el("button", { class: "pill", onclick: async () => {
      await jpost("/api/water", { amount_ml: toMetric(oz, "ml") }); closeSheet(); toast(`+${oz} oz water`);
      if (State.tab === "dashboard") switchTab("dashboard");
    } }, `+${oz} oz`)));
  const custom = el("input", { type: "number", placeholder: "Custom fl oz", inputmode: "decimal" });
  body.append(el("p", { class: "muted", style: "margin-top:0" }, "Quick add"), row,
    el("div", { class: "field", style: "margin-top:14px" }, custom),
    el("button", { class: "btn full", onclick: async () => {
      if (!num(custom.value)) return; await jpost("/api/water", { amount_ml: toMetric(num(custom.value), "ml") });
      closeSheet(); toast("Water logged"); if (State.tab === "dashboard") switchTab("dashboard");
    } }, "Add"));
  openSheet("Water", body);
}

/* ============================================================
   WORKOUTS
   ============================================================ */
async function renderWorkouts() {
  const screen = $("#screen");
  screen.append(el("div", { class: "screen-head" },
    el("div", {}, el("h2", {}, "Training")),
    el("button", { class: "btn", onclick: () => openWorkoutSheet() }, "+ Log")));
  screen.append(loading());

  let data, vol, prs;
  try {
    [data, vol, prs] = await Promise.all([
      api("/api/workouts?days=120"), api("/api/workouts/volume?days=30"), api("/api/workouts/prs"),
    ]);
  } catch (e) { screen.lastChild.replaceWith(el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  screen.lastChild.remove();

  // Volume chart (strength volume = Σ reps×weight, stored in kg → shown in lb)
  if (vol.series.length) {
    const totalLb = disp(vol.total_volume, "kg").value;
    const { card, canvas } = chartCard(`Strength volume — 30 days (${fmt(totalLb)} lb total, ${vol.sessions} sessions)`);
    screen.append(card);
    makeChart(canvas, {
      type: "bar",
      data: { labels: vol.series.map((r) => r.date.slice(5)),
        datasets: [{ data: vol.series.map((r) => disp(r.volume, "kg").value), backgroundColor: VIOLET + "cc", borderRadius: 5 }] },
      options: { scales: { ...AXES, y: { ...AXES.y, beginAtZero: true } } },
    });
  }

  // PRs (weights stored in kg → shown in lb)
  if (prs.records.length) {
    const card = el("div", { class: "card" }, el("div", { class: "card-head" }, el("h3", {}, "Personal records")));
    const list = el("div", { class: "list" });
    prs.records.slice(0, 8).forEach((r) => list.append(
      el("div", { class: "lrow d-tap-row", onclick: () => openExerciseDetail(r.name) },
        el("div", { class: "l-icon" }, "📈"),
        el("div", { class: "l-main" }, el("div", { class: "l-title chev" }, r.name),
          el("div", { class: "l-sub" }, `est. 1RM ${fmt(disp(r.e1rm, "kg").value, 1)} lb · ${r.date}`)),
        el("div", { class: "l-val" }, fmt(disp(r.weight, "kg").value, 1), el("small", {}, " lb ×" + fmt(r.reps))))));
    card.append(list); screen.append(card);
  }

  // History
  screen.append(el("div", { class: "section-title" }, "History"));
  if (!data.workouts.length) { screen.append(el("div", { class: "empty" }, "No workouts logged yet. Tap + Log to start.")); return; }
  const list = el("div", { class: "card list" });
  data.workouts.forEach((w) => list.append(workoutRow(w)));
  screen.append(list);
}
function workoutRow(w) {
  const bits = [];
  if (w.duration_min) bits.push(round(w.duration_min) + " min");
  if (w.distance_km) bits.push(round(disp(w.distance_km, "km").value, 1) + " mi");
  if (w.energy_kcal) bits.push(round(w.energy_kcal) + " kcal");
  if (w.exercises?.length) bits.push(w.exercises.length + " exercises");
  const row = el("div", { class: "lrow d-tap-row", onclick: () => openWorkoutDetail(w) },
    el("div", { class: "l-icon" }, WORKOUT_ICONS[w.type] || "🤸"),
    el("div", { class: "l-main" },
      el("div", { class: "l-title" }, w.activity, " ", el("span", { class: "tag " + w.type }, w.type)),
      el("div", { class: "l-sub" }, `${w.date}${bits.length ? " · " + bits.join(" · ") : ""}`)),
    w.source === "manual"
      ? el("button", { class: "del", onclick: async (ev) => { ev.stopPropagation(); await jdel("/api/workouts/" + w.id); switchTab("workouts"); } }, "✕")
      : el("span", { class: "tag" }, "Apple"));
  return row;
}
function openWorkoutSheet() {
  const type = el("select", {}, ...["strength", "cardio", "other"].map((t) => el("option", { value: t }, t[0].toUpperCase() + t.slice(1))));
  const activity = el("input", { placeholder: "e.g. Push day / Morning run" });
  const date = el("input", { type: "date", value: todayISO() });
  const dynamic = el("div", {});
  const body = el("div", {},
    el("div", { class: "field" }, el("label", {}, "Type"), type),
    el("div", { class: "field" }, el("label", {}, "Name"), activity),
    el("div", { class: "field" }, el("label", {}, "Date"), date),
    dynamic);
  const exercises = [];
  const renderDynamic = () => {
    dynamic.innerHTML = "";
    if (type.value === "strength") {
      const exWrap = el("div", {});
      const repaint = () => {
        exWrap.innerHTML = "";
        exercises.forEach((ex, i) => exWrap.append(exerciseBlock(ex, i, () => { exercises.splice(i, 1); repaint(); })));
      };
      dynamic.append(el("div", { class: "section-title", style: "margin-top:4px" }, "Exercises"), exWrap,
        el("button", { class: "btn secondary full", onclick: () => { exercises.push({ name: "", sets: [{ reps: "", weight: "" }] }); repaint(); } }, "+ Add exercise"));
      if (!exercises.length) { exercises.push({ name: "", sets: [{ reps: "", weight: "" }] }); }
      repaint();
    } else {
      const dur = el("input", { type: "number", inputmode: "decimal", placeholder: "min" });
      const dist = el("input", { type: "number", inputmode: "decimal", placeholder: "mi" });
      const kcal = el("input", { type: "number", inputmode: "numeric", placeholder: "kcal" });
      dynamic._cardio = { dur, dist, kcal };
      dynamic.append(el("div", { class: "row" },
        el("div", { class: "field grow" }, el("label", {}, "Duration"), dur),
        type.value === "cardio" ? el("div", { class: "field grow" }, el("label", {}, "Distance"), dist) : null),
        el("div", { class: "field" }, el("label", {}, "Energy (kcal)"), kcal));
    }
  };
  type.addEventListener("change", renderDynamic);
  renderDynamic();

  body.append(el("button", { class: "btn full", style: "margin-top:8px", onclick: async () => {
    const payload = { activity: activity.value || activity.placeholder || "Workout", type: type.value, date: date.value };
    if (type.value === "strength") {
      payload.exercises = exercises
        .map((ex) => ({ name: ex.name, sets: ex.sets.filter((s) => s.reps || s.weight)
          // Weight entered in lb; stored in kg.
          .map((s) => ({ reps: num(s.reps), weight: toMetric(num(s.weight), "kg") })) }))
        .filter((ex) => ex.name && ex.sets.length);
      if (!payload.exercises.length) return toast("Add at least one exercise");
    } else if (dynamic._cardio) {
      payload.duration_min = num(dynamic._cardio.dur.value) || null;
      // Distance entered in miles; stored in km.
      payload.distance_km = num(dynamic._cardio.dist.value) ? toMetric(num(dynamic._cardio.dist.value), "km") : null;
      payload.energy_kcal = num(dynamic._cardio.kcal.value) || null;
    }
    await jpost("/api/workouts", payload);
    closeSheet(); toast("Workout logged"); switchTab("workouts");
  } }, "Save workout"));
  openSheet("Log workout", body);
}
function exerciseBlock(ex, idx, onRemove) {
  const block = el("div", { class: "exblock" });
  const name = el("input", { placeholder: "Exercise name", value: ex.name });
  name.addEventListener("input", () => { ex.name = name.value; });
  block.append(el("div", { class: "row", style: "align-items:center" },
    el("div", { class: "grow" }, name),
    el("button", { class: "del", onclick: onRemove }, "✕")));
  const sets = el("div", { style: "margin-top:8px" });
  const repaintSets = () => {
    sets.innerHTML = "";
    ex.sets.forEach((s, i) => {
      const reps = el("input", { type: "number", inputmode: "numeric", placeholder: "reps", value: s.reps });
      const wt = el("input", { type: "number", inputmode: "decimal", placeholder: "lb", value: s.weight });
      reps.addEventListener("input", () => { s.reps = reps.value; });
      wt.addEventListener("input", () => { s.weight = wt.value; });
      sets.append(el("div", { class: "exset" }, el("span", { class: "setno" }, i + 1),
        el("div", { class: "grow" }, reps), el("div", { class: "grow" }, wt),
        el("button", { class: "del", onclick: () => { ex.sets.splice(i, 1); if (!ex.sets.length) ex.sets.push({ reps: "", weight: "" }); repaintSets(); } }, "✕")));
    });
  };
  repaintSets();
  block.append(sets, el("button", { class: "add-inline", onclick: () => { ex.sets.push({ reps: "", weight: "" }); repaintSets(); } }, "+ Set"));
  return block;
}

/* ============================================================
   BODY
   ============================================================ */
async function renderBody() {
  const screen = $("#screen");
  // Hidden file input for importing a smart-scale .xlsx export.
  const xlsxInput = el("input", { type: "file", accept: ".xlsx,.xlsm", hidden: true,
    onchange: () => xlsxInput.files[0] && importBodyXlsx(xlsxInput.files[0]) });
  screen.append(el("div", { class: "screen-head" },
    el("div", {}, el("h2", {}, "Body")),
    el("div", { class: "head-actions" },
      el("button", { class: "ghost-btn", title: "Import a smart-scale .xlsx export",
        onclick: () => xlsxInput.click() }, "⬆ Import xlsx"),
      el("button", { class: "btn", onclick: openBodySheet }, "+ Log")),
    xlsxInput));
  screen.append(loading());
  let data;
  try { data = await api("/api/body?days=365"); }
  catch (e) { screen.lastChild.replaceWith(el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  screen.lastChild.remove();

  if (!data.metrics.length) {
    screen.append(el("div", { class: "empty" }, "No body or vitals data yet. Tap + Log to record a measurement, import a smart-scale xlsx, or import Apple Health."));
    return;
  }
  // order: weight & body composition first, then circumferences, then vitals.
  const order = ["body_mass", "bmi", "body_fat", "fat_content", "muscle_mass",
    "muscle_mass_pct", "lean_body_mass", "skeletal_muscle", "body_water",
    "protein_pct", "bone_mass", "subcutaneous_fat", "visceral_fat", "bmr",
    "metabolic_age", "waist", "chest", "hips", "arm", "thigh",
    "resting_heart_rate", "bp_systolic", "bp_diastolic"];
  data.metrics.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
  // Lower-is-better metrics: a downward trend reads as good (green) in detail.
  const INVERT_METRICS = new Set(["body_fat", "fat_content", "visceral_fat",
    "subcutaneous_fat", "metabolic_age", "waist", "hips",
    "bp_systolic", "bp_diastolic", "resting_heart_rate"]);
  data.metrics.forEach((m) => {
    const s = m.summary;
    const u = dispUnit(m.unit);
    const { card, canvas } = chartCard("");
    card.classList.add("d-tap");
    card.addEventListener("click", () => openMetricDetail(m.key, {
      label: m.label, unit: m.unit, area: m.area, invert: INVERT_METRICS.has(m.key),
    }));
    card.prepend(el("div", { class: "card-head" },
      el("h3", { class: "chev" }, m.label),
      el("div", {}, el("span", { class: "value", style: "font-size:18px" }, fmt(disp(s.latest, m.unit).value, 1)),
        el("span", { class: "muted", style: "font-size:12px" }, " " + u + trendArrow(s.trend)))));
    screen.append(card);
    makeChart(canvas, {
      type: "line",
      data: { labels: m.series.map((r) => r.date.slice(2)),
        datasets: [lineDataset(m.label, m.series.map((r) => disp(r.value, m.unit).value), m.area === "heart" ? CORAL : TEAL)] },
      options: { scales: AXES },
    });
  });
}
function trendArrow(t) {
  if (!t) return "";
  const a = t.direction === "up" ? " ▲" : t.direction === "down" ? " ▼" : " →";
  return `${a} ${t.pct_change > 0 ? "+" : ""}${t.pct_change}%`;
}
function openBodySheet() {
  const mm = State.config.manual_metrics;
  const metric = el("select", {}, ...Object.entries(mm).map(([k, c]) => {
    const u = dispUnit(c.unit);
    return el("option", { value: k }, u ? `${c.label} (${u})` : c.label);
  }));
  const value = el("input", { type: "number", step: "any", inputmode: "decimal", placeholder: "Value" });
  const date = el("input", { type: "date", value: todayISO() });
  const body = el("div", {},
    el("div", { class: "field" }, el("label", {}, "Measurement"), metric),
    el("div", { class: "field" }, el("label", {}, "Value"), value),
    el("div", { class: "field" }, el("label", {}, "Date"), date),
    el("button", { class: "btn full", onclick: async () => {
      if (!value.value) return toast("Enter a value");
      // Value entered in display units; stored in the metric's canonical unit.
      const canonical = toMetric(num(value.value), mm[metric.value].unit);
      await jpost("/api/body", { metric: metric.value, value: canonical, date: date.value });
      closeSheet(); toast("Logged"); switchTab("body");
    } }, "Save"));
  openSheet("Log measurement", body);
}

// Upload a smart-scale .xlsx export (Renpho/Withings-style) to POST
// /api/import/body, then refresh the Body tab to show the imported series.
async function importBodyXlsx(file) {
  toast("Importing " + file.name + "…");
  const fd = new FormData();
  fd.append("file", file);
  try {
    const s = await api("/api/import/body", { method: "POST", body: fd });
    const rng = s.date_range ? ` (${s.date_range.start} → ${s.date_range.end})` : "";
    toast(`Imported ${s.dates_imported} day${s.dates_imported === 1 ? "" : "s"}${rng}`);
    switchTab("body");
  } catch (e) {
    toast("⚠ " + e.message);
  }
}

/* ============================================================
   SLEEP
   ============================================================ */
async function renderSleep() {
  const screen = $("#screen");
  screen.append(el("div", { class: "screen-head" },
    el("div", {}, el("h2", {}, "Sleep")),
    el("button", { class: "btn", onclick: openSleepSheet }, "+ Log")));
  screen.append(loading());
  let data;
  try { data = await api("/api/sleep?days=60"); }
  catch (e) { screen.lastChild.replaceWith(el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  screen.lastChild.remove();

  const s = data.summary;
  if (s.available) {
    screen.append(el("div", { class: "stat-grid" },
      statCard("😴 Avg asleep", round(s.avg_asleep_hours, 1) + "h", "last " + s.window_days + "d", null, "", openSleepDetail),
      statCard("📊 Consistency", "±" + round(s.consistency_std_hours, 1) + "h", "std dev", null, "", openSleepDetail),
      statCard("🌀 REM", s.avg_rem_hours != null ? round(s.avg_rem_hours, 1) + "h" : "—", "avg", null, "", openSleepDetail),
      statCard("💤 Deep", s.avg_deep_hours != null ? round(s.avg_deep_hours, 1) + "h" : "—", "avg", null, "", openSleepDetail)));
  }
  if (data.series.length) {
    const nights = data.series.filter((n) => n.asleep_hours > 0);
    const { card, canvas } = chartCard("Sleep stages — nightly hours");
    screen.append(card);
    const ds = (label, key, color) => ({ label, data: nights.map((n) => round(n[key], 2)),
      backgroundColor: color, borderRadius: 3, stack: "s" });
    makeChart(canvas, {
      type: "bar",
      data: { labels: nights.map((n) => n.date.slice(5)),
        datasets: [ds("Deep", "deep_hours", VIOLET), ds("Core", "core_hours", BLUE),
          ds("REM", "rem_hours", TEAL), ds("Awake", "awake_hours", "#3a4f4a")] },
      options: { plugins: { legend: { display: true, position: "bottom", labels: { boxWidth: 10 } } },
        scales: { x: AXES.x, y: { ...AXES.y, beginAtZero: true, stacked: true }, } },
    });
  } else {
    screen.append(el("div", { class: "empty" }, "No sleep data yet. Tap + Log or import Apple Health."));
  }
}
function openSleepSheet() {
  const date = el("input", { type: "date", value: todayISO() });
  const asleep = el("input", { type: "number", step: "0.25", inputmode: "decimal", placeholder: "e.g. 7.5" });
  const inbed = el("input", { type: "number", step: "0.25", inputmode: "decimal", placeholder: "optional" });
  const body = el("div", {},
    el("div", { class: "field" }, el("label", {}, "Night of (wake date)"), date),
    el("div", { class: "field" }, el("label", {}, "Hours asleep"), asleep),
    el("div", { class: "field" }, el("label", {}, "Hours in bed (optional)"), inbed),
    el("button", { class: "btn full", onclick: async () => {
      if (!asleep.value) return toast("Enter hours asleep");
      await jpost("/api/sleep", { date: date.value, asleep_hours: num(asleep.value),
        in_bed_hours: num(inbed.value) || null });
      closeSheet(); toast("Sleep logged"); switchTab("sleep");
    } }, "Save"));
  openSheet("Log sleep", body);
}

/* ============================================================
   GOALS
   ============================================================ */
async function renderGoals() {
  const screen = $("#screen");
  screen.append(el("div", { class: "screen-head" },
    el("div", {}, el("h2", {}, "Goals")),
    el("button", { class: "btn", onclick: openGoalSheet }, "+ New")));
  screen.append(loading());
  let active, all;
  try {
    [active, all] = await Promise.all([api("/api/goals?status=active"), api("/api/goals?status=all")]);
  } catch (e) { screen.lastChild.replaceWith(el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  screen.lastChild.remove();

  if (active.goals.length) {
    const card = el("div", { class: "card" });
    active.goals.forEach((g) => card.append(goalRow(g, false)));
    screen.append(card);
  } else {
    screen.append(el("div", { class: "empty" }, "No active goals. Set one and your coach will track it."));
  }

  const done = all.goals.filter((g) => g.status !== "active");
  if (done.length) {
    screen.append(el("div", { class: "section-title" }, "Past goals"));
    const card = el("div", { class: "card list" });
    done.forEach((g) => card.append(el("div", { class: "lrow" },
      el("div", { class: "l-icon" }, g.status === "done" ? "🏆" : "📦"),
      el("div", { class: "l-main" }, el("div", { class: "l-title" }, g.label),
        el("div", { class: "l-sub" }, g.status === "done" ? "Completed" : "Archived")),
      el("button", { class: "del", onclick: async () => { await jdel("/api/goals/" + g.id); switchTab("goals"); } }, "✕"))));
    screen.append(card);
  }
}
function goalRow(g, compact) {
  const p = g.progress;
  // Current/target are stored in metric; show them in US units.
  const cur = g.current != null ? disp(g.current, g.unit).value : null;
  const tgt = g.target != null ? disp(g.target, g.unit).value : null;
  const sub = (cur != null ? `${fmt(cur, 1)}` : "—") + (tgt != null ? ` / ${fmt(tgt, 1)} ${dispUnit(g.unit) || ""}` : "");
  const node = el("div", { class: "lrow", style: "border:none;padding:9px 0;flex-wrap:wrap" },
    el("div", { class: "l-main" },
      el("div", { class: "l-title" }, g.label),
      el("div", { class: "l-sub" }, sub),
      p != null ? el("div", { class: "bar " + barColor(p) }, el("span", { style: `width:${Math.min(100, p)}%` })) : null),
    el("div", { class: "l-val" }, p != null ? p + "%" : ""));
  if (!compact) {
    node.append(el("div", { class: "row", style: "width:100%;gap:8px;margin-top:6px" },
      el("button", { class: "pill", onclick: async () => { await jput("/api/goals/" + g.id, { status: "done" }); toast("Goal completed! 🏆"); switchTab("goals"); } }, "✓ Complete"),
      el("button", { class: "pill", onclick: () => openGoalSheet(g) }, "Edit"),
      el("button", { class: "pill", onclick: async () => { await jdel("/api/goals/" + g.id); switchTab("goals"); } }, "Delete")));
  }
  return node;
}
const barColor = (p) => (p >= 100 ? "" : p >= 60 ? "" : p >= 30 ? "amber" : "coral");
function openGoalSheet(existing) {
  const cats = State.config.goal_categories;
  const category = el("select", {}, ...Object.entries(cats).map(([k, c]) => el("option", { value: k }, c.label)));
  const label = el("input", { placeholder: "Goal name" });
  const target = el("input", { type: "number", step: "any", inputmode: "decimal", placeholder: "Target" });
  const baseline = el("input", { type: "number", step: "any", inputmode: "decimal", placeholder: "Starting value (optional)" });
  const direction = el("select", {}, el("option", { value: "increase" }, "Increase ▲"),
    el("option", { value: "decrease" }, "Decrease ▼"), el("option", { value: "maintain" }, "Maintain →"));
  const tdate = el("input", { type: "date" });
  // Show the target/baseline inputs in US units (e.g. lb for weight, fl oz for water).
  const unitHint = () => {
    const u = dispUnit(cats[category.value]?.unit);
    target.placeholder = u ? `Target (${u})` : "Target";
    baseline.placeholder = u ? `Start ${u} (optional)` : "Starting value (optional)";
  };
  if (existing) {
    const u = cats[existing.category]?.unit;
    category.value = existing.category; label.value = existing.label;
    target.value = existing.target != null ? round(disp(existing.target, u).value, 2) : "";
    baseline.value = existing.baseline != null ? round(disp(existing.baseline, u).value, 2) : "";
    direction.value = existing.direction; tdate.value = existing.target_date || "";
    category.disabled = true;
    unitHint();
  } else {
    const apply = () => { const c = cats[category.value];
      if (c && !label.value) label.placeholder = c.label;
      if (category.value === "weight" || category.value === "body_fat") direction.value = "decrease";
      unitHint(); };
    category.addEventListener("change", apply); apply();
  }
  const body = el("div", {},
    el("div", { class: "field" }, el("label", {}, "Category"), category),
    el("div", { class: "field" }, el("label", {}, "Name"), label),
    el("div", { class: "row" },
      el("div", { class: "field grow" }, el("label", {}, "Target"), target),
      el("div", { class: "field grow" }, el("label", {}, "Start (optional)"), baseline)),
    el("div", { class: "field" }, el("label", {}, "Direction"), direction),
    el("div", { class: "field" }, el("label", {}, "Target date (optional)"), tdate),
    el("button", { class: "btn full", onclick: async () => {
      // Target/baseline entered in US units; stored in the category's metric unit.
      const gunit = cats[category.value].unit || "";
      const payload = { category: category.value, label: label.value || cats[category.value].label,
        target: target.value === "" ? null : toMetric(num(target.value), gunit),
        baseline: baseline.value === "" ? null : toMetric(num(baseline.value), gunit),
        unit: gunit, direction: direction.value, target_date: tdate.value || null };
      if (existing) await jput("/api/goals/" + existing.id, payload);
      else await jpost("/api/goals", payload);
      closeSheet(); toast("Goal saved"); switchTab("goals");
    } }, existing ? "Save changes" : "Create goal"));
  openSheet(existing ? "Edit goal" : "New goal", body);
}

/* ============================================================
   COACH (chat)
   ============================================================ */
// In-memory mirror of the on-screen conversation. The server (chat_messages
// table) is the source of truth — this is just what's rendered, so switching
// tabs re-paints without a refetch. chatOldestId/chatHasMore drive "load earlier".
let chatHistory = [];
let chatBusy = false;
let coachLoaded = false;   // have we fetched persisted history this session?
let chatHasMore = false;   // older messages exist on the server
let chatOldestId = null;   // id of the oldest message currently loaded

function renderCoach() {
  const screen = $("#screen");
  if (!State.advisorReady) {
    screen.append(el("div", { class: "card" },
      el("h3", {}, "Coaching is offline"),
      el("p", { class: "muted", html: "Set <code>ANTHROPIC_API_KEY</code> in your <code>.env</code> and restart to enable your coach." })));
    return;
  }
  const header = el("div", { class: "chat-header" },
    el("span", { class: "chat-title" }, "Coach"),
    el("button", { class: "chat-newchat", type: "button", title: "Clear this conversation and start fresh", onclick: newChat }, "＋ New chat"));
  const log = el("div", { class: "chat-log", id: "chatLog" });
  const sugg = el("div", { class: "suggestions" });
  [["Meal ideas", "meals"], ["Next workout", "workout"], ["Recovery check", "recovery"], ["This week's focus", "focus"]]
    .forEach(([lbl, topic]) => sugg.append(el("button", { class: "pill", onclick: () => recommend(topic, lbl) }, lbl)));
  sugg.append(el("button", { class: "pill", onclick: () => sendChat("Review my recent data and revise my plan. Save it.") }, "Revise plan"));

  const input = el("input", { type: "text", autocomplete: "off", placeholder: "Ask your coach anything…" });
  const form = el("form", { class: "chat-form", onsubmit: (e) => { e.preventDefault(); const t = input.value.trim(); if (t) { input.value = ""; sendChat(t); } } },
    input, el("button", { class: "btn", type: "submit" }, "Send"));

  screen.append(header, log, sugg, form);

  if (coachLoaded) renderChatLog();   // re-paint from the in-memory mirror
  else loadChatHistory();             // first visit this session: fetch from server
}

// Fetch the persisted conversation once per session and render it (or, when
// there's nothing yet, fall back to the coach's intro/briefing).
async function loadChatHistory() {
  coachLoaded = true;
  try {
    const data = await api("/api/chat/history?limit=50");
    const msgs = data.messages || [];
    chatHistory = msgs.map((m) => ({ role: m.role, content: m.content }));
    chatHasMore = !!data.has_more;
    chatOldestId = msgs.length ? msgs[0].id : null;
  } catch (e) {
    chatHistory = []; chatHasMore = false; chatOldestId = null;
  }
  if (chatHistory.length) renderChatLog();
  else coachIntro();
}

// First-run greeting when there's no saved conversation yet.
function coachIntro() {
  const plan = State.status?.plan;
  if (plan) pushMsg("assistant", "Welcome back. Your plan is in motion — want a check-in on how you're tracking, or is something on your mind?");
  else if (State.status?.has_import) runBriefing();
  else pushMsg("assistant", "I'm your coach. Log a few days of food, workouts and sleep — or import your Apple Health data — and I'll build you a plan and start coaching.");
  scrollChat();
}

// Repaint the whole log from chatHistory. `toTop` keeps the view at the top
// after prepending older messages (otherwise we settle at the bottom).
function renderChatLog(toTop = false) {
  const log = $("#chatLog"); if (!log) return;
  log.innerHTML = "";
  if (chatHasMore) log.append(el("button", { class: "chat-earlier", type: "button", onclick: loadEarlier }, "Load earlier messages"));
  chatHistory.forEach((m) => addMsg(m.role, m.content));
  if (toTop) log.scrollTop = 0; else scrollChat();
}

async function loadEarlier() {
  if (chatBusy || !chatOldestId) return;
  try {
    const data = await api(`/api/chat/history?limit=50&before=${chatOldestId}`);
    const msgs = data.messages || [];
    if (msgs.length) {
      chatHistory = msgs.map((m) => ({ role: m.role, content: m.content })).concat(chatHistory);
      chatOldestId = msgs[0].id;
    }
    chatHasMore = !!data.has_more;
    renderChatLog(true);
  } catch (e) { /* leave the log as-is on failure */ }
}

async function newChat() {
  if (chatBusy) return;
  try { await jdel("/api/chat/history"); } catch (e) { /* clear locally regardless */ }
  chatHistory = []; chatHasMore = false; chatOldestId = null;
  const log = $("#chatLog"); if (log) log.innerHTML = "";
  coachIntro();
}

// Render a message AND mirror it into chatHistory.
function pushMsg(role, text) { chatHistory.push({ role, content: text }); return addMsg(role, text); }

function addMsg(role, text, cls = "") {
  const log = $("#chatLog"); if (!log) return null;
  const node = el("div", { class: `msg ${role} ${cls}` });
  if (role === "assistant" && !cls.includes("thinking")) node.innerHTML = marked.parse(text);
  else node.textContent = text;
  log.append(node); scrollChat(); return node;
}
function scrollChat() { const l = $("#chatLog"); if (l) l.scrollTop = l.scrollHeight; }
async function runBriefing() {
  if (chatBusy) return; chatBusy = true;
  const pending = addMsg("assistant", "Analyzing your data and building your plan", "thinking dots");
  try {
    const data = await api("/api/briefing", { method: "POST" });
    pending.className = "msg assistant"; pending.innerHTML = marked.parse(data.reply);
    chatHistory.push({ role: "assistant", content: data.reply });
    State.status.plan = data.plan;
  } catch (e) { pending.className = "msg assistant error"; pending.textContent = "⚠ " + e.message; }
  finally { chatBusy = false; scrollChat(); }
}
async function sendChat(text) {
  if (chatBusy) return; chatBusy = true;
  pushMsg("user", text);
  const pending = addMsg("assistant", "Thinking", "thinking dots");
  try {
    // Only the new turn goes up — the server reloads prior history for context.
    const data = await jpost("/api/chat", { messages: [{ role: "user", content: text }] });
    pending.className = "msg assistant"; pending.innerHTML = marked.parse(data.reply);
    chatHistory.push({ role: "assistant", content: data.reply });
    State.status.plan = data.plan;
  } catch (e) { pending.className = "msg assistant error"; pending.textContent = "⚠ " + e.message; chatHistory.pop(); }
  finally { chatBusy = false; scrollChat(); }
}
async function recommend(topic, label) {
  if (chatBusy) return; chatBusy = true;
  pushMsg("user", label);
  const pending = addMsg("assistant", "Thinking", "thinking dots");
  try {
    const data = await jpost("/api/recommend", { topic, label });
    pending.className = "msg assistant"; pending.innerHTML = marked.parse(data.reply);
    chatHistory.push({ role: "assistant", content: data.reply });
  } catch (e) { pending.className = "msg assistant error"; pending.textContent = "⚠ " + e.message; chatHistory.pop(); }
  finally { chatBusy = false; scrollChat(); }
}

/* ============================================================
   DEEP-DIVE DETAIL VIEWS
   ------------------------------------------------------------
   A single full-screen, slide-up overlay (#detail) that any tappable card
   or event drills into. openDetail() pushes a {title, sub, build} frame onto
   a small stack so nested drill-downs (weight → body-fat, workout → exercise
   history) get an intuitive back button; the X dismisses the whole thing, as
   does a swipe down on the header. Charts created inside live in their own
   registry so closing a detail never touches the tab's charts.
   ============================================================ */
const detailCharts = {};
let detailStack = [];

function makeDetailChart(canvas, config) {
  if (!window.Chart || !canvas) return;
  const c = new Chart(canvas, config);
  detailCharts[canvas.id || ("dc" + Math.random())] = c;
  return c;
}
function destroyDetailCharts() {
  for (const k of Object.keys(detailCharts)) { detailCharts[k].destroy(); delete detailCharts[k]; }
}

function wireDetail() {
  $("#detailClose").addEventListener("click", closeDetail);
  $("#detailBack").addEventListener("click", detailBack);
  $("#detail").addEventListener("click", (e) => { if (e.target.id === "detail") closeDetail(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#detail").classList.contains("hidden")) detailBack();
  });
  // Swipe the header down to dismiss.
  const head = $("#detailHead");
  const panel = () => $("#detail .detail");
  let startY = null, dy = 0, dragging = false;
  head.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".icon-btn")) return;     // let buttons work
    startY = e.clientY; dy = 0; dragging = true;
    panel().classList.add("dragging");
    try { head.setPointerCapture(e.pointerId); } catch {}
  });
  head.addEventListener("pointermove", (e) => {
    if (!dragging || startY == null) return;
    dy = Math.max(0, e.clientY - startY);
    panel().style.transform = `translateY(${dy}px)`;
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    const p = panel(); p.classList.remove("dragging"); p.style.transform = "";
    if (dy > 110) closeDetail();
    startY = null; dy = 0;
  };
  head.addEventListener("pointerup", end);
  head.addEventListener("pointercancel", end);
}
function resetDetailDrag() { const p = $("#detail .detail"); if (p) p.style.transform = ""; }

// Push a frame and render it. `build(body)` clears #detailBody and fills it.
function openDetail(title, sub, build) {
  detailStack.push({ title, sub, build });
  showDetailTop();
}
function showDetailTop() {
  destroyDetailCharts();
  const top = detailStack[detailStack.length - 1];
  if (!top) return;
  $("#detailTitle").textContent = top.title;
  $("#detailSub").textContent = top.sub || "";
  $("#detailBack").classList.toggle("hidden", detailStack.length <= 1);
  const body = $("#detailBody");
  body.innerHTML = ""; body.append(loading());
  $("#detail").classList.remove("hidden");
  resetDetailDrag(); body.scrollTop = 0;
  Promise.resolve().then(() => top.build(body)).catch((e) => {
    body.innerHTML = ""; body.append(el("div", { class: "empty" }, "⚠ " + (e.message || e)));
  });
}
function refreshDetail() { showDetailTop(); }              // re-run current frame
function detailBack() { if (detailStack.length > 1) { detailStack.pop(); showDetailTop(); } else closeDetail(); }
function closeDetail() { detailStack = []; destroyDetailCharts(); $("#detail").classList.add("hidden"); }

/* ---- detail building blocks ---- */
function dHero(value, unit, label, trend, invert) {
  return el("div", { class: "d-hero" },
    el("div", { class: "d-hero-val", html: String(value) + (unit ? ` <small>${escapeHtml(unit)}</small>` : "") }),
    label ? el("div", { class: "d-hero-lbl" }, label) : null,
    trend ? trendBadge(trend, invert, "d-hero-trend") : null);
}
function trendBadge(trend, invert, cls = "") {
  if (!trend) return null;
  const dir = trend.direction;
  const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "→";
  const good = invert ? dir === "down" : dir === "up";
  const tone = dir === "flat" ? "flat" : good ? "up" : "down";
  return el("div", { class: `delta ${tone} ${cls}` }, `${arrow} ${trend.pct_change > 0 ? "+" : ""}${trend.pct_change}%`);
}
function dStat(value, unit, label, tap) {
  return el("div", { class: "d-stat" + (tap ? " d-tap" : ""), onclick: tap || null },
    el("div", { class: "v", html: String(value) + (unit ? ` <small>${escapeHtml(unit)}</small>` : "") }),
    el("div", { class: "k" }, label));
}
function dStatsGrid(cols, ...stats) {
  const cls = cols === 2 ? " cols-2" : cols === 4 ? " cols-4" : "";
  return el("div", { class: "d-stats" + cls }, ...stats.filter(Boolean));
}
function dCard(title, ...kids) {
  return el("div", { class: "card" },
    title ? el("div", { class: "card-head" }, el("h3", {}, title)) : null, ...kids.filter(Boolean));
}
function dSection(t) { return el("div", { class: "section-title" }, t); }
function kvRow(k, v) { return el("div", { class: "kv" }, el("span", { class: "kv-k" }, k), el("span", { class: "kv-v", html: String(v) })); }

// SVG progress ring with a value in the middle.
function dRing(pctVal, color, centerTop, centerSub) {
  const r = 72, circ = 2 * Math.PI * r;
  const p = Math.min(100, Math.max(0, pctVal || 0));
  const off = circ * (1 - p / 100);
  const svg =
    `<svg viewBox="0 0 168 168" width="168" height="168" aria-hidden="true">
       <circle cx="84" cy="84" r="${r}" fill="none" stroke="#1a2b28" stroke-width="14"/>
       <circle cx="84" cy="84" r="${r}" fill="none" stroke="${color}" stroke-width="14"
         stroke-linecap="round" stroke-dasharray="${circ}" stroke-dashoffset="${off}"
         transform="rotate(-90 84 84)"/>
     </svg>`;
  return el("div", { class: "d-ring-wrap" },
    el("div", { class: "d-ring", html: svg },
      el("div", { class: "d-ring-center" },
        el("div", { class: "d-ring-num" }, centerTop),
        centerSub ? el("div", { class: "d-ring-sub" }, centerSub) : null)));
}

// Stacked P/C/F split by calorie share, with a legend.
function macroSplit(p, c, f) {
  const pc = num(p) * 4, cc = num(c) * 4, fc = num(f) * 9, tot = pc + cc + fc || 1;
  const w = (x) => round(x / tot * 100);
  const leg = (cls, label, val) => el("div", { class: "ml" }, el("span", { class: "dot " + cls }), el("span", {}, `${label} ${val}%`));
  return el("div", {},
    el("div", { class: "macro-split" },
      el("span", { class: "ms-p", style: `width:${w(pc)}%` }),
      el("span", { class: "ms-c", style: `width:${w(cc)}%` }),
      el("span", { class: "ms-f", style: `width:${w(fc)}%` })),
    el("div", { class: "macro-legend" }, leg("p", "Protein", w(pc)), leg("c", "Carbs", w(cc)), leg("f", "Fat", w(fc))));
}
// Horizontal labelled bars (top sources, sleep stages).
function distroRows(items, color = TEAL) {
  const max = Math.max(...items.map((i) => i.value), 1);
  const wrap = el("div", { class: "distro" });
  items.forEach((i) => wrap.append(el("div", { class: "distro-row" + (i.tap ? " d-tap-row" : ""), onclick: i.tap || null },
    el("div", { class: "distro-top" }, el("span", { class: "dn" }, i.name), el("span", { class: "dv" }, i.display)),
    el("div", { class: "distro-bar" }, el("span", { style: `width:${round(i.value / max * 100)}%;background:${i.color || color}` })))));
  return wrap;
}
function periodControl(options, current, onChange) {
  const seg = el("div", { class: "seg" });
  options.forEach((d) => seg.append(el("button", { class: d === current ? "active" : "", onclick: () => onChange(d) }, labelForDays(d))));
  return el("div", { class: "seg-wrap" }, seg);
}
function labelForDays(d) { return d === 7 ? "7d" : d === 30 ? "30d" : d === 90 ? "90d" : d === 365 ? "1y" : d + "d"; }
function detailChart(parent, title, config, height = "") {
  const { card, canvas } = chartCard(title, height);
  parent.append(card);
  makeDetailChart(canvas, config);
  return card;
}
function prettyUnit(unit) { return (!unit || unit === "count") ? "" : dispUnit(unit); }
function dpFor(unit) { const c = UNIT_CONV[unit]; if (c) return c.dp; return unit === "%" ? 1 : 0; }
function filterDays(series, days) {
  const c = new Date(); c.setDate(c.getDate() - days);
  const iso = c.toISOString().slice(0, 10);
  return series.filter((r) => r.date >= iso);
}
function seriesStats(vals) {
  if (!vals.length) return null;
  const sum = vals.reduce((a, b) => a + b, 0), avg = sum / vals.length;
  const sd = Math.sqrt(vals.reduce((a, b) => a + (b - avg) ** 2, 0) / vals.length);
  return { avg, min: Math.min(...vals), max: Math.max(...vals), sd, sum,
    first: vals[0], last: vals[vals.length - 1], n: vals.length };
}
const goalLineDataset = (label, value, len, color = AMBER) => ({
  label, data: Array(len).fill(value), borderColor: color, borderDash: [5, 4],
  borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0,
});
function timeOf(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// Period control + stats + line chart for one continuous metric series.
// `goal` (in display units) draws a dashed target line and swaps the "Change"
// stat for how the windowed average compares to the goal.
function metricWindowBlock(host, series, unit, label, color, periods = [30, 90, 365], dflt = 90, goal = null) {
  let cur = periods.includes(dflt) ? dflt : periods[periods.length - 1];
  const render = () => {
    destroyDetailCharts(); host.innerHTML = "";
    host.append(periodControl(periods, cur, (x) => { cur = x; render(); }));
    const s = filterDays(series, cur);
    const vals = s.map((r) => disp(r.value, unit).value);
    const st = seriesStats(vals);
    if (!st) { host.append(el("div", { class: "empty" }, "No data in this window.")); return; }
    const chg = st.last - st.first, dp = dpFor(unit);
    host.append(dStatsGrid(4,
      dStat(fmt(st.avg, dp), prettyUnit(unit), "Average"),
      dStat(fmt(st.min, dp), "", "Min"),
      dStat(fmt(st.max, dp), "", "Max"),
      goal ? dStat(round(st.avg / goal * 100), "%", "Avg vs goal")
           : dStat((chg >= 0 ? "+" : "") + fmt(chg, dp), "", "Change")));
    const ds = [lineDataset(label, vals, color)];
    if (goal) ds.push(goalLineDataset("goal", goal, s.length, AMBER));
    detailChart(host, `${label} — ${labelForDays(cur)}${goal ? " (— goal)" : ""}`, {
      type: "line",
      data: { labels: s.map((r) => r.date.slice(5)), datasets: ds },
      options: { scales: AXES, plugins: { legend: { display: false } } },
    });
  };
  render();
}

/* ---- generic metric detail (weight, steps, energy, body composition…) ---- */
async function openMetricDetail(key, opts = {}) {
  openDetail(opts.label || key, opts.sub || "", async (body) => {
    const data = await api(`/api/metric/${key}?days=365`);
    const series = data.series || [];
    body.innerHTML = "";
    if (!series.length) { body.append(el("div", { class: "empty" }, "No data recorded yet.")); return; }
    const unit = series[series.length - 1].unit || opts.unit || "";
    const latest = series[series.length - 1];
    const dl = disp(latest.value, unit);
    body.append(dHero(fmt(dl.value, dpFor(unit)), prettyUnit(unit), `latest · ${latest.date}`, data.summary?.trend, opts.invert));
    // Draw the personalized daily target as a dashed line when one exists for
    // this metric (steps, active energy, …). Goals are in canonical units, the
    // same scale the series renders in for these keys (count, kcal).
    const goalCfg = State.goals[key];
    const goalVal = goalCfg && goalCfg.target ? goalCfg.target : null;
    const host = el("div", {}); body.append(host);
    metricWindowBlock(host, series, unit, opts.label || key,
      opts.color || (opts.area === "heart" ? CORAL : TEAL),
      opts.periods || [30, 90, 365], opts.default || 90, goalVal);
  });
}

/* ---- Calories ---- */
async function openCaloriesDetail() {
  openDetail("Calories", "Energy intake", async (body) => {
    const d = await api("/api/nutrition/detail?days=90");
    const t = d.today, goal = t.kcal_goal, consumed = num(t.kcal);
    body.innerHTML = "";
    if (goal) {
      const p = pct(consumed, goal);
      body.append(dRing(p, p > 100 ? CORAL : TEAL, fmt(consumed), `of ${fmt(goal)} kcal`));
      body.append(el("div", { class: "d-hero-lbl", style: "text-align:center;margin:-4px 0 16px" },
        consumed <= goal ? `${fmt(goal - consumed)} kcal remaining` : `${fmt(consumed - goal)} kcal over goal`));
    } else {
      body.append(dHero(fmt(consumed), "kcal", "logged today", d.trend));
    }
    // Today's macro split
    body.append(dCard("Today's macros",
      macroSplit(t.protein, t.carbs, t.fat),
      dStatsGrid(3, dStat(fmt(t.protein), "g", "Protein"), dStat(fmt(t.carbs), "g", "Carbs"), dStat(fmt(t.fat), "g", "Fat"))));
    // Meal-by-meal (today)
    const mealCard = dCard("By meal");
    State.config.meals.forEach((m) => {
      const mm = d.by_meal[m];
      mealCard.append(el("div", { class: "lrow d-tap-row", onclick: () => { State.foodDate = todayISO(); closeDetail(); switchTab("food"); } },
        el("div", { class: "l-icon" }, MEAL_ICONS[m] || "🍽"),
        el("div", { class: "l-main" },
          el("div", { class: "l-title", style: "text-transform:capitalize" }, m),
          el("div", { class: "l-sub" }, mm ? `${fmt(mm.protein)}P · ${fmt(mm.carbs)}C · ${fmt(mm.fat)}F · ${mm.items} item${mm.items === 1 ? "" : "s"}` : "Nothing logged")),
        el("div", { class: "l-val" }, mm ? fmt(mm.kcal) : "0", el("small", {}, " kcal"))));
    });
    body.append(mealCard);
    // Trend with period toggle
    if (d.available) {
      const host = el("div", {}); body.append(host);
      let cur = 30;
      const render = () => {
        destroyDetailCharts(); host.innerHTML = "";
        host.append(periodControl([7, 30, 90], cur, (x) => { cur = x; render(); }));
        const s = filterDays(d.series, cur), kc = s.map((r) => num(r.kcal));
        const st = seriesStats(kc);
        host.append(dStatsGrid(3,
          dStat(st ? fmt(st.avg) : "—", "kcal", "Daily avg"),
          dStat(st ? fmt(st.min) : "—", "", "Lowest"),
          dStat(st ? fmt(st.max) : "—", "", "Highest")));
        const ds = [lineDataset("kcal", kc, TEAL)];
        if (goal) ds.push(goalLineDataset("goal", goal, s.length, AMBER));
        detailChart(host, `Calories — ${labelForDays(cur)}${goal ? " (— goal)" : ""}`, {
          type: "line", data: { labels: s.map((r) => r.date.slice(5)), datasets: ds },
          options: { scales: { ...AXES, y: { ...AXES.y, beginAtZero: true } }, plugins: { legend: { display: false } } },
        });
      };
      render();
    } else {
      body.append(el("div", { class: "empty" }, "Log meals to see your calorie trend."));
    }
  });
}

/* ---- Protein ---- */
async function openProteinDetail() {
  openDetail("Protein", "Daily intake & sources", async (body) => {
    const d = await api("/api/nutrition/detail?days=90");
    const t = d.today, goal = t.protein_goal, consumed = num(t.protein);
    body.innerHTML = "";
    if (goal) {
      const p = pct(consumed, goal);
      body.append(dRing(p, BLUE, fmt(consumed), `of ${fmt(goal)} g`));
      body.append(el("div", { class: "d-hero-lbl", style: "text-align:center;margin:-4px 0 16px" },
        consumed < goal ? `${fmt(goal - consumed)} g to go` : `Goal hit — ${fmt(consumed - goal)} g over`));
    } else {
      body.append(dHero(fmt(consumed), "g", "logged today", d.protein_trend));
    }
    // By meal
    const mealCard = dCard("Protein by meal");
    State.config.meals.forEach((m) => {
      const mm = d.by_meal[m];
      mealCard.append(el("div", { class: "lrow" },
        el("div", { class: "l-icon" }, MEAL_ICONS[m] || "🍽"),
        el("div", { class: "l-main" }, el("div", { class: "l-title", style: "text-transform:capitalize" }, m)),
        el("div", { class: "l-val" }, mm ? fmt(mm.protein) : "0", el("small", {}, " g"))));
    });
    body.append(mealCard);
    // Top protein sources
    if (d.sources_by_protein?.length) {
      const items = d.sources_by_protein.filter((s) => s.protein > 0).map((s) => ({
        name: s.name, value: s.protein, display: `${fmt(s.protein)} g · ${s.times}×`, color: BLUE,
      }));
      if (items.length) body.append(dCard("Top sources (90d)", distroRows(items, BLUE)));
    }
    // Trend
    if (d.available) {
      const host = el("div", {}); body.append(host);
      let cur = 30;
      const render = () => {
        destroyDetailCharts(); host.innerHTML = "";
        host.append(periodControl([7, 30, 90], cur, (x) => { cur = x; render(); }));
        const s = filterDays(d.series, cur), pr = s.map((r) => num(r.protein));
        const st = seriesStats(pr);
        host.append(dStatsGrid(3,
          dStat(st ? fmt(st.avg) : "—", "g", "Daily avg"),
          dStat(st ? fmt(st.min) : "—", "", "Lowest"),
          dStat(st ? fmt(st.max) : "—", "", "Highest")));
        const ds = [lineDataset("protein", pr, BLUE)];
        if (goal) ds.push(goalLineDataset("goal", goal, s.length, AMBER));
        detailChart(host, `Protein — ${labelForDays(cur)}${goal ? " (— goal)" : ""}`, {
          type: "line", data: { labels: s.map((r) => r.date.slice(5)), datasets: ds },
          options: { scales: { ...AXES, y: { ...AXES.y, beginAtZero: true } }, plugins: { legend: { display: false } } },
        });
      };
      render();
    }
  });
}

/* ---- Water ---- */
async function openWaterDetail() {
  openDetail("Water", "Hydration", async (body) => {
    const [today, ser] = await Promise.all([
      api("/api/water?date=" + todayISO()), api("/api/water/series?days=30"),
    ]);
    body.innerHTML = "";
    const goalMl = today.goal_ml, totMl = today.total_ml;
    const g = disp(goalMl, "ml"), tt = disp(totMl, "ml");
    const p = goalMl ? round(totMl / goalMl * 100) : 0;
    body.append(dRing(p, BLUE, fmt(tt.value), `of ${fmt(g.value)} fl oz`));
    body.append(el("div", { class: "d-hero-lbl", style: "text-align:center;margin:-4px 0 16px" },
      totMl < goalMl ? `${fmt(disp(goalMl - totMl, "ml").value)} fl oz to go` : "Goal reached 🎉"));
    // Today's entries with timestamps
    const card = dCard("Today's intake");
    if (today.entries.length) {
      today.entries.forEach((e) => {
        const oz = disp(e.amount_ml, "ml");
        card.append(el("div", { class: "lrow" },
          el("div", { class: "l-icon" }, "💧"),
          el("div", { class: "l-main" },
            el("div", { class: "l-title" }, fmt(oz.value) + " fl oz"),
            el("div", { class: "l-sub" }, timeOf(e.created_at))),
          el("button", { class: "del", onclick: async () => {
            await jdel("/api/water/" + e.id); refreshDetail();
            if (State.tab === "dashboard") switchTab("dashboard");
          } }, "✕")));
      });
    } else card.append(el("div", { class: "empty" }, "No water logged yet today."));
    card.append(el("button", { class: "btn full", style: "margin-top:10px", onclick: () => quickWater() }, "+ Add water"));
    body.append(card);
    // Trend + stats
    const series = ser.series || [];
    if (series.length) {
      const oz = series.map((r) => disp(r.total_ml, "ml").value);
      const st = seriesStats(oz);
      const hitDays = series.filter((r) => r.total_ml >= goalMl).length;
      body.append(dStatsGrid(3,
        dStat(fmt(st.avg), "oz", "Avg / day"),
        dStat(fmt(st.max), "oz", "Best day"),
        dStat(hitDays, "", "Goal days")));
      const ds = [lineDataset("fl oz", oz, BLUE)];
      ds.push(goalLineDataset("goal", g.value, series.length, AMBER));
      detailChart(body, "Water — last 30 days (— goal)", {
        type: "line", data: { labels: series.map((r) => r.date.slice(5)), datasets: ds },
        options: { scales: { ...AXES, y: { ...AXES.y, beginAtZero: true } }, plugins: { legend: { display: false } } },
      });
    }
  });
}

/* ---- Weight & body composition ---- */
async function openWeightDetail() {
  openDetail("Weight", "Body composition", async (body) => {
    const [w, comp] = await Promise.all([
      api("/api/metric/body_mass?days=365"), api("/api/body?days=365"),
    ]);
    const series = w.series || [];
    body.innerHTML = "";
    if (!series.length) {
      body.append(el("div", { class: "empty" }, "No weight data yet. Log one on the Body tab."));
      body.append(el("button", { class: "btn secondary full", onclick: () => { closeDetail(); switchTab("body"); } }, "Go to Body"));
      return;
    }
    const latest = series[series.length - 1];
    body.append(dHero(fmt(disp(latest.value, "kg").value, 1), "lb", `latest · ${latest.date}`, w.summary?.trend, true));
    // Composition tiles (each drills into its own metric)
    const comps = comp.metrics || [];
    const find = (k) => comps.find((m) => m.key === k);
    const tiles = [];
    const bmi = find("bmi");
    if (bmi) tiles.push(dStat(fmt(bmi.summary.latest, 1), "", "BMI", () => openMetricDetail("bmi", { label: "BMI", unit: "" })));
    const bf = find("body_fat");
    if (bf) tiles.push(dStat(fmt(bf.summary.latest, 1), "%", "Body fat", () => openMetricDetail("body_fat", { label: "Body Fat", invert: true })));
    const lbm = find("lean_body_mass");
    if (lbm) tiles.push(dStat(fmt(disp(lbm.summary.latest, "kg").value, 1), "lb", "Lean mass", () => openMetricDetail("lean_body_mass", { label: "Lean Body Mass" })));
    const mm = find("muscle_mass");
    if (mm) tiles.push(dStat(fmt(disp(mm.summary.latest, "kg").value, 1), "lb", "Muscle", () => openMetricDetail("muscle_mass", { label: "Muscle Mass" })));
    if (tiles.length) {
      body.append(dSection("Composition"));
      body.append(dStatsGrid(tiles.length === 2 ? 2 : tiles.length === 4 ? 2 : 3, ...tiles));
    }
    // Weight trend
    const host = el("div", {}); body.append(host);
    metricWindowBlock(host, series, "kg", "Weight", TEAL, [30, 90, 365], 90);
    // Jump to all body metrics
    if (comps.length > tiles.length) {
      body.append(el("button", { class: "btn secondary full", style: "margin-top:4px", onclick: () => { closeDetail(); switchTab("body"); } }, "View all body metrics"));
    }
  });
}

/* ---- Sleep ---- */
async function openSleepDetail() {
  openDetail("Sleep", "Last 60 nights", async (body) => {
    const data = await api("/api/sleep?days=60");
    const s = data.summary || {};
    const series = (data.series || []).filter((n) => n.asleep_hours > 0);
    body.innerHTML = "";
    if (!series.length) { body.append(el("div", { class: "empty" }, "No sleep data yet. Log a night or import Apple Health.")); return; }
    const last = series[series.length - 1];
    body.append(dHero(round(last.asleep_hours, 1), "h asleep", `night of ${last.date}`, s.trend));
    const sleepGoal = State.goals.sleep?.target;
    if (sleepGoal) {
      const tone = goalTone("sleep", last.asleep_hours);
      body.append(el("div", { class: "d-hero-lbl goal-note " + tone, style: "text-align:center;margin:-4px 0 16px" },
        `Goal ${fmt(sleepGoal)} h · last night ${goalPct("sleep", last.asleep_hours)}% · avg ${goalPct("sleep", s.avg_asleep_hours)}%`));
    }
    // Last night
    const eff = last.in_bed_hours ? round(last.asleep_hours / last.in_bed_hours * 100) : null;
    const stagesCard = dCard("Last night",
      dStatsGrid(3,
        dStat(round(last.asleep_hours, 1), "h", "Asleep"),
        last.in_bed_hours ? dStat(round(last.in_bed_hours, 1), "h", "In bed") : null,
        eff != null ? dStat(eff, "%", "Efficiency") : null));
    const stageItems = [["Deep", "deep_hours", VIOLET], ["Core", "core_hours", BLUE], ["REM", "rem_hours", TEAL], ["Awake", "awake_hours", "#3a4f4a"]]
      .filter(([, k]) => last[k] > 0).map(([l, k, c]) => ({ name: l, value: last[k], display: round(last[k], 1) + "h", color: c }));
    if (stageItems.length) stagesCard.append(el("div", { style: "margin-top:12px" }, distroRows(stageItems)));
    body.append(stagesCard);
    // Averages
    body.append(dStatsGrid(4,
      dStat(round(s.avg_asleep_hours, 1), "h", "Avg asleep"),
      dStat("±" + round(s.consistency_std_hours, 1), "h", "Consistency"),
      dStat(s.avg_rem_hours != null ? round(s.avg_rem_hours, 1) : "—", "h", "Avg REM"),
      dStat(s.avg_deep_hours != null ? round(s.avg_deep_hours, 1) : "—", "h", "Avg deep")));
    body.append(dStatsGrid(3,
      dStat(round(s.min_asleep_hours, 1), "h", "Shortest"),
      dStat(round(s.max_asleep_hours, 1), "h", "Longest"),
      dStat(s.nights_recorded, "", "Nights")));
    // Stacked stages
    const stk = (label, key, color) => ({ label, data: series.map((n) => round(n[key], 2)), backgroundColor: color, borderRadius: 3, stack: "s" });
    detailChart(body, "Sleep stages — nightly hours", {
      type: "bar",
      data: { labels: series.map((n) => n.date.slice(5)),
        datasets: [stk("Deep", "deep_hours", VIOLET), stk("Core", "core_hours", BLUE), stk("REM", "rem_hours", TEAL), stk("Awake", "awake_hours", "#3a4f4a")] },
      options: { plugins: { legend: { display: true, position: "bottom", labels: { boxWidth: 10 } } },
        scales: { x: AXES.x, y: { ...AXES.y, beginAtZero: true, stacked: true } } },
    }, "tall");
  });
}

/* ---- Training overview (dashboard Workouts card) ---- */
async function openWorkoutsDetail() {
  openDetail("Training", "Workouts & volume", async (body) => {
    const [data, vol] = await Promise.all([
      api("/api/workouts?days=120"), api("/api/workouts/volume?days=90"),
    ]);
    const sum = data.summary || {};
    body.innerHTML = "";
    body.append(dStatsGrid(3,
      dStat(sum.total_workouts ?? 0, "", "Last 30d"),
      dStat(vol.sessions ?? 0, "", "Lift sessions"),
      dStat(fmt(disp(vol.total_volume, "kg").value), "lb", "Volume 90d")));
    // By activity
    if (sum.by_activity?.length) {
      const card = dCard("By activity");
      sum.by_activity.forEach((a) => {
        const bits = [
          a.total_min ? round(a.total_min) + " min" : null,
          a.total_km ? round(disp(a.total_km, "km").value, 1) + " mi" : null,
          a.total_kcal ? round(a.total_kcal) + " kcal" : null,
        ].filter(Boolean);
        card.append(el("div", { class: "lrow" },
          el("div", { class: "l-main" },
            el("div", { class: "l-title" }, a.activity),
            bits.length ? el("div", { class: "l-sub" }, bits.join(" · ")) : null),
          el("div", { class: "l-val" }, a.n, el("small", {}, " ×"))));
      });
      body.append(card);
    }
    // Volume chart
    if (vol.series?.length) {
      detailChart(body, "Strength volume — 90 days", {
        type: "bar",
        data: { labels: vol.series.map((r) => r.date.slice(5)),
          datasets: [{ data: vol.series.map((r) => disp(r.volume, "kg").value), backgroundColor: VIOLET + "cc", borderRadius: 5 }] },
        options: { scales: { ...AXES, y: { ...AXES.y, beginAtZero: true } }, plugins: { legend: { display: false } } },
      });
    }
    // Top exercises → exercise history
    if (vol.by_exercise?.length) {
      const card = dCard("Top exercises");
      vol.by_exercise.slice(0, 8).forEach((e) => card.append(el("div", { class: "lrow d-tap-row", onclick: () => openExerciseDetail(e.name) },
        el("div", { class: "l-icon" }, "🏋"),
        el("div", { class: "l-main" }, el("div", { class: "l-title chev" }, e.name)),
        el("div", { class: "l-val" }, fmt(disp(e.volume, "kg").value), el("small", {}, " lb")))));
      body.append(card);
    }
    // Recent workouts → single workout detail
    if (data.workouts?.length) {
      const card = dCard("Recent workouts");
      data.workouts.slice(0, 15).forEach((w) => card.append(workoutDetailRow(w)));
      body.append(card);
    }
  });
}
function workoutDetailRow(w) {
  const bits = [];
  if (w.duration_min) bits.push(round(w.duration_min) + " min");
  if (w.distance_km) bits.push(round(disp(w.distance_km, "km").value, 1) + " mi");
  if (w.energy_kcal) bits.push(round(w.energy_kcal) + " kcal");
  if (w.exercises?.length) bits.push(w.exercises.length + " exercises");
  return el("div", { class: "lrow d-tap-row", onclick: () => openWorkoutDetail(w) },
    el("div", { class: "l-icon" }, WORKOUT_ICONS[w.type] || "🤸"),
    el("div", { class: "l-main" },
      el("div", { class: "l-title chev" }, w.activity),
      el("div", { class: "l-sub" }, `${w.date}${bits.length ? " · " + bits.join(" · ") : ""}`)),
    el("span", { class: "tag " + w.type }, w.type));
}

/* ---- Single workout ---- */
function openWorkoutDetail(w) {
  openDetail(w.activity, `${w.type} · ${w.date}`, async (body) => {
    body.innerHTML = "";
    // Headline metrics
    const tiles = [];
    if (w.duration_min) tiles.push(dStat(round(w.duration_min), "min", "Duration"));
    if (w.distance_km) {
      const mi = disp(w.distance_km, "km").value;
      tiles.push(dStat(round(mi, 2), "mi", "Distance"));
      if (w.duration_min && mi) tiles.push(dStat(paceStr(w.duration_min / mi), "/mi", "Pace"));
    }
    if (w.energy_kcal) tiles.push(dStat(round(w.energy_kcal), "kcal", "Energy"));
    if (tiles.length) body.append(dStatsGrid(tiles.length % 2 === 0 ? 2 : 3, ...tiles));
    // Strength exercises
    if (w.exercises?.length) {
      let totVol = 0;
      w.exercises.forEach((ex) => (ex.sets || []).forEach((s) => { totVol += num(s.reps) * (num(s.weight) || 0); }));
      body.append(dStatsGrid(2,
        dStat(w.exercises.length, "", "Exercises"),
        dStat(fmt(disp(totVol, "kg").value), "lb", "Total volume")));
      w.exercises.forEach((ex) => {
        const card = dCard(null);
        card.append(el("div", { class: "card-head" },
          el("h3", {}, ex.name || "Exercise"),
          el("a", { class: "link text-btn", onclick: () => openExerciseDetail(ex.name) }, "History ›")));
        const tb = el("tbody", {});
        (ex.sets || []).forEach((s, i) => {
          const wlb = disp(num(s.weight), "kg").value;
          tb.append(el("tr", {},
            el("td", { class: "setn" }, i + 1),
            el("td", { class: "num" }, fmt(num(s.reps))),
            el("td", { class: "num" }, num(s.weight) ? fmt(wlb, 1) + " lb" : "—"),
            el("td", {}, num(s.weight) ? fmt(num(s.reps) * wlb) : "—")));
        });
        card.append(el("table", { class: "sets-table" },
          el("thead", {}, el("tr", {}, el("th", {}, "Set"), el("th", {}, "Reps"), el("th", {}, "Weight"), el("th", {}, "Volume"))),
          tb));
        body.append(card);
      });
    }
    if (w.notes) body.append(dCard("Notes", el("p", { class: "muted", style: "margin:0" }, w.notes)));
    if (w.source === "manual") {
      body.append(el("button", { class: "btn danger full", style: "margin-top:8px", onclick: async () => {
        await jdel("/api/workouts/" + w.id); closeDetail();
        if (State.tab === "workouts") switchTab("workouts"); toast("Workout deleted");
      } }, "Delete workout"));
    } else {
      body.append(el("p", { class: "muted center", style: "font-size:13px;margin-top:12px" }, "Imported from Apple Health"));
    }
  });
}
function paceStr(minPerMi) {
  if (!isFinite(minPerMi) || minPerMi <= 0) return "—";
  const m = Math.floor(minPerMi), sec = Math.round((minPerMi - m) * 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

/* ---- Exercise history (strength progression) ---- */
async function openExerciseDetail(name) {
  openDetail(name, "Exercise history", async (body) => {
    const data = await api("/api/workouts/exercise?name=" + encodeURIComponent(name) + "&days=365");
    const sess = data.sessions || [];
    body.innerHTML = "";
    if (!sess.length) { body.append(el("div", { class: "empty" }, "No history for this exercise yet.")); return; }
    const best = sess.reduce((a, b) => (b.top_weight > a.top_weight ? b : a));
    const bestE = sess.reduce((a, b) => (b.e1rm > a.e1rm ? b : a));
    body.append(dStatsGrid(3,
      dStat(fmt(disp(best.top_weight, "kg").value, 1), "lb", "Top set"),
      dStat(fmt(disp(bestE.e1rm, "kg").value, 1), "lb", "Best e1RM"),
      dStat(sess.length, "", "Sessions")));
    detailChart(body, "Estimated 1RM progression", {
      type: "line",
      data: { labels: sess.map((s) => s.date.slice(5)), datasets: [lineDataset("e1RM", sess.map((s) => disp(s.e1rm, "kg").value), VIOLET)] },
      options: { scales: AXES, plugins: { legend: { display: false } } },
    });
    detailChart(body, "Volume per session", {
      type: "bar",
      data: { labels: sess.map((s) => s.date.slice(5)), datasets: [{ data: sess.map((s) => disp(s.volume, "kg").value), backgroundColor: VIOLET + "cc", borderRadius: 4 }] },
      options: { scales: { ...AXES, y: { ...AXES.y, beginAtZero: true } }, plugins: { legend: { display: false } } },
    });
    const card = dCard("Sessions");
    [...sess].reverse().forEach((s) => card.append(el("div", { class: "lrow" },
      el("div", { class: "l-main" },
        el("div", { class: "l-title" }, s.date),
        el("div", { class: "l-sub" }, `${s.sets} sets · top ${fmt(disp(s.top_weight, "kg").value, 1)} lb ×${s.top_reps}`)),
      el("div", { class: "l-val" }, fmt(disp(s.volume, "kg").value), el("small", {}, " lb")))));
    body.append(card);
  });
}

/* ---- Food log entry ---- */
function openFoodEntryDetail(e) {
  openDetail(e.name, `${MEAL_ICONS[e.meal] || ""} ${e.meal} · ${e.date || State.foodDate}`, async (body) => {
    body.innerHTML = "";
    body.append(dHero(fmt(e.kcal), "kcal",
      (e.qty !== 1 ? `${round(e.qty, 2)} × ` : "") + (servingUS(e.serving) || "1 serving")));
    body.append(dCard("Macros",
      macroSplit(e.protein, e.carbs, e.fat),
      dStatsGrid(3, dStat(fmt(e.protein), "g", "Protein"), dStat(fmt(e.carbs), "g", "Carbs"), dStat(fmt(e.fat), "g", "Fat"))));
    const kv = el("div", { class: "kv-list" },
      kvRow("Calories", fmt(e.kcal) + " kcal" + dailyContribHtml("calories", e.kcal)),
      kvRow("Protein", `${fmt(e.protein)} g · ${round(num(e.protein) * 4)} kcal` + dailyContribHtml("protein", e.protein)),
      kvRow("Carbs", `${fmt(e.carbs)} g · ${round(num(e.carbs) * 4)} kcal` + dailyContribHtml("carbs", e.carbs)),
      kvRow("Fat", `${fmt(e.fat)} g · ${round(num(e.fat) * 9)} kcal` + dailyContribHtml("fat", e.fat)));
    if (e.fiber != null) kv.append(kvRow("Fiber", fmt(e.fiber, 1) + " g" + dailyContribHtml("fiber", e.fiber)));
    if (e.sugar != null) kv.append(kvRow("Sugar", fmt(e.sugar, 1) + " g" + dailyContribHtml("sugar", e.sugar)));
    if (e.sodium != null) kv.append(kvRow("Sodium", fmt(e.sodium) + " mg" + dailyContribHtml("sodium", e.sodium)));
    kv.append(kvRow("Serving", servingUS(e.serving) || "1 serving"));
    kv.append(kvRow("Quantity", round(e.qty, 2) + "×"));
    body.append(dCard("Nutrition", kv));

    // Meal selector — tap a chip to reassign this entry, re-rendering in place.
    const mealCard = dCard("Meal");
    const chips = el("div", { class: "meal-chips" });
    State.config.meals.forEach((meal) => {
      chips.append(el("button", {
        class: "meal-chip" + (meal === e.meal ? " active" : ""),
        onclick: () => moveFood(e, meal, () => openFoodEntryDetail(e)),
      }, `${MEAL_ICONS[meal] || ""} ${meal}`));
    });
    mealCard.append(chips);
    body.append(mealCard);

    body.append(el("button", { class: "btn danger full", style: "margin-top:6px", onclick: async () => {
      await jdel("/api/food/" + e.id); closeDetail(); switchTab("food"); toast("Deleted " + e.name);
    } }, "Delete entry"));
  });
}

/* ============================================================
   Push notifications & settings
   ------------------------------------------------------------
   Registers the service worker (making the app installable and able to
   receive web push), manages this device's push subscription, and renders
   the Settings sheet where the user enables push, tunes each reminder's
   time, and sets quiet hours. Reminder *preferences* are server-side and
   shared across devices; the push *subscription* is per-device.
   ============================================================ */
let swReg = null;          // active ServiceWorkerRegistration (or null)
let vapidKey = null;       // cached base64url VAPID public key

const pushSupported = () =>
  "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    swReg = await navigator.serviceWorker.register("/sw.js");
  } catch (e) {
    console.warn("Service worker registration failed:", e);
  }
}

function wireSettings() {
  const btn = $("#settingsBtn");
  if (btn) btn.addEventListener("click", openSettings);
}

// One-time, unobtrusive prompt to enable reminders on first run.
function maybePromptNotifications() {
  if (!pushSupported() || !State.status?.has_data) return;
  if (Notification.permission !== "default") return;          // already decided
  if (localStorage.getItem("notifPrompted")) return;          // asked before
  localStorage.setItem("notifPrompted", "1");
  const body = el("div", { class: "settings" },
    el("p", { class: "muted" },
      "Asclepius can send gentle reminders to log meals and water, train, wind " +
      "down for sleep, and check in with your coach — only when you're behind, " +
      "never during quiet hours."),
    el("div", { class: "settings-actions" },
      el("button", { class: "btn", onclick: async () => { closeSheet(); await enablePushFlow(); } }, "Enable reminders"),
      el("button", { class: "btn secondary", onclick: closeSheet }, "Not now")));
  openSheet("Stay on track 🔔", body);
}

const urlB64ToUint8Array = (base64) => {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
};

async function getVapidKey() {
  if (vapidKey) return vapidKey;
  const data = await api("/api/push/vapid");
  if (!data.enabled || !data.public_key) throw new Error("Push isn't configured on the server.");
  vapidKey = data.public_key;
  return vapidKey;
}

async function currentSubscription() {
  if (!swReg) swReg = await navigator.serviceWorker.ready.catch(() => null);
  if (!swReg) return null;
  return swReg.pushManager.getSubscription();
}

// Request permission, subscribe this browser, and register it with the server.
async function enablePushFlow() {
  if (!pushSupported()) { toast("This browser can't show notifications."); return false; }
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { toast(perm === "denied" ? "Notifications are blocked in your browser settings." : "Notifications not enabled."); return false; }
    if (!swReg) swReg = await navigator.serviceWorker.ready;
    const key = await getVapidKey();
    let sub = await swReg.pushManager.getSubscription();
    if (!sub) {
      sub = await swReg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlB64ToUint8Array(key),
      });
    }
    await jpost("/api/push/subscribe", { subscription: sub.toJSON(), user_agent: navigator.userAgent });
    toast("Reminders enabled 🔔");
    return true;
  } catch (e) {
    toast(e.message || "Couldn't enable notifications.");
    return false;
  }
}

async function disablePushFlow() {
  try {
    const sub = await currentSubscription();
    if (sub) {
      await jpost("/api/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
      await sub.unsubscribe().catch(() => {});
    }
    toast("Reminders turned off on this device.");
  } catch (e) { /* best effort */ }
}

/* ---- Settings sheet ---------------------------------------------------- */
// A styled on/off switch wrapping a checkbox.
function toggle(checked, onchange) {
  const input = el("input", { type: "checkbox" });
  input.checked = !!checked;
  input.addEventListener("change", () => onchange(input.checked));
  return el("label", { class: "switch" }, input, el("span", { class: "track" }));
}

async function openSettings() {
  const body = el("div", { class: "settings" }, loading("Loading settings…"));
  openSheet("Settings", body);
  // Daily goals always come first and don't depend on push support.
  const goals = await loadGoals();
  body.innerHTML = "";
  renderDailyGoals(body, goals);

  if (!pushSupported()) {
    body.append(el("p", { class: "muted", style: "margin-top:18px" },
      "This browser doesn't support web push notifications. Install Asclepius to " +
      "your home screen (Share → Add to Home Screen) and open it from there to enable them."));
    return;
  }
  let prefs, vapid;
  try {
    [prefs, vapid] = await Promise.all([api("/api/push/prefs"), api("/api/push/vapid")]);
  } catch (e) {
    body.append(el("p", { class: "muted", style: "margin-top:18px" }, "Couldn't load reminder settings: " + e.message));
    return;
  }
  const sub = await currentSubscription();
  renderSettings(body, prefs, vapid, !!sub);
}

/* ---- Daily goals editor ---- */
function renderDailyGoals(body, goals) {
  body.append(el("h4", { class: "settings-head" }, "Daily goals"));
  body.append(el("p", { class: "settings-desc", style: "margin: 0 2px 10px" },
    "Personalized targets every card measures against. Edit any to fit your plan; clear a field to reset to recommended."));
  const group = el("div", { class: "settings-group" });
  ["calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium",
   "water", "steps", "active_energy", "sleep"].forEach((key) => {
    const g = goals[key];
    if (g) group.append(goalEditRow(key, g));
  });
  body.append(group);
}

function goalEditRow(key, g) {
  const isWater = g.unit === "ml";                 // stored ml, edited in fl oz
  const unitLabel = isWater ? "fl oz" : (key === "calories" ? "kcal" : (g.unit || ""));
  const toDisplay = (v) => isWater ? round(disp(v, "ml").value) : round(v, key === "sleep" ? 1 : 0);
  const input = el("input", { class: "goal-input", type: "number", step: "any",
    inputmode: "decimal", value: toDisplay(g.target) });
  const recommended = el("div", { class: "settings-desc" },
    g.customized ? `Recommended ${fmt(toDisplay(g.default))} ${unitLabel}` : "Recommended for you");
  const save = async () => {
    const raw = input.value.trim();
    let payload;
    if (raw === "") { payload = null; }            // reset to default
    else { let v = num(raw); if (isWater) v = round(toMetric(v, "ml")); payload = v; }
    try {
      const res = await jput("/api/daily-goals", { goals: { [key]: payload } });
      State.goals = res.goals;
      const ng = State.goals[key];
      input.value = toDisplay(ng.target);
      recommended.textContent = ng.customized ? `Recommended ${fmt(toDisplay(ng.default))} ${unitLabel}` : "Recommended for you";
      toast(g.label + " goal saved");
      if (State.tab === "dashboard" || State.tab === "food") switchTab(State.tab);
    } catch (e) { toast("⚠ " + e.message); }
  };
  input.addEventListener("change", save);
  return el("div", { class: "settings-row goal-row" },
    el("div", {},
      el("div", { class: "settings-label" }, g.label + (g.lower_better ? " (max)" : "")),
      recommended),
    el("div", { class: "goal-input-wrap" }, input, el("span", { class: "goal-unit" }, unitLabel)));
}

function renderSettings(body, prefs, vapid, subscribed) {
  // (Daily goals are already rendered above by openSettings; append below them.)
  const serverOff = !vapid.enabled;

  // ---- This device --------------------------------------------------------
  const deviceCard = el("div", { class: "settings-group" },
    el("div", { class: "settings-row" },
      el("div", {},
        el("div", { class: "settings-label" }, "Push on this device"),
        el("div", { class: "settings-desc" },
          serverOff ? "Server has no VAPID key — push is disabled."
            : Notification.permission === "denied" ? "Blocked in your browser settings."
              : subscribed ? "Enabled — this device will receive reminders."
                : "Off — turn on to receive reminders here.")),
      serverOff ? null : toggle(subscribed, async (on) => {
        if (on) await enablePushFlow(); else await disablePushFlow();
        openSettings();   // re-read fresh state into the sheet
      })));
  if (!serverOff && subscribed) {
    deviceCard.append(el("div", { class: "settings-actions" },
      el("button", { class: "btn secondary", onclick: async (e) => {
        const b = e.target; b.disabled = true; b.textContent = "Sending…";
        try { await jpost("/api/push/send", {}); toast("Test sent — check your notifications."); }
        catch (err) { toast(err.message); }
        finally { b.disabled = false; b.textContent = "Send test notification"; }
      } }, "Send test notification")));
  }
  body.append(el("h4", { class: "settings-head" }, "This device"), deviceCard);

  if (serverOff) return;   // nothing below matters without push configured

  // Live PUT of a preferences patch.
  const save = async (patch) => {
    try { await jput("/api/push/prefs", patch); }
    catch (e) { toast("Couldn't save: " + e.message); }
  };

  // ---- Reminders ----------------------------------------------------------
  body.append(el("h4", { class: "settings-head" }, "Reminders"));
  const typesBox = el("div", { class: "settings-group" + (prefs.enabled ? "" : " dimmed") });
  body.append(el("div", { class: "settings-group" },
    el("div", { class: "settings-row" },
      el("div", {},
        el("div", { class: "settings-label" }, "All reminders"),
        el("div", { class: "settings-desc" }, "Master switch — pause every reminder at once.")),
      toggle(prefs.enabled, (on) => { prefs.enabled = on; save({ enabled: on }); typesBox.classList.toggle("dimmed", !on); }))));

  prefs.types.forEach((t) => {
    const timeInputs = el("div", { class: "settings-times" });
    if (t.editable_time && t.time != null) {
      const ti = el("input", { class: "time-input", type: "time", value: t.time });
      ti.addEventListener("change", () => save({ types: { [t.key]: { time: ti.value } } }));
      timeInputs.append(t.has_weekend ? el("label", { class: "time-lbl" }, "Weekday", ti) : ti);
    }
    if (t.has_weekend && t.time_weekend != null) {
      const we = el("input", { class: "time-input", type: "time", value: t.time_weekend });
      we.addEventListener("change", () => save({ types: { [t.key]: { time_weekend: we.value } } }));
      timeInputs.append(el("label", { class: "time-lbl" }, "Weekend", we));
    }
    const row = el("div", { class: "settings-row stacked" },
      el("div", { class: "settings-row" },
        el("div", {},
          el("div", { class: "settings-label" }, t.label),
          el("div", { class: "settings-desc" }, t.desc)),
        toggle(t.enabled, (on) => { t.enabled = on; save({ types: { [t.key]: { enabled: on } } }); row.classList.toggle("off", !on); })),
      timeInputs);
    if (!t.enabled) row.classList.add("off");
    typesBox.append(row);
  });
  body.append(typesBox);

  // ---- Quiet hours --------------------------------------------------------
  body.append(el("h4", { class: "settings-head" }, "Quiet hours"));
  const dndStart = el("input", { class: "time-input", type: "time", value: prefs.dnd_start });
  const dndEnd = el("input", { class: "time-input", type: "time", value: prefs.dnd_end });
  dndStart.addEventListener("change", () => save({ dnd_start: dndStart.value }));
  dndEnd.addEventListener("change", () => save({ dnd_end: dndEnd.value }));
  body.append(el("div", { class: "settings-group" },
    el("div", { class: "settings-row" },
      el("div", { class: "settings-desc" }, "No notifications are sent during this window."),
      el("div", { class: "settings-times" },
        el("label", { class: "time-lbl" }, "From", dndStart),
        el("label", { class: "time-lbl" }, "To", dndEnd)))));
}
