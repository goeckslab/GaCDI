"""Core data structures shared by every importer.

Keeping these tiny and dependency-free means importers, the download loop, and
the summary writer all speak the same vocabulary regardless of repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileEntry:
    """A single item the user asked to download.

    Depending on the repository an "entry" may be a concrete file (GDC, GEO
    supplementary file) or an accession that expands into several output files
    (an SRA run producing paired FASTQs). ``file_id`` is always the stable
    identifier used for logging and de-duplication.
    """

    file_id: str
    filename: str
    url: str | None = None
    size: int | None = None
    md5: str | None = None
    source: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class DownloadResult:
    """Outcome of attempting to download one :class:`FileEntry`.

    A single entry may yield multiple ``paths`` (e.g. paired-end FASTQ), so the
    summary writer emits one row per produced file.
    """

    entry: FileEntry
    status: str  # "ok" | "failed" | "skipped" | "planned"
    paths: list[str] = field(default_factory=list)
    bytes: int = 0
    md5: str | None = None
    message: str = ""


@dataclass
class RunSummary:
    """Aggregate result of a whole run, written to the summary TSV."""

    database: str
    results: list[DownloadResult] = field(default_factory=list)

    @property
    def ok(self) -> list[DownloadResult]:
        return [r for r in self.results if r.status == "ok"]

    @property
    def failed(self) -> list[DownloadResult]:
        return [r for r in self.results if r.status == "failed"]

    def total_bytes(self) -> int:
        return sum(r.bytes for r in self.results)
