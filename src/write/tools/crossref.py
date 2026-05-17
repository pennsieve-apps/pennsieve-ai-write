"""CrossRef DOI metadata — universal fallback for any DOI.

Used by `doi_lookup` for journal articles, conference papers, protocols.io
deposits, and most preprints. Free, no auth required.
"""
from __future__ import annotations

import re

import httpx

BASE = "https://api.crossref.org"


def _strip_doi(doi: str) -> str:
    s = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    return s


def _strip_jats(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).strip()


def fetch_doi_metadata(doi: str) -> dict | None:
    """Return a record-shaped dict for any DOI registered with CrossRef:
        {doi, title, abstract, year, authors, journal, source}
    Returns None on 404 / network error.
    """
    norm = _strip_doi(doi)
    if not norm:
        return None
    try:
        r = httpx.get(
            f"{BASE}/works/{norm}",
            timeout=20,
            headers={"User-Agent": "pennsieve-ai-write (mailto:joost.wagenaar2@pennmedicine.upenn.edu)"},
        )
        if r.status_code != 200:
            return None
        msg = r.json().get("message") or {}
    except httpx.HTTPError:
        return None

    title = " ".join(msg.get("title") or []).strip()
    abstract = _strip_jats(msg.get("abstract", "") or "")
    authors_raw = msg.get("author") or []
    authors = ", ".join(
        f"{a.get('given','').strip()} {a.get('family','').strip()}".strip()
        for a in authors_raw[:8]
        if a.get("given") or a.get("family")
    )
    for key in ("published-print", "published-online", "issued", "created"):
        date_obj = msg.get(key) or {}
        parts = (date_obj.get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            year = str(parts[0])
            break
    else:
        year = ""

    venue = " ".join(msg.get("container-title") or []).strip()
    if not venue:
        venue = msg.get("type", "") or msg.get("publisher", "")

    return {
        "doi": norm,
        "title": title,
        "abstract": abstract,
        "year": year,
        "authors": authors,
        "journal": venue,
        "source": "crossref",
    }
