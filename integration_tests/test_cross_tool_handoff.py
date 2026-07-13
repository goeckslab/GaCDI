"""Cross-tool integration: the builder's selection bundle feeds the downloader.

The builder emits the canonical asset manifest, association metadata, and
provenance JSON; the downloader loads all three, enforces the bundle's cross-file
invariants, and resolves them into concrete assets. Running the downloader in
dry-run bundle mode proves the handoff without touching the network.
"""

from __future__ import annotations

from gacdi.bundle import load_selection_bundle
from gacdi.cli import main as download_main
from gacdi_manifest.cli import main as build_main


def _build_bundle(tmp_path, gdc_api):
    rc = build_main(
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


def test_builder_bundle_loads_and_validates(tmp_path, gdc_api):
    _build_bundle(tmp_path, gdc_api)
    bundle = load_selection_bundle(
        str(tmp_path / "selection_manifest.tsv"),
        str(tmp_path / "selection_metadata.tsv"),
        str(tmp_path / "selection_provenance.json"),
    )
    assert bundle.source == "gdc"
    assert {asset.asset_id for asset in bundle.assets} == {"uuid1", "uuid2"}
    assert bundle.provenance.mode == "build"


def test_downloader_consumes_builder_bundle_dry_run(tmp_path, gdc_api):
    _build_bundle(tmp_path, gdc_api)
    summary_path = tmp_path / "summary.tsv"
    rc = download_main(
        [
            "gdc",
            "--input-mode",
            "bundle",
            "--manifest",
            str(tmp_path / "selection_manifest.tsv"),
            "--metadata",
            str(tmp_path / "selection_metadata.tsv"),
            "--provenance",
            str(tmp_path / "selection_provenance.json"),
            "--output-dir",
            str(tmp_path / "out"),
            "--summary",
            str(summary_path),
            "--dry-run",
        ]
    )
    assert rc == 0
    summary = summary_path.read_text()
    assert "uuid1" in summary and "uuid2" in summary
    assert summary.count("planned") == 2
