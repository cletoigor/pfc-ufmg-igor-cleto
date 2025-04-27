# Technical Context: TCC Monografia LaTeX Project

## 1. Core Technologies

-   **LaTeX:** Primary typesetting system for the monograph (`latex/` directory).
-   **BibTeX:** Manages bibliographic references (`ListadeReferencias.bib`).
-   **PDF:** Target output format for the monograph (`Monografia.pdf`).
-   **Python:** Used for data pipeline logic within Dagster assets (`app/assets.py`, `app/data_ingestion/ingestion_utils.py`).
-   **Dagster:** Orchestration framework (`dagster` package).
    -   **`dagster-webserver`:** Provides the Dagit UI for monitoring and interaction.
    -   **`dagster-duckdb`:** Integration for using DuckDB as a resource.
-   **DuckDB:** In-process analytical data management system used via `DuckDBResource` within the `staging_tuya_logs` asset for transforming raw JSON to partitioned Parquet. Logic includes replacing `event_time`, joining `device_name`, adding `filename`, and partitioning.
-   **Parquet:** Columnar storage format for the staging data layer (`app/data/staging/`), partitioned by `event_date`.
-   **Pandas:** Used within the `staging_tuya_logs` asset to load `device_mapping.json` into a DataFrame for registration as a DuckDB view.
-   **Tuya Connector (`tuya-connector-python`):** Used by the `raw_tuya_logs` asset to interact with the Tuya Cloud API.
-   **Dotenv (`python-dotenv`):** Used to load environment variables (e.g., API keys) for Dagster configuration.

## 2. Development Environment & Tools

-   **Text Editor:** A text editor is used to modify the `.tex` and `.bib` source files (e.g., VS Code, TeXstudio, Overleaf, Sublime Text, etc. - specific editor not confirmed).
-   **LaTeX Compiler:** A command-line tool like `pdflatex` is used to compile the `.tex` source into a PDF.
-   **BibTeX Compiler:** The `bibtex` command-line tool.
-   **LaTeX Automation:** `latexmk` likely used for automating LaTeX compilation.
-   **Python Interpreter:** Required to run Dagster assets and UI (e.g., Python 3.x).
-   **Package Manager:** `pip` used for managing Python dependencies (`app/requirements.txt`, includes `dagster`, `dagster-duckdb`, `dagster-webserver`, `duckdb`, `pandas`, `tuya-connector-python`, `python-dotenv`). Managed within a virtual environment (`app/.venv/`).
-   **Dagster CLI:** Command-line interface for interacting with Dagster (e.g., `dagster dev`).
-   **Dagit:** Web-based UI for Dagster (started via `dagster dev`).
-   **Version Control:** Git (`.gitignore` exists).
-   **Operating System:** macOS.

## 3. Key LaTeX Packages (Potential/Common)

*(This section should be updated based on reviewing `Monografia.tex` preamble)*
Common packages for academic writing often include:
-   `inputenc` (e.g., `utf8`)
-   `fontenc` (e.g., `T1`)
-   `babel` (e.g., `brazil`)
-   `graphicx` (for including images)
-   `amsmath`, `amssymb` (for mathematical symbols and environments)
-   `geometry` (for page layout/margins)
-   `hyperref` (for clickable links/references)
-   `caption` (for customizing figure/table captions)
-   `booktabs` (for professional-looking tables)
-   Specific UFMG template packages (if applicable).

## 4. Technical Constraints & Considerations

-   Requires a working LaTeX distribution installed on the system.
-   Compilation errors can be cryptic and require debugging `.log` files (`Monografia.log`).
-   Maintaining consistency in formatting and style across different `.tex` files.
-   Ensuring all necessary fonts are available for LaTeX.
-   Managing figure file paths correctly for LaTeX.
-   Managing Python dependencies using `app/requirements.txt` within a virtual environment (`app/.venv/`).
-   Requires environment variables (`ACCESS_ID`, `ACCESS_SECRET`, `API_ENDPOINT`) to be set for the `raw_tuya_logs` asset to connect to the Tuya API. These are loaded via `.env` and configured in `app/assets.py`.
-   The `staging_tuya_logs` asset relies on the structure of the raw JSON files produced by `raw_tuya_logs` and the `device_mapping.json` file. Changes to these could break the asset.
-   The `DuckDBResource` is currently configured for an in-memory database. For persistence across runs or external querying, it might need reconfiguration to use a file-based database.
-   Dagster instance data (runs, schedules) defaults to storage in `~/.dagster` unless `DAGSTER_HOME` is set or `dagster.yaml` is configured for specific storage locations.
-   The Dagster daemon process needs to be running (usually started by `dagster dev`) for schedules to be active.
-   Querying the output partitioned Parquet dataset in `app/data/staging/` requires tools/libraries that support Hive-style partitioning.
