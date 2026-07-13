"""Freeze the T0.1 output contracts (see docs/CONTRACTS.md)."""

from gacdi_manifest import io
from gacdi_manifest.model import (
    ACCESS_VALUES,
    DOWNLOAD_METHODS,
    HARMONIZED_CORE_COLUMNS,
    MANIFEST_DIALECTS,
    MANIFEST_SUPERSET,
    ManifestRow,
    MetadataRecord,
    native_column,
)


def test_gdc_dialect_matches_writer():
    # The dialect registry and the actual manifest writer must not drift apart:
    # GDC stays lean/back-compatible with gdc-client and the importer contract.
    assert MANIFEST_DIALECTS["gdc"] == io.MANIFEST_COLUMNS


def test_gdc_dialect_is_a_subset_named_by_superset_or_gdc_specific():
    # Every GDC dialect column is either a superset field or a documented
    # GDC-specific alias (id->file_id, md5->checksum, state).
    aliases = {"id", "md5", "state"}
    for col in MANIFEST_DIALECTS["gdc"]:
        assert col in MANIFEST_SUPERSET or col in aliases


def test_harmonized_core_leads_with_join_keys():
    assert HARMONIZED_CORE_COLUMNS[:4] == ["source", "case_id", "sample_id", "file_id"]


def test_native_column_is_source_prefixed():
    assert native_column("gdc", "data_category") == "gdc__data_category"


def test_enums_present():
    assert "drs" in DOWNLOAD_METHODS and "sra-toolkit" in DOWNLOAD_METHODS
    assert ACCESS_VALUES == {"open", "controlled"}


def test_manifest_row_minimal():
    row = ManifestRow(source="gdc", file_id="uuid1", filename="A.svs")
    assert row.access == ""  # unset fields default empty, not None


def test_metadata_record_as_row_prefixes_native_and_keeps_core():
    rec = MetadataRecord(
        source="gdc",
        file_id="uuid1",
        case_id="C1",
        sample_id="S1",
        core={"primary_site": "Breast", "gender": "female"},
        native={"data_category": "Biospecimen"},
    )
    row = rec.as_row()
    assert row["source"] == "gdc"
    assert row["file_id"] == "uuid1"
    assert row["primary_site"] == "Breast"           # core kept unprefixed
    assert row["gdc__data_category"] == "Biospecimen"  # native prefixed
