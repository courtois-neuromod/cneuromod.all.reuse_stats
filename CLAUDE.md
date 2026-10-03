# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is the `airoh-mini` template — a starting point for structuring a reproducible data analysis. It is built on the [`invoke`](https://www.pyinvoke.org/) task runner. The `airoh` pip package provides reusable invoke tasks; this repo customizes them via `tasks.py` and `invoke.yaml`.

## Persona

Respond as Uncle Airoh: patient, warm, and wise. Assume the user may be new to coding. Explain errors gently, encourage before correcting, and frame tradeoffs as learning opportunities. When things get heated, offer a calming cup of jasmine tea.

## Setup

```bash
# uv (recommended):
uv sync

# pip:
pip install -r requirements.txt

# conda:
conda env create -n airoh_env -f environment.yml && conda activate airoh_env
```

## Common Commands

With `uv`:
```bash
uv run invoke fetch           # Download source data, record the input manifest
uv run invoke run             # Full pipeline (cached: skips steps whose output exists)
uv run invoke run --force     # Clean everything first, then run from scratch
uv run invoke run-smoke       # Fast end-to-end check that the plumbing works
uv run invoke run-notebooks   # Execute notebooks, save figures to output_data/figures/
uv run invoke run-figure-layout # Write the montage's panel geometry to panel_sizes.json (always re-runs)
uv run invoke compose-figure  # Render figure_montage.svg to PNG with Inkscape (optional binary)
uv run invoke verify          # Check code, config, data and docs still agree
uv run invoke clean           # Remove output_data/ contents
uv run invoke --list          # Show all available tasks
```

Without `uv` (activate your environment first):
```bash
invoke fetch              # Download source data (configured in invoke.yaml under files:)
invoke run                # Full pipeline (cached: skips steps whose output exists)
invoke run --force        # Clean everything first, then run from scratch
invoke run-smoke          # Fast end-to-end check that the plumbing works
invoke run-notebooks      # Execute notebooks, save figures to output_data/figures/
invoke run-figure-layout  # Write the montage's panel geometry to panel_sizes.json (always re-runs)
invoke compose-figure     # Render figure_montage.svg to PNG with Inkscape (optional binary)
invoke verify              # Check code, config, data and docs still agree
invoke clean              # Remove output_data/ contents
invoke --list             # Show all available tasks
```

## Architecture

**Always read `tasks.py` first** before proposing or implementing any pipeline change — it is the authoritative source of what tasks exist, how they are wired, and what parameters they accept.

**Execution flow:** `invoke run` triggers the project's analysis pipeline by calling each step in its body, in order. The permanent tasks — `fetch`, `run`, `verify`, `clean` — are always present; intermediate steps are project-specific.

**`pre=` chains do not fire when a task is called as a function.** A `pre=` list only runs when invoke executes that task from the command line. `run(c)` or `clean(c)` called from Python executes the body alone — so a `clean` whose real work lives entirely in `pre=` deletes nothing when `run --force` calls it, silently and with a success message. Umbrella tasks that other tasks call therefore do their work in the body. Keep `pre=` only where the task is a command-line entry point (`run-notebooks` depending on the step that produces its input), and remember that anything threading a flag through — `--force`, `--smoke`, a chunk selector — must call its steps directly, since a `pre=` chain has already run by the time the body sees the flag.

**Fetching data — download or symlink:** each data asset in `files:` gets its own `fetch-{name}` task wrapping `airoh.acquisition.fetch_data`, which makes the asset available in one of two ways: **download** from its `url` (default), or **symlink** to already-present data when a source path is given — via `invoke fetch-{name} --source /path` (add `--copy` for a real copy) or a per-asset `source:` key in `invoke.yaml`. The umbrella `fetch` task calls every `fetch-{name}` and exposes a per-asset `--{name}-source` flag that it routes to the matching one. This avoids re-downloading data that already lives on disk (a shared dataset, a sibling repo). Symlinks handle both files and whole directories, and the operation is idempotent. When wiring fetch tasks for a new project, prefer `fetch_data` over the lower-level `download_data`.

