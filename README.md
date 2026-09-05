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
- **Gold marts** — `gold_device_metrics` aggregates staging into per-device
  hourly/daily rollups (event counts, last-seen, on-time proxy), writing both
  Parquet (`app/data/marts/{hourly,daily}/`) and tables
  (`device_metrics_hourly`, `device_metrics_daily`) in the persistent
  `app/data/warehouse.duckdb`.
- **AI agent** (`app/agent/`) — runs by default against **Google's Gemini
  API** (free tier via an AI Studio key), through a provider abstraction that
  can also be pointed at a local, keyless open-weight model via Ollama, or at
  Anthropic. Three tools: `query_iot_data` (read-only SQL over the marts),
  `get_device_state` (latest reading for a named device), and
  `control_device` (turn a device on/off, guarded by a **dry-run flag**). Note:
  with the Gemini provider, prompts (and tool schemas/results) are sent to
  Google's API.
- **Dashboard** (`app/dashboard/`) — Streamlit app with live charts from the
  gold marts and a chat panel wired to the agent, showing its SQL/tool-call
  trace inline.

## Repository layout

```
latex/                       — LaTeX monograph (entry point: Monografia.tex)
app/
  definitions.py              — Dagster Definitions (assets + resources + job + schedule)
  resources.py                 — persistent DuckDBResource (app/data/warehouse.duckdb)
  assets/
    ingestion.py                — raw_tuya_logs, staging_tuya_logs
    marts.py                     — gold_device_metrics (hourly/daily rollups)
  agent/
    tools.py                     — provider-neutral tool registry: query_iot_data, get_device_state, control_device
    tuya_control.py               — dry-run-safe Tuya command sending + device registry
    llm_provider.py                — LLM provider abstraction (Gemini default, Ollama/Anthropic optional)
    agent.py                      — bounded tool-calling loop (run_agent)
  dashboard/
    app.py                        — Streamlit: live charts + AI chat panel
  data_ingestion/
    ingestion_utils.py            — Tuya API helper functions
  device_mapping.json           — device_id → friendly name registry
  tests/                       — pytest suite
  data/
    raw/  staging/  marts/        — pipeline data layers
    warehouse.duckdb              — persistent DuckDB warehouse
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
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model to use (must support tool/function calling). |
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

**Dashboard + AI chat:**

```bash
streamlit run app/dashboard/dashboard.py
```

Shows live per-device charts from the gold marts and a chat panel backed by
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
