"""Streaming, integrity-checking downloader for PDC file manifests."""

from __future__ import annotations

import csv
import hashlib
import itertools
import logging
import os
import re
from pathlib import Path
from typing import Iterable

import requests

from ..errors import DownloadError
from ..net import DEFAULT_TIMEOUT, build_session
from .decompress import expand_gzip, expanded_name, should_expand
from .detect import normalize_header, read_header

log = logging.getLogger("gacdi_manifest.download.pdc")

CHUNK_SIZE = 1024 * 1024
FILENAME_COLUMNS = ("file name", "filename", "file")
URL_COLUMNS = (
    "file download link",
    "file download url",
    "signed url",
    "url",
)
MD5_COLUMNS = ("md5sum", "md5", "file md5sum")
SIZE_COLUMNS = ("file size (in bytes)", "file size in bytes", "file size", "size")
ID_COLUMNS = ("file id", "id")


def _value(row: dict[str, str], aliases: Iterable[str]) -> str:
    for alias in aliases:
        value = row.get(alias, "")
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _safe_filename(value: str) -> str:
    if not value or "/" in value or "\\" in value or ".." in value or "\x00" in value:
        raise DownloadError(f"Unsafe PDC file name {value!r}; file names must be flat paths.")
    if value in {".", ".."}:
        raise DownloadError(f"Unsafe PDC file name {value!r}; file names must be flat paths.")
    return value


def _deduplicated_name(filename: str, file_id: str, used: set[str]) -> str:
    if filename not in used:
        used.add(filename)
        return filename
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", file_id).strip("._") or "duplicate"
    path = Path(filename)
    candidate = f"{path.stem}__{safe_id}{path.suffix}"
    counter = 2
    while candidate in used:
        candidate = f"{path.stem}__{safe_id}_{counter}{path.suffix}"
        counter += 1
    used.add(candidate)
    log.warning("Duplicate PDC file name %r will be saved as %r.", filename, candidate)
    return candidate


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # nosec B324 - manifest integrity, not cryptographic security
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalised_rows(manifest: str | Path):
    header_line, _, delimiter = read_header(manifest)
    with Path(manifest).open(encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            if line.strip():
                break
        reader = csv.DictReader(itertools.chain([header_line], handle), delimiter=delimiter)
        for raw_row in reader:
            yield {normalize_header(key): value for key, value in raw_row.items() if key is not None}


def _http_error(response: requests.Response, filename: str) -> DownloadError:
    body = response.content[:8192].decode("utf-8", errors="replace")
    lowered = body.lower()
    if response.status_code == 429 or any(
        marker in lowered for marker in ("too many", "download limit", "limit exceeded", "maximum number")
    ):
        return DownloadError(
            f"PDC temporarily refused {filename!r} because its per-file download limit was reached. "
            "Wait 24 hours before retrying this file."
        )
    if response.status_code == 403 and any(
        marker in lowered for marker in ("expiredtoken", "request has expired", "accessdenied", "access denied")
    ):
        return DownloadError(
            "This PDC manifest's download URLs have expired (PDC signs them for 7 days). "
            "Re-export the file manifest from the PDC portal and re-run."
        )
    return DownloadError(f"PDC download failed for {filename!r}: HTTP {response.status_code}.")


def _download_one(
    session: requests.Session,
    url: str,
    destination: Path,
    expected_md5: str,
    expected_size: str,
    *,
    timeout: float,
) -> None:
    partial = destination.with_name(destination.name + ".partial")
    digest = hashlib.md5()  # nosec B324 - manifest integrity, not cryptographic security
    size = 0
    try:
        try:
            response = session.get(url, stream=True, timeout=timeout)
        except requests.RequestException as exc:
            raise DownloadError(f"PDC download failed for {destination.name!r}: {exc}") from exc
        with response:
            if response.status_code != 200:
                raise _http_error(response, destination.name)
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)

        if expected_size:
            try:
                wanted_size = int(expected_size.replace(",", ""))
            except ValueError as exc:
                raise DownloadError(
                    f"PDC manifest has an invalid size {expected_size!r} for {destination.name!r}."
                ) from exc
            if size != wanted_size:
                raise DownloadError(
                    f"Size mismatch for {destination.name!r}: expected {wanted_size}, downloaded {size}."
                )
        if expected_md5 and digest.hexdigest().lower() != expected_md5.lower():
            raise DownloadError(
                f"MD5 mismatch for {destination.name!r}: expected {expected_md5.lower()}, "
                f"downloaded {digest.hexdigest().lower()}."
            )
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def download_pdc(
    manifest: str | Path,
    outdir: str | Path,
    *,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    decompress: bool = True,
) -> int:
    """Download every PDC manifest row and return the number newly transferred.

    With ``decompress`` set, gzipped text and XML payloads are expanded once
    their checksum has been verified, so ``.mzML.gz`` and ``.mzid.gz`` become
    files Galaxy can type as ``mzml`` and ``mzid``. Integrity is always checked
    against the compressed bytes the manifest describes, never the expansion.
    """
    destination_dir = Path(outdir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    http = session or build_session()
    used_names: set[str] = set()
    downloaded = 0

    for row_number, row in enumerate(_normalised_rows(manifest), start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        filename = _safe_filename(_value(row, FILENAME_COLUMNS))
        url = _value(row, URL_COLUMNS)
        if not url:
            raise DownloadError(
                f"PDC manifest row {row_number} ({filename!r}) has no File Download Link. "
                "Re-export a file manifest from the PDC portal."
            )
        file_id = _value(row, ID_COLUMNS)
        output_name = _deduplicated_name(filename, file_id, used_names)
        destination = destination_dir / output_name
        expected_md5 = _value(row, MD5_COLUMNS)
        expected_size = _value(row, SIZE_COLUMNS)
        if not expected_md5:
            raise DownloadError(
                f"PDC manifest row {row_number} ({filename!r}) has no Md5sum value. "
                "Re-export a file manifest from the PDC portal."
            )
        if not re.fullmatch(r"[0-9A-Fa-f]{32}", expected_md5):
            raise DownloadError(
                f"PDC manifest row {row_number} ({filename!r}) has invalid Md5sum {expected_md5!r}."
            )
        if not expected_size:
            raise DownloadError(
                f"PDC manifest row {row_number} ({filename!r}) has no File Size (in bytes) value. "
                "Re-export a file manifest from the PDC portal."
            )

        expand = decompress and should_expand(destination)

        # A rerun cannot re-verify an expanded file against the manifest MD5,
        # which describes the compressed bytes. Its presence is the resume
        # signal instead: it can only exist if a prior run verified the archive
        # before expanding it.
        if expand and expanded_name(destination).is_file():
            log.info(
                "Skipping %s; it is already present, expanded, as %s.",
                output_name,
                expanded_name(destination).name,
            )
            continue
        if destination.is_file() and _md5(destination).lower() == expected_md5.lower():
            log.info("Skipping %s; it is already present with the expected MD5.", output_name)
            if expand:
                expand_gzip(destination)
            continue
        log.info("Downloading PDC file %s.", output_name)
        _download_one(http, url, destination, expected_md5, expected_size, timeout=timeout)
        if expand:
            expand_gzip(destination)
        downloaded += 1

    log.info("Downloaded %d PDC file(s) into %s.", downloaded, destination_dir)
    return downloaded
