"""Parse a BibTeX file into a tidy table of papers using CNeuroMod data, by year and type."""

import re
from pathlib import Path

import pandas as pd

_PREPRINT = re.compile(r"biorxiv|arxiv|psyarxiv", re.IGNORECASE)
_THESIS = re.compile(
    r"scholaris|theses\.hal|repozitorij|teses\.|umontreal\.ca|thesis", re.IGNORECASE
)
_CONFERENCE = re.compile(r"openreview\.net|proceedings|neurips|icml|iclr", re.IGNORECASE)

# BibTeX entry types whose publication type is known from the type alone.
_TYPE_BY_ENTRY = {
    "INPROCEEDINGS": "Conference",
    "INCOLLECTION": "Book Chapter",
    "PHDTHESIS": "Thesis",
    "MASTERSTHESIS": "Thesis",
}


def classify_entry(entry_type: str, fields: dict) -> str:
    """Publication type of one entry: Journal, Preprint, Conference, Thesis, Book Chapter, Other.

    ARTICLE entries need a closer look: reference managers file preprints,
    theses and conference papers as articles, so the venue fields decide. MISC
    entries are preprints when the venue is a preprint server (DOI-resolved arXiv
    records come as MISC with publisher arXiv), and Other otherwise.
    """
    entry_type = entry_type.upper()
    if entry_type in _TYPE_BY_ENTRY:
        return _TYPE_BY_ENTRY[entry_type]
    if entry_type not in ("ARTICLE", "MISC"):
        return "Other"

    venue = " ".join(fields.get(key, "") for key in ("journal", "institution", "publisher"))
    if _PREPRINT.search(venue):
        return "Preprint"
    if entry_type == "MISC":
        return "Other"
    if _THESIS.search(venue):
        return "Thesis"
    if _CONFERENCE.search(venue):
        return "Conference"
    return "Journal"


def parse_fields(fields_text: str) -> dict:
    """Extract key=value pairs from a BibTeX entry body (handles one level of nested braces)."""
    fields: dict = {}
    for match in re.finditer(
        r"(\w+)\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|\"([^\"]*)\"|(\d+))",
        fields_text,
        re.DOTALL,
    ):
        key = match.group(1).lower()
        value = match.group(2) or match.group(3) or match.group(4) or ""
        fields[key] = value.strip()
    return fields


def iter_bib_entries(bib_text: str):
    """Yield (entry_type, key, fields) for each BibTeX entry in *bib_text*."""
    for match in re.finditer(r"@(\w+)\{([^,]+),(.*?)\n\}", bib_text, re.DOTALL):
        yield match.group(1), match.group(2), parse_fields(match.group(3))


def parse_bib_entries(bib_path: Path) -> list[dict]:
    """One record per BibTeX entry, with its `year` (or None) and publication `type`."""
    text = Path(bib_path).read_text(encoding="utf-8")
    records = []
    for entry_type, _key, fields in iter_bib_entries(text):
        year = fields.get("year", "")
        records.append({
            "year": int(year) if year.isdigit() else None,
            "type": classify_entry(entry_type, fields),
        })
    return records


def parse_bib_to_table(bib_path: Path, max_entries: int | None = None) -> pd.DataFrame:
    """Tidy table of *bib_path* with columns year, type, count.

    `max_entries` keeps only the first entries, for a fast smoke run.
    """
    records = parse_bib_entries(bib_path)[:max_entries]
    entries = pd.DataFrame(records, columns=["year", "type"])
    entries["year"] = entries["year"].astype("Int64")
    return (
        entries.groupby(["year", "type"], dropna=False)
        .size()
        .reset_index(name="count")
    )
