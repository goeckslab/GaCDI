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


def read_header(path: Path, delimiter: str) -> list[str]:
    """Read and split a manifest's header row using the given delimiter."""
    with open(path, newline="") as f:
        return next(csv.reader(f, delimiter=delimiter), [])


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

    @abstractmethod
    def parse_manifest(self, path: Path) -> list[FileEntry]:
        """Read a manifest file and return the files it lists."""

    @abstractmethod
    def request_kwargs(self, entry: FileEntry) -> dict:
        """Extra kwargs (e.g. headers) to pass to requests.get() for this entry."""

    def rate_limit(self) -> Optional["RateLimit"]:
        """Optional pacing/rate-limit policy applied to downloads from this source."""
        return None

    def known_open(self, entries: list[FileEntry], session: requests.Session) -> set[str]:
        """Best-effort ``file_id``s known accessible without a per-file network probe.

        Lets a source short-circuit the pre-flight access check (see
        ``download.engine.check_access``) for entries it can already vouch
        for cheaply, e.g. via a single bulk metadata query. Default: none,
        so every entry gets individually probed.
        """
        return set()


@dataclass
class RateLimit:
    """Simple sliding-window rate limit plus a fixed per-download pause."""

    max_per_window: int
    window_seconds: float
    per_file_sleep_seconds: float
