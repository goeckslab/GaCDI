"""Query the GDC ``/files`` endpoint into :class:`FileRow` objects.

One POST returns both the file fields needed for the manifest and the barcode
keys needed for joining, so both output tables come from a single response.
"""

from __future__ import annotations

import csv
import io
import json
import logging

import requests

from .errors import ApiError
from .model import FileRow

log = logging.getLogger("gacdi_manifest.gdc")

FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"

# Requested fields: manifest columns + join keys + useful facets.
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
    "access",
    "cases.submitter_id",
    "cases.samples.submitter_id",
    "cases.samples.sample_type",
    "cases.project.project_id",
]

DEFAULT_PAGE_SIZE = 500


def _post(session: requests.Session, payload: dict, *, text: bool = False):
    try:
        resp = session.post(FILES_ENDPOINT, json=payload, timeout=60)
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
) -> list[FileRow]:
    """Fetch matching files (paged), up to *max_files*."""
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
