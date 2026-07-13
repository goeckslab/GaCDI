"""Phase 5: isolated tests for the IDC cohort client, plus source mapping tests
that inject a fake client (no HTTP)."""

from __future__ import annotations

import json

import pytest

from gacdi_manifest.clients.idc import IDC_API, IDCCohortClient
from gacdi_manifest.errors import ApiError
from gacdi_manifest.model import FileRow
from gacdi_manifest.net import build_session
from gacdi_manifest.sources.idc import IDC_GCS_BUCKET, IDCManifestSource

PREVIEW = IDC_API + "/cohorts/manifest/preview"


# --- client (HTTP, requests_mock) -------------------------------------------
def test_client_total_found(requests_mock):
    requests_mock.post(PREVIEW, json={"manifest": {"totalFound": 42}})
    assert IDCCohortClient().total_found(build_session(), {"collection_id": ["x"]}) == 42


def test_client_iter_instances_follows_next_page(requests_mock):
    responses = [
        {"json": {"manifest": {"manifest_data": [{"crdc_series_uuid": "a"}]}, "next_page": "tok"}},
        {"json": {"manifest": {"manifest_data": [{"crdc_series_uuid": "b"}]}, "next_page": None}},
    ]
    requests_mock.post(PREVIEW, responses)
    rows = list(IDCCohortClient().iter_instances(build_session(), {"collection_id": ["x"]}))
    assert [r["crdc_series_uuid"] for r in rows] == ["a", "b"]


def test_client_http_error_becomes_api_error(requests_mock):
    requests_mock.post(PREVIEW, status_code=503, text="down")
    with pytest.raises(ApiError):
        IDCCohortClient().total_found(build_session(), {})


# --- source mapping with a fake client (no HTTP) ----------------------------
class _FakeClient:
    endpoint = "https://fake.invalid/v2"

    def __init__(self, instances):
        self._instances = instances

    def total_found(self, session, filters):
        return len(self._instances)

    def iter_instances(self, session, filters, *, page_size=5000):
        yield from self._instances


def test_source_dedups_series_and_builds_gcs_manifest():
    instances = [
        {"crdc_series_uuid": "u1", "SeriesInstanceUID": "S1", "collection_id": "c", "PatientID": "P1"},
        {"crdc_series_uuid": "u1", "SeriesInstanceUID": "S1", "collection_id": "c", "PatientID": "P1"},
        {"crdc_series_uuid": "u2", "SeriesInstanceUID": "S2", "collection_id": "c", "PatientID": "P2"},
    ]
    source = IDCManifestSource(client=_FakeClient(instances))
    rows = source.fetch(session=None, query={"filters": {"collection_id": ["c"]}})
    assert [r.file_id for r in rows] == ["u1", "u2"]  # deduped
    assert all(isinstance(r, FileRow) for r in rows)
    manifest = source.to_manifest_rows(rows)
    assert manifest[0].access_url == f"{IDC_GCS_BUCKET}u1/"
    assert manifest[0].download_method == "gcs"


def test_source_respects_max_files():
    instances = [{"crdc_series_uuid": f"u{i}", "SeriesInstanceUID": f"S{i}"} for i in range(5)]
    source = IDCManifestSource(client=_FakeClient(instances))
    rows = source.fetch(session=None, query={"filters": {}}, max_files=2)
    assert len(rows) == 2


def test_source_provenance_reports_client_endpoint():
    source = IDCManifestSource(client=_FakeClient([]))
    prov = source.provenance({"filters": {}})
    assert prov["endpoint"] == "https://fake.invalid/v2"
    assert prov["source"] == "idc"
