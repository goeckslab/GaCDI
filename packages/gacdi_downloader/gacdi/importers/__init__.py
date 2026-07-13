"""Compatibility shim for the historical ``gacdi.importers`` package.

The canonical registry now lives in :mod:`gacdi.registry` and the source modules
in :mod:`gacdi.sources`. This package re-exports the registry API and the source
classes so existing imports keep working:

    from gacdi.importers import REGISTRY, get_importer, GDCImporter
    from gacdi.importers.gdc import GDCImporter, API_FILES_ENDPOINT

New code should import from :mod:`gacdi.registry` and :mod:`gacdi.sources`.
"""

from __future__ import annotations

from importlib import import_module

from ..registry import REGISTRY, SourceSpec, get_importer, get_source

_CLASS_EXPORTS = {
    "GDCImporter": "gacdi.sources.gdc",
    "GEOImporter": "gacdi.sources.geo",
    "SRAImporter": "gacdi.sources.sra",
    "CDAImporter": "gacdi.sources.cda",
    "XenaImporter": "gacdi.sources.xena",
}


def __getattr__(name: str):
    module_path = _CLASS_EXPORTS.get(name)
    if module_path is not None:
        return getattr(import_module(module_path), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "REGISTRY",
    "SourceSpec",
    "get_source",
    "get_importer",
    *_CLASS_EXPORTS,
]
