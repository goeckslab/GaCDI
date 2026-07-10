"""Compatibility contract with the GaCDI GDC importer.

Now that the manifest builder and the ``gacdi`` downloader are one codebase (the
builder depends on ``gacdi``), these tests exercise the **real** importer entry
points instead of a replica: the builder's manifest must parse via
``gacdi.manifest.parse_gdc_manifest``, and its metadata must carry the keys the
importer's run summary is joined on (``gacdi.history.SUMMARY_COLUMNS``).
"""

from __future__ import annotations

import csv

from gacdi.history import SUMMARY_COLUMNS
from gacdi.manifest import parse_gdc_manifest

from gacdi_manifest.cli import main
from gacdi_manifest.io import BASE_METADATA_COLUMNS, MANIFEST_COLUMNS

# The importer joins its downloaded-file summary back to the metadata on these keys.
SUMMARY_JOIN_KEYS = {"file_id", "filename"}


def _build(tmp_path):
    args = [
        "gdc", "--project", "TCGA-BRCA", "--data-type", "Slide Image",
        "--manifest-out", str(tmp_path / "m.txt"),
        "--metadata-out", str(tmp_path / "md.tsv"),
        "--report-out", str(tmp_path / "r.tsv"),
    ]
    assert main(args) == 0


def test_manifest_columns_satisfy_importer_parser():
    # The GDC manifest dialect must include everything the real parser requires.
    required = {"id", "filename", "md5", "size"}
    assert required.issubset({c.lower() for c in MANIFEST_COLUMNS})


def test_builder_manifest_parses_in_real_importer(tmp_path, gdc_api):
    _build(tmp_path)
    entries = parse_gdc_manifest(tmp_path / "m.txt")
    assert [e.file_id for e in entries] == ["uuid1", "uuid2"]
    assert entries[0].filename == "A.svs"
    assert entries[0].source == "gdc"


def test_summary_join_keys_present_in_metadata(tmp_path, gdc_api):
    # The importer's summary exposes these columns; the builder's metadata must
    # carry them so the two can be joined after download.
    assert SUMMARY_JOIN_KEYS.issubset(set(SUMMARY_COLUMNS))
    _build(tmp_path)
    with open(tmp_path / "md.tsv", newline="") as fh:
        header = set(next(csv.reader(fh, delimiter="\t")))
    assert SUMMARY_JOIN_KEYS.issubset(header)


def test_manifest_and_metadata_rows_stay_aligned(tmp_path, gdc_api):
    _build(tmp_path)
    manifest_ids = {e.file_id for e in parse_gdc_manifest(tmp_path / "m.txt")}
    with open(tmp_path / "md.tsv", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert {r["file_id"] for r in rows} == manifest_ids


def test_base_metadata_leads_with_join_keys():
    assert BASE_METADATA_COLUMNS[0] == "file_id"
    assert "filename" in BASE_METADATA_COLUMNS[:2]
