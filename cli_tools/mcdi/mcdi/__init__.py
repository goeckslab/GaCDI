"""MCDI — Multi-Commons Data Importer.

``mcdi manifest``: build a filtered GDC manifest + enriched metadata table.
``mcdi download``: download files from a GDC, PDC, or IDC manifest.
"""

import os

__version__ = "0.6.0"

# Container image build id (e.g. git SHA); empty for local/editable installs.
BUILD = os.environ.get("MCDI_BUILD", "").strip()


def version_string() -> str:
    """Return the human-readable version, including the build id when present."""
    return f"{__version__}+{BUILD}" if BUILD else __version__


__all__ = ["__version__", "BUILD", "version_string"]
