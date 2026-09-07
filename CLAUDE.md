# CLAUDE.md — TCC Monografia (UFMG)

## Project Overview

UFMG undergraduate thesis (TCC) for Control and Automation Engineering, combining a LaTeX monograph with a Dagster data pipeline that ingests IoT device data from the Tuya Cloud API, a gold-layer DuckDB warehouse, an AI agent (Gemini free tier by default; local Ollama or Anthropic optionally) that can query the data and (dry-run gated) control the devices, and a Streamlit dashboard. See `README.md` at the repo root for the full architecture overview and setup steps.

## Repository Layout

```
latex/                       — LaTeX monograph (entry point: Monografia.tex)
app/                         — Dagster pipeline + AI agent (entry point: app.definitions)
  definitions.py              — Dagster Definitions (assets + resources + job + schedule)
  resources.py                 — persistent DuckDBResource (app/data/warehouse.duckdb)
  assets/
    ingestion.py                — raw_tuya_logs, staging_tuya_logs
    marts.py                     — gold_device_metrics (event, duration + on-time rollups)
    energy_marts.py              — gold_energy_metrics (power/voltage/current, kWh, CUSUM baseline)
  analysis/
    cusum.py                     — multichannel CUSUM (pure functions, framework-free)
  scenes/
    store.py                     — scheduled_scenes.json CRUD (atomic writes)
    executor.py                  — scene_is_due + run_scene, and the dry-run gates
    scheduler.py                 — Dagster op/job/schedule, every minute
  agent/
    tools.py                     — provider-neutral tool registry: query_iot_data, get_device_state, control_device
    tuya_control.py               — dry-run-safe Tuya command sending + device registry
    llm_provider.py                — LLM provider abstraction (Gemini default, Ollama/Anthropic optional)
    agent.py                      — bounded tool-calling loop (run_agent)
  dashboard/
    app.py                        — Streamlit: live charts + AI chat panel
  data_ingestion/
    ingestion_utils.py            — Tuya API helper functions
  device_mapping.json           — device ID → name mapping (also the agent's device registry)
  tests/                       — pytest suite
  data/
    raw/        — raw JSON files per device/date
    staging/    — partitioned Parquet (event_date=YYYY-MM-DD)
    marts/      — gold-layer Parquet (hourly/daily/state_intervals/on_time_daily)
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

Four assets, split across `app/assets/ingestion.py`, `app/assets/marts.py` and `app/assets/energy_marts.py`, wired into `app/definitions.py`:

1. **`raw_tuya_logs`** (`assets/ingestion.py`) — fetches Tuya API logs, saves JSON to `app/data/raw/<device_id>/<YYYY-MM-DD>/`; credentials via `TuyaCredentials` Config using `EnvVar` (`ACCESS_ID`, `ACCESS_SECRET`, `API_ENDPOINT`). Fails loudly if zero files are saved in a run.
2. **`staging_tuya_logs`** (`assets/ingestion.py`) — reads raw JSONs, transforms via DuckDB (persistent `DuckDBResource` from `resources.py`), writes partitioned Parquet to `app/data/staging/`.
3. **`gold_device_metrics`** (`assets/marts.py`) — aggregates staging into four per-device tables, written as Parquet under `app/data/marts/{hourly,daily,state_intervals,on_time_daily}/` and materialized in `app/data/warehouse.duckdb`: `device_metrics_hourly` / `device_metrics_daily` (event counts, last-seen, on-time proxy), `device_state_intervals` (contiguous on/off stretches + `switch_code`, the Tuya datapoint that device actuates through), and `device_on_time_daily` (on_minutes, on_sessions, longest_session_minutes, overnight_on_minutes).

4. **`gold_energy_metrics`** (`assets/energy_marts.py`) — the electrical side, from the `cur_power` / `cur_voltage` / `cur_current` datapoints: `device_power_hourly` and `device_power_daily` (power/voltage/current statistics plus `energy_kwh`), and `device_cusum_baseline` (per device and hour-of-day, the Phase I mean `mu0` and **sample** standard deviation `sigma0` of hourly energy). Energy is integrated by zero-order hold capped at `MAX_SAMPLE_HOLD_MINUTES` (15), so an off-period is never integrated across; a hold that straddles an hour boundary is split between both hours. The baseline excludes the last `BASELINE_HOLDOUT_DAYS` (7) so Phase I is not contaminated by the period under test.

**Timezone contract:** staging stores `event_time` in UTC (via `epoch_ms`, deliberately host-independent); the gold layer converts to local wall-clock via `LOCAL_UTC_OFFSET_HOURS` in `marts.py`, because every question asked of it ("work hours", "overnight") means local time.

`staging_tuya_logs` and `gold_device_metrics` depend on their upstream via `deps=` rather than `ins=`, so they can be rematerialized without `raw_tuya_logs` (which needs live Tuya credentials the project no longer has). The demo dataset is synthetic — regenerate with `python scripts/seed_synthetic_data.py`.

All four are wired into `tuya_processing_job`, triggered by `hourly_schedule` (`0 * * * *`).

## Statistical process control (`app/analysis/cusum.py`)

The monograph's chapter 3 method, as pure functions with no framework imports so
both the API and the Streamlit app can use them and the maths is unit-tested
against hand-computed numbers (`app/tests/test_cusum.py`).

`multichannel_cusum(observations, baseline, k=0.5, h=5.0)` runs Phase II:
`K = k·sigma0`, `H = h·sigma0`, `S_hi = max(0, S_hi + (x - (mu0 + K)))`,
`S_lo = max(0, S_lo + ((mu0 - K) - x))`, signalling when either exceeds H.

**Each hour-of-day keeps its own pair of accumulators.** That is what
"intra-channel" means, and it is not optional: every hour of one day shares that
day's conditions, so a single pooled accumulator reads correlated daily noise as
a sustained shift (measured: 18 false alarms across the six devices, versus 0
with per-channel sums). A channel with fewer than 3 baseline observations or
zero spread is carried through unmonitored rather than alarmed on.

## Scenes (`app/scenes/`)

Named sets of device actions, stored in `app/data/scheduled_scenes.json`
(atomic writes — the API and the every-minute Dagster job both write it), run by
hand from the Actuations page or fired by `scene_scheduler_job`
(`* * * * *`, which needs the Dagster **daemon**, not just the webserver).

**Two independent safety gates, deliberately:**
- Interactive: `dry_run` per request. Only a literal JSON `false` opens it, and
  the UI never sends `false` — every actuation from the web app or the Streamlit
  dashboard is a dry run that returns the payload instead of sending it.
- Unattended: `SCENE_EXECUTION_DRY_RUN` (default `1`), read by the Dagster op.

They are separate so an interactive `dry_run: false` from an API client cannot
arm a job that fires at 03:00 with nobody watching. Underneath both,
`send_device_command` still refuses to reach Tuya without credentials, so a
misconfiguration fails closed.

Start the UI: `dagster dev` from the project root (requires the Python venv in `app/.venv/` and a `.env` file with API credentials).

The DuckDB warehouse at `app/data/warehouse.duckdb` is **persistent** (not in-memory) and Dagster is its sole writer; any other process (the AI agent, the dashboard, ad-hoc analysis) must connect with `read_only=True` to avoid lock contention.

## AI Agent (`app/agent/`)

Runs by default against **Google's Gemini API** (free tier via an AI Studio key — no local RAM/GPU needed), through a provider abstraction (`agent/llm_provider.py`) that drives a bounded manual tool-calling loop in `agent/agent.py`. Selection is via `LLM_PROVIDER` env (default `"gemini"`); `GeminiProvider` uses `GEMINI_MODEL` (default `"gemini-3.8-flash"`, with automatic failover through `gemini-3.7-flash`/`gemini-3.5-flash`/`gemini-3.5-flash-lite` on a transient 503/429) and requires `GEMINI_API_KEY`/`GOOGLE_API_KEY`. Note: with the Gemini provider, prompts (and tool schemas/results) are sent to Google's API. `OllamaProvider` (local, keyless, needs RAM + `ollama pull`) and `AnthropicProvider` (paid key) remain selectable via `LLM_PROVIDER=ollama` / `LLM_PROVIDER=anthropic`; `OllamaProvider` uses `OLLAMA_MODEL` (default `"qwen3:8b"`) and optional `OLLAMA_HOST`. `provider.is_available()` never raises — it returns `False` cleanly when a key/package/server is missing, which the dashboard uses to gate the chat panel.

Three provider-neutral tools registered in `agent/tools.py`'s `TOOLS` dict (plain callables + JSON-schema specs, rendered via `openai_tool_specs()`):

- **`query_iot_data(sql)`** — read-only DuckDB SQL over the gold marts (rejects any non-SELECT/WITH/EXPLAIN/DESCRIBE/SHOW statement); falls back warehouse → marts parquet → staging parquet → a "no data yet" message.
- **`get_device_state(device_name)`** — latest known reading for a device, resolved via `device_mapping.json`.
- **`control_device(device_name, action, dry_run=True)`** — actuates a device (on/off/toggle) via `agent/tuya_control.py`'s `send_device_command`. **Dry-run is the default and the safety gate**: with `dry_run=True` the exact Tuya `commands` payload is returned but never sent; a real command requires explicitly passing `dry_run=False`. The caller's `dry_run` always overrides whatever the model puts in its tool-call arguments — the model can never disable the gate itself.

`agent/agent.py` exposes `run_agent(user_message, *, dry_run=True, history=None)` (unchanged signature), used by the Streamlit dashboard's chat panel.

## Web app (`app/api/` + `app/web/`) — the primary UI

`python -m app.api.server` (port 8000) serves both the API and the UI.

- `app/api/data_access.py` — framework-free shared data layer: the
  warehouse → marts → staging fallback (`load_metrics`, never raises), plus
  `build_overview()` / `build_health()` which produce the JSON payloads. The
  Streamlit app imports from here too, so the fallback logic has one
  definition. `app/agent/tools.py` keeps its own `_open_connection()` on
  purpose — it hands the agent a live connection for arbitrary SQL, a
  different job.
- `app/api/energy_access.py` — the energy-page payload builders (house summary,
  device detail, CUSUM, day-of-week and weekly profiles, power peaks) plus
  `boxplot_stats`. A sibling of `data_access.py`, not more of it: that module
  answers "when was it on", this one "how much did it draw". Both go through
  `load_metrics()` so the storage fallback has one definition.
- `app/api/server.py` — Starlette (NOT FastAPI, which isn't installed).
  `/api/overview`, `/api/health`, `/api/house/summary`,
  `/api/device/{device}/summary`, `/api/analysis/{cusum,profiles,peaks}`,
  the scenes CRUD, `/api/devices/{device}/toggle`, and `/api/agent/stream` (SSE).
  Every route accepts `days=<int|all>` or an absolute `start`/`end` pair —
  "Yesterday" and a custom range cannot be expressed as a trailing window. `run_agent` is
  synchronous, so the SSE route runs it in a worker thread and its `on_event`
  callback pushes onto an `asyncio.Queue` via `loop.call_soon_threadsafe` —
  that is what makes steps appear live rather than all at once at the end.
- `app/web/` — no build step, no npm, **no CDN** (nothing external can fail
  mid-demo). Four views (`static/pages/`) behind a hash router (`static/router.js`),
  shared filters in `static/state.js`, DOM helpers in `static/ui.js`, the agent
  panel in `static/agent.js`, and hand-drawn inline SVG charts in
  `static/charts.js` (line, bar, ranked bars, boxplot, CUSUM, small multiples,
  timeline, sparkline).

  **Charts size themselves from `container.clientWidth`, so a card must be in
  the document before its chart is drawn** — a detached or collapsed container
  measures zero and the SVG is laid out for a width it never had. Cards are
  appended first; the collapsed voltage/current sections draw on first expand.
- `docs/api_contract.md` is the frozen contract between the two halves; change
  it there before changing either side.

**Dashboard (`app/dashboard/dashboard.py`) — fallback.** The earlier Streamlit
UI, still maintained and still passing its AppTest smoke check.

## Key Tech Stack

| Layer | Tool |
|---|---|
| Monograph | LaTeX + BibTeX + latexmk |
| Orchestration | Dagster + dagster-webserver |
| Transformation | DuckDB (via dagster-duckdb) |
| Storage | Parquet (staging/marts), JSON (raw), DuckDB (warehouse) |
| IoT API | tuya-connector-python |
| AI agent | Google Gemini (free tier, default); optional local Ollama or Anthropic providers |
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
