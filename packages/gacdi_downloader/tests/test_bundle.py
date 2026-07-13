import csv
import hashlib
import json
from pathlib import Path

import pytest

from gacdi.auth import TokenFile
from gacdi.base import RunConfig
from gacdi.bundle import load_selection_bundle, sha256_file
from gacdi.cli import main
from gacdi.contracts import ASSET_COLUMNS, METADATA_LEADING_COLUMNS, association_row_id
from gacdi.errors import InputError
from gacdi.importers.gdc import GDCImporter


def _asset(**overrides):
    row = {
        "source": "gdc",
        "asset_id": "A1",
        "asset_kind": "file",
        "download_method": "gdc-client",
        "drs_uri": "",
        "access_url": "",
        "access": "open",
        "asset_name": "sample.vcf.gz",
        "source_size": "7",
        "source_checksum_type": "md5",
        "source_checksum": hashlib.md5(b"payload").hexdigest(),
        "file_format": "VCF",
        "payload_profile": "single_vcf",
        "galaxy_ext_hint": "vcf_bgzip",
        "dbkey": "hg38",
    }
    row.update(overrides)
    return row


def _metadata(**overrides):
    row = {
        "metadata_row_id": "",
        "source": "gdc",
        "asset_id": "A1",
        "relationship": "sample",
        "case_id": "C1",
        "sample_id": "S1",
        "project": "TCGA-X",
        "sample_type": "Primary Tumor",
        "annotation_state": "not_requested",
    }
    row.update(overrides)
    if not row["metadata_row_id"]:
        row["metadata_row_id"] = association_row_id(
            row["source"],
            row["asset_id"],
            row["relationship"],
            row["case_id"],
            row["sample_id"],
        )
    return row


def _write_tsv(path, columns, rows):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(column, "") for column in columns])


def write_bundle(
    tmp_path,
    *,
    assets=None,
    metadata=None,
    metadata_columns=METADATA_LEADING_COLUMNS,
    mode="build",
    provenance_overrides=None,
):
    asset_path = tmp_path / "selection_assets.tsv"
    metadata_path = tmp_path / "selection_metadata.tsv"
    provenance_path = tmp_path / "selection_provenance.json"
    _write_tsv(asset_path, ASSET_COLUMNS, assets or [_asset()])
    _write_tsv(metadata_path, metadata_columns, metadata or [_metadata()])
    provenance = {
        "contract_version": "1.0",
        "mode": mode,
        "source": (assets or [_asset()])[0]["source"],
        "query": {"fixture": True},
        "endpoint": "https://example.invalid/files",
        "tool": "test-selector",
        "tool_version": "1.0",
        "build": "test",
        "timestamp": "2026-07-12T00:00:00+00:00",
        "counts": {
            "assets": len(assets or [_asset()]),
            "metadata_rows": len(metadata or [_metadata()]),
            "cases": len({row.get("case_id") for row in (metadata or [_metadata()]) if row.get("case_id")}),
            "samples": len({row.get("sample_id") for row in (metadata or [_metadata()]) if row.get("sample_id")}),
            "known_source_bytes": sum(
                int(row["source_size"]) if row.get("source_size") else 0
                for row in (assets or [_asset()])
            ),
        },
        "warnings": [],
        "asset_manifest_sha256": sha256_file(asset_path),
        "metadata_sha256": sha256_file(metadata_path),
    }
    provenance.update(provenance_overrides or {})
    provenance_path.write_text(json.dumps(provenance))
    return asset_path, metadata_path, provenance_path


def test_load_selection_bundle_validates_exact_files(tmp_path):
    asset_path, metadata_path, provenance_path = write_bundle(tmp_path)
    bundle = load_selection_bundle(asset_path, metadata_path, provenance_path)

    assert bundle.source == "gdc"
    assert bundle.assets[0].asset_id == "A1"
    assert bundle.assets[0].source_size == 7
    assert bundle.metadata[0].metadata_row_id.startswith("md_")
    assert bundle.provenance.contract_version == "1.0"
    assert bundle.provenance.mode == "build"
    assert bundle.asset_manifest_sha256 == sha256_file(asset_path)
    assert bundle.metadata_sha256 == sha256_file(metadata_path)


