from pathlib import Path

import pytest
import requests

from gacdi.base import RunConfig
from gacdi.errors import DownloadError, InputError
from gacdi.importers.gdc import API_FILES_ENDPOINT, GDCImporter
from gacdi.model import FileEntry


def test_resolve_manifest(tmp_path):
    m = tmp_path / "m.txt"
    m.write_text("id\tfilename\tmd5\tsize\tstate\nID1\ta.bam\tx\t10\treleased\n")
    entries = GDCImporter().resolve(RunConfig(input_mode="manifest", manifest=str(m)), None)
    assert entries[0].file_id == "ID1"


def test_resolve_manifest_requires_path():
    with pytest.raises(InputError):
        GDCImporter().resolve(RunConfig(input_mode="manifest"), None)


def test_resolve_query(tmp_path, requests_mock):
    q = tmp_path / "q.json"
    q.write_text('{"filters": {"op": "in"}}')
    requests_mock.post(
        API_FILES_ENDPOINT,
        json={"data": {"hits": [
            {"file_id": "ID1", "file_name": "a.bam", "md5sum": "x", "file_size": "10"},
            {"file_id": "ID2", "file_name": "b.vcf", "md5sum": "y", "file_size": "20"},
        ]}},
    )
    imp = GDCImporter(session=requests.Session())
    entries = imp.resolve(RunConfig(input_mode="query", query_json=str(q)), None)
    assert [e.file_id for e in entries] == ["ID1", "ID2"]
    assert entries[0].size == 10


def test_resolve_query_no_filters(tmp_path):
    q = tmp_path / "q.json"
    q.write_text("{}")
    with pytest.raises(InputError):
        GDCImporter().resolve(RunConfig(input_mode="query", query_json=str(q)), None)


def test_download_flattens_and_cleans(tmp_path, monkeypatch):
    monkeypatch.setattr("gacdi.importers.gdc.require", lambda b: b)

    def fake_run(cmd, **kwargs):
        d = Path(tmp_path) / "ID1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "a.bam").write_bytes(b"payload")

    monkeypatch.setattr("gacdi.importers.gdc.run", fake_run)
    entry = FileEntry(file_id="ID1", filename="a.bam", source="gdc")
    res = GDCImporter().download(entry, str(tmp_path), RunConfig(), None)
    assert res.status == "ok"
    assert (tmp_path / "a.bam").exists()
    assert not (tmp_path / "ID1").exists()
    assert res.bytes == len(b"payload")


def test_download_no_files_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("gacdi.importers.gdc.require", lambda b: b)
    monkeypatch.setattr("gacdi.importers.gdc.run", lambda cmd, **kw: None)
    with pytest.raises(DownloadError):
        GDCImporter().download(FileEntry(file_id="ID1", filename="a.bam"), str(tmp_path), RunConfig(), None)
