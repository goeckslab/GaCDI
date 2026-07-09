import json

import pytest

from gacdi_manifest.gdc import FILES_ENDPOINT

SAMPLE_TSV = (
    "file_id\tfile_name\tmd5sum\tfile_size\tstate\tdata_format\t"
    "cases.0.submitter_id\tcases.0.samples.0.submitter_id\t"
    "cases.0.samples.0.sample_type\tcases.0.project.project_id\n"
    "uuid1\tA.svs\tmd5a\t100\treleased\tSVS\tTCGA-E9-A5FL\tTCGA-E9-A5FL-01A\tPrimary Tumor\tTCGA-BRCA\n"
    "uuid2\tB.svs\tmd5b\t200\treleased\tSVS\tTCGA-XX-YYYY\tTCGA-XX-YYYY-01A\tPrimary Tumor\tTCGA-BRCA\n"
)


@pytest.fixture
def gdc_api(requests_mock):
    """Register the GDC files endpoint with count / facets / TSV behaviour."""

    def callback(request, context):
        body = request.json()
        context.status_code = 200
        if body.get("facets"):
            return json.dumps(
                {"data": {"aggregations": {"data_type": {"buckets": [{"key": "Slide Image", "doc_count": 2}]}}}}
            )
        if body.get("size") == 0:
            return json.dumps({"data": {"pagination": {"total": 2}}})
        return SAMPLE_TSV

    requests_mock.post(FILES_ENDPOINT, text=callback)
    return requests_mock
