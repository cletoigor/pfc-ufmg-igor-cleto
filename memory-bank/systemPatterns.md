# System Patterns: TCC Monografia LaTeX Structure

## 1. Overall Architecture

The "system" is the TCC monograph document and its generation process. The architecture is based on a modular LaTeX project structure.

-   **Main File:** `Monografia.tex` serves as the root document. It likely includes preamble settings (packages, document class, metadata) and uses `\input{}` or `\include{}` commands to bring in content from other files.
-   **Content Modules:** The document is broken down into logical sections, each residing in its own directory and `.tex` file (e.g., `Introducao/Introducao.tex`, `Metodologia/Metodologia.tex`, `Resultados/Resultados.tex`, `Conclusao/Conclusao.tex`). This promotes organization and allows focused editing.
-   **Supporting Elements:**
    -   `Capa/capa.tex`: Title page elements.
    -   `Agradecimentos/Agradecimentos.tex`: Acknowledgements section.
    -   `Resumo/Resumo.tex`, `Resumo/Abstract.tex`: Abstract in Portuguese and English.
    -   `ListaFiguras/ListaFiguras.tex`: Generates the List of Figures.
    -   `ListaTabelas/ListaTabelas.tex`: Generates the List of Tables.
    -   `TabelaConteudo/TabelaConteudo.tex`: Generates the Table of Contents.
    -   `Apendices/`: Directory for appendices (`ApendiceA.tex`, `ApendiceB.tex`).
-   **Bibliography:** `ListadeReferencias.bib` stores bibliographic entries, managed by BibTeX.
-   **Figures:** Figures seem to be organized within subdirectories of the relevant content modules (e.g., `DescricaoProcesso/Figuras/`, `Metodologia/Figuras/`).

### Data Pipeline Architecture (`app/` directory with Dagster)

Alongside the LaTeX monograph structure, a data processing pipeline exists within the `app/` directory, orchestrated by Dagster:

-   **Orchestration:** Dagster (`dagster`, `dagster-webserver`) manages the pipeline execution, scheduling, and monitoring. Configuration is handled via `dagster.yaml` and `workspace.yaml` in the project root.
-   **Code Location:** Asset, job, schedule, and resource definitions reside in `app/assets.py`. Helper functions for ingestion are in `app/data_ingestion/ingestion_utils.py`.
-   **Ingestion Asset (`raw_tuya_logs`):**
    -   Fetches logs from the Tuya API using `tuya-connector-python`.
    -   Uses helper functions from `ingestion_utils.py`.
    -   Adds `device_id` and ingestion metadata.
    -   Saves raw logs as JSON files in `app/data/raw/`, organized by device ID and date (`app/data/raw/<device_id>/<YYYY-MM-DD>/<log_file>.json`).
    -   Returns the absolute path to the `app/data/raw/` directory.
-   **Processing Asset (`staging_tuya_logs`):**
    -   Depends on `raw_tuya_logs` (receives the raw data path as input).
    -   Uses the `dagster-duckdb` integration with a `DuckDBResource` (currently in-memory).
    -   Reads all JSON files from the input path.
    -   Loads device mapping (`app/data_ingestion/device_mapping.json`) using Pandas and registers it as a DuckDB view.
    -   Transforms data: replaces `event_time` (ms) with a readable timestamp, adds `filename`, joins `device_name`.
    -   Derives `event_date` for partitioning.
    -   Saves processed data as partitioned Parquet files in `app/data/staging/`, partitioned by `event_date`.
    -   Returns the absolute path to the `app/data/staging/` directory.
-   **Job (`tuya_processing_job`):** Defines the execution graph containing both assets.
-   **Schedule (`hourly_schedule`):** Triggers the `tuya_processing_job` to run every hour (`0 * * * *`).

```mermaid
graph TD
    subgraph Dagster Orchestration
        direction LR
        Schedule[Hourly Schedule (0 * * * *)] --> Job(tuya_processing_job)
    end

    subgraph Job Execution
        direction TB
        Asset1[raw_tuya_logs Asset] --> Asset2[staging_tuya_logs Asset]
        Asset1 -- Reads --> TuyaAPI[(Tuya Cloud API)]
        Asset1 -- Writes --> RawData[app/data/raw/.../*.json]
        Asset2 -- Reads --> RawData
        Asset2 -- Uses --> DuckDB[(DuckDBResource)]
        Asset2 -- Reads --> Mapping[app/data_ingestion/device_mapping.json]
        Asset2 -- Writes --> StagingData[app/data/staging/event_date=YYYY-MM-DD/data.parquet]
    end

    Job --> Asset1

```

