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

## 2. Key Technical Decisions

-   **LaTeX:** Chosen as the typesetting system, suitable for academic documents with complex formatting, equations, and references.
-   **BibTeX:** Used for managing citations and generating the bibliography.
-   **Modular Structure:** Breaking the document into smaller `.tex` files improves manageability.

## 3. Workflow Pattern

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

## 4. Potential Areas for Rules (.clinerules)

-   Consistent figure/table placement and captioning style.
-   Specific citation format requirements (if any beyond standard BibTeX styles).
-   Naming conventions for labels (`\label{fig:name}`, `\label{sec:name}`).
-   Preferred LaTeX packages or custom commands.
