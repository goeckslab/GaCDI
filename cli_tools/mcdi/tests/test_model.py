from mcdi.manifest.model import (
    case_barcode,
    disease_type,
    galaxy_ext,
    primary_site,
    project_id,
    sample_barcode,
    sample_type,
)


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


def test_case_site_and_disease_extraction():
    row = {"cases.0.primary_site": "Breast", "cases.0.disease_type": "Ductal and Lobular Neoplasms"}
    assert primary_site(row) == "Breast"
    assert disease_type(row) == "Ductal and Lobular Neoplasms"


def test_galaxy_ext_from_filename():
    assert galaxy_ext("TCGA-X.svs") == "svs"
    assert galaxy_ext("aligned.bam") == "bam"
    assert galaxy_ext("calls.vcf.gz") == "vcf_bgzip"
    assert galaxy_ext("mutations.maf") == "tabular"
    assert galaxy_ext("reads_1.fastq.gz") == "fastqsanger.gz"


def test_galaxy_ext_falls_back_to_format_then_generic():
    assert galaxy_ext("noextension", "BAM") == "bam"
    assert galaxy_ext("noextension", None) == "data"
