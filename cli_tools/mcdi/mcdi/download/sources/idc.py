from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from idc_index import IDCClient

from ...errors import ApiError, InputError
from ...net import build_session
from .base import CANDIDATE_DELIMITERS, FileEntry, Source, read_header, write_csv_subset

# Columns in an IDC cohort manifest (CSV/TSV): series-level (one row per
# series) or BigQuery-export (one row per SOPInstanceUID, same columns).
REQUIRED_HEADERS = {"SeriesInstanceUID", "collection_id", "PatientID", "gcs_url"}

# Matches ``cp <scheme>://<bucket>/<crdc_series_uuid>/*``. Scheme-agnostic: the
# bucket always comes from the index (see IdcIndexLookup), never the manifest
# text. Non-matching lines (comments, blanks, stray headers) are skipped, not errors.
_S5CMD_CP_RE = re.compile(r"^cp\s+\S+://[^\s/]+/([^\s/]+)/\*(?:\s|$)")

# Only bucket confirmed anonymously listable/gettable; GCS is out of scope for now.
_SUPPORTED_BUCKET = "idc-open-data"

# Fixed concurrency for the per-series S3 listing fan-out (not plumbed through --workers).
_LISTING_WORKERS = 8

_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


@dataclass
class SeriesInfo:
    """One series' location, resolved via idc-index's metadata index."""

    series_uid: str
    crdc_series_uuid: str
    aws_bucket: str
    collection_id: str
    patient_id: str
    study_uid: str
    modality: str


class IdcIndexLookup:
    """Wraps ``idc_index.IDCClient``'s bundled metadata index.

    Constructor-injection seam for unit testing without a real ``IDCClient``
    (needs ``s5cmd`` on ``PATH``, loads a ~77MB index).
    """

    def __init__(self) -> None:
        self._client: Optional[IDCClient] = None

    def _get_client(self) -> IDCClient:
        if self._client is None:
            self._client = IDCClient()
        return self._client

    def resolve(self, column: str, values: list[str]) -> tuple[dict[str, SeriesInfo], list[str]]:
        """Batch-resolve values against the current index, then prior releases for misses.

        Returns ``(resolved_by_value, still_unresolved)``. Vectorized, not per-value
        (the index can hold upwards of a million rows).
        """
        client = self._get_client()
        resolved: dict[str, SeriesInfo] = {}
        remaining = list(values)
        for df in (client.index, client.prior_versions_index):
            if not remaining:
                break
            matches = df[df[column].isin(remaining)].drop_duplicates(subset=[column])
            for _, row in matches.iterrows():
                resolved[row[column]] = SeriesInfo(
                    series_uid=row["SeriesInstanceUID"],
                    crdc_series_uuid=row["crdc_series_uuid"],
                    aws_bucket=row["aws_bucket"],
                    collection_id=row["collection_id"],
                    patient_id=row["PatientID"],
                    study_uid=row["StudyInstanceUID"],
                    modality=row["Modality"],
                )
            remaining = [v for v in remaining if v not in resolved]
        return resolved, remaining


def _list_series_objects(session: requests.Session, bucket: str, crdc_series_uuid: str) -> list[tuple[str, int]]:
    """Anonymous, paginated ListObjectsV2 over one series' object prefix
    (public-read bucket, no signing needed)."""
    prefix = f"{crdc_series_uuid}/"
    keys: list[tuple[str, int]] = []
    token: Optional[str] = None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if token:
            params["continuation-token"] = token
        resp = session.get(f"https://{bucket}.s3.amazonaws.com", params=params, timeout=60)
        if resp.status_code != 200:
            raise ApiError(f"Could not list IDC series {crdc_series_uuid!r} objects: HTTP {resp.status_code}")
        root = ET.fromstring(resp.content)
        for c in root.findall("s3:Contents", _S3_NS):
            key = c.findtext("s3:Key", namespaces=_S3_NS)
            size = int(c.findtext("s3:Size", default="0", namespaces=_S3_NS))
            keys.append((key, size))
        token = root.findtext("s3:NextContinuationToken", namespaces=_S3_NS)
        is_truncated = root.findtext("s3:IsTruncated", namespaces=_S3_NS)
        if is_truncated != "true" or not token:
            break
    if not keys:
        raise ApiError(
            f"IDC series {crdc_series_uuid!r} resolved via idc-index but has no objects "
            f"at s3://{bucket}/{prefix}"
        )
    return keys


def _csv_delimiter(path: Path) -> Optional[str]:
    """Delimiter the manifest's header matches ``REQUIRED_HEADERS`` under, or None."""
    for d in CANDIDATE_DELIMITERS:
        if REQUIRED_HEADERS.issubset(set(read_header(path, d))):
            return d
    return None


def _extract_csv_series_uids(path: Path, delimiter: str) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter=delimiter):
            series_uid = (row.get("SeriesInstanceUID") or "").strip()
            if series_uid and series_uid not in seen_set:
                seen_set.add(series_uid)
                seen.append(series_uid)
    return seen


