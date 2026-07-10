import json

import requests

from gacdi_manifest import cbioportal, gdc
from gacdi_manifest.filters import build_filters


def test_count_and_query(gdc_api):
    session = requests.Session()
    filters = build_filters(project="TCGA-BRCA", data_type="Slide Image")
    assert gdc.count(session, filters) == 2
    rows = gdc.query_files(session, filters)
    assert [r.file_id for r in rows] == ["uuid1", "uuid2"]
    assert rows[0].sample_barcode == "TCGA-E9-A5FL-01A"
    assert rows[0].md5 == "md5a" and rows[0].size == "100"


def test_facets(gdc_api):
    session = requests.Session()
    filters = build_filters(project="TCGA-BRCA")
    f = gdc.facets(session, filters, ["data_type"])
    assert f["data_type"]["Slide Image"] == 2


def test_query_is_server_sorted_for_deterministic_capping(gdc_api):
    # --max-files must cap a stable server-side order, not GDC's default order.
    session = requests.Session()
    filters = build_filters(project="TCGA-BRCA", data_type="Slide Image")
    gdc.query_files(session, filters, max_files=1)
    # The paged file request (the one carrying "fields") must request a sort.
    file_requests = [
        r.json() for r in gdc_api.request_history
        if r.json().get("fields")
    ]
    assert file_requests, "expected at least one paged file request"
    assert file_requests[-1]["sort"] == gdc.SORT


def test_cbioportal_merges_patient_and_sample(requests_mock):
    """SUBTYPE/ER are patient-level; they must be merged onto each sample."""
    study = "brca_tcga"
    url = f"{cbioportal.DEFAULT_BASE}/studies/{study}/clinical-data"

    def callback(request, context):
        context.status_code = 200
        kind = (request.qs.get("clinicaldatatype", [""])[0]).lower()
        if kind == "sample":
            return json.dumps([
                {"sampleId": "TCGA-E9-A5FL-01", "patientId": "TCGA-E9-A5FL",
                 "clinicalAttributeId": "CANCER_TYPE", "value": "Breast Cancer"},
            ])
        return json.dumps([
            {"patientId": "TCGA-E9-A5FL", "clinicalAttributeId": "SUBTYPE", "value": "BRCA_Basal"},
            {"patientId": "TCGA-E9-A5FL", "clinicalAttributeId": "ER_STATUS_BY_IHC", "value": "Negative"},
        ])

    requests_mock.get(url, text=callback)
    data, cols = cbioportal.fetch_clinical(requests.Session(), study)
    assert data["TCGA-E9-A5FL-01"]["SUBTYPE"] == "BRCA_Basal"
    assert data["TCGA-E9-A5FL-01"]["ER_STATUS_BY_IHC"] == "Negative"
    assert data["TCGA-E9-A5FL-01"]["CANCER_TYPE"] == "Breast Cancer"
    assert set(cols) == {"CANCER_TYPE", "SUBTYPE", "ER_STATUS_BY_IHC"}


def test_cbioportal_filter_attributes(requests_mock):
    study = "brca_tcga"
    url = f"{cbioportal.DEFAULT_BASE}/studies/{study}/clinical-data"

    def callback(request, context):
        context.status_code = 200
        kind = (request.qs.get("clinicaldatatype", [""])[0]).lower()
        if kind == "patient":
            return json.dumps([
                {"patientId": "TCGA-E9-A5FL", "clinicalAttributeId": "SUBTYPE", "value": "BRCA_Basal"},
                {"patientId": "TCGA-E9-A5FL", "clinicalAttributeId": "AGE", "value": "61"},
            ])
        return json.dumps([
            {"sampleId": "TCGA-E9-A5FL-01", "patientId": "TCGA-E9-A5FL",
             "clinicalAttributeId": "CANCER_TYPE", "value": "Breast Cancer"},
        ])

    requests_mock.get(url, text=callback)
    data, cols = cbioportal.fetch_clinical(requests.Session(), study, attribute_ids=["SUBTYPE"])
    assert cols == ["SUBTYPE"]
    assert data["TCGA-E9-A5FL-01"] == {"SUBTYPE": "BRCA_Basal"}


def test_cbioportal_list_attributes(requests_mock):
    study = "brca_tcga"
    url = f"{cbioportal.DEFAULT_BASE}/studies/{study}/clinical-attributes"
    requests_mock.get(url, json=[{"clinicalAttributeId": "SUBTYPE", "displayName": "Subtype"}])
    attrs = cbioportal.list_attributes(requests.Session(), study)
    assert attrs[0]["clinicalAttributeId"] == "SUBTYPE"
