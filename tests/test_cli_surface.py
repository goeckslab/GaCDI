"""Phase 0 characterization: freeze the downloader's public surface.

These assertions pin the CLI entry point, the documented exit codes, the public
import surface used by tests and Galaxy wrappers, and the registry contract so a
structural refactor cannot silently change behaviour. They must keep passing
unchanged through every later phase.
"""

from __future__ import annotations

import argparse

import pytest

import gacdi
from gacdi import cli
from gacdi.errors import (
    AuthError,
    ChecksumError,
    DependencyError,
    DownloadError,
    GacdiError,
    InputError,
)


# --- CLI entry point --------------------------------------------------------
def test_version_action_reports_distribution_and_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("gacdi ")
    assert gacdi.version_string() in out


def test_top_level_help_lists_every_source(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for name in ("gdc", "geo", "sra", "cda", "xena"):
        assert name in out


@pytest.mark.parametrize("source", ["gdc", "geo", "sra", "cda", "xena"])
def test_every_source_subcommand_help_builds_without_network(source, capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args([source, "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--input-mode" in out
    assert "--summary" in out


def test_missing_database_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args([])
    assert excinfo.value.code == 2


# --- documented exit codes --------------------------------------------------
def test_documented_exit_codes_are_stable():
    assert GacdiError.exit_code == 1
    assert InputError.exit_code == 2
    assert AuthError.exit_code == 3
    assert DownloadError.exit_code == 4
    assert ChecksumError.exit_code == 5
    assert DependencyError.exit_code == 6


def test_input_error_exit_code_propagates_through_main(tmp_path):
    rc = cli.main(
        [
            "gdc",
            "--input-mode",
            "manifest",
            "--manifest",
            str(tmp_path / "does-not-exist.txt"),
            "--summary",
            str(tmp_path / "s.tsv"),
        ]
    )
    assert rc == InputError.exit_code


# --- public import surface --------------------------------------------------
def test_public_import_surface():
    from gacdi import bundle, contracts, history, manifest, model, net, validation
    from gacdi.base import BaseImporter, RunConfig
    from gacdi.importers import REGISTRY, get_importer
    from gacdi.model import DownloadResult, FileEntry, RunSummary

    assert callable(net.build_session)
    assert callable(contracts.association_row_id)
    assert callable(validation.validate_assets)
    assert callable(bundle.load_selection_bundle)
    assert callable(manifest.parse_gdc_manifest)
    assert hasattr(history, "SUMMARY_COLUMNS")
    assert issubclass(BaseImporter, object)
    assert RunConfig is not None
    assert {DownloadResult, FileEntry, RunSummary}
    assert callable(get_importer)
    assert isinstance(REGISTRY, dict)


# --- registry contract ------------------------------------------------------
def test_registry_exposes_the_expected_sources():
    from gacdi.importers import REGISTRY

    assert set(REGISTRY) == {"gdc", "geo", "sra", "cda", "xena"}


def test_registry_names_are_unique_and_match_loaded_source():
    from gacdi.base import BaseImporter
    from gacdi.importers import REGISTRY, get_importer

    for name in REGISTRY:
        assert name and isinstance(name, str)
        instance = get_importer(name)
        assert isinstance(instance, BaseImporter)
        assert instance.name == name


def test_get_importer_rejects_unknown_source():
    from gacdi.importers import get_importer

    with pytest.raises(InputError):
        get_importer("nosuchsource")


def test_every_subparser_can_be_constructed_offline():
    parser = cli.build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
