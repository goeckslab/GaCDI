import pytest

from mcdi.errors import InputError
from mcdi.manifest.filters import build_filters, parse_extra_filter


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
