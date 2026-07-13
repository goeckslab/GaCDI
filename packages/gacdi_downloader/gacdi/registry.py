"""Lazy registry mapping database names to download-source classes.

Each entry is a :class:`SourceSpec` naming an import *target* (``module:Class``)
that is only imported when the source is actually selected. This keeps a single
broken or optional source from breaking every other CLI subcommand: building the
parser and listing sources never imports a source module.

``get_source`` is the preferred accessor; ``get_importer`` is kept as a
compatibility alias. The source classes are importable by name from this module
under both their preferred (``GDCDownloadSource``) and historical
(``GDCImporter``) names via lazy attribute access.
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
        target="gacdi.sources.gdc:GDCDownloadSource",
        help="Import files from the Genomic Data Commons",
    ),
    "geo": SourceSpec(
        target="gacdi.sources.geo:GEODownloadSource",
        help="Import supplementary files from GEO",
    ),
    "sra": SourceSpec(
        target="gacdi.sources.sra:SRADownloadSource",
        help="Import runs from the Sequence Read Archive",
    ),
    "cda": SourceSpec(
        target="gacdi.sources.cda:CDADownloadSource",
        help="Import assets discovered through the Cancer Data Aggregator",
    ),
    "xena": SourceSpec(
        target="gacdi.sources.xena:XenaDownloadSource",
        help="Import datasets from UCSC Xena hubs",
    ),
}


def get_source(name: str, **kwargs):
    """Instantiate the download source registered under *name* (lazy import)."""
    try:
        spec = REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(REGISTRY))
        raise InputError(f"Unknown database '{name}'. Available: {available}.") from None
    return spec.load()(**kwargs)


# Compatibility alias: the historical accessor name.
get_importer = get_source


# Preferred and legacy class names both resolve lazily to the source class.
_CLASS_EXPORTS: dict[str, str] = {
    "GDCDownloadSource": "gdc",
    "GEODownloadSource": "geo",
    "SRADownloadSource": "sra",
    "CDADownloadSource": "cda",
    "XenaDownloadSource": "xena",
    "GDCImporter": "gdc",
    "GEOImporter": "geo",
    "SRAImporter": "sra",
    "CDAImporter": "cda",
    "XenaImporter": "xena",
}


def __getattr__(name: str):
    source = _CLASS_EXPORTS.get(name)
    if source is not None:
        # Both the preferred class and its legacy alias live in the source
        # module's namespace, so a plain attribute lookup returns either.
        module = import_module(REGISTRY[source].target.split(":", 1)[0])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "REGISTRY",
    "SourceSpec",
    "get_source",
    "get_importer",
    *sorted(_CLASS_EXPORTS),
]
