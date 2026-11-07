"""Checks source records attached to a topic.

This module does NOT search the internet or invent sources. It checks that
the sources a person has recorded are complete and flags how trustworthy
the website type looks. A human decides whether a source really supports
a claim.
"""
import re
from urllib.parse import urlparse

REQUIRED_FIELDS = ("id", "title", "publisher", "url", "date_accessed")

PREFERRED_SUFFIXES = (
    "nasa.gov", "nist.gov", "noaa.gov", "cern.ch", "home.cern", "esa.int",
    "nature.com", "science.org", "aps.org", "iop.org", "royalsociety.org",
    "nobelprize.org", ".edu", ".gov", ".ac.uk",
)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def domain_tier(url):
    host = (urlparse(url).hostname or "").lower()
    for suffix in PREFERRED_SUFFIXES:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            return "preferred"
    return "needs_review"


def validate_sources(sources):
    """Returns (errors, warnings, known_ids)."""
    errors, warnings, ids = [], [], []
    if not isinstance(sources, list) or not sources:
        return ["No sources recorded."], warnings, ids

    for index, source in enumerate(sources):
        label = source.get("id", f"#{index + 1}") if isinstance(source, dict) else f"#{index + 1}"
        if not isinstance(source, dict):
            errors.append(f"Source {label}: must be an object.")
            continue
        for field in REQUIRED_FIELDS:
            if not source.get(field):
                errors.append(f"Source {label}: missing '{field}'.")
        url = source.get("url", "")
        if url and not url.startswith("https://"):
            errors.append(f"Source {label}: url must start with https://")
        for date_field in ("date_published", "date_updated", "date_accessed"):
            value = source.get(date_field)
            if value is not None and not DATE_PATTERN.match(str(value)):
                errors.append(f"Source {label}: {date_field} must look like YYYY-MM-DD.")
        if url.startswith("https://") and domain_tier(url) == "needs_review":
            warnings.append(f"Source {label}: not on the preferred list; needs human review.")
        if source.get("id"):
            ids.append(source["id"])

    if len(ids) != len(set(ids)):
        errors.append("Duplicate source ids.")
    return errors, warnings, ids
