---
name: literature-search
description: Find new papers that use CNeuroMod data and add them to the cneuromod.all reference list through a pull request. Runs the `lit-*` invoke tasks, web-searches for extra hits, asks the user to accept, reject or defer each candidate, and opens the PR only after explicit confirmation. Use when the user wants to update, curate or extend the CNeuroMod reference list or look for new publications.
---

# Literature search → reference-list PR

The reference list lives in `cneuromod.all` (`docs/source/cneuromod_references.bib`). The `lit-*` tasks
do the searching, logging and git mechanics; **the user makes every accept/reject decision**. Never
decide for them, and never run a real `lit-propose` without their explicit go-ahead: it pushes a
branch and opens a PR.

This is not part of `invoke run`. Every search and decision is logged under `literature_search/`
(git-tracked); see `literature_search/README.md` for the layout.

## Steps

1. **Make sure the reference list is on disk**: `uv run invoke fetch` if needed. Then
   `uv run invoke lit-search`. It queries Europe PMC, OpenAlex and arXiv since the sidecar's
   `SearchDate`, drops what is already in the bib or already decided, and drafts BibTeX.
   (Behind a flaky IPv6 route it can take about a minute: that is expected.)
2. **Widen the net with web search.** Run WebSearch for each configured query
   (`literature_search.queries` in `invoke.yaml`, e.g. `"cneuromod"`, `"cneuromod.ca"`,
   `"Courtois NeuroMod"`), limited to the period since the last search. Register each new hit with
   `uv run invoke lit-candidate --title "..." [--doi ...] [--url ...] [--query ...]`. It deduplicates
   and drafts the BibTeX itself; "already in the reference list" is a normal answer.
3. **Review candidates one at a time.** `uv run invoke lit-status` lists what is pending. For each:
   - Open the abstract or full text (WebFetch) and check that the paper **uses** CNeuroMod data. A
     paper that only cites CNeuroMod, or only mentions the Algonauts challenge, is a reject reason.
   - Show the user the title, venue, why it matched, your verdict, and the draft BibTeX.
   - **Ask** with AskUserQuestion: accept / reject / defer.
   - Record their answer with their reason:
     `uv run invoke lit-decide --id ID --decision accept|reject|defer --reason "..."`.
     If they correct the BibTeX, save it to a file and pass `--bibtex-file`.
4. **Preview, then propose.** `uv run invoke lit-propose --dry-run` prints the bib/sidecar diff and the PR
   body. Show it, get explicit confirmation, then `uv run invoke lit-propose`. It works in a temporary
   git worktree, so the user's cneuromod.all checkout is never switched or modified. Give the user the
   PR URL.
5. **Commit the log** (`literature_search/`) in this repo, after asking.

## Notes

- `lit-search --smoke` writes a real session folder (one query, 3 results per source). Remove it with
  `invoke clean-lit-search --session YYYY-MM-DD` if it was only a test. That task never touches
  `decisions.jsonl`.
- A deferred candidate stays in `lit-status` until decided, even across sessions.
- `lit-propose` does nothing if nothing is accepted and not yet proposed.
