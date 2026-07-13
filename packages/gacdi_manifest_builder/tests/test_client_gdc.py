"""Phase 5: isolated tests for the GDC files transport client, plus source
mapping tests that inject a fake client (no HTTP)."""

from __future__ import annotations

import json

import pytest

from gacdi_manifest.clients.gdc import FILES_ENDPOINT, GDCFilesClient
from gacdi_manifest.errors import ApiError
from gacdi_manifest.model import FileRow
from gacdi_manifest.net import build_session
from gacdi_manifest.sources.gdc import GDCManifestSource

SAMPLE_TSV = (
    "file_id\tfile_name\tmd5sum\tfile_size\tstate\n"
    "uuid1\tA.svs\tmd5a\t100\treleased\n"
    "uuid2\tB.svs\tmd5b\t200\treleased\n"
)


# --- client (HTTP, requests_mock) -------------------------------------------
def test_client_count_parses_total(requests_mock):
    requests_mock.post(FILES_ENDPOINT, json={"data": {"pagination": {"total": 7}}})
    assert GDCFilesClient().count(build_session(), {"op": "and"}) == 7


def test_client_count_translates_bad_payload(requests_mock):
    requests_mock.post(FILES_ENDPOINT, json={"unexpected": True})
    with pytest.raises(ApiError):
        GDCFilesClient().count(build_session(), {})


def test_client_http_error_becomes_api_error(requests_mock):
    requests_mock.post(FILES_ENDPOINT, status_code=502, text="bad gateway")
    with pytest.raises(ApiError):
        GDCFilesClient().count(build_session(), {})


def test_client_fetch_rows_pages_and_respects_max(requests_mock):
    def callback(request, context):
        body = request.json()
        if body.get("size") == 0:
            return json.dumps({"data": {"pagination": {"total": 2}}})
        return SAMPLE_TSV

    requests_mock.post(FILES_ENDPOINT, text=callback)
    rows = GDCFilesClient(page_size=1).fetch_rows(build_session(), {}, total=2)
    assert [r["file_id"] for r in rows] == ["uuid1", "uuid2"]


def test_client_facets(requests_mock):
    requests_mock.post(
        FILES_ENDPOINT,
        json={"data": {"aggregations": {"access": {"buckets": [{"key": "open", "doc_count": 5}]}}}},
    )
    out = GDCFilesClient().facets(build_session(), {}, ["access"])
    assert out == {"access": {"open": 5}}


# --- source mapping with a fake client (no HTTP) ----------------------------
class _FakeClient:
    endpoint = "https://fake.invalid/files"

    def __init__(self, rows):
        self._rows = rows

    def count(self, session, filters):
        return len(self._rows)

    def facets(self, session, filters, fields):
        return {}

    def fetch_rows(self, session, filters, *, max_files=None, total=None):
        return self._rows[:max_files] if max_files else self._rows


def test_source_maps_raw_rows_to_filerows():
    rows = [
        {"file_id": "uuid1", "file_name": "A.svs", "md5sum": "md5a", "file_size": "100", "state": "released"},
        {"file_id": "uuid2", "file_name": "B.svs", "md5sum": "md5b", "file_size": "200", "state": ""},
    ]
    source = GDCManifestSource(client=_FakeClient(rows))
    out = source.fetch(session=None, query={}, total=2)
    assert all(isinstance(r, FileRow) for r in out)
    assert [r.file_id for r in out] == ["uuid1", "uuid2"]
    assert out[0].filename == "A.svs"
    # Empty state defaults to "released".
    assert out[1].state == "released"


def test_source_provenance_reports_client_endpoint():
    source = GDCManifestSource(client=_FakeClient([]))
    prov = source.provenance({"op": "and"})
    assert prov["endpoint"] == "https://fake.invalid/files"
    assert prov["source"] == "gdc"
