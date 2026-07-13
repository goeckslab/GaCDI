"""GEO (Gene Expression Omnibus) importer.

Input mode: ``accession`` — one or more GSE/GSM accessions. For each accession we
enumerate the files in its NCBI ``suppl/`` directory and download them over
HTTPS. Metadata-only retrieval (via E-utilities/GEOquery) is deferred to a later
phase; this covers the common "give me the supplementary files" need.
"""

from __future__ import annotations

from pathlib import Path

from ..auth import TokenFile
from ..base import BaseDownloadSource, RunConfig
from ..clients.geo import FTP_BASE, GEODirectoryClient, suppl_dir_url
from ..errors import DownloadError, InputError
from ..history import unique_path
from ..manifest import parse_accessions
from ..model import DownloadResult, FileEntry
from ..net import stream_download

# Re-exported for compatibility; the canonical helpers live in clients.geo.
__all__ = ["FTP_BASE", "suppl_dir_url", "GEODownloadSource", "GEOImporter"]


class GEODownloadSource(BaseDownloadSource):
    name = "geo"
    supports_controlled = False
    supported_modes = ("accession",)

    def __init__(self, session=None, client: GEODirectoryClient | None = None) -> None:
        super().__init__(session=session)
        # The transport client is injected for tests; a default is created when
        # none is supplied so existing callers stay compatible.
        self._client = client or GEODirectoryClient()

    def resolve(self, cfg: RunConfig, token: TokenFile | None) -> list[FileEntry]:
        accessions = parse_accessions(cfg.accessions, source=self.name)
        entries: list[FileEntry] = []
        for acc in accessions:
            entries.extend(self._list_suppl_files(acc.file_id))
        if not entries:
            raise InputError("No supplementary files found for the given GEO accession(s).")
        return entries

    def _list_suppl_files(self, accession: str) -> list[FileEntry]:
        url, names = self._client.list_filenames(self.session, accession)
        return [
            FileEntry(
                file_id=accession,
                filename=name,
                url=url + name,
                source=self.name,
            )
            for name in names
        ]

    def download(
        self,
        entry: FileEntry,
        dest_dir: str,
        cfg: RunConfig,
        token: TokenFile | None,
    ) -> DownloadResult:
        if not entry.url:
            raise DownloadError(f"No URL resolved for {entry.file_id}/{entry.filename}.")
        target = unique_path(Path(dest_dir), entry.filename)
        written = stream_download(
            self.session, entry.url, target, expected_md5=entry.md5
        )
        return DownloadResult(entry, "ok", paths=[str(target)], bytes=written)


# Compatibility alias: the historical class name. ``GEODownloadSource`` is preferred.
GEOImporter = GEODownloadSource
