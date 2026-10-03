"""Pure logic for curating the CNeuroMod reference list: dedup, BibTeX drafting, sidecar update.

Candidates are plain dicts with the keys `id`, `title`, `authors` (list of "First Last"
strings), `year`, `venue`, `doi`, `arxiv_id`, `url`, `source` (list of source names),
`query` and `matched_snippet`.
"""

import hashlib
import re
from difflib import SequenceMatcher
from pathlib import Path

import requests

from analysis.citations import classify_entry, iter_bib_entries

FUZZY_TITLE_THRESHOLD = 0.9
_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", re.IGNORECASE)


def normalize_title(title: str) -> str:
    """Lowercase *title* and drop braces, LaTeX commands, punctuation and extra whitespace."""
    title = re.sub(r"\\[a-zA-Z]+", " ", title or "")
    title = re.sub(r"[^\w\s]|_", " ", title.lower())
    return " ".join(title.split())


def normalize_doi(doi: str | None) -> str:
    """Bare lowercase DOI (no URL or `doi:` prefix), or an empty string."""
    return _DOI_PREFIX.sub("", (doi or "").strip()).lower()


def candidate_id(doi: str | None, arxiv_id: str | None, title: str) -> str:
    """Stable id: the DOI, else `arxiv:<id>`, else a slug of the normalized title."""
    if normalize_doi(doi):
        return normalize_doi(doi)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    return "title:" + normalize_title(title).replace(" ", "-")[:80]


def existing_titles(bib_path: Path) -> list[str]:
    """Normalized titles of every entry already in the reference list."""
    text = Path(bib_path).read_text(encoding="utf-8")
    return [normalize_title(fields.get("title", "")) for _, _, fields in iter_bib_entries(text)]


def existing_keys(bib_text: str) -> set[str]:
    """Citation keys already used in *bib_text*."""
    return {key for _, key, _ in iter_bib_entries(bib_text)}


def similar_titles(title_a: str, title_b: str) -> bool:
    if not title_a or not title_b:
        return False
    return SequenceMatcher(None, title_a, title_b).ratio() >= FUZZY_TITLE_THRESHOLD


def is_known_title(title: str, known_titles: list[str]) -> bool:
    """True if normalized *title* equals or closely resembles any of *known_titles*."""
    return any(title == known or similar_titles(title, known) for known in known_titles)


def _as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _merge_pair(kept: dict, other: dict) -> dict:
    """Merge two records of the same paper: the DOI-bearing one wins, sources are unioned."""
    base, extra = (other, kept) if (other.get("doi") and not kept.get("doi")) else (kept, other)
    merged = dict(base)
    merged["source"] = sorted(set(_as_list(kept["source"])) | set(_as_list(other["source"])))
    for key in ("venue", "year", "url", "arxiv_id", "matched_snippet"):
        merged[key] = merged.get(key) or extra.get(key)
    return merged


def merge_duplicates(candidates: list[dict]) -> list[dict]:
    """Collapse records of the same paper (same id, or near-identical title) across sources."""
    merged: list[dict] = []
    for candidate in candidates:
        candidate = {**candidate, "source": _as_list(candidate.get("source", []))}
        title = normalize_title(candidate["title"])
        for index, kept in enumerate(merged):
            kept_title = normalize_title(kept["title"])
            if kept["id"] == candidate["id"] or similar_titles(title, kept_title):
                merged[index] = _merge_pair(kept, candidate)
                break
        else:
            merged.append(candidate)
    return merged


def deduplicate(candidates: list[dict], bib_titles: list[str], decided_ids: set[str]) -> list[dict]:
    """Drop candidates already in the bib or already accepted/rejected; merge cross-source dupes.

    `decided_ids` must hold only accept/reject decisions: a deferred candidate stays visible.
    """
    kept = []
    for candidate in merge_duplicates(candidates):
        title = normalize_title(candidate["title"])
        if candidate["id"] in decided_ids:
            continue
        if is_known_title(title, bib_titles):
            continue
        kept.append(candidate)
    return kept


# --------------------------------------------------------------------------- #
# BibTeX drafting
# --------------------------------------------------------------------------- #
def _author_surname(authors: list[str]) -> str:
    surname = authors[0].split(",")[0].split()[-1] if authors else "Anon"
    return re.sub(r"[^\w-]", "", surname) or "Anon"