## 2. Key Technical Decisions

-   **LaTeX:** Chosen for the monograph typesetting.
-   **BibTeX:** Used for monograph bibliography management.
-   **Modular LaTeX Structure:** Breaking the monograph into smaller `.tex` files.
-   **Python:** Used for data pipeline logic within Dagster assets.
-   **Dagster:** Chosen for pipeline orchestration, scheduling, and monitoring.
    -   `dagster-duckdb`: Integration for using DuckDB within assets.
    -   `dagster-webserver`: Provides the Dagit UI.
-   **DuckDB:** Used via `DuckDBResource` for efficient in-process querying and transformation of raw JSON data into Parquet within the `staging_tuya_logs` asset.
-   **Parquet:** Selected as the format for the staging data layer (`app/data/staging/`), partitioned by `event_date`.
-   **Pandas:** Used to load the device mapping JSON for registration as a DuckDB view.

## 3. Workflow Patterns

### LaTeX Monograph Workflow

1.  **Edit Content:** Modify the relevant `.tex` file for a specific section.
2.  **Add Figures/Tables:** Place image files in appropriate `Figuras/` directories and use LaTeX commands (`\includegraphics`, `\begin{figure}`, `\begin{table}`) to include them.
3.  **Add Citations:** Add citation keys (e.g., `\cite{key}`) in the text, ensuring the corresponding entry exists in `ListadeReferencias.bib`.
4.  **Compile:** Run the LaTeX compiler (e.g., `pdflatex`) on `Monografia.tex`. This typically requires multiple passes:
    -   `pdflatex Monografia.tex` (generates `.aux` files)
    -   `bibtex Monografia` (processes citations using `.aux`, generates `.bbl`)
    -   `pdflatex Monografia.tex` (includes bibliography)
    -   `pdflatex Monografia.tex` (ensures cross-references are correct)
    *Note: Tools like `latexmk` (indicated by `.fdb_latexmk`, `.fls` files) automate this multi-pass compilation.*
5.  **Review:** Check the output `Monografia.pdf` for correctness and formatting.

### Data Pipeline Workflow (Dagster)

1.  **Start Dagster:**
    -   Ensure the Python environment with dependencies (`app/requirements.txt`) is active.
    -   Ensure necessary environment variables (`ACCESS_ID`, `ACCESS_SECRET`, `API_ENDPOINT`) are set (e.g., in `app/.env`).
    -   Run `dagster dev` from the project root (`/Users/igorcleto/Documents/UFMG/PFC/PFC_1_igor_cleto`). This starts the Dagit UI and the Dagster daemon (which manages schedules).
2.  **Monitor & Trigger:**
    -   Access the Dagit UI (usually `http://localhost:3000`).
    -   Observe the `tuya_data` asset group and the `hourly_schedule`.
    -   The schedule will automatically trigger the `tuya_processing_job` every hour.
    -   Alternatively, manually trigger a run of the `tuya_processing_job` from the UI.
3.  **Execution:**
    -   Dagster executes the `raw_tuya_logs` asset.
        - Fetches data from Tuya API.
        - Saves raw JSON files to `app/data/raw/`.
        - Passes the raw data path to the downstream asset.
    -   Dagster executes the `staging_tuya_logs` asset.
        - Reads raw JSONs from the path provided by the upstream asset.
        - Uses the DuckDB resource to process data.
        - Writes partitioned Parquet files to `app/data/staging/`.
4.  **Consume Staged Data:** Use the partitioned Parquet dataset in `app/data/staging/` for downstream tasks (analysis, visualization, potentially feeding into the monograph).

## 4. Potential Areas for Rules (.clinerules)

-   Consistent figure/table placement and captioning style.
-   Specific citation format requirements (if any beyond standard BibTeX styles).
-   Naming conventions for labels (`\label{fig:name}`, `\label{sec:name}`).
-   Preferred LaTeX packages or custom commands.
