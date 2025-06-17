# Progress: TCC Monografia - Initial State

## 1. What Works / Completed

-   **Basic Project Structure:** A modular LaTeX project structure is in place with separate directories and `.tex` files for major sections (Introduction, Methodology, Results, Conclusion, Appendices, etc.).
-   **Bibliography File:** `ListadeReferencias.bib` exists for storing references.
-   **Main Document File:** `Monografia.tex` exists, likely serving as the entry point for compilation.
-   **Supporting Files:** Files for generating the cover, acknowledgements, abstract, lists of figures/tables, and table of contents exist.
-   **Initial Memory Bank:** Core files created and populated with baseline info.
-   **Compilation Setup (LaTeX):** Evidence of `latexmk` usage suggests an automated compilation process is likely functional.
-   **Data Pipeline Orchestration (Dagster):**
    -   Added Dagster dependencies (`dagster`, `dagster-duckdb`, `dagster-webserver`) to `app/requirements.txt`.
    -   Refactored ingestion and processing logic into Dagster assets (`raw_tuya_logs`, `staging_tuya_logs`) in `app/assets.py`.
    -   Created helper functions module `app/data_ingestion/ingestion_utils.py`.
    -   Defined a Dagster job (`tuya_processing_job`) targeting both assets.
    -   Defined an hourly schedule (`hourly_schedule`) for the job.
    -   Configured `DuckDBResource` (in-memory) and `TuyaCredentials` Config (using EnvVar) in `app/assets.py`.
    -   Created Dagster instance configuration (`dagster.yaml`) and workspace definition (`workspace.yaml`).
