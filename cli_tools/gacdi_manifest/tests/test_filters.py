import pytest

from gacdi_manifest.errors import InputError
from gacdi_manifest.filters import build_filters, parse_extra_filter


def test_guided_filters_structure():
    f = build_filters(project="TCGA-BRCA", data_type="Slide Image")
    assert f["op"] == "and"
    fields = {c["content"]["field"]: c["content"]["value"] for c in f["content"]}
    assert fields["cases.project.project_id"] == ["TCGA-BRCA"]
    assert fields["data_type"] == ["Slide Image"]


def test_multi_value_split():
    f = build_filters(project="TCGA-BRCA, TCGA-LUAD")
    assert f["content"][0]["content"]["value"] == ["TCGA-BRCA", "TCGA-LUAD"]


def test_parse_extra_filter():
    clause = parse_extra_filter("field=cases.samples.sample_type;op=exclude;values=Solid Tissue Normal")
    assert clause["op"] == "exclude"
    assert clause["content"]["field"] == "cases.samples.sample_type"
    assert clause["content"]["value"] == ["Solid Tissue Normal"]


def test_extra_filter_invalid():
    with pytest.raises(InputError):
        parse_extra_filter("nonsense")


def test_raw_filters_flattened():
    raw = {"op": "and", "content": [{"op": "in", "content": {"field": "x", "value": ["y"]}}]}
    f = build_filters(project="TCGA-BRCA", raw_filters=raw)
    fields = [c["content"]["field"] for c in f["content"]]
    assert "cases.project.project_id" in fields and "x" in fields


def test_no_filters_raises():
    with pytest.raises(InputError):
        build_filters()


def test_cohort_lists_become_in_clauses():
    f = build_filters(
        file_id_list=["uuid1", "uuid2"],
        case_list=["TCGA-E9-A5FL"],
        sample_list=[],
    )
    fields = {c["content"]["field"]: c["content"]["value"] for c in f["content"]}
    assert fields["file_id"] == ["uuid1", "uuid2"]
    assert fields["cases.submitter_id"] == ["TCGA-E9-A5FL"]
    # An empty list contributes no clause.
    assert "cases.samples.submitter_id" not in fields


def test_cohort_list_alone_is_sufficient():
    # A cohort list is a real selection, so it must not trip the "no filters" guard.
    f = build_filters(file_id_list=["uuid1"])
    assert f["content"][0]["content"]["field"] == "file_id"
