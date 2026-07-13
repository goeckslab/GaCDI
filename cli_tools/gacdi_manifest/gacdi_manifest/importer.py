"""Builder-side importer interface (T0.2).

Parallel to the downloader's ``gacdi/base.py`` (see NOTES §8.2), but for the
*builder* half. A :class:`BuildImporter` owns the source-specific work — define
CLI flags, turn requirements into a native query, count/preview, and fetch
records as :class:`~gacdi_manifest.model.FileRow` objects. The shared runner in
:mod:`gacdi_manifest.cli` owns everything that is the same for every source:
the annotation join, the post-query metadata filter, and writing the
manifest / metadata / report.

Each source lives in ``sources/<name>.py`` and is listed in
:mod:`gacdi_manifest.registry`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import requests

from .model import FileRow, ManifestRow


class BuildImporter(ABC):
    """Base class for all manifest-*builder* sources."""

    #: registry key / CLI subcommand, e.g. ``"gdc"``.
    name: str = ""
    #: one-line help shown for the subcommand.
    help: str = ""
    #: which manifest to emit: ``"gdc"`` = strict id/filename/md5/size/state (for
    #: gdc-client); ``"source"`` = the multi-source §4.1 schema via to_manifest_rows.
    manifest_dialect: str = "gdc"

    def add_arguments(self, parser) -> None:
        """Add this source's query flags to its subparser (optional)."""

    def to_manifest_rows(self, file_rows: list[FileRow]) -> list[ManifestRow]:
        """Map fetched files to §4.1 ManifestRow (only for ``manifest_dialect='source'``)."""
        raise NotImplementedError(f"{self.name} does not implement to_manifest_rows")

    def harmonize(self, row: dict) -> dict:
        """Best-effort map of a metadata row's native fields to harmonized-core columns.

        Called per merged metadata row; return ``{column: value}`` overrides for empty
        harmonized columns. GDC returns ``{}`` (its join already fills the core); other
        sources map from their passthrough columns.
        """
        return {}

    @abstractmethod
    def build_query(self, args) -> object:
        """Translate parsed CLI args into a native query object."""

    @abstractmethod
    def provenance(self, query: object) -> dict:
        """Return a provenance record: source, endpoint, query, version, UTC."""

    @abstractmethod
    def count(self, session: requests.Session, query: object) -> int:
        """Return how many files match *query*."""

    def facets(self, session: requests.Session, query: object) -> dict:
        """Return facet counts for a count-only preview (optional)."""
        return {}

    @abstractmethod
    def fetch(
        self,
        session: requests.Session,
        query: object,
        *,
        max_files: int | None = None,
        total: int | None = None,
    ) -> list[FileRow]:
        """Fetch matching files as :class:`FileRow` records (paged)."""
