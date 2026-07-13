"""GEO supplementary-directory transport client.

Owns the NCBI GEO requests and native response validation: building the
``suppl/`` directory URL for a GSE/GSM accession, fetching that directory over
HTTPS, and parsing the HTML listing into supplementary filenames. The source
(:mod:`gacdi.sources.geo`) owns accession expansion and mapping filenames into
:class:`~gacdi.model.FileEntry` objects.
"""

from __future__ import annotations

import re

import requests

from ..errors import DownloadError, InputError

FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/geo"
_HREF = re.compile(r'href="([^"?/][^"]*)"', re.IGNORECASE)
_ACCESSION = re.compile(r"^(GSE|GSM)\d+$", re.IGNORECASE)


def suppl_dir_url(accession: str) -> str:
    """Return the NCBI ``suppl/`` directory URL for a GSE/GSM accession."""
    acc = accession.upper()
    if not _ACCESSION.match(acc):
        raise InputError(f"Unsupported GEO accession: {accession} (expected GSE#/GSM#).")
    prefix, digits = acc[:3], acc[3:]
    stub = f"{prefix}{digits[:-3]}nnn" if len(digits) > 3 else f"{prefix}nnn"
    kind = "series" if prefix == "GSE" else "samples"
    return f"{FTP_BASE}/{kind}/{stub}/{acc}/suppl/"


class GEODirectoryClient:
    """Fetches and parses a GEO accession's supplementary directory listing."""

    def __init__(self, *, timeout: int = 60) -> None:
        self.timeout = timeout

    def suppl_dir_url(self, accession: str) -> str:
        return suppl_dir_url(accession)

    def list_filenames(self, session: requests.Session, accession: str) -> tuple[str, list[str]]:
        """Return ``(directory_url, filenames)`` for *accession* (order-preserving, deduped)."""
        url = suppl_dir_url(accession)
        resp = session.get(url, timeout=self.timeout)
        if resp.status_code >= 400:
            raise DownloadError(
                f"Could not list GEO directory for {accession} (HTTP {resp.status_code})."
            )
        names = [n for n in _HREF.findall(resp.text) if not n.startswith("..")]
        seen: dict[str, None] = {}
        for name in names:
            seen.setdefault(name, None)
        return url, list(seen)


__all__ = ["FTP_BASE", "suppl_dir_url", "GEODirectoryClient"]
