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
                                     │  dashboard          │◀─▶│  (Anthropic Tool     │
                                     │  (live device charts│   │  Runner): query_iot   │
                                     │  + chat panel)      │   │  _data, get_device_   │
                                     └─────────────────────┘   │  state, control_device│
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
- **AI agent** (`app/agent/`) — an Anthropic Tool Runner agent with three
  tools: `query_iot_data` (read-only SQL over the marts), `get_device_state`
  (latest reading for a named device), and `control_device` (turn a device
  on/off, guarded by a **dry-run flag**).
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
    tools.py                     — @beta_tool: query_iot_data, get_device_state, control_device
    tuya_control.py               — dry-run-safe Tuya command sending + device registry
    agent.py                      — Anthropic Tool Runner agent (run_agent)
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
ANTHROPIC_API_KEY=<anthropic api key>
```

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
streamlit run app/dashboard/app.py
```

Shows live per-device charts from the gold marts and a chat panel backed by
the agent — ask data questions in plain English, or issue a device control
command. Device control is **dry-run by default**: the agent shows the exact
command payload it would send, and only actuates a real device when
explicitly run with `dry_run=False`, so a demo (or a hallucinated tool call)
can never fire a command unintentionally.

**Tests:**

```bash
pytest app/tests/
```

Runs the unit test suite (ingestion helpers, agent tools, mart aggregation
SQL) entirely offline — no real Tuya or Anthropic calls are made, and no
device commands are ever sent.

## Tech stack

| Layer | Tool |
|---|---|
| Monograph | LaTeX + BibTeX + latexmk |
| Orchestration | Dagster + dagster-webserver |
| Transformation | DuckDB (via dagster-duckdb) |
| Storage | Parquet (staging/marts), JSON (raw), DuckDB (warehouse) |
| IoT API | tuya-connector-python |
| AI agent | Anthropic Python SDK (Tool Runner, `@beta_tool`) |
| Dashboard | Streamlit + Plotly |
| Tests | pytest |
