"""Cancer Data Aggregator (CDA) importer.

CDA is a cross-commons *search* layer over GDC, PDC, IDC and CDS. This importer
runs a CDA ``file`` query and produces a normalised **manifest/metadata table**
(the summary output) describing every matching file — which commons owns it, its
identifier, size, checksum and DRS URI. That table can be fed straight into the
GDC/IDC/PDC importers to retrieve the bytes.

Where a file exposes a directly resolvable ``https`` URL it is also downloaded
into the collection; files that require commons-specific or cloud (ISB-CGC)
access are reported as *skipped* with the identifier needed to fetch them.

Input mode: ``query`` — a JSON document of keyword arguments for cdapython's
``fetch_rows`` (e.g. ``{"table": "file", "match_all": ["file_format = BAM"]}``).
"""

from __future__ import annotations

from pathlib import Path

from ..auth import TokenFile
from ..base import BaseDownloadSource, RunConfig
from ..errors import DependencyError, InputError
from ..history import unique_path
from ..manifest import load_query
from ..model import DownloadResult, FileEntry
from ..net import stream_download


def _fetch_rows(**kwargs) -> list[dict]:
    """Call cdapython.fetch_rows and normalise the result to a list of dicts.

    Imported lazily so the package works without cdapython installed; it is only
    required at runtime for the CDA tool (provided by the gacdi-cda container).
    """
    try:
        from cdapython import fetch_rows  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via container only
        raise DependencyError(
            "The 'cdapython' package is required for the CDA importer. It is "
            "provided by the GaCDI CDA container image."
        ) from exc
    result = fetch_rows(**kwargs)
    if hasattr(result, "to_dict"):  # pandas DataFrame
        return result.to_dict("records")
    return list(result)


def _first(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None


def row_to_entry(row: dict) -> FileEntry:
    """Map a CDA file row into a :class:`FileEntry` tolerant of schema drift."""
    file_id = _first(row, "file_id", "id", "File.id") or ""
    drs = _first(row, "drs_uri", "drs_url", "File.drs_uri")
    commons = _first(row, "data_source", "File.data_source", "data_category")
    if isinstance(commons, (list, tuple)):
        commons = ",".join(str(c) for c in commons)
    size = _first(row, "byte_size", "size", "File.byte_size")
    return FileEntry(
        file_id=str(file_id),
        filename=str(_first(row, "label", "file_name", "File.label") or file_id or "cda_file"),
        url=drs if isinstance(drs, str) and drs.startswith("https://") else None,
        size=int(size) if str(size).isdigit() else None,
        md5=_first(row, "checksum", "md5", "File.checksum"),
        source=str(commons) if commons else "cda",
        extra={"drs_uri": drs, "commons": commons},
    )


class CDADownloadSource(BaseDownloadSource):
    name = "cda"
    supports_controlled = False
    supported_modes = ("query",)

    def resolve(self, cfg: RunConfig, token: TokenFile | None) -> list[FileEntry]:
        query = load_query(cfg.query_json)
        table = query.pop("table", "file")
        rows = _fetch_rows(table=table, **query)
        entries = [row_to_entry(r) for r in rows if r]
        if not entries:
            raise InputError("CDA query matched no files.")
        return entries

    def download(
        self,
        entry: FileEntry,
        dest_dir: str,
        cfg: RunConfig,
        token: TokenFile | None,
    ) -> DownloadResult:
        if entry.url:  # directly resolvable https DRS access URL
            target = unique_path(Path(dest_dir), entry.filename)
            written = stream_download(self.session, entry.url, target, expected_md5=entry.md5)
            return DownloadResult(entry, "ok", paths=[str(target)], bytes=written)
        commons = entry.extra.get("commons") or "the owning commons"
        return DownloadResult(
            entry,
            "skipped",
            message=(
                f"No direct URL; retrieve via the {commons} importer using "
                f"file_id {entry.file_id} (see the summary manifest)."
            ),
        )


# Compatibility alias: the historical class name. ``CDADownloadSource`` is preferred.
CDAImporter = CDADownloadSource
