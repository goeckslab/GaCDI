"""Identify which NCI data commons produced a download manifest."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from ..errors import AmbiguousManifestError, UnknownManifestError

log = logging.getLogger("gacdi_manifest.download")

GDC_REQUIRED = {"id", "filename", "md5", "size"}
GDC_STANDARD = GDC_REQUIRED | {"state"}
PDC_SIGNALS = {
    "file id",
    "file name",
    "md5sum",
    "pdc study id",
    "study id",
    "file download link",
    "file download url",
    "signed url",
    "run metadata id",
}
PDC_MIN_SIGNALS = 2
PDC_FILENAME_SIGNALS = {"file name", "filename"}
PDC_URL_SIGNALS = {"file download link", "file download url", "signed url"}

_SEPARATORS = re.compile(r"[\s_]+")


def normalize_header(value: object) -> str:
    """Make portal header spelling, case, and whitespace variations equivalent."""
    return _SEPARATORS.sub(" ", str(value or "").strip().lower())


def sniff_delimiter(header_line: str) -> str:
    """Return comma or tab, with a deterministic fallback for short headers."""
    try:
        return csv.Sniffer().sniff(header_line, delimiters="\t,").delimiter
    except csv.Error:
        return "\t" if header_line.count("\t") > header_line.count(",") else ","


def read_header(path: str | Path) -> tuple[str, list[str], str]:
    """Return the first non-blank header line, parsed cells, and delimiter."""
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            header_line = next((line for line in handle if line.strip()), "")
    except (OSError, UnicodeError) as exc:
        raise UnknownManifestError(f"Could not read manifest {path!s}: {exc}") from exc

    if not header_line:
        raise UnknownManifestError(
            "The manifest is empty. A GDC manifest needs id/filename/md5/size columns; "
            "a PDC file manifest needs File Name and File Download Link columns."
        )

    delimiter = sniff_delimiter(header_line)
    try:
        columns = next(csv.reader([header_line], delimiter=delimiter))
    except csv.Error as exc:
        raise UnknownManifestError(f"Could not parse the manifest header: {exc}") from exc
    return header_line, columns, delimiter


def _shape_message(columns: list[str]) -> str:
    observed = ", ".join(repr(column.strip()) for column in columns)
    return (
        f"Observed columns [{observed}]. A GDC manifest needs id/filename/md5/size "
        "(normally also state); a PDC file manifest needs File Name plus File Download "
        "Link and normally includes File ID/Md5sum/File Size (in bytes)."
    )


def detect_source(path: str | Path) -> str:
    """Return ``gdc`` or ``pdc``; refuse unknown or ambiguous headers."""
    _, columns, _ = read_header(path)
    header_set = {normalize_header(column) for column in columns if normalize_header(column)}
    is_gdc = GDC_REQUIRED <= header_set
    is_pdc = (
        len(PDC_SIGNALS & header_set) >= PDC_MIN_SIGNALS
        and bool(PDC_FILENAME_SIGNALS & header_set)
        and bool(PDC_URL_SIGNALS & header_set)
    )

    if is_gdc and is_pdc:
        raise AmbiguousManifestError(
            "The manifest header matches both GDC and PDC detection rules. " + _shape_message(columns)
        )
    if not is_gdc and not is_pdc:
        raise UnknownManifestError(
            "The manifest header does not match a supported GDC or PDC file manifest. "
            + _shape_message(columns)
        )
    if is_gdc:
        extras = header_set - GDC_STANDARD
        if extras:
            log.warning(
                "GDC manifest has extra column(s) that gdc-client may reject: %s",
                ", ".join(sorted(extras)),
            )
        return "gdc"
    return "pdc"
