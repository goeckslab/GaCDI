"""Canonical selection-bundle outputs added alongside legacy compatibility files."""

from __future__ import annotations

import csv
import hashlib
import json

import pytest

from gacdi_core.contracts import (
    ASSET_COLUMNS,
    CONTRACT_VERSION,
    METADATA_LEADING_COLUMNS,
    SelectionAsset,
)
from gacdi_core.errors import InputError as ContractInputError
from gacdi_core.validation import validate_assets

from gacdi_manifest import cbioportal
from gacdi_manifest.cli import main
from gacdi_manifest.errors import InputError
from gacdi_manifest.model import FileRow, ManifestRow
from gacdi_manifest.selection import build_assets


def _args(tmp_path, *extra):
    return [
        "gdc", "--project", "TCGA-BRCA", "--data-type", "Slide Image",
        "--manifest-out", str(tmp_path / "legacy_manifest.txt"),
        "--metadata-out", str(tmp_path / "legacy_metadata.tsv"),
        "--report-out", str(tmp_path / "legacy_report.tsv"),
        *extra,
    ]


def _rows(path):
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return reader.fieldnames, list(reader)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_full_build_writes_canonical_bundle_with_default_paths(tmp_path, gdc_api):
    assert main(_args(tmp_path)) == 0

    manifest = tmp_path / "selection_manifest.tsv"
    metadata = tmp_path / "selection_metadata.tsv"
    provenance = tmp_path / "selection_provenance.json"
    assert manifest.is_file() and metadata.is_file() and provenance.is_file()

    header, assets = _rows(manifest)
    assert header == list(ASSET_COLUMNS)
    assert [row["asset_id"] for row in assets] == ["uuid1", "uuid2"]
    assert {row["source"] for row in assets} == {"gdc"}
    assert {row["download_method"] for row in assets} == {"gdc-client"}
    assert {row["payload_profile"] for row in assets} == {"single_svs"}
    assert {row["galaxy_ext_hint"] for row in assets} == {"svs"}
    assert {row["access"] for row in assets} == {"open"}

    metadata_header, metadata_rows = _rows(metadata)
    assert metadata_header[: len(METADATA_LEADING_COLUMNS)] == list(METADATA_LEADING_COLUMNS)
    assert {row["annotation_state"] for row in metadata_rows} == {"not_requested"}
    assert {row["relationship"] for row in metadata_rows} == {"sample"}
    assert all(row["metadata_row_id"].startswith("md_") for row in metadata_rows)
    # Canonical native keys are source-prefixed and escaped; legacy columns remain unchanged.
    assert "gdc__cases_0_demographic_sex_at_birth" in metadata_header

    values = json.loads(provenance.read_text())
    assert values["contract_version"] == CONTRACT_VERSION
    assert values["mode"] == "build"
    assert values["source"] == "gdc"
    assert values["asset_manifest_sha256"] == _digest(manifest)
    assert values["metadata_sha256"] == _digest(metadata)
    assert values["counts"]["assets"] == 2
    assert values["counts"]["metadata_rows"] == 2


def test_explicit_output_flags_and_legacy_outputs_remain_compatible(tmp_path, gdc_api):
    canonical_manifest = tmp_path / "chosen.assets.tsv"
    canonical_metadata = tmp_path / "chosen.metadata.tsv"
    canonical_provenance = tmp_path / "chosen.provenance.json"
    assert main(_args(
        tmp_path,
        "--selection-manifest-out", str(canonical_manifest),
        "--selection-metadata-out", str(canonical_metadata),
        "--selection-provenance-out", str(canonical_provenance),
    )) == 0

    assert canonical_manifest.is_file()
    assert canonical_metadata.is_file()
    assert canonical_provenance.is_file()
    legacy_lines = (tmp_path / "legacy_manifest.txt").read_text().splitlines()
    assert legacy_lines[0] == "id\tfilename\tmd5\tsize\tstate"
    assert legacy_lines[1] == "uuid1\tA.svs\tmd5a\t100\treleased"
    legacy_header, _ = _rows(tmp_path / "legacy_metadata.tsv")
    assert "gdc__cases.0.demographic.sex_at_birth" in legacy_header


