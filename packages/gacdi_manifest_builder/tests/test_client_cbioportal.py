"""Phase 5: isolated tests for the cBioPortal client, plus enrichment
orchestration tests that inject a fake client (no HTTP)."""

from __future__ import annotations

import pytest

from gacdi_manifest import cbioportal
from gacdi_manifest.clients.cbioportal import DEFAULT_BASE, CBioPortalClient
from gacdi_manifest.errors import ApiError
from gacdi_manifest.net import build_session


# --- client (HTTP, requests_mock) -------------------------------------------
def test_client_list_attributes(requests_mock):
    requests_mock.get(
        f"{DEFAULT_BASE}/studies/brca_tcga/clinical-attributes",
        json=[{"clinicalAttributeId": "SUBTYPE"}],
    )
    attrs = CBioPortalClient().list_attributes(build_session(), "brca_tcga")
    assert attrs[0]["clinicalAttributeId"] == "SUBTYPE"


def test_client_clinical_data_passes_kind(requests_mock):
    m = requests_mock.get(f"{DEFAULT_BASE}/studies/brca_tcga/clinical-data", json=[])
    CBioPortalClient().clinical_data(build_session(), "brca_tcga", "PATIENT")
    assert m.last_request.qs["clinicaldatatype"] == ["patient"]


def test_client_http_error_becomes_api_error(requests_mock):
    requests_mock.get(f"{DEFAULT_BASE}/studies/x/clinical-attributes", status_code=404, text="no")
    with pytest.raises(ApiError):
        CBioPortalClient().list_attributes(build_session(), "x")


# --- orchestration with a fake client (no HTTP) -----------------------------
class _FakeClient:
    def __init__(self, sample, patient):
        self._sample = sample
        self._patient = patient

    def clinical_data(self, session, study_id, kind):
        return self._sample if kind == "SAMPLE" else self._patient


def test_fetch_clinical_merges_patient_values_onto_samples():
    sample = [
        {"sampleId": "TCGA-A-1-01", "patientId": "TCGA-A-1", "clinicalAttributeId": "CANCER_TYPE", "value": "BRCA"},
    ]
    patient = [
        {"patientId": "TCGA-A-1", "clinicalAttributeId": "SUBTYPE", "value": "LumA"},
    ]
    merged, cols = cbioportal.fetch_clinical(
        session=None, study_id="brca_tcga", client=_FakeClient(sample, patient)
    )
    assert merged["TCGA-A-1-01"]["SUBTYPE"] == "LumA"
    assert merged["TCGA-A-1-01"]["CANCER_TYPE"] == "BRCA"
    assert set(cols) == {"CANCER_TYPE", "SUBTYPE"}


def test_fetch_clinical_filters_to_requested_attributes():
    sample = [
        {"sampleId": "S-01", "patientId": "P", "clinicalAttributeId": "CANCER_TYPE", "value": "BRCA"},
    ]
    patient = [{"patientId": "P", "clinicalAttributeId": "SUBTYPE", "value": "LumA"}]
    merged, cols = cbioportal.fetch_clinical(
        session=None, study_id="s", attribute_ids=["SUBTYPE"], client=_FakeClient(sample, patient)
    )
    assert cols == ["SUBTYPE"]
    assert "CANCER_TYPE" not in merged["S-01"]
