"""The multi-source (§4.1) manifest schema new sources emit."""

import csv
from dataclasses import fields

from gacdi_manifest.io import SOURCE_MANIFEST_COLUMNS, write_source_manifest
from gacdi_manifest.model import (
    ACCESS_LEVELS,
    CHECKSUM_TYPES,
    DOWNLOAD_METHODS,
    ManifestRow,
)


def test_columns_match_model_field_order():
    # The writer's column order is exactly the ManifestRow field order.
    assert SOURCE_MANIFEST_COLUMNS == [f.name for f in fields(ManifestRow)]


def test_vocabularies_frozen():
    assert "drs" in DOWNLOAD_METHODS and "https" in DOWNLOAD_METHODS
    assert set(CHECKSUM_TYPES) >= {"md5", "sha256", ""}
    assert ACCESS_LEVELS == ("open", "controlled")


def test_write_source_manifest_roundtrip(tmp_path):
    rows = [
        ManifestRow(
            source="pdc", file_id="f1", filename="a.raw",
            drs_uri="drs://pdc/f1", download_method="drs",
            checksum="abc", checksum_type="md5", size="123",
            file_format="RAW", access="open", case_id="c1", sample_id="s1",
        ),
    ]
    out = tmp_path / "m.tsv"
    write_source_manifest(out, rows)
    with open(out, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        assert reader.fieldnames == SOURCE_MANIFEST_COLUMNS
        row = next(reader)
    assert row["source"] == "pdc"
    assert row["drs_uri"] == "drs://pdc/f1"
    assert row["download_method"] == "drs"
    assert row["access"] == "open"