**One asset, one `--source`:** `fetch_data`'s `source` is a single path bound to the single asset named in the call — never a root directory joined with each asset's filename. That is why each asset gets its own `fetch-{name}` task with its own `--source`, and the umbrella `fetch` routes named `--{name}-source` flags rather than one shared `--source`. Do **not** forward a single shared `--source` to several `fetch_data` calls: it links every asset to the same path and fails silently, printing a success line per asset and exiting 0.

See **Data** below for datalad datasets, sensitive data, and recording asset versions.

- `invoke.yaml` — all path and data config (`output_data_dir`, `source_data_dir`, `notebooks_dir`, `files:` for data assets — each with `output_file` plus `url` to download and/or `source` to symlink)
- `tasks.py` — project-specific invoke tasks; imports reusable tasks from `airoh` (`airoh.acquisition` for data fetching, `airoh.utils` for general helpers)
- `analysis/` — pure Python analysis logic, called by tasks in `tasks.py`
- `notebooks/` — Jupyter notebooks executed by `run_notebooks` via `airoh.utils.run_notebooks`; notebooks receive `OUTPUT_DATA_DIR`, `SOURCE_DATA_DIR` and `FIGURES_DIR` as environment variables, and write into `FIGURES_DIR/{notebook_stem}/`, not directly under `output_data/`
- `source_data/CONTENT.md` and `output_data/CONTENT.md` — authoritative docs for what each data folder contains; update these when data assets change, do not duplicate their content elsewhere
- `.claude/skills/` — each skill exists twice: as a directory (the source you edit) and as a `.zip` (what gets copied into projects created from this template). **Re-zip after editing a skill**, or projects keep receiving the old version — this has already happened once: `cd .claude/skills && zip -qr <name>.zip <name> -x '*/.*'`

**Analysis vs. notebooks:** Heavy computation belongs in `analysis/` Python code, invoked by `run-{name}` tasks, which write results to `output_data/`. Notebooks are for visualization only — they read from `output_data/` and produce figures. This keeps notebooks fast and focused.

**Idempotent tasks:** Each `run-{name}` task must check whether its outputs already exist and skip execution if they do. This means `invoke run` can be called repeatedly during development of a later step — earlier steps are skipped automatically.

**Caching is by existence, and forcing is a sledgehammer.** A step skips when its output file is there; nothing compares timestamps or hashes against its inputs. That is a deliberate ceiling on complexity — a real dependency graph is more than this template wants to explain, and a cache nobody understands is worse than one that is occasionally too eager. The consequence is that **editing a script or a notebook does not invalidate anything**: the pipeline will happily skip the step you just changed. Two ways out, both explicit:

- `invoke clean-{name}` then `invoke run` — redo one step.
- `invoke run --force` — clean everything, then run from scratch.

When results start looking stale or inconsistent, reach for `--force` rather than trying to reason about what is cached. Do not add content-hash invalidation or a dependency graph to `run`; that is the workflow-engine road, and this template deliberately stops short of it.

**Notebook outputs must live in the notebook's own folder.** `run-notebooks` treats `{figures_base}/{notebook_stem}/` as the "already ran" marker for each notebook. A notebook that writes anywhere else never creates its marker and therefore re-runs on every single `invoke run`, however cheap the rest of the pipeline is.

**Figures: the Inkscape montage pattern.** `output_data/figure_montage.svg` is hand-authored in Inkscape and is the **single source of truth for panel layout** — it links each notebook panel by relative path resolved from `output_data/` (e.g. `output_data/figures/figure_simulation/scatter.png`), and the box it places a panel in is that panel's true on-page size. `run-figure-layout` (`airoh.figures.figure_layout`) reads those boxes out of every entry in `invoke.yaml`'s `figures:` mapping and writes them to `output_data/figures/panel_sizes.json` on **every** `invoke run`; `figure_simulation.ipynb` calls `airoh.figures.panel_size(name, default)` to render each panel at exactly that size, so placement is 1:1 and text is never stretched. `compose-figure` (`airoh.figures.compose_figure`) then renders the montage to `figure_montage.png` via the Inkscape CLI, an optional system binary: a missing `inkscape` warns and skips the export rather than failing `invoke run`.

