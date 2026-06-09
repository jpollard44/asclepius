# Asclepius — your personal AI health coach

Asclepius is a **private, local** web app that turns your own Apple Health
export into a proactive AI health **coach** (powered by Claude). It reads your
real data, tells you what matters, builds you a concrete plan, and coaches you
toward the optimal version of yourself — across **sleep, activity & fitness,
heart health, and body & vitals**.

It's agent-first: the whole experience is a conversation with a coach plus a
**living plan** it maintains for you — not a metrics dashboard (you already have
those in the Health app).

> ⚕️ Asclepius is not a doctor and does not provide medical diagnosis. It's a
> tool for understanding your own data. For medical concerns, consult a
> qualified healthcare professional.

## What it does

- **Proactive briefing**: on first load it reads across your data, tells you
  what stands out, what's going well, and the few things most worth improving —
  then builds your initial plan.
- **Living plan**: a goal, 2–4 focus areas, and concrete weekly actions with
  targets tied to your numbers (e.g. "raise average sleep 6.9h → 7.5h"). The
  coach saves and revises it over time and checks your progress against it.
- **Coaching chat**: ask anything ("how's my sleep affecting recovery?", "what
  should I focus on this week?"). Claude (Opus 4.8, adaptive thinking) uses
  tools to query your actual data — summaries, trends, time series, sleep,
  workouts — before answering, and cites your real values.
- **Streaming parser** for the Apple Health `export.xml` (even multi-hundred-MB
  ones) → clean daily summaries of steps, distance, energy, exercise time, heart
  rate, resting HR, HRV, VO₂ max, blood pressure, weight, BMI, body fat, blood
  oxygen, respiratory rate, sleep stages, and workouts.

Everything runs on your machine. Your health data never leaves it except for
the compact summaries the coach sends to the Claude API when it reasons.

## Getting your Apple Health data

There is no cloud API for your own Health data — it lives on your iPhone. Export it:

1. On your iPhone, open **Health** → tap your **profile photo** (top right) →
   **Export All Health Data**.
2. You'll get an `export.zip`. Send it to your computer (AirDrop, email, etc.).
3. Upload the `.zip` (or the `export.xml` inside it) in the app.

## Quick start

```bash
# 1. Add your Anthropic API key (get one at https://console.anthropic.com/)
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...

# 2. Run it (creates a venv and installs deps on first run)
./run.sh
```

Then open **http://localhost:8765** and upload your export.

### Try it without your real data

Generate a realistic synthetic export and load that:

```bash
./.venv/bin/python scripts/generate_sample_export.py 180 data/sample_export.xml
```

Upload `data/sample_export.xml` in the app.

## How it's built

```
backend/
  config.py      Metric definitions (HK types → friendly keys, units, areas)
  parser.py      Streaming iterparse of export.xml → daily aggregates
  store.py       SQLite persistence (data + the living plan)
  analytics.py   Trends, summaries, time series the coach reasons over
  advisor.py     The coach: Claude tool-use loop + plan tools + briefing
  main.py        FastAPI app + static frontend
frontend/        Single-page coach: conversation + plan panel (vanilla JS)
  vendor/        Locally-served marked.js (no runtime CDN)
scripts/         Synthetic-data generator
tests/           Pipeline tests
```

- **Backend**: FastAPI + SQLite (no heavy data deps).
- **AI**: Anthropic Python SDK, model `claude-opus-4-8`, adaptive thinking,
  `effort: high`. The coach has tools to read data (`get_metric_summary`,
  `get_metric_timeseries`, `get_sleep_summary`, `get_workouts_summary`,
  `list_metrics`) and to maintain the plan (`get_plan`, `save_plan`), and is
  seeded with a compact data digest + the current plan each turn.
- **Frontend**: dependency-free vanilla JS; markdown rendered with a locally
  vendored marked.js so the app runs fully offline.

## Configuration

| Variable            | Default              | Purpose                          |
| ------------------- | -------------------- | -------------------------------- |
| `ANTHROPIC_API_KEY` | —                    | Required for the advisor chat    |
| `ASCLEPIUS_MODEL`   | `claude-opus-4-8`    | Advisor model                    |
| `ASCLEPIUS_DB`      | `./data/health.db`   | SQLite location                  |
| `PORT`              | `8765`               | Server port                      |

## Privacy

- `data/`, `.env`, and any `*.xml`/`*.zip` are git-ignored — your health data is
  never committed.
- Parsing and storage are fully local. Only the advisor chat calls the Claude
  API, and only with the compact summaries needed to answer your question.

## Tests

```bash
./.venv/bin/python -m pytest tests/ -q
```
