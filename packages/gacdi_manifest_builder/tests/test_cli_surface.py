"""Phase 0 characterization: freeze the builder's public surface.

These assertions pin the CLI entry point, the documented exit codes, the public
import surface, and the registry contract so a structural refactor cannot
silently change behaviour. They must keep passing unchanged through every later
phase.
"""

from __future__ import annotations

import argparse

import pytest

import gacdi_manifest
from gacdi_manifest import cli
from gacdi_manifest.errors import ApiError, InputError, ManifestError


# --- CLI entry point --------------------------------------------------------
def test_version_action_reports_distribution_and_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("gacdi-manifest ")
    assert gacdi_manifest.version_string() in out


def test_top_level_help_lists_every_source(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for name in ("gdc", "pdc", "idc"):
        assert name in out


@pytest.mark.parametrize("source", ["gdc", "pdc", "idc"])
def test_every_source_subcommand_help_builds_without_network(source, capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args([source, "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--manifest-out" in out
    assert "--count-only" in out


def test_missing_database_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args([])
    assert excinfo.value.code == 2


# --- documented exit codes --------------------------------------------------
def test_documented_exit_codes_are_stable():
    assert ManifestError.exit_code == 1
    assert InputError.exit_code == 2
    assert ApiError.exit_code == 4


# --- public import surface --------------------------------------------------
def test_public_import_surface():
    from gacdi_manifest import io, selection
    from gacdi_manifest.importer import BuildImporter
    from gacdi_manifest.registry import REGISTRY, get_importer

    assert callable(get_importer)
    assert isinstance(REGISTRY, dict)
    assert issubclass(BuildImporter, object)
    assert hasattr(io, "MANIFEST_COLUMNS")
    assert hasattr(selection, "write_selection_bundle")


def test_builder_consumes_shared_contract_surface():
    # The builder depends on the shared foundation for these symbols.
    from gacdi_core.contracts import ASSET_COLUMNS  # noqa: F401
    from gacdi_core.errors import InputError as ContractInputError  # noqa: F401
    from gacdi_core.net import build_session  # noqa: F401
    from gacdi_core.validation import validate_assets  # noqa: F401


def test_builder_errors_share_the_core_root():
    from gacdi_core.errors import GacdiError, InputError as CoreInputError

    assert issubclass(ManifestError, GacdiError)
    assert issubclass(InputError, CoreInputError)


# --- registry contract ------------------------------------------------------
def test_registry_exposes_the_expected_sources():
    from gacdi_manifest.registry import REGISTRY

    assert set(REGISTRY) == {"gdc", "pdc", "idc"}


def test_registry_names_are_unique_and_match_loaded_source():
    from gacdi_manifest.importer import BuildImporter
    from gacdi_manifest.registry import REGISTRY, get_importer

    for name in REGISTRY:
        assert name and isinstance(name, str)
        instance = get_importer(name)
        assert isinstance(instance, BuildImporter)
        assert instance.name == name


def test_get_importer_rejects_unknown_source():
    from gacdi_manifest.registry import get_importer

    with pytest.raises(InputError):
        get_importer("nosuchsource")


def test_every_subparser_can_be_constructed_offline():
    parser = cli.build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
