"""Staging downloaded files for Galaxy and writing the run summary.

Downloaded files are placed into an output directory and described explicitly in
Galaxy tool-provided metadata, including stable element IDs, datatype extensions,
and dbkeys. Separate TSVs account for retrieval assets and produced datasets.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .contracts import ASSET_COLUMNS, CONTRACT_VERSION, METADATA_LEADING_COLUMNS
from .model import DownloadResult, ProducedDataset, RunSummary

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_output_dir(path: str | Path) -> Path:
    """Create and return the collection output directory."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str) -> str:
    """Return a filesystem/Galaxy-safe version of *name*.

    Keep dots for meaningful multi-part names while replacing path separators and
    other characters that are unsafe in a Galaxy job working directory.
    """
    cleaned = _SAFE.sub("_", name.strip()).strip("._-")
    return cleaned or "dataset"


def unique_path(directory: Path, name: str) -> Path:
    """Return a non-colliding path in *directory* for *name*."""
    base = safe_filename(name)
    candidate = directory / base
    if not candidate.exists():
        return candidate
    stem, dot, ext = base.partition(".")
    i = 1
    while True:
        alt = f"{stem}_{i}{dot}{ext}" if dot else f"{stem}_{i}"
        candidate = directory / alt
        if not candidate.exists():
            return candidate
        i += 1


SUMMARY_COLUMNS = [
    "database",
    "file_id",
    "filename",
    "status",
    "size_bytes",
    "md5",
    "source",
    "message",
]


def write_summary(path: str | Path, summary: RunSummary) -> None:
    """Write one TSV row per produced file (or per entry if none)."""
    with Path(path).open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(SUMMARY_COLUMNS)
        for res in summary.results:
            e = res.entry
            rows = res.paths or [""]
            for produced in rows:
                fname = Path(produced).name if produced else e.filename
                writer.writerow(
                    [
                        summary.database,
                        e.file_id,
                        fname,
                        res.status,
                        res.bytes if produced else (e.size or ""),
                        res.md5 or e.md5 or "",
                        e.source or summary.database,
                        res.message,
                    ]
                )


TRANSFER_REPORT_COLUMNS = [
    "source",
    "asset_id",
    "asset_kind",
    "payload_profile",
    "status",
    "attempts",
    "expected_source_size",
    "transferred_size",
    "expected_source_checksum_type",
    "expected_source_checksum",
    "observed_source_checksum_type",
    "observed_source_checksum",
    "verification",
    "message",
]

DATASET_MAP_COLUMNS = [
    "source",
    "asset_id",
    "collection_output",
    "element_id",
    "role",
    "actual_filename",
    "galaxy_ext",
    "actual_size",
    "actual_checksum_type",
    "actual_checksum",
    "verification",
    "status",
    "message",
]

_TRANSFER_STATUS = {
    "ok": "retrieved",
    "skipped": "unsupported",
}


def _asset_value(result: DownloadResult, field: str, default=""):
    asset = result.entry.extra.get("selection_asset")
    if asset is not None and hasattr(asset, field):
        value = getattr(asset, field)
        return default if value is None else value
    return result.entry.extra.get(field, default)


def produced_datasets(result: DownloadResult) -> list[ProducedDataset]:
    """Return explicit produced datasets, or losslessly adapt legacy paths.

    Legacy ``DownloadResult`` objects have no per-file checksum/role information,
    so those values remain blank rather than copying an expected asset checksum.
    """
    if result.produced:
        return result.produced
    paths = [Path(path) for path in result.paths]
    adapted: list[ProducedDataset] = []
    ext_hint = str(_asset_value(result, "galaxy_ext_hint", "") or "")
    dbkey = str(_asset_value(result, "dbkey", "") or "?")
    for index, path in enumerate(paths, start=1):
        try:
            size = path.stat().st_size
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            checksum = digest.hexdigest()
        except OSError:
            size = 0
            checksum = ""
        element_id = result.entry.file_id if len(paths) == 1 else f"{result.entry.file_id}_{index}"
        inferred_ext = path.suffix.lstrip(".") or "data"
        adapted.append(
            ProducedDataset(
                path=str(path),
                element_id=element_id,
                galaxy_ext=ext_hint or inferred_ext,
                dbkey=dbkey,
                bytes=size,
                checksum_type="sha256" if checksum else "",
                checksum=checksum,
                verification="calculated" if checksum else "",
            )
        )
    result.produced = adapted
    return adapted


