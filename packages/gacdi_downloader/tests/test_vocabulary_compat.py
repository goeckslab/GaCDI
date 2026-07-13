"""Phase 4: preferred internal names and their compatibility aliases coincide.

``BaseDownloadSource`` / ``*DownloadSource`` are the preferred names;
``BaseImporter`` / ``*Importer`` remain as aliases pointing at the same objects,
and the historical ``gacdi.importers.*`` import paths keep working.
"""

from __future__ import annotations

import pytest

from gacdi.base import BaseDownloadSource, BaseImporter


def test_base_alias_is_the_same_class():
    assert BaseImporter is BaseDownloadSource


@pytest.mark.parametrize(
    "source, preferred, legacy",
    [
        ("gdc", "GDCDownloadSource", "GDCImporter"),
        ("geo", "GEODownloadSource", "GEOImporter"),
        ("sra", "SRADownloadSource", "SRAImporter"),
        ("cda", "CDADownloadSource", "CDAImporter"),
        ("xena", "XenaDownloadSource", "XenaImporter"),
    ],
)
def test_preferred_and_legacy_names_coincide(source, preferred, legacy):
    from importlib import import_module

    module = import_module(f"gacdi.sources.{source}")
    assert getattr(module, preferred) is getattr(module, legacy)

    # Historical import paths still resolve to the same class.
    legacy_module = import_module(f"gacdi.importers.{source}")
    assert getattr(legacy_module, legacy) is getattr(module, legacy)

    from gacdi.registry import get_source

    assert isinstance(get_source(source), getattr(module, preferred))


def test_registry_exposes_both_name_styles():
    from gacdi import registry

    assert registry.GDCDownloadSource is registry.GDCImporter
    assert issubclass(registry.GDCDownloadSource, BaseDownloadSource)
