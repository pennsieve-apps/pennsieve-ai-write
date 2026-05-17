"""DataCite DOI metadata — for dataset / preprint / repository DOIs that
CrossRef doesn't index (Pennsieve, Zenodo, Dryad, Figshare, FAIRsharing,
institutional repositories, DataCite-side preprints).

Used as a fallback in `doi_lookup` when CrossRef returns nothing.
"""
from __future__ import annotations

import re

import httpx

BASE = "https://api.datacite.org"


def _strip_doi(doi: str) -> str:
    s = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    return s


def _author_name(creator: dict) -> str:
    given = (creator.get("givenName") or "").strip()
    family = (creator.get("familyName") or "").strip()
    if given or family:
        return f"{given} {family}".strip()
    name = (creator.get("name") or "").strip()
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return name


def fetch_doi_metadata(doi: str) -> dict | None:
    """Return a record-shaped dict for any DataCite-registered DOI.
    Output shape matches `crossref.fetch_doi_metadata`; `journal` carries
    the publisher / repository name for datasets.
    """
    norm = _strip_doi(doi)
    if not norm:
        return None
    try:
        r = httpx.get(
            f"{BASE}/dois/{norm}",
            timeout=20,
            headers={"User-Agent": "pennsieve-ai-write (mailto:joost.wagenaar2@pennmedicine.upenn.edu)"},
        )
        if r.status_code != 200:
            return None
        attrs = (r.json().get("data") or {}).get("attributes") or {}
    except httpx.HTTPError:
        return None

    titles = attrs.get("titles") or []
    title = ""
    for t in titles:
        if not t.get("titleType"):
            title = (t.get("title") or "").strip()
            break
    if not title and titles:
        title = (titles[0].get("title") or "").strip()

    descriptions = attrs.get("descriptions") or []
    abstract = ""
    for d in descriptions:
        if (d.get("descriptionType") or "").lower() == "abstract":
            abstract = (d.get("description") or "").strip()
            break
    if not abstract and descriptions:
        abstract = (descriptions[0].get("description") or "").strip()
    abstract = re.sub(r"<[^>]+>", " ", abstract).strip()

    year_val = attrs.get("publicationYear")
    year = str(year_val) if year_val else ""

    creators = attrs.get("creators") or []
    authors = ", ".join(
        _author_name(c) for c in creators[:8] if _author_name(c)
    )

    venue = (attrs.get("publisher") or "").strip()
    rt = ((attrs.get("types") or {}).get("resourceTypeGeneral") or "").strip()
    if rt and venue and rt.lower() not in venue.lower():
        venue = f"{venue} ({rt})"
    elif rt and not venue:
        venue = rt

    return {
        "doi": norm,
        "title": title,
        "abstract": abstract,
        "year": year,
        "authors": authors,
        "journal": venue,
        "source": "datacite",
    }