def write_transfer_report(path: str | Path, summary: RunSummary) -> None:
    """Write exactly one accounting row per retrieval asset."""
    with Path(path).open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(TRANSFER_REPORT_COLUMNS)
        for result in summary.results:
            expected_checksum_type = _asset_value(result, "source_checksum_type", "")
            expected_checksum = _asset_value(result, "source_checksum", result.entry.md5 or "")
            if not expected_checksum_type and expected_checksum:
                expected_checksum_type = "md5"
            verified = result.checksum_verified
            writer.writerow(
                [
                    result.entry.source or summary.database,
                    result.entry.file_id,
                    _asset_value(result, "asset_kind", "file"),
                    _asset_value(result, "payload_profile", ""),
                    _TRANSFER_STATUS.get(result.status, result.status),
                    result.attempts,
                    result.entry.size if result.entry.size is not None else "",
                    result.bytes,
                    expected_checksum_type,
                    expected_checksum,
                    result.observed_checksum_type,
                    result.observed_checksum,
                    "" if verified is None else str(verified).lower(),
                    result.message,
                ]
            )


def write_dataset_map(path: str | Path, summary: RunSummary) -> None:
    """Write one row per actual materialized Galaxy dataset."""
    with Path(path).open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(DATASET_MAP_COLUMNS)
        for result in summary.results:
            for dataset in produced_datasets(result):
                writer.writerow(
                    [
                        result.entry.source or summary.database,
                        result.entry.file_id,
                        dataset.collection_output,
                        dataset.element_id,
                        dataset.role,
                        Path(dataset.path).name,
                        dataset.galaxy_ext,
                        dataset.bytes,
                        dataset.checksum_type,
                        dataset.checksum,
                        dataset.verification,
                        dataset.status,
                        dataset.message,
                    ]
                )


def write_galaxy_metadata(
    path: str | Path,
    summary: RunSummary,
    *,
    collection_name: str = "downloaded",
) -> None:
    """Write current Galaxy tool-provided metadata for a dynamic collection.

    The wrapper declares ``from_provided_metadata=\"true\"`` and Galaxy reads
    these entries instead of deriving datatype and identifiers from filenames.
    """
    datasets: list[dict[str, str]] = []
    for result in summary.results:
        for dataset in produced_datasets(result):
            if dataset.status != "produced":
                continue
            item = {
                "identifier_0": dataset.element_id,
                "filename": dataset.path,
                "ext": dataset.galaxy_ext or "data",
            }
            if dataset.dbkey and dataset.dbkey != "?":
                item["dbkey"] = dataset.dbkey
            datasets.append(item)
    Path(path).write_text(
        json.dumps({collection_name: {"datasets": datasets}}, indent=2, sort_keys=True) + "\n"
    )


IMPORTED_METADATA_ELEMENT_COLUMNS = ["collection_output", "element_id", "role"]


def write_imported_metadata(path: str | Path, summary: RunSummary) -> None:
    """Expand successful biological associations to concrete collection elements."""
    associations = [
        row
        for result in summary.results
        for row in result.entry.extra.get("selection_metadata", ())
    ]
    known = set(METADATA_LEADING_COLUMNS)
    extra_columns = sorted(
        {
            key
            for association in associations
            for key in association.values
            if key not in known
        }
    )
    columns = [
        *METADATA_LEADING_COLUMNS,
        *extra_columns,
        *IMPORTED_METADATA_ELEMENT_COLUMNS,
    ]
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for result in summary.results:
            metadata_rows = result.entry.extra.get("selection_metadata", ())
            for dataset in produced_datasets(result):
                if dataset.status != "produced":
                    continue
                for association in metadata_rows:
                    values = {column: association.values.get(column, "") for column in columns}
                    values.update(
                        {
                            "collection_output": dataset.collection_output,
                            "element_id": dataset.element_id,
                            "role": dataset.role,
                        }
                    )
                    writer.writerow(values)


def _retry_records(summary: RunSummary):
    assets = []
    metadata = []
    seen: set[tuple[str, str]] = set()
    seen_metadata: set[str] = set()
    for result in summary.results:
        asset = result.entry.extra.get("selection_asset")
        if result.status != "failed" or asset is None:
            continue
        key = (asset.source, asset.asset_id)
        if key not in seen:
            assets.append(asset)
            seen.add(key)
        for row in result.entry.extra.get("selection_metadata", ()):
            if row.metadata_row_id not in seen_metadata:
                metadata.append(row)
                seen_metadata.add(row.metadata_row_id)
    assets.sort(key=lambda asset: (asset.source, asset.asset_id))
    metadata.sort(
        key=lambda row: (
            row.source,
            row.asset_id,
            row.values.get("relationship", ""),
            row.values.get("case_id", ""),
            row.values.get("sample_id", ""),
        )
    )
    return assets, metadata


