# Active Context: Dagster Orchestration Setup & TCC Monografia

## 1. Current Focus

-   Redesigning the Streamlit application (`app/streamlit/streamlit_app.py`) for a homeowner-focused user experience.
-   Implementing Dagster to orchestrate the Tuya data ingestion and processing pipeline (ongoing).
-   Updating project documentation (Memory Bank) to reflect all changes.

## 2. Recent Changes

-   Added Dagster dependencies (`dagster`, `dagster-duckdb`, `dagster-webserver`) to `app/requirements.txt`.
-   Created `app/data_ingestion/ingestion_utils.py` and moved helper functions from the original ingestion script into it.
-   Created `app/assets.py` containing:
    -   `raw_tuya_logs` asset: Refactored from `app/data_ingestion/tuya_log_ingestion.py`, uses helpers from `ingestion_utils.py`, configured via `TuyaCredentials` Config class (using EnvVar). Returns the absolute path to the raw data output directory (`data/raw/`).
    -   `staging_tuya_logs` asset: Refactored from `app/data_processing/process_raw_to_staging.py`, depends on `raw_tuya_logs`, uses `DuckDBResource` (configured for in-memory DB), loads device mapping, processes raw JSONs, and writes partitioned Parquet to `data/staging/`. Returns the absolute path to the staging directory.
    -   `tuya_processing_job`: A job definition targeting both assets.
    -   `hourly_schedule`: A `ScheduleDefinition` targeting `tuya_processing_job` with a cron schedule of `0 * * * *`.
    -   `defs`: A `Definitions` object containing assets, resources (DuckDB), job, and schedule.
-   Created `dagster.yaml` (using default instance storage settings).
-   Created `workspace.yaml` pointing to `app/assets.py`.
-   Further simplified the "Perfil de Potência (Análise Multicanal)" tab in `app/streamlit/streamlit_app.py` by removing the "Estatísticas Descritivas do Perfil de Potência", "Perfil de Energia Estimada por Hora do Dia e Dia da Semana", and "Análise de Correlação Multicanal" sections. The Peak Power Analysis section was retained.
-   Corrected a bug in `app/streamlit/streamlit_app.py` where day-of-week dependent plots might only show partial data (e.g., only Saturday/Sunday) due to locale issues with `dt.day_name()`. Changed to a more robust method using `dt.weekday` and a mapping.
-   Enriched `tab1` ("Visão Geral") of `app/streamlit/streamlit_app.py` by adding detailed analyses for Voltage (V) and Current (mA), including key indicators, time series plots, and distribution plots. Tab names were also updated for brevity.
-   Adjusted the UI in `app/streamlit/streamlit_app.py` to move the "Desenvolvido por Igor Cleto." credit from the sidebar to the bottom of the main page using `st.caption()`.
-   *Previous changes related to the standalone scripts (adding device_id, partitioning, etc.) are now part of the asset logic.*
-   **Streamlit App Redesign (Homeowner Focus):**
    -   Restructured `app/streamlit/streamlit_app.py` from a tab-based layout to a multi-page layout using sidebar navigation ("Resumo da Casa", "Detalhes por Dispositivo", "Análise Avançada").
    -   Implemented the "Resumo da Casa" page with:
        -   Total energy consumption metrics (Hoje, Últimos 7 Dias, Este Mês).
        -   "Principais Consumidores": Top 5 devices by energy (kWh) for the selected period, shown as a list and bar chart.
        -   Consolidated power analysis and an ordered list of all devices by energy consumption.
    -   Implemented the "Detalhes por Dispositivo" page with:
        -   Device-specific energy consumption metrics (Hoje, Últimos 7 Dias, Este Mês).
        -   Device-specific power metrics (Avg, Max, Min, Estimated Energy kWh) for the selected period.
        -   Time series power chart, daily energy consumption chart (kWh), and average hourly power profile chart for the selected device.
        -   Added detailed Voltage (V) and Current (mA) analysis sections (metrics, time series, distribution plots) to the "Detalhes por Dispositivo" page, organized within collapsible expanders.
        -   Improved visual organization on the "Detalhes por Dispositivo" page by using `st.expander` for Power, Voltage, and Current analysis sections.
    -   Updated sidebar filters to include predefined period selections ("Hoje", "Ontem", "Últimos 7 Dias", etc.) in addition to custom date ranges.
    -   Moved the "Desenvolvido por Igor Cleto." attribution to the bottom of the navigation sidebar.
    -   Integrated CEP/SPC analysis (CUSUM chart and fault logs) into the "Análise Avançada" page.
    -   Enhanced visual separation in "Resumo da Casa" using additional dividers.
    -   Added emojis to sidebar navigation options for a more engaging look.
    -   Created and loaded a custom CSS file (`app/streamlit/style.css`) to apply styles for metrics, headers, and layout padding, improving overall visual appeal.
    -   **Code Refactoring:**
        -   Created `app/streamlit/utils/` directory.
        -   Moved data loading functions (`load_data`, `get_available_devices`) to `app/streamlit/utils/data_helpers.py`.
        -   Moved CSS loading function (`local_css`) to `app/streamlit/utils/ui_helpers.py`.
        -   Moved page rendering functions (`show_resumo_casa`, `show_detalhes_dispositivo`, `show_analise_avancada`) to `app/streamlit/utils/page_functions.py`.
        -   Updated `app/streamlit/streamlit_app.py` to import and use these refactored functions, making the main script cleaner and focused on UI flow.

## 3. Next Steps

-   Refine content and visualizations on the "Resumo da Casa" and "Detalhes por Dispositivo" pages.
-   Populate the "Análise Avançada" page with relevant technical charts if needed.
-   Thoroughly test the redesigned Streamlit application.
-   Update `memory-bank/systemPatterns.md` and `memory-bank/progress.md` to reflect the Streamlit app redesign.
-   Start the Dagster UI (`dagster dev`) to visualize assets and schedules.
-   Verify the hourly Dagster schedule is active and runs successfully.
-   Continue work on the TCC Monografia LaTeX content as needed.

## 4. Active Decisions & Considerations

-   The data pipeline is now orchestrated by Dagster.
-   The ingestion and processing steps are defined as separate assets (`raw_tuya_logs`, `staging_tuya_logs`) with an explicit dependency.
-   Helper functions for ingestion are kept separate in `app/data_ingestion/ingestion_utils.py`.
-   The pipeline is scheduled to run hourly via `ScheduleDefinition`.
-   Tuya API credentials and mapping file path for ingestion are configured via a Dagster `Config` object using `EnvVar`.
-   The processing asset uses the `dagster-duckdb` integration and `DuckDBResource` (currently configured for in-memory).
-   Dagster instance configuration (`dagster.yaml`) uses defaults (likely `~/.dagster`).
-   `workspace.yaml` points Dagster to the code location in `app/assets.py`.
