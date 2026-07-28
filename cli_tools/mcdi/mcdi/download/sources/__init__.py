from __future__ import annotations

from pathlib import Path

from ...errors import InputError
from .base import CANDIDATE_DELIMITERS, FileEntry, RateLimit, Source, read_header, read_lines
from .gdc import GDCSource
from .idc import IDCSource
from .pdc import PDCSource

SOURCES: dict[str, type[Source]] = {
    GDCSource.name: GDCSource,
    PDCSource.name: PDCSource,
    IDCSource.name: IDCSource,
}


def detect_source(path: Path) -> str:
    """Identify which data commons a manifest came from by matching its header
    row, under each candidate delimiter, against every registered source's
    schema (``Source.sniff``), or - for headerless formats - its leading raw
    lines (``Source.sniff_lines``)."""
    lines = read_lines(path)
    matches = [
        name
        for name, cls in SOURCES.items()
        if any(cls.sniff(read_header(path, d)) for d in CANDIDATE_DELIMITERS) or cls.sniff_lines(lines)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise InputError(
            f"Manifest header matches multiple sources ({matches}); pass --source explicitly."
        )
    raise InputError(
        f"Could not detect data commons from manifest header "
        f"{read_header(path, CANDIDATE_DELIMITERS[0])!r}; pass --source explicitly."
    )


__all__ = [
    "FileEntry", "RateLimit", "Source", "GDCSource", "PDCSource", "IDCSource", "SOURCES", "detect_source",
]
