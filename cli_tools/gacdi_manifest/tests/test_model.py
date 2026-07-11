from gacdi_manifest.model import (
    case_barcode,
    case_id,
    disease_type,
    galaxy_ext,
    primary_site,
    project_id,
    sample_barcode,
    sample_id,
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


def test_enumerate_samples_multi_sample_file():
    from gacdi_manifest.model import enumerate_samples

    # One case with two samples + one case with one sample -> three records, each
    # carrying its own case's clinical fields.
    row = {
        "cases.0.case_id": "c0",
        "cases.0.submitter_id": "TCGA-AA-0000",
        "cases.0.demographic.sex_at_birth": "female",
        "cases.0.samples.0.sample_id": "s0", "cases.0.samples.0.submitter_id": "TCGA-AA-0000-01A",
        "cases.0.samples.1.sample_id": "s1", "cases.0.samples.1.submitter_id": "TCGA-AA-0000-11A",
        "cases.1.case_id": "c1",
        "cases.1.submitter_id": "TCGA-BB-1111",
        "cases.1.samples.0.sample_id": "s2", "cases.1.samples.0.submitter_id": "TCGA-BB-1111-01A",
    }
    recs = enumerate_samples(row)
    assert [r["sample_id"] for r in recs] == ["s0", "s1", "s2"]
    assert [r["case_id"] for r in recs] == ["c0", "c0", "c1"]
    assert recs[0]["gender"] == "female" and recs[2]["gender"] == ""


def test_enumerate_samples_always_yields_one_record():
    from gacdi_manifest.model import enumerate_samples

    # A file with no case/sample info still yields exactly one (empty) record.
    assert len(enumerate_samples({})) == 1


def test_uuid_extraction_from_flattened_row():
    row = {
        "cases.0.case_id": "c-uuid-1",
        "cases.0.samples.0.sample_id": "s-uuid-1",
    }
    assert case_id(row) == "c-uuid-1"
    assert sample_id(row) == "s-uuid-1"


def test_barcode_extraction_unprefixed_fallback():
    row = {"cases.submitter_id": "TCGA-AA-1234"}
    assert case_barcode(row) == "TCGA-AA-1234"


def test_case_site_and_disease_extraction():
    row = {"cases.0.primary_site": "Breast", "cases.0.disease_type": "Ductal and Lobular Neoplasms"}
    assert primary_site(row) == "Breast"
    assert disease_type(row) == "Ductal and Lobular Neoplasms"


def test_clinical_extraction_from_flattened_row():
    from gacdi_manifest.model import age_at_diagnosis, gender, grade, stage, vital_status

    row = {
        "cases.0.demographic.sex_at_birth": "female",
        "cases.0.demographic.vital_status": "Alive",
        "cases.0.diagnoses.0.age_at_diagnosis": "21915",
        "cases.0.diagnoses.0.ajcc_pathologic_stage": "Stage IIA",
        "cases.0.diagnoses.0.tumor_grade": "G2",
    }
    assert gender(row) == "female"
    assert vital_status(row) == "Alive"
    assert age_at_diagnosis(row) == "21915"
    assert stage(row) == "Stage IIA"
    assert grade(row) == "G2"


def test_gender_sourced_from_sex_at_birth_not_legacy_field():
    """GDC dropped `demographic.gender` and replaced it with `sex_at_birth`.

    The harmonized `gender` column must read the current field; the legacy field
    name is no longer emitted by GDC and must not be relied on. This guards the
    regression where the column silently stayed blank on real queries.
    """
    from gacdi_manifest.gdc import FIELDS
    from gacdi_manifest.model import gender

    assert gender({"cases.0.demographic.sex_at_birth": "male"}) == "male"
    assert gender({"cases.0.demographic.gender": "male"}) is None

    # The GDC request must ask for the current field, not the dropped one.
    assert "cases.demographic.sex_at_birth" in FIELDS
    assert "cases.demographic.gender" not in FIELDS


def test_galaxy_ext_from_filename():
    assert galaxy_ext("TCGA-X.svs") == "svs"
    assert galaxy_ext("aligned.bam") == "bam"
    assert galaxy_ext("calls.vcf.gz") == "vcf_bgzip"
    assert galaxy_ext("mutations.maf") == "tabular"
    assert galaxy_ext("reads_1.fastq.gz") == "fastqsanger.gz"


def test_galaxy_ext_falls_back_to_format_then_generic():
    assert galaxy_ext("noextension", "BAM") == "bam"
    assert galaxy_ext("noextension", None) == "data"
