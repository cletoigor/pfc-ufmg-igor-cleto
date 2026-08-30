# CLAUDE.md — TCC Monografia (UFMG)

## Project Overview

UFMG undergraduate thesis (TCC) for Control and Automation Engineering, combining a LaTeX monograph with a Dagster data pipeline that ingests IoT device data from the Tuya Cloud API, a gold-layer DuckDB warehouse, an Anthropic AI agent that can query the data and (dry-run gated) control the devices, and a Streamlit dashboard. See `README.md` at the repo root for the full architecture overview and setup steps.

## Repository Layout

```
latex/                       — LaTeX monograph (entry point: Monografia.tex)
app/                         — Dagster pipeline + AI agent (entry point: app.definitions)
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
  device_mapping.json           — device ID → name mapping (also the agent's device registry)
  tests/                       — pytest suite
  data/
    raw/        — raw JSON files per device/date
    staging/    — partitioned Parquet (event_date=YYYY-MM-DD)
    marts/      — gold-layer Parquet (hourly/daily rollups)
    warehouse.duckdb — persistent DuckDB warehouse (Dagster writes; agent/dashboard read read_only=True)
dagster.yaml    — Dagster instance config
workspace.yaml  — points Dagster to app.definitions
```

## LaTeX Conventions

- Compile: `latexmk -pdf Monografia.tex` (from `latex/` directory)
- Citation style: ABNT
- Figure placement: `[htbp]`
- Table formatting: `booktabs`
- Label prefixes: `sec:`, `fig:`, `tab:`
- Language: formal academic Portuguese

## Data Pipeline Architecture (Dagster)

Three assets, split across `app/assets/ingestion.py` and `app/assets/marts.py`, wired into `app/definitions.py`:

1. **`raw_tuya_logs`** (`assets/ingestion.py`) — fetches Tuya API logs, saves JSON to `app/data/raw/<device_id>/<YYYY-MM-DD>/`; credentials via `TuyaCredentials` Config using `EnvVar` (`ACCESS_ID`, `ACCESS_SECRET`, `API_ENDPOINT`). Fails loudly if zero files are saved in a run.
2. **`staging_tuya_logs`** (`assets/ingestion.py`) — reads raw JSONs, transforms via DuckDB (persistent `DuckDBResource` from `resources.py`), writes partitioned Parquet to `app/data/staging/`.
3. **`gold_device_metrics`** (`assets/marts.py`) — aggregates staging into per-device hourly/daily rollups (event counts, last-seen, on-time proxy), writing Parquet to `app/data/marts/{hourly,daily}/` and materializing `device_metrics_hourly` / `device_metrics_daily` tables in `app/data/warehouse.duckdb`.

All three are wired into `tuya_processing_job`, triggered by `hourly_schedule` (`0 * * * *`).

Start the UI: `dagster dev` from the project root (requires the Python venv in `app/.venv/` and a `.env` file with API credentials).

The DuckDB warehouse at `app/data/warehouse.duckdb` is **persistent** (not in-memory) and Dagster is its sole writer; any other process (the AI agent, the dashboard, ad-hoc analysis) must connect with `read_only=True` to avoid lock contention.

## AI Agent (`app/agent/`)

Built on the Anthropic Python SDK's Tool Runner (`@beta_tool`), exposing three tools to the model:

- **`query_iot_data(sql)`** — read-only DuckDB SQL over the gold marts (rejects any non-SELECT/WITH/EXPLAIN/DESCRIBE/SHOW statement); falls back warehouse → marts parquet → staging parquet → a "no data yet" message.
- **`get_device_state(device_name)`** — latest known reading for a device, resolved via `device_mapping.json`.
- **`control_device(device_name, action, dry_run=True)`** — actuates a device (on/off/toggle) via `agent/tuya_control.py`'s `send_device_command`. **Dry-run is the default and the safety gate**: with `dry_run=True` the exact Tuya `commands` payload is returned but never sent; a real command requires explicitly passing `dry_run=False`.

`agent/agent.py` exposes `run_agent(user_message, *, dry_run=True, history=None)`, used by the Streamlit dashboard's chat panel.

## Dashboard (`app/dashboard/`)

Streamlit app (`streamlit run app/dashboard/app.py`): live per-device charts read from the gold marts (read-only DuckDB connection) plus a chat panel wired to `agent/agent.py`, showing the agent's tool-call trace (SQL it ran / commands it sent) inline.

## Key Tech Stack

| Layer | Tool |
|---|---|
| Monograph | LaTeX + BibTeX + latexmk |
| Orchestration | Dagster + dagster-webserver |
| Transformation | DuckDB (via dagster-duckdb) |
| Storage | Parquet (staging/marts), JSON (raw), DuckDB (warehouse) |
| IoT API | tuya-connector-python |
| AI agent | Anthropic Python SDK (Tool Runner, `@beta_tool`) |
| Dashboard | Streamlit + Plotly |
| Tests | pytest (`app/tests/`) |
| Python deps | `app/requirements.txt`, venv at `app/.venv/` |

## Files Claude Should Ignore

Generated LaTeX artifacts — do not propose edits to these:

```
latex/*.aux  latex/*.bbl  latex/*.blg  latex/*.fdb_latexmk
latex/*.fls  latex/*.log  latex/*.lof  latex/*.lot
latex/*.out  latex/*.toc  latex/*.synctex.gz  latex/*.ps
latex/Monografia.pdf  latex/**/*-eps-converted-to.pdf
latex/*/*.aux
```