def write_retry_manifest(path: str | Path, summary: RunSummary) -> None:
    """Write the exact canonical header and retryable failed retrieval assets."""
    assets, _ = _retry_records(summary)
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(ASSET_COLUMNS),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for asset in assets:
            writer.writerow(asset.as_row())


def write_retry_bundle(
    manifest_path: str | Path,
    metadata_path: str | Path,
    provenance_path: str | Path,
    summary: RunSummary,
) -> None:
    """Write a self-contained, hash-bound retry selection bundle."""
    from . import BUILD, version_string

    assets, metadata = _retry_records(summary)
    write_retry_manifest(manifest_path, summary)

    known = set(METADATA_LEADING_COLUMNS)
    extra_columns = sorted(
        {key for row in metadata for key in row.values if key not in known}
    )
    metadata_columns = [*METADATA_LEADING_COLUMNS, *extra_columns]
    with Path(metadata_path).open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=metadata_columns,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in metadata:
            writer.writerow({column: row.values.get(column, "") for column in metadata_columns})

    manifest_digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    metadata_digest = hashlib.sha256(Path(metadata_path).read_bytes()).hexdigest()
    original = next(
        (
            result.entry.extra.get("selection_provenance", {})
            for result in summary.results
            if result.entry.extra.get("selection_provenance")
        ),
        {},
    )
    query = original.get("query") if isinstance(original.get("query"), dict) else {}
    query = json.loads(json.dumps(query, sort_keys=True))
    query["gacdi_retry_of"] = {
        "asset_manifest_sha256": sorted(
            {
                result.entry.extra.get("selection_manifest_sha256")
                for result in summary.results
                if result.entry.extra.get("selection_manifest_sha256")
            }
        ),
        "metadata_sha256": sorted(
            {
                result.entry.extra.get("selection_metadata_sha256")
                for result in summary.results
                if result.entry.extra.get("selection_metadata_sha256")
            }
        ),
    }
    values = {
        "contract_version": CONTRACT_VERSION,
        "mode": "build" if assets else "preview",
        "source": assets[0].source if assets else summary.database,
        "query": query,
        "endpoint": str(original.get("endpoint", "")),
        "tool": "gacdi-retry",
        "tool_version": version_string(),
        "build": BUILD,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asset_manifest_sha256": manifest_digest,
        "metadata_sha256": metadata_digest,
        "counts": {
            "assets": len(assets),
            "metadata_rows": len(metadata),
            "cases": len(
                {
                    (row.source, row.values.get("case_id", ""))
                    for row in metadata
                    if row.values.get("case_id")
                }
            ),
            "samples": len(
                {
                    (row.source, row.values.get("sample_id", ""))
                    for row in metadata
                    if row.values.get("sample_id")
                }
            ),
            "known_source_bytes": sum(asset.source_size or 0 for asset in assets),
        },
        "warnings": [
            "Retry bundle contains only canonical assets that failed the previous import."
        ],
    }
    Path(provenance_path).write_text(json.dumps(values, indent=2, sort_keys=True) + "\n")


def write_import_provenance(
    path: str | Path,
    summary: RunSummary,
    *,
    started_utc: str,
    finished_utc: str,
    retries: int,
    max_files: int | None,
    max_bytes: int | None,
    failure_policy: str,
) -> None:
    """Write downloader/container provenance without serializing credentials."""
    from . import BUILD, version_string

    manifest_hashes = sorted(
        {
            str(result.entry.extra.get("selection_manifest_sha256"))
            for result in summary.results
            if result.entry.extra.get("selection_manifest_sha256")
        }
    )
    metadata_hashes = sorted(
        {
            str(result.entry.extra.get("selection_metadata_sha256"))
            for result in summary.results
            if result.entry.extra.get("selection_metadata_sha256")
        }
    )
    endpoints = sorted(
        {
            str(result.entry.extra.get("selection_provenance", {}).get("endpoint"))
            for result in summary.results
            if result.entry.extra.get("selection_provenance", {}).get("endpoint")
        }
    )
    values = {
        "database": summary.database,
        "downloader": "gacdi",
        "downloader_version": version_string(),
        "build": BUILD,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "failure_policy": failure_policy,
        "retries_after_first_attempt": retries,
        "max_files": max_files,
        "max_bytes": max_bytes,
        "selection_manifest_sha256": manifest_hashes,
        "selection_metadata_sha256": metadata_hashes,
        "endpoints": endpoints,
        "result_counts": dict(sorted(Counter(result.status for result in summary.results).items())),
        "produced_datasets": sum(
            len(produced_datasets(result)) for result in summary.results
        ),
    }
    Path(path).write_text(json.dumps(values, indent=2, sort_keys=True) + "\n")