-   **Memory Bank Update:** `activeContext.md`, `systemPatterns.md`, `techContext.md`, and `progress.md` updated to reflect the Dagster implementation.
-   **Streamlit App Enhancement:**
    -   Further simplified the "Perfil de Potência (Análise Multicanal)" tab in `app/streamlit/streamlit_app.py` by removing the "Estatísticas Descritivas do Perfil de Potência", "Perfil de Energia Estimada por Hora do Dia e Dia da Semana", and "Análise de Correlação Multicanal" sections. The Peak Power Analysis section was retained.
    -   Corrected a bug in `app/streamlit/streamlit_app.py` related to `day_of_week` generation to ensure all days are correctly displayed in relevant plots, addressing an issue where plots might only show partial data (e.g., only Saturday/Sunday).
    -   Enriched `tab1` ("Visão Geral") of `app/streamlit/streamlit_app.py` with detailed analyses for Voltage (V) and Current (mA), including key indicators, time series plots, and distribution plots. Tab names were also updated for brevity.
    -   Adjusted the UI in `app/streamlit/streamlit_app.py` to move the "Desenvolvido por Igor Cleto." credit from the sidebar to the bottom of the main page.
    -   **Redesigned Streamlit App for Homeowner Focus:**
        -   Changed app structure from tabs to a multi-page layout ("Resumo da Casa", "Detalhes por Dispositivo", "Análise Avançada") navigated via sidebar.
        -   "Resumo da Casa" page now shows total energy (kWh) for Today, Last 7 Days, and This Month; lists Top 5 energy consuming devices with a bar chart; and includes consolidated power metrics.
        -   "Detalhes por Dispositivo" page displays device-specific energy (kWh) for Today, Last 7 Days, This Month; power metrics (Avg, Max, Min, Estimated Energy); a power time series chart; a daily energy (kWh) chart; and an average hourly power profile chart. It now also includes detailed Voltage and Current analysis (metrics, time series, distribution plots) within collapsible sections for better organization.
        -   Sidebar filters enhanced with predefined period selections (e.g., "Hoje", "Últimos 7 Dias") for easier date range selection, and navigation options now include emojis.
        -   Moved "Desenvolvido por Igor Cleto." attribution to the bottom of the navigation sidebar.
        -   Integrated CEP/SPC analysis (CUSUM chart, fault logs) into the "Análise Avançada" page.
        -   Improved visual separation in "Resumo da Casa" with additional dividers.
        -   Created and loaded `app/streamlit/style.css` to apply custom styles for metrics, headers, and layout, enhancing the visual appeal.
    -   **Performance Optimization & UI Enhancement (Device Controls):**
        -   Used `st.fragment` in `app/streamlit/streamlit_app.py` for the "Controle Individual de Dispositivos" section.
        -   Replaced `st.button` with `st.toggle` for a standard on/off switch interface.
        -   Maintained "optimistic updates" using `st.session_state` with `st.toggle` (via `on_change` callback), ensuring immediate visual feedback and reliable command execution.
        -   Removed the diagnostic caption related to optimistic/actual states.
        -   Corrected `on_off_code` in `app/data/device_mapping.json` for "Repelente" and "Ventilador do quarto" to `"switch_1"` to fix activation issues, aligning them with "Fita de LED".
    -   **Scene Management UI Enhancements & Fixes (Streamlit App):**
        -   Resolved various errors (`NameError`, `IndentationError`, Streamlit widget warnings) in scene management.
        -   Refactored scene creation into a three-step process ("Step 1: Name & Devices", "Step 2: Schedule & Actions", "Step 3: Review & Final Save") managed by `st.session_state`, using `st.form` for the first two input steps. This provides a clearer, more granular workflow and ensures data is pre-filled when navigating back between steps.
        -   Implemented functionality to delete saved scenes, including a confirmation step.
        -   Streamlit app continues to save/load scene definitions (including schedules) to/from `app/data/scheduled_scenes.json`.
        -   Display of saved scenes remains user-friendly with `st.expander` and now includes a delete button.
    -   **Dagster for Scene Scheduling (Initial Setup - Unchanged in this iteration):**
        -   Created `app/dagster/scene_scheduler.py` containing:
            -   `tuya_api_resource`: For Dagster to access Tuya API credentials.
            -   `check_and_trigger_scenes_op`: Reads `scheduled_scenes.json`, checks schedules against current time, and triggers due scenes. Includes basic logic for non-recurring scenes (marking as triggered).
            -   `scene_scheduler_job`: Wraps the op.
            -   `scene_execution_schedule`: Configured to run the job every minute.
        -   Integrated these new Dagster components (job, schedule, resource) into the main `Definitions` object in `app/dagster/data_ingestion/assets.py`.
        -   Corrected import paths and `Definitions` structure in Dagster files.
        -   (Note: Automatic scene triggering by Dagster requires user to enable the schedule in Dagit and ensure Dagster environment is correctly configured with API credentials.)
    -   **Device Control Caching:** Updated `app/streamlit/utils/tuya_api_helpers.py` to ensure that when a device command is sent, the cache for *all* device statuses (`get_device_status`) is cleared. This ensures the "Controle Individual de Dispositivos" section reflects the latest states after any action.
    -   **Scene Deletion Logic (Streamlit App):** Improved the scene deletion process in `app/streamlit/streamlit_app.py`. It now includes a confirmation step and correctly removes the scene from both the session state (`st.session_state.saved_scenes`) and the persistent `scheduled_scenes.json` file. This ensures the "Executar Cena Salva" dropdown accurately reflects the available scenes.
    -   **File Path Robustness (Streamlit App):** Modified `app/streamlit/streamlit_app.py` to use absolute paths for `scheduled_scenes.json` and `style.css`, constructed relative to the script's own directory. This should prevent issues where the app fails to load these files if run from a different working directory, which was likely causing scenes to not appear even if present in the JSON file.
    -   **TCC Monografia - Chapter 3 (Metodologia) Iteratively Enhanced:**
        -   The Methodology chapter (`latex/Metodologia/Metodologia.tex`) was initially detailed and improved, particularly in areas of technology selection rationale, sensor configuration, data pre-processing, CEP application (CUSUM charts), and the validation process in a real-world environment.
        -   Following feedback, Section 3.1 ("Pesquisa e Análise de Tecnologias Existentes") was further expanded to include a comprehensive discussion of alternative energy measurement approaches (custom hardware, other smart plug protocols like Zigbee/Z-Wave/BLE) and a more thorough elaboration of the five key selection criteria in relation to these alternatives.
        -   Added brief explanations of HMAC-SHA256, REST APIs, and HTTP calls at the beginning of subsection 3.2.2 (`Implementação do Agendamento de Cenas com Dagster`) in `latex/Metodologia/Metodologia.tex` for better context on API communication.
        -   Added a new subsubsection 3.2.1.1 (`Biblioteca Pandas e Estrutura DataFrame`) in `latex/Metodologia/Metodologia.tex` to detail the Pandas library and DataFrame structure, including their usage within the project.
    -   **Monograph Flowcharts:** Generated Mermaid code for several flowcharts to illustrate Dagster pipelines and Streamlit app functionalities, ready for conversion to images and inclusion in the LaTeX document. This includes:
        -   Dagster data processing pipeline.
        -   Dagster scene scheduling pipeline.
        -   Streamlit app overall navigation.
        -   Streamlit scene creation process.
        -   Streamlit device control logic.
    -   **Monograph Flowcharts (Update):** Re-inserted `\includegraphics` commands for flowcharts into `latex/Metodologia/Metodologia.tex`, with paths adjusted to point to the `latex/` directory where the user has placed the PNG images. Adjusted width of `streamlit_scene_creation.png` to `0.9\textwidth`.
    -   **TCC Monografia - Chapter 3 (Metodologia) CEP Section Enhancement:** Expanded subsection 3.3.2 ("Análise Estatística e Controle Estatístico de Processos (CEP)") in `latex/Metodologia/Metodologia.tex` with a more detailed introduction to CEP, a step-by-step explanation of CUSUM chart implementation (including mathematical/statistical basis), and added details on its practical implementation and visualization within the Streamlit application.
    -   **TCC Monografia - Chapter 3 (Metodologia) Real-Time Validation Description Enhanced:** Improved section 3.4 ("Validação em Ambiente Real") in `latex/Metodologia/Metodologia.tex` to more explicitly detail and emphasize the validation of the system's real-time (or near real-time) operational aspects. This includes clarifications on testing data pipeline latency, UI responsiveness for controls and data display, timeliness of CEP alerts, and the reliability of scheduled scene execution in a dynamic environment.
    -   **TCC Monografia - Chapter 3 (Metodologia) Viability and Future Work Sections Updated:**
        -   Section 3.5 in `latex/Metodologia/Metodologia.tex` was revised and renamed to "Considerações sobre Viabilidade e Impacto Acadêmico". The content was refocused to emphasize academic relevance and provide an improved description of user benefits, while removing discussions on large-scale adoption strategies and technical scalability.
        -   A new section 3.6, "Trabalhos Futuros e Próximos Passos," was added to `latex/Metodologia/Metodologia.tex`, outlining potential future research directions such as LLM integration for conversational UX, comparison with CEMIG energy bills, predictive consumption modeling, gamification, and further UX/UI enhancements.
    -   **TCC Monografia - Chapter 4 (Resultados) Figure Relocation and Caption Update:**
        -   In `latex/Resultados/Resultados.tex`, the figure previously identified as Figure 4.2 (depicting Dagster scene scheduling UI, labeled `fig:dagster_scene_scheduler`) was removed from its original location within section 4.3.1 (`Pipeline de Dados com Dagster`).
        -   A new subsection 4.2.1, titled "Fluxograma de Execução dos Ativos raw\_tuya\_logs e staging\_tuya\_logs," was created under section 4.2 (`Requisitos do Sistema`).
        -   A figure environment was inserted into this new subsection 4.2.1, featuring the image `Figuras/dagster_data_pipeline_fluxograma.png`.
        -   The caption for this newly placed figure was set to "Fluxograma de execução dos ativos raw\_tuya\_logs e staging\_tuya\_logs."
        -   The label for this figure was set to `fig:fluxograma_raw_staging_assets`.

