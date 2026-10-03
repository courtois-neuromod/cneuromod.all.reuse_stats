from pathlib import Path

from invoke import task

# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
# Files of cneuromod.all this project reads (relative to the dataset root).
# They are annexed there, so a fresh clone has the tree but not the content.
CNEUROMOD_BIB = "docs/source/cneuromod_references.bib"
CNEUROMOD_REFERENCE_FILES = [
    CNEUROMOD_BIB,
    "docs/source/cneuromod_references.json",
]


@task(help={
    "source": "Existing cneuromod.all checkout to symlink instead of cloning "
              "(e.g. ../cneuromod.all, or the parent repo when used as a subrepo).",
})
def fetch_cneuromod(c, source=None):
    """
    Make cneuromod.all available and retrieve the reference list.

    cneuromod.all is both a source (its citation list is read here) and a
    future target (new publications will be written back to it), so the checkout is
    never copied: it is either a fresh `datalad clone` or a symlink to the
    checkout you already have. Only the reference files are retrieved, not the
    dataset content. Tolerant of partial failures: a file that cannot be
    reached warns and is skipped.
    """
    from airoh.datalad import get_data, install_dataset

    install_dataset(c, "cneuromod", source=source)
    for reference_file in CNEUROMOD_REFERENCE_FILES:
        get_data(c, "cneuromod", path=reference_file)


@task(help={
    "cneuromod_source": "Existing cneuromod.all checkout to symlink instead of cloning.",
})
def fetch(c, cneuromod_source=None):
    """
    Retrieve all data assets. Each asset has its own fetch-{name} task; this
    umbrella task routes a per-asset --{name}-source flag to the matching one.

    Records what each asset actually resolved to in source_data/MANIFEST.json,
    so the inputs a later run consumed stay identifiable — including the commit
    of a symlinked external checkout. See CLAUDE.md, "Recording asset versions".
    """
    from airoh.provenance import record_sources

    fetch_cneuromod(c, source=cneuromod_source)
    record_sources(c)

# --------------------------------------------------------------------------- #
# Analysis steps
# --------------------------------------------------------------------------- #
CITATIONS_CSV = "cneuromod_citations.csv"
SMOKE_MAX_ENTRIES = 5


def cneuromod_bib_path(c):
    """Path of the CNeuroMod reference list inside the cneuromod.all checkout."""
    dataset = c.config.get("datasets")["cneuromod"]
    dataset_dir = Path(dataset["output_dir"] if isinstance(dataset, dict) else dataset)
    return dataset_dir / CNEUROMOD_BIB


@task(help={
    "smoke": f"Parse only the first {SMOKE_MAX_ENTRIES} entries, for a fast plumbing check.",
})
def run_citations(c, smoke=False):
    """
    Count papers using CNeuroMod data, by year and publication type.

    Reads cneuromod_references.bib from the cneuromod.all checkout and writes
    output_data/cneuromod_citations.csv (columns year, type, count). Skipped if
    the CSV already exists. Never fetches: if the reference list is not on
    disk, it stops and points at `invoke fetch`.
    """
    from analysis.citations import parse_bib_to_table

    output_path = Path(c.config.get("output_data_dir")) / CITATIONS_CSV
    if output_path.exists():
        print(f"⏭️  {output_path} already exists — skipping (clean-citations to redo)")
        return

    bib_path = cneuromod_bib_path(c)
    if not bib_path.is_file():  # also catches an annexed file whose content was not retrieved
        raise SystemExit(f"❌ {bib_path} is missing or has no content — run `invoke fetch` first.")

    max_entries = SMOKE_MAX_ENTRIES if smoke else None
    table = parse_bib_to_table(bib_path, max_entries=max_entries)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_path, index=False)
    print(f"📚 {table['count'].sum()} papers → {output_path}")


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

    Read by the notebooks (via airoh.figures.panel_size) so every placed panel
    renders at exactly the physical size the montage allocates it. Always
    re-runs, never skipped: it is cheap, and a box resized in Inkscape must
    take effect on the very next `invoke run`.
    """
    from airoh.figures import figure_layout
    figure_layout(c)

@task(pre=[run_figure_layout])
def run_notebooks(c):
    """
    Execute the notebooks in notebooks/ and save their figures.

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
    Full pipeline: citations → figure layout → notebooks → composed figure.

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
    run_citations(c)
    run_figure_layout(c)
    run_notebooks(c)
    compose_figure(c)
    record_run(c, tasks="run-citations,run-figure-layout,run-notebooks,compose-figure")
    print("all analyses completed")

