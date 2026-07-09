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


def test_cbioportal_fetch(requests_mock):
    study = "brca_tcga"
    url = f"{cbioportal.DEFAULT_BASE}/studies/{study}/clinical-data"
    requests_mock.get(
        url,
        json=[
            {"sampleId": "TCGA-E9-A5FL-01", "clinicalAttributeId": "SUBTYPE", "value": "Basal"},
            {"sampleId": "TCGA-E9-A5FL-01", "clinicalAttributeId": "ER_STATUS_BY_IHC", "value": "Negative"},
        ],
    )
    data, cols = cbioportal.fetch_sample_clinical(
        requests.Session(), study, attribute_ids=["SUBTYPE", "ER_STATUS_BY_IHC"]
    )
    assert data["TCGA-E9-A5FL-01"]["SUBTYPE"] == "Basal"
    assert cols == ["SUBTYPE", "ER_STATUS_BY_IHC"]


def test_cbioportal_list_attributes(requests_mock):
    study = "brca_tcga"
    url = f"{cbioportal.DEFAULT_BASE}/studies/{study}/clinical-attributes"
    requests_mock.get(url, json=[{"clinicalAttributeId": "SUBTYPE", "displayName": "Subtype"}])
    attrs = cbioportal.list_attributes(requests.Session(), study)
    assert attrs[0]["clinicalAttributeId"] == "SUBTYPE"
