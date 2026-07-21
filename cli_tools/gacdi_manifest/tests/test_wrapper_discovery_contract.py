"""Compatibility contract with Galaxy's output discovery for the downloader wrapper.

Discovery failures in a Galaxy wrapper are close to invisible: the tool exits 0
with clean stderr, and only the output collection lands in an error state. The
failure also depends on how many files a single rule matches, so a tool test with
one file per datatype passes while a real manifest fails.

These tests encode what ``galaxy.job_execution.output_collect`` requires of the
patterns in ``macros.xml``, so a change that would break collection population
fails here instead of in a user's history. Kept self-contained (Galaxy is not a
dependency of this package) by replicating Galaxy's exact behaviour:

- ``DatasetCollector.sort`` calls ``sorted(matches, key=attrgetter(sort_by))``
- ``JsonCollectedDatasetMatch.name`` / ``.designation`` read the regex group of
  that name, returning ``None`` when the pattern does not capture it
- ``DatasetCollector.match`` applies ``re.match(pattern, filename)``
- element identifiers come from ``.designation`` and must be unique per collection
"""

from __future__ import annotations

import operator
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

MACROS = Path(__file__).resolve().parents[3] / "tools" / "gacdi-downloader" / "macros.xml"

# Datatypes registered by Galaxy's stock datatypes_conf.xml.sample. A wrapper may
# only name extensions Galaxy actually knows; an unregistered one yields elements
# Galaxy cannot resolve.
REGISTERED_EXTENSIONS = {
    "csv",
    "data",
    "mgf",
    "mzid",
    "mzml",
    "mzxml",
    "pepxml",
    "protxml",
    "tabular",
    "thermo.raw",
}

# Galaxy asserts sort_by is one of these (tool_util/parser/output_collection_def.py).
VALID_SORT_KEYS = {"filename", "name", "designation", "dbkey"}


def _discovery_rules():
    """Expand the discover_typed macro the way Galaxy's macro processor would."""
    root = ET.parse(MACROS).getroot()
    templates = {x.get("name"): x for x in root.findall("xml")}
    tokens = {t.get("name"): (t.text or "") for t in root.findall("token")}

    def _resolve(text):
        for name, value in tokens.items():
            text = text.replace(name, value)
        return text

    rules = []
    for node in templates["discover_typed"]:
        if node.tag == "discover_datasets":
            attrib = dict(node.attrib)
        elif node.tag == "expand":
            template = templates[node.get("macro")]
            child = template.find("discover_datasets")
            attrib = {
                key: value.replace("@PATTERN@", node.get("pattern", "")).replace("@EXT@", node.get("ext", ""))
                for key, value in child.attrib.items()
            }
        else:
            continue
        rules.append({key: _resolve(value) for key, value in attrib.items()})
    return rules


class Match:
    """Stand-in for galaxy.model.store.discover.RegexCollectedDatasetMatch."""

    def __init__(self, groupdict):
        self.as_dict = groupdict

    @property
    def name(self):
        return self.as_dict.get("name")

    @property
    def designation(self):
        return self.as_dict.get("designation")

    @property
    def filename(self):
        return self.as_dict.get("designation")

    @property
    def dbkey(self):
        return self.as_dict.get("dbkey")


RULES = _discovery_rules()

# One representative file per rule, plus a second file sharing an extension so
# that at least one collector must sort more than one match.
PDC_MANIFEST_FILES = {
    "05CPTAC_C_GBM_W_PNNL_20210121_B1S5_f16.mzML": "mzml",
    "06CPTAC_C_GBM_W_PNNL_20210830_B2S1_f08.mzML": "mzml",
    "11CPTAC_C_GBM_W_PNNL_20210830_B3S1_f20.mzid": "mzid",
    "12CPTAC_C_GBM_W_PNNL_20210830_B3S2_f01.psm": "tabular",
    "12CPTAC_C_GBM_W_PNNL_20210830_B3S2_f16.raw": "thermo.raw",
}


def _matches_for(rule, filenames):
    return [Match(m.groupdict()) for f in filenames if (m := re.match(rule["pattern"], f))]


def test_rules_were_found():
    assert len(RULES) >= 2


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["ext"])
def test_every_rule_names_a_registered_datatype(rule):
    assert rule["ext"] in REGISTERED_EXTENSIONS


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["ext"])
def test_every_rule_sorts_on_a_group_its_pattern_captures(rule):
    """Galaxy sorts with attrgetter(sort_by); an uncaptured group yields None.

    Sorting two such matches raises TypeError comparing None to None, which the
    user sees only as an errored collection.
    """
    sort_by = rule.get("sort_by", "filename")
    assert sort_by in VALID_SORT_KEYS
    captured = set(re.compile(rule["pattern"]).groupindex)
    assert sort_by in captured, (
        f"rule ext={rule['ext']} sorts on {sort_by!r} but its pattern captures {sorted(captured)}; "
        f"Galaxy would sort on None and raise TypeError once two files match this rule"
    )


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["ext"])
def test_every_rule_sorts_without_error_on_multiple_matches(rule):
    """Reproduces Galaxy's DatasetCollector.sort over duplicated matches."""
    doubled = [f"a_{name}" for name in PDC_MANIFEST_FILES] + [f"b_{name}" for name in PDC_MANIFEST_FILES]
    matches = _matches_for(rule, doubled)
    sorted(matches, key=operator.attrgetter(rule.get("sort_by", "filename")))


@pytest.mark.parametrize(("filename", "expected_ext"), sorted(PDC_MANIFEST_FILES.items()))
def test_each_manifest_file_matches_exactly_one_rule(filename, expected_ext):
    hits = [rule["ext"] for rule in RULES if re.match(rule["pattern"], filename)]
    assert hits == [expected_ext], (
        f"{filename} matched {hits}; a file matching no rule is dropped from the "
        f"collection, and one matching several becomes a duplicate element identifier"
    )


@pytest.mark.parametrize(
    "filename",
    [
        "TCGA-E2-A15K-11A-01-TS1.28656e31-f16f-431e-95d4-915892ecdff8.svs",
        "clinical.bcr.xml.no_such_ext",
        "README",
        "aligned.bam",
    ],
)
def test_unknown_formats_fall_through_to_data_rather_than_being_dropped(filename):
    hits = [rule["ext"] for rule in RULES if re.match(rule["pattern"], filename)]
    assert hits == ["data"]


def test_element_identifiers_are_unique_across_all_rules():
    seen = {}
    for rule in RULES:
        for match in _matches_for(rule, PDC_MANIFEST_FILES):
            assert match.designation not in seen, (
                f"{match.designation!r} claimed by both {seen.get(match.designation)} and {rule['ext']}"
            )
            seen[match.designation] = rule["ext"]
    assert set(seen) == set(PDC_MANIFEST_FILES)


def test_element_identifiers_keep_the_published_file_name():
    """Elements should read the same as the manifest rows they came from."""
    for rule in RULES:
        for match in _matches_for(rule, PDC_MANIFEST_FILES):
            assert match.designation in PDC_MANIFEST_FILES
