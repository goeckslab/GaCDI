import pytest

from gacdi.errors import InputError
from gacdi.manifest import load_query, parse_accessions, parse_gdc_manifest


def test_parse_gdc_manifest(tmp_path):
    m = tmp_path / "manifest.txt"
    m.write_text(
        "id\tfilename\tmd5\tsize\tstate\n"
        "ID1\ta.bam\tdeadbeef\t1024\treleased\n"
        "ID2\tb.vcf.gz\tcafebabe\t2048\treleased\n"
    )
    entries = parse_gdc_manifest(m)
    assert [e.file_id for e in entries] == ["ID1", "ID2"]
    assert entries[0].filename == "a.bam"
    assert entries[0].md5 == "deadbeef"
    assert entries[0].size == 1024
    assert entries[0].source == "gdc"


def test_parse_gdc_manifest_missing_columns(tmp_path):
    m = tmp_path / "bad.txt"
    m.write_text("id\tname\nID1\ta.bam\n")
    with pytest.raises(InputError):
        parse_gdc_manifest(m)


def test_parse_gdc_manifest_missing_file(tmp_path):
    with pytest.raises(InputError):
        parse_gdc_manifest(tmp_path / "nope.txt")


def test_parse_accessions_separators():
    entries = parse_accessions("GSE1, GSE2\nGSE3 GSE2", source="geo")
    # de-duplicated, order preserved
    assert [e.file_id for e in entries] == ["GSE1", "GSE2", "GSE3"]
    assert all(e.source == "geo" for e in entries)


def test_parse_accessions_empty():
    with pytest.raises(InputError):
        parse_accessions("   ")


def test_load_query(tmp_path):
    q = tmp_path / "q.json"
    q.write_text('{"filters": {"op": "in"}, "size": 5}')
    data = load_query(q)
    assert data["size"] == 5


def test_load_query_bad_json(tmp_path):
    q = tmp_path / "q.json"
    q.write_text("{not json")
    with pytest.raises(InputError):
        load_query(q)
