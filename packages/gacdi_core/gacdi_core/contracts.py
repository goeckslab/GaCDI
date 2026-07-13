"""Versioned contracts shared by GaCDI selectors and downloaders.

The v1 selection bundle deliberately separates retrieval assets from biological
metadata.  The asset manifest has one row per object that a transport fetches;
an asset may later produce one or more Galaxy datasets.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


CONTRACT_VERSION = "1.0"

# This order is the physical TSV contract.  Changing it is a breaking change.
ASSET_COLUMNS: tuple[str, ...] = (
    "source",
    "asset_id",
    "asset_kind",
    "download_method",
    "drs_uri",
    "access_url",
    "access",
    "asset_name",
    "source_size",
    "source_checksum_type",
    "source_checksum",
    "file_format",
    "payload_profile",
    "galaxy_ext_hint",
    "dbkey",
)

# Extra source-native columns may follow these keys, but the leading order is
# fixed so simple Galaxy tabular consumers can rely on it.
METADATA_LEADING_COLUMNS: tuple[str, ...] = (
    "metadata_row_id",
    "source",
    "asset_id",
    "relationship",
    "case_id",
    "sample_id",
    "project",
    "sample_type",
    "annotation_state",
)

PROVENANCE_REQUIRED_KEYS: tuple[str, ...] = (
    "contract_version",
    "mode",
    "source",
    "query",
    "endpoint",
    "tool",
    "tool_version",
    "build",
    "timestamp",
    "counts",
    "warnings",
    "asset_manifest_sha256",
    "metadata_sha256",
)
PROVENANCE_COUNT_KEYS: tuple[str, ...] = (
    "assets",
    "metadata_rows",
    "cases",
    "samples",
    "known_source_bytes",
)


def association_row_id(
    source: str,
    asset_id: str,
    relationship: str,
    case_id: str = "",
    sample_id: str = "",
) -> str:
    """Return the contract-1.0 deterministic biological-association ID."""
    identity = "\x1f".join((source, asset_id, relationship, case_id, sample_id))
    return "md_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class SelectionAsset:
    """One source object fetched once by the downloader."""

    source: str
    asset_id: str
    asset_kind: str
    download_method: str
    drs_uri: str
    access_url: str
    access: str
    asset_name: str
    source_size: int | None
    source_checksum_type: str
    source_checksum: str
    file_format: str
    payload_profile: str
    galaxy_ext_hint: str
    dbkey: str

    def as_row(self) -> dict[str, str]:
        """Return the canonical string representation used by TSV writers."""
        row: dict[str, str] = {}
        for column in ASSET_COLUMNS:
            value = getattr(self, column)
            row[column] = "" if value is None else str(value)
        return row


@dataclass(frozen=True)
class SelectionMetadataRow:
    """One biological or administrative relationship to a selection asset."""

    values: dict[str, str]

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    @property
    def metadata_row_id(self) -> str:
        return self.values["metadata_row_id"]

    @property
    def source(self) -> str:
        return self.values["source"]

    @property
    def asset_id(self) -> str:
        return self.values["asset_id"]


@dataclass(frozen=True)
class SelectionProvenance:
    """Validated provenance JSON plus the bundle digests it attests to."""

    values: dict

    @property
    def contract_version(self) -> str:
        return self.values["contract_version"]

    @property
    def mode(self) -> str:
        return self.values["mode"]

    @property
    def asset_manifest_sha256(self) -> str:
        return self.values["asset_manifest_sha256"]

    @property
    def metadata_sha256(self) -> str:
        return self.values["metadata_sha256"]


@dataclass(frozen=True)
class SelectionBundle:
    """A fully validated asset manifest, metadata table, and provenance record."""

    assets: tuple[SelectionAsset, ...]
    metadata: tuple[SelectionMetadataRow, ...]
    provenance: SelectionProvenance
    asset_manifest_sha256: str
    metadata_sha256: str
    metadata_columns: tuple[str, ...] = field(default_factory=tuple)

    @property
    def source(self) -> str:
        return self.assets[0].source

    def metadata_for(self, source: str, asset_id: str) -> tuple[SelectionMetadataRow, ...]:
        return tuple(
            row
            for row in self.metadata
            if row.source == source and row.asset_id == asset_id
        )


__all__ = [
    "CONTRACT_VERSION",
    "ASSET_COLUMNS",
    "METADATA_LEADING_COLUMNS",
    "PROVENANCE_REQUIRED_KEYS",
    "PROVENANCE_COUNT_KEYS",
    "association_row_id",
    "SelectionAsset",
    "SelectionMetadataRow",
    "SelectionProvenance",
    "SelectionBundle",
]
