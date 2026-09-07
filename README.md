# TCC UFMG — IoT Pipeline + AI Agent

Undergraduate thesis (TCC) project for the Control and Automation Engineering
program at UFMG: an end-to-end system that ingests live data from IoT devices
(Tuya Cloud API) around the author's home, orchestrated with Dagster, modeled
into a DuckDB warehouse, and exposed through both a Streamlit dashboard and an
AI agent that can answer data questions in plain English and actuate the
devices themselves.

The repo backs two deliverables: the written monograph (`latex/`) and a
demoable data-engineering + AI-agent system (`app/`).

## Architecture

```
Tuya Cloud API
      │
      ▼
┌─────────────────┐     ┌──────────────────────┐     ┌────────────────────────┐
│  raw_tuya_logs   │ ──▶ │  staging_tuya_logs    │ ──▶ │  gold_device_metrics   │
│  (JSON, per      │     │  (partitioned Parquet, │     │  (hourly/daily rollups │
│   device/date)   │     │   DuckDB transform)    │     │   → Parquet + DuckDB)  │
└─────────────────┘     └──────────────────────┘     └───────────┬────────────┘
      Dagster assets — orchestrated by `tuya_processing_job`,     │
      scheduled hourly, materializing into `warehouse.duckdb`     │
                                                                    ▼
                                          ┌─────────────────────────────────────┐
                                          │        warehouse.duckdb (gold)        │
                                          │   read-only for downstream readers    │
                                          └───────────┬─────────────┬───────────┘
                                                       │             │
                                     ┌─────────────────▼──┐   ┌──────▼───────────────┐
                                     │  Streamlit          │   │  AI agent            │
                                     │  dashboard          │◀─▶│  (Gemini free tier,  │
                                     │  (live device charts│   │  default):           │
                                     │  + chat panel)      │   │  query_iot_data, get_ │
                                     └─────────────────────┘   │  device_state,        │
                                                                │  control_device       │
                                                                │  (dry-run gated)      │
                                                                └───────┬───────────────┘
                                                                        ▼
                                                                  Tuya devices
                                                              (real actuation, opt-in)
```

- **Ingest** — `raw_tuya_logs` pulls device status logs from the Tuya Cloud
  API and saves raw JSON under `app/data/raw/<device_id>/<date>/`.
- **Stage** — `staging_tuya_logs` reads the raw JSON with DuckDB and writes a
  partitioned Parquet dataset (`event_date=YYYY-MM-DD`) under
  `app/data/staging/`, joined against the device-name mapping.
- **Gold marts** — `gold_device_metrics` aggregates staging into four
  per-device tables, written both as Parquet under `app/data/marts/` and as
  tables in the persistent `app/data/warehouse.duckdb`:
  `device_metrics_hourly` / `device_metrics_daily` (event counts, last-seen,
  on-time proxy), `device_state_intervals` (contiguous on/off stretches with
  durations, plus the Tuya datapoint each device switches on), and
  `device_on_time_daily` (per-day on-time, sessions, longest session, and
  overnight 00:00-06:00 on-time). Staging stores UTC; **the whole gold layer
  is local wall-clock time**, since every question asked of it ("during work
  hours", "overnight") means local time.
- **AI agent** (`app/agent/`) — runs by default against **Google's Gemini
  API** (free tier via an AI Studio key), through a provider abstraction that
  can also be pointed at a local, keyless open-weight model via Ollama, or at
  Anthropic. Three tools: `query_iot_data` (read-only SQL over the marts),
  `get_device_state` (latest reading for a named device), and
  `control_device` (turn a device on/off, guarded by a **dry-run flag**). Note:
  with the Gemini provider, prompts (and tool schemas/results) are sent to
  Google's API.
- **Web app** (`app/api/` + `app/web/`) — a Starlette API and a dependency-free
  single-page UI: KPI tiles, a device on/off timeline, per-device on-time, and
  an agent panel that **streams the agent's tool calls live over SSE** (the SQL
  it writes, the payload it would send, how long each step took). Charts are
  hand-drawn inline SVG — no charting library, no CDN, so nothing external can
  fail while it is running. A Streamlit version is retained at
  `app/dashboard/dashboard.py` as a fallback.

