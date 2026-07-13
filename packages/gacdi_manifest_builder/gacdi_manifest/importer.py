"""Compatibility shim: canonical base class is :mod:`gacdi_manifest.base`.

``BaseManifestSource`` is the preferred internal name; ``BuildImporter`` is
retained here so existing ``from gacdi_manifest.importer import BuildImporter``
imports keep working.
"""

from __future__ import annotations

from .base import BaseManifestSource, BuildImporter

__all__ = ["BaseManifestSource", "BuildImporter"]
