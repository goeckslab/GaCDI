"""Lazy registry mapping database names to builder importers.

Mirrors the downloader's ``gacdi/importers/__init__.py``: each entry is a
:class:`SourceSpec` naming an import *target* (``module:Class``) that is only
imported when the source is selected, so a single broken or optional source
cannot break every other CLI subcommand.

``get_source`` is the preferred accessor; ``get_importer`` is kept as a
compatibility alias. The importer classes remain importable by name from this
module (``from gacdi_manifest.registry import GDCImporter``) via lazy attribute
access.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from .errors import InputError


@dataclass(frozen=True)
class SourceSpec:
    """A lazily-loadable registry entry (``"package.module:ClassName"``)."""

    target: str
    help: str = ""

    def load(self) -> type:
        module_path, _, attr = self.target.partition(":")
        module = import_module(module_path)
        return getattr(module, attr)


REGISTRY: dict[str, SourceSpec] = {
    "gdc": SourceSpec(
        target="gacdi_manifest.sources.gdc:GDCImporter",
        help="Build a manifest from the Genomic Data Commons",
    ),
    "pdc": SourceSpec(
        target="gacdi_manifest.sources.pdc:PDCImporter",
        help="Build a manifest from the Proteomic Data Commons",
    ),
    "idc": SourceSpec(
        target="gacdi_manifest.sources.idc:IDCImporter",
        help="Build a manifest from the Imaging Data Commons",
    ),
}


def get_source(name: str) -> "BuildImporter":  # noqa: F821 - forward ref for docs
    """Instantiate the builder registered under *name* (lazy import)."""
    try:
        spec = REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(REGISTRY))
        raise InputError(f"Unknown database '{name}'. Available: {available}.") from None
    return spec.load()()


# Compatibility alias: the historical accessor name.
get_importer = get_source


_CLASS_EXPORTS: dict[str, str] = {
    "GDCImporter": "gdc",
    "PDCImporter": "pdc",
    "IDCImporter": "idc",
}


def __getattr__(name: str):
    source = _CLASS_EXPORTS.get(name)
    if source is not None:
        return REGISTRY[source].load()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "REGISTRY",
    "SourceSpec",
    "get_source",
    "get_importer",
    "GDCImporter",
    "PDCImporter",
    "IDCImporter",
]