## Repository layout

```
latex/                       — LaTeX monograph (entry point: Monografia.tex)
app/
  definitions.py              — Dagster Definitions (assets + resources + job + schedule)
  resources.py                 — persistent DuckDBResource (app/data/warehouse.duckdb)
  assets/
    ingestion.py                — raw_tuya_logs, staging_tuya_logs
    marts.py                     — gold_device_metrics (event, duration + on-time rollups)
  agent/
    tools.py                     — provider-neutral tool registry: query_iot_data, get_device_state, control_device
    tuya_control.py               — dry-run-safe Tuya command sending + device registry
    llm_provider.py                — LLM provider abstraction (Gemini default, Ollama/Anthropic optional)
    agent.py                      — bounded tool-calling loop (run_agent)
  api/
    data_access.py               — shared warehouse reader + overview/health payloads
    server.py                     — Starlette API: /api/overview, /api/health, /api/agent/stream (SSE)
  web/                          — the web UI (no build step, no CDN)
    index.html                    — app shell: sidebar + KPIs + charts + agent panel
    static/app.js                  — data fetching, filters, SSE agent stream
    static/charts.js               — hand-drawn inline-SVG timeline, bars, sparklines
    static/styles.css              — dark theme tokens
  dashboard/
    dashboard.py                  — Streamlit UI (retained as a fallback)
  data_ingestion/
    ingestion_utils.py            — Tuya API helper functions
  device_mapping.json           — device_id → friendly name registry
  tests/                        — pytest suite
  data/
    raw/  staging/  marts/        — pipeline data layers
    warehouse.duckdb              — persistent DuckDB warehouse
scripts/
  seed_synthetic_data.py      — regenerates the synthetic demo dataset in app/data/raw/
docs/
  api_contract.md             — frozen JSON contract between app/api and app/web
dagster.yaml                  — Dagster instance config
workspace.yaml                — points Dagster at app.definitions
```

## Setup

Requires Python 3.11+ (the pipeline and agent target 3.12).

