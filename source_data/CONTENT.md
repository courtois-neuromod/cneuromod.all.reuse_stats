# 📁 Source Data Contents

After `invoke fetch` is complete, expect the following content:

- `YNIMG_BrainParcellation_summary.tsv` — a spreadsheet with some data on a
  series of articles, downloaded from figshare.
- `MANIFEST.json` — what each declared asset actually resolved to: the URL or
  the real path behind a symlink, its size and checksum, and the commit of the
  repository it belongs to when it has one. Written by `invoke fetch`.

📝 Note: tsv files are **ignored by Git** (see `.gitignore`), so data assets
won't be tracked by default. `MANIFEST.json` is the deliberate exception — it is
the record of which inputs a run consumed.

📝 Note: assets here may be **symlinks** to data that already lives elsewhere on
disk, rather than local copies — this happens when a fetch task is run with
`--source` (e.g. `invoke fetch-papers --source /path`, or `invoke fetch
--papers-source /path`), or a `source:` key is set in `invoke.yaml`. The manifest
records what the link pointed at, so a symlinked input stays identifiable.

📝 Note: if this project's data is sensitive, restricted, or needs credentials to
retrieve, say so here — a collaborator whose `fetch` came back empty needs to
know whether the pipeline is broken or they simply lack access. See CLAUDE.md,
"Sensitive and restricted data".