def test_asset_header_order_is_exact(tmp_path):
    columns = list(ASSET_COLUMNS)
    columns[2], columns[3] = columns[3], columns[2]
    asset_path = tmp_path / "assets.tsv"
    metadata_path = tmp_path / "metadata.tsv"
    provenance_path = tmp_path / "provenance.json"
    _write_tsv(asset_path, columns, [_asset()])
    _write_tsv(metadata_path, METADATA_LEADING_COLUMNS, [_metadata()])
    provenance_path.write_text("{}")
    with pytest.raises(InputError, match="header does not match"):
        load_selection_bundle(asset_path, metadata_path, provenance_path)


def test_assets_must_be_sorted_and_have_one_profile(tmp_path):
    rows = [
        _asset(asset_id="B", asset_name="b.bam", source_checksum_type="", source_checksum=""),
        _asset(asset_id="A", asset_name="a.bam", source_checksum_type="", source_checksum=""),
    ]
    metadata = [
        _metadata(asset_id="B"),
        _metadata(asset_id="A"),
    ]
    paths = write_bundle(tmp_path, assets=rows, metadata=metadata)
    with pytest.raises(InputError, match="canonical ascending order"):
        load_selection_bundle(*paths)

    rows = [
        _asset(asset_id="A", asset_name="a.bam", source_checksum_type="", source_checksum=""),
        _asset(
            asset_id="B",
            asset_name="b.vcf",
            payload_profile="single_vcf",
            source_checksum_type="",
            source_checksum="",
        ),
    ]
    rows[0]["payload_profile"] = "single_bam"
    paths = write_bundle(tmp_path, assets=rows, metadata=metadata)
    with pytest.raises(InputError, match="homogeneous payload_profile"):
        load_selection_bundle(*paths)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"asset_name": "../bad.bam"}, "safe basename"),
        ({"asset_id": "../escape"}, "path traversal"),
        ({"source_size": "١"}, "non-negative integer"),
        ({"access": "unknown"}, "access must be"),
        ({"source_checksum": ""}, "must be set together"),
        ({"source_checksum": "not-an-md5"}, "invalid md5"),
        ({"download_method": "https", "access_url": "http://host/f"}, "must use: https"),
        ({"download_method": "drs", "drs_uri": ""}, "requires drs_uri"),
    ],
)
def test_asset_value_validation(tmp_path, overrides, message):
    paths = write_bundle(tmp_path, assets=[_asset(**overrides)])
    with pytest.raises(InputError, match=message):
        load_selection_bundle(*paths)


def test_metadata_leading_keys_and_foreign_keys(tmp_path):
    columns = list(METADATA_LEADING_COLUMNS)
    columns[0], columns[1] = columns[1], columns[0]
    paths = write_bundle(tmp_path, metadata_columns=columns)
    with pytest.raises(InputError, match="leading columns"):
        load_selection_bundle(*paths)

    paths = write_bundle(tmp_path, metadata=[_metadata(asset_id="MISSING")])
    with pytest.raises(InputError, match="unknown asset"):
        load_selection_bundle(*paths)