```bash
cd app
python3 -m venv .venv
source .venv/bin/activate       # .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Create a `.env` file in `app/` (gitignored) with:

```
ACCESS_ID=<tuya cloud project access id>
ACCESS_SECRET=<tuya cloud project access secret>
API_ENDPOINT=<tuya regional API endpoint, e.g. https://openapi.tuyaus.com>
```

### AI agent — three interchangeable providers

The agent is provider-neutral (`app/agent/llm_provider.py`); pick one via
`LLM_PROVIDER`:

| Provider | `LLM_PROVIDER` | Notes |
|---|---|---|
| **Gemini (default, recommended)** | `gemini` | Free tier via a Google AI Studio key. No local RAM/GPU needed. Prompts are sent to Google's API. |
| Ollama | `ollama` | Fully local and keyless, but needs enough RAM to run the model and a one-time `ollama pull`. |
| Anthropic | `anthropic` | Needs a paid Anthropic API key. |

**Gemini (default) setup:**

```bash
# Get a free key at https://aistudio.google.com/apikey
```

Add to `app/.env`:

```
GEMINI_API_KEY=<your free ai studio key>
```

Relevant env vars (all optional):

| Env var | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | Selects the backend: `gemini` (default), `ollama`, or `anthropic`. |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | (none) | Free key from Google AI Studio; required for the default provider. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model to use (must support tool/function calling). On a transient `503`/`429` the provider automatically falls through `gemini-3.7-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, since free-tier capacity is per-model. |
| `OLLAMA_MODEL` | `qwen3:8b` | Ollama model to use (must support tool calling). |
| `OLLAMA_HOST` | (Ollama's default) | Override if Ollama isn't on `localhost:11434`. |
| `ANTHROPIC_API_KEY` | (none) | Required when `LLM_PROVIDER=anthropic`. |

**Ollama (local, keyless) setup — set `LLM_PROVIDER=ollama` to use it:**

```bash
# 1. Install Ollama: https://ollama.com/download
# 2. Start the Ollama server
ollama serve
# 3. Pull the default tool-calling model
ollama pull qwen3:8b
```

**Anthropic setup — set `LLM_PROVIDER=anthropic` and add
`ANTHROPIC_API_KEY=<anthropic api key>` to `.env`.**

## Running each surface

**Pipeline (Dagster UI):**

```bash
dagster dev
```

From the repo root. Materialize `raw_tuya_logs` → `staging_tuya_logs` →
`gold_device_metrics` from the Dagster UI, or run the whole
`tuya_processing_job` (also scheduled hourly via `hourly_schedule`).

> **The shipped dataset is synthetic.** The Tuya Cloud subscription behind
> this project has lapsed, so `raw_tuya_logs` can no longer fetch live
> history. `scripts/seed_synthetic_data.py` stands in for it, writing raw JSON
> in exactly the shape that asset produces (every row stamped
> `ingested_by = 'synthetic_seed_script'`, so it stays queryable as such). To
> rebuild the demo dataset from scratch:
>
> ```bash
> python scripts/seed_synthetic_data.py
> dagster asset materialize -m app.definitions \
>     --select 'staging_tuya_logs,gold_device_metrics'
> ```
>
> The two downstream assets depend on `raw_tuya_logs` via `deps` rather than
> as an input value, precisely so they can be rematerialized without live
> credentials.

**Web app (primary UI):**

```bash
python -m app.api.server            # http://localhost:8000
```

Serves the API and the single-page UI together. The left side is the
dashboard — KPI tiles, the device on/off timeline, and per-device on-time,
all filterable by device and time range from the sidebar. The right side is
the agent panel: ask a question and its tool calls appear **as they happen**
(streamed over SSE), each showing the SQL it wrote, the rows that came back,
and how long the step took.

Device control is **dry-run by default**, shown as a prominent SAFE / ARMED
switch: in SAFE mode the agent computes the exact Tuya payload and the UI
displays it, but nothing is sent. The gate is enforced server-side — the model
cannot turn it off itself (`_dispatch_tool_call` in `app/agent/agent.py`
overwrites whatever `dry_run` the model asks for).

**Streamlit UI (fallback):**

```bash
streamlit run app/dashboard/dashboard.py
```

The earlier interface, kept working as a fallback. Shows live per-device
charts from the gold marts and a chat panel backed by
the agent — ask data questions in plain English, or issue a device control
command. Device control is **dry-run by default**: the agent shows the exact
command payload it would send, and only actuates a real device when
explicitly run with `dry_run=False`, so a demo (or a hallucinated tool call)
can never fire a command unintentionally. The charts always work; the chat
panel shows friendly guidance if the selected provider isn't available (e.g.
no `GEMINI_API_KEY` set, or Ollama isn't reachable / the model hasn't been
pulled yet).

**Tests:**

```bash
pytest app/tests/
```

Runs the unit test suite (ingestion helpers, agent tools, agent tool-calling
loop, mart aggregation SQL) entirely offline — no real Tuya, Gemini, Ollama,
or Anthropic calls are made, and no device commands are ever sent.

## Tech stack

| Layer | Tool |
|---|---|
| Monograph | LaTeX + BibTeX + latexmk |
| Orchestration | Dagster + dagster-webserver |
| Transformation | DuckDB (via dagster-duckdb) |
| Storage | Parquet (staging/marts), JSON (raw), DuckDB (warehouse) |
| IoT API | tuya-connector-python |
| AI agent | Google Gemini (free tier, default); optional local Ollama or Anthropic providers |
| Dashboard | Streamlit + Plotly |
| Tests | pytest |
