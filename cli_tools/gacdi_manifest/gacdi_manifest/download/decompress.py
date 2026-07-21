"""Normalise gzip-compressed commons payloads into forms Galaxy can type.

The data commons publish several formats gzipped: PDC ships ``.mzML.gz`` and
``.mzid.gz``, GDC ships ``.txt.gz`` and friends. Galaxy's ``mzml``/``mzid``
datatypes describe uncompressed XML, so a gzipped download cannot be handed to
msconvert, Comet, MS-GF+, or the OpenMS suite without an intervening conversion
step. Expanding them here keeps the collection pipeline-ready.

Decompression is driven by an allow-list of *inner* extensions rather than by
sniffing magic bytes, and that is deliberate. BAM, BGZF-compressed VCF, and
tabix indexes all carry the gzip magic number while being meaningless once
expanded -- Galaxy models them as their own compressed datatypes. Matching on
the inner extension keeps those files untouched.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
from pathlib import Path

from ..errors import DownloadError

log = logging.getLogger("gacdi_manifest.download.decompress")

CHUNK_SIZE = 1024 * 1024

#: Inner extensions that are plain text or XML once expanded, and whose
#: uncompressed form is the one Galaxy datatypes and downstream tools expect.
EXPANDABLE_INNER_SUFFIXES = frozenset(
    {
        ".csv",
        ".maf",
        ".mgf",
        ".mzid",
        ".mzml",
        ".mzq",
        ".mzxml",
        ".pepxml",
        ".protxml",
        ".psm",
        ".sf",
        ".tsv",
        ".txt",
        ".xml",
    }
)

#: Inner extensions that must never be expanded even though the container is
#: gzip. These are compressed-by-design formats with their own Galaxy datatypes.
PROTECTED_INNER_SUFFIXES = frozenset(
    {
        ".bam",
        ".bcf",
        ".bed",
        ".bigwig",
        ".cram",
        ".fasta",
        ".fastq",
        ".gff",
        ".gtf",
        ".sam",
        ".tbi",
        ".vcf",
    }
)


def expanded_name(path: Path) -> Path:
    """Return the path ``path`` will occupy once its ``.gz`` suffix is removed."""
    return path.with_name(path.stem)


def should_expand(path: Path) -> bool:
    """Return whether ``path`` is a gzip file worth expanding for Galaxy."""
    if path.suffix.lower() != ".gz":
        return False
    inner = Path(path.stem).suffix.lower()
    if inner in PROTECTED_INNER_SUFFIXES:
        return False
    return inner in EXPANDABLE_INNER_SUFFIXES


def expand_gzip(path: Path) -> Path:
    """Expand ``path`` in place, remove the archive, and return the new path.

    The archive is only unlinked once the expanded copy is durably in position,
    so an interrupted run leaves the verified download intact.
    """
    target = expanded_name(path)
    partial = target.with_name(target.name + ".partial")
    try:
        with gzip.open(path, "rb") as source, partial.open("wb") as destination:
            shutil.copyfileobj(source, destination, CHUNK_SIZE)
    except (OSError, EOFError) as exc:
        partial.unlink(missing_ok=True)
        raise DownloadError(
            f"Could not expand {path.name!r}; the download may be truncated or not gzip: {exc}"
        ) from exc
    os.replace(partial, target)
    path.unlink(missing_ok=True)
    log.info("Expanded %s to %s.", path.name, target.name)
    return target


def expand_directory(outdir: str | Path) -> int:
    """Expand every eligible gzip file beneath ``outdir``; return the count."""
    expanded = 0
    for path in sorted(Path(outdir).rglob("*.gz")):
        if path.is_file() and should_expand(path):
            expand_gzip(path)
            expanded += 1
    return expanded
