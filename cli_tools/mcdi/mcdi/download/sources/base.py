from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

# Delimiters tried, in order, when matching a manifest's header against each
# source's schema.
CANDIDATE_DELIMITERS = ("\t", ",")

# Leading raw lines read for Source.sniff_lines (past a manifest's leading comments).
CONTENT_SNIFF_LINES = 20


def read_header(path: Path, delimiter: str) -> list[str]:
    """Read and split a manifest's header row using the given delimiter."""
    with open(path, newline="") as f:
        return next(csv.reader(f, delimiter=delimiter), [])


def read_lines(path: Path, limit: int = CONTENT_SNIFF_LINES) -> list[str]:
    """Read up to ``limit`` leading raw lines, for ``Source.sniff_lines``."""
    with open(path) as f:
        return [line for line, _ in zip(f, range(limit))]


def write_csv_subset(
    original_path: Path,
    output_path: Path,
    delimiter: str,
    key_column: str,
    keep_keys: set[str],
) -> None:
    """Re-parse ``original_path`` and write the rows whose ``key_column`` value is in
    ``keep_keys`` to ``output_path``, preserving the original header/columns and delimiter.

    Used to carve a re-parseable "retry manifest" out of a manifest a service already
    produced, rather than reconstructing rows from the fields ``FileEntry`` retains
    (which would risk dropping columns a service's format requires but mcdi doesn't use).
    """
    with open(original_path, newline="") as fin:
        reader = csv.DictReader(fin, delimiter=delimiter)
        fieldnames = reader.fieldnames or []
        rows = [row for row in reader if (row.get(key_column) or "").strip() in keep_keys]
    with open(output_path, "w", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


@dataclass
class FileEntry:
    """A single file to download, normalized across manifest formats."""

    file_id: str
    filename: str
    rel_dir: Path
    url: str
    size: Optional[int] = None
    md5: Optional[str] = None


class Source(ABC):
    """A data commons that files can be downloaded from via an exported manifest."""

    name: str

    @staticmethod
    @abstractmethod
    def sniff(header_fields: list[str]) -> bool:
        """Return True if a manifest with these header fields belongs to this source."""

    @staticmethod
    def sniff_lines(lines: list[str]) -> bool:
        """Hook for headerless formats ``sniff`` can't identify. Default: no match."""
        return False

    @abstractmethod
    def parse_manifest(self, path: Path) -> list[FileEntry]:
        """Read a manifest file and return the files it lists."""

    @abstractmethod
    def request_kwargs(self, entry: FileEntry) -> dict:
        """Extra kwargs (e.g. headers) to pass to requests.get() for this entry."""

    @abstractmethod
    def write_subset_manifest(
        self, original_manifest: Path, failed_file_ids: set[str], output_path: Path
    ) -> None:
        """Write a manifest at ``output_path``, in this source's own format, containing
        only the rows for ``failed_file_ids`` (``FileEntry.file_id`` values) from
        ``original_manifest`` — so a partial download failure can be retried by feeding
        ``output_path`` straight back into ``mcdi download``.
        """

    def rate_limit(self) -> Optional["RateLimit"]:
        """Optional pacing/rate-limit policy applied to downloads from this source."""
        return None

    def known_open(self, entries: list[FileEntry], session: requests.Session) -> set[str]:
        """``file_id``s known accessible without a per-file probe (see
        ``download.engine.check_access``). Default: none.
        """
        return set()


@dataclass
class RateLimit:
    """Simple sliding-window rate limit plus a fixed per-download pause."""

    max_per_window: int
    window_seconds: float
    per_file_sleep_seconds: float
