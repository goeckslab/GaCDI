"""Cross-tool compatibility for the legacy GDC manifest and metadata outputs.

These assertions intentionally import both distributions, so they belong in the
integration suite rather than either package's isolated unit suite.
"""

from __future__ import annotations

import csv

from gacdi.history import SUMMARY_COLUMNS
from gacdi.manifest import parse_gdc_manifest
from gacdi_manifest.cli import main as build_main
from gacdi_manifest.io import BASE_METADATA_COLUMNS, MANIFEST_COLUMNS

SUMMARY_JOIN_KEYS = {"file_id", "filename"}


def _build(tmp_path):
    rc = build_main(
        [
            "gdc",
            "--project",
            "TCGA-BRCA",
            "--data-type",
            "Slide Image",
            "--manifest-out",
            str(tmp_path / "m.txt"),
            "--metadata-out",
            str(tmp_path / "md.tsv"),
            "--report-out",
            str(tmp_path / "r.tsv"),
        ]
    )
    assert rc == 0


def test_manifest_columns_satisfy_downloader_parser():
    required = {"id", "filename", "md5", "size"}
    assert required.issubset({column.lower() for column in MANIFEST_COLUMNS})


def test_builder_manifest_parses_in_downloader(tmp_path, gdc_api):
    _build(tmp_path)
    entries = parse_gdc_manifest(tmp_path / "m.txt")
    assert [entry.file_id for entry in entries] == ["uuid1", "uuid2"]
    assert entries[0].filename == "A.svs"
    assert entries[0].source == "gdc"


def test_summary_join_keys_are_present_in_metadata(tmp_path, gdc_api):
    assert SUMMARY_JOIN_KEYS.issubset(set(SUMMARY_COLUMNS))
    _build(tmp_path)
    with open(tmp_path / "md.tsv", newline="") as handle:
        header = set(next(csv.reader(handle, delimiter="\t")))
    assert SUMMARY_JOIN_KEYS.issubset(header)


def test_manifest_and_metadata_file_ids_align(tmp_path, gdc_api):
    _build(tmp_path)
    manifest_ids = {
        entry.file_id for entry in parse_gdc_manifest(tmp_path / "m.txt")
    }
    with open(tmp_path / "md.tsv", newline="") as handle:
        metadata_ids = {
            row["file_id"] for row in csv.DictReader(handle, delimiter="\t")
        }
    assert manifest_ids == metadata_ids


def test_base_metadata_leads_with_join_keys():
    assert BASE_METADATA_COLUMNS[0] == "file_id"
    assert "filename" in BASE_METADATA_COLUMNS[:2]
