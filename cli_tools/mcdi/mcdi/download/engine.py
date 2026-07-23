from __future__ import annotations

import hashlib
import tarfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests

from .. import version_string
from ..net import build_session as _build_session
from . import archive
from .sources.base import FileEntry, RateLimit, Source

CHUNK_SIZE = 1024 * 256
TIMEOUT_SECONDS = 60
RETRY_TOTAL = 5
RETRY_BACKOFF = 1.5


def build_session() -> requests.Session:
    return _build_session(
        retries=RETRY_TOTAL,
        backoff=RETRY_BACKOFF,
        allowed_methods=frozenset({"GET", "HEAD"}),
        user_agent=f"mcdi/{version_string()}",
    )


class Pacer:
    """Thread-safe sliding-window rate limit plus a fixed per-download pause."""

    def __init__(self, rate_limit: RateLimit):
        self._rate_limit = rate_limit
        self._lock = threading.Lock()
        self._window_start = time.monotonic()
        self._count = 0

    def wait_turn(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._window_start
            if elapsed >= self._rate_limit.window_seconds:
                self._window_start = time.monotonic()
                self._count = 0
                elapsed = 0
            if self._count >= self._rate_limit.max_per_window:
                sleep_for = self._rate_limit.window_seconds - elapsed
                time.sleep(max(sleep_for, 0))
                self._window_start = time.monotonic()
                self._count = 0
            self._count += 1
        time.sleep(self._rate_limit.per_file_sleep_seconds)


def _md5sum(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dest_path(output_dir: Path, entry: FileEntry) -> Path:
    return output_dir / entry.rel_dir / entry.filename


def _already_present(dest_path: Path, entry: FileEntry, verify: bool) -> tuple[bool, str]:
    """Return ``(satisfied, detail)``: whether ``dest_path`` already correctly holds ``entry``.

    Shared by the download step and the pre-flight access check, so a file
    that doesn't need (re-)downloading also doesn't need its remote
    accessibility re-verified on every rerun.
    """
    if not (dest_path.exists() and dest_path.stat().st_size > 0):
        return False, ""
    if not verify or not entry.md5:
        return True, "already present"
    if _md5sum(dest_path) == entry.md5:
        return True, "already present, checksum ok"
    return False, ""  # corrupt/incomplete; caller should re-fetch


@dataclass
class DownloadResult:
    entry: FileEntry
    status: str  # "downloaded", "skipped", "checksum_mismatch", "error"
    detail: str = ""
    extracted: bool = False
    extract_error: str = ""


def _archived_path(output_dir: Path, entry: FileEntry) -> Path:
    """Where ``entry``'s archive is relocated to once successfully extracted.

    Mirrors ``entry.rel_dir``/filename under a sibling of ``output_dir``
    (``<output_dir>.mcdi-archives/...``). Moving the archive there - instead
    of leaving it in ``output_dir`` next to what it was extracted into -
    means (a) a tool that recursively collects everything under
    ``output_dir`` (e.g. a Galaxy ``discover_datasets`` with ``recurse``)
    only ever sees the extracted contents, not a redundant copy of the
    packed archive, and (b) the archive's presence here doubles as the
    idempotency marker: extraction is already done for this entry iff a file
    exists here. The archive isn't deleted, just moved aside - if extraction
    fails, it's left in ``output_dir`` instead, so there's still something
    to show for the download.
    """
    archive_root = output_dir.with_name(output_dir.name + ".mcdi-archives")
    return archive_root / entry.rel_dir / entry.filename


def _maybe_extract(result: DownloadResult, dest_path: Path, archived_path: Path) -> None:
    """If requested and ``dest_path`` looks like an archive, extract it and relocate it.

    On success, moves the archive from ``dest_path`` to ``archived_path`` (see
    ``_archived_path``); on failure, leaves it at ``dest_path``.
    """
    if result.status not in ("downloaded", "skipped") or not archive.is_archive(dest_path):
        return
    try:
        archive.extract(dest_path)
        archived_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.rename(archived_path)
        result.extracted = True
    except (archive.ArchiveError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        result.extract_error = str(exc)


def _download_one(
    session: requests.Session,
    source: Source,
    entry: FileEntry,
    output_dir: Path,
    verify: bool,
    pacer: "Pacer | None",
    extract: bool = False,
) -> DownloadResult:
    dest_dir = output_dir / entry.rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / entry.filename
    archived_path = _archived_path(output_dir, entry) if extract else None

    if archived_path is not None:
        present, detail = _already_present(archived_path, entry, verify)
        if present:
            result = DownloadResult(entry, "skipped", detail)
            result.extracted = True
            return result

    present, detail = _already_present(dest_path, entry, verify)
    if present:
        result = DownloadResult(entry, "skipped", detail)
        if extract:
            _maybe_extract(result, dest_path, archived_path)
        return result
    # if not present: falls through, including to re-fetch a corrupt/incomplete file

    if pacer:
        pacer.wait_turn()

    part_path = dest_path.with_suffix(dest_path.suffix + ".part")
    try:
        kwargs = source.request_kwargs(entry)
        with session.get(entry.url, stream=True, timeout=TIMEOUT_SECONDS, **kwargs) as resp:
            if resp.status_code != 200:
                return DownloadResult(entry, "error", f"HTTP {resp.status_code}")
            with open(part_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
    except requests.RequestException as exc:
        part_path.unlink(missing_ok=True)
        return DownloadResult(entry, "error", str(exc))

    if verify and entry.md5:
        if _md5sum(part_path) != entry.md5:
            part_path.rename(dest_path)
            return DownloadResult(entry, "checksum_mismatch", "md5 did not match manifest")

    part_path.rename(dest_path)
    result = DownloadResult(entry, "downloaded")
    if extract:
        _maybe_extract(result, dest_path, archived_path)
    return result


# HTTP statuses worth retrying at the batch level: rate limiting and
# server-side/transient failures. Anything else (401/403/404/...) is a
# permanent-looking failure that a delayed retry won't fix.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _is_retryable(result: DownloadResult) -> bool:
    # A checksum mismatch could be transient transfer corruption, not
    # necessarily a bad source file, so it's worth one more attempt too.
    if result.status == "checksum_mismatch":
        return True
    if result.status != "error":
        return False
    detail = result.detail
    if detail.startswith("HTTP "):
        try:
            return int(detail.split()[1]) in _RETRYABLE_STATUSES
        except (IndexError, ValueError):
            return False
    # Any other "error" detail came from a requests.RequestException (timeout,
    # connection reset, DNS hiccup, ...) - inherently transient.
    return True


def run(
    entries: list[FileEntry],
    source: Source,
    output_dir: Path,
    workers: int = 4,
    verify: bool = False,
    extract: bool = False,
    retries: int = 2,
    retry_backoff: float = 5.0,
) -> list[DownloadResult]:
    session = build_session()
    rate_limit = source.rate_limit()
    pacer = Pacer(rate_limit) if rate_limit else None
    # PDC's per-IP rate limit applies regardless of thread count, so cap
    # effective concurrency to 1 when a pacer is active to keep pacing honest.
    effective_workers = 1 if pacer else workers

    def _pass(batch: list[FileEntry]) -> list[DownloadResult]:
        pass_results: list[DownloadResult] = []
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = {
                pool.submit(_download_one, session, source, entry, output_dir, verify, pacer, extract): entry
                for entry in batch
            }
            for future in as_completed(futures):
                result = future.result()
                pass_results.append(result)
                detail = result.detail
                if result.extracted:
                    detail = f"{detail}, extracted".lstrip(", ")
                elif result.extract_error:
                    detail = f"{detail}, extract failed: {result.extract_error}".lstrip(", ")
                print(f"[{result.status.upper():17}] {result.entry.filename} {detail}")
        return pass_results

    results_by_id = {r.entry.file_id: r for r in _pass(entries)}

    # Batch-level retry, on top of the per-request transport retry already
    # inside `build_session()`. This matters most for non-interactive runs
    # (e.g. a Galaxy job) where nothing will manually rerun the command on
    # the same output directory if a few files fail transiently.
    attempt = 0
    while attempt < retries:
        retry_entries = [r.entry for r in results_by_id.values() if _is_retryable(r)]
        if not retry_entries:
            break
        attempt += 1
        print(f"\nRetrying {len(retry_entries)} file(s) that failed transiently (attempt {attempt}/{retries})...")
        time.sleep(retry_backoff * attempt)
        for result in _pass(retry_entries):
            results_by_id[result.entry.file_id] = result

    return [results_by_id[entry.file_id] for entry in entries]


@dataclass
class AccessFailure:
    entry: FileEntry
    detail: str


def _check_access_one(
    session: requests.Session,
    source: Source,
    entry: FileEntry,
    pacer: "Pacer | None",
) -> "AccessFailure | None":
    if pacer:
        pacer.wait_turn()
    kwargs = source.request_kwargs(entry)
    headers = dict(kwargs.pop("headers", None) or {})
    headers["Range"] = "bytes=0-0"
    try:
        resp = session.get(entry.url, headers=headers, timeout=TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as exc:
        return AccessFailure(entry, str(exc))
    if resp.status_code not in (200, 206):
        return AccessFailure(entry, f"HTTP {resp.status_code}")
    return None


def check_access(
    entries: list[FileEntry],
    source: Source,
    output_dir: "Path | None" = None,
    verify: bool = False,
    extract: bool = False,
    workers: int = 4,
) -> list[AccessFailure]:
    """Probe every entry with a 1-byte ranged request; return the ones that fail.

    Meant to run before any real download, so a manifest with one
    inaccessible file (e.g. controlled-access without a valid token) is
    caught in seconds instead of after downloading everything else first.
    Two things narrow what actually needs a round trip: entries already
    correctly present in ``output_dir`` (same check the download step uses -
    including, if ``extract`` is set, entries already extracted and relocated
    to ``output_dir``'s sibling archive directory - so a rerun over
    mostly-complete output doesn't re-verify remote access for files it isn't
    going to touch anyway) skip the check outright, and entries the source
    can already vouch for as open (see ``Source.known_open``) skip the
    per-file probe specifically.
    """
    session = build_session()
    rate_limit = source.rate_limit()
    pacer = Pacer(rate_limit) if rate_limit else None
    effective_workers = 1 if pacer else workers

    def _needs_probe(e: FileEntry) -> bool:
        if extract and _already_present(_archived_path(output_dir, e), e, verify)[0]:
            return False
        return not _already_present(_dest_path(output_dir, e), e, verify)[0]

    to_probe = entries
    if output_dir is not None:
        to_probe = [e for e in entries if _needs_probe(e)]

    open_ids = source.known_open(to_probe, session)
    to_check = [e for e in to_probe if e.file_id not in open_ids]

    failures: list[AccessFailure] = []
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = [pool.submit(_check_access_one, session, source, entry, pacer) for entry in to_check]
        for future in as_completed(futures):
            failure = future.result()
            if failure is not None:
                failures.append(failure)
    return failures