def test_metadata_supports_multiple_blank_sample_associations(tmp_path):
    metadata = [
        _metadata(relationship="case", sample_id="", case_id="C1"),
        _metadata(relationship="case", sample_id="", case_id="C2"),
    ]
    bundle = load_selection_bundle(*write_bundle(tmp_path, metadata=metadata))
    assert len({row.metadata_row_id for row in bundle.metadata}) == 2


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (_metadata(relationship="garbage"), "relationship must be"),
        (_metadata(relationship="sample", sample_id=""), "requires sample_id"),
        (
            _metadata(relationship="asset", case_id="C1", sample_id=""),
            "cannot set case_id",
        ),
        (_metadata(metadata_row_id="invented"), "canonical association ID"),
    ],
)
def test_metadata_relationship_and_id_validation(tmp_path, metadata, message):
    paths = write_bundle(tmp_path, metadata=[metadata])
    with pytest.raises(InputError, match=message):
        load_selection_bundle(*paths)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"contract_version": "2.0"}, "Unsupported selection contract"),
        ({"mode": "other"}, "mode must be"),
        ({"asset_manifest_sha256": "0" * 64}, "does not match"),
        ({"metadata_sha256": "BAD"}, "lowercase SHA-256"),
        ({"source": "pdc"}, "source does not match"),
    ],
)
def test_provenance_validation(tmp_path, overrides, message):
    paths = write_bundle(tmp_path, provenance_overrides=overrides)
    with pytest.raises(InputError, match=message):
        load_selection_bundle(*paths)


def test_gdc_bundle_maps_assets_and_metadata(tmp_path):
    asset_path, metadata_path, provenance_path = write_bundle(tmp_path)
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(asset_path),
        metadata=str(metadata_path),
        provenance=str(provenance_path),
    )
    entries = GDCImporter().resolve(cfg, None)
    entry = entries[0]
    assert (entry.file_id, entry.filename, entry.size) == ("A1", "sample.vcf.gz", 7)
    assert entry.md5 == hashlib.md5(b"payload").hexdigest()
    assert entry.extra["galaxy_ext_hint"] == "vcf_bgzip"
    assert entry.extra["dbkey"] == "hg38"
    assert entry.extra["selection_metadata"][0].metadata_row_id.startswith("md_")


def test_gdc_bundle_run_materializes_all_handoff_artifacts(tmp_path, monkeypatch):
    paths = write_bundle(tmp_path)
    monkeypatch.setattr("gacdi.clients.gdc.require", lambda _: "gdc-client")

    def fake_run(command, **kwargs):
        destination = command[command.index("-d") + 1]
        subdir = Path(destination) / "A1"
        subdir.mkdir(parents=True)
        (subdir / "sample.vcf.gz").write_bytes(b"payload")

    monkeypatch.setattr("gacdi.clients.gdc.run", fake_run)
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
        output_dir=str(tmp_path / "downloads"),
        summary=str(tmp_path / "summary.tsv"),
        transfer_report=str(tmp_path / "transfer.tsv"),
        dataset_map=str(tmp_path / "map.tsv"),
        galaxy_metadata=str(tmp_path / "galaxy.json"),
        imported_metadata=str(tmp_path / "imported.tsv"),
        import_provenance=str(tmp_path / "import.json"),
        retry_manifest=str(tmp_path / "retry.tsv"),
        retries=0,
    )
    summary = GDCImporter().run(cfg)
    assert [result.status for result in summary.results] == ["ok"]
    galaxy = json.loads((tmp_path / "galaxy.json").read_text())
    assert galaxy["downloaded_vcf"]["datasets"][0]["ext"] == "vcf_bgzip"
    assert galaxy["downloaded_vcf"]["datasets"][0]["identifier_0"] == "A1"
    imported = list(csv.DictReader((tmp_path / "imported.tsv").open(), delimiter="\t"))
    assert imported[0]["sample_id"] == "S1"
    assert imported[0]["element_id"] == "A1"
    retry = list(csv.DictReader((tmp_path / "retry.tsv").open(), delimiter="\t"))
    assert retry == []


