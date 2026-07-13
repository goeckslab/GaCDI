"""GDC ``/files`` transport client.

Owns the HTTP conversation with the GDC files API: endpoint, request
construction, pagination, facets, per-request timeout, and translation of
transport/HTTP failures into :class:`~gacdi_manifest.errors.ApiError`. It returns
raw TSV dict rows and JSON payloads; mapping to :class:`FileRow` lives in the
source (:mod:`gacdi_manifest.sources.gdc`).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os

import requests

from ..errors import ApiError

log = logging.getLogger("gacdi_manifest.clients.gdc")

FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"

# Requested fields: manifest columns + join keys + workflow-relevant metadata.
FIELDS = [
    "file_id",
    "file_name",
    "md5sum",
    "file_size",
    "state",
    "data_format",
    "data_type",
    "data_category",
    "experimental_strategy",
    "platform",
    "access",
    "analysis.workflow_type",
    "cases.case_id",
    "cases.submitter_id",
    "cases.samples.sample_id",
    "cases.samples.submitter_id",
    "cases.samples.sample_type",
    "cases.project.project_id",
    "cases.primary_site",
    "cases.disease_type",
    # GDC-native clinical (demographic + diagnosis) → harmonized metadata core.
    # GDC renamed the demographic sex field: the old `gender` was dropped from the
    # schema and replaced by `sex_at_birth`. Requesting `gender` yields an all-empty
    # column that GDC prunes from the TSV, so the harmonized `gender` output stays
    # blank — read `sex_at_birth` instead.
    "cases.demographic.sex_at_birth",
    "cases.demographic.race",
    "cases.demographic.ethnicity",
    "cases.demographic.vital_status",
    "cases.diagnoses.age_at_diagnosis",
    "cases.diagnoses.primary_diagnosis",
    "cases.diagnoses.ajcc_pathologic_stage",
    "cases.diagnoses.tumor_grade",
]

# A full page expands every nested field (cases.samples.*, cases.diagnoses.*,
# cases.demographic.*) for each file, and GDC generates that TSV server-side row by
# row — so page cost scales with page size, not just file count. 500 rows of this
# many nested paths regularly exceeds the read timeout; 100 keeps each page well
# inside it while still paging efficiently. Override with GACDI_GDC_PAGE_SIZE.
DEFAULT_PAGE_SIZE = int(os.environ.get("GACDI_GDC_PAGE_SIZE") or 100)

# Per-request read timeout (seconds). The fetch pages are far heavier than the
# count/facet calls, so give them headroom; override with GACDI_GDC_TIMEOUT.
DEFAULT_TIMEOUT = int(os.environ.get("GACDI_GDC_TIMEOUT") or 120)

# Stable server-side order so paging and --max-files are reproducible across runs
# (GDC's default order is unspecified). file_id is a unique, stable UUID.
SORT = "file_id:asc"


class GDCFilesClient:
    """HTTP client for the GDC ``/files`` endpoint."""

    def __init__(
        self,
        *,
        endpoint: str = FILES_ENDPOINT,
        fields: list[str] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        timeout: int = DEFAULT_TIMEOUT,
        sort: str = SORT,
    ) -> None:
        self.endpoint = endpoint
        self.fields = list(fields if fields is not None else FIELDS)
        self.page_size = page_size
        self.timeout = timeout
        self.sort = sort

    def _post(self, session: requests.Session, payload: dict, *, text: bool = False):
        try:
            resp = session.post(self.endpoint, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:  # pragma: no cover - network only
            raise ApiError(f"GDC request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ApiError(f"GDC API returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.text if text else resp.json()

    def count(self, session: requests.Session, filters: dict) -> int:
        """Return the total number of files matching *filters*."""
        data = self._post(session, {"filters": filters, "size": 0})
        try:
            return int(data["data"]["pagination"]["total"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("Unexpected GDC count response.") from exc

    def facets(self, session: requests.Session, filters: dict, fields: list[str]) -> dict:
        """Return facet counts for *fields* under the current *filters* (preview)."""
        data = self._post(session, {"filters": filters, "facets": ",".join(fields), "size": 0})
        buckets = data.get("data", {}).get("aggregations", {})
        out: dict[str, dict] = {}
        for field_name, agg in buckets.items():
            out[field_name] = {
                b["key"]: b["doc_count"] for b in agg.get("buckets", []) if "key" in b
            }
        return out

    def fetch_rows(
        self,
        session: requests.Session,
        filters: dict,
        *,
        max_files: int | None = None,
        total: int | None = None,
    ) -> list[dict]:
        """Fetch matching files as raw TSV dict rows (paged), up to *max_files*.

        Pass *total* (from a prior :meth:`count`) to avoid re-counting.
        """
        if total is None:
            total = self.count(session, filters)
        log.info("GDC matched %d file(s).", total)
        limit = min(total, max_files) if max_files else total
        rows: list[dict] = []
        start = 0
        while start < limit:
            size = min(self.page_size, limit - start)
            payload = {
                "filters": filters,
                "fields": ",".join(self.fields),
                "format": "TSV",
                "size": size,
                "from": start,
                "sort": self.sort,
            }
            text = self._post(session, payload, text=True)
            reader = csv.DictReader(io.StringIO(text), delimiter="\t")
            page = list(reader)
            if not page:
                break
            rows.extend(page)
            start += len(page)
        return rows


def dumps_filters(filters: dict) -> str:
    return json.dumps(filters, indent=2, sort_keys=True)


__all__ = [
    "FILES_ENDPOINT",
    "FIELDS",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_TIMEOUT",
    "SORT",
    "GDCFilesClient",
    "dumps_filters",
]
