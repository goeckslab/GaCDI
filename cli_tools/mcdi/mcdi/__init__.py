"""MCDI — Multi-Commons Data Importer.

One command, two subcommands:

- ``mcdi manifest`` (:mod:`mcdi.manifest`): filter-driven generation of
  download manifests (and enriched metadata tables) for NIH/NCI cancer data
  repositories, starting with the NCI Genomic Data Commons (GDC). The builder
  emits a deliberate *two-file split*: a lean, CLI/importer-ready manifest
  (``id/filename/md5/size/state``) and a rich metadata table joining
  clinical/molecular annotations by barcode, plus a match report so selections
  and joins are never silently wrong.
- ``mcdi download`` (:mod:`mcdi.download`): downloads the files listed
  in a GDC or PDC manifest, auto-detecting which commons it came from.
"""

import os

__version__ = "0.4.0"

# Build identifier baked into the container image at build time (e.g. the git
# commit SHA). Lets you confirm the exact code a run used, even when the version
# number hasn't changed. Empty for local/editable installs.
BUILD = os.environ.get("MCDI_BUILD", "").strip()


def version_string() -> str:
    """Return the human-readable version, including the build id when present."""
    return f"{__version__}+{BUILD}" if BUILD else __version__


__all__ = ["__version__", "BUILD", "version_string"]
