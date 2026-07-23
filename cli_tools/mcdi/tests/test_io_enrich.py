import json

import requests

from mcdi.manifest import enrich, io
from mcdi.manifest.join import JoinReport
from mcdi.manifest.model import FileRow


def test_write_manifest_strict_columns(tmp_path):
    rows = [FileRow("uuid1", "A.svs", "md5a", "100", "released")]
    out = tmp_path / "m.txt"
    io.write_manifest(out, rows)
    lines = out.read_text().splitlines()
    assert lines[0] == "id\tfilename\tmd5\tsize\tstate"
    assert lines[1] == "uuid1\tA.svs\tmd5a\t100\treleased"


def test_write_metadata_columns(tmp_path):
    merged = [{"file_id": "uuid1", "filename": "A.svs", "SUBTYPE": "Basal", "matched": "yes"}]
    out = tmp_path / "md.tsv"
    io.write_metadata(out, merged, ["SUBTYPE"])
    header = out.read_text().splitlines()[0].split("\t")
    assert header[0] == "file_id" and "SUBTYPE" in header


def test_write_report(tmp_path):
    merged = [
        {"file_id": "uuid1", "size": "100", "data_type": "Slide Image", "galaxy_ext": "svs",
         "matched": "yes", "sample_barcode": "TCGA-A-1-01"},
        {"file_id": "uuid2", "size": "200", "data_type": "Slide Image", "galaxy_ext": "svs",
         "matched": "no", "sample_barcode": "TCGA-B-2-01"},
    ]
    report = JoinReport(total_files=2, matched_files=1, unmatched_files=["uuid2"])
    out = tmp_path / "r.tsv"
    io.write_report(out, database_total=2, merged_rows=merged, report=report,
                    enrichment_columns=["SUBTYPE"])
    text = out.read_text()
    assert "files_matched_to_annotation\t1" in text
    assert "annotation_match_rate\t50.0%" in text
    assert "total_download_size" in text
    assert "composition:data_type\tSlide Image\t2" in text
    assert "annotation_columns_added\t1" in text
    assert "unmatched_example\tTCGA-B-2-01" in text


def test_read_annotation_tsv(tmp_path):
    p = tmp_path / "ann.tsv"
    p.write_text("sample\tHistology\nTCGA-E9-A5FL-01\tIDC\n")
    data, cols = enrich.read_annotation_tsv(p, "sample")
    assert cols == ["Histology"]
    assert data["TCGA-E9-A5FL-01"]["Histology"] == "IDC"


def test_collect_merges_sources(tmp_path, requests_mock):
    from mcdi.manifest import cbioportal

    study = "brca_tcga"
    requests_mock.get(
        f"{cbioportal.DEFAULT_BASE}/studies/{study}/clinical-data",
        json=[{"sampleId": "TCGA-E9-A5FL-01", "clinicalAttributeId": "SUBTYPE", "value": "Basal"}],
    )
    ann = tmp_path / "ann.tsv"
    ann.write_text("sample\tHistology\nTCGA-E9-A5FL-01\tIDC\n")
    data, cols = enrich.collect(
        requests.Session(),
        cbioportal_study=study,
        cbioportal_attrs="SUBTYPE",
        annotation_tsv=str(ann),
        annotation_key_col="sample",
    )
    assert data["TCGA-E9-A5FL-01"] == {"SUBTYPE": "Basal", "Histology": "IDC"}
    assert cols == ["SUBTYPE", "Histology"]


def test_collect_merges_multiple_studies(requests_mock):
    from mcdi.manifest import cbioportal

    base = cbioportal.DEFAULT_BASE

    def make_cb(sample_recs, patient_recs):
        def cb(request, context):
            context.status_code = 200
            kind = (request.qs.get("clinicaldatatype", [""])[0]).lower()
            return json.dumps(sample_recs if kind == "sample" else patient_recs)
        return cb

    # Study A contributes PAM50 SUBTYPE (patient level).
    requests_mock.get(
        f"{base}/studies/studyA/clinical-data",
        text=make_cb(
            [{"sampleId": "TCGA-A-1-01", "patientId": "TCGA-A-1", "clinicalAttributeId": "CANCER_TYPE", "value": "BRCA"}],
            [{"patientId": "TCGA-A-1", "clinicalAttributeId": "SUBTYPE", "value": "BRCA_Basal"}],
        ),
    )
    # Study B contributes ER status (patient level).
    requests_mock.get(
        f"{base}/studies/studyB/clinical-data",
        text=make_cb(
            [{"sampleId": "TCGA-A-1-01", "patientId": "TCGA-A-1", "clinicalAttributeId": "CANCER_TYPE", "value": "BRCA"}],
            [{"patientId": "TCGA-A-1", "clinicalAttributeId": "ER_STATUS_BY_IHC", "value": "Positive"}],
        ),
    )

    data, cols = enrich.collect(requests.Session(), cbioportal_study="studyA, studyB")
    # Both studies' attributes are merged onto the same sample.
    assert data["TCGA-A-1-01"]["SUBTYPE"] == "BRCA_Basal"
    assert data["TCGA-A-1-01"]["ER_STATUS_BY_IHC"] == "Positive"
    assert "SUBTYPE" in cols and "ER_STATUS_BY_IHC" in cols


def test_report_always_has_version_stamp(tmp_path):
    out = tmp_path / "r.tsv"
    io.write_report(out, database_total=0)
    assert "mcdi_version" in out.read_text()


def test_version_string_includes_build(monkeypatch):
    import mcdi

    monkeypatch.setattr(mcdi, "BUILD", "deadbee")
    assert mcdi.version_string() == f"{mcdi.__version__}+deadbee"

    monkeypatch.setattr(mcdi, "BUILD", "")
    assert mcdi.version_string() == mcdi.__version__
