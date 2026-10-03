"""Unit tests for analysis.curation_log."""

import pytest

from analysis import curation_log as log

SESSION = "2026-10-03"


def paper(paper_id, **extra):
    return {"id": paper_id, "title": f"Paper {paper_id}", "bibtex": "@ARTICLE{K,\n}", **extra}


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path / "literature_search"


def test_append_candidate_ignores_duplicates(log_dir):
    assert log.append_candidate(log_dir, SESSION, paper("a"))
    assert not log.append_candidate(log_dir, SESSION, paper("a"))
    assert [c["id"] for c in log.load_candidates(log_dir, SESSION)] == ["a"]


def test_decisions_are_append_only_and_latest_wins(log_dir):
    log.record_decision(log_dir, SESSION, "a", "defer", "later", "me")
    log.record_decision(log_dir, SESSION, "a", "accept", "uses data", "me", bibtex_key="K")
    assert len((log_dir / "decisions.jsonl").read_text().splitlines()) == 2
    assert log.latest_decisions(log_dir)["a"]["decision"] == "accept"


def test_invalid_decision_is_refused(log_dir):
    with pytest.raises(ValueError):
        log.record_decision(log_dir, SESSION, "a", "maybe", "?", "me")


def test_decided_ids_exclude_deferred(log_dir):
    for paper_id, decision in [("a", "accept"), ("b", "reject"), ("c", "defer")]:
        log.record_decision(log_dir, SESSION, paper_id, decision, "r", "me")
    assert log.decided_ids(log_dir) == {"a", "b"}


def test_pending_includes_deferred_from_earlier_sessions(log_dir):
    log.append_candidate(log_dir, "2026-09-01", paper("old"))
    log.append_candidate(log_dir, SESSION, paper("new"))
    log.append_candidate(log_dir, SESSION, paper("done"))
    log.record_decision(log_dir, "2026-09-01", "old", "defer", "later", "me")
    log.record_decision(log_dir, SESSION, "done", "reject", "only cites", "me")
    assert {c["id"] for c in log.pending(log_dir, SESSION)} == {"old", "new"}


def test_accepted_unproposed_until_proposed(log_dir):
    log.append_candidate(log_dir, SESSION, paper("a"))
    log.record_decision(log_dir, SESSION, "a", "accept", "yes", "me")
    assert [c["id"] for _, c in log.accepted_unproposed(log_dir)] == ["a"]
    log.record_decision(log_dir, SESSION, "a", "proposed", "PR", "me", pr_url="https://x/pr/1")
    assert log.accepted_unproposed(log_dir) == []
    assert log.latest_decisions(log_dir)["a"]["pr_url"] == "https://x/pr/1"


def test_set_draft_bibtex_replaces_draft(log_dir):
    log.append_candidate(log_dir, SESSION, paper("a"))
    log.set_draft_bibtex(log_dir, SESSION, "a", "@ARTICLE{Fixed,\n}\n")
    assert log.load_candidates(log_dir, SESSION)[0]["bibtex"] == "@ARTICLE{Fixed,\n}"
    with pytest.raises(KeyError):
        log.set_draft_bibtex(log_dir, SESSION, "missing", "x")


def test_search_runs_accumulate_within_a_session(log_dir):
    log.add_search_run(log_dir, SESSION, {"n": 1})
    log.add_search_run(log_dir, SESSION, {"n": 2})
    import json
    runs = json.loads((log_dir / SESSION / "search.json").read_text())["runs"]
    assert [r["n"] for r in runs] == [1, 2]


def test_web_url_turns_ssh_remotes_into_https():
    from analysis.literature_curation import web_url

    assert web_url("git@github.com:org/repo.git") == "https://github.com/org/repo"
    assert web_url("https://github.com/org/repo.git") == "https://github.com/org/repo"
