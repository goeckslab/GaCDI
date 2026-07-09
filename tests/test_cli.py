from gacdi_manifest.cli import main


def _args(tmp_path, *extra):
    return [
        "gdc", "--project", "TCGA-BRCA", "--data-type", "Slide Image",
        "--manifest-out", str(tmp_path / "m.txt"),
        "--metadata-out", str(tmp_path / "md.tsv"),
        "--report-out", str(tmp_path / "r.tsv"),
        *extra,
    ]


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
    assert "unmatched_file\tuuid2" in report


def test_no_filters_exit_code(tmp_path):
    rc = main(["gdc", "--manifest-out", str(tmp_path / "m.txt"),
               "--metadata-out", str(tmp_path / "md.tsv"),
               "--report-out", str(tmp_path / "r.tsv")])
    assert rc == 2
