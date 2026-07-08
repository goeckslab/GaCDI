from gacdi.history import safe_filename, unique_path, write_summary
from gacdi.model import DownloadResult, FileEntry, RunSummary


def test_safe_filename():
    assert safe_filename("a b/c*.txt") == "a_b_c_.txt"
    assert safe_filename("   ") == "dataset"


def test_unique_path(tmp_path):
    p1 = unique_path(tmp_path, "x.txt")
    p1.write_text("1")
    p2 = unique_path(tmp_path, "x.txt")
    assert p1.name == "x.txt"
    assert p2.name == "x_1.txt"


def test_write_summary_rows(tmp_path):
    entry = FileEntry(file_id="ID1", filename="a.bam", md5="deadbeef", size=10, source="gdc")
    res = DownloadResult(entry, "ok", paths=[str(tmp_path / "a.bam")], bytes=10)
    summary = RunSummary("gdc", [res])
    out = tmp_path / "s.tsv"
    write_summary(out, summary)
    text = out.read_text().splitlines()
    assert text[0].split("\t")[0] == "database"
    assert "a.bam" in text[1]
    assert "ok" in text[1]


def test_write_summary_entry_without_paths(tmp_path):
    entry = FileEntry(file_id="ID1", filename="a.bam", source="gdc")
    res = DownloadResult(entry, "planned")
    out = tmp_path / "s.tsv"
    write_summary(out, RunSummary("gdc", [res]))
    assert "planned" in out.read_text()
