"""Open a pull request on cneuromod.all that adds accepted papers to its reference list.

All work happens in a temporary `git worktree` cut from `origin/<base>`. The user's own
checkout (often a symlink to a working copy with untracked files) is never switched to
another branch, and nothing in it is modified.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from analysis.reference_list import append_entries, update_sidecar

BIB_RELATIVE = "docs/source/cneuromod_references.bib"
SIDECAR_RELATIVE = "docs/source/cneuromod_references.json"
CO_AUTHOR = "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
DATABASE_NAMES = {"europepmc": "Europe PMC", "openalex": "OpenAlex", "arxiv": "arXiv"}
WEB_SEARCH = "Web search (agent)"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def sidecar_sources(runs: list[dict], web_queries: list[str]) -> list[dict]:
    """Sidecar `Sources` entries describing the search runs (and agent web searches) of a PR."""
    sources = []
    for run in runs:
        since = run.get("since", "")
        for source in run.get("sources", []):
            sources.append({"Database": DATABASE_NAMES.get(source, source),
                            "Queries": run.get("queries", []),
                            "DateFilter": f"published since {since}"})
    if web_queries:
        sources.append({"Database": WEB_SEARCH, "Queries": sorted(set(web_queries)),
                        "DateFilter": "published since last search"})
    return sources


def entry_key(bibtex: str) -> str:
    """Citation key of a single BibTeX entry."""
    return re.match(r"@\w+\s*\{([^,]+),", bibtex.strip()).group(1)


def build_pr_body(entries: list[dict], n_rejected: int, n_deferred: int,
                  runs: list[dict], log_pointer: str) -> str:
    """Markdown PR description: what was added, what was not, how it was found."""
    rows = "\n".join(
        f"| `{entry_key(e['bibtex'])}` | {e['title']} | {e.get('year') or ''} | "
        f"{e.get('venue') or ''} | {e.get('doi') or e.get('url') or ''} |" for e in entries)
    queries = sorted({q for run in runs for q in run.get("queries", [])})
    sources = sorted({DATABASE_NAMES.get(s, s) for run in runs for s in run.get("sources", [])})
    return (
        f"Adds {len(entries)} paper(s) using CNeuroMod data to the reference list, each approved "
        f"by a human curator.\n\n"
        f"| Key | Title | Year | Venue | DOI / URL |\n|---|---|---|---|---|\n{rows}\n\n"
        f"Considered but not added: {n_rejected} rejected, {n_deferred} deferred.\n\n"
        f"Search: {', '.join(sources) or 'n/a'}; queries: {', '.join(f'`{q}`' for q in queries)}; "
        f"plus agent web searches. `cneuromod_references.json` is updated with the search date and "
        f"sources.\n\nFull log of searches and decisions: {log_pointer}\n"
    )


def _unused_branch(repo: Path, branch: str) -> str:
    candidate, suffix = branch, 1
    while subprocess.run(["git", "rev-parse", "--verify", "--quiet", candidate],
                         cwd=repo, capture_output=True, check=False).returncode == 0:
        suffix += 1
        candidate = f"{branch}-{suffix}"
    return candidate


def propose(repo: Path, entries: list[str], search_date: str, sidecar_additions: list[dict],
            branch: str, title: str, body: str, base: str = "main", dry_run: bool = False) -> dict:
    """Add *entries* (BibTeX strings) to the reference list via a PR; returns what was done.

    With `dry_run`, build everything in the worktree, print the diff and body, push nothing.
    """
    repo = Path(repo).resolve()
    _git(repo, "fetch", "origin")
    branch = _unused_branch(repo, branch)
    scratch = Path(tempfile.mkdtemp(prefix="cneuromod-all-pr-"))
    worktree = scratch / "cneuromod.all"
    _git(repo, "worktree", "add", "-b", branch, str(worktree), f"origin/{base}")
    try:
        bib_path, sidecar_path = worktree / BIB_RELATIVE, worktree / SIDECAR_RELATIVE
        bib_path.write_text(append_entries(bib_path.read_text(encoding="utf-8"), entries),
                            encoding="utf-8")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        updated = update_sidecar(sidecar, search_date, sidecar_additions)
        sidecar_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
        diff = _git(worktree, "diff")
        if dry_run:
            print(diff, "\n--- PR title ---", title, "--- PR body ---", body, sep="\n")
            return {"branch": branch, "commit": None, "pr_url": None, "dry_run": True}
        _git(worktree, "add", BIB_RELATIVE, SIDECAR_RELATIVE)
        _git(worktree, "commit", "-m", f"{title}\n\n{CO_AUTHOR}")
        commit = _git(worktree, "rev-parse", "HEAD")
        _git(worktree, "push", "-u", "origin", branch)
        pr_url = subprocess.run(
            ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title,
             "--body", body],
            cwd=worktree, capture_output=True, text=True, check=True).stdout.strip()
        return {"branch": branch, "commit": commit, "pr_url": pr_url, "dry_run": False}
    finally:
        # Not `git worktree remove`: git-annex turns the worktree's `.git` file into a symlink,
        # which git 2.34 then refuses to validate. Deleting the folder and pruning is equivalent.
        shutil.rmtree(scratch, ignore_errors=True)
        _git(repo, "worktree", "prune")
        if dry_run:
            _git(repo, "branch", "-D", branch)
