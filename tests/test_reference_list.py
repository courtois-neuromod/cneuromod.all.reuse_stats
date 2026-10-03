"""Unit tests for analysis.reference_list and analysis.literature_search (network mocked)."""

import pytest
import requests

from analysis import literature_search
from analysis.citations import classify_entry, iter_bib_entries, parse_bib_entries
from analysis.reference_list import (
    append_entries,
    build_bibtex,
    candidate_id,
    deduplicate,
    draft_bibtex,
    existing_titles,
    make_key,
    normalize_title,
    update_sidecar,
)

BIB = """\
@ARTICLE{St-Laurent2026-zc,
  title     = "{CNeuroMod}-{THINGS}, a densely-sampled {fMRI} dataset",
  journal   = "Sci. Data",
  year      =  2026
}
"""


def candidate(title, doi=None, source="europepmc", **extra):
    return {"id": candidate_id(doi, None, title), "title": title, "doi": doi, "source": [source],
            "authors": ["Doe, J"], "year": 2026, "venue": "", **extra}


def test_normalize_title_strips_braces_latex_punctuation():
    assert normalize_title("{CNeuroMod}-{THINGS}, a \\textit{dense}  dataset!") == (
        "cneuromod things a dense dataset")


def test_candidate_id_prefers_doi_then_arxiv_then_slug():
    assert candidate_id("https://doi.org/10.1/ABC", "2501.1", "T") == "10.1/abc"
    assert candidate_id(None, "2501.1", "T") == "arxiv:2501.1"
    assert candidate_id(None, None, "A  Title!") == "title:a-title"


def test_existing_titles(tmp_path):
    path = tmp_path / "refs.bib"
    path.write_text(BIB, encoding="utf-8")
    assert existing_titles(path) == ["cneuromod things a densely sampled fmri dataset"]


def test_deduplicate_drops_bib_entries_exact_and_fuzzy():
    bib_titles = existing_titles_from(BIB)
    exact = candidate("CNeuroMod-THINGS, a densely-sampled fMRI dataset")
    fuzzy = candidate("CNeuroMod-THINGS: a densely sampled fMRI dataset.")
    other = candidate("Something entirely different")
    assert deduplicate([exact, fuzzy, other], bib_titles, set()) == [
        {**other, "source": ["europepmc"]}]


def existing_titles_from(text):
    return [normalize_title(fields["title"]) for _, _, fields in iter_bib_entries(text)]


def test_deduplicate_drops_decided_but_keeps_deferred():
    decided = candidate("Decided paper", doi="10.1/a")
    deferred = candidate("Deferred paper", doi="10.1/b")
    kept = deduplicate([decided, deferred], [], {decided["id"]})
    assert [c["id"] for c in kept] == [deferred["id"]]


def test_deduplicate_merges_across_sources_keeping_doi_record():
    from_arxiv = {**candidate("Same paper here", source="arxiv"), "id": "arxiv:1", "arxiv_id": "1"}
    from_epmc = candidate("Same paper here", doi="10.1/x", source="europepmc")
    [merged] = deduplicate([from_arxiv, from_epmc], [], set())
    assert merged["doi"] == "10.1/x"
    assert merged["source"] == ["arxiv", "europepmc"]


def test_make_key_style_and_uniqueness():
    paper = candidate("A paper", doi="10.1/z")
    key = make_key(paper)
    assert key.startswith("Doe2026-") and len(key) == len("Doe2026-xx")
    assert make_key(paper, {key}) != key


def test_build_bibtex_arxiv_is_a_preprint_the_parser_understands():
    paper = {**candidate("An arXiv paper"), "arxiv_id": "2501.00001", "id": "arxiv:2501.00001"}
    bibtex = build_bibtex(paper, "Doe2026-ab")
    [(entry_type, key, fields)] = iter_bib_entries(bibtex)
    assert (entry_type, key) == ("ARTICLE", "Doe2026-ab")
    assert fields["archiveprefix"] == "arXiv"
    assert classify_entry(entry_type, fields) == "Preprint"


def test_draft_bibtex_from_doi_is_rekeyed_and_parseable():
    fetched = '@article{Doe_2026, title={A {CNeuroMod} paper}, volume={1}, journal={Sci. Data}}'
    paper = candidate("A CNeuroMod paper", doi="10.1/z")
    [(entry_type, key, fields)] = iter_bib_entries(draft_bibtex(paper, fetch=lambda doi: fetched))
    assert key.startswith("Doe2026-") and entry_type == "ARTICLE"
    assert classify_entry(entry_type, fields) == "Journal"


