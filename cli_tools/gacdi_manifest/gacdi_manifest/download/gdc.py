"""Secure wrapper around the GDC Data Transfer Tool."""

from __future__ import annotations

import errno
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..errors import DownloadError

log = logging.getLogger("gacdi_manifest.download.gdc")


def _remove_gdc_logs(outdir: Path) -> None:
    for log_dir in outdir.glob("*/logs"):
        if log_dir.is_dir():
            shutil.rmtree(log_dir)


def _has_data_rows(manifest: str | Path) -> bool:
    """Return whether a manifest contains a non-blank row after its header."""
    with Path(manifest).open(encoding="utf-8-sig", newline="") as handle:
        header_seen = False
        for line in handle:
            if not line.strip():
                continue
            if not header_seen:
                header_seen = True
                continue
            return True
    return False


def download_gdc(
    manifest: str | Path,
    outdir: str | Path,
    *,
    environ: dict[str, str] | None = None,
) -> int:
    """Invoke ``gdc-client`` without exposing an authorization token in argv or a file."""
    destination = Path(outdir)
    destination.mkdir(parents=True, exist_ok=True)
    if not _has_data_rows(manifest):
        log.info("GDC manifest contains no data rows; nothing to download.")
        return 0
    env = os.environ if environ is None else environ
    token = env.get("GDC_AUTH_TOKEN", "").strip()
    argv = ["gdc-client", "download", "-m", str(manifest), "-d", str(destination)]
    client_env = os.environ.copy()
    # gdc-client uses multiprocessing manager sockets. Galaxy job paths can be
    # longer than the Unix-domain socket limit, so force its temporary sockets
    # onto the container's short, writable /tmp path.
    client_env.update({"TMPDIR": "/tmp", "TMP": "/tmp", "TEMP": "/tmp"})
    fifo: Path | None = None
    writer: threading.Thread | None = None
    writer_errors: list[BaseException] = []
    writer_stop = threading.Event()

    if token:
        fifo = destination / f".gdc-token-{os.getpid()}"
        fifo.unlink(missing_ok=True)
        os.mkfifo(fifo, 0o600)

        def write_token() -> None:
            try:
                descriptor = None
                while not writer_stop.is_set():
                    try:
                        descriptor = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                        break
                    except OSError as exc:
                        if exc.errno != errno.ENXIO:
                            raise
                        time.sleep(0.01)
                if descriptor is not None:
                    payload = token.encode("utf-8")
                    while payload:
                        written = os.write(descriptor, payload)
                        payload = payload[written:]
                    os.close(descriptor)
            except BaseException as exc:  # reported by the main thread
                writer_errors.append(exc)

        writer = threading.Thread(target=write_token, name="gdc-token-writer", daemon=True)
        writer.start()
        argv.extend(["-t", str(fifo)])

    try:
        log.info("Starting gdc-client download.")
        try:
            completed = subprocess.run(
                argv,
                check=False,
                text=True,
                stderr=subprocess.PIPE,
                env=client_env,
            )
        except OSError as exc:
            raise DownloadError(f"Could not start gdc-client: {exc}") from exc
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode:
            detail = (completed.stderr or "").strip()
            suffix = f": {detail}" if detail else "."
            raise DownloadError(f"gdc-client exited with status {completed.returncode}{suffix}")
        if writer:
            writer.join(timeout=1)
            if writer_errors:
                raise DownloadError(f"Could not provide the GDC authorization token: {writer_errors[0]}")
    finally:
        writer_stop.set()
        if writer is not None:
            writer.join(timeout=1)
        if fifo is not None:
            fifo.unlink(missing_ok=True)
        _remove_gdc_logs(destination)

    return 0
