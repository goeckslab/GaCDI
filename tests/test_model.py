from gacdi_manifest.model import case_barcode, project_id, sample_barcode, sample_type


def test_barcode_extraction_from_flattened_row():
    row = {
        "cases.0.submitter_id": "TCGA-E9-A5FL",
        "cases.0.samples.0.submitter_id": "TCGA-E9-A5FL-01A",
        "cases.0.samples.0.sample_type": "Primary Tumor",
        "cases.0.project.project_id": "TCGA-BRCA",
    }
    assert case_barcode(row) == "TCGA-E9-A5FL"
    assert sample_barcode(row) == "TCGA-E9-A5FL-01A"
    assert sample_type(row) == "Primary Tumor"
    assert project_id(row) == "TCGA-BRCA"


def test_barcode_extraction_unprefixed_fallback():
    row = {"cases.submitter_id": "TCGA-AA-1234"}
    assert case_barcode(row) == "TCGA-AA-1234"
