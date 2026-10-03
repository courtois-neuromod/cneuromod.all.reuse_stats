from pathlib import Path

from invoke import task


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
@task(help={
    "source": "Path to already-present 'papers' data to symlink instead of downloading.",
    "copy": "Copy the source data instead of symlinking it.",
})
def fetch_papers(c, source=None, copy=False):
    """
    Retrieve the 'papers' asset (download, or symlink/copy existing data).
    """
    from airoh.acquisition import fetch_data
    fetch_data(c, "papers", source=source, copy=copy)

@task(help={
    "papers_source": "Path to existing 'papers' data to symlink instead of downloading.",
    "copy": "Copy source data instead of symlinking it.",
})
def fetch(c, papers_source=None, copy=False):
    """
    Retrieve all data assets. Each asset has its own fetch-{name} task; this
    umbrella task routes a per-asset --{name}-source flag to the matching one.

    Records what each asset actually resolved to in source_data/MANIFEST.json,
    so the inputs a later run consumed stay identifiable — including the commit
    of a symlinked external checkout. See CLAUDE.md, "Recording asset versions".
    """
    from airoh.provenance import record_sources

    fetch_papers(c, source=papers_source, copy=copy)
    record_sources(c)

# --------------------------------------------------------------------------- #
# Analysis steps
# --------------------------------------------------------------------------- #
@task(help={"seed": "Seed for the random generator (default: 0)."})
def run_simulation(c, seed=None):
    """
    Run a small simulation.

    Seeded, so a rerun reproduces the same numbers and the same figures —
    pass --seed to draw a different sample.

    Skipped when its output already exists — every run step caches that way, so
    a repeated `invoke run` costs nothing. Use `invoke clean-simulation` (or
    `invoke run --force`) to redo it.
    """
    from analysis.simulation import DEFAULT_SEED, simulation

    output_dir = Path(c.config.get("output_data_dir"))
    if (output_dir / "simulation_output.csv").is_file():
        print("🫧 Skipping simulation (output exists)")
        return
    simulation(output_dir, seed=DEFAULT_SEED if seed is None else int(seed))

def montage_dpi(c):
    """
    The DPI the montage is composed at, from `figures:` in invoke.yaml.

    This template has a single montage, so the first entry's `dpi` is the
    answer; a project with several would need to decide which one a given
    notebook's panels belong to. Defaults to 300, matching
    `airoh.figures.compose_figure`.
    """
    for entry in (c.config.get("figures") or {}).values():
        return entry.get("dpi", 300)
    return 300

@task
def run_figure_layout(c):
    """
    Write every montage's panel geometry to figures_dir/panel_sizes.json.

    Read by the notebook (see figure_simulation.ipynb) so every placed panel
    renders at exactly the physical size the montage allocates it. Always
    re-runs, never skipped: it is cheap, and a box resized in Inkscape must
    take effect on the very next `invoke run`.
    """
    from airoh.figures import figure_layout
    figure_layout(c)

@task(pre=[run_simulation, run_figure_layout])
def run_notebooks(c):
    """
    Generate figures from the simulation output using a notebook.

    `run-figure-layout` runs first because the notebook sizes its placed
    panels from the geometry it writes — and `clean-figures` wipes that file
    along with the figures dir it lives in. (`run` calls both explicitly, in
    the same order; this `pre=` only covers invoking `run-notebooks` on its
    own.)

    Exports the montage's configured DPI as FIGURE_MONTAGE_DPI so notebooks
    save at it rather than hardcoding 300 — panel *pixels* must equal
    figsize × dpi for placement to stay 1:1, so the resolution has to come
    from the same config the montage is composed with.
    """
    import os

    from airoh.utils import ensure_dir_exist
    from airoh.utils import run_notebooks as airoh_run_notebooks

    notebooks_dir = Path(c.config.get("notebooks_dir"))
    figures_base = Path(c.config.get("figures_dir")).resolve()

    os.environ["FIGURE_MONTAGE_DPI"] = str(montage_dpi(c))

    ensure_dir_exist(c, "output_data_dir")
    airoh_run_notebooks(c, notebooks_dir, figures_base,
                         keys=["source_data_dir", "output_data_dir", "figures_dir"])

