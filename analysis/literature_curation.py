"""Orchestration of the literature-curation workflow behind the `lit-*` invoke tasks.

Glue only: searching is `literature_search`, dedup and BibTeX are `reference_list`, the record
is `curation_log`, the PR is `reference_pr`. Functions take explicit paths and settings, never
an invoke context, so they can be tested and reused.
"""

import json
from datetime import date, datetime
from pathlib import Path

from airoh.provenance import git_info

from analysis import curation_log as log
from analysis import reference_list as refs
from analysis import reference_pr as pr
from analysis.literature_search import run_searches

SMOKE_MAX_RESULTS = 3


def web_url(remote: str) -> str:
    """Browsable https URL for a git remote (`git@host:org/repo.git` -> `https://host/org/repo`)."""
    if remote.startswith("git@"):
        remote = "https://" + remote[4:].replace(":", "/", 1)
    return remote.removesuffix(".git")


def today() -> str:
    return date.today().isoformat()


def default_since(sidecar_path: Path) -> str:
    """The sidecar's `SearchDate`: where the previous search stopped."""
    return json.loads(Path(sidecar_path).read_text(encoding="utf-8"))["SearchDate"]


def _draft_all(candidates, bib_text, log_dir, session) -> list[dict]:
    taken = refs.existing_keys(bib_text) | {
        pr.entry_key(c["bibtex"]) for c in log.load_candidates(log_dir, session) if c.get("bibtex")}
    for candidate in candidates:
        candidate["bibtex"] = refs.draft_bibtex(candidate, taken)
        taken.add(pr.entry_key(candidate["bibtex"]))
    return candidates


def search_session(bib_path, sidecar_path, log_dir, settings: dict, since=None,
                   smoke=False, session=None) -> dict:
    """Query the configured APIs, dedup, draft BibTeX, log the run; returns the run summary."""
    session = session or today()
    since = since or default_since(sidecar_path)
    queries = settings["queries"][:1] if smoke else settings["queries"]
    max_results = SMOKE_MAX_RESULTS if smoke else settings["max_results_per_query"]
    raw, hit_counts = run_searches(settings["sources"], queries, since, max_results,
                                   settings.get("contact_email"))
    bib_text = Path(bib_path).read_text(encoding="utf-8")
    fresh = refs.deduplicate(raw, refs.existing_titles(bib_path), log.decided_ids(log_dir))
    known = {c["id"] for c in log.load_candidates(log_dir, session)}
    new = _draft_all([c for c in fresh if c["id"] not in known], bib_text, log_dir, session)
    for candidate in new:
        candidate["found_by"] = [f"api:{source}" for source in candidate["source"]]
        log.append_candidate(log_dir, session, candidate)
    summary = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "since": since, "sources": settings["sources"], "queries": queries, "smoke": smoke,
        "hit_counts": hit_counts, "n_raw": len(raw), "n_after_dedup": len(fresh),
        "n_new": len(new), "git": {"this_repo": git_info("."), "cneuromod_all": git_info(bib_path)},
    }
    log.add_search_run(log_dir, session, summary)
    return summary


def register_candidate(bib_path, log_dir, candidate: dict, session=None) -> str:
    """Log a candidate found by the agent's web search; returns a one-line outcome."""
    session = session or today()
    candidate = {**candidate, "id": refs.candidate_id(
        candidate.get("doi"), candidate.get("arxiv_id"), candidate["title"])}
    title = refs.normalize_title(candidate["title"])
    if candidate["id"] in log.decided_ids(log_dir):
        return f"already decided: {candidate['id']}"
    if refs.is_known_title(title, refs.existing_titles(bib_path)):
        return f"already in the reference list: {candidate['title']}"
    candidate["found_by"] = ["agent:websearch"]
    candidate["bibtex"] = _draft_all(
        [candidate], Path(bib_path).read_text(encoding="utf-8"), log_dir, session)[0]["bibtex"]
    added = log.append_candidate(log_dir, session, candidate)
    return f"registered {candidate['id']}" if added else f"already registered: {candidate['id']}"


def find_session(log_dir, candidate_id: str, session=None) -> str:
    """Session folder holding *candidate_id* (the given one, else the newest that has it)."""
    sessions = [session] if session else sorted(
        (p.name for p in Path(log_dir).glob("????-??-??")), reverse=True)
    for name in sessions:
        if any(c["id"] == candidate_id for c in log.load_candidates(log_dir, name)):
            return name
    raise SystemExit(f"❌ {candidate_id} is not a registered candidate — see `invoke lit-status`.")


def decide(log_dir, candidate_id, decision, reason, bibtex_file=None, session=None) -> dict:
    """Record a human decision; a corrected BibTeX file replaces the draft."""
    session = find_session(log_dir, candidate_id, session)
    if bibtex_file:
        log.set_draft_bibtex(log_dir, session, candidate_id,
                             Path(bibtex_file).read_text(encoding="utf-8"))
    candidate = next(c for c in log.load_candidates(log_dir, session) if c["id"] == candidate_id)
    key = pr.entry_key(candidate["bibtex"]) if decision == "accept" else None
    return log.record_decision(log_dir, session, candidate_id, decision, reason,
                               log.git_user_name(), bibtex_key=key)


def _pr_inputs(log_dir, accepted: list[tuple[str, dict]]):
    sessions = sorted({name for name, _ in accepted})
    runs = []
    for name in sessions:
        search_file = Path(log_dir) / name / "search.json"
        if search_file.is_file():
            runs += json.loads(search_file.read_text(encoding="utf-8"))["runs"]
    web_queries = [c["query"] for _, c in accepted
                   if "agent:websearch" in c.get("found_by", []) and c.get("query")]
    return sessions, runs, web_queries


def propose_accepted(repo, log_dir, base="main", dry_run=False) -> dict | None:
    """Open (or, with dry_run, preview) the PR for accepted candidates not yet proposed."""
    accepted = log.accepted_unproposed(log_dir)
    if not accepted:
        print("🫧 Nothing accepted and not yet proposed — see `invoke lit-status`.")
        return None
    sessions, runs, web_queries = _pr_inputs(log_dir, accepted)
    latest = log.latest_decisions(log_dir).values()
    entries = [c for _, c in accepted]
    remote = web_url((git_info(".") or {}).get("remote") or "cneuromod.all.reuse_stats")
    stamp = today()
    title = f"Add {len(entries)} CNeuroMod reference(s) ({stamp})"
    body = pr.build_pr_body(
        entries, sum(d["decision"] == "reject" for d in latest),
        sum(d["decision"] == "defer" for d in latest), runs,
        f"`literature_search/` in {remote}")
    result = pr.propose(repo, [c["bibtex"] for c in entries], sessions[-1],
                        pr.sidecar_sources(runs, web_queries), f"references/{stamp}", title,
                        body, base=base, dry_run=dry_run)
    if not dry_run:
        log.write_json(log.session_dir(log_dir, sessions[-1]) / "pr.json",
                       {**result, "entries": [c["id"] for c in entries]})
        for session, candidate in accepted:
            log.record_decision(log_dir, session, candidate["id"], "proposed",
                                "included in PR", log.git_user_name(),
                                bibtex_key=pr.entry_key(candidate["bibtex"]),
                                pr_url=result["pr_url"])
    return result
