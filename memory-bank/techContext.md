# Technical Context: TCC Monografia LaTeX Project

## 1. Core Technologies

-   **LaTeX:** Primary typesetting system for the monograph (`latex/` directory).
-   **BibTeX:** Manages bibliographic references (`ListadeReferencias.bib`).
-   **PDF:** Target output format for the monograph (`Monografia.pdf`).
-   **Python:** Used for data ingestion and processing scripts (`app/` directory).
-   **DuckDB:** In-process analytical data management system used for transforming raw JSON to partitioned Parquet (`app/data_processing/`). Replaces `event_time` (ms) with a readable timestamp, performs device name lookup (joining with `device_mapping.json`), adds filename, and partitions output (`PARTITION_BY event_date`).
-   **Parquet:** Columnar storage format for the staging data layer, stored as a partitioned dataset in `app/data/staging/` based on `event_date`. Includes original fields (except ms `event_time`) and enriched columns (readable `event_time`, `device_name`, `filename`).
-   **Pandas:** Used within the processing script to load the `device_mapping.json` into a DataFrame for easy registration as a DuckDB view.

## 2. Development Environment & Tools

-   **Text Editor:** A text editor is used to modify the `.tex` and `.bib` source files (e.g., VS Code, TeXstudio, Overleaf, Sublime Text, etc. - specific editor not confirmed).
-   **LaTeX Compiler:** A command-line tool like `pdflatex` is used to compile the `.tex` source into a PDF.
-   **BibTeX Compiler:** The `bibtex` command-line tool.
-   **LaTeX Automation:** `latexmk` likely used for automating LaTeX compilation.
-   **Python Interpreter:** Required to run `.py` scripts (e.g., Python 3.x).
-   **Package Manager:** `pip` used for managing Python dependencies (`app/requirements.txt`, includes `duckdb`, `pandas`).
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
-   Managing Python dependencies using `app/requirements.txt` (preferably within a virtual environment).
-   DuckDB performance might depend on available memory, especially when processing large volumes of JSON data in memory.
-   The processing script relies on the structure of the raw JSON files (including `device_id` and `event_time`) and the `device_mapping.json` file. Changes to these could break the processing step.
-   Querying the partitioned Parquet dataset in `app/data/staging/` requires tools/libraries that support Hive-style partitioning (e.g., DuckDB, Spark, Pandas with appropriate arguments).
