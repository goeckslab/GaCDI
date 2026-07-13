import pytest
import requests

from gacdi.base import RunConfig
from gacdi.errors import InputError
from gacdi.importers.cda import CDAImporter, row_to_entry
from gacdi.model import FileEntry


def test_row_to_entry_maps_fields():
    row = {
        "file_id": "F1",
        "label": "a.bam",
        "byte_size": 100,
        "checksum": "md5x",
        "drs_uri": "drs://commons/F1",
        "data_source": ["GDC"],
    }
    e = row_to_entry(row)
    assert (e.file_id, e.filename, e.size, e.md5) == ("F1", "a.bam", 100, "md5x")
    assert e.url is None  # drs:// is not directly downloadable
    assert e.source == "GDC"


def test_row_to_entry_https_drs_becomes_url():
    e = row_to_entry({"file_id": "F", "drs_uri": "https://host/f"})
    assert e.url == "https://host/f"


def test_resolve_maps_rows(monkeypatch, tmp_path):
    q = tmp_path / "q.json"
    q.write_text('{"table": "file", "match_all": ["x"]}')
    monkeypatch.setattr(
        "gacdi.importers.cda._fetch_rows",
        lambda **kw: [
            {"file_id": "F1", "data_source": "GDC"},
            {"file_id": "F2", "data_source": "IDC"},
        ],
    )
    entries = CDAImporter().resolve(RunConfig(input_mode="query", query_json=str(q)), None)
    assert [e.file_id for e in entries] == ["F1", "F2"]


def test_resolve_empty_raises(monkeypatch, tmp_path):
    q = tmp_path / "q.json"
    q.write_text("{}")
    monkeypatch.setattr("gacdi.importers.cda._fetch_rows", lambda **kw: [])
    with pytest.raises(InputError):
        CDAImporter().resolve(RunConfig(input_mode="query", query_json=str(q)), None)


def test_download_skips_without_url(tmp_path):
    entry = FileEntry(
        file_id="F1", filename="a.bam", source="GDC", extra={"commons": "GDC", "drs_uri": "drs://x"}
    )
    res = CDAImporter().download(entry, str(tmp_path), RunConfig(), None)
    assert res.status == "skipped"
    assert "GDC" in res.message
    assert "F1" in res.message


def test_download_direct_url(tmp_path, requests_mock):
    requests_mock.get("https://host/f", content=b"payload")
    entry = FileEntry(file_id="F", filename="f.bam", url="https://host/f", source="GDC")
    res = CDAImporter(session=requests.Session()).download(entry, str(tmp_path), RunConfig(), None)
    assert res.status == "ok"
    assert (tmp_path / "f.bam").read_bytes() == b"payload"
