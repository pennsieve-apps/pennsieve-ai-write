"""Caching DOI metadata lookup — single source of truth for author/year/title
strings used in inline citations.

Backed by CrossRef + DataCite (CrossRef first, DataCite as fallback for
dataset / institutional-repository DOIs). Persistent process-local cache.
For the compute-node deployment we don't have a persistent volume the
cache file could live on across executions — this implementation keeps
the cache in memory only, which is fine for a single-execution run with
~20–60 DOIs.

Public API:
  - `lookup(doi)` → metadata dict or None
  - `lookup_batch(dois)` → {doi: metadata}
  - `author_string(doi, fallback)` → "Bayles et al., 2018" formatting helper
"""
from __future__ import annotations

import threading

from write.tools import crossref, datacite

_lock = threading.Lock()
_cache: dict = {}


def _normalize(doi: str) -> str:
    s = (doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s.strip()


def lookup(doi: str) -> dict | None:
    """Return metadata for a DOI: `{doi, title, authors, year, journal, source}`.

    Tries CrossRef first, falls back to DataCite. Negative results are
    cached so we don't retry persistently-missing DOIs within a run.
    """
    d = _normalize(doi)
    if not d:
        return None
    with _lock:
        if d in _cache:
            return _cache[d]
        md = crossref.fetch_doi_metadata(d)
        if not md:
            md = datacite.fetch_doi_metadata(d)
        _cache[d] = md  # may store None (negative cache)
    return md


def lookup_batch(dois: list[str]) -> dict[str, dict]:
    """Resolve many DOIs at once. Returns `{doi: metadata}` for any that
    resolve; missing/failed DOIs are silently dropped."""
    out: dict[str, dict] = {}
    for doi in dois:
        md = lookup(doi)
        if md:
            out[_normalize(doi)] = md
    return out


def author_string(doi: str, fallback: str = "") -> str:
    """Render authors as 'Bayles et al., 2018' for inline citations.
    Returns `fallback` if metadata isn't available."""
    md = lookup(doi)
    if not md:
        return fallback
    authors = (md.get("authors") or "").strip()
    year = (md.get("year") or "").strip()
    if not authors:
        return year or fallback
    parts = authors.split(",")
    first_full = parts[0].strip().split()
    last_name = first_full[-1] if first_full else ""
    if not last_name:
        return year or fallback
    suffix = " et al." if len(parts) > 1 else ""
    base = f"{last_name}{suffix}"
    return f"{base}, {year}" if year else base
