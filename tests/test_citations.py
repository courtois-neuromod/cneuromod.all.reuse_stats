"""Unit tests for analysis.citations."""

import pytest

from analysis.citations import classify_entry, parse_bib_entries, parse_bib_to_table

BIB = """\
@ARTICLE{journal2023,
  title     = "A {CNeuroMod} study with {nested} braces",
  journal   = "Sci. Data",
  year      =  2023
}

@ARTICLE{preprint2023,
  title     = "A preprint",
  journal   = "bioRxiv",
  year      =  2023
}

@PHDTHESIS{thesis2025,
  title     = "A thesis",
  school    = "Université de Montréal",
  year      =  2025
}

@INPROCEEDINGS{conference2024,
  title     = "A conference paper",
  booktitle = "NeurIPS",
  year      =  2024
}

@MISC{undated,
  title     = "No year at all"
}
"""


@pytest.fixture
def bib_path(tmp_path):
    path = tmp_path / "references.bib"
    path.write_text(BIB, encoding="utf-8")
    return path


@pytest.mark.parametrize("entry_type, fields, expected", [
    ("ARTICLE", {"journal": "Sci. Data"}, "Journal"),
    ("ARTICLE", {"journal": "bioRxiv"}, "Preprint"),
    ("ARTICLE", {"publisher": "openRxiv"}, "Preprint"),
    ("ARTICLE", {"publisher": "theses.hal.science"}, "Thesis"),
    ("ARTICLE", {"journal": "openreview.net"}, "Conference"),
    ("PHDTHESIS", {}, "Thesis"),
    ("mastersthesis", {}, "Thesis"),
    ("INPROCEEDINGS", {}, "Conference"),
    ("INCOLLECTION", {}, "Book Chapter"),
    ("MISC", {}, "Other"),
    ("MISC", {"publisher": "arXiv"}, "Preprint"),
    ("MISC", {"publisher": "Zenodo"}, "Other"),
])
def test_classify_entry(entry_type, fields, expected):
    assert classify_entry(entry_type, fields) == expected


def test_parse_bib_entries(bib_path):
    records = parse_bib_entries(bib_path)
    assert records == [
        {"year": 2023, "type": "Journal"},
        {"year": 2023, "type": "Preprint"},
        {"year": 2025, "type": "Thesis"},
        {"year": 2024, "type": "Conference"},
        {"year": None, "type": "Other"},
    ]


def test_parse_bib_to_table_counts_every_entry(bib_path):
    table = parse_bib_to_table(bib_path)
    assert list(table.columns) == ["year", "type", "count"]
    assert table["count"].sum() == 5
    assert str(table["year"].dtype) == "Int64"
    assert table["year"].isna().sum() == 1


def test_parse_bib_to_table_max_entries(bib_path):
    table = parse_bib_to_table(bib_path, max_entries=2)
    assert table["count"].sum() == 2
