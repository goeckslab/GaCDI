"""Phase 0 characterization: golden-file coverage of representative outputs.

The GDC build is deterministic under the mocked API fixture, so its manifest,
metadata, and canonical selection sidecars are pinned byte-for-byte. Provenance
carries a timestamp, so it is checked structurally rather than by exact bytes.
These goldens must not change during a behaviour-neutral refactor.
"""

from __future__ import annotations

import json
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"


def _build(tmp_path, gdc_api):
    from gacdi_manifest.cli import main

    rc = main(
        [
            "gdc",
            "--project",
            "TCGA-BRCA",
            "--data-type",
            "Slide Image",
            "--manifest-out",
            str(tmp_path / "manifest.txt"),
            "--metadata-out",
            str(tmp_path / "metadata.tsv"),
            "--report-out",
            str(tmp_path / "report.tsv"),
            "--selection-manifest-out",
            str(tmp_path / "selection_manifest.tsv"),
            "--selection-metadata-out",
            str(tmp_path / "selection_metadata.tsv"),
            "--selection-provenance-out",
            str(tmp_path / "selection_provenance.json"),
        ]
    )
    assert rc == 0


def test_manifest_matches_golden(tmp_path, gdc_api):
    _build(tmp_path, gdc_api)
    assert (tmp_path / "manifest.txt").read_text() == (GOLDEN / "gdc_manifest.txt").read_text()


def test_metadata_matches_golden(tmp_path, gdc_api):
    _build(tmp_path, gdc_api)
    assert (tmp_path / "metadata.tsv").read_text() == (GOLDEN / "gdc_metadata.tsv").read_text()


def test_selection_manifest_matches_golden(tmp_path, gdc_api):
    _build(tmp_path, gdc_api)
    assert (tmp_path / "selection_manifest.tsv").read_text() == (
        GOLDEN / "gdc_selection_manifest.tsv"
    ).read_text()


def test_selection_metadata_matches_golden(tmp_path, gdc_api):
    _build(tmp_path, gdc_api)
    assert (tmp_path / "selection_metadata.tsv").read_text() == (
        GOLDEN / "gdc_selection_metadata.tsv"
    ).read_text()


def test_provenance_has_stable_structure(tmp_path, gdc_api):
    _build(tmp_path, gdc_api)
    prov = json.loads((tmp_path / "selection_provenance.json").read_text())
    assert prov["contract_version"] == "1.0"
    assert prov["source"] == "gdc"
    assert prov["mode"] == "build"
    for key in ("query", "endpoint", "tool", "tool_version", "counts", "warnings"):
        assert key in prov