def test_draft_bibtex_files_a_thesis_as_phdthesis_with_school():
    fetched = '@article{x, title={A thesis}, journal={theses.hal.science}}'
    paper = candidate("A thesis", doi="10.1/t")
    [(entry_type, _, fields)] = iter_bib_entries(draft_bibtex(paper, fetch=lambda doi: fetched))
    assert entry_type == "PHDTHESIS"
    assert fields["school"] == "theses.hal.science"
    assert classify_entry(entry_type, fields) == "Thesis"


def test_draft_bibtex_falls_back_when_doi_does_not_resolve():
    paper = candidate("Unresolvable", doi="10.1/none")
    assert draft_bibtex(paper, fetch=lambda doi: None).startswith("@ARTICLE{Doe2026-")


def test_append_entries_keeps_file_parseable(tmp_path):
    new = build_bibtex(candidate("Appended paper"), "Doe2026-zz")
    path = tmp_path / "refs.bib"
    path.write_text(append_entries(BIB, [new, new.replace("zz", "yy")]), encoding="utf-8")
    assert len(parse_bib_entries(path)) == 3
    assert path.read_text().endswith("}\n")


def test_update_sidecar_does_not_mutate_input():
    sidecar = {"SearchDate": "2026-05-04", "Sources": [{"Database": "Google Scholar"}]}
    updated = update_sidecar(sidecar, "2026-10-03", [{"Database": "OpenAlex"}])
    assert updated["SearchDate"] == "2026-10-03"
    assert [s["Database"] for s in updated["Sources"]] == ["Google Scholar", "OpenAlex"]
    assert sidecar["SearchDate"] == "2026-05-04" and len(sidecar["Sources"]) == 1


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload, self.content = payload, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_search_europepmc_normalizes_hits(monkeypatch):
    payload = {"resultList": {"result": [{
        "title": "A  paper", "authorString": "Smith AB, Jones C.", "pubYear": "2026",
        "journalTitle": "Sci. Data", "doi": "10.1/EPMC", "abstractText": "uses cneuromod"}]}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(payload))
    [hit] = literature_search.search_europepmc("cneuromod", "2026-05-04")
    assert hit["id"] == "10.1/epmc" and hit["authors"] == ["Smith, AB", "Jones, C"]
    assert hit["year"] == 2026 and hit["source"] == ["europepmc"]


def test_search_openalex_rebuilds_abstract(monkeypatch):
    payload = {"results": [{
        "title": "Work", "doi": "https://doi.org/10.1/oa", "publication_year": 2026,
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "primary_location": {"source": {"display_name": "Nature"}},
        "abstract_inverted_index": {"uses": [0], "cneuromod": [1]}}]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(payload))
    [hit] = literature_search.search_openalex("cneuromod", "2026-05-04")
    assert hit["matched_snippet"] == "uses cneuromod" and hit["venue"] == "Nature"


def test_search_arxiv_filters_by_date(monkeypatch):
    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>http://arxiv.org/abs/2601.00001v2</id><published>2026-06-01T00:00:00Z</published>
        <title>New</title><summary>s</summary><author><name>A B</name></author></entry>
      <entry><id>http://arxiv.org/abs/2401.00001v1</id><published>2024-01-01T00:00:00Z</published>
        <title>Old</title><summary>s</summary><author><name>C D</name></author></entry>
    </feed>"""
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(content=feed))
    [hit] = literature_search.search_arxiv("cneuromod", "2026-05-04")
    assert hit["id"] == "arxiv:2601.00001" and hit["title"] == "New"


def test_run_searches_survives_a_failing_source(monkeypatch):
    def fake_get(url, *args, **kwargs):
        if "europepmc" in url:
            raise requests.ConnectionError("down")
        return FakeResponse({"results": []})

    monkeypatch.setattr(requests, "get", fake_get)
    hits, counts = literature_search.run_searches(["europepmc", "openalex"], ["q"], "2026-01-01")
    assert hits == [] and counts["openalex"] == {"q": 0}
    assert counts["europepmc"]["q"].startswith("error")


def test_unknown_source_is_a_keyerror_not_silence():
    with pytest.raises(KeyError):
        literature_search.SEARCHERS["nope"]


def test_fetched_bibtex_is_rendered_in_the_reference_list_style():
    fetched = '@article{x, title={A {CNeuroMod} paper}, journal={Sci. Data}, year={2026}}'
    bibtex = draft_bibtex(candidate("A CNeuroMod paper", doi="10.1/z"), fetch=lambda doi: fetched)
    lines = bibtex.splitlines()
    assert lines[1].startswith("  title     = {A {CNeuroMod} paper}")
    assert lines[3] == "  year      = 2026"
    assert lines[-1] == "}"
