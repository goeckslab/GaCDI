"""Offline tests for the PDC (CRDC) builder — DRS §4.1 manifest + harmonization."""

import csv
import json
import re

import pytest

from gacdi_manifest.cli import main
from gacdi_manifest.io import SOURCE_MANIFEST_COLUMNS
from gacdi_manifest.sources.pdc import PDC_GRAPHQL

_STUDIES = [
    {"pdc_study_id": "PDC000714", "submitter_id_name": "Study A",
     "disease_type": "Colon Adenocarcinoma", "primary_site": "Colon",
     "analytical_fraction": "Ubiquitylome", "experiment_type": "Ubiquitylome"},
    {"pdc_study_id": "PDC000999", "submitter_id_name": "Study B",
     "disease_type": "Glioblastoma", "primary_site": "Brain",
     "analytical_fraction": "Proteome", "experiment_type": "Proteome"},
]
_FILES = {
    "PDC000714": [
        {"file_id": "f1", "file_name": "a.raw", "file_type": "Proprietary",
         "md5sum": "m1", "file_size": "100", "data_category": "Raw Mass Spectra"},
        {"file_id": "f2", "file_name": "b.txt", "file_type": "Text",
         "md5sum": "m2", "file_size": "200", "data_category": "Processed Mass Spectra"},
    ],
    "PDC000999": [
        {"file_id": "f9", "file_name": "c.raw", "file_type": "Proprietary",
         "md5sum": "m9", "file_size": "300", "data_category": "Raw Mass Spectra"},
    ],
}


@pytest.fixture
def pdc_api(requests_mock):
    def callback(request, context):
        q = request.json()["query"]
        context.status_code = 200
        if "getPaginatedUIStudy" in q:
            return json.dumps({"data": {"getPaginatedUIStudy": {
                "total": len(_STUDIES), "uiStudies": _STUDIES}}})
        m = re.search(r'pdc_study_id:"([^"]+)"', q)
        return json.dumps({"data": {"filesPerStudy": _FILES.get(m.group(1), [])}})

    requests_mock.post(PDC_GRAPHQL, text=callback)
    return requests_mock


def _args(tmp_path, *extra):
    return ["pdc", "--manifest-out", str(tmp_path / "m.txt"),
            "--metadata-out", str(tmp_path / "md.tsv"),
            "--report-out", str(tmp_path / "r.tsv"), *extra]


def test_pdc_requires_a_filter(tmp_path):
    assert main(_args(tmp_path)) == 2  # no study id / facet -> InputError


def test_pdc_drs_manifest(tmp_path, pdc_api):
    assert main(_args(tmp_path, "--pdc-study-id", "PDC000714")) == 0
    with open(tmp_path / "m.txt", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        assert reader.fieldnames == SOURCE_MANIFEST_COLUMNS
        rows = {r["file_id"]: r for r in reader}
    assert set(rows) == {"f1", "f2"}
    assert rows["f1"]["source"] == "pdc"
    assert rows["f1"]["drs_uri"] == "drs://dg.4DFC:f1"
    assert rows["f1"]["download_method"] == "drs"
    assert rows["f1"]["checksum"] == "m1" and rows["f1"]["checksum_type"] == "md5"
    assert rows["f1"]["access"] == "open"


def test_pdc_metadata_harmonized_and_passthrough(tmp_path, pdc_api):
    assert main(_args(tmp_path, "--pdc-study-id", "PDC000714")) == 0
    with open(tmp_path / "md.tsv", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        header = reader.fieldnames
        rows = {r["file_id"]: r for r in reader}
    # harmonized core populated from PDC study-level fields
    assert rows["f1"]["disease_type"] == "Colon Adenocarcinoma"
    assert rows["f1"]["primary_site"] == "Colon"
    assert rows["f1"]["project"] == "PDC000714"
    # native passthrough preserved under pdc__ prefix
    assert "pdc__analytical_fraction" in header
    assert rows["f1"]["pdc__analytical_fraction"] == "Ubiquitylome"


def test_pdc_disease_filter_selects_matching_study(tmp_path, pdc_api):
    assert main(_args(tmp_path, "--disease-type", "Glioblastoma")) == 0
    ids = {r["file_id"] for r in csv.DictReader(open(tmp_path / "m.txt"), delimiter="\t")}
    assert ids == {"f9"}  # only PDC000999 matched


def test_pdc_data_category_filter(tmp_path, pdc_api):
    assert main(_args(tmp_path, "--pdc-study-id", "PDC000714",
                      "--data-category", "Raw Mass Spectra")) == 0
    ids = {r["file_id"] for r in csv.DictReader(open(tmp_path / "m.txt"), delimiter="\t")}
    assert ids == {"f1"}  # b.txt is Processed Mass Spectra -> filtered out


def test_pdc_count_only(tmp_path, pdc_api):
    assert main(_args(tmp_path, "--pdc-study-id", "PDC000714", "--count-only")) == 0
    report = (tmp_path / "r.tsv").read_text()
    assert "files_matching_filters\t2" in report
    # count-only still emits a §4.1 (header-only) manifest
    assert open(tmp_path / "m.txt").readline().strip() == "\t".join(SOURCE_MANIFEST_COLUMNS)
