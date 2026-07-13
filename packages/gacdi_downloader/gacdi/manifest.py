"""Parsing of the three input modes shared across importers.

- ``manifest``  : a repository manifest file (GDC/CRDC-style TSV, or a plain
                  accession list) → list of :class:`FileEntry`.
- ``accession`` : a comma/whitespace/newline separated list of accessions.
- ``query``     : a JSON document describing a portal query (importer-specific).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .errors import InputError
from .model import FileEntry

# Columns of a GDC / CRDC "GDC-style" manifest.
_GDC_COLUMNS = {"id", "filename", "md5", "size"}


def parse_accessions(value: str | None, *, source: str = "") -> list[FileEntry]:
    """Split a free-form accession string into de-duplicated entries.

    Accepts commas, whitespace and newlines as separators. The accession is used
    as both ``file_id`` and (provisional) ``filename``; importers refine the
    filename once they know the produced output.
    """
    if not value:
        raise InputError("No accessions were provided.")
    tokens = [t for t in re.split(r"[\s,]+", value.strip()) if t]
    seen: dict[str, None] = {}
    for tok in tokens:
        seen.setdefault(tok, None)
    if not seen:
        raise InputError("No accessions were provided.")
    return [FileEntry(file_id=a, filename=a, source=source) for a in seen]


def parse_gdc_manifest(path: str | Path, *, source: str = "gdc") -> list[FileEntry]:
    """Parse a GDC-style TSV manifest into :class:`FileEntry` objects."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"Manifest file not found: {path}")

    with p.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        header = {c.strip().lower() for c in (reader.fieldnames or [])}
        if not _GDC_COLUMNS.issubset(header):
            missing = ", ".join(sorted(_GDC_COLUMNS - header))
            raise InputError(
                f"Manifest is missing required GDC column(s): {missing}. "
                f"Found columns: {', '.join(reader.fieldnames or []) or '(none)'}"
            )
        entries: list[FileEntry] = []
        for row in reader:
            norm = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            if not norm.get("id"):
                continue
            size = norm.get("size")
            entries.append(
                FileEntry(
                    file_id=norm["id"],
                    filename=norm.get("filename") or norm["id"],
                    md5=norm.get("md5") or None,
                    size=int(size) if size and size.isdigit() else None,
                    source=source,
                )
            )
    if not entries:
        raise InputError("Manifest contained no usable rows.")
    return entries


def load_query(path: str | Path) -> dict:
    """Load a JSON query document used by ``--input-mode query``."""
    p = Path(path)
    if not p.is_file():
        raise InputError(f"Query file not found: {path}")
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise InputError(f"Query file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("Query file must contain a JSON object.")
    return data
