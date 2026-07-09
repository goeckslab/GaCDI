"""cBioPortal client: list clinical attributes and fetch per-sample values.

Attribute ids (e.g. ``SUBTYPE`` for PAM50, ``ER_STATUS_BY_IHC``) are
study-specific, so we do not hard-map them: the caller supplies the study id and
an optional attribute list (or ``all``). Sample ids look like ``TCGA-XX-XXXX-01``.
"""

from __future__ import annotations

import logging

import requests

from .errors import ApiError

log = logging.getLogger("gacdi_manifest.cbioportal")

DEFAULT_BASE = "https://www.cbioportal.org/api"


def list_attributes(session: requests.Session, study_id: str, *, base: str = DEFAULT_BASE) -> list[dict]:
    """Return the clinical attributes defined for *study_id*."""
    url = f"{base.rstrip('/')}/studies/{study_id}/clinical-attributes"
    resp = session.get(url, timeout=60)
    if resp.status_code >= 400:
        raise ApiError(f"cBioPortal HTTP {resp.status_code} for {url}: {resp.text[:200]}")
    return resp.json()


def fetch_sample_clinical(
    session: requests.Session,
    study_id: str,
    *,
    attribute_ids: list[str] | None = None,
    base: str = DEFAULT_BASE,
) -> tuple[dict[str, dict], list[str]]:
    """Return ``{sample_id: {attr: value}}`` and the ordered attribute columns.

    Fetches all SAMPLE-level clinical data for the study and pivots it; if
    *attribute_ids* is given, only those attributes are kept.
    """
    url = f"{base.rstrip('/')}/studies/{study_id}/clinical-data"
    resp = session.get(url, params={"clinicalDataType": "SAMPLE", "projection": "SUMMARY"}, timeout=120)
    if resp.status_code >= 400:
        raise ApiError(f"cBioPortal HTTP {resp.status_code} for {url}: {resp.text[:200]}")
    records = resp.json()

    keep = set(attribute_ids) if attribute_ids else None
    by_sample: dict[str, dict] = {}
    columns: list[str] = []
    for rec in records:
        attr = rec.get("clinicalAttributeId")
        sample = rec.get("sampleId")
        if not attr or not sample:
            continue
        if keep is not None and attr not in keep:
            continue
        by_sample.setdefault(sample, {})[attr] = rec.get("value", "")
        if attr not in columns:
            columns.append(attr)

    if attribute_ids:
        # preserve the caller's requested order for columns that exist
        columns = [a for a in attribute_ids if a in columns]
    else:
        columns.sort()
    log.info("cBioPortal: %d sample(s), %d attribute(s).", len(by_sample), len(columns))
    return by_sample, columns
