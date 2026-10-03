# 📁 Output Data Contents

Once the pipeline is run, this folder will contain the following:

- `simulation_output.csv` — simulated data table with random values, written by
  `invoke run-simulation`.
- `figures/figure_simulation/scatter.png` — a plot of the simulated data.
- `figures/figure_simulation/histogram.png` — a histogram of the simulated
  data's values.
- `figures/panel_sizes.json` — the `{panel: (width_mm, height_mm)}` box each
  panel is placed in inside `figure_montage.svg`, written by
  `invoke run-figure-layout`. Read by the notebook via `airoh.figures.panel_size`
  so each panel renders at exactly its placed size.
- `figure_montage.svg` — hand-authored in Inkscape, the single source of truth
  for panel layout. A pipeline **source**, not an output, despite living here:
  its `<image>` links are relative paths that resolve from this directory. See
  `CLAUDE.md`, "Figures: the Inkscape montage pattern".
- `figure_montage.png` — the composed montage, rendered from `figure_montage.svg`
  by `invoke compose-figure` via the Inkscape CLI (skipped with a warning if
  Inkscape isn't installed).
- `figures/summary/authors.csv` — a list of authors from papers found in a
  spreadsheet retrieved from figshare.
- `PROVENANCE.json` — what produced everything above: the project's git commit,
  the environment, the input manifest it consumed, and a checksum of every
  output file. Written by `invoke run`.

📝 Note: each notebook writes into a folder named after itself under
`figures/` (`figures/figure_simulation/`, `figures/summary/`), not directly
under `output_data/`. That folder doubles as the "already ran" marker
`run-notebooks` checks, so a notebook that wrote anywhere else would re-run on
every `invoke run`.

📝 Note: csv and png files in this folder are **ignored by Git** (see
`.gitignore`), so outputs won't be tracked by default. `figure_montage.svg` and
`PROVENANCE.json` are the deliberate exceptions: the SVG is hand-authored
source, not a generated output, and `PROVENANCE.json` is small and is the
record of where the untracked results came from. It changes on every run, by
design.
