# Source Data

Populated by `invoke fetch`.

- `cneuromod.all/`: the [cneuromod.all](https://github.com/courtois-neuromod/cneuromod.all) datalad superdataset. It is either a `datalad clone` or a symlink to an existing checkout (`invoke fetch --cneuromod-source <path>`). It is gitignored and never tracked here. It is also a future write target, so `clean-cneuromod` only ever removes a symlink, never a real clone. Only two annexed files are retrieved; the imaging subdatasets are not installed:
  - `source_data/cneuromod.all/docs/source/cneuromod_references.bib`: the curated list of papers using CNeuroMod data (BibTeX). This is read by `run-citations`.
  - `source_data/cneuromod.all/docs/source/cneuromod_references.json`: metadata for that list (search date, search sources and queries, curation method). This is read by `lit-search` (its `SearchDate` is where the next search starts) and rewritten, with the new sources, by the PR that `lit-propose` opens.
- `MANIFEST.json`: written by `fetch`. Records what each asset resolved to, including the commit of a symlinked checkout. Git-tracked.

**Access:** both reference files are public. If `fetch` warns that a file could not be retrieved, check your network and your `git-annex` version (the `git-annex` package in `pyproject.toml` provides a recent one).
