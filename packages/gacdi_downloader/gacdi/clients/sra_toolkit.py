"""SRA Toolkit adapter: locate and run ``prefetch`` / ``fasterq-dump``.

Owns finding the external sra-tools binaries and running them, translating
process failures into :class:`~gacdi.errors.DownloadError`. The source
(:mod:`gacdi.sources.sra`) owns accession policy, the ``.sra`` file location, and
mapping the produced FASTQ into GaCDI results.
"""

from __future__ import annotations

import subprocess

from ..errors import DownloadError
from ..proc import require, run


class SRAToolkitAdapter:
    """Adapter around the sra-tools ``prefetch`` and ``fasterq-dump`` binaries."""

    def __init__(self, *, prefetch_binary: str = "prefetch", fasterq_binary: str = "fasterq-dump") -> None:
        self.prefetch_binary = prefetch_binary
        self.fasterq_binary = fasterq_binary

    def prefetch(self, accession: str, dest_dir: str) -> None:
        """Run ``prefetch`` for *accession* into *dest_dir*."""
        prefetch = require(self.prefetch_binary)
        try:
            run([prefetch, accession, "-O", dest_dir])
        except subprocess.CalledProcessError as exc:
            raise DownloadError(
                f"prefetch failed for {accession}: {(exc.stderr or '').strip()[:300]}"
            ) from exc

    def fasterq_dump(self, source_arg: str, dest_dir: str, *, threads: int = 1, accession: str = "") -> None:
        """Run ``fasterq-dump`` on *source_arg* into *dest_dir*."""
        fasterq = require(self.fasterq_binary)
        try:
            run([fasterq, source_arg, "-O", dest_dir, "-e", str(max(threads, 1))])
        except subprocess.CalledProcessError as exc:
            raise DownloadError(
                f"fasterq-dump failed for {accession or source_arg}: "
                f"{(exc.stderr or '').strip()[:300]}"
            ) from exc


__all__ = ["SRAToolkitAdapter"]