def test_annotation_state_distinguishes_matched_and_unmatched(tmp_path, gdc_api):
    annotation = tmp_path / "annotation.tsv"
    annotation.write_text("sample\tHistology\nTCGA-E9-A5FL-01\tIDC\n")
    assert main(_args(
        tmp_path,
        "--annotation-tsv", str(annotation),
        "--annotation-key-col", "sample",
    )) == 0
    _, rows = _rows(tmp_path / "selection_metadata.tsv")
    by_asset = {row["asset_id"]: row for row in rows}
    assert by_asset["uuid1"]["annotation_state"] == "matched"
    assert by_asset["uuid2"]["annotation_state"] == "unmatched"
    assert by_asset["uuid1"]["Histology"] == "IDC"


def test_count_only_writes_valid_empty_canonical_files(tmp_path, gdc_api):
    assert main(_args(tmp_path, "--count-only")) == 0
    manifest_header, manifest_rows = _rows(tmp_path / "selection_manifest.tsv")
    metadata_header, metadata_rows = _rows(tmp_path / "selection_metadata.tsv")
    assert manifest_header == list(ASSET_COLUMNS) and manifest_rows == []
    assert metadata_header[: len(METADATA_LEADING_COLUMNS)] == list(METADATA_LEADING_COLUMNS)
    assert metadata_rows == []
    provenance = json.loads((tmp_path / "selection_provenance.json").read_text())
    assert provenance["mode"] == "preview"
    assert provenance["counts"]["source_reported_matches"] == 2
    assert provenance["asset_manifest_sha256"] == _digest(tmp_path / "selection_manifest.tsv")


def test_cbioportal_attribute_list_writes_empty_canonical_bundle(tmp_path, requests_mock):
    study = "brca_tcga"
    requests_mock.get(
        f"{cbioportal.DEFAULT_BASE}/studies/{study}/clinical-attributes",
        json=[{"clinicalAttributeId": "SUBTYPE", "displayName": "Subtype"}],
    )
    args = [
        "gdc", "--cbioportal-study", study, "--cbioportal-list-attrs",
        "--manifest-out", str(tmp_path / "m.txt"),
        "--metadata-out", str(tmp_path / "md.tsv"),
        "--report-out", str(tmp_path / "r.tsv"),
    ]
    assert main(args) == 0
    _, assets = _rows(tmp_path / "selection_manifest.tsv")
    _, metadata = _rows(tmp_path / "selection_metadata.tsv")
    provenance = json.loads((tmp_path / "selection_provenance.json").read_text())
    assert assets == [] and metadata == []
    assert provenance["mode"] == "preview"
    assert provenance["counts"]["cbioportal_attributes"] == 1


def test_gdc_mixed_payloads_become_raw_mixed():
    class GDC:
        name = "gdc"
        manifest_dialect = "gdc"

    rows = [
        FileRow("a", "a.bam", "", "10", "released", {"access": "open", "data_format": "BAM"}),
        FileRow("b", "b.vcf", "", "20", "released", {"access": "open", "data_format": "VCF"}),
    ]
    assets, warnings = build_assets(GDC(), rows)
    assert {asset.payload_profile for asset in assets} == {"raw_mixed"}
    assert any("mixed payload profiles" in warning for warning in warnings)


def test_conflicting_duplicate_asset_rows_are_rejected():
    class DuplicateSource:
        name = "pdc"
        manifest_dialect = "source"

        def to_manifest_rows(self, file_rows):
            return [
                ManifestRow(
                    source="pdc", file_id="f1", filename="a.raw", drs_uri="drs://dg.4DFC:f1",
                    download_method="drs", access="open",
                ),
                ManifestRow(
                    source="pdc", file_id="f1", filename="different.raw", drs_uri="drs://dg.4DFC:f1",
                    download_method="drs", access="open",
                ),
            ]

    with pytest.raises(InputError, match="contradictory rows"):
        build_assets(DuplicateSource(), [FileRow("f1", "a.raw", "", "", "released")])


def test_shared_validator_rejects_invalid_access():
    asset = SelectionAsset(
        source="gdc", asset_id="f1", asset_kind="file", download_method="gdc-client",
        drs_uri="", access_url="", access="public", asset_name="a.bam", source_size=1,
        source_checksum_type="", source_checksum="", file_format="BAM",
        payload_profile="single_bam", galaxy_ext_hint="bam", dbkey="",
    )
    with pytest.raises(ContractInputError, match="access must be 'open' or 'controlled'"):
        validate_assets([asset])
