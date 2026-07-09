"""GaCDI Manifest Builder.

Filter-driven generation of download manifests (and enriched metadata tables) for
NIH/NCI cancer data repositories, starting with the NCI Genomic Data Commons (GDC).

The builder emits a deliberate *two-file split*:

- a lean, CLI/importer-ready manifest (``id/filename/md5/size/state``), and
- a rich metadata table joining clinical/molecular annotations by barcode,

plus a match report so selections and joins are never silently wrong.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
