"""Registry mapping database names to importer classes."""

from __future__ import annotations

from ..base import BaseImporter
from ..errors import InputError
from .cda import CDAImporter
from .gdc import GDCImporter
from .geo import GEOImporter
from .sra import SRAImporter
from .xena import XenaImporter

_IMPORTERS: tuple[type[BaseImporter], ...] = (
    GDCImporter,
    GEOImporter,
    SRAImporter,
    CDAImporter,
    XenaImporter,
)

REGISTRY: dict[str, type[BaseImporter]] = {cls.name: cls for cls in _IMPORTERS}


def get_importer(name: str, **kwargs) -> BaseImporter:
    """Instantiate the importer registered under *name*."""
    try:
        cls = REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(REGISTRY))
        raise InputError(f"Unknown database '{name}'. Available: {available}.") from None
    return cls(**kwargs)


__all__ = [
    "REGISTRY",
    "get_importer",
    "GDCImporter",
    "GEOImporter",
    "SRAImporter",
    "CDAImporter",
    "XenaImporter",
]
