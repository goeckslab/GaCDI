from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests

from .. import version_string
from ..net import build_session as _build_session
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
        user_agent=f"gacdi-manifest/{version_string()}",
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


@dataclass
class DownloadResult:
    entry: FileEntry
    status: str  # "downloaded", "skipped", "checksum_mismatch", "error"
    detail: str = ""


def _download_one(
    session: requests.Session,
    source: Source,
    entry: FileEntry,
    output_dir: Path,
    verify: bool,
    pacer: "Pacer | None",
) -> DownloadResult:
    dest_dir = output_dir / entry.rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / entry.filename

    if dest_path.exists() and dest_path.stat().st_size > 0:
        if not verify or not entry.md5:
            return DownloadResult(entry, "skipped", "already present")
        if _md5sum(dest_path) == entry.md5:
            return DownloadResult(entry, "skipped", "already present, checksum ok")
        # fall through and re-download a corrupt/incomplete file

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
    return DownloadResult(entry, "downloaded")


def run(
    entries: list[FileEntry],
    source: Source,
    output_dir: Path,
    workers: int = 4,
    verify: bool = False,
) -> list[DownloadResult]:
    session = build_session()
    rate_limit = source.rate_limit()
    pacer = Pacer(rate_limit) if rate_limit else None
    # PDC's per-IP rate limit applies regardless of thread count, so cap
    # effective concurrency to 1 when a pacer is active to keep pacing honest.
    effective_workers = 1 if pacer else workers

    results: list[DownloadResult] = []
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = {
            pool.submit(_download_one, session, source, entry, output_dir, verify, pacer): entry
            for entry in entries
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"[{result.status.upper():17}] {result.entry.filename} {result.detail}")

    return results
