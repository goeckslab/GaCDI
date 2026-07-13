"""Compatibility shim: GDC transport now lives in :mod:`gacdi_manifest.clients.gdc`.

Re-exports the endpoint/field constants and provides the historical module-level
``count`` / ``facets`` / ``query_files`` helpers (delegating to a default
:class:`~gacdi_manifest.clients.gdc.GDCFilesClient`) so existing imports keep
working. New code should use ``GDCFilesClient`` and the GDC source directly.
"""

from __future__ import annotations

import requests

from .clients.gdc import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEOUT,
    FIELDS,
    FILES_ENDPOINT,
    SORT,
    GDCFilesClient,
    dumps_filters,
)
from .model import FileRow

_DEFAULT_CLIENT = GDCFilesClient()


def count(session: requests.Session, filters: dict) -> int:
    return _DEFAULT_CLIENT.count(session, filters)


def facets(session: requests.Session, filters: dict, fields: list[str]) -> dict:
    return _DEFAULT_CLIENT.facets(session, filters, fields)


def query_files(
    session: requests.Session,
    filters: dict,
    *,
    max_files: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    total: int | None = None,
) -> list[FileRow]:
    from .sources.gdc import _row_to_filerow

    client = _DEFAULT_CLIENT if page_size == DEFAULT_PAGE_SIZE else GDCFilesClient(page_size=page_size)
    rows = client.fetch_rows(session, filters, max_files=max_files, total=total)
    return [_row_to_filerow(row) for row in rows]


__all__ = [
    "FILES_ENDPOINT",
    "FIELDS",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_TIMEOUT",
    "SORT",
    "GDCFilesClient",
    "count",
    "facets",
    "query_files",
    "dumps_filters",
]
