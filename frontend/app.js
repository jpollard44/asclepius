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
  wireTabs();
  try {
    const status = await api("/api/status");
    State.status = status;
    State.config = status.config || State.config;
    State.advisorReady = status.advisor_ready;
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
function openSheet(title, bodyNode) {
  $("#sheetTitle").textContent = title;
  const body = $("#sheetBody");
  body.innerHTML = "";
  body.append(bodyNode);
  $("#sheet").classList.remove("hidden");
}
function closeSheet() { $("#sheet").classList.add("hidden"); }

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
  const grid = el("div", { class: "stat-grid" });
  grid.append(
    statCard("🔥 Calories", n.kcal ? fmt(n.kcal) : "—", n.kcal_goal ? `of ${fmt(n.kcal_goal)} kcal` : "logged today",
      n.kcal_goal ? pct(n.kcal, n.kcal_goal) : null),
    statCard("💪 Protein", n.protein ? fmt(n.protein) + "g" : "—", n.protein_goal ? `of ${fmt(n.protein_goal)}g` : "today",
      n.protein_goal ? pct(n.protein, n.protein_goal) : null, "blue"),
    statCard("💧 Water", fmt(w.total_ml) + "ml", `of ${fmt(w.goal_ml)}ml`, w.pct, "blue"),
    statCard("👟 Steps", d.steps_today != null ? fmt(d.steps_today) : "—", "today"),
    statCard("⚡ Active energy", d.active_energy_today != null ? fmt(d.active_energy_today) + " kcal" : "—", "today"),
    statCard("⚖️ Weight", d.weight ? fmt(d.weight.value, 1) + " kg" : "—", d.weight ? d.weight.date : "no data"),
    statCard("😴 Sleep", d.sleep_last ? round(d.sleep_last.asleep_hours, 1) + "h" : "—", d.sleep_last ? "last night" : "no data"),
    statCard("🏋 Workouts", d.workouts_week, "this week"));
  screen.append(grid);

  // Streaks
  const s = d.streaks;
  screen.append(el("div", { class: "card" },
    el("div", { class: "card-head" }, el("h3", {}, "Streaks")),
    el("div", { class: "streaks" },
      streakBox("🔥", s.food, "Food log"),
      streakBox("⚡", s.workout, "Workouts"),
      streakBox("💧", s.water, "Water goal"))));

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
function statCard(label, value, sub, pctVal, color = "") {
  const node = el("div", { class: "stat" },
    el("div", { class: "label" }, label),
    el("div", { class: "value", html: String(value) }),
    sub ? el("div", { class: "sub" }, sub) : null);
  if (pctVal != null) node.append(el("div", { class: "bar " + color }, el("span", { style: `width:${Math.min(100, pctVal)}%` })));
  return node;
}
function streakBox(icon, n, lbl) {
  return el("div", { class: "streak" },
    el("div", { class: "s-num" }, el("span", { class: "flame" }, n > 0 ? icon : "·"), " " + n),
    el("div", { class: "s-lbl" }, lbl));
}
const pct = (v, goal) => goal ? round((num(v) / goal) * 100) : 0;

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

  let log, nutrition;
  try {
    [log, nutrition] = await Promise.all([
      api("/api/food?date=" + State.foodDate),
      api("/api/nutrition?days=30"),
    ]);
  } catch (e) { screen.lastChild.replaceWith(el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  screen.lastChild.remove();

  // Totals card with macro split
  const t = log.totals;
  screen.append(el("div", { class: "card" },
    el("div", { class: "ring-wrap" },
      el("div", {}, el("div", { class: "value", style: "font-size:30px;font-weight:800" }, fmt(t.kcal)),
        el("div", { class: "muted", style: "font-size:13px" }, "calories today")),
      el("div", { class: "grow macros" },
        macroBox("p", "Protein", t.protein),
        macroBox("c", "Carbs", t.carbs),
        macroBox("f", "Fat", t.fat)))));

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
function macroBox(cls, lbl, val) {
  return el("div", { class: "macro " + cls },
    el("div", { class: "m-val" }, fmt(val) + "g"), el("div", { class: "m-lbl" }, lbl));
}
function foodEntryRow(e) {
  return el("div", { class: "lrow" },
    el("div", { class: "l-main" },
      el("div", { class: "l-title" }, e.name + (e.qty !== 1 ? ` ×${round(e.qty, 2)}` : "")),
      el("div", { class: "l-sub" }, `${fmt(e.protein)}P · ${fmt(e.carbs)}C · ${fmt(e.fat)}F`)),
    el("div", { class: "l-val" }, fmt(e.kcal), el("small", {}, " kcal")),
    el("button", { class: "del", onclick: async () => { await jdel("/api/food/" + e.id); switchTab("food"); } }, "✕"));
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
  const customBtn = el("button", { class: "btn secondary full", style: "margin-top:12px",
    onclick: () => openCustomFood(meal) }, "+ Create custom food");
  body.append(el("div", { class: "field" }, search), results, customBtn);
  openSheet(`Add to ${meal}`, body);

  const run = async (q) => {
    const { foods } = await api("/api/foods?q=" + encodeURIComponent(q));
    results.innerHTML = "";
    foods.forEach((f) => results.append(
      el("div", { class: "food-result", onclick: () => openFoodQty(f, meal) },
        el("div", { class: "fr-main" },
          el("div", { class: "fr-name" }, f.name),
          el("div", { class: "fr-sub" }, `${f.serving || "1 serving"} · ${fmt(f.protein)}P ${fmt(f.carbs)}C ${fmt(f.fat)}F`)),
        el("div", { class: "fr-kcal" }, fmt(f.kcal)))));
    if (!foods.length) results.append(el("div", { class: "empty" }, "No matches — create a custom food."));
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
    el("p", { class: "muted", style: "margin-top:0" }, `${food.name} — ${food.serving || "per serving"}`),
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
async function quickWater() {
  const body = el("div", {});
  const row = el("div", { class: "row wrap" });
  [250, 500, 750, 1000].forEach((ml) =>
    row.append(el("button", { class: "pill", onclick: async () => {
      await jpost("/api/water", { amount_ml: ml }); closeSheet(); toast(`+${ml}ml water`);
      if (State.tab === "dashboard") switchTab("dashboard");
    } }, `+${ml}ml`)));
  const custom = el("input", { type: "number", placeholder: "Custom ml", inputmode: "numeric" });
  body.append(el("p", { class: "muted", style: "margin-top:0" }, "Quick add"), row,
    el("div", { class: "field", style: "margin-top:14px" }, custom),
    el("button", { class: "btn full", onclick: async () => {
      if (!num(custom.value)) return; await jpost("/api/water", { amount_ml: num(custom.value) });
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

  // Volume chart
  if (vol.series.length) {
    const { card, canvas } = chartCard(`Strength volume — 30 days (${fmt(vol.total_volume)} total, ${vol.sessions} sessions)`);
    screen.append(card);
    makeChart(canvas, {
      type: "bar",
      data: { labels: vol.series.map((r) => r.date.slice(5)),
        datasets: [{ data: vol.series.map((r) => r.volume), backgroundColor: VIOLET + "cc", borderRadius: 5 }] },
      options: { scales: { ...AXES, y: { ...AXES.y, beginAtZero: true } } },
    });
  }

  // PRs
  if (prs.records.length) {
    const card = el("div", { class: "card" }, el("div", { class: "card-head" }, el("h3", {}, "Personal records")));
    const list = el("div", { class: "list" });
    prs.records.slice(0, 8).forEach((r) => list.append(
      el("div", { class: "lrow" },
        el("div", { class: "l-icon" }, "📈"),
        el("div", { class: "l-main" }, el("div", { class: "l-title" }, r.name),
          el("div", { class: "l-sub" }, `est. 1RM ${fmt(r.e1rm, 1)} · ${r.date}`)),
        el("div", { class: "l-val" }, fmt(r.weight, 1), el("small", {}, " ×" + fmt(r.reps))))));
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
  if (w.distance_km) bits.push(round(w.distance_km, 1) + " km");
  if (w.energy_kcal) bits.push(round(w.energy_kcal) + " kcal");
  if (w.exercises?.length) bits.push(w.exercises.length + " exercises");
  const row = el("div", { class: "lrow" },
    el("div", { class: "l-icon" }, WORKOUT_ICONS[w.type] || "🤸"),
    el("div", { class: "l-main" },
      el("div", { class: "l-title" }, w.activity, " ", el("span", { class: "tag " + w.type }, w.type)),
      el("div", { class: "l-sub" }, `${w.date}${bits.length ? " · " + bits.join(" · ") : ""}`)),
    w.source === "manual"
      ? el("button", { class: "del", onclick: async () => { await jdel("/api/workouts/" + w.id); switchTab("workouts"); } }, "✕")
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
      const dist = el("input", { type: "number", inputmode: "decimal", placeholder: "km" });
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
          .map((s) => ({ reps: num(s.reps), weight: num(s.weight) })) }))
        .filter((ex) => ex.name && ex.sets.length);
      if (!payload.exercises.length) return toast("Add at least one exercise");
    } else if (dynamic._cardio) {
      payload.duration_min = num(dynamic._cardio.dur.value) || null;
      payload.distance_km = num(dynamic._cardio.dist.value) || null;
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
      const wt = el("input", { type: "number", inputmode: "decimal", placeholder: "kg", value: s.weight });
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
  screen.append(el("div", { class: "screen-head" },
    el("div", {}, el("h2", {}, "Body")),
    el("button", { class: "btn", onclick: openBodySheet }, "+ Log")));
  screen.append(loading());
  let data;
  try { data = await api("/api/body?days=365"); }
  catch (e) { screen.lastChild.replaceWith(el("div", { class: "empty" }, "⚠ " + e.message)); return; }
  screen.lastChild.remove();

  if (!data.metrics.length) {
    screen.append(el("div", { class: "empty" }, "No body or vitals data yet. Tap + Log to record a measurement, or import Apple Health."));
    return;
  }
  // order: weight & body comp first
  const order = ["body_mass", "body_fat", "lean_body_mass", "waist", "chest", "hips", "arm", "thigh", "resting_heart_rate", "bp_systolic", "bp_diastolic"];
  data.metrics.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
  data.metrics.forEach((m) => {
    const s = m.summary;
    const { card, canvas } = chartCard("");
    card.prepend(el("div", { class: "card-head" },
      el("h3", {}, m.label),
      el("div", {}, el("span", { class: "value", style: "font-size:18px" }, fmt(s.latest, 1)),
        el("span", { class: "muted", style: "font-size:12px" }, " " + m.unit + trendArrow(s.trend)))));
    screen.append(card);
    makeChart(canvas, {
      type: "line",
      data: { labels: m.series.map((r) => r.date.slice(2)),
        datasets: [lineDataset(m.label, m.series.map((r) => r.value), m.area === "heart" ? CORAL : TEAL)] },
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
  const metric = el("select", {}, ...Object.entries(mm).map(([k, c]) => el("option", { value: k }, `${c.label} (${c.unit})`)));
  const value = el("input", { type: "number", step: "any", inputmode: "decimal", placeholder: "Value" });
  const date = el("input", { type: "date", value: todayISO() });
  const body = el("div", {},
    el("div", { class: "field" }, el("label", {}, "Measurement"), metric),
    el("div", { class: "field" }, el("label", {}, "Value"), value),
    el("div", { class: "field" }, el("label", {}, "Date"), date),
    el("button", { class: "btn full", onclick: async () => {
      if (!value.value) return toast("Enter a value");
      await jpost("/api/body", { metric: metric.value, value: num(value.value), date: date.value });
      closeSheet(); toast("Logged"); switchTab("body");
    } }, "Save"));
  openSheet("Log measurement", body);
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
      statCard("😴 Avg asleep", round(s.avg_asleep_hours, 1) + "h", "last " + s.window_days + "d"),
      statCard("📊 Consistency", "±" + round(s.consistency_std_hours, 1) + "h", "std dev"),
      statCard("🌀 REM", s.avg_rem_hours != null ? round(s.avg_rem_hours, 1) + "h" : "—", "avg"),
      statCard("💤 Deep", s.avg_deep_hours != null ? round(s.avg_deep_hours, 1) + "h" : "—", "avg")));
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
  const cur = g.current, tgt = g.target;
  const p = g.progress;
  const sub = (cur != null ? `${fmt(cur, 1)}` : "—") + (tgt != null ? ` / ${fmt(tgt, 1)} ${g.unit || ""}` : "");
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
  if (existing) {
    category.value = existing.category; label.value = existing.label;
    target.value = existing.target ?? ""; baseline.value = existing.baseline ?? "";
    direction.value = existing.direction; tdate.value = existing.target_date || "";
    category.disabled = true;
  } else {
    const apply = () => { const c = cats[category.value];
      if (c && !label.value) label.placeholder = c.label;
      if (category.value === "weight" || category.value === "body_fat") direction.value = "decrease"; };
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
      const payload = { category: category.value, label: label.value || cats[category.value].label,
        target: num(target.value) || null, baseline: baseline.value === "" ? null : num(baseline.value),
        unit: cats[category.value].unit || "", direction: direction.value, target_date: tdate.value || null };
      if (existing) await jput("/api/goals/" + existing.id, payload);
      else await jpost("/api/goals", payload);
      closeSheet(); toast("Goal saved"); switchTab("goals");
    } }, existing ? "Save changes" : "Create goal"));
  openSheet(existing ? "Edit goal" : "New goal", body);
}

/* ============================================================
   COACH (chat)
   ============================================================ */
const chatHistory = [];
let chatBusy = false;
let coachStarted = false;

function renderCoach() {
  const screen = $("#screen");
  if (!State.advisorReady) {
    screen.append(el("div", { class: "card" },
      el("h3", {}, "Coaching is offline"),
      el("p", { class: "muted", html: "Set <code>ANTHROPIC_API_KEY</code> in your <code>.env</code> and restart to enable your coach." })));
    return;
  }
  const log = el("div", { class: "chat-log", id: "chatLog" });
  const sugg = el("div", { class: "suggestions" });
  [["Meal ideas", "meals"], ["Next workout", "workout"], ["Recovery check", "recovery"], ["This week's focus", "focus"]]
    .forEach(([lbl, topic]) => sugg.append(el("button", { class: "pill", onclick: () => recommend(topic, lbl) }, lbl)));
  sugg.append(el("button", { class: "pill", onclick: () => sendChat("Review my recent data and revise my plan. Save it.") }, "Revise plan"));

  const input = el("input", { type: "text", autocomplete: "off", placeholder: "Ask your coach anything…" });
  const form = el("form", { class: "chat-form", onsubmit: (e) => { e.preventDefault(); const t = input.value.trim(); if (t) { input.value = ""; sendChat(t); } } },
    input, el("button", { class: "btn", type: "submit" }, "Send"));

  screen.append(log, sugg, form);

  // Re-hydrate prior conversation in this session.
  chatHistory.forEach((m) => addMsg(m.role, m.content));
  if (!coachStarted) {
    coachStarted = true;
    const plan = State.status?.plan;
    if (plan) addMsg("assistant", "Welcome back. Your plan is in motion — want a check-in on how you're tracking, or is something on your mind?");
    else if (State.status?.has_import) runBriefing();
    else addMsg("assistant", "I'm your coach. Log a few days of food, workouts and sleep — or import your Apple Health data — and I'll build you a plan and start coaching.");
  }
  scrollChat();
}
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
    chatHistory.push({ role: "user", content: "[briefing]" }, { role: "assistant", content: data.reply });
    State.status.plan = data.plan;
  } catch (e) { pending.className = "msg assistant error"; pending.textContent = "⚠ " + e.message; }
  finally { chatBusy = false; scrollChat(); }
}
async function sendChat(text) {
  if (chatBusy) return; chatBusy = true;
  addMsg("user", text); chatHistory.push({ role: "user", content: text });
  const pending = addMsg("assistant", "Thinking", "thinking dots");
  try {
    const data = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: chatHistory }) });
    pending.className = "msg assistant"; pending.innerHTML = marked.parse(data.reply);
    chatHistory.push({ role: "assistant", content: data.reply });
    State.status.plan = data.plan;
  } catch (e) { pending.className = "msg assistant error"; pending.textContent = "⚠ " + e.message; chatHistory.pop(); }
  finally { chatBusy = false; scrollChat(); }
}
async function recommend(topic, label) {
  if (chatBusy) return; chatBusy = true;
  addMsg("user", label); chatHistory.push({ role: "user", content: label });
  const pending = addMsg("assistant", "Thinking", "thinking dots");
  try {
    const data = await jpost("/api/recommend", { topic });
    pending.className = "msg assistant"; pending.innerHTML = marked.parse(data.reply);
    chatHistory.push({ role: "assistant", content: data.reply });
  } catch (e) { pending.className = "msg assistant error"; pending.textContent = "⚠ " + e.message; chatHistory.pop(); }
  finally { chatBusy = false; scrollChat(); }
}