@task
def run_smoke(c):
    """
    Smoke test: a minimal end-to-end pass over the whole pipeline.

    Calls the steps directly (rather than via `pre=`) so each can be given a
    reduced workload. The point is to exercise the plumbing quickly, not to
    produce real results.

    Cleans computed outputs before and after: before, so cached outputs cannot
    hide a broken step; after, so the reduced smoke outputs are never mistaken
    for real ones by the next `invoke run` (which caches by existence).
    """
    fetch(c)
    clean(c)
    run_citations(c, smoke=True)
    run_figure_layout(c)
    run_notebooks(c)
    compose_figure(c)
    clean(c)
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
# Literature curation
# --------------------------------------------------------------------------- #
# Not part of `run`: network-bound, non-deterministic and outward-facing (it opens a PR).
# Claude drives these in a session, the user approves each addition. See the
# literature-search skill and literature_search/README.md.
SIDECAR_PATH = "docs/source/cneuromod_references.json"


def literature_settings(c):
    """The `literature_search:` block of invoke.yaml."""
    return c.config.get("literature_search")


def require_bib(c):
    """Path of the reference list; stops and points at `invoke fetch` if it is not on disk."""
    bib_path = cneuromod_bib_path(c)
    if not bib_path.is_file():
        raise SystemExit(f"❌ {bib_path} is missing or has no content — run `invoke fetch` first.")
    return bib_path


@task(help={
    "since": "Only papers published on/after this date (YYYY-MM-DD). "
             "Default: the SearchDate in cneuromod_references.json.",
    "smoke": "One query, 3 results per source, for a fast plumbing check.",
})
def lit_search(c, since=None, smoke=False):
    """
    Search Europe PMC, OpenAlex and arXiv for new CNeuroMod papers.

    Deduplicates against the reference list and past decisions, drafts BibTeX, and
    writes literature_search/<today>/. Re-running the same day adds to that session
    and never touches decisions.
    """
    from analysis.literature_curation import search_session

    bib_path = require_bib(c)
    settings = literature_settings(c)
    summary = search_session(bib_path, bib_path.with_name("cneuromod_references.json"),
                             settings["log_dir"], settings, since=since, smoke=smoke)
    print(f"🔎 since {summary['since']}: {summary['n_raw']} hits → "
          f"{summary['n_after_dedup']} after dedup, {summary['n_new']} new")
    print("   Next: `invoke lit-status`")


@task(help={
    "title": "Paper title (required).",
    "doi": "DOI, if known (the BibTeX is then fetched from doi.org).",
    "url": "Link to the paper.",
    "query": "The web search that found it.",
    "authors": "Authors separated by ' and ' (optional).",
    "year": "Publication year (optional).",
    "venue": "Journal or preprint server (optional).",
})
def lit_candidate(c, title, doi=None, url=None, query=None, authors=None, year=None, venue=None):
    """Register a paper found by web search as a candidate (dedup, draft BibTeX, log)."""
    from analysis.literature_curation import register_candidate

    candidate = {
        "title": title, "doi": doi, "url": url or "", "query": query, "arxiv_id": None,
        "authors": authors.split(" and ") if authors else [],
        "year": int(year) if year else None, "venue": venue or "", "source": ["websearch"],
        "matched_snippet": "",
    }
    print(register_candidate(require_bib(c), literature_settings(c)["log_dir"], candidate))


@task(help={"session": "Session date (YYYY-MM-DD). Default: today."})
def lit_status(c, session=None):
    """Print the candidates still awaiting a decision, with their draft BibTeX."""
    from analysis import curation_log as log
    from analysis.literature_curation import today

    log_dir = literature_settings(c)["log_dir"]
    waiting = log.pending(log_dir, session or today())
    print(f"📋 {len(waiting)} candidate(s) awaiting a decision")
    for candidate in waiting:
        print(f"\n── {candidate['id']}\n   {candidate['title']}\n   "
              f"{candidate.get('venue') or '?'} ({candidate.get('year') or '?'}) · "
              f"found by {', '.join(candidate.get('found_by', []))}\n   "
              f"{candidate.get('url') or ''}\n   “{candidate.get('matched_snippet', '')}”\n"
              f"{candidate.get('bibtex', '')}")