## 2. What's Left to Build / In Progress

-   **Content Population:** Most `.tex` files likely require significant writing or completion of content specific to the TCC topic. (Requires review of individual `.tex` files).
-   **Figures and Tables:** Inclusion and refinement of all necessary figures and tables.
-   **Bibliography Entries:** Populating `ListadeReferencias.bib` with all required references and ensuring they are cited correctly in the text.
-   **Formatting Refinement:** Ensuring strict adherence to UFMG formatting guidelines.
-   **Review and Revision:** Thorough proofreading, technical review, and revisions based on feedback.
-   **`.clinerules`:** Creation and population of the `.clinerules` file (ongoing).
-   **Memory Bank Refinement:** Updating Memory Bank files with specific project details as work progresses (ongoing).
-   **Dagster Verification:** Starting `dagster dev` and verifying the pipeline runs correctly via UI and schedule.
-   **Data Pipeline Utilization:** Defining and implementing downstream uses for the partitioned Parquet dataset in `app/data/staging/`.

## 3. Current Status Snapshot (as of 2025-04-26)

-   The foundational LaTeX structure and Memory Bank framework are established.
-   The data pipeline (raw JSON -> staging Parquet) is now implemented and orchestrated using Dagster assets, jobs, resources, and schedules.
-   The pipeline is scheduled to run hourly.
-   Memory Bank documentation has been updated to reflect the Dagster implementation.
-   The next immediate step for the data pipeline is to start the Dagster UI/daemon and verify its operation.
-   The core task for the monograph itself remains writing/completing content.

## 4. Known Issues / Blockers

-   **Dagster Runtime:** Potential issues related to environment variables not being accessible to the Dagster process, Python environment inconsistencies, or Dagster daemon/UI startup problems.
-   **API/Network:** Potential failures in the `raw_tuya_logs` asset due to Tuya API rate limits, credential errors, or network connectivity issues.
-   **Data Schema/Mapping:** Potential failures in `staging_tuya_logs` if the raw JSON schema changes unexpectedly or if `device_mapping.json` is missing/corrupt.
-   **Resource Configuration:** The in-memory DuckDB resource will lose state between runs; may need reconfiguration to a file DB if persistence is needed. Dagster instance storage defaults might need adjustment for long-term use.
-   **LaTeX:** Potential issues remain as listed previously (compilation errors, formatting, content completion).
