"""HTTP download utilities shared by importers that pull over HTTP(S)/FTP.

The retrying :func:`build_session` constructor is shared with the builder and now
lives in :mod:`gacdi_core.net`; it is re-exported here so existing
``from gacdi.net import build_session`` imports keep working. The streamed,
checksum-verifying downloader below is downloader-specific and stays here.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import requests

from gacdi_core.net import build_session  # noqa: F401 - re-exported for compatibility

from .errors import ChecksumError, DownloadError

log = logging.getLogger("gacdi.net")

DEFAULT_CHUNK = 1 << 20  # 1 MiB
DEFAULT_TIMEOUT = 60


def md5sum(path: str | os.PathLike, chunk: int = DEFAULT_CHUNK) -> str:
    """Return the hex MD5 digest of the file at *path*."""
    h = hashlib.md5()  # noqa: S324 - MD5 is the checksum GDC/NCBI publish, not for security
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def stream_download(
    session: requests.Session,
    url: str,
    dest: str | os.PathLike,
    *,
    expected_md5: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    chunk: int = DEFAULT_CHUNK,
) -> int:
    """Stream *url* to *dest*, returning the number of bytes written.

    Writes to a ``.part`` sidecar and atomically renames on success so an
    interrupted download never leaves a truncated file discoverable by Galaxy.
    Raises :class:`DownloadError` / :class:`ChecksumError` on failure.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    try:
        with session.get(url, stream=True, timeout=timeout) as resp:
            if resp.status_code >= 400:
                raise DownloadError(f"HTTP {resp.status_code} for {url}")
            written = 0
            with open(tmp, "wb") as fh:
                for block in resp.iter_content(chunk_size=chunk):
                    if block:
                        fh.write(block)
                        written += len(block)
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"Failed to download {url}: {exc}") from exc

    if expected_md5:
        actual = md5sum(tmp)
        if actual.lower() != expected_md5.lower():
            tmp.unlink(missing_ok=True)
            raise ChecksumError(
                f"Checksum mismatch for {dest.name}: expected {expected_md5}, got {actual}"
            )

    tmp.replace(dest)
    log.info("downloaded %s (%d bytes)", dest.name, written)
    return written


__all__ = ["build_session", "md5sum", "stream_download", "DEFAULT_CHUNK", "DEFAULT_TIMEOUT"]