@task
def compose_figure(c):
    """
    Render the hand-authored figure_montage.svg to PNG with Inkscape.

    Optional: Inkscape is only needed to recompose the final figure, never to
    reproduce a panel, so a missing binary warns and returns rather than
    failing the run.
    """
    from airoh.figures import compose_figure as airoh_compose_figure
    airoh_compose_figure(c)

# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
@task(help={
    "force": "Delete every computed output first, then run from scratch.",
})
def run(c, force=False):
    """
    Full pipeline: simulation → figure layout → notebooks → composed figure.

    Steps are called directly rather than through `pre=`, so that flags like
    --force reach them: a `pre=` chain runs before this body, which would be
    too late.

    Every step caches by checking whether its output already exists, so a
    repeated `run` does nothing. That is deliberate — but it also means an
    edited script or notebook will NOT re-run on its own. `--force` is the
    sledgehammer: clean everything, then start over. To redo one step, call its
    `clean-{name}` task and run again. `run-figure-layout` is the one
    deliberate exception: it always re-runs (see its docstring).
    """
    from airoh.provenance import record_run

    if force:
        print("💥 --force: removing every computed output before running")
        clean(c)
    run_simulation(c)
    run_figure_layout(c)
    run_notebooks(c)
    compose_figure(c)
    record_run(c, tasks="run-simulation,run-figure-layout,run-notebooks,compose-figure")
    print("all analyses completed")

@task
def run_smoke(c):
    """
    Smoke test: a minimal end-to-end pass over the whole pipeline.

    Calls the steps directly (rather than via `pre=`) so each can be given a
    reduced workload. The point is to exercise the plumbing quickly, not to
    produce real results.
    """
    fetch(c)
    run_simulation(c)
    run_figure_layout(c)
    run_notebooks(c)
    compose_figure(c)
    print("✅ Smoke test complete.")

@task(help={
    "skip": "Comma-separated check names to skip.",
    "strict": "Treat warnings as failures.",
})
def verify(c, skip=None, strict=False):
    """
    Check that the code, config, data and docs still agree.

    Run this before committing. It is deliberately NOT part of `run`:
    reproducing results should never depend on documentation hygiene. See
    CLAUDE.md, "Verification", for what each check covers.
    """
    from airoh.verify import verify as airoh_verify
    airoh_verify(c, skip=skip, strict=strict)

# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #
@task
def clean_simulation(c):
    """
    Remove the simulation outputs.
    """
    from airoh.utils import clean_folder
    clean_folder(c, "output_data_dir", "*.csv")

@task
def clean_figures(c):
    """
    Remove the figures dir (per-notebook panels, the "already ran" sentinels,
    and panel_sizes.json).

    Leaving a notebook's sentinel folder behind would make the next `run`
    skip it even though its figures are gone, so the whole figures_dir tree
    is removed, not just the PNGs inside it.
    """
    from airoh.utils import clean_folder
    clean_folder(c, "figures_dir")

@task
def clean_figure(c):
    """
    Remove the composed montage PNG (figure_montage.png).

    Never the SVG: that one is hand-authored in Inkscape and is a pipeline
    *source*, despite living in output_data/ (its relative image links
    resolve from there).
    """
    from airoh.figures import clean_figure as airoh_clean_figure
    airoh_clean_figure(c)

@task
def clean(c):
    """
    Remove all computed outputs.

    The steps are called in the body rather than declared as `pre=`, because a
    `pre=` chain only fires when invoke runs the task from the command line.
    Calling `clean(c)` from Python — which is what `run --force` does — would
    otherwise execute an empty function and silently delete nothing.
    """
    clean_simulation(c)
    clean_figures(c)
    clean_figure(c)

@task
def clean_papers(c):
    """
    Remove the 'papers' source asset (the downloaded or symlinked file).

    Not called by `clean` or `run --force` — those only touch output_data/.
    Use this (or the umbrella `clean-source`) before `invoke fetch-papers` when
    you need to point a stale symlink somewhere new: fetch never overwrites a
    real file or existing symlink sitting at the destination.
    """
    papers_file = Path(c.config.get("files")["papers"]["output_file"])
    if papers_file.is_symlink() or papers_file.exists():
        papers_file.unlink()
        print(f"🧹 Removed: {papers_file}")
    else:
        print(f"🫧 Skipping: {papers_file} does not exist.")

@task
def clean_source(c):
    """
    Remove all source data assets. Body calls each clean-{name} task.
    """
    clean_papers(c)
