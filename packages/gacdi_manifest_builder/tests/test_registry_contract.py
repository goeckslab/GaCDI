"""Phase 1 contract tests for the lazy builder registry.

These guarantee that every registry entry loads to a real builder, that the CLI
parser can be built offline, and that one deliberately-unavailable source does
not break the other subcommands.
"""

from __future__ import annotations

import pytest

from gacdi_manifest import cli
from gacdi_manifest.errors import InputError
from gacdi_manifest.importer import BuildImporter
from gacdi_manifest.registry import REGISTRY, SourceSpec, get_importer, get_source


def test_names_are_unique_and_non_empty():
    assert all(name and isinstance(name, str) for name in REGISTRY)
    assert len(set(REGISTRY)) == len(REGISTRY)


def test_every_target_loads_to_the_correct_interface():
    for name, spec in REGISTRY.items():
        assert isinstance(spec, SourceSpec)
        cls = spec.load()
        assert issubclass(cls, BuildImporter)
        assert cls.name == name


def test_get_source_and_alias_return_instances():
    for name in REGISTRY:
        assert isinstance(get_source(name), BuildImporter)
        assert isinstance(get_importer(name), BuildImporter)
    assert get_importer is get_source


def test_get_source_rejects_unknown():
    with pytest.raises(InputError):
        get_source("nope")


def test_cli_parser_builds_offline():
    parser = cli.build_parser()
    # Every registered source is present as a subcommand.
    help_text = parser.format_help()
    for name in REGISTRY:
        assert name in help_text


def test_unavailable_source_does_not_break_others(monkeypatch):
    broken = dict(REGISTRY)
    broken["broken"] = SourceSpec(
        target="gacdi_manifest._does_not_exist:Nope", help="broken"
    )
    monkeypatch.setattr("gacdi_manifest.registry.REGISTRY", broken)
    monkeypatch.setattr(cli, "REGISTRY", broken, raising=False)

    # The good sources still resolve and the parser still builds (the broken
    # source is registered but its query flags are simply absent).
    assert get_source("gdc").name == "gdc"
    cli.build_parser()

    # The broken source fails only when it is actually selected.
    with pytest.raises(ModuleNotFoundError):
        get_source("broken")
