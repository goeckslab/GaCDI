import pytest

from gacdi_manifest.errors import InputError
from gacdi_manifest.postfilter import apply_metadata_filters, parse_metadata_filter

ROWS = [
    {"file_id": "u1", "sample_type": "Primary Tumor", "ER_STATUS": "Positive", "matched": "yes"},
    {"file_id": "u2", "sample_type": "Solid Tissue Normal", "ER_STATUS": "", "matched": "no"},
    {"file_id": "u3", "sample_type": "Primary Tumor", "ER_STATUS": "Negative", "matched": "yes"},
]


def test_parse_defaults_to_present():
    f = parse_metadata_filter("column=ER_STATUS")
    assert f == {"column": "ER_STATUS", "op": "present", "values": []}


def test_parse_field_alias_and_values():
    f = parse_metadata_filter("field=sample_type;op=in;values=Primary Tumor, Metastatic")
    assert f["column"] == "sample_type"
    assert f["op"] == "in"
    assert f["values"] == ["Primary Tumor", "Metastatic"]


def test_parse_rejects_missing_column_and_bad_op_and_missing_values():
    with pytest.raises(InputError):
        parse_metadata_filter("op=present")
    with pytest.raises(InputError):
        parse_metadata_filter("column=x;op=wat")
    with pytest.raises(InputError):
        parse_metadata_filter("column=x;op=in")  # value op needs values


def test_present_keeps_only_non_blank():
    kept = apply_metadata_filters(ROWS, ["column=ER_STATUS;op=present"])
    assert [r["file_id"] for r in kept] == ["u1", "u3"]


def test_blank_keeps_only_empty():
    kept = apply_metadata_filters(ROWS, ["column=ER_STATUS;op=blank"])
    assert [r["file_id"] for r in kept] == ["u2"]


def test_in_and_exclude():
    keep_in = apply_metadata_filters(ROWS, ["column=sample_type;op=in;values=Primary Tumor"])
    assert [r["file_id"] for r in keep_in] == ["u1", "u3"]
    keep_ex = apply_metadata_filters(ROWS, ["column=sample_type;op=exclude;values=Solid Tissue Normal"])
    assert [r["file_id"] for r in keep_ex] == ["u1", "u3"]


def test_contains_is_case_insensitive():
    kept = apply_metadata_filters(ROWS, ["column=ER_STATUS;op=contains;values=posit"])
    assert [r["file_id"] for r in kept] == ["u1"]


def test_multiple_filters_are_anded():
    kept = apply_metadata_filters(
        ROWS,
        ["column=sample_type;op=in;values=Primary Tumor", "column=ER_STATUS;op=contains;values=neg"],
    )
    assert [r["file_id"] for r in kept] == ["u3"]


def test_unknown_column_raises_when_columns_known():
    with pytest.raises(InputError):
        apply_metadata_filters(ROWS, ["column=NOPE;op=present"], columns=["file_id", "sample_type"])


def test_empty_specs_returns_copy():
    out = apply_metadata_filters(ROWS, [])
    assert out == ROWS and out is not ROWS
