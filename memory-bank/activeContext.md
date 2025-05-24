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
    -   **Performance Improvement (Device Controls):**
        -   Refactored the "Controle Individual de Dispositivos" section in `app/streamlit/streamlit_app.py` to use `st.fragment`.
        -   Created a `device_control_fragment(device_info)` function decorated with `@st.fragment` to handle the UI and interaction logic for a single device.
        -   Replaced `st.button` with `st.toggle` for device controls within the fragment, providing a standard on/off switch interface.
        -   Maintained the "optimistic update" pattern using `st.session_state` with `st.toggle`. This ensures the toggle visually changes state immediately upon user interaction, providing instant UI feedback, while the actual API command is sent. If the API command fails, the toggle state reverts.
        -   Removed the diagnostic caption previously used for observing optimistic vs. actual states.
        -   Updated `app/data/device_mapping.json` to change `on_off_code` for "Repelente" and "Ventilador do quarto" to `"switch_1"` (matching "Fita de LED") to address activation issues.
        -   These changes further enhance the usability and responsiveness of device controls.
    -   **Scene Management UI Refactor & Enhancements:**
        -   Corrected various errors (`NameError`, `IndentationError`, Streamlit widget warnings) in scene management.
        -   Refactored scene creation into a more granular three-step process using `st.session_state` to manage flow:
            1.  **Step 1 (Name & Devices):** Form to input scene name and select devices. Button: "Próximo: Definir Horário e Ações".
            2.  **Step 2 (Schedule & Actions):** Form to define schedule (time, days, recurrence) and device actions (Ligar/Desligar). Buttons: "Voltar (Nome e Dispositivos)" and "Próximo: Revisar Cena".
            3.  **Step 3 (Review & Final Save):** Displays a summary of all defined details. Buttons: "Modificar Detalhes" (returns to Step 1, pre-filling data) and "Salvar Cena Definitivamente".
        -   Ensured temporary scene data is pre-filled when navigating back between steps.
        -   Implemented functionality to delete saved scenes, including a confirmation step.
        -   Streamlit app continues to save/load scene definitions (including schedules) to/from `app/data/scheduled_scenes.json`.
        -   Display of saved scenes remains user-friendly with `st.expander` and now includes a delete button.
    -   **Dagster for Scene Scheduling (Initial Setup - Unchanged in this iteration):**
        -   Created `app/dagster/scene_scheduler.py` containing:
            -   `tuya_api_resource`: For Dagster to access Tuya API credentials.
            -   `check_and_trigger_scenes_op`: Reads `scheduled_scenes.json`, checks schedules, and triggers due scenes. Includes basic logic for non-recurring scenes.
            -   `scene_scheduler_job`: Wraps the op.
            -   `scene_execution_schedule`: Schedules the job to run every minute.
        -   Updated `app/dagster/data_ingestion/assets.py` to include these new Dagster components in the main `Definitions` object.
        -   Corrected import paths and `Definitions` structure in Dagster files.
    -   **Caching for Device Controls:** Modified `app/streamlit/utils/tuya_api_helpers.py` so that `send_device_command` clears the entire cache for `get_device_status`. This ensures that after a device action, all device statuses in the "Controle Individual de Dispositivos" section are refreshed from the API on their next display.
    -   **Scene Deletion Logic:** Improved scene deletion in `app/streamlit/streamlit_app.py`. Deletion now involves a confirmation step and correctly removes the scene from both `st.session_state.saved_scenes` and the `scheduled_scenes.json` file, ensuring the "Executar Cena Salva" list is accurate.
    -   **File Path Robustness (Streamlit):** Modified `app/streamlit/streamlit_app.py` to use absolute paths for `scheduled_scenes.json` and `style.css` by constructing them based on the script's directory. This resolves issues where these files might not be found if the app is run from a different working directory.

## 3. Next Steps

-   Refine content and visualizations on the "Resumo da Casa" and "Detalhes por Dispositivo" pages.
-   Populate the "Análise Avançada" page with relevant technical charts if needed.
-   Thoroughly test the redesigned Streamlit application, including scene creation with schedules.
-   Discuss and decide on the implementation strategy for automatic scene triggering based on saved schedules (e.g., in-app limited polling, Dagster integration, or other backend service). **Current: Dagster setup for scene scheduling is complete.**
-   User to test Dagster scene scheduling:
    - Ensure Tuya API env vars are available to Dagster.
    - Reload Dagster definitions in Dagit.
    - Enable `scene_execution_schedule`.
    - Create a scheduled scene in Streamlit and observe Dagster logs.
-   Address timezone handling and robustness of non-recurring scene logic in Dagster op as future enhancements.
-   Update `memory-bank/systemPatterns.md` and `memory-bank/progress.md` to reflect the Streamlit app redesign and new Dagster-based scheduling capabilities.
-   Start the Dagster UI (`dagster dev`) to visualize all assets, jobs, and schedules.
-   Verify both the hourly Dagster data pipeline schedule and the per-minute scene execution schedule are active and run as expected.
-   Continue work on the TCC Monografia LaTeX content as needed.

## 4. Active Decisions & Considerations

-   The data pipeline is now orchestrated by Dagster.
-   The ingestion and processing steps are defined as separate assets (`raw_tuya_logs`, `staging_tuya_logs`) with an explicit dependency.
-   Helper functions for ingestion are kept separate in `app/data_ingestion/ingestion_utils.py`.
-   The pipeline is scheduled to run hourly via `ScheduleDefinition`.
-   Tuya API credentials and mapping file path for ingestion are configured via a Dagster `Config` object using `EnvVar`.
-   The processing asset uses the `dagster-duckdb` integration and `DuckDBResource` (currently configured for in-memory).
-   Dagster instance configuration (`dagster.yaml`) uses defaults (likely `~/.dagster`).
-   `workspace.yaml` points Dagster to the code location in `app/dagster/data_ingestion/assets.py` (assuming this was implicitly corrected, as `app/assets.py` did not exist).