def test_gdc_bundle_preflights_access_and_preview(tmp_path):
    controlled = write_bundle(tmp_path, assets=[_asset(access="controlled")])
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(controlled[0]),
        metadata=str(controlled[1]),
        provenance=str(controlled[2]),
    )
    entries = GDCImporter().resolve(cfg, None)
    assert "controlled-access" in entries[0].extra["preflight_error"]

    token_path = tmp_path / "token.txt"
    token_path.write_text("secret")
    with TokenFile(token_path) as token:
        token_entry = GDCImporter().resolve(cfg, token)[0]
        assert token_entry.file_id == "A1"
        assert token_entry.extra["preflight_error"] == ""

    preview_dir = tmp_path / "preview"
    preview_dir.mkdir()
    preview = write_bundle(preview_dir, mode="preview")
    preview_cfg = RunConfig(
        input_mode="bundle",
        manifest=str(preview[0]),
        metadata=str(preview[1]),
        provenance=str(preview[2]),
    )
    with pytest.raises(InputError, match="preview"):
        GDCImporter().resolve(preview_cfg, None)


def test_controlled_preflight_writes_one_failed_transfer_row(tmp_path):
    paths = write_bundle(tmp_path, assets=[_asset(access="controlled")])
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
        output_dir=str(tmp_path / "downloads"),
        summary=str(tmp_path / "summary.tsv"),
        transfer_report=str(tmp_path / "transfer.tsv"),
        dataset_map=str(tmp_path / "map.tsv"),
        galaxy_metadata=str(tmp_path / "galaxy.json"),
        imported_metadata=str(tmp_path / "imported.tsv"),
        import_provenance=str(tmp_path / "import.json"),
        retry_manifest=str(tmp_path / "retry.tsv"),
    )
    summary = GDCImporter().run(cfg)
    assert [result.status for result in summary.results] == ["failed"]
    rows = list(csv.DictReader((tmp_path / "transfer.tsv").open(), delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "controlled-access" in rows[0]["message"]
    retry_rows = list(csv.DictReader((tmp_path / "retry.tsv").open(), delimiter="\t"))
    assert [row["asset_id"] for row in retry_rows] == ["A1"]
    retry_bundle = load_selection_bundle(
        tmp_path / "retry.tsv",
        tmp_path / "retry_metadata.tsv",
        tmp_path / "retry_provenance.json",
    )
    assert [asset.asset_id for asset in retry_bundle.assets] == ["A1"]
    import_values = json.loads((tmp_path / "import.json").read_text())
    assert import_values["result_counts"] == {"failed": 1}


def test_mixed_access_preflight_only_blocks_controlled_assets(tmp_path):
    assets = [
        _asset(asset_id="A1", access="controlled"),
        _asset(
            asset_id="A2",
            access="open",
            asset_name="open.vcf.gz",
            source_checksum_type="",
            source_checksum="",
        ),
    ]
    metadata = [
        _metadata(asset_id="A1", sample_id="S1"),
        _metadata(asset_id="A2", sample_id="S2"),
    ]
    paths = write_bundle(tmp_path, assets=assets, metadata=metadata)
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
    )
    entries = GDCImporter().resolve(cfg, None)
    assert "controlled-access" in entries[0].extra["preflight_error"]
    assert entries[1].extra["preflight_error"] == ""


def test_gdc_bundle_requires_explicit_raw_mixed_opt_in(tmp_path):
    paths = write_bundle(tmp_path, assets=[_asset(payload_profile="raw_mixed")])
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
    )
    with pytest.raises(InputError, match="allow_raw_mixed=true"):
        GDCImporter().resolve(cfg, None)

    cfg.options["allow_raw_mixed"] = "true"
    assert GDCImporter().resolve(cfg, None)[0].file_id == "A1"


