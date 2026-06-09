# Asclepius — your personal Apple Health advisor

Asclepius is a **private, local** web app that ingests your own Apple Health
export and gives you an AI health advisor (powered by Claude) that analyzes
your **sleep, activity & fitness, heart health, and body & vitals** — grounded
in your real numbers, not generic advice.

> ⚕️ Asclepius is not a doctor and does not provide medical diagnosis. It's a
> tool for understanding your own data. For medical concerns, consult a
> qualified healthcare professional.

## What it does

- **Parses your Apple Health export** (`export.xml`, even multi-hundred-MB ones)
  into clean daily summaries — steps, distance, active energy, exercise time,
  heart rate, resting HR, HRV, VO₂ max, blood pressure, weight, BMI, body fat,
  blood oxygen, respiratory rate, sleep stages, and workouts.
- **Dashboard** with headline cards, trends, a sleep panel, and a workout
  breakdown.
- **Metric explorer** to chart any metric over 30 days → all time.
- **Advisor chat**: ask questions in plain English. Claude (Opus 4.8, with
  adaptive thinking) uses tools to query your actual data — summaries, trends,
  and time series — before answering, and cites your real values.

Everything runs on your machine. Your health data never leaves it except for
the compact summaries the advisor sends to the Claude API when you chat.

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
  store.py       SQLite persistence
  analytics.py   Trends, summaries, time series (powers dashboard + advisor)
  advisor.py     Claude tool-use loop, grounded in your data
  main.py        FastAPI app + static frontend
frontend/        Single-page dashboard + chat (vanilla JS + Chart.js)
scripts/         Synthetic-data generator
tests/           Pipeline tests
```

- **Backend**: FastAPI + SQLite (no heavy data deps).
- **AI**: Anthropic Python SDK, model `claude-opus-4-8`, adaptive thinking,
  `effort: high`. The advisor has tools (`get_metric_summary`,
  `get_metric_timeseries`, `get_sleep_summary`, `get_workouts_summary`,
  `list_metrics`) and is also seeded with a compact data digest each turn.
- **Frontend**: dependency-free vanilla JS, Chart.js via CDN.

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
