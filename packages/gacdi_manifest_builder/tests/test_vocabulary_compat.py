"""Phase 4: preferred internal names and their compatibility aliases coincide.

``BaseManifestSource`` / ``*ManifestSource`` are the preferred names;
``BuildImporter`` / ``*Importer`` remain as aliases pointing at the same objects,
and the historical ``gacdi_manifest.importer`` path keeps working.
"""

from __future__ import annotations

import pytest

from gacdi_manifest.base import BaseManifestSource
from gacdi_manifest.importer import BuildImporter


def test_base_alias_is_the_same_class():
    assert BuildImporter is BaseManifestSource


@pytest.mark.parametrize(
    "source, preferred, legacy",
    [
        ("gdc", "GDCManifestSource", "GDCImporter"),
        ("pdc", "PDCManifestSource", "PDCImporter"),
        ("idc", "IDCManifestSource", "IDCImporter"),
    ],
)
def test_preferred_and_legacy_names_coincide(source, preferred, legacy):
    from importlib import import_module

    module = import_module(f"gacdi_manifest.sources.{source}")
    assert getattr(module, preferred) is getattr(module, legacy)

    from gacdi_manifest.registry import get_source

    assert isinstance(get_source(source), getattr(module, preferred))


def test_registry_exposes_both_name_styles():
    from gacdi_manifest import registry

    assert registry.GDCManifestSource is registry.GDCImporter
    assert issubclass(registry.GDCManifestSource, BaseManifestSource)
