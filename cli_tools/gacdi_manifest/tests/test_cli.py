from gacdi_manifest.cli import main


def _args(tmp_path, *extra):
    return [
        "gdc", "--project", "TCGA-BRCA", "--data-type", "Slide Image",
        "--manifest-out", str(tmp_path / "m.txt"),
        "--metadata-out", str(tmp_path / "md.tsv"),
        "--report-out", str(tmp_path / "r.tsv"),
        *extra,
    ]


def test_bad_cbioportal_study_fails_fast(tmp_path):
    # A flag-in-value or spaces inside an id is rejected before any GDC query.
    rc = main(_args(tmp_path, "--cbioportal-study", "cbioportal-study brca_tcga"))
    assert rc == 2


def test_count_only(tmp_path, gdc_api):
    rc = main(_args(tmp_path, "--count-only"))
    assert rc == 0
    assert "files_matching_filters\t2" in (tmp_path / "r.tsv").read_text()
    # manifest is header-only in preview mode
    assert (tmp_path / "m.txt").read_text().strip() == "id\tfilename\tmd5\tsize\tstate"


def test_full_build_with_annotation(tmp_path, gdc_api):
    ann = tmp_path / "ann.tsv"
    ann.write_text("sample\tHistology\nTCGA-E9-A5FL-01\tIDC\n")
    rc = main(_args(tmp_path, "--annotation-tsv", str(ann), "--annotation-key-col", "sample"))
    assert rc == 0

    manifest = (tmp_path / "m.txt").read_text().splitlines()
    assert manifest[0] == "id\tfilename\tmd5\tsize\tstate"
    assert "uuid1\tA.svs\tmd5a\t100\treleased" in manifest

    metadata = (tmp_path / "md.tsv").read_text()
    header = metadata.splitlines()[0]
    assert "Histology" in header
    assert "galaxy_ext" in header  # workflow datatype hint present
    assert "\tsvs\t" in metadata  # A.svs -> svs datatype
    assert "IDC" in metadata  # uuid1 matched by barcode

    report = (tmp_path / "r.tsv").read_text()
    assert "files_matched_to_annotation\t1" in report
    assert "total_download_size" in report
    assert "unmatched_example\tTCGA-XX-YYYY-01A" in report


def test_metadata_filter_trims_manifest_and_metadata(tmp_path, gdc_api):
    # Post-query filter on a generated column: keep only the female sample (uuid1).
    rc = main(_args(tmp_path, "--metadata-filter", "column=gender;op=in;values=female"))
    assert rc == 0

    manifest = (tmp_path / "m.txt").read_text()
    assert "uuid1" in manifest and "uuid2" not in manifest

    metadata = (tmp_path / "md.tsv").read_text()
    assert "uuid1" in metadata and "uuid2" not in metadata

    report = (tmp_path / "r.tsv").read_text()
    assert "metadata_filter\trows_kept\t1 of 2" in report


def test_metadata_filter_unknown_column_fails(tmp_path, gdc_api):
    rc = main(_args(tmp_path, "--metadata-filter", "column=NoSuchColumn;op=present"))
    assert rc == 2


def test_native_passthrough_columns_present(tmp_path, gdc_api):
    # Every native GDC field is preserved as a gdc__ prefixed column (§4.1).
    rc = main(_args(tmp_path))
    assert rc == 0
    with open(tmp_path / "md.tsv", newline="") as fh:
        header = next(__import__("csv").reader(fh, delimiter="\t"))
    assert any(c.startswith("gdc__") for c in header)
    assert "gdc__cases.0.demographic.sex_at_birth" in header


def test_metadata_filter_on_passthrough_column(tmp_path, gdc_api):
    # The post-query filter can target a native passthrough column.
    rc = main(_args(tmp_path, "--metadata-filter",
                    "column=gdc__cases.0.demographic.sex_at_birth;op=in;values=female"))
    assert rc == 0
    manifest = (tmp_path / "m.txt").read_text()
    assert "uuid1" in manifest and "uuid2" not in manifest


def test_metadata_carries_gdc_native_clinical(tmp_path, gdc_api):
    # Clinical columns come from GDC itself — no cBioPortal study supplied.
    import csv

    rc = main(_args(tmp_path))
    assert rc == 0
    with open(tmp_path / "md.tsv", newline="") as fh:
        rows = {r["file_id"]: r for r in csv.DictReader(fh, delimiter="\t")}

    r1 = rows["uuid1"]
    assert r1["case_id"] == "case-uuid-1" and r1["sample_id"] == "sample-uuid-1"
    assert r1["gender"] == "female"
    assert r1["age_at_diagnosis"] == "21915"
    assert r1["stage"] == "Stage IIA"
    assert rows["uuid2"]["gender"] == "male" and rows["uuid2"]["stage"] == "Stage IIIB"


def test_no_matches_writes_note(tmp_path, requests_mock):
    import json

    from gacdi_manifest.gdc import FILES_ENDPOINT

    def callback(request, context):
        context.status_code = 200
        if request.json().get("facets"):
            return json.dumps({"data": {"aggregations": {}}})
        return json.dumps({"data": {"pagination": {"total": 0}}})

    requests_mock.post(FILES_ENDPOINT, text=callback)
    rc = main(_args(tmp_path))
    assert rc == 0
    report = (tmp_path / "r.tsv").read_text()
    assert "files_matching_filters\t0" in report
    assert "no_files_matched" in report
    # manifest is header-only, metadata too
    assert (tmp_path / "m.txt").read_text().strip() == "id\tfilename\tmd5\tsize\tstate"


def test_report_carries_provenance(tmp_path, gdc_api):
    rc = main(_args(tmp_path))
    assert rc == 0
    report = (tmp_path / "r.tsv").read_text()
    assert "provenance\tsource\tgdc" in report
    assert "provenance\tendpoint\t" in report
    assert "provenance\tquery_filters\t" in report
    assert "provenance\tgenerated_utc\t" in report


def test_file_id_list_flag(tmp_path, gdc_api):
    id_file = tmp_path / "ids.txt"
    id_file.write_text("# my cohort\nuuid1\nuuid2\n")
    rc = main([
        "gdc", "--file-id-list", str(id_file),
        "--manifest-out", str(tmp_path / "m.txt"),
        "--metadata-out", str(tmp_path / "md.tsv"),
        "--report-out", str(tmp_path / "r.tsv"),
    ])
    assert rc == 0
    # The posted filter must carry the two ids (comment/blank lines skipped).
    file_id_clause = [
        c for req in gdc_api.request_history
        for c in req.json().get("filters", {}).get("content", [])
        if c.get("content", {}).get("field") == "file_id"
    ]
    assert file_id_clause and file_id_clause[0]["content"]["value"] == ["uuid1", "uuid2"]


def test_no_filters_exit_code(tmp_path):
    rc = main(["gdc", "--manifest-out", str(tmp_path / "m.txt"),
               "--metadata-out", str(tmp_path / "md.tsv"),
               "--report-out", str(tmp_path / "r.tsv")])
    assert rc == 2
