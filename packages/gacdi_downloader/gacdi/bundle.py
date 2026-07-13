"""Read and integrity-check canonical GaCDI selection bundles."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from .contracts import (
    ASSET_COLUMNS,
    METADATA_LEADING_COLUMNS,
    SelectionAsset,
    SelectionBundle,
    SelectionMetadataRow,
    SelectionProvenance,
)
from .errors import InputError
from .validation import validate_assets, validate_metadata, validate_provenance


_ASCII_INTEGER = re.compile(r"^[0-9]+$")


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of the exact bytes in *path*."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"Bundle file not found: {path}")
    digest = hashlib.sha256()
    try:
        with p.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise InputError(f"Could not read bundle file {path}: {exc}") from exc
    return digest.hexdigest()


def _header(reader: csv.DictReader, *, label: str) -> tuple[str, ...]:
    header = tuple(reader.fieldnames or ())
    if not header:
        raise InputError(f"{label} is empty or has no header.")
    if len(set(header)) != len(header):
        raise InputError(f"{label} contains duplicate column names.")
    return header


def parse_asset_manifest(path: str | Path) -> list[SelectionAsset]:
    """Parse and validate a contract-1.0 retrieval-asset TSV."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"Selection asset manifest not found: {path}")
    try:
        with p.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            header = _header(reader, label="Selection asset manifest")
            if header != ASSET_COLUMNS:
                raise InputError(
                    "Selection asset manifest header does not match contract 1.0. "
                    f"Expected: {', '.join(ASSET_COLUMNS)}; found: {', '.join(header)}"
                )
            assets: list[SelectionAsset] = []
            for row_number, raw in enumerate(reader, start=2):
                if None in raw:
                    raise InputError(
                        f"Asset row {row_number}: found more values than the contract header defines."
                    )
                row = {key: (value or "").strip() for key, value in raw.items()}
                size_value = row["source_size"]
                if size_value and not _ASCII_INTEGER.fullmatch(size_value):
                    raise InputError(
                        f"Asset row {row_number}: source_size must be a non-negative integer."
                    )
                assets.append(
                    SelectionAsset(
                        source=row["source"],
                        asset_id=row["asset_id"],
                        asset_kind=row["asset_kind"],
                        download_method=row["download_method"],
                        drs_uri=row["drs_uri"],
                        access_url=row["access_url"],
                        access=row["access"],
                        asset_name=row["asset_name"],
                        source_size=int(size_value) if size_value else None,
                        source_checksum_type=row["source_checksum_type"],
                        source_checksum=row["source_checksum"],
                        file_format=row["file_format"],
                        payload_profile=row["payload_profile"],
                        galaxy_ext_hint=row["galaxy_ext_hint"],
                        dbkey=row["dbkey"],
                    )
                )
    except UnicodeError as exc:
        raise InputError(f"Selection asset manifest is not valid UTF-8: {exc}") from exc
    validate_assets(assets)
    return assets


def parse_selection_metadata(
    path: str | Path, assets: list[SelectionAsset]
) -> tuple[list[SelectionMetadataRow], tuple[str, ...]]:
    """Parse metadata, allowing native columns after the fixed leading keys."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"Selection metadata not found: {path}")
    try:
        with p.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            header = _header(reader, label="Selection metadata")
            leading = header[: len(METADATA_LEADING_COLUMNS)]
            if leading != METADATA_LEADING_COLUMNS:
                raise InputError(
                    "Selection metadata leading columns do not match contract 1.0. "
                    f"Expected: {', '.join(METADATA_LEADING_COLUMNS)}; "
                    f"found: {', '.join(leading)}"
                )
            rows: list[SelectionMetadataRow] = []
            for row_number, raw in enumerate(reader, start=2):
                if None in raw:
                    raise InputError(
                        f"Metadata row {row_number}: found more values than the header defines."
                    )
                rows.append(
                    SelectionMetadataRow(
                        {key: (value or "").strip() for key, value in raw.items()}
                    )
                )
    except UnicodeError as exc:
        raise InputError(f"Selection metadata is not valid UTF-8: {exc}") from exc
    validate_metadata(rows, assets)
    return rows, header


def parse_selection_provenance(
    path: str | Path,
    *,
    asset_manifest_sha256: str,
    metadata_sha256: str,
) -> SelectionProvenance:
    """Parse provenance JSON and verify both selection-file digests."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"Selection provenance not found: {path}")
    try:
        def reject_duplicate_pairs(pairs):
            values = {}
            for key, value in pairs:
                if key in values:
                    raise ValueError(f"duplicate key '{key}'")
                values[key] = value
            return values

        def reject_constant(value):
            raise ValueError(f"non-finite value '{value}'")

        values = json.loads(
            p.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"Selection provenance is not valid JSON: {exc}") from exc
    if not isinstance(values, dict):
        raise InputError("Selection provenance must contain a JSON object.")
    validate_provenance(
        values,
        asset_manifest_sha256=asset_manifest_sha256,
        metadata_sha256=metadata_sha256,
    )
    return SelectionProvenance(values)


def load_selection_bundle(
    asset_manifest: str | Path,
    metadata: str | Path,
    provenance: str | Path,
) -> SelectionBundle:
    """Load all three bundle files and enforce their cross-file invariants."""
    asset_digest = sha256_file(asset_manifest)
    metadata_digest = sha256_file(metadata)
    assets = parse_asset_manifest(asset_manifest)
    metadata_rows, metadata_columns = parse_selection_metadata(metadata, assets)
    provenance_record = parse_selection_provenance(
        provenance,
        asset_manifest_sha256=asset_digest,
        metadata_sha256=metadata_digest,
    )
    if provenance_record.values["source"] != assets[0].source:
        raise InputError(
            "Selection provenance source does not match the canonical asset manifest source."
        )
    counts = provenance_record.values["counts"]
    actual_counts = {
        "assets": len(assets),
        "metadata_rows": len(metadata_rows),
        "cases": len(
            {
                (row.source, row.values.get("case_id", ""))
                for row in metadata_rows
                if row.values.get("case_id")
            }
        ),
        "samples": len(
            {
                (row.source, row.values.get("sample_id", ""))
                for row in metadata_rows
                if row.values.get("sample_id")
            }
        ),
        "known_source_bytes": sum(asset.source_size or 0 for asset in assets),
    }
    mismatches = [
        f"{key}: provenance={counts[key]}, actual={actual}"
        for key, actual in actual_counts.items()
        if counts[key] != actual
    ]
    if mismatches:
        raise InputError(
            "Selection provenance counts do not match bundle contents ("
            + "; ".join(mismatches)
            + ")."
        )
    return SelectionBundle(
        assets=tuple(assets),
        metadata=tuple(metadata_rows),
        provenance=provenance_record,
        asset_manifest_sha256=asset_digest,
        metadata_sha256=metadata_digest,
        metadata_columns=metadata_columns,
    )


__all__ = [
    "sha256_file",
    "parse_asset_manifest",
    "parse_selection_metadata",
    "parse_selection_provenance",
    "load_selection_bundle",
]
