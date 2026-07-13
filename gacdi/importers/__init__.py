"""Lazy registry mapping database names to importer classes.

Each entry is a :class:`SourceSpec` naming an import *target* (``module:Class``)
that is only imported when the source is actually selected. This keeps a single
broken or optional source (for example one whose extra runtime dependency is not
installed) from breaking every other CLI subcommand: building the parser and
listing sources never imports a source module.

``get_source`` is the preferred accessor; ``get_importer`` is kept as a
compatibility alias. The importer classes also remain importable by name from
this package (``from gacdi.importers import GDCImporter``) via lazy attribute
access.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from ..errors import InputError


@dataclass(frozen=True)
class SourceSpec:
    """A lazily-loadable registry entry.

    ``target`` is a ``"package.module:ClassName"`` string; ``load`` imports the
    module and returns the class only when needed.
    """

    target: str
    help: str = ""

    def load(self) -> type:
        module_path, _, attr = self.target.partition(":")
        module = import_module(module_path)
        return getattr(module, attr)


REGISTRY: dict[str, SourceSpec] = {
    "gdc": SourceSpec(
        target="gacdi.importers.gdc:GDCImporter",
        help="Import files from the Genomic Data Commons",
    ),
    "geo": SourceSpec(
        target="gacdi.importers.geo:GEOImporter",
        help="Import supplementary files from GEO",
    ),
    "sra": SourceSpec(
        target="gacdi.importers.sra:SRAImporter",
        help="Import runs from the Sequence Read Archive",
    ),
    "cda": SourceSpec(
        target="gacdi.importers.cda:CDAImporter",
        help="Import assets discovered through the Cancer Data Aggregator",
    ),
    "xena": SourceSpec(
        target="gacdi.importers.xena:XenaImporter",
        help="Import datasets from UCSC Xena hubs",
    ),
}


def get_source(name: str, **kwargs):
    """Instantiate the importer registered under *name* (lazy import)."""
    try:
        spec = REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(REGISTRY))
        raise InputError(f"Unknown database '{name}'. Available: {available}.") from None
    return spec.load()(**kwargs)


# Compatibility alias: the historical accessor name.
get_importer = get_source


# Backwards-compatible lazy class re-exports: ``from gacdi.importers import
# GDCImporter`` keeps working without importing every source at package import.
_CLASS_EXPORTS: dict[str, str] = {
    "GDCImporter": "gdc",
    "GEOImporter": "geo",
    "SRAImporter": "sra",
    "CDAImporter": "cda",
    "XenaImporter": "xena",
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
    "GEOImporter",
    "SRAImporter",
    "CDAImporter",
    "XenaImporter",
]
