"""Registry mapping database names to builder importers (T0.2).

Mirrors the downloader's ``gacdi/importers/__init__.py``: sources self-list here,
and ``cli.py`` builds its subparsers by iterating the registry instead of
hardcoding ``gdc``.
"""

from __future__ import annotations

from .errors import InputError
from .importer import BuildImporter
from .sources.gdc import GDCImporter
from .sources.idc import IDCImporter
from .sources.pdc import PDCImporter

_IMPORTERS: tuple[type[BuildImporter], ...] = (
    GDCImporter,
    PDCImporter,
    IDCImporter,
)

REGISTRY: dict[str, type[BuildImporter]] = {cls.name: cls for cls in _IMPORTERS}


def get_importer(name: str) -> BuildImporter:
    """Instantiate the builder registered under *name*."""
    try:
        cls = REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(REGISTRY))
        raise InputError(f"Unknown database '{name}'. Available: {available}.") from None
    return cls()


__all__ = ["REGISTRY", "get_importer", "GDCImporter", "PDCImporter", "IDCImporter"]
