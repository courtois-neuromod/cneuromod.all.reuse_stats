"""Query open scholarly APIs for papers that may use CNeuroMod data.

Each `search_*` function returns normalized candidate dicts (see `analysis.reference_list`).
These are leads for a human to verify, not decisions: a hit may merely cite CNeuroMod.
"""

import xml.etree.ElementTree as ET

import requests

from analysis.reference_list import REQUEST_TIMEOUT, candidate_id, normalize_doi

EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENALEX_URL = "https://api.openalex.org/works"
ARXIV_URL = "https://export.arxiv.org/api/query"
SNIPPET_LENGTH = 300
_ATOM = {"atom": "http://www.w3.org/2005/Atom"}


def _get(url: str, params: dict, contact_email: str | None) -> requests.Response:
    """GET with a polite User-Agent (and contact address, when configured)."""
    user_agent = "cneuromod-reuse-stats (literature curation)"
    if contact_email:
        user_agent += f"; mailto:{contact_email}"
    response = requests.get(url, params=params, headers={"User-Agent": user_agent},
                            timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response


def _candidate(*, title, authors, year, venue, doi, arxiv_id, url, source, query, snippet) -> dict:
    title = " ".join((title or "").split())
    return {
        "id": candidate_id(doi, arxiv_id, title),
        "title": title,
        "authors": authors,
        "year": int(year) if str(year or "").isdigit() else None,
        "venue": venue or "",
        "doi": normalize_doi(doi) or None,
        "arxiv_id": arxiv_id,
        "url": url or (f"https://doi.org/{normalize_doi(doi)}" if doi else ""),
        "source": [source],
        "query": query,
        "matched_snippet": " ".join((snippet or "").split())[:SNIPPET_LENGTH],
    }


def _europepmc_authors(author_string: str) -> list[str]:
    """'Smith AB, Jones C.' -> ['Smith, AB', 'Jones, C']."""
    names = [name.strip() for name in (author_string or "").rstrip(".").split(", ") if name.strip()]
    return [", ".join(name.rsplit(" ", 1)) if " " in name else name for name in names]


def search_europepmc(query, since, max_results=100, contact_email=None) -> list[dict]:
    """Europe PMC (OA full text, bioRxiv/PsyArXiv preprints), first published since *since*."""
    params = {
        "query": f'"{query}" AND FIRST_PDATE:[{since} TO *]',
        "format": "json",
        "resultType": "core",
        "pageSize": max_results,
    }
    results = _get(EUROPEPMC_URL, params, contact_email).json()["resultList"]["result"]
    return [
        _candidate(
            title=hit.get("title"),
            authors=_europepmc_authors(hit.get("authorString")),
            year=hit.get("pubYear"),
            venue=(hit.get("journalInfo") or {}).get("journal", {}).get("title")
            or hit.get("journalTitle")
            or (hit.get("bookOrReportDetails") or {}).get("publisher"),
            doi=hit.get("doi"),
            arxiv_id=None,
            url=None,
            source="europepmc",
            query=query,
            snippet=hit.get("abstractText"),
        )
        for hit in results[:max_results]
    ]


def _openalex_abstract(inverted_index: dict | None) -> str:
    """OpenAlex ships abstracts as {word: [positions]}; put the words back in order."""
    words = {pos: word for word, positions in (inverted_index or {}).items() for pos in positions}
    return " ".join(words[pos] for pos in sorted(words))


def search_openalex(query, since, max_results=100, contact_email=None) -> list[dict]:
    """OpenAlex works matching *query* (title, abstract, indexed full text) since *since*."""
    params = {
        "search": query,
        "filter": f"from_publication_date:{since}",
        "per-page": min(max_results, 200),
    }
    if contact_email:
        params["mailto"] = contact_email
    results = _get(OPENALEX_URL, params, contact_email).json()["results"]
    return [
        _candidate(
            title=work.get("title"),
            authors=[a["author"]["display_name"] for a in work.get("authorships", [])],
            year=work.get("publication_year"),
            venue=((work.get("primary_location") or {}).get("source") or {}).get("display_name"),
            doi=work.get("doi"),
            arxiv_id=None,
            url=None,
            source="openalex",
            query=query,
            snippet=_openalex_abstract(work.get("abstract_inverted_index")),
        )
        for work in results[:max_results]
    ]


def search_arxiv(query, since, max_results=100, contact_email=None) -> list[dict]:
    """arXiv (title/abstract) submissions on or after *since*, newest first."""
    params = {
        "search_query": f'all:"{query}"',
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    root = ET.fromstring(_get(ARXIV_URL, params, contact_email).content)
    candidates = []
    for entry in root.findall("atom:entry", _ATOM):
        published = entry.findtext("atom:published", "", _ATOM)[:10]
        if published < since:
            continue
        abs_url = entry.findtext("atom:id", "", _ATOM)
        candidates.append(_candidate(
            title=entry.findtext("atom:title", "", _ATOM),
            authors=[a.findtext("atom:name", "", _ATOM)
                     for a in entry.findall("atom:author", _ATOM)],
            year=published[:4],
            venue="arXiv",
            doi=entry.findtext("{http://arxiv.org/schemas/atom}doi"),
            arxiv_id=abs_url.rsplit("/abs/", 1)[-1].split("v")[0],
            url=abs_url,
            source="arxiv",
            query=query,
            snippet=entry.findtext("atom:summary", "", _ATOM),
        ))
    return candidates


SEARCHERS = {"europepmc": search_europepmc, "openalex": search_openalex, "arxiv": search_arxiv}


def run_searches(sources, queries, since, max_results=100, contact_email=None):
    """Run every (source, query) pair; return (all candidates, per-source hit counts).

    A source that fails (network, rate limit) is reported in the counts as an error string
    and skipped, so one flaky API does not lose the others' results.
    """
    candidates: list[dict] = []
    hit_counts: dict = {}
    for source in sources:
        hit_counts[source] = {}
        for query in queries:
            try:
                hits = SEARCHERS[source](query, since, max_results, contact_email)
            except (requests.RequestException, ET.ParseError, KeyError, ValueError) as error:
                print(f"⚠️  {source} / {query!r}: {error}")
                hit_counts[source][query] = f"error: {error}"
                continue
            hit_counts[source][query] = len(hits)
            candidates.extend(hits)
    return candidates, hit_counts
