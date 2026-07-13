"""SRA (Sequence Read Archive) importer.

Input mode: ``accession`` — one or more run/experiment/study accessions
(SRR/ERR/DRR, SRX, SRP…). Each accession is fetched with ``prefetch`` and then
converted to FASTQ with ``fasterq-dump`` (both from the ``sra-tools`` package).
Outputs are optionally gzip-compressed for downstream Galaxy tools.

Controlled-access (dbGaP) retrieval via an ngc/JWT cart is deferred to a later
phase.
"""

from __future__ import annotations

import gzip
import re
import shutil
from pathlib import Path

from ..auth import TokenFile
from ..base import BaseDownloadSource, RunConfig
from ..clients.sra_toolkit import SRAToolkitAdapter
from ..errors import DownloadError, InputError
from ..manifest import parse_accessions
from ..model import DownloadResult, FileEntry

_RUN_ACCESSION = re.compile(r"^[SED]R[RXPAS]\d+$", re.IGNORECASE)


def _gzip_file(path: Path) -> Path:
    """Compress *path* to ``path.gz`` and remove the original."""
    target = path.with_suffix(path.suffix + ".gz")
    with open(path, "rb") as src, gzip.open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    path.unlink(missing_ok=True)
    return target


class SRADownloadSource(BaseDownloadSource):
    name = "sra"
    supports_controlled = False
    supported_modes = ("accession",)

    def __init__(self, session=None, toolkit: SRAToolkitAdapter | None = None) -> None:
        super().__init__(session=session)
        # The toolkit adapter is injected for tests; a default is created when
        # none is supplied so existing callers stay compatible.
        self._toolkit = toolkit or SRAToolkitAdapter()

    def resolve(self, cfg: RunConfig, token: TokenFile | None) -> list[FileEntry]:
        entries = parse_accessions(cfg.accessions, source=self.name)
        for e in entries:
            if not _RUN_ACCESSION.match(e.file_id):
                raise InputError(
                    f"'{e.file_id}' does not look like an SRA accession (e.g. SRR000001)."
                )
        return entries

    def download(
        self,
        entry: FileEntry,
        dest_dir: str,
        cfg: RunConfig,
        token: TokenFile | None,
    ) -> DownloadResult:
        acc = entry.file_id
        dest = Path(dest_dir)

        self._toolkit.prefetch(acc, dest_dir)

        # prefetch writes <dest>/<acc>/<acc>.sra (or .sralite)
        sra_dir = dest / acc
        sra_file = next(iter(sra_dir.glob(f"{acc}.sra*")), None)
        source_arg = str(sra_file) if sra_file else acc

        try:
            self._toolkit.fasterq_dump(source_arg, dest_dir, threads=max(cfg.jobs, 1), accession=acc)
        finally:
            shutil.rmtree(sra_dir, ignore_errors=True)

        produced = sorted(dest.glob(f"{acc}*.fastq"))
        if not produced:
            raise DownloadError(f"fasterq-dump produced no FASTQ for {acc}.")

        paths: list[str] = []
        total = 0
        for fq in produced:
            final = _gzip_file(fq)
            paths.append(str(final))
            total += final.stat().st_size
        return DownloadResult(entry, "ok", paths=paths, bytes=total)


# Compatibility alias: the historical class name. ``SRADownloadSource`` is preferred.
SRAImporter = SRADownloadSource
