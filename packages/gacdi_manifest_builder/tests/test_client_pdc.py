"""Phase 5: isolated tests for the PDC GraphQL client, plus source mapping tests
that inject a fake client (no HTTP)."""

from __future__ import annotations

import json

import pytest

from gacdi_manifest.clients.pdc import PDC_GRAPHQL, PDCGraphQLClient
from gacdi_manifest.errors import ApiError
from gacdi_manifest.model import FileRow
from gacdi_manifest.net import build_session
from gacdi_manifest.sources.pdc import DRS_PREFIX, PDCManifestSource


# --- client (HTTP, requests_mock) -------------------------------------------
def test_client_iter_studies_paginates(requests_mock):
    pages = [
        {"data": {"getPaginatedUIStudy": {"total": 2, "uiStudies": [{"pdc_study_id": "PDC1"}]}}},
        {"data": {"getPaginatedUIStudy": {"total": 2, "uiStudies": [{"pdc_study_id": "PDC2"}]}}},
    ]
    requests_mock.post(PDC_GRAPHQL, [{"json": p} for p in pages])
    studies = list(PDCGraphQLClient().iter_studies(build_session(), page_size=1))
    assert [s["pdc_study_id"] for s in studies] == ["PDC1", "PDC2"]


def test_client_files_for_study(requests_mock):
    requests_mock.post(
        PDC_GRAPHQL,
        json={"data": {"filesPerStudy": [{"file_id": "f1", "file_name": "a.raw"}]}},
    )
    files = PDCGraphQLClient().files_for_study(build_session(), "PDC1")
    assert files[0]["file_id"] == "f1"


def test_client_graphql_error_becomes_api_error(requests_mock):
    requests_mock.post(PDC_GRAPHQL, json={"errors": [{"message": "boom"}]})
    with pytest.raises(ApiError):
        PDCGraphQLClient().files_for_study(build_session(), "PDC1")


def test_client_http_error_becomes_api_error(requests_mock):
    requests_mock.post(PDC_GRAPHQL, status_code=500, text="err")
    with pytest.raises(ApiError):
        PDCGraphQLClient().files_for_study(build_session(), "PDC1")


# --- source mapping with a fake client (no HTTP) ----------------------------
class _FakeClient:
    endpoint = "https://fake.invalid/graphql"

    def iter_studies(self, session, *, page_size=100):
        yield {"pdc_study_id": "PDC1", "disease_type": "Colon Adenocarcinoma", "primary_site": "Colon"}

    def files_for_study(self, session, study_id):
        return [
            {"file_id": "f1", "file_name": "a.raw", "file_type": "RAW",
             "md5sum": "abc", "file_size": "10", "data_category": "Raw Mass Spectra"},
        ]


def test_source_maps_files_and_builds_drs_manifest():
    source = PDCManifestSource(client=_FakeClient())
    query = {"study_ids": ["PDC1"], "disease_type": None, "primary_site": None,
             "analytical_fraction": None, "data_category": None}
    rows = source.fetch(session=None, query=query)
    assert all(isinstance(r, FileRow) for r in rows)
    assert rows[0].file_id == "f1"
    manifest = source.to_manifest_rows(rows)
    assert manifest[0].drs_uri == f"{DRS_PREFIX}f1"
    assert manifest[0].download_method == "drs"


def test_source_provenance_reports_client_endpoint():
    source = PDCManifestSource(client=_FakeClient())
    prov = source.provenance({"study_ids": []})
    assert prov["endpoint"] == "https://fake.invalid/graphql"
    assert prov["source"] == "pdc"
