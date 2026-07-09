"""Compatibility contract with the GaCDI GDC importer (NIH_commons branch).

These tests encode what the importer's ``parse_gdc_manifest`` requires and how its
history ``summary`` is keyed, so a change here that would break the download
hand-off fails loudly. Kept self-contained (the importer package is not on this
branch) by replicating the importer's exact expectations.
"""

from __future__ import annotations

import csv

from gacdi_manifest.cli import main
from gacdi_manifest.io import BASE_METADATA_COLUMNS, MANIFEST_COLUMNS

# --- mirrored from NIH_commons: gacdi/manifest.py and gacdi/history.py ---
IMPORTER_REQUIRED_MANIFEST_COLUMNS = {"id", "filename", "md5", "size"}
IMPORTER_SUMMARY_KEYS = {"file_id", "filename"}  # how downloaded files are identified
IMPORTER_MANIFEST_INPUT_FORMATS = {"tabular", "txt"}


def _simulate_importer_parse(path):
    """Replica of gacdi.manifest.parse_gdc_manifest's contract."""
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        header = {c.strip().lower() for c in (reader.fieldnames or [])}
        assert IMPORTER_REQUIRED_MANIFEST_COLUMNS.issubset(header), (
            f"manifest missing required columns: "
            f"{IMPORTER_REQUIRED_MANIFEST_COLUMNS - header}"
        )
        entries = []
        for row in reader:
            norm = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            if not norm.get("id"):
                continue
            entries.append({"file_id": norm["id"], "filename": norm.get("filename") or norm["id"]})
    return entries


def test_manifest_columns_match_importer_requirements():
    assert IMPORTER_REQUIRED_MANIFEST_COLUMNS.issubset({c.lower() for c in MANIFEST_COLUMNS})


def test_manifest_output_parses_in_importer(tmp_path, gdc_api):
    args = [
        "gdc", "--project", "TCGA-BRCA", "--data-type", "Slide Image",
        "--manifest-out", str(tmp_path / "m.txt"),
        "--metadata-out", str(tmp_path / "md.tsv"),
        "--report-out", str(tmp_path / "r.tsv"),
    ]
    assert main(args) == 0

    entries = _simulate_importer_parse(tmp_path / "m.txt")
    assert [e["file_id"] for e in entries] == ["uuid1", "uuid2"]
    assert entries[0]["filename"] == "A.svs"


def test_metadata_joins_to_importer_summary(tmp_path, gdc_api):
    """metadata leads with file_id/filename, so it joins the importer's summary."""
    main([
        "gdc", "--project", "TCGA-BRCA", "--data-type", "Slide Image",
        "--manifest-out", str(tmp_path / "m.txt"),
        "--metadata-out", str(tmp_path / "md.tsv"),
        "--report-out", str(tmp_path / "r.tsv"),
    ])
    with open(tmp_path / "md.tsv", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        header = set(reader.fieldnames or [])
        rows = list(reader)

    # The importer's history summary key columns must exist in the metadata.
    assert IMPORTER_SUMMARY_KEYS.issubset(header)
    # Same file ids appear in the manifest and metadata (rows stay aligned).
    manifest_ids = {e["file_id"] for e in _simulate_importer_parse(tmp_path / "m.txt")}
    assert {r["file_id"] for r in rows} == manifest_ids


def test_base_metadata_leads_with_join_keys():
    assert BASE_METADATA_COLUMNS[0] == "file_id"
    assert "filename" in BASE_METADATA_COLUMNS[:2]
