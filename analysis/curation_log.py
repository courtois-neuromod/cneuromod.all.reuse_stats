"""Git-tracked record of literature searches and the decisions taken on their candidates.

Layout under *log_dir*: `decisions.jsonl` (append-only, one line per decision) and one
`<YYYY-MM-DD>/` folder per search session with `search.json`, `candidates.jsonl`, `pr.json`.
The log is a record, not a computed output: nothing here is removed by `clean`.

A decision is never edited. Later lines supersede earlier ones for the same candidate, and
`proposed` is the last word on an accepted candidate: it carries the PR URL.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

DECISIONS_FILE = "decisions.jsonl"
FINAL_DECISIONS = {"accept", "reject", "proposed"}
VALID_DECISIONS = {"accept", "reject", "defer"}


def session_dir(log_dir, session: str) -> Path:
    """Folder of one search session (created on demand)."""
    path = Path(log_dir) / session
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")


def load_candidates(log_dir, session: str) -> list[dict]:
    """Candidates of *session*, in the order they were registered."""
    return _read_jsonl(Path(log_dir) / session / "candidates.jsonl")


def append_candidate(log_dir, session: str, candidate: dict) -> bool:
    """Register *candidate* in the session; False if its id is already there."""
    path = session_dir(log_dir, session) / "candidates.jsonl"
    records = _read_jsonl(path)
    if any(record["id"] == candidate["id"] for record in records):
        return False
    _write_jsonl(path, [*records, candidate])
    return True


def set_draft_bibtex(log_dir, session: str, candidate_id: str, bibtex: str) -> None:
    """Replace a candidate's draft BibTeX (a user's correction)."""
    path = Path(log_dir) / session / "candidates.jsonl"
    records = _read_jsonl(path)
    for record in records:
        if record["id"] == candidate_id:
            record["bibtex"] = bibtex.strip()
            _write_jsonl(path, records)
            return
    raise KeyError(f"{candidate_id} is not a candidate of session {session}")


def git_user_name(cwd=None) -> str:
    """`git config user.name`, or 'unknown'."""
    result = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True,
                            cwd=cwd, check=False)
    return result.stdout.strip() or "unknown"


def record_decision(log_dir, session, candidate_id, decision, reason, decided_by,
                    bibtex_key=None, pr_url=None) -> dict:
    """Append one decision line; returns the record."""
    if decision not in VALID_DECISIONS | {"proposed"}:
        raise ValueError(f"decision must be one of {sorted(VALID_DECISIONS)}, got {decision!r}")
    record = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session": session,
        "candidate_id": candidate_id,
        "decision": decision,
        "reason": reason,
        "decided_by": decided_by,
        "bibtex_key": bibtex_key,
        "pr_url": pr_url,
    }
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(log_dir) / DECISIONS_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def latest_decisions(log_dir) -> dict[str, dict]:
    """Most recent decision record per candidate id."""
    return {r["candidate_id"]: r for r in _read_jsonl(Path(log_dir) / DECISIONS_FILE)}


def decided_ids(log_dir) -> set[str]:
    """Ids that are settled (accepted, rejected or proposed). Deferred ones are not."""
    return {cid for cid, record in latest_decisions(log_dir).items()
            if record["decision"] in FINAL_DECISIONS}


def pending(log_dir, session: str) -> list[dict]:
    """Session candidates still awaiting a decision, plus candidates deferred in other sessions."""
    latest = latest_decisions(log_dir)
    waiting = [c for c in load_candidates(log_dir, session)
               if latest.get(c["id"], {}).get("decision") not in FINAL_DECISIONS]
    seen = {c["id"] for c in waiting}
    for folder in sorted(Path(log_dir).glob("????-??-??")):
        if folder.name == session:
            continue
        for candidate in load_candidates(log_dir, folder.name):
            deferred = latest.get(candidate["id"], {}).get("decision") == "defer"
            if deferred and candidate["id"] not in seen:
                waiting.append(candidate)
                seen.add(candidate["id"])
    return waiting


def accepted_unproposed(log_dir) -> list[tuple[str, dict]]:
    """(session, candidate) for every accepted candidate not yet in a PR, oldest first."""
    latest = latest_decisions(log_dir)
    found: dict[str, tuple[str, dict]] = {}
    for folder in sorted(Path(log_dir).glob("????-??-??")):
        for candidate in load_candidates(log_dir, folder.name):
            if latest.get(candidate["id"], {}).get("decision") == "accept":
                found.setdefault(candidate["id"], (folder.name, candidate))
    return list(found.values())


def write_json(path: Path, data: dict) -> None:
    """Write *data* as pretty JSON."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_search_run(log_dir, session: str, run_info: dict) -> None:
    """Append one search run to the session's `search.json` (same-day reruns accumulate)."""
    path = session_dir(log_dir, session) / "search.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"runs": []}
    existing["runs"].append(run_info)
    write_json(path, existing)