@task(help={
    "id": "Candidate id, as printed by lit-status (required).",
    "decision": "accept, reject or defer (required).",
    "reason": "Why, in a sentence (required).",
    "bibtex_file": "File with a corrected BibTeX entry, replacing the draft.",
    "session": "Session date holding the candidate (default: newest that has it).",
})
def lit_decide(c, id, decision, reason, bibtex_file=None, session=None):
    """Record a human decision on a candidate in literature_search/decisions.jsonl."""
    from analysis.literature_curation import decide

    if decision not in ("accept", "reject", "defer"):
        raise SystemExit("❌ --decision must be accept, reject or defer.")
    record = decide(literature_settings(c)["log_dir"], id, decision, reason,
                    bibtex_file=bibtex_file, session=session)
    print(f"📝 {record['decision']}: {record['candidate_id']}")


@task(help={"dry_run": "Print the diff and PR body; push nothing."})
def lit_propose(c, dry_run=False):
    """
    Add accepted candidates to cneuromod.all through a pull request.

    Works in a temporary git worktree cut from origin/<pr_base>, so your cneuromod.all
    checkout keeps its branch and working tree. Pushes a branch and opens the PR
    (outward-facing: preview with --dry-run first), then logs the PR URL.
    """
    from analysis.literature_curation import propose_accepted

    settings = literature_settings(c)
    require_bib(c)
    dataset = c.config.get("datasets")["cneuromod"]
    repo = dataset["output_dir"] if isinstance(dataset, dict) else dataset
    result = propose_accepted(repo, settings["log_dir"], base=settings["pr_base"], dry_run=dry_run)
    if result and result["pr_url"]:
        print(f"🚀 {result['pr_url']}")


@task(help={"session": "Session date to remove (YYYY-MM-DD, required)."})
def clean_lit_search(c, session):
    """
    Remove one literature_search/<date>/ session folder.

    Never touches decisions.jsonl, and is not called by `clean`: the log is a record,
    not a computed output.
    """
    import shutil

    folder = Path(literature_settings(c)["log_dir"]) / session
    if folder.is_dir():
        shutil.rmtree(folder)
        print(f"🧹 Removed {folder}")
    else:
        print(f"🫧 Skipping: {folder} does not exist.")


# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #
@task
def clean_citations(c):
    """Remove output_data/cneuromod_citations.csv, the output of run-citations."""
    output_path = Path(c.config.get("output_data_dir")) / CITATIONS_CSV
    if output_path.exists():
        output_path.unlink()
        print(f"🧹 Removed {output_path}")
    else:
        print(f"🫧 Skipping: {output_path} does not exist.")


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
    clean_citations(c)
    clean_figures(c)
    clean_figure(c)

@task
def clean_cneuromod(c):
    """
    Remove the 'cneuromod' source link (a symlink to an existing checkout).

    Not called by `clean` or `run --force` — those only touch output_data/.
    Use this (or the umbrella `clean-source`) before `invoke fetch-cneuromod
    --source ...` to re-point a stale symlink. A real clone is never deleted
    here: cneuromod.all is also a write target, so it may hold work that is not
    pushed yet. Remove such a checkout by hand if you really mean to.
    """
    dataset = c.config.get("datasets")["cneuromod"]
    dataset_dir = Path(dataset["output_dir"] if isinstance(dataset, dict) else dataset)
    if dataset_dir.is_symlink():
        dataset_dir.unlink()
        print(f"🧹 Removed link: {dataset_dir}")
    elif dataset_dir.exists():
        print(f"⚠️  {dataset_dir} is a real checkout, not a link: left untouched "
              "(it may hold unpushed work). Remove it by hand if you are sure.")
    else:
        print(f"🫧 Skipping: {dataset_dir} does not exist.")

@task
def clean_source(c):
    """
    Remove all source data assets. Body calls each clean-{name} task.
    """
    clean_cneuromod(c)
