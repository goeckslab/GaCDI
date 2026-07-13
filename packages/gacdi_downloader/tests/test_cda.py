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


class _FakeAdapter:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def fetch_rows(self, **kwargs):
        self.calls.append(kwargs)
        return self._rows


def test_resolve_maps_rows(tmp_path):
    q = tmp_path / "q.json"
    q.write_text('{"table": "file", "match_all": ["x"]}')
    adapter = _FakeAdapter([
        {"file_id": "F1", "data_source": "GDC"},
        {"file_id": "F2", "data_source": "IDC"},
    ])
    entries = CDAImporter(adapter=adapter).resolve(
        RunConfig(input_mode="query", query_json=str(q)), None
    )
    assert [e.file_id for e in entries] == ["F1", "F2"]
    # The source maps the query and routes "table" to the adapter.
    assert adapter.calls[0]["table"] == "file"


def test_resolve_empty_raises(tmp_path):
    q = tmp_path / "q.json"
    q.write_text("{}")
    with pytest.raises(InputError):
        CDAImporter(adapter=_FakeAdapter([])).resolve(
            RunConfig(input_mode="query", query_json=str(q)), None
        )


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