def make_key(candidate: dict, taken_keys: set[str] = frozenset()) -> str:
    """Key in the existing `Lastname<year>-xx` style, unique among *taken_keys*."""
    stem = f"{_author_surname(candidate.get('authors') or [])}{candidate.get('year') or ''}"
    digest = hashlib.sha1(candidate["id"].encode()).hexdigest()
    letters = [chr(ord("a") + int(digest[i : i + 2], 16) % 26) for i in range(0, 40, 2)]
    for first, second in zip(letters, letters[1:]):
        key = f"{stem}-{first}{second}"
        if key not in taken_keys:
            return key
    raise ValueError(f"no free key for {stem}")


def _escape(text: str) -> str:
    return text.replace('"', "'")


def build_bibtex(candidate: dict, key: str) -> str:
    """Minimal BibTeX entry from candidate metadata alone (arXiv gets an `@ARTICLE` preprint)."""
    fields = {
        "title": _escape(candidate["title"]),
        "author": " and ".join(candidate.get("authors") or []) or "Anonymous",
    }
    if candidate.get("arxiv_id"):
        fields.update(journal="arXiv", archivePrefix="arXiv", eprint=candidate["arxiv_id"])
    elif candidate.get("venue"):
        fields["journal"] = _escape(candidate["venue"])
    if normalize_doi(candidate.get("doi")):
        fields["doi"] = normalize_doi(candidate["doi"])
    if candidate.get("url"):
        fields["url"] = candidate["url"]
    body = ",\n".join(f'  {name:<9} = "{value}"' for name, value in fields.items())
    if candidate.get("year"):
        body += f",\n  year      =  {candidate['year']}"
    return f"@ARTICLE{{{key},\n{body}\n}}"


# (connect, read) seconds. A short connect timeout lets a host with a dead IPv6 route fall
# back to IPv4 quickly: requests tries each address in turn, with the full timeout apiece.
REQUEST_TIMEOUT = (5, 30)


def fetch_doi_bibtex(doi: str, timeout=REQUEST_TIMEOUT) -> str | None:
    """BibTeX for *doi* via doi.org content negotiation, or None if it cannot be had."""
    try:
        response = requests.get(
            f"https://doi.org/{normalize_doi(doi)}",
            headers={"Accept": "application/x-bibtex"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    text = response.text.strip()
    return text if text.startswith("@") else None


def format_entry(entry_type: str, key: str, fields: dict) -> str:
    """Render an entry in the reference list's style: one `name = {value}` line per field."""
    lines = [f"  {name:<9} = {value if name == 'year' else '{' + value + '}'}"
             for name, value in fields.items()]
    return f"@{entry_type.upper()}{{{key},\n" + ",\n".join(lines) + "\n}"


def _rekey_and_retype(bibtex: str, key: str) -> str | None:
    """Re-render fetched *bibtex* under our key; theses become `@PHDTHESIS` with a `school`.

    None if the text holds no parseable entry (the caller then builds one from metadata).
    """
    bibtex = bibtex.strip()
    if not bibtex.endswith("\n}"):  # doi.org returns one line; our parser wants a closing "\n}"
        bibtex = bibtex[:-1].rstrip() + "\n}"
    entries = list(iter_bib_entries(bibtex))
    if len(entries) != 1:
        return None
    entry_type, _, fields = entries[0]
    if classify_entry(entry_type, fields) == "Thesis" and entry_type.upper() != "PHDTHESIS":
        entry_type = "PHDTHESIS"
        fields.setdefault("school", fields.get("institution") or fields.get("publisher")
                          or fields.get("journal", ""))
    return format_entry(entry_type, key, fields)


def draft_bibtex(candidate: dict, taken_keys: set[str] = frozenset(),
                 fetch=fetch_doi_bibtex) -> str:
    """Draft a BibTeX entry: from the DOI if it resolves, otherwise built from the metadata."""
    key = make_key(candidate, taken_keys)
    fetched = fetch(candidate["doi"]) if candidate.get("doi") else None
    return (_rekey_and_retype(fetched, key) if fetched else None) or build_bibtex(candidate, key)


# --------------------------------------------------------------------------- #
# Writing back
# --------------------------------------------------------------------------- #
def append_entries(bib_text: str, entries: list[str]) -> str:
    """Append *entries* to *bib_text*, one blank line apart, keeping the file parseable."""
    text = bib_text.rstrip("\n") + "\n"
    for entry in entries:
        text += "\n" + entry.strip() + "\n"
    return text


def update_sidecar(sidecar: dict, search_date: str, sources: list[dict]) -> dict:
    """New sidecar dict with `SearchDate` advanced and *sources* appended (input not mutated)."""
    updated = {**sidecar, "SearchDate": search_date}
    updated["Sources"] = [*sidecar.get("Sources", []), *sources]
    return updated
