"""Shared fixtures for the cross-tool integration suite.

This suite installs both distributions together and exercises the builder ->
downloader selection-bundle handoff. It mocks the GDC files endpoint so the
builder half runs fully offline.
"""

from __future__ import annotations

import json

import pytest

from gacdi_manifest.gdc import FILES_ENDPOINT

SAMPLE_TSV = (
    "file_id\tfile_name\tmd5sum\tfile_size\tstate\tdata_format\taccess\t"
    "cases.0.case_id\tcases.0.submitter_id\t"
    "cases.0.samples.0.sample_id\tcases.0.samples.0.submitter_id\t"
    "cases.0.samples.0.sample_type\tcases.0.project.project_id\t"
    "cases.0.demographic.sex_at_birth\tcases.0.diagnoses.0.age_at_diagnosis\t"
    "cases.0.diagnoses.0.ajcc_pathologic_stage\n"
    "uuid1\tA.svs\tmd5a00000000000000000000000000000\t100\treleased\tSVS\topen\t"
    "case-uuid-1\tTCGA-E9-A5FL\t"
    "sample-uuid-1\tTCGA-E9-A5FL-01A\tPrimary Tumor\tTCGA-BRCA\tfemale\t21915\tStage IIA\n"
    "uuid2\tB.svs\tmd5b00000000000000000000000000000\t200\treleased\tSVS\topen\t"
    "case-uuid-2\tTCGA-XX-YYYY\t"
    "sample-uuid-2\tTCGA-XX-YYYY-01A\tPrimary Tumor\tTCGA-BRCA\tmale\t25000\tStage IIIB\n"
)


@pytest.fixture
def gdc_api(requests_mock):
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
