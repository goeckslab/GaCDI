from pathlib import Path
import hashlib

import pytest
import requests

from gacdi.base import RunConfig
from gacdi.errors import ChecksumError, DownloadError, InputError
from gacdi.importers.gdc import API_FILES_ENDPOINT, GDCImporter
from gacdi.model import FileEntry


def test_resolve_manifest(tmp_path):
    m = tmp_path / "m.txt"
    m.write_text("id\tfilename\tmd5\tsize\tstate\nID1\ta.bam\tx\t10\treleased\n")
    entries = GDCImporter().resolve(
        RunConfig(input_mode="manifest", manifest=str(m), options={"legacy_access": "open"}),
        None,
    )
    assert entries[0].file_id == "ID1"
    assert entries[0].extra["access"] == "open"


def test_resolve_manifest_requires_access_declaration_and_token(tmp_path):
    manifest = tmp_path / "m.txt"
    manifest.write_text("id\tfilename\tmd5\tsize\tstate\nID1\ta.bam\tx\t10\treleased\n")
    with pytest.raises(InputError, match="explicit access declaration"):
        GDCImporter().resolve(RunConfig(input_mode="manifest", manifest=str(manifest)), None)
    cfg = RunConfig(
        input_mode="manifest",
        manifest=str(manifest),
        options={"legacy_access": "controlled"},
    )
    entries = GDCImporter().resolve(cfg, None)
    assert "provide a GDC token" in entries[0].extra["preflight_error"]


def test_resolve_manifest_rejects_path_like_asset_id(tmp_path):
    manifest = tmp_path / "m.txt"
    manifest.write_text(
        "id\tfilename\tmd5\tsize\tstate\n../escape\ta.bam\tx\t10\treleased\n"
    )
    cfg = RunConfig(
        input_mode="manifest",
        manifest=str(manifest),
        options={"legacy_access": "open"},
    )
    with pytest.raises(InputError, match="Unsafe GDC asset id"):
        GDCImporter().resolve(cfg, None)


def test_download_rejects_unsafe_id_before_client_or_cleanup(tmp_path, monkeypatch):
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep")
    called = False

    def fake_require(_):
        nonlocal called
        called = True
        return "gdc-client"

    monkeypatch.setattr("gacdi.importers.gdc.require", fake_require)
    with pytest.raises(InputError, match="Unsafe GDC asset id"):
        GDCImporter().download(
            FileEntry(file_id="..", filename="a.bam"),
            str(tmp_path / "downloads"),
            RunConfig(),
            None,
        )
    assert called is False
    assert sentinel.read_text() == "keep"


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


def test_resolve_query_pages_through_all_files(tmp_path, requests_mock):
    # 250 matching files across pages of 500 -> the importer must return them all,
    # not a capped subset. Serve them in two pages driven by the `from` offset.
    q = tmp_path / "q.json"
    q.write_text('{"filters": {"op": "in"}, "size": 100}')
    total = 250

    def callback(request, context):
        body = request.json()
        start = int(body.get("from", 0))
        size = int(body.get("size"))
        hits = [
            {"file_id": f"ID{i}", "file_name": f"f{i}.bam", "md5sum": "x", "file_size": "1"}
            for i in range(start, min(start + size, total))
        ]
        return {"data": {"hits": hits, "pagination": {"total": total}}}

    requests_mock.post(API_FILES_ENDPOINT, json=callback)
    imp = GDCImporter(session=requests.Session())
    entries = imp.resolve(RunConfig(input_mode="query", query_json=str(q)), None)
    assert len(entries) == total
    assert entries[0].file_id == "ID0" and entries[-1].file_id == f"ID{total - 1}"


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
    res = GDCImporter().download(entry, str(tmp_path), RunConfig(assign_ext="cram"), None)
    assert res.status == "ok"
    assert (tmp_path / "a.bam").exists()
    assert not (tmp_path / "ID1").exists()
    assert res.bytes == len(b"payload")
    assert res.produced[0].galaxy_ext == "cram"


def test_download_no_files_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("gacdi.importers.gdc.require", lambda b: b)
    monkeypatch.setattr("gacdi.importers.gdc.run", lambda cmd, **kw: None)
    with pytest.raises(DownloadError):
        GDCImporter().download(FileEntry(file_id="ID1", filename="a.bam"), str(tmp_path), RunConfig(), None)


def test_bundle_download_rejects_source_size_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("gacdi.importers.gdc.require", lambda _: "gdc-client")

    def fake_run(cmd, **kwargs):
        subdir = tmp_path / "ID1"
        subdir.mkdir()
        (subdir / "a.bam").write_bytes(b"short")

    monkeypatch.setattr("gacdi.importers.gdc.run", fake_run)
    entry = FileEntry(file_id="ID1", filename="a.bam", size=100, source="gdc")
    with pytest.raises(ChecksumError, match="Size mismatch"):
        GDCImporter().download(
            entry,
            str(tmp_path),
            RunConfig(input_mode="bundle"),
            None,
        )
    assert not (tmp_path / "a.bam").exists()


def test_bundle_download_verifies_sha256_source_checksum(tmp_path, monkeypatch):
    payload = b"source bytes"
    monkeypatch.setattr("gacdi.importers.gdc.require", lambda _: "gdc-client")

    def fake_run(cmd, **kwargs):
        subdir = tmp_path / "ID1"
        subdir.mkdir()
        (subdir / "a.dat").write_bytes(payload)

    monkeypatch.setattr("gacdi.importers.gdc.run", fake_run)
    expected = hashlib.sha256(payload).hexdigest()
    entry = FileEntry(
        file_id="ID1",
        filename="a.dat",
        size=len(payload),
        source="gdc",
        extra={
            "source_checksum_type": "sha256",
            "source_checksum": expected,
            "galaxy_ext_hint": "data",
        },
    )
    result = GDCImporter().download(
        entry,
        str(tmp_path),
        RunConfig(input_mode="bundle"),
        None,
    )
    assert result.checksum_verified is True
    assert result.observed_checksum_type == "sha256"
    assert result.observed_checksum == expected
