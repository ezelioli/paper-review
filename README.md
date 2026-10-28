# paper-review

Builds a single-file HTML review copy of a LaTeX paper from its sources:
paper-like typesetting, the planned structure of each section as a pop-over,
paragraph markers that show their plan item, a switcher between plot variants
of each figure, and a switch that hides all review material. The PDF stays the
reference for layout; the page is a reading and review aid.

## What runs where

| Step | Where | What |
|---|---|---|
| `paper-review build` | your machine | copies the paper to `<output dir>/.work`, runs `make4ht` (tex4ht) with a generated configuration, and assembles `index.html` with every image embedded |
| Hosting | anywhere | `index.html` is self-contained: open it locally or put it on any static host |
| Interaction | the reader's browser | CSS and a small script; variant picks and the review switch are remembered per browser |

Nothing is written to the paper's directory; the paper's own sources are used
as they are.

## Requirements

- TeX Live with `make4ht` (tested with TeX Live 2026), plus `pdflatex` and
  `bibtex` when no `.bbl` is given.
- [uv](https://docs.astral.sh/uv/); it installs the Python dependency
  (BeautifulSoup) on first use.
- Optional: Ghostscript, for PDF plot variants (converted to SVG with
  `dvisvgm --pdf`). PNG, JPEG and SVG variants need nothing.

## Use

Put a `paper-review.toml` in the paper directory and run, from there:

```sh
paper-review build                # reads ./paper-review.toml
paper-review build path/to/paper-review.toml -o page.html
paper-review build --fragment     # without <html>/<head>/<body>, for a host page
```

`bin/paper-review` can be linked onto the PATH, e.g.
`ln -s ~/tools/paper-review/bin/paper-review ~/.local/bin/`. In a Makefile,
after the PDF build (so the `.bbl` file is current):

```make
PAPER_REVIEW ?= paper-review

html: paper
	$(PAPER_REVIEW) build
```

The configuration can also live next to the paper instead of inside it.
See `examples/paper-review.toml`.

```toml
paper = "."                 # paper directory (default: this file's)
main = "main.tex"           # main file in the paper directory
bbl = "build/main.bbl"      # optional: reuse the PDF build's bibliography;
                            # otherwise pdflatex + bibtex run in the work copy
output = "build/paper-review/index.html"  # default; relative to this file

[macros]                    # only if the paper uses its own macro names
plan = "reviewplan"         # environment with the planned structure
marker = "reviewmark"       # \marker{n}: paragraph marker for plan item n
todo = ["reviewtodo"]       # commands whose text is a todo

[figures."fig:results"]     # plot variants of the figure with this \label
paper = "bars"              # variant included in the PDF (omit if none yet)
dir = "../plots"            # variant files, relative to this file
variants = { bars = "bars.png", lines = "lines.png" }
```

## The `review` LaTeX package

`tex/review.sty` provides the review commands for the PDF; the HTML build finds
it on its own. To use it in a paper, copy it next to the paper (Overleaf needs
the file in the project) and load it:

```latex
\usepackage{review}          % options: final (hide review material), popups
```

```latex
\begin{reviewplan}           % planned structure of a section
  \begin{enumerate}
    \item \textbf{Setup:} ...
    \item \textbf{Result:} ...
  \end{enumerate}
\end{reviewplan}

\reviewmark{1} First paragraph, written against plan item 1.
\reviewtodo{[todo: add numbers]}

\begin{figure}
  \includegraphics{fig/results.pdf}
  \reviewvariants[bars]{fig:results}{bars=fig/bars.png, lines=fig/lines.png}
  \caption{...}\label{fig:results}
\end{figure}
```

- In the PDF, the plan is shown inline in orange (or as pop-up notes with
  `popups`), markers as orange `[n]`, todos in red. `final` hides plans and
  markers.
- `\reviewvariants[<paper variant>]{<label>}{<name>=<file>, ...}` typesets
  nothing; it lists plot variants for the HTML page (paths relative to the
  paper). Variants can also be listed in the configuration instead.

A paper that already defines its own review macros does not need the package:
name them under `[macros]`. They are then replaced in the HTML build only, and
todo commands keep their own formatting.

## Document classes

tex4ht handles most classes directly (tested: `article`, `llncs`). Classes
it cannot handle are built as `article`, with stand-ins for their own commands
in `tex/classes/<class>.tex` (provided: `IEEEtran`, whose headings tex4ht
does not convert). To support another class, add such a file; it is read with
`\input` right after `article` is loaded. `acmart` currently fails in tex4ht and
has no stand-in yet.

## Limits

- No page layout: single column, no page breaks or float placement.
- Complex tables, TikZ and packages tex4ht does not know may render roughly or
  need a fix in the generated configuration (`tex4ht_cfg` in `paper_review.py`).
- Figures from the paper are converted to images by tex4ht; variants are shown
  as given.
- TeX errors in the HTML build are reported but do not stop it; the page may be
  incomplete where they occur. Details: `<output dir>/.work/pr-html.log`.
- Tested only on macOS with TeX Live 2026, with the `article`, `llncs` and
  `IEEEtran` classes; `acmart` is not supported yet.

## Author and license

Enrico Zelioli. Written with the help of Claude (Anthropic), an AI assistant.
MIT License, see `LICENSE`.
