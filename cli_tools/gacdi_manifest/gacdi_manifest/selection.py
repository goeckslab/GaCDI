"""Canonical selection-bundle generation for every manifest selector.

The legacy source manifests remain compatibility outputs.  This module adds the
versioned, source-neutral boundary consumed by the next-generation downloader:
one row per retrieval asset, one or more biological metadata associations per
asset, and a JSON provenance record attesting to both TSV byte streams.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from gacdi.contracts import (
    ASSET_COLUMNS,
    CONTRACT_VERSION,
    METADATA_LEADING_COLUMNS,
    SelectionAsset,
    SelectionMetadataRow,
    association_row_id,
)
from gacdi.validation import validate_assets, validate_metadata, validate_provenance

from . import BUILD, version_string
from .errors import InputError
from .io import BASE_METADATA_COLUMNS
from .model import FileRow, HARMONIZED_CORE_COLUMNS, field_value

if TYPE_CHECKING:  # pragma: no cover
    from .importer import BuildImporter


DEFAULT_SELECTION_MANIFEST = "selection_manifest.tsv"
DEFAULT_SELECTION_METADATA = "selection_metadata.tsv"
DEFAULT_SELECTION_PROVENANCE = "selection_provenance.json"

_ANNOTATION_STATES = frozenset({"not_requested", "matched", "unmatched"})
_CHECKSUM_PATTERNS = {
    "md5": re.compile(r"^[0-9a-fA-F]{32}$"),
    "sha256": re.compile(r"^[0-9a-fA-F]{64}$"),
}

# Keep harmonized columns ahead of file-routing and source-native passthrough
# columns.  The first nine columns are fixed separately by
# METADATA_LEADING_COLUMNS.
_LEADING_MAPPED_FIELDS = {
    "source", "file_id", "case_id", "sample_id", "project", "sample_type", "matched"
}
_HARMONIZED_TAIL = [
    c for c in HARMONIZED_CORE_COLUMNS
    if c not in _LEADING_MAPPED_FIELDS
]
_LEGACY_TAIL = [
    c for c in BASE_METADATA_COLUMNS
    if c not in _LEADING_MAPPED_FIELDS and c not in _HARMONIZED_TAIL
]
CANONICAL_METADATA_BASE_COLUMNS: tuple[str, ...] = tuple(
    [*METADATA_LEADING_COLUMNS, *_HARMONIZED_TAIL, *_LEGACY_TAIL]
)


def default_output_paths(manifest_out: str) -> tuple[str, str, str]:
    """Return useful canonical defaults beside the legacy manifest output."""
    parent = Path(manifest_out).parent
    return (
        str(parent / DEFAULT_SELECTION_MANIFEST),
        str(parent / DEFAULT_SELECTION_METADATA),
        str(parent / DEFAULT_SELECTION_PROVENANCE),
    )


def _scalar(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return str(value).strip()


def _safe_asset_name(name: str, asset_id: str) -> str:
    value = _scalar(name) or asset_id
    # Source APIs occasionally return a relative path.  The canonical contract
    # carries a safe logical basename; the original locator remains source-native
    # metadata.
    value = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return value if value not in {"", ".", ".."} else asset_id


def _source_size(value) -> int | None:
    text = _scalar(value)
    if not text or not re.fullmatch(r"[0-9]+", text):
        return None
    return int(text)


def _dbkey(fr: FileRow) -> str:
    for key in (
        "dbkey", "genome_build", "reference_genome_assembly", "reference_genome", "assembly"
    ):
        value = _scalar(fr.meta.get(key))
        if value:
            return value
    return ""


def _asset_kind(source: str, download_method: str) -> str:
    if source == "idc":
        return "series"
    if download_method == "sra-toolkit":
        return "run"
    return "file"


def _payload_profile(source: str, file_format: str, galaxy_ext: str) -> str:
    fmt = (file_format or "").strip().lower()
    ext = (galaxy_ext or "").strip().lower()
    if source == "gdc":
        if ext == "bam" or fmt == "bam":
            return "single_bam"
        if ext == "cram" or fmt == "cram":
            return "single_cram"
        if ext in {"vcf", "vcf_bgzip"} or fmt == "vcf":
            return "single_vcf"
        if ext == "svs" or fmt == "svs":
            return "single_svs"
        if ext in {"tabular", "csv", "txt"} or fmt in {"tsv", "csv", "txt", "maf"}:
            return "single_table"
        return "single_data"
    if source == "idc":
        return "dicom_series"
    if source == "pdc":
        return "proteomics"
    if ext in {"fastqsanger", "fastqsanger.gz"} or fmt in {"fastq", "fq"}:
        return "sequencing_reads"
    if ext in {"bam", "cram", "bai"} or fmt in {"bam", "cram", "bai"}:
        return "aligned_reads"
    if ext in {"vcf", "vcf_bgzip"} or fmt == "vcf":
        return "variants"
    if ext in {"svs", "tiff"} or fmt in {"svs", "tif", "tiff"}:
        return "pathology_image"
    if fmt == "dicom":
        return "medical_imaging"
    if ext in {"tabular", "csv", "txt"} or fmt in {"tsv", "csv", "txt", "maf"}:
        return "tabular"
    if ext == "idat" or fmt == "idat":
        return "methylation_array"
    return "raw"


def _checksum(checksum_type: str, checksum: str, warnings: list[str]) -> tuple[str, str]:
    kind = _scalar(checksum_type).lower()
    value = _scalar(checksum)
    if not value:
        return "", ""
    if not kind:
        warnings.append("A source checksum had no checksum type and was omitted from canonical output.")
        return "", ""
    pattern = _CHECKSUM_PATTERNS.get(kind)
    if kind not in {"md5", "sha256", "etag"} or (pattern and not pattern.fullmatch(value)):
        warnings.append(
            f"A source supplied an invalid or unsupported {kind or 'unknown'} checksum; "
            "canonical checksum fields were left blank."
        )
        return "", ""
    return kind, value


def build_assets(
    importer: "BuildImporter", file_rows: list[FileRow]
) -> tuple[list[SelectionAsset], list[str]]:
    """Convert source records into sorted, validated retrieval assets."""
    warnings: list[str] = []
    by_id = {fr.file_id: fr for fr in file_rows}

    if importer.manifest_dialect == "source":
        native_rows = importer.to_manifest_rows(file_rows)
        candidates = []
        for row in native_rows:
            fr = by_id.get(row.file_id)
            if fr is None:  # defensive; source mapper should preserve identity
                continue
            checksum_type, checksum = _checksum(row.checksum_type, row.checksum, warnings)
            file_format = _scalar(row.file_format) or _scalar(fr.data_format)
            candidates.append(
                SelectionAsset(
                    source=_scalar(row.source) or importer.name,
                    asset_id=_scalar(row.file_id),
                    asset_kind=_asset_kind(importer.name, _scalar(row.download_method)),
                    download_method=_scalar(row.download_method),
                    drs_uri=_scalar(row.drs_uri),
                    access_url=_scalar(row.access_url),
                    access=_scalar(row.access),
                    asset_name=_safe_asset_name(row.filename, row.file_id),
                    source_size=_source_size(row.size),
                    source_checksum_type=checksum_type,
                    source_checksum=checksum,
                    file_format=file_format,
                    payload_profile=_payload_profile(importer.name, file_format, fr.galaxy_ext),
                    galaxy_ext_hint=fr.galaxy_ext,
                    dbkey=_dbkey(fr),
                )
            )
    else:
        candidates = []
        for fr in file_rows:
            checksum_type, checksum = _checksum("md5" if fr.md5 else "", fr.md5, warnings)
            file_format = _scalar(fr.data_format)
            candidates.append(
                SelectionAsset(
                    source=importer.name,
                    asset_id=fr.file_id,
                    asset_kind="file",
                    download_method="gdc-client",
                    drs_uri="",
                    access_url="",
                    access=_scalar(field_value(fr.meta, "access")),
                    asset_name=_safe_asset_name(fr.filename, fr.file_id),
                    source_size=_source_size(fr.size),
                    source_checksum_type=checksum_type,
                    source_checksum=checksum,
                    file_format=file_format,
                    payload_profile=_payload_profile(importer.name, file_format, fr.galaxy_ext),
                    galaxy_ext_hint=fr.galaxy_ext,
                    dbkey=_dbkey(fr),
                )
            )

    # One canonical row per retrieval asset. Identical repeats are collapsed;
    # contradictory repeats are rejected rather than silently causing an
    # under-specified or duplicate download.
    unique: dict[tuple[str, str], SelectionAsset] = {}
    for asset in sorted(candidates, key=lambda r: (r.source, r.asset_id)):
        key = (asset.source, asset.asset_id)
        previous = unique.get(key)
        if previous is None:
            unique[key] = asset
        elif previous != asset:
            raise InputError(
                f"Source returned contradictory rows for retrieval asset "
                f"'{asset.source}:{asset.asset_id}'. Refine the source query or adapter "
                "instead of choosing one row silently."
            )
        else:
            warnings.append(f"Duplicate source row for {asset.source}:{asset.asset_id} was collapsed.")

    assets = list(unique.values())
    profiles = {asset.payload_profile for asset in assets}
    if len(profiles) > 1:
        warnings.append(
            "Selection contains mixed payload profiles; every asset is marked raw_mixed."
        )
        assets = [
            SelectionAsset(
                **{**asset.__dict__, "payload_profile": "raw_mixed"}
            )
            for asset in assets
        ]
    assets.sort(key=lambda r: (r.source, r.asset_id))

    if assets:
        validate_assets(assets)
    return assets, list(dict.fromkeys(warnings))


def _relationship(case_id: str, sample_id: str) -> str:
    if sample_id:
        return "sample"
    if case_id:
        return "case"
    return "asset"


def _stable_row(row: dict) -> str:
    return json.dumps(
        {str(k): _scalar(v) for k, v in row.items()},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _native_column(source: str, column: str, occupied: set[str]) -> str:
    """Return a deterministic, collision-safe canonical native column name."""
    prefix = f"{source}__"
    if not column.startswith(prefix):
        return column
    native = column[len(prefix):]
    escaped = re.sub(r"[^A-Za-z0-9_]+", "_", native).strip("_") or "field"
    candidate = prefix + escaped
    if candidate in occupied and candidate != column:
        suffix = hashlib.sha256(column.encode("utf-8")).hexdigest()[:8]
        candidate = f"{candidate}_{suffix}"
    return candidate


def build_metadata(
    source: str,
    merged_rows: list[dict],
    assets: list[SelectionAsset],
    *,
    annotation_requested: bool,
) -> list[SelectionMetadataRow]:
    """Build deterministic metadata associations with collision-safe row IDs."""
    unique_associations: dict[tuple[str, ...], tuple[str, dict]] = {}
    for row in merged_rows:
        asset_id = _scalar(row.get("file_id"))
        case_id = _scalar(row.get("case_id"))
        sample_id = _scalar(row.get("sample_id"))
        relationship = _relationship(case_id, sample_id)
        identity = (source, asset_id, relationship, case_id, sample_id)
        serialized = _stable_row(row)
        previous = unique_associations.get(identity)
        if previous is None:
            unique_associations[identity] = (serialized, row)
        elif previous[0] != serialized:
            raise InputError(
                "Source returned contradictory metadata rows for canonical association "
                f"'{source}:{asset_id}:{relationship}:{case_id}:{sample_id}'."
            )

    prepared = [
        (identity, serialized, row)
        for identity, (serialized, row) in unique_associations.items()
    ]

    linked_assets = {(identity[0], identity[1]) for identity, _, _ in prepared}
    for asset in assets:
        if (asset.source, asset.asset_id) not in linked_assets:
            # Every retrieval asset has a metadata foreign-key row even when its
            # source exposes no biological relationship.
            identity = (asset.source, asset.asset_id, "asset", "", "")
            prepared.append((identity, "{}", {}))
    prepared.sort(key=lambda item: (*item[0], item[1]))

    output: list[SelectionMetadataRow] = []
    for identity, _, row in prepared:
        matched = _scalar(row.get("matched")) == "yes"
        annotation_state = (
            "not_requested" if not annotation_requested else ("matched" if matched else "unmatched")
        )
        values: dict[str, str] = {
            "metadata_row_id": association_row_id(*identity),
            "source": source,
            "asset_id": identity[1],
            "relationship": identity[2],
            "case_id": identity[3],
            "sample_id": identity[4],
            "project": _scalar(row.get("project")),
            "sample_type": _scalar(row.get("sample_type")),
            "annotation_state": annotation_state,
        }
        for column in [*_HARMONIZED_TAIL, *_LEGACY_TAIL]:
            values[column] = _scalar(row.get(column))
        occupied = set(values)
        for column in sorted(row):
            if column in _LEADING_MAPPED_FIELDS or column in values:
                continue
            canonical_column = _native_column(source, column, occupied)
            if canonical_column in occupied:
                suffix = hashlib.sha256(column.encode("utf-8")).hexdigest()[:8]
                canonical_column = f"{canonical_column}_{suffix}"
            values[canonical_column] = _scalar(row.get(column))
            occupied.add(canonical_column)
        output.append(SelectionMetadataRow(values))

    if output:
        validate_metadata(output, assets)
    return output


def metadata_columns(rows: list[SelectionMetadataRow]) -> list[str]:
    known = set(CANONICAL_METADATA_BASE_COLUMNS)
    extra = sorted({key for row in rows for key in row.values if key not in known})
    return [*CANONICAL_METADATA_BASE_COLUMNS, *extra]


def write_asset_manifest(path: str | Path, assets: list[SelectionAsset]) -> None:
    if assets:
        validate_assets(assets)
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ASSET_COLUMNS), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for asset in assets:
            writer.writerow(asset.as_row())


def write_selection_metadata(path: str | Path, rows: list[SelectionMetadataRow]) -> list[str]:
    columns = metadata_columns(rows)
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.values.get(column, "") for column in columns})
    return columns


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_value(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def write_selection_bundle(
    *,
    importer: "BuildImporter",
    file_rows: list[FileRow],
    merged_rows: list[dict],
    manifest_path: str | Path,
    metadata_path: str | Path,
    provenance_path: str | Path,
    query,
    source_provenance: dict | None,
    annotation_requested: bool,
    mode: str,
    source_matches: int | None,
    warnings: list[str] | None = None,
    extra_counts: dict | None = None,
) -> dict:
    """Write and attest a complete canonical selection bundle."""
    if mode not in {"preview", "build"}:
        raise ValueError("selection provenance mode must be 'preview' or 'build'")

    assets, conversion_warnings = build_assets(importer, file_rows)
    metadata = build_metadata(
        importer.name,
        merged_rows,
        assets,
        annotation_requested=annotation_requested,
    )
    write_asset_manifest(manifest_path, assets)
    metadata_header = write_selection_metadata(metadata_path, metadata)
    manifest_digest = _sha256(manifest_path)
    metadata_digest = _sha256(metadata_path)

    cases = {(row.source, row.values.get("case_id", "")) for row in metadata if row.values.get("case_id")}
    samples = {(row.source, row.values.get("sample_id", "")) for row in metadata if row.values.get("sample_id")}
    known_bytes = sum(asset.source_size or 0 for asset in assets)
    counts = {
        "source_reported_matches": source_matches,
        "assets": len(assets),
        "metadata_rows": len(metadata),
        "cases": len(cases),
        "samples": len(samples),
        "known_source_bytes": known_bytes,
    }
    counts.update(extra_counts or {})

    all_warnings = list(dict.fromkeys([*(warnings or []), *conversion_warnings]))
    if assets and any(not asset.access for asset in assets):
        all_warnings.append("One or more assets have no declared access level.")
    if mode == "preview" and not assets:
        all_warnings.append(
            "Preview mode reports source counts without enumerating retrieval assets."
        )

    source_provenance = source_provenance or {}
    timestamp = source_provenance.get("generated_utc") or datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat(timespec="seconds")
    values = {
        "contract_version": CONTRACT_VERSION,
        "mode": mode,
        "source": importer.name,
        "query": _json_value(query),
        "endpoint": source_provenance.get("endpoint", ""),
        "tool": "gacdi-manifest",
        "tool_version": version_string(),
        "build": BUILD,
        "timestamp": timestamp,
        "asset_manifest_sha256": manifest_digest,
        "metadata_sha256": metadata_digest,
        "counts": counts,
        "warnings": all_warnings,
        "metadata_columns": metadata_header,
    }
    validate_provenance(
        values,
        asset_manifest_sha256=manifest_digest,
        metadata_sha256=metadata_digest,
    )
    # The shared validator checks bundle hashes/version; selector generation also
    # freezes the only two legal modes.
    if values["mode"] not in {"preview", "build"}:  # pragma: no cover - guarded above
        raise ValueError(f"Invalid selection mode: {values['mode']}")
    with Path(provenance_path).open("w") as handle:
        json.dump(values, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return values


__all__ = [
    "ASSET_COLUMNS",
    "METADATA_LEADING_COLUMNS",
    "CANONICAL_METADATA_BASE_COLUMNS",
    "DEFAULT_SELECTION_MANIFEST",
    "DEFAULT_SELECTION_METADATA",
    "DEFAULT_SELECTION_PROVENANCE",
    "default_output_paths",
    "build_assets",
    "build_metadata",
    "metadata_columns",
    "write_asset_manifest",
    "write_selection_metadata",
    "write_selection_bundle",
]