Resizing a box only fully takes effect after the panel it belongs to is re-rendered — and that panel is a notebook output, so it obeys the same existence-based caching as everything else (see **Caching is by existence**, above). `panel_sizes.json` and the composed montage update on every `invoke run` regardless, but a panel whose notebook did *not* re-run keeps its old pixel size, so Inkscape stretches it into the new box — precisely the problem this pattern exists to avoid. After resizing a box, run `invoke clean-figures && invoke run` (or `invoke run --force`) so the affected panel actually redraws at the new size.

Two rules that must be kept wherever a notebook renders a montage panel: **never** pass `bbox_inches="tight"` (it resizes the canvas after the fact, which is exactly what breaks the 1:1 guarantee) — use `layout="constrained"` to reclaim margins inside the fixed canvas instead — and always save at the montage's DPI, so saved pixels equal `figsize × dpi`. That DPI is not hardcoded in the notebook: `run-notebooks` reads it from `figures:` (→ `figure_montage.dpi`, default 300) via the `montage_dpi` helper in `tasks.py` and exports it as `FIGURE_MONTAGE_DPI`, which the notebook reads. Composing the montage at a different resolution therefore re-sizes the panels with it, instead of silently breaking placement.

`run-figure-layout` is a deliberate exception to the existence-based caching described above: it always re-runs, because it is cheap and a box resized in Inkscape must take effect on the very next `invoke run`, not only after a `clean`.

**Task naming conventions:**
- Fetch tasks are named `fetch-{name}` (e.g. `fetch-papers`), one per data asset; the umbrella `fetch` calls them all and routes a `--{name}-source` flag to each.
- Analysis tasks are named `run-{name}` (e.g. `run-preprocessing`, `run-model`).
- Cleaning tasks mirror them: `clean-{name}` removes only the outputs of the corresponding step. Granular clean tasks are what make a selective re-run possible, so every run step needs one.
- The top-level `clean` task calls all `clean-{name}` tasks for **analysis** steps in its body — it only ever touches `output_data/`. Source assets have their own mirrored `clean-{name}` tasks (e.g. `clean-papers`) plus an umbrella `clean-source`, kept separate from `clean` since removing a source asset is a deliberate act (e.g. before re-pointing a stale symlink with `fetch-{name} --source`), not something `run --force` should ever do implicitly.
- The top-level `run` task calls all steps in its body, in order.
- `verify` checks the project against its own documentation; see **Verification**.

**Task parameters:** `run-{name}` tasks should expose chunk or subset parameters (e.g. a subject ID, a chunk index) so that individual pieces can be rerun in isolation. They should also support a `smoke` flag for a fast minimal run useful for testing the pipeline end-to-end without running the full analysis.

## Data

### Where data lives

`source_data/` holds inputs and nothing else; `output_data/` holds what the
pipeline computed. Neither is a scratch directory — a file that is neither a
declared input nor a produced output does not belong in either.

Both folders are **gitignored by default**, and that default is the right one:
data has its own distribution channel (a URL, a datalad dataset, a shared
filesystem), and git is bad at large binaries in a way that cannot be undone —
a big file committed once stays in the history forever. Track an output only
when it is small, diffable, and genuinely useful to read in a pull request: a
metrics table, yes; a NIfTI volume or a multi-megabyte figure, no. When a
project does start tracking outputs, keep a **guard line** in the folder's
`.gitignore` for the file types that must never be committed there, even if
nothing currently produces them:

```gitignore
# Guard: no step writes NIfTI here, but keep this so a stray volume can never
# be committed by accident.
*.nii.gz
```

`invoke verify` enforces the same idea mechanically — it fails on a tracked
file over ~10 MB or of a known-binary type — but a guard line documents the
intent at the place someone would otherwise break it.

### Datalad datasets, and plain assets

`--source` symlinks or copies a plain file or folder and does **not** run
`datalad get`. Symlinking a datalad dataset exposes only content that is
already present — un-fetched files are broken symlinks. So for a real datalad
dataset use `airoh.datalad` instead of `fetch_data`, configured under
`datasets:` in `invoke.yaml` (either `{name: output_dir}` or `{name: {output_dir,
url, source}}`):

