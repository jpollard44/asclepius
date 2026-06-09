"use strict";

const $ = (sel) => document.querySelector(sel);
const api = async (path, opts) => {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
};

const chatHistory = []; // [{role, content}]
let advisorReady = true;
let busy = false;

init();

async function init() {
  marked.setOptions({ breaks: true });
  try {
    const status = await api("/api/status");
    advisorReady = status.advisor_ready;
    if (status.has_data) enterApp(status);
    else showUpload();
  } catch (e) {
    showUpload();
  }
  wireUpload();
  wireChat();
}

// ---------------------------------------------------------------------------
// Onboarding
// ---------------------------------------------------------------------------
function showUpload() {
  $("#uploadView").classList.remove("hidden");
  $("#appView").classList.add("hidden");
  $("#reloadBtn").classList.add("hidden");
  $("#uploadStatus").textContent = "";
}

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
  status.textContent = `Reading ${file.name}… large exports can take a moment.`;
  const fd = new FormData();
  fd.append("file", file);
  try {
    await api("/api/upload", { method: "POST", body: fd });
    const st = await api("/api/status");
    enterApp(st);
  } catch (e) {
    status.className = "upload-status error";
    status.textContent = e.message;
  }
}

// ---------------------------------------------------------------------------
// Coach
// ---------------------------------------------------------------------------
function enterApp(status) {
  $("#uploadView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  $("#reloadBtn").classList.remove("hidden");
  renderPlan(status.plan);

  if (!advisorReady) {
    addMsg("assistant",
      "I'm ready, but I need an **Anthropic API key** to think. Set " +
      "`ANTHROPIC_API_KEY` in your `.env` and restart, then ask me anything.");
    return;
  }

  if (status.plan) {
    addMsg("assistant",
      "Welcome back. Your plan is on the right. Want a check-in on how you're " +
      "tracking against it, or is there something specific on your mind?");
  } else {
    // First time with data: proactively brief and build the plan.
    runBriefing();
  }
}

async function runBriefing() {
  if (busy) return;
  busy = true;
  $("#sendBtn").disabled = true;
  const pending = addMsg("assistant", "Analyzing your data and building your plan", "thinking dots");
  try {
    const data = await api("/api/briefing", { method: "POST" });
    pending.className = "msg assistant";
    pending.innerHTML = marked.parse(data.reply);
    chatHistory.push({ role: "user", content: "[briefing requested]" });
    chatHistory.push({ role: "assistant", content: data.reply });
    renderPlan(data.plan);
  } catch (e) {
    pending.className = "msg assistant error";
    pending.textContent = "⚠ " + e.message;
  } finally {
    busy = false;
    $("#sendBtn").disabled = false;
    scrollChat();
  }
}

function wireChat() {
  $("#chatForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#chatInput").value.trim();
    if (text) sendChat(text);
  });
  $("#suggestions").addEventListener("click", (e) => {
    if (e.target.classList.contains("chip")) sendChat(e.target.textContent);
  });
  $("#refreshPlanBtn").addEventListener("click", () =>
    sendChat("Review my recent data and revise my plan accordingly. Save the updated plan."));
}

function addMsg(role, text, cls = "") {
  const log = $("#chatLog");
  const el = document.createElement("div");
  el.className = `msg ${role} ${cls}`;
  if (role === "assistant" && !cls.includes("thinking")) el.innerHTML = marked.parse(text);
  else el.textContent = text;
  log.appendChild(el);
  scrollChat();
  return el;
}

function scrollChat() { const l = $("#chatLog"); l.scrollTop = l.scrollHeight; }

async function sendChat(text) {
  if (busy) return;
  busy = true;
  $("#chatInput").value = "";
  $("#sendBtn").disabled = true;
  addMsg("user", text);
  chatHistory.push({ role: "user", content: text });
  const pending = addMsg("assistant", "Thinking", "thinking dots");
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: chatHistory }),
    });
    pending.className = "msg assistant";
    pending.innerHTML = marked.parse(data.reply);
    chatHistory.push({ role: "assistant", content: data.reply });
    renderPlan(data.plan);
  } catch (e) {
    pending.className = "msg assistant error";
    pending.textContent = "⚠ " + e.message;
    chatHistory.pop();
  } finally {
    busy = false;
    $("#sendBtn").disabled = false;
    $("#chatInput").focus();
    scrollChat();
  }
}

// ---------------------------------------------------------------------------
// Plan panel
// ---------------------------------------------------------------------------
function renderPlan(plan) {
  const body = $("#planBody");
  const meta = $("#planMeta");
  if (!plan) {
    body.innerHTML = '<p class="muted">Your coach will build your plan from your first briefing.</p>';
    meta.textContent = "";
    return;
  }
  let html = "";
  if (plan.goal) html += `<div class="plan-goal">${escapeHtml(plan.goal)}</div>`;
  if (plan.focus && plan.focus.length) {
    html += '<div class="focus-tags">' +
      plan.focus.map((f) => `<span>${escapeHtml(f)}</span>`).join("") + "</div>";
  }
  if (plan.content) html += marked.parse(plan.content);
  body.innerHTML = html;
  meta.textContent = plan.updated_at ? `Updated ${plan.updated_at.replace("T", " ")}` : "";
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
