"""Phase 5: isolated tests for the downloader GDC transport (files API client and
gdc-client tool adapter), plus source query-mapping with a fake client."""

from __future__ import annotations

import subprocess

import pytest
import requests

from gacdi.base import RunConfig
from gacdi.clients.gdc import API_FILES_ENDPOINT, GDCClientTool, GDCFilesApiClient
from gacdi.errors import DownloadError, InputError
from gacdi.sources.gdc import GDCDownloadSource


# --- files API client (HTTP) ------------------------------------------------
def test_client_iter_hits_pages_to_total(requests_mock):
    responses = [
        {"json": {"data": {"hits": [{"file_id": "A"}], "pagination": {"total": 2}}}},
        {"json": {"data": {"hits": [{"file_id": "B"}], "pagination": {"total": 2}}}},
    ]
    requests_mock.post(API_FILES_ENDPOINT, responses)
    hits = list(
        GDCFilesApiClient().iter_hits(requests.Session(), filters={"x": 1}, page_size=1)
    )
    assert [h["file_id"] for h in hits] == ["A", "B"]


def test_client_http_error_becomes_download_error(requests_mock):
    requests_mock.post(API_FILES_ENDPOINT, status_code=500, text="boom")
    with pytest.raises(DownloadError):
        list(GDCFilesApiClient().iter_hits(requests.Session(), filters={}))


def test_client_respects_custom_endpoint(requests_mock):
    endpoint = "https://fixture.invalid/gdc/files"
    requests_mock.post(endpoint, json={"data": {"hits": [], "pagination": {"total": 0}}})
    assert list(
        GDCFilesApiClient().iter_hits(requests.Session(), filters={}, endpoint=endpoint)
    ) == []


# --- tool adapter -----------------------------------------------------------
def test_tool_translates_process_failure(monkeypatch):
    monkeypatch.setattr("gacdi.clients.gdc.require", lambda b: b)

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr="denied")

    monkeypatch.setattr("gacdi.clients.gdc.run", fake_run)
    with pytest.raises(DownloadError, match="gdc-client failed"):
        GDCClientTool().download("FILE", "/tmp/x", token=None)


def test_tool_passes_token_flag(monkeypatch):
    monkeypatch.setattr("gacdi.clients.gdc.require", lambda b: "gdc-client")
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd

    monkeypatch.setattr("gacdi.clients.gdc.run", fake_run)
    GDCClientTool().download("FILE", "/tmp/x", token="tok")
    assert "-t" in seen["cmd"]


# --- source query mapping with a fake client (no HTTP) ----------------------
class _FakeFilesClient:
    endpoint = API_FILES_ENDPOINT

    def __init__(self, hits):
        self._hits = hits

    def iter_hits(self, session, *, filters, fields=None, page_size=None, endpoint=None):
        yield from self._hits


def test_source_query_maps_hits_to_entries(tmp_path):
    query = tmp_path / "q.json"
    query.write_text('{"filters": {"x": 1}}')
    hits = [
        {"file_id": "A", "file_name": "a.bam", "md5sum": "m", "file_size": "10"},
        {"no_id": True},  # skipped
        {"file_id": "B", "file_size": "notanint"},
    ]
    source = GDCDownloadSource(files_client=_FakeFilesClient(hits))
    entries = source.resolve(RunConfig(input_mode="query", query_json=str(query)), token=None)
    assert [e.file_id for e in entries] == ["A", "B"]
    assert entries[0].filename == "a.bam" and entries[0].size == 10
    assert entries[1].filename == "B" and entries[1].size is None


def test_source_query_no_matches_raises(tmp_path):
    query = tmp_path / "q.json"
    query.write_text('{"filters": {"x": 1}}')
    source = GDCDownloadSource(files_client=_FakeFilesClient([]))
    with pytest.raises(InputError):
        source.resolve(RunConfig(input_mode="query", query_json=str(query)), token=None)
