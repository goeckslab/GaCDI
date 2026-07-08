"""HTTP download utilities shared by importers that pull over HTTP(S)/FTP.

A single retrying :class:`requests.Session` plus a streamed, checksum-verifying
downloader means every importer gets the same robustness for free, and unit
tests can inject a fake session so no test touches the network.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import ChecksumError, DownloadError

log = logging.getLogger("gacdi.net")

DEFAULT_CHUNK = 1 << 20  # 1 MiB
DEFAULT_TIMEOUT = 60


def build_session(retries: int = 5, backoff: float = 0.5) -> requests.Session:
    """Return a session that retries transient errors with exponential backoff."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


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