- `install_dataset(c, name, source=None)` — make the checkout available:
  symlink an existing checkout at `source` (dataset tree only, does not
  `datalad get`), or `datalad clone` from `url`. No-op if `output_dir` already
  exists.
- `get_data(c, name, path=None, recursive=False, strict=False)` — retrieve
  content (the whole dataset, or just `path`). Tolerant of partial failures by
  default; `--strict` raises instead (use in the smoke test).
- `update_dataset(c, name, strict=False)` — advance an installed dataset's pin
  via `datalad update --merge`, without pulling content.
- For a plain git submodule (not datalad-backed), use
  `airoh.acquisition.ensure_submodule` instead.

A project with its own analysis-specific prefetch step (e.g. "get every file
matching this glob that a `run-*` step reads") composes it from
`airoh.datalad.prefetch_pattern` plus `load_known_failures`/
`save_known_failures` rather than reimplementing the glob/skip/get/reclassify
loop — see the `airoh` API reference for the full signatures.

Three things bite projects working with real datalad superdatasets:

- **Subdatasets nest.** A derivative folder is often a subdataset inside
  another subdataset, and plain `git submodule update --init` cannot reach one:
  it only sees the top level. `airoh.datalad.install_subdataset` (`datalad get
  -n <path>` under the hood) installs the intermediate dataset and the nested
  one in a single call, without pulling content, and without touching large
  sibling subdatasets.
- **Retrieval is partial and must be tolerant.** Content on credentialed
  remotes fails per-file for anyone without access. A fetch that aborts on the
  first inaccessible file is useless to collaborators with partial access:
  warn, skip, and carry on with whatever is reachable — every `airoh.datalad`
  retrieval function does this by default. Fail loudly only in the smoke test
  (`strict=True`), where an empty result means the plumbing is broken.
- **The annex version matters.** A repository in annex v10 format is simply
  refused by an older `git-annex`, and the failure looks like "no content
  anywhere" rather than an error. Pin it as a declared project dependency (the
  `git-annex` PyPI package bundles a recent binary) instead of writing a README
  note nobody reads.

**Gathering assets is a separate job from reproducing results.** `fetch`
retrieves; `run` reads what is already on disk and never pulls. That split is
what makes `run` fast, offline-capable, and honest about what it depends on. A
`run` that quietly re-fetches on demand is slow in a way nobody can diagnose,
and hides the fact that a result was produced from data that arrived halfway
through. If a step finds its input missing, it should say so and point at
`invoke fetch` — not fix it silently.

### Sensitive and restricted data

Never commit identifiable data, credentials, or anything under a data-use
agreement — not to this repository, not "temporarily". Git history is not
erasable in practice once pushed.

- Keep the gitignore-by-default posture for `source_data/`, and add a guard
  line for the formats that would carry identifiable content.
- Restricted content usually lives behind a credentialed remote. Retrieval will
  fail for some people by design; that is not a bug to work around.
- **Document the access requirements in `source_data/CONTENT.md`**: who can get
  this data, how, and what a person without access will see. A collaborator
  whose `fetch` came back empty otherwise cannot tell whether the pipeline is
  broken or they simply lack permission — and will file the wrong bug.
- Derived outputs inherit the sensitivity of their inputs. An aggregate table
  is usually fine to track; a per-participant one usually is not.

### Recording asset versions

`fetch` writes `source_data/MANIFEST.json` and `run` writes
`output_data/PROVENANCE.json` (see `airoh.provenance`). Between them they record
what each input actually resolved to — including the commit of a symlinked
external checkout — and what produced the current outputs: the project's own
commit and dirty flag, the environment, the manifest consumed, and a checksum
per output file. Both are small and git-tracked.

`PROVENANCE.json` changes on every run. That is the record working, not churn to
suppress; do not try to make it stable.

**These records attest, they do not retrieve.** They can tell you that a result
came from commit `abc123` of an input dataset with an uncommitted working tree —
which is exactly the question "why do my numbers differ from the paper's" needs
answered — but they cannot bring that state back. Retrieval is datalad's job,
and when this repository is aggregated as a submodule into a larger paper
project, datalad is what pins it. The records are what you get when datalad is
not in play, which is most of the time during day-to-day analysis.

