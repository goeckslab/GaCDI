from mcdi.manifest.join import join, normalize_barcode
from mcdi.manifest.model import FileRow


def _filerow(uuid, sample_bc):
    return FileRow(
        file_id=uuid, filename=f"{uuid}.svs", md5="x", size="1", state="released",
        meta={"cases.0.samples.0.submitter_id": sample_bc, "cases.0.submitter_id": sample_bc[:12]},
    )


def test_normalize_levels():
    bc = "TCGA-E9-A5FL-01A-01-DX1"
    assert normalize_barcode(bc, "patient") == "TCGA-E9-A5FL"
    assert normalize_barcode(bc, "sample", trim_vial=True) == "TCGA-E9-A5FL-01"
    assert normalize_barcode(bc, "sample", trim_vial=False) == "TCGA-E9-A5FL-01A"
    assert normalize_barcode(bc, "full") == bc


def test_join_matches_and_reports():
    rows = [_filerow("uuid1", "TCGA-E9-A5FL-01A"), _filerow("uuid2", "TCGA-XX-YYYY-01A")]
    annotations = {"TCGA-E9-A5FL-01": {"SUBTYPE": "Basal"}}
    merged, report = join(rows, annotations, level="sample", trim_vial=True, annotation_columns=["SUBTYPE"])
    assert report.total_files == 2
    assert report.matched_files == 1
    assert report.unmatched_files == ["uuid2"]
    assert merged[0]["SUBTYPE"] == "Basal" and merged[0]["matched"] == "yes"
    assert merged[1]["SUBTYPE"] == "" and merged[1]["matched"] == "no"


def test_join_reports_unused_annotation():
    rows = [_filerow("uuid1", "TCGA-E9-A5FL-01A")]
    annotations = {"TCGA-ZZ-0000-01": {"SUBTYPE": "LumA"}}
    _, report = join(rows, annotations, annotation_columns=["SUBTYPE"])
    assert "TCGA-ZZ-0000-01" in report.unused_annotations
