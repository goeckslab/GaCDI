"""GDC transport: the files-query API client and the gdc-client tool adapter.

The HTTP client owns the ``/files`` REST conversation (request construction,
pagination, HTTP error translation) and yields raw hit dicts. The tool adapter
owns locating and running the external ``gdc-client`` binary and translating its
process failures. The source (:mod:`gacdi.sources.gdc`) owns selection
resolution, validation, and mapping hits/outputs into GaCDI objects.
"""

from __future__ import annotations

import subprocess
from typing import Iterator

import requests

from ..errors import DownloadError
from ..proc import require, run

API_FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"
DEFAULT_QUERY_FIELDS = "file_id,file_name,md5sum,file_size"
# Files fetched per request when paging a query. The client pages through *all*
# matching files regardless of this value; it only controls request granularity.
DEFAULT_PAGE_SIZE = 500


class GDCFilesApiClient:
    """HTTP client for the GDC ``/files`` query endpoint."""

    def __init__(self, *, endpoint: str = API_FILES_ENDPOINT, timeout: int = 60) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    def iter_hits(
        self,
        session: requests.Session,
        *,
        filters: dict,
        fields: str = DEFAULT_QUERY_FIELDS,
        page_size: int = DEFAULT_PAGE_SIZE,
        endpoint: str | None = None,
    ) -> Iterator[dict]:
        """Yield raw hit dicts for *filters*, paging through every matching file."""
        endpoint = endpoint or self.endpoint
        start, total, seen = 0, None, 0
        while True:
            payload = {
                "filters": filters,
                "fields": fields,
                "format": "JSON",
                "sort": "file_id:asc",
                "size": page_size,
                "from": start,
            }
            resp = session.post(endpoint, json=payload, timeout=self.timeout)
            if resp.status_code >= 400:
                raise DownloadError(f"GDC API returned HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json().get("data", {})
            hits = data.get("hits", [])
            yield from hits
            seen += len(hits)
            if total is None:
                try:
                    total = int(data.get("pagination", {}).get("total", seen))
                except (TypeError, ValueError):
                    total = seen
            start += len(hits)
            if not hits or start >= total:
                break


class GDCClientTool:
    """Adapter around the external ``gdc-client`` download binary."""

    def __init__(self, binary: str = "gdc-client") -> None:
        self.binary = binary

    def download(self, file_id: str, dest_dir: str, token: object | None = None) -> None:
        """Run ``gdc-client download`` for *file_id* into *dest_dir*."""
        gdc = require(self.binary)
        cmd = [gdc, "download", file_id, "-d", dest_dir]
        if token is not None:
            cmd += ["-t", str(token)]
        try:
            run(cmd, secret_flags=("-t",))
        except subprocess.CalledProcessError as exc:
            raise DownloadError(
                f"gdc-client failed for {file_id}: {(exc.stderr or '').strip()[:300]}"
            ) from exc


__all__ = [
    "API_FILES_ENDPOINT",
    "DEFAULT_QUERY_FIELDS",
    "DEFAULT_PAGE_SIZE",
    "GDCFilesApiClient",
    "GDCClientTool",
]
