# Technical Context: TCC Monografia LaTeX Project

## 1. Core Technologies

-   **LaTeX:** The primary typesetting system used for document creation. The specific distribution (e.g., TeX Live, MiKTeX) is not yet confirmed but is likely one of these standard distributions.
-   **BibTeX:** Used for managing bibliographic references stored in `ListadeReferencias.bib` and formatting citations within the document.
-   **PDF:** The target output format (`Monografia.pdf`).

## 2. Development Environment & Tools

-   **Text Editor:** A text editor is used to modify the `.tex` and `.bib` source files (e.g., VS Code, TeXstudio, Overleaf, Sublime Text, etc. - specific editor not confirmed).
-   **LaTeX Compiler:** A command-line tool like `pdflatex` is used to compile the `.tex` source into a PDF.
-   **BibTeX Compiler:** The `bibtex` command-line tool is used to process the bibliography.
-   **Automation:** `latexmk` appears to be used (based on `.fdb_latexmk`, `.fls` files) to automate the multi-pass compilation process (pdflatex -> bibtex -> pdflatex -> pdflatex).
-   **Version Control:** (Optional but recommended) A system like Git might be used for tracking changes, although not explicitly indicated by the current file list.
-   **Operating System:** macOS (as indicated by the environment details).

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
-   Ensuring all necessary fonts are available.
-   Managing figure file paths correctly relative to the main `.tex` file or using appropriate packages (`graphicx`'s `\graphicspath`).
