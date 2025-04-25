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

### Data Pipeline Architecture (`app/` directory)

Alongside the LaTeX monograph structure, a data processing pipeline exists within the `app/` directory:

-   **Raw Data Storage:** JSON log files are stored in `app/data/raw/`, organized by device ID and date (e.g., `app/data/raw/<device_id>/<date>/<log_file>.json`). Each JSON record *also* contains a `device_id` field added during ingestion.
-   **Processing Script:** A Python script `app/data_processing/process_raw_to_staging.py` uses DuckDB to read all JSON files (including `device_id`), replaces `event_time` (ms) with a readable timestamp format (aliased as `event_time`), looks up `device_name` from `device_mapping.json`, adds the source `filename`, and derives `event_date` (from original ms timestamp).
-   **Staging Data Storage:** The processed data is saved as partitioned Parquet files in `app/data/staging/`, partitioned by `event_date`. Key columns include original fields (except ms `event_time`), `device_id`, `filename`, the readable `event_time`, and `device_name`.

```mermaid
flowchart LR
    subgraph Raw Data
        direction TB
        JSON1[raw/.../*.json]
        JSON2[...]
        JSON3[...]
    end

    subgraph Processing
        direction TB
        Script[process_raw_to_staging.py]
        DuckDB[(DuckDB)]
        Script -- Reads --> JSON1
        Script -- Reads --> JSON2
        Script -- Reads --> JSON3
        Script -- Uses --> DuckDB
    end

    subgraph Staging Data
        direction TB
        PartitionDir[staging/event_date=YYYY-MM-DD/]
        ParquetFile[data.parquet]
        PartitionDir --> ParquetFile
    end

    Raw --> Processing
    Processing -- Writes --> Staging Data
```

## 2. Key Technical Decisions

-   **LaTeX:** Chosen for the monograph typesetting.
-   **BibTeX:** Used for monograph bibliography management.
-   **Modular LaTeX Structure:** Breaking the monograph into smaller `.tex` files.
-   **Python:** Used for data ingestion (`app/data_ingestion/`) and processing (`app/data_processing/`).
-   **DuckDB:** Chosen for efficient in-process querying and transformation of raw JSON data into Parquet.
-   **Parquet:** Selected as the format for the staging data layer due to its efficiency for analytical workloads.

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

### Data Pipeline Workflow

1.  **Data Ingestion:** The `app/data_ingestion/tuya_log_ingestion.py` script fetches logs and saves them as JSON files in `app/data/raw/`, adding a `device_id` field to each log record within the JSON.
2.  **Run Processing Script:** Execute `python app/data_processing/process_raw_to_staging.py`.
3.  **Output:** The script reads raw JSONs, replaces `event_time` with a readable timestamp, adds `filename`, looks up `device_name`, derives `event_date`, and writes/overwrites partitioned Parquet files into `app/data/staging/`, organized by `event_date`.
4.  **Consume Staged Data:** Use the partitioned Parquet dataset in `app/data/staging/` (containing original fields (except ms `event_time`), `device_id`, `filename`, readable `event_time`, `device_name`) for downstream tasks.

## 4. Potential Areas for Rules (.clinerules)

-   Consistent figure/table placement and captioning style.
-   Specific citation format requirements (if any beyond standard BibTeX styles).
-   Naming conventions for labels (`\label{fig:name}`, `\label{sec:name}`).
-   Preferred LaTeX packages or custom commands.
