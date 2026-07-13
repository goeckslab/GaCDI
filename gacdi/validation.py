"""Validation rules for the canonical GaCDI selection bundle."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from .contracts import (
    CONTRACT_VERSION,
    PROVENANCE_REQUIRED_KEYS,
    PROVENANCE_COUNT_KEYS,
    SelectionAsset,
    SelectionMetadataRow,
    association_row_id,
)
from .errors import InputError


ASSET_KINDS = frozenset({"file", "series", "run", "prefix", "bundle"})
DOWNLOAD_METHODS = frozenset(
    {"gdc-client", "drs", "https", "ftp", "gcs", "sra-toolkit"}
)
ACCESS_VALUES = frozenset({"open", "controlled"})
CHECKSUM_TYPES = frozenset({"md5", "sha256", "etag"})
ANNOTATION_STATES = frozenset({"not_requested", "matched", "unmatched"})
RELATIONSHIPS = frozenset({"asset", "case", "sample"})
PROVENANCE_MODES = frozenset({"preview", "build"})

_SOURCE = re.compile(r"^[a-z][a-z0-9_-]*$")
_HEX = {
    "md5": re.compile(r"^[0-9a-fA-F]{32}$"),
    "sha256": re.compile(r"^[0-9a-fA-F]{64}$"),
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _required(value: str, *, field: str, row_number: int) -> None:
    if not value:
        raise InputError(f"Asset row {row_number}: '{field}' is required.")


def _validate_access_url(asset: SelectionAsset, row_number: int) -> None:
    method = asset.download_method
    if method in {"gdc-client", "sra-toolkit"}:
        # These transports use asset_id as their stable locator.
        return
    if method == "drs":
        if not asset.drs_uri:
            raise InputError(f"Asset row {row_number}: download_method 'drs' requires drs_uri.")
        parsed = urlparse(asset.drs_uri)
        if parsed.scheme not in {"drs", "https"}:
            raise InputError(
                f"Asset row {row_number}: drs_uri must use the drs or https scheme."
            )
        return
    if not asset.access_url:
        raise InputError(
            f"Asset row {row_number}: download_method '{method}' requires access_url."
        )
    parsed = urlparse(asset.access_url)
    expected = {
        "https": {"https"},
        "ftp": {"ftp", "https"},
        "gcs": {"gs", "https"},
    }.get(method)
    if expected and parsed.scheme not in expected:
        schemes = ", ".join(sorted(expected))
        raise InputError(
            f"Asset row {row_number}: access_url for '{method}' must use: {schemes}."
        )


def validate_assets(assets: list[SelectionAsset]) -> None:
    """Validate row values, locators, uniqueness, and the one-source v1 rule."""
    if not assets:
        raise InputError("Selection asset manifest contained no assets.")

    keys: set[tuple[str, str]] = set()
    ordered_keys: list[tuple[str, str]] = []
    sources: set[str] = set()
    profiles: set[str] = set()
    for row_number, asset in enumerate(assets, start=2):
        for field in (
            "source",
            "asset_id",
            "asset_kind",
            "download_method",
            "access",
            "asset_name",
            "payload_profile",
        ):
            _required(str(getattr(asset, field)), field=field, row_number=row_number)

        if not _SOURCE.fullmatch(asset.source):
            raise InputError(
                f"Asset row {row_number}: invalid source '{asset.source}'; use a lowercase source ID."
            )
        if asset.asset_kind not in ASSET_KINDS:
            raise InputError(
                f"Asset row {row_number}: unsupported asset_kind '{asset.asset_kind}'."
            )
        if asset.download_method not in DOWNLOAD_METHODS:
            raise InputError(
                f"Asset row {row_number}: unsupported download_method '{asset.download_method}'."
            )
        if asset.access not in ACCESS_VALUES:
            raise InputError(
                f"Asset row {row_number}: access must be 'open' or 'controlled'."
            )
        if (
            "/" in asset.asset_id
            or "\\" in asset.asset_id
            or asset.asset_id in {".", ".."}
            or any(ord(character) < 32 or ord(character) == 127 for character in asset.asset_id)
        ):
            raise InputError(
                f"Asset row {row_number}: asset_id must not contain path traversal or control "
                f"characters, got '{asset.asset_id}'."
            )
        if (
            "/" in asset.asset_name
            or "\\" in asset.asset_name
            or asset.asset_name in {".", ".."}
            or any(ord(character) < 32 or ord(character) == 127 for character in asset.asset_name)
        ):
            raise InputError(
                f"Asset row {row_number}: asset_name must be a safe basename, got '{asset.asset_name}'."
            )
        if asset.source_size is not None and asset.source_size < 0:
            raise InputError(f"Asset row {row_number}: source_size cannot be negative.")

        checksum_type = asset.source_checksum_type
        checksum = asset.source_checksum
        if bool(checksum_type) != bool(checksum):
            raise InputError(
                f"Asset row {row_number}: source_checksum_type and source_checksum must be set together."
            )
        if checksum_type:
            if checksum_type not in CHECKSUM_TYPES:
                raise InputError(
                    f"Asset row {row_number}: unsupported checksum type '{checksum_type}'."
                )
            pattern = _HEX.get(checksum_type)
            if pattern and not pattern.fullmatch(checksum):
                raise InputError(
                    f"Asset row {row_number}: invalid {checksum_type} checksum '{checksum}'."
                )

        _validate_access_url(asset, row_number)
        key = (asset.source, asset.asset_id)
        if key in keys:
            raise InputError(
                f"Asset row {row_number}: duplicate retrieval asset '{asset.source}:{asset.asset_id}'."
            )
        keys.add(key)
        ordered_keys.append(key)
        sources.add(asset.source)
        profiles.add(asset.payload_profile)

    if len(sources) != 1:
        raise InputError(
            "Contract 1.0 requires exactly one source per selection bundle; found: "
            + ", ".join(sorted(sources))
        )
    if len(profiles) != 1:
        raise InputError(
            "Contract 1.0 requires one homogeneous payload_profile per bundle; found: "
            + ", ".join(sorted(profiles))
        )
    if ordered_keys != sorted(ordered_keys):
        raise InputError(
            "Selection assets must be in canonical ascending order by source, asset_id."
        )


def validate_metadata(
    rows: list[SelectionMetadataRow], assets: list[SelectionAsset]
) -> None:
    """Validate metadata identities and foreign keys to retrieval assets."""
    if not rows:
        raise InputError("Selection metadata contained no rows.")

    asset_keys = {(asset.source, asset.asset_id) for asset in assets}
    linked: Counter[tuple[str, str]] = Counter()
    row_ids: set[str] = set()
    associations: set[tuple[str, str, str, str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        values = row.values
        for field in ("metadata_row_id", "source", "asset_id", "relationship", "annotation_state"):
            if not values.get(field, ""):
                raise InputError(f"Metadata row {row_number}: '{field}' is required.")
        if row.metadata_row_id in row_ids:
            raise InputError(
                f"Metadata row {row_number}: duplicate metadata_row_id '{row.metadata_row_id}'."
            )
        row_ids.add(row.metadata_row_id)
        relationship = values["relationship"]
        case_id = values.get("case_id", "")
        sample_id = values.get("sample_id", "")
        if relationship not in RELATIONSHIPS:
            raise InputError(
                f"Metadata row {row_number}: relationship must be asset, case, or sample."
            )
        if relationship == "asset" and (case_id or sample_id):
            raise InputError(
                f"Metadata row {row_number}: an asset relationship cannot set case_id or sample_id."
            )
        if relationship == "case" and (not case_id or sample_id):
            raise InputError(
                f"Metadata row {row_number}: a case relationship requires case_id and no sample_id."
            )
        if relationship == "sample" and not sample_id:
            raise InputError(
                f"Metadata row {row_number}: a sample relationship requires sample_id."
            )
        expected_row_id = association_row_id(
            row.source,
            row.asset_id,
            relationship,
            case_id,
            sample_id,
        )
        if row.metadata_row_id != expected_row_id:
            raise InputError(
                f"Metadata row {row_number}: metadata_row_id does not match the canonical "
                f"association ID; expected '{expected_row_id}'."
            )
        association = (row.source, row.asset_id, relationship, case_id, sample_id)
        if association in associations:
            raise InputError(
                f"Metadata row {row_number}: duplicate biological association for "
                f"'{row.source}:{row.asset_id}'."
            )
        associations.add(association)
        key = (row.source, row.asset_id)
        if key not in asset_keys:
            raise InputError(
                f"Metadata row {row_number}: unknown asset '{row.source}:{row.asset_id}'."
            )
        annotation_state = values["annotation_state"]
        if annotation_state not in ANNOTATION_STATES:
            raise InputError(
                f"Metadata row {row_number}: unsupported annotation_state '{annotation_state}'."
            )
        linked[key] += 1

    missing = sorted(asset_keys - set(linked))
    if missing:
        rendered = ", ".join(f"{source}:{asset_id}" for source, asset_id in missing)
        raise InputError(f"Selection metadata has no row for asset(s): {rendered}.")


def validate_provenance(
    values: dict,
    *,
    asset_manifest_sha256: str,
    metadata_sha256: str,
) -> None:
    """Validate provenance version, digest syntax, and bundle integrity."""
    missing = [key for key in PROVENANCE_REQUIRED_KEYS if key not in values]
    if missing:
        raise InputError("Selection provenance is missing required key(s): " + ", ".join(missing))
    if values["contract_version"] != CONTRACT_VERSION:
        raise InputError(
            f"Unsupported selection contract version '{values['contract_version']}'; "
            f"expected '{CONTRACT_VERSION}'."
        )
    if not isinstance(values["source"], str) or not _SOURCE.fullmatch(values["source"]):
        raise InputError("Selection provenance source must be a lowercase source ID.")
    if not isinstance(values["query"], dict):
        raise InputError("Selection provenance query must be a JSON object.")
    for key in ("endpoint", "tool", "tool_version", "build", "timestamp"):
        if not isinstance(values[key], str):
            raise InputError(f"Selection provenance key '{key}' must be a string.")
    if not values["tool"] or not values["tool_version"] or not values["timestamp"]:
        raise InputError("Selection provenance tool, tool_version, and timestamp are required.")
    if not isinstance(values["counts"], dict):
        raise InputError("Selection provenance counts must be a JSON object.")
    missing_counts = [key for key in PROVENANCE_COUNT_KEYS if key not in values["counts"]]
    if missing_counts:
        raise InputError(
            "Selection provenance counts is missing required key(s): "
            + ", ".join(missing_counts)
        )
    for key in PROVENANCE_COUNT_KEYS:
        value = values["counts"][key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise InputError(
                f"Selection provenance count '{key}' must be a non-negative integer."
            )
    if not isinstance(values["warnings"], list) or not all(
        isinstance(warning, str) for warning in values["warnings"]
    ):
        raise InputError("Selection provenance warnings must be a list of strings.")
    if not isinstance(values["mode"], str) or values["mode"] not in PROVENANCE_MODES:
        raise InputError("Selection provenance mode must be 'preview' or 'build'.")
    for key in ("asset_manifest_sha256", "metadata_sha256"):
        digest = values[key]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise InputError(f"Selection provenance key '{key}' must be a lowercase SHA-256 digest.")
    if values["asset_manifest_sha256"] != asset_manifest_sha256:
        raise InputError("Selection asset manifest SHA-256 does not match provenance.")
    if values["metadata_sha256"] != metadata_sha256:
        raise InputError("Selection metadata SHA-256 does not match provenance.")


__all__ = [
    "ASSET_KINDS",
    "DOWNLOAD_METHODS",
    "ACCESS_VALUES",
    "CHECKSUM_TYPES",
    "ANNOTATION_STATES",
    "RELATIONSHIPS",
    "PROVENANCE_MODES",
    "validate_assets",
    "validate_metadata",
    "validate_provenance",
]