def test_gdc_bundle_rejects_profile_extension_mismatch_and_etag(tmp_path):
    paths = write_bundle(
        tmp_path,
        assets=[_asset(payload_profile="single_bam", galaxy_ext_hint="vcf_bgzip")],
    )
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
    )
    with pytest.raises(InputError, match="incompatible with galaxy_ext_hint"):
        GDCImporter().resolve(cfg, None)

    format_dir = tmp_path / "format"
    format_dir.mkdir()
    paths = write_bundle(
        format_dir,
        assets=[
            _asset(
                payload_profile="single_bam",
                galaxy_ext_hint="bam",
                file_format="VCF",
            )
        ],
    )
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
    )
    with pytest.raises(InputError, match="incompatible with file_format"):
        GDCImporter().resolve(cfg, None)

    etag_dir = tmp_path / "etag"
    etag_dir.mkdir()
    paths = write_bundle(
        etag_dir,
        assets=[_asset(source_checksum_type="etag", source_checksum="opaque")],
    )
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
    )
    with pytest.raises(InputError, match="checksum types must be md5 or sha256"):
        GDCImporter().resolve(cfg, None)


def test_gdc_bundle_rejects_wrong_source_and_missing_sidecars(tmp_path):
    with pytest.raises(InputError, match="requires --manifest"):
        GDCImporter().resolve(RunConfig(input_mode="bundle"), None)

    asset = _asset(
        source="pdc",
        download_method="drs",
        drs_uri="drs://dg.example/A1",
        source_checksum_type="",
        source_checksum="",
    )
    metadata = _metadata(source="pdc")
    paths = write_bundle(
        tmp_path,
        assets=[asset],
        metadata=[metadata],
        provenance_overrides={"source": "pdc"},
    )
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
    )
    with pytest.raises(InputError, match="source 'gdc'"):
        GDCImporter().resolve(cfg, None)


def test_gdc_bundle_download_reports_actual_checksums(tmp_path, monkeypatch):
    paths = write_bundle(tmp_path)
    cfg = RunConfig(
        input_mode="bundle",
        manifest=str(paths[0]),
        metadata=str(paths[1]),
        provenance=str(paths[2]),
    )
    entry = GDCImporter().resolve(cfg, None)[0]
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()

    monkeypatch.setattr("gacdi.clients.gdc.require", lambda binary: binary)

    def fake_run(command, **kwargs):
        directory = output_dir / "A1"
        directory.mkdir()
        (directory / "sample.vcf.gz").write_bytes(b"payload")

    monkeypatch.setattr("gacdi.clients.gdc.run", fake_run)
    result = GDCImporter().download(entry, str(output_dir), cfg, None)
    assert result.status == "ok"
    assert result.checksum_verified is True
    assert result.observed_checksum_type == "md5"
    assert result.observed_checksum == hashlib.md5(b"payload").hexdigest()
    assert result.produced[0].status == "produced"
    assert result.produced[0].element_id == "A1"
    assert result.produced[0].galaxy_ext == "vcf_bgzip"
    assert result.produced[0].checksum_type == "sha256"
    assert result.produced[0].checksum == hashlib.sha256(b"payload").hexdigest()


def test_cli_bundle_dry_run_accepts_all_report_flags(tmp_path):
    paths = write_bundle(tmp_path)
    summary = tmp_path / "summary.tsv"
    transfer = tmp_path / "transfer.tsv"
    dataset_map = tmp_path / "dataset_map.tsv"
    galaxy_metadata = tmp_path / "galaxy.json"
    rc = main(
        [
            "gdc",
            "--input-mode",
            "bundle",
            "--manifest",
            str(paths[0]),
            "--metadata",
            str(paths[1]),
            "--provenance",
            str(paths[2]),
            "--output-dir",
            str(tmp_path / "out"),
            "--summary",
            str(summary),
            "--transfer-report",
            str(transfer),
            "--dataset-map",
            str(dataset_map),
            "--galaxy-metadata",
            str(galaxy_metadata),
            "--dry-run",
        ]
    )
    assert rc == 0
    assert "planned" in summary.read_text()
    assert "planned" in transfer.read_text()
    assert len(dataset_map.read_text().splitlines()) == 1
    assert json.loads(galaxy_metadata.read_text()) == {"downloaded_vcf": {"datasets": []}}
