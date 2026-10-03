# Literature search log

Git-tracked record of every search for new CNeuroMod papers and of every decision taken on the
results. It is a record, not a computed output: `invoke clean` never touches it. Written by the
`lit-*` tasks (see the `literature-search` skill and the README's "Curate the reference list").

- `decisions.jsonl`: append-only, one line per decision: `timestamp`, `session`, `candidate_id`,
  `decision` (`accept`, `reject`, `defer`, or `proposed` once a PR includes it), `reason`,
  `decided_by` (git `user.name`), `bibtex_key`, `pr_url`. A later line supersedes an earlier one for the
  same candidate. Nothing is edited in place.
- `<YYYY-MM-DD>/search.json`: one entry per search run that day: `since`, sources, queries, hits per
  source and query, counts before and after dedup, and the git state of this repo and of cneuromod.all.
- `<YYYY-MM-DD>/candidates.jsonl`: the candidates, with their draft BibTeX (`bibtex`) and how they
  were found (`found_by`: `api:europepmc`, `api:openalex`, `api:arxiv`, `agent:websearch`).
- `<YYYY-MM-DD>/pr.json`: branch, commit, PR URL and entries of the PR opened by `lit-propose`.
