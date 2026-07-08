"""Staging downloaded files for Galaxy and writing the run summary.

Downloaded files are placed into an output directory that a Galaxy tool scans
with ``<discover_datasets pattern="__name_and_ext__">`` to build a list
collection. A separate TSV summarises every file for provenance.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .model import RunSummary

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_output_dir(path: str | Path) -> Path:
    """Create and return the collection output directory."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str) -> str:
    """Return a filesystem/Galaxy-safe version of *name*.

    Galaxy's ``__name_and_ext__`` discovery splits the trailing extension off the
    element identifier, so we keep dots but replace anything unusual.
    """
    cleaned = _SAFE.sub("_", name.strip()).strip("._-")
    return cleaned or "dataset"


def unique_path(directory: Path, name: str) -> Path:
    """Return a non-colliding path in *directory* for *name*."""
    base = safe_filename(name)
    candidate = directory / base
    if not candidate.exists():
        return candidate
    stem, dot, ext = base.partition(".")
    i = 1
    while True:
        alt = f"{stem}_{i}{dot}{ext}" if dot else f"{stem}_{i}"
        candidate = directory / alt
        if not candidate.exists():
            return candidate
        i += 1


SUMMARY_COLUMNS = [
    "database",
    "file_id",
    "filename",
    "status",
    "size_bytes",
    "md5",
    "source",
    "message",
]


def write_summary(path: str | Path, summary: RunSummary) -> None:
    """Write one TSV row per produced file (or per entry if none)."""
    with Path(path).open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(SUMMARY_COLUMNS)
        for res in summary.results:
            e = res.entry
            rows = res.paths or [""]
            for produced in rows:
                fname = Path(produced).name if produced else e.filename
                writer.writerow(
                    [
                        summary.database,
                        e.file_id,
                        fname,
                        res.status,
                        res.bytes if produced else (e.size or ""),
                        res.md5 or e.md5 or "",
                        e.source or summary.database,
                        res.message,
                    ]
                )
