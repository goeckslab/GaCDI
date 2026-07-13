"""IDC cohort/manifest transport client.

Owns the REST conversation with the NCI Imaging Data Commons cohort manifest
preview endpoint: request construction, the ``next_page`` token pagination, and
translation of transport/HTTP errors into
:class:`~gacdi_manifest.errors.ApiError`. It returns raw manifest payloads and
instance rows; the source (:mod:`gacdi_manifest.sources.idc`) owns filter
construction, series dedup/mapping, and harmonization.
"""

from __future__ import annotations

import logging
from typing import Iterator

import requests

from ..errors import ApiError

log = logging.getLogger("gacdi_manifest.clients.idc")

IDC_API = "https://api.imaging.datacommons.cancer.gov/v2"
# Series-identifying manifest fields requested (instance-grained; the source
# dedups to series).
FIELDS = ["collection_id", "PatientID", "StudyInstanceUID", "SeriesInstanceUID", "crdc_series_uuid"]
DEFAULT_PAGE_SIZE = 5000


class IDCCohortClient:
    """REST client for the IDC cohort manifest preview endpoint."""

    def __init__(self, *, endpoint: str = IDC_API, timeout: int = 120) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def preview(
        self,
        session: requests.Session,
        filters: dict,
        *,
        page_size: int,
        next_page: str | None = None,
    ) -> tuple[dict, str | None]:
        """Return one ``(manifest, next_page)`` page for *filters*."""
        body = {
            "cohort_def": {"name": "gacdi", "description": "gacdi", "filters": filters},
            "fields": FIELDS,
        }
        params: dict = {"page_size": page_size}
        if next_page:
            params["next_page"] = next_page
        try:
            resp = session.post(
                self.endpoint + "/cohorts/manifest/preview",
                params=params,
                json=body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network only
            raise ApiError(f"IDC request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ApiError(f"IDC API returned HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data.get("manifest") or {}, data.get("next_page")

    def total_found(self, session: requests.Session, filters: dict) -> int:
        """Return the cheap instance-level ``totalFound`` count for *filters*."""
        manifest, _ = self.preview(session, filters, page_size=1)
        return int(manifest.get("totalFound") or 0)

    def iter_instances(
        self,
        session: requests.Session,
        filters: dict,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Iterator[dict]:
        """Yield raw instance-level manifest rows across all pages."""
        token = None
        while True:
            manifest, token = self.preview(session, filters, page_size=page_size, next_page=token)
            batch = manifest.get("manifest_data") or []
            yield from batch
            if not token or not batch:
                break


__all__ = ["IDC_API", "FIELDS", "DEFAULT_PAGE_SIZE", "IDCCohortClient"]
