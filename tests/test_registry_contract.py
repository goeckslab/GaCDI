"""Phase 1 contract tests for the lazy downloader registry.

These guarantee that every registry entry loads to a real importer, that the CLI
parser can be built offline, that a source can be imported without its optional
runtime dependency, and that one deliberately-unavailable source does not break
the other subcommands.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from gacdi import cli
from gacdi.base import BaseImporter
from gacdi.errors import InputError
from gacdi.importers import REGISTRY, SourceSpec, get_importer, get_source


def test_names_are_unique_and_non_empty():
    assert all(name and isinstance(name, str) for name in REGISTRY)
    assert len(set(REGISTRY)) == len(REGISTRY)


def test_every_target_loads_to_the_correct_interface():
    for name, spec in REGISTRY.items():
        assert isinstance(spec, SourceSpec)
        cls = spec.load()
        assert issubclass(cls, BaseImporter)
        assert cls.name == name


def test_get_source_and_alias_return_instances():
    for name in REGISTRY:
        assert isinstance(get_source(name), BaseImporter)
        assert isinstance(get_importer(name), BaseImporter)
    assert get_importer is get_source


def test_get_source_rejects_unknown():
    with pytest.raises(InputError):
        get_source("nope")


def test_cli_parser_builds_without_importing_any_source():
    # Importing the registry / building the parser must not import source modules
    # (which is what keeps an optional dependency from breaking every subcommand).
    code = (
        "import sys; import gacdi.cli as c; c.build_parser();"
        "mods=[m for m in sys.modules if m.startswith('gacdi.importers.')];"
        "print(sorted(mods))"
    )
    out = subprocess.check_output([sys.executable, "-c", code], text=True).strip()
    assert out == "[]", f"parser build eagerly imported source modules: {out}"


def test_cda_imports_without_its_optional_dependency():
    # cdapython is invoked lazily; importing the source and constructing it must
    # not require the optional SDK to be installed.
    import importlib

    module = importlib.import_module("gacdi.importers.cda")
    assert module.CDAImporter().name == "cda"


def test_unavailable_source_does_not_break_others(monkeypatch):
    broken = dict(REGISTRY)
    broken["broken"] = SourceSpec(target="gacdi._does_not_exist:Nope", help="broken")
    monkeypatch.setattr("gacdi.importers.REGISTRY", broken)
    monkeypatch.setattr(cli, "REGISTRY", broken, raising=False)

    # The good sources still resolve and the parser still builds.
    assert get_source("gdc").name == "gdc"
    cli.build_parser()

    # Only the broken source fails, and only when it is selected.
    with pytest.raises(ModuleNotFoundError):
        get_source("broken")