## Verification

`invoke verify` checks that the code, config, data and documentation still agree.
It runs a flat list of independent checks — task list versus README, dependency
files against each other, paths named in the docs, each data folder against its
`CONTENT.md`, config keys, tracked file sizes, provenance freshness, the linter —
and exits non-zero if any of them fails. Configure it under `verify:` in
`invoke.yaml`.

**Run it before committing.** Documentation drift is invisible: nothing breaks
when the README lists a task that no longer exists, or a docstring describes
behaviour that was removed two commits ago, so it accumulates until a reader is
actively misled. These checks are the mechanical floor under the instruction to
keep CLAUDE.md and README.md current.

`verify` is deliberately **not** part of `run`. Reproducing results must not
depend on documentation hygiene, and a pipeline that refuses to compute because
a path in the README moved is a pipeline people route around.

The checks are mechanical, so they cannot evaluate a claim like "this step never
pulls data" or "the default threshold is 30". The `/verify` skill covers that
second layer: it runs these checks, then reads the prose against the code. Use
it after any change that alters what a step does, as opposed to what it is
called.

## Code style

**Module and function size:** Each module in `analysis/` covers a single concern; if a file grows past ~200 lines, consider splitting it. Each function should do one thing — aim for under ~30 lines; longer is a signal to extract a helper.

**Naming:** Prefer self-explanatory names over brevity: `n_subjects` not `n`, `output_path` not `p`, `group_means` not `gm`. Avoid abbreviations unless universally known in the domain (`df` for a DataFrame is fine).

**Linting:** The project linter and its configuration are chosen during `init` and stored in `pyproject.toml` or `ruff.toml`, depending on the package manager chosen at init (see **Setup** — only the `uv` path keeps `pyproject.toml`). Run it before committing. Never disable a lint rule without a comment explaining why.

**Testing:** Two baseline checks, and they cover different failures. `invoke run-smoke` is the behavioural one: does the pipeline run end to end and produce something. `invoke verify` is the structural one: do the code, config, data and docs still describe the same project. Run both before committing; neither substitutes for the other. Add unit tests in a tests directory, using the project's chosen test framework, when a function contains non-trivial logic, has edge cases the smoke test won't catch, or is shared across multiple steps. Unit tests are optional for simple glue/orchestration code but encouraged for any pure transformation or computation logic in `analysis/`. The test framework and directory are configured during `init`.

**Template cleanup:** When starting a new project from this template, remove the demo code before adding project-specific work:
- Delete `run_simulation` from `tasks.py` and remove it from the `pre=` chains on `run_notebooks` and `run`
- Delete `analysis/simulation.py` (and the `analysis/` folder if it stays empty)
- Clear or replace `source_data/CONTENT.md` and `output_data/CONTENT.md` with project-specific descriptions
- Update `invoke.yaml` (`files:`, paths) for the new project's data sources

**Adding a new analysis step:** add a function to `analysis/`, add a `run-{name}` task and a matching `clean-{name}` task in `tasks.py`, call both from the bodies of the top-level `run` and `clean` tasks (see the `pre=` warning above — a body call, not `pre=`), and create or extend a notebook in `notebooks/` for visualization.

**Evolving CLAUDE.md:** Run `invoke verify` after any structural change — it catches the mechanical half of this instruction (renamed tasks, moved paths, undocumented outputs) that is otherwise left to memory. Keep this file current as the project grows. It should always reflect the actual scope of the project — what it does, what data it uses, and what analysis steps it contains. When adding or removing a task, rename a folder, or change the pipeline structure, update CLAUDE.md in the same commit. Stale guidance here misleads future AI sessions and collaborators alike.

**Keeping README.md current:** README.md is the user-facing documentation for this project. Any structural or workflow change — new tasks, renamed folders, updated commands, new dependencies — must be reflected there in the same commit. The task list in README.md should match `invoke --list` exactly; if a task is added or removed, update README.md accordingly. For data folder contents, point to `source_data/CONTENT.md` and `output_data/CONTENT.md` rather than duplicating their content inline.
