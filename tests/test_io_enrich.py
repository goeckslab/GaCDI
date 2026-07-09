import requests

from gacdi_manifest import enrich, io
from gacdi_manifest.join import JoinReport
from gacdi_manifest.model import FileRow


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
    report = JoinReport(total_files=2, matched_files=1, unmatched_files=["uuid2"])
    out = tmp_path / "r.tsv"
    io.write_report(out, matched_total=2, report=report)
    text = out.read_text()
    assert "files_matched_to_annotation\t1" in text
    assert "unmatched_file\tuuid2" in text


def test_read_annotation_tsv(tmp_path):
    p = tmp_path / "ann.tsv"
    p.write_text("sample\tHistology\nTCGA-E9-A5FL-01\tIDC\n")
    data, cols = enrich.read_annotation_tsv(p, "sample")
    assert cols == ["Histology"]
    assert data["TCGA-E9-A5FL-01"]["Histology"] == "IDC"


def test_collect_merges_sources(tmp_path, requests_mock):
    from gacdi_manifest import cbioportal

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
