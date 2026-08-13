from __future__ import annotations

import base64
import binascii
import csv
import json
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

from ...errors import ApiError, InputError
from ...net import build_session
from .base import CANDIDATE_DELIMITERS, FileEntry, RateLimit, Source, read_header

REQUIRED_HEADERS = {"PDC Study ID", "Data Category", "File Type", "File Download Link"}

GRAPHQL_URL = "https://pdc.cancer.gov/graphql"
_PAGE_SIZE = 100
_STALE_MARGIN_SECONDS = 900

FILES_PER_STUDY_QUERY = """
query FilesPerStudy($studyId: String!, $offset: Int!, $limit: Int!) {
  filesPerStudy(pdc_study_id: $studyId, offset: $offset, limit: $limit) {
    file_name
    file_size
    md5sum
    signedUrl { url }
  }
}
"""


def _find_md5_key(fieldnames: list[str]) -> str | None:
    for name in fieldnames:
        if "md5" in name.lower():
            return name
    return None


def _cloudfront_policy_expiry(url: str) -> Optional[int]:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    policy = query.get("Policy", [None])[0]
    if not policy:
        return None
    padded = policy.replace("-", "+").replace("_", "=").replace("~", "/")
    padded += "=" * (-len(padded) % 4)
    try:
        data = json.loads(base64.b64decode(padded))
        return int(data["Statement"][0]["Condition"]["DateLessThan"]["AWS:EpochTime"])
    except (KeyError, IndexError, TypeError, ValueError, binascii.Error):
        return None


def _is_stale(url: str) -> bool:
    expiry = _cloudfront_policy_expiry(url)
    return expiry is None or expiry <= time.time() + _STALE_MARGIN_SECONDS


class PdcUrlRefresher:
    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or build_session()

    def _post(self, study_id: str, offset: int) -> list[dict]:
        try:
            resp = self._session.post(
                GRAPHQL_URL,
                json={
                    "query": FILES_PER_STUDY_QUERY,
                    "variables": {"studyId": study_id, "offset": offset, "limit": _PAGE_SIZE},
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            raise ApiError(f"PDC filesPerStudy request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ApiError(f"PDC filesPerStudy HTTP {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        if "errors" in payload:
            raise ApiError(f"PDC filesPerStudy({study_id!r}) errors: {payload['errors']}")
        return payload["data"]["filesPerStudy"]

    def fetch_study(self, study_id: str) -> dict[str, dict]:
        by_name: dict[str, dict] = {}
        offset = 0
        while True:
            page = self._post(study_id, offset)
            for rec in page:
                by_name[rec["file_name"]] = rec
            if len(page) < _PAGE_SIZE:
                return by_name
            offset += _PAGE_SIZE


class PDCSource(Source):
    name = "pdc"

    def __init__(self, refresher: Optional[PdcUrlRefresher] = None):
        self._refresher = refresher or PdcUrlRefresher()

    @staticmethod
    def sniff(header_fields: list[str]) -> bool:
        return REQUIRED_HEADERS.issubset(set(header_fields))

    def parse_manifest(self, path: Path) -> list[FileEntry]:
        delimiter = next(
            (d for d in CANDIDATE_DELIMITERS if self.sniff(read_header(path, d))),
            CANDIDATE_DELIMITERS[-1],
        )
        rows = []
        with open(path, newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            md5_key = _find_md5_key(reader.fieldnames or [])
            for row in reader:
                run_metadata_id = (row.get("Run Metadata ID") or "").strip()
                rows.append(
                    {
                        "filename": row["File Name"].strip(),
                        "study_id": row["PDC Study ID"].strip(),
                        "study_version": row["PDC Study Version"].strip(),
                        "data_category": row["Data Category"].strip(),
                        "file_type": row["File Type"].strip(),
                        "run_metadata_id": run_metadata_id,
                        "url": row["File Download Link"].strip(),
                        "md5": row[md5_key].strip() if md5_key and row.get(md5_key) else None,
                    }
                )

        self._refresh_stale(rows)

        entries = []
        for row in rows:
            parts = [row["study_id"], row["study_version"], row["data_category"]]
            if row["run_metadata_id"] and row["run_metadata_id"].lower() != "null":
                parts.append(row["run_metadata_id"])
            parts.append(row["file_type"])
            entries.append(
                FileEntry(
                    file_id=row["filename"],
                    filename=row["filename"],
                    rel_dir=Path("pdc").joinpath(*parts),
                    url=row["url"],
                    md5=row["md5"],
                )
            )
        return entries

    def _refresh_stale(self, rows: list[dict]) -> None:
        by_study: dict[str, list[dict]] = {}
        for row in rows:
            if _is_stale(row["url"]):
                by_study.setdefault(row["study_id"], []).append(row)
        if not by_study:
            return

        errors: list[str] = []
        for study_id, stale_rows in by_study.items():
            fresh = self._refresher.fetch_study(study_id)
            for row in stale_rows:
                rec = fresh.get(row["filename"])
                if rec is None:
                    errors.append(f"{row['filename']!r} (study {study_id}): not found in current PDC data")
                    continue
                fresh_md5 = rec.get("md5sum")
                if row["md5"] and fresh_md5 and row["md5"].lower() != fresh_md5.lower():
                    errors.append(
                        f"{row['filename']!r} (study {study_id}): md5 mismatch "
                        f"(manifest {row['md5']!r} vs PDC {fresh_md5!r})"
                    )
                    continue
                row["url"] = rec["signedUrl"]["url"]
                row["md5"] = row["md5"] or fresh_md5

        if errors:
            raise InputError("PDC signed-URL refresh failed:\n" + "\n".join(errors))

    def request_kwargs(self, entry: FileEntry) -> dict:
        return {}

    def rate_limit(self) -> RateLimit:
        # Avoids tripping PDC's 24h per-IP restriction on repeated file downloads.
        return RateLimit(max_per_window=10, window_seconds=600, per_file_sleep_seconds=2)