def _extract_s5cmd_series_uuids(path: Path) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    with open(path) as f:
        for raw in f:
            m = _S5CMD_CP_RE.match(raw.strip())
            if not m:
                continue  # comment, blank, or an unrecognized/header line - skip, don't error
            crdc_series_uuid = m.group(1)
            if crdc_series_uuid not in seen_set:
                seen_set.add(crdc_series_uuid)
                seen.append(crdc_series_uuid)
    return seen


def _extract_series_refs(path: Path) -> tuple[str, list[str]]:
    """(index_column, ordered_deduplicated_ids) a manifest references."""
    delimiter = _csv_delimiter(path)
    if delimiter is not None:
        return "SeriesInstanceUID", _extract_csv_series_uids(path, delimiter)
    return "crdc_series_uuid", _extract_s5cmd_series_uuids(path)


class IDCSource(Source):
    name = "idc"

    def __init__(self, lookup: Optional[IdcIndexLookup] = None):
        self._lookup = lookup or IdcIndexLookup()
        # file_id (S3 key) -> (series_uid, crdc_series_uuid), populated by parse_manifest;
        # lets write_subset_manifest map a failed download back to its manifest row.
        self._series_by_file_id: dict[str, tuple[str, str]] = {}

    @staticmethod
    def sniff(header_fields: list[str]) -> bool:
        return REQUIRED_HEADERS.issubset(set(header_fields))

    @staticmethod
    def sniff_lines(lines: list[str]) -> bool:
        return any(_S5CMD_CP_RE.match(line.strip()) for line in lines)

    def parse_manifest(self, path: Path) -> list[FileEntry]:
        self._series_by_file_id = {}
        column, ids = _extract_series_refs(path)
        if not ids:
            raise InputError(f"IDC manifest {path} contained no resolvable series references.")

        resolved, unresolved = self._lookup.resolve(column, ids)
        if unresolved:
            raise InputError(
                f"{len(unresolved)} IDC series not found in idc-index metadata (current or prior "
                f"releases); manifest may be stale: {unresolved}"
            )

        session = build_session()
        entries: list[FileEntry] = []
        with ThreadPoolExecutor(max_workers=min(_LISTING_WORKERS, len(resolved))) as pool:
            futures = [pool.submit(self._entries_for_series, session, info) for info in resolved.values()]
            for future in as_completed(futures):
                entries.extend(future.result())
        return entries

    def _entries_for_series(self, session: requests.Session, info: SeriesInfo) -> list[FileEntry]:
        if info.aws_bucket != _SUPPORTED_BUCKET:
            raise ApiError(
                f"IDC series {info.series_uid!r} resolves to unsupported bucket {info.aws_bucket!r} "
                f"(only {_SUPPORTED_BUCKET!r} is currently supported)."
            )
        rel_dir = (
            Path("idc") / info.collection_id / info.patient_id / info.study_uid
            / f"{info.modality}_{info.series_uid}"
        )
        entries = [
            FileEntry(
                file_id=key,
                filename=key.rsplit("/", 1)[-1],
                rel_dir=rel_dir,
                url=f"https://{info.aws_bucket}.s3.amazonaws.com/{key}",
                size=size,
                md5=None,  # no reliable per-object checksum (S3 ETag unsound for multipart uploads)
            )
            for key, size in _list_series_objects(session, info.aws_bucket, info.crdc_series_uuid)
        ]
        for entry in entries:
            self._series_by_file_id[entry.file_id] = (info.series_uid, info.crdc_series_uuid)
        return entries

    def request_kwargs(self, entry: FileEntry) -> dict:
        return {}

    def known_open(self, entries: list[FileEntry], session: requests.Session) -> set[str]:
        """Already confirmed to exist via the listing in ``parse_manifest`` - skip the
        redundant per-file probe in ``engine.check_access``."""
        return {e.file_id for e in entries}

    def write_subset_manifest(
        self, original_manifest: Path, failed_file_ids: set[str], output_path: Path
    ) -> None:
        """Map each failed file back to the series (manifest row) it came from - one
        manifest row can expand into many files, so a failure pulls in the whole series.
        Re-running the result is safe: files already on disk are skipped (see
        ``engine._already_present``)."""
        delimiter = _csv_delimiter(original_manifest)
        if delimiter is not None:
            series_uids = {
                self._series_by_file_id[fid][0]
                for fid in failed_file_ids
                if fid in self._series_by_file_id
            }
            write_csv_subset(
                original_manifest, output_path, delimiter=delimiter, key_column="SeriesInstanceUID",
                keep_keys=series_uids,
            )
            return

        crdc_uuids = {
            self._series_by_file_id[fid][1]
            for fid in failed_file_ids
            if fid in self._series_by_file_id
        }
        with open(original_manifest) as fin, open(output_path, "w") as fout:
            for raw in fin:
                m = _S5CMD_CP_RE.match(raw.strip())
                if m and m.group(1) in crdc_uuids:
                    fout.write(raw)
