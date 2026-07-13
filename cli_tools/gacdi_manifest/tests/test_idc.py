"""Offline tests for the IDC (imaging) builder — series-level GCS §4.1 manifest."""

import csv
import json

import pytest

from gacdi_manifest.cli import main
from gacdi_manifest.io import SOURCE_MANIFEST_COLUMNS
from gacdi_manifest.sources.idc import IDC_API

# Two pages of instance rows spanning two series (s-aaa has 2 instances, s-bbb has 1).
_PAGE0 = [
    {"collection_id": "4d_lung", "PatientID": "P1", "StudyInstanceUID": "st1",
     "SeriesInstanceUID": "1.2.3", "crdc_series_uuid": "s-aaa"},
    {"collection_id": "4d_lung", "PatientID": "P1", "StudyInstanceUID": "st1",
     "SeriesInstanceUID": "1.2.3", "crdc_series_uuid": "s-aaa"},
]
_PAGE1 = [
    {"collection_id": "4d_lung", "PatientID": "P2", "StudyInstanceUID": "st2",
     "SeriesInstanceUID": "4.5.6", "crdc_series_uuid": "s-bbb"},
]


@pytest.fixture
def idc_api(requests_mock):
    def callback(request, context):
        context.status_code = 200
        token = request.qs.get("next_page", [None])[0]
        if request.qs.get("page_size", ["0"])[0] == "1":  # cheap count probe
            return json.dumps({"manifest": {"totalFound": 3, "manifest_data": []}})
        if not token:
            return json.dumps({"manifest": {"totalFound": 3, "manifest_data": _PAGE0},
                               "next_page": "TOKEN2"})
        return json.dumps({"manifest": {"totalFound": 3, "manifest_data": _PAGE1}})

    requests_mock.post(IDC_API + "/cohorts/manifest/preview", text=callback)
    return requests_mock


def _args(tmp_path, *extra):
    return ["idc", "--manifest-out", str(tmp_path / "m.txt"),
            "--metadata-out", str(tmp_path / "md.tsv"),
            "--report-out", str(tmp_path / "r.tsv"), *extra]


def test_idc_requires_a_filter(tmp_path):
    assert main(_args(tmp_path)) == 2


def test_idc_series_gcs_manifest(tmp_path, idc_api):
    assert main(_args(tmp_path, "--collection-id", "4d_lung")) == 0
    with open(tmp_path / "m.txt", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        assert reader.fieldnames == SOURCE_MANIFEST_COLUMNS
        rows = {r["file_id"]: r for r in reader}
    # instance rows collapsed to one row per series
    assert set(rows) == {"s-aaa", "s-bbb"}
    assert rows["s-aaa"]["source"] == "idc"
    assert rows["s-aaa"]["download_method"] == "gcs"
    assert rows["s-aaa"]["access_url"] == "gs://idc-open-data/s-aaa/"
    assert rows["s-aaa"]["file_format"] == "DICOM"
    assert rows["s-aaa"]["case_id"] == "P1"


def test_idc_metadata_harmonized_and_passthrough(tmp_path, idc_api):
    assert main(_args(tmp_path, "--collection-id", "4d_lung")) == 0
    with open(tmp_path / "md.tsv", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        header = reader.fieldnames
        rows = {r["file_id"]: r for r in reader}
    assert rows["s-aaa"]["project"] == "4d_lung"   # harmonized from collection_id
    assert rows["s-aaa"]["case_id"] == "P1"
    assert "idc__SeriesInstanceUID" in header       # native passthrough


def test_idc_max_files_caps_series(tmp_path, idc_api):
    assert main(_args(tmp_path, "--collection-id", "4d_lung", "--max-files", "1")) == 0
    ids = {r["file_id"] for r in csv.DictReader(open(tmp_path / "m.txt"), delimiter="\t")}
    assert ids == {"s-aaa"}


def test_idc_count_only_uses_instance_total(tmp_path, idc_api):
    assert main(_args(tmp_path, "--collection-id", "4d_lung", "--count-only")) == 0
    assert "files_matching_filters\t3" in (tmp_path / "r.tsv").read_text()
