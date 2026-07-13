"""cBioPortal clinical API transport client.

Owns the HTTP conversation with cBioPortal: the base URL, the
``clinical-attributes`` and ``clinical-data`` requests, and translation of HTTP
errors into :class:`~gacdi_manifest.errors.ApiError`. It returns raw records; the
enrichment/join orchestration (merging patient-level values onto samples, column
selection) lives outside the client in :mod:`gacdi_manifest.cbioportal`.
"""

from __future__ import annotations

import logging

import requests

from ..errors import ApiError

log = logging.getLogger("gacdi_manifest.clients.cbioportal")

DEFAULT_BASE = "https://www.cbioportal.org/api"


class CBioPortalClient:
    """HTTP client for the cBioPortal clinical endpoints."""

    def __init__(self, *, base: str = DEFAULT_BASE) -> None:
        self.base = base.rstrip("/")

    def list_attributes(self, session: requests.Session, study_id: str) -> list[dict]:
        """Return the clinical attributes defined for *study_id*."""
        url = f"{self.base}/studies/{study_id}/clinical-attributes"
        resp = session.get(url, timeout=60)
        if resp.status_code >= 400:
            raise ApiError(f"cBioPortal HTTP {resp.status_code} for {url}: {resp.text[:200]}")
        return resp.json()

    def clinical_data(self, session: requests.Session, study_id: str, kind: str) -> list[dict]:
        """Return raw ``clinical-data`` records for *study_id* at level *kind* (SAMPLE/PATIENT)."""
        url = f"{self.base}/studies/{study_id}/clinical-data"
        resp = session.get(
            url, params={"clinicalDataType": kind, "projection": "SUMMARY"}, timeout=120
        )
        if resp.status_code >= 400:
            raise ApiError(f"cBioPortal HTTP {resp.status_code} for {url}: {resp.text[:200]}")
        return resp.json()


__all__ = ["DEFAULT_BASE", "CBioPortalClient"]
