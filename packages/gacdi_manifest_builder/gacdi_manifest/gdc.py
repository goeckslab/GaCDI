"""Query the GDC ``/files`` endpoint into :class:`FileRow` objects.

One POST returns both the file fields needed for the manifest and the barcode
keys needed for joining, so both output tables come from a single response.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os

import requests

from .errors import ApiError
from .model import FileRow

log = logging.getLogger("gacdi_manifest.gdc")

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


def _post(session: requests.Session, payload: dict, *, text: bool = False,
          timeout: int = DEFAULT_TIMEOUT):
    try:
        resp = session.post(FILES_ENDPOINT, json=payload, timeout=timeout)
    except requests.RequestException as exc:  # pragma: no cover - network only
        raise ApiError(f"GDC request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise ApiError(f"GDC API returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.text if text else resp.json()


def count(session: requests.Session, filters: dict) -> int:
    """Return the total number of files matching *filters*."""
    payload = {"filters": filters, "size": 0}
    data = _post(session, payload)
    try:
        return int(data["data"]["pagination"]["total"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError("Unexpected GDC count response.") from exc


def _row_to_filerow(row: dict) -> FileRow:
    def pick(*keys: str) -> str:
        for k in keys:
            if row.get(k) not in (None, ""):
                return str(row[k]).strip()
        return ""

    return FileRow(
        file_id=pick("file_id", "id"),
        filename=pick("file_name", "filename"),
        md5=pick("md5sum", "md5"),
        size=pick("file_size", "size"),
        state=pick("state") or "released",
        meta=dict(row),
    )


def query_files(
    session: requests.Session,
    filters: dict,
    *,
    max_files: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    total: int | None = None,
) -> list[FileRow]:
    """Fetch matching files (paged), up to *max_files*.

    Pass *total* (from a prior :func:`count`) to avoid re-counting.
    """
    if total is None:
        total = count(session, filters)
    log.info("GDC matched %d file(s).", total)
    limit = min(total, max_files) if max_files else total
    rows: list[FileRow] = []
    start = 0
    while start < limit:
        size = min(page_size, limit - start)
        payload = {
            "filters": filters,
            "fields": ",".join(FIELDS),
            "format": "TSV",
            "size": size,
            "from": start,
            "sort": SORT,
        }
        text = _post(session, payload, text=True)
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        page = [_row_to_filerow(r) for r in reader]
        if not page:
            break
        rows.extend(page)
        start += len(page)
    return rows


def facets(session: requests.Session, filters: dict, fields: list[str]) -> dict:
    """Return facet counts for *fields* under the current *filters* (preview)."""
    payload = {
        "filters": filters,
        "facets": ",".join(fields),
        "size": 0,
    }
    data = _post(session, payload)
    buckets = data.get("data", {}).get("aggregations", {})
    out: dict[str, dict] = {}
    for field_name, agg in buckets.items():
        out[field_name] = {
            b["key"]: b["doc_count"] for b in agg.get("buckets", []) if "key" in b
        }
    return out


def dumps_filters(filters: dict) -> str:
    return json.dumps(filters, indent=2, sort_keys=True)
